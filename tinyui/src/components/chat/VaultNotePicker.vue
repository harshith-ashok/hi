<script setup lang="ts">
// Pick one of your vault notes to add to the chat as context.
import { NotebookText } from '@lucide/vue'
import { ref, watch } from 'vue'
import { getJson } from '@/backend'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'

export interface VaultNote { path: string; title: string }
const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ pick: [note: VaultNote] }>()

const query = ref('')
const notes = ref<VaultNote[]>([])
const loading = ref(false)
let timer = 0
let ticket = 0

async function search() {
  const mine = ++ticket
  loading.value = true
  const found = await getJson<VaultNote[]>(`/vault/notes?q=${encodeURIComponent(query.value.trim())}`)
  if (mine !== ticket) return // a newer search is on its way
  notes.value = found ?? []
  loading.value = false
}

watch(open, (on) => { if (on) { query.value = ''; void search() } })
watch(query, () => { clearTimeout(timer); timer = window.setTimeout(() => void search(), 200) })

function pick(note: VaultNote) {
  open.value = false
  emit('pick', note)
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent class="max-w-lg">
      <DialogHeader><DialogTitle>Add a note</DialogTitle><DialogDescription>Its text goes to hi with your next message. Nothing is changed in the note.</DialogDescription></DialogHeader>
      <Input v-model="query" placeholder="Search your notes" aria-label="Search your notes" autofocus spellcheck="false" />
      <ul class="max-h-72 divide-y overflow-y-auto rounded-lg border" aria-label="Notes">
        <li v-for="n in notes" :key="n.path">
          <button type="button" class="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-accent/60" @click="pick(n)">
            <NotebookText class="size-4 shrink-0 text-muted-foreground" />
            <span class="min-w-0 flex-1"><span class="block truncate text-sm">{{ n.title }}</span><span class="block truncate text-xs text-muted-foreground">{{ n.path }}</span></span>
          </button>
        </li>
        <li v-if="!notes.length" class="px-3 py-6 text-center text-sm text-muted-foreground">{{ loading ? 'Searching…' : query.trim() ? 'No notes match.' : 'No notes found.' }}</li>
      </ul>
    </DialogContent>
  </Dialog>
</template>
