"""Check for fastpath.py: everyday commands handled without Gemini. Run: python test_fastpath.py"""
import tempfile
from datetime import datetime
from pathlib import Path

import memory
memory.DB_PATH = Path(tempfile.mkdtemp()) / "t.db"
memory.init()
import fastpath

NOW = datetime(2026, 11, 8, 11, 0)   # Sunday 11:00 AM
calls = []
def fake(result):
    def parse(text):
        calls.append(text)
        return result
    return parse
route = lambda text, laptop=True, result=None: fastpath.route(text, laptop, now=NOW, parse=fake(result))
P = lambda **k: {"intent": "other", "minutes": None, "at": None, "text": None, "target": None, **k}

# exact phrases: instant, no model call
calls.clear()
assert route("Pause.") == ("Paused, sir.", [{"do": "pause", "target": ""}])
assert route("skip this song") == ("Next track, sir.", [{"do": "next", "target": ""}])
assert route("Lock my computer.") == ("Locking your computer, sir.", [{"do": "lock", "target": ""}])
assert route("What time is it?") == ("It's 11:00 AM, sir.", [])
assert route("what day is it") == ("It's Sunday, 8 November, sir.", [])
assert calls == [], "exact phrases must not call the model"
assert route("pause", laptop=False) is None          # phone: laptop actions go to Gemini, which explains
assert route("what time is it", laptop=False) == ("It's 11:00 AM, sir.", [])

# no command keyword: straight to Gemini, no model call
assert route("What's the weather in Paris?") is None and calls == []

# timers and reminders (also from the phone)
r = route("set a timer for two and a half minutes", laptop=False, result=P(intent="timer", minutes=2.5))
assert r == ("Timer set for 2.5 minutes, sir.", []), r
assert route("Remind me in 20 minutes to stretch.", result=P(intent="reminder", minutes=20, text="stretch")) == \
       ("I'll remind you at 11:20 AM to stretch, sir.", [])
assert route("remind me at 7 pm to call mum", result=P(intent="reminder", at="19:00", text="call mum")) == \
       ("I'll remind you at 7:00 PM to call mum, sir.", [])
assert route("remind me at 9 am to call the bank", result=P(intent="reminder", at="09:00", text="call the bank")) == \
       ("I'll remind you tomorrow at 9:00 AM to call the bank, sir.", [])      # 9 AM already passed today
assert route("remind me tomorrow at 7 pm to pay rent", result=P(intent="reminder", at="19:00", text="pay rent")) == \
       ("I'll remind you tomorrow at 7:00 PM to pay rent, sir.", [])
pending = {t: d for _, d, t in memory.pending_reminders()}
assert pending["your 2.5 minute timer is done"] == NOW.timestamp() + 150
assert pending["stretch"] == NOW.timestamp() + 1200
assert pending["call mum"] == datetime(2026, 11, 8, 19, 0).timestamp()
assert pending["call the bank"] == datetime(2026, 11, 9, 9, 0).timestamp()
assert pending["pay rent"] == datetime(2026, 11, 9, 19, 0).timestamp()

# laptop actions
assert route("Set the volume to 30 percent.", result=P(intent="volume", target="30")) == \
       ("Volume set to 30 percent, sir.", [{"do": "volume", "target": "30"}])
assert route("Open VS Code.", result=P(intent="open_app", target="VS Code")) == \
       ("Opening VS Code, sir.", [{"do": "open_app", "target": "VS Code"}])
assert route("open youtube", result=P(intent="open_app", target="youtube")) == \
       ("Opening youtube, sir.", [{"do": "open_website", "target": "youtube.com"}])   # known sites open in the browser
assert route("Play Loser by Tame Impala.", result=P(intent="play", target="Loser by Tame Impala")) == \
       ("Playing Loser by Tame Impala, sir.", [{"do": "play", "target": "Loser by Tame Impala"}])
assert route("Play Loser by Tame Impala.", laptop=False, result=P(intent="play", target="x")) is None

# anything unsure goes to Gemini
for bad in (None, P(), P(intent="timer"), P(intent="timer", minutes=0), P(intent="reminder", minutes=5),
            P(intent="reminder", at="25:99", text="x"), P(intent="volume", target="loud"), P(intent="play"),
            P(intent="time")):
    assert route("set a timer or open something", result=bad) is None, bad
calls.clear()
assert route("Set a timer for 5 minutes and open YouTube.", result=P(intent="timer", minutes=5)) is None and calls == []
assert route("Remind me in 5 minutes to buy bread and milk.", result=P(intent="reminder", minutes=5, text="buy bread and milk")) ==        ("I'll remind you at 11:05 AM to buy bread and milk, sir.", [])
print("fastpath tests passed")
