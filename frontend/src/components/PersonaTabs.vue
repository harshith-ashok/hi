<!-- Port of /ui-vue.html's .tabs — a horizontally-scrollable row (no
     reserved spacer pushing "hi ·auto" to the far right, unlike the
     original /ui.html panel design), since this is a real webpage that
     might be viewed on a narrow phone screen, not a fixed 620px popup. -->
<script setup lang="ts">
import type { PersonaChoice } from '../types'

defineProps<{ persona: PersonaChoice }>()
const emit = defineEmits<{ select: [PersonaChoice] }>()

const personas: PersonaChoice[] = ['term', 'butler', 'docs', 'web', 'auto']
const label = (p: PersonaChoice) => (p === 'auto' ? 'hi ·auto' : p)
</script>

<template>
  <div class="tabs">
    <div
      v-for="p in personas"
      :key="p"
      class="tab"
      :class="{ active: persona === p }"
      @click="emit('select', p)"
    >
      {{ label(p) }}
    </div>
  </div>
</template>

<style scoped>
.tabs {
  display: flex;
  gap: 4px;
  padding: 10px 18px 0 18px;
  border-bottom: 1px solid var(--hairline);
  overflow-x: auto;
  flex-shrink: 0;
}
.tabs::-webkit-scrollbar {
  display: none;
}
.tab {
  font-family: var(--mono);
  font-size: 12.5px;
  color: var(--text-faint);
  padding: 7px 12px 9px 12px;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  white-space: nowrap;
  user-select: none;
  transition: color 0.15s ease;
}
.tab:hover {
  color: var(--text-dim);
}
.tab.active {
  color: var(--teal);
  border-bottom-color: var(--teal);
}
</style>
