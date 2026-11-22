"""Understand what was dropped, then file it into a group.

Images are described by the vision model, voice notes transcribed, other files read as text. A small model then
puts each item in an existing group or a new one. If the model is down the items stay in the Inbox (and the
failure shows in GET /health); nothing is lost.
"""

from __future__ import annotations

import json
import logging
import re
import threading

from langchain_core.messages import HumanMessage

from hi import attachments
from hi.canvas import board
from hi.core import health
from hi.llm.registry import get_tier_model_fast
from hi.llm.resilience import invoke_with_retry

log = logging.getLogger(__name__)
DEP = "canvas_organiser"
BATCH = 25
SNIPPET = 400
_work = threading.Lock()  # one description/grouping pass at a time, so drops do not pile model calls on each other

_PROMPT = """You sort a person's quick notes, images and voice notes into named groups on a board.
Existing groups: {groups}
For each item below, choose the best existing group, or invent a new short group name (1-3 words, e.g. "Trip planning",
"Project ideas", "Groceries"). Related items must share a group name, spelled identically. Use "{inbox}" only when
an item is too vague to place.
Reply with ONLY a JSON object mapping each item id to its group name.

Items:
{items}"""


def describe(item_id: str) -> None:
    """Fill in the summary of a dropped file (what the image shows, what the voice note says) and clear its pending flag."""
    item = board.get_item(item_id)
    if item is None or item["type"] != "file":
        board.set_meta(item_id, pending=False)
        return
    path = board.file_path(item_id, item["hi"]["name"])
    summary = attachments.read_file(path, "audio" if item["hi"]["kind"] == "voice" else "") if path else "(file missing)"
    board.set_meta(item_id, summary=summary.strip()[:4000], pending=False)


def _label(item: dict) -> str:
    text = item.get("text") or item["hi"].get("summary", "")
    name = item["hi"].get("name", "")
    return f"[{item['hi']['kind']}{' ' + name if name else ''}] {re.sub(chr(10), ' ', text)[:SNIPPET]}"


def _parse(reply: str) -> dict[str, str]:
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    try:
        data = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, str) and v.strip()} if isinstance(data, dict) else {}


def organise(regroup: bool = False) -> int:
    """File waiting items into groups; with regroup, reconsider every item not placed by hand. Returns how many moved."""
    items = [i for i in board.inbox_items(only_new=not regroup) if not i["hi"].get("pending")]
    moved = 0
    for start in range(0, len(items), BATCH):
        batch = items[start:start + BATCH]
        prompt = _PROMPT.format(
            groups=", ".join(board.group_labels()) or "(none yet)", inbox=board.INBOX_LABEL,
            items="\n".join(f"{i['id']}: {_label(i)}" for i in batch),
        )
        try:
            reply = invoke_with_retry(get_tier_model_fast("haiku"), [HumanMessage(prompt)])
            health.mark_ok(DEP)
        except Exception as e:  # boundary: the model being down must not lose the drop
            health.mark_down(DEP, e)
            log.warning("canvas organiser failed: %s", e)
            return moved
        known = {i["id"] for i in batch}
        moved += board.assign({k: v for k, v in _parse(reply).items() if k in known})
    return moved


def process(item_id: str | None = None) -> None:
    """Describe what is pending, then file the new items. Safe to call from a background thread."""
    with _work:
        for pending in ([item_id] if item_id else board.pending_ids()):
            try:
                describe(pending)
            except Exception:  # boundary: one unreadable file must not stop the rest
                log.exception("could not describe canvas item %s", pending)
                board.set_meta(pending, pending=False, summary="(could not be read)")
        organise()
