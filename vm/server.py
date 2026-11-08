"""
Jarvis VM server — listens on port 8000 for requests from the Legion client.

Endpoints:
  POST /ask   { "message": "..." }  →  { "reply": "..." }
  GET  /ping                         →  { "status": "ok" }
  GET  /status                       →  { "activity": "Checking the weather..." }
  GET  /notify                       →  { "notes": [...] }  things to say out loud (reminders, alerts)
  POST /see?q=question  (raw image body, Content-Type image/jpeg or image/png)  →  { "reply": "..." }
  GET  /voice                        →  phone push-to-talk page (needs HTTPS: tailscale serve)
  POST /voice/turn  (raw audio body, Content-Type audio/wav or audio/ogg)
                                     →  { "transcript", "reply", "audio": base64 MP3 or null }

Telegram (Phase 2) runs as a thread in this same process when TELEGRAM_BOT_TOKEN is set,
so there is only ever one poller for the bot (two pollers = Telegram 409 errors).

Run:
  python server.py

Environment variables (put these in a .env file and load with python-dotenv):
  GEMINI_API_KEY   your Gemini API key
  GEMINI_MODEL     gemini-1.5-flash (default)
  OLLAMA_URL       http://<legion-tailscale-ip>:11434
  OLLAMA_MODEL     qwen2.5-coder:7b (default)
"""

import base64
import time
import urllib.parse
import logging
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Load .env file if present
_env = Path(__file__).parent / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

import memory
import brain
import tools
import voice
import telegram_bot
import scheduler
import skills
import accounts
from datetime import datetime

VOICE_PAGE = Path(__file__).parent / "voice.html"
MAX_AUDIO_BYTES = 10 * 1024 * 1024   # ~5 minutes of 16 kHz WAV; anything bigger is refused

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        # Route HTTP access logs through Python logging instead of stdout
        line = format % args
        if "/status" in line or "/notify" in line:
            return   # polled twice a second during a turn; would flood the journal
        logging.info(f"{self.address_string()} - {line}")

    def do_GET(self):
        if self.path == "/ping":
            self._respond(200, {"status": "ok"})
        elif self.path == "/status":
            self._respond(200, {"activity": tools.ACTIVITY})
        elif self.path.startswith("/notify"):
            # The laptop polls this every 3 s and says how long you've been idle, so alerts can go
            # to the laptop when you're at it and to Telegram when you're not.
            idle = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("idle")
            if idle:
                scheduler.seen_laptop(idle[0])
            items = scheduler.inbox.take()
            # Only fresh items: a laptop that was off shouldn't replay yesterday's reminders
            notes = [i["say"] for i in items if "say" in i and time.time() - i["t"] < 300]
            todo = [{"do": i["do"], "target": i["target"]} for i in items if "do" in i and time.time() - i["t"] < 60]
            self._respond(200, {"notes": notes, "actions": todo})
        elif self.path == "/voice":
            self._send(200, VOICE_PAGE.read_bytes(), "text/html; charset=utf-8")
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/voice/turn":
            self._voice_turn()
        elif self.path.startswith("/see"):
            self._see()
        elif self.path == "/ask":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
                message = data.get("message", "").strip()
                if not message:
                    self._respond(400, {"error": "empty message"})
                    return
                if data.get("source") == "laptop":   # only the laptop can run actions
                    reply, actions = brain.think(message, laptop=True)
                else:
                    reply, actions = brain.think(message), []
                self._respond(200, {"reply": reply, "actions": actions})
            except Exception as e:
                logging.error(f"Error handling /ask: {e}")
                self._respond(500, {"error": "internal error"})
        else:
            self._respond(404, {"error": "not found"})

    def _voice_turn(self):
        """Phone page: audio in -> transcript, reply text, reply audio (Ryan, MP3)."""
        length = int(self.headers.get("Content-Length", 0))
        if not 0 < length <= MAX_AUDIO_BYTES:
            self._respond(413, {"error": "audio missing or too large"})
            return
        audio = self.rfile.read(length)
        mime = self.headers.get("Content-Type", "audio/wav").split(";")[0].strip()
        try:
            transcript = voice.transcribe(audio, mime)
            reply = brain.think(transcript) if transcript else "I couldn't make that out, sir."
            sound = voice.mp3(reply)
            self._respond(200, {"transcript": transcript, "reply": reply,
                                "audio": base64.b64encode(sound).decode() if sound else None})
        except Exception as e:
            logging.error(f"Error handling /voice/turn: {e}")
            self._respond(500, {"error": "internal error"})

    def _see(self):
        """Laptop screenshot (or any picture) + question -> answer."""
        length = int(self.headers.get("Content-Length", 0))
        if not 0 < length <= MAX_AUDIO_BYTES:
            self._respond(413, {"error": "image missing or too large"})
            return
        image = self.rfile.read(length)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        question = (query.get("q") or ["What's on my screen?"])[0]
        mime = self.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        try:
            self._respond(200, {"reply": brain.look(image, mime, question)})
        except Exception as e:
            logging.error(f"Error handling /see: {e}")
            self._respond(500, {"error": "internal error"})

    def _respond(self, code: int, data: dict):
        self._send(code, json.dumps(data).encode(), "application/json")

    def _send(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

if __name__ == "__main__":
    memory.init()
    telegram_bot.start(brain.think, voice.transcribe, voice.speech, look=brain.look)

    def deliver(text, kind="alert"):   # Jarvis speaking first: laptop if you're at it, else Telegram
        logging.info(f"Notify ({kind}): {text}")
        scheduler.route(text, kind, datetime.now(),
                        push_laptop=lambda t: scheduler.inbox.push({"t": time.time(), "say": t}),
                        send_phone=telegram_bot.send_all)
    city = os.getenv("BRIEF_CITY", "Bangalore")
    scheduler.start(deliver, brain.brief, rain=lambda: skills.rain_chance(city), events=accounts.upcoming_events)
    port = 8000
    logging.info(f"Jarvis VM server starting on port {port}...")
    # Threading: /status must answer while an /ask is still being worked on
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
