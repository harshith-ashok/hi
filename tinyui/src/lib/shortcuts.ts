// The app's keyboard shortcuts: one table, read by the listener (components/app/ShortcutsHost.vue) and by the help sheet.

export type ShortcutId = 'search' | 'newChat' | 'settings' | 'copyLast' | 'help'

export interface Shortcut {
  id: ShortcutId
  key: string // lower-case, as KeyboardEvent.key
  shift?: boolean
  label: string
  anywhere?: boolean // also works while typing in a text field other than the message box
}

export const isMac = typeof navigator !== 'undefined' && /mac|iphone|ipad/i.test(navigator.platform || navigator.userAgent)

export const SHORTCUTS: Shortcut[] = [
  { id: 'search', key: 'k', label: 'Search chats', anywhere: true },
  { id: 'newChat', key: 'o', shift: true, label: 'New chat' },
  { id: 'settings', key: ',', label: 'Open settings', anywhere: true },
  { id: 'copyLast', key: 'c', shift: true, label: 'Copy the last reply' },
  { id: 'help', key: '/', label: 'Show shortcuts and commands', anywhere: true },
]

/** Ctrl+B (or Cmd+B) toggles the sidebar and Esc stops a reply; both are handled elsewhere but listed in the help. */
export const OTHER_KEYS: { keys: string; label: string }[] = [
  { keys: `${isMac ? '⌘' : 'Ctrl'} B`, label: 'Show or hide the sidebar' },
  { keys: 'Esc', label: 'Stop the reply' },
  { keys: 'Enter', label: 'Send' },
  { keys: 'Shift Enter', label: 'New line' },
  { keys: '↑ ↓', label: 'Recall earlier messages' },
  { keys: 'Tab', label: 'Accept a suggestion or a command' },
]

export function display(s: Shortcut): string {
  const key = s.key === ',' || s.key === '/' ? s.key : s.key.toUpperCase()
  return isMac ? `${s.shift ? '⇧' : ''}⌘${key}` : `Ctrl+${s.shift ? 'Shift+' : ''}${key}`
}

export function find(e: KeyboardEvent): Shortcut | undefined {
  const mod = isMac ? e.metaKey : e.ctrlKey
  if (!mod || e.altKey || e.isComposing) return undefined
  return SHORTCUTS.find((s) => s.key === e.key.toLowerCase() && !!s.shift === e.shiftKey)
}

/** Whether a shortcut may fire for a key pressed in `target` (a text field other than the message box only allows
 *  the shortcuts marked `anywhere`). */
export function allowedIn(s: Shortcut, target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  const editable = !!el?.closest?.('input, textarea, select, [contenteditable="true"]')
  return !editable || el?.getAttribute?.('aria-label') === 'Message' || !!s.anywhere
}
