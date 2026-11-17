"""How the result of a background run reaches you: the detail goes to a report in the vault, a one-line headline goes
to the island (or a macOS notification), and approvals can be answered from there.

    deliver(Delivery(...))   writes the report (if there is a body), then posts the headline through the gate
                             (hi/context/inbox.py), which dedupes and keeps to the interruption budget.

If the Mac cannot be reached the report is still written: you lose the pop-up, never the work.
"""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass, field
from typing import Callable, NamedTuple

import hi.config as config
from hi.core import health
from hi.core.redact import redact
from hi.memory import proposals as proposal_store
from hi.memory import reports

log = logging.getLogger(__name__)

MAX_HEADLINE_WORDS = 25
_BRIDGE_DOWN = ("Can't reach", "The Mac bridge", "Mac bridge error")


@dataclass(frozen=True)
class Delivery:
    headline: str  # plain text, at most 25 words
    body: str = ""  # Markdown; becomes the report
    kind: str = "info"  # info | digest | approval | reminder | failure
    priority: str = "normal"  # low | normal | urgent
    dedupe_key: str = ""  # the same key is shown once per day
    origin: str = ""
    proposals: tuple[str, ...] = ()
    links: tuple[str, ...] = ()
    payload: dict = field(default_factory=dict)  # for the island: action_id, proposal_id, ...
    popup: str = "yes"  # yes | approvals (only if something needs approving) | no
    notes: tuple[str, ...] = ()  # what was left out of the run and why; added to the end of the report


class Delivered(NamedTuple):
    report_id: str  # "" when there was no body
    status: str  # shown | notified | deduped | budget | quiet | unsupported | bridge-down | error


def clean_headline(text: str, max_words: int = MAX_HEADLINE_WORDS) -> str:
    """One plain line: no Markdown, links, URLs or paths, at most `max_words` words."""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)  # [label](url) -> label
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"(?<!\w)(?:~|\.{0,2})/[\w.\-~/]+", "", text)  # a file path
    text = re.sub(r"[*`#>|]+", "", text)
    text = re.sub(r"(?<!\w)_+|_+(?!\w)", "", text)  # _emphasis_ markers, but not the underscore in send_email
    text = re.sub(r"\s+", " ", text).strip(" -:")
    words = text.split()
    return " ".join(words[:max_words]) + ("…" if len(words) > max_words else "")


def headline_from(answer: str) -> str:
    """The headline of a background run's answer: its first heading or first sentence. Reports are asked to start
    with a one-line headline, so no model call is needed."""
    answer = re.sub(r"```.*?(?:```|\Z)", " ", answer, flags=re.DOTALL)  # code is never a headline
    for line in answer.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("---"):
            continue
        sentence = re.split(r"(?<=[.!?])\s", line.lstrip("#").strip(), maxsplit=1)[0]
        if cleaned := clean_headline(sentence):
            return cleaned
    return ""


def _post_default(message: str, kind: str, priority: str, dedupe_key: str, payload: dict) -> str:
    """Natively on a Mac, straight to the gate. In Docker, through the host bridge."""
    if sys.platform == "darwin":
        from hi.context import inbox

        return inbox.post(message, "automation", kind, priority, dedupe_key, payload)
    import json

    from hi import host

    result = host.call("post_to_inbox", {"message": message, "kind": kind, "priority": priority,
                                          "dedupe_key": dedupe_key, "payload_json": json.dumps(payload)})
    return "bridge-down" if result.startswith(_BRIDGE_DOWN) else result.strip()


def _proposals_section(found: list[dict]) -> str:
    """The full arguments of every proposal, for the report: this is what the user reads before approving."""
    import json

    blocks = [f"### {p['id']}: {p['tool']}\n```json\n{json.dumps(p.get('args') or {}, indent=2, ensure_ascii=False)}\n```"
              for p in found]
    return "## Actions waiting for your approval\n\n" + "\n\n".join(blocks)


def _with_proposals(d: Delivery) -> tuple[str, str, str, str, dict]:
    """(headline, kind, priority, dedupe_key, payload) after folding in the proposals waiting on the user."""
    headline, kind, priority, key, payload = clean_headline(d.headline), d.kind, d.priority, d.dedupe_key, dict(d.payload)
    if kind == "approval" and not d.proposals:  # a live approval: never let a cut-off command be approved blind
        full = clean_headline(d.headline, 60)
        headline, payload["truncated"] = full, len(d.headline.split()) > 60
    found = [p for pid in d.proposals if (p := proposal_store.get(pid))]
    if len(found) == 1:  # one action: say exactly what it is, and let the island answer it
        headline = clean_headline(f"Approve {proposal_store.describe(found[0], 90)}?", MAX_HEADLINE_WORDS)
        kind, priority, key = "approval", "urgent", f"proposal:{found[0]['id']}"
        payload["proposal_id"] = found[0]["id"]
    elif found:
        headline = clean_headline(f"{headline} ({len(found)} actions need your approval)")
    return headline, kind, priority, key, payload


def deliver(d: Delivery, post: Callable[[str, str, str, str, dict], str] | None = None) -> Delivered:
    """Write the report, then post the headline. Never raises: a failure is in the returned status."""
    secrets = config.secret_values()
    headline, kind, priority, key, payload = _with_proposals(d)
    headline = redact(headline, secrets)
    report_id = ""
    body = d.body
    if found := [p for pid in d.proposals if (p := proposal_store.get(pid))]:
        body = f"{body.rstrip()}\n\n{_proposals_section(found)}".strip()
    if d.notes and body.strip():
        body += "\n\n---\n*Run notes:* " + "; ".join(d.notes)
    try:
        if body.strip():
            report_id, _ = reports.write_report(d.origin, headline, body, d.links, d.proposals, priority)
            payload["report_id"] = report_id
    except OSError as e:
        health.mark_down("vault", e)
        log.exception("could not write the report for %r", headline)
    if d.popup == "no" or (d.popup == "approvals" and kind != "approval"):
        return Delivered(report_id, "silent")  # the report is in the Inbox; nothing is shown
    try:
        status = (post or _post_default)(headline, kind, priority, key, payload)
    except Exception as e:  # boundary: delivery must never take a background job down
        log.exception("could not post %r", headline)
        status = "error"
        health.mark_down("island", e)
    else:
        if status == "bridge-down":
            health.mark_down("host_bridge", "could not post to the Mac")
        elif status == "notified":
            health.mark_down("island", "the menu bar app is not running; a macOS notification was shown instead")
        elif status == "shown":
            health.mark_ok("island")
    return Delivered(report_id, status)
