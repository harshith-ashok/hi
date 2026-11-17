<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getHealth, getJson } from './backend'

const blocks = ref<[string, Record<string, unknown>][]>([])
interface Health {
  ok: boolean
  deps: Record<string, { ok: boolean; error: string; since: number }>
  jobs?: Record<string, { last_run: number }>
  timezone?: string
  pending_proposals?: number
  latency?: Record<string, { runs: number; avg_seconds: number; avg_first_token_s: number | null }>
}
const health = ref<Health | null>(null)
const briefing = ref('')
const updated = ref('')
const loading = ref(false)

async function load() {
  loading.value = true
  health.value = await getHealth<Health>()
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
      <section v-if="health" aria-label="Health">
        <div class="sect-h"><h2>Health</h2></div>
        <div v-for="(d, name) in health.deps" :key="name" class="kv" :class="{ bad: !d.ok }">
          <span>{{ name }}</span>
          <span>{{ d.ok ? 'ok' : `down: ${d.error}` }}<template v-if="health.jobs?.[String(name).replace('job:', '')]"> · last ran {{ new Date(health.jobs[String(name).replace('job:', '')].last_run * 1000).toTimeString().slice(0, 8) }}</template></span>
        </div>
        <div class="kv"><span>timezone</span><span>{{ health.timezone }}</span></div>
        <div class="kv"><span>actions waiting</span><span>{{ health.pending_proposals ?? 0 }}</span></div>
        <div v-for="(l, origin) in health.latency ?? {}" :key="origin" class="kv">
          <span>{{ origin }} turns</span>
          <span>{{ l.runs }} · avg {{ l.avg_seconds }}s<template v-if="l.avg_first_token_s !== null"> · first word {{ l.avg_first_token_s }}s</template></span>
        </div>
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
