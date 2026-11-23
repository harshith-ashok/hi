<script setup lang="ts">
// Image generation settings: which backend, where it is, which model, and whether it is up right now.
import { computed, onMounted, ref } from 'vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'
import { fetchConfig, getHealth, saveConfigChecked } from '@/backend'

const BACKENDS: [string, string, string][] = [
  ['service', 'Image service', 'The imagegen service in this repo, on your own GPU'],
  ['openai', 'OpenAI-compatible', 'Any server with /v1/images/generations (set IMAGE_API_KEY in ~/.hi/.env for a hosted one)'],
  ['off', 'Off', 'No image generation'],
]
const MODELS: [string, string][] = [
  ['Tongyi-MAI/Z-Image-Turbo', 'Z-Image-Turbo: fast, fits 16 GB, good with text in images (Apache-2.0)'],
  ['black-forest-labs/FLUX.2-klein-4B', 'FLUX.2 [klein] 4B: very fast, about 13 GB (Apache-2.0)'],
]

const backend = ref('service')
const url = ref('')
const model = ref('')
const message = ref('')
const hint = computed(() => BACKENDS.find((b) => b[0] === backend.value)?.[2] ?? '')
const health = ref<{ ok: boolean; error: string } | null>(null)

async function check() {
  health.value = (await getHealth<{ deps: Record<string, { ok: boolean; error: string }> }>())?.deps?.imagegen ?? null
}
async function save() {
  message.value = (await saveConfigChecked({ IMAGE_BACKEND: backend.value, IMAGE_URL: url.value, IMAGE_MODEL: model.value })).message
  await check()
}

onMounted(async () => {
  const config = await fetchConfig()
  backend.value = String(config?.IMAGE_BACKEND ?? backend.value)
  url.value = String(config?.IMAGE_URL ?? '')
  model.value = String(config?.IMAGE_MODEL ?? '')
  void check()
})
</script>

<template>
  <div class="grid gap-4 md:grid-cols-2">
    <Card>
      <CardHeader><CardTitle>Image generation</CardTitle><CardDescription>Lets hi draw new pictures: illustrations, logos, posters, concept art.</CardDescription></CardHeader>
      <CardContent class="space-y-4">
        <div class="flex flex-wrap gap-2" role="radiogroup" aria-label="Image backend">
          <Button v-for="[id, label] in BACKENDS" :key="id" size="sm" role="radio" :aria-checked="id === backend" :variant="id === backend ? 'default' : 'outline'" @click="backend = id">{{ label }}</Button>
        </div>
        <p class="text-xs text-muted-foreground">{{ hint }}</p>
        <div class="space-y-1.5">
          <Label for="iurl">Server URL</Label>
          <Input id="iurl" v-model="url" placeholder="blank: the tailscale box in tailscale mode, else this machine" spellcheck="false" />
          <p class="text-xs text-muted-foreground">From Docker, a service on your Mac is <code class="rounded bg-muted px-1">http://host.docker.internal:8793</code>.</p>
        </div>
        <div class="space-y-1.5"><Label for="imodel">Model</Label><Input id="imodel" v-model="model" spellcheck="false" /></div>
        <div class="flex items-center gap-3"><Button @click="save">Save</Button><Button variant="outline" @click="check">Check</Button><span class="text-sm text-muted-foreground" role="status">{{ message }}</span></div>
        <p v-if="health" :class="['flex items-center gap-2 text-sm', health.ok ? 'text-success' : 'text-destructive']">
          <span :class="['size-2 rounded-full', health.ok ? 'bg-success' : 'bg-destructive']" />
          {{ health.ok ? (backend === 'off' ? 'Switched off' : 'The image server is reachable') : health.error }}
        </p>
      </CardContent>
    </Card>
    <Card>
      <CardHeader><CardTitle>Which model</CardTitle><CardDescription>Both run on your own GPU through the image service.</CardDescription></CardHeader>
      <CardContent class="space-y-2">
        <button v-for="[id, why] in MODELS" :key="id" :class="cn('flex w-full flex-col rounded-md border px-3 py-2 text-left hover:bg-accent', model === id && 'border-primary bg-accent')" @click="model = id">
          <span class="font-mono text-xs">{{ id }}</span><span class="text-xs text-muted-foreground">{{ why }}</span>
        </button>
        <p class="pt-2 text-xs text-muted-foreground">
          Start the service on an NVIDIA machine with <code class="rounded bg-muted px-1">docker compose --profile gpu up -d --build imagegen</code>, or on a Mac
          with <code class="rounded bg-muted px-1">python imagegen/server.py</code>. The first picture downloads the model (about 12 GB) and loads it, which takes a few minutes.
        </p>
      </CardContent>
    </Card>
  </div>
</template>
