// Projects: named workspaces (instructions, files and chats), kept in the vault by the backend. One shared list for the
// sidebar, the projects page and the chat.

import { ref } from 'vue'
import { BASE_URL, deleteJson, getJson, patchJson, postJson } from '@/backend'
import type { SessionInfo } from '@/composables/useSessions'

export interface ProjectSummary { slug: string; name: string; description: string; files: number }
export interface ProjectFile { name: string; size: number }
export interface ProjectDetail { slug: string; name: string; description: string; instructions: string; files: ProjectFile[]; chats: SessionInfo[] }

const projects = ref<ProjectSummary[]>([])
const loaded = ref(false)
/** The project open on the projects page. */
const selected = ref('')
/** The project a chat started now belongs to ('' = none): set by "New chat" on a project page, cleared by the sidebar's. */
const startIn = ref('')

async function refresh() {
  const rows = await getJson<ProjectSummary[]>('/projects')
  if (rows) projects.value = rows
  loaded.value = true
}

async function create(name: string, description = '', instructions = ''): Promise<ProjectDetail | null> {
  const made = await postJson<ProjectDetail>('/projects', { name, description, instructions })
  if (made) await refresh()
  return made
}

const get = (slug: string) => getJson<ProjectDetail>(`/projects/${slug}`)

async function update(slug: string, fields: Partial<Pick<ProjectDetail, 'name' | 'description' | 'instructions'>>): Promise<ProjectDetail | null> {
  const row = await patchJson<ProjectDetail>(`/projects/${slug}`, fields)
  if (row) await refresh()
  return row
}

async function remove(slug: string): Promise<boolean> {
  const ok = await deleteJson(`/projects/${slug}`)
  if (ok) {
    if (selected.value === slug) selected.value = ''
    if (startIn.value === slug) startIn.value = ''
    await refresh()
  }
  return ok
}

async function uploadFile(slug: string, file: File): Promise<boolean> {
  try {
    const res = await fetch(`${BASE_URL}/projects/${slug}/files?name=${encodeURIComponent(file.name)}`, { method: 'POST', headers: { 'X-Hi-Client': 'tinyui' }, body: file })
    return res.ok
  } catch {
    return false
  }
}

const removeFile = (slug: string, name: string) => deleteJson(`/projects/${slug}/files/${encodeURIComponent(name)}`)

export const useProjects = () => ({ projects, loaded, selected, startIn, refresh, create, get, update, remove, uploadFile, removeFile })
