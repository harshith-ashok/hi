// The "live chat" detail pane for the proper main app window
// (TODO.md: "create a proper native app that expands the functionality
// and replaces the terminal agent entirely"). Reuses the exact same
// pieces the floating Option+Space panel already uses (TabsRow,
// BriefingStrip, TurnRow, WidgetView, PendingActionList, PromptBar —
// all made non-private in ContentView.swift for exactly this reuse)
// rather than a second, diverging implementation — both surfaces share
// one AppState/BackendClient, so a conversation started in the quick
// panel continues seamlessly if the user switches to the main window,
// and vice versa.
//
// The one real difference from ContentView.swift's own layout: no fixed
// `.frame(maxHeight: 320)` cap on the turn log — ContentView's cap
// exists only because PanelController animates between two fixed
// popup heights; a real resizable window has no such constraint, so the
// turn log here just fills whatever space the window gives it.

import SwiftUI

struct MainChatPane: View {
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
            Divider().foregroundStyle(HiTheme.hairline)

            if state.turns.isEmpty {
                Spacer()
                Text("Ask anything, or pick a tab to force a persona.")
                    .font(HiTheme.mono(12.5))
                    .foregroundStyle(HiTheme.textFaint)
                    .frame(maxWidth: .infinity)
                Spacer()
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 0) {
                            ForEach(state.turns) { turn in
                                TurnRow(turn: turn).id(turn.id)
                            }
                        }
                        .padding(.vertical, 6)
                    }
                    .onChange(of: state.turns) { newTurns in
                        guard let lastID = newTurns.last?.id else { return }
                        proxy.scrollTo(lastID, anchor: .bottom)
                    }
                }
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
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(HiTheme.bgPanel)
    }
}
