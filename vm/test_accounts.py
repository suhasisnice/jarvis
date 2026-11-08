"""Check for accounts.py: read-only calendar (iCal link) and Gmail (IMAP). Run: python test_accounts.py"""
from datetime import datetime, timedelta, timezone
import accounts

ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART:20261109T063000Z
SUMMARY:Team standup
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=Asia/Kolkata:20261109T180000
SUMMARY:Gym
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20261110
SUMMARY:Mum's birthday
END:VEVENT
BEGIN:VEVENT
DTSTART:20261101T090000
SUMMARY:Old meeting
END:VEVENT
BEGIN:VEVENT
DTSTART:20261109T200000
SUMMARY:Dinner with
  friends
END:VEVENT
END:VCALENDAR
"""
NOW = datetime(2026, 11, 9, 9, 0)   # local (naive) time, as on the server (Asia/Kolkata)
LOCAL = timezone(timedelta(hours=5, minutes=30))

ev = accounts.parse_ics(ICS, local_tz=LOCAL)
names = [s for _, s in ev]
assert "Dinner with friends" in names, names            # folded lines are joined
standup = dict((s, d) for d, s in ev)["Team standup"]
assert standup == datetime(2026, 11, 9, 12, 0), standup   # 06:30 UTC = 12:00 IST, returned naive local
assert dict((s, d) for d, s in ev)["Mum's birthday"] == datetime(2026, 11, 10, 0, 0)

accounts._fetch = lambda url: ICS
accounts.CAL_URL = "https://example/basic.ics"
up = accounts.upcoming_events(hours=24, now=NOW, local_tz=LOCAL)
assert [s for _, s in up] == ["Team standup", "Gym", "Dinner with friends", "Mum's birthday"], up   # sorted; past and >24h dropped
accounts._now, accounts.LOCAL_TZ = (lambda: NOW), LOCAL
r = accounts.calendar(days=1)
assert "Team standup" in r and "12:00 PM" in r and "Old meeting" not in r, r
accounts.CAL_URL = ""
assert "isn't set up" in accounts.calendar() and accounts.upcoming_events() == []

class FakeIMAP:
    def __init__(self, host, port=993): self.host = host
    def login(self, u, p): assert (u, p) == ("me@gmail.com", "app pass"); return ("OK", [])
    def select(self, box, readonly=False): assert readonly, "must never mark mail as read"; return ("OK", [b"3"])
    def search(self, charset, crit): return ("OK", [b"4 7 9"])
    def fetch(self, num, what):
        subj = {b"9": "=?utf-8?q?Interview_invite?=", b"7": "Your order shipped", b"4": "Hi"}[num]
        return ("OK", [(b"x", f"From: Recruiter <hr@co.com>\r\nSubject: {subj}\r\n\r\n".encode())])
    def logout(self): pass
accounts.imaplib.IMAP4_SSL = FakeIMAP
accounts.GMAIL_USER, accounts.GMAIL_PASS = "me@gmail.com", "app pass"
r = accounts.unread_email(limit=2)
assert r.startswith("You have 3 unread emails.") and "Interview invite" in r and "Recruiter" in r and "Hi" not in r, r
accounts.GMAIL_USER = ""
assert "isn't set up" in accounts.unread_email()
print("accounts tests passed")
