<script setup lang="ts">
// A reply as the chat draws it: prose, code blocks with a copy button, and Mermaid blocks as real diagrams.
import { Workflow } from '@lucide/vue'
import { computed } from 'vue'
import CodeBlock from '@/components/content/CodeBlock.vue'
import MermaidDiagram from '@/components/content/MermaidDiagram.vue'
import { Skeleton } from '@/components/ui/skeleton'
import { segments } from '@/lib/markdown'

const props = defineProps<{ source: string; streaming?: boolean }>()
const parts = computed(() => segments(props.source))
</script>

<template>
  <div class="min-w-0">
    <template v-for="(part, i) in parts" :key="i">
      <div
        v-if="part.kind === 'html'"
        class="prose prose-sm max-w-none break-words dark:prose-invert prose-headings:font-semibold prose-pre:bg-muted prose-img:rounded-lg prose-table:block prose-table:overflow-x-auto prose-a:text-primary"
        v-html="part.html"
      />
      <CodeBlock v-else-if="part.kind === 'code'" :lang="part.lang" :text="part.text" />
      <MermaidDiagram v-else-if="part.closed || !streaming" :code="part.text" />
      <div v-else class="not-prose my-3 space-y-2 rounded-lg border p-4" role="status" aria-label="Drawing a diagram">
        <div class="flex items-center gap-2 text-xs text-muted-foreground"><Workflow class="size-3.5 animate-pulse" /> Drawing a diagram…</div>
        <Skeleton class="h-20 w-full" />
      </div>
    </template>
  </div>
</template>
