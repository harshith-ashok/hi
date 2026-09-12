"""On-demand agents (TODO.md Phase 27), per explicit request: "I can give
them tasks and it will do that based on prompts I give. Before it
finalizes and starts implementing it should ask me questions to clarify
the instructions."

Reuses the orchestrator's existing subagent infrastructure
(`hi/orchestrator/subagent.py`'s `build_subagent()`) rather than a new
execution mechanism — an on-demand agent is exactly one scoped ReAct
agent given a self-contained task, the same shape as one DAG node.

Runtime state is in-memory (a `threading.Lock` + module dict), the same
pattern `hi/orchestrator/pending_actions.py` already established for
"this process's own live coordination state, not a second persistence
layer" — a finished run (done or error) is additionally written as a
durable Markdown record into the vault, matching this project's
"filesystem is the source of truth" stance for anything meant to
outlive the process.

Lifecycle: clarifying -> ready -> running -> done | error. A preset
(already well-specified by definition) skips straight past clarifying —
the frontend's "one-click" agents.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from langchain_core.messages import HumanMessage

from hi.frontmatter import with_frontmatter as _build_frontmatter
from hi.model_warmup import invoke_with_retry
from hi.models import get_tier_model, get_tier_model_fast
from hi.orchestrator.pending_actions import mark_orchestrated_active, mark_orchestrated_done
from hi.orchestrator.subagent import build_subagent
from hi.router import classify
from hi.vault import knowledge_dir

MAX_CLARIFICATION_ROUNDS = 2
MAX_QUESTIONS_PER_ROUND = 3

# Presets: already well-specified plain-language tasks — the frontend's
# "one-click" agents skip clarification entirely since there's nothing
# genuinely ambiguous left to ask about. Kept short and few on purpose;
# add more here as real recurring asks emerge rather than guessing at a
# long list upfront.
PRESETS: dict[str, str] = {
    "daily-summary": "Summarize what I've worked on today across my dev projects and vault notes.",
    "uncommitted-changes": "Check every known dev project for uncommitted git changes and list what's outstanding, project by project.",
    "upcoming-deadlines": "Find and summarize my upcoming deadlines across tracked tasks and applications, soonest first.",
}


@dataclass
class AgentRun:
    id: str
    prompt: str
    status: str  # "clarifying" | "ready" | "running" | "done" | "error"
    created_at: float
    preset: str | None = None
    questions: list[str] = field(default_factory=list)
    qa: list[dict[str, str]] = field(default_factory=list)
    rounds: int = 0
    persona: str | None = None
    mcp_server: str | None = None
    result: str = ""
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "status": self.status,
            "created_at": self.created_at,
            "preset": self.preset,
            "questions": self.questions,
            "qa": self.qa,
            "persona": self.persona,
            "mcp_server": self.mcp_server,
            "result": self.result,
            "error": self.error,
        }


_lock = threading.Lock()
_runs: dict[str, AgentRun] = {}


def list_runs() -> list[AgentRun]:
    with _lock:
        return sorted(_runs.values(), key=lambda r: r.created_at, reverse=True)


def get_run(run_id: str) -> AgentRun | None:
    with _lock:
        return _runs.get(run_id)


def list_presets() -> dict[str, str]:
    return dict(PRESETS)


def create_run(prompt: str, preset: str | None = None, mcp_server: str | None = None) -> AgentRun:
    """Starts a new on-demand agent. `preset`, if given and recognized,
    overrides `prompt` with the preset's own well-specified task text
    and skips clarification. Otherwise generates clarifying questions
    (if the task actually needs any) before anything runs.

    `mcp_server`, if given, must be one of get_mcp_tools_by_server()'s
    keys (a server that's actually configured and reachable right now)
    — per explicit request: "I want to create agents that can
    communicate with the mcp I assign." Checked eagerly, not deferred
    until execution, so a bad assignment fails immediately rather than
    silently running without the tools the user thought they were
    granting."""
    if mcp_server is not None:
        from hi.mcp_tools import get_mcp_tools_by_server

        if mcp_server not in get_mcp_tools_by_server():
            run = AgentRun(
                id=uuid4().hex[:10], prompt=prompt, status="error", created_at=time.time(),
                mcp_server=mcp_server,
                error=f"MCP server '{mcp_server}' isn't currently configured and reachable.",
            )
            with _lock:
                _runs[run.id] = run
            return run

    task_text = PRESETS.get(preset, prompt) if preset else prompt
    run = AgentRun(
        id=uuid4().hex[:10], prompt=task_text, status="clarifying", created_at=time.time(),
        preset=preset, mcp_server=mcp_server,
    )
    with _lock:
        _runs[run.id] = run

    if preset in PRESETS:
        run.status = "ready"
        _start_execution(run)
        return run

    questions = _generate_clarifying_questions(task_text, _mcp_context(mcp_server))
    if not questions:
        run.status = "ready"
        _start_execution(run)
    else:
        run.questions = questions
    return run


def answer_questions(run_id: str, answers: list[str]) -> AgentRun | None:
    """Records answers to the run's current questions. Either surfaces
    another (bounded) round of questions or moves to execution — never
    asks forever."""
    run = get_run(run_id)
    if run is None or run.status != "clarifying":
        return run

    for question, answer in zip(run.questions, answers):
        run.qa.append({"question": question, "answer": answer})
    run.rounds += 1

    if run.rounds >= MAX_CLARIFICATION_ROUNDS:
        run.status = "ready"
        _start_execution(run)
        return run

    context = f"{_mcp_context(run.mcp_server)}\n{_qa_context(run)}".strip()
    more_questions = _generate_clarifying_questions(run.prompt, context)
    if not more_questions:
        run.status = "ready"
        _start_execution(run)
    else:
        run.questions = more_questions
    return run


def _qa_context(run: AgentRun) -> str:
    return "\n".join(f"Q: {qa['question']}\nA: {qa['answer']}" for qa in run.qa)


def _mcp_context(mcp_server: str | None) -> str:
    """Told to the clarifying-question generator so it doesn't ask about
    things an assigned MCP server already resolves (which instance,
    what credentials) — that connection is already configured server-
    side the moment `mcp_server` is set; only genuinely open questions
    about the task itself should come back."""
    if not mcp_server:
        return ""
    return (
        f"This agent has already been given a working, pre-configured connection "
        f"to the '{mcp_server}' MCP server for this task — do not ask which instance, "
        f"URL, or credentials to use for it, that's already handled."
    )


def _generate_clarifying_questions(task_description: str, context: str = "") -> list[str]:
    """Reasoning off (get_tier_model_fast) — this is a judgment call
    about ambiguity, the same shape as memory_graph.py's/vault_rag.py's
    note-relevance selection this same session already found runs much
    faster without visible chain-of-thought, and the user is actively
    waiting on this specific call to see the questions at all."""
    model = get_tier_model_fast("sonnet")
    prompt = (
        "A user wants to spin up an autonomous agent for this task:\n\n"
        f"{task_description}\n\n"
        + (f"Already clarified so far:\n{context}\n\n" if context else "")
        + "If the task is ambiguous or underspecified in a way that would "
        "genuinely change what the agent does or produces, ask up to "
        f"{MAX_QUESTIONS_PER_ROUND} short, specific clarifying questions "
        "— one per line, nothing else. Don't ask about anything a "
        "reasonable default already handles fine. If the task is "
        "already clear enough to act on as-is, reply with exactly the "
        "single word NONE and nothing else."
    )
    reply = invoke_with_retry(model, [HumanMessage(prompt)]).strip()
    if not reply or reply.strip().upper() == "NONE":
        return []
    questions = [line.strip("-•* ").strip() for line in reply.splitlines() if line.strip()]
    return questions[:MAX_QUESTIONS_PER_ROUND]


def _finalized_task_text(run: AgentRun) -> str:
    if not run.qa:
        return run.prompt
    return f"{run.prompt}\n\nClarifications:\n{_qa_context(run)}"


def _start_execution(run: AgentRun) -> None:
    run.status = "running"
    threading.Thread(target=_run_agent, args=(run,), daemon=True).start()


def _run_agent(run: AgentRun) -> None:
    task_text = _finalized_task_text(run)
    try:
        persona, tier = classify(task_text)
    except Exception:
        persona, tier = "term", "sonnet"
    run.persona = persona

    # Same window pending_actions.py's own docstring describes for an
    # orchestrated subagent: no terminal pane this background thread
    # could sensibly block on for a destructive-action confirmation, so
    # any such tool call must route to the async pending-approval queue
    # instead of a blocking input().
    mark_orchestrated_active()
    try:
        model = get_tier_model(tier)
        extra_tools = None
        extra_prompt = None
        if run.mcp_server:
            from hi.mcp_tools import get_mcp_tools_by_server

            extra_tools = get_mcp_tools_by_server().get(run.mcp_server, [])
            extra_prompt = (
                f"You have also been given tools from the '{run.mcp_server}' MCP server "
                "specifically for this task — use them when they're the right way to "
                "accomplish what's asked, the same as any of your other tools."
            )
        agent = build_subagent(model, persona, extra_tools=extra_tools, extra_prompt=extra_prompt)
        result = agent.invoke({"messages": [{"role": "user", "content": task_text}]})
        messages = result.get("messages", [])
        run.result = messages[-1].content if messages else "(no output)"
        run.status = "done"
    except Exception as e:
        run.error = str(e)
        run.status = "error"
    finally:
        mark_orchestrated_done()

    _persist(run)


def _persist(run: AgentRun) -> None:
    """Durable record of a finished run — vault-backed Markdown, same
    frontmatter convention as every other note, so it's readable/
    prunable by hand and searchable via the vault's own tag search."""
    try:
        agents_dir = knowledge_dir() / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        created = datetime.fromtimestamp(run.created_at).strftime("%Y-%m-%d %H:%M:%S")
        qa_section = (
            "\n".join(f"- **{qa['question']}** {qa['answer']}" for qa in run.qa) or "(none needed)"
        )
        body = (
            f"# On-demand agent — {run.id}\n\n"
            f"**Created:** {created}\n"
            f"**Persona:** {run.persona or '(unassigned)'}\n"
            f"**MCP server:** {run.mcp_server or '(none)'}\n"
            f"**Status:** {run.status}\n\n"
            f"## Task\n\n{run.prompt}\n\n"
            f"## Clarifications\n\n{qa_section}\n\n"
            f"## Result\n\n{run.result if run.status == 'done' else (run.error or '(none)')}\n"
        )
        content = _build_frontmatter(body, {"tags": ["hi", "agent-run"], "status": run.status})
        (agents_dir / f"{run.id}.md").write_text(content)
    except Exception:
        pass  # a persistence failure shouldn't hide a real run result from the live in-memory state
