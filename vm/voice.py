"""
Phone voice (Phase 2): hear with Gemini, speak with the same Ryan voice as the laptop.

  transcribe(audio_bytes, mime) -> str     "" if no speech or Gemini unavailable
  mp3(text) -> bytes | None                 Ryan voice (needs: pip install edge-tts)
  ogg_opus(mp3_bytes) -> bytes | None       Telegram voice-bubble format (needs: pip install av)
  speech(text) -> (bytes, "ogg"|"mp3") | (None, None)

Both pip packages are optional: without them Jarvis still answers in text.
"""
import asyncio
import io
import logging

import brain

VOICE = "en-GB-RyanNeural"
RATE = "+8%"   # same as the laptop
PROMPT = ("Transcribe the speech in this audio exactly. Output only the spoken words, "
          "nothing else. If there is no speech, output nothing.")


def transcribe(audio: bytes, mime: str) -> str:
    """Gemini hears the audio directly (it accepts audio/ogg and audio/wav; tested 2026-11-02)."""
    if not audio or brain._client is None:
        return ""
    from google.genai import types
    for model in (brain.GEMINI_MODEL, brain.GEMINI_FALLBACK):
        try:
            r = brain._client.models.generate_content(
                model=model, contents=[types.Part.from_bytes(data=audio, mime_type=mime), PROMPT])
            return (r.text or "").strip()
        except Exception as e:
            logging.warning(f"Transcription with {model} failed ({e}).")
    return ""


def mp3(text: str):
    if not text.strip():
        return None
    try:
        import edge_tts
    except ImportError:
        logging.warning("edge-tts not installed; replying in text only (pip install edge-tts).")
        return None

    async def run():
        buf = bytearray()
        async for part in edge_tts.Communicate(text, VOICE, rate=RATE).stream():
            if part["type"] == "audio":
                buf.extend(part["data"])
        return bytes(buf)
    try:
        return asyncio.run(run()) or None
    except Exception as e:
        logging.warning(f"edge-tts failed ({e}).")
        return None


def ogg_opus(mp3_bytes: bytes):
    """MP3 -> OGG/Opus mono 48 kHz, what Telegram needs for a real voice bubble."""
    try:
        import av
    except ImportError:
        logging.warning("PyAV not installed; voice replies go as MP3 files (pip install av).")
        return None
    try:
        out_buf = io.BytesIO()
        with av.open(io.BytesIO(mp3_bytes)) as inp, av.open(out_buf, "w", format="ogg") as out:
            stream = out.add_stream("libopus", rate=48000)
            stream.layout = "mono"
            resampler = av.AudioResampler(format="s16", layout="mono", rate=48000)
            for frame in inp.decode(audio=0):
                for r in resampler.resample(frame):
                    for packet in stream.encode(r):
                        out.mux(packet)
            for packet in stream.encode(None):
                out.mux(packet)
        return out_buf.getvalue()
    except Exception as e:
        logging.warning(f"OGG/Opus conversion failed ({e}); sending MP3 instead.")
        return None


def speech(text: str):
    audio = mp3(text)
    if not audio:
        return None, None
    ogg = ogg_opus(audio)
    return (ogg, "ogg") if ogg else (audio, "mp3")
