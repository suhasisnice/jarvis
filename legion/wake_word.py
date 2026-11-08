import pyaudio
from openwakeword.model import Model
import logging
import numpy as np

def listen_for_wake_word(queue, busy, muted=None, threshold=0.6):
    # muted: ui.mic_muted. While set, same as busy: keep reading, never detect.
    # busy: a threading.Event set while Jarvis is talking/recording. We keep
    # reading the mic so it doesn't overflow, but skip detection — otherwise
    # Jarvis hears his own "Yes, sir?" and wakes himself in a loop.
    try:
        model = Model(wakeword_models=["hey_jarvis"])
    except Exception as e:
        logging.error(f"Model failed to load: {e}")
        return

    try:
        audio = pyaudio.PyAudio()
        stream = audio.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1280)
    except Exception as e:
        logging.error(f"Mic failed to open: {e}")
        return

    while True:
        try:
            chunk = np.frombuffer(stream.read(1280), dtype=np.int16)
        except Exception as e:
            logging.error(f"Failed to read audio chunk: {e}")
            continue

        if busy.is_set() or (muted is not None and muted.is_set()):
            model.reset()   # drop his own voice so it can't trigger when we resume
            continue

        score = model.predict(chunk)
        for k, v in score.items():
            if v > threshold:
                logging.info("Wake word detected.")
                queue.put("WAKE")
