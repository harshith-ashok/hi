<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { fetchConfig, fetchModels, fetchVoices, saveConfig } from './backend'
import { getWakePhrase, setWakePhrase, speak, unlockAudio } from './voice'

type Mode = 'local' | 'tailscale' | 'openrouter'
const MODES: { id: Mode; hint: string }[] = [
  { id: 'local', hint: 'Ollama on this machine' },
  { id: 'tailscale', hint: 'Ollama on another machine over Tailscale' },
  { id: 'openrouter', hint: 'OpenRouter API' },
]
const ENDPOINT: Record<Mode, { key: string; label: string; placeholder: string; secret?: boolean }> = {
  local: { key: 'OLLAMA_HOST', label: 'ollama url', placeholder: 'http://127.0.0.1:11434' },
  tailscale: { key: 'TAILSCALE_OLLAMA_URL', label: 'tailscale ollama url', placeholder: 'http://my-desktop:11434 or http://100.x.y.z:11434' },
  openrouter: { key: 'OPENROUTER_API_KEY', label: 'openrouter api key', placeholder: 'sk-or-…', secret: true },
}
const MODEL_KEYS = ['HAIKU_MODEL', 'SONNET_MODEL', 'OPUS_MODEL', 'TERM_MODEL', 'BUTLER_MODEL', 'DOCS_MODEL', 'WEB_MODEL', 'VISION_MODEL']

const tab = ref<'connection' | 'models' | 'voice'>('connection')
const active = ref<Mode>('local')
const mode = ref<Mode>('local')
const keySet = ref(false)
const endpoints = reactive<Record<string, string>>({ OLLAMA_HOST: '', TAILSCALE_OLLAMA_URL: '', OPENROUTER_API_KEY: '' })
const models = reactive<Record<string, string>>({})
const loaded = reactive<Record<string, string>>({}) // what the backend has, to send only changes
const available = ref<string[]>([])
const filter = ref('')
const focused = ref('')
const status = ref('')

const voices = ref<string[]>([])
const voice = ref('default')
const voiceSaved = ref('default')
const wakePhrase = ref(getWakePhrase())
const voiceStatus = ref('')

async function loadVoices() {
  const result = await fetchVoices()
  voices.value = result?.voices ?? []
  voiceStatus.value = result === null ? 'backend unreachable' : result.error
}

async function preview() {
  unlockAudio()
  voiceStatus.value = `speaking as ${voice.value} …`
  await speak(`Hi, this is ${voice.value}. How does this sound?`, (why) => (voiceStatus.value = `tts failed: ${why}`), voice.value)
  if (voiceStatus.value.startsWith('speaking')) voiceStatus.value = ''
}

async function saveVoice() {
  setWakePhrase(wakePhrase.value)
  wakePhrase.value = getWakePhrase()
  if (voice.value !== voiceSaved.value) {
    const result = await saveConfig({ TTS_VOICE: voice.value })
    if (!result) return void (voiceStatus.value = 'save failed')
    voiceSaved.value = voice.value
  }
  voiceStatus.value = 'saved'
}

const endpoint = computed(() => ENDPOINT[mode.value])
const shown = computed(() => available.value.filter((m) => m.toLowerCase().includes(filter.value.toLowerCase())).slice(0, 200))

async function loadModels() {
  status.value = 'checking …'
  const url = mode.value === 'openrouter' ? '' : endpoints[endpoint.value.key]
  const result = await fetchModels(mode.value, url)
  available.value = result?.models ?? []
  status.value = result === null ? 'backend unreachable' : result.error || `${available.value.length} models available`
}

async function selectMode(next: Mode) {
  mode.value = next
  const config = await fetchConfig(next)
  if (config) {
    for (const key of MODEL_KEYS) loaded[key] = models[key] = String(config[key] ?? '')
  }
  filter.value = ''
  await loadModels()
}

async function save() {
  const body: Record<string, string> = { AI_MODE: mode.value }
  for (const key of MODEL_KEYS) if (models[key] && models[key] !== loaded[key]) body[key] = models[key]
  const field = endpoint.value.key
  if (endpoints[field] || !endpoint.value.secret) body[field] = endpoints[field]
  const result = await saveConfig(body)
  if (!result) {
    status.value = 'save failed'
    return
  }
  active.value = mode.value
  if (endpoint.value.secret && endpoints[field]) {
    keySet.value = true
    endpoints[field] = ''
  }
  Object.assign(loaded, models)
  status.value = `now using ${mode.value} · saved ${result.updated.join(', ')}`
  await loadModels()
}

onMounted(async () => {
  const config = await fetchConfig()
  if (!config) {
    status.value = 'backend unreachable'
    return
  }
  active.value = mode.value = String(config.AI_MODE) as Mode
  voice.value = voiceSaved.value = String(config.TTS_VOICE ?? 'default')
  void loadVoices()
  endpoints.OLLAMA_HOST = String(config.OLLAMA_HOST ?? '')
  endpoints.TAILSCALE_OLLAMA_URL = String(config.TAILSCALE_OLLAMA_URL ?? '')
  keySet.value = Boolean(config.OPENROUTER_API_KEY_SET)
  await selectMode(mode.value)
})
</script>

<template>
  <header class="top">
    <div><h1>Settings</h1></div>
    <div class="grow"></div>
    <div class="tabs notab" role="tablist">
      <button v-for="t in ['connection', 'models', 'voice']" :key="t" role="tab" :class="{ on: tab === t }" @click="tab = t as typeof tab">{{ t }}</button>
    </div>
  </header>
  <div class="scroll">
    <div class="col">
      <template v-if="tab === 'connection'">
        <section class="stack">
          <div class="sect-h"><h2>Where the language model runs</h2></div>
          <div class="seg" role="radiogroup" aria-label="AI mode">
            <button v-for="m in MODES" :key="m.id" role="radio" :aria-checked="m.id === mode" @click="selectMode(m.id)">
              {{ m.id }}<span v-if="m.id === active" class="dim"> · active</span>
            </button>
          </div>
          <p class="hint">{{ MODES.find((m) => m.id === mode)?.hint }}<span v-if="mode !== active"> — not active until saved</span></p>
        </section>
        <div class="form">
          <label>{{ endpoint.label }}
            <input
              v-model="endpoints[endpoint.key]"
              class="field"
              :type="endpoint.secret ? 'password' : 'text'"
              :placeholder="endpoint.secret && keySet ? '•••••••• (set — type to replace)' : endpoint.placeholder"
              spellcheck="false"
              autocomplete="off"
              @keydown.enter="loadModels"
            />
          </label>
        </div>
      </template>

      <div v-else-if="tab === 'models'" class="cols two">
        <section>
          <div class="sect-h"><h2>Model per role</h2></div>
          <div class="pick">
            <button v-for="key in MODEL_KEYS" :key="key" :class="{ on: focused === key }" @click="focused = key">
              <span class="r">{{ key.replace('_MODEL', '') }}</span><span class="m">{{ models[key] }}</span>
            </button>
          </div>
        </section>
        <section>
          <div class="sect-h"><h2>Assign to {{ focused ? focused.replace('_MODEL', '') : '…' }}</h2><span>{{ available.length }} available</span></div>
          <input v-model="filter" class="field full" aria-label="Filter models" placeholder="Filter models…" spellcheck="false" />
          <div class="pick items">
            <button v-for="m in shown" :key="m" :disabled="!focused" @click="models[focused] = m">
              <span>{{ m }}</span><span v-if="focused && models[focused] === m" class="assigned">assigned</span>
            </button>
            <div v-if="!shown.length" class="empty">No models found. Check the connection.</div>
          </div>
        </section>
      </div>

      <div v-else class="cols two">
        <section>
          <div class="sect-h"><h2>Voice for replies</h2><span>phonon</span></div>
          <div class="pick" role="radiogroup" aria-label="Voice">
            <button v-if="!voices.includes(voice)" class="on"><span>{{ voice }}</span></button>
            <button v-for="v in voices" :key="v" role="radio" :class="{ on: v === voice }" :aria-checked="v === voice" @click="voice = v"><span>{{ v }}</span></button>
          </div>
          <button class="btn quiet" @click="preview">Preview {{ voice }}</button>
        </section>
        <section>
          <div class="sect-h"><h2>Wake phrase</h2></div>
          <div class="form">
            <input v-model="wakePhrase" class="field big" aria-label="Wake phrase" placeholder="hey hi" spellcheck="false" @keydown.enter="saveVoice" />
            <p class="hint">Used when Wake is on. Say it, then speak your request.</p>
            <div><button class="btn primary" @click="saveVoice">Save voice</button> <span class="msg">{{ voiceStatus }}</span></div>
          </div>
        </section>
      </div>

      <div v-if="tab !== 'voice'" class="formfoot">
        <button class="btn" @click="loadModels">Test</button>
        <button class="btn primary" @click="save">Save &amp; use {{ mode }}</button>
        <span class="msg">{{ status }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.notab { border-bottom: 0; }
.stack { display: flex; flex-direction: column; gap: 14px; }
.seg { display: flex; flex-wrap: wrap; gap: 2px 18px; }
.seg button { min-height: 34px; color: var(--dim); display: inline-flex; gap: 1ch; }
.seg button::before { content: '( )'; }
.seg button[aria-checked='true'] { color: var(--ink); font-weight: 600; }
.seg button[aria-checked='true']::before { content: '(•)'; }
.form { display: flex; flex-direction: column; gap: 14px; max-width: 60ch; }
.form label { display: flex; flex-direction: column; gap: 2px; color: var(--dim); font-size: 12px; }
.form .field { width: 100%; color: var(--ink); font-size: 13.5px; }
.field.big { font-size: 16px; }
.field.full { width: 100%; margin: 12px 0; }
.two { grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }
.pick { display: flex; flex-direction: column; margin-bottom: 8px; }
.pick button { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; min-height: 32px; width: 100%; padding: 3px 0 3px 12px; margin-left: -12px; border-left: 2px solid transparent; overflow-wrap: anywhere; }
.pick button:hover:not(:disabled) { border-left-color: var(--line); }
.pick button.on { border-left-color: var(--ink); }
.pick .r { font-weight: 600; }
.pick .m { color: var(--dim); }
.assigned { font-size: 12px; }
.assigned::before { content: '● '; }
.items { max-height: 420px; overflow-y: auto; }
.formfoot { display: flex; align-items: baseline; gap: 20px; flex-wrap: wrap; padding-top: 14px; border-top: 1px solid var(--line); }
</style>
