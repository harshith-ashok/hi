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
"""

from langchain_core.messages import AIMessageChunk, BaseMessage


def stream_and_print(agent, messages: list) -> list[BaseMessage]:
    """Stream `agent`'s response for `messages`, printing generated text as
    it arrives, and return the final complete message list — the same
    shape `agent.invoke(...)["messages"]` would return."""
    final_messages: list[BaseMessage] | None = None
    for _ns, mode, payload in agent.stream(
        {"messages": messages}, stream_mode=["messages", "values"], subgraphs=True
    ):
        if mode == "messages":
            chunk, _metadata = payload
            if isinstance(chunk, AIMessageChunk) and chunk.content:
                print(chunk.content, end="", flush=True)
        else:
            final_messages = payload["messages"]
    print()
    return final_messages
