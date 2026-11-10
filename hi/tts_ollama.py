"""Neural TTS through Ollama's speech endpoint (model: `phonon`, Gradium's
on-device TTS — `ollama pull phonon`). Works from Docker too: the backend just
talks HTTP to the host's Ollama (`OLLAMA_HOST`).

Ollama streams the WAV with placeholder (0xFFFFFFFF) sizes in its header, which
some players refuse; `_fix_wav_sizes` rewrites them once the body is complete.
"""

from __future__ import annotations

import json
import struct
import urllib.request

import hi.config as config


def _fix_wav_sizes(wav: bytes) -> bytes:
    if wav[:4] != b"RIFF" or wav[36:40] != b"data":
        return wav
    return wav[:4] + struct.pack("<I", len(wav) - 8) + wav[8:40] + struct.pack("<I", len(wav) - 44) + wav[44:]


def list_voices() -> list[str]:
    """Voices the TTS model offers (Ollama's /api/show lists them)."""
    request = urllib.request.Request(
        f"{config.TTS_OLLAMA_HOST.rstrip('/')}/api/show",
        data=json.dumps({"model": config.TTS_MODEL}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return list(json.load(response).get("voices") or [])
    except OSError as e:
        raise RuntimeError(f"can't reach Ollama at {config.TTS_OLLAMA_HOST}: {e}") from e


def synthesize_wav(text: str, voice: str | None = None) -> bytes:
    request = urllib.request.Request(
        f"{config.TTS_OLLAMA_HOST.rstrip('/')}/v1/audio/speech",
        data=json.dumps({"model": config.TTS_MODEL, "input": text, "voice": voice or config.TTS_VOICE}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return _fix_wav_sizes(response.read())
    except OSError as e:
        raise RuntimeError(f"Ollama TTS failed at {config.TTS_OLLAMA_HOST} — is `{config.TTS_MODEL}` pulled? ({e})") from e
