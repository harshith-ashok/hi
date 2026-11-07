<script setup lang="ts">
// What the assistant has learned: its memory file and latest reflection, both plain Markdown in the vault.
import { onMounted, ref } from 'vue'
import { getJson } from './backend'
import Markdown from './Markdown.vue'

const memory = ref('')
const reflection = ref('')
const loaded = ref(false)

const body = (text: string) => text.replace(/^---\n[\s\S]*?\n---\n/, '').trim()

onMounted(async () => {
  const data = await getJson<{ memory: string; reflection: string }>('/memory')
  memory.value = body(data?.memory ?? '')
  reflection.value = body(data?.reflection ?? '')
  loaded.value = true
})
</script>

<template>
  <div class="memory">
    <div class="dim">memory · edit or delete lines in Obsidian: hi/memory/memory.md</div>
    <Markdown v-if="memory" :source="memory" />
    <div v-else class="dim">{{ loaded ? 'nothing remembered yet' : 'loading…' }}</div>
    <div class="dim head">latest reflection · hi/reflections/</div>
    <Markdown v-if="reflection" :source="reflection" />
    <div v-else class="dim">{{ loaded ? 'no reflection yet — one is written each day from the journal' : '' }}</div>
  </div>
</template>

<style scoped>
.memory { overflow-y: auto; padding-right: 8px; }
.head { margin-top: 24px; }
</style>
