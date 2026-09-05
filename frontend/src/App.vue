<!-- Root layout — redesigned per explicit request to use /ui-vue.html as
     the template: a real full-height webpage column (edge-to-edge, side
     hairlines only, no rounded floating panel on a "desk" background),
     with a header bar carrying a real connection-status indicator. The
     previous "centered popup on a dark desk" design was closer to
     /ui.html's own floating-panel mockup — appropriate for that, not
     for a page meant to actually be used in a browser (including on a
     phone, per the template's own "iPhone" framing — the max-width:780px
     + @media(max-width:480px) breakpoints throughout this rework are
     both taken directly from it). -->
<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import BriefingStrip from './components/BriefingStrip.vue'
import Composer from './components/Composer.vue'
import PersonaTabs from './components/PersonaTabs.vue'
import TurnRow from './components/TurnRow.vue'
import { BASE_URL, fetchBriefing } from './backend'
import { useChat } from './composables/useChat'
import { useConnectionStatus } from './composables/useConnectionStatus'
import type { BriefingInfo, PersonaChoice } from './types'

const { turns, isBusy, submit, newChat } = useChat()
const { isReachable } = useConnectionStatus()
const persona = ref<PersonaChoice>('auto')
const briefing = ref<BriefingInfo | null>(null)
const logEl = ref<HTMLElement>()

const backendHost = BASE_URL.replace(/^https?:\/\//, '')

onMounted(async () => {
  briefing.value = await fetchBriefing()
})

watch(
  turns,
  async () => {
    await nextTick()
    logEl.value?.scrollTo({ top: logEl.value.scrollHeight, behavior: 'smooth' })
  },
  { deep: true },
)

function handleSubmit(text: string) {
  submit(text, persona.value === 'auto' ? null : persona.value)
}

function runBriefingAction() {
  const action = briefing.value?.action
  if (!action) return
  briefing.value = null
  handleSubmit(action)
}
</script>

<template>
  <div class="app">
    <header>
      <span class="glyph">(hi)</span>
      <span class="device">{{ backendHost }}</span>
      <div class="spacer"></div>
      <button v-if="turns.length" class="clear-btn" title="New chat" @click="newChat">new chat</button>
      <div class="status">
        <div class="dot" :class="{ down: !isReachable }"></div>
        {{ isReachable ? 'connected' : 'unreachable' }}
      </div>
    </header>

    <PersonaTabs :persona="persona" @select="(p) => (persona = p)" />
    <BriefingStrip
      v-if="briefing"
      :briefing="briefing"
      @action="runBriefingAction"
      @dismiss="briefing = null"
    />

    <div v-if="turns.length" ref="logEl" class="log">
      <TurnRow v-for="turn in turns" :key="turn.id" :turn="turn" />
    </div>
    <div v-else class="empty">Ask anything, or pick a tab to force a persona.</div>

    <Composer :is-busy="isBusy" @submit="handleSubmit" />
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  max-width: 780px;
  margin: 0 auto;
  border-left: 1px solid var(--hairline);
  border-right: 1px solid var(--hairline);
}

header {
  display: flex;
  align-items: center;
  padding: 14px 18px;
  border-bottom: 1px solid var(--hairline);
  gap: 12px;
  flex-shrink: 0;
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
.clear-btn {
  background: none;
  border: none;
  color: var(--text-faint);
  font-family: var(--mono);
  font-size: 11px;
  cursor: pointer;
  padding: 0;
}
.clear-btn:hover {
  color: var(--rust);
}
.status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-dim);
}
.status .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--teal);
}
.status .dot.down {
  background: var(--rust);
}

.log {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0 16px 0;
}

.empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--mono);
  font-size: 12.5px;
  color: var(--text-faint);
}

@media (max-width: 480px) {
  .app {
    border-left: none;
    border-right: none;
  }
  .device {
    display: none;
  }
}
</style>
