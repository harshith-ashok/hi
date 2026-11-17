<script setup lang="ts">
import { X } from '@lucide/vue'
import Orb from '@/components/chat/Orb.vue'
import ApprovalBar from '@/components/chat/ApprovalBar.vue'
import { Button } from '@/components/ui/button'
import type { Pending } from '@/backend'

defineProps<{ state: string; caption: string; pending: Pending[] }>()
const emit = defineEmits<{ leave: []; answer: [approve: boolean] }>()
</script>

<template>
  <section class="fixed inset-0 z-50 flex flex-col items-center justify-between bg-background/95 p-6 backdrop-blur" role="dialog" aria-modal="true" aria-label="Voice mode">
    <div class="flex w-full items-center justify-between">
      <span class="text-lg font-semibold">hi</span>
      <Button variant="ghost" size="sm" @click="emit('leave')"><X class="size-4" /> Leave voice mode <kbd class="ml-1 rounded bg-muted px-1 font-mono text-[10px]">esc</kbd></Button>
    </div>
    <div class="flex flex-col items-center gap-4">
      <Orb :state="state" />
      <div class="text-sm uppercase tracking-[0.3em] text-muted-foreground" role="status">{{ state }}</div>
      <p class="min-h-12 max-w-xl text-center text-lg leading-relaxed">{{ caption }}</p>
    </div>
    <div class="w-full max-w-xl"><ApprovalBar :pending="pending" @answer="emit('answer', $event)" /></div>
  </section>
</template>
