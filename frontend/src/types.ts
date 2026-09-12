// Shapes for the AG-UI SSE stream (hi/agui_adapter.py) and the richer
// per-turn "trace" model this frontend builds from it — segments, not
// just a flat string, so a single assistant turn can show its thinking,
// tool calls, and final answer as distinct blocks in order, the way
// Claude/Claude Code's own transcript does, rather than one opaque
// wall of text.

export type Persona = 'term' | 'butler' | 'docs' | 'web'
export type PersonaChoice = Persona | 'auto'

export interface ThinkingSegment {
  kind: 'thinking'
  text: string
  open: boolean // still streaming (or genuinely never closed — see agui_adapter.py's defensive close)
}

export interface ToolSegment {
  kind: 'tool'
  id: string
  name: string
  args: string
  result?: string
  open: boolean
}

export interface TextSegment {
  kind: 'text'
  text: string
}

export interface SubagentSegment {
  kind: 'subagent'
  taskId: string
  persona: string
  status: 'started' | 'retrying' | 'finished' | 'error'
  text?: string
}

export interface PendingSegment {
  kind: 'pending'
  id: string
  description: string
  resolution?: boolean // undefined = awaiting
}

export type TraceSegment = ThinkingSegment | ToolSegment | TextSegment | SubagentSegment | PendingSegment

export interface ChatTurn {
  id: string
  role: 'user' | 'assistant' | 'error'
  persona?: string
  tier?: string
  orchestrated?: boolean
  segments: TraceSegment[]
  streaming: boolean
}

// --- Raw AG-UI wire events this frontend actually reacts to. The real
// schema (ag-ui-protocol) carries more fields than are listed here —
// only what's used is typed, same "don't model the whole schema up
// front" posture BackendClient.swift's own BackendEvent enum documents.
export interface AguiEvent {
  type: string
  name?: string // CUSTOM events only
  value?: Record<string, unknown> // CUSTOM events only
  messageId?: string
  delta?: string
  toolCallId?: string
  toolCallName?: string
  content?: string
  subagentRunId?: string
  result?: string
  message?: string // RUN_ERROR
}

export interface BriefingInfo {
  context: string
  suggestion: string
  action: string
}

export interface PendingActionInfo {
  id: string
  description: string
  created_at: number
}

// --- Home dashboard (ui-vue.html's own template) — every field here is
// real data from hi/dashboard.py, never fabricated. Fields that don't
// have a real backend source (calendar events, Focus/DND read state)
// are deliberately absent, not present-but-fake.
export interface Vitals {
  cpu_percent: number
  memory_percent: number
  battery_percent: number | null
  wifi_ssid: string | null
  active_model: string
  last_latency_ms: number | null
}

export interface VaultStats {
  notes_touched_today: number
  last_edited_note: string | null
}

export interface TodayStats {
  tasks_due_today: number
  next_deadline: string | null
}

export interface ActivityEntry {
  time: string
  persona: string
  text: string
}

// --- On-demand agents (hi/agents_ondemand.py) — a plain-language task
// spun up as a scoped agent, with a clarification round before it
// actually runs. Polled, not streamed (GET /agents/{id}) — same
// "background thread + polling" shape as PendingActionsMonitor.swift,
// not a second SSE surface.
export type AgentRunStatus = 'clarifying' | 'ready' | 'running' | 'done' | 'error'

export interface AgentQA {
  question: string
  answer: string
}

export interface AgentRunInfo {
  id: string
  prompt: string
  status: AgentRunStatus
  created_at: number
  preset: string | null
  questions: string[]
  qa: AgentQA[]
  persona: string | null
  mcp_server: string | null
  result: string
  error: string | null
}

// --- MCP server management (hi/mcp_tools.py / hi/mcp_install.py),
// surfaced in the Agents view per explicit request. `McpServerInfo` is
// the catalog + credential status (GET /mcp/servers); the "assign to an
// agent" picker uses a plain Record<string, number> (server -> live
// tool count, GET /agents/mcp-servers) instead — only servers that are
// actually connected right now are real choices for a new agent.
export interface McpServerInfo {
  name: string
  description: string
  configured: boolean
}

// --- Background tasks (hi/agents/term/background_tasks.py) — a long-
// running shell command (a dev server, a watcher) started by
// run_shell_command, no terminal pane involved at all: tracked here
// instead, live-tailed and stoppable from the Agents view. Replaces the
// old tmux-pane redirect entirely, per explicit request.
export type BackgroundTaskStatus = 'running' | 'exited'

export interface BackgroundTaskInfo {
  id: string
  command: string
  cwd: string | null
  started_at: number
  pid: number
  status: BackgroundTaskStatus
  exit_code: number | null
  output_tail: string
}
