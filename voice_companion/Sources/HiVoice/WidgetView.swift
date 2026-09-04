// A generic renderer for MCP-UI widgets (TODO.md Phase 18) — a tool's
// own rendered HTML, shown below the turn log whenever `AppState.widget`
// is set. Sandboxed on purpose: `loadHTMLString(_:baseURL:)` with a nil
// base URL loads the string as an opaque in-memory document with no
// filesystem/network origin to escalate from — there's no reason a
// locally-generated widget needs arbitrary network access, matching this
// project's "nothing reaches the network unless something explicit
// requires it" discipline (mirrors hi/'s own air-gapped-tooling stance,
// even though this is a UI convenience, not a model-serving path).
//
// **Not verified against a real MCP-UI server** — none of this project's
// configured MCP servers (Playwright, GitHub, Obsidian) implement the
// mcp-ui extension yet, so this has only been exercised against
// synthetic HTML shaped like the real spec's `text/html` resource
// payload. See `hi/agui_adapter.py`'s own docstring for the same caveat
// on the detection side.

import SwiftUI
import WebKit

struct WidgetView: View {
    // Kept in sync with PanelController's own height math (its
    // `widgetHeight` reads these two constants directly rather than
    // duplicating them) — the same "keep in sync" relationship
    // ContentView.swift's TurnLogView already has with
    // PanelController.logMaxHeight.
    static let headerHeight: CGFloat = 26
    static let contentHeight: CGFloat = 180

    let widget: WidgetInfo
    var onDismiss: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Text(widget.uri)
                    .font(HiTheme.mono(10.5))
                    .foregroundStyle(HiTheme.textFaint)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Spacer(minLength: 8)
                Button(action: onDismiss) {
                    Image(systemName: "xmark")
                        .font(.system(size: 9))
                        .foregroundStyle(HiTheme.textFaint)
                }
                .buttonStyle(.plain)
                .help("Dismiss widget")
            }
            .padding(.horizontal, 12)
            .frame(height: Self.headerHeight)
            .background(HiTheme.bgRow)

            WebViewRepresentable(html: widget.html)
                .frame(height: Self.contentHeight)
        }
    }
}

/// Bridges `WKWebView` into SwiftUI. No delegate/navigation hookup
/// needed — this only ever loads one static, already-complete HTML
/// string per widget, never a real URL a user could navigate away to.
private struct WebViewRepresentable: NSViewRepresentable {
    let html: String

    func makeNSView(context: Context) -> WKWebView {
        let webView = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        webView.loadHTMLString(html, baseURL: nil)
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        // A new widget replaces the old one wholesale (AppState.setWidget
        // never mutates in place), so re-loading unconditionally here is
        // correct, not wasteful — this only runs when `html` actually
        // changed identity via a new WidgetInfo value.
        webView.loadHTMLString(html, baseURL: nil)
    }
}
