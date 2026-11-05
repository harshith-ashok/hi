<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getJson } from './backend'

const dates = ref<string[]>([])
const current = ref('')
const content = ref('')

async function open(date: string) {
  current.value = date
  content.value = (await getJson<{ content: string }>(`/conversations/${date}`))?.content ?? '(could not load)'
}

onMounted(async () => {
  dates.value = [...((await getJson<string[]>('/conversations')) ?? [])].reverse()
  if (dates.value.length) void open(dates.value[0])
})
</script>

<template>
  <div class="split">
    <nav>
      <button v-for="d in dates" :key="d" :class="{ on: d === current }" @click="open(d)">{{ d }}</button>
      <span v-if="!dates.length" class="dim">no conversations yet</span>
    </nav>
    <pre>{{ content }}</pre>
  </div>
</template>

<style scoped>
.split { display: flex; gap: 32px; height: 100%; }
nav { display: flex; flex-direction: column; align-items: flex-start; overflow-y: auto; min-width: 14ch; }
nav button { background: none; border: 0; padding: 0; cursor: pointer; color: var(--dim); }
nav button:hover, nav button.on { color: var(--accent); }
pre { flex: 1; margin: 0; white-space: pre-wrap; word-break: break-word; overflow-y: auto; font: inherit; }
.dim { color: var(--dim); }
</style>
