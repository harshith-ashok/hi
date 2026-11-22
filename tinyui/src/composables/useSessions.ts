// The list of conversations, and which one is open. One shared list for the sidebar and the chat.

import { computed, reactive, ref } from 'vue'
import { deleteJson, getJson, patchJson, postJson } from '@/backend'
import type { StoredTurn } from '@/composables/useChat'

export interface SessionInfo {
  id: string
  title: string
  created: string
  updated: string
  pinned: boolean
  archived: boolean
  turns: number
  project?: string // the slug of the project the chat belongs to
  incognito?: boolean // not listed, not remembered; deleted when you leave it
  snippet?: string
}

const KEY = 'session'
const sessions = ref<SessionInfo[]>([])
const titles = reactive<Record<string, string>>({}) // every title seen, so the open chat keeps its name while a search hides it from the list
const query = ref('')
const loaded = ref(false)
const currentId = ref(localStorage.getItem(KEY) ?? '') // '' = a new chat that has no session yet
let refreshing = 0

/** The open incognito chat, if any. It is deleted when you open or start another chat. */
const incognitoId = ref('')
/** The next chat made is incognito (set by the ghost button, cleared by any change of chat). */
const nextIncognito = ref(false)

const remember = (id: string) => {
  const leaving = currentId.value
  if (leaving && leaving === incognitoId.value && id !== leaving) {
    incognitoId.value = ''
    void deleteJson(`/sessions/${leaving}`) // nothing of an incognito chat outlives your visit
  }
  nextIncognito.value = false
  currentId.value = id
  if (id) localStorage.setItem(KEY, id)
  else localStorage.removeItem(KEY)
}

async function refresh() {
  const ticket = ++refreshing
  const rows = await getJson<SessionInfo[]>(`/sessions${query.value.trim() ? `?q=${encodeURIComponent(query.value.trim())}` : ''}`)
  if (ticket !== refreshing || !rows) return // a newer refresh (a newer search) is already on its way
  sessions.value = rows
  for (const row of rows) titles[row.id] = row.title
  loaded.value = true
}

/** Make a session. It is not opened: the caller does that with `select`, once it has set up the chat for it. */
async function create(title = '', project = '', incognito = false): Promise<SessionInfo | null> {
  const made = await postJson<SessionInfo>('/sessions', { ...(title ? { title } : {}), ...(project ? { project } : {}), ...(incognito ? { incognito } : {}) })
  if (made) {
    if (made.incognito) incognitoId.value = made.id // never listed: the backend hides it
    else sessions.value = [made, ...sessions.value]
    titles[made.id] = made.title
  }
  return made
}

const select = (id: string) => remember(id)

/** Show a provisional title in the list right away. The backend sets the same words when the turn is saved. */
function preview(id: string, text: string) {
  const words = text.trim().split(/\s+/)
  const title = words.slice(0, 7).join(' ') + (words.length > 7 ? '…' : '')
  if (!titles[id] || titles[id] === 'New chat') titles[id] = title
  sessions.value = sessions.value.map((s) => (s.id === id && s.title === 'New chat' ? { ...s, title } : s))
}

/** The saved turns of a session, or null if it no longer exists. */
async function open(id: string): Promise<StoredTurn[] | null> {
  const data = await getJson<SessionInfo & { turns: StoredTurn[] }>(`/sessions/${id}`)
  if (!data) {
    if (currentId.value === id) remember('')
    return null
  }
  if (data.incognito) incognitoId.value = id // the page was reloaded inside an incognito chat
  remember(id)
  return data.turns
}

const startNew = () => remember('')

async function rename(id: string, title: string) {
  const row = await patchJson<SessionInfo>(`/sessions/${id}`, { title })
  if (row) {
    titles[id] = row.title
    sessions.value = sessions.value.map((s) => (s.id === id ? { ...s, ...row } : s))
  }
}

async function pin(id: string, pinned: boolean) {
  if (await patchJson(`/sessions/${id}`, { pinned })) await refresh()
}

async function archive(id: string) {
  if (await patchJson(`/sessions/${id}`, { archived: true })) {
    sessions.value = sessions.value.filter((s) => s.id !== id)
    if (currentId.value === id) remember('')
  }
}

async function remove(id: string): Promise<boolean> {
  const ok = await deleteJson(`/sessions/${id}`)
  if (ok) {
    sessions.value = sessions.value.filter((s) => s.id !== id)
    if (currentId.value === id) remember('')
  }
  return ok
}

const DAY = 86_400_000
const GROUPS = ['Pinned', 'Today', 'Yesterday', 'Previous 7 days', 'Earlier'] as const

/** The sessions, grouped by when they were last used. */
const grouped = computed(() => {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const buckets: Record<(typeof GROUPS)[number], SessionInfo[]> = { Pinned: [], Today: [], Yesterday: [], 'Previous 7 days': [], Earlier: [] }
  for (const s of sessions.value) {
    const at = Date.parse(s.updated) || 0
    const key = s.pinned ? 'Pinned' : at >= today ? 'Today' : at >= today - DAY ? 'Yesterday' : at >= today - 7 * DAY ? 'Previous 7 days' : 'Earlier'
    buckets[key].push(s)
  }
  return GROUPS.map((name) => ({ name, items: buckets[name] })).filter((g) => g.items.length)
})

/** Put a chat in a project, or ('') take it out. */
async function setProject(id: string, project: string): Promise<boolean> {
  const row = await patchJson<SessionInfo>(`/sessions/${id}`, { project })
  if (row) sessions.value = sessions.value.map((s) => (s.id === id ? { ...s, ...row } : s))
  return !!row
}

export function useSessions() {
  return { sessions, titles, query, loaded, currentId, incognitoId, nextIncognito, grouped, refresh, create, select, preview, open, startNew, rename, pin, archive, remove, setProject }
}
