<script setup lang="ts">
// A reply as the chat draws it: prose, code blocks with a copy button, and Mermaid blocks as real diagrams.
import { Box, Workflow } from '@lucide/vue'
import { computed } from 'vue'
import CodeBlock from '@/components/content/CodeBlock.vue'
import MermaidDiagram from '@/components/content/MermaidDiagram.vue'
import Viewer3D from '@/components/content/Viewer3D.vue'
import { Skeleton } from '@/components/ui/skeleton'
import { segments } from '@/lib/markdown'
import { parseScene } from '@/lib/scene3d'

const props = defineProps<{ source: string; streaming?: boolean }>()
const parts = computed(() => segments(props.source))
const sceneOf = (text: string) => parseScene(text)
</script>

<template>
  <div class="min-w-0">
    <template v-for="(part, i) in parts" :key="i">
      <div
        v-if="part.kind === 'html'"
        class="reply-prose prose prose-sm max-w-none break-words dark:prose-invert prose-headings:font-semibold prose-pre:bg-muted prose-img:rounded-lg prose-table:block prose-table:overflow-x-auto prose-a:text-primary"
        v-html="part.html"
      />
      <CodeBlock v-else-if="part.kind === 'code'" :lang="part.lang" :text="part.text" :previewable="!streaming" />
      <template v-else-if="part.kind === 'scene3d'">
        <template v-if="part.closed || !streaming">
          <Viewer3D v-if="'scene' in sceneOf(part.text)" :scene="(sceneOf(part.text) as { scene: import('@/lib/scene3d').SceneData }).scene" />
          <p v-else class="not-prose my-3 rounded-lg border border-destructive/40 p-3 text-xs text-destructive">{{ (sceneOf(part.text) as { error: string }).error }}</p>
        </template>
        <div v-else class="not-prose my-3 space-y-2 rounded-lg border p-4" role="status" aria-label="Building a 3D view">
          <div class="flex items-center gap-2 text-xs text-muted-foreground"><Box class="size-3.5 animate-pulse" /> Building a 3D view…</div>
          <Skeleton class="h-24 w-full" />
        </div>
      </template>
      <MermaidDiagram v-else-if="part.closed || !streaming" :code="part.text" />
      <div v-else class="not-prose my-3 space-y-2 rounded-lg border p-4" role="status" aria-label="Drawing a diagram">
        <div class="flex items-center gap-2 text-xs text-muted-foreground"><Workflow class="size-3.5 animate-pulse" /> Drawing a diagram…</div>
        <Skeleton class="h-20 w-full" />
      </div>
    </template>
  </div>
</template>
