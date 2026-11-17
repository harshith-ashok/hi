<script setup lang="ts">
// A UI the assistant made: fetched from the backend (already checked there), drawn, and answered. When the user presses
// a button or submits, their choices go back as the next message, and the UI locks so the answer stays what it was.
import { AlertCircle, CheckCircle2 } from '@lucide/vue'
import { computed, onMounted, provide, reactive, ref, watch } from 'vue'
import { BASE_URL } from '@/backend'
import UiNode from '@/components/genui/UiNode.vue'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Skeleton } from '@/components/ui/skeleton'
import { UI_KEY, defaultsOf, formatResponse, missingRequired, type UiSpec, type UiValue } from '@/lib/uispec'

const props = defineProps<{ src?: string; spec?: UiSpec; answered: boolean }>()
const emit = defineEmits<{ respond: [text: string] }>()

const spec = ref<UiSpec | null>(props.spec ?? null)
const error = ref('')
const sent = ref(false) // an answer is on its way; cleared again if the chat did not take it
const values = reactive<Record<string, UiValue>>({})
const errors = reactive<Record<string, boolean>>({})
const answered = computed(() => props.answered || sent.value)

function adopt(s: UiSpec) {
  spec.value = s
  Object.assign(values, defaultsOf(s.ui))
}

onMounted(async () => {
  if (props.spec) return adopt(props.spec)
  try {
    const res = await fetch(BASE_URL + props.src)
    if (!res.ok) throw new Error(`could not load the UI (${res.status})`)
    adopt((await res.json()) as UiSpec)
  } catch (err) {
    error.value = (err as Error).message
  }
})
watch(() => props.spec, (s) => s && adopt(s))

provide(UI_KEY, {
  values, errors, answered,
  submit(action, scope) {
    if (answered.value || !spec.value) return false
    const missing = missingRequired(scope ?? spec.value.ui, values)
    if (missing.length) {
      for (const name of missing) errors[name] = true
      return false
    }
    sent.value = true
    emit('respond', formatResponse(spec.value.title, action, spec.value.ui, values))
    // The chat locks this UI itself once the answer becomes a message. If it never did (it was busy), let the user try again.
    setTimeout(() => { if (!props.answered) sent.value = false }, 1500)
    return true
  },
})
</script>

<template>
  <section class="not-prose space-y-3 rounded-xl border bg-card p-4" :aria-label="spec?.title || 'Interactive content'">
    <div v-if="spec?.title || (answered && spec?.interactive)" class="flex items-center justify-between gap-2">
      <h3 class="text-sm font-semibold">{{ spec?.title }}</h3>
      <span v-if="answered && spec?.interactive" class="flex items-center gap-1 text-xs text-muted-foreground"><CheckCircle2 class="size-3.5 text-success" /> Answered</span>
    </div>
    <Alert v-if="error" variant="destructive"><AlertCircle class="size-4" /><AlertDescription>{{ error }}</AlertDescription></Alert>
    <div v-else-if="!spec" class="space-y-2" role="status" aria-label="Loading"><Skeleton class="h-4 w-1/3" /><Skeleton class="h-20 w-full" /></div>
    <UiNode v-else :node="spec.ui" />
  </section>
</template>
