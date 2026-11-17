// The scene maths language (hi/expr.py checks an expression when a scene is saved; this runs it in the chat).
// A calculator, not JavaScript: numbers, named variables, + - * / % ^, parentheses and the functions below. It compiles to
// closures; nothing is ever passed to eval or Function, so an expression can only produce a number.

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi)
const smooth = (a: number, b: number, x: number) => {
  const t = clamp(b === a ? 0 : (x - a) / (b - a), 0, 1)
  return t * t * (3 - 2 * t)
}
const hash = (x: number, y: number, z: number) => {
  const s = Math.sin(x * 127.1 + y * 311.7 + z * 74.7) * 43758.5453
  return s - Math.floor(s)
}
/** Smooth value noise in [-1, 1]. */
function noise(x: number, y = 0, z = 0): number {
  const [xi, yi, zi] = [Math.floor(x), Math.floor(y), Math.floor(z)]
  const [xf, yf, zf] = [x - xi, y - yi, z - zi].map((f) => f * f * (3 - 2 * f))
  const lerp = (a: number, b: number, k: number) => a + (b - a) * k
  const at = (dx: number, dy: number, dz: number) => hash(xi + dx, yi + dy, zi + dz)
  const v = lerp(
    lerp(lerp(at(0, 0, 0), at(1, 0, 0), xf), lerp(at(0, 1, 0), at(1, 1, 0), xf), yf),
    lerp(lerp(at(0, 0, 1), at(1, 0, 1), xf), lerp(at(0, 1, 1), at(1, 1, 1), xf), yf),
    zf,
  )
  return v * 2 - 1
}

const FUNCTIONS: Record<string, [number, (...a: number[]) => number]> = {
  sin: [1, Math.sin], cos: [1, Math.cos], tan: [1, Math.tan], asin: [1, Math.asin], acos: [1, Math.acos], atan: [1, Math.atan],
  atan2: [2, Math.atan2], sinh: [1, Math.sinh], cosh: [1, Math.cosh], tanh: [1, Math.tanh], sqrt: [1, Math.sqrt], abs: [1, Math.abs],
  exp: [1, Math.exp], log: [1, Math.log], ln: [1, Math.log], log2: [1, Math.log2], log10: [1, Math.log10], pow: [2, Math.pow],
  min: [2, Math.min], max: [2, Math.max], floor: [1, Math.floor], ceil: [1, Math.ceil], round: [1, Math.round], sign: [1, Math.sign],
  mod: [2, (a, b) => ((a % b) + b) % b], hypot: [2, Math.hypot], clamp: [3, clamp], mix: [3, (a, b, k) => a + (b - a) * k],
  smoothstep: [3, smooth], fract: [1, (v) => v - Math.floor(v)], noise: [3, noise], step: [2, (edge, v) => (v >= edge ? 1 : 0)],
}
const CONSTANTS: Record<string, number> = { pi: Math.PI, e: Math.E, tau: Math.PI * 2 }
const BINARY: Record<string, [number, boolean]> = { '+': [1, false], '-': [1, false], '*': [2, false], '/': [2, false], '%': [2, false], '^': [4, true] }
const MAX_CHARS = 300

type Node = (v: number[]) => number
export interface Compiled { fn: (...values: number[]) => number; uses: Set<string> }

function lex(text: string): string[] {
  return text.match(/\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+|[A-Za-z_]\w*|\S/g) ?? []
}

/** Compile `text` over the variables `names` (the values are passed in that order). Throws Error with the reason. */
export function compile(text: string, names: string[]): Compiled {
  if (!text.trim()) throw new Error('empty expression')
  if (text.length > MAX_CHARS) throw new Error('expression too long')
  const tokens = lex(text)
  const uses = new Set<string>()
  let pos = 0
  const peek = () => tokens[pos]
  const take = () => {
    if (pos >= tokens.length) throw new Error('the expression ends too soon')
    return tokens[pos++]
  }

  function parse(min: number): Node {
    let left = unary()
    for (;;) {
      const op = peek()
      const info = op ? BINARY[op] : undefined
      if (!info || info[0] < min) return left
      take()
      const right = parse(info[1] ? info[0] : info[0] + 1)
      const a = left
      left =
        op === '+' ? (v) => a(v) + right(v)
        : op === '-' ? (v) => a(v) - right(v)
        : op === '*' ? (v) => a(v) * right(v)
        : op === '/' ? (v) => a(v) / right(v)
        : op === '%' ? (v) => a(v) % right(v)
        : (v) => Math.pow(a(v), right(v))
    }
  }
  function unary(): Node {
    if (peek() === '-') {
      take()
      const inner = parse(3)
      return (v) => -inner(v)
    }
    if (peek() === '+') {
      take()
      return parse(3)
    }
    return atom()
  }
  function atom(): Node {
    const t = take()
    if (/^[\d.]/.test(t)) {
      const n = Number(t)
      if (!Number.isFinite(n)) throw new Error(`bad number ${t}`)
      return () => n
    }
    if (/^[A-Za-z_]/.test(t)) {
      if (peek() === '(') {
        const spec = FUNCTIONS[t]
        if (!spec) throw new Error(`unknown function ${t}`)
        take()
        const args: Node[] = []
        if (peek() !== ')') {
          args.push(parse(1))
          while (peek() === ',') {
            take()
            args.push(parse(1))
          }
        }
        if (take() !== ')') throw new Error('missing )')
        if (args.length !== spec[0]) throw new Error(`${t} takes ${spec[0]} argument(s)`)
        const f = spec[1]
        return args.length === 1 ? (v) => f(args[0](v)) : args.length === 2 ? (v) => f(args[0](v), args[1](v)) : (v) => f(...args.map((a) => a(v)))
      }
      if (t in CONSTANTS) return () => CONSTANTS[t]
      const i = names.indexOf(t)
      if (i < 0) throw new Error(`unknown name ${t}`)
      uses.add(t)
      return (v) => v[i]
    }
    if (t === '(') {
      const inner = parse(1)
      if (take() !== ')') throw new Error('missing )')
      return inner
    }
    throw new Error(`unexpected ${t}`)
  }

  const root = parse(1)
  if (pos < tokens.length) throw new Error(`unexpected ${tokens[pos]}`)
  return { fn: (...values: number[]) => root(values), uses }
}
