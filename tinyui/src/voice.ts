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

let player: HTMLAudioElement | null = null

export function stopSpeaking() {
  player?.pause()
  player = null
  speechSynthesis.cancel()
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

/** Speak `text`; resolves when playback ends. Uses the backend's neural TTS
 * (/tts) when it has one, else the browser's built-in voice — the Docker
 * image has no TTS engine. */
export async function speak(text: string): Promise<void> {
  stopSpeaking()
  try {
    const res = await fetch(`${BASE_URL}/tts`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) })
    if (!res.ok) throw new Error(`tts failed (${res.status})`)
    const audio = new Audio(URL.createObjectURL(await res.blob()))
    player = audio
    const context = new AudioContext()
    const analyser = context.createAnalyser()
    context.createMediaElementSource(audio).connect(analyser)
    analyser.connect(context.destination)
    let playing = true
    trackLevel(analyser, () => playing, 5)
    await new Promise<void>((resolve, reject) => {
      audio.onended = () => resolve()
      audio.onerror = () => reject(new Error('audio playback failed'))
      audio.play().catch(reject)
    }).finally(() => {
      playing = false
      void context.close()
    })
  } catch {
    await speakInBrowser(text)
  }
}
