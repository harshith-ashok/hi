<script setup lang="ts">
// Listens for the app's keyboard shortcuts and shows the help sheet. Lives inside SidebarProvider so it can open the sidebar.
import { useEventListener } from '@vueuse/core'
import { nextTick, ref, watch } from 'vue'
import { getJson } from '@/backend'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useSidebar } from '@/components/ui/sidebar'
import { allowedIn, display, find, OTHER_KEYS, SHORTCUTS, type ShortcutId } from '@/lib/shortcuts'

const emit = defineEmits<{ newChat: []; navigate: [view: 'settings'] }>()
const sidebar = useSidebar()
const help = ref(false)
const skills = ref<{ name: string; description: string }[]>([])

watch(help, async (open) => { if (open) skills.value = (await getJson<typeof skills.value>('/skills')) ?? [] })

async function focusSearch() {
  sidebar.setOpen(true)
  sidebar.setOpenMobile(true)
  await nextTick()
  setTimeout(() => document.querySelector<HTMLInputElement>('input[aria-label="Search chats"]')?.focus(), 50)
}

const actions: Record<ShortcutId, () => void> = {
  search: () => void focusSearch(),
  newChat: () => emit('newChat'),
  settings: () => emit('navigate', 'settings'),
  copyLast: () => {
    if (!window.getSelection()?.toString()) window.dispatchEvent(new CustomEvent('hi:copy-last'))
  },
  help: () => (help.value = !help.value),
}

// the message box's /help and /config commands
useEventListener(window, 'hi:help', () => (help.value = true))
useEventListener(window, 'hi:go', (e: Event) => { if ((e as CustomEvent).detail === 'settings') emit('navigate', 'settings') })

useEventListener(window, 'keydown', (e: KeyboardEvent) => {
  const shortcut = find(e)
  if (!shortcut || !allowedIn(shortcut, e.target)) return
  e.preventDefault()
  actions[shortcut.id]()
})
</script>

<template>
  <Dialog v-model:open="help">
    <DialogContent class="max-w-md">
      <DialogHeader>
        <DialogTitle>Shortcuts and commands</DialogTitle>
        <DialogDescription>Type <kbd class="rounded border px-1 font-mono text-xs">/</kbd> in the message box to run a skill.</DialogDescription>
      </DialogHeader>
      <ul class="space-y-1.5 text-sm">
        <li v-for="s in SHORTCUTS" :key="s.id" class="flex items-center justify-between gap-4"><span>{{ s.label }}</span><kbd class="rounded border px-1.5 py-0.5 font-mono text-xs text-muted-foreground">{{ display(s) }}</kbd></li>
        <li v-for="k in OTHER_KEYS" :key="k.keys" class="flex items-center justify-between gap-4"><span>{{ k.label }}</span><kbd class="rounded border px-1.5 py-0.5 font-mono text-xs text-muted-foreground">{{ k.keys }}</kbd></li>
      </ul>
      <div v-if="skills.length" class="max-h-40 overflow-y-auto border-t pt-3">
        <p class="mb-1.5 text-xs font-medium text-muted-foreground">Skills</p>
        <ul class="space-y-1 text-sm">
          <li v-for="s in skills" :key="s.name" class="flex items-baseline gap-2"><span class="font-mono text-xs">/{{ s.name }}</span><span class="truncate text-xs text-muted-foreground">{{ s.description }}</span></li>
        </ul>
      </div>
    </DialogContent>
  </Dialog>
</template>
