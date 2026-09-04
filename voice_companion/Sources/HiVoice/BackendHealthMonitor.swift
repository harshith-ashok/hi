// Periodically checks whether hi/ipc/server.py (`hi --voice-daemon`) is
// actually reachable, so the menu bar status icon can show "backend not
// running" as its own distinct state — a real, actionable signal this
// app was otherwise silent about: AppState.error only ever fires *after*
// a query is attempted and fails, so without this, the panel would just
// look broken with no explanation until you tried to use it.

import Foundation

@MainActor
final class BackendHealthMonitor: ObservableObject {
    @Published private(set) var isReachable = false

    private let backend: BackendClient
    private var task: Task<Void, Never>?
    private static let checkInterval: Duration = .seconds(5)

    init(backend: BackendClient) {
        self.backend = backend
        task = Task { [weak self] in
            while let self, !Task.isCancelled {
                self.isReachable = await self.backend.ping()
                try? await Task.sleep(for: Self.checkInterval)
            }
        }
    }

    deinit {
        task?.cancel()
    }
}
