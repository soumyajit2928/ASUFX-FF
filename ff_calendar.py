from pathlib import Path

code = r'''import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

# -------------------- CONFIGURATION --------------------

FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
MODE = os.getenv("MODE", "today").strip().lower()  # "today" or "week"
TZ = ZoneInfo("Asia/Kolkata")

REQUEST_TIMEOUT = 25
HIGH_IMPACT = {
    "label": "🔴 Red Folder — High Impact",
    "color": 0xE74C3C,
}
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ForexCalendarBot/1.0)"})


# -------------------- FETCH AND FILTER --------------------

def parse_event_datetime(value):
    """Parse an ISO timestamp; assume UTC if the feed omits a timezone."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing or invalid event date: {value!r}")

    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    dt = datetime.fromisoformat(value)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(TZ)


def fetch_events():
    print(f"Fetching calendar feed: {FEED_URL}")
    response = SESSION.get(FEED_URL, timeout=REQUEST_TIMEOUT)
    print(f"Feed HTTP status: {response.status_code}")
    print(f"Feed Content-Type: {response.headers.get('Content-Type', 'unknown')}")
    response.raise_for_status()

    try:
        data = response.json()
    except requests.exceptions.JSONDecodeError as exc:
        preview = response.text[:250].replace("\n", " ")
        raise RuntimeError(
            f"Calendar feed did not return valid JSON. Response preview: {preview}"
        ) from exc

    if not isinstance(data, list):
        raise RuntimeError(f"Expected a JSON list from the calendar feed, got {type(data).__name__}")

    print(f"Raw events received: {len(data)}")
    impact_values = sorted({
        str(event.get("impact", "")).strip()
        for event in data
        if isinstance(event, dict)
    })
    print(f"Impact values found in feed: {impact_values}")

    events = []
    bad_dates = 0

    for event in data:
        if not isinstance(event, dict):
            continue

        # Intentionally only include high-impact / red-folder news.
        if str(event.get("impact", "")).strip().lower() != "high":
            continue

        try:
            event_dt = parse_event_datetime(event.get("date"))
        except (ValueError, TypeError):
            bad_dates += 1
            print(f"Skipping event with invalid date: {event.get('title', 'Unknown event')!r}")
            continue

        events.append({**event, "dt": event_dt})

    events.sort(key=lambda item: item["dt"])
    print(f"High-impact events with valid dates: {len(events)}")

    if MODE == "today":
        today = datetime.now(TZ).date()
        events = [event for event in events if event["dt"].date() == today]
        print(f"High-impact events for today ({today} IST): {len(events)}")
    else:
        print(f"MODE={MODE}: keeping all high-impact events in the feed")

    if bad_dates:
        print(f"Skipped events with invalid dates: {bad_dates}")

    return events


# -------------------- DISCORD MESSAGE BUILDING --------------------

def safe_text(value, fallback="-"):
    if value is None:
        return fallback
    value = str(value).strip()
    return value if value else fallback


def event_lines(event):
    time_text = (
        event["dt"].strftime("%a, %d %b • %I:%M %p IST")
        if MODE == "week"
        else event["dt"].strftime("%I:%M %p IST")
    )

    country = safe_text(event.get("country"), "Unknown country")
    title = safe_text(event.get("title"), "Untitled event")
    forecast = safe_text(event.get("forecast"))
    previous = safe_text(event.get("previous"))

    # Keep individual lines concise and avoid Markdown breaking on long values.
    return (
        f"**{time_text}** · **{country}**\n"
        f"{title}\n"
        f"Forecast: `{forecast}` | Previous: `{previous}`"
    )


def build_embeds(events):
    """Build embeds within Discord's per-embed and aggregate message limits."""
    embeds = []
    current_lines = []
    current_length = 0

    for event in events:
        line = event_lines(event)
        line_length = len(line) + 1

        # Stay well below the 4096-character description cap.
        if current_lines and current_length + line_length > 3500:
            embeds.append({
                "title": HIGH_IMPACT["label"],
                "description": "\n\n".join(current_lines),
                "color": HIGH_IMPACT["color"],
                "footer": {"text": "Source: Forex Factory • Times in IST"},
            })
            current_lines = []
            current_length = 0

        current_lines.append(line)
        current_length += line_length

    if current_lines:
        embeds.append({
            "title": HIGH_IMPACT["label"],
            "description": "\n\n".join(current_lines),
            "color": HIGH_IMPACT["color"],
            "footer": {"text": "Source: Forex Factory • Times in IST"},
        })

    return embeds


# -------------------- SEND TO DISCORD --------------------

def post_to_discord(payload):
    if not WEBHOOK_URL:
        raise RuntimeError(
            "DISCORD_WEBHOOK_URL is not set. Add your Discord webhook URL as an environment variable."
        )

    response = SESSION.post(
        WEBHOOK_URL,
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )

    if not response.ok:
        raise RuntimeError(
            f"Discord webhook failed: HTTP {response.status_code}: {response.text[:1000]}"
        )

    # Discord webhooks commonly return 204 No Content when wait is not enabled.
    print(f"Discord accepted message (HTTP {response.status_code}).")


def send_embeds(embeds):
    # Discord permits up to 10 embeds per message, but total text across all
    # embeds is limited. Send one embed per request to stay safely under limits.
    for index, embed in enumerate(embeds, start=1):
        print(f"Sending embed {index}/{len(embeds)}...")
        post_to_discord({"embeds": [embed]})


def main():
    if MODE not in {"today", "week"}:
        raise RuntimeError('Invalid MODE. Set MODE to "today" or "week".')

    events = fetch_events()
    now_text = datetime.now(TZ).strftime("%A, %d %b %Y")

    if not events:
        post_to_discord({
            "content": f"📅 No 🔴 high-impact (red-folder) Forex Factory news found for {now_text}."
        })
        return

    mode_label = "Today" if MODE == "today" else "This Week"
    post_to_discord({
        "content": f"📅 **Forex Factory — High-Impact Red Folder News ({mode_label})**\nTimes are shown in IST."
    })

    embeds = build_embeds(events)
    send_embeds(embeds)
    print(f"Done. Sent {len(events)} high-impact event(s) in {len(embeds)} embed(s).")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
'''
path = Path("/mnt/data/forex_factory_discord_webhook.py")
path.write_text(code, encoding="utf-8")
print(f"Created: {path}")
print(f"Lines: {len(code.splitlines())}")
