// Microphone, wake word, conversation mode and speaking replies. Moved out of the chat view so the composer and the
// full-screen voice mode share one state.

import { computed, ref, watch, type Ref } from 'vue'
import { afterWakePhrase, ramble, record, speak, stopSpeaking, transcribe, unlockAudio, type Recording } from '@/voice'

export interface VoiceHooks {
  submit: (text: string) => void
  setInput: (text: string) => void
  focusInput: () => void
  notify: (text: string, kind?: 'info' | 'error') => void
  busy: Ref<boolean>
  acting: Ref<boolean>
  online: Ref<boolean>
  lastPersona: () => string
}

export function useVoice(hooks: VoiceHooks) {
  const mic = ref<'idle' | 'listening' | 'transcribing' | 'structuring'>('idle')
  const rambler = ref(true) // structure spoken transcripts before sending
  const voiceMode = ref(false) // full-screen, voice only
  const caption = ref('')
  const talk = ref(false) // conversation mode: speak replies, then listen again
  const speaking = ref(false)
  const wake = ref(false) // always listening for the wake phrase
  const speakReplies = ref(localStorage.getItem('speakReplies') === '1')
  let recording: Recording | null = null
  let ttsWarned = false

  watch(speakReplies, (on) => {
    localStorage.setItem('speakReplies', on ? '1' : '0')
    if (on) unlockAudio()
    else if (!talk.value) stopSpeaking()
  })

  /** What the orb and the status pill show. */
  const state = computed(() =>
    !hooks.online.value ? 'offline'
    : mic.value !== 'idle' ? mic.value
    : speaking.value ? 'speaking'
    : hooks.busy.value ? (hooks.acting.value ? 'acting' : 'thinking')
    : 'ready',
  )

  // send=false: dictation, the transcript lands in the box to edit; send=true: hands-free.
  async function listen(send = true) {
    unlockAudio()
    if (mic.value !== 'idle') return recording?.stop()
    try {
      recording = await record()
    } catch {
      return hooks.notify('Microphone unavailable', 'error')
    }
    mic.value = 'listening'
    const wav = await recording.result
    recording = null
    if (!wav) {
      mic.value = 'idle'
      talk.value = false
      return
    }
    mic.value = 'transcribing'
    try {
      const heard = await transcribe(wav)
      mic.value = 'structuring'
      const text = rambler.value ? await ramble(heard) : heard
      if (text !== heard) hooks.notify(`Heard: ${heard}`)
      caption.value = ''
      if (send) hooks.submit(text)
      else {
        hooks.setInput(text)
        hooks.focusInput()
      }
    } catch (err) {
      hooks.notify((err as Error).message, 'error')
      talk.value = false
    }
    mic.value = 'idle'
  }

  // Each utterance is transcribed locally (whisper.cpp) and acted on only if it starts with the wake phrase.
  async function wakeLoop() {
    while (wake.value) {
      if (mic.value !== 'idle' || speaking.value || hooks.busy.value) {
        await new Promise((r) => setTimeout(r, 300))
        continue
      }
      let wav: Blob | null
      try {
        recording = await record()
        wav = await recording.result
        recording = null
      } catch {
        hooks.notify('Microphone unavailable', 'error')
        break
      }
      if (!wav || !wake.value || speaking.value) continue // silence, switched off, or our own voice
      try {
        const rest = afterWakePhrase(await transcribe(wav))
        if (rest === null) continue
        if (rest) hooks.submit(rest)
        else await listen()
      } catch (err) {
        hooks.notify((err as Error).message, 'error')
        break
      }
    }
    wake.value = false
  }

  function toggleWake() {
    unlockAudio()
    wake.value = !wake.value
    if (wake.value) void wakeLoop()
    else recording?.stop()
  }

  /** Speak the short summary; the full answer stays on screen. */
  async function reply(text: string) {
    if (!talk.value && !speakReplies.value) return
    caption.value = text
    speaking.value = true
    if (wake.value && mic.value === 'idle') recording?.stop() // do not transcribe our own voice
    try {
      await speak(text, (why) => {
        if (!ttsWarned) hooks.notify(`Voice offline (${why}): showing text only`)
        ttsWarned = true
      }, undefined, hooks.lastPersona())
    } catch (err) {
      return hooks.notify((err as Error).message, 'error')
    } finally {
      speaking.value = false
    }
    if (talk.value) void listen()
  }

  function toggleTalk() {
    unlockAudio()
    talk.value = !talk.value
    if (talk.value) void listen()
    else {
      recording?.stop()
      stopSpeaking()
    }
  }

  function toggleVoiceMode() {
    voiceMode.value = !voiceMode.value
    caption.value = ''
    if (voiceMode.value !== talk.value) toggleTalk()
  }

  /** Esc: stop listening, talking and the wake word. */
  function stopAll() {
    voiceMode.value = false
    talk.value = false
    wake.value = false
    recording?.stop()
    stopSpeaking()
  }

  return { mic, rambler, voiceMode, caption, talk, speaking, wake, speakReplies, state, listen, toggleWake, toggleTalk, toggleVoiceMode, reply, stopAll }
}
