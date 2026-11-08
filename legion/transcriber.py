import os
import numpy as np
import logging
from faster_whisper import WhisperModel

# CTranslate2 loads cuBLAS/cuDNN via plain LoadLibrary, which only searches PATH —
# so put the pip-shipped CUDA DLLs on PATH before the model loads, or GPU transcribe
# dies with "cublas64_12.dll not found". Harmless no-op if the wheels aren't installed.
def _add_cuda_dlls():
    try:
        import nvidia.cublas, nvidia.cudnn
        dirs = [os.path.join(list(p.__path__)[0], "bin") for p in (nvidia.cublas, nvidia.cudnn)]
        os.environ["PATH"] = os.pathsep.join(dirs) + os.pathsep + os.environ["PATH"]
    except Exception:
        pass

# Load once at startup — loading a model is slow, you don't want to do it per request.
# "small" on the GPU: more accurate than "base" and still sub-second per utterance.
_model = None

def _get_model():
    global _model
    if _model is None:
        _add_cuda_dlls()
        try:
            # small.en: English-only, more accurate on English than multilingual "small"
            _model = WhisperModel("small.en", device="cuda", compute_type="float16")
            logging.info("Whisper model loaded on GPU (small.en/float16).")
        except Exception as e:
            # No GPU / missing CUDA libs → fall back to the CPU model so Jarvis still hears.
            logging.warning(f"GPU model unavailable ({e}); falling back to CPU base/int8.")
            try:
                _model = WhisperModel("base", device="cpu", compute_type="int8")
                logging.info("Whisper model loaded on CPU.")
            except Exception as e2:
                logging.error(f"Failed to load Whisper model: {e2}")
    return _model

def transcribe(audio: np.ndarray) -> str:
    """
    Takes a numpy array of audio (from recorder.py) and returns the spoken text.

    How it works:
    - Whisper expects float32 audio normalised between -1.0 and 1.0.
    - We recorded int16 (values up to 32768), so we divide to normalise.
    - Whisper returns segments — chunks of text with timestamps.
    - We join them all into one string and return it.
    """
    model = _get_model()
    if model is None:
        return ""

    if len(audio) == 0:
        return ""

    # Convert int16 → float32, normalise to -1.0 … 1.0
    audio_float = audio.astype(np.float32) / 32768.0

    try:
        # vad_filter: Silero VAD drops non-speech before decoding. Without it, Whisper
        # hallucinates text ("Thank you.") on silence/room noise, which kept follow-up
        # mode alive in a loop. With it, silence transcribes to "" and the turn ends.
        segments, _ = model.transcribe(audio_float, language="en", vad_filter=True)
        text = " ".join(segment.text.strip() for segment in segments)
        logging.info(f"Transcribed: {text!r}")
        return text.strip()
    except Exception as e:
        logging.error(f"Transcription failed: {e}")
        return ""
