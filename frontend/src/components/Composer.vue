<!-- Port of /ui-vue.html's .composer — pinned to the bottom, an explicit
     send button (not just a keyboard hint) since this is a real webpage
     that might be used from a phone, safe-area padding for a notch. -->
<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{ isBusy: boolean }>()
const emit = defineEmits<{ submit: [string] }>()

const text = ref('')
const inputEl = ref<HTMLInputElement>()

function submit() {
  const trimmed = text.value.trim()
  if (!trimmed || props.isBusy) return
  emit('submit', trimmed)
  text.value = ''
}

defineExpose({ focus: () => inputEl.value?.focus() })
</script>

<template>
  <div class="composer">
    <span class="prefix">&gt;</span>
    <input
      ref="inputEl"
      v-model="text"
      type="text"
      placeholder="ask anything, or name a persona to force it"
      :disabled="isBusy"
      @keydown.enter="submit"
    />
    <button :disabled="isBusy || !text.trim()" @click="submit">
      {{ isBusy ? '…' : 'send' }}
    </button>
  </div>
</template>

<style scoped>
.composer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 18px calc(14px + env(safe-area-inset-bottom, 0px)) 18px;
  border-top: 1px solid var(--hairline);
  background: var(--bg-panel);
  flex-shrink: 0;
}
.prefix {
  font-family: var(--mono);
  font-size: 13px;
  color: var(--teal);
  flex-shrink: 0;
}
input {
  flex: 1;
  min-width: 0;
  background: transparent;
  border: none;
  outline: none;
  font-family: var(--mono);
  font-size: 14px;
  color: var(--text);
  caret-color: var(--teal);
}
input::placeholder {
  color: var(--text-faint);
}
input:disabled {
  opacity: 0.6;
}
button {
  background: none;
  border: 1px solid var(--hairline);
  border-radius: 6px;
  color: var(--text-dim);
  font-family: var(--mono);
  font-size: 12px;
  padding: 6px 10px;
  cursor: pointer;
  flex-shrink: 0;
}
button:not(:disabled):active {
  border-color: var(--teal);
  color: var(--teal);
}
button:disabled {
  opacity: 0.5;
  cursor: default;
}
</style>
