"""Classifies each auto-routing-mode turn into (persona, tier) using the
haiku-tier model, so hi/repl.py's `(hi) >` prompt can pick the right agent
and model without the user specifying a persona flag.
"""

from langchain_core.messages import HumanMessage

from hi.model_warmup import invoke_with_retry
from hi.models import get_tier_model
from hi.personas import PERSONAS

TIERS = ("haiku", "sonnet", "opus")

PERSONA_DESCRIPTIONS = {
    "butler": (
        "macOS system control (Bluetooth, volume, Wi-Fi, Do Not Disturb, "
        "screenshots, clipboard, apps, TODO list). Controlling the Mac or "
        "managing tasks."
    ),
    "docs": (
        "Strict, read-only search over the user's own Obsidian vault "
        "notes — never answers from general knowledge. Questions about "
        "what's written in the user's notes."
    ),
    "web": (
        "Wikipedia search and summarization. General-knowledge lookup "
        "questions not about the user's own data."
    ),
    "term": (
        "Runs real shell commands in the user's terminal (filesystem/shell "
        "questions, running commands), and is also the general-purpose "
        "assistant with persistent memory (notes, people, dev-flow "
        "launcher, remembering facts) and coding/project questions — the "
        "default choice when nothing else fits better. Remembers command "
        "output and conversation context across turns."
    ),
}

TIER_DESCRIPTIONS = {
    "haiku": "trivial/simple requests needing minimal reasoning",
    "sonnet": "typical, moderately complex requests — the default for most things",
    "opus": "genuinely complex, multi-step, or high-stakes requests needing the most capable model",
}


def classify(prompt: str) -> tuple[str, str]:
    """Return (persona_name, tier) for `prompt`."""
    model = get_tier_model("haiku")
    persona_lines = "\n".join(f"- {name}: {desc}" for name, desc in PERSONA_DESCRIPTIONS.items())
    tier_lines = "\n".join(f"- {tier}: {desc}" for tier, desc in TIER_DESCRIPTIONS.items())
    selection_prompt = (
        "Classify the user's request below. Choose exactly one persona and "
        "exactly one tier.\n\n"
        f"Personas:\n{persona_lines}\n\n"
        f"Tiers:\n{tier_lines}\n\n"
        f"User request:\n{prompt}\n\n"
        "Reply with ONLY two lowercase words separated by a space: "
        "<persona> <tier>. Example: term sonnet"
    )
    # A HumanMessage, not SystemMessage: gpt-oss:20b-cloud (the default
    # haiku-tier model) returns empty content for a system-message-only
    # conversation — verified this is specific to the smaller model, not
    # the transient empty-response issue invoke_with_retry otherwise
    # handles; gpt-oss:120b-cloud tolerates system-only fine elsewhere in
    # this codebase (hi/memory_graph.py).
    reply = invoke_with_retry(model, [HumanMessage(selection_prompt)]).lower()

    persona = next((p for p in PERSONAS if p in reply), "term")
    tier = next((t for t in TIERS if t in reply), "sonnet")
    return persona, tier
