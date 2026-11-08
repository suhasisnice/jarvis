import time
import os
import subprocess
import socket
import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

import memory

def set_reminder(minutes: float, text: str) -> str:
    """Set a timer or reminder; it is delivered by voice on the laptop and by Telegram. text = what to say when it fires, e.g. "your 2 minute timer is done" or "call mum". Convert 'at 7 pm' into minutes from now using the current time."""
    due = time.time() + minutes * 60
    memory.add_reminder(due, text)
    local_time = datetime.fromtimestamp(due).strftime("%H:%M")
    return f"Reminder set for {local_time}: {text}."

def list_reminders() -> str:
    """List the user's upcoming reminders and timers with their times."""
    reminders = memory.pending_reminders()
    if not reminders:
        return "You have no reminders."
    reminder_list = []
    for _, due, text in reminders:
        local_time = datetime.fromtimestamp(due).strftime("%H:%M")
        reminder_list.append(f"{local_time} {text}")
    return "; ".join(reminder_list)

def cancel_reminder(words: str) -> str:
    """Cancel a reminder or timer the user no longer wants. words = a few words from its text.
    To change a reminder, cancel it and set a new one."""
    n = memory.cancel_reminders(words)
    return f"Cancelled {n} reminder{'s' if n != 1 else ''}." if n else "I couldn't find that reminder."

def remember(fact: str) -> str:
    """Save a lasting fact about the user when they say remember/note that."""
    memory.add_fact(fact)
    return "I'll remember that."

def forget(fact: str) -> str:
    """Delete a saved fact about the user when they say forget that. fact = a few words from it."""
    n = memory.forget_fact(fact)
    return "Forgot it." if n else "I couldn't find that."

def server_status() -> str:
    """Health of the user's homelab server (the machine you run on): uptime, load, memory and disk use.
    Use for "is the server up", "how is the homelab", "how much disk is left"."""
    uptime = "unknown"
    load = "unknown"
    memory_usage = "unknown"
    disk_usage = "unknown"

    try:
        with open("/proc/uptime", "r") as f:
            uptime_seconds = float(f.readline().split()[0])
            uptime = f"{uptime_seconds / 3600:.1f} hours"
    except (FileNotFoundError, PermissionError):
        pass

    try:
        load = os.getloadavg()[0]
    except (AttributeError, OSError):
        pass

    try:
        with open("/proc/meminfo", "r") as f:
            meminfo = f.read()
            mem_total = int([line for line in meminfo.split("\n") if line.startswith("MemTotal")][0].split()[1])
            mem_available = int([line for line in meminfo.split("\n") if line.startswith("MemAvailable")][0].split()[1])
            memory_usage = f"{100 * (mem_total - mem_available) / mem_total:.1f}%"
    except (FileNotFoundError, PermissionError, IndexError):
        pass

    try:
        disk = os.statvfs("/")
        disk_total = disk.f_blocks * disk.f_frsize
        disk_available = disk.f_bavail * disk.f_frsize
        disk_usage = f"{100 * (disk_total - disk_available) / disk_total:.1f}%"
    except (AttributeError, OSError):
        pass

    return f"Uptime {uptime}, load {load}, memory {memory_usage} used, disk {disk_usage} used."

def laptop_status() -> str:
    """Whether the user's Lenovo Legion laptop is on (online) or off/asleep, checked by ping over Tailscale.
    Use for "is my laptop on", "status of my laptop"."""
    LAPTOP_IP = os.environ.get('LAPTOP_IP', '100.117.131.59')
    try:
        result = subprocess.run(['ping', '-c', '1', '-W', '2', LAPTOP_IP], capture_output=True)
        if result.returncode == 0:
            return "Your laptop is online."
        else:
            return "Your laptop is off or asleep."
    except Exception:
        return "Your laptop is off or asleep."


LAPTOP_MAC = os.environ.get("LAPTOP_MAC", "C8:53:09:5B:93:85")      # wired (PCIe) card: the one that wakes
WOL_BROADCAST = os.environ.get("WOL_BROADCAST", "192.168.68.255")


def wake_laptop() -> str:
    """Wake the user's laptop from sleep (Wake-on-LAN). Use when they ask to wake, turn on or start their laptop/PC."""
    try:
        packet = b"\xff" * 6 + bytes.fromhex(LAPTOP_MAC.replace(":", "").replace("-", "")) * 16
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(packet, (WOL_BROADCAST, 9))
            s.sendto(packet, ("255.255.255.255", 9))
        return "Wake signal sent to your laptop, sir. It takes about 20 seconds."
    except Exception:
        return "I couldn't send the wake signal."


def laptop_remote(action: str, target: str = "") -> str:
    """Do something on the user's laptop (Lenovo Legion) from here: use this for ANY request to open an app or
    site, change volume, play/pause music, lock or sleep their laptop/PC/computer. action is one of:
    open_app, open_website, volume (target = percent), mute, screenshot, lock, sleep, play (target = song),
    pause, next. Ask the user to confirm before sleep."""
    if "online" not in laptop_status():
        return "Your laptop is asleep, sir. Ask me to wake it first."
    import scheduler   # here, not at the top: scheduler is imported by the server first
    scheduler.inbox.push({"t": time.time(), "do": action, "target": str(target)})
    return "Done, sir. Your laptop will do it within a few seconds."


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.load(r)


def rain_chance(city: str):
    """Highest chance of rain (%) this hour and the next two, or None if unknown. Open-Meteo, no key."""
    try:
        place = _get_json("https://geocoding-api.open-meteo.com/v1/search?count=1&name=" + urllib.parse.quote(city))["results"][0]
        hourly = _get_json(f"https://api.open-meteo.com/v1/forecast?latitude={place['latitude']}&longitude={place['longitude']}"
                           "&hourly=precipitation_probability&timezone=auto&forecast_days=2")["hourly"]
        start = datetime.now().replace(minute=0, second=0, microsecond=0)
        window = [p for t, p in zip(hourly["time"], hourly["precipitation_probability"])
                  if p is not None and start <= datetime.fromisoformat(t) < start + timedelta(hours=3)]
        return int(max(window)) if window else None
    except Exception:
        return None
