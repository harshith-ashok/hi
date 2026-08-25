"""Screen capture + OCR (TODO.md Phase 4, "screen/OCR last") — callable
directly whenever a prompt calls for it, no separate enable step (an
earlier version required one; removed per explicit request, see
privacy.py's docstring). Stays strictly on-demand regardless: every call
takes exactly one screenshot, OCRs it, deletes the image immediately, and
returns only the extracted text — never a saved image, never a
background/interval loop. Goes through the same shared sensitive-context
refusal as browser observation (hi/perception/privacy.py) on every single
call, with no opt-out.

OCR runs entirely on-device via Apple's Vision framework (PyObjC), not a
new heavy dependency like pytesseract plus a bundled tesseract binary —
verified live against a real screenshot before wiring this up. The
pyobjc-framework-* packages this needs were already a transitive
dependency of pynput (Phase 1's hotkey listener) except
pyobjc-framework-vision itself, one small addition to pyproject.toml.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from langchain_core.tools import tool

from hi.perception.privacy import sensitive_context_reason

_RECOGNITION_LEVEL_ACCURATE = 1


def _ocr_image(path: Path) -> list[str]:
    import Quartz
    import Vision
    from Cocoa import NSURL

    url = NSURL.fileURLWithPath_(str(path))
    image_source = Quartz.CGImageSourceCreateWithURL(url, None)
    cg_image = Quartz.CGImageSourceCreateImageAtIndex(image_source, 0, None)
    if cg_image is None:
        return []

    lines: list[str] = []

    def handler(request, error):
        if error:
            return
        for observation in request.results():
            top_candidates = observation.topCandidates_(1)
            if top_candidates:
                lines.append(str(top_candidates[0].string()))

    request = Vision.VNRecognizeTextRequest.alloc().initWithCompletionHandler_(handler)
    request.setRecognitionLevel_(_RECOGNITION_LEVEL_ACCURATE)
    req_handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, None)
    req_handler.performRequests_error_([request], None)
    return lines


@tool
def read_screen() -> str:
    """Take a single screenshot of the whole screen right now, extract
    its text via on-device OCR, and return the text. The screenshot
    itself is discarded immediately, never saved. Use for reading an
    error dialog, a PDF, or anything else visible that isn't in a file —
    callable directly, no enable step needed. Refuses if the active
    window looks private/incognito or a password manager is frontmost.
    """
    reason = sensitive_context_reason()
    if reason:
        return f"Refused: {reason}"

    path = Path(tempfile.mktemp(suffix=".png"))
    try:
        result = subprocess.run(["screencapture", "-x", str(path)], capture_output=True, text=True)
        if result.returncode != 0 or not path.exists():
            return f"Screenshot failed: {result.stderr.strip() or 'unknown error'}"
        lines = _ocr_image(path)
    finally:
        path.unlink(missing_ok=True)

    if not lines:
        return "No text detected on screen."
    return "\n".join(lines)
