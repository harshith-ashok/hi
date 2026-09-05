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
