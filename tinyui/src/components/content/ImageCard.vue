<script setup lang="ts">
// A picture the assistant made: the image, the prompt behind it, and what you can do with it.
import { Download, Maximize2, RefreshCw, TriangleAlert } from '@lucide/vue'
import { ref } from 'vue'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'

defineProps<{ src: string; prompt: string }>()
const emit = defineEmits<{ another: [] }>()
const open = ref(false)
const failed = ref(false)
</script>

<template>
  <figure class="not-prose my-3 overflow-hidden rounded-lg border bg-card">
    <div class="relative bg-muted/40">
      <button v-if="!failed" class="block w-full" aria-label="Open the image full size" @click="open = true">
        <img :src="src" :alt="prompt" class="mx-auto max-h-[28rem] w-auto max-w-full object-contain" loading="lazy" @error="failed = true" />
      </button>
      <div v-else class="flex items-center gap-2 p-6 text-sm text-destructive"><TriangleAlert class="size-4" /> The image could not be loaded.</div>
    </div>
    <figcaption class="space-y-2 border-t px-3 py-2">
      <p class="line-clamp-2 text-xs text-muted-foreground" :title="prompt">{{ prompt }}</p>
      <div class="flex flex-wrap items-center gap-1">
        <Button variant="ghost" size="sm" class="h-7 gap-1.5 px-2 text-xs" @click="open = true"><Maximize2 class="size-3.5" /> Open</Button>
        <Button as="a" :href="src" download variant="ghost" size="sm" class="h-7 gap-1.5 px-2 text-xs"><Download class="size-3.5" /> Download</Button>
        <Button variant="ghost" size="sm" class="h-7 gap-1.5 px-2 text-xs" @click="emit('another')"><RefreshCw class="size-3.5" /> Another version</Button>
      </div>
    </figcaption>

    <Dialog v-model:open="open">
      <DialogContent class="w-[min(1100px,94vw)] max-w-none sm:max-w-none">
        <DialogHeader><DialogTitle class="line-clamp-2 text-sm font-normal">{{ prompt }}</DialogTitle></DialogHeader>
        <img :src="src" :alt="prompt" class="mx-auto max-h-[78vh] w-auto max-w-full rounded-md object-contain" />
      </DialogContent>
    </Dialog>
  </figure>
</template>
