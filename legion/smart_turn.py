"""
Smart Turn v3.2 (pipecat-ai, open source): listens to HOW you speak (tone, rhythm) and says
whether you've finished your thought or are just pausing. The recorder asks it after a short
silence, so Jarvis replies fast when you're done and waits when you're mid-sentence.

Measured 2026-11-07 on Ryan-voice samples: finished sentences 0.97-0.99; cut off mid-thought 0.01-0.12.
Runs on the CPU in a few milliseconds. Model (~8 MB) downloads once to the Hugging Face cache.
"""
import logging
import os

import numpy as np

THRESHOLD = 0.5      # above = finished. Raise if he still cuts you off, lower if he waits too long.
SECONDS = 8          # the model looks at the last 8 s of audio
RATE = 16000

_session = _features = None
_failed = False


def _load():
    global _session, _features, _failed
    try:
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        import onnxruntime
        from faster_whisper.feature_extractor import FeatureExtractor
        from huggingface_hub import hf_hub_download
        path = hf_hub_download("pipecat-ai/smart-turn-v3", "smart-turn-v3.2-cpu.onnx")
        _session = onnxruntime.InferenceSession(path, providers=["CPUExecutionProvider"])
        _features = FeatureExtractor(feature_size=80)
        logging.info("Smart Turn loaded.")
    except Exception as e:
        _failed = True
        logging.warning(f"Smart Turn unavailable ({e}); using the fixed silence timer.")


def _trim_tail(audio, keep=0.2, loud=500, chunk=1280):
    """Keep only 0.2 s of quiet after the last speech. The model expects that (Pipecat runs it after a
    0.2 s pause); with the recorder's 0.6 s quiet tail it said "finished" to everything (found 2026-11-08)."""
    rms = [np.sqrt(np.mean(audio[i:i + chunk].astype(np.float32) ** 2)) for i in range(0, len(audio), chunk)]
    spoken = [i for i, r in enumerate(rms) if r >= loud]
    return audio[:(spoken[-1] + 1) * chunk + int(keep * RATE)] if spoken else audio


def finished(audio_int16: np.ndarray):
    """True = they've finished, False = mid-thought, None = model unavailable (caller falls back)."""
    if _session is None and not _failed:
        _load()
    if _failed or not len(audio_int16):
        return None
    audio = _trim_tail(audio_int16)[-SECONDS * RATE:].astype(np.float32) / 32768
    audio = (audio - audio.mean()) / np.sqrt(audio.var() + 1e-7)               # same normalising as training
    audio = np.concatenate([np.zeros(SECONDS * RATE - len(audio), np.float32), audio])  # pad at the START
    mel = _features(audio)[:, :SECONDS * 100][None].astype(np.float32)          # 80 x 800
    p = float(_session.run(None, {"input_features": mel})[0][0][0])
    logging.info(f"Smart Turn: {p:.2f} ({'done' if p > THRESHOLD else 'still talking'})")
    return p > THRESHOLD


if __name__ == "__main__":
    speech, quiet = np.full(16000, 3000, np.int16), np.full(9600, 50, np.int16)
    assert len(_trim_tail(np.concatenate([speech, quiet]))) == 16640 + 3200   # cut to the chunk after speech + 0.2 s
    assert len(_trim_tail(quiet)) == len(quiet)                               # no speech: leave it alone
    print("smart_turn checks passed")
