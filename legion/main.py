import ctypes
import queue
import time
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import pyaudio
import requests

from wake_word import listen_for_wake_word
from recorder import record_until_silence
from transcriber import transcribe
from speaker import speak, set_muted, prewarm
import actions
import ui

FOLLOW_UP_SECONDS = 12.0   # how long he keeps listening after a reply before needing "Hey Jarvis"
_pool = ThreadPoolExecutor(max_workers=1)

# Spoken commands that silence / un-silence Jarvis's voice (he still listens).
MUTE_CMDS = {"mute", "mute yourself", "be quiet", "silence", "shut up", "stop talking"}
UNMUTE_CMDS = {"unmute", "speak", "you can talk", "talk to me", "resume"}
MIC_OFF_CMDS = {"mute my mic", "mute the mic", "mute mic", "mute microphone", "mute my microphone",
                "turn off the mic", "stop listening"}   # back on only via the orb's mic button

# Configure logging — every log line will show time + level + message
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("jarvis.log", encoding="utf-8")],   # file: so slow turns can be checked later
)

VM_URL = "http://100.95.197.12:8000"  # VM Tailscale IP
SAMPLE_RATE = 16000
CHUNK = 1280

def brain_thread(wake_queue, audio_stream, busy):
    """
    Thread 2: waits for a WAKE signal, records what you say,
    transcribes it, sends it to the VM brain, speaks the reply.
    Loops forever. `busy` is set for the whole turn so the wake-word
    listener ignores Jarvis's own voice.
    """
    logging.info("Brain thread ready.")
    while True:
        # Block here until Thread 1 drops "WAKE" in the queue
        signal = wake_queue.get()
        if signal != "WAKE":
            continue

        busy.set()   # from here until the turn ends, don't listen for the wake word
        try:
            speak("Yes, sir?")
            ui.set_state("listening", "Listening…")
            audio = record_until_silence(audio_stream)   # first turn: no timeout

            # Follow-up mode: after each reply, keep listening a few seconds so you
            # can just keep talking. A silence ends the conversation and we go back
            # to waiting for the wake word.
            while True:
                ui.set_state("thinking", "")
                text = transcribe(audio)
                # Empty = noise that VAD threw away. Don't end the chat over it, just keep listening.
                if text:
                    handle_turn(text, audio_stream)
                if ui.mic_muted.is_set():
                    break   # mic muted mid-chat: stop listening until it's back on

                ui.set_state("listening", "")
                audio = record_until_silence(audio_stream, wait_for_speech=FOLLOW_UP_SECONDS)
                if not len(audio):
                    break   # real silence for the whole window — back to waiting for "Hey Jarvis"
        finally:
            # Drop any wakes that slipped in while he was talking, then listen again
            while not wake_queue.empty():
                wake_queue.get_nowait()
            busy.clear()

def handle_turn(text: str, audio_stream) -> None:
    _last_turn[0] = time.time()
    logging.info(f"You said: {text!r}")
    cmd = text.lower().strip(" .,!?")
    if cmd in MUTE_CMDS:
        speak("Very well, sir.", audio_stream)   # last words before going quiet
        set_muted(True)
    elif cmd in MIC_OFF_CMDS:
        speak("Microphone off, sir. Tap the mic button to turn it back on.", audio_stream)
        ui.mic_muted.set()
    elif cmd in UNMUTE_CMDS:
        set_muted(False)
        speak("At your service, sir.", audio_stream)
    else:
        ui.set_state("thinking", text)
        # Ask in the background. While waiting, check what the brain is doing and narrate
        # it once per tool ("Checking the weather in Paris, sir.") — silent for plain chat.
        job = _pool.submit(ask_brain, text)
        said = ""
        while True:
            try:
                reply, todo = job.result(timeout=0.5)
                break
            except FutureTimeout:
                activity = brain_activity()
                if activity and activity != said:
                    speak(activity, audio_stream)
                    said = activity
        for action in todo:   # the brain's "hands": open apps, volume, lock...
            if action.get("do") == "look":   # "what's on my screen?": show him, answer from what he sees
                reply = see_screen(text)
                continue
            if action.get("do") == "find":   # the search result IS the answer ("Found Resume v3.pdf, sir.")
                reply = actions.run(action)
                continue
            logging.info(f"Action {action}: {actions.run(action)}")
        # speak() returns True on barge-in; either way the next record catches what they say.
        speak(reply, audio_stream)

def see_screen(question: str) -> str:
    try:
        r = requests.post(f"{VM_URL}/see", params={"q": question}, data=actions.capture_screen(),
                          headers={"Content-Type": "image/jpeg"}, timeout=40)
        r.raise_for_status()
        return r.json().get("reply", "I have no response, sir.")
    except Exception as e:
        logging.error(f"Screen look failed: {e}")
        return "I couldn't see your screen, sir."

_last_turn = [0.0]   # when you last talked to Jarvis (voice counts as "at the laptop" too)

class _LastInput(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

def idle_seconds() -> float:
    """Seconds since you last touched the keyboard/mouse OR talked to Jarvis."""
    info = _LastInput(cbSize=ctypes.sizeof(_LastInput))
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    keyboard = (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000
    return min(keyboard, time.time() - _last_turn[0])

def notify_thread(busy):
    """
    Thread 3: Jarvis speaking first. Every 3 s, picks up reminders and alerts from the brain
    and says them when he isn't mid-conversation; warns if the homelab stops answering.
    """
    misses, down, pending = 0, False, []
    while True:
        try:
            data = requests.get(f"{VM_URL}/notify", params={"idle": int(idle_seconds())}, timeout=3).json()
            pending += data.get("notes", [])
            for action in data.get("actions", []):   # sent from your phone ("open Chrome on my laptop")
                if action.get("do") not in ("look", "find"):
                    logging.info(f"Remote action {action}: {actions.run(action)}")
            if down:
                pending.append("The homelab is back online, sir.")
            misses, down = 0, False
        except Exception:
            misses += 1
            if misses == 3:   # ~10 s of silence from the brain
                down = True
                pending.append("Sir, I've lost contact with the homelab.")
        if pending and not busy.is_set():
            busy.set()   # keeps the wake word from hearing him
            try:
                for note in pending:
                    ui.set_state("speaking", note)
                    speak(note)
            finally:
                pending.clear()
                ui.set_state("idle", "")
                busy.clear()
        time.sleep(3)

def brain_activity() -> str:
    """What the brain is doing right now (a tool in progress), or "" if nothing/unreachable."""
    try:
        return requests.get(f"{VM_URL}/status", timeout=1).json().get("activity", "")
    except Exception:
        return ""

def ask_brain(text: str) -> tuple[str, list]:
    """
    Sends transcribed text to the VM over HTTP and returns (reply, actions to run here).
    Falls back to a local error message if the VM is unreachable.
    """
    try:
        response = requests.post(
            f"{VM_URL}/ask",
            json={"message": text, "source": "laptop"},
            timeout=30   # must exceed the brain's worst case: 10s Gemini + 10s fallback
                         # Gemini + Ollama, or slow replies trip this first and look like an error
        )
        response.raise_for_status()
        data = response.json()
        return data.get("reply", "I have no response, sir."), data.get("actions", [])
    except requests.exceptions.ConnectionError:
        logging.error("Cannot reach VM brain.")
        return "I can't reach my brain right now, sir. Check the server.", []
    except Exception as e:
        logging.error(f"Brain request failed: {e}")
        return "Something went wrong on my end, sir.", []

def main():
    logging.info("Jarvis starting up...")
    ui.start()

    # Shared queue between the two threads
    wake_queue = queue.Queue()
    # Set while Jarvis is speaking/recording so he doesn't wake on his own voice
    speaking = threading.Event()

    # Open one mic stream shared by both wake word detection and recording
    audio = pyaudio.PyAudio()
    stream = audio.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK
    )

    # Thread 1: always listening for the wake word
    t1 = threading.Thread(
        target=listen_for_wake_word,
        args=(wake_queue, speaking, ui.mic_muted),
        daemon=True   # dies automatically when main program exits
    )

    # Thread 2: waits for wake signal, records, transcribes, thinks, speaks
    t2 = threading.Thread(
        target=brain_thread,
        args=(wake_queue, stream, speaking),
        daemon=True
    )

    # Synthesize stock phrases now so they play instantly later
    threading.Thread(
        target=prewarm,
        args=("Yes, sir?", "Very well, sir.", "At your service, sir."),
        daemon=True,
    ).start()

    # Greet with the gate held so his own greeting can't trigger a wake
    speaking.set()
    # Load the fast-lane model onto the GPU now and keep it there (a cold load takes ~8 s)
    threading.Thread(target=lambda: requests.post("http://localhost:11434/api/generate",
                     json={"model": "qwen3.5:4b", "keep_alive": -1}, timeout=60), daemon=True).start()
    t1.start()
    t2.start()
    threading.Thread(target=notify_thread, args=(speaking,), daemon=True).start()   # Thread 3
    speak("Jarvis online. Good to see you, sir.")
    speaking.clear()
    logging.info("Jarvis ready.")

    # Keep main thread alive — both worker threads run in the background
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        logging.info("Shutting down.")
        stream.stop_stream()
        stream.close()
        audio.terminate()

if __name__ == "__main__":
    main()
