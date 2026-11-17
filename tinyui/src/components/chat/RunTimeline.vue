<script setup lang="ts">
// What the assistant is doing, step by step, with the time each step takes. Open while it works, one line after.
import { AlertCircle, Check, ChevronDown, Circle, Loader2, Network } from '@lucide/vue'
import { useIntervalFn } from '@vueuse/core'
import { computed, ref, watch } from 'vue'
import MermaidDiagram from '@/components/content/MermaidDiagram.vue'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import type { Turn } from '@/composables/useChat'
import { ms, runDiagram, stepsOf } from '@/lib/run'
import { cn } from '@/lib/utils'

const props = defineProps<{ turn: Turn }>()

const running = computed(() => props.turn.status === 'running')
const now = ref(Date.now())
const { pause, resume } = useIntervalFn(() => (now.value = Date.now()), 100, { immediate: false })
watch(running, (on) => (on ? resume() : pause()), { immediate: true })

const steps = computed(() => stepsOf(props.turn, now.value))
const active = computed(() => steps.value.find((s) => s.state === 'active'))
const total = computed(() => (props.turn.restored ? (props.turn.seconds ?? 0) * 1000 : (props.turn.t1 ?? now.value) - props.turn.t0))
const toolCount = computed(() => props.turn.blocks.filter((b) => b.kind === 'tool').length)

const open = ref(running.value)
let touched = false
watch(running, (on) => { if (!touched) open.value = on })
const toggle = (v: boolean) => { touched = true; open.value = v }

const slowModel = computed(() => active.value?.key === 'model' && now.value - (active.value.t0 ?? now.value) > 8000)
const mapOpen = ref(false)
const duration = (s: { t0?: number; t1?: number; state: string }) =>
  props.turn.restored || !s.t0 ? '' : ms((s.t1 ?? (s.state === 'active' ? now.value : s.t0)) - s.t0)
</script>

<template>
  <Collapsible :open="open" class="rounded-lg border bg-card/50" @update:open="toggle">
    <CollapsibleTrigger class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm" :aria-label="running ? 'Progress' : 'Show steps'">
      <Loader2 v-if="running" class="size-4 shrink-0 animate-spin text-info" />
      <AlertCircle v-else-if="turn.status === 'error'" class="size-4 shrink-0 text-destructive" />
      <Check v-else class="size-4 shrink-0 text-success" />
      <span class="min-w-0 flex-1 truncate">
        <template v-if="running">{{ active?.title ?? 'Working' }}<span v-if="active?.detail" class="text-muted-foreground"> · {{ active.detail }}</span></template>
        <template v-else-if="turn.status === 'cancelled'">Stopped</template>
        <template v-else-if="turn.status === 'error'">Failed</template>
        <template v-else>Done<span class="text-muted-foreground"> · {{ toolCount ? `${toolCount} tool${toolCount > 1 ? 's' : ''}` : 'no tools' }}</span></template>
      </span>
      <span v-if="total > 0" class="font-mono text-xs tabular-nums text-muted-foreground">{{ ms(total) }}</span>
      <ChevronDown :class="cn('size-4 shrink-0 text-muted-foreground transition-transform', open && 'rotate-180')" />
    </CollapsibleTrigger>

    <CollapsibleContent>
      <ol class="space-y-0 border-t px-3 py-2" aria-label="Steps">
        <li v-for="(s, i) in steps" :key="s.key" class="relative flex gap-3 pb-2.5 last:pb-0">
          <span v-if="i < steps.length - 1" class="absolute left-[7px] top-4 h-[calc(100%-8px)] w-px bg-border" aria-hidden="true" />
          <Loader2 v-if="s.state === 'active'" class="relative mt-0.5 size-4 shrink-0 animate-spin bg-card text-info" />
          <Check v-else-if="s.state === 'done'" class="relative mt-0.5 size-4 shrink-0 rounded-full bg-card text-success" />
          <AlertCircle v-else-if="s.state === 'failed'" class="relative mt-0.5 size-4 shrink-0 bg-card text-destructive" />
          <Circle v-else class="relative mt-0.5 size-4 shrink-0 bg-card text-muted-foreground/50" />
          <div class="min-w-0 flex-1 text-sm leading-5">
            <div class="flex items-baseline gap-2">
              <span :class="cn(s.state === 'pending' && 'text-muted-foreground')">{{ s.title }}</span>
              <span v-if="s.detail && s.key !== 'error'" class="truncate text-xs text-muted-foreground">{{ s.detail }}</span>
              <span class="grow" />
              <span class="font-mono text-xs tabular-nums text-muted-foreground">{{ duration(s) }}</span>
            </div>
            <div v-if="s.key === 'error'" class="text-xs text-destructive">{{ s.detail }}</div>
            <div v-else-if="s.key === 'model' && slowModel" class="text-xs text-muted-foreground">
              The model is still starting. The first request after a quiet spell loads it into memory, which can take a minute.
            </div>
          </div>
        </li>
      </ol>
      <div v-if="!running && steps.length > 1" class="flex justify-end border-t px-2 py-1">
        <Button variant="ghost" size="sm" class="h-7 gap-1.5 text-xs" @click="mapOpen = true"><Network class="size-3.5" /> Run map</Button>
      </div>
    </CollapsibleContent>

    <Dialog v-model:open="mapOpen">
      <DialogContent class="w-[min(1100px,94vw)] max-w-none sm:max-w-none">
        <DialogHeader><DialogTitle>How this answer was made</DialogTitle></DialogHeader>
        <MermaidDiagram v-if="mapOpen" :code="runDiagram(turn)" title="Run map" />
      </DialogContent>
    </Dialog>
  </Collapsible>
</template>
