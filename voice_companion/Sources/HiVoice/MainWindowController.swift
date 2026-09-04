// Owns the proper main app window (TODO.md: "create a proper native
// app... replaces the terminal agent entirely") — a standard, resizable,
// titled NSWindow, unlike PanelController's borderless floating panel.
// Deliberately simple compared to PanelController: no custom
// positioning/animation logic, no compact/expanded height math — a real
// window just gets a real size and the user resizes/moves it themselves,
// like any other Mac app.

import AppKit
import SwiftUI

@MainActor
final class MainWindowController: NSObject, NSWindowDelegate {
    private let window: NSWindow

    init(
        state: AppState, backend: BackendClient, onSubmit: @escaping (String) -> Void,
        onToggleListening: @escaping () -> Void, onRunBriefingAction: @escaping () -> Void,
        onResolvePendingAction: @escaping (String, Bool) -> Void
    ) {
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 920, height: 640),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "hi"
        // Per explicit request to match the existing Spotlight panel's
        // look: a transparent, title-hidden titlebar over the same dark
        // background as the panel (HiTheme.bgPanel's own hex, since
        // NSColor/SwiftUI Color don't bridge directly) — the traffic-
        // light buttons and drag/resize behavior of a real window stay,
        // but the titlebar strip itself is now a plain dark bar instead
        // of the default light/vibrant material. Deliberately NOT
        // paired with .fullSizeContentView — that would extend the
        // SwiftUI content view up underneath the titlebar/traffic
        // lights instead of just recoloring the strip, which would need
        // extra top-padding workarounds in every top-level view to
        // avoid the traffic lights overlapping real content.
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.backgroundColor = NSColor(srgbRed: 0x15 / 255, green: 0x18 / 255, blue: 0x1c / 255, alpha: 1)
        window.minSize = NSSize(width: 640, height: 420)
        window.center()
        window.isReleasedWhenClosed = false  // closing hides it — reopened via the Dock icon/menu, not rebuilt

        super.init()
        window.delegate = self

        let hosting = NSHostingView(
            rootView: MainWindowView(
                state: state,
                backend: backend,
                onSubmit: onSubmit,
                onToggleListening: onToggleListening,
                onRunBriefingAction: onRunBriefingAction,
                onResolvePendingAction: onResolvePendingAction
            )
        )
        window.contentView = hosting
    }

    func show() {
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    /// NSWindowDelegate: a real app window closing shouldn't quit a
    /// background daemon-style app — just hide it, same as the floating
    /// panel's own hide/show model, so the Dock icon (or Option+Space)
    /// can bring it right back without losing the transcript.
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        window.orderOut(nil)
        return false
    }
}
