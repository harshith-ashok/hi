<!-- Direct port of /ui.html's .briefing strip. -->
<script setup lang="ts">
import type { BriefingInfo } from '../types'

const props = defineProps<{ briefing: BriefingInfo }>()
const emit = defineEmits<{ action: []; dismiss: [] }>()

const stripText = props.briefing.suggestion || props.briefing.context.split('\n')[0]
</script>

<template>
  <div class="briefing">
    <div class="dot"></div>
    <span class="text">{{ stripText }}</span>
    <span v-if="briefing.action" class="action" @click="emit('action')">run this →</span>
    <span class="dismiss" @click="emit('dismiss')">✕</span>
  </div>
</template>

<style scoped>
.briefing {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 18px;
  background: var(--bg-row);
  border-bottom: 1px solid var(--hairline);
  font-family: var(--mono);
  font-size: 11.5px;
  color: var(--text-dim);
  flex-shrink: 0;
}
.dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--amber);
  flex-shrink: 0;
}
.text {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.action {
  color: var(--teal);
  cursor: pointer;
  flex-shrink: 0;
}
.dismiss {
  color: var(--text-faint);
  cursor: pointer;
  flex-shrink: 0;
  font-size: 9px;
}
</style>
