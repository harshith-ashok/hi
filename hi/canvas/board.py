"""The drop box canvas, stored as an Obsidian JSON Canvas file: <VAULT_PATH>/hi/canvas/dropbox.canvas.

Open it in Obsidian and it is the same board tinyui shows. Dropped images and audio are saved next to it in
hi/canvas/files/<id>/. Every item is a text or file node; each carries a "hi" block (kind, group, summary, ...)
that Obsidian ignores. Groups are group nodes. Layout is computed here (groups side by side, items stacked
inside), so a node's position is always derived from its group, never stored as a user choice.
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

import hi.config as config

INBOX_LABEL = "Inbox"
GROUP_WIDTH, ITEM_WIDTH, PAD, GAP, LABEL_SPACE = 340, 308, 16, 12, 36
GROUP_GAP = 60
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".oga", ".flac", ".opus", ".webm", ".caf"}
MAX_FILE_BYTES = 200_000_000
_ID = re.compile(r"[0-9a-f]{12}")
_lock = threading.RLock()


def canvas_dir() -> Path:
    return config.VAULT_PATH / "hi" / "canvas"


def canvas_path() -> Path:
    return canvas_dir() / "dropbox.canvas"


def files_root() -> Path:
    return canvas_dir() / "files"


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _load() -> dict:
    try:
        data = json.loads(canvas_path().read_text())
    except (OSError, json.JSONDecodeError):
        data = {}
    return {"nodes": [n for n in data.get("nodes", []) if isinstance(n, dict)], "edges": data.get("edges", [])}


def _save(data: dict) -> None:
    _layout(data)
    canvas_dir().mkdir(parents=True, exist_ok=True)
    tmp = canvas_path().with_suffix(".canvas.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(canvas_path())


def _groups(data: dict) -> list[dict]:
    return [n for n in data["nodes"] if n.get("type") == "group"]


def _items(data: dict) -> list[dict]:
    return [n for n in data["nodes"] if n.get("type") != "group"]


def _inbox(data: dict) -> dict:
    """The Inbox group, created (and listed first) if missing."""
    for group in _groups(data):
        if group.get("label") == INBOX_LABEL:
            return group
    group = {"id": _new_id(), "type": "group", "label": INBOX_LABEL, "x": 0, "y": 0, "width": GROUP_WIDTH, "height": 100}
    data["nodes"].insert(0, group)
    return group


def _height(item: dict) -> int:
    kind = item["hi"]["kind"]
    if kind == "image":
        return 220
    if kind in ("voice", "file"):
        return 90 + min(120, 18 * (len(item["hi"].get("summary", "")) // 38))
    return min(260, 56 + 20 * (len(item.get("text", "")) // 36 + 1))


def _layout(data: dict) -> None:
    """Drop empty groups (never the Inbox), then place groups side by side and items inside them."""
    used = {i["hi"].get("group") for i in _items(data)}
    data["nodes"] = [n for n in data["nodes"] if n.get("type") != "group" or n["id"] in used or n.get("label") == INBOX_LABEL]
    x = 0
    for group in _groups(data):
        y = LABEL_SPACE
        for item in sorted((i for i in _items(data) if i["hi"].get("group") == group["id"]), key=lambda i: i["hi"]["created"]):
            item.update(x=x + PAD, y=y, width=ITEM_WIDTH, height=_height(item))
            y += item["height"] + GAP
        group.update(x=x, y=0, width=GROUP_WIDTH, height=max(y + PAD - GAP, 100))
        x += GROUP_WIDTH + GROUP_GAP


def _view(item: dict) -> dict:
    meta = item["hi"]
    file = item.get("file", "")
    return {
        "id": item["id"], "kind": meta["kind"], "group": meta.get("group"), "created": meta["created"],
        "name": meta.get("name", ""), "text": item.get("text", ""), "summary": meta.get("summary", ""),
        "pending": bool(meta.get("pending")), "url": f"/canvas/files/{item['id']}/{meta['name']}" if file else "",
        "x": item["x"], "y": item["y"], "width": item["width"], "height": item["height"],
    }


def snapshot() -> dict:
    """Everything the UI draws: groups (with position and size) and their items."""
    with _lock:
        data = _load()
        _layout(data)
        items = _items(data)
        return {
            "groups": [{
                "id": g["id"], "label": g["label"], "x": g["x"], "y": g["y"], "width": g["width"], "height": g["height"],
                "items": [_view(i) for i in items if i["hi"].get("group") == g["id"]],
            } for g in _groups(data)],
            "pending": sum(1 for i in items if i["hi"].get("pending")),
        }


def _add(data: dict, node: dict, kind: str, **meta) -> dict:
    node["hi"] = {"kind": kind, "group": _inbox(data)["id"], "created": datetime.now().isoformat(timespec="microseconds"), **meta}
    node["id"] = node.get("id") or _new_id()
    data["nodes"].append(node)
    return node


def add_text(text: str) -> str:
    """Drop a piece of text; returns its id."""
    with _lock:
        data = _load()
        node = _add(data, {"type": "text", "text": text.strip()}, "text")
        _save(data)
        return node["id"]


def _kind_of(name: str, kind: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    return "voice" if kind == "audio" or suffix in AUDIO_SUFFIXES else "file"


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w.\- ]", "_", Path(name.replace("\\", "/")).name).strip(". ") or "file"


def add_file(name: str, stream: BinaryIO, length: int, kind: str = "") -> str:
    """Drop an image, voice note or any file (copied from `stream` to hi/canvas/files/); returns its id.
    The item is marked pending until organise.process has described or transcribed it."""
    if length > MAX_FILE_BYTES:
        raise ValueError(f"{name} is larger than {MAX_FILE_BYTES // 1_000_000} MB")
    item_id, name = _new_id(), _safe_name(name)
    folder = files_root() / item_id
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / name).open("wb") as out:
        shutil.copyfileobj(stream, out, 1_048_576)
    with _lock:
        data = _load()
        relative = (folder / name).relative_to(config.VAULT_PATH).as_posix()
        _add(data, {"id": item_id, "type": "file", "file": relative}, _kind_of(name, kind), name=name, pending=True)
        _save(data)
    return item_id


def file_path(item_id: str, name: str) -> Path | None:
    """The saved file for an item, or None (ids and names are checked, so this cannot leave the canvas folder)."""
    if not _ID.fullmatch(item_id) or name != _safe_name(name):
        return None
    path = files_root() / item_id / name
    return path if path.is_file() else None


def _find(data: dict, item_id: str) -> dict | None:
    return next((n for n in _items(data) if n["id"] == item_id), None)


def get_item(item_id: str) -> dict | None:
    with _lock:
        item = _find(_load(), item_id)
        return None if item is None else {**item, "hi": dict(item["hi"])}


def set_meta(item_id: str, **meta) -> None:
    """Update an item's "hi" block (summary, pending, ...); a no-op if the item was deleted meanwhile."""
    with _lock:
        data = _load()
        if item := _find(data, item_id):
            item["hi"].update(meta)
            _save(data)


def group_for(data: dict, label: str) -> dict:
    """The group called `label` (case-insensitive), created if it does not exist."""
    label = re.sub(r"\s+", " ", label).strip()[:40] or INBOX_LABEL
    for group in _groups(data):
        if group["label"].lower() == label.lower():
            return group
    group = {"id": _new_id(), "type": "group", "label": label, "x": 0, "y": 0, "width": GROUP_WIDTH, "height": 100}
    data["nodes"].append(group)
    return group


def assign(assignments: dict[str, str]) -> int:
    """Move items to groups by label ({item id: label}); labels that do not exist yet become groups. Returns how many moved."""
    with _lock:
        data = _load()
        moved = 0
        for item_id, label in assignments.items():
            if item := _find(data, item_id):
                group = group_for(data, label)
                moved += item["hi"].get("group") != group["id"]
                item["hi"]["group"] = group["id"]
        _save(data)
        return moved


def move_item(item_id: str, group_id: str | None = None, label: str | None = None) -> bool:
    """Move an item to an existing group (by id) or to the group called `label` (created if new)."""
    with _lock:
        data = _load()
        item = _find(data, item_id)
        if item is None:
            return False
        if label:
            item["hi"]["group"] = group_for(data, label)["id"]
        elif any(g["id"] == group_id for g in _groups(data)):
            item["hi"]["group"] = group_id
        else:
            return False
        item["hi"]["manual"] = True  # the user put it here; a later regroup leaves it alone
        _save(data)
        return True


def rename_group(group_id: str, label: str) -> bool:
    label = re.sub(r"\s+", " ", label).strip()[:40]
    with _lock:
        data = _load()
        group = next((g for g in _groups(data) if g["id"] == group_id), None)
        if group is None or not label:
            return False
        group["label"] = label
        _save(data)
        return True


def set_text(item_id: str, text: str) -> bool:
    with _lock:
        data = _load()
        item = _find(data, item_id)
        if item is None or item["type"] != "text" or not text.strip():
            return False
        item["text"] = text.strip()
        _save(data)
        return True


def delete_item(item_id: str) -> bool:
    with _lock:
        data = _load()
        item = _find(data, item_id)
        if item is None:
            return False
        data["nodes"].remove(item)
        _save(data)
    if _ID.fullmatch(item_id):
        shutil.rmtree(files_root() / item_id, ignore_errors=True)
    return True


def pending_ids() -> list[str]:
    with _lock:
        return [i["id"] for i in _items(_load()) if i["hi"].get("pending")]


def inbox_items(only_new: bool = True) -> list[dict]:
    """Items waiting to be sorted: those in the Inbox, or (only_new=False) every item the user has not placed by hand."""
    with _lock:
        data = _load()
        inbox_id = _inbox(data)["id"]
        return [{**i, "hi": dict(i["hi"])} for i in _items(data)
                if (i["hi"].get("group") == inbox_id if only_new else not i["hi"].get("manual"))]


def group_labels() -> list[str]:
    with _lock:
        return [g["label"] for g in _groups(_load()) if g["label"] != INBOX_LABEL]
