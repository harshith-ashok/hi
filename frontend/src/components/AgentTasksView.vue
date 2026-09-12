<!-- On-demand agents (hi/agents_ondemand.py, TODO.md Phase 27), per
     explicit request: give an agent a task from a prompt, have it ask
     clarifying questions before it commits to running, and be able to
     "one-click" a few preset agents from here too.

     Polled (GET /agents every 3s), not streamed — same "background
     thread + polling" shape PendingActionsMonitor.swift already
     established for this backend's other long-running work, not a
     second SSE surface for what's fundamentally the same kind of
     "check back on this later" state. -->
<script setup lang="ts">
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import {
  answerAgentQuestions,
  configureMcpServer,
  configureN8nServer,
  createAgentRun,
  fetchAgentMcpServers,
  fetchAgentPresets,
  fetchAgentRuns,
  fetchBackgroundTasks,
  fetchMcpServers,
  stopBackgroundTask,
} from '../backend'
import { renderMarkdown } from '../lib/markdown'
import type { AgentRunInfo, BackgroundTaskInfo, McpServerInfo } from '../types'

const presets = ref<Record<string, string>>({})
const runs = ref<AgentRunInfo[]>([])
const promptText = ref('')
const isSpawning = ref(false)
const expandedId = ref<string | null>(null)
// runId -> in-progress answers, one per question, while a run is in
// "clarifying" — separate from the run's own persisted `qa` so a draft
// doesn't get wiped by the next poll landing mid-typing.
const drafts = reactive<Record<string, string[]>>({})
const answering = ref<Set<string>>(new Set())

// --- MCP servers (hi/mcp_tools.py / hi/mcp_install.py), per explicit
// request: "update the agents view to house this mcp part. I want to
// create agents that can communicate with the mcp I assign." ---
const mcpServers = ref<McpServerInfo[]>([])
// server name -> live tool count, only for servers actually connected
// right now — the real, pickable choices for "assign to this agent"
// (a server that's merely credentialed but unreachable isn't usable).
const connectedMcpServers = ref<Record<string, number>>({})
const selectedMcpServer = ref<string>('') // '' = no MCP server assigned
const showMcpPanel = ref(false)
const credentialDrafts = reactive<Record<string, string>>({})
const n8nUrlDraft = ref('')
const n8nTokenDraft = ref('')
const configuring = ref<Set<string>>(new Set())
const mcpStatusMessage = ref<string | null>(null)

async function loadMcpServers() {
  const [catalog, connected] = await Promise.all([fetchMcpServers(), fetchAgentMcpServers()])
  mcpServers.value = catalog
  connectedMcpServers.value = connected
}

async function saveCredential(name: string) {
  const credential = (credentialDrafts[name] ?? '').trim()
  if (!credential || configuring.value.has(name)) return
  configuring.value.add(name)
  const ok = await configureMcpServer(name, credential)
  configuring.value.delete(name)
  mcpStatusMessage.value = ok ? `${name} configured.` : `Failed to configure ${name}.`
  if (ok) {
    credentialDrafts[name] = ''
    await loadMcpServers()
  }
}

async function saveN8n() {
  const url = n8nUrlDraft.value.trim()
  const token = n8nTokenDraft.value.trim()
  if (!url || !token || configuring.value.has('n8n')) return
  configuring.value.add('n8n')
  const ok = await configureN8nServer(url, token)
  configuring.value.delete('n8n')
  mcpStatusMessage.value = ok ? 'n8n configured.' : 'Failed to configure n8n.'
  if (ok) {
    n8nUrlDraft.value = ''
    n8nTokenDraft.value = ''
    await loadMcpServers()
  }
}

let timer: ReturnType<typeof setInterval> | undefined

async function refresh() {
  const fresh = await fetchAgentRuns()
  // Replace in place by id rather than reassigning the whole array —
  // a run the user has expanded/is answering shouldn't visually reset
  // every 3s just because a poll landed.
  const byId = new Map(fresh.map((r) => [r.id, r]))
  for (const run of runs.value) {
    const updated = byId.get(run.id)
    if (updated) Object.assign(run, updated)
  }
  for (const run of fresh) {
    if (!runs.value.some((r) => r.id === run.id)) runs.value.push(run)
  }
  runs.value.sort((a, b) => b.created_at - a.created_at)
}

// --- Background tasks (hi/agents/term/background_tasks.py) — a
// long-running command (a dev server, a watcher) run_shell_command
// started, no terminal pane involved at all. Per explicit request:
// "spawn terminal instances as separate task... instead of relying on
// the left pane." Same replace-in-place polling shape as agent runs
// above, so an expanded/being-watched task doesn't reset every 3s. ---
const backgroundTasks = ref<BackgroundTaskInfo[]>([])
const expandedTaskId = ref<string | null>(null)
const stoppingTask = ref<Set<string>>(new Set())

async function refreshBackgroundTasks() {
  const fresh = await fetchBackgroundTasks()
  const byId = new Map(fresh.map((t) => [t.id, t]))
  for (const task of backgroundTasks.value) {
    const updated = byId.get(task.id)
    if (updated) Object.assign(task, updated)
  }
  for (const task of fresh) {
    if (!backgroundTasks.value.some((t) => t.id === task.id)) backgroundTasks.value.push(task)
  }
  backgroundTasks.value.sort((a, b) => b.started_at - a.started_at)
}

function toggleTask(id: string) {
  expandedTaskId.value = expandedTaskId.value === id ? null : id
}

async function stopTask(id: string) {
  if (stoppingTask.value.has(id)) return
  stoppingTask.value.add(id)
  await stopBackgroundTask(id)
  stoppingTask.value.delete(id)
  await refreshBackgroundTasks()
}

onMounted(async () => {
  presets.value = await fetchAgentPresets()
  await Promise.all([refresh(), loadMcpServers(), refreshBackgroundTasks()])
  timer = setInterval(() => {
    refresh()
    refreshBackgroundTasks()
  }, 3000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})

function upsertRun(run: AgentRunInfo) {
  const idx = runs.value.findIndex((r) => r.id === run.id)
  if (idx === -1) runs.value.unshift(run)
  else runs.value[idx] = run
  expandedId.value = run.id
}

async function spawnPreset(id: string) {
  if (isSpawning.value) return
  isSpawning.value = true
  const run = await createAgentRun({ preset: id, mcpServer: selectedMcpServer.value || undefined })
  isSpawning.value = false
  if (run) upsertRun(run)
}

async function spawnCustom() {
  const prompt = promptText.value.trim()
  if (!prompt || isSpawning.value) return
  isSpawning.value = true
  const run = await createAgentRun({ prompt, mcpServer: selectedMcpServer.value || undefined })
  isSpawning.value = false
  if (run) {
    upsertRun(run)
    promptText.value = ''
  }
}

function draftFor(run: AgentRunInfo): string[] {
  if (!drafts[run.id] || drafts[run.id].length !== run.questions.length) {
    drafts[run.id] = run.questions.map(() => '')
  }
  return drafts[run.id]
}

async function submitAnswers(run: AgentRunInfo) {
  const answers = draftFor(run)
  if (answers.some((a) => !a.trim()) || answering.value.has(run.id)) return
  answering.value.add(run.id)
  const updated = await answerAgentQuestions(run.id, answers)
  answering.value.delete(run.id)
  if (updated) {
    upsertRun(updated)
    delete drafts[run.id]
  }
}

function statusLabel(run: AgentRunInfo): string {
  return {
    clarifying: 'needs input',
    ready: 'starting…',
    running: 'running…',
    done: 'done',
    error: 'failed',
  }[run.status]
}

function toggle(id: string) {
  expandedId.value = expandedId.value === id ? null : id
}

function relativeTime(epochSeconds: number): string {
  const diffMin = Math.round((Date.now() / 1000 - epochSeconds) / 60)
  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.round(diffMin / 60)
  return diffHr < 24 ? `${diffHr}h ago` : `${Math.round(diffHr / 24)}d ago`
}

// playwright needs no credential at all — nothing to configure, it's
// either available (npx on PATH) or not.
function needsCredentialForm(server: McpServerInfo): boolean {
  return !server.configured && server.name !== 'playwright'
}
</script>

<template>
  <div class="agents-view">
    <h1>Agents</h1>
    <p class="note">
      Give an agent a task in plain language — it'll ask clarifying questions before it commits to
      running, then work on it in the background. Presets below are already well-specified and run
      immediately, no clarification needed.
    </p>

    <div class="mcp-section">
      <button class="mcp-toggle" @click="showMcpPanel = !showMcpPanel">
        {{ showMcpPanel ? '▾' : '▸' }} MCP servers
        <span class="mcp-count">({{ Object.keys(connectedMcpServers).length }} connected)</span>
      </button>

      <div v-if="showMcpPanel" class="mcp-panel">
        <div v-for="server in mcpServers" :key="server.name" class="mcp-server">
          <div class="mcp-server-header">
            <div class="dot" :class="{ on: server.configured, off: !server.configured }"></div>
            <span class="mcp-name">{{ server.name }}</span>
            <span class="mcp-tool-count" v-if="connectedMcpServers[server.name] !== undefined">
              {{ connectedMcpServers[server.name] }} tools live
            </span>
            <span class="mcp-status">{{ server.configured ? 'configured' : 'not configured' }}</span>
          </div>
          <div class="mcp-desc">{{ server.description }}</div>

          <div v-if="needsCredentialForm(server) && server.name !== 'n8n'" class="mcp-form">
            <input
              v-model="credentialDrafts[server.name]"
              type="password"
              placeholder="credential / API key"
              :disabled="configuring.has(server.name)"
            />
            <button
              :disabled="configuring.has(server.name) || !credentialDrafts[server.name]?.trim()"
              @click="saveCredential(server.name)"
            >
              {{ configuring.has(server.name) ? 'Saving…' : 'Save' }}
            </button>
          </div>

          <div v-else-if="needsCredentialForm(server) && server.name === 'n8n'" class="mcp-form mcp-form-n8n">
            <input v-model="n8nUrlDraft" type="text" placeholder="n8n MCP URL (http://host:5678/mcp-server/http)" :disabled="configuring.has('n8n')" />
            <input v-model="n8nTokenDraft" type="password" placeholder="bearer token" :disabled="configuring.has('n8n')" />
            <button :disabled="configuring.has('n8n') || !n8nUrlDraft.trim() || !n8nTokenDraft.trim()" @click="saveN8n">
              {{ configuring.has('n8n') ? 'Saving…' : 'Save' }}
            </button>
          </div>
        </div>
        <div v-if="mcpStatusMessage" class="mcp-status-message">{{ mcpStatusMessage }}</div>
      </div>

      <div class="mcp-assign">
        <label>Assign an MCP server to the next agent (optional)</label>
        <select v-model="selectedMcpServer">
          <option value="">None</option>
          <option v-for="(count, name) in connectedMcpServers" :key="name" :value="name">
            {{ name }} ({{ count }} tools)
          </option>
        </select>
      </div>
    </div>

    <div class="presets">
      <button
        v-for="(text, id) in presets"
        :key="id"
        class="preset-btn"
        :disabled="isSpawning"
        :title="text"
        @click="spawnPreset(id)"
      >
        {{ id.replace(/-/g, ' ') }}
      </button>
    </div>

    <div class="composer">
      <textarea
        v-model="promptText"
        rows="2"
        placeholder="Describe a task for a new agent…"
        :disabled="isSpawning"
        @keydown.enter.meta.prevent="spawnCustom"
      ></textarea>
      <button class="spawn-btn" :disabled="isSpawning || !promptText.trim()" @click="spawnCustom">
        {{ isSpawning ? 'Spawning…' : 'Spawn agent' }}
      </button>
    </div>

    <div v-if="runs.length === 0" class="status">No agents yet — try a preset above, or describe a task.</div>

    <div v-for="run in runs" :key="run.id" class="run-card" :class="`s-${run.status}`">
      <div class="run-header" @click="toggle(run.id)">
        <div class="dot" :class="{ busy: run.status === 'running' || run.status === 'ready', error: run.status === 'error' }"></div>
        <div class="run-prompt">{{ run.prompt }}</div>
        <div class="run-meta">
          <span v-if="run.mcp_server" class="run-mcp-badge">{{ run.mcp_server }}</span>
          <span class="run-status">{{ statusLabel(run) }}</span>
          <span class="run-time">{{ relativeTime(run.created_at) }}</span>
        </div>
      </div>

      <div v-if="expandedId === run.id" class="run-body">
        <div v-if="run.status === 'clarifying'" class="clarify">
          <div v-for="(q, i) in run.questions" :key="i" class="question">
            <label>{{ q }}</label>
            <input v-model="draftFor(run)[i]" type="text" :disabled="answering.has(run.id)" />
          </div>
          <button
            class="answer-btn"
            :disabled="answering.has(run.id) || draftFor(run).some((a) => !a.trim())"
            @click="submitAnswers(run)"
          >
            {{ answering.has(run.id) ? 'Submitting…' : 'Submit answers' }}
          </button>
        </div>

        <div v-else-if="run.status === 'running' || run.status === 'ready'" class="status">
          {{ run.persona ? `${run.persona} is working on this…` : 'starting…' }}
        </div>

        <div v-else-if="run.status === 'done'" class="result markdown" v-html="renderMarkdown(run.result)"></div>

        <div v-else-if="run.status === 'error'" class="status error">{{ run.error }}</div>

        <div v-if="run.qa.length" class="qa-log">
          <div class="qa-title">clarifications</div>
          <div v-for="(pair, i) in run.qa" :key="i" class="qa-pair">
            <div class="qa-q">{{ pair.question }}</div>
            <div class="qa-a">{{ pair.answer }}</div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="backgroundTasks.length" class="background-section">
      <h2>Background tasks</h2>
      <p class="note">
        A dev server or watcher started via a shell command — runs as a plain background process,
        no terminal pane involved. Live-tailed here instead of something you'd have to keep a pane
        open to watch.
      </p>
      <div v-for="task in backgroundTasks" :key="task.id" class="run-card" :class="task.status === 'running' ? 's-running' : 's-done'">
        <div class="run-header" @click="toggleTask(task.id)">
          <div class="dot" :class="{ busy: task.status === 'running' }"></div>
          <div class="run-prompt">{{ task.command }}</div>
          <div class="run-meta">
            <span class="run-status">
              {{ task.status === 'running' ? 'running' : `exited (${task.exit_code})` }}
            </span>
            <span class="run-time">{{ relativeTime(task.started_at) }}</span>
          </div>
          <button
            v-if="task.status === 'running'"
            class="stop-btn"
            :disabled="stoppingTask.has(task.id)"
            @click.stop="stopTask(task.id)"
          >
            {{ stoppingTask.has(task.id) ? 'stopping…' : 'stop' }}
          </button>
        </div>
        <div v-if="expandedTaskId === task.id" class="run-body">
          <pre class="task-output">{{ task.output_tail || '(no output yet)' }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.agents-view {
  max-width: 640px;
  margin: 0 auto;
  padding: 28px 20px 60px;
}
h1 {
  font-family: var(--mono);
  font-size: 16px;
  font-weight: 500;
  color: var(--text);
  margin: 0 0 10px 0;
}
.note {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-faint);
  margin: 0 0 20px 0;
  line-height: 1.5;
}
.presets {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}
.preset-btn {
  background: var(--bg-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  color: var(--teal);
  font-family: var(--mono);
  font-size: 11.5px;
  padding: 8px 12px;
  cursor: pointer;
  text-transform: capitalize;
}
.preset-btn:disabled {
  opacity: 0.5;
  cursor: default;
}
.composer {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 24px;
}
.composer textarea {
  width: 100%;
  resize: vertical;
  background: var(--bg-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  padding: 10px;
  font-family: var(--mono);
  font-size: 12.5px;
  color: var(--text);
  outline: none;
  box-sizing: border-box;
}
.composer textarea:focus {
  border-color: var(--teal-dim);
}
.spawn-btn {
  align-self: flex-end;
  background: none;
  border: 1px solid var(--teal-dim);
  border-radius: 6px;
  color: var(--teal);
  font-family: var(--mono);
  font-size: 12px;
  font-weight: 500;
  padding: 7px 14px;
  cursor: pointer;
}
.spawn-btn:disabled {
  opacity: 0.5;
  cursor: default;
}
.status {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--text-faint);
}
.status.error {
  color: var(--rust);
}
.run-card {
  background: var(--bg-card);
  border: 1px solid var(--hairline);
  border-left: 2px solid var(--hairline);
  border-radius: 10px;
  margin-bottom: 10px;
  overflow: hidden;
}
.run-card.s-running,
.run-card.s-ready {
  border-left-color: var(--amber);
}
.run-card.s-done {
  border-left-color: var(--teal-dim);
}
.run-card.s-error {
  border-left-color: var(--rust);
}
.run-card.s-clarifying {
  border-left-color: var(--purple);
}
.run-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  cursor: pointer;
}
.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--teal-dim);
}
.dot.busy {
  background: var(--amber);
  animation: pulse 1.4s ease-in-out infinite;
}
.dot.error {
  background: var(--rust);
}
.dot.on {
  background: var(--teal);
}
.dot.off {
  background: var(--text-faint);
}
@keyframes pulse {
  50% {
    opacity: 0.35;
  }
}
.run-prompt {
  flex: 1;
  font-size: 12.5px;
  color: var(--text-dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.run-meta {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}
.run-status {
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--text-faint);
}
.run-time {
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--text-faint);
}
.run-body {
  padding: 0 14px 14px;
  border-top: 1px solid var(--hairline);
  padding-top: 12px;
}
.clarify {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.question label {
  display: block;
  font-family: var(--mono);
  font-size: 11.5px;
  color: var(--text-dim);
  margin-bottom: 4px;
}
.question input {
  width: 100%;
  background: var(--bg-panel);
  border: 1px solid var(--hairline);
  border-radius: 4px;
  padding: 7px 8px;
  font-family: var(--mono);
  font-size: 12px;
  color: var(--text);
  outline: none;
  box-sizing: border-box;
}
.question input:focus {
  border-color: var(--teal-dim);
}
.answer-btn {
  align-self: flex-start;
  background: none;
  border: 1px solid var(--teal-dim);
  border-radius: 6px;
  color: var(--teal);
  font-family: var(--mono);
  font-size: 11.5px;
  padding: 6px 12px;
  cursor: pointer;
}
.answer-btn:disabled {
  opacity: 0.5;
  cursor: default;
}
.qa-log {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--hairline);
}
.qa-title {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--text-faint);
  margin-bottom: 6px;
  letter-spacing: 0.04em;
}
.qa-pair {
  margin-bottom: 6px;
  font-size: 11.5px;
}
.qa-q {
  color: var(--text-faint);
}
.qa-a {
  color: var(--text-dim);
  padding-left: 8px;
}
/* .result's typography comes from the global .markdown class (lib/markdown.ts) */

.mcp-section {
  margin-bottom: 20px;
}
.mcp-toggle {
  background: none;
  border: none;
  color: var(--text-dim);
  font-family: var(--mono);
  font-size: 12px;
  padding: 0;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
}
.mcp-count {
  color: var(--text-faint);
  font-size: 10.5px;
}
.mcp-panel {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.mcp-server {
  background: var(--bg-card);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  padding: 10px 12px;
}
.mcp-server-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.mcp-name {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--text);
  font-weight: 500;
}
.mcp-tool-count {
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--teal);
}
.mcp-status {
  margin-left: auto;
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--text-faint);
}
.mcp-desc {
  margin-top: 4px;
  font-size: 11.5px;
  color: var(--text-faint);
  line-height: 1.4;
}
.mcp-form {
  margin-top: 8px;
  display: flex;
  gap: 6px;
}
.mcp-form-n8n {
  flex-direction: column;
}
.mcp-form input {
  flex: 1;
  background: var(--bg-panel);
  border: 1px solid var(--hairline);
  border-radius: 4px;
  padding: 6px 8px;
  font-family: var(--mono);
  font-size: 11.5px;
  color: var(--text);
  outline: none;
  box-sizing: border-box;
}
.mcp-form input:focus {
  border-color: var(--teal-dim);
}
.mcp-form button {
  background: none;
  border: 1px solid var(--teal-dim);
  border-radius: 4px;
  color: var(--teal);
  font-family: var(--mono);
  font-size: 11px;
  padding: 6px 10px;
  cursor: pointer;
  white-space: nowrap;
}
.mcp-form button:disabled {
  opacity: 0.5;
  cursor: default;
}
.mcp-status-message {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-faint);
}
.mcp-assign {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.mcp-assign label {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-faint);
}
.mcp-assign select {
  background: var(--bg-card);
  border: 1px solid var(--hairline);
  border-radius: 6px;
  padding: 5px 8px;
  font-family: var(--mono);
  font-size: 11.5px;
  color: var(--text);
  outline: none;
}
.run-mcp-badge {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--purple);
  border: 1px solid var(--purple-dim);
  border-radius: 4px;
  padding: 1px 6px;
}
.background-section {
  margin-top: 28px;
  padding-top: 20px;
  border-top: 1px solid var(--hairline);
}
.background-section h2 {
  font-family: var(--mono);
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  margin: 0 0 6px 0;
}
.stop-btn {
  background: none;
  border: 1px solid var(--rust);
  border-radius: 4px;
  color: var(--rust);
  font-family: var(--mono);
  font-size: 10.5px;
  padding: 3px 8px;
  cursor: pointer;
  flex-shrink: 0;
}
.stop-btn:disabled {
  opacity: 0.5;
  cursor: default;
}
.task-output {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-dim);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 320px;
  overflow-y: auto;
  margin: 0;
}
</style>
