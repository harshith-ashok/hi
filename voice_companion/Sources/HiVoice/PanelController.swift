// Spotlight-style shell: a centered, floating `KeyablePanel`, hidden
// until summoned by a global hotkey (Option+Space, chosen to avoid
// colliding with real Spotlight's Cmd+Space) or the menu bar's "Show hi
// Voice" item, positioned the way Spotlight itself sits — horizontally
// centered, roughly the upper third of the main screen.
// `.nonactivatingPanel` still means showing it never steals focus from
// whatever app was frontmost or changes its menu bar; KeyablePanel is
// what lets it *also* accept keyboard input for the text field despite
// that, the standard Spotlight-alternative trick.
//
// Width (620pt) and the two target heights below match ui.html's own
// panel proportions (TODO.md's "implement ui.html" follow-up) — compact
// while there's no conversation yet (tabs + briefing-if-any + prompt
// bar), expanded once the turn log has content (adds up to ui.html's
// own 320pt log max-height). Deliberately only reacts to AppState's
// *kind* of content (hidden/visible, turns empty-or-not, briefing
// present-or-not) here — never business logic (what a submitted query
// means, when dictation starts), that lives in AppDelegate via the
// injected callbacks.

import AppKit
import Combine
import SwiftUI

@MainActor
final class PanelController: NSObject {
    private let panel: KeyablePanel
    private let state: AppState
    private var globalHotkeyMonitor: Any?
    private var localKeyMonitor: Any?
    private var kindSubscription: AnyCancellable?

    private static let panelWidth: CGFloat = 620
    // Estimated from ContentView's actual padding/font values (tabs row
    // ~37 + divider ~1 + prompt bar ~56); ContentView.swift's own
    // top-level `.frame(maxWidth:.infinity, maxHeight:.infinity)` fill
    // absorbs any gap between this estimate and SwiftUI's true layout
    // in the flexible turn-log area, so precision here matters far less
    // than it would without that fix — see that file's comment.
    private static let compactHeight: CGFloat = 94
    private static let briefingStripHeight: CGFloat = 30
    private static let compactHeightWithBriefing: CGFloat = compactHeight + briefingStripHeight
    private static let logMaxHeight: CGFloat = 320
    private static let expandedHeightBase: CGFloat = compactHeight + 1 + logMaxHeight  // + divider
    private static let expandedHeightWithBriefing: CGFloat = expandedHeightBase + briefingStripHeight
    // TODO.md Phase 18: an MCP-UI widget (WidgetView.swift) adds its own
    // header + content height plus one more divider — reads WidgetView's
    // own constants directly rather than duplicating the numbers, same
    // relationship this file already has with ContentView's TurnLogView
    // via logMaxHeight.
    private static let widgetHeight: CGFloat = WidgetView.headerHeight + WidgetView.contentHeight + 1
    // TODO.md Phase 20 ("approvals as generative UI"): each pending
    // action card adds its own fixed height plus a divider; capped at 3
    // simultaneous cards in the height estimate (more is a rare edge
    // case, and this project's own "close estimate, let the flexible
    // area absorb slack" approach — see ContentView.swift's own comment
    // — already tolerates being a little off for a rare case like this).
    private static let maxPendingCardsInHeightEstimate = 3
    // Spotlight itself sits close to, but not exactly at, the vertical
    // center — roughly a third of the way down the screen.
    private static let topInsetFraction: CGFloat = 0.28

    /// - onSubmit: the text field's Return action, or the transcript once
    ///   dictation stops itself (isFinal) — whichever happens first.
    init(
        state: AppState, onSubmit: @escaping (String) -> Void, onToggleListening: @escaping () -> Void,
        onRunBriefingAction: @escaping () -> Void, onResolvePendingAction: @escaping (String, Bool) -> Void
    ) {
        self.state = state

        let initialFrame = NSRect(x: 0, y: 0, width: Self.panelWidth, height: Self.compactHeight)
        panel = KeyablePanel(
            contentRect: initialFrame,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        panel.isMovable = false
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.hidesOnDeactivate = false

        super.init()

        let hosting = NSHostingView(
            rootView: ContentView(
                state: state,
                onSubmit: onSubmit,
                onToggleListening: onToggleListening,
                onRunBriefingAction: onRunBriefingAction,
                onResolvePendingAction: onResolvePendingAction
            )
        )
        panel.contentView = hosting

        startGlobalHotkeyMonitor()
        startLocalKeyMonitor()
        observeKind()
    }

    // Repositioning/refocusing must only happen on a genuine *kind*
    // transition, not on every keystroke or streamed token — a real bug
    // caught live in the original design (see voice_companion/README.md,
    // "The panel visibly jumped down and snapped back on every
    // keystroke"): without deduplicating on kind rather than full state
    // equality, every published change (a keystroke, a streamed token
    // appended to the last turn) re-fired the animated setFrame() call
    // below, visibly interrupting itself before settling. `turns` is
    // mapped down to just `isEmpty` (a token append never flips that)
    // before comparison, for the same reason.
    /// Everything below the briefing strip that can add height beyond
    /// the base compact/expanded numbers — a widget, and/or however many
    /// pending-approval cards are currently showing. Folded into one
    /// value (rather than a 5th separate CombineLatest publisher —
    /// Combine's built-in operators only go up to CombineLatest4) so
    /// `observeKind()` still combines exactly 4 publishers.
    private struct ExtraContent: Equatable {
        var hasWidget: Bool
        var pendingCount: Int
    }

    private enum PanelKind: Equatable {
        case hidden
        case compact(hasBriefing: Bool, extra: ExtraContent)
        case expanded(hasBriefing: Bool, extra: ExtraContent)
    }

    private func observeKind() {
        let visible = state.$isVisible
        let turnsEmpty = state.$turns.map(\.isEmpty)
        let hasBriefing = state.$briefing.map { $0 != nil }
        let extra = Publishers.CombineLatest(state.$widget, state.$pendingActions)
            .map { widget, pendingActions in ExtraContent(hasWidget: widget != nil, pendingCount: pendingActions.count) }

        kindSubscription = Publishers.CombineLatest4(visible, turnsEmpty, hasBriefing, extra)
            .map { isVisible, turnsEmpty, hasBriefing, extra -> PanelKind in
                guard isVisible else { return .hidden }
                return turnsEmpty
                    ? .compact(hasBriefing: hasBriefing, extra: extra)
                    : .expanded(hasBriefing: hasBriefing, extra: extra)
            }
            .removeDuplicates()
            .sink { [weak self] kind in
                self?.apply(kind)
            }
    }

    private static func extraHeight(_ extra: ExtraContent) -> CGFloat {
        var height: CGFloat = 0
        if extra.hasWidget { height += widgetHeight }
        if extra.pendingCount > 0 {
            let cards = min(extra.pendingCount, maxPendingCardsInHeightEstimate)
            height += (CGFloat(cards) * (PendingActionCard.cardHeight + 1))  // +1 per card's own divider
        }
        return height
    }

    private func apply(_ kind: PanelKind) {
        switch kind {
        case .hidden:
            panel.orderOut(nil)
        case .compact(let hasBriefing, let extra):
            let base = hasBriefing ? Self.compactHeightWithBriefing : Self.compactHeight
            reposition(height: base + Self.extraHeight(extra))
            showAndFocus()
        case .expanded(let hasBriefing, let extra):
            let base = hasBriefing ? Self.expandedHeightWithBriefing : Self.expandedHeightBase
            reposition(height: base + Self.extraHeight(extra))
            showAndFocus()
        }
    }

    private func showAndFocus() {
        if !panel.isVisible {
            panel.alphaValue = 0
            panel.orderFrontRegardless()
            NSAnimationContext.runAnimationGroup { context in
                context.duration = 0.16
                panel.animator().alphaValue = 1
            }
        }
        panel.makeKey()
    }

    private func reposition(height: CGFloat) {
        guard let screenFrame = NSScreen.main?.frame else { return }
        let newFrame = NSRect(
            x: screenFrame.midX - Self.panelWidth / 2,
            y: screenFrame.maxY - screenFrame.height * Self.topInsetFraction - height,
            width: Self.panelWidth,
            height: height
        )
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.2
            context.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
            panel.animator().setFrame(newFrame, display: true)
        }
    }

    /// Option+Space toggles the panel open/closed from anywhere — needs
    /// Accessibility trust, same as the original hover monitor did; see
    /// AppDelegate.requestAccessibilityPermission().
    private func startGlobalHotkeyMonitor() {
        globalHotkeyMonitor = NSEvent.addGlobalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard Self.isToggleHotkey(event) else { return }
            Task { @MainActor in self?.state.toggle() }
        }
    }

    /// A *local* monitor (fires only while this app's own window is key)
    /// for Escape-to-dismiss and the same hotkey toggling closed again —
    /// the global monitor above never sees events while this app itself
    /// is frontmost/key.
    private func startLocalKeyMonitor() {
        localKeyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self else { return event }
            if event.keyCode == Self.escapeKeyCode {
                self.state.hide()
                return nil
            }
            if Self.isToggleHotkey(event) {
                self.state.toggle()
                return nil
            }
            return event
        }
    }

    private static let escapeKeyCode: UInt16 = 53
    private static let spaceKeyCode: UInt16 = 49

    private static func isToggleHotkey(_ event: NSEvent) -> Bool {
        event.keyCode == spaceKeyCode && event.modifierFlags.intersection(.deviceIndependentFlagsMask) == .option
    }

    deinit {
        if let globalHotkeyMonitor {
            NSEvent.removeMonitor(globalHotkeyMonitor)
        }
        if let localKeyMonitor {
            NSEvent.removeMonitor(localKeyMonitor)
        }
    }
}
