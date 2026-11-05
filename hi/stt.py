"""Speech-to-text via a whisper.cpp `whisper-server` running natively on the
Mac (Metal). The backend may live in Docker, so it only talks HTTP to it:
`WHISPER_CPP_URL` (default: the host's port 8080).

Start the server with e.g.
    whisper-server -m ~/.hi/models/ggml-base.en.bin --port 8080
"""

from __future__ import annotations

import json
import urllib.request
import uuid

import hi.config as config


def _multipart(wav: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    fields = {"response_format": "json", "temperature": "0.0"}
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        for k, v in fields.items()
    ]
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
        "Content-Type: audio/wav\r\n\r\n".encode() + wav + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), boundary


def transcribe_wav(wav: bytes) -> str:
    """16 kHz mono WAV bytes in, transcript out. Raises RuntimeError with a
    readable message if the whisper.cpp server isn't reachable."""
    body, boundary = _multipart(wav)
    request = urllib.request.Request(
        f"{config.WHISPER_CPP_URL.rstrip('/')}/inference",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read()).get("text", "").strip()
    except OSError as e:
        raise RuntimeError(
            f"whisper.cpp server not reachable at {config.WHISPER_CPP_URL} — "
            "start `whisper-server` (brew install whisper-cpp)"
        ) from e
