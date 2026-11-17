<script setup lang="ts">
// One component of a generated UI, drawn with the app's own components. It calls itself for children.
import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, Circle, Info, Loader2, OctagonX, Star, XCircle } from '@lucide/vue'
import { computed, inject, ref } from 'vue'
import { BASE_URL } from '@/backend'
import CodeBlock from '@/components/content/CodeBlock.vue'
import MarkdownContent from '@/components/content/MarkdownContent.vue'
import MermaidDiagram from '@/components/content/MermaidDiagram.vue'
import Viewer3D from '@/components/content/Viewer3D.vue'
import UiChart from '@/components/genui/UiChart.vue'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import { INPUTS, TONE, UI_KEY, missingRequired, type UiNode, type UiValue } from '@/lib/uispec'

defineOptions({ name: 'UiNode' })
const props = defineProps<{ node: UiNode }>()
const ctx = inject(UI_KEY)!

const isInput = computed(() => INPUTS.has(props.node.type) && !!props.node.name)
const locked = computed(() => ctx.answered.value)
const step = ref(0)
const open = ref(false)

// values
const text = (name: string) => String(ctx.values[name] ?? '')
const num = (name: string) => Number(ctx.values[name] ?? 0)
const flag = (name: string) => ctx.values[name] === true
const list = (name: string) => (Array.isArray(ctx.values[name]) ? (ctx.values[name] as string[]) : [])
function put(name: string, value: UiValue) {
  if (locked.value) return
  ctx.values[name] = value
  delete ctx.errors[name]
}
function onText(name: string, value: string | number) { put(name, String(value)) }
function onNumber(name: string, value: string | number) { put(name, value === '' ? '' : Number(value)) }
function onFlag(name: string, value: boolean | 'indeterminate') { put(name, value === true) }
function onSlider(name: string, value: number[] | undefined) { if (value) put(name, value[0]) }
function toggle(name: string, option: string, on: boolean | 'indeterminate') {
  const now = list(name).filter((v) => v !== option)
  put(name, on === true ? [...now, option] : now)
}
const absolute = (src: string) => (src.startsWith('/') ? BASE_URL + src : src)
const tone = (name?: string) => TONE[name ?? 'neutral'] ?? TONE.neutral
const AlertIcon = computed(() => ({ info: Info, success: CheckCircle2, warning: AlertTriangle, danger: OctagonX })[props.node.tone as string] ?? Info)
const heading = computed(() => `h${Math.min(4, Math.max(1, Number(props.node.level) || 2))}`)
const headingClass = computed(() => ['text-2xl font-bold', 'text-xl font-semibold', 'text-lg font-semibold', 'text-base font-semibold'][Math.min(4, Math.max(1, Number(props.node.level) || 2)) - 1])
const pad = computed(() => (props.node.type === 'grid' ? `grid-cols-1 sm:grid-cols-${Math.min(4, Number(props.node.columns) || 2)}` : ''))

const items = computed<UiNode[]>(() => (Array.isArray(props.node.items) ? props.node.items : []))

// the wizard
const steps = computed<UiNode[]>(() => (Array.isArray(props.node.steps) ? props.node.steps : []))
function next() {
  const missing = missingRequired(steps.value[step.value], ctx.values)
  if (missing.length) return missing.forEach((m) => (ctx.errors[m] = true))
  step.value = Math.min(steps.value.length - 1, step.value + 1)
}
const back = () => (step.value = Math.max(0, step.value - 1))
function finish() { ctx.submit(props.node.action, props.node) }
function fire(action?: string) {
  open.value = false
  if (action) ctx.submit(action)
}
</script>

<template>
  <!-- input components -->
  <div v-if="isInput" class="space-y-2">
    <Label v-if="node.type !== 'checkbox' && node.type !== 'switch' && node.label" :for="`f-${node.name}`" class="text-sm font-medium">
      {{ node.label }}<span v-if="node.required" class="ml-0.5 text-destructive" aria-hidden="true">*</span>
    </Label>
    <p v-if="node.description && node.type !== 'checkbox' && node.type !== 'switch'" class="text-xs text-muted-foreground">{{ node.description }}</p>

    <Input v-if="node.type === 'input'" :id="`f-${node.name}`" :model-value="text(node.name)" :placeholder="node.placeholder" :disabled="locked" autocomplete="off" @update:model-value="onText(node.name, $event)" />
    <Input v-else-if="node.type === 'date'" :id="`f-${node.name}`" type="date" :model-value="text(node.name)" :disabled="locked" @update:model-value="onText(node.name, $event)" />
    <Input v-else-if="node.type === 'number'" :id="`f-${node.name}`" type="number" :min="node.min" :max="node.max" :step="node.step" :model-value="ctx.values[node.name] as number" :disabled="locked" @update:model-value="onNumber(node.name, $event)" />
    <Textarea v-else-if="node.type === 'textarea'" :id="`f-${node.name}`" rows="3" :model-value="text(node.name)" :placeholder="node.placeholder" :disabled="locked" @update:model-value="onText(node.name, $event)" />

    <Select v-else-if="node.type === 'select'" :model-value="text(node.name)" :disabled="locked" @update:model-value="onText(node.name, $event as string)">
      <SelectTrigger :id="`f-${node.name}`" class="w-full max-w-sm"><SelectValue placeholder="Choose…" /></SelectTrigger>
      <SelectContent><SelectItem v-for="o in node.options" :key="o.value" :value="o.value" :disabled="o.disabled">{{ o.label }}</SelectItem></SelectContent>
    </Select>

    <RadioGroup v-else-if="node.type === 'radio'" :model-value="text(node.name)" :disabled="locked" class="gap-2" @update:model-value="onText(node.name, $event as string)">
      <div v-for="o in node.options" :key="o.value" class="flex items-start gap-2.5">
        <RadioGroupItem :id="`f-${node.name}-${o.value}`" :value="o.value" :disabled="o.disabled" class="mt-0.5" />
        <Label :for="`f-${node.name}-${o.value}`" class="flex flex-col items-start gap-0.5 font-normal"><span>{{ o.label }}</span><span v-if="o.description" class="text-xs text-muted-foreground">{{ o.description }}</span></Label>
      </div>
    </RadioGroup>

    <div v-else-if="node.type === 'checkboxes'" class="space-y-2">
      <div v-for="o in node.options" :key="o.value" class="flex items-start gap-2.5">
        <Checkbox :id="`f-${node.name}-${o.value}`" :model-value="list(node.name).includes(o.value)" :disabled="locked || o.disabled" class="mt-0.5" @update:model-value="toggle(node.name, o.value, $event)" />
        <Label :for="`f-${node.name}-${o.value}`" class="flex flex-col items-start gap-0.5 font-normal"><span>{{ o.label }}</span><span v-if="o.description" class="text-xs text-muted-foreground">{{ o.description }}</span></Label>
      </div>
    </div>

    <div v-else-if="node.type === 'checkbox'" class="flex items-start gap-2.5">
      <Checkbox :id="`f-${node.name}`" :model-value="flag(node.name)" :disabled="locked" class="mt-0.5" @update:model-value="onFlag(node.name, $event)" />
      <Label :for="`f-${node.name}`" class="flex flex-col items-start gap-0.5 font-normal"><span>{{ node.label }}<span v-if="node.required" class="ml-0.5 text-destructive">*</span></span><span v-if="node.description" class="text-xs text-muted-foreground">{{ node.description }}</span></Label>
    </div>

    <div v-else-if="node.type === 'switch'" class="flex items-center justify-between gap-4 rounded-lg border p-3">
      <Label :for="`f-${node.name}`" class="flex flex-col items-start gap-0.5 font-normal"><span class="font-medium">{{ node.label }}</span><span v-if="node.description" class="text-xs text-muted-foreground">{{ node.description }}</span></Label>
      <Switch :id="`f-${node.name}`" :model-value="flag(node.name)" :disabled="locked" @update:model-value="onFlag(node.name, $event)" />
    </div>

    <div v-else-if="node.type === 'slider'" class="flex max-w-md items-center gap-3">
      <Slider :id="`f-${node.name}`" :model-value="[num(node.name)]" :min="node.min" :max="node.max" :step="node.step" :disabled="locked" class="flex-1" @update:model-value="onSlider(node.name, $event)" />
      <span class="w-12 text-right font-mono text-sm tabular-nums">{{ num(node.name) }}</span>
    </div>

    <div v-else-if="node.type === 'rating'" class="flex gap-1" role="radiogroup" :aria-label="node.label">
      <button v-for="i in node.max" :key="i" type="button" role="radio" :aria-checked="num(node.name) === i" :aria-label="`${i} of ${node.max}`" :disabled="locked" class="rounded p-0.5 disabled:opacity-60" @click="put(node.name, i)">
        <Star :class="cn('size-6', i <= num(node.name) ? 'fill-warning text-warning' : 'text-muted-foreground')" />
      </button>
    </div>
    <p v-if="ctx.errors[node.name]" class="text-xs text-destructive" role="alert">This one is required.</p>
  </div>

  <!-- layout -->
  <div v-else-if="node.type === 'stack'" class="space-y-4"><UiNode v-for="(c, i) in node.children" :key="i" :node="c" /></div>
  <div v-else-if="node.type === 'row'" class="flex flex-wrap items-center gap-3"><UiNode v-for="(c, i) in node.children" :key="i" :node="c" /></div>
  <div v-else-if="node.type === 'grid'" :class="cn('grid gap-4', pad)"><UiNode v-for="(c, i) in node.children" :key="i" :node="c" /></div>
  <Card v-else-if="node.type === 'card'">
    <CardHeader v-if="node.title || node.description"><CardTitle v-if="node.title">{{ node.title }}</CardTitle><CardDescription v-if="node.description">{{ node.description }}</CardDescription></CardHeader>
    <CardContent class="space-y-4"><UiNode v-for="(c, i) in node.children" :key="i" :node="c" /></CardContent>
  </Card>
  <Tabs v-else-if="node.type === 'tabs'" default-value="0">
    <TabsList><TabsTrigger v-for="(t, i) in node.tabs" :key="i" :value="String(i)">{{ t.label }}</TabsTrigger></TabsList>
    <TabsContent v-for="(t, i) in node.tabs" :key="i" :value="String(i)" class="space-y-4 pt-3"><UiNode v-for="(c, j) in t.children" :key="j" :node="c" /></TabsContent>
  </Tabs>
  <Accordion v-else-if="node.type === 'accordion'" type="single" collapsible class="rounded-lg border px-4">
    <AccordionItem v-for="(t, i) in node.items" :key="i" :value="String(i)">
      <AccordionTrigger>{{ t.label }}</AccordionTrigger>
      <AccordionContent class="space-y-4"><UiNode v-for="(c, j) in t.children" :key="j" :node="c" /></AccordionContent>
    </AccordionItem>
  </Accordion>
  <Separator v-else-if="node.type === 'divider'" />

  <!-- display -->
  <component :is="heading" v-else-if="node.type === 'heading'" :class="headingClass">{{ node.text }}</component>
  <MarkdownContent v-else-if="node.type === 'text'" :source="node.text" />
  <Badge v-else-if="node.type === 'badge'" variant="outline" :class="cn('font-normal', tone(node.tone))">{{ node.text }}</Badge>
  <div v-else-if="node.type === 'alert'" :class="cn('flex gap-3 rounded-lg border p-3 text-sm', tone(node.tone))" role="status">
    <component :is="AlertIcon" class="mt-0.5 size-4 shrink-0" />
    <div><p v-if="node.title" class="font-medium">{{ node.title }}</p><MarkdownContent v-if="node.text" :source="node.text" /></div>
  </div>
  <component :is="node.ordered ? 'ol' : 'ul'" v-else-if="node.type === 'list'" :class="cn('space-y-1 pl-5 text-sm', node.ordered ? 'list-decimal' : 'list-disc')"><li v-for="(item, i) in node.items" :key="i">{{ item }}</li></component>
  <div v-else-if="node.type === 'table'" class="overflow-x-auto rounded-lg border">
    <Table>
      <TableCaption v-if="node.caption">{{ node.caption }}</TableCaption>
      <TableHeader><TableRow><TableHead v-for="(c, i) in node.columns" :key="i">{{ c }}</TableHead></TableRow></TableHeader>
      <TableBody><TableRow v-for="(row, r) in node.rows" :key="r"><TableCell v-for="(cell, c) in row" :key="c">{{ cell }}</TableCell></TableRow></TableBody>
    </Table>
  </div>
  <div v-else-if="node.type === 'stat'" :class="cn('min-w-36 rounded-lg border p-4', tone(node.tone))">
    <p class="text-xs text-muted-foreground">{{ node.label }}</p><p class="text-2xl font-semibold tabular-nums">{{ node.value }}</p><p v-if="node.delta" class="text-xs text-muted-foreground">{{ node.delta }}</p>
  </div>
  <div v-else-if="node.type === 'progress'" class="space-y-1.5"><div class="flex justify-between text-xs text-muted-foreground"><span>{{ node.label }}</span><span class="tabular-nums">{{ node.value }}%</span></div><Progress :model-value="node.value" /></div>
  <CodeBlock v-else-if="node.type === 'code'" :lang="node.lang" :text="node.text" />
  <img v-else-if="node.type === 'image' && node.src" :src="absolute(node.src)" :alt="node.alt" class="max-h-96 max-w-full rounded-lg border object-contain" loading="lazy" />
  <UiChart v-else-if="node.type === 'chart'" :kind="node.kind" :data="node.data" :title="node.title" />
  <MermaidDiagram v-else-if="node.type === 'mermaid'" :code="node.code" />
  <Viewer3D v-else-if="node.type === 'scene3d'" :scene="node.scene" />
  <ol v-else-if="node.type === 'timeline' || node.type === 'steps'" class="space-y-0">
    <li v-for="(it, i) in items" :key="i" class="relative flex gap-3 pb-4 last:pb-0">
      <span v-if="i < items.length - 1" class="absolute left-[9px] top-5 h-[calc(100%-12px)] w-px bg-border" aria-hidden="true" />
      <Loader2 v-if="it.state === 'active'" class="relative mt-0.5 size-5 shrink-0 animate-spin bg-background text-info" />
      <CheckCircle2 v-else-if="it.state === 'done'" class="relative mt-0.5 size-5 shrink-0 bg-background text-success" />
      <XCircle v-else-if="it.state === 'failed'" class="relative mt-0.5 size-5 shrink-0 bg-background text-destructive" />
      <Circle v-else class="relative mt-0.5 size-5 shrink-0 bg-background text-muted-foreground/60" />
      <div class="min-w-0 text-sm"><div class="flex items-baseline gap-2"><span :class="cn('font-medium', it.state === 'pending' && 'text-muted-foreground')">{{ it.title }}</span><span v-if="it.time" class="text-xs text-muted-foreground">{{ it.time }}</span></div><p v-if="it.text" class="text-muted-foreground">{{ it.text }}</p></div>
    </li>
  </ol>

  <!-- actions -->
  <Button v-else-if="node.type === 'button'" :variant="node.variant" :disabled="locked" @click="ctx.submit(node.action)">{{ node.label }}</Button>
  <form v-else-if="node.type === 'form'" class="space-y-4" @submit.prevent="ctx.submit(node.action, node)">
    <UiNode v-for="(c, i) in node.children" :key="i" :node="c" />
    <Button type="submit" :disabled="locked">{{ node.submit }}</Button>
  </form>
  <Dialog v-else-if="node.type === 'dialog'" v-model:open="open">
    <DialogTrigger as-child><Button variant="outline" :disabled="locked">{{ node.trigger }}</Button></DialogTrigger>
    <DialogContent>
      <DialogHeader><DialogTitle>{{ node.title }}</DialogTitle><DialogDescription v-if="node.description">{{ node.description }}</DialogDescription></DialogHeader>
      <div class="space-y-4"><UiNode v-for="(c, i) in node.children" :key="i" :node="c" /></div>
      <DialogFooter><Button v-for="(a, i) in node.actions" :key="i" :variant="a.variant" @click="fire(a.action)">{{ a.label }}</Button></DialogFooter>
    </DialogContent>
  </Dialog>
  <AlertDialog v-else-if="node.type === 'confirm'">
    <AlertDialogTrigger as-child><Button :variant="node.destructive ? 'destructive' : 'default'" :disabled="locked">{{ node.trigger }}</Button></AlertDialogTrigger>
    <AlertDialogContent>
      <AlertDialogHeader><AlertDialogTitle>{{ node.title }}</AlertDialogTitle><AlertDialogDescription v-if="node.description">{{ node.description }}</AlertDialogDescription></AlertDialogHeader>
      <AlertDialogFooter><AlertDialogCancel>{{ node.cancel }}</AlertDialogCancel><AlertDialogAction :class="node.destructive ? 'bg-destructive text-white hover:bg-destructive/90' : ''" @click="ctx.submit(node.action)">{{ node.confirm }}</AlertDialogAction></AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
  <div v-else-if="node.type === 'wizard'" class="space-y-4 rounded-lg border p-4">
    <ol class="flex flex-wrap items-center gap-2 text-sm" aria-label="Steps">
      <li v-for="(s, i) in steps" :key="i" class="flex items-center gap-2">
        <span :class="cn('flex size-6 items-center justify-center rounded-full border text-xs', i < step && 'border-success bg-success text-white', i === step && 'border-primary bg-primary text-primary-foreground')">{{ i < step ? '✓' : i + 1 }}</span>
        <span :class="i === step ? 'font-medium' : 'text-muted-foreground'">{{ s.title }}</span><span v-if="i < steps.length - 1" class="mx-1 h-px w-6 bg-border" />
      </li>
    </ol>
    <div v-if="steps[step]" class="space-y-4">
      <p v-if="steps[step].description" class="text-sm text-muted-foreground">{{ steps[step].description }}</p>
      <UiNode v-for="(c, i) in steps[step].children" :key="`${step}-${i}`" :node="c" />
    </div>
    <div class="flex justify-between">
      <Button variant="outline" :disabled="step === 0 || locked" @click="back"><ChevronLeft class="size-4" /> Back</Button>
      <Button v-if="step < steps.length - 1" :disabled="locked" @click="next">Next <ChevronRight class="size-4" /></Button>
      <Button v-else :disabled="locked" @click="finish">{{ node.submit }}</Button>
    </div>
  </div>
</template>
