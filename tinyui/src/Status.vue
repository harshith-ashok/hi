<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getJson } from './backend'

const blocks = ref<[string, Record<string, unknown>][]>([])
const briefing = ref('')
const updated = ref('')
const loading = ref(false)

async function load() {
  loading.value = true
  const [vitals, vault, today, b] = await Promise.all([
    getJson<Record<string, unknown>>('/vitals'),
    getJson<Record<string, unknown>>('/vault-stats'),
    getJson<Record<string, unknown>>('/today'),
    getJson<{ context: string; suggestion: string } | null>('/briefing'),
  ])
  blocks.value = [['System', vitals ?? {}], ['Vault', vault ?? {}], ['Today', today ?? {}]]
  briefing.value = b ? [b.context, b.suggestion].filter(Boolean).join('\n\n') : ''
  updated.value = new Date().toTimeString().slice(0, 8)
  loading.value = false
}

onMounted(load)
</script>

<template>
  <header class="top">
    <div><h1>Status</h1><span v-if="updated" class="sub">updated {{ updated }}</span></div>
    <div class="grow"></div>
    <button class="btn" :disabled="loading" @click="load">{{ loading ? 'Refreshing…' : 'Refresh' }}</button>
  </header>
  <div class="scroll">
    <div class="col">
      <section v-if="briefing" class="summary">
        <div class="sect-h"><h2>Briefing</h2></div>
        <pre>{{ briefing }}</pre>
      </section>
      <div class="cols">
        <section v-for="[title, data] in blocks" :key="title">
          <div class="sect-h"><h2>{{ title }}</h2></div>
          <div v-for="(value, key) in data" :key="key" class="kv"><span>{{ key }}</span><span>{{ value }}</span></div>
          <div v-if="!Object.keys(data).length" class="empty">no data</div>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.summary pre { padding-top: 10px; max-width: 64ch; }
</style>
