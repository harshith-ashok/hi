<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getJson } from './backend'

const blocks = ref<[string, Record<string, unknown>][]>([])
const briefing = ref('')

async function load() {
  const [vitals, vault, today, b] = await Promise.all([
    getJson<Record<string, unknown>>('/vitals'),
    getJson<Record<string, unknown>>('/vault-stats'),
    getJson<Record<string, unknown>>('/today'),
    getJson<{ context: string; suggestion: string } | null>('/briefing'),
  ])
  blocks.value = [['system', vitals ?? {}], ['vault', vault ?? {}], ['today', today ?? {}]]
  briefing.value = b ? [b.context, b.suggestion].filter(Boolean).join('\n\n') : ''
}

onMounted(load)
</script>

<template>
  <div>
    <section v-for="[title, data] in blocks" :key="title">
      <div class="dim">{{ title }}</div>
      <div v-for="(value, key) in data" :key="key" class="row"><span class="dim">{{ key }}</span><span>{{ value }}</span></div>
    </section>
    <section v-if="briefing">
      <div class="dim">briefing</div>
      <pre>{{ briefing }}</pre>
    </section>
    <button @click="load">refresh</button>
  </div>
</template>

<style scoped>
section { margin-bottom: 20px; }
.row { display: flex; gap: 2ch; }
.row span:first-child { min-width: 22ch; }
pre { margin: 0; white-space: pre-wrap; font: inherit; }
button { background: none; border: 0; padding: 0; cursor: pointer; color: var(--accent); }
.dim { color: var(--dim); }
</style>
