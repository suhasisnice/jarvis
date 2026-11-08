import ctypes
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Tuple, Union

# Virtual key codes used in tests (imported by test_actions)
DOWN, UP, MUTE, WIN, PRTSC = 0xAE, 0xAF, 0xAD, 0x5B, 0x2C

# ----------------------------------------------------------------------
# Helper mappings
# ----------------------------------------------------------------------
_ALIAS_MAP = {
    "vs code": "code",
    "vscode": "code",
    "visual studio code": "code",
    "google chrome": "chrome",
    "file explorer": "explorer",
    "calculator": "calc",
    "edge": "msedge",
}


def _normalize_app_name(name: str) -> str:
    """Return the canonical executable name for a given app string."""
    lowered = name.strip().lower()
    return _ALIAS_MAP.get(lowered, lowered)


def capture_screen() -> bytes:
    """Screenshot of the whole screen as JPEG bytes, via Windows' own .NET (no extra packages)."""
    import tempfile
    path = os.path.join(tempfile.gettempdir(), "jarvis_screen.jpg")
    script = ("Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
              "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen; "
              "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height; "
              "[System.Drawing.Graphics]::FromImage($bmp).CopyFromScreen($b.Left,$b.Top,0,0,$bmp.Size); "
              f"$bmp.Save('{path}',[System.Drawing.Imaging.ImageFormat]::Jpeg)")
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, timeout=15,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(path, "rb") as f:
        return f.read()


_HOME = os.path.expanduser("~")
SEARCH_ROOTS = [p for p in (os.path.join(_HOME, d) for d in ("Desktop", "Documents", "Downloads",
                os.path.join("OneDrive", "Desktop"), os.path.join("OneDrive", "Documents"))) if os.path.isdir(p)]
_SKIP = {"node_modules", "__pycache__", "venv", "site-packages", "AppData"}
_OPENABLE = (".pdf", ".docx", ".doc", ".txt", ".md", ".pptx", ".xlsx", ".png", ".jpg", ".jpeg")


def find_files(words, roots, days=None, limit=5):
    """Files whose NAME contains every word, newest first. Skips hidden and tooling folders."""
    want = words.lower().split()
    cutoff = time.time() - days * 86400 if days else 0
    hits = []
    for root in roots:
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _SKIP]   # don't descend
            for name in files:
                if all(w in name.lower() for w in want):
                    path = os.path.join(folder, name)
                    try:
                        mtime = os.path.getmtime(path)
                    except OSError:
                        continue
                    if mtime >= cutoff:
                        hits.append((mtime, path))
    return [p for _, p in sorted(hits, reverse=True)[:limit]]


def _find(target, dry):
    words, _, days = target.partition("|")
    days = int(days) if days.strip().isdigit() else None
    pick = lambda hits: [f for f in hits if f.lower().endswith(_OPENABLE)][:5] or hits[:5]   # documents beat code files
    found = pick(find_files(words, SEARCH_ROOTS, days, limit=200))
    note = ""
    if not found and days:   # "this week" but the file is older: newest match is still the useful answer
        found = pick(find_files(words, SEARCH_ROOTS, limit=200))
        note = f"Nothing from the last {days} days, but "
    if not found:
        return "I couldn't find that file, sir."
    if not dry and found[0].lower().endswith(_OPENABLE):
        os.startfile(found[0])   # documents and pictures only, never programs
    more = f" There are {len(found) - 1} more like it." if len(found) > 1 else ""
    if note:
        return f"{note}the newest is {os.path.basename(found[0])}, sir.{more}"
    return f"Found {os.path.basename(found[0])}, sir.{more}"


# ----------------------------------------------------------------------
# Planning
# ----------------------------------------------------------------------
def plan(action: Dict[str, Any]) -> Tuple[str, Union[str, List[int], None]]:
    """
    Convert a high‑level action dict into a low‑level Windows instruction.

    Returns a tuple (verb, argument) where verb is one of:
        "start", "keys", "hotkey", "lock", "sleep"
    and argument is the data required for that verb.

    Raises:
        ValueError – if the input dict is malformed or contains an unknown
        command.
    """
    if not isinstance(action, dict):
        raise ValueError("action must be a dict")

    do = action.get("do")
    if not isinstance(do, str):
        raise ValueError("missing or invalid 'do' field")

    # ------------------- open_app -------------------
    if do == "open_app":
        target = action.get("target")
        if not isinstance(target, str) or not target.strip():
            raise ValueError("open_app requires a non‑empty 'target'")
        exe = _normalize_app_name(target)
        # Plain names only: | & ^ < > would let cmd run a second, hidden command
        if not re.fullmatch(r"[a-z0-9 ._+-]+", exe):
            raise ValueError(f"unsafe app name {exe!r}")
        return ("start", exe)

    # ------------------- open_website -------------------
    if do == "open_website":
        target = action.get("target")
        if not isinstance(target, str) or not target.strip():
            raise ValueError("open_website requires a non‑empty 'target'")
        url = target.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            url = "https://" + url
        return ("url", url)

    # ------------------- volume -------------------
    if do == "volume":
        target = action.get("target")
        if not isinstance(target, str) or not target.isdigit():
            raise ValueError("volume target must be a numeric string")
        vol = int(target)
        vol = max(0, min(100, vol))          # clamp to [0,100]
        down_presses = [DOWN] * 50          # bring volume to 0%
        up_presses = [UP] * (vol // 2)      # raise to desired level
        return ("keys", down_presses + up_presses)

    # ------------------- mute -------------------
    if do == "mute":
        return ("keys", [MUTE])

    # ------------------- screenshot -------------------
    if do == "screenshot":
        return ("hotkey", [WIN, PRTSC])

    # ------------------- find -------------------
    if do == "find":
        target = action.get("target")
        if not isinstance(target, str) or not target.strip():
            raise ValueError("find requires a non-empty 'target'")
        return ("find", target.strip())

    # ------------------- lock -------------------
    if do == "lock":
        return ("lock", None)

    # ------------------- sleep -------------------
    if do == "sleep":
        return ("sleep", None)

    # ------------------- play -------------------
    if do == "play":
        target = action.get("target")
        if not isinstance(target, str) or not target.strip():
            raise ValueError("play requires a non-empty 'target'")
        return ("play", target.strip())

    # ------------------- pause -------------------
    if do == "pause":
        return ("keys", [0xB3])

    # ------------------- next -------------------
    if do == "next":
        return ("keys", [0xB0])

    # Unknown command
    raise ValueError(f"unknown action '{do}'")

def first_video(html: str) -> str | None:
    """
    Extract the first video ID from a YouTube results page and return the video URL.

    Args:
        html: The HTML content of a YouTube results page.

    Returns:
        The URL of the first video found, or None if no video is found.
    """
    match = re.search(r'"videoId":"([A-Za-z0-9_-]{11})"', html)
    if match:
        video_id = match.group(1)
        return f"https://www.youtube.com/watch?v={video_id}"
    return None

# ----------------------------------------------------------------------
# Execution helpers
# ----------------------------------------------------------------------
def _exec_start(arg: str) -> None:
    """Launch an application or URL via the Windows start command."""
    subprocess.Popen(["cmd", "/c", "start", "", arg], shell=False)


def _exec_keys(vk_list: List[int]) -> None:
    """Press and release each virtual‑key code in order."""
    for vk in vk_list:
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)   # key down
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)   # key up


def _exec_hotkey(vk_list: List[int]) -> None:
    """Press all keys, then release them in reverse order."""
    for vk in vk_list:
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)   # down
    for vk in reversed(vk_list):
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)   # up


def _exec_lock() -> None:
    ctypes.windll.user32.LockWorkStation()


def _exec_sleep() -> None:
    # Use PowerShell to invoke the .NET method that suspends the system.
    cmd = [
        "powershell",
        "-Command",
        "Add-Type -AssemblyName System.Windows.Forms; "
        "[System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $false)",
    ]
    subprocess.run(cmd, shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ----------------------------------------------------------------------
# Public run function
# ----------------------------------------------------------------------
def run(action: Dict[str, Any], dry: bool = False) -> str:
    """
    Execute (or simulate) a planned action.

    If *dry* is True, no side‑effects occur; a short descriptive sentence is
    returned instead.  Any exception raised while planning results in a polite
    failure message.
    """
    try:
        verb, arg = plan(action)
    except Exception:
        return "I couldn't do that, sir."

    if verb == "find":   # only reads the disk, so dry mode can really search
        try:
            return _find(arg, dry)
        except Exception:
            return "I couldn't search for that, sir."

    # Dry‑run description
    if dry:
        if isinstance(arg, list):
            arg_repr = f"{len(arg)} keys"
        else:
            arg_repr = str(arg) if arg is not None else ""
        if verb == "play":
            return f"Would play {arg_repr}"
        return f"Would {verb} {arg_repr}".strip()

    # Real execution
    try:
        if verb == "url":
            os.startfile(arg)                    # browser opens it directly, no cmd parsing
        elif verb == "start":
            _exec_start(arg)                     # type: ignore[arg-type]
        elif verb == "keys":
            _exec_keys(arg)                      # type: ignore[arg-type]
        elif verb == "hotkey":
            _exec_hotkey(arg)                    # type: ignore[arg-type]
        elif verb == "lock":
            _exec_lock()
        elif verb == "sleep":
            _exec_sleep()
        elif verb == "play":
            url = None
            if not dry:
                search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(arg)}"
                req = urllib.request.Request(
                    search_url,
                    headers={'User-Agent': 'Mozilla/5.0'},
                )
                with urllib.request.urlopen(req, timeout=10) as response:
                    html = response.read().decode('utf-8', errors='ignore')
                    url = first_video(html)
            if url is None:
                return "I couldn't find that song, sir."
            os.startfile(url)
        else:
            # Should never happen because plan validates verbs
            raise RuntimeError(f"Unsupported verb {verb}")
    except Exception:
        return "I couldn't do that, sir."

    return "Done, sir."
