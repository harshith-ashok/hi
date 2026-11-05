// Turns the AG-UI event stream into a flat, append-only transcript.

import { reactive, ref } from 'vue'
import { streamQuery, type AguiEvent } from './backend'

export type Kind = 'user' | 'note' | 'error' | 'thinking' | 'text' | 'tool'

export interface Entry {
  id: number
  kind: Kind
  text: string
  name?: string // tool name
  result?: string
}

export function useChat() {
  const entries = ref<Entry[]>([])
  const busy = ref(false)
  let controller: AbortController | null = null
  let nextId = 0

  function add(kind: Kind, text = '', extra: Partial<Entry> = {}): Entry {
    const entry = reactive<Entry>({ id: nextId++, kind, text, ...extra })
    entries.value.push(entry)
    return entry
  }

  async function ask(text: string, persona: string | null) {
    add('user', text)
    busy.value = true
    controller = new AbortController()

    let thinking: Entry | null = null
    let answer: Entry | null = null
    const tools = new Map<string, Entry>()

    const apply = (e: AguiEvent) => {
      switch (e.type) {
        case 'CUSTOM':
          if (e.name === 'persona_selected') {
            const v = e.value ?? {}
            add('note', `${v.name}/${v.tier}${v.plan ? ' · plan' : ''}`)
          } else if (e.name === 'subagent_retrying') {
            add('note', `retrying ${e.value?.task_id}: ${e.value?.reason}`)
          }
          break
        case 'THINKING_TEXT_MESSAGE_CONTENT':
          thinking ??= add('thinking')
          thinking.text += e.delta ?? ''
          break
        case 'TOOL_CALL_START':
          tools.set(e.toolCallId ?? '', add('tool', '', { name: e.toolCallName ?? '?' }))
          break
        case 'TOOL_CALL_ARGS':
          if (tools.has(e.toolCallId ?? '')) tools.get(e.toolCallId ?? '')!.text += e.delta ?? ''
          break
        case 'TOOL_CALL_RESULT': {
          const tool = tools.get(e.toolCallId ?? '')
          if (tool) tool.result = e.content ?? ''
          thinking = answer = null // anything after a tool call is a fresh block
          break
        }
        case 'TEXT_MESSAGE_CONTENT':
          if (e.subagentRunId) break
          answer ??= add('text')
          answer.text += e.delta ?? ''
          break
        case 'SUBAGENT_STARTED':
          add('note', `[${e.subagentRunId}: ${e.name}] started`)
          break
        case 'SUBAGENT_FINISHED':
          add('note', `[${e.subagentRunId}] done`)
          break
        case 'SUBAGENT_ERROR':
          add('error', `[${e.subagentRunId}] ${e.message}`)
          break
        case 'RUN_ERROR':
          add('error', e.message ?? 'something went wrong')
          break
      }
    }

    const started = performance.now()
    try {
      for await (const event of streamQuery(text, persona, controller.signal)) apply(event)
    } catch (err) {
      if ((err as Error).name === 'AbortError') add('note', '(cancelled)')
      else add('error', (err as Error).message || 'lost connection to the backend')
    } finally {
      busy.value = false
      add('note', `${((performance.now() - started) / 1000).toFixed(1)}s`)
    }
  }

  const cancel = () => controller?.abort()
  const clear = () => (entries.value = [])

  return { entries, busy, add, ask, cancel, clear }
}
