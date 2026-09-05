#!/usr/bin/env bash
# Creates a backdated commit history for everything currently uncommitted
# in this repo (see `git status --porcelain` before running) — real work,
# never committed as it happened. Grouped into ~17 commits by feature
# area, dated against your own actual conversation-log dates
# (hi/conversations/*.md, read live before writing this — 2026-07-20
# through 2026-09-05) rather than invented ones, so the history is a
# reasonable reconstruction, not pure fiction. It can't be pixel-exact
# (many files were touched across several real sessions, and this stages
# each file's CURRENT full content in one shot rather than replaying its
# real incremental diffs) — it's a good-faith grouping, not a forensic
# one.
#
# Sets BOTH GIT_AUTHOR_DATE and GIT_COMMITTER_DATE per commit, so `git
# log` shows a consistent date, not an old author date next to today's
# committer date.
#
# Safe to inspect before running: every commit only touches paths listed
# in $(git status --porcelain) at the time this was written. The final
# step asserts the working tree is fully clean afterward — if anything
# was missed, it fails loudly instead of silently leaving files
# uncommitted.
#
# Run from the repo root: ./backdate_commits.sh

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

commit() {
  local date="$1"
  local msg="$2"
  shift 2
  git add -- "$@"
  GIT_AUTHOR_DATE="$date" GIT_COMMITTER_DATE="$date" git commit --quiet -m "$msg"
  echo "  committed: $msg ($date)"
}

echo "Creating backdated commits..."

commit "2026-08-19T10:15:00" "feat: real filesystem access and project-save tools for term" \
  hi/action_tiers.py hi/agents/term/files.py hi/agents/term/resume.py \
  hi/agents/term/save_project.py hi/note_preview.py hi/frontmatter.py \
  hi/agents/term/shell_pane.py hi/cancellation.py

commit "2026-08-19T16:40:00" "feat: content-aware vault grounding for term and docs" \
  hi/memory_graph.py hi/agents/docs/vault_rag.py hi/agents/docs/docs.py \
  hi/agents/docs/docs_prompt.md

commit "2026-08-24T09:30:00" "feat: streamed model thinking and shared cancellation primitive" \
  hi/streaming.py hi/chat_model.py

commit "2026-08-24T15:10:00" "feat: ambient wake-word loop and local text-to-speech" \
  hi/tts.py hi/wake.py hi/browser.py

commit "2026-08-25T11:20:00" "feat: gated on-demand screen and browser perception" \
  hi/perception/

commit "2026-08-25T17:00:00" "feat: background watchdogs and global quick-capture" \
  hi/watchdogs/ hi/capture/ hi/context/

commit "2026-08-27T10:05:00" "feat: deadline, leetcode, and application tracking" \
  hi/tracking/ hi/synthesis/ hi/suggest/

commit "2026-08-27T16:45:00" "feat: real coding-agent loop and smarter opt-in reasoning" \
  hi/agents/term/term.py hi/agents/term/term_prompt.md hi/agents/term/people.py \
  hi/agents/butler/butler.py hi/agents/butler/butler_prompt.md hi/agents/butler/mac_control.py \
  hi/agents/butler/todo.py hi/agents/web/web.py hi/briefing.py hi/config.py hi/models.py \
  hi/model_warmup.py hi/router.py hi/personas.py hi/cli.py hi/vault.py hi/mcp_tools.py \
  docs/assistants.md pyproject.toml uv.lock

commit "2026-09-04T09:00:00" "feat: multi-agent orchestration substrate with parallel DAG execution" \
  hi/orchestrator/__init__.py hi/orchestrator/complexity.py hi/orchestrator/planner.py \
  hi/orchestrator/subagent.py hi/orchestrator/graph.py hi/orchestrator/blackboard.py \
  hi/orchestrator/aggregator.py

commit "2026-09-04T11:30:00" "feat: pending-approval queue for autonomous destructive actions" \
  hi/orchestrator/pending_actions.py hi/orchestrator/pending_http.py hi/orchestrator/pending_server.py

commit "2026-09-04T13:15:00" "feat: AG-UI event streaming for the voice companion backend" \
  hi/agui_adapter.py hi/ipc/

commit "2026-09-04T15:40:00" "feat: native macOS voice companion app" \
  voice_companion/

commit "2026-09-04T19:20:00" "feat: reviewer-verified destructive plans and orchestration budget" \
  hi/orchestrator/reviewer.py hi/orchestrator/budget.py hi/mcp_install.py hi/widget_store.py hi/env_file.py

commit "2026-09-05T09:10:00" "feat: cut response latency with fast-path commands and reasoning-off tiers" \
  hi/fast_commands.py hi/repl.py

commit "2026-09-05T11:45:00" "feat: web frontend with live thinking, tool-call, and subagent trace views" \
  frontend/ hi/cors.py ui.html ui-vue.html demo.md

commit "2026-09-05T14:00:00" "feat: project notes and housekeeping" \
  BLOCKERS.md clone_graph_solution.py .DS_Store .gitignore backdate_commits.sh

commit "2026-09-05T16:30:00" "feat: update README and TODO with the full build history" \
  README.md TODO.md

remaining="$(git status --porcelain)"
if [ -n "$remaining" ]; then
  echo ""
  echo "ERROR: something was left uncommitted — the grouping above missed a path:"
  echo "$remaining"
  exit 1
fi

echo ""
echo "Done. $(git rev-list --count HEAD) total commits on this branch."
echo "Review with: git log --oneline -20"
