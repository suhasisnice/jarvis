"""Check for memory.py (reminders + facts) and skills.py (Gemini tools). Run: python test_skills.py"""
import os, tempfile, time
from pathlib import Path

import memory
memory.DB_PATH = Path(tempfile.mkdtemp()) / "t.db"
memory.init()
import skills

# --- memory: reminders ---
now = time.time()
a = memory.add_reminder(now + 60, "stretch")
b = memory.add_reminder(now - 5, "drink water")
assert isinstance(a, int) and a != b
assert [t for _, _, t in memory.pending_reminders()] == ["drink water", "stretch"]   # soonest first
assert memory.due_reminders(now) == [(b, "drink water")]
assert memory.due_reminders(now) == []                                  # each fires only once
assert [t for _, _, t in memory.pending_reminders()] == ["stretch"]
assert memory.due_reminders(now + 61) == [(a, "stretch")]

# --- memory: facts ---
memory.add_fact("My birthday is 12 March")
memory.add_fact("I like dark mode")
assert memory.facts() == ["My birthday is 12 March", "I like dark mode"]
assert memory.forget_fact("birthday") == 1 and memory.facts() == ["I like dark mode"]
assert memory.forget_fact("nothing like this") == 0

# --- skills: what Gemini calls ---
r = skills.set_reminder(20, "call mum")
assert "call mum" in r and ":" in r, r                                   # says the time, e.g. "at 18:45"
assert "call mum" in skills.list_reminders()
assert memory.due_reminders(time.time() + 20 * 60 + 1)[-1][1] == "call mum"
assert "no reminders" in skills.list_reminders().lower()
assert "remember" in skills.remember("I drive a red car").lower()
assert "I drive a red car" in memory.facts()
assert "forgot" in skills.forget("red car").lower() and memory.facts() == ["I like dark mode"]
assert "couldn't find" in skills.forget("zebra").lower()

skills.set_reminder(5, "water the plants")
assert "Cancelled 1" in skills.cancel_reminder("plants") and "plants" not in skills.list_reminders()
assert "couldn't find" in skills.cancel_reminder("plants")

s = skills.server_status()
for word in ("uptime", "disk", "memory"):
    assert word in s.lower(), s

skills.subprocess.run = lambda *a, **k: type("R", (), {"returncode": 0})()
assert "online" in skills.laptop_status().lower()
skills.subprocess.run = lambda *a, **k: type("R", (), {"returncode": 1})()
assert "asleep" in skills.laptop_status().lower()
print("skills tests passed")
