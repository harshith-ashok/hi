"""The drop folder: save a file, and `hi` reads it, files it as a note, and adds its action items to your tasks.

    <vault>/hi/drop/                  put files here (Finder, or "Save to Files" on the iPhone: the vault is in iCloud)
    <vault>/hi/drop/notes/            the notes `hi` wrote: summary, action items, the extracted text
    <vault>/hi/drop/processed/YYYY-MM/  the originals, once filed
    <vault>/hi/drop/index.jsonl       {sha256, name, note, ts}: a file already filed is moved, never filed twice

A file is read only once it has stopped changing between two polls (a download or an iCloud sync may still be writing).
Documents, images and audio are read by hi/attachments.py. A model writes a title, a summary and the action items as
JSON; code writes the note and the tasks, so nothing here can touch more than the drop folder and your task list.
A file that cannot be read stays where it is, is reported once, and is retried with a growing delay.

With SCREENSHOT_WATCH on, new macOS screenshots on the Desktop are described the same way (local vision model only,
and the originals are left alone).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import hi.config as config
from hi import attachments
from hi.automation import limits
from hi.automation.deliver import Delivery, deliver
from hi.automation.worker import get_worker
from hi.core.redact import redact
from hi.llm import registry

log = logging.getLogger(__name__)

POLL_S = 60
STUCK_AFTER_S = 600
MAX_BACKOFF_S = 3600
MODEL_TEXT_CHARS = 12000
NOTE_TEXT_CHARS = 20000
MAX_TASKS = 5
PARTIAL = (".download", ".part", ".crdownload", ".tmp", ".partial")
SCREENSHOT = re.compile(r"^(Screenshot|Screen Shot) .*\.(png|jpg|jpeg)$", re.IGNORECASE)
UNREADABLE = ("(could not", "(binary file", "(this PDF has no text layer", "(no speech found)", "(audio is too large",
              "(file is ", "(image is ")

_PROMPT = """A file was saved to the user's drop folder. Read it and reply with JSON only (no code fence):
{{"title": "at most 8 words", "summary": "2 to 4 plain sentences", "tasks": ["things the USER must do, only if clearly stated, imperative, at most {tasks}"], "folder": "a folder name in their notes where it belongs, or empty"}}

File: {name} ({kind})
Text:
{text}"""


@dataclass
class _Seen:
    size: int
    mtime: float


@dataclass
class _Failure:
    first: float
    count: int
    retry_at: float


_seen: dict[str, _Seen] = {}
_failures: dict[str, _Failure] = {}
_started_at: float | None = None


def drop_dir() -> Path:
    return Path(config.DROP_PATH) if config.DROP_PATH else config.VAULT_PATH / "hi" / "drop"


def index_path() -> Path:
    return drop_dir() / "index.jsonl"


def _kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in attachments.AUDIO_TYPES:
        return "voice memo"
    if suffix in attachments.IMAGE_TYPES:
        return "photo"
    return "document"


def candidates(folder: Path | None = None) -> list[Path]:
    """Files directly in the drop folder that could be filed: no folders, dotfiles, iCloud placeholders or partial
    downloads."""
    folder = folder or drop_dir()
    try:
        entries = sorted(folder.iterdir())
    except OSError:
        return []
    return [p for p in entries if p.is_file() and not p.name.startswith(".") and p.suffix.lower() not in PARTIAL
            and p.name != "index.jsonl"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _index() -> dict[str, dict]:
    try:
        lines = index_path().read_text().splitlines()
    except OSError:
        return {}
    found = {}
    for line in lines:
        try:
            entry = json.loads(line)
            found[entry["sha256"]] = entry
        except (ValueError, KeyError):
            continue
    return found


def _index_add(digest: str, name: str, note: str) -> None:
    index_path().parent.mkdir(parents=True, exist_ok=True)
    with index_path().open("a") as f:
        f.write(json.dumps({"sha256": digest, "name": name, "note": note, "ts": time.time()}) + "\n")


def is_stable(path: Path) -> bool:
    """True once the file's size and modified time are the same as at the previous poll."""
    stat = path.stat()
    now = _Seen(stat.st_size, stat.st_mtime)
    previous = _seen.get(str(path))
    _seen[str(path)] = now
    return previous is not None and previous == now and stat.st_size > 0


def stuck_files(now: datetime | None = None) -> list[str]:
    """Names of files that failed to be filed and have been waiting over ten minutes."""
    now_ts = now.timestamp() if now else time.time()
    present = {p.name for p in candidates()}
    return sorted(name for name, f in _failures.items() if name in present and now_ts - f.first > STUCK_AFTER_S)


# --- reading and filing -----------------------------------------------------------------------------------------

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "note"


def _clean_json(reply: str) -> dict:
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    try:
        data = json.loads(match.group(0)) if match else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def summarize(name: str, kind: str, text: str, model_fn: Callable[[str], str] | None = None) -> dict:
    """{title, summary, tasks, folder, summarized}. Falls back to the file name and the start of the text when the
    model is unavailable, so a file is still filed."""
    fallback = {"title": Path(name).stem.replace("_", " ")[:60], "summary": " ".join(text.split())[:300], "tasks": [],
                "folder": "", "summarized": False}
    try:
        prompt = _PROMPT.format(name=name, kind=kind, text=text[:MODEL_TEXT_CHARS], tasks=MAX_TASKS)
        data = _clean_json((model_fn or _default_model)(prompt))
    except Exception as e:  # boundary: no model is a degraded note, not a failed file
        log.warning("could not summarize %s: %s", name, e)
        return fallback
    tasks = [str(t).strip() for t in data.get("tasks", []) if isinstance(t, str) and t.strip()][:MAX_TASKS]
    title, summary = str(data.get("title", "")).strip(), str(data.get("summary", "")).strip()
    if not title or not summary:
        return fallback
    return {"title": title[:80], "summary": summary[:800], "tasks": tasks,
            "folder": str(data.get("folder", "")).strip()[:60], "summarized": True}


def _default_model(prompt: str) -> str:
    from langchain_core.messages import HumanMessage

    from hi.llm.resilience import invoke_with_retry

    tier = limits.choose_tier("haiku")
    if tier is None:
        raise RuntimeError("no model allowed by the hosted-model limit")
    started = time.time()
    reply = invoke_with_retry(registry.get_tier_model_fast(tier), [HumanMessage(prompt)])
    limits.record("drop", tier, not registry.is_local(tier), 0, time.time() - started)
    return reply


def _write_note(title: str, kind: str, name: str, digest: str, info: dict, text: str, source: str, now: datetime) -> Path:
    from hi.memory.frontmatter import with_frontmatter

    notes = drop_dir() / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    path, n = notes / f"{now:%Y-%m-%d}-{_slug(title)}.md", 1
    while path.exists():
        n += 1
        path = notes / f"{now:%Y-%m-%d}-{_slug(title)}-{n}.md"
    parts = [f"# {title}", "", info["summary"] or "(no summary)"]
    if info["tasks"]:
        parts += ["", "## Action items", *[f"- [ ] {t}" for t in info["tasks"]]]
    if info.get("folder"):
        parts += ["", f"Suggested folder: {info['folder']}"]
    parts += ["", f"Source: {source}" if source else "", "", "## Extracted text", "", redact(text[:NOTE_TEXT_CHARS], config.secret_values())]
    fields = {"tags": ["hi", "drop"], "kind": kind, "file": name, "sha256": digest[:16],
              "created": now.isoformat(timespec="seconds")}
    path.write_text(with_frontmatter("\n".join(parts).rstrip() + "\n", fields))
    return path


def _add_tasks(tasks: list[str]) -> int:
    from hi.capture.schema import Task
    from hi.capture.store import list_items, save

    existing = {t.text.strip().lower() for t in list_items(kind="task") if getattr(t, "status", "") == "pending"}
    added = 0
    for text in tasks:
        if text.strip().lower() not in existing:
            save(Task(text=text, source_persona="drop"))
            added += 1
    return added


def _archive_target(path: Path, now: datetime) -> Path:
    """Where `path` will be kept once filed (not moved yet: the note is written first, so a crash never loses a file)."""
    folder = drop_dir() / "processed" / f"{now:%Y-%m}"
    target, n = folder / path.name, 1
    while target.exists():
        n += 1
        target = folder / f"{path.stem}-{n}{path.suffix}"
    return target


def _archive(path: Path, now: datetime) -> Path:
    target = _archive_target(path, now)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(target))
    return target


def process(path: Path, now: datetime, deliver_fn=deliver, model_fn=None, keep_original: bool = False,
            read_fn: Callable[[Path, str], str] | None = None) -> str:
    """File one stable file. Returns "filed", "duplicate" or "failed"."""
    name, kind = path.name, _kind(path)
    digest = sha256(path)
    index = _index()
    if digest in index:  # already filed once: just get it out of the way
        if not keep_original:
            _archive(path, now)
        _failures.pop(name, None)
        return "duplicate"
    text = (read_fn or attachments.read_file)(path, "audio" if kind == "voice memo" else "")
    if not text.strip() or text.startswith(UNREADABLE):
        _record_failure(name, digest, text.strip() or "(empty)", deliver_fn)
        return "failed"
    info = summarize(name, kind, text, model_fn)
    tasks_added = _add_tasks(info["tasks"])
    source, target = "", None if keep_original else _archive_target(path, now)
    if target is not None:
        source = f"[[{target.relative_to(config.VAULT_PATH).as_posix()}]]" if target.is_relative_to(config.VAULT_PATH) else str(target)
    note = _write_note(info["title"], kind, name, digest, info, text, source, now)
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
    _index_add(digest, name, note.name)
    _failures.pop(name, None)
    headline = f"Filed {kind}: {info['title']}" + (f", {tasks_added} task{'s' * (tasks_added != 1)} added" if tasks_added else "")
    body = f"{info['summary']}\n\nNote: [[{note.relative_to(config.VAULT_PATH).as_posix()}]]" if note.is_relative_to(config.VAULT_PATH) else info["summary"]
    if not info["summarized"]:
        body += "\n\n(No summary: the model was not available. The text is in the note.)"
    deliver_fn(Delivery(headline=headline, body=body, kind="info", origin="drop", dedupe_key=f"drop:{digest}"))
    return "filed"


def _record_failure(name: str, digest: str, reason: str, deliver_fn) -> None:
    now = time.time()
    failure = _failures.get(name)
    count = (failure.count if failure else 0) + 1
    _failures[name] = _Failure(failure.first if failure else now, count, now + min(POLL_S * 2 ** count, MAX_BACKOFF_S))
    if count == 1:  # said once; the retries are silent
        deliver_fn(Delivery(headline=f"Could not read {name}: {reason[:80]}", kind="failure", origin="drop",
                            dedupe_key=f"drop-fail:{digest}"))


# --- the polls ----------------------------------------------------------------------------------------------------

def poll(now: datetime | None = None, deliver_fn=deliver, submit=None, model_fn=None) -> list[str]:
    """Queue every stable, ready file in the drop folder. Returns their names."""
    now = now or datetime.now()
    submit = submit or get_worker().submit
    queued = []
    for path in candidates():
        failure = _failures.get(path.name)
        if failure and time.time() < failure.retry_at:
            continue
        try:
            ready = is_stable(path)
        except OSError:
            continue
        if ready:
            queued.append(path.name)
            submit(f"drop:{path}", lambda p=path: _safe_process(p, now, deliver_fn, model_fn))
    for gone in [k for k in _seen if not Path(k).exists()]:
        _seen.pop(gone, None)
    return queued


def _safe_process(path: Path, now: datetime, deliver_fn, model_fn, keep_original: bool = False) -> None:
    try:
        process(path, now, deliver_fn, model_fn, keep_original)
    except Exception as e:  # boundary: one bad file must not stop the others
        log.exception("could not file %s", path.name)
        _record_failure(path.name, path.name, f"{type(e).__name__}: {e}", deliver_fn)


def accept(source: Path) -> Path:
    """Copy `source` into the drop folder so the next poll files it (tinyui's "File it" on an attachment). The copy
    keeps the name; a clash gets a number."""
    folder = drop_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target, n = folder / source.name, 1
    while target.exists():
        n += 1
        target = folder / f"{source.stem}-{n}{source.suffix}"
    shutil.copy2(source, target)
    return target


def screenshot_dir() -> Path:
    home = os.environ.get("HI_HOST_HOME")
    return (Path(home) if home else Path.home()) / "Desktop"


def vision_is_local(model: str | None = None) -> tuple[bool, str]:
    """(local, why not). Screenshots can show anything, so only a local vision model may read them."""
    model = model or config.VISION_MODEL
    if "cloud" in model:
        return False, f"the vision model ({model}) is hosted; set a local one first"
    return True, ""


def screenshots_allowed() -> tuple[bool, str]:
    """(allowed, why not)."""
    if not config.SCREENSHOT_WATCH:
        return False, "SCREENSHOT_WATCH is off"
    return vision_is_local()


def poll_screenshots(now: datetime | None = None, deliver_fn=deliver, submit=None, model_fn=None) -> list[str]:
    """New screenshots on the Desktop, described and filed. The files themselves stay where they are."""
    global _started_at
    allowed, _ = screenshots_allowed()
    if not allowed:
        return []
    now = now or datetime.now()
    _started_at = _started_at or time.time()
    submit = submit or get_worker().submit
    queued = []
    for path in candidates(screenshot_dir()):
        try:
            if not SCREENSHOT.match(path.name) or path.stat().st_mtime < _started_at or not is_stable(path):
                continue
            if sha256(path) in _index():
                continue
        except OSError:
            continue
        queued.append(path.name)
        submit(f"shot:{path}", lambda p=path: _safe_process(p, now, deliver_fn, model_fn, keep_original=True))
    return queued


def start() -> None:
    from hi.core import jobs

    jobs.every("drop", POLL_S, lambda: (poll(), poll_screenshots()))
