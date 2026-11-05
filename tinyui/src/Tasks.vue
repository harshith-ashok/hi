<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { getJson, postJson, type Task } from './backend'

const procs = ref<Task[]>([])
const runs = ref<Task[]>([])
const selected = ref('')
const prompt = ref('')
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
  if (run) selected.value = run.id
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
  <div class="split">
    <nav>
      <span class="dim">background</span>
      <button v-for="p in procs" :key="p.id" :class="{ on: p.id === selected }" @click="selected = p.id">{{ p.id }} {{ p.status }} · {{ p.command }}</button>
      <span v-if="!procs.length" class="dim">none</span>
      <span class="dim gap">agents</span>
      <button v-for="r in runs" :key="r.id" :class="{ on: r.id === selected }" @click="selected = r.id">{{ r.id }} {{ r.status }} · {{ (r.prompt ?? '').slice(0, 40) }}</button>
      <span v-if="!runs.length" class="dim">none</span>
      <div class="new">
        <span class="accent">+</span>
        <input v-model="prompt" placeholder="new agent: describe a task" spellcheck="false" @keydown.enter="startAgent" />
      </div>
    </nav>
    <div class="detail">
      <template v-if="detail()">
        <div class="dim">{{ detail()!.command ?? detail()!.prompt }} — {{ detail()!.status }}</div>
        <button v-if="detail()!.command && detail()!.status === 'running'" class="err" @click="stop(detail()!.id)">stop</button>
        <template v-if="detail()!.status === 'clarifying'">
          <label v-for="(q, i) in detail()!.questions" :key="i">
            <span>{{ q }}</span>
            <input v-model="(answers[detail()!.id] ??= [])[i]" spellcheck="false" />
          </label>
          <button class="accent" @click="answer(detail()!)">answer</button>
        </template>
        <pre>{{ detail()!.output_tail ?? detail()!.result ?? detail()!.error ?? '' }}</pre>
      </template>
    </div>
  </div>
</template>

<style scoped>
.split { display: flex; gap: 32px; height: 100%; }
nav { display: flex; flex-direction: column; align-items: flex-start; overflow-y: auto; width: 42ch; }
nav button { background: none; border: 0; padding: 0; cursor: pointer; color: var(--fg); text-align: left; }
nav button:hover, nav button.on { color: var(--accent); }
.gap { margin-top: 16px; }
.new { margin-top: 16px; display: flex; gap: 1ch; width: 100%; }
input { background: none; border: 0; border-bottom: 1px solid var(--dim); outline: none; flex: 1; padding: 2px 0; }
input:focus { border-color: var(--accent); }
.detail { flex: 1; overflow-y: auto; display: flex; flex-direction: column; align-items: flex-start; gap: 8px; }
.detail label { display: grid; gap: 2px; width: 100%; }
.detail button { background: none; border: 0; padding: 0; cursor: pointer; }
pre { margin: 0; white-space: pre-wrap; word-break: break-word; font: inherit; }
.dim { color: var(--dim); }
.accent { color: var(--accent); }
.err { color: var(--err); }
</style>
