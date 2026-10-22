import json
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]
IMPACTS = [x.strip() for x in os.environ.get("ALERT_IMPACTS", "High").split(",") if x.strip()]
PING = os.environ.get("ALERT_PING", "")  # e.g. "@here" or "<@&ROLE_ID>"; used for High impact only

TZ = ZoneInfo("Asia/Kolkata")
FF_TZ = ZoneInfo("America/New_York")  # the feed's native timezone
STATE_FILE = "state.json"

MIN_AHEAD = 2    # minutes
MAX_AHEAD = 15   # minutes
FEED_MAX_AGE_HOURS = 6

ICON = {"High": "🔴", "Medium": "🟠"}
COLOR = {"High": 0xE74C3C, "Medium": 0xE67E22}


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"sent": {}, "feed": [], "feed_fetched": None}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def get_feed(state, now):
    fetched = state.get("feed_fetched")
    if fetched and state.get("feed"):
        age = now - datetime.fromisoformat(fetched)
        if age < timedelta(hours=FEED_MAX_AGE_HOURS):
            return state["feed"]
    try:
        r = requests.get(FEED, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        r.raise_for_status()
        state["feed"] = r.json()
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
        if e.get("impact") not in IMPACTS:
            continue
        dt = datetime.fromisoformat(e["date"])
        # skip "All Day" / tentative events (stored at 00:00 feed time)
        local_ff = dt.astimezone(FF_TZ)
        if local_ff.hour == 0 and local_ff.minute == 0:
            continue
        mins = (dt - now).total_seconds() / 60
        if MIN_AHEAD <= mins <= MAX_AHEAD and event_id(e) not in state["sent"]:
            due.append((dt, mins, e))

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
        top = "High" if any(e["impact"] == "High" for _, e in items) else "Medium"
        has_high = has_high or top == "High"
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

    payload = {"embeds": embeds[:10]}
    if PING and has_high:
        payload["content"] = PING

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
