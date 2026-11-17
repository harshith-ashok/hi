<script setup lang="ts">
// Background processes and on-demand agents. An agent that needs more detail asks its questions here.
import { Bot, MessageCircleQuestion, Plus, Square, Terminal } from '@lucide/vue'
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import ListRow from '@/components/app/ListRow.vue'
import MasterDetail from '@/components/app/MasterDetail.vue'
import PageHeader from '@/components/app/PageHeader.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { getJson, postJson, type Task } from '@/backend'

const procs = ref<Task[]>([])
const runs = ref<Task[]>([])
const selected = ref('')
const prompt = ref('')
const pane = ref(false)
const answers = reactive<Record<string, string[]>>({})
let timer = 0

const detail = computed(() => [...procs.value, ...runs.value].find((t) => t.id === selected.value))
const waiting = computed(() => runs.value.filter((r) => r.status === 'clarifying').length)
const pick = (id: string) => ((selected.value = id), (pane.value = true))

async function load() {
  procs.value = (await getJson<Task[]>('/background')) ?? []
  runs.value = (await getJson<Task[]>('/agents')) ?? []
}

async function startAgent() {
  const text = prompt.value.trim()
  if (!text) return
  prompt.value = ''
  const run = await postJson<Task>('/agents', { prompt: text })
  await load()
  if (run) pick(run.id)
}

async function answer(run: Task) {
  await postJson(`/agents/${run.id}/answer`, { answers: (answers[run.id] ?? []).map((a) => a ?? '') })
  await load()
}

async function stop(id: string) {
  await postJson(`/background/${id}/stop`)
  await load()
}

onMounted(() => {
  void load()
  timer = window.setInterval(load, 2000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <PageHeader title="Tasks" :subtitle="`${procs.filter((p) => p.status === 'running').length} running · ${waiting} waiting on you`" />
    <MasterDetail :detail-open="pane" back-label="All tasks" @back="pane = false">
      <template #list>
        <div class="px-4 pb-1 pt-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">Background</div>
        <ListRow v-for="p in procs" :key="p.id" :active="p.id === selected" @click="pick(p.id)">
          <span class="flex items-center gap-2 text-sm"><Terminal class="size-3.5 shrink-0 text-muted-foreground" /><span class="truncate font-mono text-xs">{{ p.command ?? p.id }}</span><Badge variant="outline" class="ml-auto">{{ p.status }}</Badge></span>
        </ListRow>
        <p v-if="!procs.length" class="px-4 py-3 text-sm text-muted-foreground">None.</p>
        <div class="px-4 pb-1 pt-4 text-xs font-medium uppercase tracking-wide text-muted-foreground">Agents</div>
        <ListRow v-for="r in runs" :key="r.id" :active="r.id === selected" @click="pick(r.id)">
          <span class="flex items-center gap-2 text-sm"><Bot class="size-3.5 shrink-0 text-muted-foreground" /><span class="truncate">{{ (r.prompt ?? r.id).slice(0, 40) }}</span><Badge :variant="r.status === 'clarifying' ? 'default' : 'outline'" class="ml-auto">{{ r.status }}</Badge></span>
        </ListRow>
        <p v-if="!runs.length" class="px-4 py-3 text-sm text-muted-foreground">None.</p>
        <form class="mt-auto flex gap-2 border-t p-3" @submit.prevent="startAgent">
          <Input v-model="prompt" aria-label="New agent goal" placeholder="Describe a new agent…" spellcheck="false" />
          <Button type="submit" size="icon" aria-label="Start agent"><Plus class="size-4" /></Button>
        </form>
      </template>
      <template #detail>
        <div v-if="detail" class="space-y-4 p-5">
          <div class="flex items-start gap-3">
            <div class="min-w-0"><h2 class="break-words font-semibold">{{ detail.command ?? detail.prompt }}</h2><p class="text-xs text-muted-foreground">{{ detail.id }} · {{ detail.status }}</p></div>
            <span class="grow" />
            <Button v-if="detail.command" variant="destructive" size="sm" :disabled="detail.status !== 'running'" @click="stop(detail.id)"><Square class="size-3.5" /> Stop</Button>
          </div>
          <form v-if="detail.status === 'clarifying'" class="space-y-3 rounded-lg border border-info/40 bg-info/5 p-4" aria-label="Questions from the agent" @submit.prevent="answer(detail)">
            <div class="flex items-center gap-2 text-sm font-medium"><MessageCircleQuestion class="size-4 text-info" /> Needs your answer</div>
            <div v-for="(q, i) in detail.questions" :key="i" class="space-y-1.5">
              <Label :for="`a${i}`" class="text-sm font-normal">{{ q }}</Label>
              <Input :id="`a${i}`" v-model="(answers[detail.id] ??= [])[i]" spellcheck="false" />
            </div>
            <Button type="submit" size="sm">Answer</Button>
          </form>
          <div v-if="detail.output_tail ?? detail.result ?? detail.error">
            <div class="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">{{ detail.command ? 'Latest output' : 'Result' }}</div>
            <pre class="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-lg border bg-muted/40 p-3 font-mono text-xs">{{ detail.output_tail ?? detail.result ?? detail.error }}</pre>
          </div>
        </div>
        <p v-else class="p-5 text-sm text-muted-foreground">Select a task.</p>
      </template>
    </MasterDetail>
  </div>
</template>
