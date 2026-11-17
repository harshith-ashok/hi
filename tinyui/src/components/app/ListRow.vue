<script setup lang="ts">
import { cn } from '@/lib/utils'

defineProps<{ active?: boolean }>()
</script>

<template>
  <button :class="cn('flex w-full flex-col gap-0.5 border-b px-4 py-3 text-left transition-colors hover:bg-accent/60', active && 'bg-accent')">
    <slot />
  </button>
</template>
