<script setup lang="ts">
// One exchange: what you asked, then everything the assistant did and said, drawn as it arrives.
import { AlertCircle, Check, Copy, Paperclip, RefreshCw, Workflow } from '@lucide/vue'
import { computed, ref } from 'vue'
import AskForm from '@/components/chat/AskForm.vue'
import RunTimeline from '@/components/chat/RunTimeline.vue'
import ThinkingBlock from '@/components/chat/ThinkingBlock.vue'
import ToolCall from '@/components/chat/ToolCall.vue'
import MarkdownContent from '@/components/content/MarkdownContent.vue'
import MermaidDiagram from '@/components/content/MermaidDiagram.vue'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { answerOf, type Turn } from '@/composables/useChat'
import { questionsOf } from '@/lib/run'

const props = defineProps<{ turn: Turn; isLast: boolean; busy: boolean; answered: boolean }>()
const emit = defineEmits<{ answer: [text: string]; regenerate: []; draw: []; redraw: [error: string] }>()

const running = computed(() => props.turn.status === 'running')
const answer = computed(() => answerOf(props.turn))
const hasText = computed(() => props.turn.blocks.some((b) => b.kind === 'text'))
const lastBlock = computed(() => props.turn.blocks[props.turn.blocks.length - 1])
const copied = ref(false)

async function copy() {
  await navigator.clipboard?.writeText(answer.value)
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}
</script>

<template>
  <article class="space-y-4" :aria-label="`Exchange: ${turn.ask.slice(0, 40)}`">
    <div class="flex justify-end">
      <div class="max-w-[85%] rounded-2xl rounded-br-md bg-secondary px-4 py-2.5 text-sm">
        <p class="whitespace-pre-wrap break-words">{{ turn.ask }}</p>
        <div v-if="turn.files.length" class="mt-1.5 flex flex-wrap gap-1.5">
          <Badge v-for="f in turn.files" :key="f" variant="outline" class="gap-1 font-normal"><Paperclip class="size-3" />{{ f }}</Badge>
        </div>
      </div>
    </div>

    <div class="flex gap-3">
      <div class="mt-1 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-[11px] font-semibold text-primary-foreground" aria-hidden="true">hi</div>
      <div class="min-w-0 flex-1 space-y-3">
        <div v-if="turn.route" class="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span class="font-medium text-foreground">{{ turn.route.persona }}</span><span>·</span><span>{{ turn.route.tier }}</span>
          <Badge v-if="turn.route.plan" variant="secondary" class="h-4 px-1.5 text-[10px]">plan</Badge>
        </div>

        <RunTimeline :turn="turn" />

        <div v-if="running && !turn.blocks.length" class="space-y-2" role="status" aria-label="Waiting for a reply">
          <Skeleton class="h-4 w-3/4" /><Skeleton class="h-4 w-1/2" /><Skeleton class="h-4 w-2/3" />
        </div>

        <template v-for="(block, i) in turn.blocks" :key="i">
          <ThinkingBlock v-if="block.kind === 'thinking'" :block="block" />
          <template v-else-if="block.kind === 'tool'">
            <AskForm v-if="block.name === 'ask_user' && questionsOf(block.args).length" :questions="questionsOf(block.args)" :answered="answered" :disabled="busy" @submit="emit('answer', $event)" />
            <ToolCall v-else :block="block" :running="running" :restored="turn.restored" />
          </template>
          <MarkdownContent v-else :source="block.text" :streaming="running && i === turn.blocks.length - 1" />
        </template>
        <span v-if="running && lastBlock?.kind === 'text'" class="inline-block h-4 w-1.5 animate-pulse rounded-sm bg-foreground/60 align-middle" aria-hidden="true" />

        <div v-if="turn.visual.state === 'pending'" class="space-y-2 rounded-lg border p-4" role="status" aria-label="Drawing a diagram">
          <div class="flex items-center gap-2 text-xs text-muted-foreground"><Workflow class="size-3.5 animate-pulse" /> Drawing a diagram of the answer…</div>
          <Skeleton class="h-24 w-full" />
        </div>
        <MermaidDiagram v-else-if="turn.visual.state === 'ready'" :code="turn.visual.mermaid" title="Diagram of the answer" can-redraw @redraw="emit('redraw', $event)" />

        <Alert v-if="turn.status === 'error' && turn.error" variant="destructive">
          <AlertCircle class="size-4" />
          <AlertDescription>{{ turn.error }}</AlertDescription>
        </Alert>
        <p v-if="turn.status === 'cancelled'" class="text-xs text-muted-foreground">Stopped.</p>
        <ul v-if="turn.notes.length" class="space-y-0.5 text-xs text-muted-foreground"><li v-for="(n, i) in turn.notes" :key="i">{{ n }}</li></ul>

        <div v-if="!running && answer" class="flex items-center gap-1 pt-0.5">
          <Tooltip><TooltipTrigger as-child><Button variant="ghost" size="icon" class="size-7" aria-label="Copy the answer" @click="copy"><Check v-if="copied" class="size-3.5" /><Copy v-else class="size-3.5" /></Button></TooltipTrigger><TooltipContent>Copy answer</TooltipContent></Tooltip>
          <Tooltip v-if="turn.visual.state !== 'ready'"><TooltipTrigger as-child><Button variant="ghost" size="icon" class="size-7" aria-label="Draw a diagram of this answer" @click="emit('draw')"><Workflow class="size-3.5" /></Button></TooltipTrigger><TooltipContent>Draw a diagram</TooltipContent></Tooltip>
          <Tooltip v-if="isLast && !busy"><TooltipTrigger as-child><Button variant="ghost" size="icon" class="size-7" aria-label="Ask again" @click="emit('regenerate')"><RefreshCw class="size-3.5" /></Button></TooltipTrigger><TooltipContent>Ask again</TooltipContent></Tooltip>
        </div>
        <p v-if="!running && !hasText && turn.status === 'done' && !turn.blocks.length" class="text-sm text-muted-foreground">No reply.</p>
      </div>
    </div>
  </article>
</template>
