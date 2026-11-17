<script setup lang="ts">
// What the assistant has learned: its memory file and latest reflection, both plain Markdown in the vault.
import { Plus, X } from '@lucide/vue'
import { computed, onMounted, ref } from 'vue'
import PageHeader from '@/components/app/PageHeader.vue'
import MarkdownContent from '@/components/content/MarkdownContent.vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { getJson, postJson } from '@/backend'

const memory = ref('')
const reflection = ref('')
const loaded = ref(false)
const fresh = ref('')

// Bullets are the facts; headings group them.
const facts = computed(() => memory.value.split('\n').filter((l) => l.startsWith('- ')))
const clean = (line: string) => line.slice(2).replace(/\s*\(\d{4}-\d{2}-\d{2},.*\)$/, '')
const body = (text: string) => text.replace(/^---\n[\s\S]*?\n---\n/, '').trim()

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

onMounted(load)
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <PageHeader title="Memory" subtitle="vault/hi/memory/memory.md" />
    <div class="grid min-h-0 flex-1 gap-4 overflow-y-auto p-4 lg:grid-cols-2">
      <Card class="min-h-0">
        <CardHeader>
          <CardTitle>What hi has learned</CardTitle>
          <CardDescription>Edit or delete lines in Obsidian too.</CardDescription>
        </CardHeader>
        <CardContent class="space-y-3">
          <form class="flex gap-2" @submit.prevent="remember">
            <Input v-model="fresh" aria-label="Teach hi a fact" placeholder="Teach hi something…" spellcheck="false" />
            <Button type="submit" variant="secondary"><Plus class="size-4" /> Remember</Button>
          </form>
          <ul class="divide-y">
            <li v-for="line in facts" :key="line" class="flex items-start gap-2 py-2 text-sm">
              <span class="flex-1">{{ clean(line) }}</span>
              <Button variant="ghost" size="icon" class="size-7 shrink-0" :aria-label="`Forget: ${clean(line)}`" @click="forget(line)"><X class="size-3.5" /></Button>
            </li>
          </ul>
          <p v-if="!facts.length" class="text-sm text-muted-foreground">{{ loaded ? 'Nothing remembered yet.' : 'Loading…' }}</p>
        </CardContent>
      </Card>
      <Card class="min-h-0">
        <CardHeader>
          <CardTitle>Latest daily reflection</CardTitle>
          <CardDescription>vault/hi/reflections</CardDescription>
        </CardHeader>
        <CardContent>
          <MarkdownContent v-if="reflection" :source="reflection" />
          <p v-else class="text-sm text-muted-foreground">{{ loaded ? 'No reflection yet. One is written each day from the journal.' : '' }}</p>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
