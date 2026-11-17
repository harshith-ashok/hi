"""Text-to-image server for Z-Image-Turbo and FLUX.2 [klein] (Hugging Face diffusers), on CUDA or Apple MPS when there is one.

The OpenAI image API, so hi/imagegen.py is a plain HTTP client and so is any other OpenAI-compatible tool:
    POST /v1/images/generations  {"prompt", "size": "1024x1024", "seed"?, "model"?}  -> {"data": [{"b64_json": "<png>"}]}
    GET  /v1/models                                                                  -> {"data": [{"id": MODEL}]}
    GET  /health                                                                      -> {"ok": true, "model", "loaded", "device"}

The model loads on the first request (it takes a while and a lot of memory) and stays loaded. Requests run one at a time.
Settings, all optional environment variables: IMAGE_MODEL (default Tongyi-MAI/Z-Image-Turbo), IMAGE_PORT, IMAGE_DEVICE,
IMAGE_DTYPE, IMAGE_STEPS, IMAGE_GUIDANCE, IMAGE_OFFLOAD=1 (CPU offload, for cards with less memory), HF_TOKEN.
Z-Image-Turbo is Apache-2.0 and fits 16 GB. FLUX.2 [klein] 4B is Apache-2.0 and needs about 13 GB; its 9B sibling is
non-commercial. The per-model defaults below are what the model cards recommend; override them if a release changes.
"""

from __future__ import annotations

import base64
import io
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

PORT = int(os.environ.get("IMAGE_PORT", 8790))
MODEL = os.environ.get("IMAGE_MODEL", "Tongyi-MAI/Z-Image-Turbo")
MAX_SIDE = 1536
MIN_SIDE = 256
MULTIPLE = 16
MAX_REQUEST_BYTES = 20_000
MAX_PROMPT_CHARS = 4000

# model id fragment -> how to run it
FAMILIES = [
    {"match": "z-image", "pipeline": "ZImagePipeline", "steps": 9, "guidance": 0.0},  # 9 steps = 8 forwards, guidance must be 0
    {"match": "flux.2-klein", "pipeline": "Flux2KleinPipeline", "steps": 4, "guidance": 1.0},
    {"match": "flux2-klein", "pipeline": "Flux2KleinPipeline", "steps": 4, "guidance": 1.0},
]


def family(model_id: str) -> dict:
    lowered = model_id.lower()
    found = next((f for f in FAMILIES if f["match"] in lowered), {})
    # Explicit None checks, not `or`: a guidance of 0.0 is the right value for Z-Image-Turbo and is falsy.
    steps = os.environ.get("IMAGE_STEPS")
    guidance = os.environ.get("IMAGE_GUIDANCE")
    return {
        "pipeline": found.get("pipeline", "AutoPipelineForText2Image"),
        "steps": int(steps) if steps else found.get("steps", 25),
        "guidance": float(guidance) if guidance not in (None, "") else found.get("guidance", 4.0),
    }


class BadRequest(ValueError):
    """The request is not something we will run. The message is for the caller."""


def parse_size(size: Any) -> tuple[int, int]:
    """"1024x768" -> (1024, 768), checked and rounded to what the model needs."""
    try:
        width, height = (int(part) for part in str(size or "1024x1024").lower().split("x"))
    except ValueError:
        raise BadRequest(f"size must look like 1024x1024, got {size!r}") from None
    if not (MIN_SIDE <= width <= MAX_SIDE and MIN_SIDE <= height <= MAX_SIDE):
        raise BadRequest(f"each side must be between {MIN_SIDE} and {MAX_SIDE} pixels")
    return width // MULTIPLE * MULTIPLE, height // MULTIPLE * MULTIPLE


def pick_device() -> str:
    forced = os.environ.get("IMAGE_DEVICE")
    if forced:
        return forced
    import torch

    if torch.cuda.is_available():
        return "cuda"
    return "mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else "cpu"


def load_pipeline(model_id: str, device: str):
    """Build the diffusers pipeline for `model_id` (slow: downloads the weights the first time)."""
    import diffusers
    import torch

    spec = family(model_id)
    dtype_name = os.environ.get("IMAGE_DTYPE") or ("bfloat16" if device == "cuda" else "float16" if device == "mps" else "float32")
    dtype = getattr(torch, dtype_name)
    cls = getattr(diffusers, spec["pipeline"], None) or diffusers.AutoPipelineForText2Image
    pipe = cls.from_pretrained(model_id, torch_dtype=dtype)
    if device == "cuda" and os.environ.get("IMAGE_OFFLOAD") == "1":
        pipe.enable_model_cpu_offload()
    else:
        pipe.to(device)
    return pipe


def run_pipeline(pipe: Any, device: str, spec: dict, prompt: str, width: int, height: int, seed: int | None) -> Any:
    """Run the pipeline once and return the PIL image."""
    import torch

    generator = torch.Generator("cpu" if device == "mps" else device).manual_seed(seed if seed is not None else int(time.time() * 1000) % 2**31)
    return pipe(prompt=prompt, width=width, height=height, num_inference_steps=spec["steps"],
                guidance_scale=spec["guidance"], generator=generator).images[0]


class Generator:
    """Holds the loaded pipeline and runs one request at a time. `loader` and `runner` are injectable so tests need no GPU."""

    def __init__(self, model_id: str = MODEL, loader: Callable[[str, str], Any] = load_pipeline, device: Callable[[], str] = pick_device,
                 runner: Callable[..., Any] = run_pipeline):
        self.model_id, self._loader, self._device_fn, self._runner = model_id, loader, device, runner
        self.device = ""
        self._pipe: Any = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._pipe is not None

    def generate(self, prompt: str, width: int, height: int, seed: int | None = None) -> bytes:
        """A PNG of `prompt`. Raises BadRequest for an unusable prompt."""
        prompt = (prompt or "").strip()
        if not prompt:
            raise BadRequest("prompt is empty")
        if len(prompt) > MAX_PROMPT_CHARS:
            raise BadRequest(f"prompt is longer than {MAX_PROMPT_CHARS} characters")
        with self._lock:
            if self._pipe is None:
                self.device = self._device_fn()
                self._pipe = self._loader(self.model_id, self.device)
            image = self._runner(self._pipe, self.device, family(self.model_id), prompt, width, height, seed)
            out = io.BytesIO()
            image.save(out, format="PNG")
            return out.getvalue()


def handle(generator: Generator, method: str, path: str, body: bytes) -> tuple[int, dict]:
    """One request -> (status, JSON). Kept apart from the HTTP plumbing so it can be tested directly."""
    if method == "GET" and path == "/health":
        return 200, {"ok": True, "model": generator.model_id, "loaded": generator.loaded, "device": generator.device or "not loaded yet"}
    if method == "GET" and path == "/v1/models":
        return 200, {"data": [{"id": generator.model_id, "object": "model"}]}
    if method == "POST" and path == "/v1/images/generations":
        try:
            request = json.loads(body or b"{}")
            if not isinstance(request, dict):
                raise BadRequest("the body must be a JSON object")
            width, height = parse_size(request.get("size"))
            seed = request.get("seed")
            if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
                raise BadRequest("seed must be an integer")
            png = generator.generate(str(request.get("prompt", "")), width, height, seed)
        except (BadRequest, json.JSONDecodeError) as e:
            return 400, {"error": {"message": str(e)}}
        except Exception as e:  # boundary: a failed generation is an error for the caller, not a crashed server
            return 500, {"error": {"message": f"generation failed: {type(e).__name__}: {e}"}}
        return 200, {"created": int(time.time()), "data": [{"b64_json": base64.b64encode(png).decode(), "revised_prompt": request.get("prompt")}]}
    return 404, {"error": {"message": "not found"}}


def make_handler(generator: Generator):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002
            pass

        def _send(self, status: int, payload: dict) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            self._send(*handle(generator, "GET", self.path.split("?")[0], b""))

        def do_POST(self) -> None:
            size = int(self.headers.get("Content-Length") or 0)
            if size > MAX_REQUEST_BYTES:
                return self._send(413, {"error": {"message": "request too large"}})
            self._send(*handle(generator, "POST", self.path.split("?")[0], self.rfile.read(size)))

    return Handler


def main() -> None:
    generator = Generator()
    print(f"image server on :{PORT}, model {generator.model_id} (loads on the first request)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), make_handler(generator)).serve_forever()


if __name__ == "__main__":
    main()
