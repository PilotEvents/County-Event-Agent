agent.py
import anthropic, requests, json, os
from datetime import datetime, timedelta

# ── Configuration (loaded from GitHub Secrets) ──────────────────────
CITYSPARK_USER   = os.environ["CITYSPARK_USER"]
CITYSPARK_PASS   = os.environ["CITYSPARK_PASS"]
ANTHROPIC_KEY    = os.environ["ANTHROPIC_API_KEY"]
PORTAL           = "pilot"
COUNTY           = "Moore County, NC"
RADIUS_MI        = 30
DAYS_AHEAD       = 90

CITYSPARK_API    = "https://api.cityspark.com/v1"

SOURCES = [
    "Eventbrite Moore County NC",
    "Facebook Events Moore County NC",
    "Meetup Moore County NC",
    "Moore County Parks and Recreation events",
    "Moore County library events",
    "Moore County Chamber of Commerce events",
    "Pinehurst Southern Pines Aberdeen local events",
    "Moore County schools community events",
    "Sandhills Community College events",
    "Ticketmaster Moore County NC",
    "Events in Southern Pines NC",
    "Events in Pinehurst NC",
    "Events in Carthage NC",
    "Events in Aberdeen NC",
    "https://www.pinehurst.com/events/",
    "https://www.southernpines.com/calendar/",
    "https://www.moorecountync.gov/events",
    "https://www.sandhills.edu/calendar",
    "https://homeofgolf.com/events/",
    "https://www.thepinestimes.com/events/"
    
]

SYSTEM = f"""
You are a local event research agent for {COUNTY}.
Search for ALL public events in the next {DAYS_AHEAD} days.
For each event return a JSON object with these fields:
  name, description, start_datetime (ISO 8601), end_datetime (ISO 8601),
  location_name, address, city, state, ticket_url, free (true/false)
Return ONLY a valid JSON array. No other text.
Only include events physically in or near {COUNTY} (within {RADIUS_MI} miles).
"""

def search_source(source, client):
    """Ask Claude to search one source and return events as JSON."""
    resp = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        system=SYSTEM,
        messages=[{"role": "user",
                   "content": f"Find all upcoming events from: {source}"}]
    )
    text = "".join(b.text for b in resp.content if hasattr(b, "text"))
    clean = text.strip().lstrip("```json").lstrip("```").rstrip("```")
    return json.loads(clean)

def deduplicate(events):
    """Remove duplicate events by name + start date."""
    seen, unique = set(), []
    for ev in events:
        key = (ev.get("name","").lower().strip(),
               ev.get("start_datetime","")[:10])
        if key not in seen:
            seen.add(key)
            unique.append(ev)
    return unique

def submit(event):
    """Submit one event to CitySpark."""
    payload = {
        "portal": PORTAL,
        "name": event.get("name", "Untitled Event"),
        "description": event.get("description", ""),
        "startDate": event.get("start_datetime", ""),
        "endDate": event.get("end_datetime", ""),
        "location": {
            "locationName": event.get("location_name", ""),
            "address": event.get("address", ""),
            "city": event.get("city", ""),
            "state": event.get("state", "NC"),
        },
        "links": [{"linkUrl": event.get("ticket_url", "")}],
    }
    r = requests.post(
        f"{CITYSPARK_API}/events",
        auth=(CITYSPARK_USER, CITYSPARK_PASS),
        json=payload,
        timeout=15
    )
    return r.status_code in (200, 201)

def main():
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    all_events = []

    print(f"Starting event agent for {COUNTY}")
    print(f"Scanning {len(SOURCES)} sources...")

    for source in SOURCES:
        print(f"  Searching: {source}")
        try:
            events = search_source(source, client)
            print(f"    Found {len(events)} events")
            all_events.extend(events)
        except Exception as e:
            print(f"    Error: {e}")

    unique = deduplicate(all_events)
    print(f"\nTotal: {len(all_events)} found, {len(unique)} unique after dedup")

    submitted = 0
    for ev in unique:
        if submit(ev):
            submitted += 1
            print(f"  Submitted: {ev.get('name')}")
        else:
            print(f"  Skipped (already exists or error): {ev.get('name')}")

    print(f"\nDone. {submitted}/{len(unique)} events submitted to CitySpark.")

if __name__ == "__main__":
    main()
