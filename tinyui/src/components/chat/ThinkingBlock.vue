<script setup lang="ts">
import { Brain, ChevronDown } from '@lucide/vue'
import { computed, ref, watch } from 'vue'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import type { ThinkBlock } from '@/composables/useChat'
import { ms } from '@/lib/run'
import { cn } from '@/lib/utils'

const props = defineProps<{ block: ThinkBlock }>()
const live = computed(() => props.block.t1 === undefined)
const open = ref(live.value)
let touched = false
watch(live, (on) => { if (!touched) open.value = on })
function toggle(value: boolean) {
  touched = true
  open.value = value
}
</script>

<template>
  <Collapsible :open="open" @update:open="toggle">
    <CollapsibleTrigger class="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground">
      <Brain :class="cn('size-3.5', live && 'animate-pulse text-info')" />
      <span>{{ live ? 'Thinking…' : `Thought for ${ms((block.t1 ?? 0) - block.t0)}` }}</span>
      <ChevronDown :class="cn('size-3.5 transition-transform', open && 'rotate-180')" />
    </CollapsibleTrigger>
    <CollapsibleContent>
      <p class="mt-1.5 max-h-48 overflow-y-auto whitespace-pre-wrap border-l-2 pl-3 text-xs italic leading-relaxed text-muted-foreground">{{ block.text }}</p>
    </CollapsibleContent>
  </Collapsible>
</template>
