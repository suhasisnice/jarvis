"""
Jarvis on Telegram — talk to the VM brain from your phone (text + voice notes).

CONTRACT (test_phase2.py checks all of this):

Module-level:
  API = "https://api.telegram.org"
  MAX_LEN = 4096                           Telegram's message length limit
  parse_allowed(value) -> set[int]         "111, 222 ,x," -> {111, 222}; "" or None -> set()
  start(think, transcribe, speech, env=os.environ) -> threading.Thread | None
        Reads env["TELEGRAM_BOT_TOKEN"] (missing/empty -> log "Telegram disabled" and return None)
        and env["TELEGRAM_ALLOWED_IDS"] (via parse_allowed). Starts Bot.run() in a daemon thread.

class Bot(token, allowed_ids: set[int], think, transcribe, speech, http=requests):
  think(text) -> reply str                      the normal brain
  transcribe(audio_bytes, mime) -> str          Gemini transcription ("" if no speech)
  speech(text) -> (bytes, "ogg") | (bytes, "mp3") | (None, None)   may also raise
  http: object with .post(url, data=None, files=None, timeout=None) and .get(url, timeout=None)
        returning objects with .json() and .content (requests-compatible)

  call(method, files=None, http_timeout=30, **params) -> parsed JSON (use ["result"])
        POST f"{API}/bot{token}/{method}" with data=params, files=files, timeout=http_timeout.
        (http_timeout is OUR wait; a "timeout" in params is Telegram's long-poll wait. Mixing
        them up turns long polling into a tight loop.)
        If the JSON has ok: false -> raise RuntimeError including error_code and description.
        Any exception text must NEVER contain the token: replace it with "<token>" and re-raise
        as RuntimeError (requests puts the full URL, including the token, in its messages).

  handle(update: dict) -> None
        msg = update["message"] (ignore updates without one). uid = msg["from"]["id"], chat = msg["chat"]["id"].
        - allowed_ids empty (setup mode): sendMessage ONE text containing the sender's numeric ID and the
          words "TELEGRAM_ALLOWED_IDS", then return. Never call think/transcribe.
        - uid not in allowed_ids: log a warning with the uid and return. NO API calls at all.
        - text message: sendChatAction(chat_id, action="typing"), reply = think(text),
          send the reply as text (split into chunks <= MAX_LEN, preferring to split at spaces/newlines,
          losing no characters other than the whitespace at split points). No voice reply for text input.
        - voice message (msg["voice"]["file_id"]): sendChatAction typing; getFile(file_id=...) -> result["file_path"];
          download bytes with http.get(f"{API}/file/bot{token}/{file_path}").content;
          transcript = transcribe(bytes, "audio/ogg").strip().
            If empty: send one text "I couldn't make that out, sir." and return (no think).
            Else: send a text showing what was heard (must contain the transcript), reply = think(transcript),
            send the reply text FIRST, THEN the voice: speech(reply) ->
              ("ogg")  sendVoice(chat_id, files={"voice": ("reply.ogg", data, "audio/ogg")})
              ("mp3")  sendAudio(chat_id, files={"audio": ("reply.mp3", data, "audio/mpeg")})
              (None)   nothing.
            Any exception from speech or from sending the voice is logged, never raised.
        - anything else (photo, sticker...): one polite text, e.g. "I can only handle text and voice messages for now, sir."
        sendMessage params: chat_id, text.

  poll_once(offset) -> new offset
        updates = call("getUpdates", offset=offset, timeout=50, ...) with an HTTP timeout above 50 s.
        Handle each update inside its own try/except (log and continue). Return last update_id + 1,
        or the same offset if there were no updates.

  run() -> never returns
        call("deleteWebhook") once (a leftover webhook blocks polling), then loop poll_once forever.
        On any error: log it (mention "409 = another program is polling this bot" if 409 is in the text),
        sleep with backoff 5 s doubling to max 60 s, reset backoff after a successful poll.

Stdlib + requests only. Log with the logging module. Never log the token.
"""
import logging
import os
import threading
import time
import requests

API = "https://api.telegram.org"
MAX_LEN = 4096

def parse_allowed(value):
    if not value:
        return set()
    return {int(x.strip()) for x in value.split(",") if x.strip().isdigit()}

BOT = None   # the running bot, so other parts (reminders, alerts) can message you first


def send_all(text, silent=False):
    """Message every allowed user (silent = no notification sound). Does nothing if Telegram is off; never raises."""
    if BOT:
        BOT.send_all(text, silent)


def start(think, transcribe, speech, env=os.environ, look=None):
    global BOT
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        logging.info("Telegram disabled")
        return None
    allowed_ids = parse_allowed(env.get("TELEGRAM_ALLOWED_IDS", ""))
    if allowed_ids:
        logging.info(f"Telegram enabled for {len(allowed_ids)} allowed user(s).")
    else:
        logging.warning("Telegram in SETUP MODE: it only tells senders their ID. Set TELEGRAM_ALLOWED_IDS.")
    bot = Bot(token, allowed_ids, think, transcribe, speech, look=look)
    if allowed_ids:
        BOT = bot
    thread = threading.Thread(target=bot.run, daemon=True)
    thread.start()
    return thread

class Bot:
    def __init__(self, token, allowed_ids, think, transcribe, speech, http=requests, look=None):
        self.look = look   # look(image_bytes, mime, question) -> reply; None = photos not supported
        self.token = token
        self.allowed_ids = allowed_ids
        self.think = think
        self.transcribe = transcribe
        self.speech = speech
        self.http = http

    def _redact(self, e):
        # requests puts the full URL (with the token) in its error text; never let it reach a log
        return RuntimeError(str(e).replace(self.token, "<token>"))

    def call(self, method, files=None, http_timeout=30, **params):
        # http_timeout = how long WE wait; params (incl. Telegram's own "timeout") go to Telegram
        url = f"{API}/bot{self.token}/{method}"
        try:
            response = self.http.post(url, data=params, files=files, timeout=http_timeout)
            result = response.json()
        except Exception as e:
            raise self._redact(e) from None
        if not result.get("ok", True):
            raise RuntimeError(f"{method} failed: {result.get('error_code')} {result.get('description')}")
        return result

    def _download(self, file_path):
        try:
            return self.http.get(f"{API}/file/bot{self.token}/{file_path}", timeout=30).content
        except Exception as e:
            raise self._redact(e) from None

    def handle(self, update):
        if "message" not in update:
            return
        msg = update["message"]
        uid = msg["from"]["id"]
        chat = msg["chat"]["id"]

        if not self.allowed_ids:
            self.call("sendMessage", chat_id=chat, text=(
                f"Setup mode. Your Telegram ID is {uid}. Add TELEGRAM_ALLOWED_IDS={uid} "
                "to ~/jarvis/.env and restart Jarvis. Until then I answer no one."))
            return

        if uid not in self.allowed_ids:
            logging.warning(f"Unauthorized access attempt by user ID: {uid}")
            return

        if "text" in msg:
            self.call("sendChatAction", chat_id=chat, action="typing")
            reply = self.think(msg["text"])
            self._send_text_chunks(chat, reply)
        elif "voice" in msg:
            self.call("sendChatAction", chat_id=chat, action="typing")
            file_id = msg["voice"]["file_id"]
            file_path = self.call("getFile", file_id=file_id)["result"]["file_path"]
            voice_bytes = self._download(file_path)
            transcript = self.transcribe(voice_bytes, "audio/ogg").strip()
            if not transcript:
                self.call("sendMessage", chat_id=chat, text="I couldn't make that out, sir.")
                return
            self.call("sendMessage", chat_id=chat, text=f"I heard: {transcript}")
            reply = self.think(transcript)
            self._send_text_chunks(chat, reply)
            self._send_voice_reply(chat, reply)
        elif "photo" in msg and self.look:
            self.call("sendChatAction", chat_id=chat, action="typing")
            biggest = msg["photo"][-1]["file_id"]   # Telegram lists sizes smallest first
            file_path = self.call("getFile", file_id=biggest)["result"]["file_path"]
            reply = self.look(self._download(file_path), "image/jpeg", msg.get("caption") or "What is this?")
            self._send_text_chunks(chat, reply)
        else:
            self.call("sendMessage", chat_id=chat, text="I can only handle text, voice and photos for now, sir.")

    def send_all(self, text, silent=False):
        for uid in self.allowed_ids:   # a private chat's id is the user's id
            try:
                if silent:
                    self.call("sendMessage", chat_id=uid, text=text, disable_notification=True)
                else:
                    self._send_text_chunks(uid, text)
            except Exception as e:
                logging.error(f"Telegram send failed: {self._redact(e)}")

    def _send_text_chunks(self, chat_id, text):
        # Split at the last newline/space before MAX_LEN (keeps line breaks; hard cut if none)
        text = text.strip()
        while text:
            if len(text) <= MAX_LEN:
                chunk, text = text, ""
            else:
                cut = max(text.rfind("\n", 0, MAX_LEN), text.rfind(" ", 0, MAX_LEN))
                if cut <= 0:
                    cut = MAX_LEN
                chunk, text = text[:cut], text[cut:].lstrip()
            self.call("sendMessage", chat_id=chat_id, text=chunk)

    def _send_voice_reply(self, chat_id, text):
        try:
            voice_data, voice_type = self.speech(text)
            if voice_data is None:
                return
            if voice_type == "ogg":
                self.call("sendVoice", chat_id=chat_id, files={"voice": ("reply.ogg", voice_data, "audio/ogg")})
            elif voice_type == "mp3":
                self.call("sendAudio", chat_id=chat_id, files={"audio": ("reply.mp3", voice_data, "audio/mpeg")})
        except Exception as e:
            logging.error(f"Error sending voice reply: {e}")

    def poll_once(self, offset):
        # Long polling: Telegram holds the request up to 50 s until a message arrives,
        # so our HTTP wait must be longer than that.
        updates = self.call("getUpdates", http_timeout=60, offset=offset, timeout=50)["result"]
        for update in updates:
            try:
                self.handle(update)
            except Exception as e:
                logging.error(f"Telegram: error handling update: {e}")
        if updates:
            return updates[-1]["update_id"] + 1
        return offset

    def run(self, loops=None, sleep=time.sleep):
        # loops/sleep exist for the tests; in production run() never returns.
        offset, backoff, webhook_cleared = None, 5, False
        while loops is None or loops > 0:
            if loops is not None:
                loops -= 1
            try:
                if not webhook_cleared:
                    self.call("deleteWebhook")   # a leftover webhook blocks polling (409)
                    webhook_cleared = True
                offset = self.poll_once(offset)
                backoff = 5
            except Exception as e:
                hint = " (409 = another program is polling this bot)" if "409" in str(e) else ""
                logging.error(f"Telegram: {e}{hint}; retrying in {backoff}s")
                sleep(backoff)
                backoff = min(backoff * 2, 60)
