import os
import sys
import time
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]
TZ = ZoneInfo("Asia/Kolkata")
MODE = os.environ.get("MODE", "today")  # "today" or "week"

# Discord role to ping (numeric role ID). Leave unset for no ping.
_role = os.environ.get("PING_ROLE_ID", "").strip()
ROLE_ID = _role if _role.isdigit() else ""
ROLE_MENTION = f"<@&{ROLE_ID}>" if ROLE_ID else ""
ALLOWED_MENTIONS = {"parse": [], "roles": [ROLE_ID] if ROLE_ID else []}

# Only these currencies are posted (the feed's "country" field is the currency code)
CURRENCIES = {"AUD", "USD", "CAD", "CHF", "JPY", "EUR", "GBP", "NZD"}

IMPACTS = {
    "High":   {"label": "🔴 Red Folder (High Impact)",     "color": 0xE74C3C},
}


def fetch_json(url, attempts=4):
    """Fetch the FF feed with retries (the feed often returns 429/5xx to shared GitHub runners)."""
    last = None
    for i in range(attempts):
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            if r.status_code == 429 or r.status_code >= 500:
                raise RuntimeError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.json()
        except Exception as ex:
            last = ex
            print(f"Feed fetch attempt {i + 1}/{attempts} failed: {ex}", file=sys.stderr)
            time.sleep(5 * (i + 1))
    raise last


def fetch_events():
    raw = fetch_json(FEED)
    print(f"Feed returned {len(raw)} events total.")
    events = []
    for e in raw:
        if e.get("impact") not in IMPACTS or e.get("country") not in CURRENCIES:
            continue
        dt = datetime.fromisoformat(e["date"]).astimezone(TZ)
        events.append({**e, "dt": dt})
    events.sort(key=lambda x: x["dt"])
    print(f"{len(events)} high-impact events for the selected currencies this week.")
    if MODE == "today":
        today = datetime.now(TZ).date()
        events = [e for e in events if e["dt"].date() == today]
        print(f"{len(events)} of them fall on today ({today}, IST).")
    return events


def line(e):
    time_str = e["dt"].strftime("%a %d %b, %I:%M %p") if MODE == "week" else e["dt"].strftime("%I:%M %p")
    f = e.get("forecast") or "-"
    p = e.get("previous") or "-"
    return f"`{time_str}` **{e['country']}** · {e['title']}\n   Forecast: {f} | Previous: {p}"


def build_embeds(events):
    embeds = []
    for impact, meta in IMPACTS.items():
        group = [e for e in events if e["impact"] == impact]
        if not group:
            continue
        # split into chunks to stay under Discord's 4096-char embed description limit
        chunk, size = [], 0
        for e in group:
            l = line(e)
            if chunk and size + len(l) > 3800:
                embeds.append((meta, chunk))
                chunk, size = [], 0
            chunk.append(l)
            size += len(l) + 1
        if chunk:
            embeds.append((meta, chunk))
    return [
        {
            "title": meta["label"],
            "description": "\n".join(lines),
            "color": meta["color"],
            "footer": {"text": "Source: Forex Factory • Times in IST"},
        }
        for meta, lines in embeds
    ]


def send(embeds):
    # Discord allows up to 10 embeds per message
    for i in range(0, len(embeds), 10):
        r = requests.post(WEBHOOK, json={"embeds": embeds[i:i + 10]}, timeout=20)
        r.raise_for_status()


def main():
    events = fetch_events()
    when = datetime.now(TZ).strftime("%A, %d %b %Y")
    if not events:
        requests.post(
            WEBHOOK, json={"content": f"📅 No red folder news for {when}."}, timeout=20
        ).raise_for_status()
        return
    header = f"📅 **Forex Factory Calendar: {'Today' if MODE == 'today' else 'This Week'}** ({when})"
    if ROLE_MENTION:
        header = f"{ROLE_MENTION} {header}"
    requests.post(
        WEBHOOK, json={"content": header, "allowed_mentions": ALLOWED_MENTIONS}, timeout=20
    ).raise_for_status()
    send(build_embeds(events))


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        print(f"Error: {ex}", file=sys.stderr)
        sys.exit(1)
