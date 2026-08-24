"""Wake-word daemon (`BLOCKERS.md` → "Ambient & real-time gaps" #1):
listens only for a wake phrase via `openWakeWord` — fully open-source,
local, ONNX-based, **no account or API key needed**, unlike Porcupine
(which is why the original TODO.md Phase 5 wake-word item was left open:
Porcupine needs a paid Picovoice account this project never had access
to). Not transcribing continuously — only once the wake word actually
fires.

On trigger: reuses `hi/voice.py`'s existing `record_until_silence()`/
`transcribe()` pipeline unchanged, then pipes the result straight to the
router (`hi/router.py`'s `classify()`) — skipping the manual
review-then-Enter step Ctrl-V uses in the interactive REPL, since the
whole point of a wake-word loop is hands-free operation. Speaks the
response via `hi/tts.py`'s `SpeechQueue`, and a fresh wake-word trigger
while still speaking barges in immediately (`speech_queue.stop()`) —
same interrupt primitive `hi/streaming.py`'s Ctrl-J cancellation
already uses (Phase 10), reused rather than a second mechanism.

Deliberately `hi/wake.py`, a flat module — not `hi/voice/wake.py` as
TODO.md originally sketched. `hi/voice.py` already exists as a working
module, not a package; converting it into one just to nest a new file
under it would be pure churn for zero benefit, and every other
top-level piece of this codebase (`hi/router.py`, `hi/streaming.py`,
`hi/cancellation.py`, `hi/tts.py`, ...) is already a flat module — this
follows that same convention, not a new one.

Two separate, sequential `sd.InputStream` sessions, never concurrent:
one short-lived stream per wake-word-listening cycle (closed the moment
the wake word fires), then `hi/voice.py`'s own separate stream for
recording the actual command afterward. Kept sequential deliberately —
most audio backends don't cleanly support two simultaneous input streams
on the same device.

Run with: hi --wake-daemon
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import openwakeword
import sounddevice as sd
from openwakeword.model import Model

from hi.models import get_tier_model
from hi.personas import get_agent_builder
from hi.router import classify
from hi.streaming import stream_and_print
from hi.tts import SpeechQueue
from hi.vault import log_conversation
from hi.voice import listen_and_transcribe

SAMPLE_RATE = 16_000
CHUNK_SAMPLES = 1280  # 80ms at 16kHz — openWakeWord's expected frame size
DETECTION_THRESHOLD = 0.5
WAKE_WORD_MODEL_FILE = "hey_jarvis_v0.1.onnx"
WAKE_PHRASE = "Hey Jarvis"

_agent_cache: dict[tuple[str, str], object] = {}


def _model_path() -> str:
    pkg_dir = Path(openwakeword.__file__).parent
    return str(pkg_dir / "resources" / "models" / WAKE_WORD_MODEL_FILE)


def _get_agent(persona_name: str, tier: str):
    key = (persona_name, tier)
    if key not in _agent_cache:
        _agent_cache[key] = get_agent_builder(persona_name)(get_tier_model(tier))
    return _agent_cache[key]


def _listen_for_wake_word(wake_model: Model, key: str) -> None:
    """Blocks until the wake word fires. Opens its own short-lived mic
    stream, closed before returning, so it never overlaps with
    listen_and_transcribe()'s own separate stream for the command that
    follows."""
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16") as stream:
        while True:
            chunk, _overflowed = stream.read(CHUNK_SAMPLES)
            prediction = wake_model.predict(chunk[:, 0])
            score = prediction[key]
            if score >= DETECTION_THRESHOLD:
                return


def _handle_query(text: str, speech_queue: SpeechQueue) -> None:
    persona_name, tier = classify(text)
    print(f"\n({persona_name}) heard: {text}")
    agent = _get_agent(persona_name, tier)
    final_messages = stream_and_print(
        agent, [{"role": "user", "content": text}], speech_queue=speech_queue
    )
    speech_queue.finish()
    log_conversation(persona_name, text, final_messages[-1].content)


def run_wake_daemon() -> None:
    wake_model = Model(wakeword_model_paths=[_model_path()])
    key = list(wake_model.models.keys())[0]
    speech_queue = SpeechQueue()

    print(f'Wake-word daemon listening for "{WAKE_PHRASE}". Ctrl-C to stop.')
    while True:
        _listen_for_wake_word(wake_model, key)
        speech_queue.stop()  # barge-in: a fresh trigger interrupts any speech in progress
        wake_model.reset()
        print(f"\n[{WAKE_PHRASE} detected — listening]")

        text = listen_and_transcribe()
        if not text.strip():
            print("(heard nothing)")
            continue
        _handle_query(text, speech_queue)
