"""Make a new picture from a description: `generate_image`.

It calls an OpenAI-compatible images endpoint (POST /v1/images/generations): the `imagegen` service in this repo
(Z-Image-Turbo or FLUX.2 klein through diffusers, on your own GPU) or any other server that speaks that API. The PNG is
saved under <vault>/hi/plots/ and shown in the chat like a chart (GET /plots/<name>.png).

With IMAGE_BACKEND=off the tool is not offered. With the service down it is hidden and /health shows `imagegen` down,
instead of a model calling a tool that is known to fail. Nothing leaves your machine unless you point IMAGE_URL at a
hosted API yourself.
"""

from __future__ import annotations

import base64
import re
from datetime import datetime

import httpx
from langchain_core.tools import tool

import hi.config as config
from hi.core import health
from hi.memory.vault import plots_dir

SIZES = ("512x512", "768x768", "1024x1024", "1024x768", "768x1024", "1280x720", "720x1280")
DEFAULT_SIZE = "1024x1024"
TIMEOUT_S = 300.0  # the first request loads the model, which takes minutes on a cold GPU
MAX_PROMPT_CHARS = 4000


class ImageError(RuntimeError):
    """Generation did not work; the message says why, for the model and the user."""


def enabled() -> bool:
    return config.IMAGE_BACKEND != "off"


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.IMAGE_API_KEY}"} if config.IMAGE_API_KEY else {}


def generate(prompt: str, size: str = DEFAULT_SIZE, seed: int | None = None, client: httpx.Client | None = None) -> bytes:
    """A PNG for `prompt`. Raises ImageError with a reason on any failure."""
    prompt = " ".join(prompt.split())
    if not prompt:
        raise ImageError("the prompt is empty")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ImageError(f"the prompt is longer than {MAX_PROMPT_CHARS} characters")
    if not enabled():
        raise ImageError("image generation is switched off (IMAGE_BACKEND=off)")
    body: dict = {"model": config.IMAGE_MODEL, "prompt": prompt, "size": size if size in SIZES else DEFAULT_SIZE,
                  "n": 1, "response_format": "b64_json"}
    if seed is not None:
        body["seed"] = int(seed)
    url = f"{config.image_url()}/v1/images/generations"
    try:
        response = (client or httpx).post(url, json=body, headers=_headers(), timeout=TIMEOUT_S)
    except httpx.HTTPError as e:
        health.mark_down("imagegen", e)
        raise ImageError(f"the image service at {config.image_url()} is not reachable ({type(e).__name__}). "
                         "Start it with `docker compose --profile gpu up -d imagegen`.") from e
    if response.status_code != 200:
        detail = _error_text(response)
        if response.status_code >= 500 or response.status_code in (401, 403, 404):
            health.mark_down("imagegen", f"{response.status_code}: {detail}")
        raise ImageError(f"the image service refused the request ({response.status_code}): {detail}")
    health.mark_ok("imagegen")
    try:
        png = base64.b64decode(response.json()["data"][0]["b64_json"])
    except (KeyError, IndexError, ValueError, TypeError):
        raise ImageError("the image service answered, but not with an image") from None
    if not png.startswith(b"\x89PNG"):
        raise ImageError("the image service did not return a PNG")
    return png


def _error_text(response: httpx.Response) -> str:
    try:
        return str(response.json()["error"]["message"])[:300]
    except (KeyError, ValueError, TypeError):
        return response.text[:300] or "no details"


def save(png: bytes, prompt: str, now: datetime | None = None) -> str:
    """Write the PNG next to the charts and return its URL path, /plots/<name>.png."""
    now = now or datetime.now()
    slug = re.sub(r"[^\w-]+", "-", prompt.lower()).strip("-")[:36] or "image"
    name = f"image-{slug}-{now:%H%M%S}.png"
    plots_dir().mkdir(parents=True, exist_ok=True)
    (plots_dir() / name).write_bytes(png)
    return f"/plots/{name}"


@tool
def generate_image(prompt: str, size: str = DEFAULT_SIZE, seed: int | None = None) -> str:
    """Create a NEW image from a description and show it to the user: illustrations, logos, posters, wallpapers, concept
    art, product mockups, icons. (To show an existing real photo of a person or place, use find_image instead.) It can
    take from several seconds to over a minute, and the first image after a quiet spell is slower.

    Write the prompt as a vivid description in English: the subject, style or medium, lighting, composition and mood
    ("a lighthouse on a cliff at dawn, watercolour, soft mist, wide shot"). Text you want in the image goes in quotes.
    Use the same seed to get the same picture again; omit it for a new one.

    Args:
        prompt: What to draw.
        size: One of 512x512, 768x768, 1024x1024, 1024x768, 768x1024, 1280x720, 720x1280.
        seed: Optional whole number for a repeatable result.
    """
    try:
        png = generate(prompt, size, seed)
    except ImageError as e:
        return f"No image was made: {e}"
    path = save(png, prompt)
    return f"Image made and already displayed to the user in the UI (do not embed or link it): {path}"
