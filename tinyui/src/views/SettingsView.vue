<script setup lang="ts">
import { Check, Loader2 } from '@lucide/vue'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import PageHeader from '@/components/app/PageHeader.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { autoOpen } from '@/composables/useArtifact'
import { askOnce, notificationsOn, permission } from '@/composables/useNotifications'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'
import { BASE_URL, fetchConfig, fetchModels, fetchVoices, getJson, saveConfig, saveConfigChecked } from '@/backend'
import ImagesTab from '@/views/ImagesTab.vue'
import { getWakePhrase, setWakePhrase, speak, unlockAudio } from '@/voice'

type Mode = 'local' | 'tailscale'
const MODES: { id: Mode; hint: string }[] = [
  { id: 'local', hint: 'Ollama on this machine' },
  { id: 'tailscale', hint: 'Ollama on another machine over Tailscale' },
]
const ENDPOINT: Record<Mode, { key: string; label: string; placeholder: string }> = {
  local: { key: 'OLLAMA_HOST', label: 'Ollama URL', placeholder: 'http://127.0.0.1:11434' },
  tailscale: { key: 'TAILSCALE_OLLAMA_URL', label: 'Tailscale Ollama URL', placeholder: 'http://my-desktop:11434 or http://100.x.y.z:11434' },
}
const MODEL_KEYS = ['HAIKU_MODEL', 'SONNET_MODEL', 'OPUS_MODEL', 'VISION_MODEL']
const BACKENDS: [string, string][] = [['ollama', 'phonon (Ollama)'], ['huggingface', 'Hugging Face (GPU)']]
const AUTO_KEYS = ['HEARTBEAT', 'HEARTBEAT_EVERY', 'HEARTBEAT_HOURS', 'SCREENSHOT_WATCH', 'MAX_BACKGROUND_RUNS_PER_HOUR', 'MAX_HOSTED_CALLS_PER_DAY', 'MAX_NOTIFICATIONS_PER_HOUR', 'PROPOSAL_TTL_DAYS'] as const

const tab = ref('connection')

// personal preferences: standing instructions that go with every message (hi/knowledge/preferences.md)
const prefs = ref('')
const prefsSaved = ref('')
const prefsMax = ref(8000)
const prefsStatus = ref('')
async function loadPrefs() {
  const found = await getJson<{ text: string; max_chars: number }>('/preferences')
  if (!found) return void (prefsStatus.value = 'Could not load: is the backend running?')
  prefs.value = prefsSaved.value = found.text
  prefsMax.value = found.max_chars
}
async function savePrefs() {
  try {
    const res = await fetch(`${BASE_URL}/preferences`, { method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-Hi-Client': 'tinyui' }, body: JSON.stringify({ text: prefs.value }) })
    if (!res.ok) return void (prefsStatus.value = (await res.json().catch(() => ({})))?.detail ?? 'Could not save.')
    prefsSaved.value = prefs.value.trim()
    prefsStatus.value = 'Saved. The next reply uses it.'
  } catch {
    prefsStatus.value = 'Could not save: is the backend running?'
  }
}
watch(tab, (t) => { if (t === 'interface') void loadPrefs() })
const active = ref<Mode>('local')
const mode = ref<Mode>('local')
const endpoints = reactive<Record<string, string>>({ OLLAMA_HOST: '', TAILSCALE_OLLAMA_URL: '' })
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
const ttsBackend = ref('ollama')

const automation = reactive<Record<string, string>>({})
const autoStatus = ref('')
const saving = ref(false)

const endpoint = computed(() => ENDPOINT[mode.value])
const shown = computed(() => available.value.filter((m) => m.toLowerCase().includes(filter.value.toLowerCase())).slice(0, 200))
const everyMinutes = computed({
  get: () => String(Math.round(Number(automation.HEARTBEAT_EVERY || 1800) / 60)),
  set: (v: string) => (automation.HEARTBEAT_EVERY = String(Math.max(1, Number(v) || 30) * 60)),
})

async function pickBackend(value: string) {
  ttsBackend.value = value
  voice.value = 'default' // voices differ per engine
  if (!(await saveConfig({ TTS_BACKEND: value, TTS_VOICE: 'default' }))) return void (voiceStatus.value = 'Save failed')
  voiceSaved.value = 'default'
  await loadVoices()
}
async function loadVoices() {
  const result = await fetchVoices()
  voices.value = result?.voices ?? []
  voiceStatus.value = result === null ? 'Backend unreachable' : result.error
}
async function preview() {
  unlockAudio()
  voiceStatus.value = `Speaking as ${voice.value}…`
  await speak(`Hi, this is ${voice.value}. How does this sound?`, (why) => (voiceStatus.value = `TTS failed: ${why}`), voice.value)
  if (voiceStatus.value.startsWith('Speaking')) voiceStatus.value = ''
}
async function saveVoice() {
  setWakePhrase(wakePhrase.value)
  wakePhrase.value = getWakePhrase()
  if (voice.value !== voiceSaved.value) {
    if (!(await saveConfig({ TTS_VOICE: voice.value }))) return void (voiceStatus.value = 'Save failed')
    voiceSaved.value = voice.value
  }
  voiceStatus.value = 'Saved'
}

async function loadModels() {
  status.value = 'Checking…'
  const result = await fetchModels(mode.value, endpoints[endpoint.value.key])
  available.value = result?.models ?? []
  status.value = result === null ? 'Backend unreachable' : result.error || `${available.value.length} models available`
}
async function selectMode(next: Mode) {
  mode.value = next
  const config = await fetchConfig(next)
  if (config) for (const key of MODEL_KEYS) loaded[key] = models[key] = String(config[key] ?? '')
  filter.value = ''
  await loadModels()
}
async function save() {
  saving.value = true
  const body: Record<string, string> = { AI_MODE: mode.value }
  for (const key of MODEL_KEYS) if (models[key] && models[key] !== loaded[key]) body[key] = models[key]
  body[endpoint.value.key] = endpoints[endpoint.value.key]
  const result = await saveConfig(body)
  saving.value = false
  if (!result) return void (status.value = 'Save failed')
  active.value = mode.value
  Object.assign(loaded, models)
  status.value = `Now using ${mode.value} · saved ${result.updated.join(', ')}`
  await loadModels()
}
async function saveAutomation() {
  const body: Record<string, string> = {}
  for (const key of AUTO_KEYS) body[key] = String(automation[key] ?? '')
  autoStatus.value = (await saveConfigChecked(body)).message
}

onMounted(async () => {
  const config = await fetchConfig()
  if (!config) return void (status.value = 'Backend unreachable')
  for (const key of AUTO_KEYS) automation[key] = String(config[key] ?? '')
  active.value = mode.value = String(config.AI_MODE) as Mode
  voice.value = voiceSaved.value = String(config.TTS_VOICE ?? 'default')
  ttsBackend.value = String(config.TTS_BACKEND ?? 'ollama')
  void loadVoices()
  endpoints.OLLAMA_HOST = String(config.OLLAMA_HOST ?? '')
  endpoints.TAILSCALE_OLLAMA_URL = String(config.TAILSCALE_OLLAMA_URL ?? '')
  await selectMode(mode.value)
})
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <PageHeader title="Settings" />
    <div class="min-h-0 flex-1 overflow-y-auto p-4">
      <div class="mx-auto max-w-4xl space-y-4">
        <Tabs v-model="tab"><TabsList><TabsTrigger value="connection">Connection</TabsTrigger><TabsTrigger value="models">Models</TabsTrigger><TabsTrigger value="voice">Voice</TabsTrigger><TabsTrigger value="images">Images</TabsTrigger><TabsTrigger value="interface">Interface</TabsTrigger><TabsTrigger value="automation">Automation</TabsTrigger></TabsList></Tabs>

        <Card v-if="tab === 'connection'">
          <CardHeader><CardTitle>Where the language model runs</CardTitle><CardDescription>{{ MODES.find((m) => m.id === mode)?.hint }}<template v-if="mode !== active"> · not active until saved</template></CardDescription></CardHeader>
          <CardContent class="space-y-4">
            <div class="flex gap-2" role="radiogroup" aria-label="AI mode">
              <Button v-for="m in MODES" :key="m.id" role="radio" :aria-checked="m.id === mode" :variant="m.id === mode ? 'default' : 'outline'" @click="selectMode(m.id)">{{ m.id }}<Badge v-if="m.id === active" variant="secondary" class="ml-1.5 h-4 px-1.5 text-[10px]">active</Badge></Button>
            </div>
            <div class="max-w-xl space-y-1.5">
              <Label for="endpoint">{{ endpoint.label }}</Label>
              <Input id="endpoint" v-model="endpoints[endpoint.key]" :placeholder="endpoint.placeholder" spellcheck="false" autocomplete="off" @keydown.enter="loadModels" />
            </div>
          </CardContent>
        </Card>

        <div v-else-if="tab === 'models'" class="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader><CardTitle>Model per role</CardTitle><CardDescription>Pick a role, then a model.</CardDescription></CardHeader>
            <CardContent class="space-y-1">
              <button v-for="key in MODEL_KEYS" :key="key" :class="cn('flex w-full items-baseline justify-between gap-3 rounded-md px-3 py-2 text-left text-sm hover:bg-accent', focused === key && 'bg-accent')" @click="focused = key">
                <span class="font-medium">{{ key.replace('_MODEL', '') }}</span><span class="truncate text-muted-foreground">{{ models[key] }}</span>
              </button>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Assign to {{ focused ? focused.replace('_MODEL', '') : '…' }}</CardTitle><CardDescription>{{ available.length }} available</CardDescription></CardHeader>
            <CardContent class="space-y-2">
              <Input v-model="filter" aria-label="Filter models" placeholder="Filter models…" spellcheck="false" />
              <div class="max-h-96 space-y-0.5 overflow-y-auto">
                <button v-for="m in shown" :key="m" :disabled="!focused" class="flex w-full items-center justify-between gap-2 rounded-md px-3 py-1.5 text-left text-sm hover:bg-accent disabled:opacity-50" @click="models[focused] = m">
                  <span class="break-all">{{ m }}</span><Check v-if="focused && models[focused] === m" class="size-4 shrink-0 text-success" />
                </button>
                <p v-if="!shown.length" class="p-2 text-sm text-muted-foreground">No models found. Check the connection.</p>
              </div>
            </CardContent>
          </Card>
        </div>

        <div v-else-if="tab === 'voice'" class="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader><CardTitle>Voice for replies</CardTitle><CardDescription>{{ ttsBackend === 'huggingface' ? 'phonon-40m-en' : 'phonon' }}</CardDescription></CardHeader>
            <CardContent class="space-y-3">
              <div class="flex flex-wrap gap-2" role="radiogroup" aria-label="Voice engine"><Button v-for="[id, label] in BACKENDS" :key="id" size="sm" role="radio" :aria-checked="id === ttsBackend" :variant="id === ttsBackend ? 'default' : 'outline'" @click="pickBackend(id)">{{ label }}</Button></div>
              <p v-if="ttsBackend === 'huggingface'" class="text-xs text-muted-foreground">Needs the GPU service: <code class="rounded bg-muted px-1">docker compose --profile gpu up -d --build tts</code></p>
              <div class="flex max-h-64 flex-wrap gap-1.5 overflow-y-auto" role="radiogroup" aria-label="Voice">
                <Button v-if="!voices.includes(voice)" size="sm" variant="default">{{ voice }}</Button>
                <Button v-for="v in voices" :key="v" size="sm" role="radio" :aria-checked="v === voice" :variant="v === voice ? 'default' : 'outline'" @click="voice = v">{{ v }}</Button>
              </div>
              <Button variant="secondary" size="sm" @click="preview">Preview {{ voice }}</Button>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Wake phrase</CardTitle><CardDescription>Used when Wake is on. Say it, then speak your request.</CardDescription></CardHeader>
            <CardContent class="space-y-3">
              <Input v-model="wakePhrase" aria-label="Wake phrase" placeholder="hey hi" spellcheck="false" @keydown.enter="saveVoice" />
              <div class="flex items-center gap-3"><Button @click="saveVoice">Save voice</Button><span class="text-sm text-muted-foreground" role="status">{{ voiceStatus }}</span></div>
            </CardContent>
          </Card>
        </div>

        <ImagesTab v-else-if="tab === 'images'" />

        <div v-else-if="tab === 'interface'" class="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader><CardTitle>Artifacts</CardTitle><CardDescription>Pages, documents and diagrams a reply writes for you to keep.</CardDescription></CardHeader>
            <CardContent class="space-y-4">
              <div class="flex items-center justify-between gap-4"><div><Label for="auto-artifact">Open artifacts automatically</Label><p class="text-xs text-muted-foreground">Show each one beside the chat as soon as it is written. This browser only.</p></div><Switch id="auto-artifact" v-model="autoOpen" /></div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Notifications</CardTitle><CardDescription>Hear about things while you are in another tab.</CardDescription></CardHeader>
            <CardContent class="space-y-4">
              <div class="flex items-center justify-between gap-4">
                <div><Label for="notify">Notify me</Label><p class="text-xs text-muted-foreground">When a reply finishes or an approval is waiting while this tab is hidden. This browser only.<template v-if="permission === 'denied'"> The browser is blocking them: allow notifications for this site in its settings.</template><template v-else-if="permission === 'unsupported'"> This browser does not support them.</template></p></div>
                <Switch id="notify" :model-value="notificationsOn" :disabled="permission === 'unsupported'" @update:model-value="notificationsOn = !!$event; if ($event) void askOnce()" />
              </div>
            </CardContent>
          </Card>
          <Card class="md:col-span-2">
            <CardHeader><CardTitle>Personal preferences</CardTitle><CardDescription>Standing instructions hi sees with every message: how you like answers, what to always do. Plain text or Markdown.</CardDescription></CardHeader>
            <CardContent class="space-y-3">
              <Textarea v-model="prefs" class="min-h-40" aria-label="Personal preferences" placeholder="- Keep answers short.&#10;- I use metric units." :maxlength="prefsMax" />
              <div class="flex items-center gap-3"><Button :disabled="prefs.trim() === prefsSaved.trim()" @click="savePrefs">Save</Button><span class="text-sm text-muted-foreground" role="status">{{ prefsStatus }}</span><span class="ml-auto text-xs text-muted-foreground">{{ prefs.length.toLocaleString() }} / {{ prefsMax.toLocaleString() }}</span></div>
            </CardContent>
          </Card>
        </div>

        <div v-else class="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader><CardTitle>Heartbeat</CardTitle><CardDescription>Every so often hi looks at what is due and on your screen, and prepares what you will need. It never sends or changes anything without your approval in the Inbox.</CardDescription></CardHeader>
            <CardContent class="space-y-4">
              <div class="flex items-center justify-between"><Label for="hb">Heartbeat</Label><Switch id="hb" :model-value="automation.HEARTBEAT === 'on'" @update:model-value="automation.HEARTBEAT = $event ? 'on' : 'off'" /></div>
              <div class="space-y-1.5"><Label for="every">Check every (minutes)</Label><Input id="every" v-model="everyMinutes" type="number" min="1" inputmode="numeric" /></div>
              <div class="space-y-1.5"><Label for="hours">Active hours (24h, like 08-22)</Label><Input id="hours" v-model="automation.HEARTBEAT_HOURS" placeholder="08-22" spellcheck="false" /></div>
              <div class="flex items-center justify-between"><div><Label for="shots">Watch screenshots</Label><p class="text-xs text-muted-foreground">Needs a local vision model: screenshots can show anything.</p></div><Switch id="shots" :model-value="automation.SCREENSHOT_WATCH === 'on'" @update:model-value="automation.SCREENSHOT_WATCH = $event ? 'on' : 'off'" /></div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Limits</CardTitle><CardDescription>What may run by itself.</CardDescription></CardHeader>
            <CardContent class="space-y-3">
              <div class="space-y-1.5"><Label for="l1">Background runs per hour</Label><Input id="l1" v-model="automation.MAX_BACKGROUND_RUNS_PER_HOUR" type="number" min="0" inputmode="numeric" /></div>
              <div class="space-y-1.5"><Label for="l2">Hosted-model runs per day</Label><Input id="l2" v-model="automation.MAX_HOSTED_CALLS_PER_DAY" type="number" min="0" inputmode="numeric" /></div>
              <div class="space-y-1.5"><Label for="l3">Pop-ups per hour</Label><Input id="l3" v-model="automation.MAX_NOTIFICATIONS_PER_HOUR" type="number" min="0" inputmode="numeric" /></div>
              <div class="space-y-1.5"><Label for="l4">Days an action waits for approval</Label><Input id="l4" v-model="automation.PROPOSAL_TTL_DAYS" type="number" min="1" inputmode="numeric" /></div>
              <div class="flex items-center gap-3"><Button @click="saveAutomation">Save</Button><span class="text-sm text-muted-foreground" role="status">{{ autoStatus }}</span></div>
            </CardContent>
          </Card>
        </div>

        <div v-if="tab === 'connection' || tab === 'models'" class="flex items-center gap-3 border-t pt-4">
          <Button variant="outline" @click="loadModels">Test</Button>
          <Button :disabled="saving" @click="save"><Loader2 v-if="saving" class="size-4 animate-spin" /> Save and use {{ mode }}</Button>
          <span class="text-sm text-muted-foreground" role="status">{{ status }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
