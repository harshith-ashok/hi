import { ref } from 'vue'

// The one HTML page shown beside the chat. Module-level so a code block deep in a reply can open it.
export interface PreviewPage { html: string; title: string }

const page = ref<PreviewPage | null>(null)

export function usePreview() {
  return {
    page,
    open: (html: string, title = 'Preview') => (page.value = { html, title }),
    close: () => (page.value = null),
  }
}

/** Code-block languages that can be drawn as a page. */
export const isPage = (lang: string) => ['html', 'htm'].includes(lang.toLowerCase())
