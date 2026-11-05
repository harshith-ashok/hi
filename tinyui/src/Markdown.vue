<script setup lang="ts">
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed } from 'vue'

const props = defineProps<{ source: string }>()

DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

const html = computed(() => DOMPurify.sanitize(marked.parse(props.source, { gfm: true, breaks: true, async: false })))
</script>

<template>
  <div class="md" v-html="html" />
</template>

<style>
.md { overflow-wrap: anywhere; }
.md > :first-child { margin-top: 0; }
.md > :last-child { margin-bottom: 0; }
.md h1, .md h2, .md h3, .md h4 { font-size: 1em; margin: 1em 0 0.4em; color: var(--accent); }
.md p, .md ul, .md ol, .md pre, .md table, .md blockquote { margin: 0.5em 0; }
.md ul, .md ol { padding-left: 3ch; }
.md code { background: color-mix(in srgb, var(--dim) 22%, transparent); padding: 0 0.4ch; border-radius: 3px; }
.md pre { background: color-mix(in srgb, var(--dim) 16%, transparent); padding: 8px 12px; overflow-x: auto; border-radius: 4px; }
.md pre code { background: none; padding: 0; }
.md blockquote { border-left: 2px solid var(--dim); padding-left: 2ch; color: var(--dim); }
.md table { border-collapse: collapse; display: block; overflow-x: auto; }
.md th, .md td { border: 1px solid var(--dim); padding: 2px 1.5ch; text-align: left; }
.md a { color: var(--accent); }
.md hr { border: 0; border-top: 1px solid var(--dim); }
</style>
