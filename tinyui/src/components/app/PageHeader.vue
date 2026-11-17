<script setup lang="ts">
import { SidebarTrigger } from '@/components/ui/sidebar'

defineProps<{ title: string; subtitle?: string }>()
</script>

<template>
  <header class="flex h-14 shrink-0 items-center gap-2 border-b px-3">
    <SidebarTrigger />
    <div class="min-w-0">
      <h1 class="truncate text-sm font-semibold">{{ title }}</h1>
      <p v-if="subtitle" class="truncate text-xs text-muted-foreground">{{ subtitle }}</p>
    </div>
    <span class="grow" />
    <slot />
  </header>
</template>
