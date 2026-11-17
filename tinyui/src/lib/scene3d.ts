// Turns a scene description (data, never code) into three.js objects. The backend checks scenes before saving them
// (hi/scene3d.py); this builder checks again, because a scene can also arrive inside an answer.

import type * as THREE_NS from 'three'

type T = typeof THREE_NS
type Vec3 = [number, number, number]

export interface SceneObject {
  type: string
  position?: Vec3
  rotation?: Vec3 // degrees
  scale?: Vec3
  color?: string
  material?: { kind?: string; metalness?: number; roughness?: number; opacity?: number; emissive?: string; flatShading?: boolean; doubleSide?: boolean }
  animate?: { rotate?: Vec3; bob?: number }
  children?: SceneObject[]
  [key: string]: unknown
}

export interface SceneData {
  title?: string
  objects: SceneObject[]
  background?: string
  camera?: { position?: Vec3; target?: Vec3; fov?: number }
  lights?: { type: string; color?: string; intensity?: number; position?: Vec3 }[]
  grid?: boolean
  axes?: boolean
  autoRotate?: boolean
}

const MAX_OBJECTS = 400
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

export interface Animated { object: THREE_NS.Object3D; rotate?: Vec3; bob?: number; baseY: number }

function geometryFor(THREE: T, o: SceneObject): THREE_NS.BufferGeometry | null {
  const r = num(o.radius, 0.5)
  switch (o.type) {
    case 'box': { const [w, h, d] = vec(o.size, [1, 1, 1]); return new THREE.BoxGeometry(w, h, d) }
    case 'sphere': return new THREE.SphereGeometry(r, 48, 32)
    case 'cylinder': return new THREE.CylinderGeometry(r, r, num(o.height, 1), 48)
    case 'cone': return new THREE.ConeGeometry(r, num(o.height, 1), 48)
    case 'capsule': return new THREE.CapsuleGeometry(num(o.radius, 0.3), num(o.length, 0.8), 8, 24)
    case 'torus': return new THREE.TorusGeometry(r, num(o.tube, 0.15), 24, 64)
    case 'torusknot': return new THREE.TorusKnotGeometry(r, num(o.tube, 0.15), 128, 16)
    case 'plane': { const s = Array.isArray(o.size) ? o.size : [1, 1]; return new THREE.PlaneGeometry(num(s[0], 1), num(s[1], 1)) }
    case 'circle': return new THREE.CircleGeometry(r, 48)
    case 'ring': return new THREE.RingGeometry(num(o.inner, 0.3), num(o.outer, 0.5), 48)
    case 'tetrahedron': return new THREE.TetrahedronGeometry(r)
    case 'octahedron': return new THREE.OctahedronGeometry(r)
    case 'dodecahedron': return new THREE.DodecahedronGeometry(r)
    case 'icosahedron': return new THREE.IcosahedronGeometry(r)
    case 'lathe': {
      const pts = points(o.points, 2)
      return pts.length >= 2 ? new THREE.LatheGeometry(pts.map(([x, y]) => new THREE.Vector2(x, y)), 48) : null
    }
    case 'extrude': {
      const pts = points(o.shape, 2)
      if (pts.length < 3) return null
      const shape = new THREE.Shape(pts.map(([x, y]) => new THREE.Vector2(x, y)))
      return new THREE.ExtrudeGeometry(shape, { depth: num(o.depth, 0.3), bevelEnabled: false })
    }
    case 'mesh': {
      const verts = points(o.vertices, 3)
      const faces = Array.isArray(o.faces) ? (o.faces as unknown[]).filter((f): f is number[] => Array.isArray(f) && f.length === 3 && f.every((n) => Number.isInteger(n) && n >= 0 && n < verts.length)) : []
      if (verts.length < 3 || !faces.length) return null
      const g = new THREE.BufferGeometry()
      g.setAttribute('position', new THREE.Float32BufferAttribute(verts.flat(), 3))
      g.setIndex(faces.flat())
      g.computeVertexNormals()
      return g
    }
    default: return null
  }
}

function materialFor(THREE: T, o: SceneObject): THREE_NS.Material {
  const m = o.material ?? {}
  const base = { color: new THREE.Color(o.color ?? '#8899aa'), side: m.doubleSide || o.type === 'plane' ? THREE.DoubleSide : THREE.FrontSide, transparent: num(m.opacity, 1) < 1, opacity: num(m.opacity, 1) }
  switch (m.kind) {
    case 'basic': return new THREE.MeshBasicMaterial(base)
    case 'wireframe': return new THREE.MeshBasicMaterial({ ...base, wireframe: true })
    case 'phong': return new THREE.MeshPhongMaterial({ ...base, flatShading: !!m.flatShading, emissive: new THREE.Color(m.emissive ?? '#000000') })
    case 'toon': return new THREE.MeshToonMaterial(base)
    default: return new THREE.MeshStandardMaterial({ ...base, metalness: num(m.metalness, 0.1), roughness: num(m.roughness, 0.6), flatShading: !!m.flatShading, emissive: new THREE.Color(m.emissive ?? '#000000') })
  }
}

function build(THREE: T, o: SceneObject, animated: Animated[], count: { n: number }, depth: number): THREE_NS.Object3D | null {
  if (++count.n > MAX_OBJECTS || depth > MAX_DEPTH) return null
  let node: THREE_NS.Object3D
  if (o.type === 'group') {
    const group = new THREE.Group()
    for (const child of Array.isArray(o.children) ? o.children : []) {
      const built = build(THREE, child, animated, count, depth + 1)
      if (built) group.add(built)
    }
    node = group
  } else {
    const geometry = geometryFor(THREE, o)
    if (!geometry) return null
    node = new THREE.Mesh(geometry, materialFor(THREE, o))
  }
  node.position.set(...vec(o.position, [0, 0, 0]))
  const [rx, ry, rz] = vec(o.rotation, [0, 0, 0])
  node.rotation.set(THREE.MathUtils.degToRad(rx), THREE.MathUtils.degToRad(ry), THREE.MathUtils.degToRad(rz))
  node.scale.set(...vec(o.scale, [1, 1, 1]))
  if (typeof o.name === 'string') node.name = o.name
  if (o.animate) animated.push({ object: node, rotate: o.animate.rotate ? vec(o.animate.rotate, [0, 0, 0]) : undefined, bob: num(o.animate.bob, 0) || undefined, baseY: node.position.y })
  return node
}

/** The scene as three.js objects, plus the ones that move. */
export function buildScene(THREE: T, data: SceneData): { root: THREE_NS.Group; animated: Animated[]; lights: THREE_NS.Light[] } {
  const root = new THREE.Group()
  const animated: Animated[] = []
  const count = { n: 0 }
  for (const o of data.objects) {
    const built = build(THREE, o, animated, count, 1)
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
  return { root, animated, lights }
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
