import os
import sys
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]
TZ = ZoneInfo("Asia/Kolkata")
MODE = os.environ.get("MODE", "today")  # "today" or "week"

IMPACTS = {
    "High":   {"label": "🔴 Red Folder (High Impact)",     "color": 0xE74C3C},
    "Medium": {"label": "🟠 Orange Folder (Medium Impact)", "color": 0xE67E22},
}


def fetch_events():
    r = requests.get(FEED, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    r.raise_for_status()
    events = []
    for e in r.json():
        if e.get("impact") not in IMPACTS:
            continue
        dt = datetime.fromisoformat(e["date"]).astimezone(TZ)
        events.append({**e, "dt": dt})
    events.sort(key=lambda x: x["dt"])
    if MODE == "today":
        today = datetime.now(TZ).date()
        events = [e for e in events if e["dt"].date() == today]
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
            WEBHOOK, json={"content": f"📅 No red/orange folder news for {when}."}, timeout=20
        ).raise_for_status()
        return
    header = f"📅 **Forex Factory Calendar: {'Today' if MODE == 'today' else 'This Week'}** ({when})"
    requests.post(WEBHOOK, json={"content": header}, timeout=20).raise_for_status()
    send(build_embeds(events))


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        print(f"Error: {ex}", file=sys.stderr)
        sys.exit(1)
