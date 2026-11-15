"""Importing a module must not start threads or hit the network (MAKE.md, principle 3)."""

import importlib
import threading

import pytest

# Modules that are expected to stay quiet on import. Agent modules build models at import
# today; they join this list when MAKE.md phase 5 removes that.
QUIET = ["hi.config", "hi.router", "hi.vault", "hi.llm", "hi.env_file", "hi.toolkit", "hi.retry"]


@pytest.mark.parametrize("name", QUIET)
def test_import_starts_no_threads(name):
    before = threading.active_count()
    importlib.import_module(name)
    assert threading.active_count() == before
