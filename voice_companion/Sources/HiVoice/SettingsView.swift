// Settings screen (TODO.md "proper native app") — a real GUI over
// ~/.hi/.env instead of hand-editing it, backed by hi/ipc/server.py's
// new GET/POST /config. Deliberately does NOT include the MCP
// credentials (GitHub token, Obsidian API key) — those stay reachable
// only through hi/mcp_install.py's conversational, confirm-gated tool
// (ask butler "configure the github MCP server"), never echoed back to
// a GET here; see that endpoint's own comment for why.

import SwiftUI

struct SettingsView: View {
    let backend: BackendClient

    @State private var fields: [String: String] = [:]
    @State private var isLoading = true
    @State private var isSaving = false
    @State private var statusMessage: String?

    private static let fieldOrder = [
        "VAULT_PATH", "HAIKU_MODEL", "SONNET_MODEL", "OPUS_MODEL", "VISION_MODEL",
        "BUTLER_MODEL", "DOCS_MODEL", "WEB_MODEL", "TERM_MODEL",
    ]
    private static let fieldLabels: [String: String] = [
        "VAULT_PATH": "Obsidian vault path",
        "HAIKU_MODEL": "\"haiku\" tier model (quick lookups)",
        "SONNET_MODEL": "\"sonnet\" tier model (default)",
        "OPUS_MODEL": "\"opus\" tier model (hardest requests)",
        "VISION_MODEL": "vision model (screen/image reading)",
        "BUTLER_MODEL": "butler's own default model",
        "DOCS_MODEL": "docs' own default model",
        "WEB_MODEL": "web's own default model",
        "TERM_MODEL": "term's own default model",
    ]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("Settings")
                    .font(HiTheme.mono(15, weight: .medium))
                    .foregroundStyle(HiTheme.text)

                Text(
                    "Written directly to ~/.hi/.env — the same file hi/config.py "
                    + "reads at startup. Restart hi (and the voice daemon) for "
                    + "model/vault-path changes to take effect."
                )
                .font(HiTheme.mono(11))
                .foregroundStyle(HiTheme.textFaint)

                if isLoading {
                    Text("Loading…")
                        .font(HiTheme.mono(12))
                        .foregroundStyle(HiTheme.textFaint)
                } else {
                    VStack(alignment: .leading, spacing: 14) {
                        ForEach(Self.fieldOrder, id: \.self) { field in
                            fieldRow(field)
                        }
                    }

                    HStack(spacing: 10) {
                        Button(action: save) {
                            Text(isSaving ? "Saving…" : "Save")
                                .font(HiTheme.mono(12, weight: .medium))
                                .foregroundStyle(HiTheme.teal)
                        }
                        .buttonStyle(.plain)
                        .disabled(isSaving)

                        if let statusMessage {
                            Text(statusMessage)
                                .font(HiTheme.mono(11))
                                .foregroundStyle(HiTheme.textDim)
                        }
                    }
                    .padding(.top, 4)
                }
            }
            .padding(20)
            .frame(maxWidth: 520, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(HiTheme.bgPanel)
        .task {
            fields = await backend.fetchConfig()
            isLoading = false
        }
    }

    private func fieldRow(_ field: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(Self.fieldLabels[field] ?? field)
                .font(HiTheme.mono(11))
                .foregroundStyle(HiTheme.textFaint)
            TextField("", text: Binding(
                get: { fields[field] ?? "" },
                set: { fields[field] = $0 }
            ))
            .textFieldStyle(.plain)
            .font(HiTheme.mono(12.5))
            .foregroundStyle(HiTheme.text)
            .padding(8)
            .background(HiTheme.bgRow)
            .clipShape(RoundedRectangle(cornerRadius: 4))
        }
    }

    private func save() {
        isSaving = true
        statusMessage = nil
        Task {
            let note = await backend.updateConfig(fields)
            isSaving = false
            statusMessage = note ?? "Failed to save — is the backend running?"
        }
    }
}
