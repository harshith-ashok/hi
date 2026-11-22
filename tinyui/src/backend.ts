// Talks to `hi --voice-daemon` (hi/ipc/server.py). One POST per query,
// streamed back as AG-UI SSE and parsed by hand (EventSource can't POST).

export const BASE_URL: string = import.meta.env.VITE_HI_BACKEND ?? 'http://127.0.0.1:8765' // the override is for testing

// Sent on every request that changes something. A browser only sends a custom header after a CORS preflight, which the
// backend answers for tinyui's own origin only, so another web page cannot approve or delete anything.
const CLIENT = { 'X-Hi-Client': 'tinyui' }

export interface AguiEvent {
  type: string
  name?: string
  value?: Record<string, unknown>
  delta?: string
  toolCallId?: string
  toolCallName?: string
  content?: string
  subagentRunId?: string
  result?: string
  message?: string
}

export interface Pending { id: string; description: string }
export interface Task { id: string; command?: string; prompt?: string; status: string; output_tail?: string; result?: string; error?: string; questions?: string[] }
export interface Models { models: string[]; error: string }

export async function getJson<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${BASE_URL}${path}`)
    return res.ok ? ((await res.json()) as T) : null
  } catch {
    return null
  }
}

export async function postJson<T>(path: string, body: unknown = {}): Promise<T | null> {
  try {
    const res = await fetch(`${BASE_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...CLIENT },
      body: JSON.stringify(body),
    })
    if (!res.ok) return null
    const text = await res.text()
    return (text ? JSON.parse(text) : {}) as T
  } catch {
    return null
  }
}

export async function deleteJson(path: string): Promise<boolean> {
  try {
    return (await fetch(`${BASE_URL}${path}`, { method: 'DELETE', headers: CLIENT })).ok
  } catch {
    return false
  }
}

// /health answers 503 with a body when an essential is down; the body is what the strip shows.
export async function getHealth<T>(): Promise<T | null> {
  try {
    return (await (await fetch(`${BASE_URL}/health`)).json()) as T
  } catch {
    return null
  }
}

export async function patchJson<T>(path: string, body: unknown): Promise<T | null> {
  try {
    const res = await fetch(`${BASE_URL}${path}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json', ...CLIENT }, body: JSON.stringify(body) })
    return res.ok ? ((await res.json()) as T) : null
  } catch {
    return null
  }
}

export const fileAttachment = (id: string) => postJson<{ queued: string }>(`/context/${id}/file`)

export type Config = Record<string, string | boolean | string[]>
export const fetchConfig = (mode?: string) => getJson<Config>(`/config${mode ? `?mode=${mode}` : ''}`)
export const saveConfig = (fields: Record<string, string>) => postJson<{ updated: string[]; note: string }>('/config', fields)
// Like saveConfig, but says why a save was refused (for example a hosted vision model with screenshot watching).
export async function saveConfigChecked(fields: Record<string, string>): Promise<{ ok: boolean; message: string }> {
  try {
    const res = await fetch(`${BASE_URL}/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...CLIENT },
      body: JSON.stringify(fields),
    })
    return { ok: res.ok, message: res.ok ? 'saved' : ((await res.text()) || `failed (${res.status})`) }
  } catch {
    return { ok: false, message: 'backend unreachable' }
  }
}
export const fetchModels = (mode: string, host = '') =>
  getJson<Models>(`/models?mode=${mode}${host ? `&host=${encodeURIComponent(host)}` : ''}`)
export const fetchVoices = () => getJson<{ voices: string[]; error: string }>('/tts/voices')
export const fetchPending = async () => (await getJson<Pending[]>('/pending')) ?? []
export const resolvePending = (id: string, approve: boolean) => postJson(`/pending/${id}/${approve ? 'approve' : 'deny'}`)

export async function ping(): Promise<boolean> {
  try {
    await fetch(`${BASE_URL}/config`)
    return true
  } catch {
    return false
  }
}

export interface Uploaded { id: string; name: string; size: number; chars: number; error?: string }

// Saves a dropped file as context. Never starts a reply.
export async function uploadContext(file: Blob, name: string, kind = ''): Promise<Uploaded> {
  const res = await fetch(`${BASE_URL}/context?name=${encodeURIComponent(name)}${kind ? `&kind=${kind}` : ''}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/octet-stream' },
    body: file,
  })
  const body = (await res.json().catch(() => ({}))) as Uploaded
  if (!res.ok || body.error) throw new Error(body.error ?? `upload failed (${res.status})`)
  return body
}

export interface QueryOptions { attachments?: string[]; session?: string; visualize?: boolean; tier?: string; parent?: string; style?: string; think?: boolean }

export async function* streamQuery(text: string, persona: string | null, signal: AbortSignal, options: QueryOptions = {}): AsyncGenerator<AguiEvent> {
  const res = await fetch(`${BASE_URL}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text,
      persona: persona ?? undefined,
      attachments: options.attachments?.length ? options.attachments : undefined,
      session: options.session || undefined,
      visualize: options.visualize || undefined,
      style: options.style && options.style !== 'normal' ? options.style : undefined, // a writing style from GET /styles
      think: options.think === false ? false : undefined, // false turns streamed reasoning off
      parent: options.parent, // set for an edit or "ask again": the turn it follows ('' = the start of the chat)
      tier: options.tier && options.tier !== 'auto' ? options.tier : undefined, // fast, balanced or deep; omitted = the router chooses
    }),
    signal,
  })
  if (!res.ok || !res.body) throw new Error(`backend returned ${res.status} — is \`hi --voice-daemon\` running?`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try {
        yield JSON.parse(line.slice(6)) as AguiEvent
      } catch {
        // a malformed line is dropped, not fatal to the stream
      }
    }
  }
}

/** A Mermaid diagram of an answer (null when there is nothing to draw). `error` asks for a fix of a diagram that failed to parse. */
export const drawVisual = (question: string, answer: string, error = '') =>
  postJson<{ mermaid: string | null }>('/visual', { question, answer, error })

export interface CanvasItem { id: string; kind: 'text' | 'image' | 'voice' | 'file'; group: string; created: string; name: string; text: string; summary: string; pending: boolean; url: string; x: number; y: number; width: number; height: number }
export interface CanvasGroup { id: string; label: string; x: number; y: number; width: number; height: number; items: CanvasItem[] }
export interface Canvas { groups: CanvasGroup[]; pending: number }

export const fetchCanvas = () => getJson<Canvas>('/canvas')
export const dropText = (text: string) => postJson<{ id: string }>('/canvas/text', { text })
export const regroupCanvas = (all: boolean) => postJson<Canvas & { moved: number }>('/canvas/regroup', { all })
export const moveCanvasItem = (id: string, groupId: string) => patchJson<Canvas>(`/canvas/items/${id}`, { group_id: groupId })
export const renameCanvasGroup = (id: string, label: string) => patchJson<Canvas>(`/canvas/groups/${id}`, { label })
export async function deleteCanvasItem(id: string): Promise<Canvas | null> {
  try {
    const res = await fetch(`${BASE_URL}/canvas/items/${id}`, { method: 'DELETE', headers: CLIENT })
    return res.ok ? ((await res.json()) as Canvas) : null
  } catch {
    return null
  }
}

// Drops a file (or a recorded voice note, kind=audio) onto the board: hi describes it and sorts it into a group.
export async function dropCanvasFile(file: Blob, name: string, kind = ''): Promise<void> {
  const res = await fetch(`${BASE_URL}/canvas/file?name=${encodeURIComponent(name)}${kind ? `&kind=${kind}` : ''}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/octet-stream', ...CLIENT },
    body: file,
  })
  if (!res.ok) throw new Error(`could not add ${name} (${res.status})`)
}
