// Talks to `hi --voice-daemon` (hi/ipc/server.py). One POST per query,
// streamed back as AG-UI SSE and parsed by hand (EventSource can't POST).

export const BASE_URL = 'http://127.0.0.1:8765'

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
      headers: { 'Content-Type': 'application/json' },
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
    return (await fetch(`${BASE_URL}${path}`, { method: 'DELETE' })).ok
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

export const fileAttachment = (id: string) => postJson<{ queued: string }>(`/context/${id}/file`)

export type Config = Record<string, string | boolean | string[]>
export const fetchConfig = (mode?: string) => getJson<Config>(`/config${mode ? `?mode=${mode}` : ''}`)
export const saveConfig = (fields: Record<string, string>) => postJson<{ updated: string[]; note: string }>('/config', fields)
// Like saveConfig, but says why a save was refused (for example a hosted vision model with screenshot watching).
export async function saveConfigChecked(fields: Record<string, string>): Promise<{ ok: boolean; message: string }> {
  try {
    const res = await fetch(`${BASE_URL}/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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

export async function* streamQuery(text: string, persona: string | null, signal: AbortSignal, attachments: string[] = []): AsyncGenerator<AguiEvent> {
  const res = await fetch(`${BASE_URL}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, persona: persona ?? undefined, attachments: attachments.length ? attachments : undefined }),
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
