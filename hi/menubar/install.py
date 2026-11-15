"""Package the menu bar app as ~/Applications/hi.app and add it to Login Items (`hi --install-app`).

The bundle is tiny: a compiled Swift launcher that starts this project's Python (`python -m hi.cli --menubar`)
as its child and forwards quit signals. It exists so macOS knows the app as "hi": Screen Recording and
Accessibility permissions are listed (and granted) under hi, not under whatever terminal started it, and
the app can be opened from Finder, Spotlight and Login Items. The Python code stays in this repository,
so updating the code needs no reinstall; reinstalling after moving the repo or its virtualenv is needed.
"""

from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

APP = Path.home() / "Applications" / "hi.app"
BUNDLE_ID = "com.harshith.hi.menubar"
REPO = Path(__file__).resolve().parents[2]

LAUNCHER_SWIFT = '''
import Foundation

let process = Process()
process.executableURL = URL(fileURLWithPath: "{python}")
process.arguments = ["-m", "hi.cli", "--menubar"]
process.currentDirectoryURL = URL(fileURLWithPath: "{repo}")
var env = ProcessInfo.processInfo.environment
env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + (env["PATH"] ?? "/usr/bin:/bin")
process.environment = env

var sources: [DispatchSourceSignal] = []
for sig in [SIGTERM, SIGINT, SIGHUP] {{
    signal(sig, SIG_IGN)
    let source = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    source.setEventHandler {{ process.terminate() }}
    source.resume()
    sources.append(source)
}}
process.terminationHandler = {{ p in exit(p.terminationStatus) }}
do {{ try process.run() }} catch {{ exit(1) }}
dispatchMain()
'''


def _icon_png(size: int) -> bytes:
    from AppKit import (
        NSBezierPath, NSBitmapImageRep, NSColor, NSGradient, NSImage, NSImageSymbolConfiguration, NSMakeRect,
    )

    image = NSImage.alloc().initWithSize_((size, size))
    image.lockFocus()
    body = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(size * 0.06, size * 0.06, size * 0.88, size * 0.88), size * 0.2, size * 0.2
    )
    NSGradient.alloc().initWithStartingColor_endingColor_(
        NSColor.colorWithWhite_alpha_(0.0, 1.0), NSColor.colorWithWhite_alpha_(0.32, 1.0)
    ).drawInBezierPath_angle_(body, -90)  # black at the top, graphite below: the notch island
    symbol = NSImage.imageWithSystemSymbolName_accessibilityDescription_("sparkles", None)
    config = NSImageSymbolConfiguration.configurationWithPointSize_weight_scale_(size * 0.42, 0.4, 3)
    config = config.configurationByApplyingConfiguration_(
        NSImageSymbolConfiguration.configurationWithPaletteColors_([NSColor.whiteColor()])
    )
    symbol = symbol.imageWithSymbolConfiguration_(config)
    extent = symbol.size()
    symbol.drawInRect_(NSMakeRect((size - extent.width) / 2, (size - extent.height) / 2, extent.width, extent.height))
    image.unlockFocus()
    rep = NSBitmapImageRep.alloc().initWithData_(image.TIFFRepresentation())
    return bytes(rep.representationUsingType_properties_(4, {}))  # 4 = PNG


def _make_icns(dest: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "hi.iconset"
        iconset.mkdir()
        for base in (16, 32, 128, 256, 512):
            (iconset / f"icon_{base}x{base}.png").write_bytes(_icon_png(base))
            (iconset / f"icon_{base}x{base}@2x.png").write_bytes(_icon_png(base * 2))
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(dest)], check=True)


def _login_item_script(add: bool) -> str:
    remove = 'if exists login item "hi" then delete login item "hi"'
    if not add:
        return f'tell application "System Events"\n{remove}\nend tell'
    return (
        f'tell application "System Events"\n{remove}\n'
        f'make login item at end with properties {{name:"hi", path:"{APP}", hidden:true}}\nend tell'
    )


def install_app() -> str:
    if sys.platform != "darwin":
        return "The menu bar app is macOS only."
    if not shutil.which("swiftc"):
        return "swiftc not found: install the Xcode command line tools (`xcode-select --install`) and retry."
    if APP.exists():
        shutil.rmtree(APP)
    (APP / "Contents" / "MacOS").mkdir(parents=True)
    (APP / "Contents" / "Resources").mkdir()
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "launcher.swift"
        source.write_text(LAUNCHER_SWIFT.format(python=sys.executable, repo=REPO))
        built = subprocess.run(
            ["swiftc", "-O", str(source), "-o", str(APP / "Contents" / "MacOS" / "hi")], capture_output=True, text=True
        )
    if built.returncode != 0:
        return f"Building the launcher failed:\n{built.stderr[-800:]}"
    _make_icns(APP / "Contents" / "Resources" / "hi.icns")
    (APP / "Contents" / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleName": "hi", "CFBundleDisplayName": "hi", "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": "hi", "CFBundleIconFile": "hi", "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1", "CFBundleShortVersionString": "1.0", "LSMinimumSystemVersion": "13.0",
        "LSUIElement": True,  # menu bar and notch only: no Dock icon
        "NSHighResolutionCapable": True,
        "NSAppleEventsUsageDescription": "hi reads the frontmost window's title so it knows what you are working on.",
    }))
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(APP)], capture_output=True)  # ad hoc
    login = subprocess.run(["osascript", "-e", _login_item_script(True)], capture_output=True, text=True)
    added = "added to Login Items" if login.returncode == 0 else f"could not add the Login Item ({login.stderr.strip()[:120]})"
    return f"Installed {APP} and {added}. Open it from Finder or Spotlight, or run `hi`."


def uninstall_app() -> str:
    subprocess.run(["osascript", "-e", _login_item_script(False)], capture_output=True)
    if APP.exists():
        shutil.rmtree(APP)
    return "Removed hi.app and its Login Item."
