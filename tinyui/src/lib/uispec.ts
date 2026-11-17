// What the assistant can show as UI (hi/ui_spec.py checks it before it gets here), and how the user's answer is written
// back as a message. Everything here is data: the chat draws only the components it knows.

import type { InjectionKey, Ref } from 'vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type UiNode = { type: string; [key: string]: any }
export interface UiSpec { title?: string; ui: UiNode; interactive?: boolean }
export type UiValue = string | number | boolean | string[]

export const INPUTS = new Set(['input', 'number', 'textarea', 'select', 'radio', 'checkbox', 'checkboxes', 'switch', 'slider', 'date', 'rating'])

export interface UiContext {
  values: Record<string, UiValue>
  errors: Record<string, boolean>
  answered: Ref<boolean>
  submit: (action: string, scope?: UiNode) => boolean
}
export const UI_KEY: InjectionKey<UiContext> = Symbol('genui')

/** Every child list of a node: children, tab and accordion sections, wizard steps. */
function kids(node: UiNode): UiNode[] {
  const out: UiNode[] = Array.isArray(node.children) ? node.children : []
  for (const key of ['tabs', 'items', 'steps']) {
    const sections = node[key]
    if (Array.isArray(sections)) for (const s of sections) if (s && Array.isArray(s.children)) out.push(...s.children)
  }
  return out
}

/** The input components at or below `node`, in order. */
export function inputsIn(node: UiNode): UiNode[] {
  const found: UiNode[] = INPUTS.has(node.type) && node.name ? [node] : []
  for (const child of kids(node)) found.push(...inputsIn(child))
  return found
}

export function defaultFor(node: UiNode): UiValue {
  const d = node.default
  switch (node.type) {
    case 'checkboxes': return Array.isArray(d) ? [...d] : []
    case 'checkbox':
    case 'switch': return !!d
    case 'number':
    case 'slider':
    case 'rating': return typeof d === 'number' ? d : node.type === 'rating' ? 0 : Number(node.min ?? 0)
    default: return typeof d === 'string' ? d : ''
  }
}

export function defaultsOf(root: UiNode): Record<string, UiValue> {
  return Object.fromEntries(inputsIn(root).map((n) => [n.name as string, defaultFor(n)]))
}

export function isEmpty(node: UiNode, value: UiValue | undefined): boolean {
  if (value === undefined) return true
  if (node.type === 'checkboxes') return (value as string[]).length === 0
  if (node.type === 'checkbox' || node.type === 'switch') return value !== true // a required checkbox must be ticked
  if (node.type === 'rating') return value === 0
  return value === '' || value === null
}

/** The names of required inputs under `scope` that have no answer yet. */
export function missingRequired(scope: UiNode, values: Record<string, UiValue>): string[] {
  return inputsIn(scope).filter((n) => n.required && isEmpty(n, values[n.name])).map((n) => n.name as string)
}

function say(node: UiNode, value: UiValue): string {
  const label = (v: string) => (Array.isArray(node.options) ? (node.options.find((o: { value: string; label: string }) => o.value === v)?.label ?? v) : v)
  if (Array.isArray(value)) return value.map(label).join(', ') || '(none)'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  return typeof value === 'string' ? label(value) || '(empty)' : String(value)
}

/** The user's answer as the message that goes back to the assistant. */
export function formatResponse(title: string | undefined, action: string, root: UiNode, values: Record<string, UiValue>): string {
  const lines = inputsIn(root).map((n) => `- ${n.label || n.name}: ${say(n, values[n.name as string] ?? defaultFor(n))}`)
  return [`My response${title ? ` to "${title}"` : ''}: ${action}`, ...lines].join('\n')
}

export const TONE: Record<string, string> = {
  neutral: 'border-border bg-muted/40 text-foreground',
  info: 'border-info/40 bg-info/10 text-foreground',
  success: 'border-success/40 bg-success/10 text-foreground',
  warning: 'border-warning/50 bg-warning/10 text-foreground',
  danger: 'border-destructive/40 bg-destructive/10 text-foreground',
}
