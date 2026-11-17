// Mermaid, loaded on first use (it is large) and used one render at a time (it shares global state).

type Mermaid = typeof import('mermaid').default

let loading: Promise<Mermaid> | null = null
let queue: Promise<unknown> = Promise.resolve()
let configured = ''
let counter = 0

const load = () => (loading ??= import('mermaid').then((m) => m.default))
export const isDark = () => document.documentElement.classList.contains('dark')

const messageOf = (err: unknown) => (err instanceof Error ? err.message : String(err)).split('\n').slice(0, 3).join(' ').trim()

export type Rendered = { svg: string } | { error: string }

/** Draw `code` as an SVG string, or say why it could not be drawn. Never throws. */
export function renderMermaid(code: string): Promise<Rendered> {
  const run = async (): Promise<Rendered> => {
    const mermaid = await load()
    const theme = isDark() ? 'dark' : 'neutral'
    if (configured !== theme) {
      mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme, fontFamily: 'inherit', flowchart: { useMaxWidth: true } })
      configured = theme
    }
    const id = `mmd-${++counter}`
    try {
      await mermaid.parse(code)
      const { svg } = await mermaid.render(id, code)
      return { svg }
    } catch (err) {
      document.getElementById(`d${id}`)?.remove() // Mermaid leaves its error graphic in the page
      return { error: messageOf(err) }
    }
  }
  const result = queue.then(run, run)
  queue = result.catch(() => undefined)
  return result
}

/** Escape a label for use inside a quoted Mermaid node. */
export const label = (text: string, max = 40) => {
  const flat = text.replace(/["\\[\](){}<>|#;]/g, ' ').replace(/\s+/g, ' ').trim()
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat
}
