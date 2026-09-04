// Parses hi/vault.py's log_conversation() format ("## HH:MM:SS —
// persona\n\n**User:** ...\n\n**Assistant:** ...\n\n", repeated) back
// into real Turn values — the exact same type the live chat pane
// renders via TurnRow, so a past conversation gets the identical
// padding/border/tag styling as a live one instead of a second,
// visually inconsistent rendering.

import Foundation

struct HistoryExchange: Identifiable {
    let id = UUID()
    let time: String
    let userTurn: Turn
    let assistantTurn: Turn
}

enum ConversationLogParser {
    private static let pattern =
        "## (\\d{2}:\\d{2}:\\d{2}) — (\\S+)\\n\\n\\*\\*User:\\*\\* (.*?)\\n\\n\\*\\*Assistant:\\*\\* (.*?)(?=\\n## |\\z)"
    private static let regex = try? NSRegularExpression(pattern: pattern, options: [.dotMatchesLineSeparators])

    static func parse(_ raw: String) -> [HistoryExchange] {
        guard let regex else { return [] }
        let nsrange = NSRange(raw.startIndex..<raw.endIndex, in: raw)
        var exchanges: [HistoryExchange] = []

        regex.enumerateMatches(in: raw, options: [], range: nsrange) { match, _, _ in
            guard
                let match, match.numberOfRanges == 5,
                let timeRange = Range(match.range(at: 1), in: raw),
                let personaRange = Range(match.range(at: 2), in: raw),
                let userRange = Range(match.range(at: 3), in: raw),
                let assistantRange = Range(match.range(at: 4), in: raw)
            else { return }

            let time = String(raw[timeRange])
            let persona = String(raw[personaRange])
            let userText = String(raw[userRange]).trimmingCharacters(in: .whitespacesAndNewlines)
            let assistantText = String(raw[assistantRange]).trimmingCharacters(in: .whitespacesAndNewlines)

            exchanges.append(HistoryExchange(
                time: time,
                userTurn: Turn(role: .user, content: userText),
                assistantTurn: Turn(role: .assistant(persona: persona), content: assistantText)
            ))
        }
        return exchanges
    }
}
