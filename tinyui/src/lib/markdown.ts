// Splits Markdown into pieces the chat draws differently: prose (HTML), code blocks, and Mermaid diagrams.

import DOMPurify from 'dompurify'
import { marked, type Token, type TokensList } from 'marked'
import { BASE_URL } from '@/backend'

export type Segment =
  | { kind: 'html'; html: string }
  | { kind: 'code'; lang: string; text: string }
  | { kind: 'mermaid'; text: string; closed: boolean }

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
      const lang = (token.lang ?? '').trim().split(/\s+/)[0].toLowerCase()
      if (lang === 'mermaid') out.push({ kind: 'mermaid', text: token.text, closed: isClosed(token.raw) })
      else out.push({ kind: 'code', lang, text: token.text })
    } else group.push(token)
  }
  flush()
  return out
}
