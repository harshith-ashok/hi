// Native SwiftUI port of ui.html's panel design (TODO.md's "implement
// ui.html" follow-up to the Spotlight redesign) — persona tabs, a
// one-line briefing strip, a sequential turn log (not chat bubbles —
// ui.html's own framing: "turn log — sequential lines"), and an
// always-present "(persona) >" prompt bar. See Theme.swift for the
// color/font choices ported from ui.html's CSS, and its header for what
// was deliberately substituted (system fonts, not bundled web fonts)
// rather than copied pixel-for-pixel.
//
// Two panel heights, exactly like the pre-redesign version this
// replaces: compact (tabs + briefing-if-any + prompt bar, no log yet)
// and expanded (adds the scrolling turn log) — PanelController computes
// which one applies and animates the window frame between them; this
// view just renders whatever AppState currently holds; it doesn't
// resize its own window.

import SwiftUI

struct ContentView: View {
    @ObservedObject var state: AppState
    var onSubmit: (String) -> Void
    var onToggleListening: () -> Void
    var onRunBriefingAction: () -> Void
    var onResolvePendingAction: (String, Bool) -> Void

    @FocusState private var fieldFocused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            TabsRow(state: state)
            if let briefing = state.briefing {
                BriefingStrip(briefing: briefing, onAction: onRunBriefingAction, onDismiss: { state.dismissBriefing() })
            }
            if !state.turns.isEmpty {
                Divider().foregroundStyle(HiTheme.hairline)
                TurnLogView(turns: state.turns)
            }
            if let widget = state.widget {
                Divider().foregroundStyle(HiTheme.hairline)
                WidgetView(widget: widget, onDismiss: { state.dismissWidget() })
            }
            if !state.pendingActions.isEmpty {
                PendingActionList(actions: state.pendingActions, onResolve: onResolvePendingAction)
            }
            Divider().foregroundStyle(HiTheme.hairline)
            PromptBar(state: state, fieldFocused: $fieldFocused, onSubmit: onSubmit, onToggleListening: onToggleListening)
        }
        // Explicitly fills whatever frame PanelController assigns the
        // window (rather than sizing to natural content height and
        // potentially leaving the panel's own background showing
        // through unstyled empty space below it) — PanelController's
        // target heights are close estimates, not a guaranteed exact
        // match to SwiftUI's real layout (no way to visually iterate on
        // that in this environment), so any slack is absorbed here by
        // the flexible turn-log area rather than clipping the fixed-
        // height tabs/briefing/prompt-bar rows around it.
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(HiTheme.bgPanel)
        .clipShape(RoundedRectangle(cornerRadius: HiTheme.cornerRadius))
        .overlay(
            RoundedRectangle(cornerRadius: HiTheme.cornerRadius)
                .strokeBorder(HiTheme.hairline, lineWidth: 1)
        )
        .onChange(of: state.isVisible) { visible in
            if visible { fieldFocused = true }
        }
    }
}

// MARK: - Persona tabs

struct TabsRow: View {
    @ObservedObject var state: AppState

    var body: some View {
        HStack(spacing: 2) {
            ForEach([PersonaChoice.term, .butler, .docs, .web], id: \.self) { choice in
                TabButton(choice: choice, isActive: state.persona == choice) {
                    state.selectPersona(choice)
                }
            }
            Spacer(minLength: 8)
            if !state.turns.isEmpty {
                Button(action: { state.clearConversation() }) {
                    Image(systemName: "trash")
                        .font(.system(size: 10.5))
                        .foregroundStyle(HiTheme.textFaint)
                }
                .buttonStyle(.plain)
                .help("Clear conversation")
                .padding(.trailing, 4)
            }
            TabButton(choice: .auto, isActive: state.persona == .auto) {
                state.selectPersona(.auto)
            }
        }
        .padding(.horizontal, 12)
        .padding(.top, 8)
    }
}

struct TabButton: View {
    let choice: PersonaChoice
    let isActive: Bool
    let action: () -> Void

    @State private var isHovering = false

    var body: some View {
        Button(action: action) {
            Text(choice.tabLabel)
                .font(HiTheme.mono(12))
                .foregroundStyle(isActive ? HiTheme.teal : (isHovering ? HiTheme.textDim : HiTheme.textFaint))
                .padding(.horizontal, 8)
                .padding(.top, 6)
                .padding(.bottom, 8)
                .overlay(alignment: .bottom) {
                    Rectangle()
                        .fill(isActive ? HiTheme.teal : .clear)
                        .frame(height: 2)
                }
        }
        .buttonStyle(.plain)
        .onHover { isHovering = $0 }
    }
}

// MARK: - Briefing strip

struct BriefingStrip: View {
    let briefing: BriefingInfo
    let onAction: () -> Void
    let onDismiss: () -> Void

    @State private var isHoveringAction = false

    var body: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(HiTheme.amber)
                .frame(width: 5, height: 5)
            Text(briefing.stripText)
                .font(HiTheme.mono(11.5))
                .foregroundStyle(HiTheme.textDim)
                .lineLimit(1)
                .truncationMode(.tail)
            Spacer(minLength: 8)
            if briefing.hasAction {
                Button(action: onAction) {
                    Text("run this →")
                        .font(HiTheme.mono(11.5))
                        .foregroundStyle(isHoveringAction ? HiTheme.text : HiTheme.teal)
                }
                .buttonStyle(.plain)
                .onHover { isHoveringAction = $0 }
            }
            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .font(.system(size: 9))
                    .foregroundStyle(HiTheme.textFaint)
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
        .background(HiTheme.bgRow)
    }
}

// MARK: - Turn log (sequential lines, not chat bubbles)

private struct TurnLogView: View {
    let turns: [Turn]

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(turns) { turn in
                        TurnRow(turn: turn).id(turn.id)
                    }
                }
                .padding(.vertical, 6)
            }
            .frame(maxHeight: 320)  // matches PanelController.logMaxHeight — keep in sync
            .onChange(of: turns) { newTurns in
                guard let lastID = newTurns.last?.id else { return }
                proxy.scrollTo(lastID, anchor: .bottom)
            }
        }
    }
}

struct TurnRow: View {
    let turn: Turn
    @State private var thinkingExpanded = false

    private var borderColor: Color {
        switch turn.role {
        case .user: return HiTheme.textFaint
        case .assistant: return HiTheme.tealDim
        case .systemError: return HiTheme.rust
        }
    }

    private var tagColor: Color {
        switch turn.role {
        case .user: return HiTheme.textFaint
        case .assistant: return HiTheme.teal
        case .systemError: return HiTheme.rust
        }
    }

    private var backgroundTint: Color {
        switch turn.role {
        case .assistant: return HiTheme.assistantTint
        default: return .clear
        }
    }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Text(turn.tag)
                .font(HiTheme.mono(11))
                .foregroundStyle(tagColor)
                .frame(width: 58, alignment: .leading)

            VStack(alignment: .leading, spacing: 6) {
                if !turn.thinkingText.isEmpty {
                    ThinkingDisclosure(text: turn.thinkingText, isActive: turn.isThinkingActive, expanded: $thinkingExpanded)
                }
                if !turn.toolCalls.isEmpty {
                    ToolCallList(calls: turn.toolCalls)
                }
                HStack(spacing: 0) {
                    Text(turn.content)
                        .font(turn.role == .user ? HiTheme.mono(12.5) : HiTheme.sans(13.5))
                        .foregroundStyle(turn.role == .user ? HiTheme.textDim : HiTheme.text)
                        .lineSpacing(4)
                        .textSelection(.enabled)
                    if turn.isStreaming {
                        StreamingCursor()
                    }
                }
                .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 9)
        .background(backgroundTint)
        .overlay(alignment: .leading) {
            Rectangle().fill(borderColor).frame(width: 2)
        }
    }
}

struct StreamingCursor: View {
    @State private var visible = true

    var body: some View {
        Rectangle()
            .fill(HiTheme.teal)
            .frame(width: 6, height: 13)
            .opacity(visible ? 1 : 0)
            .padding(.leading, 2)
            .onAppear {
                withAnimation(.easeInOut(duration: 0.5).repeatForever(autoreverses: true)) {
                    visible = false
                }
            }
    }
}

/// Shows a turn's live/completed thinking content — auto-expanded while
/// `isActive` (THINKING_START..THINKING_END is in flight), auto-collapsed
/// to a small tappable label once it ends, same "show the work while
/// it's happening, tuck it away once there's a real answer, one tap
/// away" behavior as the web frontend's own collapsible thinking block.
struct ThinkingDisclosure: View {
    let text: String
    let isActive: Bool
    @Binding var expanded: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Button(action: { expanded.toggle() }) {
                HStack(spacing: 6) {
                    if isActive {
                        Circle().fill(HiTheme.amber).frame(width: 5, height: 5)
                    }
                    Text(isActive ? "thinking…" : "thought")
                        .font(HiTheme.mono(10.5))
                        .foregroundStyle(HiTheme.textFaint)
                }
            }
            .buttonStyle(.plain)

            if expanded || isActive {
                Text(text)
                    .font(HiTheme.sans(12))
                    .italic()
                    .foregroundStyle(HiTheme.textFaint)
                    .lineSpacing(3)
                    .textSelection(.enabled)
            }
        }
    }
}

/// Shows each tool call made during a turn as a one-line "→ tool_name"
/// entry — pending (no result yet) shows an amber dot, matching
/// PendingActionCard's own use of amber for "in flight, not yet
/// resolved". Tapping a completed call expands its raw result inline,
/// same tap-to-expand pattern as ThinkingDisclosure above. Closes the
/// same web-frontend-vs-native-app parity gap the THINKING_* events did
/// (BLOCKERS.md "Features to add" #8) — the AG-UI events were already
/// streaming here, just discarded with a `break` until now.
struct ToolCallList: View {
    let calls: [ToolCallInfo]
    @State private var expandedID: ToolCallInfo.ID?

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            ForEach(calls) { call in
                VStack(alignment: .leading, spacing: 3) {
                    Button(action: {
                        guard call.result != nil else { return }
                        expandedID = (expandedID == call.id) ? nil : call.id
                    }) {
                        HStack(spacing: 6) {
                            if call.result == nil {
                                Circle().fill(HiTheme.amber).frame(width: 5, height: 5)
                            }
                            Text("→ \(call.name)")
                                .font(HiTheme.mono(10.5))
                                .foregroundStyle(HiTheme.textFaint)
                        }
                    }
                    .buttonStyle(.plain)
                    .disabled(call.result == nil)

                    if expandedID == call.id, let result = call.result {
                        Text(result)
                            .font(HiTheme.mono(11))
                            .foregroundStyle(HiTheme.textFaint)
                            .lineSpacing(3)
                            .textSelection(.enabled)
                            .padding(.leading, 11)
                    }
                }
            }
        }
    }
}

// MARK: - Prompt bar

struct PromptBar: View {
    @ObservedObject var state: AppState
    var fieldFocused: FocusState<Bool>.Binding
    var onSubmit: (String) -> Void
    var onToggleListening: () -> Void

    private var prefix: String {
        if let backendName = state.persona.backendName { return "(\(backendName)) >" }
        return "(\(state.lastAnsweredPersona ?? "hi")) >"
    }

    var body: some View {
        HStack(spacing: 8) {
            Text(prefix)
                .font(HiTheme.mono(13))
                .foregroundStyle(HiTheme.teal)
                .fixedSize()

            TextField("ask anything, or pick a tab to force it", text: $state.inputText)
                .textFieldStyle(.plain)
                .font(HiTheme.mono(13))
                .foregroundStyle(HiTheme.text)
                .focused(fieldFocused)
                .disabled(state.isBusy)
                .onSubmit { submit() }

            micButton

            Text(state.isBusy ? "…" : "↵")
                .font(HiTheme.mono(10.5))
                .foregroundStyle(HiTheme.textFaint)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .overlay(
                    RoundedRectangle(cornerRadius: 4)
                        .strokeBorder(HiTheme.hairline, lineWidth: 1)
                )
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 13)
    }

    private var micButton: some View {
        Button(action: onToggleListening) {
            Image(systemName: state.isListening ? "mic.fill" : "mic")
                .font(.system(size: 13))
                .foregroundStyle(state.isListening ? HiTheme.teal : HiTheme.textFaint)
        }
        .buttonStyle(.plain)
        .disabled(state.isBusy)
        .help(state.isListening ? "Stop dictation" : "Dictate instead of typing")
    }

    private func submit() {
        let trimmed = state.inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !state.isBusy else { return }
        onSubmit(trimmed)
    }
}
