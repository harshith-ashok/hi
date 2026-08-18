"""Voice input for the REPL's Ctrl-V binding: records from the mic until
the user stops talking, then transcribes with faster-whisper.

The Whisper model is loaded lazily (module-level cache, first use only) so
personas that never touch voice input don't pay its load cost.
"""

import numpy as np
import sounddevice as sd

from hi.config import WHISPER_MODEL

SAMPLE_RATE = 16_000
CHUNK_SECONDS = 0.1
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_SECONDS)

SPEECH_RMS_THRESHOLD = 0.02
SILENCE_SECONDS = 0.7
SILENCE_CHUNKS = int(SILENCE_SECONDS / CHUNK_SECONDS)

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return _model


def record_until_silence(max_seconds: float = 20.0) -> np.ndarray:
    """Record from the default mic until the user has spoken and then
    fallen silent for SILENCE_SECONDS, or max_seconds is reached."""
    chunks: list[np.ndarray] = []
    heard_speech = False
    silent_run = 0

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32") as stream:
        max_chunks = int(max_seconds / CHUNK_SECONDS)
        for _ in range(max_chunks):
            chunk, _ = stream.read(CHUNK_SAMPLES)
            chunk = chunk[:, 0]
            chunks.append(chunk)

            rms = float(np.sqrt(np.mean(np.square(chunk))))
            if rms >= SPEECH_RMS_THRESHOLD:
                heard_speech = True
                silent_run = 0
            elif heard_speech:
                silent_run += 1
                if silent_run >= SILENCE_CHUNKS:
                    break

    if not chunks:
        return np.zeros(0, dtype="float32")
    return np.concatenate(chunks)


def transcribe(audio: np.ndarray) -> str:
    if audio.size == 0:
        return ""
    segments, _ = _get_model().transcribe(audio, language="en")
    return " ".join(segment.text.strip() for segment in segments).strip()


def listen_and_transcribe(max_seconds: float = 20.0) -> str:
    return transcribe(record_until_silence(max_seconds))
