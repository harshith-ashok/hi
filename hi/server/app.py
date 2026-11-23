"""The Starlette app. Run with `hi --voice-daemon` (or `uvicorn hi.server.app:app`)."""

from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from hi.server.cors import allowed_origins
from hi.server.routes import ALL

log = logging.getLogger(__name__)

HOST = os.environ.get("HI_HOST", "127.0.0.1")  # 0.0.0.0 inside the container; compose publishes it loopback-only
DEFAULT_PORT = 8768


@asynccontextmanager
async def lifespan(app: Starlette):
    """The only place the backend starts background work: confirm-before-acting goes through the
    pending queue (there's no terminal to ask in), then the jobs and the model warm-up."""
    from hi import startup
    from hi.action_tiers import set_confirm_handler
    from hi.orchestrator.pending_actions import wait_for_approval
    from hi.server.headless import run_turn
    from hi.server.turn import _warm_up

    set_confirm_handler(wait_for_approval)
    startup.start_background_jobs(run_turn)
    threading.Thread(target=_warm_up, name="warm-up", daemon=True).start()
    yield


def create_app() -> Starlette:
    return Starlette(
        routes=ALL,
        middleware=[
            Middleware(CORSMiddleware, allow_origins=allowed_origins(), allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Content-Type", "X-Hi-Client"]),
        ],
        lifespan=lifespan,
    )


app = create_app()


def main(port: int = DEFAULT_PORT) -> None:
    import uvicorn

    print(f"hi backend listening on http://{HOST}:{port}. Ctrl-C to stop.", flush=True)
    uvicorn.run(app, host=HOST, port=port, log_level="warning")
