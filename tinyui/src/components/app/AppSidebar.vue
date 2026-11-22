<script setup lang="ts">
import { Archive, Brain, Folder, Inbox, ListChecks, MoreHorizontal, Moon, Pencil, Pin, PinOff, Plus, ScrollText, Search, Settings, Sun, SunMoon, Trash2, Activity, X } from '@lucide/vue'
import { computed, nextTick, onMounted, ref, watch, type Component } from 'vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupContent, SidebarGroupLabel, SidebarHeader, SidebarMenu,
  SidebarMenuAction, SidebarMenuBadge, SidebarMenuButton, SidebarMenuItem, SidebarRail,
} from '@/components/ui/sidebar'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useProjects } from '@/composables/useProjects'
import { useSessions, type SessionInfo } from '@/composables/useSessions'
import { useStatus } from '@/composables/useStatus'
import { useTheme } from '@/composables/useTheme'
import type { View } from '@/lib/views'

const props = defineProps<{ view: View }>()
const emit = defineEmits<{ navigate: [view: View]; open: [id: string]; fresh: [] }>()

const sessions = useSessions()
const projectStore = useProjects()
onMounted(() => void projectStore.refresh())
function openProject(slug: string) {
  projectStore.selected.value = slug
  emit('navigate', 'projects')
}
const status = useStatus()
const { theme, cycle } = useTheme()

const nav = computed<{ view: View; label: string; icon: Component; badge: number }[]>(() => [
  { view: 'projects', label: 'Projects', icon: Folder, badge: 0 },
  { view: 'inbox', label: 'Inbox', icon: Inbox, badge: status.waitingActions.value },
  { view: 'tasks', label: 'Tasks', icon: ListChecks, badge: status.activeTasks.value },
  { view: 'memory', label: 'Memory', icon: Brain, badge: 0 },
  { view: 'logs', label: 'Daily logs', icon: ScrollText, badge: 0 },
  { view: 'status', label: 'Status', icon: Activity, badge: 0 },
  { view: 'settings', label: 'Settings', icon: Settings, badge: 0 },
])

// search: debounced, over titles and what was said
let timer = 0
watch(sessions.query, () => {
  clearTimeout(timer)
  timer = window.setTimeout(() => void sessions.refresh(), 250)
})

// rename in place
const renaming = ref('')
const draft = ref('')
const renameInput = ref<InstanceType<typeof Input>[] | InstanceType<typeof Input>>()
async function startRename(s: SessionInfo) {
  renaming.value = s.id
  draft.value = s.title
  await nextTick()
  const comp = Array.isArray(renameInput.value) ? renameInput.value[0] : renameInput.value
  const el = comp?.$el as HTMLInputElement | undefined // the component's root is the <input>
  el?.focus()
  el?.select()
}
async function commitRename() {
  const id = renaming.value
  renaming.value = ''
  if (id && draft.value.trim()) await sessions.rename(id, draft.value.trim())
}

// delete with a confirmation
const doomed = ref<SessionInfo | null>(null)
async function confirmDelete() {
  const s = doomed.value
  doomed.value = null
  if (!s) return
  const wasOpen = sessions.currentId.value === s.id
  if (await sessions.remove(s.id) && wasOpen) emit('fresh')
}

const ThemeIcon = computed(() => ({ auto: SunMoon, light: Sun, dark: Moon })[theme.value])
const open = (id: string) => emit('open', id)
const isActive = (id: string) => props.view === 'chat' && sessions.currentId.value === id
</script>

<template>
  <Sidebar>
    <SidebarHeader class="gap-3 p-3">
      <div class="flex items-center gap-2">
        <div class="flex size-7 items-center justify-center rounded-md bg-primary text-xs font-bold text-primary-foreground">hi</div>
        <span class="text-sm font-semibold">hi</span>
        <Tooltip>
          <TooltipTrigger as-child>
            <span class="ml-1 flex items-center gap-1.5 text-xs text-muted-foreground" role="status">
              <span :class="['size-2 rounded-full', status.online.value ? 'bg-success' : 'bg-destructive']" />{{ status.online.value ? 'online' : 'offline' }}
            </span>
          </TooltipTrigger>
          <TooltipContent>{{ status.online.value ? `${status.host.value} · ${status.model.value}` : 'The backend is not answering. Run `hi` to start it.' }}</TooltipContent>
        </Tooltip>
        <span class="grow" />
        <Tooltip><TooltipTrigger as-child><Button variant="ghost" size="icon" class="size-8" :aria-label="`Theme: ${theme}`" @click="cycle"><component :is="ThemeIcon" class="size-4" /></Button></TooltipTrigger><TooltipContent>Theme: {{ theme }}</TooltipContent></Tooltip>
      </div>
      <Button class="w-full justify-start gap-2" @click="emit('fresh')"><Plus class="size-4" /> New chat</Button>
      <div class="relative">
        <Search class="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
        <Input v-model="sessions.query.value" class="h-9 pl-8 pr-8" placeholder="Search chats" aria-label="Search chats" spellcheck="false" />
        <button v-if="sessions.query.value" class="absolute right-2 top-2.5 text-muted-foreground hover:text-foreground" aria-label="Clear search" @click="sessions.query.value = ''"><X class="size-4" /></button>
      </div>
    </SidebarHeader>

    <SidebarContent>
      <SidebarGroup v-if="projectStore.projects.value.length">
        <SidebarGroupLabel>Projects</SidebarGroupLabel>
        <SidebarGroupContent>
          <SidebarMenu>
            <SidebarMenuItem v-for="p in projectStore.projects.value" :key="p.slug">
              <SidebarMenuButton :is-active="view === 'projects' && projectStore.selected.value === p.slug" :tooltip="p.name" @click="openProject(p.slug)"><Folder /><span class="truncate">{{ p.name }}</span></SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>
      <SidebarGroup v-for="group in sessions.grouped.value" :key="group.name">
        <SidebarGroupLabel>{{ group.name }}</SidebarGroupLabel>
        <SidebarGroupContent>
          <SidebarMenu>
            <SidebarMenuItem v-for="s in group.items" :key="s.id">
              <Input v-if="renaming === s.id" ref="renameInput" v-model="draft" class="h-8" aria-label="Chat title" @keydown.enter.prevent="commitRename" @keydown.esc.prevent="renaming = ''" @blur="commitRename" />
              <template v-else>
                <SidebarMenuButton :is-active="isActive(s.id)" :tooltip="s.title" class="h-auto flex-col items-start gap-0 py-1.5" @click="open(s.id)">
                  <span class="flex w-full items-center gap-1.5"><Pin v-if="s.pinned" class="size-3 shrink-0 text-muted-foreground" /><span class="truncate">{{ s.title }}</span></span>
                  <span v-if="s.snippet" class="w-full truncate text-xs font-normal text-muted-foreground">{{ s.snippet }}</span>
                </SidebarMenuButton>
                <DropdownMenu>
                  <DropdownMenuTrigger as-child><SidebarMenuAction show-on-hover aria-label="Chat actions"><MoreHorizontal /></SidebarMenuAction></DropdownMenuTrigger>
                  <DropdownMenuContent side="right" align="start">
                    <DropdownMenuItem @select="startRename(s)"><Pencil class="size-4" /> Rename</DropdownMenuItem>
                    <DropdownMenuItem @select="sessions.pin(s.id, !s.pinned)"><component :is="s.pinned ? PinOff : Pin" class="size-4" /> {{ s.pinned ? 'Unpin' : 'Pin' }}</DropdownMenuItem>
                    <DropdownMenuItem @select="sessions.archive(s.id)"><Archive class="size-4" /> Archive</DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem variant="destructive" @select="doomed = s"><Trash2 class="size-4" /> Delete</DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </template>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>
      <p v-if="sessions.loaded.value && !sessions.grouped.value.length" class="px-4 py-6 text-center text-sm text-muted-foreground">
        {{ sessions.query.value ? 'No chats match.' : 'No chats yet. Say hi.' }}
      </p>
    </SidebarContent>

    <SidebarFooter class="border-t p-2">
      <SidebarMenu>
        <SidebarMenuItem v-for="n in nav" :key="n.view">
          <SidebarMenuButton :is-active="view === n.view" @click="emit('navigate', n.view)"><component :is="n.icon" /><span>{{ n.label }}</span></SidebarMenuButton>
          <SidebarMenuBadge v-if="n.badge"><Badge class="h-5 min-w-5 justify-center px-1.5">{{ n.badge }}</Badge></SidebarMenuBadge>
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarFooter>
    <SidebarRail />

    <Dialog :open="!!doomed" @update:open="(v: boolean) => !v && (doomed = null)">
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete this chat?</DialogTitle>
          <DialogDescription>“{{ doomed?.title }}” and everything said in it will be removed. This cannot be undone.</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" @click="doomed = null">Cancel</Button>
          <Button variant="destructive" @click="confirmDelete">Delete</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </Sidebar>
</template>
