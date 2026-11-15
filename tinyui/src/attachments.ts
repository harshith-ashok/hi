// Files dropped (or pasted) into the window become context for the next message.
// Dropping only uploads; nothing is sent to the agent until the user sends a message.

import { reactive, ref } from 'vue'
import { uploadContext } from './backend'
import { toWav } from './voice'

export interface Attachment {
  key: number
  name: string
  status: 'reading' | 'ready' | 'failed'
  id?: string
  detail?: string
}

const AUDIO = /\.(mp3|m4a|aac|ogg|oga|flac|opus|webm|wav|caf)$/i
const MAX_FILES = 50
const MAX_CONVERT_BYTES = 100_000_000

// A dropped folder arrives as entries, not files: walk it.
async function filesOf(entry: FileSystemEntry): Promise<File[]> {
  if (entry.isFile) return [await new Promise<File>((ok, no) => (entry as FileSystemFileEntry).file(ok, no))]
  const reader = (entry as FileSystemDirectoryEntry).createReader()
  const children: FileSystemEntry[] = []
  for (;;) {
    const batch = await new Promise<FileSystemEntry[]>((ok, no) => reader.readEntries(ok, no))
    if (!batch.length) break
    children.push(...batch)
  }
  return (await Promise.all(children.map(filesOf))).flat()
}

export function useAttachments() {
  const items = ref<Attachment[]>([])
  let next = 0

  async function addFile(file: File) {
    const item = reactive<Attachment>({ key: next++, name: file.name, status: 'reading' })
    items.value.push(item)
    try {
      const audio = AUDIO.test(file.name)
      let body: Blob = file
      let name = file.name
      if (audio && file.size <= MAX_CONVERT_BYTES) {
        // Convert to the 16 kHz mono WAV that the whisper.cpp server needs (the in-process
        // Whisper takes any format). Bigger files go up as they are: decoding holds them in memory.
        body = await toWav(file).catch(() => file)
        if (body !== file) name += '.wav'
      }
      const saved = await uploadContext(body, name, audio ? 'audio' : '')
      item.id = saved.id
      item.status = 'ready'
    } catch (err) {
      item.status = 'failed'
      item.detail = (err as Error).message
    }
  }

  // Must be called synchronously from the drop event: the DataTransfer empties afterwards.
  function addFromTransfer(data: DataTransfer) {
    const entries = [...data.items].map((i) => i.webkitGetAsEntry?.()).filter((e): e is FileSystemEntry => !!e)
    const loose = [...data.files]
    const collect = entries.length ? Promise.all(entries.map(filesOf)).then((f) => f.flat()) : Promise.resolve(loose)
    void collect.then((files) => files.slice(0, MAX_FILES).forEach((f) => void addFile(f)))
  }

  function addFromPaste(data: DataTransfer | null): boolean {
    const files = [...(data?.files ?? [])]
    files.forEach((f) => void addFile(f))
    return files.length > 0
  }

  const remove = (key: number) => (items.value = items.value.filter((i) => i.key !== key))
  const clear = () => (items.value = [])
  const reading = () => items.value.some((i) => i.status === 'reading')
  const ready = () => items.value.filter((i) => i.status === 'ready')

  return { items, addFromTransfer, addFromPaste, remove, clear, reading, ready }
}
