"""Streams an agent's response token-by-token to stdout, instead of
printing it all at once after the whole thing has been generated.

Uses stream_mode=["messages", "values"], subgraphs=True on every agent
type uniformly — verified directly (not assumed) that this yields a
consistent (namespace, mode, payload) shape whether or not the agent
actually has subgraphs, so this needs no per-persona branching. Filtering
by `isinstance(chunk, AIMessageChunk) and chunk.content` (rather than by
node name) reliably isolates real generated text from tool-call/tool-result
noise — verified that an unfiltered stream includes full tool outputs
(e.g. an entire cited note's raw content) as intermediate chunks.

Cancellable via hi/cancellation.py's shared Ctrl-J primitive (BLOCKERS.md
"Ambient & real-time gaps" #3) — previously there was no way to interrupt
a mid-generation response at all, unlike waiting on a shell command,
which already had this. Verified live that agent.stream(...) returns a
real, closeable Python generator before relying on `.close()` for
best-effort cancellation of the underlying run.

Optionally speaks each printed chunk too (BLOCKERS.md "Ambient &
real-time gaps" #1's TTS half, hi/tts.py's SpeechQueue) — an opt-in
parameter, not a default-on behavior change for every existing caller:
hi/repl.py's typed/Ctrl-V sessions stay silent unless a caller explicitly
passes one in (currently only hi/wake.py's ambient voice loop does,
where hearing the answer is the entire point). Ctrl-J is the same
interrupt for both halves — cancelling a response also barges in on
whatever's currently being spoken from it.

Also surfaces a reasoning-capable model's `thinking` content as it
streams (TODO.md Phase 14, BLOCKERS.md "Suggested feature improvements"
D) — previously silently dropped entirely, the same gap the sibling
`sage/backend` project on this machine already found and fixed for the
same underlying Ollama models. hi/chat_model.py's make_chat_model()
enables `reasoning=True` per-model (probed, not assumed); when a chunk
actually carries `additional_kwargs["reasoning_content"]`, it's printed
dimmed and prefixed so it reads as "thinking out loud," not the real
answer — never fed to shown_chunks/speech_queue, since hearing a
model's raw internal monologue spoken aloud would be strange, not
useful (only the actual answer is spoken/returned).
"""

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage

from hi.cancellation import CancellationToken, Throttle
from hi.tts import SpeechQueue

_DIM = "\033[2m"
_RESET = "\033[0m"


def stream_and_print(
    agent, messages: list, speech_queue: SpeechQueue | None = None
) -> list[BaseMessage]:
    """Stream `agent`'s response for `messages`, printing generated text as
    it arrives, and return the final complete message list — the same
    shape `agent.invoke(...)["messages"]` would return, or, if interrupted
    (Ctrl-J), the original `messages` plus whatever text was actually
    shown before the interrupt (or a plain marker if none was), so callers
    never have to special-case an empty/stale return.

    Deliberately does NOT fall back to whatever `final_messages` happened
    to be set to when cancelled — a "values"-mode tick can fire *before*
    generation completes too (an early state snapshot right after the
    human message is added, still just echoing the input back), which
    would silently return stale, pre-generation state as if it were the
    real answer. Found live, by testing the interrupt path against a real
    agent stream rather than assuming the None-check alone was enough.

    Args:
        speech_queue: if given, every printed chunk is also fed to it for
            speaking (hi/tts.py) — sentence-chunked as they arrive, not
            after the full response completes. Not flushed/finished here;
            the caller owns the queue's lifetime and calls finish() once
            it's done feeding it (e.g. after logging the turn).
    """
    final_messages: list[BaseMessage] | None = None
    shown_chunks: list[str] = []
    token = CancellationToken()
    throttle = Throttle()
    thinking_open = False  # whether a dimmed "thinking" block is currently being printed

    stream = agent.stream(
        {"messages": messages}, stream_mode=["messages", "values"], subgraphs=True
    )
    for _ns, mode, payload in stream:
        if token.poll(throttle):
            stream.close()  # best-effort — signals the underlying run to stop, not guaranteed
            if speech_queue is not None:
                speech_queue.stop()  # same interrupt barges in on speech too
            break
        if mode == "messages":
            chunk, _metadata = payload
            if not isinstance(chunk, AIMessageChunk):
                continue
            thinking = chunk.additional_kwargs.get("reasoning_content")
            if thinking:
                if not thinking_open:
                    print(f"\n{_DIM}(thinking) ", end="", flush=True)
                    thinking_open = True
                print(thinking, end="", flush=True)
            if chunk.content:
                if thinking_open:
                    print(f"{_RESET}\n", end="", flush=True)
                    thinking_open = False
                print(chunk.content, end="", flush=True)
                shown_chunks.append(chunk.content)
                if speech_queue is not None:
                    speech_queue.feed(chunk.content)
        else:
            final_messages = payload["messages"]

    if thinking_open:
        print(_RESET, end="", flush=True)

    if token.cancelled:
        print("\n(Ctrl-J — stopped listening to the response; it may still be generating.)")
        shown_text = "".join(shown_chunks) or "(interrupted before any text was generated)"
        return [*messages, AIMessage(content=shown_text)]

    print()
    return final_messages
