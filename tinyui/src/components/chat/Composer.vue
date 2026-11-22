<script setup lang="ts">
import { ArrowUp, AudioLines, BrainCircuit, ChevronDown, Ear, FileUp, Gauge, Loader2, MessagesSquare, Mic, Paperclip, Sparkles, Square, TextCursorInput, Volume2, Wand2, Workflow, X, Zap } from '@lucide/vue'
import { computed, nextTick, onMounted, onUnmounted, ref, watch, type Component } from 'vue'
import { getJson, postJson } from '@/backend'
import type { Attachment } from '@/attachments'
import type { ContextWindow } from '@/composables/useChat'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { useVoice } from '@/composables/useVoice'
import { cn } from '@/lib/utils'

type Voice = ReturnType<typeof useVoice>

// What you choose is how much model to spend. hi still decides what kind of help a message needs.
const TIERS: { id: string; label: string; hint: string; icon: Component }[] = [
  { id: 'auto', label: 'Auto', hint: 'hi picks the size for each message', icon: Sparkles },
  { id: 'haiku', label: 'Fast', hint: 'Quick answers and lookups', icon: Zap },
  { id: 'sonnet', label: 'Balanced', hint: 'Most everyday work', icon: Gauge },
  { id: 'opus', label: 'Deep', hint: 'Hard problems. Slower.', icon: BrainCircuit },
]

const props = defineProps<{
  modelValue: string
  tier: string
  models: Record<string, string>
  visualize: boolean
  busy: boolean
  voice: Voice
  wakePhrase: string
  attachments: Attachment[]
  history?: string[]
  contextWindow?: ContextWindow | null
}>()
const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:tier': [value: string]
  'update:visualize': [value: boolean]
  submit: []
  cancel: []
  recall: [step: number]
  attach: [files: FileList]
  removeAttachment: [key: number]
  fileIt: [attachment: Attachment]
}>()

const box = ref<InstanceType<typeof Textarea> | null>(null)
const picker = ref<HTMLInputElement>()
// How full the model's context window is: shown from half full, or as soon as earlier messages have been left out.
const RING = 2 * Math.PI * 7
const fill = computed(() => Math.min(1, (props.contextWindow?.used ?? 0) / (props.contextWindow?.limit || 1)))
const showRing = computed(() => !!props.contextWindow && (fill.value >= 0.5 || props.contextWindow.dropped_turns > 0))
const ringHint = computed(() => {
  const c = props.contextWindow
  if (!c) return ''
  const left = c.dropped_turns ? ` ${c.dropped_turns} earlier ${c.dropped_turns === 1 ? 'message is' : 'messages are'} not in context.` : ''
  return `Context: about ${c.used.toLocaleString()} of ${c.limit.toLocaleString()} tokens.${left}`
})
const current = computed(() => TIERS.find((t) => t.id === props.tier) ?? TIERS[0])
const canSend = computed(() => props.modelValue.trim().length > 0 || props.attachments.some((a) => a.status === 'ready'))

// "/" at the start of the box lists the vault skills; Tab or Enter completes the name.
interface SkillCommand { name: string; description: string }
const skills = ref<SkillCommand[]>([])
const active = ref(0)
const dismissed = ref(false)
const list = ref<HTMLUListElement | null>(null)
onMounted(async () => { skills.value = (await getJson<SkillCommand[]>('/skills')) ?? [] })
const matches = computed(() => {
  const m = /^\/([\w-]*)$/.exec(props.modelValue)
  if (!m || dismissed.value) return []
  return skills.value.filter((s) => s.name.toLowerCase().startsWith(m[1].toLowerCase()))
})
watch(() => props.modelValue, () => { active.value = 0; dismissed.value = false })
watch(active, async () => {
  await nextTick()
  list.value?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' })
})
// --- suggestions: grey text after the cursor, Tab accepts -----------------------------------------------------------
// Instant: the most recent earlier message that starts with what is typed. Smarter: the model's guess, after a pause.
const SUGGEST_MIN = 6
const SUGGEST_DELAY_MS = 450
const suggestOn = ref(localStorage.getItem('suggest') !== '0')
watch(suggestOn, (v) => { localStorage.setItem('suggest', v ? '1' : '0'); if (!v) suggestion.value = '' })
const suggestion = ref('')
let suggestTimer: ReturnType<typeof setTimeout> | undefined
let suggestSeq = 0

const fromHistory = computed(() => {
  const typed = props.modelValue
  if (typed.length < 3 || typed.includes('\n') || typed.startsWith('/')) return ''
  const hit = [...(props.history ?? [])].reverse().find((m) => m.length > typed.length && m.toLowerCase().startsWith(typed.toLowerCase()))
  return hit ? hit.slice(typed.length) : ''
})
const ghost = computed(() => (matches.value.length || !suggestOn.value ? '' : fromHistory.value || suggestion.value))

watch(() => props.modelValue, (typed, before) => {
  clearTimeout(suggestTimer)
  suggestSeq++
  const added = typed.slice(before.length)
  if (suggestion.value && typed.startsWith(before) && suggestion.value.startsWith(added)) suggestion.value = suggestion.value.slice(added.length) // typed what was suggested
  else suggestion.value = ''
  if (suggestion.value || fromHistory.value || !suggestOn.value || props.busy) return
  if (typed.trim().length < SUGGEST_MIN || typed.includes('\n') || typed.startsWith('/')) return
  const mine = suggestSeq
  suggestTimer = setTimeout(async () => {
    const res = await postJson<{ suggestion: string }>('/suggest', { text: typed, recent: (props.history ?? []).slice(-5) })
    if (mine === suggestSeq && res?.suggestion) suggestion.value = res.suggestion
  }, SUGGEST_DELAY_MS)
})
onUnmounted(() => clearTimeout(suggestTimer))

function complete(skill: SkillCommand) {
  emit('update:modelValue', `/${skill.name} `)
}

function onKey(e: KeyboardEvent) {
  if (matches.value.length) {
    const n = matches.value.length
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      active.value = (active.value + (e.key === 'ArrowDown' ? 1 : n - 1)) % n
      return
    }
    if ((e.key === 'Tab' || e.key === 'Enter') && !e.shiftKey && !e.isComposing) {
      e.preventDefault()
      complete(matches.value[active.value])
      return
    }
    if (e.key === 'Escape') { dismissed.value = true; return }
  }
  if (e.key === 'Tab' && !e.shiftKey && ghost.value && !e.isComposing) {
    e.preventDefault()
    emit('update:modelValue', props.modelValue + ghost.value)
    suggestion.value = ''
    return
  }
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    emit('submit') // while a reply is streaming the message is queued (ChatView)
  } else if ((e.key === 'ArrowUp' || e.key === 'ArrowDown') && !props.modelValue.includes('\n')) {
    e.preventDefault()
    emit('recall', e.key === 'ArrowUp' ? -1 : 1)
  }
}

function pick(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files?.length) emit('attach', input.files)
  input.value = ''
}

interface Toggle { key: string; label: string; hint: string; icon: Component; on: boolean; busy?: boolean; click: () => void }
const toggles = computed<Toggle[]>(() => [
  { key: 'suggest', label: 'Suggest', hint: 'Grey suggestions as you type. Tab accepts.', icon: TextCursorInput, on: suggestOn.value, click: () => (suggestOn.value = !suggestOn.value) },
  { key: 'dictate', label: 'Dictate', hint: 'Speak into the box. Does not send.', icon: Mic, on: props.voice.mic.value !== 'idle', busy: ['transcribing', 'structuring'].includes(props.voice.mic.value), click: () => void props.voice.listen(false) },
  { key: 'tidy', label: 'Tidy', hint: 'Clean up and structure what you say before sending', icon: Wand2, on: props.voice.rambler.value, click: () => (props.voice.rambler.value = !props.voice.rambler.value) },
  { key: 'speak', label: 'Speak', hint: 'Read replies aloud, even for typed requests', icon: Volume2, on: props.voice.speakReplies.value, click: () => (props.voice.speakReplies.value = !props.voice.speakReplies.value) },
  { key: 'wake', label: 'Wake', hint: `Always listening for “${props.wakePhrase}”`, icon: Ear, on: props.voice.wake.value, click: props.voice.toggleWake },
  { key: 'converse', label: 'Converse', hint: 'Speak the reply, then listen again', icon: MessagesSquare, on: props.voice.talk.value, click: props.voice.toggleTalk },
])
defineExpose({ focus: () => (box.value?.$el as HTMLTextAreaElement | undefined)?.focus() })
</script>

<template>
  <div class="rounded-2xl border bg-card shadow-sm focus-within:ring-2 focus-within:ring-ring/40">
    <ul v-if="attachments.length" class="flex flex-wrap gap-1.5 px-3 pt-3" aria-label="Attached context">
      <li v-for="a in attachments" :key="a.key">
        <Badge variant="secondary" :class="cn('h-6 gap-1.5 pr-1 font-normal', a.status === 'failed' && 'border-destructive text-destructive')" :title="a.detail">
          <Loader2 v-if="a.status === 'reading'" class="size-3 animate-spin" /><Paperclip v-else class="size-3" />
          <span class="max-w-40 truncate">{{ a.name }}</span>
          <button v-if="a.status === 'ready' && a.id" type="button" class="rounded px-1 text-[10px] underline hover:text-foreground" title="File it as a note and add its tasks" @click="emit('fileIt', a)">file it</button>
          <button type="button" class="rounded p-0.5 hover:bg-background" :aria-label="`Remove ${a.name}`" @click="emit('removeAttachment', a.key)"><X class="size-3" /></button>
        </Badge>
      </li>
    </ul>

    <ul v-if="matches.length" ref="list" class="mx-2 mt-2 max-h-56 overflow-y-auto rounded-lg border bg-popover text-sm shadow-sm" role="listbox" aria-label="Skills">
      <li v-for="(skill, i) in matches" :key="skill.name" role="option" :aria-selected="i === active" :class="cn('flex cursor-pointer items-baseline gap-2 px-3 py-1.5', i === active && 'bg-accent text-accent-foreground')" @mousedown.prevent="complete(skill)" @mousemove="active = i">
        <span class="font-mono text-xs">/{{ skill.name }}</span>
        <span class="truncate text-xs text-muted-foreground">{{ skill.description }}</span>
      </li>
    </ul>

    <div class="relative">
      <div v-if="ghost" class="pointer-events-none absolute inset-0 overflow-hidden whitespace-pre-wrap break-words px-4 py-3 text-sm" aria-hidden="true"><span class="invisible">{{ modelValue }}</span><span class="text-muted-foreground/60">{{ ghost }}</span><kbd class="ml-2 rounded border px-1 align-middle text-[10px] text-muted-foreground/70">Tab</kbd></div>
      <Textarea
        ref="box"
        :model-value="modelValue"
        class="max-h-52 min-h-[52px] resize-none border-0 bg-transparent px-4 py-3 text-sm shadow-none focus-visible:ring-0"
        :placeholder="voice.mic.value === 'listening' ? 'Listening… speak now' : voice.wake.value ? `Say “${wakePhrase}”, or type here` : 'Message hi…  (Enter to send, Shift+Enter for a new line)'"
        aria-label="Message"
        rows="1"
        spellcheck="false"
        autocomplete="off"
        @update:model-value="emit('update:modelValue', String($event))"
        @keydown="onKey"
      />
    </div>

    <div class="flex flex-wrap items-center gap-1 px-2 pb-2">
      <input ref="picker" type="file" multiple class="sr-only" tabindex="-1" aria-hidden="true" @change="pick" />
      <Tooltip><TooltipTrigger as-child><Button variant="ghost" size="icon" class="size-8" aria-label="Attach files" @click="picker?.click()"><FileUp class="size-4" /></Button></TooltipTrigger><TooltipContent>Attach files as context</TooltipContent></Tooltip>

      <DropdownMenu>
        <DropdownMenuTrigger as-child>
          <Button variant="ghost" size="sm" class="h-8 gap-1.5 px-2 text-xs" aria-label="Model size" :title="`Model size: ${current.label}. ${current.hint}`">
            <component :is="current.icon" class="size-3.5" />{{ current.label }}<ChevronDown class="size-3 opacity-60" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" side="top" class="w-72">
          <DropdownMenuLabel class="text-xs font-normal text-muted-foreground">How much model to use</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuRadioGroup :model-value="tier" @update:model-value="emit('update:tier', String($event))">
            <DropdownMenuRadioItem v-for="t in TIERS" :key="t.id" :value="t.id" class="items-start gap-2 py-2">
              <component :is="t.icon" class="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              <span class="min-w-0">
                <span class="block text-sm font-medium">{{ t.label }}</span>
                <span class="block text-xs text-muted-foreground">{{ t.hint }}</span>
                <span v-if="models[t.id]" class="mt-0.5 block truncate font-mono text-[11px] text-muted-foreground">{{ models[t.id] }}</span>
              </span>
            </DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>

      <Tooltip v-if="showRing"><TooltipTrigger as-child>
        <span class="flex size-8 items-center justify-center" role="img" :aria-label="ringHint">
          <svg viewBox="0 0 20 20" class="size-5 -rotate-90"><circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" class="text-muted" stroke-width="2.5" /><circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" :class="fill > 0.9 ? 'text-destructive' : 'text-primary'" :stroke-dasharray="RING" :stroke-dashoffset="RING * (1 - fill)" /></svg>
        </span>
      </TooltipTrigger><TooltipContent>{{ ringHint }}</TooltipContent></Tooltip>

      <Tooltip><TooltipTrigger as-child>
        <Button variant="ghost" size="sm" :aria-pressed="visualize" :class="cn('h-8 gap-1.5 px-2 text-xs', visualize && 'bg-accent text-accent-foreground')" @click="emit('update:visualize', !visualize)"><Workflow class="size-4" /> Visualize</Button>
      </TooltipTrigger><TooltipContent>Always draw a diagram of each answer</TooltipContent></Tooltip>

      <span class="mx-1 hidden h-5 w-px bg-border sm:block" aria-hidden="true" />
      <Tooltip v-for="t in toggles" :key="t.key"><TooltipTrigger as-child>
        <Button variant="ghost" size="icon" :aria-label="t.label" :aria-pressed="t.on" :disabled="t.busy" :class="cn('size-8', t.on && 'bg-accent text-accent-foreground')" @click="t.click">
          <Loader2 v-if="t.busy" class="size-4 animate-spin" /><component :is="t.icon" v-else class="size-4" />
        </Button>
      </TooltipTrigger><TooltipContent>{{ t.label }}: {{ t.hint }}</TooltipContent></Tooltip>

      <span class="grow" />
      <Tooltip><TooltipTrigger as-child><Button variant="ghost" size="icon" class="size-8" aria-label="Voice mode" @click="voice.toggleVoiceMode"><AudioLines class="size-4" /></Button></TooltipTrigger><TooltipContent>Full-screen voice mode</TooltipContent></Tooltip>
      <Button v-if="busy" size="icon" class="size-8 rounded-full" aria-label="Stop" @click="emit('cancel')"><Square class="size-3.5 fill-current" /></Button>
      <Button v-else size="icon" class="size-8 rounded-full" aria-label="Send" :disabled="!canSend" @click="emit('submit')"><ArrowUp class="size-4" /></Button>
    </div>
  </div>
</template>
