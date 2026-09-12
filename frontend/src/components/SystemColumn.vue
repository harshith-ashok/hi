<!-- Left column of /ui-vue.html's three-column layout — every stat is
     real (hi/dashboard.py). Deliberately diverges from the mockup in
     two honest ways: no Focus/DND row (macOS has no stable read API for
     it — see hi/agents/butler/mac_control.py's own toggle_dnd()
     docstring) and no "next calendar event" (no calendar integration
     exists) — shown as "next deadline" instead, which IS real. -->
<script setup lang="ts">
import type { TodayStats, VaultStats, Vitals } from '../types'

defineProps<{
  vitals: Vitals | null
  vaultStats: VaultStats | null
  todayStats: TodayStats | null
}>()

function pct(n: number | null | undefined): string {
  return n === null || n === undefined ? '—' : `${Math.round(n)}%`
}

function ms(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  return n < 1000 ? `${Math.round(n)}ms` : `${(n / 1000).toFixed(1)}s`
}
</script>

<template>
  <div>
    <div class="col-title">SYSTEM</div>

    <div class="card">
      <div class="card-title">vitals</div>
      <div class="stat-row">
        <span class="stat-label">CPU</span><span class="stat-value">{{ pct(vitals?.cpu_percent) }}</span>
      </div>
      <div class="bar"><div class="bar-fill" :style="{ width: pct(vitals?.cpu_percent) }"></div></div>
      <div class="stat-row" style="margin-top: 8px">
        <span class="stat-label">Memory</span><span class="stat-value">{{ pct(vitals?.memory_percent) }}</span>
      </div>
      <div class="bar">
        <div class="bar-fill amber" :style="{ width: pct(vitals?.memory_percent) }"></div>
      </div>
      <div v-if="vitals?.battery_percent != null" class="stat-row" style="margin-top: 8px">
        <span class="stat-label">Battery</span><span class="stat-value">{{ pct(vitals.battery_percent) }}</span>
      </div>
    </div>

    <div class="card">
      <div class="card-title">network</div>
      <div class="stat-row">
        <span class="stat-label">Wi-Fi</span>
        <span class="stat-value">{{ vitals?.wifi_ssid ?? 'not connected' }}</span>
      </div>
    </div>

    <div class="card">
      <div class="card-title">today</div>
      <div class="stat-row">
        <span class="stat-label">Next deadline</span>
        <span class="stat-value">{{ todayStats?.next_deadline ?? 'none' }}</span>
      </div>
      <div class="stat-row" style="margin-top: 6px">
        <span class="stat-label">Tasks due</span><span class="stat-value">{{ todayStats?.tasks_due_today ?? '—' }}</span>
      </div>
    </div>

    <div class="card">
      <div class="card-title">vault</div>
      <div class="stat-row">
        <span class="stat-label">Touched today</span>
        <span class="stat-value">{{ vaultStats?.notes_touched_today ?? '—' }} notes</span>
      </div>
      <div class="stat-row" style="margin-top: 6px">
        <span class="stat-label">Last edited</span>
        <span class="stat-value truncate">{{ vaultStats?.last_edited_note ?? 'none' }}</span>
      </div>
    </div>

    <div class="card">
      <div class="card-title"><div class="dot on"></div>model</div>
      <div class="stat-row">
        <span class="stat-label">Active</span>
        <span class="stat-value truncate">{{ vitals?.active_model ?? '—' }}</span>
      </div>
      <div class="stat-row" style="margin-top: 6px">
        <span class="stat-label">Last latency</span><span class="stat-value">{{ ms(vitals?.last_latency_ms) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.col-title {
  font-family: var(--mono);
  font-size: 10.5px;
  letter-spacing: 0.04em;
  color: var(--text-faint);
  margin-bottom: 10px;
  padding-left: 2px;
}
.card {
  background: var(--bg-card);
  border: 1px solid var(--hairline);
  border-radius: 10px;
  padding: 12px 14px;
  margin-bottom: 10px;
}
.card-title {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-dim);
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.dot.on {
  background: var(--teal);
}
.stat-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px;
}
.stat-label {
  font-size: 11.5px;
  color: var(--text-dim);
  flex-shrink: 0;
}
.stat-value {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--text);
  text-align: right;
}
.stat-value.truncate {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 140px;
}
.bar {
  height: 4px;
  background: var(--hairline);
  border-radius: 2px;
  overflow: hidden;
  margin-top: 4px;
}
.bar-fill {
  height: 100%;
  background: var(--teal);
}
.bar-fill.amber {
  background: var(--amber);
}
</style>
