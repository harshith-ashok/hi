// Talks to hi/ipc/server.py (`hi --voice-daemon`) — the same backend
// voice_companion/Sources/HiVoice/BackendClient.swift talks to, just
// from a browser instead of URLSession. One POST per query, streamed
// as AG-UI's own SSE framing and parsed by hand (fetch's ReadableStream,
// not EventSource — EventSource can't send a POST body, and /query
// needs one).

import type { AgentRunInfo, AguiEvent, BackgroundTaskInfo, BriefingInfo, McpServerInfo, PendingActionInfo, TodayStats, VaultStats, Vitals } from './types'

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

// --- Home dashboard (hi/dashboard.py) ---

export async function fetchVitals(): Promise<Vitals | null> {
  return getJson<Vitals>('/vitals')
}

export async function fetchVaultStats(): Promise<VaultStats | null> {
  return getJson<VaultStats>('/vault-stats')
}

export async function fetchTodayStats(): Promise<TodayStats | null> {
  return getJson<TodayStats>('/today')
}

export async function fetchLastProject(): Promise<string | null> {
  const obj = await getJson<{ name: string | null }>('/last-project')
  return obj?.name ?? null
}

export async function fetchTrace(): Promise<string | null> {
  const obj = await getJson<{ content: string }>('/trace')
  return obj?.content ?? null
}

// --- On-demand agents (hi/agents_ondemand.py) ---

export async function fetchAgentRuns(): Promise<AgentRunInfo[]> {
  return (await getJson<AgentRunInfo[]>('/agents')) ?? []
}

export async function fetchAgentPresets(): Promise<Record<string, string>> {
  return (await getJson<Record<string, string>>('/agents/presets')) ?? {}
}

export async function fetchAgentRun(id: string): Promise<AgentRunInfo | null> {
  return getJson<AgentRunInfo>(`/agents/${id}`)
}

// --- MCP server management, surfaced in the Agents view per explicit
// request: "update the agents view to house this mcp part. I want to
// create agents that can communicate with the mcp I assign." ---

/** Full catalog + credential status (playwright/github/obsidian/n8n) —
 * mirrors GET /config's shape for the write-only MCP fields that
 * endpoint deliberately excludes (never echo a secret back via a GET). */
export async function fetchMcpServers(): Promise<McpServerInfo[]> {
  return (await getJson<McpServerInfo[]>('/mcp/servers')) ?? []
}

/** Only servers actually connected right now, with real tool counts —
 * the real choices for "assign an MCP server to this agent" (a server
 * that's merely credentialed but unreachable isn't a usable choice). */
export async function fetchAgentMcpServers(): Promise<Record<string, number>> {
  return (await getJson<Record<string, number>>('/agents/mcp-servers')) ?? {}
}

/** Single-credential servers (github/obsidian). Returns whether it saved. */
export async function configureMcpServer(name: string, credential: string): Promise<boolean> {
  try {
    const res = await fetch(`${BASE_URL}/mcp/configure`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, credential }),
    })
    return res.ok
  } catch {
    return false
  }
}

/** n8n's own two-value config (its instance URL + a bearer token). */
export async function configureN8nServer(url: string, token: string): Promise<boolean> {
  try {
    const res = await fetch(`${BASE_URL}/mcp/configure/n8n`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, token }),
    })
    return res.ok
  } catch {
    return false
  }
}

/** Starts a new on-demand agent — either a free-form `prompt` (may come
 * back needing clarification) or a `preset` id (already well-specified,
 * skips straight to running). `mcpServer`, if given, must be one of
 * fetchAgentMcpServers()'s keys — grants that server's tools to the
 * spawned agent for this task. */
export async function createAgentRun(opts: { prompt?: string; preset?: string; mcpServer?: string }): Promise<AgentRunInfo | null> {
  try {
    const res = await fetch(`${BASE_URL}/agents`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: opts.prompt, preset: opts.preset, mcp_server: opts.mcpServer }),
    })
    if (!res.ok) return null
    return (await res.json()) as AgentRunInfo
  } catch {
    return null
  }
}

export async function answerAgentQuestions(id: string, answers: string[]): Promise<AgentRunInfo | null> {
  try {
    const res = await fetch(`${BASE_URL}/agents/${id}/answer`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answers }),
    })
    if (!res.ok) return null
    return (await res.json()) as AgentRunInfo
  } catch {
    return null
  }
}

// --- Background tasks (hi/agents/term/background_tasks.py) — replaces
// the old tmux-pane redirect for a long-running command entirely. ---

export async function fetchBackgroundTasks(): Promise<BackgroundTaskInfo[]> {
  return (await getJson<BackgroundTaskInfo[]>('/background')) ?? []
}

export async function fetchBackgroundTask(id: string): Promise<BackgroundTaskInfo | null> {
  return getJson<BackgroundTaskInfo>(`/background/${id}`)
}

export async function stopBackgroundTask(id: string): Promise<boolean> {
  try {
    const res = await fetch(`${BASE_URL}/background/${id}/stop`, { method: 'POST' })
    if (!res.ok) return false
    const obj = (await res.json()) as { stopped: boolean }
    return obj.stopped
  } catch {
    return false
  }
}

/** Quick capture — bypasses the LLM entirely, straight into the same
 * untriaged inbox the global macOS hotkey already writes to. */
export async function postCapture(text: string): Promise<boolean> {
  try {
    const res = await fetch(`${BASE_URL}/capture`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    })
    return res.ok
  } catch {
    return false
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
