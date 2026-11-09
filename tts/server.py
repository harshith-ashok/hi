"""TTS server for Hugging Face's gradium/phonon-40m-en (Phonon), on CUDA when there is a GPU.

Same request shape as Ollama's speech endpoint, so hi/tts_hf.py is a plain HTTP client:
    POST /v1/audio/speech  {"input": "...", "voice": "Easton"}  -> audio/wav (24 kHz mono)
    GET  /voices                                                -> {"voices": ["default", "Easton", ...]}
    GET  /health                                                -> {"device": "cuda"}
The model is gated: accept its terms on Hugging Face and pass HF_TOKEN. Weights are cached in /models.
The model's licence is CC BY-NC 4.0 (no commercial use). Voices come from the gradium/phonon-voices repo.
"""

import io
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import soundfile
import torch
from huggingface_hub import hf_hub_download
from safetensors.torch import load_file
from transformers import AutoProcessor, GradiumPhononTTSForConditionalGeneration

MODEL_ID = os.environ.get("TTS_HF_MODEL", "gradium/phonon-40m-en")
VOICES_REPO = "gradium/phonon-voices"
PORT = int(os.environ.get("TTS_PORT", 8780))
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
SAMPLE_RATE = 24000
MAX_CHUNK_TOKENS = 50  # long text is split into sentences and spoken one after the other

_lock = threading.Lock()  # one synthesis at a time
_voice_cache: dict[str, torch.Tensor] = {}


def _load():
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    model = GradiumPhononTTSForConditionalGeneration.from_pretrained(MODEL_ID).to(DEVICE).eval()
    return processor, model


def _english_voices() -> dict[str, str]:
    """name -> file in the voices repo, for the English voices."""
    path = hf_hub_download(VOICES_REPO, "voices.jsonl")
    rows = [json.loads(line) for line in open(path) if line.strip()]
    return {r["name"]: r["filename"] for r in rows if r.get("language") == "en"}


processor, model = _load()
VOICE_FILES = _english_voices()
DEFAULT_VOICE = "default"


def _voice(name: str) -> torch.Tensor:
    """The voice's latents as (num_frames, 512). 'default' is the model repo's own voice."""
    if name not in _voice_cache:
        if name in ("", DEFAULT_VOICE):
            path = hf_hub_download(MODEL_ID, "default-voice.safetensors")
        elif name in VOICE_FILES:
            path = hf_hub_download(VOICES_REPO, VOICE_FILES[name])
        else:
            raise ValueError(f"unknown voice '{name}'")
        _voice_cache[name] = load_file(path)["speaker_wavs"][0].T.float()
    return _voice_cache[name]


def _speak_chunk(text: str, voice: torch.Tensor) -> np.ndarray:
    conversation = [{"role": "user", "content": [{"type": "audio"}, {"type": "text", "text": text}]}]
    inputs = processor.apply_chat_template(
        conversation, tokenize=True, return_dict=True, add_generation_prompt=True,
        processor_kwargs={"audio_prompt_latents": [voice]},
    ).to(model.device)
    with torch.no_grad():
        outputs = model.generate(**inputs)
    audio = processor.decode(outputs.audio_latents, outputs.audio_latents_mask)
    audio = audio[0] if isinstance(audio, list) else audio
    return audio.float().cpu().numpy().reshape(-1)


def synthesize(text: str, voice_name: str) -> bytes:
    with _lock:
        voice = _voice(voice_name)
        chunks = [_speak_chunk(part, voice) for part in processor.split_text(text, MAX_CHUNK_TOKENS)]
    audio = np.concatenate(chunks) if chunks else np.zeros(1, dtype=np.float32)
    buf = io.BytesIO()
    soundfile.write(buf, audio, SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    def _json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/voices":
            self._json({"voices": [DEFAULT_VOICE, *sorted(VOICE_FILES)]})
        elif self.path == "/health":
            self._json({"device": DEVICE, "model": MODEL_ID})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        if self.path != "/v1/audio/speech":
            return self._json({"error": "not found"}, 404)
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            text = str(body.get("input") or "").strip()
            if not text:
                return self._json({"error": "missing input"}, 400)
            wav = synthesize(text, str(body.get("voice") or DEFAULT_VOICE))
        except Exception as e:  # noqa: BLE001 - report any failure to the caller as JSON
            return self._json({"error": str(e)}, 500)
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(wav)))
        self.end_headers()
        self.wfile.write(wav)

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    print(f"tts: {MODEL_ID} on {DEVICE}, port {PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
