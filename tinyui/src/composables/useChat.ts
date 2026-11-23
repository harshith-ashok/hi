// Turns the AG-UI event stream into turns: what you asked, and every step the assistant took to answer, each with the
// time it started and ended, so the chat can show real progress instead of a spinner.

import { reactive, ref } from 'vue'
import { streamQuery, type AguiEvent } from '@/backend'
import type { SavedArtifact } from '@/composables/useArtifact'

export interface ToolBlock { kind: 'tool'; id: string; name: string; args: string; result?: string; t0: number; t1?: number }
export interface ThinkBlock { kind: 'thinking'; text: string; t0: number; t1?: number }
export interface TextBlock { kind: 'text'; text: string; t0: number; t1?: number }
export type Block = ToolBlock | ThinkBlock | TextBlock

/** The attempts at one point in a chat: this turn is number `index` of `count` (ids oldest first). */
export interface Versions { index: number; count: number; ids: string[] }

export interface Visual { state: 'none' | 'pending' | 'ready' | 'failed'; mermaid: string; t0?: number; t1?: number }

export interface Turn {
  id: number
  serverId?: string // the backend's id for this turn (hi/memory/transcript.py); known once the turn is saved
  parent?: string // the id of the turn it follows in its chat
  artifacts?: SavedArtifact[] // pages, documents and diagrams this turn made (saved by the backend)
  versions?: Versions // other attempts at this point (after an edit or "ask again")
  ask: string
  files: string[]
  t0: number
  t1?: number
  status: 'running' | 'done' | 'error' | 'cancelled'
  route?: { persona: string; tier: string; plan: boolean; at: number }
  context?: { memory: number; notes: string[]; at: number }
  blocks: Block[]
  visual: Visual
  server?: { route_s: number; first_token_s: number | null; total_s: number; tools: { name: string; s: number }[] }
  error?: string
  notes: string[]
  restored?: boolean // loaded from a saved session: no step timings, only the total
  seconds?: number
}

/** A turn as the backend saves it (hi/memory/transcript.py). */
export interface StoredTurn {
  id: string
  parent: string
  versions?: Versions | null
  artifacts?: SavedArtifact[]
  time: string
  ask: string
  answer: string
  tools: { name: string; args: string; result: string }[]
  persona: string
  tier: string
  seconds: number
  visual: string
  error: string
  plan: boolean
}

/** How full the model's context window was for the latest turn (the backend estimates tokens). */
export interface ContextWindow { used: number; limit: number; dropped_turns: number }

export interface AskOptions {
  persona?: string | null
  attachments?: string[]
  names?: string[]
  session?: string
  visualize?: boolean
  parent?: string // the turn this one follows; set for an edit or "ask again"
  think?: boolean // false: answer without streamed reasoning
  style?: string // a writing style id from GET /styles ('normal' or none = how hi usually writes)
  tier?: string // haiku | sonnet | opus, or 'auto' to let the router choose
}

let nextId = 0

export const answerOf = (turn: Turn) => turn.blocks.filter((b): b is TextBlock => b.kind === 'text').map((b) => b.text).join('\n\n')
export const toolsOf = (turn: Turn) => turn.blocks.filter((b): b is ToolBlock => b.kind === 'tool')

export function fromStored(stored: StoredTurn): Turn {
  const at = Date.parse(stored.time) || Date.now()
  const blocks: Block[] = stored.tools.map((t, i) => ({ kind: 'tool', id: `r${nextId}-${i}`, name: t.name, args: t.args, result: t.result, t0: at, t1: at }))
  if (stored.answer) blocks.push({ kind: 'text', text: stored.answer, t0: at, t1: at })
  return reactive<Turn>({
    id: nextId++, serverId: stored.id || undefined, parent: stored.parent || undefined, versions: stored.versions ?? undefined, artifacts: stored.artifacts?.length ? stored.artifacts : undefined, ask: stored.ask, files: [], t0: at, t1: at + (stored.seconds || 0) * 1000,
    status: stored.error === 'stopped' ? 'cancelled' : stored.error && !stored.answer ? 'error' : 'done',
    route: stored.persona ? { persona: stored.persona, tier: stored.tier, plan: stored.plan, at } : undefined,
    blocks, visual: { state: stored.visual ? 'ready' : 'none', mermaid: stored.visual },
    error: stored.error && stored.error !== 'stopped' ? stored.error : undefined, notes: [], restored: true, seconds: stored.seconds,
  })
}

export function useChat(hooks: { onSpoken?: (text: string) => void; onDone?: (turn: Turn) => void; onArtifact?: (saved: SavedArtifact) => void } = {}) {
  const turns = ref<Turn[]>([])
  const busy = ref(false)
  const contextWindow = ref<ContextWindow | null>(null)
  let controller: AbortController | null = null

  const current = () => turns.value[turns.value.length - 1]

  /** End the block that is still open, so its duration is known. */
  function closeOpen(turn: Turn, now = Date.now()) {
    const last = turn.blocks[turn.blocks.length - 1]
    if (last && last.kind !== 'tool' && last.t1 === undefined) last.t1 = now
  }

  function apply(turn: Turn, e: AguiEvent, calls: Map<string, ToolBlock>) {
    const now = Date.now()
    switch (e.type) {
      case 'CUSTOM':
        if (e.name === 'persona_selected') {
          const v = e.value ?? {}
          turn.route = { persona: String(v.name), tier: String(v.tier), plan: !!v.plan, at: now }
        } else if (e.name === 'context_used') {
          const v = e.value as { memory: number; notes: string[] }
          turn.context = { memory: v.memory, notes: v.notes, at: now }
        } else if (e.name === 'artifact') {
          const saved = e.value as unknown as SavedArtifact
          turn.artifacts = [...(turn.artifacts ?? []).filter((a) => a.slug !== saved.slug), saved]
          hooks.onArtifact?.(saved)
        } else if (e.name === 'context_window') {
          contextWindow.value = e.value as unknown as ContextWindow
        } else if (e.name === 'turn') {
          const v = e.value as { id: string; parent: string }
          turn.serverId = v.id
          turn.parent = v.parent || undefined
        } else if (e.name === 'timing') {
          turn.server = e.value as Turn['server']
        } else if (e.name === 'phase' && e.value?.name === 'visualizing') {
          if (e.value.state === 'start') turn.visual = { state: 'pending', mermaid: '', t0: now }
        } else if (e.name === 'visual') {
          const mermaid = String((e.value as { mermaid?: string } | undefined)?.mermaid ?? '')
          turn.visual = { state: mermaid ? 'ready' : 'none', mermaid, t0: turn.visual.t0, t1: now }
        } else if (e.name === 'spoken_summary' || e.name === 'spoken_chunk') {
          const text = (e.value as { text?: string | null } | undefined)?.text
          if (text) hooks.onSpoken?.(text)
        } else if (e.name === 'subagent_retrying') {
          turn.notes.push(`retrying ${e.value?.task_id}: ${e.value?.reason}`)
        }
        break
      case 'THINKING_TEXT_MESSAGE_CONTENT': {
        let last = turn.blocks[turn.blocks.length - 1]
        if (!last || last.kind !== 'thinking' || last.t1 !== undefined) {
          closeOpen(turn, now)
          last = { kind: 'thinking', text: '', t0: now }
          turn.blocks.push(last)
          last = turn.blocks[turn.blocks.length - 1] // the reactive proxy, not the raw object
        }
        ;(last as ThinkBlock).text += e.delta ?? ''
        break
      }
      case 'TOOL_CALL_START': {
        closeOpen(turn, now)
        turn.blocks.push({ kind: 'tool', id: e.toolCallId ?? '', name: e.toolCallName ?? '?', args: '', t0: now })
        calls.set(e.toolCallId ?? '', turn.blocks[turn.blocks.length - 1] as ToolBlock)
        break
      }
      case 'TOOL_CALL_ARGS': {
        const call = calls.get(e.toolCallId ?? '')
        if (call) call.args += e.delta ?? ''
        break
      }
      case 'TOOL_CALL_RESULT': {
        const call = calls.get(e.toolCallId ?? '')
        if (call) {
          call.result = e.content ?? ''
          call.t1 = now
        }
        break
      }
      case 'TEXT_MESSAGE_CONTENT': {
        if (e.subagentRunId) break
        let last = turn.blocks[turn.blocks.length - 1]
        if (!last || last.kind !== 'text' || last.t1 !== undefined) {
          closeOpen(turn, now)
          turn.blocks.push({ kind: 'text', text: '', t0: now })
          last = turn.blocks[turn.blocks.length - 1]
        }
        ;(last as TextBlock).text += e.delta ?? ''
        break
      }
      case 'SUBAGENT_STARTED':
        turn.notes.push(`${e.name} started`)
        break
      case 'SUBAGENT_ERROR':
        turn.notes.push(`${e.subagentRunId}: ${e.message}`)
        break
      case 'RUN_ERROR':
        turn.error = e.message ?? 'something went wrong'
        break
    }
  }

  async function ask(text: string, options: AskOptions = {}) {
    const turn = reactive<Turn>({
      id: nextId++, ask: text, files: options.names ?? [], t0: Date.now(), status: 'running', blocks: [],
      visual: { state: 'none', mermaid: '' }, notes: [],
    })
    turns.value.push(turn)
    const live = current()
    busy.value = true
    controller = new AbortController()
    const calls = new Map<string, ToolBlock>()
    try {
      for await (const event of streamQuery(text, options.persona ?? null, controller.signal, options)) apply(live, event, calls)
      live.status = live.error ? 'error' : 'done'
    } catch (err) {
      if ((err as Error).name === 'AbortError') live.status = 'cancelled'
      else {
        live.status = 'error'
        live.error = (err as Error).message || 'lost connection to the backend'
      }
    } finally {
      closeOpen(live)
      live.t1 = Date.now()
      if (live.visual.state === 'pending') live.visual = { state: 'none', mermaid: '' }
      busy.value = false
      hooks.onDone?.(live)
    }
  }

  const cancel = () => controller?.abort()
  const truncate = (count: number) => { turns.value = turns.value.slice(0, count) } // drop this turn and the ones after it from view
  const clear = () => { turns.value = []; contextWindow.value = null }
  const load = (stored: StoredTurn[]) => { turns.value = stored.map(fromStored); contextWindow.value = null }

  return { turns, busy, contextWindow, ask, cancel, truncate, clear, load }
}
