"""Picks the TTS backend from config.TTS_BACKEND: "ollama" (phonon, the default) or
"huggingface" (Phonon from Hugging Face on a CUDA GPU, hi/tts_hf.py). Both return WAV bytes and a voice list.
"""

from __future__ import annotations

import hi.config as config


def _backend():
    if config.TTS_BACKEND == "huggingface":
        from hi import tts_hf

        return tts_hf
    from hi import tts_ollama

    return tts_ollama


def synthesize_wav(text: str, voice: str | None = None) -> bytes:
    return _backend().synthesize_wav(text, voice)


def list_voices() -> list[str]:
    return _backend().list_voices()
