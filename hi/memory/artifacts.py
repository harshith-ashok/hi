"""Artifacts: pages, documents and diagrams a reply wrote for you to keep and change.

A reply marks one with `artifact` on a code fence, optionally with a title:

    ```html artifact title="Budget"
    <h1>…</h1>
    ```

Each is saved in the vault, one file per version, so asking for a change makes a new version (the same title in the same
chat) and nothing is overwritten:

    <vault>/hi/artifacts/<session>/<slug>/v<N>.<ext>
    <vault>/hi/artifacts/<session>/<slug>/index.json     title, kind, ext and the list of versions
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import hi.config as config

KINDS = ("html", "svg", "markdown", "mermaid", "code")
_EXT = {"html": "html", "svg": "svg", "markdown": "md", "mermaid": "mmd"}
_LANG_KIND = {"html": "html", "htm": "html", "svg": "svg", "md": "markdown", "markdown": "markdown", "mermaid": "mermaid"}
_CODE_EXT = {"python": "py", "py": "py", "javascript": "js", "js": "js", "typescript": "ts", "ts": "ts", "css": "css", "json": "json",
             "bash": "sh", "sh": "sh", "sql": "sql", "yaml": "yaml", "yml": "yaml", "swift": "swift", "rust": "rs", "go": "go"}
_OPEN = re.compile(r"^(?P<fence>`{3,}|~{3,})(?P<lang>[\w+#.-]*)(?P<rest>.*)$")
_MARK = re.compile(r"(?:^|\s)artifact(?:\s|$)")
_TITLE = re.compile(r"""title\s*=\s*(?:"([^"]*)"|'([^']*)')""")
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_TITLE = 80
MAX_CHARS = 400_000  # one version; anything bigger is not an artifact a reply should be writing


@dataclass
class Artifact:
    title: str
    kind: str
    lang: str
    content: str

    @property
    def slug(self) -> str:
        return slugify(self.title)

    @property
    def ext(self) -> str:
        return _EXT.get(self.kind) or _CODE_EXT.get(self.lang.lower(), "txt")


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-") or "untitled"


def kind_of(lang: str) -> str:
    return _LANG_KIND.get(lang.lower(), "code")


def extract(answer: str) -> list[Artifact]:
    """The fenced blocks of `answer` marked `artifact`, in order. An unclosed block is not one yet."""
    found: list[Artifact] = []
    lines = answer.splitlines()
    i = 0
    while i < len(lines):
        m = _OPEN.match(lines[i])
        if not m:
            i += 1
            continue
        fence = m["fence"]
        j = i + 1
        while j < len(lines) and not re.match(rf"^{re.escape(fence[0])}{{{len(fence)},}}\s*$", lines[j]):
            j += 1
        if j >= len(lines):  # never closed
            break
        if _MARK.search(m["rest"]):
            title = _TITLE.search(m["rest"])
            name = ((title and (title[1] or title[2])) or "").strip()[:MAX_TITLE] or "Untitled"
            content = "\n".join(lines[i + 1:j])
            if content.strip() and len(content) <= MAX_CHARS:
                found.append(Artifact(name, kind_of(m["lang"]), m["lang"], content))
        i = j + 1
    return found


# --- the store ---------------------------------------------------------------------------------------------------------

def artifacts_dir(session: str) -> Path:
    return config.VAULT_PATH / "hi" / "artifacts" / session


def _index_path(session: str, slug: str) -> Path:
    return artifacts_dir(session) / slug / "index.json"


def _read_index(session: str, slug: str) -> dict | None:
    try:
        return json.loads(_index_path(session, slug).read_text())
    except (OSError, json.JSONDecodeError):
        return None


def save(session: str, turn: str, artifact: Artifact) -> dict:
    """Store `artifact` as the next version of its title in `session` (a repeat of the latest content is not a new
    version). Returns {slug, title, kind, version}."""
    slug = artifact.slug
    folder = artifacts_dir(session) / slug
    index = _read_index(session, slug) or {"title": artifact.title, "kind": artifact.kind, "ext": artifact.ext, "versions": []}
    versions = index["versions"]
    if versions:
        latest = folder / f"v{versions[-1]['n']}.{index['ext']}"
        if latest.exists() and latest.read_text() == artifact.content:
            return {"slug": slug, "title": index["title"], "kind": index["kind"], "version": versions[-1]["n"]}
    n = (versions[-1]["n"] if versions else 0) + 1
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"v{n}.{index['ext']}").write_text(artifact.content)
    versions.append({"n": n, "turn": turn, "time": datetime.now().isoformat(timespec="seconds")})
    tmp = folder / "index.json.tmp"
    tmp.write_text(json.dumps(index, ensure_ascii=False, indent=1))
    tmp.replace(folder / "index.json")
    return {"slug": slug, "title": index["title"], "kind": index["kind"], "version": n}


def listing(session: str) -> list[dict]:
    """[{slug, title, kind, versions, latest}] for the chat, most recently changed first."""
    out = []
    for path in artifacts_dir(session).glob("*/index.json"):
        index = _read_index(session, path.parent.name)
        if index and index.get("versions"):
            out.append({"slug": path.parent.name, "title": index["title"], "kind": index["kind"],
                        "versions": len(index["versions"]), "latest": index["versions"][-1]["n"],
                        "_time": index["versions"][-1]["time"]})
    out.sort(key=lambda a: a["_time"], reverse=True)
    return [{k: v for k, v in a.items() if k != "_time"} for a in out]


def read(session: str, slug: str, version: int) -> dict | None:
    """{title, kind, lang, version, versions, content} for one version, or None."""
    if not SLUG.fullmatch(slug):
        return None
    index = _read_index(session, slug)
    if not index or version not in [v["n"] for v in index["versions"]]:
        return None
    try:
        content = (artifacts_dir(session) / slug / f"v{version}.{index['ext']}").read_text()
    except OSError:
        return None
    return {"title": index["title"], "kind": index["kind"], "ext": index["ext"], "version": version,
            "versions": [v["n"] for v in index["versions"]], "content": content}


def latest(session: str) -> list[dict]:
    """The newest version of every artifact in the chat, in full, most recently changed first."""
    out = []
    for item in listing(session):
        if (found := read(session, item["slug"], item["latest"])):
            out.append({**found, "slug": item["slug"]})
    return out


def delete_session(session: str) -> None:
    shutil.rmtree(artifacts_dir(session), ignore_errors=True)
