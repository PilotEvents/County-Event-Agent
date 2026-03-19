import anthropic, requests, json, os, time

CITYSPARK_USER   = os.environ["CITYSPARK_USER"]
CITYSPARK_PASS   = os.environ["CITYSPARK_PASS"]
ANTHROPIC_KEY    = os.environ["ANTHROPIC_API_KEY"]
PORTAL           = "pilot"
COUNTY           = "Moore County, NC"
RADIUS_MI        = 30
DAYS_AHEAD       = 30
CITYSPARK_API    = "https://api.cityspark.com/v1"

# Trimmed to 5 sources while we debug
SOURCES = [
    "Moore County Parks and Recreation events NC",
    "Moore County library events NC",
    "Pinehurst NC upcoming events",
    "Southern Pines NC upcoming events",
    "Sandhills Community College events NC",
]

SYSTEM = f"""
You are a local event research agent for {COUNTY}.
Search for ALL public events in the next {DAYS_AHEAD} days.
Return ONLY a valid JSON array, with no explanation before or after it.
Each item must have: name, description, start_datetime (ISO 8601),
end_datetime (ISO 8601), location_name, address, city, state, ticket_url.
If you find no events, return an empty array: []
"""

def search_source(source, client):
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4000,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                system=SYSTEM,
                messages=[{"role": "user",
                           "content": f"Find all upcoming events from: {source}"}]
            )
            # Print raw response so we can see what's coming back
            text = "".join(b.text for b in resp.content if hasattr(b, "text"))
            print(f"    Raw response (first 300 chars): {repr(text[:300])}")

            # Clean up any markdown formatting and parse
            clean = text.strip()
            if clean.startswith("```"):
                clean = clean.split("```")[1]
                if clean.startswith("json"):
                    clean = clean[4:]
            clean = clean.strip()

            if not clean or clean == "[]":
                return []
            return json.loads(clean)

        except Exception as e:
            msg = str(e)
            if "rate_limit" in msg or "429" in msg:
                wait = 90 * (attempt + 1)
                print(f"    Rate limited. Waiting {wait}s (attempt {attempt+1}/3)...")
                time.sleep(wait)
            else:
                print(f"    Parse/API error: {e}")
                return []
    return []

def deduplicate(events):
    seen, unique = set(), []
    for ev in events:
        key = (ev.get("name", "").lower().strip(),
               ev.get("start_datetime", "")[:10])
        if key not in seen:
            seen.add(key)
            unique.append(ev)
    return unique

def submit(event):
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
    print(f"    CitySpark response: {r.status_code}")
    return r.status_code in (200, 201)

def main():
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    all_events = []

    print(f"Starting event agent for {COUNTY}")
    print(f"Scanning {len(SOURCES)} sources (debug mode — 5 sources only)...")

    for source in SOURCES:
        print(f"\n  Searching: {source}")
        try:
            events = search_source(source, client)
            print(f"    Found {len(events)} events")
            all_events.extend(events)
        except Exception as e:
            print(f"    Unhandled error: {e}")
        print(f"    Waiting 60s before next source...")
        time.sleep(60)

    unique = deduplicate(all_events)
    print(f"\nTotal: {len(all_events)} found, {len(unique)} unique after dedup")

    submitted = 0
    for ev in unique:
        print(f"\n  Submitting: {ev.get('name')}")
        if submit(ev):
            submitted += 1
            print(f"    Success!")
        else:
            print(f"    Skipped.")
        time.sleep(2)

    print(f"\nDone. {submitted}/{len(unique)} events submitted to CitySpark.")

if __name__ == "__main__":
    main()
