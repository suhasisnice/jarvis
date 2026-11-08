"""Check for Phase 2 additions in skills.py and scheduler.py. Run: python test_phase2b.py"""
import json, tempfile, time
from datetime import datetime, timedelta
from pathlib import Path

import memory
memory.DB_PATH = Path(tempfile.mkdtemp()) / "t.db"
memory.init()
import skills, scheduler

# --- wake_laptop: Wake-on-LAN magic packet, stdlib socket ---
sent = []
class FakeSock:
    def __init__(self, *a): pass
    def setsockopt(self, *a): pass
    def sendto(self, data, addr): sent.append((data, addr))
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
skills.socket.socket = FakeSock
r = skills.wake_laptop()
assert "wake" in r.lower(), r
mac = bytes.fromhex(skills.LAPTOP_MAC.replace(":", "").replace("-", ""))
assert sent and all(d == b"\xff" * 6 + mac * 16 for d, _ in sent) and sent[0][1][1] == 9, sent

# --- laptop_remote: phone -> laptop actions, queued for the laptop to pick up ---
skills.subprocess.run = lambda *a, **k: type("R", (), {"returncode": 0})()       # laptop online
scheduler.inbox.take()
assert "done" in skills.laptop_remote("open_app", "chrome").lower()
items = scheduler.inbox.take()
assert len(items) == 1 and items[0]["do"] == "open_app" and items[0]["target"] == "chrome" and items[0]["t"] <= time.time()
skills.subprocess.run = lambda *a, **k: type("R", (), {"returncode": 1})()       # laptop asleep
r = skills.laptop_remote("play", "Loser")
assert "asleep" in r.lower() and scheduler.inbox.take() == [], r

# --- rain_chance: max precipitation probability over the next 2 hours, Open-Meteo, no key ---
def fake_get(url):
    if "geocoding" in url:
        return {"results": [{"latitude": 12.97, "longitude": 77.59}]}
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    hours = [(now + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(-1, 5)]
    return {"hourly": {"time": hours, "precipitation_probability": [99, 10, 40, 70, 95, 95]}}
skills._get_json = fake_get
assert skills.rain_chance("Bangalore") == 70          # this hour + next two hours, not the past hour or later
skills._get_json = lambda url: (_ for _ in ()).throw(OSError("offline"))
assert skills.rain_chance("Bangalore") is None

# --- scheduler: rain alert, calendar heads-up, kinds passed to deliver ---
got = []
deliver = lambda text, kind: got.append((kind, text))
brief = lambda: "brief"
state = {}
noon = datetime(2026, 11, 9, 12, 0)
ev = lambda: [(noon + timedelta(minutes=10), "Team standup"), (noon + timedelta(hours=3), "Gym")]
scheduler.tick(noon, deliver, brief, state, disk_percent=lambda: 10, rain=lambda: 75, events=ev)
assert ("alert", "Sir, rain is likely in the next couple of hours (75%).") in got, got
assert ("alert", "Sir, Team standup starts in 10 minutes.") in got, got
assert len(got) == 2, got
got.clear()
scheduler.tick(noon + timedelta(minutes=30), deliver, brief, state, disk_percent=lambda: 10, rain=lambda: 90, events=ev)
assert got == [], "rain alert at most once per 3 hours; each event once"
scheduler.tick(noon + timedelta(hours=3, minutes=1), deliver, brief, state, disk_percent=lambda: 10, rain=lambda: 90, events=lambda: [])
assert got == [("alert", "Sir, rain is likely in the next couple of hours (90%).")], got
got.clear()
memory.add_reminder(noon.timestamp(), "stretch")
scheduler.tick(noon.replace(hour=8, day=10), deliver, brief, {}, disk_percent=lambda: 95, rain=lambda: None, events=lambda: [])
assert ("reminder", "Reminder, sir: stretch.") in got and ("brief", "brief") in got and ("alert", "Sir, the homelab disk is 95% full.") in got, got

# --- scheduler.route: where a message goes ---
phone, laptop = [], []
send = lambda text, silent=False: phone.append((text, silent))
push = lambda text: laptop.append(text)
r = lambda text, kind, now: scheduler.route(text, kind, now, push, send)
scheduler.PRESENCE.update(seen=time.time(), idle=30)                 # at the laptop
r("Reminder, sir: stretch.", "reminder", noon)
assert laptop == ["Reminder, sir: stretch."] and phone == [], (laptop, phone)
scheduler.PRESENCE.update(seen=time.time(), idle=900)                # laptop on, but away 15 min
r("Reminder, sir: stretch.", "reminder", noon)
assert phone == [("Reminder, sir: stretch.", False)], phone
scheduler.PRESENCE.update(seen=time.time() - 60, idle=0)             # laptop not polling (off)
phone.clear(); laptop.clear()
r("Sir, rain is likely.", "alert", noon)
assert phone == [("Sir, rain is likely.", False)] and laptop == []
phone.clear()
r("Sir, rain is likely.", "alert", noon.replace(hour=23, minute=30))  # quiet hours: alerts go silent
assert phone == [("Sir, rain is likely.", True)] and laptop == []
phone.clear()
r("Reminder, sir: take meds.", "reminder", noon.replace(hour=23, minute=30))   # reminders you set still ring
assert phone == [("Reminder, sir: take meds.", False)]
scheduler.seen_laptop(42)
assert scheduler.PRESENCE["idle"] == 42 and time.time() - scheduler.PRESENCE["seen"] < 1
# Every Gemini tool must take only simple typed arguments, or Gemini rejects EVERY call (seen 2026-11-08)
import inspect, tools, accounts
for f in [tools.get_weather, tools.web_search, tools.laptop, skills.laptop_remote, skills.wake_laptop,
          accounts.calendar, accounts.unread_email] + [getattr(skills, n) for n in ("set_reminder", "list_reminders",
          "cancel_reminder", "remember", "forget", "server_status", "laptop_status")]:
    untyped = [n for n, p in inspect.signature(f).parameters.items() if p.annotation is inspect._empty]
    assert not untyped, (f.__name__, untyped)
print("phase2b tests passed")
