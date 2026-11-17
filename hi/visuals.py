"""Draw an answer: one Mermaid diagram that shows what an answer says, for the chat to render beside the text.

`make_visual` asks a small model for the diagram and checks the reply in code (a known diagram type, a sensible size)
so the UI only ever receives something it can try to draw. The UI parses it with Mermaid itself; if that fails it can
ask again with the parse error (`error=`), which is how a model that wrote a bad label gets a second chance.
"""

from __future__ import annotations

import re
from typing import Callable

MAX_CHARS = 4000
MIN_ANSWER_CHARS = 40
DIAGRAMS = (
    "flowchart", "graph", "sequenceDiagram", "classDiagram", "stateDiagram", "erDiagram", "gantt", "pie", "mindmap",
    "timeline", "journey", "quadrantChart", "gitGraph", "xychart-beta", "sankey-beta", "block-beta",
)

_PROMPT = """Draw the key idea of this answer as ONE Mermaid diagram, so a reader grasps it at a glance.

Question: {question}

Answer:
{answer}

Rules:
- Pick the type that fits: flowchart for steps or structure, sequenceDiagram for interactions over time, mindmap for a
  topic with parts, timeline for dates, stateDiagram-v2 for states, erDiagram for data, pie for shares, gantt for plans.
- At most 12 nodes. Short labels. Put every label in double quotes, for example A["Read the file"] --> B["Parse it"].
  Never put parentheses, brackets or quotes inside a label.
- Show what the answer says, not what the question asked.
- Reply with the Mermaid code only: no explanation, no code fence. If the answer is a plain fact or has nothing to
  draw, reply exactly: NONE{retry}"""


def clean_mermaid(text: str) -> str | None:
    """The diagram code in a model reply, or None if there isn't a usable one."""
    text = re.sub(r"^```(?:mermaid)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE).strip()
    if not text or text.upper() == "NONE" or len(text) > MAX_CHARS:
        return None
    first = text.splitlines()[0].strip()
    if not any(first == d or first.startswith((d + " ", d + "-", d + ";")) for d in DIAGRAMS):
        return None
    return text


def _default_model(prompt: str) -> str:
    from langchain_core.messages import HumanMessage

    from hi.llm.registry import get_tier_model_fast
    from hi.llm.resilience import invoke_with_retry

    return invoke_with_retry(get_tier_model_fast("haiku"), [HumanMessage(prompt)])


def make_visual(question: str, answer: str, error: str = "", model_fn: Callable[[str], str] | None = None) -> str | None:
    """A Mermaid diagram for `answer`, or None. Never raises: no diagram is an acceptable outcome."""
    if len(answer.strip()) < MIN_ANSWER_CHARS:
        return None
    retry = f"\n\nYour previous diagram failed to parse with: {error[:300]}. Simplify it and fix that." if error else ""
    prompt = _PROMPT.format(question=question[:600], answer=answer[:3500], retry=retry)
    try:
        return clean_mermaid((model_fn or _default_model)(prompt))
    except Exception:  # boundary: a failed diagram must never fail the turn it decorates
        return None
