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
CODE_MODEL = _env.get("CODE_MODEL", DEFAULT_MODEL)
BUTLER_MODEL = _env.get("BUTLER_MODEL", DEFAULT_MODEL)
DOCS_MODEL = _env.get("DOCS_MODEL", DEFAULT_MODEL)
WEB_MODEL = _env.get("WEB_MODEL", "web")
