<!-- Right column of /ui-vue.html's layout.
     - Pending approvals: polled independently via GET /pending (the
       same real queue TraceSegmentView.vue's inline cards already use
       during an active stream) — shown here too so one's visible at a
       glance even without an open chat turn.
     - Orchestrator card: only appears while the CURRENTLY ACTIVE turn is
       a real orchestrated run — reusing that turn's own live subagent
       segments. There is no cross-request "an orchestrator is running"
       signal on the backend outside of an in-flight stream, so this
       deliberately doesn't try to fake persistence beyond that.
     - Per-persona cards: "busy" while that persona is the one currently
       streaming; otherwise the real most-recent activity-feed line for
       that persona, or "idle" if it hasn't done anything today. -->
<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { fetchPendingActions, resolvePendingAction } from '../backend'
import type { ActivityEntry, ChatTurn, PendingActionInfo, SubagentSegment } from '../types'

const props = defineProps<{
  currentTurn: ChatTurn | null
  activity: ActivityEntry[]
}>()

const personas = ['term', 'butler', 'docs', 'web']

const pending = ref<PendingActionInfo[]>([])
let timer: ReturnType<typeof setInterval> | undefined
async function refreshPending() {
  pending.value = await fetchPendingActions()
}
refreshPending()
timer = setInterval(refreshPending, 4000)
onUnmounted(() => clearInterval(timer))

const resolving = ref<Set<string>>(new Set())
async function resolve(id: string, approve: boolean) {
  resolving.value.add(id)
  await resolvePendingAction(id, approve)
  pending.value = pending.value.filter((p) => p.id !== id)
  resolving.value.delete(id)
}

const orchestratorSegments = computed<SubagentSegment[]>(() => {
  if (!props.currentTurn?.orchestrated) return []
  return props.currentTurn.segments.filter((s): s is SubagentSegment => s.kind === 'subagent')
})

function personaCard(persona: string) {
  const busy = props.currentTurn?.streaming && props.currentTurn?.persona === persona && !props.currentTurn?.orchestrated
  const lastEntry = props.activity.find((a) => a.persona === persona)
  return {
    busy,
    snippet: busy ? 'working…' : lastEntry ? lastEntry.text : 'idle',
  }
}

function statusIcon(status: string): string {
  return status === 'finished' ? '✓' : status === 'error' ? '✗' : '…'
}
</script>

<template>
  <div>
    <div class="col-title">AGENTS</div>

    <div v-for="action in pending" :key="action.id" class="card c-amber">
      <div class="card-title"><div class="dot busy"></div>pending approval</div>
      <div class="snippet">{{ action.description }}</div>
      <div class="approve-btns">
        <button class="deny" :disabled="resolving.has(action.id)" @click="resolve(action.id, false)">deny</button>
        <button class="allow" :disabled="resolving.has(action.id)" @click="resolve(action.id, true)">allow</button>
      </div>
    </div>

    <div v-if="currentTurn?.orchestrated" class="card c-purple">
      <div class="card-title">
        <div class="dot" :class="currentTurn.streaming ? 'busy' : 'on'"></div>
        orchestrator
      </div>
      <div class="agent-status">{{ currentTurn.streaming ? 'running…' : 'done' }}</div>
      <div class="subagents">
        <div v-for="seg in orchestratorSegments" :key="seg.taskId" class="subagent-row">
          <div class="dot" :class="seg.status === 'finished' ? 'on' : seg.status === 'error' ? 'error' : 'busy'"></div>
          {{ seg.taskId }}: {{ seg.persona }} {{ statusIcon(seg.status) }}
        </div>
      </div>
    </div>

    <div v-for="persona in personas" :key="persona" class="card c-teal">
      <div class="card-title">
        <div class="dot" :class="personaCard(persona).busy ? 'busy' : 'off'"></div>
        {{ persona }}
      </div>
      <div class="snippet">{{ personaCard(persona).snippet }}</div>
    </div>
  </div>
</template>

<style scoped>
.col-title {
  font-family: var(--mono);
  font-size: 10.5px;
  letter-spacing: 0.04em;
  color: var(--text-faint);
  margin-bottom: 10px;
  padding-left: 2px;
}
.card {
  background: var(--bg-card);
  border: 1px solid var(--hairline);
  border-radius: 10px;
  padding: 12px 14px;
  margin-bottom: 10px;
  border-left: 2px solid var(--hairline);
}
.card.c-teal {
  border-left-color: var(--teal);
}
.card.c-purple {
  border-left-color: var(--purple);
}
.card.c-amber {
  border-left-color: var(--amber);
}
.card-title {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-dim);
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--text-faint);
}
.dot.on {
  background: var(--teal);
}
.dot.off {
  background: var(--text-faint);
}
.dot.busy {
  background: var(--amber);
  animation: pulse 1.4s ease-in-out infinite;
}
.dot.error {
  background: var(--rust);
}
@keyframes pulse {
  50% {
    opacity: 0.35;
  }
}
.snippet,
.agent-status {
  font-size: 12px;
  color: var(--text-dim);
  line-height: 1.5;
}
.agent-status {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--text-faint);
}
.subagents {
  margin-top: 6px;
}
.subagent-row {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 3px 0;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-dim);
}
.approve-btns {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}
.approve-btns button {
  font-family: var(--mono);
  font-size: 11px;
  border-radius: 5px;
  padding: 5px 10px;
  cursor: pointer;
  border: 1px solid var(--hairline);
  background: none;
  color: var(--text-dim);
}
.approve-btns .allow {
  border-color: var(--teal-dim);
  color: var(--teal);
}
.approve-btns .deny {
  border-color: var(--rust);
  color: var(--rust);
}
.approve-btns button:disabled {
  opacity: 0.5;
  cursor: default;
}
</style>
