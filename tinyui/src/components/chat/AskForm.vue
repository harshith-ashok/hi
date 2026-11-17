<script setup lang="ts">
import { MessageCircleQuestion } from '@lucide/vue'
import { reactive } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const props = defineProps<{ questions: string[]; answered: boolean; disabled: boolean }>()
const emit = defineEmits<{ submit: [text: string] }>()
const answers = reactive<string[]>([])

function send() {
  const lines = props.questions.map((q, i) => `${i + 1}. ${q} ${(answers[i] ?? '').trim() || '(no answer, use your judgment)'}`)
  emit('submit', `Here are my answers:\n${lines.join('\n')}`)
}
</script>

<template>
  <form class="space-y-3 rounded-lg border border-info/40 bg-info/5 p-4" aria-label="Questions from the assistant" @submit.prevent="!answered && !disabled && send()">
    <div class="flex items-center gap-2 text-sm font-medium"><MessageCircleQuestion class="size-4 text-info" /> I need a few answers</div>
    <div v-for="(q, i) in questions" :key="i" class="space-y-1.5">
      <Label :for="`q${i}`" class="text-sm font-normal">{{ q }}</Label>
      <Input :id="`q${i}`" v-model="answers[i]" :disabled="answered" autocomplete="off" spellcheck="false" />
    </div>
    <Button type="submit" size="sm" :disabled="answered || disabled">{{ answered ? 'Answered' : 'Send answers' }}</Button>
  </form>
</template>
