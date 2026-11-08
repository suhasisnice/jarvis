"""
Fastpath module: handles everyday commands locally via Ollama without invoking Gemini.
"""

import json
import os
import re
import logging
import urllib.request
from datetime import datetime, timedelta

import memory
import skills

# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
FAST_MODEL = os.getenv("FAST_MODEL", "qwen3.5:4b")
KEYWORDS = re.compile(r"\b(timer|remind|volume|open|play)\b", re.I)

SITES = {
    "youtube",
    "google",
    "gmail",
    "github",
    "netflix",
    "instagram",
    "reddit",
    "twitter",
    "x",
    "facebook",
    "amazon",
    "spotify",
    "linkedin",
    "whatsapp",
    "chatgpt",
}

# Exact phrase handling --------------------------------------------------
_EXACT_PHRASES = {
    # pause / resume
    "pause": ("pause", "Paused, sir."),
    "pause the music": ("pause", "Paused, sir."),
    "pause music": ("pause", "Paused, sir."),
    "resume": ("pause", "Paused, sir."),
    "resume the music": ("pause", "Paused, sir."),
    # next / skip
    "next": ("next", "Next track, sir."),
    "skip": ("next", "Next track, sir."),
    "next song": ("next", "Next track, sir."),
    "skip song": ("next", "Next track, sir."),
    "skip this song": ("next", "Next track, sir."),
    "next track": ("next", "Next track, sir."),
    # lock
    "lock": ("lock", "Locking your computer, sir."),
    "lock my computer": ("lock", "Locking your computer, sir."),
    "lock my pc": ("lock", "Locking your computer, sir."),
    "lock the pc": ("lock", "Locking your computer, sir."),
    "lock my laptop": ("lock", "Locking your computer, sir."),
    "lock the computer": ("lock", "Locking your computer, sir."),
    # time / date (handled specially)
    "what time is it": "time",
    "what's the time": "time",
    "whats the time": "time",
    "what is the time": "time",
    "time": "time",
    "what's the date": "date",
    "what is the date": "date",
    "what's the date today": "date",
    "what's today's date": "date",
    "what day is it": "date",
    "what's the day today": "date",
}

# Schema and system prompt placeholders ---------------------------------
SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                "timer",
                "reminder",
                "volume",
                "open_app",
                "open_website",
                "play",
                "pause",
                "next",
                "mute",
                "lock",
                "time",
                "date",
                "other",
            ],
        },
        "minutes": {"type": ["number", "null"]},
        "at": {"type": ["string", "null"]},
        "text": {"type": ["string", "null"]},
        "target": {"type": ["string", "null"]},
    },
    "required": ["intent", "minutes", "at", "text", "target"],
}
# Tested 2026-11-08 on qwen3.5:4b: 20/24 intents right, ~1 s, no question mistaken for a command.
SYSTEM = """You turn one spoken command into JSON. It came from speech recognition, so expect small mistakes.
intent:
- timer: "set a timer for 5 minutes". minutes = length (2.5 for two and a half).
- reminder: "remind me in 20 minutes to stretch" -> minutes=20, text="stretch". "remind me at 7 pm to call mum" -> at="19:00", text="call mum". Always 24-hour HH:MM.
- volume: target = percent as a number string, "set volume to 30" -> "30".
- open_app: target = app name. open_website: target = site, e.g. "youtube.com".
- play: target = the song or video, e.g. "Loser by Tame Impala". pause: pause or resume. next: next/skip track.
- mute, lock: no fields. time: asks the time. date: asks today's date or day.
- other: ANYTHING else: questions, chat, weather, news, search, remembering facts, cancelling or changing reminders, sleep, screen questions, or anything unclear.
Unused fields are null."""


# ----------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------
def _normalize(text: str) -> str:
    """Lower‑case and strip surrounding punctuation."""
    return re.sub(r"^[\s.,!?:;]+|[\s.,!?:;]+$", "", text.lower())


def _format_time(dt: datetime) -> str:
    hour = dt.hour % 12 or 12
    return f"{hour}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def _format_date(dt: datetime) -> str:
    return f"It's {dt.strftime('%A')}, {dt.day} {dt.strftime('%B')}, sir."


# ----------------------------------------------------------------------
# Core functions
# ----------------------------------------------------------------------
def parse(text: str):
    """
    Send *text* to the fast model via Ollama and return the parsed JSON dict.
    Returns ``None`` on any error.
    """
    payload = {
        "model": FAST_MODEL,
        "stream": False,
        "think": False,
        "keep_alive": -1,   # stay loaded on the GPU: a cold load (~8 s) is longer than our 4 s limit
        "format": SCHEMA,
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": text},
        ],
    }
    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL.rstrip('/')}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode())
        # Expected structure: {'message': {'content': '<json string>'}}
        content = data.get("message", {}).get("content", "")
        return json.loads(content)
    except Exception as exc:  # pragma: no cover – exercised via tests with fake parse
        logging.warning(f"Fast lane: local model unavailable ({exc}); asking Gemini.")
        return None


def route(text: str, laptop: bool = True, now: datetime = None, parse=parse):
    """
    Route *text* to a fast reply/action pair or return ``None`` to fall back
    to Gemini.
    """
    now = now or datetime.now()
    norm = _normalize(text)

    # ------------------------------------------------------------------
    # 1) Exact phrase handling
    # ------------------------------------------------------------------
    if norm in _EXACT_PHRASES:
        val = _EXACT_PHRASES[norm]
        if isinstance(val, tuple):
            action, reply = val
            if not laptop:
                return None
            return reply, [{"do": action, "target": ""}]
        elif val == "time":
            reply = f"It's {_format_time(now)}, sir."
            return reply, []
        elif val == "date":
            reply = _format_date(now)
            return reply, []

    # ------------------------------------------------------------------
    # 2) Keyword check – if none, defer to Gemini
    # ------------------------------------------------------------------
    if not KEYWORDS.search(text):
        return None
    if re.search(r"\b(and|then|also)\b.*\b(timer|remind|volume|open|play|pause|lock|mute|set|turn|search|tell|what|check)\b", text, re.I):
        return None   # two requests in one sentence: the local model only handles one, Gemini does both

    # ------------------------------------------------------------------
    # 3) Model parsing
    # ------------------------------------------------------------------
    p = parse(text)
    if not isinstance(p, dict):
        return None

    intent = p.get("intent")
    # --------------------------------------------------------------
    # Timer
    # --------------------------------------------------------------
    if intent == "timer":
        minutes = p.get("minutes")
        if isinstance(minutes, (int, float)) and minutes > 0:
            label = f"{minutes:g}"
            due_ts = now.timestamp() + minutes * 60
            memory.add_reminder(due_ts, f"your {label} minute timer is done")
            return f"Timer set for {label} minutes, sir.", []
        return None

    # --------------------------------------------------------------
    # Reminder
    # --------------------------------------------------------------
    if intent == "reminder":
        text_msg = p.get("text")
        if not isinstance(text_msg, str) or not text_msg.strip():
            return None

        minutes = p.get("minutes")
        at_str = p.get("at")
        due = None

        if isinstance(minutes, (int, float)) and minutes > 0:
            due = now + timedelta(minutes=minutes)
        elif isinstance(at_str, str):
            m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", at_str.strip())
            if not m:
                return None
            hour, minute = map(int, m.groups())
            due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        else:
            return None

        # Adjust for "tomorrow" or past time
        lower = text.lower()
        if "tomorrow" in lower or due <= now:
            due += timedelta(days=1)

        day_prefix = "tomorrow " if due.date() > now.date() else ""
        time_str = _format_time(due)
        memory.add_reminder(due.timestamp(), text_msg)
        return f"I'll remind you {day_prefix}at {time_str} to {text_msg}, sir.", []

    # --------------------------------------------------------------
    # Volume
    # --------------------------------------------------------------
    if intent == "volume":
        if not laptop:
            return None
        target = p.get("target")
        if not isinstance(target, str) or not target.isdigit():
            return None
        n = int(target)
        if not (0 <= n <= 100):
            return None
        return f"Volume set to {n} percent, sir.", [{"do": "volume", "target": str(n)}]

    # --------------------------------------------------------------
    # Open app / website
    # --------------------------------------------------------------
    if intent in ("open_app", "open_website"):
        if not laptop:
            return None
        target = p.get("target")
        if not isinstance(target, str) or not target.strip():
            return None
        target_clean = target.strip()
        low = target_clean.lower()
        if low in SITES or intent == "open_website":
            # known site → open in browser
            site = low if "." in low else f"{low}.com"   # "youtube" -> youtube.com
            action = {"do": "open_website", "target": site}
            reply = f"Opening {low}, sir."
            return reply, [action]
        else:
            action = {"do": "open_app", "target": target_clean}
            reply = f"Opening {target_clean}, sir."
            return reply, [action]

    # --------------------------------------------------------------
    # Play
    # --------------------------------------------------------------
    if intent == "play":
        if not laptop:
            return None
        target = p.get("target")
        if not isinstance(target, str) or not target.strip():
            return None
        return f"Playing {target.strip()}, sir.", [{"do": "play", "target": target.strip()}]

    # --------------------------------------------------------------
    # Other intents that require laptop (pause/next/lock) – already handled
    # via exact phrases, so fall through.
    # --------------------------------------------------------------
    return None
