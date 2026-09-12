<!--
  Renders one segment of an assistant turn — the actual "show
  everything that happens in the background, but prettier" piece.
  Thinking/tool-call/subagent blocks are real, distinct cards (icon +
  label + collapsible detail), not the terminal's plain dimmed-prefix
  or `[t1: persona] starting…` print lines — same underlying events,
  a much richer view of them.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { TraceSegment } from '../types'
import { resolvePendingAction } from '../backend'
import { renderMarkdown } from '../lib/markdown'

const props = defineProps<{ segment: TraceSegment }>()

// Thinking/tool blocks start expanded while streaming, then collapse
// once finished — Claude's own "thinking" UI does the same: show the
// work while it's happening, tuck it away once there's a real answer,
// but leave it one click away.
const expanded = ref(true)
watch(
  () => (props.segment.kind === 'thinking' || props.segment.kind === 'tool' ? props.segment.open : undefined),
  (open) => {
    if (open === false) expanded.value = false
  },
)

const parsedArgs = computed(() => {
  if (props.segment.kind !== 'tool') return ''
  try {
    return JSON.stringify(JSON.parse(props.segment.args || '{}'), null, 2)
  } catch {
    return props.segment.args
  }
})

const resolving = ref(false)
async function resolve(id: string, approve: boolean) {
  resolving.value = true
  await resolvePendingAction(id, approve)
  resolving.value = false
  // The real outcome arrives via the stream's own pending_action_resolved
  // event shortly after — this just disables the buttons immediately so
  // a click can't double-fire while that round trip is in flight.
}
</script>

<template>
  <div v-if="segment.kind === 'thinking'" class="block thinking">
    <button class="block-header" @click="expanded = !expanded">
      <span class="icon">◌</span>
      <span class="label">Thinking</span>
      <span v-if="segment.open" class="pulse"></span>
      <span class="chevron" :class="{ open: expanded }">›</span>
    </button>
    <div v-if="expanded" class="block-body thinking-text">{{ segment.text }}</div>
  </div>

  <div v-else-if="segment.kind === 'tool'" class="block tool">
    <button class="block-header" @click="expanded = !expanded">
      <span class="icon">⚙</span>
      <span class="label mono">{{ segment.name }}</span>
      <span v-if="segment.open" class="pulse"></span>
      <span v-else class="done-mark">✓</span>
      <span class="chevron" :class="{ open: expanded }">›</span>
    </button>
    <div v-if="expanded" class="block-body">
      <pre v-if="parsedArgs" class="mono args">{{ parsedArgs }}</pre>
      <pre v-if="segment.result" class="mono result">{{ segment.result }}</pre>
    </div>
  </div>

  <div v-else-if="segment.kind === 'subagent'" class="block subagent">
    <div class="block-header static">
      <span class="icon">{{ segment.status === 'finished' ? '✓' : segment.status === 'error' ? '✗' : '◌' }}</span>
      <span class="label mono">{{ segment.taskId }} · {{ segment.persona }}</span>
      <span v-if="segment.status === 'started' || segment.status === 'retrying'" class="pulse"></span>
      <span v-if="segment.status === 'retrying'" class="retry-note">retrying at a higher tier…</span>
    </div>
    <div v-if="segment.text" class="block-body subagent-text markdown" v-html="renderMarkdown(segment.text)"></div>
  </div>

  <div v-else-if="segment.kind === 'pending'" class="block pending">
    <div class="pending-row">
      <span class="dot" :class="{ approved: segment.resolution === true, denied: segment.resolution === false }"></span>
      <span class="pending-desc mono">{{ segment.description }}</span>
      <span v-if="segment.resolution === undefined" class="pending-actions">
        <button class="deny-btn" :disabled="resolving" @click="resolve(segment.id, false)">Deny</button>
        <button class="approve-btn" :disabled="resolving" @click="resolve(segment.id, true)">Approve</button>
      </span>
      <span v-else class="pending-outcome">{{ segment.resolution ? 'Approved' : 'Denied' }}</span>
    </div>
  </div>

  <div v-else class="text-segment markdown" v-html="renderMarkdown(segment.text)"></div>
</template>

<style scoped>
.block {
  margin: 6px 0;
  border-radius: 6px;
  border: 1px solid var(--hairline);
  background: var(--bg-row);
  overflow: hidden;
}

.block-header {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 7px 10px;
  background: none;
  border: none;
  color: var(--text-faint);
  font-family: var(--mono);
  font-size: 11.5px;
  cursor: pointer;
  text-align: left;
}
.block-header.static {
  cursor: default;
}
.thinking .block-header,
.thinking .icon {
  color: var(--text-faint);
}
.tool .block-header .icon {
  color: var(--amber);
}
.subagent .block-header .icon {
  color: var(--teal);
}

.label {
  flex: 1;
  color: var(--text-dim);
}
.label.mono {
  font-family: var(--mono);
}

.pulse {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--amber);
  animation: pulse 1s ease-in-out infinite;
}
@keyframes pulse {
  50% {
    opacity: 0.25;
  }
}

.done-mark {
  color: var(--teal);
}
.retry-note {
  color: var(--amber);
  font-size: 10.5px;
}

.chevron {
  color: var(--text-faint);
  transition: transform 0.12s ease;
}
.chevron.open {
  transform: rotate(90deg);
}

.block-body {
  padding: 8px 12px 10px 30px;
  border-top: 1px solid var(--hairline);
}

.thinking-text {
  font-family: var(--sans);
  font-size: 12px;
  font-style: italic;
  line-height: 1.5;
  color: var(--text-faint);
  white-space: pre-wrap;
}

.mono {
  font-family: var(--mono);
}
.args,
.result {
  margin: 0 0 6px 0;
  font-size: 11.5px;
  color: var(--text-dim);
  white-space: pre-wrap;
  word-break: break-word;
}
.result {
  color: var(--text);
}

.subagent-text {
  font-size: 13px;
  color: var(--text-dim);
}

.pending {
  border-color: var(--amber);
}
.pending-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
}
.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--amber);
  flex-shrink: 0;
}
.dot.approved {
  background: var(--teal);
}
.dot.denied {
  background: var(--rust);
}
.pending-desc {
  flex: 1;
  font-size: 12px;
  color: var(--text-dim);
}
.pending-actions {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}
.pending-actions button {
  font-family: var(--mono);
  font-size: 11.5px;
  background: none;
  border: none;
  cursor: pointer;
  padding: 0;
}
.deny-btn {
  color: var(--rust);
}
.approve-btn {
  color: var(--teal);
  font-weight: 500;
}
.pending-outcome {
  font-family: var(--mono);
  font-size: 11.5px;
  color: var(--text-faint);
  flex-shrink: 0;
}

/* .text-segment's own typography now comes from the global .markdown
   class (lib/markdown.ts's rendered output) — no scoped override left
   to duplicate/conflict with it. */
</style>
