"""POST /query: one question in, an AG-UI event stream out."""

from __future__ import annotations

import time

from ag_ui.encoder import EventEncoder
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.routing import Route

from hi import attachments
from hi.dashboard import record_query_latency
from hi.llm.registry import TIERS
from hi.memory import sessions
from hi.server import turn
from hi.server.http import iterate_in_one_thread, json_body, required_text


async def query(request: Request) -> StreamingResponse:
    body = await json_body(request)
    text = required_text(body)
    forced_persona = body.get("persona") or None
    ids = body.get("attachments")
    context = attachments.render([str(i) for i in ids]) if isinstance(ids, list) else ""
    fresh = bool(body.get("fresh"))  # the menu bar prompt: start from a clean conversation
    origin = body.get("origin") if body.get("origin") in ("ui", "island", "voice") else "ui"
    tier = body.get("tier") if body.get("tier") in TIERS else None  # fast, balanced or deep; None = the router chooses
    session = str(body.get("session") or "")
    session = session if sessions.valid_id(session) else ""
    visualize = body.get("visualize") is True  # draw a diagram of the answer after it streams
    encoder = EventEncoder()

    async def stream():
        started = time.monotonic()
        try:
            events = iterate_in_one_thread(
                lambda: turn.stream_query_as_agui(text, forced_persona=forced_persona, fresh=fresh, context=context, origin=origin,
                    session=session, visualize=visualize, forced_tier=tier)
            )
            async for event in events:
                yield encoder.encode(event)
        finally:
            record_query_latency(time.monotonic() - started)  # the dashboard's "last latency" stat

    return StreamingResponse(stream(), media_type=encoder.get_content_type())


routes = [Route("/query", query, methods=["POST"])]
