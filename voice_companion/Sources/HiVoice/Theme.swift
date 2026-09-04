// Centralized visual language for the panel (TODO.md's "implement
// ui.html" follow-up to the Spotlight redesign): colors/fonts matching
// ui.html's design intent — a dark terminal aesthetic, JetBrains Mono +
// Inter, a teal accent, warm off-white text — ported to real
// macOS-native choices rather than a literal pixel-for-pixel
// recreation. Two deliberate substitutions, not oversights:
//
// - SF Mono instead of JetBrains Mono, and the system font instead of
//   Inter — both already installed, zero bundling risk. This is what
//   "feel like a native app" actually argues for: a hand-bundled web
//   font in a small utility panel is exactly the kind of thing that
//   reads as non-native (and ui.html's own copies are .woff2, a web
//   font format Core Text doesn't reliably handle). The mockup's font
//   *choice* — a monospace/humanist-sans pairing, monospace for
//   terminal-flavored chrome, sans for prose — is preserved; the
//   specific typeface isn't.
// - One fixed dark palette, not adapting to system light/dark mode —
//   matching ui.html's own single-theme design (it has no light
//   variant) and this project's whole terminal-first brand identity,
//   rather than the semantic-color light/dark adaptation the rest of
//   this app used before this redesign.
//
// `rust` (ui.html's --rust, present in its CSS but never assigned to a
// visible element in the mockup markup — only used in a background
// gradient) is repurposed here as this app's one semantic error color,
// since the mockup itself never had an error state to design for.

import SwiftUI

enum HiTheme {
    // MARK: - Colors — named after ui.html's own CSS custom properties

    static let bgPanel = Color(hex: 0x15181c)
    static let bgRow = Color(hex: 0x1a1e23)
    static let hairline = Color(hex: 0x262b31)
    static let text = Color(hex: 0xe4e1d6)
    static let textDim = Color(hex: 0x7c848c)
    static let textFaint = Color(hex: 0x4b5157)
    static let teal = Color(hex: 0x4fa69c)
    static let tealDim = Color(hex: 0x2e5f59)
    static let amber = Color(hex: 0xc99a3e)
    static let rust = Color(hex: 0xb4563a)

    static let assistantTint = teal.opacity(0.05)

    // MARK: - Fonts (SF Mono / system — see file header)

    static func mono(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }

    static func sans(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .default)
    }

    static let cornerRadius: CGFloat = 10
}

private extension Color {
    init(hex: UInt32, opacity: Double = 1) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255,
            opacity: opacity
        )
    }
}
