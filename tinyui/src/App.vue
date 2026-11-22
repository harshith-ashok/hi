<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import AppSidebar from '@/components/app/AppSidebar.vue'
import ShortcutsHost from '@/components/app/ShortcutsHost.vue'
import ChatView from '@/components/chat/ChatView.vue'
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { useProjects } from '@/composables/useProjects'
import { useSessions } from '@/composables/useSessions'
import type { View } from '@/lib/views'
import { unlockAudio } from '@/voice'
import InboxView from '@/views/InboxView.vue'
import LogsView from '@/views/LogsView.vue'
import MemoryView from '@/views/MemoryView.vue'
import ProjectsView from '@/views/ProjectsView.vue'
import SettingsView from '@/views/SettingsView.vue'
import StatusView from '@/views/StatusView.vue'
import TasksView from '@/views/TasksView.vue'

const sessions = useSessions()
const projects = useProjects()
const view = ref<View>(window.location.hash.startsWith('#/inbox') ? 'inbox' : 'chat') // a link from the menu bar island

const openSession = (id: string) => {
  view.value = 'chat'
  sessions.select(id)
}
const newChat = () => {
  view.value = 'chat'
  projects.startIn.value = ''
  sessions.select('')
}
const chatIn = (slug: string) => {  // "New chat" on a project page: the chat is made inside that project
  view.value = 'chat'
  sessions.select('')
  projects.startIn.value = slug
}

watch(view, (v) => (document.title = v === 'chat' ? 'hi' : `hi · ${v}`))
onMounted(() => {
  window.addEventListener('pointerdown', unlockAudio, { once: true }) // lets later spoken replies play
  window.addEventListener('keydown', unlockAudio, { once: true })
})
</script>

<template>
  <TooltipProvider :delay-duration="300">
    <SidebarProvider class="h-svh">
      <ShortcutsHost @new-chat="newChat" @navigate="view = $event" />
      <AppSidebar :view="view" @navigate="view = $event" @open="openSession" @fresh="newChat" />
      <SidebarInset class="h-svh min-w-0 overflow-hidden">
        <ChatView v-show="view === 'chat'" :active="view === 'chat'" />
        <InboxView v-if="view === 'inbox'" />
        <ProjectsView v-else-if="view === 'projects'" @open="openSession" @new-chat="chatIn" />
        <TasksView v-else-if="view === 'tasks'" />
        <MemoryView v-else-if="view === 'memory'" />
        <LogsView v-else-if="view === 'logs'" />
        <StatusView v-else-if="view === 'status'" />
        <SettingsView v-else-if="view === 'settings'" />
      </SidebarInset>
    </SidebarProvider>
    <Toaster position="bottom-right" rich-colors />
  </TooltipProvider>
</template>
