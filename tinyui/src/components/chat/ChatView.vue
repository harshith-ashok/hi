<script setup lang="ts">
import { ArrowDown, BarChart3, FolderGit2, Lightbulb, Network, Pencil, Search, SlidersHorizontal, Workflow, X } from '@lucide/vue'
import { useResizeObserver } from '@vueuse/core'
import { computed, nextTick, onMounted, onUnmounted, ref, watch, type Component } from 'vue'
import { toast } from 'vue-sonner'
import { drawVisual, fetchPending, fileAttachment, patchJson, resolvePending, type Pending } from '@/backend'
import { useAttachments, type Attachment } from '@/attachments'
import ApprovalBar from '@/components/chat/ApprovalBar.vue'
import Composer from '@/components/chat/Composer.vue'
import PreviewPane from '@/components/chat/PreviewPane.vue'
import TurnView from '@/components/chat/TurnView.vue'
import VoiceOverlay from '@/components/chat/VoiceOverlay.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SidebarTrigger } from '@/components/ui/sidebar'
import { answerOf, toolsOf, useChat, type Turn } from '@/composables/useChat'
import { useSessions } from '@/composables/useSessions'
import { useStatus } from '@/composables/useStatus'
import { useVoice } from '@/composables/useVoice'
import { getWakePhrase } from '@/voice'

const props = defineProps<{ active: boolean }>()

const SUGGESTIONS: { icon: Component; title: string; text: string }[] = [
  { icon: Network, title: 'Explain with a diagram', text: 'Explain how a request travels through hi, from tinyui to the answer' },
  { icon: Search, title: 'Search my notes', text: 'What did I note about binary search trees?' },
  { icon: BarChart3, title: 'Plot something', text: 'Plot a linear regression on some made-up data' },
  { icon: FolderGit2, title: 'Check a repo', text: 'What changed in the hi repo since yesterday?' },
  { icon: SlidersHorizontal, title: 'Control my Mac', text: 'Turn off Bluetooth' },
  { icon: Lightbulb, title: 'Plan my day', text: 'What should I work on next?' },
]

const sessions = useSessions()
const status = useStatus()
const attached = useAttachments()
const input = ref('')
const tier = ref(['haiku', 'sonnet', 'opus'].includes(localStorage.getItem('tier') ?? '') ? localStorage.getItem('tier')! : 'auto')
localStorage.removeItem('persona') // an older version chose an agent here; what you choose now is the model size
const visualize = ref(localStorage.getItem('visualize') === '1')
watch(tier, (v) => localStorage.setItem('tier', v))
watch(visualize, (v) => localStorage.setItem('visualize', v ? '1' : '0'))
const composer = ref<InstanceType<typeof Composer> | null>(null)

const notify = (text: string, kind: 'info' | 'error' = 'info') => (kind === 'error' ? toast.error(text) : toast(text))

const chat = useChat({
  onSpoken: (text) => void voice.reply(text),
  onDone: () => {
    void sessions.refresh()
    setTimeout(() => void sessions.refresh(), 6000) // the model-written title arrives a few seconds later
  },
})
const lastTurn = computed(() => chat.turns.value[chat.turns.value.length - 1])
const acting = computed(() => !!lastTurn.value && toolsOf(lastTurn.value).some((t) => t.result === undefined) && chat.busy.value)
const voice = useVoice({
  submit: (text) => void submit(text),
  setInput: (text) => (input.value = text),
  focusInput: () => composer.value?.focus(),
  notify, busy: chat.busy, acting, online: status.online,
  lastPersona: () => (lastTurn.value?.route?.persona === 'butler' ? 'butler' : 'term'),
})

// --- sessions ------------------------------------------------------------------------------------------------------
let loadedId = sessions.currentId.value
const title = computed(() => sessions.titles[sessions.currentId.value] ?? (chat.turns.value.length ? 'Chat' : 'New chat'))
const editing = ref(false)
const draft = ref('')

async function switchTo(id: string) {
  queued.value = ''
  if (chat.busy.value) {
    chat.cancel()
    toast('Stopped the reply that was running.')
  }
  loadedId = id
  if (!id) return chat.clear()
  const turns = await sessions.open(id)
  if (turns === null) {
    loadedId = ''
    toast.error('That chat no longer exists.')
    return chat.clear()
  }
  chat.load(turns)
  stick.value = true
  toEnd()
}
watch(sessions.currentId, (id) => { if (id !== loadedId) void switchTo(id) })

async function commitTitle() {
  editing.value = false
  const id = sessions.currentId.value
  if (id && draft.value.trim() && draft.value.trim() !== title.value) await sessions.rename(id, draft.value.trim())
}

// --- sending -------------------------------------------------------------------------------------------------------
const history: string[] = []
let historyPos = 0
let suggested: string | null = null
const queued = ref('') // a message typed while a reply was streaming; it goes out when that reply ends

async function submit(override?: string, branch?: { parent: string }) {
  const files = attached.ready()
  const text = (override ?? input.value).trim() || (files.length ? 'Look at the attached files.' : '')
  if (!text) return
  if (attached.reading()) return notify('Still reading the attached files…')
  if (chat.busy.value) {
    if (override !== undefined) return notify('Still replying. Press Esc or Stop to cancel.')
    queued.value = text // typing ahead: one message waits, a newer one replaces it
    input.value = ''
    return
  }
  input.value = ''
  history.push(text)
  historyPos = history.length
  let session = sessions.currentId.value
  if (!session) {
    const made = await sessions.create()
    if (!made) return notify('Could not start a chat: is the backend running?', 'error')
    session = made.id
    loadedId = session // so selecting it below does not reload an empty chat over this one
    sessions.select(session)
    sessions.preview(session, text) // the sidebar shows the first words now, not "New chat" until the answer ends
  }
  const message = suggested && /^(y|yes|yeah|ok|okay|sure)$/i.test(text) ? suggested : text
  suggested = null
  const names = files.map((f) => f.name)
  const ids = files.map((f) => f.id!)
  attached.clear()
  stick.value = true
  await chat.ask(message, { tier: tier.value, attachments: ids, names, session, visualize: visualize.value, parent: branch?.parent })
  if (branch) await reload() // the other attempts at this point are listed with the saved chat
}

/** Draw the open chat again from what the backend saved (so the attempt switchers are right). */
async function reload() {
  const id = sessions.currentId.value
  const turns = id ? await sessions.open(id) : null
  if (turns) chat.load(turns)
}

/** Edit a message, or ask for another answer: send it again as a new attempt after the turn before it. */
async function again(index: number, text: string) {
  if (chat.busy.value) return notify('Still replying. Press Esc or Stop to cancel.')
  const target = chat.turns.value[index]
  const draft = input.value
  chat.truncate(index)
  await submit(text, { parent: target.parent ?? '' })
  if (chat.turns.value.length <= index) await reload() // it never started: put the turns back
  input.value = draft // submit clears the box; what you were typing is still yours
}

async function switchVersion(id: string) {
  const session = sessions.currentId.value
  if (!session || chat.busy.value) return
  if (await patchJson(`/sessions/${session}`, { head: id })) await reload()
  else notify('Could not switch to that attempt.', 'error')
}

function recall(step: number) {
  if (!history.length) return
  historyPos = Math.max(0, Math.min(history.length, historyPos + step))
  input.value = history[historyPos] ?? ''
}

async function fileIt(a: Attachment) {
  if (!a.id) return
  const out = await fileAttachment(a.id)
  notify(out ? `Filing ${a.name}. It will appear in the Inbox within a minute.` : `Could not file ${a.name}.`, out ? 'info' : 'error')
}

const answeredForm = (i: number) => i < chat.turns.value.length - 1

// --- diagrams ------------------------------------------------------------------------------------------------------
async function draw(turn: Turn, error = '') {
  const before = turn.visual
  turn.visual = { state: 'pending', mermaid: '', t0: Date.now() }
  const out = await drawVisual(turn.ask, answerOf(turn), error)
  if (out?.mermaid) turn.visual = { state: 'ready', mermaid: out.mermaid, t0: before.t0 ?? turn.visual.t0, t1: Date.now() }
  else {
    turn.visual = error ? before : { state: 'none', mermaid: '' }
    notify(out ? 'Nothing here that a diagram would help with.' : 'Could not draw a diagram: is the backend running?', out ? 'info' : 'error')
  }
}

// --- approvals: a confirmation arrives on the backend queue while a turn is streaming ----------------------------
const pending = ref<Pending[]>([])
watch(chat.busy, (isBusy) => {
  if (isBusy) {
    const poll = window.setInterval(async () => {
      pending.value = await fetchPending()
      if (!chat.busy.value) clearInterval(poll)
    }, 800)
  } else pending.value = []
})
async function answerPending(approve: boolean) {
  const [first] = pending.value
  if (!first) return
  pending.value = pending.value.slice(1)
  await resolvePending(first.id, approve)
  notify(`${approve ? 'Allowed' : 'Denied'}: ${first.description}`)
}

// --- keys, drag and drop -------------------------------------------------------------------------------------------
function onKey(e: KeyboardEvent) {
  if (!props.active) return
  if (e.key === 'Escape') {
    if (chat.busy.value) chat.cancel()
    voice.stopAll()
  } else if (pending.value.length && !input.value && (e.key === 'y' || e.key === 'n') && !(e.target instanceof HTMLInputElement)) {
    e.preventDefault()
    void answerPending(e.key === 'y')
  }
}
const dragging = ref(false)
let depth = 0
const hasFiles = (e: DragEvent) => !!e.dataTransfer?.types.includes('Files')
const onEnter = (e: DragEvent) => { if (props.active && hasFiles(e)) { depth++; dragging.value = true } }
const onOver = (e: DragEvent) => { if (props.active && hasFiles(e)) e.preventDefault() } // required, or the drop is refused
const onLeave = () => { if (--depth <= 0) { depth = 0; dragging.value = false } }
function onDrop(e: DragEvent) {
  depth = 0
  dragging.value = false
  if (!props.active || !e.dataTransfer || !hasFiles(e)) return
  e.preventDefault()
  attached.addFromTransfer(e.dataTransfer) // adds context only; nothing is sent
}
const onPaste = (e: ClipboardEvent) => { if (props.active && attached.addFromPaste(e.clipboardData)) e.preventDefault() }

// --- scrolling: follow the reply while it streams, unless you scrolled up to read -------------------------------
const scroller = ref<HTMLElement>()
const content = ref<HTMLElement>()
const stick = ref(true)
const onScroll = () => {
  const el = scroller.value
  if (el) stick.value = el.scrollHeight - el.scrollTop - el.clientHeight < 140
}
const toEnd = (smooth = false) => nextTick(() => scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: smooth ? 'smooth' : 'auto' }))
useResizeObserver(content, () => stick.value && toEnd()) // diagrams and images change height after they arrive

async function copyLast() {
  const turn = lastTurn.value
  const text = turn ? answerOf(turn) : ''
  if (!text) return notify('There is no reply to copy yet.')
  await navigator.clipboard?.writeText(text)
  notify('Copied the last reply.')
}

onMounted(async () => {
  window.addEventListener('hi:copy-last', copyLast)
  window.addEventListener('keydown', onKey)
  window.addEventListener('dragenter', onEnter)
  window.addEventListener('dragover', onOver)
  window.addEventListener('dragleave', onLeave)
  window.addEventListener('drop', onDrop)
  window.addEventListener('paste', onPaste)
  await sessions.refresh()
  if (sessions.currentId.value) {
    loadedId = ''
    await switchTo(sessions.currentId.value)
  }
  composer.value?.focus()
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('dragenter', onEnter)
  window.removeEventListener('dragover', onOver)
  window.removeEventListener('dragleave', onLeave)
  window.removeEventListener('hi:copy-last', copyLast)
  window.removeEventListener('drop', onDrop)
  window.removeEventListener('paste', onPaste)
})
// When a reply ends, send what was typed meanwhile. If the reply was stopped, give the text back instead.
watch(chat.busy, (busy) => {
  if (busy || !queued.value) return
  const text = queued.value
  queued.value = ''
  if (lastTurn.value?.status === 'cancelled') input.value = input.value || text
  else void submit(text)
})
watch(() => props.active, (on) => on && nextTick(() => composer.value?.focus()))
</script>

<template>
  <div class="flex h-full min-h-0">
  <div class="flex h-full min-h-0 min-w-0 flex-1 flex-col">
    <header class="flex h-14 shrink-0 items-center gap-2 border-b px-3">
      <SidebarTrigger />
      <div class="min-w-0 flex-1">
        <Input v-if="editing" v-model="draft" class="h-8 max-w-md" aria-label="Chat title" autofocus @keydown.enter.prevent="commitTitle" @keydown.esc.prevent="editing = false" @blur="commitTitle" />
        <button v-else class="group flex max-w-full items-center gap-2 text-left" :disabled="!sessions.currentId.value" title="Rename" @click="draft = title; editing = true">
          <h1 class="truncate text-sm font-semibold">{{ title }}</h1>
          <Pencil v-if="sessions.currentId.value" class="size-3 shrink-0 text-muted-foreground opacity-0 group-hover:opacity-100" />
        </button>
        <p v-if="lastTurn?.route" class="truncate text-xs text-muted-foreground">{{ lastTurn.route.persona }} · {{ lastTurn.route.tier }}</p>
      </div>
      <span v-if="!['ready', 'thinking', 'acting'].includes(voice.state.value)" class="rounded-full border px-2.5 py-0.5 text-xs text-muted-foreground" role="status">{{ voice.state.value }}</span>
    </header>

    <div ref="scroller" class="relative min-h-0 flex-1 overflow-y-auto" @scroll.passive="onScroll">
      <div ref="content" class="mx-auto w-full max-w-[46rem] space-y-8 px-4 py-6">
        <div v-if="!chat.turns.value.length" class="flex flex-col items-center gap-6 py-10 text-center">
          <div class="flex size-12 items-center justify-center rounded-2xl bg-primary text-lg font-bold text-primary-foreground">hi</div>
          <div>
            <h2 class="text-2xl font-semibold tracking-tight">What can I do for you?</h2>
            <p class="mt-1 text-sm text-muted-foreground">Ask anything. Turn on <span class="inline-flex items-center gap-1 font-medium text-foreground"><Workflow class="size-3.5" /> Visualize</span> to see every answer as a diagram.</p>
          </div>
          <div class="grid w-full gap-2 sm:grid-cols-2">
            <button v-for="s in SUGGESTIONS" :key="s.title" class="flex items-start gap-3 rounded-xl border bg-card p-3 text-left transition-colors hover:bg-accent" @click="submit(s.text)">
              <component :is="s.icon" class="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              <span><span class="block text-sm font-medium">{{ s.title }}</span><span class="block text-xs text-muted-foreground">{{ s.text }}</span></span>
            </button>
          </div>
        </div>
        <TurnView
          v-for="(turn, i) in chat.turns.value"
          :key="turn.id"
          :turn="turn"
          :is-last="i === chat.turns.value.length - 1"
          :busy="chat.busy.value"
          :answered="answeredForm(i)"
          @answer="submit($event)"
          @regenerate="again(i, turn.ask)"
          @edit="again(i, $event)"
          @switch-version="switchVersion"
          @draw="draw(turn)"
          @redraw="draw(turn, $event)"
        />
      </div>
      <Button v-if="!stick && chat.turns.value.length" variant="secondary" size="sm" class="sticky bottom-3 left-1/2 mx-auto flex -translate-x-1/2 gap-1.5 rounded-full shadow-md" @click="stick = true; toEnd(true)"><ArrowDown class="size-3.5" /> Latest</Button>
    </div>

    <div class="shrink-0 border-t bg-background/80 px-4 pb-4 pt-3 backdrop-blur">
      <div class="mx-auto w-full max-w-[46rem] space-y-2">
        <ApprovalBar :pending="pending" @answer="answerPending" />
        <div v-if="queued" class="flex items-center gap-2 rounded-lg border bg-muted/50 px-3 py-1.5 text-xs text-muted-foreground" role="status">
          <span class="shrink-0">Sends when the reply ends:</span><span class="truncate text-foreground">{{ queued }}</span>
          <button type="button" class="ml-auto rounded p-0.5 hover:bg-background" aria-label="Remove the queued message" @click="queued = ''"><X class="size-3.5" /></button>
        </div>
        <Composer
          ref="composer"
          v-model="input"
          v-model:tier="tier"
          :models="status.models.value"
          v-model:visualize="visualize"
          :busy="chat.busy.value"
          :voice="voice"
          :wake-phrase="getWakePhrase()"
          :attachments="attached.items.value"
          :history="history"
          :context-window="chat.contextWindow.value"
          @submit="submit()"
          @cancel="chat.cancel"
          @recall="recall"
          @attach="attached.addFiles($event)"
          @remove-attachment="attached.remove($event)"
          @file-it="fileIt"
        />
        <p class="text-center text-[11px] text-muted-foreground">Esc stops a reply · ↑ recalls your last message · Tab accepts a suggestion · drop files anywhere to add context</p>
      </div>
    </div>

    <div v-if="dragging" class="pointer-events-none fixed inset-0 z-40 flex flex-col items-center justify-center gap-1 bg-background/80 backdrop-blur-sm" aria-hidden="true">
      <div class="rounded-2xl border-2 border-dashed border-primary px-12 py-10 text-center"><p class="text-lg font-medium">Drop to add as context</p><p class="text-sm text-muted-foreground">Files, folders, PDFs, images, audio, zips. Nothing is sent until you send.</p></div>
    </div>

    <VoiceOverlay v-if="voice.voiceMode.value" :state="voice.state.value" :caption="voice.caption.value" :pending="pending" @leave="voice.toggleVoiceMode" @answer="answerPending" />
  </div>
  <PreviewPane />
  </div>
</template>
