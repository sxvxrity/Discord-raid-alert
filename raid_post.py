import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "").strip()
UK = ZoneInfo("Europe/London")
STATE_FILE = "state.json"
PING_BEFORE = timedelta(minutes=60)

# Raid window in UK time: Friday 6:00 PM -> Monday 12:00 AM (midnight Sunday night)
START_WEEKDAY = 4  # Friday
START_HOUR = 18
LENGTH_DAYS = 3  # Friday -> Monday 00:00

ZONES = [
    ("🇬🇧 UK", "Europe/London"),
    ("🇺🇸 US East", "America/New_York"),
    ("🇺🇸 US Central", "America/Chicago"),
    ("🇺🇸 US West", "America/Los_Angeles"),
    ("🇦🇺 Sydney / Melbourne", "Australia/Sydney"),
]


def current_window(now):
    """Return (start, end) of the live window, or the next one."""
    for offset in range(-4, 8):
        d = (now + timedelta(days=offset)).date()
        if d.weekday() != START_WEEKDAY:
            continue
        start = datetime(d.year, d.month, d.day, START_HOUR, 0, tzinfo=UK)
        e = d + timedelta(days=LENGTH_DAYS)
        end = datetime(e.year, e.month, e.day, 0, 0, tzinfo=UK)
        if end > now:
            return start, end


def ts(dt, style="F"):
    return f"<t:{int(dt.timestamp())}:{style}>"


def eta(delta):
    mins = max(0, round(delta.total_seconds() / 60))
    if mins < 1:
        return "less than a minute"
    if mins < 60:
        return f"about {mins} minute" + ("" if mins == 1 else "s")
    h = round(mins / 60)
    return f"about {h} hour" + ("" if h == 1 else "s")



def build_embed(now, start, end):
    live = start <= now < end
    embed = {
        "title": "🔴 RAID TIME IS LIVE" if live else "🚨 NEXT RAID WINDOW",
        "color": 0xE74C3C if live else 0xF39C12,
        "description": (
            "Raiding is **ON** right now!" if live else "Raiding is **OFF** until the next window."
        ),
        "fields": [],
    }

    if live:
        embed["fields"].append(
            {"name": "⏳ Started", "value": ts(start, "R"), "inline": True}
        )
    else:
        embed["fields"].append(
            {
                "name": "⏳ Starts in",
                "value": f"{ts(start, 'R')}\n{eta(start - now)}",

                "inline": True,
            }
        )
    embed["fields"].append(
        {
            "name": "🏁 Ends in",
            "value": f"{ts(end, 'R')}\n{eta(end - now)}",

            "inline": True,
        }
    )
    embed["fields"].append(
        {
            "name": "🕒 In your local time",
            "value": f"{ts(start)}\n→ {ts(end)}",
            "inline": False,
        }
    )

    for name, tz in ZONES:
        z = ZoneInfo(tz)
        s, e = start.astimezone(z), end.astimezone(z)
        embed["fields"].append(
            {
                "name": name,
                "value": f"{s:%a %-I:%M %p} → {e:%a %-I:%M %p}",
                "inline": True,
            }
        )

    embed["footer"] = {"text": "Updates automatically every week • Follow your local time zone"}
    return embed


def call(method, url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "RaidTimes (github-actions, 1.0)",
        },
    )
    with urllib.request.urlopen(req) as r:
        body = r.read()
        return json.loads(body) if body else None


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def main():
    now = datetime.now(UK)
    start, end = current_window(now)
    payload = {
        "content": "",
        "embeds": [build_embed(now, start, end)],
        "allowed_mentions": {"parse": []},
    }

    if not WEBHOOK:
        print("DRY RUN (no DISCORD_WEBHOOK set)")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        print("Hours until start:", (start - now).total_seconds() / 3600)
        return

    state = load_state()

    # Edit the existing message, or post a new one if missing/deleted
    msg_id = state.get("message_id")
    if msg_id:
        try:
            call("PATCH", f"{WEBHOOK}/messages/{msg_id}", payload)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                msg_id = None
            else:
                raise
    if not msg_id:
        res = call("POST", WEBHOOK + "?wait=true", payload)
        state["message_id"] = res["id"]

    # One @everyone ping, about an hour before the window starts
    until_start = start - now
    if timedelta(0) < until_start <= PING_BEFORE and state.get("ping_for") != start.isoformat():
        call(
            "POST",
            WEBHOOK,
            {
                "content": f"@everyone 🚨 **RAID TIME** starts {ts(start, 'R')}! Get your bases ready.",
                "allowed_mentions": {"parse": ["everyone"]},
            },
        )
        state["ping_for"] = start.isoformat()

    save_state(state)


if __name__ == "__main__":
    main()
