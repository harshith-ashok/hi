// Polls whether hi --voice-daemon is reachable, for the header's
// connection-status dot (ui-vue.html's own template) — the same 5s
// interval and "any real response = reachable" logic
// BackendHealthMonitor.swift already established, so this isn't a
// second, differently-tuned mechanism.

import { onUnmounted, ref } from 'vue'
import { ping } from '../backend'

export function useConnectionStatus() {
  const isReachable = ref(false)
  let timer: ReturnType<typeof setInterval> | undefined

  async function check() {
    isReachable.value = await ping()
  }

  check()
  timer = setInterval(check, 5000)
  onUnmounted(() => clearInterval(timer))

  return { isReachable }
}
