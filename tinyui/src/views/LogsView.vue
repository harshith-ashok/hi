<script setup lang="ts">
// The readable day-by-day conversation logs (hi/conversations/), from before sessions and for every persona.
import { Search } from '@lucide/vue'
import { computed, onMounted, ref } from 'vue'
import ListRow from '@/components/app/ListRow.vue'
import MasterDetail from '@/components/app/MasterDetail.vue'
import PageHeader from '@/components/app/PageHeader.vue'
import MarkdownContent from '@/components/content/MarkdownContent.vue'
import { Input } from '@/components/ui/input'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { getJson } from '@/backend'

const dates = ref<string[]>([])
const current = ref('')
const content = ref('')
const raw = ref(false)
const query = ref('')
const pane = ref(false)
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
  <div class="flex h-full min-h-0 flex-col">
    <PageHeader title="Daily logs" :subtitle="`${dates.length} days`" />
    <MasterDetail :detail-open="pane" back-label="All days" @back="pane = false">
      <template #list>
        <div class="relative p-3"><Search class="absolute left-5 top-5.5 size-4 text-muted-foreground" /><Input v-model="query" class="pl-8" placeholder="Filter by date" aria-label="Filter by date" spellcheck="false" /></div>
        <ListRow v-for="d in shown" :key="d" :active="d === current" @click="open(d)"><span class="text-sm">{{ d }}</span></ListRow>
        <p v-if="loaded && !shown.length" class="p-4 text-sm text-muted-foreground">{{ dates.length ? 'No days match.' : 'No conversation logs yet.' }}</p>
      </template>
      <template #detail>
        <div class="space-y-4 p-5">
          <div class="flex items-center gap-3">
            <div><h2 class="font-semibold">{{ current || 'No day chosen' }}</h2><p class="text-xs text-muted-foreground">vault/hi/conversations</p></div>
            <span class="grow" />
            <Tabs :model-value="raw ? 'md' : 'view'" @update:model-value="raw = $event === 'md'"><TabsList><TabsTrigger value="view">Transcript</TabsTrigger><TabsTrigger value="md">Markdown</TabsTrigger></TabsList></Tabs>
          </div>
          <pre v-if="raw" class="overflow-x-auto whitespace-pre-wrap rounded-lg border bg-muted/40 p-4 font-mono text-xs">{{ content }}</pre>
          <MarkdownContent v-else :source="content" />
        </div>
      </template>
    </MasterDetail>
  </div>
</template>
