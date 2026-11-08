<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getJson } from './backend'
import Markdown from './Markdown.vue'

const dates = ref<string[]>([])
const current = ref('')
const content = ref('')
const raw = ref(false)
const query = ref('')
const pane = ref(false) // narrow screens: list or detail, not both
const loaded = ref(false)

const shown = computed(() => dates.value.filter((d) => d.includes(query.value.trim())))

async function open(date: string) {
  current.value = date
  pane.value = true
  content.value = (await getJson<{ content: string }>(`/conversations/${date}`))?.content ?? '(could not load)'
}

onMounted(async () => {
  dates.value = [...((await getJson<string[]>('/conversations')) ?? [])].reverse()
  loaded.value = true
  if (dates.value.length) {
    await open(dates.value[0])
    pane.value = false
  }
})
</script>

<template>
  <header class="top">
    <div><h1>History</h1><span class="sub">{{ dates.length }} days</span></div>
    <div class="grow"></div>
    <label class="search"><span class="dim">/</span><input v-model="query" placeholder="Filter by date" aria-label="Filter by date" spellcheck="false" /></label>
  </header>
  <div class="panes" :class="{ 'detail-open': pane }">
    <div class="list">
      <div class="list-scroll">
        <button v-for="d in shown" :key="d" class="row-btn" :class="{ on: d === current }" @click="open(d)"><span class="t">{{ d }}</span></button>
        <div v-if="loaded && !shown.length" class="empty">{{ dates.length ? 'No days match.' : 'No conversations yet.' }}</div>
      </div>
    </div>
    <section class="detail-pane" aria-label="Conversation">
      <button class="back" @click="pane = false">All days</button>
      <div class="head"><div><h2>{{ current || '—' }}</h2><div class="meta">vault/hi/conversations</div></div></div>
      <div class="tabs" role="tablist">
        <button role="tab" :class="{ on: !raw }" @click="raw = false">Transcript</button>
        <button role="tab" :class="{ on: raw }" @click="raw = true">Markdown</button>
      </div>
      <pre v-if="raw" class="tape">{{ content }}</pre>
      <Markdown v-else :source="content" class="transcript" />
    </section>
  </div>
</template>

<style scoped>
.search { display: flex; align-items: baseline; gap: 8px; }
.search input { border: 0; border-bottom: 1px solid var(--line); background: transparent; outline: none; min-width: 180px; height: 30px; font-size: 12.5px; }
.search input:focus { border-bottom-color: var(--ink); }
.transcript { max-width: 68ch; }
</style>
