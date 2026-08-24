"""Local TTS via macOS's built-in `say` (`BLOCKERS.md` → "Ambient &
real-time gaps" #1's TTS half) — the zero-dependency MVP, the same
reasoning that already picked `AVSpeechSynthesizer` for the voice
companion (`voice_companion/Sources/HiVoice/SpeechOutput.swift`): a
native OS tool over a new bundled dependency (`kokoro`/`piper` remain
real upgrades to reach for later if `say`'s quality proves insufficient,
not a starting requirement).

`SpeechQueue` speaks completed sentences as they arrive in a streamed
response, not after the whole thing finishes — `feed()` is safe to call
repeatedly with growing partial text; a background worker thread speaks
each completed sentence in order via `subprocess.Popen(["say", ...])`,
so the caller (a token-consuming loop) never blocks on playback itself.
`stop()` is the barge-in primitive: clears anything still queued and
kills the currently-playing utterance immediately.
"""

from __future__ import annotations

import queue
import re
import subprocess
import threading

_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")


class SpeechQueue:
    def __init__(self) -> None:
        self._buffer = ""
        self._queue: queue.Queue[str] = queue.Queue()
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True).start()

    def feed(self, new_text: str) -> None:
        """Append newly-streamed text; any sentence(s) now complete in
        the buffer are queued to speak, in order."""
        self._buffer += new_text
        parts = _SENTENCE_END_RE.split(self._buffer)
        complete, self._buffer = parts[:-1], parts[-1]
        for sentence in complete:
            sentence = sentence.strip()
            if sentence:
                self._queue.put(sentence)

    def finish(self) -> None:
        """Flush whatever's left in the buffer as a final sentence —
        call once the stream this queue was fed from has ended."""
        tail = self._buffer.strip()
        self._buffer = ""
        if tail:
            self._queue.put(tail)

    def stop(self) -> None:
        """Barge-in: drop everything still queued and kill mid-utterance
        playback immediately, rather than letting it finish."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()

    def _run(self) -> None:
        while True:
            sentence = self._queue.get()
            with self._lock:
                self._process = subprocess.Popen(["say", sentence])
            self._process.wait()
            with self._lock:
                self._process = None
