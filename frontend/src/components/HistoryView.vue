<!-- Read-only view of one day's logged conversation — reuses the same
     ConversationLogParser (lib/parseActivity.ts's own parseActivity(),
     which returns short summaries; here we want the FULL exchange, so
     this reads the raw log directly and renders it as-is rather than
     truncating). -->
<script setup lang="ts">
import { ref, watch } from 'vue'
import { fetchConversation } from '../backend'
import { renderMarkdown } from '../lib/markdown'

const props = defineProps<{ date: string }>()

const content = ref<string | null>(null)
const isLoading = ref(true)

async function load() {
  isLoading.value = true
  content.value = await fetchConversation(props.date)
  isLoading.value = false
}

watch(() => props.date, load, { immediate: true })
</script>

<template>
  <div class="history">
    <div class="header">{{ date }}</div>
    <div v-if="isLoading" class="status">Loading…</div>
    <div v-else-if="content" class="content markdown" v-html="renderMarkdown(content)"></div>
    <div v-else class="status error">Couldn't load this conversation.</div>
  </div>
</template>

<style scoped>
.history {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}
.header {
  font-family: var(--mono);
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  margin-bottom: 14px;
}
.status {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--text-faint);
}
.status.error {
  color: var(--rust);
}
/* .content's own typography now comes from the global .markdown class
   (lib/markdown.ts's rendered output). */
</style>
