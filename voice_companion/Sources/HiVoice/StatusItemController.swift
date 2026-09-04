// Small menu bar status icon (explicit request). This app has no Dock
// icon (NSApp.setActivationPolicy(.accessory) in AppDelegate), so before
// this existed there was no persistent on-screen affordance at all — no
// visible sign it was running, and genuinely no way to quit it except
// killing the process from a terminal. The icon doubles as that missing
// affordance (its menu's Quit item is the app's only quit path), a
// manual "Show" trigger (a fallback for the global hotkey, which needs
// Accessibility trust that might not be granted yet), a live status
// readout: AppState's own visible/listening/busy signals plus whether
// hi --voice-daemon is actually reachable (BackendHealthMonitor) — a
// state the app was otherwise silent about until a query failed — and,
// per TODO.md Phase 17, a "pending approvals" indicator
// (PendingActionsMonitor) so a destructive action an orchestrated
// subagent is waiting on never hangs silently with no visible sign
// anything needs the user's attention.

import AppKit
import Combine

@MainActor
final class StatusItemController: NSObject {
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
    private let statusLineItem = NSMenuItem(title: "Backend: checking…", action: nil, keyEquivalent: "")
    private let menu = NSMenu()

    private var stateSubscription: AnyCancellable?
    private var healthSubscription: AnyCancellable?
    private var pendingSubscription: AnyCancellable?
    private var lastReachable = false
    private var lastPendingCount = 0
    private var onShow: (() -> Void)?
    private var pendingMonitor: PendingActionsMonitor?

    private static let pendingItemTag = 1001

    init(state: AppState, health: BackendHealthMonitor, pending: PendingActionsMonitor, onShow: @escaping () -> Void) {
        super.init()
        self.onShow = onShow
        self.pendingMonitor = pending

        statusLineItem.isEnabled = false
        let showItem = NSMenuItem(title: "Show hi Voice", action: #selector(show), keyEquivalent: " ")
        showItem.keyEquivalentModifierMask = .option
        showItem.target = self
        let quitItem = NSMenuItem(title: "Quit hi Voice", action: #selector(quit), keyEquivalent: "q")
        quitItem.target = self

        menu.addItem(statusLineItem)
        menu.addItem(.separator())
        menu.addItem(showItem)
        menu.addItem(quitItem)
        statusItem.menu = menu

        applyIcon(state: state, reachable: health.isReachable, pendingCount: 0)

        // Combines every signal the icon depends on into one stream so a
        // change to any of them (visibility, listening, busy, the last
        // turn's role) recomputes the same way — mirrors PanelController's
        // own dedup-before-combine approach: `turns` is mapped down to
        // just its last role before comparison, so a streamed token
        // appended to the last turn's *content* (role unchanged) doesn't
        // re-trigger this on every token.
        let lastRole = state.$turns.map { $0.last?.role }.removeDuplicates()
        stateSubscription = Publishers.CombineLatest4(
            state.$isVisible, state.$isListening, state.$isBusy, lastRole
        )
        .sink { [weak self] _, _, _, _ in
            guard let self else { return }
            self.applyIcon(state: state, reachable: self.lastReachable, pendingCount: self.lastPendingCount)
        }
        healthSubscription = health.$isReachable.sink { [weak self] reachable in
            guard let self else { return }
            self.lastReachable = reachable
            self.applyIcon(state: state, reachable: reachable, pendingCount: self.lastPendingCount)
            self.statusLineItem.title = reachable
                ? "Backend: connected"
                : "Backend: not running (hi --voice-daemon)"
        }
        pendingSubscription = pending.$actions.sink { [weak self] actions in
            guard let self else { return }
            self.lastPendingCount = actions.count
            self.applyIcon(state: state, reachable: self.lastReachable, pendingCount: actions.count)
            self.rebuildPendingMenuItems(actions)
        }
    }

    private func applyIcon(state: AppState, reachable: Bool, pendingCount: Int) {
        let symbol: String
        let description: String
        var tint: NSColor?

        if !reachable {
            symbol = "exclamationmark.triangle.fill"
            description = "hi Voice — backend not running"
            tint = .systemRed
        } else if pendingCount > 0 {
            symbol = "exclamationmark.circle.fill"
            description = "hi Voice — \(pendingCount) action\(pendingCount == 1 ? "" : "s") awaiting approval"
            tint = .systemOrange
        } else if !state.isVisible {
            symbol = "waveform"
            description = "hi Voice — idle"
        } else if state.isListening {
            symbol = "mic.fill"
            description = "hi Voice — listening"
            tint = .systemBlue
        } else if state.isBusy {
            symbol = "ellipsis.circle"
            description = "hi Voice — working"
        } else if case .systemError = state.turns.last?.role {
            symbol = "exclamationmark.triangle.fill"
            description = "hi Voice — error"
            tint = .systemRed
        } else {
            symbol = "text.cursor"
            description = "hi Voice — ready for input"
        }

        let image = NSImage(systemSymbolName: symbol, accessibilityDescription: description)
        image?.isTemplate = true  // adapts to light/dark menu bar automatically, per Apple HIG
        statusItem.button?.image = image
        statusItem.button?.contentTintColor = tint
        statusItem.button?.toolTip = description
    }

    /// Removes any pending-action rows from a previous poll, then
    /// re-adds one row per currently-pending action (with its own
    /// Approve/Deny submenu) right below the status line — always
    /// empty today, per PendingActionInfo's own doc comment, but built
    /// and ready for whenever that changes.
    private func rebuildPendingMenuItems(_ actions: [PendingActionInfo]) {
        for item in menu.items.filter({ $0.tag == Self.pendingItemTag }) {
            menu.removeItem(item)
        }
        guard !actions.isEmpty else { return }

        var insertAt = menu.index(of: statusLineItem) + 1
        for action in actions {
            let item = NSMenuItem(title: action.description, action: nil, keyEquivalent: "")
            item.tag = Self.pendingItemTag
            let submenu = NSMenu()
            let approveItem = NSMenuItem(title: "Approve", action: #selector(approvePending(_:)), keyEquivalent: "")
            approveItem.target = self
            approveItem.representedObject = action
            let denyItem = NSMenuItem(title: "Deny", action: #selector(denyPending(_:)), keyEquivalent: "")
            denyItem.target = self
            denyItem.representedObject = action
            submenu.addItem(approveItem)
            submenu.addItem(denyItem)
            item.submenu = submenu
            menu.insertItem(item, at: insertAt)
            insertAt += 1
        }
        menu.insertItem(.separator(), at: insertAt)
        menu.items[insertAt].tag = Self.pendingItemTag
    }

    @objc private func approvePending(_ sender: NSMenuItem) {
        guard let action = sender.representedObject as? PendingActionInfo else { return }
        pendingMonitor?.resolve(action, approve: true)
    }

    @objc private func denyPending(_ sender: NSMenuItem) {
        guard let action = sender.representedObject as? PendingActionInfo else { return }
        pendingMonitor?.resolve(action, approve: false)
    }

    @objc private func show() {
        onShow?()
    }

    @objc private func quit() {
        NSApplication.shared.terminate(nil)
    }
}
