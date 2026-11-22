<script setup lang="ts">
import { ExternalLink, X } from '@lucide/vue'
import { onUnmounted, ref } from 'vue'
import { Button } from '@/components/ui/button'
import { usePreview } from '@/composables/usePreview'

// An HTML page a reply wrote, in a sandboxed frame to the right of the chat. The frame has no access to this app or
// its backend (no allow-same-origin), so the page can run its own scripts and nothing else.
const { page, close } = usePreview()
const MIN = 320
const stored = Number(localStorage.getItem('previewWidth'))
const width = ref(stored >= MIN ? stored : 560)
const dragging = ref(false)
const pane = ref<HTMLElement>()

function drag(e: PointerEvent) {
  const right = pane.value?.parentElement?.getBoundingClientRect().right ?? window.innerWidth
  const max = (pane.value?.parentElement?.clientWidth ?? window.innerWidth) * 0.7
  const move = (ev: PointerEvent) => (width.value = Math.round(Math.min(max, Math.max(MIN, right - ev.clientX))))
  const up = () => {
    dragging.value = false
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', up)
    localStorage.setItem('previewWidth', String(width.value))
  }
  dragging.value = true
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', up)
  e.preventDefault()
}
onUnmounted(() => (dragging.value = false))

function openInTab() {
  if (!page.value) return
  const url = URL.createObjectURL(new Blob([page.value.html], { type: 'text/html' }))
  window.open(url, '_blank', 'noopener')
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
</script>

<template>
  <aside v-if="page" ref="pane" class="relative flex min-h-0 shrink-0 flex-col border-l bg-background max-md:fixed max-md:inset-0 max-md:z-50 md:w-[var(--preview-w)]" :style="{ '--preview-w': `${width}px` }" aria-label="HTML preview">
    <div class="absolute inset-y-0 -left-1 z-10 hidden w-2 cursor-col-resize hover:bg-primary/30 md:block" :class="dragging && 'bg-primary/40'" role="separator" aria-orientation="vertical" aria-label="Resize preview" @pointerdown="drag" />
    <header class="flex h-14 shrink-0 items-center gap-1 border-b px-3">
      <h2 class="min-w-0 flex-1 truncate text-sm font-semibold">{{ page.title }}</h2>
      <Button variant="ghost" size="icon" class="size-8" aria-label="Open in a new tab" title="Open in a new tab" @click="openInTab"><ExternalLink class="size-4" /></Button>
      <Button variant="ghost" size="icon" class="size-8" aria-label="Close preview" @click="close"><X class="size-4" /></Button>
    </header>
    <iframe :key="page.html" :srcdoc="page.html" sandbox="allow-scripts allow-forms allow-modals allow-popups" class="min-h-0 w-full flex-1 bg-white" :class="dragging && 'pointer-events-none'" title="HTML preview" />
  </aside>
</template>
