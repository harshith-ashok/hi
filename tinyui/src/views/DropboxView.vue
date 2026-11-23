<script setup lang="ts">
// The drop box: drop text, images, voice notes and files; hi describes them and sorts them into groups on a canvas.
// The board is an Obsidian canvas in the vault (hi/canvas/dropbox.canvas), so it opens there too.
import { FileText, ImagePlus, Mic, Sparkles, Square, Trash2 } from '@lucide/vue'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import PageHeader from '@/components/app/PageHeader.vue'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import {
  BASE_URL, deleteCanvasItem, dropCanvasFile, dropText, fetchCanvas, moveCanvasItem, regroupCanvas, renameCanvasGroup,
  type Canvas, type CanvasItem,
} from '@/backend'
import { toWav } from '@/voice'

const board = ref<Canvas>({ groups: [], pending: 0 })
const text = ref('')
const sorting = ref(false)
const over = ref(false)
const dragging = ref('')
const target = ref('')
const editing = ref('')
const recording = ref(false)
const picker = ref<HTMLInputElement>()
let recorder: MediaRecorder | null = null
let timer = 0

const size = computed(() => ({
  width: Math.max(600, ...board.value.groups.map((g) => g.x + g.width + 40)) + 'px',
  height: Math.max(400, ...board.value.groups.map((g) => g.y + g.height + 40)) + 'px',
}))
const total = computed(() => board.value.groups.reduce((n, g) => n + g.items.length, 0))

async function load() {
  const next = await fetchCanvas()
  if (next) board.value = next
  schedule()
}
// Poll quickly while something is being read or sorted, slowly otherwise (another window may drop things).
function schedule() {
  clearTimeout(timer)
  timer = window.setTimeout(() => void load(), board.value.pending ? 2000 : 15000)
}

async function addText() {
  const value = text.value.trim()
  if (!value) return
  text.value = ''
  if (!(await dropText(value))) toast.error('Could not reach the backend.')
  await load()
}

async function addFiles(files: File[], kind = '') {
  for (const file of files) {
    try {
      await dropCanvasFile(file, file.name, kind)
    } catch (err) {
      toast.error((err as Error).message)
    }
  }
  await load()
}

function onDrop(event: DragEvent) {
  over.value = false
  const files = [...(event.dataTransfer?.files ?? [])]
  if (files.length) void addFiles(files)
  else if (event.dataTransfer?.getData('text/plain') && !dragging.value) {
    text.value = event.dataTransfer.getData('text/plain')
    void addText()
  }
}

function onPaste(event: ClipboardEvent) {
  const files = [...(event.clipboardData?.files ?? [])]
  if (!files.length) return
  event.preventDefault()
  void addFiles(files)
}

async function toggleRecording() {
  if (recorder && recording.value) return recorder.stop()
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const chunks: Blob[] = []
    recorder = new MediaRecorder(stream)
    recorder.ondataavailable = (e) => chunks.push(e.data)
    recorder.onstop = async () => {
      recording.value = false
      stream.getTracks().forEach((t) => t.stop())
      const raw = new Blob(chunks)
      const wav = await toWav(raw).catch(() => null) // the whisper.cpp fallback needs 16 kHz WAV
      await addFiles([new File([wav ?? raw], wav ? 'voice-note.wav' : 'voice-note.webm')], 'audio')
    }
    recorder.start()
    recording.value = true
  } catch {
    toast.error('Could not use the microphone.')
  }
}

async function sort(all: boolean) {
  sorting.value = true
  const out = await regroupCanvas(all)
  sorting.value = false
  if (!out) return void toast.error('Sorting failed: is the model reachable? (see Status)')
  board.value = out
  toast.success(out.moved ? `Moved ${out.moved} item${out.moved === 1 ? '' : 's'}.` : 'Nothing to move.')
}

async function move(groupId: string) {
  const id = dragging.value
  dragging.value = target.value = ''
  const group = board.value.groups.find((g) => g.items.some((i) => i.id === id))
  if (!id || group?.id === groupId) return
  board.value = (await moveCanvasItem(id, groupId)) ?? board.value
}

async function remove(item: CanvasItem) {
  board.value = (await deleteCanvasItem(item.id)) ?? board.value
}

async function rename(id: string, event: Event) {
  const label = (event.target as HTMLInputElement).value.trim()
  editing.value = ''
  if (label) board.value = (await renameCanvasGroup(id, label)) ?? board.value
}

const src = (item: CanvasItem) => BASE_URL + item.url
const shown = (item: CanvasItem) => (item.kind === 'text' ? item.text : item.summary)

onMounted(() => void load())
onUnmounted(() => clearTimeout(timer))
</script>

<template>
  <div class="flex h-full min-h-0 flex-col" @dragover.prevent="over = !dragging" @dragleave.self="over = false" @drop.prevent="onDrop" @paste="onPaste">
    <PageHeader title="Drop box" :subtitle="`${total} item${total === 1 ? '' : 's'}${board.pending ? ` · reading ${board.pending}…` : ''}`">
      <Button variant="outline" size="sm" :disabled="sorting" @click="sort(true)">
        <Sparkles class="size-4" /> {{ sorting ? 'Sorting…' : 'Sort again' }}
      </Button>
    </PageHeader>

    <div class="flex shrink-0 items-end gap-2 border-b p-3">
      <Textarea v-model="text" rows="2" class="min-h-0 resize-none" placeholder="Drop a thought, paste an image, or drag files here…"
        @keydown.enter.exact.prevent="addText" />
      <Button size="sm" :disabled="!text.trim()" @click="addText">Add</Button>
      <Button variant="outline" size="icon" title="Add images or files" @click="picker?.click()"><ImagePlus class="size-4" /></Button>
      <input ref="picker" type="file" multiple class="hidden" @change="addFiles([...(($event.target as HTMLInputElement).files ?? [])]); ($event.target as HTMLInputElement).value = ''" />
      <Button :variant="recording ? 'destructive' : 'outline'" size="icon" :title="recording ? 'Stop and drop the voice note' : 'Record a voice note'" @click="toggleRecording">
        <Square v-if="recording" class="size-4" /><Mic v-else class="size-4" />
      </Button>
    </div>

    <div class="relative min-h-0 grow overflow-auto" :class="over && 'bg-accent/40'">
      <p v-if="!total" class="absolute inset-0 grid place-items-center text-sm text-muted-foreground">
        Nothing here yet. Drop text, images or a voice note and hi will sort them into groups.
      </p>
      <div class="relative" :style="size">
        <section v-for="g in board.groups" :key="g.id"
          class="absolute rounded-xl border bg-muted/40 transition-colors" :class="target === g.id && 'border-primary bg-accent'"
          :style="{ left: g.x + 20 + 'px', top: g.y + 20 + 'px', width: g.width + 'px', height: g.height + 'px' }"
          @dragover.prevent.stop="dragging && (target = g.id)" @dragleave.self="target = ''" @drop.prevent.stop="dragging ? move(g.id) : onDrop($event)">
          <input v-if="editing === g.id" autofocus class="m-1 w-[calc(100%-8px)] rounded bg-background px-2 py-1 text-sm font-semibold"
            :value="g.label" @blur="rename(g.id, $event)" @keydown.enter="($event.target as HTMLInputElement).blur()" @keydown.esc="editing = ''" />
          <h2 v-else class="cursor-text truncate px-3 py-2 text-sm font-semibold" title="Double-click to rename" @dblclick="editing = g.id">{{ g.label }}</h2>
        </section>

        <template v-for="g in board.groups" :key="g.id + '-items'">
          <article v-for="item in g.items" :key="item.id" draggable="true"
            class="group absolute overflow-hidden rounded-lg border bg-card p-2 text-sm shadow-sm"
            :class="dragging === item.id && 'opacity-40'"
            :style="{ left: item.x + 20 + 'px', top: item.y + 20 + 'px', width: item.width + 'px', height: item.height + 'px' }"
            @dragstart="dragging = item.id" @dragend="dragging = target = ''"
            @dragover.prevent.stop="dragging && (target = g.id)" @drop.prevent.stop="dragging ? move(g.id) : onDrop($event)">
            <Button variant="ghost" size="icon" class="absolute right-1 top-1 z-10 size-6 opacity-0 group-hover:opacity-100" title="Delete" @click="remove(item)">
              <Trash2 class="size-3.5" />
            </Button>
            <img v-if="item.kind === 'image'" :src="src(item)" :alt="item.summary" draggable="false" class="h-full w-full rounded object-cover" />
            <template v-else>
              <audio v-if="item.kind === 'voice'" :src="src(item)" controls class="mb-1 h-8 w-full" />
              <p v-else-if="item.kind === 'file'" class="mb-1 flex items-center gap-1 truncate font-medium"><FileText class="size-4 shrink-0" /> {{ item.name }}</p>
              <p v-if="item.pending" class="text-muted-foreground">Reading…</p>
              <p v-else class="line-clamp-6 whitespace-pre-wrap break-words" :class="item.kind !== 'text' && 'text-muted-foreground'">{{ shown(item) }}</p>
            </template>
          </article>
        </template>
      </div>
    </div>
  </div>
</template>
