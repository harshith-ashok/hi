"""Helpers shared by the route modules."""

from __future__ import annotations

import asyncio
import json
import threading
from typing import AsyncIterator, Callable, Iterator, TypeVar

from starlette.exceptions import HTTPException
from starlette.requests import Request

T = TypeVar("T")

# State-changing routes that run something or delete something (approvals, schedules, filing) need this header.
# A browser only sends a custom header after a CORS preflight, and the preflight is answered only for tinyui's own
# origins (hi/server/cors.py). Without it, any web page open in your browser could POST an approval to this loopback
# server: a request with no body and no custom header is "simple" and is sent without asking.
CLIENT_HEADER = "X-Hi-Client"


def require_client(request: Request) -> None:
    if not request.headers.get(CLIENT_HEADER):
        raise HTTPException(403, f"Send the {CLIENT_HEADER} header with this request (tinyui and the menu bar app do)")


async def json_body(request: Request) -> dict:
    """The request's JSON object; 400 if it isn't valid JSON or isn't an object."""
    try:
        body = json.loads(await request.body() or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")
    if not isinstance(body, dict):
        raise HTTPException(400, "Expected a JSON object")
    return body


def required_text(body: dict, key: str = "text") -> str:
    value = str(body.get(key) or "").strip()
    if not value:
        raise HTTPException(400, f"Missing '{key}'")
    return value


async def iterate_in_one_thread(make_iterator: Callable[[], Iterator[T]]) -> AsyncIterator[T]:
    """Run a blocking generator on ONE dedicated thread and yield its items asynchronously.

    One thread, not a threadpool hop per item: agent streams keep per-thread state (an event loop
    for orchestrated runs). If the consumer stops early (the client disconnected), the producer
    stops at its next item and closes the generator on its own thread, so its cleanup runs.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    stop = threading.Event()
    done = object()

    def post(item) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, item)
        except RuntimeError:  # the loop is already closed
            pass

    def produce() -> None:
        iterator = make_iterator()
        try:
            for item in iterator:
                if stop.is_set():
                    break
                post(item)
        except BaseException as e:  # handed to the consumer, which re-raises it
            post(e)
        finally:
            close = getattr(iterator, "close", None)
            if close:
                close()
            post(done)

    threading.Thread(target=produce, name="stream", daemon=True).start()
    try:
        while True:
            item = await queue.get()
            if item is done:
                return
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        stop.set()
