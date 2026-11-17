<script setup lang="ts">
import { ShieldAlert } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import type { Pending } from '@/backend'

defineProps<{ pending: Pending[] }>()
const emit = defineEmits<{ answer: [approve: boolean] }>()
</script>

<template>
  <div v-if="pending.length" class="flex items-center gap-3 rounded-lg border border-warning/50 bg-warning/10 px-4 py-3" role="alertdialog" aria-label="Confirm an action">
    <ShieldAlert class="size-5 shrink-0 text-warning" />
    <div class="min-w-0 flex-1 text-sm">
      <div class="font-medium">Confirm this action</div>
      <div class="truncate text-muted-foreground" :title="pending[0].description">{{ pending[0].description }}</div>
    </div>
    <Button size="sm" variant="destructive" @click="emit('answer', true)">Allow <kbd class="ml-1 rounded bg-background/20 px-1 font-mono text-[10px]">y</kbd></Button>
    <Button size="sm" variant="outline" @click="emit('answer', false)">Deny <kbd class="ml-1 rounded bg-muted px-1 font-mono text-[10px]">n</kbd></Button>
  </div>
</template>
