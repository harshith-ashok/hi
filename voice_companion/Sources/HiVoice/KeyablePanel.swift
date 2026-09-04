// A borderless NSPanel does NOT become key by default — its text field
// would never accept keyboard input without this override. This is the
// standard Spotlight-alternative pattern (Alfred/Raycast/etc. all need
// the same override): `.nonactivatingPanel` in the style mask means
// *showing* this panel never steals focus from — or changes the menu bar
// of — whatever app was frontmost, but the panel can still separately
// become key to receive keystrokes once explicitly asked to
// (`makeKeyAndOrderFront`, called by PanelController).

import AppKit

final class KeyablePanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}
