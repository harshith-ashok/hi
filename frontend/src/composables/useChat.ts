// Owns the turn list and translates the raw AG-UI event stream into
// rich per-turn segments (thinking / tool call / text / subagent /
// pending-approval) — the actual "show everything that happens in the
// background" logic. One state machine per assistant turn: segments
// are appended to in event order, so replaying them is exactly
// replaying what happened, in the order it happened.

import { reactive, ref } from 'vue'
import { streamQuery } from '../backend'
import type {
  AguiEvent,
  ChatTurn,
  PendingSegment,
  SubagentSegment,
  ThinkingSegment,
  ToolSegment,
} from '../types'

function lastThinking(turn: ChatTurn): ThinkingSegment | undefined {
  const seg = turn.segments[turn.segments.length - 1]
  return seg?.kind === 'thinking' ? seg : undefined
}

function findTool(turn: ChatTurn, id: string | undefined): ToolSegment | undefined {
  if (!id) return undefined
  return turn.segments.find((s) => s.kind === 'tool' && s.id === id) as ToolSegment | undefined
}

function findSubagent(turn: ChatTurn, taskId: string | undefined): SubagentSegment | undefined {
  if (!taskId) return undefined
  return turn.segments.find((s) => s.kind === 'subagent' && s.taskId === taskId) as
    | SubagentSegment
    | undefined
}

function findPending(turn: ChatTurn, id: unknown): PendingSegment | undefined {
  if (typeof id !== 'string') return undefined
  return turn.segments.find((s) => s.kind === 'pending' && s.id === id) as PendingSegment | undefined
}

export function useChat() {
  const turns = ref<ChatTurn[]>([])
  const isBusy = ref(false)
  let controller: AbortController | null = null

  function newChat() {
    controller?.abort()
    turns.value = []
    isBusy.value = false
  }

  function applyEvent(turn: ChatTurn, event: AguiEvent) {
    switch (event.type) {
      case 'CUSTOM':
        applyCustom(turn, event)
        return

      case 'THINKING_START':
        turn.segments.push(reactive({ kind: 'thinking', text: '', open: true }))
        return
      case 'THINKING_TEXT_MESSAGE_CONTENT': {
        const seg = lastThinking(turn)
        if (seg) seg.text += event.delta ?? ''
        return
      }
      case 'THINKING_END': {
        const seg = lastThinking(turn)
        if (seg) seg.open = false
        return
      }

      case 'TOOL_CALL_START':
        turn.segments.push(
          reactive({ kind: 'tool', id: event.toolCallId ?? '', name: event.toolCallName ?? '?', args: '', open: true }),
        )
        return
      case 'TOOL_CALL_ARGS': {
        const seg = findTool(turn, event.toolCallId)
        if (seg) seg.args += event.delta ?? ''
        return
      }
      case 'TOOL_CALL_END': {
        const seg = findTool(turn, event.toolCallId)
        if (seg) seg.open = false
        return
      }
      case 'TOOL_CALL_RESULT': {
        const seg = findTool(turn, event.toolCallId)
        if (seg) seg.result = event.content ?? ''
        return
      }

      case 'TEXT_MESSAGE_CONTENT': {
        // A subagent's own answer (orchestrated runs) carries
        // subagentRunId and routes into that specific card instead of
        // the turn's general text flow.
        if (event.subagentRunId) {
          const seg = findSubagent(turn, event.subagentRunId)
          if (seg) seg.text = (seg.text ?? '') + (event.delta ?? '')
          return
        }
        const last = turn.segments[turn.segments.length - 1]
        if (last && last.kind === 'text') {
          last.text += event.delta ?? ''
        } else {
          turn.segments.push(reactive({ kind: 'text', text: event.delta ?? '' }))
        }
        return
      }

      case 'SUBAGENT_STARTED':
        turn.segments.push(
          reactive({
            kind: 'subagent',
            taskId: event.subagentRunId ?? '',
            persona: (event.name as string) ?? '?',
            status: 'started',
          }),
        )
        return
      case 'SUBAGENT_FINISHED': {
        const seg = findSubagent(turn, event.subagentRunId)
        if (seg) {
          seg.status = 'finished'
          if (event.result) seg.text = event.result
        }
        return
      }
      case 'SUBAGENT_ERROR': {
        const seg = findSubagent(turn, event.subagentRunId)
        if (seg) {
          seg.status = 'error'
          seg.text = event.message
        }
        return
      }

      case 'RUN_ERROR':
        turn.role = 'error'
        turn.segments.push(reactive({ kind: 'text', text: event.message ?? 'Something went wrong.' }))
        return

      default:
        return // RUN_STARTED/RUN_FINISHED/TEXT_MESSAGE_START/TEXT_MESSAGE_END need no segment change
    }
  }

  function applyCustom(turn: ChatTurn, event: AguiEvent) {
    const value = event.value ?? {}
    switch (event.name) {
      case 'persona_selected':
        turn.persona = value.name as string
        turn.tier = value.tier as string
        turn.orchestrated = Boolean(value.plan)
        return
      case 'subagent_retrying': {
        const seg = findSubagent(turn, event.subagentRunId ?? (value.task_id as string))
        if (seg) seg.status = 'retrying'
        return
      }
      case 'pending_action':
        turn.segments.push(
          reactive({ kind: 'pending', id: value.id as string, description: value.description as string }),
        )
        return
      case 'pending_action_resolved': {
        const seg = findPending(turn, value.id)
        if (seg) seg.resolution = Boolean(value.approved)
        return
      }
      default:
        return // spoken_summary, mcp_ui_widget: not rendered in this text-first trace view
    }
  }

  async function submit(text: string, persona: string | null) {
    const trimmed = text.trim()
    if (!trimmed || isBusy.value) return

    turns.value.push(
      reactive({ id: crypto.randomUUID(), role: 'user', segments: [{ kind: 'text', text: trimmed }], streaming: false }),
    )
    const assistantTurn = reactive<ChatTurn>({
      id: crypto.randomUUID(),
      role: 'assistant',
      segments: [],
      streaming: true,
    })
    turns.value.push(assistantTurn)

    isBusy.value = true
    controller = new AbortController()
    try {
      for await (const event of streamQuery(trimmed, persona, controller.signal)) {
        applyEvent(assistantTurn, event)
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        assistantTurn.role = 'error'
        assistantTurn.segments.push(
          reactive({ kind: 'text', text: (e as Error).message || 'Lost connection to the backend.' }),
        )
      }
    } finally {
      assistantTurn.streaming = false
      isBusy.value = false
    }
  }

  return { turns, isBusy, submit, newChat }
}
