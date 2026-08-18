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

# Claude-tier-style model selection for the auto-router (hi/router.py): each
# turn picks a persona AND a tier, so a quick lookup doesn't burn the same
# model as a complex request. Cloud variants only (measured a local 8B model
# at 30-85s per call on this machine — CPU-only, no GPU acceleration — which
# is worse than Ollama Cloud's occasional cold-start latency, and HAIKU runs
# on every single router turn).
HAIKU_MODEL = _env.get("HAIKU_MODEL", "gpt-oss:20b-cloud")
SONNET_MODEL = _env.get("SONNET_MODEL", DEFAULT_MODEL)
OPUS_MODEL = _env.get("OPUS_MODEL", "qwen3.5:397b-cloud")
