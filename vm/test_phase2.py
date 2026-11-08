"""Offline tests for Phase 2 (phone access). No network, no keys.

Run:  python test_phase2.py      (prints "phase2 tests passed")
"""
import io
import json
import wave

import telegram_bot as tb

TOKEN = "123456:SECRET-TOKEN-abc"
OWNER = 111
STRANGER = 999


class FakeResp:
    def __init__(self, payload=None, content=b""):
        self._payload = payload if payload is not None else {"ok": True, "result": True}
        self.content = content
        self.status_code = 200

    def json(self):
        return self._payload


class FakeHTTP:
    """Records every Bot API call. Routes by method name (the last part of the URL)."""

    def __init__(self, voice_bytes=b"OggS-fake-voice", updates=None, fail_with=None):
        self.calls = []          # (method, data, files)
        self.voice_bytes = voice_bytes
        self.updates = updates or []
        self.fail_with = fail_with

    def post(self, url, data=None, files=None, timeout=None):
        if self.fail_with:
            raise self.fail_with
        method = url.rsplit("/", 1)[1]
        self.calls.append((method, data or {}, files, timeout))
        if method == "getFile":
            return FakeResp({"ok": True, "result": {"file_path": "voice/file_1.oga"}})
        if method == "getUpdates":
            return FakeResp({"ok": True, "result": self.updates})
        return FakeResp()

    def get(self, url, timeout=None):
        self.calls.append(("download", {"url": url}, None, timeout))
        if self.voice_bytes is None:
            raise ConnectionError(f"Max retries exceeded with url: {url}")
        return FakeResp(content=self.voice_bytes)

    def methods(self):
        return [c[0] for c in self.calls]

    def sent_texts(self):
        return [c[1]["text"] for c in self.calls if c[0] == "sendMessage"]


def make_bot(allowed=(OWNER,), http=None, think=None, transcribe=None, speech=None):
    seen = {"think": [], "transcribe": [], "speech": []}

    def _think(text):
        seen["think"].append(text)
        return think(text) if think else f"Reply to: {text}"

    def _transcribe(data, mime):
        seen["transcribe"].append((data, mime))
        return transcribe(data, mime) if transcribe else "what is the weather"

    def _speech(text):
        seen["speech"].append(text)
        return speech(text) if speech else (b"OggS-reply", "ogg")

    bot = tb.Bot(TOKEN, set(allowed), _think, _transcribe, _speech, http=http or FakeHTTP())
    return bot, seen


def text_update(uid, text, update_id=1):
    return {"update_id": update_id, "message": {"from": {"id": uid}, "chat": {"id": uid}, "text": text}}


def voice_update(uid, update_id=1):
    return {"update_id": update_id,
            "message": {"from": {"id": uid}, "chat": {"id": uid}, "voice": {"file_id": "F1", "duration": 2}}}


def test_parse_allowed():
    assert tb.parse_allowed("111, 222 ,x,") == {111, 222}
    assert tb.parse_allowed("") == set()
    assert tb.parse_allowed(None) == set()


def test_setup_mode_only_reports_id():
    http = FakeHTTP()
    bot, seen = make_bot(allowed=(), http=http)
    bot.handle(text_update(STRANGER, "hello"))
    texts = http.sent_texts()
    assert len(texts) == 1 and str(STRANGER) in texts[0] and "TELEGRAM_ALLOWED_IDS" in texts[0]
    assert seen["think"] == [], "setup mode must not reach the brain"


def test_stranger_is_ignored():
    http = FakeHTTP()
    bot, seen = make_bot(http=http)
    bot.handle(text_update(STRANGER, "hello"))
    bot.handle(voice_update(STRANGER))
    assert http.calls == [], "strangers get no reply at all"
    assert seen["think"] == [] and seen["transcribe"] == []


def test_owner_text_gets_text_reply_without_voice():
    http = FakeHTTP()
    bot, seen = make_bot(http=http)
    bot.handle(text_update(OWNER, "what is 2 plus 2"))
    assert seen["think"] == ["what is 2 plus 2"]
    assert "sendChatAction" in http.methods()
    assert http.sent_texts() == ["Reply to: what is 2 plus 2"]
    assert "sendVoice" not in http.methods() and "sendAudio" not in http.methods()


def test_long_reply_is_split_under_limit():
    long = "word " * 2000     # 10,000 chars
    http = FakeHTTP()
    bot, _ = make_bot(http=http, think=lambda t: long)
    bot.handle(text_update(OWNER, "tell me a lot"))
    texts = http.sent_texts()
    assert len(texts) >= 3
    assert all(len(t) <= tb.MAX_LEN for t in texts)
    assert "".join(texts).replace(" ", "") == long.replace(" ", ""), "no text lost when splitting"


def test_owner_voice_note_full_flow():
    http = FakeHTTP(voice_bytes=b"OggS-voice-data")
    bot, seen = make_bot(http=http)
    bot.handle(voice_update(OWNER))
    m = http.methods()
    assert m.index("getFile") < m.index("download")
    assert seen["transcribe"] == [(b"OggS-voice-data", "audio/ogg")]
    assert seen["think"] == ["what is the weather"]
    texts = http.sent_texts()
    assert any("what is the weather" in t for t in texts), "show the user what was heard"
    assert texts[-1] == "Reply to: what is the weather"
    assert m.index("sendMessage") < m.index("sendVoice"), "text first, voice after"
    voice_call = [c for c in http.calls if c[0] == "sendVoice"][0]
    # requests-style multipart: files={"voice": (filename, bytes, mime)}
    assert voice_call[2]["voice"][1] == b"OggS-reply"
    assert voice_call[1]["chat_id"] == OWNER
    download = [c for c in http.calls if c[0] == "download"][0]
    assert "voice/file_1.oga" in download[1]["url"]


def test_voice_falls_back_to_mp3_then_text_only():
    http = FakeHTTP()
    bot, _ = make_bot(http=http, speech=lambda t: (b"ID3-mp3", "mp3"))
    bot.handle(voice_update(OWNER))
    assert "sendAudio" in http.methods() and "sendVoice" not in http.methods()

    http = FakeHTTP()
    bot, _ = make_bot(http=http, speech=lambda t: (None, None))
    bot.handle(voice_update(OWNER))
    assert "sendAudio" not in http.methods() and "sendVoice" not in http.methods()
    assert http.sent_texts()[-1] == "Reply to: what is the weather"

    def boom(t):
        raise RuntimeError("tts down")
    http = FakeHTTP()
    bot, _ = make_bot(http=http, speech=boom)
    bot.handle(voice_update(OWNER))      # must not raise
    assert http.sent_texts()[-1] == "Reply to: what is the weather", "text still sent when voice fails"


def test_unclear_voice_note_does_not_reach_brain():
    http = FakeHTTP()
    bot, seen = make_bot(http=http, transcribe=lambda d, m: "  ")
    bot.handle(voice_update(OWNER))
    assert seen["think"] == []
    assert len(http.sent_texts()) == 1


def test_token_never_leaks_in_errors():
    leaky = ConnectionError(f"Max retries exceeded with url: /bot{TOKEN}/getUpdates")
    bot, _ = make_bot(http=FakeHTTP(fail_with=leaky))
    try:
        bot.call("getUpdates")
        raise AssertionError("call should raise on network error")
    except AssertionError:
        raise
    except Exception as e:
        assert TOKEN not in str(e), "bot token must be redacted from error text"


def test_api_error_raises():
    class Http409(FakeHTTP):
        def post(self, url, data=None, files=None, timeout=None):
            return FakeResp({"ok": False, "error_code": 409, "description": "Conflict: terminated by other getUpdates request"})
    bot, _ = make_bot(http=Http409())
    try:
        bot.call("getUpdates")
        raise AssertionError("ok:false must raise")
    except AssertionError:
        raise
    except Exception as e:
        assert "409" in str(e)


def test_poll_once_advances_offset_and_survives_bad_update():
    http = FakeHTTP(updates=[text_update(OWNER, "boom", update_id=5), text_update(OWNER, "fine", update_id=6)])

    def think(text):
        if text == "boom":
            raise RuntimeError("brain exploded")
        return "ok"
    bot, _ = make_bot(http=http, think=think)
    new_offset = bot.poll_once(None)
    assert new_offset == 7
    assert "ok" in http.sent_texts(), "a crash on one message must not stop the next"


def test_unsupported_message_gets_polite_reply():
    http = FakeHTTP()
    bot, seen = make_bot(http=http)
    bot.handle({"update_id": 1, "message": {"from": {"id": OWNER}, "chat": {"id": OWNER}, "photo": [{}]}})
    assert len(http.sent_texts()) == 1 and seen["think"] == []


def test_long_polling_really_long_polls():
    http = FakeHTTP()
    bot, _ = make_bot(http=http)
    bot.poll_once(42)
    method, data, files, http_timeout = http.calls[0]
    assert method == "getUpdates" and data.get("offset") == 42
    assert data.get("timeout") == 50, "Telegram must be asked to hold the request (long poll)"
    assert http_timeout and http_timeout > 50, "our HTTP wait must outlast Telegram's"


def test_failed_voice_download_does_not_leak_token():
    bot, _ = make_bot(http=FakeHTTP(voice_bytes=None))
    try:
        bot.handle(voice_update(OWNER))
        raise AssertionError("download failure should raise")
    except AssertionError:
        raise
    except Exception as e:
        assert TOKEN not in str(e)
    dl = [c for c in bot.http.calls if c[0] == "download"][0]
    assert dl[3], "voice download must have a timeout"


def test_run_survives_network_down_at_start():
    class FlakyHTTP(FakeHTTP):
        def __init__(self):
            super().__init__()
            self.failures = 2

        def post(self, url, data=None, files=None, timeout=None):
            if self.failures:
                self.failures -= 1
                raise ConnectionError("network unreachable")
            return super().post(url, data, files, timeout)
    http, naps = FlakyHTTP(), []
    bot, _ = make_bot(http=http)
    bot.run(loops=4, sleep=naps.append)
    assert http.methods()[:2] == ["deleteWebhook", "getUpdates"], "retries deleteWebhook, then polls"
    assert naps == [5, 10], "backs off 5 s then 10 s"


def test_reply_keeps_line_breaks():
    http = FakeHTTP()
    bot, _ = make_bot(http=http, think=lambda t: "Line one.\nLine two.")
    bot.handle(text_update(OWNER, "two lines please"))
    assert http.sent_texts() == ["Line one.\nLine two."]


def _with_fake_modules(fn):
    """Run fn with brain/memory/tools/voice replaced by offline fakes, then restore them."""
    import sys
    import types
    fake = {name: types.ModuleType(name) for name in ("brain", "memory", "tools", "voice")}
    fake["brain"].think = lambda t: f"Reply to: {t}"
    fake["brain"]._client = None
    fake["brain"].GEMINI_MODEL = fake["brain"].GEMINI_FALLBACK = "fake-model"
    fake["memory"].init = lambda: None
    fake["tools"].ACTIVITY = ""
    fake["voice"].transcribe = lambda audio, mime: "hello jarvis" if audio.startswith(b"RIFF") else ""
    fake["voice"].mp3 = lambda text: b"ID3fake"
    fake["voice"].speech = lambda text: (None, None)
    saved = {k: sys.modules.get(k) for k in list(fake) + ["server"]}
    sys.modules.update(fake)
    sys.modules.pop("server", None)
    try:
        return fn()
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def test_server_voice_endpoints():
    import base64
    import threading
    import urllib.error
    import urllib.request

    def run():
        import server
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"

        def req(path, body=None, ctype=None):
            r = urllib.request.Request(base + path, data=body, headers={"Content-Type": ctype} if ctype else {})
            try:
                with urllib.request.urlopen(r, timeout=5) as resp:
                    return resp.status, resp.read()
            except urllib.error.HTTPError as e:
                return e.code, e.read()
        try:
            code, page = req("/voice")
            assert code == 200 and b"Hold the orb" in page, "phone page is served"

            code, body = req("/voice/turn", b"RIFF-fake-wav", "audio/wav")
            j = json.loads(body)
            assert code == 200 and j["transcript"] == "hello jarvis"
            assert j["reply"] == "Reply to: hello jarvis"
            assert base64.b64decode(j["audio"]) == b"ID3fake"

            code, body = req("/voice/turn", b"just-noise", "audio/wav")
            j = json.loads(body)
            assert code == 200 and j["transcript"] == "" and "couldn't" in j["reply"]

            server.MAX_AUDIO_BYTES = 10
            code, _ = req("/voice/turn", b"RIFF" + b"x" * 50, "audio/wav")
            assert code == 413, "oversized audio is refused"

            code, body = req("/ask", json.dumps({"message": "still there?"}).encode(), "application/json")
            assert code == 200 and json.loads(body)["reply"] == "Reply to: still there?", "laptop /ask unchanged"
            code, body = req("/status")
            assert code == 200 and json.loads(body) == {"activity": ""}
        finally:
            httpd.shutdown()
    _with_fake_modules(run)


def test_voice_speech_fallbacks():
    def run():
        import importlib
        import voice as v_fake  # noqa: F401  (the fake; reload the real one below)
        import sys
        sys.modules.pop("voice", None)
        real = importlib.import_module("voice")
        assert real.transcribe(b"", "audio/ogg") == "", "no audio -> empty"
        assert real.transcribe(b"RIFF", "audio/wav") == "", "no Gemini client -> empty, no crash"
        real.mp3 = lambda t: None
        assert real.speech("hi") == (None, None), "no TTS -> text only"
        real.mp3, real.ogg_opus = (lambda t: b"ID3"), (lambda b: None)
        assert real.speech("hi") == (b"ID3", "mp3"), "no converter -> MP3 fallback"
        real.ogg_opus = lambda b: b"OggS"
        assert real.speech("hi") == (b"OggS", "ogg")
        sys.modules.pop("voice", None)
    _with_fake_modules(run)


def test_start_without_token_is_disabled():
    assert tb.start(lambda t: t, lambda d, m: "", lambda t: (None, None), env={}) is None


def test_photo_and_send_all():
    seen = []
    bot, _ = make_bot()
    bot.look = lambda img, mime, q: seen.append((img, mime, q)) or "A cat, sir."
    bot.handle({"update_id": 9, "message": {"from": {"id": OWNER}, "chat": {"id": OWNER}, "caption": "what breed?",
                "photo": [{"file_id": "small"}, {"file_id": "big"}]}})
    assert seen == [(b"OggS-fake-voice", "image/jpeg", "what breed?")], seen
    assert [c[1]["file_id"] for c in bot.http.calls if c[0] == "getFile"] == ["big"]
    assert bot.http.sent_texts() == ["A cat, sir."]
    bot.http.calls.clear()
    bot.send_all("Reminder, sir: stretch.")
    assert [(c[1]["chat_id"], c[1]["text"]) for c in bot.http.calls] == [(OWNER, "Reminder, sir: stretch.")]
    bot.http.fail_with = ConnectionError(f"bot{TOKEN} down")
    bot.send_all("never raises")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("phase2 tests passed")
