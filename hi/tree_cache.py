"""Caches a `tree -L 4` snapshot of the vault at ~/.hi/tree_cache.md, so
agents can see the vault's overall folder structure as extra context without
re-running `tree` (or listing every file) on every turn.
"""

import shutil
import subprocess
from pathlib import Path

from hi.config import VAULT_PATH

TREE_CACHE_PATH = Path.home() / ".hi" / "tree_cache.md"


def refresh_tree_cache() -> None:
    """Regenerate ~/.hi/tree_cache.md from the vault. No-ops if `tree` isn't
    installed or the vault doesn't exist yet."""
    if shutil.which("tree") is None or not VAULT_PATH.is_dir():
        return
    result = subprocess.run(
        ["tree", "-L", "4"],
        cwd=VAULT_PATH,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        TREE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        TREE_CACHE_PATH.write_text(result.stdout)


def read_tree_cache() -> str:
    """Return the cached tree snapshot, or "" if it doesn't exist yet."""
    if not TREE_CACHE_PATH.exists():
        return ""
    return TREE_CACHE_PATH.read_text()
