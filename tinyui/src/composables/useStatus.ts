// Is the backend up, which model host it uses, and what is waiting for you. Polled while the app is open.

import { onMounted, onUnmounted, ref } from 'vue'
import { fetchConfig, getJson, ping } from '@/backend'

const online = ref(false)
const host = ref('')
const model = ref('')
const models = ref<Record<string, string>>({ haiku: '', sonnet: '', opus: '' }) // the model behind each tier
const activeTasks = ref(0)
const waitingActions = ref(0) // actions the assistant prepared that need an answer
let users = 0
let timer = 0

async function refresh() {
  online.value = await ping()
  if (!online.value) return
  activeTasks.value = ((await getJson<{ status: string }[]>('/background')) ?? []).filter((t) => t.status === 'running').length
  waitingActions.value = ((await getJson<{ status: string }[]>('/proposals?status=pending')) ?? []).length
  const config = await fetchConfig()
  const mode = String(config?.AI_MODE ?? '')
  host.value = `${mode} · ${config?.[mode === 'tailscale' ? 'TAILSCALE_OLLAMA_URL' : 'OLLAMA_HOST']}`
  model.value = String(config?.SONNET_MODEL ?? '')
  models.value = { haiku: String(config?.HAIKU_MODEL ?? ''), sonnet: String(config?.SONNET_MODEL ?? ''), opus: String(config?.OPUS_MODEL ?? '') }
}

export function useStatus() {
  onMounted(() => {
    if (users++ === 0) {
      void refresh()
      timer = window.setInterval(refresh, 5000)
    }
  })
  onUnmounted(() => {
    if (--users === 0) clearInterval(timer)
  })
  return { online, host, model, models, activeTasks, waitingActions, refresh }
}
