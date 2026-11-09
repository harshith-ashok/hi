"""Neural TTS from Hugging Face (gradium/phonon-40m-en, Phonon) on a GPU, through the `tts` service in
docker-compose.yml (tts/server.py). For machines where Ollama's `phonon` has no CUDA build:
set TTS_BACKEND=huggingface. Plain HTTP, so it works from Docker or natively.
"""

from __future__ import annotations

import json
import urllib.request

import hi.config as config


def list_voices() -> list[str]:
    try:
        with urllib.request.urlopen(f"{config.TTS_URL.rstrip('/')}/voices", timeout=10) as response:
            return list(json.load(response).get("voices") or [])
    except OSError as e:
        raise RuntimeError(_unreachable(e)) from e


def synthesize_wav(text: str, voice: str | None = None) -> bytes:
    request = urllib.request.Request(
        f"{config.TTS_URL.rstrip('/')}/v1/audio/speech",
        data=json.dumps({"input": text, "voice": voice or config.TTS_VOICE}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:  # the first call downloads the model
            return response.read()
    except OSError as e:
        raise RuntimeError(_unreachable(e)) from e


def _unreachable(error: Exception) -> str:
    return f"can't reach the Hugging Face TTS service at {config.TTS_URL} — run `docker compose --profile gpu up -d tts` ({error})"
