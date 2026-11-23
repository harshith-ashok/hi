<script setup lang="ts">
// An artifact a reply wrote, as a card in the reply; clicking it opens the artifact beside the chat.
import { Code2, FileText, Globe, Image, Loader2, Workflow } from '@lucide/vue'
import { computed, type Component } from 'vue'
import { useArtifact, type ArtifactKind, type SavedArtifact } from '@/composables/useArtifact'
import { useSessions } from '@/composables/useSessions'

const props = defineProps<{ title: string; kind: ArtifactKind; lang: string; text: string; writing?: boolean; saved?: SavedArtifact }>()
const { openSaved, openInline, shown } = useArtifact()
const sessions = useSessions()

const KIND: Record<ArtifactKind, { label: string; icon: Component }> = {
  html: { label: 'Web page', icon: Globe }, svg: { label: 'Image', icon: Image }, markdown: { label: 'Document', icon: FileText },
  mermaid: { label: 'Diagram', icon: Workflow }, code: { label: 'Code', icon: Code2 },
}
const meta = computed(() => KIND[props.kind])
const open = computed(() => !!props.saved && shown.value?.slug === props.saved.slug && shown.value?.version === props.saved.version)

async function show() {
  const session = sessions.currentId.value
  if (props.saved && session && (await openSaved(session, props.saved.slug, props.saved.version))) return
  openInline(props.text, props.title)  // not saved (an old chat, or no session): show the block as it is
}
</script>

<template>
  <button type="button" class="not-prose my-3 flex w-full items-center gap-3 rounded-xl border bg-card p-3 text-left transition-colors hover:bg-accent disabled:cursor-wait" :class="open && 'border-primary'" :disabled="writing" :aria-label="`Open ${title}`" @click="show">
    <span class="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground"><Loader2 v-if="writing" class="size-5 animate-spin" /><component :is="meta.icon" v-else class="size-5" /></span>
    <span class="min-w-0 flex-1">
      <span class="block truncate text-sm font-medium">{{ title }}</span>
      <span class="block text-xs text-muted-foreground">{{ writing ? 'Writing…' : meta.label }}<template v-if="saved && !writing"> · version {{ saved.version }}</template></span>
    </span>
  </button>
</template>
