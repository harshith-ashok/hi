// Math in replies: $…$ inline and $$…$$ as a block, drawn with KaTeX. Prices ("$5 and $10") are left alone: an inline
// formula has no space just inside its dollar signs and its closing one is not followed by a digit. Code is untouched
// because marked reads code spans and blocks before it looks for these.

import katex from 'katex'
import type { TokenizerAndRendererExtension } from 'marked'

const draw = (tex: string, displayMode: boolean) => {
  try {
    return katex.renderToString(tex, { displayMode, throwOnError: false, strict: 'ignore', trust: false })
  } catch {
    return `<code>${tex.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]!)}</code>` // never an exception: show the source
  }
}

const BLOCK = /^\$\$[ \t]*\n?([\s\S]+?)\n?[ \t]*\$\$[ \t]*(?:\n|$)/
const INLINE = /^\$(?![\s$])((?:\\.|[^$\\\n])+?)(?<![\s\\])\$(?!\d)/

export const mathExtensions: TokenizerAndRendererExtension[] = [
  {
    name: 'mathBlock',
    level: 'block',
    start: (src) => src.indexOf('$$'),
    tokenizer(src) {
      const m = BLOCK.exec(src)
      return m ? { type: 'mathBlock', raw: m[0], text: m[1].trim() } : undefined
    },
    renderer: (token) => `<div class="math-block">${draw(String(token.text), true)}</div>\n`,
  },
  {
    name: 'mathInline',
    level: 'inline',
    start: (src) => src.indexOf('$'),
    tokenizer(src) {
      const m = INLINE.exec(src)
      return m ? { type: 'mathInline', raw: m[0], text: m[1] } : undefined
    },
    renderer: (token) => draw(String(token.text), false),
  },
]
