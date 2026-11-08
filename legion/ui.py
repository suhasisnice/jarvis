"""
The orb window. A tiny local web server serves orb.html at http://127.0.0.1:7777/
and Jarvis's current state as JSON at /state. The orb asks for /state 20 times a second.
Other files call set_state() and set_level() to drive it.
"""
import json
import logging
import shutil
import subprocess
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 7777
ORB = Path(__file__).with_name("orb.html")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

_state = {"state": "idle", "level": 0.0, "text": ""}

# Mic mute: set = Jarvis ignores the mic, even "Hey Jarvis". Toggled by the orb's mic button
# (the only way back on, since he can't hear you while it's set) or the "mute my mic" voice command.
mic_muted = threading.Event()


def set_state(state, text=None):
    """state is one of: idle, listening, thinking, speaking."""
    _state["state"] = state
    if state != "speaking":
        _state["level"] = 0.0
    if text is not None:
        _state["text"] = text


def set_level(level):
    """Voice loudness while speaking, 0.0 to 1.0. Makes the orb spin faster."""
    # float(): loudness arrives as numpy float32, which json.dumps can't serialise
    _state["level"] = float(max(0.0, min(1.0, level)))


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # 20 requests a second would flood the log

    def do_GET(self):
        if self.path == "/state":
            body, kind = json.dumps({**_state, "mic_muted": mic_muted.is_set()}).encode(), "application/json"
        elif self.path == "/":
            body, kind = b'<!doctype html><meta charset="utf-8">' + ORB.read_bytes(), "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/mic":
            self.send_error(404)
            return
        mic_muted.clear() if mic_muted.is_set() else mic_muted.set()
        logging.info(f"Mic {'muted' if mic_muted.is_set() else 'on'} (orb button).")
        body = json.dumps({"mic_muted": mic_muted.is_set()}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start(open_window=True):
    # 127.0.0.1 = only this PC can see it, not the network
    server = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{PORT}/"
    logging.info(f"Orb at {url}")
    if not open_window:
        return
    # Edge "app mode" = a plain window with no tabs or address bar
    try:
        subprocess.Popen([shutil.which("msedge") or EDGE, f"--app={url}", "--window-size=420,520"])
    except OSError:
        webbrowser.open(url)
