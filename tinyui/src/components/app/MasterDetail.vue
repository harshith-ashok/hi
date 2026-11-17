<script setup lang="ts">
// A list on the left and the chosen item on the right; on a narrow screen one at a time.
import { ArrowLeft } from '@lucide/vue'
import { Button } from '@/components/ui/button'

defineProps<{ detailOpen: boolean; backLabel?: string }>()
const emit = defineEmits<{ back: [] }>()
</script>

<template>
  <div class="grid min-h-0 flex-1 md:grid-cols-[320px_minmax(0,1fr)]">
    <aside :class="['min-h-0 flex-col overflow-y-auto border-r', detailOpen ? 'hidden md:flex' : 'flex']"><slot name="list" /></aside>
    <section :class="['min-h-0 flex-col overflow-y-auto', detailOpen ? 'flex' : 'hidden md:flex']">
      <Button variant="ghost" size="sm" class="m-2 w-fit md:hidden" @click="emit('back')"><ArrowLeft class="size-4" /> {{ backLabel ?? 'Back' }}</Button>
      <slot name="detail" />
    </section>
  </div>
</template>
