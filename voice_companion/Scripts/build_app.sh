#!/bin/bash
# Assembles a real .app bundle from the Swift Package Manager build output
# — required, not optional, since macOS hard-crashes (TCC) any process
# that touches Microphone/Speech Recognition without an Info.plist
# declaring why (verified live: the bare `swift build` binary crashed
# with exactly this reason before this script existed). SPM alone
# produces a plain executable, not a bundle with an Info.plist, so this
# is the lightweight, no-Xcode-project alternative to get one.
set -euo pipefail

cd "$(dirname "$0")/.."

CONFIGURATION="${1:-debug}"
swift build -c "$CONFIGURATION"

BIN_PATH="$(swift build -c "$CONFIGURATION" --show-bin-path)/HiVoice"
APP_DIR="$(swift build -c "$CONFIGURATION" --show-bin-path)/hi Voice.app"

rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"

cp "$BIN_PATH" "$APP_DIR/Contents/MacOS/HiVoice"
cp Resources/Info.plist "$APP_DIR/Contents/Info.plist"

# Ad-hoc codesign (no Developer ID needed for local, personal use) — a
# completely unsigned binary can behave inconsistently with TCC prompts
# on some macOS versions; ad-hoc signing gives it a stable identity
# without needing an Apple Developer account.
codesign --force --deep --sign - "$APP_DIR"

echo "Built: $APP_DIR"
echo "Run with: open \"$APP_DIR\""
