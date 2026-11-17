<script setup lang="ts">
import { Check, Copy } from '@lucide/vue'
import { ref } from 'vue'
import { Button } from '@/components/ui/button'

const props = defineProps<{ lang: string; text: string }>()
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
      <Button variant="ghost" size="sm" class="h-6 gap-1 px-2 text-xs" @click="copy">
        <Check v-if="copied" class="size-3" /><Copy v-else class="size-3" />{{ copied ? 'Copied' : 'Copy' }}
      </Button>
    </div>
    <pre class="overflow-x-auto p-3 font-mono text-[13px] leading-relaxed"><code>{{ text }}</code></pre>
  </div>
</template>
