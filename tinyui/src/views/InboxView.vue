<script setup lang="ts">
// What the assistant prepared on its own: reports, actions waiting for your approval, and scheduled tasks.
import { CalendarClock, Check, FileText, Pause, Play, ShieldQuestion, Trash2, X } from '@lucide/vue'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import ListRow from '@/components/app/ListRow.vue'
import MasterDetail from '@/components/app/MasterDetail.vue'
import PageHeader from '@/components/app/PageHeader.vue'
import MarkdownContent from '@/components/content/MarkdownContent.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { deleteJson, getJson, postJson } from '@/backend'

interface Report { id: string; headline: string; origin: string; priority: string; created: string; body?: string }
interface Proposal { id: string; tool: string; args: Record<string, unknown>; status: string; origin: string; summary: string; result: string; reason: string; created_at: number }
interface Run { slot: string; status: string; error?: string; report?: string }
interface Schedule { id: string; when: string; enabled: boolean; kind: string; tier: string; deliver: string; prompt: string; next: string[]; runs: Run[] }

const tab = ref<'reports' | 'actions' | 'schedules'>('reports')
const reports = ref<Report[]>([])
const proposals = ref<Proposal[]>([])
const schedules = ref<Schedule[]>([])
const scheduleErrors = ref<string[]>([])
const selected = ref('')
const report = ref<Report | null>(null)
const pane = ref(false)
const busy = ref('')
const message = ref('')
const doomed = ref<Schedule | null>(null)
let timer = 0

const waiting = computed(() => proposals.value.filter((p) => p.status === 'created'))
const proposal = computed(() => proposals.value.find((p) => p.id === selected.value))
const schedule = computed(() => schedules.value.find((s) => s.id === selected.value))

async function load() {
  reports.value = (await getJson<Report[]>('/reports')) ?? reports.value
  proposals.value = (await getJson<Proposal[]>('/proposals')) ?? proposals.value
  const s = await getJson<{ schedules: Schedule[]; errors: string[] }>('/schedules')
  if (s) {
    schedules.value = s.schedules
    scheduleErrors.value = s.errors
  }
}

async function open(id: string) {
  selected.value = id
  pane.value = true
  message.value = ''
  if (tab.value === 'reports') report.value = await getJson<Report>(`/reports/${id}`)
}

function switchTab(next: string) {
  tab.value = next as typeof tab.value
  selected.value = ''
  report.value = null
  pane.value = false
}

async function approve(p: Proposal) {
  busy.value = p.id
  const out = await postJson<{ status: string; result: string }>(`/proposals/${p.id}/approve`)
  message.value = out ? `${out.status}: ${out.result}` : 'Could not approve (already answered?)'
  busy.value = ''
  await load()
}
async function deny(p: Proposal) {
  busy.value = p.id
  await postJson(`/proposals/${p.id}/deny`)
  busy.value = ''
  await load()
}
async function toggle(s: Schedule) {
  await postJson(`/schedules/${s.id}/toggle`)
  await load()
}
async function runNow(s: Schedule) {
  message.value = (await postJson<{ message: string }>(`/schedules/${s.id}/run`))?.message ?? 'Could not start it.'
  await load()
}
async function remove() {
  const s = doomed.value
  doomed.value = null
  if (!s) return
  await deleteJson(`/schedules/${s.id}`)
  selected.value = ''
  pane.value = false
  await load()
}

const when = (ts: number) => new Date(ts * 1000).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' })

onMounted(async () => {
  await load()
  const link = /^#\/inbox\/(.+)$/.exec(window.location.hash) // a link from the island: open that report
  if (link) await open(decodeURIComponent(link[1]))
  timer = window.setInterval(load, 5000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <PageHeader title="Inbox" :subtitle="`${waiting.length} waiting on you · ${reports.length} reports · ${schedules.length} schedules`" />
    <div class="border-b px-4 py-2">
      <Tabs :model-value="tab" @update:model-value="switchTab(String($event))">
        <TabsList>
          <TabsTrigger value="reports"><FileText class="size-3.5" /> Reports</TabsTrigger>
          <TabsTrigger value="actions"><ShieldQuestion class="size-3.5" /> Actions<Badge v-if="waiting.length" class="ml-1.5 h-4 px-1.5">{{ waiting.length }}</Badge></TabsTrigger>
          <TabsTrigger value="schedules"><CalendarClock class="size-3.5" /> Schedules</TabsTrigger>
        </TabsList>
      </Tabs>
    </div>
    <MasterDetail :detail-open="pane" @back="pane = false">
      <template #list>
        <template v-if="tab === 'reports'">
          <ListRow v-for="r in reports" :key="r.id" :active="r.id === selected" @click="open(r.id)">
            <span class="flex items-center gap-2"><span class="truncate text-sm font-medium">{{ r.headline }}</span><Badge variant="outline" class="ml-auto shrink-0 font-normal">{{ r.origin }}</Badge></span>
            <span class="text-xs text-muted-foreground">{{ r.created.slice(0, 16).replace('T', ' ') }}</span>
          </ListRow>
          <p v-if="!reports.length" class="p-4 text-sm text-muted-foreground">Nothing yet. Reports from schedules, the heartbeat and the drop folder appear here.</p>
        </template>
        <template v-else-if="tab === 'actions'">
          <ListRow v-for="p in proposals" :key="p.id" :active="p.id === selected" @click="open(p.id)">
            <span class="flex items-center gap-2"><span class="truncate font-mono text-xs">{{ p.summary }}</span><Badge :variant="p.status === 'created' ? 'default' : 'outline'" class="ml-auto shrink-0">{{ p.status === 'created' ? 'waiting' : p.status }}</Badge></span>
            <span class="text-xs text-muted-foreground">{{ p.id }} · {{ p.origin }} · {{ when(p.created_at) }}</span>
          </ListRow>
          <p v-if="!proposals.length" class="p-4 text-sm text-muted-foreground">Nothing is waiting for approval.</p>
        </template>
        <template v-else>
          <ListRow v-for="s in schedules" :key="s.id" :active="s.id === selected" @click="open(s.id)">
            <span class="flex items-center gap-2"><span class="truncate text-sm font-medium">{{ s.id }}</span><Badge variant="outline" class="ml-auto shrink-0 font-mono text-[10px] font-normal">{{ s.enabled ? s.when : 'paused' }}</Badge></span>
            <span class="text-xs text-muted-foreground">next {{ s.next[0] ?? 'never' }}</span>
          </ListRow>
          <p v-for="e in scheduleErrors" :key="e" class="p-4 text-sm text-destructive">⚠ {{ e }}</p>
          <p v-if="!schedules.length && !scheduleErrors.length" class="p-4 text-sm text-muted-foreground">No schedules. Ask hi: “every weekday at 8 brief me”.</p>
        </template>
      </template>

      <template #detail>
        <div v-if="tab === 'reports' && report" class="space-y-4 p-5">
          <div><h2 class="text-lg font-semibold">{{ report.headline }}</h2><p class="text-xs text-muted-foreground">{{ report.origin }} · {{ report.created }}</p></div>
          <MarkdownContent :source="report.body ?? ''" />
        </div>

        <div v-else-if="tab === 'actions' && proposal" class="space-y-4 p-5">
          <div class="flex flex-wrap items-start gap-3">
            <div><h2 class="font-mono text-lg font-semibold">{{ proposal.tool }}</h2><p class="text-xs text-muted-foreground">{{ proposal.id }} · {{ proposal.origin }} · {{ proposal.status }}</p></div>
            <span class="grow" />
            <template v-if="proposal.status === 'created'">
              <Button :disabled="busy === proposal.id" @click="approve(proposal)"><Check class="size-4" /> Approve and run</Button>
              <Button variant="outline" :disabled="busy === proposal.id" @click="deny(proposal)"><X class="size-4" /> Deny</Button>
            </template>
          </div>
          <div><div class="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Exactly what will run</div><pre class="overflow-auto rounded-lg border bg-muted/40 p-3 font-mono text-xs">{{ proposal.tool }}({{ JSON.stringify(proposal.args, null, 2) }})</pre></div>
          <p v-if="proposal.reason" class="text-sm text-muted-foreground">{{ proposal.reason }}</p>
          <div v-if="proposal.result"><div class="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Result</div><pre class="overflow-auto whitespace-pre-wrap rounded-lg border bg-muted/40 p-3 font-mono text-xs">{{ proposal.result }}</pre></div>
          <p v-if="message" class="text-sm" role="status">{{ message }}</p>
        </div>

        <div v-else-if="tab === 'schedules' && schedule" class="space-y-4 p-5">
          <div class="flex flex-wrap items-start gap-3">
            <div><h2 class="text-lg font-semibold">{{ schedule.id }}</h2><p class="text-xs text-muted-foreground">{{ schedule.kind }} · {{ schedule.when }} · {{ schedule.tier }} · {{ schedule.deliver }}</p></div>
            <span class="grow" />
            <Button variant="outline" size="sm" @click="runNow(schedule)"><Play class="size-3.5" /> Run now</Button>
            <Button variant="outline" size="sm" @click="toggle(schedule)"><component :is="schedule.enabled ? Pause : Play" class="size-3.5" /> {{ schedule.enabled ? 'Pause' : 'Resume' }}</Button>
            <Button variant="destructive" size="sm" @click="doomed = schedule"><Trash2 class="size-3.5" /> Delete</Button>
          </div>
          <pre class="whitespace-pre-wrap rounded-lg border bg-muted/40 p-3 text-sm">{{ schedule.prompt }}</pre>
          <div><div class="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Next</div><p class="text-sm">{{ schedule.next.join(' · ') || 'never' }}</p></div>
          <div v-if="schedule.runs.length">
            <div class="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Recent runs</div>
            <ul class="divide-y rounded-lg border text-sm">
              <li v-for="r in schedule.runs" :key="r.slot + r.status" class="flex items-center gap-3 px-3 py-2"><span class="font-mono text-xs">{{ r.slot.replace('T', ' ').slice(0, 16) }}</span><Badge variant="outline">{{ r.status }}</Badge><span v-if="r.error" class="truncate text-xs text-muted-foreground">{{ r.error }}</span></li>
            </ul>
          </div>
          <p v-if="message" class="text-sm" role="status">{{ message }}</p>
        </div>

        <p v-else class="p-5 text-sm text-muted-foreground">Select an item.</p>
      </template>
    </MasterDetail>

    <Dialog :open="!!doomed" @update:open="(v: boolean) => !v && (doomed = null)">
      <DialogContent>
        <DialogHeader><DialogTitle>Delete the schedule “{{ doomed?.id }}”?</DialogTitle><DialogDescription>It will no longer run. Its note is removed from the vault.</DialogDescription></DialogHeader>
        <DialogFooter><Button variant="outline" @click="doomed = null">Cancel</Button><Button variant="destructive" @click="remove">Delete</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
