// Real Markdown rendering for assistant/subagent text — picking up a
// deliberate earlier deferral (frontend/README.md's own "no markdown
// rendering... add a renderer later if it's actually wanted"). marked
// (parsing) + marked-highlight/highlight.js (code blocks) +
// DOMPurify (sanitizing before it's ever used as v-html) — the exact
// same combination already proven for this kind of LLM-generated-
// markdown-into-a-dark-terminal-themed-UI job in the sibling `sage`
// project's own Console, not picked blind.

import { marked } from 'marked'
import { markedHighlight } from 'marked-highlight'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'

marked.use(
  markedHighlight({
    langPrefix: 'hljs language-',
    highlight(code: string, lang: string) {
      const language = hljs.getLanguage(lang) ? lang : undefined
      try {
        return language ? hljs.highlight(code, { language }).value : hljs.highlightAuto(code).value
      } catch {
        return code
      }
    },
  }),
)
marked.setOptions({ gfm: true, breaks: true })

// Deliberately no LaTeX/KaTeX handling: nothing in this project's own
// transcripts (unlike the sibling `sage` project's, which built real
// KaTeX rendering after confirming its models leaned on math notation)
// shows hi's personas reaching for \[...\]/\(...\) math markup — not
// worth a whole new rendering dependency on a need that isn't
// confirmed here. Revisit if that turns out wrong in practice.

export function renderMarkdown(text: string): string {
  try {
    const html = marked.parse(text, { async: false }) as string
    return DOMPurify.sanitize(html)
  } catch {
    // A markdown-pipeline surprise degrades to escaped plain text
    // instead of an empty/broken render.
    const div = document.createElement('div')
    div.textContent = text
    return div.innerHTML
  }
}
