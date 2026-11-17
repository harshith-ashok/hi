"""Shared fixtures. Unit tests never touch the network or the real ~/.hi or vault."""

from __future__ import annotations

import pytest

import hi.config as config


@pytest.fixture
def tmp_vault(tmp_path, monkeypatch):
    """Point the vault at an empty temp directory for one test."""
    monkeypatch.setattr(config, "VAULT_PATH", tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def _state_dir(tmp_path_factory, monkeypatch):
    """Runtime counters (hi/automation/limits.py) go to a temp folder, never the real ~/.hi/state."""
    folder = tmp_path_factory.mktemp("state")
    monkeypatch.setattr(config, "state_dir", lambda: folder)
