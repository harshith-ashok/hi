<script setup lang="ts">
// Projects: a workspace with its own instructions, files and chats.
import { FileText, FolderPlus, MessageSquarePlus, Trash2, Upload } from '@lucide/vue'
import { computed, onMounted, ref, watch } from 'vue'
import ListRow from '@/components/app/ListRow.vue'
import MasterDetail from '@/components/app/MasterDetail.vue'
import PageHeader from '@/components/app/PageHeader.vue'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useProjects, type ProjectDetail } from '@/composables/useProjects'

const emit = defineEmits<{ open: [sessionId: string]; newChat: [slug: string] }>()
const store = useProjects()

const detail = ref<ProjectDetail | null>(null)
const name = ref('')
const description = ref('')
const instructions = ref('')
const pane = ref(false)
const message = ref('')
const creating = ref(false)
const newName = ref('')
const doomed = ref(false)
const picker = ref<HTMLInputElement>()

const dirty = computed(() => !!detail.value && (name.value !== detail.value.name || description.value !== detail.value.description || instructions.value !== detail.value.instructions))

async function load(slug: string) {
  const found = slug ? await store.get(slug) : null
  detail.value = found
  if (found) {
    name.value = found.name
    description.value = found.description
    instructions.value = found.instructions
  }
  pane.value = !!found
}

function choose(slug: string) {
  store.selected.value = slug
  message.value = ''
}

async function create() {
  const made = await store.create(newName.value.trim())
  if (!made) return void (message.value = 'Could not make that project.')
  creating.value = false
  newName.value = ''
  choose(made.slug)
}

async function save() {
  if (!detail.value) return
  const row = await store.update(detail.value.slug, { name: name.value, description: description.value, instructions: instructions.value })
  message.value = row ? 'Saved.' : 'Could not save.'
  if (row) await load(row.slug)
}

async function upload(files: FileList | null) {
  if (!detail.value || !files) return
  const failed: string[] = []
  for (const file of Array.from(files)) if (!(await store.uploadFile(detail.value.slug, file))) failed.push(file.name)
  message.value = failed.length ? `Could not add: ${failed.join(', ')}` : ''
  await load(detail.value.slug)
  await store.refresh()
  if (picker.value) picker.value.value = ''
}

async function removeFile(file: string) {
  if (!detail.value) return
  await store.removeFile(detail.value.slug, file)
  await load(detail.value.slug)
  await store.refresh()
}

async function confirmDelete() {
  if (!detail.value) return
  await store.remove(detail.value.slug)
  doomed.value = false
  detail.value = null
  pane.value = false
}

const size = (bytes: number) => (bytes < 1024 ? `${bytes} B` : bytes < 1_048_576 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1_048_576).toFixed(1)} MB`)

watch(store.selected, (slug) => void load(slug))
onMounted(async () => {
  await store.refresh()
  if (store.selected.value) await load(store.selected.value)
})
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <PageHeader title="Projects" subtitle="Instructions, files and chats that belong together">
      <Button size="sm" class="gap-1.5" @click="creating = true"><FolderPlus class="size-4" /> New project</Button>
    </PageHeader>
    <MasterDetail :detail-open="pane" back-label="Projects" @back="pane = false">
      <template #list>
        <p v-if="store.loaded.value && !store.projects.value.length" class="px-4 py-6 text-sm text-muted-foreground">No projects yet. A project keeps the instructions and files for one piece of work, so every chat in it starts with them.</p>
        <ListRow v-for="p in store.projects.value" :key="p.slug" :active="p.slug === store.selected.value" @click="choose(p.slug)">
          <span class="truncate text-sm font-medium">{{ p.name }}</span>
          <span v-if="p.description" class="truncate text-xs text-muted-foreground">{{ p.description }}</span>
          <span class="text-xs text-muted-foreground">{{ p.files }} {{ p.files === 1 ? 'file' : 'files' }}</span>
        </ListRow>
      </template>
      <template #detail>
        <div v-if="!detail" class="p-8 text-center text-sm text-muted-foreground">Pick a project, or make a new one.</div>
        <div v-else class="mx-auto w-full max-w-2xl space-y-6 p-4">
          <div class="space-y-3">
            <div class="space-y-1.5"><Label for="pname">Name</Label><Input id="pname" v-model="name" /></div>
            <div class="space-y-1.5"><Label for="pdesc">Description</Label><Input id="pdesc" v-model="description" placeholder="What this project is for" /></div>
            <div class="space-y-1.5">
              <Label for="pins">Instructions</Label>
              <Textarea id="pins" v-model="instructions" class="min-h-40" placeholder="How hi should work in this project: tone, rules, context. Every chat in the project starts with this." />
              <p class="text-xs text-muted-foreground">Long instructions are shortened when sent to the model (the first 6,000 characters are used).</p>
            </div>
            <div class="flex items-center gap-3"><Button :disabled="!dirty" @click="save">Save</Button><span class="text-sm text-muted-foreground" role="status">{{ message }}</span></div>
          </div>

          <section class="space-y-2">
            <div class="flex items-center justify-between">
              <h2 class="text-sm font-semibold">Files</h2>
              <Button variant="outline" size="sm" class="gap-1.5" @click="picker?.click()"><Upload class="size-4" /> Add files</Button>
              <input ref="picker" type="file" multiple class="sr-only" tabindex="-1" aria-hidden="true" @change="upload(($event.target as HTMLInputElement).files)" />
            </div>
            <p v-if="!detail.files.length" class="text-sm text-muted-foreground">No files. hi can open the ones you add when a chat in this project needs them.</p>
            <ul class="divide-y rounded-lg border">
              <li v-for="f in detail.files" :key="f.name" class="flex items-center gap-2 px-3 py-2 text-sm">
                <FileText class="size-4 shrink-0 text-muted-foreground" /><span class="min-w-0 flex-1 truncate">{{ f.name }}</span><span class="text-xs text-muted-foreground">{{ size(f.size) }}</span>
                <Button variant="ghost" size="icon" class="size-7" :aria-label="`Remove ${f.name}`" @click="removeFile(f.name)"><Trash2 class="size-3.5" /></Button>
              </li>
            </ul>
          </section>

          <section class="space-y-2">
            <div class="flex items-center justify-between">
              <h2 class="text-sm font-semibold">Chats</h2>
              <Button size="sm" class="gap-1.5" @click="emit('newChat', detail.slug)"><MessageSquarePlus class="size-4" /> New chat</Button>
            </div>
            <p v-if="!detail.chats.length" class="text-sm text-muted-foreground">No chats in this project yet.</p>
            <ul class="divide-y rounded-lg border">
              <li v-for="c in detail.chats" :key="c.id"><button class="flex w-full flex-col px-3 py-2 text-left hover:bg-accent/60" @click="emit('open', c.id)"><span class="truncate text-sm">{{ c.title }}</span><span class="text-xs text-muted-foreground">{{ c.turns }} {{ c.turns === 1 ? 'message' : 'messages' }}</span></button></li>
            </ul>
          </section>

          <div class="border-t pt-4"><Button variant="outline" class="gap-1.5 text-destructive" @click="doomed = true"><Trash2 class="size-4" /> Delete project</Button></div>
        </div>
      </template>
    </MasterDetail>

    <Dialog v-model:open="creating">
      <DialogContent>
        <DialogHeader><DialogTitle>New project</DialogTitle><DialogDescription>Give it a name. You can add instructions and files next.</DialogDescription></DialogHeader>
        <Input v-model="newName" placeholder="Project name" aria-label="Project name" autofocus @keydown.enter.prevent="newName.trim() && create()" />
        <DialogFooter><Button variant="outline" @click="creating = false">Cancel</Button><Button :disabled="!newName.trim()" @click="create">Create</Button></DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="doomed">
      <DialogContent>
        <DialogHeader><DialogTitle>Delete this project?</DialogTitle><DialogDescription>“{{ detail?.name }}”, its instructions and its files will be removed. Its chats are kept; they just stop belonging to a project.</DialogDescription></DialogHeader>
        <DialogFooter><Button variant="outline" @click="doomed = false">Cancel</Button><Button variant="destructive" @click="confirmDelete">Delete</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
