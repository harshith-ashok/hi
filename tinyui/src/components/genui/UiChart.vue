<script setup lang="ts">
// A small SVG chart (bar, line, area, pie) for the numbers the assistant wants to show. No chart library: the data is
// at most a couple of hundred points and the shapes are simple.
import { computed } from 'vue'

interface Point { label: string; value: number }
const props = defineProps<{ kind: string; data: Point[]; title?: string }>()

const W = 600
const H = 280
const PAD = { l: 44, r: 12, t: 12, b: 36 }
const COLORS = ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#14b8a6', '#ec4899', '#84cc16', '#f97316', '#64748b']

const max = computed(() => Math.max(0, ...props.data.map((p) => p.value)))
const min = computed(() => Math.min(0, ...props.data.map((p) => p.value)))
const span = computed(() => max.value - min.value || 1)
const inner = { w: W - PAD.l - PAD.r, h: H - PAD.t - PAD.b }
const y = (v: number) => PAD.t + inner.h - ((v - min.value) / span.value) * inner.h
const x = (i: number) => PAD.l + (props.data.length === 1 ? inner.w / 2 : (i / (props.data.length - 1)) * inner.w)
const slot = computed(() => inner.w / Math.max(1, props.data.length))
const ticks = computed(() => [0, 0.25, 0.5, 0.75, 1].map((f) => ({ v: min.value + f * span.value, y: y(min.value + f * span.value) })))
const fmt = (n: number) => (Math.abs(n) >= 1000 ? `${(n / 1000).toFixed(1)}k` : Number.isInteger(n) ? String(n) : n.toFixed(1))
const path = computed(() => props.data.map((p, i) => `${i ? 'L' : 'M'}${x(i)},${y(p.value)}`).join(' '))
const area = computed(() => `${path.value} L${x(props.data.length - 1)},${y(0)} L${x(0)},${y(0)} Z`)
const labelEvery = computed(() => Math.ceil(props.data.length / 10))

const total = computed(() => props.data.reduce((s, p) => s + Math.max(0, p.value), 0) || 1)
const slices = computed(() => {
  let angle = -Math.PI / 2
  return props.data.map((p, i) => {
    const sweep = (Math.max(0, p.value) / total.value) * Math.PI * 2
    const [x0, y0, x1, y1] = [Math.cos(angle), Math.sin(angle), Math.cos(angle + sweep), Math.sin(angle + sweep)]
    const d = `M0,0 L${x0 * 100},${y0 * 100} A100,100 0 ${sweep > Math.PI ? 1 : 0} 1 ${x1 * 100},${y1 * 100} Z`
    angle += sweep
    return { d, color: COLORS[i % COLORS.length], label: p.label, pct: Math.round((Math.max(0, p.value) / total.value) * 100) }
  })
})
</script>

<template>
  <figure class="not-prose space-y-2">
    <figcaption v-if="title" class="text-sm font-medium">{{ title }}</figcaption>
    <svg v-if="kind !== 'pie'" :viewBox="`0 0 ${W} ${H}`" class="w-full max-w-2xl" role="img" :aria-label="title || 'Chart'">
      <g v-for="t in ticks" :key="t.v">
        <line :x1="PAD.l" :x2="W - PAD.r" :y1="t.y" :y2="t.y" stroke="currentColor" class="text-border" />
        <text :x="PAD.l - 6" :y="t.y + 4" text-anchor="end" class="fill-muted-foreground text-[11px]">{{ fmt(t.v) }}</text>
      </g>
      <template v-if="kind === 'bar'">
        <rect v-for="(p, i) in data" :key="i" :x="PAD.l + i * slot + slot * 0.15" :y="Math.min(y(p.value), y(0))" :width="slot * 0.7" :height="Math.abs(y(p.value) - y(0))" rx="3" :fill="COLORS[0]">
          <title>{{ p.label }}: {{ p.value }}</title>
        </rect>
      </template>
      <template v-else>
        <path v-if="kind === 'area'" :d="area" :fill="COLORS[0]" opacity="0.18" />
        <path :d="path" fill="none" :stroke="COLORS[0]" stroke-width="2.5" stroke-linejoin="round" />
        <circle v-for="(p, i) in data" :key="i" :cx="x(i)" :cy="y(p.value)" r="3.5" :fill="COLORS[0]"><title>{{ p.label }}: {{ p.value }}</title></circle>
      </template>
      <text v-for="(p, i) in data" v-show="i % labelEvery === 0" :key="'l' + i" :x="kind === 'bar' ? PAD.l + i * slot + slot / 2 : x(i)" :y="H - 12" text-anchor="middle" class="fill-muted-foreground text-[11px]">{{ p.label }}</text>
    </svg>
    <div v-else class="flex flex-wrap items-center gap-6">
      <svg viewBox="-110 -110 220 220" class="size-48" role="img" :aria-label="title || 'Pie chart'">
        <path v-for="s in slices" :key="s.label" :d="s.d" :fill="s.color" stroke="var(--background)" stroke-width="2"><title>{{ s.label }}: {{ s.pct }}%</title></path>
      </svg>
      <ul class="space-y-1 text-sm">
        <li v-for="s in slices" :key="s.label" class="flex items-center gap-2"><span class="size-3 rounded-sm" :style="{ background: s.color }" />{{ s.label }}<span class="text-muted-foreground">{{ s.pct }}%</span></li>
      </ul>
    </div>
  </figure>
</template>
