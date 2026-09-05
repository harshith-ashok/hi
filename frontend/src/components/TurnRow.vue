<!-- Ports /ui.html's .turn/.persona-tag/.content structure directly —
     same border-accent-by-role, same tag column width, same fonts. An
     assistant turn's "content" is now a list of TraceSegmentView
     blocks instead of one string, so thinking/tool-call/subagent
     activity renders inline in the log, in the order it happened. -->
<script setup lang="ts">
import { computed } from 'vue'
import type { ChatTurn } from '../types'
import TraceSegmentView from './TraceSegmentView.vue'

const props = defineProps<{ turn: ChatTurn }>()

const tag = computed(() => {
  if (props.turn.role === 'user') return 'you'
  if (props.turn.role === 'error') return '!'
  return props.turn.persona ? `(${props.turn.persona})` : '(hi)'
})
</script>

<template>
  <div class="turn" :class="turn.role">
    <div class="persona-tag">{{ tag }}</div>
    <div class="content">
      <template v-if="turn.role === 'user'">{{ (turn.segments[0] as any)?.text }}</template>
      <template v-else>
        <TraceSegmentView v-for="(seg, i) in turn.segments" :key="i" :segment="seg" />
        <span v-if="turn.streaming" class="cursor"></span>
      </template>
    </div>
  </div>
</template>

<style scoped>
.turn {
  display: flex;
  padding: 10px 18px;
  gap: 12px;
  border-left: 2px solid transparent;
}
.turn.user {
  border-left-color: var(--text-faint);
}
.turn.assistant {
  border-left-color: var(--teal-dim);
  background: rgba(79, 166, 156, 0.03);
}
.turn.error {
  border-left-color: var(--rust);
  background: rgba(180, 86, 58, 0.05);
}

.persona-tag {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-faint);
  width: 58px;
  flex-shrink: 0;
  padding-top: 1px;
}
.turn.assistant .persona-tag {
  color: var(--teal);
}
.turn.error .persona-tag {
  color: var(--rust);
}

.content {
  flex: 1;
  min-width: 0;
  font-family: var(--sans);
  font-size: 14px;
  line-height: 1.55;
  color: var(--text);
}
.turn.user .content {
  color: var(--text-dim);
  font-family: var(--mono);
  font-size: 13px;
  white-space: pre-wrap;
}

.cursor {
  display: inline-block;
  width: 6px;
  height: 13px;
  background: var(--teal);
  margin-left: 2px;
  vertical-align: -2px;
  animation: blink 1s steps(1) infinite;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}

@media (max-width: 480px) {
  .persona-tag {
    width: 48px;
    font-size: 10px;
  }
}
</style>
