<script setup lang="ts">
// An interactive 3D view: drag to rotate, scroll to zoom, right-drag to pan. Shows a scene described as data
// (hi/scene3d.py) or a mesh file (.glb .gltf .obj .stl .ply). three.js is loaded on first use, and a WebGL context is
// only held while the viewer is on screen (browsers allow only a handful at once).
import { Box, Download, Grid3x3, Maximize2, RefreshCw, RotateCw, TriangleAlert } from '@lucide/vue'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useTheme } from '@/composables/useTheme'
import { buildScene, disposeTree, MESH_EXTENSIONS, parseScene, type Animated, type SceneData } from '@/lib/scene3d'
import { cn } from '@/lib/utils'

type ThreeModule = typeof import('three')

const props = defineProps<{ src?: string; scene?: SceneData; title?: string; large?: boolean }>()

const { dark } = useTheme()
const host = ref<HTMLDivElement>()
const canvas = ref<HTMLCanvasElement>()
const loading = ref(true)
const error = ref('')
const poster = ref('') // the last picture, shown while the renderer is released
const autoRotate = ref(false)
const wire = ref(false)
const expanded = ref(false)
const info = ref('')
const heading = ref(props.title ?? '3D')

interface Live {
  THREE: ThreeModule
  renderer: import('three').WebGLRenderer
  scene: import('three').Scene
  camera: import('three').PerspectiveCamera
  controls: import('three/examples/jsm/controls/OrbitControls.js').OrbitControls
  root: import('three').Object3D
  animated: Animated[]
  grid?: import('three').GridHelper
  raf: number
  dirty: boolean
  home: { position: import('three').Vector3; target: import('three').Vector3 }
}
let live: Live | null = null
let data: SceneData | null = null
let visible = false
let starting = false
let observer: IntersectionObserver | undefined
let resizer: ResizeObserver | undefined
let hiddenTimer = 0
const clock = { last: 0 }

const background = () => (dark.value ? '#18181b' : '#f4f4f5')

async function loadSceneData(): Promise<SceneData> {
  if (props.scene) return props.scene
  const res = await fetch(props.src!)
  if (!res.ok) throw new Error(`could not load the scene (${res.status})`)
  const parsed = parseScene(await res.text())
  if ('error' in parsed) throw new Error(parsed.error)
  return parsed.scene
}

async function loadMesh(THREE: ThreeModule): Promise<import('three').Object3D> {
  const url = props.src!
  const ext = /\.(\w+)$/.exec(url.split('?')[0])?.[1]?.toLowerCase()
  const fallback = () => new THREE.MeshStandardMaterial({ color: '#8899aa', metalness: 0.1, roughness: 0.6 })
  if (ext === 'glb' || ext === 'gltf') {
    const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
    return (await new GLTFLoader().loadAsync(url)).scene
  }
  if (ext === 'obj') {
    const { OBJLoader } = await import('three/examples/jsm/loaders/OBJLoader.js')
    const group = await new OBJLoader().loadAsync(url)
    group.traverse((n) => { if ((n as import('three').Mesh).isMesh) (n as import('three').Mesh).material = fallback() })
    return group
  }
  if (ext === 'stl') {
    const { STLLoader } = await import('three/examples/jsm/loaders/STLLoader.js')
    return new THREE.Mesh(await new STLLoader().loadAsync(url), fallback())
  }
  const { PLYLoader } = await import('three/examples/jsm/loaders/PLYLoader.js')
  const geometry = await new PLYLoader().loadAsync(url)
  geometry.computeVertexNormals()
  const colored = !!geometry.getAttribute('color')
  return new THREE.Mesh(geometry, colored ? new THREE.MeshStandardMaterial({ vertexColors: true }) : fallback())
}

function frame(l: Live, fov: number) {
  const { THREE } = l
  const box = new THREE.Box3().setFromObject(l.root)
  if (box.isEmpty()) return
  const size = box.getSize(new THREE.Vector3())
  const center = box.getCenter(new THREE.Vector3())
  const span = Math.max(size.x, size.y, size.z) || 1
  const distance = (span / (2 * Math.tan(THREE.MathUtils.degToRad(fov) / 2))) * 1.5 + span * 0.3
  l.camera.position.set(center.x + distance * 0.8, center.y + distance * 0.55, center.z + distance * 0.8)
  l.controls.target.copy(center)
  l.camera.near = span / 200
  l.camera.far = span * 200
  l.camera.updateProjectionMatrix()
  l.grid?.position.set(center.x, box.min.y, center.z)
  info.value = `${size.x.toFixed(1)} × ${size.y.toFixed(1)} × ${size.z.toFixed(1)}`
}

function resize() {
  if (!live || !host.value) return
  const { clientWidth: w, clientHeight: h } = host.value
  if (!w || !h) return
  live.renderer.setSize(w, h, false)
  live.camera.aspect = w / h
  live.camera.updateProjectionMatrix()
  live.dirty = true
}

function tick(now: number) {
  const l = live
  if (!l) return
  l.raf = requestAnimationFrame(tick)
  const dt = Math.min(0.1, (now - clock.last) / 1000)
  clock.last = now
  const moving = l.animated.length > 0 || autoRotate.value
  if (!moving && !l.dirty) return
  for (const a of l.animated) {
    if (a.rotate) { a.object.rotation.x += a.rotate[0] * dt; a.object.rotation.y += a.rotate[1] * dt; a.object.rotation.z += a.rotate[2] * dt }
    if (a.bob) a.object.position.y = a.baseY + Math.sin(now / 600) * a.bob
  }
  l.controls.autoRotate = autoRotate.value
  l.controls.update()
  l.renderer.render(l.scene, l.camera)
  l.dirty = false
}

async function start() {
  if (live || starting || !visible || !canvas.value) return
  starting = true
  loading.value = !poster.value
  error.value = ''
  try {
    const THREE = await import('three')
    const { OrbitControls } = await import('three/examples/jsm/controls/OrbitControls.js')
    let root: import('three').Object3D
    let animated: Animated[] = []
    let lights: import('three').Light[] = []
    let sceneData: SceneData | null = null
    if (props.scene || (props.src && !MESH_EXTENSIONS.test(props.src.split('?')[0]))) {
      data ??= await loadSceneData()
      sceneData = data
      heading.value = props.title ?? data.title ?? '3D scene'
      const built = buildScene(THREE, data)
      root = built.root
      animated = built.animated
      lights = built.lights
    } else {
      root = await loadMesh(THREE)
      const sun = new THREE.DirectionalLight('#ffffff', 2.2)
      sun.position.set(3, 5, 4)
      lights = [new THREE.AmbientLight('#ffffff', 0.7), new THREE.HemisphereLight('#ffffff', '#555566', 0.6), sun]
    }
    if (!visible || !canvas.value) { disposeTree(root); return } // scrolled away while loading

    let renderer: import('three').WebGLRenderer
    try {
      renderer = new THREE.WebGLRenderer({ canvas: canvas.value, antialias: true })
    } catch {
      throw new Error('3D is not available here: the browser could not start WebGL.')
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    const scene = new THREE.Scene()
    scene.background = new THREE.Color(sceneData?.background ?? background())
    scene.add(root, ...lights)
    const fov = sceneData?.camera?.fov ?? 50
    const camera = new THREE.PerspectiveCamera(fov, 1, 0.01, 1000)
    const controls = new OrbitControls(camera, canvas.value)
    controls.enableDamping = true
    controls.autoRotateSpeed = 2
    let grid: import('three').GridHelper | undefined
    if (sceneData?.grid !== false) {
      grid = new THREE.GridHelper(20, 20, dark.value ? '#52525b' : '#a1a1aa', dark.value ? '#3f3f46' : '#d4d4d8')
      scene.add(grid)
    }
    if (sceneData?.axes) scene.add(new THREE.AxesHelper(2))
    const l: Live = { THREE, renderer, scene, camera, controls, root, animated, grid, raf: 0, dirty: true, home: { position: new THREE.Vector3(), target: new THREE.Vector3() } }
    live = l
    controls.addEventListener('change', () => { l.dirty = true })
    frame(l, fov)
    if (sceneData?.camera?.position) camera.position.set(...sceneData.camera.position)
    if (sceneData?.camera?.target) controls.target.set(...sceneData.camera.target)
    l.home.position.copy(camera.position)
    l.home.target.copy(controls.target)
    autoRotate.value = autoRotate.value || !!sceneData?.autoRotate
    if (wire.value) setWire(true)
    resize()
    poster.value = ''
    clock.last = performance.now()
    l.raf = requestAnimationFrame(tick)
  } catch (err) {
    error.value = (err as Error).message || 'Could not draw this.'
  } finally {
    loading.value = false
    starting = false
  }
}

/** Free the WebGL context, keeping a picture of the last frame. */
function release(keepPoster = true) {
  const l = live
  if (!l) return
  cancelAnimationFrame(l.raf)
  if (keepPoster) {
    l.renderer.render(l.scene, l.camera)
    poster.value = l.renderer.domElement.toDataURL('image/png')
  }
  l.controls.dispose()
  disposeTree(l.root)
  l.renderer.dispose()
  l.renderer.forceContextLoss()
  live = null
}

function setWire(on: boolean) {
  if (!live) return
  live.root.traverse((n) => {
    const mats = (n as import('three').Mesh).material
    for (const m of Array.isArray(mats) ? mats : mats ? [mats] : []) (m as import('three').MeshBasicMaterial).wireframe = on
  })
  live.dirty = true
}

function reset() {
  if (!live) return
  live.camera.position.copy(live.home.position)
  live.controls.target.copy(live.home.target)
  live.controls.update()
  live.dirty = true
}

function snapshot() {
  if (!live) return
  live.renderer.render(live.scene, live.camera)
  const a = Object.assign(document.createElement('a'), { href: live.renderer.domElement.toDataURL('image/png'), download: `${heading.value.replace(/\W+/g, '-').toLowerCase()}.png` })
  a.click()
}

watch(wire, setWire)
watch(autoRotate, () => { if (live) live.dirty = true })
watch(dark, () => {
  if (!live || data?.background) return
  live.scene.background = new live.THREE.Color(background())
  live.dirty = true
})

onMounted(() => {
  observer = new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting
    clearTimeout(hiddenTimer)
    if (visible) void start()
    else hiddenTimer = window.setTimeout(() => !visible && release(), 4000) // not on screen for a while: give the GPU back
  }, { rootMargin: '200px' })
  if (host.value) {
    observer.observe(host.value)
    resizer = new ResizeObserver(resize)
    resizer.observe(host.value)
  }
})
onBeforeUnmount(() => {
  clearTimeout(hiddenTimer)
  observer?.disconnect()
  resizer?.disconnect()
  release(false)
})
</script>

<template>
  <figure class="not-prose my-3 overflow-hidden rounded-lg border bg-card">
    <figcaption class="flex items-center gap-1 border-b px-3 py-1.5 text-xs text-muted-foreground">
      <Box class="size-3.5" />
      <span class="font-medium">{{ heading }}</span>
      <span v-if="info" class="ml-1 font-mono">{{ info }}</span>
      <span class="grow" />
      <Tooltip><TooltipTrigger as-child><Button variant="ghost" size="icon" :class="cn('size-7', autoRotate && 'bg-accent')" :aria-pressed="autoRotate" aria-label="Auto-rotate" @click="autoRotate = !autoRotate"><RotateCw class="size-3.5" /></Button></TooltipTrigger><TooltipContent>Auto-rotate</TooltipContent></Tooltip>
      <Tooltip><TooltipTrigger as-child><Button variant="ghost" size="icon" :class="cn('size-7', wire && 'bg-accent')" :aria-pressed="wire" aria-label="Wireframe" @click="wire = !wire"><Grid3x3 class="size-3.5" /></Button></TooltipTrigger><TooltipContent>Wireframe</TooltipContent></Tooltip>
      <Tooltip><TooltipTrigger as-child><Button variant="ghost" size="icon" class="size-7" aria-label="Reset the view" @click="reset"><RefreshCw class="size-3.5" /></Button></TooltipTrigger><TooltipContent>Reset the view</TooltipContent></Tooltip>
      <Tooltip><TooltipTrigger as-child><Button variant="ghost" size="icon" class="size-7" aria-label="Save a picture" @click="snapshot"><Download class="size-3.5" /></Button></TooltipTrigger><TooltipContent>Save a picture</TooltipContent></Tooltip>
      <Tooltip v-if="!large"><TooltipTrigger as-child><Button variant="ghost" size="icon" class="size-7" aria-label="Expand" @click="expanded = true"><Maximize2 class="size-3.5" /></Button></TooltipTrigger><TooltipContent>Expand</TooltipContent></Tooltip>
    </figcaption>

    <div ref="host" :class="cn('relative w-full touch-none', large ? 'h-[70vh]' : 'h-[360px]')">
      <canvas ref="canvas" class="size-full" aria-label="Interactive 3D view. Drag to rotate, scroll to zoom." role="img" />
      <img v-if="poster && !live" :src="poster" alt="" class="absolute inset-0 size-full object-cover" />
      <div v-if="loading" class="absolute inset-0 grid place-items-center bg-card" role="status" aria-label="Loading the 3D view"><Skeleton class="size-2/3" /></div>
      <div v-if="error" class="absolute inset-0 grid place-items-center bg-card p-4">
        <Alert variant="destructive" class="max-w-md"><TriangleAlert class="size-4" /><AlertDescription class="text-xs">{{ error }}</AlertDescription></Alert>
      </div>
    </div>

    <Dialog v-if="!large" v-model:open="expanded">
      <DialogContent class="w-[min(1200px,94vw)] max-w-none sm:max-w-none" @open-auto-focus.prevent>  <!-- no focus on a tool button: its tooltip would take the first Escape -->
        <DialogHeader><DialogTitle>{{ heading }}</DialogTitle></DialogHeader>
        <Viewer3D v-if="expanded" :src="src" :scene="scene" :title="title" large />
      </DialogContent>
    </Dialog>
  </figure>
</template>
