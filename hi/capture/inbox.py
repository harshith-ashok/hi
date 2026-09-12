"""Untriaged raw captures, written by the global hotkey
(hi/capture/hotkey.py) or anything else that wants to jot something down
without deciding right now whether it's a task or an event.
hi/capture/triage.py classifies and clears these out.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import hi.config as config

def _inbox_dir():
    return config.VAULT_PATH / "hi" / "tasks" / "inbox"


def write_inbox_item(raw_text: str) -> Path:
    _inbox_dir().mkdir(parents=True, exist_ok=True)
    path = _inbox_dir() / f"{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}-{uuid.uuid4().hex[:6]}.md"
    path.write_text(raw_text)
    return path


def list_inbox_items() -> list[Path]:
    if not _inbox_dir().is_dir():
        return []
    return sorted(_inbox_dir().glob("*.md"))
