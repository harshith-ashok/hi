<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { getJson, postJson, type Task } from './backend'

const procs = ref<Task[]>([])
const runs = ref<Task[]>([])
const selected = ref('')
const prompt = ref('')
const pane = ref(false)
const pick = (id: string) => ((selected.value = id), (pane.value = true))
const answers = ref<Record<string, string[]>>({})
let timer = 0

async function load() {
  procs.value = (await getJson<Task[]>('/background')) ?? []
  runs.value = (await getJson<Task[]>('/agents')) ?? []
}

const detail = () => [...procs.value, ...runs.value].find((t) => t.id === selected.value)

async function startAgent() {
  const text = prompt.value.trim()
  if (!text) return
  prompt.value = ''
  const run = await postJson<Task>('/agents', { prompt: text })
  await load()
  if (run) pick(run.id)
}

async function answer(run: Task) {
  await postJson(`/agents/${run.id}/answer`, { answers: (answers.value[run.id] ?? []).map((a) => a ?? '') })
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
  <header class="top">
    <div><h1>Tasks</h1><span class="sub">{{ procs.filter((p) => p.status === 'running').length }} running · {{ runs.filter((r) => r.status === 'clarifying').length }} waiting on you</span></div>
  </header>
  <div class="panes" :class="{ 'detail-open': pane }">
    <div class="list">
      <div class="list-scroll">
        <div class="day">Background</div>
        <button v-for="p in procs" :key="p.id" class="row-btn" :class="{ on: p.id === selected }" @click="pick(p.id)">
          <span class="t"><span>{{ p.command ?? p.id }}</span><span class="badge">{{ p.status }}</span></span>
          <span class="s">{{ p.id }}</span>
        </button>
        <div v-if="!procs.length" class="empty">none</div>
        <div class="day">Agents</div>
        <button v-for="r in runs" :key="r.id" class="row-btn" :class="{ on: r.id === selected }" @click="pick(r.id)">
          <span class="t"><span>{{ (r.prompt ?? r.id).slice(0, 40) }}</span><span class="badge" :class="{ hot: r.status === 'clarifying' }">{{ r.status }}</span></span>
          <span class="s">{{ r.id }}</span>
        </button>
        <div v-if="!runs.length" class="empty">none</div>
      </div>
      <form class="addrow" @submit.prevent="startAgent">
        <input v-model="prompt" class="field" aria-label="New agent goal" placeholder="Describe a new agent…" spellcheck="false" />
        <button class="btn" type="submit">+ Agent</button>
      </form>
    </div>
    <section class="detail-pane" aria-label="Task detail">
      <template v-if="detail()">
        <button class="back" @click="pane = false">All tasks</button>
        <div class="head">
          <div><h2>{{ detail()!.command ?? detail()!.prompt }}</h2><div class="meta">{{ detail()!.id }} · {{ detail()!.status }}</div></div>
          <button v-if="detail()!.command" class="btn danger" :disabled="detail()!.status !== 'running'" @click="stop(detail()!.id)">Stop</button>
        </div>
        <div v-if="detail()!.status === 'clarifying'" class="ask" role="group" aria-label="Questions from the agent">
          <span class="lbl">needs your answer</span>
          <label v-for="(q, i) in detail()!.questions" :key="i">
            <p>{{ q }}</p>
            <input v-model="(answers[detail()!.id] ??= [])[i]" class="field" spellcheck="false" />
          </label>
          <button class="btn primary" @click="answer(detail()!)">Answer</button>
        </div>
        <div v-if="detail()!.output_tail ?? detail()!.result ?? detail()!.error">
          <div class="lbl">{{ detail()!.command ? 'latest output' : 'result' }}</div>
          <pre class="tape result">{{ detail()!.output_tail ?? detail()!.result ?? detail()!.error }}</pre>
        </div>
      </template>
      <div v-else class="empty">Select a task.</div>
    </section>
  </div>
</template>

<style scoped>
.ask { border-left: 1px solid var(--ink); padding: 2px 0 2px 14px; display: flex; flex-direction: column; gap: 10px; }
.ask label { display: grid; gap: 2px; }
.ask p { font-weight: 600; max-width: 60ch; }
</style>
