import { ref, watch } from 'vue'
import { getJson } from '@/backend'

// The one artifact shown beside the chat (a page, document, diagram or code a reply wrote). Module-level so a card deep
// in a reply can open it.
export type ArtifactKind = 'html' | 'svg' | 'markdown' | 'mermaid' | 'code'

/** What the backend saved for a turn (hi/memory/artifacts.py). */
export interface SavedArtifact { slug: string; title: string; kind: ArtifactKind; version: number }

export interface Shown {
  title: string
  kind: ArtifactKind
  ext: string
  content: string
  version: number
  versions: number[] // every version saved, oldest first; one entry for a block that was never saved
  session?: string
  slug?: string
}

const shown = ref<Shown | null>(null)
const loading = ref(false)

/** Open the panel by itself when a reply makes an artifact. */
export const autoOpen = ref(localStorage.getItem('artifactsAuto') !== '0')
watch(autoOpen, (on) => localStorage.setItem('artifactsAuto', on ? '1' : '0'))

/** The id the backend gives a title (hi/memory/artifacts.py slugify). */
export const slugify = (title: string) => title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40).replace(/-+$/, '') || 'untitled'

/** Code-block languages that can be drawn as a page. */
export const isPage = (lang: string) => ['html', 'htm'].includes(lang.toLowerCase())

async function openSaved(session: string, slug: string, version: number): Promise<boolean> {
  loading.value = true
  const found = await getJson<Omit<Shown, 'session' | 'slug'>>(`/artifacts/${session}/${slug}/${version}`)
  loading.value = false
  if (found) shown.value = { ...found, session, slug }
  return !!found
}

export function useArtifact() {
  return {
    shown,
    loading,
    autoOpen,
    openSaved,
    /** An html block with no `artifact` mark: shown, but not saved and with no versions. */
    openInline: (html: string, title = 'Preview') => (shown.value = { title, kind: 'html', ext: 'html', content: html, version: 1, versions: [1] }),
    close: () => (shown.value = null),
  }
}
