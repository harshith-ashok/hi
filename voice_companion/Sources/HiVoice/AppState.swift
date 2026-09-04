// The panel's state (rearchitected for TODO.md's "implement ui.html"
// follow-up to the Spotlight redesign): ui.html's own interaction model
// is genuinely different from what this app had before — a persistent,
// growing turn log with an always-present prompt bar (REPL-style: ask,
// get an answer appended to the log, ask again), not a one-shot
// "input -> processing -> done screen -> New Question" cycle. The old
// CompanionPhase enum (hidden/input/processing/done/error) encoded that
// one-shot cycle directly; it's gone, replaced by a flatter set of
// published properties that can be independently true (busy AND has
// turns AND listening, e.g.) the way a real terminal session can be.
//
// An error is now just another entry in the turn log (Turn.Role
// .systemError), not a whole separate screen that replaces the
// conversation — nothing should ever destroy turn history, matching
// ui.html's own log-centric design and how a real terminal never wipes
// scrollback just because one command failed.

import Foundation

/// The panel's persona-tab row (term/butler/docs/web, or "hi ·auto" for
/// router-mode classification) — independent of any one turn; it's
/// which persona *future* queries go to, mirroring `hi --term` etc.
/// forcing a persona at the terminal versus plain `hi`'s auto-routing.
enum PersonaChoice: String, CaseIterable, Identifiable {
    case auto, term, butler, docs, web

    var id: String { rawValue }

    /// The literal backend persona name to send when forced, nil for
    /// auto (let hi/router.py's classify() pick per query).
    var backendName: String? { self == .auto ? nil : rawValue }

    var tabLabel: String { self == .auto ? "hi ·auto" : rawValue }
}

struct Turn: Identifiable, Equatable {
    enum Role: Equatable {
        case user
        case assistant(persona: String)
        case systemError
    }

    let id = UUID()
    let role: Role
    var content: String
    var isStreaming: Bool = false

    var tag: String {
        switch role {
        case .user: return "you"
        case .assistant(let persona): return "(\(persona))"
        case .systemError: return "!"
        }
    }
}

/// An MCP-UI widget (TODO.md Phase 18) — a tool's own rendered HTML,
/// not just its text result. Shown in a sandboxed `WKWebView`
/// (`WidgetView.swift`) below the turn log while set. **Not verified
/// against a real MCP-UI server** — none of this project's configured
/// MCP servers implement the mcp-ui extension; the parsing/rendering
/// path is built and compiles clean against a synthetic value shaped
/// like the real spec (see `hi/agui_adapter.py`'s own docstring).
struct WidgetInfo: Equatable {
    let uri: String
    let html: String
}

/// A destructive action awaiting human approval, rendered inline
/// (TODO.md Phase 20, "approvals as generative UI") — `PendingActionCard`
/// shows real Approve/Deny buttons while `resolution` is nil, then a
/// brief "Approved"/"Denied" state before `AppState` removes it.
struct InlinePendingAction: Identifiable, Equatable {
    let id: String
    let description: String
    var resolution: Bool?
}

struct BriefingInfo: Equatable {
    let context: String
    let suggestion: String
    let action: String

    /// The single line shown in the compact briefing strip — the
    /// suggestion if the backend produced one (a real yes/no question,
    /// short by construction), else a trimmed first line of the raw
    /// context as a fallback so the strip never renders a multi-line
    /// dump into a one-line row.
    var stripText: String {
        if !suggestion.isEmpty { return suggestion }
        return context.components(separatedBy: "\n").first ?? context
    }

    var hasAction: Bool { !action.isEmpty }
}

@MainActor
final class AppState: ObservableObject {
    @Published var isVisible = false
    @Published var persona: PersonaChoice = .auto
    @Published var inputText = ""
    @Published var isListening = false
    @Published var isBusy = false
    @Published var turns: [Turn] = []
    @Published var briefing: BriefingInfo?
    @Published private(set) var lastAnsweredPersona: String?
    @Published var widget: WidgetInfo?
    @Published var pendingActions: [InlinePendingAction] = []

    func show() { isVisible = true }
    func hide() { isVisible = false }
    func toggle() { isVisible ? hide() : show() }

    func selectPersona(_ choice: PersonaChoice) { persona = choice }

    func setBriefing(_ info: BriefingInfo?) { briefing = info }
    func dismissBriefing() { briefing = nil }

    func setListening(_ listening: Bool) { isListening = listening }

    func appendUserTurn(_ text: String) {
        turns.append(Turn(role: .user, content: text))
    }

    func beginAssistantTurn(persona: String) {
        turns.append(Turn(role: .assistant(persona: persona), content: "", isStreaming: true))
        lastAnsweredPersona = persona
    }

    /// Appends one more chunk of a still-streaming assistant turn — a
    /// no-op if the last turn isn't actually a live stream (defensive;
    /// shouldn't happen given AppDelegate's own call ordering, but this
    /// is cheap insurance against a stray late token after a
    /// disconnect/cancel).
    func appendToken(_ text: String) {
        guard let last = turns.last, last.isStreaming else { return }
        turns[turns.count - 1].content += text
    }

    /// Replaces the streaming turn's content with the backend's own
    /// final text (may differ slightly from the concatenated tokens —
    /// e.g. whitespace normalization) and marks it settled.
    func finishAssistantTurn(finalText: String) {
        guard let last = turns.last, last.isStreaming else { return }
        turns[turns.count - 1].content = finalText
        turns[turns.count - 1].isStreaming = false
    }

    func appendError(_ message: String) {
        // A mid-stream disconnect leaves a permanently-frozen streaming
        // cursor behind if not cleaned up — drop that dangling turn
        // rather than leaving dead UI in the log.
        if let last = turns.last, last.isStreaming {
            turns.removeLast()
        }
        turns.append(Turn(role: .systemError, content: message))
    }

    func clearConversation() {
        turns = []
        lastAnsweredPersona = nil
    }

    /// Sets the currently-shown MCP-UI widget (TODO.md Phase 18) — replaces
    /// whatever was there before, same as a new tool result superseding
    /// an old one rather than stacking widgets.
    func setWidget(uri: String, html: String) {
        widget = WidgetInfo(uri: uri, html: html)
    }

    func dismissWidget() {
        widget = nil
    }

    /// Adds a newly-reported pending action, deduped by id — the same
    /// action can arrive again from a later SSE poll tick
    /// (`hi/agui_adapter.py`'s `_pending_action_events()` only reports a
    /// truly new id, but this stays defensive rather than trusting that).
    func addPendingAction(id: String, description: String) {
        guard !pendingActions.contains(where: { $0.id == id }) else { return }
        pendingActions.append(InlinePendingAction(id: id, description: description))
    }

    /// Marks a pending action resolved (from either the backend's own
    /// SSE event, or optimistically the instant a local Approve/Deny tap
    /// is sent) — shown briefly as "Approved"/"Denied" before being
    /// removed, rather than disappearing the instant it's resolved,
    /// which would read as the card just vanishing with no feedback.
    func markPendingActionResolved(id: String, approved: Bool) {
        guard let index = pendingActions.firstIndex(where: { $0.id == id }) else { return }
        guard pendingActions[index].resolution == nil else { return }  // already settling — don't restart the timer
        pendingActions[index].resolution = approved
        Task {
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            pendingActions.removeAll { $0.id == id }
        }
    }
}
