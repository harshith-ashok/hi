"""Files dropped into the chat as context: saved under <vault>/hi/context/<id>/, read
into text where possible, and prepended to the user's next message. Dropping a file
never triggers a reply.

Understood: text and code (anything that decodes), PDF, Word (.docx), images (described
by the vision model), audio (transcribed by the built-in Whisper), and zip archives (unpacked safely, text members read). Anything else is
saved and named so the agent can still open it by path.
"""

from __future__ import annotations

import base64
import io
import re
import uuid
import zipfile
from pathlib import Path
from typing import BinaryIO
from xml.etree import ElementTree

from langchain_core.messages import HumanMessage

import hi.config as config
from hi import llm
from hi.vault import context_dir

MAX_UPLOAD_BYTES = 1_000_000_000  # 1 GB; streamed to disk, never held whole in memory
MAX_TEXT_READ_BYTES = 5_000_000  # how much of a plain file is read as text
MAX_PARSE_BYTES = 200_000_000  # PDFs, Word files, zips and audio are parsed in memory up to this size
MAX_IMAGE_BYTES = 20_000_000  # sent to the vision model
MAX_PROMPT_CHARS = 20_000  # per attachment; the full text stays on disk
MAX_ZIP_MEMBERS = 200
MAX_ZIP_UNPACKED_BYTES = 2_000_000_000
MAX_ZIP_TEXT_FILES = 25
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
AUDIO_TYPES = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".oga", ".flac", ".opus", ".webm", ".caf"}
_ID = re.compile(r"[0-9a-f]{12}")


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w.\- ]", "_", Path(name.replace("\\", "/")).name).strip(". ") or "file"


def _decode(data: bytes) -> str | None:
    """The text of a file, or None if it is binary."""
    if b"\x00" in data[:8000]:
        return None
    return data.decode("utf-8", errors="replace")


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    pages = [(page.extract_text() or "").strip() for page in PdfReader(io.BytesIO(data)).pages]
    if not any(pages):
        return "(this PDF has no text layer: it is probably scanned images)"
    return "\n\n".join(f"--- page {i} ---\n{text}" for i, text in enumerate(pages, 1))


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ElementTree.fromstring(z.read("word/document.xml"))
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = ["".join(t.text or "" for t in p.iter(f"{ns}t")) for p in root.iter(f"{ns}p")]
    return "\n".join(paragraphs)


def _describe_image(data: bytes, mime: str) -> str:
    try:
        from hi.llm.registry import ensure_pulled

        ensure_pulled(config.VISION_MODEL)
        model = llm.build_chat_model(config.VISION_MODEL)
        message = HumanMessage(content=[
            {"type": "text", "text": "Describe this image in detail. Transcribe any text in it exactly."},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}},
        ])
        return str(model.invoke([message]).content)
    except Exception as e:
        return f"(could not describe the image: {llm.friendly_error(e)})"


_whisper = None


def _transcribe_local(path: Path) -> str | None:
    """faster-whisper in this process: any audio format, any length, read from disk.
    None if it isn't installed (the Docker image skips it), so the caller falls back."""
    global _whisper
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    if _whisper is None:
        _whisper = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
    segments, _info = _whisper.transcribe(str(path))
    return " ".join(s.text.strip() for s in segments).strip()


def _transcribe(path: Path) -> str:
    """Speech to text with the built-in Whisper: in-process faster-whisper, else the
    whisper.cpp server (16 kHz WAV only, which the browser converts to)."""
    try:
        text = _transcribe_local(path)
        if text is None:
            from hi.stt import transcribe_wav

            if path.stat().st_size > MAX_PARSE_BYTES:
                return f"(audio is too large for the whisper.cpp server, saved at {path})"
            text = transcribe_wav(path.read_bytes(), timeout=900)
        return text or "(no speech found)"
    except Exception as e:
        return f"(could not transcribe: {e})"


def _unpack_zip(data: bytes, folder: Path) -> str:
    """Extract a zip without trusting it: no path escapes, bounded size and count."""
    lines, texts = [], []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        members = [m for m in z.infolist() if not m.is_dir()]
        if len(members) > MAX_ZIP_MEMBERS or sum(m.file_size for m in members) > MAX_ZIP_UNPACKED_BYTES:
            return f"(archive too large to unpack: {len(members)} files)"
        root = folder.resolve()
        for m in members:
            target = (root / m.filename).resolve()
            if not target.is_relative_to(root):
                continue  # zip-slip
            target.parent.mkdir(parents=True, exist_ok=True)
            blob = z.read(m)
            target.write_bytes(blob)
            lines.append(f"- {m.filename} ({m.file_size:,} bytes)")
            if len(texts) < MAX_ZIP_TEXT_FILES and (text := _decode(blob)) is not None:
                texts.append(f"=== {m.filename} ===\n{text[:4000]}")
    return "Files (unpacked next to the archive):\n" + "\n".join(lines) + "\n\n" + "\n\n".join(texts)


def _read(path: Path, kind: str) -> str:
    suffix, size = path.suffix.lower(), path.stat().st_size
    try:
        if suffix in IMAGE_TYPES:
            return _describe_image(path.read_bytes(), IMAGE_TYPES[suffix]) if size <= MAX_IMAGE_BYTES else (
                f"(image is {size:,} bytes: too large to describe)")
        if kind == "audio" or suffix in AUDIO_TYPES:
            return _transcribe(path)
        parsers = {".pdf": _pdf_text, ".docx": _docx_text}
        if suffix in parsers or suffix == ".zip":
            if size > MAX_PARSE_BYTES:
                return f"(file is {size:,} bytes: too large to read here, saved at {path})"
            data = path.read_bytes()
            if suffix == ".zip":
                return _unpack_zip(data, path.parent / (path.stem + "_unpacked"))
            return parsers[suffix](data)
        with path.open("rb") as f:
            head = f.read(MAX_TEXT_READ_BYTES)
        text = _decode(head)
        if text is None:
            return f"(binary file, {size:,} bytes: not readable as text)"
        return text + (f"\n... (only the first {MAX_TEXT_READ_BYTES:,} of {size:,} bytes read)" if size > len(head) else "")
    except Exception as e:  # a corrupt file is a note for the model, not a failed upload
        return f"(could not read {path.name}: {type(e).__name__}: {e})"


def save(name: str, stream: BinaryIO, length: int, kind: str = "") -> dict:
    """Store one dropped file, copying `length` bytes from `stream` to disk in chunks."""
    if length > MAX_UPLOAD_BYTES:
        raise ValueError(f"{name} is larger than {MAX_UPLOAD_BYTES // 1_000_000_000} GB")
    attachment_id = uuid.uuid4().hex[:12]
    folder = context_dir() / attachment_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / _safe_name(name)
    with path.open("wb") as out:
        remaining = length
        while remaining > 0:
            chunk = stream.read(min(1_048_576, remaining))
            if not chunk:
                break
            out.write(chunk)
            remaining -= len(chunk)
    text = _read(path, kind)
    (folder / "extracted.md").write_text(text)
    return {"id": attachment_id, "name": path.name, "size": path.stat().st_size, "chars": len(text)}


def _entry(attachment_id: str) -> str | None:
    if not _ID.fullmatch(attachment_id):
        return None
    folder = context_dir() / attachment_id
    extracted = folder / "extracted.md"
    files = [p for p in folder.glob("*") if p.is_file() and p.name != "extracted.md"] if folder.is_dir() else []
    if not extracted.is_file() or not files:
        return None
    text = extracted.read_text()
    shown = text[:MAX_PROMPT_CHARS]
    cut = f"\n... (cut: {len(text):,} characters in all, full text in {extracted})" if len(text) > MAX_PROMPT_CHARS else ""
    return f"### {files[0].name}\nSaved at: {files[0]}\n\n{shown}{cut}"


def render(attachment_ids: list[str]) -> str:
    """The context block added to the user's message, empty if there are no attachments."""
    entries = [e for i in attachment_ids if (e := _entry(str(i)))]
    if not entries:
        return ""
    return "\n\n---\nThe user attached these files as context for this message:\n\n" + "\n\n".join(entries)
