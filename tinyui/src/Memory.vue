<script setup lang="ts">
// What the assistant has learned: its memory file and latest reflection, both plain Markdown in the vault.
import { computed, onMounted, ref } from 'vue'
import { getJson, postJson } from './backend'
import Markdown from './Markdown.vue'

const memory = ref('')
const reflection = ref('')
const loaded = ref(false)
const fresh = ref('')

// Bullets are the facts; headings group them. Everything else stays Markdown.
const facts = computed(() => memory.value.split('\n').filter((l) => l.startsWith('- ')))
const clean = (line: string) => line.slice(2).replace(/\s*\(\d{4}-\d{2}-\d{2},.*\)$/, '')

async function load() {
  const data = await getJson<{ memory: string; reflection: string }>('/memory')
  memory.value = body(data?.memory ?? '')
  reflection.value = body(data?.reflection ?? '')
  loaded.value = true
}

async function remember() {
  const text = fresh.value.trim()
  if (!text) return
  fresh.value = ''
  await postJson('/memory/add', { text })
  await load()
}

async function forget(line: string) {
  await postJson('/memory/forget', { text: line })
  await load()
}

const body = (text: string) => text.replace(/^---\n[\s\S]*?\n---\n/, '').trim()

onMounted(load)
</script>

<template>
  <header class="top"><div><h1>Memory</h1><span class="sub">vault/hi/memory/memory.md</span></div></header>
  <div class="scroll">
    <div class="col">
      <div class="cols">
        <section>
          <div class="sect-h"><h2>What hi has learned</h2><span>edit or delete lines in Obsidian</span></div>
          <form class="addrow" @submit.prevent="remember">
            <input v-model="fresh" class="field" aria-label="Teach hi a fact" placeholder="Teach hi something…" spellcheck="false" />
            <button class="btn" type="submit">Remember</button>
          </form>
          <div v-for="line in facts" :key="line" class="fact">
            <span class="tx">{{ clean(line) }}</span>
            <button class="btn quiet" :aria-label="`Forget: ${clean(line)}`" @click="forget(line)">Forget</button>
          </div>
          <div v-if="!facts.length" class="empty">{{ loaded ? 'Nothing remembered yet.' : 'loading…' }}</div>
        </section>
        <section>
          <div class="sect-h"><h2>Latest daily reflection</h2><span>vault/hi/reflections</span></div>
          <Markdown v-if="reflection" :source="reflection" class="prose" />
          <div v-else class="empty">{{ loaded ? 'No reflection yet. One is written each day from the journal.' : '' }}</div>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.fact { display: flex; align-items: baseline; gap: 14px; padding: 2px 0; }
.fact .tx { flex: 1; }
.prose { padding-top: 12px; max-width: 68ch; }
</style>
