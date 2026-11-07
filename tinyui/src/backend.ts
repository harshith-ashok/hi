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

export type Config = Record<string, string | boolean | string[]>
export const fetchConfig = (mode?: string) => getJson<Config>(`/config${mode ? `?mode=${mode}` : ''}`)
export const saveConfig = (fields: Record<string, string>) => postJson<{ updated: string[]; note: string }>('/config', fields)
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

export async function* streamQuery(text: string, persona: string | null, signal: AbortSignal): AsyncGenerator<AguiEvent> {
  const res = await fetch(`${BASE_URL}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, persona: persona ?? undefined }),
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
