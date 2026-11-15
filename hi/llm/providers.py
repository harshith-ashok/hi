"""The AI layer: the only module that knows which provider is behind a model.

Modes (`config.AI_MODE`):
  local       Ollama on this machine            -> config.OLLAMA_HOST
  tailscale   Ollama on another box via tailnet -> config.TAILSCALE_OLLAMA_URL

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


def ollama_host(mode: str | None = None) -> str:
    """The Ollama endpoint for `mode` ('' when tailscale has no URL yet)."""
    mode = mode or config.AI_MODE
    if mode == "tailscale":
        return normalize_url(config.TAILSCALE_OLLAMA_URL)
    if mode == "local":
        return normalize_url(config.OLLAMA_HOST)
    return ""


def describe() -> str:
    """Short human label for status lines."""
    return f"{config.AI_MODE} {ollama_host() or '(no url set)'}"


def signature() -> str:
    """Changes whenever the mode or endpoint does — use in cache keys."""
    return f"{config.AI_MODE}|{ollama_host()}"


def friendly_error(e: Exception) -> str:
    """A provider error as a one-line message a user can act on."""
    return str(e) or type(e).__name__


def model_name(model: BaseChatModel) -> str:
    return getattr(model, "model", None) or model.model_name


def build_chat_model(name: str, *, thinking: bool = False, **kwargs) -> BaseChatModel:
    """A chat model for `name` on the active provider.

    `thinking` asks for streamed reasoning (surfaced as
    `additional_kwargs["reasoning_content"]`). `kwargs` such as
    temperature/keep_alive pass through.
    """
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
    """
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
