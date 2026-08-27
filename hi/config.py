"""Reads ~/.hi/.env for user-configurable settings: the Obsidian vault path
and the Ollama model used by each persona. Missing file or missing keys fall
back to sensible defaults, so a fresh install works with no .env at all.
"""

import re
from pathlib import Path

ENV_PATH = Path.home() / ".hi" / ".env"

DEFAULT_MODEL = "gpt-oss:120b-cloud"

_ESCAPE_RE = re.compile(r"\\(.)")


def _parse_env(path: Path) -> dict[str, str]:
    if not path.exists():
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


_env = _parse_env(ENV_PATH)

VAULT_PATH = Path(_env.get("VAULT_PATH", str(Path.home() / ".hi" / "vault")))
BUTLER_MODEL = _env.get("BUTLER_MODEL", DEFAULT_MODEL)
DOCS_MODEL = _env.get("DOCS_MODEL", DEFAULT_MODEL)
WEB_MODEL = _env.get("WEB_MODEL", "gpt-oss:20b-cloud")
TERM_MODEL = _env.get("TERM_MODEL", DEFAULT_MODEL)
WHISPER_MODEL = _env.get("WHISPER_MODEL", "base.en")

# hi/perception/vision.py's ask_about_screen — a real vision-capable
# model, not a tier (haiku/sonnet/opus below are all text-only), per
# explicit request.
VISION_MODEL = _env.get("VISION_MODEL", "gemma4:31b-cloud")

# Claude-tier-style model selection for the auto-router (hi/router.py): each
# turn picks a persona AND a tier, so a quick lookup doesn't burn the same
# model as a complex request. Cloud variants only (measured a local 8B model
# at 30-85s per call on this machine — CPU-only, no GPU acceleration — which
# is worse than Ollama Cloud's occasional cold-start latency, and HAIKU runs
# on every single router turn).
HAIKU_MODEL = _env.get("HAIKU_MODEL", "gpt-oss:20b-cloud")
SONNET_MODEL = _env.get("SONNET_MODEL", DEFAULT_MODEL)
# Was qwen3.5:397b-cloud — confirmed live (TODO.md Phase 14) that this
# requires a subscription this account doesn't have (a real 402 at call
# time, exactly the silent-breakage BLOCKERS.md flagged as a risk, not
# just a theoretical one). nemotron-3-ultra:cloud is the largest model in
# the confirmed-usable set (BLOCKERS.md's own recommended swap-in),
# confirmed live and working.
OPUS_MODEL = _env.get("OPUS_MODEL", "nemotron-3-ultra:cloud")

# MCP (Model Context Protocol) server credentials (hi/mcp_tools.py). Both
# None if unset — the corresponding server is simply left out rather than
# failing, so `hi` works the same with or without them configured.
GITHUB_PERSONAL_ACCESS_TOKEN = _env.get("GITHUB_PERSONAL_ACCESS_TOKEN") or None
OBSIDIAN_REST_API_KEY = _env.get("OBSIDIAN_REST_API_KEY") or None

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
