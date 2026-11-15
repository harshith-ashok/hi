"""Visualise: the model explains a topic by drawing it.

`visualise()` takes an SVG the model wrote, strips anything active, saves it under <vault>/hi/plots/ and
returns the /plots/<name>.svg path the UI already knows how to show inline (same route as chart PNGs)."""

import re
from datetime import datetime

from langchain_core.tools import tool

from hi.memory.vault import plots_dir

MAX_SVG_BYTES = 200_000
_ACTIVE = re.compile(r"<(script|foreignObject|iframe|object|embed)\b.*?(</\1\s*>|/>)", re.IGNORECASE | re.DOTALL)
_HANDLERS = re.compile(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*')", re.IGNORECASE)
_EXTERNAL = re.compile(r"""(href|src)\s*=\s*["'](?!#)[^"']*["']""", re.IGNORECASE)


def clean_svg(svg: str) -> str | None:
    """The SVG with scripts, event handlers and external references removed, or None if it isn't an SVG."""
    match = re.search(r"<svg\b.*</svg>", svg, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    cleaned = _EXTERNAL.sub("", _HANDLERS.sub("", _ACTIVE.sub("", match.group(0))))
    if "xmlns=" not in cleaned[:300]:
        cleaned = cleaned.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    return cleaned


@tool
def visualise(svg: str, title: str = "diagram") -> str:
    """Explain something visually by drawing it. Shows a diagram in the UI.

    Use for "explain X", "how does X work", "visualise X": flows, architectures, cycles, comparisons,
    timelines. Draw a clear diagram: a viewBox (e.g. 0 0 800 500), a white background rect, labelled boxes,
    arrows, readable text (font-size 14+). No scripts, no external images or fonts.

    Args:
        svg: A complete, self-contained <svg>...</svg> document.
        title: Short name of what is being explained.
    """
    cleaned = clean_svg(svg)
    if cleaned is None:
        return "That was not a valid <svg> document; send a complete <svg>...</svg>."
    if len(cleaned.encode()) > MAX_SVG_BYTES:
        return "That SVG is too large; simplify the diagram and try again."
    slug = re.sub(r"[^\w-]+", "-", title.lower()).strip("-")[:40] or "diagram"
    name = f"{slug}-{datetime.now():%H%M%S}.svg"
    plots_dir().mkdir(parents=True, exist_ok=True)
    (plots_dir() / name).write_text(cleaned)
    return f"Diagram '{title}' is already displayed to the user in the UI (do not embed or link it): /plots/{name}"
