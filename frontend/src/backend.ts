// Talks to hi/ipc/server.py (`hi --voice-daemon`) — the same backend
// voice_companion/Sources/HiVoice/BackendClient.swift talks to, just
// from a browser instead of URLSession. One POST per query, streamed
// as AG-UI's own SSE framing and parsed by hand (fetch's ReadableStream,
// not EventSource — EventSource can't send a POST body, and /query
// needs one).

import type { AguiEvent, BriefingInfo, PendingActionInfo } from './types'

export const BASE_URL = 'http://127.0.0.1:8765'

async function getJson<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${BASE_URL}${path}`)
    if (!res.ok) return null
    return (await res.json()) as T
  } catch {
    return null
  }
}

/**
 * True if hi --voice-daemon is up and answering at all — mirrors
 * BackendClient.swift's own ping(): any real HTTP response (even the
 * 400 this empty-text POST itself gets back) means the process is
 * alive; only a network-level failure (fetch throwing) means it isn't.
 * Used for the header's connection-status dot, polled every 5s, same
 * interval as BackendHealthMonitor.swift.
 */
export async function ping(): Promise<boolean> {
  try {
    await fetch(`${BASE_URL}/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: '' }),
    })
    return true
  } catch {
    return false
  }
}

export async function fetchBriefing(): Promise<BriefingInfo | null> {
  return getJson<BriefingInfo>('/briefing')
}

export async function fetchPendingActions(): Promise<PendingActionInfo[]> {
  return (await getJson<PendingActionInfo[]>('/pending')) ?? []
}

export async function resolvePendingAction(id: string, approve: boolean): Promise<boolean> {
  try {
    const res = await fetch(`${BASE_URL}/pending/${id}/${approve ? 'approve' : 'deny'}`, { method: 'POST' })
    return res.status === 204
  } catch {
    return false
  }
}

export async function fetchConversationDates(): Promise<string[]> {
  return (await getJson<string[]>('/conversations')) ?? []
}

export async function fetchConversation(date: string): Promise<string | null> {
  const obj = await getJson<{ date: string; content: string }>(`/conversations/${date}`)
  return obj?.content ?? null
}

export async function fetchConfig(): Promise<Record<string, string>> {
  return (await getJson<Record<string, string>>('/config')) ?? {}
}

export async function updateConfig(fields: Record<string, string>): Promise<string | null> {
  try {
    const res = await fetch(`${BASE_URL}/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(fields),
    })
    if (!res.ok) return null
    const obj = (await res.json()) as { note?: string }
    return obj.note ?? null
  } catch {
    return null
  }
}

/**
 * Streams one query's AG-UI events. An async generator, not a callback
 * — callers just `for await (const event of streamQuery(...))`, same
 * shape as consuming any other async iterable, and cancellation is
 * "stop awaiting/break out of the loop" rather than a bespoke cancel
 * method (the underlying fetch is aborted via `signal` if the caller
 * passes one).
 */
export async function* streamQuery(
  text: string,
  persona: string | null,
  signal?: AbortSignal,
): AsyncGenerator<AguiEvent> {
  const res = await fetch(`${BASE_URL}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, persona: persona ?? undefined }),
    signal,
  })
  if (!res.ok || !res.body) {
    throw new Error(`Backend returned ${res.status} — is \`hi --voice-daemon\` running?`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // AG-UI's SSE framing: "data: <json>\n\n" — one event per non-blank
    // "data: " line, buffering any trailing partial line across chunks
    // (a chunk boundary can land mid-line).
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try {
        yield JSON.parse(line.slice(6)) as AguiEvent
      } catch {
        // A malformed line is dropped, not fatal to the rest of the
        // stream — matches BackendClient.swift's own decodeError
        // posture (parsed-but-unrecognized events are just skipped).
      }
    }
  }
}
