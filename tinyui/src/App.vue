<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { BASE_URL, fetchConfig, fetchPending, getJson, ping, resolvePending, type Pending } from './backend'
import { useChat } from './chat'
import History from './History.vue'
import Markdown from './Markdown.vue'
import Memory from './Memory.vue'
import Orb from './Orb.vue'
import Settings from './Settings.vue'
import Status from './Status.vue'
import Tasks from './Tasks.vue'
import { afterWakePhrase, getWakePhrase, ramble, record, speak, stopSpeaking, transcribe, unlockAudio, type Recording } from './voice'

const PERSONAS: [string, string][] = [
  ['auto', 'picks for you'],
  ['term', 'shell · files · code · GitHub'],
  ['butler', 'Mac control · to-dos'],
  ['docs', 'search your notes'],
  ['web', 'Wikipedia · images · URLs'],
]
const VIEWS = ['chat', 'history', 'tasks', 'memory', 'status', 'settings'] as const
const TRIES = ['get me a picture of srk', 'plot a linear regression', 'turn off bluetooth', 'make logic_play private', 'what did I note about binary search trees', 'delete the build folder']
const FLOW = ['send', 'route', 'tools', 'reply', 'speak']

// Light, dark, or follow the OS. Remembered across reloads.
const theme = ref(localStorage.getItem('theme') ?? 'auto')
watch(
  theme,
  (value) => {
    if (value === 'auto') document.documentElement.removeAttribute('data-theme')
    else document.documentElement.setAttribute('data-theme', value)
    localStorage.setItem('theme', value)
  },
  { immediate: true },
)
const cycleTheme = () => (theme.value = ({ auto: 'light', light: 'dark', dark: 'auto' } as Record<string, string>)[theme.value])
const activeTasks = ref(0)
const nextPersona = () => (persona.value = PERSONAS[(PERSONAS.findIndex((p) => p[0] === persona.value) + 1) % PERSONAS.length][0])

const { entries, busy, add, ask, cancel, clear } = useChat((text) => void reply(text))
const mic = ref<'idle' | 'listening' | 'transcribing' | 'structuring'>('idle')
const rambler = ref(true) // structure spoken transcripts before sending
const voiceMode = ref(false) // full-screen, voice only
const caption = ref('')
const talk = ref(false) // conversation mode: speak replies, then listen again
// Independent of the mic: speak replies even to typed requests. Remembered across reloads.
const speakReplies = ref(localStorage.getItem('speakReplies') === '1')
watch(speakReplies, (on) => {
  localStorage.setItem('speakReplies', on ? '1' : '0')
  if (on) unlockAudio()
  else if (!talk.value) stopSpeaking()
})
const wake = ref(false) // always listening for the wake phrase; hands-free input
let recording: Recording | null = null
let ttsWarned = false
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
  activeTasks.value = ((await getJson<{ status: string }[]>('/background')) ?? []).filter((t) => t.status === 'running').length
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
  unlockAudio()
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

// Wake word: each utterance is transcribed locally (whisper.cpp) and acted on only if it
// starts with the wake phrase. "hey hi, what's due" sends the rest; a bare "hey hi" listens next.
async function wakeLoop() {
  while (wake.value) {
    if (mic.value !== 'idle' || speaking.value || busy.value) {
      await new Promise((r) => setTimeout(r, 300))
      continue
    }
    let wav: Blob | null
    try {
      recording = await record()
      wav = await recording.result
      recording = null
    } catch {
      add('error', 'microphone unavailable')
      break
    }
    if (!wav || !wake.value || speaking.value) continue // silence, switched off, or our own voice
    try {
      const rest = afterWakePhrase(await transcribe(wav))
      if (rest === null) continue
      if (rest) submit(rest)
      else await listen()
    } catch (err) {
      add('error', (err as Error).message)
      break
    }
  }
  wake.value = false
}

function toggleWake() {
  unlockAudio()
  wake.value = !wake.value
  if (wake.value) void wakeLoop()
  else recording?.stop()
}

// Speak the short summary; the full answer stays on screen.
async function reply(text: string) {
  if (!talk.value && !speakReplies.value) return
  caption.value = text
  speaking.value = true
  if (wake.value && mic.value === 'idle') recording?.stop() // don't transcribe our own voice
  try {
    await speak(text, (why) => {
      if (!ttsWarned) note(`phonon tts failed (${why}) — using the browser voice`)
      ttsWarned = true
    })
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
  unlockAudio()
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
    wake.value = false
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
  window.addEventListener('pointerdown', unlockAudio, { once: true }) // lets later spoken replies play
  window.addEventListener('keydown', unlockAudio, { once: true })
  timers.push(window.setInterval(refreshStatus, 5000))
  void refreshStatus()
  void briefing()
  inputEl.value?.focus()
})
onUnmounted(() => {
  window.removeEventListener('keydown', onWindowKey)
  timers.forEach(clearInterval)
})

// Charts made by run_python come back as /plots/<name>.png paths in the tool result.
const plots = (result?: string) => [...new Set(result?.match(/\/plots\/[\w-]+\.(?:png|jpg|webp)/g) ?? [])].map((p) => BASE_URL + p)

// Files made by run_python (PDF, CSV, ...) come back as /files/<run>/<name> paths.
const files = (result?: string) =>
  [...new Set(result?.match(/\/files\/[\w.-]+\/[\w.-]+/g) ?? [])].map((p) => ({ href: BASE_URL + p, name: p.split('/').pop() }))

const short = (s: string, n = 240) => {
  const flat = s.replace(/\s+/g, ' ').trim()
  return flat.length > n ? `${flat.slice(0, n)}…` : flat
}

// Where a tool acts, so a Mac action never looks like a chat reply.
const MAC_TOOLS = /^(set_volume|mute|unmute|toggle_(wifi|bluetooth|dnd)|adjust_brightness|lock_screen|open_app|quit_app|list_running_apps|take_screenshot|read_clipboard|write_clipboard|open_url_in_browser|observe_current_tab|read_screen|ask_about_screen)$/
const GITHUB_TOOLS = /^(get_me|set_repo_visibility|search_(repositories|code|issues|pull_requests|commits)|get_file_contents|list_(issues|pull_requests|commits|branches|releases|tags)|issue_|pull_request|create_(pull_request|branch|repository|or_update_file)|merge_|push_files|fork_|actions_|get_job_logs|add_issue)/
function scope(name = ''): { label: string; strong: boolean } | null {
  if (MAC_TOOLS.test(name)) return { label: 'your mac', strong: true }
  if (name === 'run_shell_command') return { label: 'shell', strong: true }
  if (GITHUB_TOOLS.test(name)) return { label: 'github', strong: true }
  if (name === 'run_python') return { label: 'sandbox', strong: false }
  if (/vault|_note|^list_notes$|conversation/.test(name)) return { label: 'vault', strong: false }
  if (/^(search_wikipedia|find_image|fetch)$|^browser_/.test(name)) return { label: 'web', strong: false }
  return null
}

const turnEntries = computed(() => {
  const at = entries.value.map((e) => e.kind).lastIndexOf('user')
  return at < 0 ? [] : entries.value.slice(at)
})
// Where the current request is: send › route › tools › reply › speak.
const flow = computed(() => {
  if (speaking.value) return 5
  if (!busy.value) return 0
  const kinds = turnEntries.value.map((e) => e.kind)
  if (kinds.includes('text')) return 4
  if (kinds.includes('tool')) return 3
  return kinds.includes('route') ? 2 : 1
})
const title = computed(() => {
  const first = entries.value.find((e) => e.kind === 'user')
  return first ? short(first.text, 56) : 'New chat'
})
const routeLine = computed(() => {
  const route = [...entries.value].reverse().find((e) => e.kind === 'route')
  if (!route) return entries.value.length ? '' : 'no messages yet'
  return `${persona.value === 'auto' ? 'routed' : 'chosen'} → ${route.text.replace('/', ' · ')}`
})
const [personaName, personaTier] = [(t: string) => t.split('/')[0], (t: string) => t.split('/')[1] ?? '']
const zoomed = ref(new Set<number>())
const toggle = (set: Set<number>, id: number) => (set.has(id) ? set.delete(id) : set.add(id))
</script>
<template>
  <div class="shell">
    <header class="rail">
      <div class="logo">hi</div>
      <div class="sys" :class="{ busy: state() !== 'ready' && state() !== 'offline', bad: state() === 'offline' }" role="status">{{ state() }}</div>
      <nav class="nav">
        <button v-for="v in VIEWS" :key="v" :class="{ on: v === view }" :aria-current="v === view ? 'page' : undefined" @click="view = v">
          {{ v }}<span v-if="v === 'tasks' && activeTasks" class="count">{{ activeTasks }}</span>
        </button>
      </nav>
      <div class="rail-foot">
        <button class="plain" @click="clear(); view = 'chat'">new chat</button>
        <button class="plain" :title="`${host} · ${model}`" @click="cycleTheme">theme: {{ theme }}</button>
      </div>
    </header>

    <main class="stage">
      <div v-show="view === 'chat'" class="chat">
        <header class="top">
          <div class="titles">
            <h1>{{ title }}</h1>
            <span class="sub">{{ routeLine }}</span>
          </div>
          <div class="grow"></div>
          <ol class="strip" aria-label="Request progress">
            <li v-for="(label, i) in FLOW" :key="label" :class="{ now: flow === i + 1, past: flow > i + 1 }">{{ label }}</li>
          </ol>
        </header>

        <div ref="logEl" class="feed">
          <div class="lane">
            <div v-if="!entries.length" class="hero">
              <p><b>hi.</b> Type or talk. I run commands, control your Mac, search your notes and read the web. Everything I do shows up here as it happens.</p>
            </div>
            <template v-for="e in entries" :key="e.id">
              <div v-if="e.kind === 'user'" class="turn-user"><span class="who dim">you</span><p class="say">{{ e.text }}</p></div>
              <div v-else-if="e.kind === 'route'" class="who">
                <b>{{ personaName(e.text) }}</b><span class="dim">{{ personaTier(e.text) }}</span>
              </div>
              <div v-else-if="e.kind === 'tool'" class="step" :class="{ running: e.result === undefined, open: expanded.has(e.id) }">
                <button class="stephead" :aria-expanded="expanded.has(e.id)" @click="toggle(expanded, e.id)">
                  <span class="node" aria-hidden="true"></span>
                  <span class="st-title">{{ e.name }}</span>
                  <span class="st-sum">{{ e.result === undefined ? 'running…' : short(e.result, 140) }}</span>
                  <span v-if="scope(e.name)" class="scope" :class="{ strong: scope(e.name)!.strong }">{{ scope(e.name)!.label }}</span>
                </button>
                <div v-if="expanded.has(e.id)" class="inner">
                  <div class="lbl">arguments</div>
                  <pre class="tape">{{ e.text || '(none)' }}</pre>
                  <div class="lbl">result</div>
                  <pre class="tape result">{{ e.result ?? '(waiting for result)' }}</pre>
                </div>
                <figure v-for="src in plots(e.result)" :key="src" class="fig" :class="{ wide: zoomed.has(e.id) }">
                  <img :src="src" alt="result image" />
                  <figcaption>
                    <span>{{ src.split('/').pop() }}</span>
                    <button class="btn quiet" @click="toggle(zoomed, e.id)">{{ zoomed.has(e.id) ? 'Shrink' : 'Expand' }}</button>
                  </figcaption>
                </figure>
                <div v-for="f in files(e.result)" :key="f.href" class="filerow">
                  <b>{{ f.name }}</b>
                  <a class="btn quiet" :href="f.href" target="_blank" rel="noopener">Download</a>
                </div>
              </div>
              <Markdown v-else-if="e.kind === 'text'" :source="e.text" class="reply" />
              <div v-else-if="e.kind === 'thinking'" class="thinking dim">{{ e.text }}</div>
              <div v-else-if="e.kind === 'context'" class="timing dim">used {{ e.text }}</div>
              <div v-else-if="e.kind === 'timing'" class="timing dim">{{ e.text }}</div>
              <div v-else-if="e.kind === 'error'" class="err note">{{ e.text }}</div>
              <div v-else class="note dim">{{ e.text }}</div>
            </template>
          </div>
        </div>

        <div class="dock">
          <div class="lane">
            <div v-if="pending.length" class="gate" role="alertdialog">
              <span class="msg"><b>Confirm deletion</b> <span>{{ pending[0].description }}</span></span>
              <button class="btn danger" @click="answerPending(true)">Delete <kbd>y</kbd></button>
              <button class="btn quiet" @click="answerPending(false)">Keep <kbd>n</kbd></button>
            </div>

            <div v-if="!entries.length" class="tries">
              <span class="lbl">try</span>
              <button v-for="t in TRIES" :key="t" class="chip" @click="submit(t)">{{ t }}</button>
            </div>

            <form class="comp" autocomplete="off" @submit.prevent="submit()">
              <div class="row">
                <span class="prompt" aria-hidden="true">&gt;</span>
                <input
                  ref="inputEl"
                  v-model="input"
                  :placeholder="mic === 'listening' ? 'Listening… speak now' : 'Message hi'"
                  aria-label="Message"
                  spellcheck="false"
                  autocomplete="off"
                  @keydown.up.prevent="recall(-1)"
                  @keydown.down.prevent="recall(1)"
                />
                <span v-if="mic !== 'idle'" class="wakehint">{{ mic }}…</span>
                <span v-else-if="wake" class="wakehint">say “{{ getWakePhrase() }}”…</span>
                <button class="btn primary" type="submit">Send →</button>
              </div>
              <div class="tools">
                <span class="lbl">input</span>
                <button type="button" class="tog" :aria-pressed="mic !== 'idle'" :disabled="mic === 'transcribing' || mic === 'structuring'" title="Dictate into the box. Does not send or speak." @click="listen(false)">Dictate</button>
                <button type="button" class="tog" :aria-pressed="rambler" title="Clean up and structure what you said before sending" @click="rambler = !rambler">Tidy</button>
                <span class="lbl">voice</span>
                <button type="button" class="tog" :aria-pressed="speakReplies" title="Read replies aloud, even for typed requests" @click="speakReplies = !speakReplies">Speak</button>
                <button type="button" class="tog" :aria-pressed="wake" title="Always listening for the wake phrase (set in settings)" @click="toggleWake">Wake</button>
                <button type="button" class="tog" :aria-pressed="talk" title="Conversation mode: speak the reply, then listen again" @click="toggleTalk">Converse</button>
                <button type="button" class="tog agent-pick" :aria-pressed="persona !== 'auto'" title="Advanced: force one agent for your next messages. Auto picks for you." @click="nextPersona">agent: {{ persona }}</button>
                <button type="button" class="btn quiet voice-open" title="Full-screen orb, hands-free" @click="toggleVoiceMode">Voice mode</button>
              </div>
            </form>
            <div class="keys"><span><kbd>↵</kbd>send</span><span><kbd>↑</kbd><kbd>↓</kbd>recall</span><span><kbd>esc</kbd>cancel</span><span><kbd>y</kbd><kbd>n</kbd>answer a confirmation</span></div>
          </div>
        </div>
      </div>

      <History v-if="view === 'history'" />
      <Tasks v-else-if="view === 'tasks'" />
      <Memory v-else-if="view === 'memory'" :key="view" />
      <Status v-else-if="view === 'status'" />
      <Settings v-else-if="view === 'settings'" />
    </main>

    <section v-if="voiceMode" class="voice" role="dialog" aria-modal="true" aria-label="Voice mode">
      <div class="voice-top">
        <b>hi</b>
        <button class="btn quiet" @click="toggleVoiceMode">Leave voice mode (esc)</button>
      </div>
      <Orb :state="state()" />
      <div class="word" role="status">{{ state() }}</div>
      <p class="cap">{{ caption }}</p>
      <div v-if="pending.length" class="gate" @click.stop>
        <span class="msg"><b>Confirm deletion</b> <span>{{ pending[0].description }}</span></span>
        <button class="btn danger" @click="answerPending(true)">Delete <kbd>y</kbd></button>
        <button class="btn quiet" @click="answerPending(false)">Keep <kbd>n</kbd></button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.shell { display: grid; grid-template-rows: auto minmax(0, 1fr); grid-template-columns: minmax(0, 1fr); height: 100%; position: relative; }

/* header rail */
.rail { display: flex; align-items: baseline; gap: 6px 22px; flex-wrap: wrap; padding: 14px var(--gutter) 12px; border-bottom: 1px solid var(--line); }
.logo { font-weight: 600; font-size: 14px; }
.sys { display: flex; gap: 7px; align-items: baseline; color: var(--dim); font-size: 12px; }
.sys::before { content: '●'; color: var(--ok); font-size: 9px; position: relative; top: -1px; }
.sys.busy::before { content: '▌'; color: var(--ink); font-size: 12px; top: 1px; animation: blink 1s steps(1) infinite; }
.sys.bad::before { color: var(--err); }
.nav { display: flex; gap: 2px 16px; flex-wrap: wrap; }
.nav button { color: var(--dim); min-height: 28px; display: inline-flex; align-items: center; gap: 4px; }
.nav button:hover { color: var(--ink); }
.nav button.on { color: var(--ink); text-decoration: underline; text-underline-offset: 6px; }
.count { color: var(--dim); }
.count::before { content: '('; }
.count::after { content: ')'; }
.rail-foot { margin-left: auto; color: var(--dim); font-size: 12px; display: flex; gap: 16px; }
.plain { color: var(--dim); min-height: 28px; }
.plain:hover { color: var(--ink); text-decoration: underline; }

.stage { display: flex; flex-direction: column; min-width: 0; min-height: 0; height: 100%; }
.stage > * { min-height: 0; }
.chat { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.titles { min-width: 0; }

/* progress strip */
.strip { display: flex; margin: 0; padding: 0; list-style: none; font-size: 12px; color: var(--dim); }
.strip li + li::before { content: '›'; margin: 0 8px; color: var(--line); }
.strip li.past { color: var(--ink); }
.strip li.now { color: var(--ink); font-weight: 600; }
.strip li.now::after { content: '▌'; animation: blink 1s steps(1) infinite; }

/* feed */
.feed { flex: 1 1 0; min-height: 0; overflow-y: auto; scrollbar-width: thin; }
.lane { max-width: calc(100ch + 40px); margin: 0 auto; padding: 0 20px; }
.feed .lane { padding-top: 18px; padding-bottom: 20px; display: flex; flex-direction: column; gap: 10px; }
.hero { padding: 6vh 0 0; color: var(--dim); max-width: 60ch; }
.hero b { color: var(--ink); font-weight: 600; }
.turn-user { margin-top: 22px; animation: fade 0.3s both; }
.turn-user:first-child { margin-top: 0; }
.who { display: flex; gap: 10px; color: var(--dim); font-size: 12px; margin-top: 2px; }
.who b { color: var(--ink); font-weight: 600; }
.say { font-size: 14.5px; font-weight: 600; overflow-wrap: anywhere; white-space: pre-wrap; }
.say::before { content: '> '; color: var(--dim); font-weight: 400; }
.reply { max-width: 68ch; margin-top: 4px; }
.note, .thinking, .timing { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; max-width: 68ch; }
.thinking { font-style: italic; }

/* tool steps */
.step { position: relative; padding-left: 2.5ch; }
.stephead { width: 100%; display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 0 12px; padding: 4px 0; min-height: 32px; align-items: baseline; }
.stephead .node { position: absolute; left: 0; top: 4px; color: var(--dim); font-size: 12px; }
.node::before { content: '+'; }
.step.running .node::before { content: '~'; color: var(--ink); animation: blink 1s steps(1) infinite; }
.stephead:hover .st-title { text-decoration: underline; text-underline-offset: 3px; }
.st-title { font-weight: 600; }
.st-sum { color: var(--dim); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.scope { color: var(--dim); font-size: 11.5px; }
.scope::before { content: '('; }
.scope::after { content: ')'; }
.scope.strong { color: var(--ink); font-weight: 600; }
.inner { display: flex; flex-direction: column; gap: 6px; padding: 6px 0 14px; }
.fig { margin: 10px 0 0; width: 420px; max-width: 100%; transition: width 0.3s; }
.fig.wide { width: 100%; }
.fig img { display: block; width: 100%; height: auto; background: #fff; }
.fig figcaption { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 4px 0; border-top: 1px solid var(--line); color: var(--dim); font-size: 12px; }
.filerow { display: flex; align-items: baseline; gap: 16px; margin-top: 10px; padding: 6px 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); max-width: 68ch; }
.filerow b { flex: 1; font-weight: 600; overflow-wrap: anywhere; }
a.btn { text-decoration: none; }

/* dock */
.dock { flex: none; padding-bottom: 14px; background: var(--bg); }
.gate { display: flex; align-items: baseline; gap: 6px 20px; flex-wrap: wrap; padding: 10px 0; margin-bottom: 6px; border-top: 1px solid var(--err); border-bottom: 1px solid var(--err); color: var(--err); }
.gate .msg { flex: 1 1 220px; display: flex; gap: 10px; flex-wrap: wrap; color: inherit; font-size: inherit; }
.gate .msg b { font-weight: 600; }
.gate .msg span { color: var(--ink); }
kbd { font: inherit; opacity: 0.7; margin-left: 4px; }
.tries { display: flex; gap: 4px 16px; align-items: baseline; overflow-x: auto; padding: 4px 0 8px; scrollbar-width: none; font-size: 12px; }
.tries::-webkit-scrollbar { display: none; }
.tries .lbl { flex: none; }
.chip { flex: none; color: var(--dim); min-height: 28px; font-size: 12px; white-space: nowrap; }
.chip:hover { color: var(--ink); text-decoration: underline; text-underline-offset: 3px; }
.comp { border-top: 1px solid var(--ink); }
.comp .row { display: flex; align-items: center; gap: 10px; }
.comp .prompt { font-weight: 600; }
.comp input { flex: 1; min-width: 0; height: 48px; border: 0; background: transparent; outline: none; font-size: 14.5px; }
.comp input::placeholder { color: var(--dim); opacity: 1; }
.wakehint { color: var(--dim); font-size: 12px; white-space: nowrap; }
.tools { display: flex; gap: 2px 16px; flex-wrap: wrap; align-items: baseline; }
.tog { min-height: 30px; color: var(--dim); font-size: 12.5px; display: inline-flex; gap: 1ch; }
.tog::before { content: '[ ]'; }
.tog:hover:not(:disabled) { color: var(--ink); }
.tog[aria-pressed='true'] { color: var(--ink); font-weight: 600; }
.tog[aria-pressed='true']::before { content: '[x]'; }
.voice-open { margin-left: auto; }
.keys { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 4px; color: var(--dim); font-size: 11.5px; }
.keys kbd { opacity: 1; color: var(--ink); margin: 0 5px 0 0; }

/* voice mode */
.voice { position: absolute; inset: 0; z-index: 50; background: var(--bg); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 14px; padding: 64px 20px 28px; animation: fade 0.25s both; }
.voice-top { position: absolute; top: 14px; left: 20px; right: 20px; display: flex; align-items: baseline; justify-content: space-between; }
.voice .word { font-size: 20px; font-weight: 600; }
.voice .cap { color: var(--dim); max-width: 60ch; text-align: center; min-height: 2.8em; }

@media (max-width: 640px) {
  .rail-foot { margin-left: 0; width: 100%; }
  .strip { width: 100%; }
  .keys { display: none; }
}
@media (max-height: 760px) { .keys { display: none; } }
</style>
