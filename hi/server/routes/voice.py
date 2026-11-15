"""Speech: text to audio (/tts), audio to text (/stt), and the rambler that tidies a spoken transcript."""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from hi.core import health
from hi.server.http import json_body, required_text


def _synthesize(text: str, voice: str, persona: str) -> bytes:
    from hi.tts_engine import synthesize_wav
    from hi.voices import voice_for

    return synthesize_wav(text, voice or voice_for(persona))


def _synthesize_with_retry(text: str, voice: str, persona: str) -> bytes:
    """The configured engine, tried twice; there is deliberately no other engine to fall back to."""
    try:
        return _synthesize(text, voice, persona)
    except Exception:
        return _synthesize(text, voice, persona)


async def tts(request: Request) -> Response:
    body = await json_body(request)
    text = required_text(body)
    voice, persona = str(body.get("voice") or "").strip(), str(body.get("persona") or "").strip()
    try:
        wav = await run_in_threadpool(_synthesize_with_retry, text, voice, persona)
    except Exception as e:  # boundary: no other engine is tried, a different voice would be worse than silence
        health.mark_down("tts", e)
        raise HTTPException(503, f"voice offline: {e}")
    health.mark_ok("tts")
    return Response(wav, media_type="audio/wav")


async def tts_voices(request: Request) -> JSONResponse:
    from hi.tts_engine import list_voices

    try:
        return JSONResponse({"voices": await run_in_threadpool(list_voices), "error": ""})
    except RuntimeError as e:
        return JSONResponse({"voices": [], "error": str(e)})


async def stt(request: Request) -> JSONResponse:
    """A 16 kHz mono WAV body in, {"text": ...} out, via the native whisper.cpp server."""
    wav = await request.body()
    if not wav:
        raise HTTPException(400, "Missing audio body")
    from hi.stt import transcribe_wav

    try:
        return JSONResponse({"text": await run_in_threadpool(transcribe_wav, wav)})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


async def ramble(request: Request) -> JSONResponse:
    original = required_text(await json_body(request))
    from hi.rambler import structure

    return JSONResponse({"text": await run_in_threadpool(structure, original), "original": original})


routes = [
    Route("/tts", tts, methods=["POST"]),
    Route("/tts/voices", tts_voices, methods=["GET"]),
    Route("/stt", stt, methods=["POST"]),
    Route("/ramble", ramble, methods=["POST"]),
]
