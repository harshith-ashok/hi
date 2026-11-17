"""Reports: the full text of what a background run produced, kept as Markdown in the vault.

    <vault>/hi/reports/YYYY-MM-DD/HHMM-<slug>.md   frontmatter {id, origin, headline, priority, ...} + the body

A report is where the detail goes; the island and notifications only get its one-line headline (see
hi/automation/deliver.py). Everything written here is redacted first, because a report may be synced or shared.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import hi.config as config
from hi.core.redact import redact
from hi.memory.frontmatter import parse_frontmatter, with_frontmatter

_ID = re.compile(r"\d{8}-\d{4}-[a-z0-9-]{1,60}(?:-\d+)?")


def reports_dir() -> Path:
    return config.VAULT_PATH / "hi" / "reports"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "report"


def _one_line(text: str) -> str:
    line = re.sub(r"\s+", " ", text).strip()
    return "(" + line[1:] if line.startswith("[") else line  # a leading "[" would read back as a list


def _path_for(report_id: str) -> Path | None:
    if not _ID.fullmatch(report_id):
        return None
    day = f"{report_id[:4]}-{report_id[4:6]}-{report_id[6:8]}"
    return reports_dir() / day / f"{report_id[9:13]}-{report_id[14:]}.md"


def write_report(
    origin: str, headline: str, body: str, links: Iterable[str] = (), proposals: Iterable[str] = (),
    priority: str = "normal", now: datetime | None = None,
) -> tuple[str, Path]:
    """Save a report and return (id, path)."""
    now = now or datetime.now()
    headline = redact(_one_line(headline), config.secret_values())
    slug = _slug(headline)
    report_id, n = f"{now:%Y%m%d-%H%M}-{slug}", 1
    while (path := _path_for(report_id)) is not None and path.exists():
        n += 1
        report_id = f"{now:%Y%m%d-%H%M}-{slug}-{n}"
    path = _path_for(report_id)
    assert path is not None
    fields: dict = {
        "id": report_id, "origin": origin, "headline": headline, "priority": priority,
        "created": now.isoformat(timespec="seconds"), "tags": ["hi", "report"],
    }
    if proposals := list(proposals):
        fields["proposals"] = proposals
    text = redact(body.strip(), config.secret_values())
    if links := list(links):
        text += "\n\n" + " ".join(links)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(with_frontmatter(f"# {headline}\n\n{text}\n", fields))
    return report_id, path


def _summary(path: Path) -> dict:
    fields, _ = parse_frontmatter(path.read_text(errors="ignore"))
    return {k: fields.get(k, "") for k in ("id", "origin", "headline", "priority", "created", "proposals")}


def list_reports(day: date | None = None, limit: int = 50) -> list[dict]:
    """Newest first; one day, or the most recent days."""
    root = reports_dir()
    if not root.exists():
        return []
    folders = [root / day.isoformat()] if day else sorted((d for d in root.iterdir() if d.is_dir()), reverse=True)
    found: list[dict] = []
    for folder in folders:
        for path in sorted(folder.glob("*.md"), reverse=True):
            found.append(_summary(path))
            if len(found) >= limit:
                return found
    return found


def read_report(report_id: str) -> dict | None:
    """The report's summary fields plus its Markdown `body`, or None."""
    path = _path_for(report_id)
    if path is None or not path.is_file():
        return None
    return {**_summary(path), "body": parse_frontmatter(path.read_text(errors="ignore"))[1]}


def recent_headlines(limit: int = 8) -> list[str]:
    """What was prepared lately, so the heartbeat does not prepare the same thing twice."""
    return [r["headline"] for r in list_reports(limit=limit) if r["headline"]]
