"""Run Python the agent wrote in the sandbox container (sandbox/) and keep what it
made: every chart is saved as a PNG under <vault>/hi/plots/ next to the code that
produced it, and the UI shows it inline (GET /plots/<name>, hi/ipc/server.py).
"""

import base64
import re
import time
import uuid

import httpx
from langchain_core.tools import tool

import hi.config as config
from hi.vault import files_dir, plots_dir

PLOT_URL_PREFIX = "/plots/"
FILE_URL_PREFIX = "/files/"


def _save_plots(code: str, images: list[dict]) -> list[str]:
    """Write the code and each image to the vault; return the plot URLs."""
    if not images:
        return []
    folder = plots_dir()
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    (folder / f"{stem}.py").write_text(code)
    urls = []
    for i, image in enumerate(images, 1):
        name = f"{stem}-{i}.png"
        (folder / name).write_bytes(base64.b64decode(image["b64"]))
        urls.append(PLOT_URL_PREFIX + name)
    return urls


def _save_files(files: list[dict]) -> list[str]:
    """Write non-image outputs (PDF, CSV, ...) to the vault; return their URLs."""
    if not files:
        return []
    stem = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    folder = files_dir() / stem
    folder.mkdir(parents=True, exist_ok=True)
    urls = []
    for file in files:
        name = re.sub(r"[^\w.-]", "_", file["name"])
        (folder / name).write_bytes(base64.b64decode(file["b64"]))
        urls.append(f"{FILE_URL_PREFIX}{stem}/{name}")
    return urls


@tool
def run_python(code: str) -> str:
    """Run Python code in an isolated sandbox (120s limit, outbound internet) and return
    its output. numpy, pandas, scipy, scikit-learn, statsmodels, matplotlib and seaborn
    are installed; anything else: subprocess.run([sys.executable, "-m", "pip",
    "install", "pkg"], check=True) at the top of the code. It can download data over
    HTTP. Use it to compute things, train/evaluate ML models, and draw
    charts: call plt.show() or plt.savefig() and every figure is shown to the user
    automatically in the UI. Files you write to the current directory (pdf, csv, json,
    txt, md, html, xlsx, svg) are saved to the user's vault and linked in the UI. Print the numbers worth reporting. No files persist
    between runs, so put the whole program in one call.

    Args:
        code: Complete, self-contained Python program.
    """
    try:
        response = httpx.post(f"{config.SANDBOX_URL.rstrip('/')}/run", json={"code": code}, timeout=150)
        response.raise_for_status()
        result = response.json()
    except httpx.HTTPError as e:
        return f"Sandbox unavailable at {config.SANDBOX_URL} ({e}). It runs as the `sandbox` service in docker-compose."

    plots = _save_plots(code, result["images"])
    files = _save_files(result.get("files", []))
    parts = [f"Exit code: {result['exit_code']}"]
    if result["stdout"]:
        parts.append(f"stdout:\n{result['stdout']}")
    if result["stderr"]:
        parts.append(f"stderr:\n{result['stderr']}")
    if plots:
        parts.append(
            f"{len(plots)} chart(s) were generated and are already displayed to the user in the UI "
            "(do not embed or link them). Saved: " + ", ".join(plots)
        )
    if files:
        parts.append(
            "Files created are saved in the vault and linked in the UI for the user (do not paste their "
            "contents or links): " + ", ".join(files)
        )
    return "\n".join(parts)
