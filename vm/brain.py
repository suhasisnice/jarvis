import os
import logging
import threading
from pathlib import Path
from datetime import datetime

import requests
import google.genai as genai
from google.genai import types

import memory
import tools
import skills
import fastpath
import accounts

# Reminders, facts, homelab + laptop status (vm/skills.py)
SKILLS = [skills.set_reminder, skills.list_reminders, skills.cancel_reminder, skills.remember, skills.forget,
          skills.server_status, skills.laptop_status, skills.wake_laptop]
# Calendar/email only once set up in .env: otherwise Gemini "reads" an empty calendar and says so
SKILLS += [accounts.calendar] if accounts.CAL_URL else []
SKILLS += [accounts.unread_email] if accounts.GMAIL_USER and accounts.GMAIL_PASS else []

# Jarvis's personality lives in persona.txt so it can be edited without touching code
SYSTEM_PROMPT = (Path(__file__).parent / "persona.txt").read_text(encoding="utf-8")

def _system_prompt() -> str:
    # Give Jarvis today's real date each turn — otherwise he assumes his training-data
    # year (he was saying 2024) and states stale facts as current.
    today = datetime.now().strftime("%A, %d %B %Y, %I:%M %p")   # local time; server zone is Asia/Kolkata
    return (
        SYSTEM_PROMPT
        + f"\n\nCURRENT CONTEXT\nToday's date is {today}. Treat this as the present. "
        "For anything that may have changed since your training data — current office "
        "holders, recent events, live figures — say plainly that your information may be "
        "out of date rather than stating an old answer as fact."
        + _known_facts()
    )

def _known_facts() -> str:
    known = memory.facts()
    return ("\n\nTHINGS THE USER ASKED YOU TO REMEMBER\n- " + "\n- ".join(known)) if known else ""

GEMINI_MODEL  = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
# Second Gemini to try on a free-tier 429/503 before dropping to the much weaker Ollama model
GEMINI_FALLBACK = os.getenv("GEMINI_FALLBACK", "gemini-3.1-flash-lite")
OLLAMA_URL    = os.getenv("OLLAMA_URL", "http://localhost:11434")   # Legion's Ollama, reached over Tailscale
OLLAMA_MODEL  = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")

def _init_gemini():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logging.warning("GEMINI_API_KEY not set — will use Ollama only.")
        return None
    # timeout is in milliseconds, per request. 10 s is Google's MINIMUM (8 s was rejected with
    # 400 "Minimum allowed deadline is 10s", failing every call). A healthy reply takes ~1 s,
    # so anything longer is a free-tier stall: give up and try the fallback model.
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=10000))

_client = _init_gemini()

def _ask_gemini(history: list[dict], model: str, image=None) -> str:
    # Build contents list — Gemini uses "model" not "assistant"
    contents = [
        types.Content(
            role="model" if m["role"] == "assistant" else "user",
            parts=[types.Part(text=m["content"])]
        )
        for m in history
    ]
    if image:   # (bytes, mime): attach the picture to the latest message so he can see it
        contents[-1].parts.insert(0, types.Part.from_bytes(data=image[0], mime_type=image[1]))
    response = _client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=_system_prompt(),
            # Pass the Python function directly: the SDK auto-calls it when Jarvis
            # needs live weather, then answers from the result. Free, no API key.
            tools=[tools.get_weather, tools.web_search, *SKILLS] + ([tools.laptop] if tools.LAPTOP else [skills.laptop_remote]),
        ),
    )
    return response.text.strip()

def _ask_ollama(history: list[dict]) -> str:
    messages = [{"role": "system", "content": _system_prompt()}] + history
    response = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={"model": OLLAMA_MODEL, "messages": messages, "stream": False},
        timeout=(3, 60)   # 3 s to connect (fail fast if the PC is off), 60 s to answer
    )
    response.raise_for_status()
    return response.json()["message"]["content"].strip()

# Laptop, Telegram and the phone page share one memory. One turn at a time, so two
# conversations can't interleave their messages (or each other's tool narration).
_turn_lock = threading.Lock()

def think(user_message: str, laptop: bool = False, image=None):
    """
    Main entry point. Takes the user's message, saves it,
    gets a reply from Gemini (or Ollama fallback), saves the reply, returns it.
    laptop=True also gives him the laptop's hands and returns (reply, actions) instead.
    """
    with _turn_lock:
        tools.ACTIONS, tools.LAPTOP = [], laptop
        # Everyday commands: local model on the laptop + fixed reply, no Gemini call at all
        fast = None if image else fastpath.route(user_message, laptop)
        if fast:
            logging.info("Reply from fast lane (local).")
            memory.save("user", user_message)
            memory.save("assistant", fast[0])
            return fast if laptop else fast[0]
        reply = _think(user_message, image)
        return (reply, tools.ACTIONS) if laptop else reply

def look(image: bytes, mime: str, question: str) -> str:
    """Answer a question about a picture (screenshot or phone photo)."""
    return think(question + "\nIf the picture shows an error, quote the key line and give the fix in up to "
                 "three short sentences.", image=(image, mime))

def brief() -> str:
    """Morning brief for the scheduler. Not saved into the chat memory."""
    city = os.getenv("BRIEF_CITY", "Bangalore")
    ask = [{"role": "user", "content": f"Give my morning brief in two or three short sentences: greet me, "
            f"today's weather in {city}, my calendar for today (calendar), "
            f"my unread email count (unread_email) and my reminders for today (list_reminders). Skip anything not set up."}]
    with _turn_lock:
        tools.LAPTOP = False
        for model in (GEMINI_MODEL, GEMINI_FALLBACK):
            try:
                return _ask_gemini(ask, model)
            except Exception as e:
                logging.warning(f"Brief via {model} failed ({e}).")
    return "Good morning, sir. I couldn't put the brief together today."

def _think(user_message: str, image=None) -> str:
    tools.ACTIVITY = ""   # new turn: nothing in progress until a tool starts
    memory.save("user", user_message)
    history = memory.get_history()

    reply = ""

    if _client:
        for model in (GEMINI_MODEL, GEMINI_FALLBACK):
            try:
                reply = _ask_gemini(history, model, image)
                logging.info(f"Reply from Gemini ({model}).")
                break
            except Exception as e:
                logging.warning(f"Gemini {model} failed ({e}).")

    if not reply:
        try:
            reply = _ask_ollama(history)
            logging.info("Reply from Ollama.")
        except Exception as e:
            logging.error(f"Ollama also failed: {e}")
            reply = "I'm having trouble thinking right now, sir."

    tools.ACTIVITY = ""
    memory.save("assistant", reply)
    return reply
