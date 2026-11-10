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
        "saving a screenshot file to disk, clipboard, which apps/windows "
        "are currently running or open, quitting an app, TODO list). "
        "Controlling the Mac or managing tasks. NOT for questions about "
        "what's visually displayed on screen or in the browser right now "
        "— that's term."
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
        "default choice when nothing else fits better. Also the ONLY "
        "persona that can visually read/describe what's actually "
        "displayed on screen right now or in the browser's current tab — "
        "'what's on my screen', 'what does this error say', 'describe "
        "this image/diagram' (NOT 'what apps are running', that's "
        "butler). Also the ONLY persona that can read/list/search actual "
        "project files on disk directly — a README, source code, config "
        "— not just the user's Obsidian vault notes: 'read the README', "
        "'what does this file do', 'find the file that handles X', "
        "'search this project for Y', 'save this project to the vault'. "
        "Also the ONLY persona that can propose/apply real file edits and "
        "run tests to iterate on them, and that can summarize/find "
        "patterns across the ENTIRE vault at once (not just answer a "
        "specific note-lookup question). Remembers command output and "
        "conversation context across turns."
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
    # this codebase.
    reply = invoke_with_retry(model, [HumanMessage(selection_prompt)]).lower()

    persona = next((p for p in PERSONAS if p in reply), "term")
    tier = next((t for t in TIERS if t in reply), "sonnet")
    return persona, tier


# --- fast path: skip the classification model call for obvious turns --------
import re
import time

STICKY_SECONDS = 120
STICKY_MAX_WORDS = 4  # "and the second one?", "yes", "do it"
_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), persona, tier)
    for pattern, persona, tier in (
        (r"\b(on|in|from) my (screen|display|browser)\b|\b(my|this|the) screen\b|this error|current tab|\bwhat am i looking at\b", "term", "sonnet"),
        (r"\b(volume|wi-?fi|bluetooth|timers?|alarm|do not disturb|dnd|clipboard|brightness|apple music|playlist|now playing)\b|\b(pause|skip|resume)\b.*\b(music|song|track)\b|\bplay\b.*\b(song|album|music)\b", "butler", "haiku"),
        (r"\b(my notes?|my vault|in my obsidian|what did i (write|note))\b", "docs", "sonnet"),
        (r"\bwikipedia\b|\b(picture|photo|image|pic)s? of\b", "web", "haiku"),
        (r"\b(python|plot|visuali[sz]e|matplotlib|regression|scikit|sklearn)\b", "term", "sonnet"),
        (r"\bgithub\b|\bpull requests?\b|\brepos?\b|\b(make|set)\b.*\b(private|public)\b", "term", "sonnet"),
    )
)
_last_route: tuple[str, str, float] | None = None


def fast_route(prompt: str) -> tuple[str, str] | None:
    """(persona, tier) when the turn is obvious without a model call, else
    None. Multi-part requests ("... and then ...") always go to the model so
    plan detection still applies."""
    lowered = prompt.lower()
    if " and then " in lowered or " then " in lowered or lowered.count(",") >= 2:
        return None
    for pattern, persona, tier in _RULES:
        if pattern.search(prompt):
            return persona, tier
    if _last_route and time.monotonic() - _last_route[2] < STICKY_SECONDS and len(prompt.split()) <= STICKY_MAX_WORDS:
        return _last_route[0], _last_route[1]
    return None


def remember_route(persona: str, tier: str) -> None:
    global _last_route
    _last_route = (persona, tier, time.monotonic())


def collapse(persona: str) -> str:
    """The agents the user actually talks to: butler (Mac, music, to-dos) and term (everything else).
    web and docs are tool bundles inside term now; a restricted agent only dead-ends a request."""
    return persona if persona == "butler" else "term"
