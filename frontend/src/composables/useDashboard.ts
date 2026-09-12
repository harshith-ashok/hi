// Polls the real system/vault/task stats behind the home dashboard's
// left column (hi/dashboard.py) and today's activity feed (parsed from
// the same /conversations/{date} endpoint the History sidebar already
// used, per ui-vue.html's own template). All real data — see
// hi/dashboard.py's own docstring for what's deliberately not included.

import { onUnmounted, ref } from 'vue'
import {
  fetchConversation,
  fetchLastProject,
  fetchTodayStats,
  fetchVaultStats,
  fetchVitals,
} from '../backend'
import { parseActivity } from '../lib/parseActivity'
import type { ActivityEntry, TodayStats, VaultStats, Vitals } from '../types'

const REFRESH_MS = 15000

export function useDashboard() {
  const vitals = ref<Vitals | null>(null)
  const vaultStats = ref<VaultStats | null>(null)
  const todayStats = ref<TodayStats | null>(null)
  const lastProject = ref<string | null>(null)
  const activity = ref<ActivityEntry[]>([])

  async function refresh() {
    const today = new Date().toISOString().slice(0, 10)
    const [v, vs, t, lp, log] = await Promise.all([
      fetchVitals(),
      fetchVaultStats(),
      fetchTodayStats(),
      fetchLastProject(),
      fetchConversation(today),
    ])
    vitals.value = v
    vaultStats.value = vs
    todayStats.value = t
    lastProject.value = lp
    activity.value = log ? parseActivity(log) : []
  }

  refresh()
  const timer = setInterval(refresh, REFRESH_MS)
  onUnmounted(() => clearInterval(timer))

  return { vitals, vaultStats, todayStats, lastProject, activity, refresh }
}
