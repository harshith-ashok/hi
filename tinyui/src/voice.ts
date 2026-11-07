// Mic capture -> 16 kHz mono WAV -> backend /stt (whisper.cpp), and spoken
// replies via /tts. Recording ends on silence.

import { BASE_URL } from './backend'

const SAMPLE_RATE = 16000
const SILENCE_MS = 700 // end of utterance
const NO_SPEECH_MS = 6000 // give up if nothing was said
const MAX_MS = 20000
const SPEECH_LEVEL = 0.02

/** Live loudness 0..1 of whatever is active (mic while listening, playback while
 * speaking). Plain object, read every animation frame by the orb. */
export const audioLevel = { value: 0 }

function rms(analyser: AnalyserNode, buf: Float32Array<ArrayBuffer>): number {
  analyser.getFloatTimeDomainData(buf)
  return Math.sqrt(buf.reduce((sum, v) => sum + v * v, 0) / buf.length)
}

function trackLevel(analyser: AnalyserNode, active: () => boolean, gain: number) {
  const buf = new Float32Array(analyser.fftSize)
  const frame = () => {
    if (!active()) return void (audioLevel.value = 0)
    audioLevel.value = audioLevel.value * 0.7 + Math.min(1, rms(analyser, buf) * gain) * 0.3
    requestAnimationFrame(frame)
  }
  requestAnimationFrame(frame)
}

function encodeWav(samples: Float32Array): Blob {
  const view = new DataView(new ArrayBuffer(44 + samples.length * 2))
  const write = (offset: number, text: string) => [...text].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)))
  write(0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  write(8, 'WAVEfmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, 1, true) // mono
  view.setUint32(24, SAMPLE_RATE, true)
  view.setUint32(28, SAMPLE_RATE * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  write(36, 'data')
  view.setUint32(40, samples.length * 2, true)
  samples.forEach((s, i) => view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, s)) * 0x7fff, true))
  return new Blob([view], { type: 'audio/wav' })
}

async function toWav(recording: Blob): Promise<Blob> {
  const decoded = await new AudioContext().decodeAudioData(await recording.arrayBuffer())
  const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * SAMPLE_RATE), SAMPLE_RATE)
  const source = offline.createBufferSource()
  source.buffer = decoded
  source.connect(offline.destination)
  source.start()
  return encodeWav((await offline.startRendering()).getChannelData(0))
}

export interface Recording {
  stop: () => void
  result: Promise<Blob | null> // null: nothing was said
}

export async function record(): Promise<Recording> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  const recorder = new MediaRecorder(stream)
  const chunks: Blob[] = []
  recorder.ondataavailable = (e) => chunks.push(e.data)

  const context = new AudioContext()
  await context.resume().catch(() => {}) // a suspended context reads silence, so speech would never be detected
  const analyser = context.createAnalyser()
  context.createMediaStreamSource(stream).connect(analyser)
  const level = new Float32Array(analyser.fftSize)

  let live = true
  trackLevel(analyser, () => live, 6)
  let spoke = false
  let quietSince = performance.now()
  const started = quietSince
  const result = new Promise<Blob | null>((resolve) => {
    recorder.onstop = async () => {
      clearInterval(timer)
      live = false
      stream.getTracks().forEach((t) => t.stop())
      void context.close()
      resolve(spoke ? await toWav(new Blob(chunks)) : null)
    }
  })
  const stop = () => recorder.state !== 'inactive' && recorder.stop()

  const timer = window.setInterval(() => {
    analyser.getFloatTimeDomainData(level)
    const rms = Math.sqrt(level.reduce((sum, v) => sum + v * v, 0) / level.length)
    const now = performance.now()
    if (rms > SPEECH_LEVEL) {
      spoke = true
      quietSince = now
    }
    if (now - started > MAX_MS) stop()
    else if (spoke && now - quietSince > SILENCE_MS) stop()
    else if (!spoke && now - started > NO_SPEECH_MS) stop()
  }, 100)

  recorder.start()
  return { stop, result }
}

export async function transcribe(wav: Blob): Promise<string> {
  const res = await fetch(`${BASE_URL}/stt`, { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: wav })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error ?? `stt failed (${res.status})`)
  return data.text as string
}

/** Rambler: the backend cleans/structures a spoken transcript (haiku tier). */
export async function ramble(text: string): Promise<string> {
  try {
    const res = await fetch(`${BASE_URL}/ramble`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) })
    return res.ok ? ((await res.json()).text as string) : text
  } catch {
    return text
  }
}

// One audio element for every clip. Safari (and Chrome without a prior click) only lets an
// element play if it was started inside a user gesture, and our clips arrive after a network
// fetch, long after the click. So the element is "unlocked" once by a gesture (unlockAudio)
// and then reused: setting a new src on an unlocked element may play freely.
const player = new Audio()
let unlocked = false

/** Call from any click/key handler. Safe to call repeatedly. */
export function unlockAudio() {
  if (unlocked) return
  unlocked = true
  player.src = URL.createObjectURL(encodeWav(new Float32Array(240)))
  player.play().catch(() => (unlocked = false)) // not in a gesture after all: try again next time
  speechSynthesis.speak(new SpeechSynthesisUtterance('')) // same unlock for the browser-voice fallback
}

export function stopSpeaking() {
  player.pause()
  speechSynthesis.cancel()
  audioLevel.value = 0
}

function speakInBrowser(text: string): Promise<void> {
  return new Promise((resolve) => {
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.onboundary = () => (audioLevel.value = 0.6)
    utterance.onend = utterance.onerror = () => {
      audioLevel.value = 0
      resolve()
    }
    const decay = window.setInterval(() => (audioLevel.value *= 0.8), 50)
    utterance.addEventListener('end', () => clearInterval(decay))
    utterance.addEventListener('error', () => clearInterval(decay))
    speechSynthesis.speak(utterance)
  })
}

const WINDOW_S = 0.05

/** Loudness of the clip in 50 ms windows, read from the decoded audio, so the orb can follow
 * playback without routing the sound through an AudioContext (which could mute it). */
async function envelope(clip: Blob): Promise<number[]> {
  const context = new AudioContext()
  try {
    const decoded = await context.decodeAudioData(await clip.arrayBuffer())
    const samples = decoded.getChannelData(0)
    const step = Math.max(1, Math.floor(decoded.sampleRate * WINDOW_S))
    const levels: number[] = []
    for (let i = 0; i < samples.length; i += step) {
      let sum = 0
      const end = Math.min(samples.length, i + step)
      for (let j = i; j < end; j++) sum += samples[j] * samples[j]
      levels.push(Math.min(1, Math.sqrt(sum / (end - i)) * 5))
    }
    return levels
  } finally {
    void context.close()
  }
}

function followPlayback(levels: number[]): () => void {
  let on = true
  const frame = () => {
    if (!on) return
    const target = levels.length ? (levels[Math.floor(player.currentTime / WINDOW_S)] ?? 0) : 0.3
    audioLevel.value = audioLevel.value * 0.6 + target * 0.4
    requestAnimationFrame(frame)
  }
  requestAnimationFrame(frame)
  return () => {
    on = false
    audioLevel.value = 0
  }
}

/** Speak `text`; resolves when playback ends. Uses the backend's TTS (/tts, Ollama's
 * phonon). Only if that fails does it use the browser's voice, and says why. */
export async function speak(text: string, onFallback?: (reason: string) => void, voice?: string): Promise<void> {
  stopSpeaking()
  try {
    const res = await fetch(`${BASE_URL}/tts`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, voice }) })
    if (!res.ok) throw new Error(res.statusText || `tts failed (${res.status})`)
    const clip = await res.blob()
    const levels = await envelope(clip).catch(() => [])
    player.src = URL.createObjectURL(clip)
    const stopMeter = followPlayback(levels)
    await new Promise<void>((resolve, reject) => {
      player.onended = () => resolve()
      player.onpause = () => resolve() // stopSpeaking()
      player.onerror = () => reject(new Error('audio playback failed'))
      player.play().catch(reject)
    }).finally(stopMeter)
  } catch (err) {
    onFallback?.((err as Error).message)
    await speakInBrowser(text)
  }
}

const WAKE_KEY = 'wakePhrase'
export const DEFAULT_WAKE_PHRASE = 'hey hi'
export const getWakePhrase = () => localStorage.getItem(WAKE_KEY) || DEFAULT_WAKE_PHRASE
export const setWakePhrase = (phrase: string) => localStorage.setItem(WAKE_KEY, phrase.trim() || DEFAULT_WAKE_PHRASE)

const words = (t: string) => t.toLowerCase().replace(/[^a-z0-9\s]+/g, ' ').split(/\s+/).filter(Boolean)

/** What was said after the wake phrase ('' if only the phrase), or null if `heard` doesn't start with it. */
export function afterWakePhrase(heard: string): string | null {
  const phrase = words(getWakePhrase())
  const spoken = words(heard)
  if (!phrase.every((w, i) => spoken[i] === w)) return null
  return heard.trim().split(/\s+/).slice(phrase.length).join(' ').replace(/^[\s,.:;!?-]+/, '')
}
