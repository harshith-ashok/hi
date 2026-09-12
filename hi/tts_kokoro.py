"""Local, human-sounding TTS via Kokoro (hexgrad/Kokoro-82M) — replaces
`AVSpeechSynthesizer` as what the voice companion app actually speaks
with (per explicit request: "something that sounds actually like a
human, maybe even use kokoro"). Fully local after the one-time model
download (same category as faster-whisper/IndicTrans2's own weights),
consistent with this project's zero-runtime-network-call posture for
inference.

One cached `KPipeline`, built lazily on first use (loading it costs real
time — torch/spacy init — so this must not happen per call, and must not
happen at import time either, since not every process that imports this
module needs TTS).
"""

from __future__ import annotations

import io
import threading

import numpy as np
from scipy.io import wavfile

_pipeline = None
_lock = threading.Lock()

SAMPLE_RATE = 24000
DEFAULT_VOICE = "af_heart"


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        with _lock:
            if _pipeline is None:
                from kokoro import KPipeline

                _pipeline = KPipeline(lang_code="a")
    return _pipeline


def synthesize_wav(text: str, voice: str = DEFAULT_VOICE) -> bytes:
    """Synthesizes `text` and returns real 16-bit PCM WAV file bytes at
    Kokoro's native 24kHz output rate."""
    pipeline = _get_pipeline()
    chunks = [result.audio.numpy() for result in pipeline(text, voice=voice)]
    audio = np.concatenate(chunks) if chunks else np.zeros(1, dtype=np.float32)
    pcm16 = np.clip(audio, -1.0, 1.0)
    pcm16 = (pcm16 * 32767).astype(np.int16)
    buf = io.BytesIO()
    wavfile.write(buf, SAMPLE_RATE, pcm16)
    return buf.getvalue()
