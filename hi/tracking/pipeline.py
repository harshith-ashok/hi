"""Generic named-pipeline tracker (TODO.md Phase 4 item 7, "Logic Play
recruitment/event pipeline tracker"): rather than guessing what stages a
specific named pipeline like "Logic Play" actually uses — a recruitment
funnel and an event lifecycle are genuinely different shapes, and this
codebase has zero information about either — this builds the reusable
mechanism instead: create_pipeline(name, stages) once, then add/move/
list entries through those stages. Any pipeline shaped like "named things
moving through ordered stages" can be tracked the moment its real stages
are known, without more code.

hi/tracking/applications.py stays a separate, bespoke tracker rather than
being rebuilt on top of this: it has domain-specific fields (date_sent,
resume version) a generic pipeline entry doesn't need, and unifying them
would trade away real domain fit for a small amount of code reuse.
"""

from __future__ import annotations

import re
from pathlib import Path

from langchain_core.tools import tool

from hi.config import VAULT_PATH
from hi.frontmatter import dump_frontmatter, parse_frontmatter

PIPELINES_DIR = VAULT_PATH / "hi" / "tasks" / "pipelines"
_META_STEM = "_meta"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-") or "item"


def _pipeline_dir(name: str) -> Path:
    return PIPELINES_DIR / _slugify(name)


def _meta_path(name: str) -> Path:
    return _pipeline_dir(name) / f"{_META_STEM}.md"


def _load_stages(name: str) -> list[str] | None:
    meta_path = _meta_path(name)
    if not meta_path.exists():
        return None
    fields, _body = parse_frontmatter(meta_path.read_text())
    stages = fields.get("stages")
    return stages if isinstance(stages, list) else None


@tool
def create_pipeline(name: str, stages: list[str]) -> str:
    """Create a new named pipeline with an ordered list of stages — use
    this once before tracking entries in it, e.g. a recruitment funnel
    (["applied", "interview", "accepted", "rejected"]) or an event's
    lifecycle (["planning", "promotion", "running", "done"]).

    Args:
        name: A short name for the pipeline, e.g. "Logic Play recruitment".
        stages: Ordered stage names.
    """
    if not stages:
        return "A pipeline needs at least one stage."
    directory = _pipeline_dir(name)
    directory.mkdir(parents=True, exist_ok=True)
    _meta_path(name).write_text(
        dump_frontmatter({"tags": ["hi", "pipeline"], "name": name, "stages": stages})
    )
    return f"Created pipeline '{name}' with stages: {', '.join(stages)}."


@tool
def add_pipeline_entry(pipeline: str, entry: str, notes: str = "") -> str:
    """Add a new entry to a pipeline, starting at its first stage.

    Args:
        pipeline: The pipeline's name, e.g. "Logic Play recruitment".
        entry: The entry's name, e.g. a candidate or event name.
        notes: Optional free-text notes.
    """
    stages = _load_stages(pipeline)
    if stages is None:
        return f"No pipeline named '{pipeline}' — create it first with create_pipeline."
    path = _pipeline_dir(pipeline) / f"{_slugify(entry)}.md"
    fields: dict[str, str | list[str]] = {
        "tags": ["hi", "pipeline-entry"],
        "entry": entry,
        "stage": stages[0],
    }
    body = f"# {entry}\n\n{notes}\n" if notes else f"# {entry}\n"
    path.write_text(f"{dump_frontmatter(fields)}\n{body}")
    return f"Added '{entry}' to '{pipeline}' at stage '{stages[0]}'."


def _find_entry(directory: Path, entry: str) -> Path | None:
    return next(
        (p for p in directory.glob("*.md") if p.stem != _META_STEM and entry.lower() in p.stem.lower()),
        None,
    )


@tool
def update_pipeline_entry_stage(pipeline: str, entry: str, stage: str) -> str:
    """Move a pipeline entry to a different stage.

    Args:
        pipeline: The pipeline's name.
        entry: Text identifying the entry, matched case-insensitively.
        stage: The stage to move it to — must be one of the pipeline's configured stages.
    """
    stages = _load_stages(pipeline)
    if stages is None:
        return f"No pipeline named '{pipeline}'."
    if stage not in stages:
        return f"Invalid stage '{stage}' for '{pipeline}'. Stages: {', '.join(stages)}."

    match = _find_entry(_pipeline_dir(pipeline), entry)
    if match is None:
        return f"No entry matching '{entry}' in '{pipeline}'."

    fields, body = parse_frontmatter(match.read_text())
    fields["stage"] = stage
    match.write_text(f"{dump_frontmatter(fields)}\n{body}")
    return f"Moved '{fields.get('entry', entry)}' to '{stage}'."


@tool
def list_pipeline_entries(pipeline: str, stage: str | None = None) -> str:
    """List entries in a pipeline, optionally filtered to one stage.

    Args:
        pipeline: The pipeline's name.
        stage: Optional stage to filter to. Omit for every entry.
    """
    directory = _pipeline_dir(pipeline)
    if not directory.is_dir():
        return f"No pipeline named '{pipeline}'."
    lines = []
    for path in sorted(directory.glob("*.md")):
        if path.stem == _META_STEM:
            continue
        fields, _body = parse_frontmatter(path.read_text())
        entry_stage = fields.get("stage", "?")
        if stage and entry_stage != stage:
            continue
        lines.append(f"{fields.get('entry', path.stem)} — {entry_stage}")
    return "\n".join(lines) if lines else f"No entries{f' in stage {stage}' if stage else ''}."
