"""Resume/application tracker: one Markdown file per application under
<VAULT_PATH>/hi/tasks/applications/, frontmatter target/status/date_sent/
version — same one-file-per-item pattern as hi/capture/store.py's tasks,
just a different, more specific schema. due_follow_ups() feeds
hi/briefing.py the same way hi/watchdogs/idle_repos.py and
hi/tracking/deadlines.py do.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from langchain_core.tools import tool

import hi.config as config
from hi.frontmatter import dump_frontmatter, parse_frontmatter

def _applications_dir():
    return config.VAULT_PATH / "hi" / "tasks" / "applications"

STATUSES = ("applied", "OA", "interview", "rejected", "offer")
FOLLOW_UP_DAYS_DEFAULT = 7

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-") or "application"


@dataclass
class Application:
    target: str
    status: str = "applied"
    date_sent: str = field(default_factory=lambda: date.today().isoformat())
    version: str | None = None
    notes: str = ""

    @property
    def slug(self) -> str:
        return _slugify(self.target)

    def path(self) -> Path:
        return _applications_dir() / f"{self.slug}.md"

    def save(self) -> Path:
        _applications_dir().mkdir(parents=True, exist_ok=True)
        fields: dict[str, str | list[str]] = {
            "tags": ["hi", "application"],
            "target": self.target,
            "status": self.status,
            "date_sent": self.date_sent,
        }
        if self.version:
            fields["version"] = self.version
        body = f"# {self.target}\n\n{self.notes}\n" if self.notes else f"# {self.target}\n"
        path = self.path()
        path.write_text(f"{dump_frontmatter(fields)}\n{body}")
        return path


def _load(path: Path) -> Application:
    fields, body = parse_frontmatter(path.read_text())
    notes = "\n".join(
        line for line in body.splitlines() if line.strip() and not line.strip().startswith("#")
    ).strip()
    version = fields.get("version")
    return Application(
        target=str(fields.get("target", path.stem)),
        status=str(fields.get("status", "applied")),
        date_sent=str(fields.get("date_sent", "")),
        version=version if isinstance(version, str) else None,
        notes=notes,
    )


def list_applications_data() -> list[Application]:
    if not _applications_dir().is_dir():
        return []
    return [_load(p) for p in sorted(_applications_dir().glob("*.md"))]


def find_application(target: str) -> Application | None:
    for app in list_applications_data():
        if target.lower() in app.target.lower():
            return app
    return None


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def due_follow_ups(days: int = FOLLOW_UP_DAYS_DEFAULT) -> list[Application]:
    """Applications still marked "applied" with no status update in
    `days` days — a nudge to check in, never an automatic action."""
    cutoff = date.today() - timedelta(days=days)
    due = []
    for app in list_applications_data():
        if app.status != "applied":
            continue
        sent = _parse_date(app.date_sent)
        if sent and sent <= cutoff:
            due.append(app)
    return due


@tool
def add_application(
    target: str,
    status: str = "applied",
    date_sent: str | None = None,
    version: str | None = None,
) -> str:
    """Track a new job/internship application.

    Args:
        target: Company and/or role, e.g. "Acme - Backend Intern".
        status: One of applied/OA/interview/rejected/offer. Defaults to "applied".
        date_sent: ISO date it was sent, e.g. "2026-09-04". Defaults to today.
        version: Optional resume version used, e.g. "v3-backend".
    """
    if status not in STATUSES:
        return f"Invalid status '{status}'. Use one of: {', '.join(STATUSES)}."
    app = Application(target=target, status=status, date_sent=date_sent or date.today().isoformat(), version=version)
    app.save()
    return f"Tracking application: {target} ({status})."


@tool
def update_application_status(target: str, status: str) -> str:
    """Update an existing application's status, matched by partial,
    case-insensitive text against its target.

    Args:
        target: Text identifying the application, e.g. "Acme".
        status: One of applied/OA/interview/rejected/offer.
    """
    if status not in STATUSES:
        return f"Invalid status '{status}'. Use one of: {', '.join(STATUSES)}."
    app = find_application(target)
    if not app:
        return f"No application matching '{target}' found."
    app.status = status
    app.save()
    return f"Updated {app.target}: {status}."


@tool
def list_applications() -> str:
    """List every tracked application with its current status."""
    apps = list_applications_data()
    if not apps:
        return "No applications tracked yet."
    return "\n".join(f"{a.target} — {a.status} (sent {a.date_sent})" for a in apps)
