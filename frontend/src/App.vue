<!-- Redesigned per explicit request to implement /ui-vue.html's updated
     template: a home dashboard (system vitals, quick-action tiles, a
     live activity feed, per-agent status, pending approvals) rather
     than a persistent chat transcript. The mockup drops persona tabs
     and the always-visible briefing strip entirely — auto-routing only
     now, and the briefing is fetched on demand via the "run briefing"
     tile instead of shown automatically.

     Every dashboard value is real (hi/dashboard.py, polled by
     useDashboard.ts) — see that module's own docstring for the couple
     of stats the mockup shows that have no real backing (calendar
     events, Focus/DND read state) and are therefore not faked here.

     Settings/History (built for feature parity with the native app,
     before this redesign) aren't in the new mockup at all, but stay
     reachable via two small topbar links rather than being deleted —
     real, working views with nowhere else to live now that persona
     tabs are gone.

     Per explicit follow-up request: the response (briefing/trace/
     current answer) now lives INSIDE the middle grid column instead of
     a separate block stacked above the whole 3-column layout — that
     stacking was what pushed the left (SYSTEM) column down every time a
     response appeared, since everything below it shared one vertical
     flow. Now the left column's own row position never depends on
     what's in the middle one. The activity feed (center column) is
     removed per the same request — its underlying data (useDashboard's
     `activity`) is kept, since AgentsColumn's per-persona "last thing
     they did" snippets still read from it. SystemColumn is also
     `position: sticky` now, so it stays in view even if the middle
     column's content (a long response) scrolls the page well past the
     left column's own natural height. -->
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import AgentsColumn from './components/AgentsColumn.vue'
import AgentTasksView from './components/AgentTasksView.vue'
import BriefingStrip from './components/BriefingStrip.vue'
import HeroPrompt from './components/HeroPrompt.vue'
import HistoryView from './components/HistoryView.vue'
import SettingsView from './components/SettingsView.vue'
import SystemColumn from './components/SystemColumn.vue'
import TurnRow from './components/TurnRow.vue'
import { BASE_URL, fetchBriefing, fetchConversationDates } from './backend'
import { useChat } from './composables/useChat'
import { useDashboard } from './composables/useDashboard'
import type { BriefingInfo } from './types'

const { turns, isBusy, submit } = useChat()
const { vitals, vaultStats, todayStats, lastProject, activity, refresh: refreshDashboard } = useDashboard()

const briefing = ref<BriefingInfo | null>(null)
const briefingLoading = ref(false)
const briefingChecked = ref(false)
const traceContent = ref<string | null>(null)
const view = ref<'home' | 'settings' | 'history' | 'agents'>('home')
const historyDates = ref<string[]>([])
const selectedHistoryDate = ref<string | null>(null)

const backendHost = BASE_URL.replace(/^https?:\/\//, '')

const currentTurn = computed(() => {
  const last = turns.value[turns.value.length - 1]
  return last && last.role !== 'user' ? last : null
})

const clock = ref('')
function updateClock() {
  clock.value = new Date().toLocaleTimeString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' })
}
let clockTimer: ReturnType<typeof setInterval> | undefined

onMounted(() => {
  updateClock()
  clockTimer = setInterval(updateClock, 30000)
  // Deliberately NOT auto-loaded here (unlike an earlier version of this
  // file) — /ui-vue.html's own "run briefing" tile is meant to be the
  // one thing that triggers this, on demand. Auto-loading on mount too
  // meant the strip was often already showing before the tile was ever
  // clicked, so a click silently re-fetched identical data with zero
  // visible change — indistinguishable from the tile just not working.
})
onUnmounted(() => clearInterval(clockTimer))

async function loadBriefing() {
  briefingLoading.value = true
  briefing.value = await fetchBriefing()
  briefingLoading.value = false
  briefingChecked.value = true
}

function handleSubmit(text: string) {
  traceContent.value = null
  submit(text, null) // auto-routing only — the mockup dropped forced-persona tabs
  // Refresh the dashboard's own stats shortly after a turn starts, so
  // e.g. a capture/task-completing turn is reflected without waiting a
  // full 15s polling cycle.
  setTimeout(refreshDashboard, 2000)
}

function runBriefingAction() {
  const action = briefing.value?.action
  if (!action) return
  briefing.value = null
  handleSubmit(action)
}

async function openHistory() {
  view.value = 'history'
  historyDates.value = await fetchConversationDates()
  selectedHistoryDate.value = historyDates.value[0] ?? null
}
</script>

<template>
  <div class="topbar">
    <span class="glyph">(hi)</span>
    <span class="device">{{ backendHost }}</span>
    <div class="spacer"></div>
    <button class="nav-link" @click="view = 'home'">home</button>
    <button class="nav-link" @click="openHistory">history</button>
    <button class="nav-link" @click="view = 'agents'">agents</button>
    <button class="nav-link" @click="view = 'settings'">settings</button>
    <span class="clock">{{ clock }}</span>
  </div>

  <template v-if="view === 'settings'">
    <SettingsView />
  </template>

  <template v-else-if="view === 'agents'">
    <AgentTasksView />
  </template>

  <template v-else-if="view === 'history'">
    <div class="history-page">
      <div class="history-sidebar">
        <div
          v-for="date in historyDates"
          :key="date"
          class="history-date"
          :class="{ active: date === selectedHistoryDate }"
          @click="selectedHistoryDate = date"
        >
          {{ date }}
        </div>
      </div>
      <HistoryView v-if="selectedHistoryDate" :date="selectedHistoryDate" />
    </div>
  </template>

  <template v-else>
    <HeroPrompt
      :is-busy="isBusy"
      :briefing-loading="briefingLoading"
      :last-project="lastProject"
      @submit="handleSubmit"
      @refresh-briefing="loadBriefing"
      @show-trace="(c) => (traceContent = c)"
    />

    <div class="layout">
      <div class="sticky-col">
        <SystemColumn :vitals="vitals" :vault-stats="vaultStats" :today-stats="todayStats" />
      </div>

      <div class="middle-col">
        <BriefingStrip v-if="briefing" :briefing="briefing" @action="runBriefingAction" @dismiss="briefing = null" />
        <div v-else-if="briefingChecked" class="briefing-empty">
          Nothing worth surfacing right now.
          <span class="dismiss" @click="briefingChecked = false">&times;</span>
        </div>

        <div v-if="traceContent" class="trace-panel">
          <div class="trace-header">
            <span>last run trace</span>
            <button @click="traceContent = null">&times;</button>
          </div>
          <pre>{{ traceContent }}</pre>
        </div>

        <div v-if="currentTurn" class="current-response">
          <TurnRow :turn="currentTurn" />
        </div>
        <div v-else class="idle-hint">Ask something above to see the response here.</div>
      </div>

      <AgentsColumn :current-turn="currentTurn" :activity="activity" />
    </div>
  </template>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  padding: 16px 28px;
  gap: 16px;
}
.glyph {
  font-family: var(--mono);
  font-weight: 600;
  font-size: 15px;
  color: var(--teal);
}
.device {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-faint);
  border: 1px solid var(--hairline);
  border-radius: 5px;
  padding: 3px 8px;
}
.spacer {
  flex: 1;
}
.nav-link {
  background: none;
  border: none;
  color: var(--text-faint);
  font-family: var(--mono);
  font-size: 11px;
  cursor: pointer;
  padding: 0;
}
.nav-link:hover {
  color: var(--teal);
}
.clock {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--text-faint);
}

.sticky-col {
  position: sticky;
  top: 20px;
}

.middle-col > * + * {
  margin-top: 10px;
}

.idle-hint {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--text-faint);
  padding: 20px 0;
}

.briefing-empty {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  background: var(--bg-card);
  border: 1px solid var(--hairline);
  border-radius: 10px;
  font-family: var(--mono);
  font-size: 11.5px;
  color: var(--text-faint);
}
.briefing-empty .dismiss {
  margin-left: auto;
  cursor: pointer;
  font-size: 13px;
}

.trace-panel,
.current-response {
  background: var(--bg-card);
  border: 1px solid var(--hairline);
  border-radius: 10px;
  overflow: hidden;
}
.trace-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  border-bottom: 1px solid var(--hairline);
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-faint);
}
.trace-header button {
  background: none;
  border: none;
  color: var(--text-faint);
  cursor: pointer;
  font-size: 14px;
}
.trace-panel pre {
  margin: 0;
  padding: 14px;
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  font-family: var(--mono);
  font-size: 11.5px;
  color: var(--text-dim);
}

.layout {
  display: grid;
  grid-template-columns: 220px 1fr 260px;
  gap: 18px;
  max-width: 1180px;
  margin: 0 auto;
  padding: 0 28px 40px 28px;
  align-items: start;
}

.history-page {
  display: flex;
  max-width: 900px;
  margin: 0 auto;
  height: calc(100vh - 68px);
}
.history-sidebar {
  width: 180px;
  flex-shrink: 0;
  overflow-y: auto;
  border-right: 1px solid var(--hairline);
}
.history-date {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--text-dim);
  padding: 8px 14px;
  cursor: pointer;
}
.history-date:hover {
  color: var(--text);
}
.history-date.active {
  color: var(--teal);
  background: var(--bg-card);
}

@media (max-width: 900px) {
  .layout {
    grid-template-columns: 1fr;
  }
  .sticky-col {
    /* Stacked single-column layout at this width — sticky here would
       pin the stats over content stacked below it instead of beside
       it, which reads as broken, not helpful. */
    position: static;
  }
}
</style>
