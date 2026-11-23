<script setup lang="ts">
import { Check, Columns2, Copy } from '@lucide/vue'
import { ref } from 'vue'
import { Button } from '@/components/ui/button'
import { isPage, useArtifact } from '@/composables/useArtifact'

const props = defineProps<{ lang: string; text: string; previewable?: boolean }>()
const { openInline } = useArtifact()
const copied = ref(false)

async function copy() {
  await navigator.clipboard?.writeText(props.text)
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}
</script>

<template>
  <div class="not-prose my-3 overflow-hidden rounded-lg border bg-muted/40">
    <div class="flex items-center justify-between border-b px-3 py-1 text-xs text-muted-foreground">
      <span class="font-mono">{{ lang || 'text' }}</span>
      <span class="flex items-center gap-1">
        <Button v-if="previewable && isPage(lang)" variant="ghost" size="sm" class="h-6 gap-1 px-2 text-xs" title="Show this page beside the chat" @click="openInline(text)"><Columns2 class="size-3" />Preview</Button>
        <Button variant="ghost" size="sm" class="h-6 gap-1 px-2 text-xs" @click="copy">
          <Check v-if="copied" class="size-3" /><Copy v-else class="size-3" />{{ copied ? 'Copied' : 'Copy' }}
        </Button>
      </span>
    </div>
    <pre class="overflow-x-auto p-3 font-mono text-[13px] leading-relaxed"><code>{{ text }}</code></pre>
  </div>
</template>
