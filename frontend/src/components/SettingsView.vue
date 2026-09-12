<!-- Settings screen — a real GUI over ~/.hi/.env instead of hand-editing
     it, backed by hi/ipc/server.py's GET/POST /config. Deliberately
     does NOT include the MCP credentials (GitHub token, Obsidian API
     key) — those stay reachable only through hi/mcp_install.py's
     conversational, confirm-gated tool, never echoed back to a GET
     here; see that endpoint's own comment for why. -->
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { fetchConfig, updateConfig } from '../backend'

const fields = ref<Record<string, string>>({})
const isLoading = ref(true)
const isSaving = ref(false)
const statusMessage = ref<string | null>(null)

const FIELD_ORDER = [
  'VAULT_PATH', 'HAIKU_MODEL', 'SONNET_MODEL', 'OPUS_MODEL', 'VISION_MODEL',
  'BUTLER_MODEL', 'DOCS_MODEL', 'WEB_MODEL', 'TERM_MODEL',
]
const FIELD_LABELS: Record<string, string> = {
  VAULT_PATH: 'Obsidian vault path',
  HAIKU_MODEL: '"haiku" tier model (quick lookups)',
  SONNET_MODEL: '"sonnet" tier model (default)',
  OPUS_MODEL: '"opus" tier model (hardest requests)',
  VISION_MODEL: 'vision model (screen/image reading)',
  BUTLER_MODEL: "butler's own default model",
  DOCS_MODEL: "docs' own default model",
  WEB_MODEL: "web's own default model",
  TERM_MODEL: "term's own default model",
}

onMounted(async () => {
  fields.value = await fetchConfig()
  isLoading.value = false
})

async function save() {
  isSaving.value = true
  statusMessage.value = null
  const note = await updateConfig(fields.value)
  isSaving.value = false
  statusMessage.value = note ?? 'Failed to save — is the backend running?'
}
</script>

<template>
  <div class="settings">
    <h1>Settings</h1>
    <p class="note">
      Written directly to ~/.hi/.env — the same file hi/config.py reads at startup. Restart hi
      (and the voice daemon) for model/vault-path changes to take effect.
    </p>

    <div v-if="isLoading" class="status">Loading…</div>
    <template v-else>
      <div v-for="field in FIELD_ORDER" :key="field" class="field">
        <label>{{ FIELD_LABELS[field] ?? field }}</label>
        <input v-model="fields[field]" type="text" />
      </div>

      <div class="actions">
        <button :disabled="isSaving" @click="save">{{ isSaving ? 'Saving…' : 'Save' }}</button>
        <span v-if="statusMessage" class="status-message">{{ statusMessage }}</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.settings {
  max-width: 520px;
  margin: 0 auto;
  padding: 28px 20px;
}
h1 {
  font-family: var(--mono);
  font-size: 16px;
  font-weight: 500;
  color: var(--text);
  margin: 0 0 10px 0;
}
.note {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-faint);
  margin: 0 0 20px 0;
  line-height: 1.5;
}
.status {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--text-faint);
}
.field {
  margin-bottom: 14px;
}
label {
  display: block;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-faint);
  margin-bottom: 4px;
}
input {
  width: 100%;
  background: var(--bg-card);
  border: 1px solid var(--hairline);
  border-radius: 4px;
  padding: 8px;
  font-family: var(--mono);
  font-size: 12.5px;
  color: var(--text);
  outline: none;
}
input:focus {
  border-color: var(--teal-dim);
}
.actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 4px;
}
.actions button {
  background: none;
  border: 1px solid var(--hairline);
  border-radius: 6px;
  color: var(--teal);
  font-family: var(--mono);
  font-size: 12px;
  font-weight: 500;
  padding: 6px 12px;
  cursor: pointer;
}
.actions button:disabled {
  opacity: 0.5;
  cursor: default;
}
.status-message {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-dim);
}
</style>
