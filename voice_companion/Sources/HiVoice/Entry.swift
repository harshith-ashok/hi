// A @main struct rather than a script-style main.swift: top-level code
// in main.swift is not implicitly @MainActor-isolated under Swift 6's
// strict concurrency (caught live — `AppDelegate()`, a @MainActor type,
// failed to compile from plain top-level main.swift code with "call to
// main actor-isolated initializer in a synchronous nonisolated context").
// A static main() can be explicitly @MainActor instead.

import AppKit

@main
struct HiVoiceApp {
    @MainActor
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.run()
    }
}
