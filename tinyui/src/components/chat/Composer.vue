<script setup lang="ts">
import { ArrowUp, AudioLines, Ear, FileUp, Loader2, MessagesSquare, Mic, Paperclip, Sparkles, Square, Volume2, Wand2, Workflow, X } from '@lucide/vue'
import { computed, ref, type Component } from 'vue'
import type { Attachment } from '@/attachments'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { useVoice } from '@/composables/useVoice'
import { cn } from '@/lib/utils'

type Voice = ReturnType<typeof useVoice>

const PERSONAS: [string, string][] = [
  ['auto', 'Auto'], ['term', 'Shell, files, code'], ['butler', 'Mac and to-dos'], ['docs', 'Your notes'], ['web', 'Web lookups'],
]

const props = defineProps<{
  modelValue: string
  persona: string
  visualize: boolean
  busy: boolean
  voice: Voice
  wakePhrase: string
  attachments: Attachment[]
}>()
const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:persona': [value: string]
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
const canSend = computed(() => props.modelValue.trim().length > 0 || props.attachments.some((a) => a.status === 'ready'))

function onKey(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    if (!props.busy) emit('submit')
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

    <div class="flex flex-wrap items-center gap-1 px-2 pb-2">
      <input ref="picker" type="file" multiple class="sr-only" tabindex="-1" aria-hidden="true" @change="pick" />
      <Tooltip><TooltipTrigger as-child><Button variant="ghost" size="icon" class="size-8" aria-label="Attach files" @click="picker?.click()"><FileUp class="size-4" /></Button></TooltipTrigger><TooltipContent>Attach files as context</TooltipContent></Tooltip>

      <Select :model-value="persona" @update:model-value="emit('update:persona', String($event))">
        <Tooltip><TooltipTrigger as-child>
          <SelectTrigger class="h-8 w-auto gap-1.5 border-0 bg-transparent px-2 text-xs shadow-none" aria-label="Agent"><Sparkles class="size-3.5" /><SelectValue /></SelectTrigger>
        </TooltipTrigger><TooltipContent>Which agent answers. Auto picks for you.</TooltipContent></Tooltip>
        <SelectContent><SelectItem v-for="[id, label] in PERSONAS" :key="id" :value="id">{{ label }}</SelectItem></SelectContent>
      </Select>

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
