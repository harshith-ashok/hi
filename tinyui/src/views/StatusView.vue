<script setup lang="ts">
import { RefreshCw } from '@lucide/vue'
import { onMounted, ref } from 'vue'
import PageHeader from '@/components/app/PageHeader.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { getHealth, getJson } from '@/backend'

interface Health {
  ok: boolean
  deps: Record<string, { ok: boolean; error: string; since: number }>
  jobs?: Record<string, { last_run: number }>
  timezone?: string
  pending_proposals?: number
  latency?: Record<string, { runs: number; avg_seconds: number; avg_first_token_s: number | null }>
}

const blocks = ref<[string, Record<string, unknown>][]>([])
const briefing = ref('')
const health = ref<Health | null>(null)
const updated = ref('')
const loading = ref(false)

const jobTime = (name: string) => {
  const job = health.value?.jobs?.[name.replace('job:', '')]
  return job ? new Date(job.last_run * 1000).toTimeString().slice(0, 8) : ''
}

async function load() {
  loading.value = true
  health.value = await getHealth<Health>()
  const [vitals, vault, today, b] = await Promise.all([
    getJson<Record<string, unknown>>('/vitals'),
    getJson<Record<string, unknown>>('/vault-stats'),
    getJson<Record<string, unknown>>('/today'),
    getJson<{ context: string; suggestion: string } | null>('/briefing'),
  ])
  blocks.value = [['System', vitals ?? {}], ['Vault', vault ?? {}], ['Today', today ?? {}]]
  briefing.value = b ? [b.context, b.suggestion].filter(Boolean).join('\n\n') : ''
  updated.value = new Date().toTimeString().slice(0, 8)
  loading.value = false
}
onMounted(load)
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <PageHeader title="Status" :subtitle="updated ? `updated ${updated}` : ''">
      <Button variant="outline" size="sm" :disabled="loading" @click="load"><RefreshCw :class="['size-3.5', loading && 'animate-spin']" /> Refresh</Button>
    </PageHeader>
    <div class="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
      <Card v-if="briefing"><CardHeader><CardTitle>Briefing</CardTitle></CardHeader><CardContent><pre class="max-w-prose whitespace-pre-wrap text-sm">{{ briefing }}</pre></CardContent></Card>

      <Card v-if="health">
        <CardHeader class="flex-row items-center gap-3"><CardTitle>Health</CardTitle><Badge :variant="health.ok ? 'secondary' : 'destructive'">{{ health.ok ? 'all essentials up' : 'something essential is down' }}</Badge></CardHeader>
        <CardContent>
          <ul class="divide-y text-sm">
            <li v-for="(d, name) in health.deps" :key="name" class="flex items-center gap-3 py-2">
              <span :class="['size-2 shrink-0 rounded-full', d.ok ? 'bg-success' : 'bg-destructive']" />
              <span class="font-mono text-xs">{{ name }}</span>
              <span :class="['min-w-0 flex-1 truncate text-xs', d.ok ? 'text-muted-foreground' : 'text-destructive']">{{ d.ok ? 'ok' : d.error }}</span>
              <span v-if="jobTime(String(name))" class="text-xs text-muted-foreground">last ran {{ jobTime(String(name)) }}</span>
            </li>
          </ul>
          <dl class="mt-3 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
            <div class="flex justify-between"><dt class="text-muted-foreground">Timezone</dt><dd>{{ health.timezone }}</dd></div>
            <div class="flex justify-between"><dt class="text-muted-foreground">Actions waiting</dt><dd>{{ health.pending_proposals ?? 0 }}</dd></div>
            <div v-for="(l, origin) in health.latency ?? {}" :key="origin" class="flex justify-between gap-3"><dt class="text-muted-foreground">{{ origin }} turns</dt><dd>{{ l.runs }} · avg {{ l.avg_seconds }}s<template v-if="l.avg_first_token_s !== null"> · first word {{ l.avg_first_token_s }}s</template></dd></div>
          </dl>
        </CardContent>
      </Card>

      <div class="grid gap-4 lg:grid-cols-3">
        <Card v-for="[title, data] in blocks" :key="title">
          <CardHeader><CardTitle>{{ title }}</CardTitle></CardHeader>
          <CardContent>
            <dl class="space-y-1 text-sm"><div v-for="(value, key) in data" :key="key" class="flex justify-between gap-3"><dt class="text-muted-foreground">{{ key }}</dt><dd class="text-right">{{ value }}</dd></div></dl>
            <p v-if="!Object.keys(data).length" class="text-sm text-muted-foreground">No data.</p>
          </CardContent>
        </Card>
      </div>
    </div>
  </div>
</template>
