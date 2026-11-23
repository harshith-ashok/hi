// Commands typed in the message box with a leading "/". They run in the app and never reach the model. A skill with one of
// these names is not reachable with "/" (hi/memory/skills.py BUILTIN_COMMANDS keeps the same list), so the built-ins win.

export interface Command { name: string; description: string; usage?: string }

export const COMMANDS: Command[] = [
  { name: 'new', description: 'Start a new chat' },
  { name: 'clear', description: 'Start a new chat (same as /new)' },
  { name: 'help', description: 'Show shortcuts and commands' },
  { name: 'skills', description: 'List the skills you can run' },
  { name: 'model', description: 'Choose the model size', usage: 'fast, balanced, deep or auto' },
  { name: 'tier', description: 'Same as /model', usage: 'fast, balanced, deep or auto' },
  { name: 'config', description: 'Open settings' },
]

/** The model-size names a person types, and what the app calls them. */
export const TIER_NAMES: Record<string, { id: string; label: string }> = {
  auto: { id: 'auto', label: 'Auto' },
  fast: { id: 'haiku', label: 'Fast' }, haiku: { id: 'haiku', label: 'Fast' },
  balanced: { id: 'sonnet', label: 'Balanced' }, sonnet: { id: 'sonnet', label: 'Balanced' },
  deep: { id: 'opus', label: 'Deep' }, opus: { id: 'opus', label: 'Deep' },
}

/** `/name rest` as a built-in command, or null (including for a skill, a path like /Users/me/x, or ordinary text). */
export function parseCommand(text: string): { name: string; arg: string } | null {
  const m = /^\/([A-Za-z][\w-]*)(?:\s+([\s\S]*))?$/.exec(text.trim())
  if (!m) return null
  const name = m[1].toLowerCase()
  return COMMANDS.some((c) => c.name === name) ? { name, arg: (m[2] ?? '').trim() } : null
}
