<script setup lang="ts">
import { Check, Code2, Copy, Download, Eye, ExternalLink, Loader2, X } from '@lucide/vue'
import { computed, onUnmounted, ref, watch } from 'vue'
import CodeBlock from '@/components/content/CodeBlock.vue'
import MarkdownContent from '@/components/content/MarkdownContent.vue'
import MermaidDiagram from '@/components/content/MermaidDiagram.vue'
import { Button } from '@/components/ui/button'
import { useArtifact } from '@/composables/useArtifact'

// An artifact beside the chat. Pages and SVG run in a sandboxed frame with no access to this app or its backend (no
// allow-same-origin), so they can run their own scripts and nothing else.
const { shown, loading, openSaved, close } = useArtifact()
const MIN = 320
const stored = Number(localStorage.getItem('previewWidth'))
const width = ref(stored >= MIN ? stored : 560)
const dragging = ref(false)
const pane = ref<HTMLElement>()
const view = ref<'preview' | 'code'>('preview')
const copied = ref(false)

const drawn = computed(() => (shown.value?.kind === 'html' || shown.value?.kind === 'svg') && view.value === 'preview')
const hasPreview = computed(() => ['html', 'svg'].includes(shown.value?.kind ?? ''))
const document = computed(() => {
  const a = shown.value
  if (!a) return ''
  if (a.kind !== 'svg') return a.content
  return `<!doctype html><meta charset="utf-8"><body style="margin:0;display:grid;place-items:center;min-height:100vh;background:#fff">${a.content}</body>`
})
watch(() => shown.value?.slug, () => (view.value = 'preview'))

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

const MIME: Record<string, string> = { html: 'text/html', svg: 'image/svg+xml', markdown: 'text/markdown' }
function blobUrl() {
  const a = shown.value!
  return URL.createObjectURL(new Blob([a.content], { type: `${MIME[a.kind] ?? 'text/plain'};charset=utf-8` }))
}
function download() {
  const a = shown.value
  if (!a) return
  const link = Object.assign(globalThis.document.createElement('a'), { href: blobUrl(), download: `${a.slug || 'artifact'}.${a.ext}` })
  link.click()
  setTimeout(() => URL.revokeObjectURL(link.href), 10_000)
}
function openInTab() {
  if (!shown.value) return
  const url = blobUrl()
  window.open(url, '_blank', 'noopener')
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
async function copy() {
  await navigator.clipboard?.writeText(shown.value?.content ?? '')
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}
async function pickVersion(event: Event) {
  const a = shown.value
  if (a?.session && a.slug) await openSaved(a.session, a.slug, Number((event.target as HTMLSelectElement).value))
}
</script>

<template>
  <aside v-if="shown" ref="pane" class="relative flex min-h-0 shrink-0 flex-col border-l bg-background max-md:fixed max-md:inset-0 max-md:z-50 md:w-[var(--preview-w)]" :style="{ '--preview-w': `${width}px` }" aria-label="Artifact">
    <div class="absolute inset-y-0 -left-1 z-10 hidden w-2 cursor-col-resize hover:bg-primary/30 md:block" :class="dragging && 'bg-primary/40'" role="separator" aria-orientation="vertical" aria-label="Resize panel" @pointerdown="drag" />
    <header class="flex h-14 shrink-0 items-center gap-1 border-b px-3">
      <h2 class="min-w-0 flex-1 truncate text-sm font-semibold">{{ shown.title }}</h2>
      <Loader2 v-if="loading" class="size-4 animate-spin text-muted-foreground" aria-label="Loading" />
      <select v-if="shown.versions.length > 1" class="h-8 rounded-md border bg-background px-1.5 text-xs" aria-label="Version" :value="shown.version" @change="pickVersion">
        <option v-for="n in shown.versions" :key="n" :value="n">v{{ n }}{{ n === shown.versions[shown.versions.length - 1] ? ' (latest)' : '' }}</option>
      </select>
      <div v-if="hasPreview" class="flex rounded-md border" role="group" aria-label="View">
        <Button variant="ghost" size="icon" class="size-8 rounded-r-none" :class="view === 'preview' && 'bg-accent'" aria-label="Preview" :aria-pressed="view === 'preview'" @click="view = 'preview'"><Eye class="size-4" /></Button>
        <Button variant="ghost" size="icon" class="size-8 rounded-l-none" :class="view === 'code' && 'bg-accent'" aria-label="Code" :aria-pressed="view === 'code'" @click="view = 'code'"><Code2 class="size-4" /></Button>
      </div>
      <Button variant="ghost" size="icon" class="size-8" aria-label="Copy" title="Copy" @click="copy"><Check v-if="copied" class="size-4" /><Copy v-else class="size-4" /></Button>
      <Button variant="ghost" size="icon" class="size-8" aria-label="Download" title="Download" @click="download"><Download class="size-4" /></Button>
      <Button v-if="hasPreview" variant="ghost" size="icon" class="size-8" aria-label="Open in a new tab" title="Open in a new tab" @click="openInTab"><ExternalLink class="size-4" /></Button>
      <Button variant="ghost" size="icon" class="size-8" aria-label="Close" @click="close"><X class="size-4" /></Button>
    </header>
    <iframe v-if="drawn" :key="`${shown.slug}-${shown.version}-${shown.content.length}`" :srcdoc="document" sandbox="allow-scripts allow-forms allow-modals allow-popups" class="min-h-0 w-full flex-1 bg-white" :class="dragging && 'pointer-events-none'" :title="shown.title" />
    <div v-else class="min-h-0 flex-1 overflow-y-auto p-4">
      <MarkdownContent v-if="shown.kind === 'markdown' && view === 'preview'" :source="shown.content" />
      <MermaidDiagram v-else-if="shown.kind === 'mermaid' && view === 'preview'" :code="shown.content" :title="shown.title" />
      <CodeBlock v-else :lang="shown.kind === 'code' || hasPreview ? shown.ext : shown.kind" :text="shown.content" />
    </div>
  </aside>
</template>
