<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { deleteJson, getJson, postJson } from './backend'
import Markdown from './Markdown.vue'

interface Report { id: string; headline: string; origin: string; priority: string; created: string; body?: string }
interface Proposal { id: string; tool: string; args: Record<string, unknown>; status: string; origin: string; summary: string; result: string; reason: string; created_at: number }
interface Run { slot: string; status: string; error?: string; report?: string }
interface Schedule { id: string; when: string; enabled: boolean; kind: string; tier: string; deliver: string; prompt: string; next: string[]; runs: Run[] }

const TABS = ['reports', 'actions', 'schedules'] as const
const tab = ref<(typeof TABS)[number]>('reports')
const reports = ref<Report[]>([])
const proposals = ref<Proposal[]>([])
const schedules = ref<Schedule[]>([])
const scheduleErrors = ref<string[]>([])
const selected = ref('')
const report = ref<Report | null>(null)
const pane = ref(false)
const busy = ref('')
const message = ref('')
let timer = 0

const waiting = computed(() => proposals.value.filter((p) => p.status === 'created'))
const proposal = computed(() => proposals.value.find((p) => p.id === selected.value))
const schedule = computed(() => schedules.value.find((s) => s.id === selected.value))

async function load() {
  reports.value = (await getJson<Report[]>('/reports')) ?? reports.value
  proposals.value = (await getJson<Proposal[]>('/proposals')) ?? proposals.value
  const s = await getJson<{ schedules: Schedule[]; errors: string[] }>('/schedules')
  if (s) {
    schedules.value = s.schedules
    scheduleErrors.value = s.errors
  }
}

async function open(id: string) {
  selected.value = id
  pane.value = true
  message.value = ''
  if (tab.value === 'reports') report.value = await getJson<Report>(`/reports/${id}`)
}

function switchTab(next: (typeof TABS)[number]) {
  tab.value = next
  selected.value = ''
  report.value = null
  pane.value = false
}

async function approve(p: Proposal) {
  busy.value = p.id
  const out = await postJson<{ status: string; result: string }>(`/proposals/${p.id}/approve`)
  message.value = out ? `${out.status}: ${out.result}` : 'Could not approve (already answered?)'
  busy.value = ''
  await load()
}

async function deny(p: Proposal) {
  busy.value = p.id
  await postJson(`/proposals/${p.id}/deny`)
  busy.value = ''
  await load()
}

async function toggle(s: Schedule) {
  await postJson(`/schedules/${s.id}/toggle`)
  await load()
}

async function runNow(s: Schedule) {
  const out = await postJson<{ message: string }>(`/schedules/${s.id}/run`)
  message.value = out?.message ?? 'Could not start it.'
  await load()
}

async function remove(s: Schedule) {
  if (!window.confirm(`Delete the schedule "${s.id}"?`)) return
  await deleteJson(`/schedules/${s.id}`)
  selected.value = ''
  pane.value = false
  await load()
}

const when = (ts: number) => new Date(ts * 1000).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' })

onMounted(async () => {
  await load()
  const link = /^#\/inbox\/(.+)$/.exec(window.location.hash) // a link from the island: open that report
  if (link) await open(decodeURIComponent(link[1]))
  timer = window.setInterval(load, 5000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <header class="top">
    <div><h1>Inbox</h1><span class="sub">{{ waiting.length }} waiting on you · {{ reports.length }} reports · {{ schedules.length }} schedules</span></div>
  </header>
  <div class="tabs" role="tablist" aria-label="Inbox sections">
    <button v-for="t in TABS" :key="t" role="tab" :class="{ on: t === tab }" :aria-selected="t === tab" @click="switchTab(t)">
      {{ t }}<span v-if="t === 'actions' && waiting.length" class="count">{{ waiting.length }}</span>
    </button>
  </div>
  <div class="panes" :class="{ 'detail-open': pane }">
    <div class="list">
      <div class="list-scroll">
        <template v-if="tab === 'reports'">
          <button v-for="r in reports" :key="r.id" class="row-btn" :class="{ on: r.id === selected }" @click="open(r.id)">
            <span class="t"><span>{{ r.headline }}</span><span class="badge">{{ r.origin }}</span></span>
            <span class="s">{{ r.created.slice(0, 16).replace('T', ' ') }}</span>
          </button>
          <div v-if="!reports.length" class="empty">Nothing yet. Reports from schedules, the heartbeat and the drop folder appear here.</div>
        </template>
        <template v-else-if="tab === 'actions'">
          <button v-for="p in proposals" :key="p.id" class="row-btn" :class="{ on: p.id === selected }" @click="open(p.id)">
            <span class="t"><span>{{ p.summary }}</span><span class="badge" :class="{ hot: p.status === 'created' }">{{ p.status === 'created' ? 'waiting' : p.status }}</span></span>
            <span class="s">{{ p.id }} · {{ p.origin }} · {{ when(p.created_at) }}</span>
          </button>
          <div v-if="!proposals.length" class="empty">Nothing is waiting for approval.</div>
        </template>
        <template v-else>
          <button v-for="s in schedules" :key="s.id" class="row-btn" :class="{ on: s.id === selected }" @click="open(s.id)">
            <span class="t"><span>{{ s.id }}</span><span class="badge">{{ s.enabled ? s.when : 'paused' }}</span></span>
            <span class="s">next {{ s.next[0] ?? 'never' }}</span>
          </button>
          <div v-for="e in scheduleErrors" :key="e" class="empty">⚠ {{ e }}</div>
          <div v-if="!schedules.length && !scheduleErrors.length" class="empty">No schedules. Ask hi: “every weekday at 8 brief me”.</div>
        </template>
      </div>
    </div>

    <section class="detail-pane" aria-label="Detail">
      <button class="back" @click="pane = false">Back</button>

      <template v-if="tab === 'reports' && report">
        <div class="head"><div><h2>{{ report.headline }}</h2><div class="meta">{{ report.origin }} · {{ report.created }}</div></div></div>
        <Markdown :source="report.body ?? ''" />
      </template>

      <template v-else-if="tab === 'actions' && proposal">
        <div class="head">
          <div><h2>{{ proposal.tool }}</h2><div class="meta">{{ proposal.id }} · {{ proposal.origin }} · {{ proposal.status }}</div></div>
          <div v-if="proposal.status === 'created'" class="actions">
            <button class="btn primary" :disabled="busy === proposal.id" @click="approve(proposal)">Approve and run</button>
            <button class="btn quiet" :disabled="busy === proposal.id" @click="deny(proposal)">Deny</button>
          </div>
        </div>
        <div class="lbl">exactly what will run</div>
        <pre class="tape result">{{ proposal.tool }}({{ JSON.stringify(proposal.args, null, 2) }})</pre>
        <p v-if="proposal.reason" class="meta">{{ proposal.reason }}</p>
        <div v-if="proposal.result"><div class="lbl">result</div><pre class="tape result">{{ proposal.result }}</pre></div>
        <p v-if="message" class="meta" role="status">{{ message }}</p>
      </template>

      <template v-else-if="tab === 'schedules' && schedule">
        <div class="head">
          <div><h2>{{ schedule.id }}</h2><div class="meta">{{ schedule.kind }} · {{ schedule.when }} · {{ schedule.tier }} · {{ schedule.deliver }}</div></div>
          <div class="actions">
            <button class="btn" @click="runNow(schedule)">Run now</button>
            <button class="btn" @click="toggle(schedule)">{{ schedule.enabled ? 'Pause' : 'Resume' }}</button>
            <button class="btn danger" @click="remove(schedule)">Delete</button>
          </div>
        </div>
        <pre class="tape result">{{ schedule.prompt }}</pre>
        <div class="lbl">next</div>
        <div class="meta">{{ schedule.next.join(' · ') || 'never' }}</div>
        <div v-if="schedule.runs.length" class="lbl">recent runs</div>
        <div v-for="r in schedule.runs" :key="r.slot + r.status" class="kv">
          <span>{{ r.slot.replace('T', ' ').slice(0, 16) }}</span>
          <span>{{ r.status }}<template v-if="r.error"> · {{ r.error }}</template></span>
        </div>
        <p v-if="message" class="meta" role="status">{{ message }}</p>
      </template>

      <div v-else class="empty">Select an item.</div>
    </section>
  </div>
</template>

<style scoped>
.actions { display: flex; gap: 8px; flex-wrap: wrap; }
.count { margin-left: 6px; }
</style>
