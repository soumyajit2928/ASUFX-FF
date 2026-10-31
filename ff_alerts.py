import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]
IMPACTS = ["High"]  # red folder only
CURRENCIES = {"AUD", "USD", "CAD", "CHF", "JPY", "EUR", "GBP", "NZD"}
# Discord role to ping (numeric role ID). Leave unset for no ping.
_role = os.environ.get("PING_ROLE_ID", "").strip()
ROLE_ID = _role if _role.isdigit() else ""
ROLE_MENTION = f"<@&{ROLE_ID}>" if ROLE_ID else ""
ALLOWED_MENTIONS = {"parse": [], "roles": [ROLE_ID] if ROLE_ID else []}

TZ = ZoneInfo("Asia/Kolkata")
FF_TZ = ZoneInfo("America/New_York")  # the feed's native timezone
STATE_FILE = "state.json"

MIN_AHEAD = 1    # minutes
MAX_AHEAD = 20   # minutes (wide window: GitHub cron runs are often delayed)
FEED_MAX_AGE_HOURS = 3

ICON = {"High": "🔴"}
COLOR = {"High": 0xE74C3C}


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"sent": {}, "feed": [], "feed_fetched": None}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


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


def get_feed(state, now):
    fetched = state.get("feed_fetched")
    if fetched and state.get("feed"):
        age = now - datetime.fromisoformat(fetched)
        if age < timedelta(hours=FEED_MAX_AGE_HOURS):
            return state["feed"]
    try:
        state["feed"] = fetch_json(FEED)
        state["feed_fetched"] = now.isoformat()
    except Exception as ex:
        if state.get("feed"):
            print(f"Feed refresh failed ({ex}); using cached copy.", file=sys.stderr)
        else:
            raise
    return state["feed"]


def event_id(e):
    return f"{e['date']}|{e['country']}|{e['title']}"


def main():
    now = datetime.now(timezone.utc)
    state = load_state()

    # prune alert history older than 2 days
    cutoff = now - timedelta(days=2)
    state["sent"] = {
        k: v for k, v in state.get("sent", {}).items()
        if datetime.fromisoformat(v) > cutoff
    }

    feed = get_feed(state, now)

    due = []
    for e in feed:
        if e.get("impact") not in IMPACTS or e.get("country") not in CURRENCIES:
            continue
        dt = datetime.fromisoformat(e["date"])
        # skip "All Day" / tentative events (stored at 00:00 feed time)
        local_ff = dt.astimezone(FF_TZ)
        if local_ff.hour == 0 and local_ff.minute == 0:
            continue
        mins = (dt - now).total_seconds() / 60
        if MIN_AHEAD <= mins <= MAX_AHEAD and event_id(e) not in state["sent"]:
            due.append((dt, mins, e))

    print(f"{len(due)} alert(s) due in the next {MAX_AHEAD} min.")
    if not due:
        save_state(state)
        return

    # group events that release at the same time
    groups = {}
    for dt, mins, e in due:
        groups.setdefault(dt, []).append((mins, e))

    embeds, ids = [], []
    has_high = False
    for dt in sorted(groups):
        items = groups[dt]
        mins = round(min(m for m, _ in items))
        top = "High"
        has_high = True
        lines = []
        for _, e in items:
            lines.append(
                f"{ICON[e['impact']]} **{e['country']}** · {e['title']}\n"
                f"   Forecast: {e.get('forecast') or '-'} | Previous: {e.get('previous') or '-'}"
            )
            ids.append(event_id(e))
        embeds.append({
            "title": f"⏰ News in ~{mins} min · {dt.astimezone(TZ).strftime('%I:%M %p')} IST",
            "description": "\n".join(lines),
            "color": COLOR[top],
            "footer": {"text": "Source: Forex Factory"},
        })

    payload = {"embeds": embeds[:10], "allowed_mentions": ALLOWED_MENTIONS}
    if ROLE_MENTION:
        payload["content"] = ROLE_MENTION

    r = requests.post(WEBHOOK, json=payload, timeout=20)
    r.raise_for_status()

    # only mark as sent after Discord accepted it
    for i in ids:
        state["sent"][i] = now.isoformat()
    save_state(state)


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        print(f"Error: {ex}", file=sys.stderr)
        sys.exit(1)
