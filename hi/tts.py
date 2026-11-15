"""Speech for the assistant's own scripts (timers, the wake daemon, streamed replies): phonon on the Mac's Ollama
(hi/tts_ollama.py), played with `afplay`. It never falls back to macOS `say`: if phonon is unreachable the
alert is simply not spoken (and a line is printed), because a different voice is worse than silence here.

`speak(text)` says one thing and waits. `SpeechQueue` speaks sentences as they arrive in a streamed response:
a synthesis thread turns each completed sentence into audio while a playback thread plays the previous one,
so the gap between sentences is the playback itself, not a round trip to the model. `stop()` is the barge-in
primitive: it drops everything queued and cuts the current utterance.
"""

from __future__ import annotations

import os
import queue
import re
import subprocess
import tempfile
import threading

from hi import tts_ollama
from hi.voices import voice_for

_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")


def _synthesize_to_file(text: str, persona: str | None = None) -> str | None:
    """Phonon audio for `text` in a temp file, or None (after printing why) if it could not be made."""
    try:
        wav = tts_ollama.synthesize_wav(text, voice_for(persona))
    except Exception as e:
        print(f"[speech skipped: {e}]", flush=True)
        return None
    fd, path = tempfile.mkstemp(suffix=".wav", prefix="hi-speech-")
    with os.fdopen(fd, "wb") as f:
        f.write(wav)
    return path


def speak(text: str, persona: str | None = None) -> None:
    """Say `text` aloud with phonon (in `persona`'s voice) and return when it has finished."""
    path = _synthesize_to_file(text, persona)
    if path is None:
        return
    try:
        subprocess.run(["afplay", path], capture_output=True)
    finally:
        os.unlink(path)


class SpeechQueue:
    def __init__(self) -> None:
        self.persona: str | None = None  # whose voice to speak in; set per turn by the caller
        self._buffer = ""
        self._sentences: queue.Queue[str] = queue.Queue()
        self._audio: queue.Queue[str] = queue.Queue(maxsize=2)  # synthesize at most two sentences ahead
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._generation = 0  # bumped by stop(): audio made for an older generation is discarded
        threading.Thread(target=self._synthesize_loop, daemon=True).start()
        threading.Thread(target=self._play_loop, daemon=True).start()

    def feed(self, new_text: str) -> None:
        """Append newly-streamed text; any sentence(s) now complete in the buffer are queued to speak, in order."""
        self._buffer += new_text
        parts = _SENTENCE_END_RE.split(self._buffer)
        complete, self._buffer = parts[:-1], parts[-1]
        for sentence in complete:
            sentence = sentence.strip()
            if sentence:
                self._sentences.put(sentence)

    def finish(self) -> None:
        """Flush whatever is left in the buffer as a final sentence: call once the stream has ended."""
        tail = self._buffer.strip()
        self._buffer = ""
        if tail:
            self._sentences.put(tail)

    def stop(self) -> None:
        """Barge-in: drop everything still queued and cut off playback immediately."""
        with self._lock:
            self._generation += 1
            self._drain(self._sentences)
            for path in self._drain(self._audio):
                os.unlink(path)
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()

    @staticmethod
    def _drain(q: queue.Queue) -> list:
        items = []
        while True:
            try:
                items.append(q.get_nowait())
            except queue.Empty:
                return items

    def _synthesize_loop(self) -> None:
        while True:
            sentence = self._sentences.get()
            generation = self._generation
            path = _synthesize_to_file(sentence, self.persona)
            if path is None:
                continue
            if generation != self._generation:  # stop() was called while this was being made
                os.unlink(path)
                continue
            self._audio.put(path)

    def _play_loop(self) -> None:
        while True:
            path = self._audio.get()
            with self._lock:
                self._process = subprocess.Popen(["afplay", path])
            self._process.wait()
            with self._lock:
                self._process = None
            os.unlink(path)
