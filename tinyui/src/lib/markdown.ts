// Splits Markdown into pieces the chat draws differently: prose (HTML, with math), code blocks, and Mermaid diagrams.

import DOMPurify from 'dompurify'
import { marked, type Token, type TokensList } from 'marked'
import { BASE_URL } from '@/backend'
import { mathExtensions } from '@/lib/math'
import 'katex/dist/katex.min.css'

marked.use({ extensions: mathExtensions }) // $…$ and $$…$$ (hi's replies, KaTeX)

export type Segment =
  | { kind: 'html'; html: string }
  | { kind: 'code'; lang: string; text: string }
  | { kind: 'mermaid'; text: string; closed: boolean }
  | { kind: 'scene3d'; text: string; closed: boolean }
  | { kind: 'artifact'; lang: string; title: string; text: string; closed: boolean }

DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

// Charts and files the assistant makes are served by the backend; a relative path would point at the web UI.
const absolute = (html: string) => html.replace(/(src|href)="(\/(?:plots|files)\/[^"]+)"/g, `$1="${BASE_URL}$2"`)

const render = (group: Token[], links: TokensList['links']) =>
  absolute(DOMPurify.sanitize(marked.parser(Object.assign([...group], { links }) as TokensList, { gfm: true, breaks: true })))

/** A fenced block is closed when its raw text ends with the fence it opened with. While a reply streams the last
 *  block may not be: drawing it then would only flicker. */
const isClosed = (raw: string) => /\n(```|~~~)\s*$/.test(raw.trimEnd()) || /^(```|~~~)[^\n]*\n?(```|~~~)\s*$/.test(raw.trimEnd())

/** The artifact kind for a code-fence language (hi/memory/artifacts.py kind_of). */
export const kindOf = (lang: string): 'html' | 'svg' | 'markdown' | 'mermaid' | 'code' =>
  ({ html: 'html', htm: 'html', svg: 'svg', md: 'markdown', markdown: 'markdown', mermaid: 'mermaid' } as const)[lang.toLowerCase() as 'html'] ?? 'code'

export function segments(source: string): Segment[] {
  const tokens = marked.lexer(source, { gfm: true, breaks: true })
  const out: Segment[] = []
  let group: Token[] = []
  const flush = () => {
    if (group.length) out.push({ kind: 'html', html: render(group, tokens.links) })
    group = []
  }
  for (const token of tokens) {
    if (token.type === 'code') {
      flush()
      const info = (token.lang ?? '').trim().split(/\s+/)
      const lang = info[0].toLowerCase()
      const isArtifact = /(^|\s)artifact(\s|$)/.test(info.slice(1).join(' '))
      if (isArtifact) out.push({ kind: 'artifact', lang, title: /title\s*=\s*(?:"([^"]*)"|'([^']*)')/.exec(info.join(' '))?.slice(1).find(Boolean)?.trim() || 'Untitled', text: token.text, closed: isClosed(token.raw) })
      else if (lang === 'mermaid') out.push({ kind: 'mermaid', text: token.text, closed: isClosed(token.raw) })
      else if (lang === 'scene3d' || lang === '3d') out.push({ kind: 'scene3d', text: token.text, closed: isClosed(token.raw) })
      else out.push({ kind: 'code', lang, text: token.text })
    } else group.push(token)
  }
  flush()
  return out
}
