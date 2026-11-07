"""Tiny HTTP wrapper that runs one Python snippet per request.

POST /run {"code": "..."} -> {"stdout", "stderr", "exit_code", "timed_out", "images": [{"name", "b64"}], "files": [{"name", "b64"}]}

Matplotlib uses the Agg backend; `plt.show()` saves the figure as a PNG instead of
opening a window, and any figure still open at the end is saved too.
"""

from __future__ import annotations

import base64
import json
import resource
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TIMEOUT_SECONDS = 120  # long enough for a pip install plus a model fit
MAX_OUTPUT_CHARS = 8000
MAX_IMAGES = 6
MAX_FILES = 8
FILE_EXTENSIONS = {".pdf", ".csv", ".tsv", ".json", ".txt", ".md", ".html", ".xlsx", ".svg", ".jpg", ".jpeg"}
MAX_IMAGE_BYTES = 5_000_000
MAX_REQUEST_BYTES = 200_000
SLOTS = threading.BoundedSemaphore(2)  # at most two snippets at once

RUNNER = '''
import os, site, sys
_user_site = site.getusersitepackages()  # pip installs land here (HOME is the run's scratch dir)
os.makedirs(_user_site, exist_ok=True)
sys.path.append(_user_site)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

_count = [0]

def _save_open_figures():
    for number in plt.get_fignums():
        _count[0] += 1
        plt.figure(number).savefig(f"figure_{_count[0]}.png", dpi=110, bbox_inches="tight")
    plt.close("all")

plt.show = lambda *a, **k: _save_open_figures()

source = open("main.py").read()
try:
    exec(compile(source, "main.py", "exec"), {"__name__": "__main__"})
finally:
    _save_open_figures()
'''


def _limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (TIMEOUT_SECONDS, TIMEOUT_SECONDS))
    resource.setrlimit(resource.RLIMIT_FSIZE, (50_000_000, 50_000_000))


def run(code: str) -> dict:
    work = Path(tempfile.mkdtemp(prefix="run-"))
    try:
        (work / "main.py").write_text(code)
        (work / "_runner.py").write_text(RUNNER)
        env = {
            "PATH": "/usr/local/bin:/usr/bin", "HOME": str(work), "MPLCONFIGDIR": str(work / ".mpl"), "PYTHONUNBUFFERED": "1",
            "PYTHONUSERBASE": str(work), "PIP_USER": "1", "PIP_NO_CACHE_DIR": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        }
        try:
            done = subprocess.run(
                [sys.executable, "_runner.py"], cwd=work, env=env, capture_output=True, text=True,
                timeout=TIMEOUT_SECONDS, preexec_fn=_limits,
            )
            stdout, stderr, exit_code, timed_out = done.stdout, done.stderr, done.returncode, False
        except subprocess.TimeoutExpired as e:
            stdout, stderr, exit_code, timed_out = (e.stdout or "", f"Timed out after {TIMEOUT_SECONDS}s.", -1, True)
            stdout = stdout if isinstance(stdout, str) else stdout.decode(errors="replace")
        images = [
            {"name": p.name, "b64": base64.b64encode(p.read_bytes()).decode()}
            for p in sorted(work.glob("*.png"))[:MAX_IMAGES]
            if p.stat().st_size <= MAX_IMAGE_BYTES
        ]
        files = [
            {"name": p.name, "b64": base64.b64encode(p.read_bytes()).decode()}
            for p in sorted(work.iterdir())
            if p.is_file() and p.suffix.lower() in FILE_EXTENSIONS and p.name not in ("main.py", "_runner.py")
            and p.stat().st_size <= MAX_IMAGE_BYTES
        ][:MAX_FILES]
        return {
            "files": files,
            "stdout": stdout[-MAX_OUTPUT_CHARS:], "stderr": stderr[-MAX_OUTPUT_CHARS:],
            "exit_code": exit_code, "timed_out": timed_out, "images": images,
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass

    def _send(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._send({"ok": True} if self.path == "/health" else {"error": "not found"}, 200 if self.path == "/health" else 404)

    def do_POST(self) -> None:
        if self.path != "/run":
            return self._send({"error": "not found"}, 404)
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_REQUEST_BYTES:
            return self._send({"error": "code too large"}, 413)
        try:
            code = json.loads(self.rfile.read(length) or b"{}").get("code", "")
        except (json.JSONDecodeError, AttributeError):
            return self._send({"error": "expected JSON {\"code\": \"...\"}"}, 400)
        if not isinstance(code, str) or not code.strip():
            return self._send({"error": "missing 'code'"}, 400)
        with SLOTS:
            self._send(run(code))


if __name__ == "__main__":
    print("sandbox listening on :8000", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
