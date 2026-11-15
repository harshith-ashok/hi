"""Dependencies point one way (MAKE.md, section 3): lower layers never import upward.

    core                     imports nothing else in hi
    llm                      core, config
    memory                   core, config, llm
    everything but cli/server  never imports hi.server
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "hi"

ALLOWED = {
    "core": set(),
    "llm": {"core", "config"},
    "memory": {"core", "config", "llm"},
}


def imported_packages(path: Path) -> set[str]:
    """First-level `hi` packages/modules imported by a file, e.g. {"core", "config"}."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            parts = node.module.split(".")
            if parts[0] == "hi" and len(parts) > 1:
                found.add(parts[1])
            elif node.module == "hi":  # `from hi import llm, probes`
                found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "hi" and len(parts) > 1:
                    found.add(parts[1])
    return found


def package_files(package: str) -> list[Path]:
    return sorted((ROOT / package).rglob("*.py"))


def test_lower_layers_do_not_import_upward():
    problems = []
    for package, allowed in ALLOWED.items():
        for path in package_files(package):
            extra = imported_packages(path) - allowed - {package}
            if extra:
                problems.append(f"{path.relative_to(ROOT)} imports {sorted(extra)}")
    assert not problems, "\n".join(problems)


def test_only_the_cli_and_the_server_itself_import_the_server():
    problems = []
    for path in ROOT.rglob("*.py"):
        relative = path.relative_to(ROOT)
        if relative.parts[0] == "server" or relative.name == "cli.py":
            continue
        if "server" in imported_packages(path):
            problems.append(str(relative))
    assert not problems, f"these import hi.server: {problems}"


def test_the_layer_packages_exist():
    for package in ALLOWED:
        assert package_files(package), package
