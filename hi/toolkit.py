"""Tool registry + per-turn tool selection.

A persona may own 130+ tools (native + MCP), but a model only reasons well
over a handful. Every tool belongs to a *group*, and every group has a
priority that decides when the model sees it:

  P1  always offered              (the core of the persona)
  P2  offered when the user's message matches the group's keywords
  P3  offered only after the model asks for it with `more_tools(group)`
  --  hidden: duplicates of a higher-priority tool, never offered

The agent still *registers* every tool (so anything offered can run); the
`ToolSelector` middleware only narrows what the model sees on each call.
Selection is keyword rules over the latest user message: no extra model call.

Tools not listed here are grouped by MCP server (P2, matched by server name),
so a newly configured server is reachable instead of silently dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from langchain.agents.middleware import AgentMiddleware, ModelRequest
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, tool

MAX_VISIBLE = 50


@dataclass(frozen=True)
class Group:
    name: str
    priority: int  # 1 always · 2 on keyword match · 3 on request only
    tools: tuple[str, ...]
    keywords: str = ""  # regex, case-insensitive (P2 only)
    about: str = ""  # one line shown in more_tools()


GROUPS: tuple[Group, ...] = (
    # ---- term: core -------------------------------------------------------
    Group("core", 1, (
        "run_shell_command", "search_vault", "read_vault_note", "read_project_file", "list_project_files", "search_files",
        "edit_project_file", "write_project_file",
        "read_note", "list_notes", "create_note", "append_note",
    )),
    # ---- term: native, on keyword ----------------------------------------
    Group("background", 2, ("list_background_tasks", "check_background_task", "stop_background_task", "check_dev_servers"),
          r"background|long[- ]running|dev server|still running|stop (the|that)|process", "background shell tasks, dev servers"),
    Group("devflow", 2, ("open_dev_flow", "add_dev_flow", "resume_context", "save_project_to_vault"),
          r"dev flow|workflow|set up my|start working|resume|pick up where|save (this )?project", "dev flows, resume context, save project to the vault"),
    Group("screen", 2, ("read_screen", "ask_about_screen", "observe_current_tab", "open_url_in_browser"),
          r"screen|tab\b|browser|looking at|displayed|this error|image|diagram|open (the )?(url|link|site)", "what is on screen / in the browser tab, open a URL"),
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
    Group("sandbox", 2, ("run_python",),
          r"python|\bplot|\bgraph\b|\bchart|visuali[sz]|regression|classif|cluster|train(ing)? (a |the )?model|machine learning|\bml\b|matplotlib|numpy|pandas|scikit|sklearn|dataset|histogram|scatter|simulat|\bcompute\b|calculate",
          "run Python in a sandbox: calculations, ML, charts shown in the UI"),
    Group("web", 2, ("search_wikipedia", "find_image"),
          r"wikipedia|who is|who was|what is|what are|look up|define|history of|picture|photo|\bimage|\bpic\b|show me (a|an)\b",
          "Wikipedia lookups and pictures of people, places and things"),
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
    # ---- butler ----------------------------------------------------------
    Group("mac", 1, (
        "set_volume", "mute", "unmute", "toggle_wifi", "toggle_bluetooth", "toggle_dnd", "adjust_brightness",
        "lock_screen", "open_app", "quit_app", "list_running_apps", "take_screenshot", "read_clipboard", "write_clipboard",
        "open_url_in_browser", "play_music", "music_control", "now_playing", "list_playlists",
    )),
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
    """Narrows the tools the model sees on each call (see module docstring).
    Create one per agent; `more_tools` is that agent's escape hatch.

    `persona_groups` limits which curated groups apply to this persona (a tool
    listed in two groups resolves to the first one the persona has).
    `server_groups` maps tool name -> MCP server for servers with no curated
    group, which then get one P2 group each."""

    def __init__(self, tools: list[BaseTool], persona_groups: set[str] | None = None,
                 server_groups: dict[str, str] | None = None) -> None:
        super().__init__()
        self._unlocked: set[str] = set()
        self._turn_text = ""
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
        self.more_tools = self._make_more_tools()

    def _make_more_tools(self) -> BaseTool:
        selector = self

        @tool
        def more_tools(group: str) -> str:
            """Make another group of tools available for the rest of this turn.
            Call this when you need a capability none of your current tools provide."""
            if group not in selector._groups:
                return f"Unknown group '{group}'. Available: {', '.join(selector._groups)}"
            selector._unlocked.add(group)
            names = [n for n, g in selector._tool_group.items() if g.name == group]
            return f"Unlocked '{group}'. You can now call: {', '.join(names)}"

        menu = "\n".join(f"- {g.name}: {g.about}" for g in self._groups.values() if g.priority >= 2 and g.about)
        more_tools.description += "\nGroups:\n" + menu
        return more_tools

    def active_groups(self, messages: list) -> set[str]:
        """Groups on offer for the turn these messages belong to."""
        humans = [m for m in messages if isinstance(m, HumanMessage)]
        text = str(humans[-1].content) if humans else ""
        if text != self._turn_text:  # a new user message starts a new turn
            self._turn_text, self._unlocked = text, set()
        return self._active_groups(text)

    def _active_groups(self, text: str) -> set[str]:
        active = set(self._unlocked)
        for g in self._groups.values():
            if g.priority == 1 or (g.priority == 2 and g.keywords and re.search(g.keywords, text, re.IGNORECASE)):
                active.add(g.name)
        return active

    def _rank(self, name: str) -> tuple[int, int]:
        group = self._tool_group.get(name)
        if group is None:
            return (0, 0)
        return (group.priority, group.tools.index(name) if name in group.tools else 0)

    def wrap_model_call(self, request: ModelRequest, handler):
        active = self.active_groups(request.messages)
        shown = [t for t in request.tools if t.name == "more_tools" or (t.name in self._tool_group and self._tool_group[t.name].name in active)]
        # priority first, then the order tools are listed in their group, so a cap cuts the least important
        shown.sort(key=lambda t: self._rank(t.name))
        return handler(request.override(tools=shown[: MAX_VISIBLE + 1]))


def filter_prompt(prompt: str, section_groups: dict[str, str], active: set[str]) -> str:
    """Drop `## ` sections of `prompt` whose tool group is not active, so the
    system prompt never describes tools the model cannot call. Sections not
    in `section_groups` are always kept."""
    head, *sections = prompt.split("\n## ")
    kept = [s for s in sections if section_groups.get(s.split("\n", 1)[0].strip(), "core") in active or section_groups.get(s.split("\n", 1)[0].strip()) is None]
    return "\n## ".join([head, *kept])
