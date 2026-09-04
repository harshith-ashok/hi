// Read-only view of one day's logged conversation (TODO.md "proper
// native app" sidebar history) — fetched fresh each time a date is
// selected rather than cached, since the backend's own conversation
// logs are the single source of truth and this view has no reason to
// duplicate that state locally.
//
// Renders via ConversationLogParser -> the exact same TurnRow the live
// chat pane uses (same padding, role-accent border, tag styling) rather
// than a raw Markdown dump — per explicit request to give past
// conversations real formatting/padding matching the rest of the app,
// not a second, plainer look.

import SwiftUI

struct HistoryView: View {
    let date: String
    let backend: BackendClient

    @State private var exchanges: [HistoryExchange] = []
    @State private var isLoading = true
    @State private var loadFailed = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Text(date)
                    .font(HiTheme.mono(13, weight: .medium))
                    .foregroundStyle(HiTheme.text)
                Spacer()
                if !exchanges.isEmpty {
                    Text("\(exchanges.count) exchange\(exchanges.count == 1 ? "" : "s")")
                        .font(HiTheme.mono(11))
                        .foregroundStyle(HiTheme.textFaint)
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 14)

            Divider().foregroundStyle(HiTheme.hairline)

            if isLoading {
                Spacer()
                Text("Loading…")
                    .font(HiTheme.mono(12))
                    .foregroundStyle(HiTheme.textFaint)
                    .frame(maxWidth: .infinity)
                Spacer()
            } else if loadFailed {
                Spacer()
                Text("Couldn't load this conversation.")
                    .font(HiTheme.mono(12))
                    .foregroundStyle(HiTheme.rust)
                    .frame(maxWidth: .infinity)
                Spacer()
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(exchanges) { exchange in
                            Text(exchange.time)
                                .font(HiTheme.mono(10.5))
                                .foregroundStyle(HiTheme.textFaint)
                                .padding(.horizontal, 16)
                                .padding(.top, 14)
                                .padding(.bottom, 4)
                            TurnRow(turn: exchange.userTurn)
                            TurnRow(turn: exchange.assistantTurn)
                        }
                    }
                    .padding(.bottom, 12)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(HiTheme.bgPanel)
        .task(id: date) {
            isLoading = true
            loadFailed = false
            if let content = await backend.fetchConversation(date: date) {
                exchanges = ConversationLogParser.parse(content)
            } else {
                loadFailed = true
            }
            isLoading = false
        }
    }
}
