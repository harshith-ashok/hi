<script setup lang="ts">
import { Check, Copy, Download, Maximize2, RefreshCw, TriangleAlert, Workflow } from '@lucide/vue'
import { ref, watch } from 'vue'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { useTheme } from '@/composables/useTheme'
import { renderMermaid } from '@/lib/mermaid'

const props = defineProps<{ code: string; title?: string; canRedraw?: boolean }>()
const emit = defineEmits<{ redraw: [error: string] }>()

const { dark } = useTheme()
const svg = ref('')
const error = ref('')
const drawing = ref(true)
const open = ref(false)
const copied = ref(false)
let ticket = 0

async function draw() {
  const mine = ++ticket
  drawing.value = true
  const out = await renderMermaid(props.code)
  if (mine !== ticket) return
  drawing.value = false
  if ('svg' in out) {
    svg.value = out.svg
    error.value = ''
  } else {
    svg.value = ''
    error.value = out.error
  }
}

watch(() => [props.code, dark.value], draw, { immediate: true })

async function copy() {
  await navigator.clipboard?.writeText(props.code)
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}

function download() {
  const url = URL.createObjectURL(new Blob([svg.value], { type: 'image/svg+xml' }))
  const a = Object.assign(document.createElement('a'), { href: url, download: `${(props.title ?? 'diagram').replace(/\W+/g, '-').toLowerCase()}.svg` })
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <figure class="not-prose my-3 overflow-hidden rounded-lg border bg-card">
    <figcaption class="flex items-center gap-2 border-b px-3 py-1.5 text-xs text-muted-foreground">
      <Workflow class="size-3.5" />
      <span class="font-medium">{{ title ?? 'Diagram' }}</span>
      <span class="grow" />
      <Button v-if="svg" variant="ghost" size="icon" class="size-7" title="Expand" @click="open = true"><Maximize2 class="size-3.5" /></Button>
      <Button v-if="svg" variant="ghost" size="icon" class="size-7" title="Download SVG" @click="download"><Download class="size-3.5" /></Button>
      <Button variant="ghost" size="icon" class="size-7" title="Copy the Mermaid code" @click="copy">
        <Check v-if="copied" class="size-3.5" /><Copy v-else class="size-3.5" />
      </Button>
    </figcaption>

    <div v-if="drawing && !svg" class="space-y-2 p-4" role="status" aria-label="Drawing the diagram">
      <Skeleton class="h-4 w-1/3" /><Skeleton class="h-24 w-full" /><Skeleton class="h-4 w-1/2" />
    </div>
    <div v-else-if="error" class="space-y-2 p-3">
      <Alert variant="destructive">
        <TriangleAlert class="size-4" />
        <AlertDescription class="text-xs">Could not draw this diagram: {{ error }}</AlertDescription>
      </Alert>
      <Button v-if="canRedraw" variant="outline" size="sm" @click="emit('redraw', error)"><RefreshCw class="size-3.5" /> Ask for another</Button>
      <details class="text-xs text-muted-foreground"><summary class="cursor-pointer">Mermaid code</summary><pre class="mt-1 overflow-x-auto rounded bg-muted p-2">{{ code }}</pre></details>
    </div>
    <div v-else class="flex justify-center overflow-x-auto p-3 [&_svg]:h-auto [&_svg]:max-w-full" v-html="svg" />

    <Dialog v-model:open="open">
      <DialogContent class="max-h-[92vh] w-[min(1200px,94vw)] max-w-none overflow-auto sm:max-w-none">
        <DialogHeader><DialogTitle>{{ title ?? 'Diagram' }}</DialogTitle></DialogHeader>
        <div class="flex justify-center [&_svg]:h-auto [&_svg]:w-full [&_svg]:max-w-none" v-html="svg" />
      </DialogContent>
    </Dialog>
  </figure>
</template>
