"""Check for scheduler.py: Jarvis speaking first. Run: python test_scheduler.py"""
import tempfile, threading
from datetime import datetime, timedelta
from pathlib import Path

import memory
memory.DB_PATH = Path(tempfile.mkdtemp()) / "t.db"
memory.init()
import scheduler

# Inbox: what the laptop picks up and speaks
box = scheduler.Inbox()
box.push("a"); box.push("b")
assert box.take() == ["a", "b"] and box.take() == []

sent = []
deliver = lambda text, kind=None: sent.append(text)   # kind: reminder | brief | alert
brief = lambda: "Good morning, sir. Sunny, 31 degrees."
state = {}
seven = datetime(2026, 11, 8, 7, 59)
eight = datetime(2026, 11, 8, 8, 0)

# due reminders are delivered once, with the reminder text
memory.add_reminder(seven.timestamp() - 1, "stretch")
memory.add_reminder(seven.timestamp() + 3600 * 50, "later")   # not due during this test
scheduler.tick(seven, deliver, brief, state, disk_percent=lambda: 40)
assert sent == ["Reminder, sir: stretch."], sent
scheduler.tick(seven, deliver, brief, state, disk_percent=lambda: 40)
assert sent == ["Reminder, sir: stretch."], "a reminder must fire only once"

# morning brief: once, in the BRIEF_HOUR hour (default 8), not before
sent.clear()
scheduler.tick(eight, deliver, brief, state, disk_percent=lambda: 40)
scheduler.tick(eight + timedelta(minutes=20), deliver, brief, state, disk_percent=lambda: 40)
assert sent == ["Good morning, sir. Sunny, 31 degrees."], sent
sent.clear()
scheduler.tick(eight + timedelta(days=1), deliver, brief, state, disk_percent=lambda: 40)
assert sent == ["Good morning, sir. Sunny, 31 degrees."], "next day gets a new brief"

# disk alert above 90%: once a day
sent.clear()
noon = datetime(2026, 11, 9, 12, 0)
scheduler.tick(noon, deliver, brief, state, disk_percent=lambda: 95.4)
scheduler.tick(noon + timedelta(hours=1), deliver, brief, state, disk_percent=lambda: 96)
assert len(sent) == 1 and "95%" in sent[0] and "disk" in sent[0].lower(), sent

# one failing job never blocks the others
sent.clear()
memory.add_reminder(noon.timestamp(), "still delivered")
def bad_brief(): raise RuntimeError("gemini down")
scheduler.tick(datetime(2026, 11, 10, 8, 5), deliver, bad_brief, {}, disk_percent=lambda: 1 / 0)
assert sent == ["Reminder, sir: still delivered."], sent

# start() runs tick in a daemon thread
calls = []
t = scheduler.start(lambda text: None, brief, interval=0.01, tick=lambda *a, **k: calls.append(1))
import time; time.sleep(0.3)
assert len(calls) >= 3 and t.daemon and t.is_alive(), calls   # keeps looping (sleep must work)
print("scheduler tests passed")
