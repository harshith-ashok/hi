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
  <div class="settings">
    <div class="modes">
      <button v-for="m in MODES" :key="m.id" :class="{ on: m.id === mode }" @click="selectMode(m.id)">
        {{ m.id === mode ? '▸' : ' ' }} {{ m.id }}<span v-if="m.id === active" class="accent"> ●</span>
      </button>
    </div>
    <div class="dim hint">{{ MODES.find((m) => m.id === mode)?.hint }}<span v-if="mode !== active"> — not active until saved</span></div>

    <div class="cols">
      <div class="fields">
        <label>
          <span class="dim">{{ endpoint.label }}</span>
          <input
            v-model="endpoints[endpoint.key]"
            :type="endpoint.secret ? 'password' : 'text'"
            :placeholder="endpoint.secret && keySet ? '•••••••• (set — type to replace)' : endpoint.placeholder"
            spellcheck="false"
            autocomplete="off"
            @keydown.enter="loadModels"
          />
        </label>
        <label v-for="key in MODEL_KEYS" :key="key">
          <span class="dim">{{ key }}</span>
          <input v-model="models[key]" list="available" spellcheck="false" @focus="focused = key" @keydown.enter="save" />
        </label>
        <datalist id="available"><option v-for="m in shown" :key="m" :value="m" /></datalist>
      </div>

      <div class="list">
        <span class="dim">models</span>
        <input v-model="filter" class="filter" placeholder="filter" spellcheck="false" />
        <div class="items">
          <button v-for="m in shown" :key="m" :disabled="!focused" @click="models[focused] = m">{{ m }}</button>
        </div>
      </div>
    </div>

    <div class="voice">
      <span class="dim">voice (phonon)</span>
      <select v-model="voice">
        <option v-if="!voices.includes(voice)" :value="voice">{{ voice }}</option>
        <option v-for="v in voices" :key="v" :value="v">{{ v }}</option>
      </select>
      <button @click="preview">preview</button>
      <span class="dim">wake phrase</span>
      <input v-model="wakePhrase" placeholder="hey hi" spellcheck="false" @keydown.enter="saveVoice" />
      <button class="accent" @click="saveVoice">save voice</button>
      <span class="dim">{{ voiceStatus }}</span>
    </div>

    <div class="bar dim">
      {{ status }}
      <span class="actions">
        <button @click="loadModels">test</button>
        <button class="accent" @click="save">save &amp; use {{ mode }}</button>
      </span>
    </div>
  </div>
</template>

<style scoped>
.settings { overflow-y: auto; }
.modes button { background: none; border: 0; padding: 0; margin-right: 3ch; cursor: pointer; white-space: pre; }
.modes button:hover, .modes button.on { color: var(--accent); }
.hint { margin: 4px 0 16px; }
.cols { display: flex; gap: 32px; }
.fields { flex: 3; display: grid; gap: 8px; align-content: start; }
.list { flex: 2; display: flex; flex-direction: column; min-width: 0; }
.items { display: flex; flex-direction: column; align-items: flex-start; max-height: 420px; overflow-y: auto; }
.items button { background: none; border: 0; padding: 0; cursor: pointer; text-align: left; word-break: break-all; }
.items button:hover:not(:disabled) { color: var(--accent); }
.items button:disabled { cursor: default; }
label { display: grid; gap: 2px; }
input { background: none; border: 1px solid var(--dim); padding: 4px 8px; outline: none; }
input:focus { border-color: var(--accent); }
.filter { margin: 2px 0 8px; }
.voice { margin-top: 20px; display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; }
.voice select { background: var(--bg); color: inherit; border: 1px solid var(--dim); padding: 4px 8px; font: inherit; }
.voice button { background: none; border: 0; cursor: pointer; padding: 0; color: var(--dim); }
.voice button:hover, .voice .accent { color: var(--accent); }
.bar { margin-top: 12px; display: flex; justify-content: space-between; }
.actions button { background: none; border: 0; cursor: pointer; color: var(--dim); margin-left: 16px; padding: 0; }
.actions button:hover, .actions .accent { color: var(--accent); }
.dim { color: var(--dim); }
.accent { color: var(--accent); }
</style>
