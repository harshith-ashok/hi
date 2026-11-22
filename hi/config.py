"""Reads ~/.hi/.env for user-configurable settings: the Obsidian vault path
and the Ollama model used by each persona. Missing file or missing keys fall
back to sensible defaults, so a fresh install works with no .env at all.
"""

import os
import re
from pathlib import Path

ENV_PATH = Path.home() / ".hi" / ".env"

DEFAULT_MODEL = "gpt-oss:120b-cloud"

_ESCAPE_RE = re.compile(r"\\(.)")


def _parse_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        else:
            value = _ESCAPE_RE.sub(r"\1", value)
        env[key] = value
    return env


# Layers, lowest to highest: real environment variables, the host's own credentials in
# ~/.hi/.env (docker-compose.yml mounts it read-only here), then this
# machine's ~/.hi/.env (inside Docker: settings saved from the UI).
HOST_ENV_PATH = Path("/run/hi-host.env")
# Only credentials come from the host file: paths and addresses in it (VAULT_PATH,
# OLLAMA_HOST, ...) are right for the Mac and wrong inside the container.
HOST_ENV_KEYS = (
    "GITHUB_PERSONAL_ACCESS_TOKEN", "N8N_MCP_URL", "N8N_MCP_TOKEN",
    "TAILSCALE_OLLAMA_URL", "HOST_BRIDGE_TOKEN", "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET",
    "TTS_BACKEND", "AI_MODE", "IMAGE_API_KEY",
)
_host_env = {k: v for k, v in _parse_env(HOST_ENV_PATH).items() if k in HOST_ENV_KEYS}
_env = {**os.environ, **_host_env, **_parse_env(ENV_PATH)}

# --- AI layer -----------------------------------------------------------
# Two ways to reach a model (see hi/llm.py for what each one does):
#   local       Ollama on this machine (OLLAMA_HOST)
#   tailscale   Ollama on another machine over your tailnet (TAILSCALE_OLLAMA_URL)
MODES = ("local", "tailscale")
AI_MODE = _env.get("AI_MODE") or "local"
if AI_MODE not in MODES:
    if AI_MODE == "openrouter":  # removed; an old saved setting must not break startup
        print("[config] AI_MODE=openrouter is no longer supported; using local.", flush=True)
    AI_MODE = "local"

OLLAMA_HOST = _env.get("OLLAMA_HOST") or "http://127.0.0.1:11434"
TAILSCALE_OLLAMA_URL = _env.get("TAILSCALE_OLLAMA_URL") or ""

# Model names differ per mode (each box has its own models), so each mode
# keeps its own set in ~/.hi/.env under a prefix. The unprefixed names below
# (SONNET_MODEL, ...) are always the *active* mode's values — everything else
# in the codebase reads those and never needs to know about modes.
#
# Haiku runs on every router turn and sonnet on most answers; opus is the
# heaviest tier. Ollama defaults are cloud variants (a local 8B model measured
# 30-85s per call on this machine).
MODEL_ROLES = (
    "HAIKU_MODEL", "SONNET_MODEL", "OPUS_MODEL",
    "VISION_MODEL",
)
_MODE_PREFIX = {"local": "", "tailscale": "TAILSCALE_"}
_OLLAMA_DEFAULTS = {
    "HAIKU_MODEL": "gpt-oss:20b-cloud",
    "SONNET_MODEL": DEFAULT_MODEL,
    "OPUS_MODEL": "nemotron-3-ultra:cloud",
    "VISION_MODEL": "gemma4:31b-cloud",
}
# The tailscale box is the RTX PRO 4000 laptop (16GB VRAM): all local models, no cloud. Measured there:
# gemma4:e4b (6.5GB, fits fully on the GPU) does ~250 tok/s and ~0.1s tool calls, so it serves every role and
# stays resident. gpt-oss:20b (14GB) spills ~20% to CPU (~11 tok/s) and evicts gemma while loaded, so it is
# only the opus tier, used for big tasks. Voice (phonon) runs on the Mac, not here.
_TAILSCALE_DEFAULTS = {
    "HAIKU_MODEL": "gemma4:e4b",
    "SONNET_MODEL": "gemma4:e4b",
    "OPUS_MODEL": "gpt-oss:20b",
    "VISION_MODEL": "gemma4:e4b",
}


def env_key(role: str, mode: str) -> str:
    return _MODE_PREFIX[mode] + role


def model_for(role: str, mode: str | None = None) -> str:
    """`role`'s model name under `mode` (default: the active mode)."""
    mode = mode or AI_MODE
    defaults = _TAILSCALE_DEFAULTS if mode == "tailscale" else _OLLAMA_DEFAULTS
    return _env.get(env_key(role, mode)) or defaults[role]


def apply_mode() -> None:
    """Point the unprefixed model globals at the active mode's values."""
    for role in MODEL_ROLES:
        globals()[role] = model_for(role)


apply_mode()

# Self-hosted models stay loaded forever (Ollama's keep_alive=-1); hosted/cloud ones just get a long TTL.
KEEP_ALIVE: int | str = -1 if AI_MODE == "tailscale" else "30m"

# Always-on screen context (hi/context/daemon.py): extra app names it must never read, comma separated.
CONTEXT_DENYLIST = {a.strip().lower() for a in (_env.get("CONTEXT_DENYLIST") or "").split(",") if a.strip()}

VAULT_PATH = Path(_env.get("VAULT_PATH", str(Path.home() / ".hi" / "vault")))
WHISPER_MODEL = _env.get("WHISPER_MODEL", "base.en")
# Learning from your use, written to the vault (hi/memory.py, hi/reflection_agent.py). "off" disables.
MEMORY_EXTRACTION = (_env.get("MEMORY_EXTRACTION") or "on").lower() != "off"
REFLECTION = (_env.get("REFLECTION") or "on").lower() != "off"
# Text-to-speech: an Ollama speech model (hi/tts_ollama.py), `ollama pull phonon`.
# Phonon has no CUDA build, so voice always uses the Mac's own Ollama, never the tailscale box.
TTS_OLLAMA_HOST = _env.get("TTS_OLLAMA_HOST") or OLLAMA_HOST
TTS_MODEL = _env.get("TTS_MODEL") or "phonon"
# Which engine speaks: "ollama" (phonon) or "huggingface" (phonon-40m-en from Hugging Face on a CUDA GPU, the `tts` compose
# service, hi/tts_hf.py), for machines where phonon has no GPU build.
TTS_BACKEND = (_env.get("TTS_BACKEND") or "ollama").lower()
TTS_URL = _env.get("TTS_URL") or "http://localhost:8780"
# How the assistant addresses you in replies and speech ("" turns it off).
USER_ADDRESS = _env.get("USER_ADDRESS", "sir").strip()
TTS_VOICE = _env.get("TTS_VOICE") or "default"
# Where the menu bar app's island appears: "notch" (hangs from the notch) or "cursor" (opens next to the mouse pointer).
ISLAND_MODE = (_env.get("ISLAND_MODE") or "notch").lower()
# whisper.cpp `whisper-server` (hi/stt.py): the `whisper` compose service, or one run natively for Metal.
# The Mac bridge (hi/host_bridge.py): the Dockerized backend's way to run Mac-only tools.
HOST_BRIDGE_PORT = int(_env.get("HOST_BRIDGE_PORT") or 8766)
HOST_BRIDGE_BIND = _env.get("HOST_BRIDGE_BIND") or "127.0.0.1"
HOST_BRIDGE_URL = _env.get("HOST_BRIDGE_URL") or f"http://host.docker.internal:{HOST_BRIDGE_PORT}"
HOST_BRIDGE_TOKEN = _env.get("HOST_BRIDGE_TOKEN") or ""

# The code-execution sandbox container (sandbox/, docker-compose.yml).
SANDBOX_URL = _env.get("SANDBOX_URL") or "http://127.0.0.1:8000"
WHISPER_CPP_URL = _env.get("WHISPER_CPP_URL") or "http://127.0.0.1:8080"

# hi/perception/vision.py's ask_about_screen — a real vision-capable
# model, not a tier (haiku/sonnet/opus below are all text-only), per
# explicit request.

# Claude-tier-style model selection for the auto-router (hi/router.py): each
# turn picks a persona AND a tier, so a quick lookup doesn't burn the same
# model as a complex request. Cloud variants only (measured a local 8B model
# at 30-85s per call on this machine — CPU-only, no GPU acceleration — which
# is worse than Ollama Cloud's occasional cold-start latency, and HAIKU runs
# on every single router turn).
# Was qwen3.5:397b-cloud — confirmed live (TODO.md Phase 14) that this
# requires a subscription this account doesn't have (a real 402 at call
# time, exactly the silent-breakage BLOCKERS.md flagged as a risk, not
# just a theoretical one). nemotron-3-ultra:cloud is the largest model in
# the confirmed-usable set (BLOCKERS.md's own recommended swap-in),
# confirmed live and working.

# MCP (Model Context Protocol) server credentials (hi/mcp_tools.py). Both
# None if unset — the corresponding server is simply left out rather than
# failing, so `hi` works the same with or without them configured.
GITHUB_PERSONAL_ACCESS_TOKEN = _env.get("GITHUB_PERSONAL_ACCESS_TOKEN") or None
# Google Workspace (Drive, Docs, Sheets, Gmail, Calendar, ...): an OAuth "Desktop app" client from
# Google Cloud Console. The server stays absent until both are set; sign in once when asked.
GOOGLE_OAUTH_CLIENT_ID = _env.get("GOOGLE_OAUTH_CLIENT_ID") or None
GOOGLE_OAUTH_CLIENT_SECRET = _env.get("GOOGLE_OAUTH_CLIENT_SECRET") or None
GOOGLE_MCP_PORT = int(_env.get("GOOGLE_MCP_PORT") or 8777)  # the sign-in callback; published on loopback
GOOGLE_MCP_URL = _env.get("GOOGLE_MCP_URL") or None  # a running workspace-mcp (docker-compose.yml); unset = start one per call
OBSIDIAN_REST_API_KEY = _env.get("OBSIDIAN_REST_API_KEY") or None
# n8n's own MCP server needs two values, not one credential — the
# instance's own URL (self-hosted, varies per user, unlike Obsidian's
# fixed loopback address) alongside its bearer token.
N8N_MCP_URL = _env.get("N8N_MCP_URL") or None
N8N_MCP_TOKEN = _env.get("N8N_MCP_TOKEN") or None

# hi/perception/diff_watch.py — an interval-based screenshot-diff watcher,
# a genuinely different privacy posture than every other perception tool
# (which are strictly one-shot, explicitly-asked-for). Off unless the user
# opts in explicitly; unset/anything else defaults to disabled.
DIFF_WATCH_ENABLED = _env.get("DIFF_WATCH_ENABLED", "").strip().lower() in ("1", "true", "yes")

# hi/suggest/engine.py's model-judgment enrichment (TODO.md Phase 14) — an
# extra real model call every suggestion cycle (default every 30min), on
# top of the always-on deterministic gates. Off by default for the same
# reason DIFF_WATCH_ENABLED is: a recurring background cloud-model cost the
# user should opt into explicitly, not one this project should incur
# silently just by existing.
SMART_SUGGESTIONS_ENABLED = _env.get("SMART_SUGGESTIONS_ENABLED", "").strip().lower() in ("1", "true", "yes")


# --- Automation (hi/automation/): web search, scheduled tasks, the heartbeat, the drop folder -----------------
def _flag(name: str, default: bool) -> bool:
    value = (_env.get(name) or "").strip().lower()
    return default if not value else value in ("1", "true", "yes", "on")


def _number(name: str, default: float) -> float:
    try:
        return float(_env.get(name) or default)
    except ValueError:
        return float(default)


# Image generation (hi/imagegen.py): "service" = the `imagegen` service in this repo (Z-Image-Turbo or FLUX.2 klein), "openai" =
# any OpenAI-compatible images endpoint (set IMAGE_API_KEY), "off" = no image generation.
IMAGE_BACKEND = (_env.get("IMAGE_BACKEND") or "service").lower()
IMAGE_URL = _env.get("IMAGE_URL") or ""  # blank: image_url() picks one
IMAGE_PORT = 8790
IMAGE_MODEL = _env.get("IMAGE_MODEL") or "Tongyi-MAI/Z-Image-Turbo"
IMAGE_API_KEY = _env.get("IMAGE_API_KEY") or ""


def image_url() -> str:
    """Where the image service is: IMAGE_URL if set; in tailscale mode the Ollama box on port 8790 (the GPU is there);
    else the compose `imagegen` service (IMAGE_URL_DEFAULT) or this machine."""
    if IMAGE_URL:
        return IMAGE_URL.rstrip("/")
    if AI_MODE == "tailscale" and TAILSCALE_OLLAMA_URL:
        from urllib.parse import urlsplit

        host = urlsplit(TAILSCALE_OLLAMA_URL if "//" in TAILSCALE_OLLAMA_URL else f"//{TAILSCALE_OLLAMA_URL}").hostname
        if host:
            return f"http://{host}:{IMAGE_PORT}"
    return (_env.get("IMAGE_URL_DEFAULT") or f"http://127.0.0.1:{IMAGE_PORT}").rstrip("/")
# SearXNG, the private search engine (the `searxng` compose service; natively, publish it on 8888).
SEARXNG_URL = _env.get("SEARXNG_URL") or "http://127.0.0.1:8888"
SEARXNG_SECRET = _env.get("SEARXNG_SECRET") or ""
# The model's context window in tokens, sent to Ollama as num_ctx on every chat model. Ollama's own default is small and
# truncates silently. 16384 is also as much as the tailscale box can take: do not raise the default.
CONTEXT_TOKENS = int(_number("CONTEXT_TOKENS", 16384))

# The heartbeat: every HEARTBEAT_EVERY seconds, between the hours in HEARTBEAT_HOURS ("08-22"), look for work to prepare.
HEARTBEAT = _flag("HEARTBEAT", True)
HEARTBEAT_EVERY = int(_number("HEARTBEAT_EVERY", 1800))
HEARTBEAT_HOURS = _env.get("HEARTBEAT_HOURS") or "08-22"
# The drop folder (default <vault>/hi/drop): anything saved there is read, filed as a note and its tasks added.
DROP_PATH = _env.get("DROP_PATH") or ""
SCREENSHOT_WATCH = _flag("SCREENSHOT_WATCH", False)
# Unattended work: how long a proposal waits for you, and the limits on what runs by itself.
PROPOSAL_TTL_DAYS = int(_number("PROPOSAL_TTL_DAYS", 7))
MAX_BACKGROUND_RUNS_PER_HOUR = int(_number("MAX_BACKGROUND_RUNS_PER_HOUR", 6))
MAX_HOSTED_CALLS_PER_DAY = int(_number("MAX_HOSTED_CALLS_PER_DAY", 50))
MAX_NOTIFICATIONS_PER_HOUR = int(_number("MAX_NOTIFICATIONS_PER_HOUR", 3))
MAX_BACKGROUND_TOOL_CALLS = int(_number("MAX_BACKGROUND_TOOL_CALLS", 15))

def to_flag(value: object) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _to_hours(value: object) -> str:
    text = str(value).strip()
    if not re.fullmatch(r"\d{1,2}\s*-\s*\d{1,2}", text) or any(int(h) > 24 for h in re.findall(r"\d+", text)):
        raise ValueError('use two hours like "08-22"')
    return text


def _positive_int(value: object) -> int:
    number = int(str(value).strip())
    if number < 0:
        raise ValueError("must be zero or more")
    return number


def _image_backend(value: object) -> str:
    text = str(value).strip().lower()
    if text not in ("service", "openai", "off"):
        raise ValueError("must be service, openai or off")
    return text


def _context_tokens(value: object) -> int:
    number = int(str(value).strip())
    if not 2048 <= number <= 262144:
        raise ValueError("must be between 2048 and 262144")
    return number


# How a setting saved from the UI is turned into the type the rest of the code reads (the .env file holds text).
_COERCE = {
    "HEARTBEAT": to_flag, "SCREENSHOT_WATCH": to_flag, "HEARTBEAT_HOURS": _to_hours,
    "HEARTBEAT_EVERY": _positive_int, "PROPOSAL_TTL_DAYS": _positive_int, "MAX_BACKGROUND_RUNS_PER_HOUR": _positive_int,
    "MAX_HOSTED_CALLS_PER_DAY": _positive_int, "MAX_NOTIFICATIONS_PER_HOUR": _positive_int,
    "IMAGE_BACKEND": _image_backend, "CONTEXT_TOKENS": _context_tokens,
}


def coerce(key: str, value: object) -> object:
    """`value` as the setting `key` expects it. Raises ValueError with a message the user can act on."""
    try:
        return _COERCE[key](value) if key in _COERCE else value
    except ValueError as e:
        raise ValueError(f"{key}: {e}") from e


_SECRET_SUFFIXES = ("_TOKEN", "_KEY", "_SECRET", "PASSWORD")
MIN_SECRET_LENGTH = 8


def secret_values() -> list[str]:
    """The current value of every credential setting, read live. Used to keep them out of anything that leaves `hi`."""
    found = {
        str(value)
        for source in (_env, globals())
        for name, value in source.items()
        if name.isupper() and name.endswith(_SECRET_SUFFIXES) and isinstance(value, str) and len(value) >= MIN_SECRET_LENGTH
    }
    return sorted(found)


def state_dir() -> Path:
    """Runtime counters (usage, limits). Not memory: the vault is where `hi` remembers things."""
    path = Path.home() / ".hi" / "state"
    path.mkdir(parents=True, exist_ok=True)
    return path


def set_value(key: str, value: str) -> None:
    """Persist `key=value` to ~/.hi/.env and apply it to this process
    immediately (every consumer reads `config.<KEY>` live at call time).
    Model names are stored under the active mode's prefix; setting AI_MODE
    re-points every model global at the new mode's set."""
    from hi.env_file import write_env_var

    if key == "AI_MODE" and value not in MODES:
        raise ValueError(f"AI_MODE must be one of: {', '.join(MODES)}")
    stored_key = env_key(key, AI_MODE) if key in MODEL_ROLES else key
    typed = coerce(key, value)
    write_env_var(stored_key, value, path=ENV_PATH)
    _env[stored_key] = value
    globals()[key] = Path(value) if key == "VAULT_PATH" else typed
    if key == "AI_MODE":
        apply_mode()
