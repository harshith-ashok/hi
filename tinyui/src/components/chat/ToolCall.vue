<script setup lang="ts">
import { AlertCircle, Check, ChevronDown, Download, Loader2, Wrench } from '@lucide/vue'
import { ref } from 'vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import type { ToolBlock } from '@/composables/useChat'
import { files, ms, plots, scope, short } from '@/lib/run'
import { cn } from '@/lib/utils'

const props = defineProps<{ block: ToolBlock; running: boolean; restored?: boolean }>()
const open = ref(false)
const pending = () => props.block.result === undefined
const failed = () => pending() && !props.running
const tone = () => ({ danger: 'border-destructive/40 text-destructive', warn: 'border-warning/50 text-warning', neutral: '' })[scope(props.block.name)?.tone ?? 'neutral']
</script>

<template>
  <div class="rounded-lg border bg-card/50">
    <Collapsible :open="open" @update:open="(v: boolean) => (open = v)">
      <CollapsibleTrigger class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm">
        <Loader2 v-if="pending() && running" class="size-4 shrink-0 animate-spin text-info" />
        <AlertCircle v-else-if="failed()" class="size-4 shrink-0 text-destructive" />
        <Check v-else class="size-4 shrink-0 text-success" />
        <Wrench class="size-3.5 shrink-0 text-muted-foreground" />
        <span class="font-mono text-[13px]">{{ block.name }}</span>
        <Badge v-if="scope(block.name)" variant="outline" :class="cn('h-5 px-1.5 text-[10px] font-normal', tone())">{{ scope(block.name)!.label }}</Badge>
        <span class="min-w-0 flex-1 truncate text-xs text-muted-foreground">{{ pending() ? (running ? 'running…' : 'no result') : short(block.result ?? '', 120) }}</span>
        <span v-if="block.t1 && !restored" class="font-mono text-xs tabular-nums text-muted-foreground">{{ ms(block.t1 - block.t0) }}</span>
        <ChevronDown :class="cn('size-4 shrink-0 text-muted-foreground transition-transform', open && 'rotate-180')" />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div class="space-y-2 border-t p-3">
          <div><div class="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Arguments</div><pre class="max-h-48 overflow-auto rounded bg-muted p-2 font-mono text-xs">{{ block.args || '(none)' }}</pre></div>
          <div><div class="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Result</div><pre class="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-muted p-2 font-mono text-xs">{{ block.result ?? '(waiting for result)' }}</pre></div>
        </div>
      </CollapsibleContent>
    </Collapsible>

    <div v-if="plots(block.result).length" class="grid gap-2 border-t p-3 sm:grid-cols-2">
      <a v-for="src in plots(block.result)" :key="src" :href="src" target="_blank" rel="noopener" class="block overflow-hidden rounded-md border bg-background">
        <img :src="src" alt="Image made by the assistant" class="max-h-96 w-full object-contain" loading="lazy" />
      </a>
    </div>
    <div v-if="files(block.result).length" class="flex flex-wrap gap-2 border-t p-3">
      <Button v-for="f in files(block.result)" :key="f.href" as="a" :href="f.href" target="_blank" rel="noopener" variant="outline" size="sm"><Download class="size-3.5" /> {{ f.name }}</Button>
    </div>
  </div>
</template>
