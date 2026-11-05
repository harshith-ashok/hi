"""The AI layer: the only module that knows which provider is behind a model.

Modes (`config.AI_MODE`):
  local       Ollama on this machine            -> config.OLLAMA_HOST
  tailscale   Ollama on another box via tailnet -> config.TAILSCALE_OLLAMA_URL
  openrouter  OpenRouter's hosted API           -> config.OPENROUTER_API_KEY

Everything else asks this module for a chat model, a model list, or an
availability check, and reads `signature()` for cache keys so a mode/host/key
change naturally builds fresh clients.
"""

from __future__ import annotations

import json
import urllib.request
from urllib.parse import urlparse

import ollama
from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama

import hi.config as config

OLLAMA_PORT = 11434
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_REASONING = {"effort": "low"}  # keeps answers quick; models that can't reason ignore it


def normalize_url(url: str) -> str:
    """`my-pc` / `100.64.0.5` / `my-pc.tailnet.ts.net:11434` -> a full http URL."""
    url = url.strip().rstrip("/")
    if not url:
        return ""
    if "://" not in url:
        url = f"http://{url}"
    if urlparse(url).port is None:
        url = f"{url}:{OLLAMA_PORT}"
    return url


def is_openrouter(mode: str | None = None) -> bool:
    return (mode or config.AI_MODE) == "openrouter"


def ollama_host(mode: str | None = None) -> str:
    """The Ollama endpoint for `mode` ('' for openrouter / unset tailscale)."""
    mode = mode or config.AI_MODE
    if mode == "tailscale":
        return normalize_url(config.TAILSCALE_OLLAMA_URL)
    if mode == "local":
        return normalize_url(config.OLLAMA_HOST)
    return ""


def describe() -> str:
    """Short human label for status lines."""
    if is_openrouter():
        return "openrouter"
    return f"{config.AI_MODE} {ollama_host() or '(no url set)'}"


def signature() -> str:
    """Changes whenever the mode, endpoint or key does — use in cache keys."""
    key = config.OPENROUTER_API_KEY
    return f"{config.AI_MODE}|{ollama_host()}|{hash(key) if key else ''}"


def friendly_error(e: Exception) -> str:
    """A provider error as a one-line message a user can act on."""
    text = str(e) or type(e).__name__
    if "Missing Authentication header" in text or "No cookie auth" in text or "User not found" in text:
        return "OpenRouter rejected the API key — check it in settings."
    return text


def model_name(model: BaseChatModel) -> str:
    return getattr(model, "model", None) or model.model_name  # ChatOllama / ChatOpenRouter


def build_chat_model(name: str, *, thinking: bool = False, **kwargs) -> BaseChatModel:
    """A chat model for `name` on the active provider.

    `thinking` asks for streamed reasoning (surfaced as
    `additional_kwargs["reasoning_content"]` by both integrations). `kwargs`
    such as temperature/keep_alive pass through; Ollama-only ones are dropped
    for OpenRouter.
    """
    if is_openrouter():
        from langchain_openrouter import ChatOpenRouter

        if not config.OPENROUTER_API_KEY:
            raise RuntimeError("OpenRouter API key not set — add it in settings.")
        kwargs.pop("keep_alive", None)
        return ChatOpenRouter(
            model=name,
            openrouter_api_key=config.OPENROUTER_API_KEY,
            reasoning=OPENROUTER_REASONING if thinking else None,
            **kwargs,
        )

    host = ollama_host()
    if not host:
        raise RuntimeError("Tailscale Ollama URL not set — add it in settings.")
    if thinking:
        kwargs["reasoning"] = True
    return ChatOllama(model=name, base_url=host, **kwargs)


def list_models(mode: str | None = None, host: str | None = None, timeout: float = 5.0) -> list[str]:
    """Model names available under `mode` (default: active). `host` overrides
    the Ollama endpoint, so the settings screen can test a URL before saving.
    Raises OSError/ValueError when unreachable."""
    mode = mode or config.AI_MODE
    if is_openrouter(mode):
        request = urllib.request.Request(f"{OPENROUTER_BASE}/models")
        if config.OPENROUTER_API_KEY:
            request.add_header("Authorization", f"Bearer {config.OPENROUTER_API_KEY}")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return sorted(m["id"] for m in json.load(response)["data"])

    url = normalize_url(host) if host else ollama_host(mode)
    if not url:
        raise ValueError("no URL set")
    with urllib.request.urlopen(f"{url}/api/tags", timeout=timeout) as response:
        return sorted(m["name"] for m in json.load(response)["models"])


_available: set[tuple[str, str]] = set()


def ensure_available(name: str) -> None:
    """Make sure `name` can be used under the active mode.

    local: pulled on demand. tailscale: must already exist on the remote box
    (we don't start multi-GB downloads on someone else's machine).
    openrouter: nothing to do — the API validates the slug on first call.
    """
    if is_openrouter():
        return
    key = (signature(), name)
    if key in _available:
        return
    host = ollama_host()
    try:
        names = list_models()
    except (OSError, ValueError) as e:
        raise RuntimeError(f"Can't reach Ollama ({describe()}): {e}") from e
    if name not in names:
        if config.AI_MODE == "tailscale":
            raise RuntimeError(f"Model '{name}' isn't on {host} — pull it there, or pick another in settings.")
        print(f"Pulling model '{name}'... this may take a while.")
        try:
            for progress in ollama.Client(host=host).pull(name, stream=True):
                print(f"{progress.status} {progress.completed or ''}/{progress.total or ''}", flush=True)
        except Exception as e:
            raise RuntimeError(f"Failed to pull model '{name}' on {host}: {e}") from e
    _available.add(key)
