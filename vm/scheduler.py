"""Jarvis speaking first: reminders, morning brief, disk alert."""
import logging
import os
import shutil
import threading
import time
from datetime import datetime

import memory

BRIEF_HOUR = int(os.environ.get('BRIEF_HOUR', '8'))
DISK_ALERT = 90

class Inbox:
    """Thread-safe list for storing and retrieving messages."""
    def __init__(self):
        self._items = []
        self._lock = threading.Lock()

    def push(self, text):
        """Add a message to the inbox."""
        with self._lock:
            self._items.append(text)

    def take(self):
        """Retrieve all messages from the inbox and clear it."""
        with self._lock:
            items = self._items.copy()
            self._items.clear()
            return items

inbox = Inbox()

def disk_percent():
    """Return the percentage of disk space used on the root directory."""
    usage = shutil.disk_usage('/')
    return (usage.used / usage.total) * 100

def tick(now: datetime, deliver, brief, state: dict, disk_percent=disk_percent, rain=None, events=None):
    """Perform scheduled tasks and deliver messages."""
    try:
        for _id, text in memory.due_reminders(now.timestamp()):
            deliver(f'Reminder, sir: {text}.', 'reminder')
    except Exception:
        logging.exception("Failed to deliver reminders")

    try:
        if now.hour == BRIEF_HOUR and state.get('brief_day') != now.date():
            state['brief_day'] = now.date()
            deliver(brief(), 'brief')
    except Exception:
        logging.exception("Failed to deliver morning brief")

    try:
        p = disk_percent()
        if p > DISK_ALERT and state.get('disk_day') != now.date():
            state['disk_day'] = now.date()
            deliver(f'Sir, the homelab disk is {p:.0f}% full.', 'alert')
    except Exception:
        logging.exception("Failed to deliver disk alert")

    try:   # rain in the next couple of hours: at most once every 3 hours
        p = rain() if rain is not None else None
        if p is not None and p >= 60 and now.timestamp() >= state.get('rain_until', 0):
            state['rain_until'] = now.timestamp() + 3 * 3600
            deliver(f'Sir, rain is likely in the next couple of hours ({p}%).', 'alert')
    except Exception:
        logging.exception("Failed to check rain")

    try:   # calendar heads-up ~10 minutes before each event, once each
        seen = state.setdefault('cal_seen', set())
        for start, summary in (events() if events is not None else []):
            ahead = (start - now).total_seconds()
            if 0 <= ahead <= 11 * 60 and (start.isoformat(), summary) not in seen:
                seen.add((start.isoformat(), summary))
                deliver(f'Sir, {summary} starts in {max(1, round(ahead / 60))} minutes.', 'alert')
    except Exception:
        logging.exception("Failed to check the calendar")

def start(deliver, brief, interval=15, tick=tick, rain=None, events=None):
    """Start a daemon thread to perform scheduled tasks."""
    state = {}

    def loop():
        while True:
            try:
                tick(datetime.now(), deliver, brief, state, rain=rain, events=events)
            except Exception:
                logging.exception("Failed to perform scheduled tasks")
            time.sleep(interval)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    return thread


# Where messages go: the laptop speaks them if you're at it, otherwise Telegram.
PRESENCE = {'seen': 0.0, 'idle': 1e9}   # last laptop poll time, and how long you'd been idle then
QUIET_START = int(os.environ.get('QUIET_START', '23'))
QUIET_END = int(os.environ.get('QUIET_END', '7'))


def seen_laptop(idle_seconds):
    PRESENCE.update(seen=time.time(), idle=float(idle_seconds))


def _quiet(now):
    return now.hour >= QUIET_START or now.hour < QUIET_END


def route(text, kind, now, push_laptop, send_phone):
    """Alerts in quiet hours arrive silently on the phone; reminders you set always ring."""
    if kind == 'alert' and _quiet(now):
        send_phone(text, silent=True)
        return
    at_laptop = time.time() - PRESENCE['seen'] < 15 and PRESENCE['idle'] < 600
    if at_laptop:
        push_laptop(text)
    else:
        send_phone(text, silent=False)
