"""Git on the user's Mac, for the Dockerized agent.

The container sees the repos (mounted under /host) but cannot push: it has no SSH keys, no known_hosts and
no stored credentials, and the user's keys must not be mounted into a container that runs model-driven
commands. So git runs on the Mac, through the host bridge, with the Mac's own credentials.

- `git_on_mac(repo, git_args)`: local work and fetch/pull. `push` is refused here on purpose.
- `git_push(repo, ...)`: the only way to push. It asks for approval first (a push publishes work), then
  runs `git_push_on_mac` on the Mac. The model never reaches `git_push_on_mac` directly.

`repo` is a path in any of the forms the agent meets (`/host/Dev/X`, `~/Dev/X`, `/Users/me/Dev/X`) or just a
repo name like "logic_play", which is looked up under ~/Dev, ~/Documents and ~/Desktop.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

from langchain_core.tools import tool

from hi.action_tiers import confirm_destructive

SEARCH_ROOTS = ("Dev", "Documents", "Desktop")
SEARCH_DEPTH = 3
ALLOWED = {
    "status", "diff", "log", "show", "add", "commit", "branch", "checkout", "switch", "stash",
    "fetch", "pull", "merge", "remote", "rev-parse", "ls-files", "tag", "blame", "shortlog", "cherry-pick",
}
BLOCKED_FLAGS = ("--upload-pack", "--receive-pack", "--exec", "-c", "--config", "--git-dir", "--work-tree")
# Anything that throws work away is not offered; the user does those by hand.
DISCARDING = {"-f", "--force", "-D", "--hard", "--", "drop", "clear"}
TIMEOUT_SECONDS = 90
MAX_OUTPUT = 6000


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _home_path(repo: str) -> Path:
    """A container or host spelling of a path -> the real path on this Mac."""
    if repo.startswith("/host/") or repo == "/host":
        return Path.home() / repo.removeprefix("/host").lstrip("/")
    return Path(repo).expanduser()


def _find_by_name(name: str) -> list[Path]:
    wanted, found = _norm(name), []
    for root in SEARCH_ROOTS:
        base = Path.home() / root
        if not base.is_dir():
            continue
        for dirpath, dirnames, _files in os.walk(base):
            depth = len(Path(dirpath).relative_to(base).parts)
            if ".git" in dirnames:
                if _norm(Path(dirpath).name) == wanted:
                    found.append(Path(dirpath))
                dirnames[:] = []  # no repos inside repos
            dirnames[:] = [d for d in dirnames if d not in {"node_modules", ".git", "Library"} and depth < SEARCH_DEPTH]
    return found


def resolve_repo(repo: str) -> tuple[Path | None, str]:
    """(path, '') or (None, why). Only git repos inside the user's home are allowed."""
    repo = repo.strip()
    if "/" in repo or repo.startswith("~"):
        path = _home_path(repo)
    else:
        matches = _find_by_name(repo)
        if len(matches) != 1:
            return None, (f"No git repo named '{repo}' under ~/Dev, ~/Documents or ~/Desktop." if not matches
                          else "Several repos match, give the path: " + ", ".join(str(m) for m in matches))
        path = matches[0]
    path = path.resolve()
    if not path.is_relative_to(Path.home().resolve()):
        return None, f"{path} is outside your home folder."
    if not (path / ".git").exists():
        return None, f"{path} is not a git repository."
    return path, ""


def _git(path: Path, argv: list[str]) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_EDITOR": "true", "GIT_SSH_COMMAND": "ssh -o BatchMode=yes"}
    try:
        result = subprocess.run(["git", "-C", str(path), *argv], capture_output=True, text=True, timeout=TIMEOUT_SECONDS, env=env)
    except subprocess.TimeoutExpired:
        return f"git {argv[0]} timed out after {TIMEOUT_SECONDS}s."
    output = (result.stdout + result.stderr).strip()
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + "\n…(truncated)"
    return f"Exit code: {result.returncode}\n{output}"


@tool
def git_on_mac(repo: str, git_args: str) -> str:
    """Run a git command in a repo on the user's Mac (not in your container). Use for status, diff, log, add,
    commit, branch, checkout/switch, stash, fetch, pull, merge. Pushing is a separate tool, git_push.
    For `commit` pass a message with -m. Check `status`/`diff` first so the message describes the change.

    Args:
        repo: Repo name ("logic_play") or path ("/host/Dev/LogicPlay/logic_play", "~/Dev/...").
        git_args: The git arguments without the word git, e.g. "status -sb" or 'commit -am "fix leaderboard"'.
    """
    path, why = resolve_repo(repo)
    if path is None:
        return why
    try:
        argv = shlex.split(git_args)
    except ValueError as e:
        return f"Can't parse the arguments: {e}"
    if not argv:
        return "Give a git command, e.g. 'status'."
    if argv[0] == "push":
        return "Use the git_push tool to push."
    if argv[0] not in ALLOWED:
        return f"'git {argv[0]}' is not allowed here. Allowed: {', '.join(sorted(ALLOWED))}."
    if any(a in BLOCKED_FLAGS or a.startswith(("--upload-pack=", "--exec=", "--config=", "--git-dir=", "--work-tree=")) for a in argv):
        return "That flag is not allowed."
    if DISCARDING & set(argv[1:]):
        return "That would discard work, so it is not done from here. Ask the user to run it themselves."
    if argv[0] == "commit" and not any(re.fullmatch(r"-[a-zA-Z]*m.*", a) or a in ("--message", "-F", "--file") or a.startswith("--message=") for a in argv[1:]):
        return "Pass a commit message with -m."
    return _git(path, argv)


@tool
def git_push_on_mac(repo: str, remote: str = "origin", branch: str = "", force: bool = False) -> str:
    """Push a branch from a repo on the Mac. Host side of git_push; the approval happens before this is called.

    Args:
        repo: Repo name or path.
        remote: Remote name.
        branch: Branch to push. Empty pushes the current branch.
        force: Use --force-with-lease.
    """
    path, why = resolve_repo(repo)
    if path is None:
        return why
    if not re.fullmatch(r"[\w.\-]+", remote) or (branch and not re.fullmatch(r"[\w./\-]+", branch)):
        return "Invalid remote or branch name."
    if not branch:
        branch = subprocess.run(["git", "-C", str(path), "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
        if not branch:
            return "Detached HEAD: say which branch to push."
    return _git(path, ["push", "-u", *(["--force-with-lease"] if force else []), remote, branch])


@tool
def git_push(repo: str, remote: str = "origin", branch: str = "", force: bool = False) -> str:
    """Push a branch to its remote, from the user's Mac (which has the SSH keys). Asks the user to approve first.
    Commit with git_on_mac before pushing.

    Args:
        repo: Repo name ("logic_play") or path.
        remote: Remote name, usually origin.
        branch: Branch to push, e.g. "v3". Empty pushes the current branch.
        force: Force push (--force-with-lease). Only if the user explicitly asked.
    """
    path, why = resolve_repo_anywhere(repo)
    shown = path or repo
    description = f"git push{' --force-with-lease' if force else ''} {remote} {branch or '(current branch)'} in {shown}"
    if why and sys.platform == "darwin":
        return why
    if not confirm_destructive(description):
        return f"Push not done: the user declined ({description})."
    args = {"repo": repo, "remote": remote, "branch": branch, "force": force}
    if sys.platform == "darwin":
        return git_push_on_mac.invoke(args)
    from hi import host

    return host.call("git_push_on_mac", args)


def resolve_repo_anywhere(repo: str) -> tuple[Path | None, str]:
    """On the Mac, resolve the repo; in the container the Mac does it (the name lookup needs the Mac's folders)."""
    return resolve_repo(repo) if sys.platform == "darwin" else (None, "")
