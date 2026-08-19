"""Shared note-content preview generation, used by both grounding graphs
(`hi/memory_graph.py` for `term`, `hi/agents/docs/vault_rag.py` for
`docs`) so their relevance-selection prompts can see a hint of a note's
actual content, not just its filename.

This is `BLOCKERS.md` #4's "cheapest fix, do first" (9a in `TODO.md`):
both grounding graphs previously asked a model "which of these bare
paths look relevant" with zero content visible — a note titled
`misc.md` could never be selected no matter how relevant its content
was, since nothing about what's *in* the note was ever shown. A full
local keyword-scoring pass or embedding index (9b/9c) are real, separate,
larger pieces of work for genuine scale; this is the one-line-per-note
preview that makes the existing single-LLM-call selection step actually
content-aware instead of title-only, at near-zero added cost.
"""

from __future__ import annotations

from hi.frontmatter import parse_frontmatter

PREVIEW_CHARS = 220


def note_preview(content: str) -> str:
    """A short preview of a note's actual content: its first heading (if
    any) plus the start of the first real paragraph after it, truncated.
    Falls back to the first non-empty text if there's no heading."""
    _fields, body = parse_frontmatter(content)
    lines = [line.strip() for line in body.splitlines()]

    heading = next((line.lstrip("#").strip() for line in lines if line.startswith("#")), None)
    paragraph_lines = [line for line in lines if line and not line.startswith("#")]
    paragraph = " ".join(paragraph_lines)[:PREVIEW_CHARS]

    if heading and paragraph:
        return f"{heading} — {paragraph}"
    if heading:
        return heading
    return paragraph or "(empty)"
