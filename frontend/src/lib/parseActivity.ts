// Parses hi/vault.py's log_conversation() format ("## HH:MM:SS —
// persona\n\n**User:** ...\n\n**Assistant:** ...\n\n") into short
// activity-feed entries — the dashboard's center column. Same pattern
// already verified in voice_companion/Sources/HiVoice/
// ConversationLogParser.swift (cross-checked there against real log
// content via Python's `re` module before trusting it), ported to
// TypeScript for the same real data source.

import type { ActivityEntry } from '../types'

const PATTERN = /## (\d{2}:\d{2}:\d{2}) — (\S+)\n\n\*\*User:\*\* ([\s\S]*?)\n\n\*\*Assistant:\*\* ([\s\S]*?)(?=\n## |$)/g

export function parseActivity(raw: string, limit = 8): ActivityEntry[] {
  const entries: ActivityEntry[] = []
  for (const match of raw.matchAll(PATTERN)) {
    const [, time, persona, , assistant] = match
    const firstLine = assistant.trim().split('\n')[0].slice(0, 90)
    entries.push({ time, persona, text: firstLine })
  }
  // Newest first — log_conversation() appends chronologically, so the
  // last matches in the file are the most recent.
  return entries.reverse().slice(0, limit)
}
