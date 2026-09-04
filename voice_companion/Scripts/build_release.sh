#!/bin/bash
# Builds a standalone, distributable "hi Voice.app" for dragging into
# /Applications — a one-time build (or "whenever I've changed the
# source and want to update it"), NOT the everyday launch path.
#
# Scripts/run.sh (and build_app.sh, which it calls) rebuild and
# re-codesign on EVERY invocation — the actual reason Accessibility/
# Microphone/Speech Recognition permission prompts kept reappearing on
# every launch: without a paid Apple Developer ID, the only signature
# available is an ad-hoc one, and macOS's TCC ties an ad-hoc-signed
# app's permission grant to the actual compiled binary's hash, not just
# its bundle identifier — so a fresh build (even from unchanged source;
# Swift's build output isn't guaranteed byte-identical run to run) looks
# like "different code" to TCC and it re-asks. That's a real constraint
# of ad-hoc signing, not a bug this script can fully remove.
#
# What actually stops the re-prompting: build once, drag the result into
# /Applications, and launch THAT going forward (Spotlight, Dock, Login
# Items) — never through this script or run.sh again. A stable, already-
# signed .app that isn't touched between launches keeps the exact same
# signature every time, so TCC's grant sticks.
set -euo pipefail

cd "$(dirname "$0")/.."

BUNDLE_ID="com.hi.voicecompanion"  # must match Resources/Info.plist's CFBundleIdentifier

echo "Building hi Voice.app (release configuration)..."
swift build -c release

BIN_PATH="$(swift build -c release --show-bin-path)/HiVoice"
DIST_DIR="dist"
APP_DIR="$DIST_DIR/hi Voice.app"

rm -rf "$DIST_DIR"
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"

cp "$BIN_PATH" "$APP_DIR/Contents/MacOS/HiVoice"
cp Resources/Info.plist "$APP_DIR/Contents/Info.plist"

# --identifier pins the signature's identity to the same bundle ID
# Info.plist declares, rather than letting codesign auto-derive one —
# best practice for an ad-hoc signature, though (see header) it can't by
# itself make TCC ignore a genuine binary change on a future rebuild.
codesign --force --deep --sign - --identifier "$BUNDLE_ID" "$APP_DIR"

echo
echo "Built: $(pwd)/$APP_DIR"
echo
echo "Drag \"hi Voice.app\" into /Applications, then launch it from there"
echo "(Spotlight, Dock, or Login Items) from now on — not via this script"
echo "or Scripts/run.sh, both of which rebuild + re-sign every time and"
echo "will keep re-triggering permission prompts as a result."

open -R "$APP_DIR"
