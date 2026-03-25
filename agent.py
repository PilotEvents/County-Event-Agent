import anthropic, requests, json, os, time, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, date, timezone

ANTHROPIC_KEY  = os.environ["ANTHROPIC_API_KEY"]
EMAIL_FROM     = os.environ["EMAIL_FROM"]       # your Gmail address
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]   # Gmail app password
EMAIL_TO       = os.environ["EMAIL_TO"]         # where to send the digest
COUNTY         = "Moore County, NC"
DAYS_AHEAD     = 30

SOURCES = [
     # Search phrases
    "Moore County Parks and Recreation events NC",
    "Moore County library events NC",
    "Pinehurst NC upcoming events",
    "Southern Pines NC upcoming events",
    "Sandhills Community College events NC",
    "Moore County Chamber of Commerce events NC",
    "Aberdeen NC upcoming events",
    "Carthage NC upcoming events",
    "Moore County schools community events NC",
     # Direct URLs
    "https://www.vopnc.org/our-community/calendar-of-events",
    "https://www.southernpines.net/calendar.aspx",
    "https://www.thepinestimes.com/events/",
    "https://homeofgolf.com/events/",
    "https://www.eventbrite.com/d/nc--pinehurst/moore-county-nc/",
    "https://ticketmesandhills.com",
]

SYSTEM = """You are an event extraction agent. Your job is to find upcoming local events and return them as a JSON array.

CRITICAL: Your response must be ONLY a JSON array. No introduction. No explanation. No markdown. No text before or after.
Start your response with [ and end with ].

Each event object must have exactly these fields:
- name (string)
- date (human readable, e.g. "Saturday, March 22")
- time (e.g. "7:00 PM" or "All day" if unknown)  
- location (venue name and city)
- description (1-2 sentences max)
- url (ticket or event page URL, or "" if none)
- category (one of: Arts, Music, Sports, Food, Community, Family, Festival, Other)

If you find no events, return exactly: []
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
                           "content": f"Search for upcoming events in the next {DAYS_AHEAD} days. Source to search: {source}. Return ONLY a JSON array."}]
            )
            text = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()

            # Find the JSON array inside the response no matter what else is there
            start = text.find("[")
            end   = text.rfind("]") + 1
            if start == -1 or end == 0:
                return []
            return json.loads(text[start:end])

        except Exception as e:
            msg = str(e)
            if "rate_limit" in msg or "429" in msg:
                wait = 90 * (attempt + 1)
                print(f"    Rate limited. Waiting {wait}s (attempt {attempt+1}/3)...")
                time.sleep(wait)
            else:
                print(f"    Error: {e}")
                return []
    return []

def deduplicate(events):
    today = date.today().isoformat()  # e.g. "2026-03-25"
    seen, unique = set(), []
    for ev in events:
        # Filter out past events
        event_date = ev.get("start_datetime", ev.get("date", ""))
        if event_date and event_date[:10] < today:
            continue
        key = (ev.get("name", "").lower().strip(),
               ev.get("date", "").lower().strip())
        if key not in seen:
            seen.add(key)
            unique.append(ev)
    return unique
    
CAT_COLORS = {
    "Arts":      "#534AB7",
    "Music":     "#993556",
    "Sports":    "#3B6D11",
    "Food":      "#854F0B",
    "Community": "#0F6E56",
    "Family":    "#185FA5",
    "Festival":  "#993C1D",
    "Other":     "#5F5E5A",
}

def build_html(events, sources_scanned, run_date):
    total = len(events)
    cat_counts = {}
    for ev in events:
        c = ev.get("category", "Other")
        cat_counts[c] = cat_counts.get(c, 0) + 1

    pills_html = ""
    for cat, count in sorted(cat_counts.items()):
        color = CAT_COLORS.get(cat, "#888")
        pills_html += f'<span style="display:inline-block;background:{color};color:#fff;font-size:12px;font-weight:500;padding:3px 10px;border-radius:99px;margin:2px 4px 2px 0">{cat} ({count})</span>'

    cards_html = ""
    for ev in events:
        cat    = ev.get("category", "Other")
        color  = CAT_COLORS.get(cat, "#888")
        url    = ev.get("url", "")
        source = ev.get("source", "")
        if url:
            link = f'<a href="{url}" style="font-size:12px;color:{color};text-decoration:none;border:1px solid {color};border-radius:4px;padding:2px 8px;white-space:nowrap">View event →</a>'
        elif source and not source.startswith("http"):
            link = f'<span style="font-size:11px;color:#888;font-style:italic">via {source}</span>'
        else:
            link = ""
        cards_html += f"""
        <div style="background:#fff;border:1px solid #e8e8e8;border-radius:8px;padding:14px 16px;margin-bottom:10px">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px">
            <div style="flex:1">
              <span style="font-size:11px;font-weight:600;color:{color};text-transform:uppercase;letter-spacing:0.05em">{cat}</span>
              <div style="font-size:15px;font-weight:600;color:#1a1a1a;margin:3px 0">{ev.get('name','')}</div>
              <div style="font-size:13px;color:#555;margin-bottom:4px">{ev.get('date','')} &nbsp;·&nbsp; {ev.get('time','')} &nbsp;·&nbsp; {ev.get('location','')}</div>
              <div style="font-size:13px;color:#444;line-height:1.5">{ev.get('description','')}</div>
            </div>
            <div style="flex-shrink:0;margin-top:4px">{link}</div>
          </div>
        </div>"""

    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f5f5f3;font-family:Arial,sans-serif">
<div style="max-width:620px;margin:0 auto;padding:24px 16px">

  <div style="background:#0F6E56;border-radius:10px 10px 0 0;padding:20px 24px">
    <div style="font-size:11px;color:#9FE1CB;letter-spacing:0.08em;text-transform:uppercase;margin-bottom:4px">Daily Event Digest</div>
    <div style="font-size:22px;font-weight:700;color:#fff">Moore County Events</div>
    <div style="font-size:13px;color:#9FE1CB;margin-top:4px">{run_date} &nbsp;·&nbsp; Next {DAYS_AHEAD} days</div>
  </div>

  <div style="background:#E1F5EE;border-left:4px solid #0F6E56;padding:14px 20px">
    <div style="font-size:13px;color:#085041">
      Found <strong>{total} events</strong> across {sources_scanned} sources today.
    </div>
    <div style="margin-top:8px">{pills_html}</div>
  </div>

  <div style="background:#fff;border-radius:0 0 10px 10px;padding:20px 20px 8px">
    {cards_html}
    <div style="font-size:11px;color:#aaa;text-align:center;padding:16px 0 8px;border-top:1px solid #f0f0f0;margin-top:8px">
      Generated by your County Event Agent &nbsp;·&nbsp; Review and add to CitySpark at your convenience
    </div>
  </div>

</div>
</body></html>"""

def send_email(html, event_count, run_date):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📅 {event_count} Moore County events found — {run_date}"
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())

def main():
    run_date = datetime.now().strftime("%A, %B %-d, %Y")
    print(f"Starting event agent for {COUNTY} — {run_date}")
    print(f"Scanning {len(SOURCES)} sources...")

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    all_events = []

    for i, source in enumerate(SOURCES):
        print(f"  [{i+1}/{len(SOURCES)}] {source}")
        events = search_source(source, client)
        for ev in events:
            if not ev.get("url"):
                ev["url"] = source if source.startswith("http") else ""
            ev["source"] = source
        print(f"    → {len(events)} events found")
        all_events.extend(events)
        time.sleep(60)

    unique = deduplicate(all_events)
    print(f"\nTotal: {len(all_events)} found, {len(unique)} unique after dedup")

    if unique:
        html = build_html(unique, len(SOURCES), run_date)
        send_email(html, len(unique), run_date)
        print(f"Email sent to {EMAIL_TO} with {len(unique)} events.")
    else:
        print("No events found — no email sent.")

if __name__ == "__main__":
    main()
