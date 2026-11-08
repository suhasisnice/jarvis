import io
import asyncio
import logging
from functools import lru_cache

import av
import re
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pyaudio

import edge_tts
import ui

# edge-tts: Microsoft's online neural voices. Free, no API key, far more natural
# than the local Piper voice. Needs internet. Ryan is a polished British male.
VOICE = "en-GB-RyanNeural"
RATE_PCT = "+8%"   # a touch faster than default — conversational, less robotic
RATE = 24000       # edge neural voices are 24 kHz; we decode/resample to this
CHUNK = 1024       # samples per playback piece (~43 ms); orb updates once per piece

_audio = pyaudio.PyAudio()
_tts_pool = ThreadPoolExecutor(max_workers=2)   # makes the next sentence's voice while one plays

# Barge-in: while Jarvis speaks, watch the mic and stop if the user talks over him.
# BARGE_RMS is the knob — mic loudness that counts as "someone is talking". Raise it
# if his own voice through SPEAKERS keeps interrupting him; lower it on headphones.
# Calibrated 2026-11-02 from the log: his own voice reached the mic at 188-856, the user
# talking over him at 5415-8034. 1500 sits well between. 4-in-a-row missed real speech.
BARGE_RMS = 1500
BARGE_SUSTAIN = 2    # consecutive loud mic batches (~80 ms each) required
BARGE_GRACE = 6      # playback pieces (~250 ms) to ignore first, so the stream settles
BARGE_SPEECH = 0.5   # Silero speech probability needed too, so coughs/bangs/music don't count.
                     # Measured 2026-11-08: speech 0.99, noise and cough-like bursts 0.03-0.13.

_vad = None
def _is_speech(audio_int16) -> bool:
    """Silero VAD (bundled with faster-whisper) on the last ~0.25 s of mic audio."""
    global _vad
    try:
        if _vad is None:
            from faster_whisper.vad import get_vad_model
            _vad = get_vad_model()
        a = audio_int16[-4096:].astype(np.float32) / 32768
        a = a[: len(a) // 512 * 512]
        return len(a) > 0 and float(np.max(_vad(a))) > BARGE_SPEECH
    except Exception:
        return True   # VAD broken: fall back to loudness only, as before

_muted = False
def set_muted(value: bool) -> None:
    global _muted
    _muted = bool(value)
def is_muted() -> bool:
    return _muted


def _synth(text: str) -> bytes:
    """Run edge-tts (async) and return the full MP3 for `text`."""
    async def run():
        buf = bytearray()
        async for part in edge_tts.Communicate(text, VOICE, rate=RATE_PCT).stream():
            if part["type"] == "audio":
                buf.extend(part["data"])
        return bytes(buf)
    return asyncio.run(run())


def _to_pcm(mp3: bytes) -> np.ndarray:
    """Decode edge-tts MP3 to mono 16-bit PCM at RATE, as one int16 array."""
    container = av.open(io.BytesIO(mp3))
    resampler = av.AudioResampler(format="s16", layout="mono", rate=RATE)
    out = []
    for frame in container.decode(audio=0):
        for r in resampler.resample(frame):
            out.append(r.to_ndarray().reshape(-1))
    container.close()
    return np.concatenate(out) if out else np.array([], dtype=np.int16)


@lru_cache(maxsize=64)
def _pcm(text: str) -> np.ndarray:
    """Synth + decode, cached: fixed phrases ("Yes, sir?") play instantly after the first time."""
    return _to_pcm(_synth(text))


def prewarm(*phrases: str) -> None:
    """Synthesize stock phrases ahead of time so their first use has no delay."""
    for p in phrases:
        try:
            _pcm(p)
        except Exception as e:
            logging.warning(f"Prewarm failed for {p!r}: {e}")


def _mic_read(mic_stream):
    """Whatever the mic has buffered right now (int16 array), or None if no new audio arrived.

    None matters: the mic delivers audio in ~80 ms batches but we check every ~43 ms, so
    half the checks find nothing. Counting those as "quiet" reset the barge-in counter
    every other check, so it could never trigger.
    """
    try:
        avail = mic_stream.get_read_available()
        if not avail:
            return None
        data = np.frombuffer(mic_stream.read(avail, exception_on_overflow=False), dtype=np.int16)
        return data if len(data) else None
    except Exception:
        return None


def speak(text: str, mic_stream=None, is_speech=None) -> bool:
    """Speak text in the British neural voice, feeding loudness to the orb as it plays.

    If `mic_stream` is given, watch for the user talking over Jarvis (barge-in): on
    sustained speech, stop playback early and return True. Returns False otherwise.
    Does nothing (returns False) while muted.
    """
    if not text.strip() or _muted:
        return False
    interrupted = False
    try:
        # Each sentence's voice is made in the background, so he starts talking as soon as the
        # FIRST sentence is ready instead of waiting for the whole reply (~1 s sooner on long ones).
        jobs = [_tts_pool.submit(_pcm, part) for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part]
        if not len(jobs[0].result()):
            return False
        out = _audio.open(format=pyaudio.paInt16, channels=1, rate=RATE, output=True)
        ui.set_state("speaking", text)
        if mic_stream is not None:
            _mic_read(mic_stream)   # drain stale mic audio before we start watching
        is_speech = is_speech or _is_speech
        recent = np.zeros(0, dtype=np.int16)
        loud = 0
        peak = 0.0   # loudest mic reading while he spoke — logged so BARGE_RMS can be calibrated
        n = 0
        for job in jobs:
            pcm = job.result()
            for i in range(0, len(pcm), CHUNK):
                n += 1
                piece = pcm[i:i + CHUNK]
                loudness = np.sqrt(np.mean(piece.astype(np.float32) ** 2)) if len(piece) else 0.0
                ui.set_level(loudness / 6000)   # about 6000 = loud speech
                out.write(piece.tobytes())
                if mic_stream is not None and n > BARGE_GRACE:
                    data = _mic_read(mic_stream)
                    if data is None:
                        continue   # no new mic audio this piece — neither loud nor quiet
                    recent = np.concatenate([recent, data])[-4096:]
                    rms = float(np.sqrt(np.mean(data.astype(np.float32) ** 2)))
                    peak = max(peak, rms)
                    # loud AND sounds like a voice (his own echo is quiet; a cough isn't speech)
                    loud = loud + 1 if rms > BARGE_RMS and is_speech(recent) else 0
                    if loud >= BARGE_SUSTAIN:
                        interrupted = True
                        break
            if interrupted:
                break
        out.stop_stream()
        out.close()
        if mic_stream is not None:
            logging.info(f"Barge-in check: peak mic RMS {peak:.0f} (threshold {BARGE_RMS})")
        logging.info(("Interrupted while saying: " if interrupted else "Spoke: ") + repr(text))
    except Exception as e:
        logging.error(f"TTS failed: {e}")
    finally:
        ui.set_state("idle")
    return interrupted


def _demo():
    """Self-check for barge-in, with a fake mic that (like the real one) only has new
    audio on every other check. No sound is played."""
    global _audio, _pcm

    class FakeOut:
        def write(self, b): pass
        def stop_stream(self): pass
        def close(self): pass

    class FakeAudio:
        def open(self, **kw): return FakeOut()

    class FakeMic:
        def __init__(self, level): self.level, self.n = level, 0
        def get_read_available(self):
            self.n += 1
            return 1280 if self.n % 2 else 0          # audio only every other check
        def read(self, n, exception_on_overflow=False):
            return np.full(n, self.level, dtype=np.int16).tobytes()

    real_audio, real_pcm = _audio, _pcm
    _audio, _pcm = FakeAudio(), (lambda text: np.zeros(CHUNK * 60, dtype=np.int16))
    try:
        yes, no = (lambda a: True), (lambda a: False)
        assert speak("long reply", FakeMic(BARGE_RMS * 3), is_speech=yes) is True, "loud talking must interrupt"
        assert speak("long reply", FakeMic(BARGE_RMS // 3), is_speech=yes) is False, "quiet room must not interrupt"
        assert speak("long reply", FakeMic(BARGE_RMS * 3), is_speech=no) is False, "a loud cough must not interrupt"
    finally:
        _audio, _pcm = real_audio, real_pcm
    print("speaker barge-in self-check passed")


if __name__ == "__main__":
    _demo()
