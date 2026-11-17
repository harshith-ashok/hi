// Turns a scene description (data, never code) into three.js objects and a timeline. The backend checks scenes before
// saving them (hi/scene3d.py); this builder checks again, because a scene can also arrive inside an answer.
//
// Everything that moves is a function of the time `t` (seconds), not a running total: `update(t)` puts the scene at time
// t, so the viewer can play, pause, scrub and record by changing t.

import type * as THREE_NS from 'three'
import { compile } from '@/lib/expr'

type T = typeof THREE_NS
type Vec3 = [number, number, number]
type Tick = (t: number) => void

export interface Track { property: string; keys: { t: number; value: number | number[] | string; ease?: string }[]; loop?: string }
export interface Animate {
  rotate?: Vec3
  bob?: number
  bobSpeed?: number
  orbit?: { center?: Vec3; radius?: number; speed?: number; axis?: string; phase?: number; tilt?: number }
  pulse?: { amount?: number; speed?: number }
  path?: { points: Vec3[]; duration?: number; loop?: string; orient?: boolean; closed?: boolean }
  tracks?: Track[]
}
export interface Repeat { mode: string; total: number; stagger?: number; count?: number; radius?: number; axis?: string; faceCenter?: boolean; step?: Vec3; rotateStep?: Vec3; scaleStep?: number; counts?: Vec3; spacing?: Vec3 }
export interface SceneObject {
  type: string
  position?: Vec3
  rotation?: Vec3 // degrees
  scale?: Vec3
  color?: string
  material?: {
    kind?: string; metalness?: number; roughness?: number; opacity?: number; emissive?: string; emissiveIntensity?: number
    flatShading?: boolean; doubleSide?: boolean; clearcoat?: number; transmission?: number; ior?: number
    texture?: { kind: string; colors?: string[]; repeat?: [number, number] }
  }
  animate?: Animate
  repeat?: Repeat
  children?: SceneObject[]
  castShadow?: boolean
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any
}
export interface CameraSpec {
  position?: Vec3; target?: Vec3; fov?: number
  orbit?: { radius?: number; height?: number; speed?: number; phase?: number }
  tracks?: Track[]
}
export interface SceneData {
  title?: string
  objects: SceneObject[]
  background?: string
  camera?: CameraSpec
  lights?: { type: string; color?: string; intensity?: number; position?: Vec3 }[]
  grid?: boolean
  axes?: boolean
  autoRotate?: boolean
  duration?: number
  loop?: boolean
  shadows?: boolean
  environment?: boolean
  ground?: { color?: string; size?: number }
  fog?: { color?: string; near?: number; far?: number }
}

const MAX_OBJECTS = 2000
const MAX_DEPTH = 6
const MAX_VERTICES = 60_000
const num = (v: unknown, fallback: number) => (typeof v === 'number' && Number.isFinite(v) ? v : fallback)
const vec = (v: unknown, fallback: Vec3): Vec3 => (Array.isArray(v) && v.length === 3 ? [num(v[0], fallback[0]), num(v[1], fallback[1]), num(v[2], fallback[2])] : fallback)
const points = (v: unknown, width: number): number[][] =>
  Array.isArray(v) ? v.filter((p): p is number[] => Array.isArray(p) && p.length === width && p.every((n) => Number.isFinite(n))).slice(0, MAX_VERTICES) : []

/** Parse the JSON of a scene, or say what is wrong with it. */
export function parseScene(text: string): { scene: SceneData } | { error: string } {
  try {
    const data = JSON.parse(text) as SceneData
    if (!data || !Array.isArray(data.objects) || !data.objects.length) return { error: 'The scene has no objects.' }
    return { scene: data }
  } catch (err) {
    return { error: `The scene is not valid JSON: ${(err as Error).message}` }
  }
}

// ---- easing, looping, keyframes ---------------------------------------------------------------------------------

const bounceOut = (x: number) => {
  const [n, d] = [7.5625, 2.75]
  if (x < 1 / d) return n * x * x
  if (x < 2 / d) return n * (x -= 1.5 / d) * x + 0.75
  if (x < 2.5 / d) return n * (x -= 2.25 / d) * x + 0.9375
  return n * (x -= 2.625 / d) * x + 0.984375
}
export const EASE: Record<string, (k: number) => number> = {
  linear: (k) => k,
  easeIn: (k) => k * k * k,
  easeOut: (k) => 1 - Math.pow(1 - k, 3),
  easeInOut: (k) => (k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2),
  bounce: bounceOut,
  elastic: (k) => (k === 0 || k === 1 ? k : Math.pow(2, -10 * k) * Math.sin((k * 10 - 0.75) * ((2 * Math.PI) / 3)) + 1),
  back: (k) => 1 + 2.70158 * Math.pow(k - 1, 3) + 1.70158 * Math.pow(k - 1, 2),
}

/** `t` folded into [0, length] by the loop mode. */
export function loopTime(t: number, length: number, mode = 'loop'): number {
  if (length <= 0) return 0
  if (mode === 'once') return Math.min(Math.max(t, 0), length)
  if (mode === 'pingpong') {
    const p = ((t % (2 * length)) + 2 * length) % (2 * length)
    return p > length ? 2 * length - p : p
  }
  return ((t % length) + length) % length
}

export const trackLength = (track: Track) => Math.max(0, ...track.keys.map((k) => k.t))

function evalTrack(THREE: T, track: Track, t: number): number | number[] | THREE_NS.Color {
  const keys = track.keys
  const tt = loopTime(t, trackLength(track), track.loop)
  const next = keys.findIndex((k) => k.t > tt)
  const [a, b] = next <= 0 ? [keys[next === 0 ? 0 : keys.length - 1], keys[next === 0 ? 0 : keys.length - 1]] : [keys[next - 1], keys[next]]
  const k = a === b || b.t === a.t ? 0 : (EASE[b.ease ?? 'easeInOut'] ?? EASE.easeInOut)((tt - a.t) / (b.t - a.t))
  if (typeof a.value === 'number' && typeof b.value === 'number') return a.value + (b.value - a.value) * k
  if (typeof a.value === 'string' && typeof b.value === 'string') return new THREE.Color(a.value).lerp(new THREE.Color(b.value), k)
  const [va, vb] = [a.value as number[], b.value as number[]]
  return va.map((x, i) => x + (vb[i] - x) * k)
}

const PALETTES: Record<string, string[]> = {
  viridis: ['#440154', '#3b528b', '#21918c', '#5ec962', '#fde725'],
  plasma: ['#0d0887', '#7e03a8', '#cc4778', '#f89540', '#f0f921'],
  cool: ['#00e5ff', '#3b82f6', '#8b5cf6', '#d946ef'],
  warm: ['#fde047', '#fb923c', '#ef4444', '#7f1d1d'],
  rainbow: ['#ef4444', '#f59e0b', '#22c55e', '#06b6d4', '#6366f1', '#d946ef'],
  gray: ['#18181b', '#a1a1aa', '#fafafa'],
}
function paletteColor(THREE: T, name: string | undefined, k: number, out: THREE_NS.Color): THREE_NS.Color {
  const stops = PALETTES[name ?? 'viridis'] ?? PALETTES.viridis
  const f = Math.min(Math.max(k, 0), 1) * (stops.length - 1)
  const i = Math.min(stops.length - 2, Math.floor(f))
  return out.set(stops[i]).lerp(new THREE.Color(stops[i + 1]), f - i)
}

/** Repeatable pseudo-random numbers, so particles are in the same place every time. */
function rng(seed: number) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

// ---- building -------------------------------------------------------------------------------------------------------

interface Ctx {
  THREE: T
  ticks: Tick[]
  count: { n: number }
  geo: Map<string, THREE_NS.BufferGeometry>
  mat: Map<string, THREE_NS.Material>
  seconds: { longest: number; continuous: boolean }
  shadows: boolean
}
interface Instance { index: number; stagger: number; offset: Vec3; rotate: Vec3; scale: number }
const ONE: Instance = { index: 0, stagger: 0, offset: [0, 0, 0], rotate: [0, 0, 0], scale: 1 }

function textureFor(THREE: T, spec: NonNullable<NonNullable<SceneObject['material']>['texture']>): THREE_NS.CanvasTexture {
  const [c1, c2] = [spec.colors?.[0] ?? '#ffffff', spec.colors?.[1] ?? '#334155']
  const size = 256
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const g = canvas.getContext('2d')!
  g.fillStyle = c1
  g.fillRect(0, 0, size, size)
  g.fillStyle = c2
  switch (spec.kind) {
    case 'checker': for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) if ((x + y) % 2) g.fillRect((x * size) / 8, (y * size) / 8, size / 8, size / 8); break
    case 'stripes': for (let x = 0; x < 8; x += 2) g.fillRect((x * size) / 8, 0, size / 8, size); break
    case 'grid': g.fillRect(0, 0, size, 6); g.fillRect(0, 0, 6, size); break
    case 'dots': for (let y = 0; y < 6; y++) for (let x = 0; x < 6; x++) { g.beginPath(); g.arc(((x + 0.5) * size) / 6, ((y + 0.5) * size) / 6, size / 18, 0, Math.PI * 2); g.fill() } break
    case 'gradient': { const grad = g.createLinearGradient(0, 0, size, size); grad.addColorStop(0, c1); grad.addColorStop(1, c2); g.fillStyle = grad; g.fillRect(0, 0, size, size); break }
    case 'noise': { const img = g.getImageData(0, 0, size, size); const a = new THREE.Color(c1); const b = new THREE.Color(c2); const r = rng(7); for (let i = 0; i < size * size; i++) { const k = r(); img.data[i * 4] = (a.r + (b.r - a.r) * k) * 255; img.data[i * 4 + 1] = (a.g + (b.g - a.g) * k) * 255; img.data[i * 4 + 2] = (a.b + (b.b - a.b) * k) * 255; img.data[i * 4 + 3] = 255 } g.putImageData(img, 0, 0); break }
  }
  const tex = new THREE.CanvasTexture(canvas)
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping
  const [ru, rv] = spec.repeat ?? [1, 1]
  tex.repeat.set(ru, rv)
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

function materialFor(ctx: Ctx, o: SceneObject, unique: boolean): THREE_NS.Material {
  const { THREE } = ctx
  const m = o.material ?? {}
  const key = JSON.stringify([o.color, m])
  const cached = !unique && ctx.mat.get(key)
  if (cached) return cached
  const opacity = num(m.opacity, 1)
  const base: THREE_NS.MeshStandardMaterialParameters = { color: new THREE.Color(o.color ?? '#8899aa'), side: m.doubleSide || ['plane', 'surface', 'parametric', 'circle', 'ring'].includes(o.type) ? THREE.DoubleSide : THREE.FrontSide, transparent: opacity < 1, opacity }
  const emissive = new THREE.Color(m.emissive ?? '#000000')
  let material: THREE_NS.Material
  switch (m.kind) {
    case 'basic': material = new THREE.MeshBasicMaterial(base); break
    case 'wireframe': material = new THREE.MeshBasicMaterial({ ...base, wireframe: true }); break
    case 'phong': material = new THREE.MeshPhongMaterial({ ...base, flatShading: !!m.flatShading, emissive }); break
    case 'toon': material = new THREE.MeshToonMaterial(base); break
    case 'physical':
      material = new THREE.MeshPhysicalMaterial({ ...base, metalness: num(m.metalness, 0), roughness: num(m.roughness, 0.2), clearcoat: num(m.clearcoat, 0), transmission: num(m.transmission, 0), ior: num(m.ior, 1.5), thickness: 0.6, emissive, emissiveIntensity: num(m.emissiveIntensity, 1), flatShading: !!m.flatShading })
      break
    default: material = new THREE.MeshStandardMaterial({ ...base, metalness: num(m.metalness, 0.1), roughness: num(m.roughness, 0.6), flatShading: !!m.flatShading, emissive, emissiveIntensity: num(m.emissiveIntensity, 1) })
  }
  if (m.texture) (material as THREE_NS.MeshStandardMaterial).map = textureFor(THREE, m.texture)
  if (!unique) ctx.mat.set(key, material)
  return material
}

function geometryFor(ctx: Ctx, o: SceneObject): THREE_NS.BufferGeometry | null {
  const { THREE } = ctx
  const cacheable = !['lathe', 'extrude', 'mesh'].includes(o.type)
  const key = cacheable ? JSON.stringify([o.type, o.size, o.radius, o.height, o.length, o.tube, o.inner, o.outer]) : ''
  if (cacheable && ctx.geo.has(key)) return ctx.geo.get(key)!
  const r = num(o.radius, 0.5)
  let g: THREE_NS.BufferGeometry | null = null
  switch (o.type) {
    case 'box': { const [w, h, d] = vec(o.size, [1, 1, 1]); g = new THREE.BoxGeometry(w, h, d); break }
    case 'sphere': g = new THREE.SphereGeometry(r, 48, 32); break
    case 'cylinder': g = new THREE.CylinderGeometry(r, r, num(o.height, 1), 48); break
    case 'cone': g = new THREE.ConeGeometry(r, num(o.height, 1), 48); break
    case 'capsule': g = new THREE.CapsuleGeometry(num(o.radius, 0.3), num(o.length, 0.8), 8, 24); break
    case 'torus': g = new THREE.TorusGeometry(r, num(o.tube, 0.15), 24, 64); break
    case 'torusknot': g = new THREE.TorusKnotGeometry(r, num(o.tube, 0.15), 128, 16); break
    case 'plane': { const s = Array.isArray(o.size) ? o.size : [1, 1]; g = new THREE.PlaneGeometry(num(s[0], 1), num(s[1], 1)); break }
    case 'circle': g = new THREE.CircleGeometry(r, 48); break
    case 'ring': g = new THREE.RingGeometry(num(o.inner, 0.3), num(o.outer, 0.5), 48); break
    case 'tetrahedron': g = new THREE.TetrahedronGeometry(r); break
    case 'octahedron': g = new THREE.OctahedronGeometry(r); break
    case 'dodecahedron': g = new THREE.DodecahedronGeometry(r); break
    case 'icosahedron': g = new THREE.IcosahedronGeometry(r); break
    case 'lathe': { const pts = points(o.points, 2); g = pts.length >= 2 ? new THREE.LatheGeometry(pts.map(([x, y]) => new THREE.Vector2(x, y)), 48) : null; break }
    case 'extrude': {
      const pts = points(o.shape, 2)
      g = pts.length >= 3 ? new THREE.ExtrudeGeometry(new THREE.Shape(pts.map(([x, y]) => new THREE.Vector2(x, y))), { depth: num(o.depth, 0.3), bevelEnabled: false }) : null
      break
    }
    case 'mesh': {
      const verts = points(o.vertices, 3)
      const faces = Array.isArray(o.faces) ? (o.faces as unknown[]).filter((f): f is number[] => Array.isArray(f) && f.length === 3 && f.every((n) => Number.isInteger(n) && n >= 0 && n < verts.length)) : []
      if (verts.length >= 3 && faces.length) {
        g = new THREE.BufferGeometry()
        g.setAttribute('position', new THREE.Float32BufferAttribute(verts.flat(), 3))
        g.setIndex(faces.flat())
        g.computeVertexNormals()
      }
      break
    }
  }
  if (g && cacheable) ctx.geo.set(key, g)
  return g
}

/** A surface over a grid of (a, b) whose positions are recomputed by `place`. */
function gridMesh(ctx: Ctx, na: number, nb: number, place: (ia: number, ib: number, t: number, out: Float32Array, at: number) => void, o: SceneObject, dynamic: boolean): THREE_NS.Mesh {
  const { THREE } = ctx
  const g = new THREE.BufferGeometry()
  const positions = new Float32Array(na * nb * 3)
  const index: number[] = []
  for (let b = 0; b < nb - 1; b++) for (let a = 0; a < na - 1; a++) {
    const i = b * na + a
    index.push(i, i + na, i + 1, i + 1, i + na, i + na + 1)
  }
  g.setIndex(index)
  g.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  const byHeight = o.colorBy === 'height'
  if (byHeight) g.setAttribute('color', new THREE.BufferAttribute(new Float32Array(na * nb * 3), 3))
  let lo = Infinity
  let hi = -Infinity
  const fill = (t: number) => {
    for (let b = 0; b < nb; b++) for (let a = 0; a < na; a++) place(a, b, t, positions, (b * na + a) * 3)
    g.attributes.position.needsUpdate = true
    g.computeVertexNormals()
    if (byHeight) {
      const colors = g.attributes.color.array as Float32Array
      const c = new THREE.Color()
      for (let i = 0; i < na * nb; i++) {
        paletteColor(THREE, o.palette, (positions[i * 3 + 1] - lo) / (hi - lo || 1), c)
        colors[i * 3] = c.r; colors[i * 3 + 1] = c.g; colors[i * 3 + 2] = c.b
      }
      g.attributes.color.needsUpdate = true
    }
  }
  // Height colours use one range over the whole animation, found by sampling, so colours do not flicker as it moves.
  const samples = dynamic ? [0, 1, 2, 3, 5, 8] : [0]
  for (const s of samples) {
    for (let b = 0; b < nb; b++) for (let a = 0; a < na; a++) place(a, b, s, positions, (b * na + a) * 3)
    for (let i = 0; i < na * nb; i++) { lo = Math.min(lo, positions[i * 3 + 1]); hi = Math.max(hi, positions[i * 3 + 1]) }
  }
  fill(0)
  const mesh = new THREE.Mesh(g, materialFor(ctx, { ...o, material: { ...(o.material ?? {}), doubleSide: true } }, true))
  if (byHeight) (mesh.material as THREE_NS.MeshStandardMaterial).vertexColors = true
  if (dynamic) {
    mesh.frustumCulled = false
    ctx.ticks.push((t) => fill(t))
    ctx.seconds.continuous = true
  }
  return mesh
}

function expressionNode(ctx: Ctx, o: SceneObject, inst: Instance): THREE_NS.Object3D | null {
  const { THREE } = ctx
  try {
    if (o.type === 'surface') {
      const [x0, x1, nx] = vec(o.x, [-1, 1, 32])
      const [y0, y1, ny] = vec(o.y, [-1, 1, 32])
      const f = compile(String(o.expr), ['x', 'y', 't'])
      const [na, nb] = [Math.max(2, Math.floor(nx)), Math.max(2, Math.floor(ny))]
      return gridMesh(ctx, na, nb, (a, b, t, out, at) => {
        const [x, y] = [x0 + ((x1 - x0) * a) / (na - 1), y0 + ((y1 - y0) * b) / (nb - 1)]
        const h = f.fn(x, y, t)
        out[at] = x; out[at + 1] = Number.isFinite(h) ? h : 0; out[at + 2] = y
      }, o, f.uses.has('t'))
    }
    if (o.type === 'parametric') {
      const [u0, u1, nu] = vec(o.u, [0, 6.283, 48])
      const [v0, v1, nv] = vec(o.v, [0, 3.1416, 24])
      const [fx, fy, fz] = (['fx', 'fy', 'fz'] as const).map((k) => compile(String(o[k]), ['u', 'v', 't']))
      const [na, nb] = [Math.max(2, Math.floor(nu)), Math.max(2, Math.floor(nv))]
      return gridMesh(ctx, na, nb, (a, b, t, out, at) => {
        const [u, v] = [u0 + ((u1 - u0) * a) / (na - 1), v0 + ((v1 - v0) * b) / (nb - 1)]
        const p = [fx.fn(u, v, t), fy.fn(u, v, t), fz.fn(u, v, t)]
        for (let i = 0; i < 3; i++) out[at + i] = Number.isFinite(p[i]) ? p[i] : 0
      }, o, [fx, fy, fz].some((c) => c.uses.has('t')))
    }
    if (o.type === 'curve') {
      const [u0, u1, n] = vec(o.u, [0, 6.283, 200])
      const steps = Math.max(2, Math.floor(n))
      const [fx, fy, fz] = (['fx', 'fy', 'fz'] as const).map((k) => compile(String(o[k]), ['u', 't']))
      const radius = num(o.radius, 0)
      const dynamic = [fx, fy, fz].some((c) => c.uses.has('t'))
      const sample = (t: number) => Array.from({ length: steps }, (_, i) => {
        const u = u0 + ((u1 - u0) * i) / (steps - 1)
        const p = [fx.fn(u, t), fy.fn(u, t), fz.fn(u, t)].map((x) => (Number.isFinite(x) ? x : 0))
        return new THREE.Vector3(p[0], p[1], p[2])
      })
      const color = new THREE.Color(o.color ?? '#3b82f6')
      if (radius > 0) {
        const mesh = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(sample(0)), steps, radius, 8), materialFor(ctx, o, false))
        if (dynamic) {
          mesh.frustumCulled = false
          ctx.ticks.push((t) => { mesh.geometry.dispose(); mesh.geometry = new THREE.TubeGeometry(new THREE.CatmullRomCurve3(sample(t)), steps, radius, 8) })
          ctx.seconds.continuous = true
        }
        return mesh
      }
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(sample(0)), new THREE.LineBasicMaterial({ color }))
      if (dynamic) {
        line.frustumCulled = false
        ctx.ticks.push((t) => line.geometry.setFromPoints(sample(t)))
        ctx.seconds.continuous = true
      }
      return line
    }
  } catch {
    return null // a bad expression skips this object; the rest of the scene still draws
  }
  void inst
  return null
}

function particles(ctx: Ctx, o: SceneObject): THREE_NS.Points {
  const { THREE } = ctx
  const n = Math.max(1, Math.min(5000, Math.floor(num(o.count, 200))))
  const [spread, speed, life, gravity] = [num(o.spread, 1), num(o.speed, 0.5), Math.max(0.1, num(o.life, 4)), num(o.gravity, 0)]
  const rand = rng(Math.floor(num(o.seed, 1)))
  const seeds = Array.from({ length: n }, () => [rand(), rand(), rand(), rand()])
  const positions = new Float32Array(n * 3)
  const colors = new Float32Array(n * 3)
  const c = new THREE.Color()
  const base = new THREE.Color(o.color ?? '#ffffff')
  seeds.forEach((s, i) => {
    if (o.palette) paletteColor(THREE, o.palette, s[2], c)
    else c.copy(base)
    colors[i * 3] = c.r; colors[i * 3 + 1] = c.g; colors[i * 3 + 2] = c.b
  })
  const place = (t: number) => {
    for (let i = 0; i < n; i++) {
      const [r1, r2, r3, r4] = seeds[i]
      const age = (((t / life + r1) % 1) + 1) % 1 * life
      let x = 0; let y = 0; let z = 0
      const dir = () => { const th = r2 * Math.PI * 2; const ph = Math.acos(2 * r3 - 1); return [Math.sin(ph) * Math.cos(th), Math.cos(ph), Math.sin(ph) * Math.sin(th)] }
      switch (o.emitter) {
        case 'box': x = (r1 - 0.5) * spread * 2; y = (r2 - 0.5) * spread * 2; z = (r3 - 0.5) * spread * 2; y += Math.sin(t * speed + r4 * 6.28) * 0.1; break
        case 'ring': { const a = r1 * Math.PI * 2 + t * speed * 0.3; const rr = spread * (0.85 + r2 * 0.3); x = Math.cos(a) * rr; z = Math.sin(a) * rr; y = (r3 - 0.5) * 0.2; break }
        case 'spiral': { const a = r1 * Math.PI * 2 + t * speed; const rr = spread * (0.3 + 0.7 * r3); x = Math.cos(a) * rr; z = Math.sin(a) * rr; y = (r2 - 0.5) * spread * 2; break }
        case 'burst': { const d = dir(); x = d[0] * speed * age; y = d[1] * speed * age + 0.5 * gravity * age * age; z = d[2] * speed * age; break }
        case 'rain': x = (r1 - 0.5) * spread * 2; z = (r2 - 0.5) * spread * 2; y = spread - ((age * Math.max(speed, 0.1)) % (spread * 2)); break
        case 'fountain': { const v0 = speed * (0.8 + 0.4 * r3); const a = r2 * Math.PI * 2; const cone = 0.25 * spread; x = Math.cos(a) * cone * v0 * age; z = Math.sin(a) * cone * v0 * age; y = v0 * age + 0.5 * gravity * age * age; break }
        default: { const d = dir(); const rr = spread * Math.cbrt(r4); x = d[0] * rr + Math.sin(t * speed + r4 * 6.28) * 0.08; y = d[1] * rr + Math.cos(t * speed + r1 * 6.28) * 0.08; z = d[2] * rr }
      }
      positions[i * 3] = x; positions[i * 3 + 1] = y; positions[i * 3 + 2] = z
    }
  }
  place(0)
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  g.setAttribute('color', new THREE.BufferAttribute(colors, 3))
  const pts = new THREE.Points(g, new THREE.PointsMaterial({ size: num(o.size, 0.05), vertexColors: true, transparent: true, opacity: 0.9, depthWrite: false, sizeAttenuation: true }))
  pts.frustumCulled = false
  ctx.ticks.push((t) => { place(t); g.attributes.position.needsUpdate = true })
  ctx.seconds.continuous = true
  return pts
}

function label(ctx: Ctx, o: SceneObject): THREE_NS.Sprite {
  const { THREE } = ctx
  const text = String(o.text ?? '').slice(0, 80)
  const canvas = document.createElement('canvas')
  const g = canvas.getContext('2d')!
  const font = '600 64px ui-sans-serif, system-ui, sans-serif'
  g.font = font
  const w = Math.ceil(g.measureText(text).width) + 48
  canvas.width = w; canvas.height = 110
  g.font = font
  if (o.background) { g.fillStyle = String(o.background); g.beginPath(); g.roundRect(0, 0, w, 110, 22); g.fill() }
  g.fillStyle = o.color ?? '#111111'
  g.textBaseline = 'middle'
  g.fillText(text, 24, 58)
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }))
  const h = num(o.size, 0.3)
  sprite.scale.set((h * w) / 110, h, 1)
  return sprite
}

function applyMotion(ctx: Ctx, node: THREE_NS.Object3D, o: SceneObject, inst: Instance, mats: THREE_NS.Material[]) {
  const { THREE } = ctx
  const anim = o.animate ?? {}
  const basePos = new THREE.Vector3(...vec(o.position, [0, 0, 0])).add(new THREE.Vector3(...inst.offset))
  const baseRot = vec(o.rotation, [0, 0, 0]).map((d, i) => THREE.MathUtils.degToRad(d + inst.rotate[i]))
  const [sx, sy, sz] = vec(o.scale, [1, 1, 1])
  const baseScale: Vec3 = [sx * inst.scale, sy * inst.scale, sz * inst.scale]
  node.position.copy(basePos)
  node.rotation.set(baseRot[0], baseRot[1], baseRot[2])
  node.scale.set(...baseScale)
  const moves = !!(anim.rotate || anim.bob || anim.orbit || anim.pulse || anim.path || anim.tracks?.length)
  if (!moves) return
  const orbit = anim.orbit
  const curve = anim.path && anim.path.points?.length >= 2 ? new THREE.CatmullRomCurve3(anim.path.points.map((p) => new THREE.Vector3(...vec(p, [0, 0, 0]))), !!anim.path.closed) : null
  for (const tr of anim.tracks ?? []) ctx.seconds.longest = Math.max(ctx.seconds.longest, trackLength(tr) + inst.stagger)
  if (curve) ctx.seconds.longest = Math.max(ctx.seconds.longest, num(anim.path?.duration, 5) + inst.stagger)
  if (anim.rotate || anim.bob || anim.orbit || anim.pulse || (anim.path && anim.path.loop !== 'once')) ctx.seconds.continuous = true
  ctx.ticks.push((time) => {
    const t = Math.max(0, time - inst.stagger)
    const pos = basePos.clone()
    const rot = [...baseRot]
    const scale: Vec3 = [...baseScale]
    if (anim.rotate) for (let i = 0; i < 3; i++) rot[i] += anim.rotate[i] * t
    if (anim.bob) pos.y += Math.sin(t * num(anim.bobSpeed, 1.6)) * anim.bob
    if (anim.pulse) { const k = 1 + num(anim.pulse.amount, 0.2) * Math.sin(t * num(anim.pulse.speed, 2)); for (let i = 0; i < 3; i++) scale[i] *= k }
    if (orbit) {
      const a = num(orbit.speed, 1) * t + num(orbit.phase, 0)
      const r = num(orbit.radius, 2)
      const [c, s] = [Math.cos(a) * r, Math.sin(a) * r]
      const local = orbit.axis === 'x' ? new THREE.Vector3(0, c, s) : orbit.axis === 'z' ? new THREE.Vector3(c, s, 0) : new THREE.Vector3(c, 0, s)
      local.applyAxisAngle(new THREE.Vector3(1, 0, 0), THREE.MathUtils.degToRad(num(orbit.tilt, 0)))
      pos.add(new THREE.Vector3(...vec(orbit.center, [0, 0, 0]))).add(local)
    }
    if (curve && anim.path) {
      const u = loopTime(t, num(anim.path.duration, 5), anim.path.loop) / num(anim.path.duration, 5)
      pos.copy(curve.getPointAt(Math.min(u, 1)))
    }
    for (const tr of anim.tracks ?? []) {
      const v = evalTrack(THREE, tr, t)
      if (tr.property === 'position') pos.set(...(v as Vec3)).add(new THREE.Vector3(...inst.offset)) // each copy keeps its place in the repeat
      else if (tr.property === 'rotation') for (let i = 0; i < 3; i++) rot[i] = THREE.MathUtils.degToRad((v as number[])[i])
      else if (tr.property === 'scale') for (let i = 0; i < 3; i++) scale[i] = (v as number[])[i]
      else for (const m of mats) {
        const mm = m as THREE_NS.MeshStandardMaterial
        if (tr.property === 'color' && mm.color) mm.color.copy(v as THREE_NS.Color)
        else if (tr.property === 'emissive' && mm.emissive) mm.emissive.copy(v as THREE_NS.Color)
        else if (tr.property === 'opacity') { mm.opacity = v as number; mm.transparent = (v as number) < 1 }
      }
    }
    node.position.copy(pos)
    node.rotation.set(rot[0], rot[1], rot[2])
    node.scale.set(...scale)
    if (curve && anim.path?.orient) {
      const u = loopTime(t, num(anim.path.duration, 5), anim.path.loop) / num(anim.path.duration, 5)
      node.lookAt(pos.clone().add(curve.getTangentAt(Math.min(u, 1))))
    }
  })
}

function buildOne(ctx: Ctx, o: SceneObject, depth: number, inst: Instance): THREE_NS.Object3D | null {
  const { THREE } = ctx
  if (++ctx.count.n > MAX_OBJECTS || depth > MAX_DEPTH) return null
  let node: THREE_NS.Object3D | null = null
  const colorMoves = !!o.animate?.tracks?.some((t) => ['color', 'opacity', 'emissive'].includes(t.property))
  const mats: THREE_NS.Material[] = []
  switch (o.type) {
    case 'group': {
      const group = new THREE.Group()
      for (const child of Array.isArray(o.children) ? o.children : []) {
        const built = buildNode(ctx, child, depth + 1)
        if (built) group.add(built)
      }
      node = group
      break
    }
    case 'surface': case 'parametric': case 'curve':
      node = expressionNode(ctx, o, inst)
      break
    case 'points': node = particles(ctx, o); break
    case 'label': node = label(ctx, o); break
    case 'line': {
      const pts = points(o.points, 3)
      if (pts.length < 2) return null
      const material = o.dashed ? new THREE.LineDashedMaterial({ color: o.color ?? '#3b82f6', dashSize: 0.15, gapSize: 0.1 }) : new THREE.LineBasicMaterial({ color: o.color ?? '#3b82f6' })
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts.map((p) => new THREE.Vector3(p[0], p[1], p[2]))), material)
      if (o.dashed) line.computeLineDistances()
      node = line
      break
    }
    case 'arrow': {
      const from = new THREE.Vector3(...vec(o.from, [0, 0, 0]))
      const to = new THREE.Vector3(...vec(o.to, [0, 1, 0]))
      const dir = to.clone().sub(from)
      node = new THREE.ArrowHelper(dir.clone().normalize(), from, Math.max(dir.length(), 0.01), new THREE.Color(o.color ?? '#ef4444').getHex())
      break
    }
    default: {
      const geometry = geometryFor(ctx, o)
      if (!geometry) return null
      const material = materialFor(ctx, o, colorMoves)
      mats.push(material)
      const mesh = new THREE.Mesh(geometry, material)
      if (ctx.shadows && o.castShadow !== false) { mesh.castShadow = true; mesh.receiveShadow = true }
      node = mesh
    }
  }
  if (!node) return null
  if (node instanceof THREE.Mesh && !mats.length) mats.push(node.material as THREE_NS.Material)
  if (typeof o.name === 'string') node.name = o.name
  applyMotion(ctx, node, o, inst, mats)
  return node
}

const axisVec = (axis: string | undefined): Vec3 => (axis === 'x' ? [1, 0, 0] : axis === 'z' ? [0, 0, 1] : [0, 1, 0])

function instances(rep: Repeat): Instance[] {
  const total = Math.max(1, Math.min(Math.floor(rep.total || rep.count || 1), MAX_OBJECTS))
  const stagger = num(rep.stagger, 0)
  const out: Instance[] = []
  for (let i = 0; i < total; i++) {
    if (rep.mode === 'grid') {
      const [nx, ny] = vec(rep.counts, [3, 1, 3])
      const [sx, sy, sz] = vec(rep.spacing, [1, 1, 1])
      const [cx, cy, cz] = vec(rep.counts, [3, 1, 3])
      const [ix, iy, iz] = [i % nx, Math.floor(i / nx) % ny, Math.floor(i / (nx * ny))]
      out.push({ index: i, stagger: stagger * i, offset: [(ix - (cx - 1) / 2) * sx, (iy - (cy - 1) / 2) * sy, (iz - (cz - 1) / 2) * sz], rotate: [0, 0, 0], scale: 1 })
    } else if (rep.mode === 'ring') {
      const a = (i / total) * Math.PI * 2
      const r = num(rep.radius, 2)
      const [c, s] = [Math.cos(a) * r, Math.sin(a) * r]
      const axis = axisVec(rep.axis)
      const offset: Vec3 = axis[1] ? [c, 0, s] : axis[0] ? [0, c, s] : [c, s, 0]
      const face = rep.faceCenter ? (-a * 180) / Math.PI + 90 : 0
      out.push({ index: i, stagger: stagger * i, offset, rotate: axis[1] ? [0, face, 0] : axis[0] ? [face, 0, 0] : [0, 0, face], scale: 1 })
    } else {
      const [dx, dy, dz] = vec(rep.step, [1, 0, 0])
      const [rx, ry, rz] = vec(rep.rotateStep, [0, 0, 0])
      out.push({ index: i, stagger: stagger * i, offset: [dx * i, dy * i, dz * i], rotate: [rx * i, ry * i, rz * i], scale: Math.pow(num(rep.scaleStep, 1), i) })
    }
  }
  return out
}

function buildNode(ctx: Ctx, o: SceneObject, depth: number): THREE_NS.Object3D | null {
  if (!o.repeat) return buildOne(ctx, o, depth, ONE)
  const group = new ctx.THREE.Group()
  for (const inst of instances(o.repeat)) {
    const built = buildOne(ctx, o, depth, inst)
    if (built) group.add(built)
  }
  return group
}

export interface CameraRig { moving: boolean; apply: (t: number, camera: THREE_NS.PerspectiveCamera, target: THREE_NS.Vector3) => void }
export interface Built {
  root: THREE_NS.Group
  lights: THREE_NS.Light[]
  update: (t: number) => void
  duration: number // 0 for a still scene
  animated: boolean
  camera: CameraRig
  ground?: THREE_NS.Mesh
}

/** The scene as three.js objects, and `update(t)` to put it at time t. */
export function buildScene(THREE: T, data: SceneData): Built {
  const ctx: Ctx = { THREE, ticks: [], count: { n: 0 }, geo: new Map(), mat: new Map(), seconds: { longest: 0, continuous: false }, shadows: !!data.shadows }
  const root = new THREE.Group()
  for (const o of data.objects) {
    const built = buildNode(ctx, o, 1)
    if (built) root.add(built)
  }
  const lights: THREE_NS.Light[] = []
  for (const l of data.lights ?? []) {
    const color = new THREE.Color(l.color ?? '#ffffff')
    const intensity = num(l.intensity, 1)
    const light =
      l.type === 'ambient' ? new THREE.AmbientLight(color, intensity)
      : l.type === 'point' ? new THREE.PointLight(color, intensity * 30)
      : l.type === 'hemisphere' ? new THREE.HemisphereLight(color, '#444444', intensity)
      : new THREE.DirectionalLight(color, intensity * 2)
    if (l.type !== 'ambient' && l.type !== 'hemisphere') light.position.set(...vec(l.position, [3, 5, 4]))
    lights.push(light)
  }
  if (!lights.length) {
    const sun = new THREE.DirectionalLight('#ffffff', 2.2)
    sun.position.set(3, 5, 4)
    lights.push(new THREE.AmbientLight('#ffffff', 0.7), new THREE.HemisphereLight('#ffffff', '#555566', 0.6), sun)
  }
  if (data.shadows) {
    for (const l of lights) if ((l as THREE_NS.DirectionalLight).isDirectionalLight || (l as THREE_NS.PointLight).isPointLight) {
      l.castShadow = true
      const shadow = (l as THREE_NS.DirectionalLight).shadow
      shadow.mapSize.set(2048, 2048)
      const cam = shadow.camera
      if (cam && 'left' in cam) Object.assign(cam, { left: -12, right: 12, top: 12, bottom: -12, near: 0.5, far: 60 })
    }
  }

  // camera motion
  const cam = data.camera
  const orbit = cam?.orbit
  const camTracks = cam?.tracks ?? []
  for (const tr of camTracks) ctx.seconds.longest = Math.max(ctx.seconds.longest, trackLength(tr))
  const camera: CameraRig = {
    moving: !!orbit || camTracks.length > 0,
    apply(t, c, target) {
      if (orbit) {
        const a = num(orbit.speed, 0.3) * t + num(orbit.phase, 0)
        const r = num(orbit.radius, 5)
        c.position.set(target.x + Math.cos(a) * r, target.y + num(orbit.height, 2), target.z + Math.sin(a) * r)
      }
      for (const tr of camTracks) {
        const v = evalTrack(THREE, tr, t) as Vec3
        if (tr.property === 'position') c.position.set(...v)
        else if (tr.property === 'target') target.set(...v)
      }
      c.lookAt(target)
    },
  }
  if (orbit) ctx.seconds.continuous = true

  const animated = ctx.ticks.length > 0 || camera.moving
  const natural = ctx.seconds.longest || (ctx.seconds.continuous || camera.moving ? 10 : 0)
  const duration = animated ? Math.max(0.1, num(data.duration, natural || 10)) : 0
  return { root, lights, update: (t) => { for (const tick of ctx.ticks) tick(t) }, duration, animated, camera }
}

/** Free the GPU memory of everything under `root`. */
export function disposeTree(root: THREE_NS.Object3D) {
  root.traverse((node) => {
    const mesh = node as THREE_NS.Mesh
    mesh.geometry?.dispose()
    const mats = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : []
    for (const m of mats) {
      for (const value of Object.values(m)) (value as { isTexture?: boolean; dispose?: () => void } | null)?.isTexture && (value as { dispose: () => void }).dispose()
      m.dispose()
    }
  })
}

export const MESH_EXTENSIONS = /\.(glb|gltf|obj|stl|ply)$/i
export { MAX_VERTICES }
