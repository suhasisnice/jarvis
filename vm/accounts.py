"""
Read-only access to your Google Calendar (its secret iCal link) and Gmail (IMAP + an app password).
Nothing here can send, delete or mark anything read. Set in ~/jarvis/.env:
  CAL_ICS_URL=...          Google Calendar > Settings > your calendar > "Secret address in iCal format"
  GMAIL_USER=you@gmail.com
  GMAIL_APP_PASSWORD=...   Google Account > Security > App passwords
"""
import email
import email.header
import email.utils
import imaplib
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

CAL_URL = os.environ.get("CAL_ICS_URL", "")
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_PASS = os.environ.get("GMAIL_APP_PASSWORD", "")
_now = datetime.now   # swapped in tests
LOCAL_TZ = None       # None = the server's own time zone


def _fetch(url):
    with urllib.request.urlopen(url, timeout=15) as r:
        return r.read().decode("utf-8")


def _start(line, local_tz):
    """One DTSTART line -> naive local datetime."""
    head, value = line.split(":", 1)
    value = value.strip()
    if "VALUE=DATE" in head or len(value) == 8:                  # all-day event
        return datetime.strptime(value[:8], "%Y%m%d")
    when = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        when = when.replace(tzinfo=timezone.utc)
    elif "TZID=" in head:
        when = when.replace(tzinfo=ZoneInfo(head.split("TZID=", 1)[1].split(";")[0]))
    else:
        return when                                               # "floating" time: already local
    return when.astimezone(local_tz).replace(tzinfo=None)


def parse_ics(text, local_tz=None):
    # ponytail: repeating events (RRULE) only show their first date; expand them if that matters
    local_tz = local_tz or datetime.now().astimezone().tzinfo
    lines = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]                                  # folded line continues the last one
        else:
            lines.append(raw)
    events, start, summary = [], None, None
    for line in lines:
        if line == "BEGIN:VEVENT":
            start = summary = None
        elif line.startswith("DTSTART"):
            try:
                start = _start(line, local_tz)
            except Exception:
                start = None
        elif line.startswith("SUMMARY"):
            summary = line.split(":", 1)[1].strip()
        elif line == "END:VEVENT" and start and summary:
            events.append((start, summary))
    return events


def upcoming_events(hours=24, now=None, local_tz=None):
    now = now or datetime.now()
    if not CAL_URL:
        return []
    try:
        return sorted(e for e in parse_ics(_fetch(CAL_URL), local_tz) if now <= e[0] < now + timedelta(hours=hours))
    except Exception:
        return []


def calendar(days: int = 1) -> str:
    """The user's upcoming calendar events for the next `days` days (read-only).
    Use for "what's on my calendar", "am I free", "what's today"."""
    if not CAL_URL:
        return "Your calendar isn't set up, sir."
    # Gemini tools must only take simple typed arguments, so the clock/zone come from module globals
    events = upcoming_events(days * 24, _now(), LOCAL_TZ)
    if not events:
        return "Nothing on your calendar."
    return "; ".join(f"{d:%a} {d:%I:%M %p}".replace(" 0", " ") + f" {s}" for d, s in events)


def _decode(value):
    return str(email.header.make_header(email.header.decode_header(value or "")))


def unread_email(limit: int = 5) -> str:
    """Count and latest subjects of the user's unread Gmail (read-only, never marks anything read).
    Use for "any new emails", "check my mail"."""
    if not GMAIL_USER or not GMAIL_PASS:
        return "Your email isn't set up, sir."
    m = None
    try:
        m = imaplib.IMAP4_SSL("imap.gmail.com")
        m.login(GMAIL_USER, GMAIL_PASS)
        m.select("INBOX", readonly=True)                          # readonly: nothing gets marked read
        ids = m.search(None, "UNSEEN")[1][0].split()
        if not ids:
            return "No unread emails, sir."
        latest = []
        for num in reversed(ids[-limit:]):
            raw = m.fetch(num, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")[1][0][1]
            msg = email.message_from_bytes(raw)
            name, addr = email.utils.parseaddr(_decode(msg["From"]))
            latest.append(f"{name or addr}: {_decode(msg['Subject'])}")
        return f"You have {len(ids)} unread emails. Latest: " + "; ".join(latest)
    except Exception:
        return "I couldn't reach your email, sir."               # never echo the error: it can hold credentials
    finally:
        if m is not None:
            try:
                m.logout()
            except Exception:
                pass
