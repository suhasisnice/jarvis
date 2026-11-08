import pyaudio
import numpy as np
import logging
import smart_turn

# VAD: we use energy-based silence detection.
# If the audio volume stays below SILENCE_THRESHOLD for SILENCE_SECONDS, we stop.
SILENCE_THRESHOLD = 500   # RMS energy below this = silence
SILENCE_SECONDS   = 1.3   # fallback when Smart Turn can't load: fixed wait before we cut off
SHORT_SILENCE     = 0.6   # after this much silence, ask Smart Turn "have they finished?"
MAX_SILENCE       = 2.5   # if it says "still talking", wait this long before giving up
SAMPLE_RATE       = 16000
CHUNK             = 1280


def _flush(stream):
    """Drop audio buffered while Jarvis was speaking, so we don't record his own voice."""
    try:
        while stream.get_read_available() >= CHUNK:
            stream.read(CHUNK, exception_on_overflow=False)
    except Exception:
        pass


def record_until_silence(stream, wait_for_speech=None, is_finished=smart_turn.finished) -> np.ndarray:
    """
    Record from an open mic stream until the user stops talking; return it as one array.

    wait_for_speech: if set (seconds), wait that long for the user to START talking.
    If they don't, return an empty array. This powers follow-up mode — Jarvis keeps
    listening after a reply, but gives up gracefully if you've nothing more to say.
    None = start recording immediately (the first turn, right after the wake word).
    """
    _flush(stream)   # ignore the audio buffered while he was speaking

    frames = []
    silent_chunks = 0
    short = int(SHORT_SILENCE * SAMPLE_RATE / CHUNK)        # ~7 chunks
    limit = int(SILENCE_SECONDS * SAMPLE_RATE / CHUNK)      # ~16 chunks, until Smart Turn answers

    speech_started = wait_for_speech is None
    waited_chunks = 0
    max_wait = int((wait_for_speech or 0) * SAMPLE_RATE / CHUNK)

    logging.info("Listening..." if not speech_started else "Recording...")

    while True:
        try:
            chunk = np.frombuffer(stream.read(CHUNK, exception_on_overflow=False), dtype=np.int16)
        except Exception as e:
            logging.error(f"Failed to read chunk during recording: {e}")
            break

        rms = np.sqrt(np.mean(chunk.astype(np.float32) ** 2))

        if not speech_started:
            # Still waiting for the user to begin. Keep the first loud chunk when it comes.
            if rms >= SILENCE_THRESHOLD:
                speech_started = True
                frames.append(chunk)
            else:
                waited_chunks += 1
                if waited_chunks >= max_wait:
                    return np.array([], dtype=np.int16)   # nobody spoke — end the turn
            continue

        frames.append(chunk)
        if rms < SILENCE_THRESHOLD:
            silent_chunks += 1
        else:
            silent_chunks = 0
            limit = int(SILENCE_SECONDS * SAMPLE_RATE / CHUNK)   # new pause, new verdict

        if silent_chunks == short:
            verdict = is_finished(np.concatenate(frames))
            if verdict is not None:   # None = model unavailable: keep the fixed 1.3 s wait
                limit = short if verdict else int(MAX_SILENCE * SAMPLE_RATE / CHUNK)

        if silent_chunks >= limit:
            logging.info("Silence detected. Stopping recording.")
            break

    if not frames:
        return np.array([], dtype=np.int16)
    return np.concatenate(frames)


def _demo():
    """Self-check with a fake stream: no speech -> empty; speech then silence -> audio."""
    class FakeStream:
        def __init__(self, rms_sequence):
            # each entry = approx RMS for one chunk; build int16 chunks to match
            self.chunks = []
            for r in rms_sequence:
                self.chunks.append(np.full(CHUNK, int(r), dtype=np.int16).tobytes())
            self.i = 0
        def get_read_available(self): return 0
        def read(self, n, exception_on_overflow=True):
            if self.i >= len(self.chunks):
                return np.zeros(CHUNK, dtype=np.int16).tobytes()  # trailing silence
            c = self.chunks[self.i]; self.i += 1; return c

    none = lambda audio: None
    quiet = [0] * 40
    assert len(record_until_silence(FakeStream(quiet), wait_for_speech=0.5, is_finished=none)) == 0, "silence should give empty"

    loud = [2000] * 5 + [0] * 60   # talk, then go quiet
    n = lambda verdict: len(record_until_silence(FakeStream(loud), wait_for_speech=0.5, is_finished=lambda a: verdict)) // CHUNK
    done, unsure, talking = n(True), n(None), n(False)
    assert 5 < done < unsure < talking, (done, unsure, talking)   # done stops soonest, "still talking" waits longest
    assert done == 5 + int(SHORT_SILENCE * SAMPLE_RATE / CHUNK), done
    print("recorder self-check passed")


if __name__ == "__main__":
    _demo()
