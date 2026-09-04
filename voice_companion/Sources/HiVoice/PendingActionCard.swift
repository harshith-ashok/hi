// Inline approve/deny UI for a destructive action an orchestrated
// subagent is waiting on (TODO.md Phase 20, "approvals as generative
// UI, not text") — real tappable buttons rendered right where the run
// that triggered them is happening, via the same AG-UI CUSTOM events
// (`pending_action`/`pending_action_resolved`, hi/agui_adapter.py) every
// other part of a turn already streams through. This is additional to,
// not a replacement for, the existing menu-bar indicator
// (PendingActionsMonitor.swift/StatusItemController.swift) — that one
// polls globally and is useful even when the panel itself is closed;
// this one is scoped to the run visibly producing it right now.

import SwiftUI

struct PendingActionCard: View {
    // Kept in sync with PanelController's own height math, the same
    // "keep in sync" relationship WidgetView's constants already have.
    static let cardHeight: CGFloat = 56

    let action: InlinePendingAction
    var onResolve: (Bool) -> Void

    var body: some View {
        HStack(spacing: 10) {
            Circle()
                .fill(statusColor)
                .frame(width: 6, height: 6)

            Text(action.description)
                .font(HiTheme.mono(11.5))
                .foregroundStyle(HiTheme.textDim)
                .lineLimit(2)
                .truncationMode(.tail)
                .frame(maxWidth: .infinity, alignment: .leading)

            switch action.resolution {
            case .none:
                Button(action: { onResolve(false) }) {
                    Text("Deny")
                        .font(HiTheme.mono(11.5))
                        .foregroundStyle(HiTheme.rust)
                }
                .buttonStyle(.plain)
                Button(action: { onResolve(true) }) {
                    Text("Approve")
                        .font(HiTheme.mono(11.5, weight: .medium))
                        .foregroundStyle(HiTheme.teal)
                }
                .buttonStyle(.plain)
            case .some(true):
                Text("Approved").font(HiTheme.mono(11.5)).foregroundStyle(HiTheme.teal)
            case .some(false):
                Text("Denied").font(HiTheme.mono(11.5)).foregroundStyle(HiTheme.rust)
            }
        }
        .padding(.horizontal, 16)
        .frame(height: Self.cardHeight)
        .background(HiTheme.bgRow)
        .overlay(alignment: .leading) {
            Rectangle().fill(statusColor).frame(width: 2)
        }
    }

    private var statusColor: Color {
        switch action.resolution {
        case .none: return HiTheme.amber
        case .some(true): return HiTheme.teal
        case .some(false): return HiTheme.rust
        }
    }
}

struct PendingActionList: View {
    let actions: [InlinePendingAction]
    var onResolve: (String, Bool) -> Void

    var body: some View {
        VStack(spacing: 0) {
            ForEach(actions) { action in
                Divider().foregroundStyle(HiTheme.hairline)
                PendingActionCard(action: action, onResolve: { approved in onResolve(action.id, approved) })
            }
        }
    }
}
