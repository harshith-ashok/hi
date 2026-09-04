// Periodically polls hi/ipc/server.py's GET /pending (TODO.md Phase 17),
// same shape as BackendHealthMonitor's own polling loop, for the menu
// bar's "pending approvals" indicator. Honest limitation, carried over
// from BackendClient.swift's own PendingActionInfo docstring: this
// always polls an empty list today, since an orchestrated run only ever
// happens in the terminal REPL's own process, not this app's backend —
// built and tested end-to-end regardless, ready for whenever that
// changes.

import Foundation

@MainActor
final class PendingActionsMonitor: ObservableObject {
    @Published private(set) var actions: [PendingActionInfo] = []

    private let backend: BackendClient
    private var task: Task<Void, Never>?
    private static let checkInterval: Duration = .seconds(5)

    init(backend: BackendClient) {
        self.backend = backend
        task = Task { [weak self] in
            while let self, !Task.isCancelled {
                self.actions = await self.backend.fetchPendingActions()
                try? await Task.sleep(for: Self.checkInterval)
            }
        }
    }

    func resolve(_ action: PendingActionInfo, approve: Bool) {
        Task {
            guard await backend.resolvePendingAction(id: action.id, approve: approve) else { return }
            // Don't wait for the next poll cycle to reflect this —
            // remove it from the list immediately so the menu doesn't
            // keep offering to resolve something already resolved.
            actions.removeAll { $0.id == action.id }
        }
    }

    deinit {
        task?.cancel()
    }
}
