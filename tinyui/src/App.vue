<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { fetchConfig, fetchPending, getJson, ping, resolvePending, type Pending } from './backend'
import { useChat } from './chat'
import History from './History.vue'
import Markdown from './Markdown.vue'
import Orb from './Orb.vue'
import Settings from './Settings.vue'
import Status from './Status.vue'
import Tasks from './Tasks.vue'
import { ramble, record, speak, stopSpeaking, transcribe, type Recording } from './voice'

const PERSONAS = ['auto', 'term', 'butler', 'docs', 'web']
const VIEWS = ['chat', 'history', 'tasks', 'status', 'settings'] as const

const { entries, busy, add, ask, cancel, clear } = useChat((text) => void reply(text))
const mic = ref<'idle' | 'listening' | 'transcribing' | 'structuring'>('idle')
const rambler = ref(true) // structure spoken transcripts before sending
const voiceMode = ref(false) // full-screen, voice only
const caption = ref('')
const talk = ref(false) // conversation mode: speak replies, then listen again
let recording: Recording | null = null
const input = ref('')
const persona = ref('auto')
const online = ref(false)
const host = ref('')
const model = ref('')
const view = ref<(typeof VIEWS)[number]>('chat')
const pending = ref<Pending[]>([])
const logEl = ref<HTMLElement>()
const inputEl = ref<HTMLInputElement>()
const expanded = ref(new Set<number>())
const sent: string[] = []
let sentPos = 0
let suggested: string | null = null
const timers: number[] = []

const note = (text: string) => add('note', text)
const speaking = ref(false)
const acting = () => entries.value.some((e) => e.kind === 'tool' && e.result === undefined)
const state = () =>
  !online.value ? 'offline'
  : mic.value !== 'idle' ? mic.value
  : speaking.value ? 'speaking'
  : busy.value ? (acting() ? 'acting' : 'thinking')
  : 'ready'

async function refreshStatus() {
  online.value = await ping()
  if (!online.value) return
  const config = await fetchConfig()
  const mode = String(config?.AI_MODE ?? '')
  host.value = mode === 'openrouter' ? mode : `${mode} · ${config?.[mode === 'tailscale' ? 'TAILSCALE_OLLAMA_URL' : 'OLLAMA_HOST']}`
  model.value = String(config?.SONNET_MODEL ?? '')
}

async function briefing() {
  const b = await getJson<{ context: string; suggestion: string; action: string } | null>('/briefing')
  if (!b) return
  suggested = b.action
  note(b.suggestion ? `${b.context}\n\n${b.suggestion}` : b.context)
}

function submit(override?: string) {
  const text = (override ?? input.value).trim()
  input.value = ''
  if (!text) return
  view.value = 'chat'
  sent.push(text)
  sentPos = sent.length
  if (busy.value) return note('still replying — esc to cancel')
  const message = suggested && /^(y|yes|yeah|ok|okay|sure)$/i.test(text) ? suggested : text
  suggested = null
  void ask(message, persona.value === 'auto' ? null : persona.value)
}

// send=false: dictation — the transcript lands in the input box to edit; send=true: hands-free.
async function listen(send = true) {
  if (mic.value !== 'idle') return recording?.stop()
  try {
    recording = await record()
  } catch {
    return void add('error', 'microphone unavailable')
  }
  mic.value = 'listening'
  const wav = await recording.result
  recording = null
  if (!wav) {
    mic.value = 'idle'
    talk.value = false
    return
  }
  mic.value = 'transcribing'
  try {
    const heard = await transcribe(wav)
    mic.value = 'structuring'
    const text = rambler.value ? await ramble(heard) : heard
    if (text !== heard) note(`heard: ${heard}`)
    caption.value = ''
    if (send) submit(text) // keeps the line breaks of structured text
    else {
      input.value = text
      inputEl.value?.focus()
    }
  } catch (err) {
    add('error', (err as Error).message)
    talk.value = false
  }
  mic.value = 'idle'
}

// Speak the short summary; the full answer stays on screen.
async function reply(text: string) {
  if (!talk.value) return
  caption.value = text
  speaking.value = true
  try {
    await speak(text)
  } catch (err) {
    return void add('error', (err as Error).message)
  } finally {
    speaking.value = false
  }
  if (talk.value) void listen()
}

function toggleVoiceMode() {
  voiceMode.value = !voiceMode.value
  caption.value = ''
  if (voiceMode.value !== talk.value) toggleTalk()
}

function toggleTalk() {
  talk.value = !talk.value
  if (talk.value) void listen()
  else {
    recording?.stop()
    stopSpeaking()
  }
}

function recall(step: number) {
  if (!sent.length) return
  sentPos = Math.max(0, Math.min(sent.length, sentPos + step))
  input.value = sent[sentPos] ?? ''
}

async function answerPending(approve: boolean) {
  const [first] = pending.value
  if (!first) return
  pending.value = pending.value.slice(1)
  await resolvePending(first.id, approve)
  note(`${approve ? 'approved' : 'denied'}: ${first.description}`)
}

function onWindowKey(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    if (busy.value) cancel()
    if (voiceMode.value) voiceMode.value = false
    talk.value = false
    recording?.stop()
    stopSpeaking()
  } else if (pending.value.length && !input.value && (e.key === 'y' || e.key === 'n')) {
    e.preventDefault()
    void answerPending(e.key === 'y')
  }
}

// Destructive-action confirms arrive on the backend's pending queue while a turn is streaming.
watch(busy, (isBusy) => {
  if (isBusy) {
    const poll = window.setInterval(async () => {
      pending.value = await fetchPending()
      if (!busy.value) clearInterval(poll)
    }, 800)
  } else pending.value = []
})

// Stick to the bottom while output streams.
watch(
  () => entries.value.map((e) => e.text.length + (e.result?.length ?? 0)).join(),
  () => nextTick(() => logEl.value?.scrollTo({ top: logEl.value.scrollHeight })),
)

onMounted(() => {
  window.addEventListener('keydown', onWindowKey)
  timers.push(window.setInterval(refreshStatus, 5000))
  void refreshStatus()
  void briefing()
  inputEl.value?.focus()
})
onUnmounted(() => {
  window.removeEventListener('keydown', onWindowKey)
  timers.forEach(clearInterval)
})

const short = (s: string, n = 240) => {
  const flat = s.replace(/\s+/g, ' ').trim()
  return flat.length > n ? `${flat.slice(0, n)}…` : flat
}
</script>

<template>
  <div class="app">
    <aside>
      <div class="title">hi <span class="dim">{{ state() }}</span></div>
      <button @click="clear(); view = 'chat'">+ new chat</button>

      <div class="group dim">persona</div>
      <button v-for="p in PERSONAS" :key="p" :class="{ on: p === persona }" @click="persona = p">{{ p === persona ? '▸' : ' ' }} {{ p }}</button>

      <div class="group dim">view</div>
      <button v-for="v in VIEWS" :key="v" :class="{ on: v === view }" @click="view = v">{{ v === view ? '▸' : ' ' }} {{ v }}</button>

      <div class="foot dim">{{ host }}<br />{{ model }}</div>
    </aside>

    <main>
      <div v-show="view === 'chat'" class="chat">
        <div ref="logEl" class="log">
          <template v-for="e in entries" :key="e.id">
            <div v-if="e.kind === 'user'" class="user"><span class="accent">&gt; </span>{{ e.text }}</div>
            <div v-else-if="e.kind === 'tool'" class="tool" @click="expanded.has(e.id) ? expanded.delete(e.id) : expanded.add(e.id)">
              <span class="accent">▸ {{ e.name }}</span> <span class="dim">{{ e.text }}</span>
              <div v-if="e.result !== undefined" class="dim indent">{{ expanded.has(e.id) ? e.result : short(e.result) }}</div>
            </div>
            <Markdown v-else-if="e.kind === 'text'" :source="e.text" class="text" />
            <div v-else :class="e.kind">{{ e.text }}</div>
          </template>
        </div>

        <div v-if="pending.length" class="confirm">
          <span class="err">confirm</span> {{ pending[0].description }}
          <button @click="answerPending(true)">[y] yes</button><button @click="answerPending(false)">[n] no</button>
        </div>

        <div class="prompt">
          <span class="accent">&gt;</span>
          <input
            ref="inputEl"
            v-model="input"
            placeholder="message"
            spellcheck="false"
            autocomplete="off"
            @keydown.enter="submit()"
            @keydown.up.prevent="recall(-1)"
            @keydown.down.prevent="recall(1)"
          />
          <span v-if="mic !== 'idle'" class="dim">{{ mic }}…</span>
          <button title="voice only: full-screen orb, hands-free" @click="toggleVoiceMode">[voice]</button>
          <button :class="{ accent: rambler }" title="rambler: clean up and structure what you say before sending" @click="rambler = !rambler">[{{ rambler ? 'ramble on' : 'ramble' }}]</button>
          <button :class="{ accent: talk }" title="talk: speak replies and keep listening" @click="toggleTalk">[{{ talk ? 'talk on' : 'talk' }}]</button>
          <button title="dictate into the input box (no send, no speech)" :disabled="mic === 'transcribing' || mic === 'structuring'" @click="listen(false)">[mic]</button>
        </div>
      </div>

      <History v-if="view === 'history'" />
      <Tasks v-else-if="view === 'tasks'" />
      <Status v-else-if="view === 'status'" />
      <Settings v-else-if="view === 'settings'" />
    </main>

    <div v-if="voiceMode" class="voice" @click="toggleVoiceMode">
      <Orb :state="state()" />
      <div class="state">{{ state() }}</div>
      <div v-if="caption" class="caption dim">{{ caption }}</div>
      <div v-if="pending.length" class="confirm" @click.stop>
        <span class="err">confirm</span> {{ pending[0].description }}
        <button @click="answerPending(true)">[y] yes</button><button @click="answerPending(false)">[n] no</button>
      </div>
      <div class="dim hint">esc or click to leave</div>
    </div>
  </div>
</template>

<style scoped>
.voice { position: fixed; inset: 0; z-index: 10; background: var(--bg); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px; cursor: pointer; }
.voice .state { color: var(--accent); letter-spacing: 0.2em; text-transform: uppercase; }
.voice .caption { max-width: 60ch; text-align: center; min-height: 3em; }
.voice .hint { position: absolute; bottom: 16px; font-size: 12px; }
.app { height: 100%; display: flex; }
aside { width: 24ch; flex: none; padding: 12px 16px; display: flex; flex-direction: column; align-items: flex-start; border-right: 1px solid var(--dim); }
aside button { background: none; border: 0; padding: 0; cursor: pointer; text-align: left; white-space: pre; }
aside button:hover, aside button.on { color: var(--accent); }
.title { margin-bottom: 12px; }
.group { margin-top: 20px; }
.foot { margin-top: auto; font-size: 12px; word-break: break-all; }
main { flex: 1; min-width: 0; padding: 12px 24px; display: flex; flex-direction: column; max-width: 110ch; }
main > * { flex: 1; min-height: 0; }
.chat { display: flex; flex-direction: column; }
.log { flex: 1; overflow-y: auto; border: 1px solid var(--dim); border-radius: 6px; padding: 12px 16px; margin-bottom: 8px; scrollbar-width: thin; }
.log > div { white-space: pre-wrap; word-break: break-word; margin-bottom: 12px; }
.log > .md { white-space: normal; }
.note, .thinking, .dim { color: var(--dim); }
.thinking { font-style: italic; }
.error, .err { color: var(--err); }
.accent { color: var(--accent); }
.tool { cursor: pointer; }
.indent { padding-left: 2ch; }
.prompt { display: flex; gap: 1ch; border-top: 1px solid var(--dim); padding-top: 8px; }
.prompt input { flex: 1; background: none; border: 0; outline: none; }
.confirm { flex: none; border: 1px solid var(--err); padding: 8px 12px; margin-bottom: 8px; }
.confirm button { background: none; border: 0; cursor: pointer; margin-left: 2ch; color: var(--accent); }
</style>
