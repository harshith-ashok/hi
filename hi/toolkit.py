"""Tool registry + per-turn tool selection.

A persona may own 130+ tools (native + MCP). Every tool belongs to a *group*; the
`ToolSelector` middleware offers the model every tool on every call, ordered by group
priority (P1 core first), except tools hidden as duplicates of a higher-priority tool
and tools whose outside dependency is down (see `dependency_is_up`).

Tools not listed here are grouped by MCP server (P2, matched by server name),
so a newly configured server is reachable instead of silently dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from langchain.agents.middleware import AgentMiddleware, ModelRequest
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, tool

from hi.core import health

# Tools that only work while an outside dependency is up. While it is marked down (hi/core/health.py)
# the model isn't offered them, instead of calling a tool that is known to fail.
SANDBOX_TOOLS = frozenset({"run_python", "run_python_file"})


def required_dependency(tool_name: str) -> str | None:
    from hi.host import HOST_TOOLS

    if tool_name in SANDBOX_TOOLS:
        return "sandbox"
    if tool_name == "web_search":
        return "searxng"
    return "host_bridge" if tool_name in HOST_TOOLS else None


def dependency_is_up(tool_name: str) -> bool:
    dep = required_dependency(tool_name)
    return dep is None or health.is_up(dep)


# Tools that only read: a background run may call these without asking. Anything not listed here (and not
# marked readOnlyHint by its MCP server) is not read-only, so an unattended run turns it into a proposal.
READ_ONLY = frozenset({
    "search_vault", "read_vault_note", "read_project_file", "list_project_files", "search_files", "read_note", "list_notes",
    "current_context", "use_skill", "get_person_info", "list_people", "list_conversations", "read_conversation",
    "leetcode_stats", "list_applications", "list_pipeline_entries", "list_deadlines", "list_tasks",
    "what_next", "check_suggestions", "show_last_run_trace",
    "search_wikipedia", "find_image", "fetch", "web_search",
    "get_me", "search_repositories", "search_code", "get_file_contents", "list_issues", "issue_read",
    "list_pull_requests", "pull_request_read", "list_commits", "list_branches", "actions_list", "get_job_logs",
    "get_commit", "actions_get", "get_label", "get_latest_release", "get_release_by_tag", "get_tag", "list_releases",
    "list_tags", "search_commits", "search_issues", "search_pull_requests",
    "list_running_apps", "now_playing", "list_timers", "list_playlists",
    "list_background_tasks", "check_background_task", "check_dev_servers",
    "list_schedules",
})
SCREEN_TOOLS = frozenset({"current_context", "read_screen", "ask_about_screen", "observe_current_tab", "take_screenshot"})
WEB_TOOLS = frozenset({"web_search", "fetch", "search_wikipedia", "find_image"})


def is_read_only(name: str, tool: BaseTool | None = None) -> bool:
    """True if `name` is on the read-only list, or its MCP server marked it `readOnlyHint`."""
    if name in READ_ONLY:
        return True
    meta = getattr(tool, "metadata", None) or {}
    hint = meta.get("readOnlyHint", (meta.get("annotations") or {}).get("readOnlyHint"))
    return hint is True


@dataclass(frozen=True)
class Group:
    name: str
    priority: int  # 1 always · 2 on keyword match · 3 on request only
    tools: tuple[str, ...]
    keywords: str = ""  # regex, case-insensitive (P2 only)
    about: str = ""


GROUPS: tuple[Group, ...] = (
    # ---- term: core -------------------------------------------------------
    Group("core", 1, (
        "run_shell_command", "run_mac_shell", "search_vault", "read_vault_note", "read_project_file", "list_project_files", "search_files",
        "edit_project_file", "write_project_file",
        "read_note", "list_notes", "create_note", "append_note", "current_context", "use_skill", "git_on_mac", "git_push",
    )),
    # ---- term: native, on keyword ----------------------------------------
    Group("background", 2, ("list_background_tasks", "check_background_task", "stop_background_task", "check_dev_servers"),
          r"background|long[- ]running|dev server|still running|stop (the|that)|process", "background shell tasks, dev servers"),
    Group("devflow", 2, ("open_dev_flow", "add_dev_flow", "resume_context", "save_project_to_vault"),
          r"dev flow|workflow|set up my|start working|resume|pick up where|save (this )?project", "dev flows, resume context, save project to the vault"),
    Group("screen", 2, ("read_screen", "ask_about_screen", "observe_current_tab", "open_url_in_browser",
                        "pause_screen_context", "resume_screen_context"),
          r"screen|pause|resume|tab\b|browser|looking at|displayed|this error|image|diagram|open (the )?(url|link|site)", "what is on screen / in the browser tab, open a URL"),
    Group("people", 2, ("add_person_info", "get_person_info", "delete_person", "list_people"),
          r"\bpeople\b|person|contact|colleague|friend|who is|about \w+'s|met \w+", "per-person notes"),
    Group("history", 2, ("list_conversations", "read_conversation"),
          r"conversation|earlier|yesterday|last time|we (talked|discussed)|previous|remember when", "past conversations"),
    Group("tracking", 2, (
        "leetcode_daily", "log_leetcode_attempt", "leetcode_stats",
        "add_application", "update_application_status", "list_applications",
        "create_pipeline", "add_pipeline_entry", "update_pipeline_entry_stage", "list_pipeline_entries",
        "list_deadlines", "assign_task_owner", "team_status_draft", "team_deadline_pings",
    ), r"leetcode|application|applied|interview|pipeline|deadline|\bdue\b|team|assign|owner", "leetcode, job applications, pipelines, deadlines, team ops"),
    Group("sandbox", 2, ("run_python", "run_python_file"),
          r"python|\bplot|\bgraph\b|\bchart|visuali[sz]|regression|classif|cluster|train(ing)? (a |the )?model|machine learning|\bml\b|matplotlib|numpy|pandas|scikit|sklearn|dataset|\.py\b|run (it|this|the (file|script))|histogram|scatter|simulat|\bcompute\b|calculate",
          "run Python in a sandbox: calculations, ML, charts shown in the UI"),
    Group("web", 2, ("search_wikipedia", "find_image"),
          r"wikipedia|who is|who was|what is|what are|look up|define|history of|picture|photo|\bimage|\bpic\b|show me (a|an)\b",
          "Wikipedia lookups and pictures of people, places and things"),
    Group("visualise", 2, ("visualise",),
          r"explain|visuali[sz]e|diagram|illustrate|draw|how does .+ work|show me how|walk me through",
          "explain a topic by drawing a diagram shown in the UI"),
    Group("insight", 2, ("what_next", "generate_retro", "reflect_on_week", "synthesize_vault", "check_suggestions", "show_last_run_trace"),
          r"what (should|next)|what's next|retro|reflect|synthes|suggest|trace|summari[sz]e (my|the) (vault|week)", "what to do next, weekly retro/reflection, vault synthesis"),
    # ---- MCP: subsets by priority ----------------------------------------
    Group("github", 2, (
        "get_me", "set_repo_visibility", "search_repositories", "search_code", "get_file_contents", "list_issues", "issue_read", "issue_write",
        "add_issue_comment", "list_pull_requests", "pull_request_read", "create_pull_request",
        "list_commits", "list_branches", "actions_list", "get_job_logs",
    ), r"github|\brepos?\b|repositor|\b(make|set)\b.*\b(private|public)\b|visibility|pull request|\bpr\b|\bissues?\b|\bcommits?\b|\bbranch|workflow run|ci\b", "GitHub reads, issues, PRs, branches, CI, repo public/private"),
    Group("github_admin", 3, (
        "merge_pull_request", "push_files", "create_branch", "get_commit", "actions_get", "create_or_update_file", "delete_file", "fork_repository", "create_repository",
        "update_pull_request", "update_pull_request_branch", "pull_request_review_write", "add_comment_to_pending_review",
        "add_reply_to_pull_request_comment", "sub_issue_write", "actions_run_trigger",
        "get_label", "get_latest_release", "get_release_by_tag", "get_tag", "list_releases", "list_tags",
        "list_repository_collaborators", "list_issue_fields", "list_issue_types", "search_commits",
        "search_issues", "search_pull_requests",
    ), about="GitHub writes (merge, push, delete, fork, create repo), releases, tags, extra searches"),
    Group("browser", 2, (
        "browser_navigate", "browser_snapshot", "browser_click", "browser_type", "browser_fill_form",
        "browser_take_screenshot", "browser_wait_for", "browser_tabs", "browser_navigate_back",
    ), r"website|web ?page|browse|click|navigate|scrape|log ?in to|fill (in|out)|https?://", "drive a real browser (Playwright)"),
    Group("browser_advanced", 3, (
        "browser_close", "browser_resize", "browser_console_messages", "browser_handle_dialog", "browser_emulate_media",
        "browser_evaluate", "browser_file_upload", "browser_drop", "browser_find", "browser_press_key",
        "browser_network_requests", "browser_network_request", "browser_run_code_unsafe", "browser_drag",
        "browser_hover", "browser_select_option",
    ), about="Playwright extras: JS eval, network, console, uploads, drag, hover"),
    Group("obsidian", 3, (
        "vault_list", "vault_read", "vault_write", "vault_append", "vault_patch", "vault_delete", "vault_move",
        "vault_copy", "vault_get_document_map", "active_file_get_path", "search_query", "search_simple",
        "tag_list", "command_list", "command_execute", "open_file",
    ), about="Obsidian app (needs it running): search, tags, commands. Prefer read_note/list_notes."),
    Group("fetch", 1, ("fetch",), about="fetch a URL as markdown"),
    Group("ask", 1, ("ask_user",), about="ask the user clarifying questions as a form"),
    Group("search", 1, ("web_search",), about="search the web (SearXNG)"),
    # ---- butler ----------------------------------------------------------
    Group("mac", 1, (
        "set_volume", "mute", "unmute", "toggle_wifi", "toggle_bluetooth", "toggle_dnd", "adjust_brightness", "resize_window", "scale_window",
        "lock_screen", "open_app", "quit_app", "list_running_apps", "take_screenshot", "read_clipboard", "write_clipboard",
        "open_url_in_browser", "play_music", "music_control", "now_playing", "list_playlists",
        "set_timer", "list_timers", "cancel_timer",
    )),
    Group("schedule", 2, ("schedule_task", "list_schedules", "pause_schedule", "delete_schedule", "run_schedule_now"),
          r"remind|every|each (day|week|morning|evening)|schedule|daily|weekly|monthly|at \d|tomorrow|cron|recurring|repeat",
          "scheduled tasks and reminders"),
    Group("tasks", 2, ("add_task", "capture_note", "complete_task", "remove_task", "list_tasks"),
          r"task|todo|to-do|remind|capture|jot", "the TODO list and quick capture"),
    Group("mcp_setup", 3, ("list_available_mcp_servers", "configure_mcp_server", "configure_n8n_server"),
          about="connect/configure MCP servers"),
)

# Duplicates of a higher-priority tool: registered, never shown.
HIDDEN = frozenset({"what_next_smart", "generate_retro_smart"})

# One MCP server can expose a hundred tools (Google Workspace). Split it by service, matched on tool
# name, so a request about a spreadsheet offers sheet tools and not Gmail's. First match wins.
SERVICE_SPLITS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "google": (
        ("gmail", r"gmail|email|draft|label|thread", r"gmail|e-?mail|inbox|draft|google"),
        ("calendar", r"event|calendar|freebusy", r"calendar|\bcal\b|event|meeting|schedule|agenda|google"),
        ("sheets", r"sheet|spreadsheet|cell", r"sheet|spreadsheet|google"),
        ("slides", r"slide|presentation", r"slide|presentation|deck|google"),
        ("forms", r"form", r"\bforms?\b|survey|google"),
        ("tasks", r"task", r"google tasks?|google"),
        ("contacts", r"contact", r"contact|google"),
        ("chat", r"chat|space", r"google chat|google"),
        ("docs", r"doc", r"\bdocs?\b|document|google"),
        ("drive", r"", r"drive|file|folder|share|google"),
    ),
}


def service_group(server: str, tool_name: str) -> Group | None:
    """The per-service group for `tool_name` of a split server, else None."""
    for service, name_re, keywords in SERVICE_SPLITS.get(server, ()):
        if re.search(name_re, tool_name, re.IGNORECASE):
            return Group(f"{server}_{service}", 2, (), keywords, f"{server} {service}")
    return None


class ToolSelector(AgentMiddleware):
    """Orders the tools the model sees and drops unusable ones (see module docstring).
    Create one per agent.

    `persona_groups` limits which curated groups apply to this persona (a tool
    listed in two groups resolves to the first one the persona has).
    `server_groups` maps tool name -> MCP server for servers with no curated
    group, which then get one P2 group each."""

    def __init__(self, tools: list[BaseTool], persona_groups: set[str] | None = None,
                 server_groups: dict[str, str] | None = None) -> None:
        super().__init__()
        self._tool_group: dict[str, Group] = {}
        self._groups: dict[str, Group] = {}
        for t in tools:
            group = next((g for g in GROUPS if t.name in g.tools and (persona_groups is None or g.name in persona_groups)), None)
            server = (server_groups or {}).get(t.name)
            if group is None and server:
                split = service_group(server, t.name)
                group = (split and self._groups.get(split.name)) or split or self._groups.get(server) or Group(server, 2, (), re.escape(server), f"{server} MCP server")
            if group and t.name not in HIDDEN:
                self._tool_group[t.name] = group
                self._groups.setdefault(group.name, group)

    def active_groups(self, messages: list) -> set[str]:
        """Every group is on offer on every turn."""
        return set(self._groups)

    def _rank(self, name: str) -> tuple[int, int]:
        group = self._tool_group.get(name)
        if group is None:
            return (0, 0)
        return (group.priority, group.tools.index(name) if name in group.tools else 0)

    def wrap_model_call(self, request: ModelRequest, handler):
        shown = [t for t in request.tools if t.name in self._tool_group and dependency_is_up(t.name)]
        shown.sort(key=lambda t: self._rank(t.name))  # most important groups first
        return handler(request.override(tools=shown))


def filter_prompt(prompt: str, section_groups: dict[str, str], active: set[str]) -> str:
    """Drop `## ` sections of `prompt` whose tool group is not active, so the
    system prompt never describes tools the model cannot call. Sections not
    in `section_groups` are always kept."""
    head, *sections = prompt.split("\n## ")
    kept = [s for s in sections if section_groups.get(s.split("\n", 1)[0].strip(), "core") in active or section_groups.get(s.split("\n", 1)[0].strip()) is None]
    return "\n## ".join([head, *kept])
