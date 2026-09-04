// Wires the pieces together: permissions -> panel -> mic/text -> backend
// -> speech output. It inherits all the task/memory/agent logic from
// the shared Python backend instead of duplicating any of it — this
// file owns UI/session flow only, every actual answer comes from
// hi/ipc/server.py (BackendClient), the same backend hi/repl.py's
// router mode already drives.
//
// A query can come from typing directly into the field, from dictation,
// or a mix (typed prefix + dictated suffix) — dictation live-updates
// the same text field typing would, rather than a dedicated "Listening"
// state. Each submitted query appends a user turn, then a streaming
// assistant turn, into AppState's growing turn log (TODO.md's "implement
// ui.html" follow-up) — nothing here erases prior turns; a session is a
// running conversation, not a series of one-shot Q&As.

import AppKit
import Combine

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private let state = AppState()
    private let recognizer = SpeechRecognizer()
    private let speechOutput = SpeechOutput()
    private let backend = BackendClient()
    private lazy var healthMonitor = BackendHealthMonitor(backend: backend)
    private lazy var pendingMonitor = PendingActionsMonitor(backend: backend)

    private var panelController: PanelController?
    private var mainWindowController: MainWindowController?
    private var statusItemController: StatusItemController?
    private var transcriptSubscription: AnyCancellable?
    private var queryTask: Task<Void, Never>?

    /// The field's text at the moment dictation started, so a partial
    /// transcript update appends after whatever was already typed rather
    /// than overwriting it.
    private var textBeforeDictation = ""

    func applicationDidFinishLaunching(_ notification: Notification) {
        // TODO.md: "create a proper native app... replaces the terminal
        // agent entirely" — .regular, not .accessory: a Dock icon, real
        // Cmd+Tab presence, a standard app menu (built below), the way
        // an app meant to be someone's daily driver behaves. The
        // Option+Space quick panel and menu bar status item both still
        // work exactly as before; this only adds presence on top.
        NSApp.setActivationPolicy(.regular)
        buildMainMenu()

        requestAccessibilityPermission()

        panelController = PanelController(
            state: state,
            onSubmit: { [weak self] text in self?.submit(text) },
            onToggleListening: { [weak self] in self?.toggleDictation() },
            onRunBriefingAction: { [weak self] in self?.runBriefingAction() },
            onResolvePendingAction: { [weak self] id, approved in self?.resolvePendingAction(id: id, approved: approved) }
        )
        mainWindowController = MainWindowController(
            state: state,
            backend: backend,
            onSubmit: { [weak self] text in self?.submit(text) },
            onToggleListening: { [weak self] in self?.toggleDictation() },
            onRunBriefingAction: { [weak self] in self?.runBriefingAction() },
            onResolvePendingAction: { [weak self] id, approved in self?.resolvePendingAction(id: id, approved: approved) }
        )
        statusItemController = StatusItemController(state: state, health: healthMonitor, pending: pendingMonitor, onShow: { [weak self] in
            self?.state.show()
        })

        transcriptSubscription = recognizer.$partialTranscript
            .sink { [weak self] partial in
                guard let self, self.recognizer.isListening else { return }
                let combined = self.textBeforeDictation.isEmpty ? partial : "\(self.textBeforeDictation) \(partial)"
                self.state.inputText = combined
            }

        loadBriefing()
        mainWindowController?.show()
    }

    /// A minimal programmatic main menu — this app has no Xib/Storyboard
    /// (build_app.sh's own comment: plain SPM build, no Xcode project),
    /// so switching to .regular activation policy needs one built by
    /// hand or Cmd+Q/standard window commands silently wouldn't work.
    /// Deliberately minimal: just the two menus an app can't function
    /// properly without, not a full custom menu bar.
    private func buildMainMenu() {
        let mainMenu = NSMenu()

        let appMenuItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About hi", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit hi", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appMenuItem.submenu = appMenu
        mainMenu.addItem(appMenuItem)

        let windowMenuItem = NSMenuItem()
        let windowMenu = NSMenu(title: "Window")
        windowMenu.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "Zoom", action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        windowMenu.addItem(.separator())
        windowMenu.addItem(withTitle: "Bring All to Front", action: #selector(NSApplication.arrangeInFront(_:)), keyEquivalent: "")
        windowMenuItem.submenu = windowMenu
        mainMenu.addItem(windowMenuItem)
        NSApp.windowsMenu = windowMenu

        NSApp.mainMenu = mainMenu
    }

    /// Dock icon clicked with no visible windows (e.g. the main window
    /// was closed, which only hides it — see MainWindowController's own
    /// windowShouldClose) — bring it back rather than doing nothing.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows: Bool) -> Bool {
        if !hasVisibleWindows {
            mainWindowController?.show()
        }
        return true
    }

    /// Fetched once at launch (same "shown once at session start" as
    /// hi/repl.py's own briefing), not re-fetched every time the panel
    /// is summoned — a haiku-tier call on every Option+Space would be
    /// wasteful for something that doesn't change turn to turn.
    private func loadBriefing() {
        Task {
            if let info = await backend.fetchBriefing() {
                state.setBriefing(info)
            }
        }
    }

    private func runBriefingAction() {
        guard let action = state.briefing?.action, !action.isEmpty else { return }
        state.dismissBriefing()
        submit(action)
    }

    /// A tap on an inline PendingActionCard's Approve/Deny button
    /// (TODO.md Phase 20). Updates local state immediately for instant
    /// feedback rather than waiting on the round trip through the SSE
    /// `pending_action_resolved` event that will also arrive shortly
    /// after (a harmless, idempotent re-set of the same value — see
    /// AppState.markPendingActionResolved()'s own guard against
    /// restarting an already-running removal timer).
    private func resolvePendingAction(id: String, approved: Bool) {
        Task {
            let ok = await backend.resolvePendingAction(id: id, approve: approved)
            if ok {
                state.markPendingActionResolved(id: id, approved: approved)
            }
        }
    }

    /// Accessibility is required for the global hotkey monitor
    /// (PanelController) — requested once, up front, with the system's
    /// own explanatory prompt rather than silently. Microphone/Speech
    /// Recognition are requested lazily, the first time dictation is
    /// actually toggled on, for the same reason.
    private func requestAccessibilityPermission() {
        let options: [String: Any] = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true]
        _ = AXIsProcessTrustedWithOptions(options as CFDictionary)
    }

    private func toggleDictation() {
        if recognizer.isListening {
            _ = recognizer.stop()
            state.setListening(false)
            return
        }

        speechOutput.stopSpeaking()  // barge-in
        textBeforeDictation = state.inputText

        Task {
            guard await recognizer.requestPermissions() else {
                state.appendError(recognizer.lastError ?? "Microphone/Speech permission not granted.")
                return
            }
            do {
                state.setListening(true)
                try recognizer.start()
            } catch {
                state.setListening(false)
                state.appendError("Couldn't start dictation: \(error.localizedDescription)")
            }
        }
    }

    private func submit(_ text: String) {
        if recognizer.isListening {
            _ = recognizer.stop()
            state.setListening(false)
        }
        let query = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty, !state.isBusy else { return }

        state.appendUserTurn(query)
        state.inputText = ""
        state.isBusy = true

        let forcedPersona = state.persona.backendName

        queryTask?.cancel()
        queryTask = Task {
            var sawPersona = false
            var finalText = ""
            var spokenSummary: String?
            var runErrorMessage: String?
            do {
                for try await event in backend.query(query, persona: forcedPersona) {
                    switch event {
                    case .personaSelected(let name, _, _):
                        sawPersona = true
                        state.beginAssistantTurn(persona: name)
                    case .runStarted:
                        break  // the assistant turn already began above; nothing more to do here
                    case .textDelta(let text, let subagentID):
                        // A Phase 16 orchestrated subagent's own text is
                        // background progress, not the growing answer —
                        // only the main (non-subagent) stream is what
                        // the visible turn should show live; runFinished
                        // supplies the real synthesized answer either way.
                        if subagentID == nil {
                            state.appendToken(text)
                        }
                    case .toolCallStart, .toolCallResult:
                        break  // not rendered in the transcript, same as before this phase
                    case .subagentStarted, .subagentFinished, .subagentError:
                        break  // milestone-level DAG progress — a real future UI surface, not built here (see TODO.md Phase 18/19's own scoping note)
                    case .runFinished(let result):
                        finalText = result
                    case .runError(let message):
                        runErrorMessage = message
                    case .spokenSummary(let text):
                        spokenSummary = text
                    case .mcpUIWidget(let uri, let html):
                        state.setWidget(uri: uri, html: html)
                    case .pendingAction(let id, let description):
                        state.addPendingAction(id: id, description: description)
                    case .pendingActionResolved(let id, let approved):
                        state.markPendingActionResolved(id: id, approved: approved)
                    case .decodeError:
                        break
                    }
                }
            } catch {
                state.isBusy = false
                state.appendError(
                    sawPersona
                        ? "Lost connection to the backend mid-response."
                        : "Couldn't reach the voice backend — is `hi --voice-daemon` running?"
                )
                return
            }

            state.isBusy = false
            if let runErrorMessage {
                state.appendError(runErrorMessage)
                return
            }
            state.finishAssistantTurn(finalText: finalText)
            if let spokenSummary {
                speechOutput.speak(spokenSummary)
            }
        }
    }
}
