// The proper main app window (TODO.md: "create a proper native app
// that expands the functionality and replaces the terminal agent
// entirely... create a UI for it") — a standard resizable window with
// a sidebar (new chat / conversation history / settings), unlike the
// existing Option+Space quick panel (PanelController/ContentView),
// which stays exactly as it was for fast, no-window-management access.
// Both surfaces share the same AppState/BackendClient instances (passed
// in from AppDelegate), so a conversation continues seamlessly across
// either one.
//
// A hand-built sidebar, not NavigationSplitView/List — per explicit
// request to actually match the existing Spotlight-panel look
// (HiTheme's dark palette, monospace, teal accent) rather than macOS's
// own native sidebar vibrancy/materials, which don't take a custom
// background color the way a plain VStack does. Same trade-off
// PromptBar/TabButton already made: hand-rolled controls over native
// ones, for a consistent custom look over free native chrome.

import SwiftUI

enum MainWindowSelection: Hashable {
    case chat
    case history(String)
    case settings
}

struct MainWindowView: View {
    @ObservedObject var state: AppState
    let backend: BackendClient
    var onSubmit: (String) -> Void
    var onToggleListening: () -> Void
    var onRunBriefingAction: () -> Void
    var onResolvePendingAction: (String, Bool) -> Void

    @State private var selection: MainWindowSelection = .chat
    @State private var conversationDates: [String] = []

    private static let sidebarWidth: CGFloat = 200

    var body: some View {
        HStack(spacing: 0) {
            sidebar
            Divider().foregroundStyle(HiTheme.hairline)
            detail
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(HiTheme.bgPanel)
        .task {
            conversationDates = await backend.fetchConversationDates()
        }
    }

    // MARK: - Sidebar

    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 0) {
            SidebarRow(icon: "square.and.pencil", label: "New Chat", isActive: selection == .chat) {
                state.clearConversation()
                selection = .chat
            }
            .padding(.top, 12)
            .padding(.horizontal, 8)

            if !conversationDates.isEmpty {
                Text("HISTORY")
                    .font(HiTheme.mono(9.5, weight: .medium))
                    .foregroundStyle(HiTheme.textFaint)
                    .padding(.horizontal, 16)
                    .padding(.top, 20)
                    .padding(.bottom, 6)

                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(conversationDates, id: \.self) { date in
                            SidebarRow(label: date, isActive: selection == .history(date)) {
                                selection = .history(date)
                            }
                            .padding(.horizontal, 8)
                        }
                    }
                }
            }

            Spacer(minLength: 0)

            Divider().foregroundStyle(HiTheme.hairline)
            SidebarRow(icon: "gearshape", label: "Settings", isActive: selection == .settings) {
                selection = .settings
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 8)
        }
        .frame(width: Self.sidebarWidth)
        .frame(maxHeight: .infinity)
        .background(HiTheme.bgRow)
    }

    // MARK: - Detail

    @ViewBuilder
    private var detail: some View {
        switch selection {
        case .chat:
            MainChatPane(
                state: state,
                onSubmit: onSubmit,
                onToggleListening: onToggleListening,
                onRunBriefingAction: onRunBriefingAction,
                onResolvePendingAction: onResolvePendingAction
            )
        case .history(let date):
            HistoryView(date: date, backend: backend)
        case .settings:
            SettingsView(backend: backend)
        }
    }
}

/// One row in the hand-built sidebar — matches TabButton's own
/// hover/active styling conventions (teal when active, dim on hover,
/// faint otherwise) for visual consistency with the rest of the app.
private struct SidebarRow: View {
    var icon: String?
    let label: String
    let isActive: Bool
    let action: () -> Void

    @State private var isHovering = false

    init(icon: String? = nil, label: String, isActive: Bool, action: @escaping () -> Void) {
        self.icon = icon
        self.label = label
        self.isActive = isActive
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                if let icon {
                    Image(systemName: icon)
                        .font(.system(size: 11.5))
                        .frame(width: 14)
                }
                Text(label)
                    .font(HiTheme.mono(12))
                    .lineLimit(1)
                    .truncationMode(.tail)
                Spacer(minLength: 0)
            }
            .foregroundStyle(isActive ? HiTheme.teal : (isHovering ? HiTheme.textDim : HiTheme.textFaint))
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
            .background(isActive ? HiTheme.assistantTint : (isHovering ? HiTheme.bgPanel : .clear))
            .clipShape(RoundedRectangle(cornerRadius: 5))
        }
        .buttonStyle(.plain)
        .onHover { isHovering = $0 }
    }
}
