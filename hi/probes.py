"""Live checks of what `hi` depends on, for GET /health. Each probe is cheap and bounded by a short
timeout, and records its result in the health registry (hi/core/health.py)."""

from __future__ import annotations

import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Callable

import hi.config as config
from hi import llm
from hi.core import health

TIMEOUT_S = 2.0
DEADLINE_S = 4.0  # urlopen's timeout doesn't cover DNS lookups, so each probe also gets a hard deadline


def _get(url: str) -> None:
    with urllib.request.urlopen(url, timeout=TIMEOUT_S):
        pass


def _ollama() -> None:
    llm.list_models(timeout=TIMEOUT_S)


def _host_bridge() -> None:
    _get(f"{config.HOST_BRIDGE_URL.rstrip('/')}/health")


def _sandbox() -> None:
    _get(f"{config.SANDBOX_URL.rstrip('/')}/health")


def _vault() -> None:
    config.VAULT_PATH.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=config.VAULT_PATH):
        pass  # creating a file proves the vault is writable


PROBES: dict[str, Callable[[], None]] = {
    "ollama": _ollama,
    "host_bridge": _host_bridge,
    "sandbox": _sandbox,
    "vault": _vault,
}


def run(probes: dict[str, Callable[[], None]] | None = None) -> dict:
    """Run every probe and return {"ok": bool, "deps": {name: {ok, error, since}}}.

    "ok" means the essentials work (the model host and the vault). The host bridge and the
    sandbox are optional extras: they show up in `deps` but don't fail the overall status.
    """
    probes = probes or PROBES
    pool = ThreadPoolExecutor(max_workers=len(probes), thread_name_prefix="probe")
    futures = {pool.submit(probe): name for name, probe in probes.items()}
    done, pending = wait(futures, timeout=DEADLINE_S)
    pool.shutdown(wait=False, cancel_futures=True)  # a stuck probe thread is abandoned, not waited for
    for future in done:
        name = futures[future]
        try:
            future.result()
        except Exception as e:  # boundary: any failure is just "this dependency is down"
            health.mark_down(name, llm.friendly_error(e))
        else:
            health.mark_ok(name)
    for future in pending:
        health.mark_down(futures[future], f"no answer within {DEADLINE_S:g}s")
    deps = health.snapshot()
    essentials = ("ollama", "vault")
    return {"ok": all(deps.get(name, {}).get("ok", True) for name in essentials), "deps": deps}
