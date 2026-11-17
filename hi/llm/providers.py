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
import logging
import threading
import urllib.request
from urllib.parse import urlparse

import ollama
from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama

import hi.config as config

log = logging.getLogger(__name__)

OLLAMA_PORT = 11434
# Labels our requests in a LlamaTop-style gateway dashboard; a plain Ollama ignores it.
APP_HEADERS = {"X-LlamaTop-App": "hi"}


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


def describe(mode: str | None = None) -> str:
    """Short human label for status lines."""
    return f"{mode or config.AI_MODE} {ollama_host(mode) or '(no url set)'}"


def signature(mode: str | None = None) -> str:
    """Changes whenever the mode or endpoint does — use in cache keys."""
    return f"{mode or config.AI_MODE}|{ollama_host(mode)}"


def configured_modes() -> list[str]:
    """The modes that can be tried, the active one first. Tailscale only counts once it has a URL."""
    modes = [config.AI_MODE] + [m for m in config.MODES if m != config.AI_MODE]
    return [m for m in modes if ollama_host(m)]


def friendly_error(e: Exception) -> str:
    """A provider error as a one-line message a user can act on."""
    return str(e) or type(e).__name__


def model_name(model: BaseChatModel) -> str:
    return getattr(model, "model", None) or model.model_name


def build_chat_model(name: str, *, thinking: bool = False, mode: str | None = None, **kwargs) -> BaseChatModel:
    """A chat model for `name` on `mode`'s provider (default: the active one).

    `thinking` asks for streamed reasoning (surfaced as
    `additional_kwargs["reasoning_content"]`). `kwargs` such as
    temperature/keep_alive pass through.
    """
    host = ollama_host(mode)
    if not host:
        raise RuntimeError("Tailscale Ollama URL not set — add it in settings.")
    if thinking:
        kwargs["reasoning"] = True
    return ChatOllama(model=name, base_url=host, client_kwargs={"headers": APP_HEADERS}, **kwargs)


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


class ModelUnavailable(RuntimeError):
    """The model isn't on the Ollama host (yet). The host itself is reachable."""


_available: set[tuple[str, str]] = set()
_pulling: set[tuple[str, str]] = set()
_pull_lock = threading.Lock()


def _pull(name: str, mode: str, host: str) -> None:
    try:
        for progress in ollama.Client(host=host, headers=APP_HEADERS).pull(name, stream=True):
            log.debug("pull %s: %s %s/%s", name, progress.status, progress.completed or "", progress.total or "")
        log.info("pulled model %s on %s", name, host)
    except Exception as e:  # boundary: a background download must never crash the process
        log.warning("pulling %s on %s failed: %s", name, host, e)
    finally:
        with _pull_lock:
            _pulling.discard((signature(mode), name))


def _start_pull(name: str, mode: str, host: str) -> bool:
    """Download `name` in the background. False if it is already being downloaded."""
    key = (signature(mode), name)
    with _pull_lock:
        if key in _pulling:
            return False
        _pulling.add(key)
    log.info("pulling model %s on %s in the background", name, host)
    threading.Thread(target=_pull, args=(name, mode, host), daemon=True, name=f"pull-{name}").start()
    return True


def ensure_available(name: str, mode: str | None = None) -> None:
    """Make sure `name` can be used under `mode` (default: the active one).

    Never downloads inside the caller's request. A missing model raises ModelUnavailable: on a
    local host a background pull is started so it works next time, on a tailscale box (someone
    else's machine) it must be pulled there. An unreachable host raises RuntimeError.
    """
    mode = mode or config.AI_MODE
    key = (signature(mode), name)
    if key in _available:
        return
    host = ollama_host(mode)
    try:
        names = list_models(mode=mode)
    except (OSError, ValueError) as e:
        raise RuntimeError(f"Can't reach Ollama ({describe(mode)}): {e}") from e
    if name not in names:
        if mode == "tailscale":
            raise ModelUnavailable(f"Model '{name}' isn't on {host} — pull it there, or pick another in settings.")
        started = _start_pull(name, mode, host)
        state = "is downloading in the background" if started else "is still downloading"
        raise ModelUnavailable(f"Model '{name}' isn't on {host} yet; it {state}. Try again shortly.")
    _available.add(key)
