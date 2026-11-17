"""Find and mask secrets in text that is about to leave `hi`'s control (a delivery, a web search, a prompt to a
hosted model). Pure text in, text out: no settings and no I/O, so the caller passes in the exact values to hide."""

from __future__ import annotations

import re
from typing import Iterable

MASK = "[redacted]"
MIN_KNOWN_LENGTH = 8  # a shorter "secret" would mask ordinary words

_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE | re.DOTALL) if flags else re.compile(p)
    for p, flags in (
        (r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", True),
        (r"\bsk-[A-Za-z0-9_\-]{16,}", False),
        (r"\bgh[pousr]_[A-Za-z0-9]{20,}", False),
        (r"\bgithub_pat_[A-Za-z0-9_]{20,}", False),
        (r"\bxox[abprs]-[A-Za-z0-9\-]{10,}", False),
        (r"\bAKIA[0-9A-Z]{16}\b", False),
        (r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}", False),
        (r"\bBearer\s+[A-Za-z0-9._~+/\-]{16,}=*", False),
    )
)
# KEY=value or KEY: value, where the key's name says it is a credential.
_ASSIGNMENT = re.compile(
    r"""(?P<key>\b[A-Za-z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|_KEY)\b)(?P<sep>\s*[=:]\s*)(?P<value>"[^"\n]+"|'[^'\n]+'|[^\s,;]+)""",
    re.IGNORECASE,
)


def _known(values: Iterable[str]) -> list[str]:
    """The distinct usable values, longest first so a value that contains another is masked whole."""
    return sorted({v for v in values if v and len(v) >= MIN_KNOWN_LENGTH}, key=len, reverse=True)


def contains_secret(text: str, known: Iterable[str] = ()) -> bool:
    if any(value in text for value in _known(known)):
        return True
    if any(p.search(text) for p in _PATTERNS):
        return True
    return any(len(m.group("value").strip("'\"")) >= MIN_KNOWN_LENGTH for m in _ASSIGNMENT.finditer(text))


def redact(text: str, known: Iterable[str] = ()) -> str:
    """`text` with every secret replaced by [redacted]."""
    for value in _known(known):
        text = text.replace(value, MASK)
    for pattern in _PATTERNS:
        text = pattern.sub(MASK, text)

    def hide(match: re.Match) -> str:
        value = match.group("value")
        if len(value.strip("'\"")) < MIN_KNOWN_LENGTH or value == MASK:
            return match.group(0)
        return f"{match.group('key')}{match.group('sep')}{MASK}"

    return _ASSIGNMENT.sub(hide, text)
