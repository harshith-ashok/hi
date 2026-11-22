"""Reading the files of a project (a workspace made in the chat app: its own instructions and files)."""

from __future__ import annotations

from langchain_core.tools import tool

from hi import attachments
from hi.memory import projects


@tool
def read_workspace_file(project: str, name: str) -> str:
    """Read a file that belongs to one of the user's projects: the workspaces they make in the chat app, each with its
    own instructions and files. When a chat is in a project, its file list is given to you. Documents are parsed,
    images described and audio transcribed. (Not for code projects on disk: those use read_project_file.)

    Args:
        project: The project's slug, as given in the chat's project note.
        name: The file name from the project's file list.
    """
    if projects.get(project) is None:
        return f"No project '{project}'."
    if not projects.valid_file_name(name):
        return f"'{name}' is not a file name."
    path = projects.projects_dir() / project / name
    if not path.is_file():
        listed = ", ".join(f["name"] for f in projects.files(project)) or "none"
        return f"No file '{name}' in project '{project}'. Files: {listed}."
    return attachments.read_file(path)[: attachments.MAX_PROMPT_CHARS]
