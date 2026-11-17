// Helpers that read a turn: where a tool acts, what it produced, how long each step took, and the run as a diagram.

import { BASE_URL } from '@/backend'
import { label } from '@/lib/mermaid'
import { MESH_EXTENSIONS } from '@/lib/scene3d'
import { answerOf, toolsOf, type Turn } from '@/composables/useChat'

// Charts made by run_python come back as /plots/<name> paths in a tool result.
export const plots = (result?: string) => [...new Set(result?.match(/\/plots\/[\w-]+\.(?:png|jpg|webp|svg)/g) ?? [])].map((p) => BASE_URL + p)

// Files made by run_python (PDF, CSV, ...) come back as /files/<run>/<name> paths.
export const files = (result?: string) =>
  [...new Set(result?.match(/\/files\/[\w.-]+\/[\w.-]+/g) ?? [])].map((p) => ({ href: BASE_URL + p, name: p.split('/').pop() ?? p }))

/** 3D scenes saved by render_3d (/scenes/<name>.json), or written by the sandbox as <name>.scene.json. */
export const scenes = (result?: string) =>
  [...new Set(result?.match(/\/scenes\/[\w-]+\.json|\/files\/[\w.-]+\/[\w.-]+\.scene\.json/g) ?? [])].map((p) => BASE_URL + p)

/** Mesh files the sandbox exported (.glb .gltf .obj .stl .ply). */
export const meshes = (result?: string) => files(result).filter((f) => MESH_EXTENSIONS.test(f.name))

export const short = (s: string, n = 140) => {
  const flat = s.replace(/\s+/g, ' ').trim()
  return flat.length > n ? `${flat.slice(0, n)}…` : flat
}

export const ms = (n: number) => (n < 950 ? `${Math.max(0, Math.round(n))} ms` : n < 60_000 ? `${(n / 1000).toFixed(1)} s` : `${Math.floor(n / 60_000)}m ${Math.round((n % 60_000) / 1000)}s`)

const MAC_TOOLS = /^(set_volume|mute|unmute|toggle_(wifi|bluetooth|dnd)|adjust_brightness|lock_screen|open_app|quit_app|list_running_apps|take_screenshot|read_clipboard|write_clipboard|open_url_in_browser|observe_current_tab|read_screen|ask_about_screen)$/
const GITHUB_TOOLS = /^(get_me|set_repo_visibility|search_(repositories|code|issues|pull_requests|commits)|get_file_contents|list_(issues|pull_requests|commits|branches|releases|tags)|issue_|pull_request|create_(pull_request|branch|repository|or_update_file)|merge_|push_files|fork_|actions_|get_job_logs|add_issue)/

export interface Scope { label: string; tone: 'danger' | 'warn' | 'neutral' }

/** Where a tool acts, so a Mac action never looks like a chat reply. */
export function scope(name = ''): Scope | null {
  if (MAC_TOOLS.test(name)) return { label: 'your Mac', tone: 'danger' }
  if (name === 'run_shell_command') return { label: 'shell', tone: 'danger' }
  if (GITHUB_TOOLS.test(name)) return { label: 'GitHub', tone: 'warn' }
  if (name === 'run_python') return { label: 'sandbox', tone: 'neutral' }
  if (/vault|_note|^list_notes$|conversation/.test(name)) return { label: 'vault', tone: 'neutral' }
  if (/^(search_wikipedia|find_image|fetch|web_search)$|^browser_/.test(name)) return { label: 'web', tone: 'neutral' }
  return null
}

/** The questions of an ask_user call, or [] while its arguments are still streaming. */
export function questionsOf(args: string): string[] {
  try {
    const q = (JSON.parse(args) as { questions?: unknown }).questions
    return Array.isArray(q) ? q.map(String).filter((s) => s.trim()) : []
  } catch {
    return []
  }
}

export type StepState = 'pending' | 'active' | 'done' | 'failed'
export interface Step { key: string; title: string; detail?: string; state: StepState; t0?: number; t1?: number }

const toolTitle = (name: string) => name.replace(/_/g, ' ')

/** The steps of a turn, in order, with the live state of each. `now` is only used for the wait hints. */
export function stepsOf(turn: Turn, now: number): Step[] {
  const running = turn.status === 'running'
  const failed = turn.status === 'error'
  const steps: Step[] = []
  const routeAt = turn.route?.at
  steps.push({
    key: 'route', title: turn.route ? `Chose ${turn.route.persona}${turn.route.plan ? ' (multi-step plan)' : ''}` : 'Choosing an agent',
    detail: turn.route ? turn.route.tier : undefined, state: routeAt ? 'done' : running ? 'active' : failed ? 'failed' : 'pending', t0: turn.t0, t1: routeAt,
  })
  if (turn.context) {
    const n = turn.context.notes.length
    steps.push({ key: 'context', title: 'Loaded context', detail: `${turn.context.memory} memories${n ? ` · ${n} note${n > 1 ? 's' : ''}` : ''}`, state: 'done', t0: routeAt, t1: turn.context.at })
  }
  const first = turn.blocks[0]
  const waitFrom = turn.context?.at ?? routeAt
  if (waitFrom && (running || first)) {
    const waited = (first?.t0 ?? now) - waitFrom
    steps.push({
      key: 'model', title: first ? 'Model responded' : waited > 6000 ? 'Waiting for the model (it may be loading)' : 'Waiting for the model',
      state: first ? 'done' : running ? 'active' : 'failed', t0: waitFrom, t1: first?.t0,
    })
  }
  for (const [i, block] of turn.blocks.entries()) {
    const open = block.t1 === undefined && running
    const state: StepState = open ? 'active' : 'done'
    if (block.kind === 'thinking') steps.push({ key: `b${i}`, title: open ? 'Thinking' : 'Thought it through', state, t0: block.t0, t1: block.t1 })
    else if (block.kind === 'tool') {
      const done = block.result !== undefined
      steps.push({ key: `b${i}`, title: toolTitle(block.name), detail: scope(block.name)?.label, state: done ? 'done' : running ? 'active' : 'failed', t0: block.t0, t1: block.t1 })
    } else steps.push({ key: `b${i}`, title: open ? 'Writing the answer' : 'Wrote the answer', state, t0: block.t0, t1: block.t1 })
  }
  // A tool has answered and the model is reading the result: that wait is a step too, or the header says nothing.
  const last = turn.blocks[turn.blocks.length - 1]
  if (running && last?.kind === 'tool' && last.result !== undefined) {
    steps.push({ key: 'after-tool', title: 'Waiting for the model to read the result', state: 'active', t0: last.t1 })
  }
  if (turn.visual.state === 'pending') steps.push({ key: 'visual', title: 'Drawing a diagram', state: 'active', t0: turn.visual.t0 })
  else if (turn.visual.state === 'ready' && turn.visual.t0) steps.push({ key: 'visual', title: 'Drew a diagram', state: 'done', t0: turn.visual.t0, t1: turn.visual.t1 })
  if (failed) steps.push({ key: 'error', title: 'Stopped with an error', detail: turn.error, state: 'failed' })
  return steps
}

/** The run as a Mermaid flowchart: you → agent → context → each tool → answer, with how long each took. */
export function runDiagram(turn: Turn): string {
  const lines = ['flowchart LR', `  U["You: ${label(turn.ask, 28)}"]`]
  let prev = 'U'
  const add = (id: string, text: string, style = '') => {
    lines.push(`  ${id}["${text}"]${style}`, `  ${prev} --> ${id}`)
    prev = id
  }
  if (turn.route) add('R', `${label(turn.route.persona, 20)} · ${label(turn.route.tier, 12)}`)
  if (turn.context) add('C', `Context: ${turn.context.memory} memories, ${turn.context.notes.length} notes`)
  for (const [i, tool] of toolsOf(turn).entries()) {
    const took = tool.t1 && tool.t0 && !turn.restored ? ` ${ms(tool.t1 - tool.t0)}` : ''
    add(`T${i}`, `${label(toolTitle(tool.name), 28)}${took}`)
  }
  const answer = answerOf(turn)
  if (answer) add('A', `Answer${turn.t1 ? ` ${ms(turn.t1 - turn.t0)}` : ''}`)
  if (turn.visual.state === 'ready') add('V', 'Diagram')
  return lines.join('\n')
}
