<script setup lang="ts">
// A circle of waves that moves with the voice: mic level while listening,
// playback level while speaking, a slow swell while thinking.
import { onMounted, onUnmounted, ref } from 'vue'
import { audioLevel } from './voice'

const props = defineProps<{ state: string }>()
const canvas = ref<HTMLCanvasElement>()
let raf = 0

function draw(time: number) {
  const el = canvas.value
  const ctx = el?.getContext('2d')
  if (!el || !ctx) return
  const size = el.width
  const t = time / 1000
  const style = getComputedStyle(el)
  const accent = style.getPropertyValue('--accent').trim() || '#66d9e8'

  const thinking = props.state === 'thinking' || props.state === 'acting' || props.state === 'structuring'
  const level = thinking ? 0.25 + 0.15 * Math.sin(t * 2) : audioLevel.value
  const base = size * 0.22

  ctx.clearRect(0, 0, size, size)
  ctx.translate(size / 2, size / 2)
  for (let ring = 0; ring < 4; ring++) {
    ctx.beginPath()
    const radius = base * (1 + ring * 0.13) + level * size * 0.05 * (ring + 1)
    const wobble = (0.02 + level * 0.16) * radius * (1 - ring * 0.15)
    for (let i = 0; i <= 120; i++) {
      const a = (i / 120) * Math.PI * 2
      const wave = Math.sin(a * 3 + t * (1.2 + ring * 0.5) + ring) + 0.6 * Math.sin(a * 5 - t * (1.6 + ring * 0.3)) + 0.4 * Math.sin(a * 8 + t * 2.4)
      const r = radius + wobble * wave
      const x = Math.cos(a) * r
      const y = Math.sin(a) * r
      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    ctx.closePath()
    ctx.strokeStyle = accent
    ctx.globalAlpha = ring === 0 ? 0.95 : 0.55 - ring * 0.12
    ctx.lineWidth = ring === 0 ? 2.5 : 1.5
    ctx.stroke()
  }
  ctx.globalAlpha = 1
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  raf = requestAnimationFrame(draw)
}

onMounted(() => (raf = requestAnimationFrame(draw)))
onUnmounted(() => cancelAnimationFrame(raf))
</script>

<template>
  <canvas ref="canvas" width="480" height="480" />
</template>

<style scoped>
canvas { width: min(60vmin, 420px); height: min(60vmin, 420px); }
</style>
