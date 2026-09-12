<!-- Port of /ui-vue.html's .hero — the search bar + quick-action tiles.
     Every tile dispatches something real, not a decorative placeholder:
     - open last project / new note -> a real chat submission
     - run briefing -> re-fetches the real briefing (emitted to parent)
     - quick capture -> a real inline POST /capture, no LLM involved
     - start voice mode -> the browser's real SpeechRecognition API
       (Chromium-based browsers only — Safari doesn't implement it; this
       is disclosed in the UI itself, not silently broken there)
     - trace last run -> fetches the real GET /trace (emitted to parent) -->
<script setup lang="ts">
import { ref } from 'vue'
import { fetchTrace, postCapture } from '../backend'

const props = defineProps<{ isBusy: boolean; briefingLoading: boolean; lastProject: string | null }>()
const emit = defineEmits<{
  submit: [string]
  refreshBriefing: []
  showTrace: [string]
}>()

const text = ref('')
const inputEl = ref<HTMLInputElement>()

const showCapture = ref(false)
const captureText = ref('')
const captureStatus = ref<string | null>(null)

const isListening = ref(false)
const voiceSupported = 'webkitSpeechRecognition' in window || 'SpeechRecognition' in window
let recognition: any = null

function submit() {
  const trimmed = text.value.trim()
  if (!trimmed || props.isBusy) return
  emit('submit', trimmed)
  text.value = ''
}

function openLastProject() {
  const hint = props.lastProject ? ` (${props.lastProject})` : ''
  emit('submit', `open my last project${hint}`)
}

function newNote() {
  text.value = 'create a note: '
  inputEl.value?.focus()
  const len = text.value.length
  requestAnimationFrame(() => inputEl.value?.setSelectionRange(len, len))
}

async function traceLastRun() {
  const content = await fetchTrace()
  emit('showTrace', content ?? 'No orchestrated run has completed yet.')
}

function toggleCapture() {
  showCapture.value = !showCapture.value
  captureStatus.value = null
}

async function submitCapture() {
  const trimmed = captureText.value.trim()
  if (!trimmed) return
  const ok = await postCapture(trimmed)
  captureStatus.value = ok ? 'Captured.' : 'Failed — is the backend running?'
  if (ok) captureText.value = ''
}

function toggleVoice() {
  if (!voiceSupported) return
  if (isListening.value) {
    recognition?.stop()
    return
  }
  const Ctor = (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition
  recognition = new Ctor()
  recognition.continuous = false
  recognition.interimResults = true
  recognition.onstart = () => (isListening.value = true)
  recognition.onend = () => (isListening.value = false)
  recognition.onerror = () => (isListening.value = false)
  recognition.onresult = (event: any) => {
    let transcript = ''
    for (let i = 0; i < event.results.length; i++) transcript += event.results[i][0].transcript
    text.value = transcript
  }
  recognition.start()
}
</script>

<template>
  <div class="hero">
    <div class="prompt">
      <span class="prefix">&gt;</span>
      <input
        ref="inputEl"
        v-model="text"
        type="text"
        placeholder="ask anything, or name a persona to force it"
        :disabled="isBusy"
        @keydown.enter="submit"
      />
      <span v-if="isListening" class="listening">listening…</span>
      <span class="hint">&crarr;</span>
    </div>

    <div v-if="showCapture" class="capture-row">
      <span class="prefix">+</span>
      <input
        v-model="captureText"
        type="text"
        placeholder="jot something down — no reply needed"
        @keydown.enter="submitCapture"
      />
      <button @click="submitCapture">save</button>
      <span v-if="captureStatus" class="capture-status">{{ captureStatus }}</span>
    </div>

    <div class="tiles">
      <div class="tile" @click="openLastProject">&#8618; open last project</div>
      <div class="tile" :class="{ active: briefingLoading }" @click="emit('refreshBriefing')">
        &#8618; {{ briefingLoading ? 'checking…' : 'run briefing' }}
      </div>
      <div class="tile" @click="toggleCapture">&#8618; quick capture</div>
      <div class="tile" :class="{ active: isListening }" :title="voiceSupported ? '' : 'Not supported in this browser'" @click="toggleVoice">
        &#8618; {{ isListening ? 'listening…' : 'start voice mode' }}
      </div>
      <div class="tile" @click="traceLastRun">&#8618; trace last run</div>
      <div class="tile" @click="newNote">&#8618; new note</div>
    </div>
  </div>
</template>

<style scoped>
.hero {
  max-width: 620px;
  margin: 10px auto 28px auto;
  padding: 0 20px;
}
.prompt,
.capture-row {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--bg-row);
  border: 1px solid var(--hairline);
  border-radius: 12px;
  padding: 14px 18px;
}
.capture-row {
  margin-top: 8px;
  padding: 10px 16px;
}
.prefix {
  font-family: var(--mono);
  color: var(--teal);
  font-size: 15px;
}
input {
  flex: 1;
  min-width: 0;
  background: none;
  border: none;
  outline: none;
  color: var(--text);
  font-family: var(--mono);
  font-size: 14.5px;
  caret-color: var(--teal);
}
input::placeholder {
  color: var(--text-faint);
}
input:disabled {
  opacity: 0.6;
}
.hint {
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--text-faint);
  border: 1px solid var(--hairline);
  border-radius: 4px;
  padding: 2px 6px;
}
.listening {
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--amber);
  flex-shrink: 0;
}
.capture-row button {
  font-family: var(--mono);
  font-size: 11px;
  background: none;
  border: 1px solid var(--hairline);
  border-radius: 5px;
  color: var(--teal);
  padding: 4px 9px;
  cursor: pointer;
  flex-shrink: 0;
}
.capture-status {
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--text-faint);
  flex-shrink: 0;
}

.tiles {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-top: 12px;
}
.tile {
  background: var(--bg-row);
  border: 1px solid var(--hairline);
  border-radius: 8px;
  padding: 10px 12px;
  cursor: pointer;
  font-family: var(--mono);
  font-size: 11.5px;
  color: var(--text-dim);
  transition:
    border-color 0.15s ease,
    color 0.15s ease;
}
.tile:hover {
  border-color: var(--teal-dim);
  color: var(--text);
}
.tile.active {
  border-color: var(--amber);
  color: var(--amber);
}

@media (max-width: 480px) {
  .tiles {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
