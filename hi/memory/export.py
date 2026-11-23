"""A chat as one Markdown document: what you asked and what hi answered, on the branch that is showing."""

from __future__ import annotations

import re

from hi.memory import artifacts, projects, sessions, transcript


def filename(title: str) -> str:
    """A safe file name for the export (no extension)."""
    return re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")[:60] or "chat"


def markdown(session_id: str) -> str | None:
    """The chat as Markdown, or None when there is no such chat."""
    s = sessions.get(session_id)
    if s is None:
        return None
    project = projects.get(s.project) if s.project else None
    made = artifacts.by_turn(s.id)
    lines = [f"# {s.title}", ""]
    if s.created:
        lines.append(f"*Started {s.created.replace('T', ' ')}*" + (f" · project: {project.name}" if project else ""))
        lines.append("")
    for turn in transcript.session_path(s.id, s.head):
        lines += ["## You", "", str(turn.get("ask", "")).strip(), ""]
        answer = str(turn.get("answer") or "").strip()
        if answer:
            lines += ["## hi", "", answer, ""]
        elif turn.get("error") not in ("", None, "stopped"):
            lines += ["## hi", "", f"*(no answer: {turn['error']})*", ""]
        for a in made.get(turn.get("id", ""), []):
            lines.append(f"> Artifact: {a['title']} (version {a['version']}), saved as `hi/artifacts/{s.id}/{a['slug']}/v{a['version']}` in the vault")
        if made.get(turn.get("id", "")):
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
