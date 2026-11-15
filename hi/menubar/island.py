"""The notch island: a Liquid Glass panel that hangs from the notch and holds the assistant's UI.

- A slightly wider black pill sits over the notch at rest (a click opens the prompt). Macs without a notch
  have no pill; the menu bar icon opens the island instead.
- Opened by a click, it captures the screen first (before any window of ours shows), then expands downward
  from the notch with a prompt field. Enter sends it; the answer streams in underneath. Esc, the close button
  or a click elsewhere closes it.
- A nudge from the assistant (hi/context/inbox.py) opens the same island with its question and a reply field,
  without taking focus from what you are typing, and counts as ignored if untouched for a minute.

Material, type and symbols are the system's (NSGlassEffectView, SF Pro, SF Symbols), so the OS decides how it
renders. Only the bottom corners are visible and round: the top of the panel sits past the screen edge so it
reads as growing out of the notch.
"""

from __future__ import annotations

import math
import threading
import time

import objc
import Quartz
from Quartz import CAGradientLayer, CAShapeLayer
from AppKit import (
    NSAnimationContext, NSApplication, NSAppearance, NSBackingStoreBuffered, NSButton, NSColor, NSEvent,
    NSEventTypeRightMouseDown, NSFont, NSMenuItem, NSGlassEffectView, NSImage, NSImageView, NSMakeRect, NSMenu, NSPanel,
    NSScreen, NSScrollView, NSSound, NSStatusBar, NSTextField, NSTextView, NSTimer, NSVariableStatusItemLength, NSView,
)
from Foundation import NSObject
from PyObjCTools import AppHelper

import hi.config as config
from hi.context import inbox, now
from hi.env_file import write_env_var
from hi.menubar import hotkey
from hi.menubar.app import capture_screen, stream_answer

ISLAND_W = 440
OVERHANG = 28  # how far the panel extends past the screen's top edge, hiding its square-ish top
PILL_PAD = 24  # the resting pill is this much wider than the notch
CORNER = 34
# The Siri-bar look: solid black through the notch, fading to translucent glass, with a thin light rim.
BLACK_UNTIL_PAD = 14  # points of solid black below the notch before the fade starts
BOTTOM_ALPHA = 0.18  # how much black is left at the very bottom
RIM_ALPHA = 0.30
FIELD_H = 30
ANSWER_H = 190
MAX_PICTURE_H = 260
IGNORED_AFTER = 60  # seconds an untouched nudge stays before it counts as ignored
LINGER_AFTER_ANSWER = 180
POLL_SECONDS = 2
ANIMATION_SECONDS = 0.32
MASK_LEFT_DOWN, MASK_RIGHT_DOWN = 1 << 1, 1 << 3
CONTROL_FLAG = 1 << 18  # a control-click is a right-click
CURSOR_PAD = 16  # top padding in cursor mode: no notch to clear
CURSOR_GAP = 14  # gap between the pointer and the island's top edge
EDGE = 8  # keep the cursor-mode island this far inside the screen


class IslandPanel(NSPanel):
    """Takes keyboard focus for the text field without activating the app, and may sit past the screen edge."""

    def canBecomeKeyWindow(self) -> bool:
        return True

    def constrainFrameRect_toScreen_(self, rect, _screen):
        return rect


class NotchPill(NSView):
    """The resting black pill over the notch: a click opens the prompt."""

    def acceptsFirstMouse_(self, _event) -> bool:
        return True

    def mouseDown_(self, _event) -> None:
        self.opener.openPrompt_(None)


def wrap_text_view(view: NSTextView, width: int) -> None:
    """Make an NSTextView wrap at `width` and grow downward instead of running off to the right."""
    view.setHorizontallyResizable_(False)
    view.setVerticallyResizable_(True)
    view.setMinSize_((width, 0))
    view.setMaxSize_((width, 10_000_000))
    view.textContainer().setWidthTracksTextView_(False)
    view.textContainer().setContainerSize_((width - 14, 10_000_000))  # minus the container's side padding


def notch_geometry(screen) -> tuple[float, float, float]:
    """(width, height, center x) of the notch on `screen`; (0, 0, center) when it has none."""
    frame, top = screen.frame(), screen.safeAreaInsets().top
    if top <= 0:
        return 0.0, 0.0, frame.origin.x + frame.size.width / 2
    left, right = screen.auxiliaryTopLeftArea(), screen.auxiliaryTopRightArea()
    return right.origin.x - (left.origin.x + left.size.width), top, frame.origin.x + frame.size.width / 2


class Delegate(NSObject):
    # ---- setup -----------------------------------------------------------------------------------
    def applicationDidFinishLaunching_(self, _notification) -> None:
        self.expanded, self.mode, self.item, self.answered = False, "prompt", None, False
        self.queue, self.opened_at, self.ocr_thread, self.offset = [], 0.0, None, 0
        self.cursor_mode, self.anchor = config.ISLAND_MODE == "cursor", (0.0, 0.0)
        self.build_status_item()
        self.build_island()
        self.build_pill()
        self.monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            MASK_LEFT_DOWN | MASK_RIGHT_DOWN, lambda _e: AppHelper.callAfter(self.clickedElsewhere)
        )
        if not hotkey.register(lambda: AppHelper.callAfter(self.hotkeyPressed)):
            print("[island] could not register the Control+Option+Z hotkey", flush=True)
        if self.pill is not None and self.cursor_mode:
            self.pill.orderOut_(None)
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(POLL_SECONDS, self, "tick:", None, True)

    @objc.python_method
    def build_status_item(self) -> None:
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        button = self.status_item.button()
        icon = NSImage.imageWithSystemSymbolName_accessibilityDescription_("sparkles", "hi")
        button.setImage_(icon) if icon is not None else button.setTitle_("hi")
        button.setTarget_(self)
        button.setAction_("statusClicked:")
        button.sendActionOn_(MASK_LEFT_DOWN | MASK_RIGHT_DOWN)

    @objc.python_method
    def build_pill(self) -> None:
        self.pill = None
        rect = self.pill_rect()
        if rect is None:
            return  # no notch: the menu bar icon is the way in
        width, height = rect.size.width - PILL_PAD, rect.size.height
        panel = IslandPanel.alloc().initWithContentRect_styleMask_backing_defer_(rect, 1 << 7, NSBackingStoreBuffered, False)
        panel.setLevel_(26)  # above the menu bar and the island's own level, so the notch stays clickable
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(False)
        panel.setCollectionBehavior_((1 << 0) | (1 << 4) | (1 << 8))  # all Spaces, stationary, full-screen auxiliary
        view = NotchPill.alloc().initWithFrame_(NSMakeRect(0, 0, width + PILL_PAD, height))
        view.opener = self
        view.setWantsLayer_(True)
        view.layer().setBackgroundColor_(Quartz.CGColorCreateGenericGray(0.0, 1.0))
        view.layer().setCornerRadius_(10)
        view.layer().setMaskedCorners_((1 << 0) | (1 << 1))  # the two bottom corners only
        panel.setContentView_(view)
        panel.orderFrontRegardless()
        self.pill = panel

    @objc.python_method
    def pill_rect(self):
        """Where the pill belongs: centered over the notch at the very top of the main screen, or None without a notch."""
        screen = NSScreen.mainScreen()
        width, height, center = notch_geometry(screen)
        if height == 0:
            return None
        frame = screen.frame()
        return NSMakeRect(center - (width + PILL_PAD) / 2, frame.origin.y + frame.size.height - height, width + PILL_PAD, height)

    @objc.python_method
    def keep_pill_placed(self) -> None:
        """macOS can move windows when displays change or wake (the pill once ended up mid-screen): put it back."""
        rect = self.pill_rect()
        if self.pill is None or rect is None or self.cursor_mode or self.expanded:
            return
        current = self.pill.frame()
        if abs(current.origin.x - rect.origin.x) > 1 or abs(current.origin.y - rect.origin.y) > 1 or abs(current.size.width - rect.size.width) > 1:
            self.pill.setFrame_display_(rect, True)
            self.pill.orderFrontRegardless()

    @objc.python_method
    def build_island(self) -> None:
        panel = IslandPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, ISLAND_W, 200), 1 << 7, NSBackingStoreBuffered, False
        )
        panel.setLevel_(25)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua"))  # light text on dark glass
        panel.setCollectionBehavior_((1 << 0) | (1 << 4) | (1 << 8))
        panel.setReleasedWhenClosed_(False)
        glass = NSGlassEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, ISLAND_W, 200))
        glass.setCornerRadius_(CORNER)
        glass.setStyle_(0)  # regular
        glass.setWantsLayer_(True)
        glass.layer().setCornerRadius_(CORNER)  # the glass backdrop must follow the rounded shape too
        glass.layer().setMasksToBounds_(True)
        glass.setTintColor_(NSColor.colorWithWhite_alpha_(0.0, 0.2))
        content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, ISLAND_W, 200))
        content.setWantsLayer_(True)
        content.layer().setCornerRadius_(CORNER)
        content.layer().setMasksToBounds_(True)
        self.fade = CAGradientLayer.layer()  # black at the top (the notch), clear at the bottom
        self.fade.setStartPoint_((0.5, 1.0))
        self.fade.setEndPoint_((0.5, 0.0))
        self.rim = CAShapeLayer.layer()  # the thin light outline
        self.rim.setFillColor_(None)
        self.rim.setStrokeColor_(Quartz.CGColorCreateGenericGray(1.0, RIM_ALPHA))
        self.rim.setLineWidth_(1.0)
        content.layer().insertSublayer_atIndex_(self.fade, 0)
        content.layer().addSublayer_(self.rim)
        glass.setContentView_(content)
        panel.setContentView_(glass)

        self.icon = NSImageView.imageViewWithImage_(NSImage.imageWithSystemSymbolName_accessibilityDescription_("sparkles", "hi"))
        self.icon.setContentTintColor_(NSColor.secondaryLabelColor())
        self.title = NSTextField.wrappingLabelWithString_("")
        self.title.setFont_(NSFont.systemFontOfSize_weight_(13, 0.4))  # semibold
        self.title.setMaximumNumberOfLines_(4)
        self.status = NSTextField.labelWithString_("")
        self.status.setFont_(NSFont.systemFontOfSize_(11))
        self.status.setTextColor_(NSColor.secondaryLabelColor())
        self.close_button = NSButton.buttonWithImage_target_action_(
            NSImage.imageWithSystemSymbolName_accessibilityDescription_("xmark.circle.fill", "close"), self, "closeClicked:"
        )
        self.close_button.setBordered_(False)
        self.close_button.setContentTintColor_(NSColor.tertiaryLabelColor())
        self.field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 10, FIELD_H))
        self.field.setBezelStyle_(1)  # rounded
        self.field.setFont_(NSFont.systemFontOfSize_(13))
        self.field.setFocusRingType_(1)  # none: the glass is the chrome
        self.field.setTarget_(self)
        self.field.setAction_("submit:")
        self.field.setDelegate_(self)
        self.scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.scroll.setHasVerticalScroller_(True)
        self.scroll.setDrawsBackground_(False)
        self.text = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, ISLAND_W - 40, 10))
        self.text.setEditable_(False)
        self.text.setDrawsBackground_(False)
        self.text.setTextColor_(NSColor.labelColor())
        self.text.setFont_(NSFont.systemFontOfSize_(13))
        self.text.setAutoresizingMask_(2)
        self.text.setTextContainerInset_((2, 4))
        wrap_text_view(self.text, ISLAND_W - 40)
        self.scroll.setDocumentView_(self.text)
        self.picture = NSImageView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.picture.setImageScaling_(3)  # proportionally up or down
        self.picture.setHidden_(True)
        self.picture_h = 0.0  # height the current diagram needs, 0 when the answer has none
        for view in (self.icon, self.title, self.status, self.close_button, self.field, self.picture, self.scroll):
            content.addSubview_(view)
        self.panel, self.glass, self.content = panel, glass, content

    # ---- geometry ---------------------------------------------------------------------------------
    @objc.python_method
    def target_rect(self, answer_open: bool):
        """Window rect for the island, top anchored past the screen's top edge, centered on the notch."""
        if self.cursor_mode:
            return self.cursor_rect(answer_open)
        screen = NSScreen.mainScreen()
        _w, notch_h, center = notch_geometry(screen)
        frame = screen.frame()
        top_pad = OVERHANG + (notch_h or 24) + 10  # the menu bar is 24pt on a Mac without a notch
        title_h, status_h, height = self.content_height(top_pad, answer_open)
        top = frame.origin.y + frame.size.height + OVERHANG
        return NSMakeRect(center - ISLAND_W / 2, top - height, ISLAND_W, height), top_pad, title_h, status_h

    @objc.python_method
    def content_height(self, top_pad: float, answer_open: bool) -> tuple[float, float, float]:
        if self.mode == "nudge":  # as tall as the question needs, up to four lines
            wanted = self.title.cell().cellSizeForBounds_(NSMakeRect(0, 0, ISLAND_W - 20 - 44, 10_000)).height
            title_h = min(math.ceil(wanted) + 2, 72)
        else:
            title_h = 20
        status_h = 16 if str(self.status.stringValue()) else 0
        picture = self.picture_h + 10 if answer_open and self.picture_h else 0
        body = title_h + status_h + 8 + FIELD_H + (picture + 10 + ANSWER_H if answer_open else 0) + 16
        return title_h, status_h, top_pad + body

    @objc.python_method
    def cursor_rect(self, answer_open: bool):
        """Cursor mode: hangs just below the pointer position captured when it opened, kept inside that screen."""
        x, y = self.anchor
        screen = next((s for s in NSScreen.screens() if s.frame().origin.x <= x < s.frame().origin.x + s.frame().size.width
                       and s.frame().origin.y <= y <= s.frame().origin.y + s.frame().size.height), NSScreen.mainScreen())
        area = screen.visibleFrame()
        title_h, status_h, height = self.content_height(CURSOR_PAD, answer_open)
        left = min(max(x - ISLAND_W / 2, area.origin.x + EDGE), area.origin.x + area.size.width - ISLAND_W - EDGE)
        top = min(y - CURSOR_GAP, area.origin.y + area.size.height - EDGE)
        bottom = max(top - height, area.origin.y + EDGE)
        return NSMakeRect(left, bottom, ISLAND_W, top - bottom), CURSOR_PAD, title_h, status_h

    @objc.python_method
    def rest_rect(self):
        """Where the island shrinks to and grows from: the pill at the notch, or a dot at the pointer."""
        if self.cursor_mode:
            return NSMakeRect(self.anchor[0] - 20, self.anchor[1] - CURSOR_GAP - 20, 40, 20)
        return (self.pill.frame() if self.pill is not None else self.panel.frame())

    @objc.python_method
    def layout(self, answer_open: bool, animate: bool = True) -> None:
        rect, top_pad, title_h, status_h = self.target_rect(answer_open)
        height, x = rect.size.height, 20

        def from_top(y: float, h: float) -> float:
            return height - y - h

        self.content.setFrame_(NSMakeRect(0, 0, ISLAND_W, height))
        self.icon.setFrame_(NSMakeRect(x, from_top(top_pad, 16) - 1, 16, 16)) if self.mode == "prompt" else self.icon.setFrame_(NSMakeRect(0, 0, 0, 0))
        text_x = x + 24 if self.mode == "prompt" else x
        self.title.setFrame_(NSMakeRect(text_x, from_top(top_pad, title_h), ISLAND_W - text_x - 44, title_h))
        self.close_button.setFrame_(NSMakeRect(ISLAND_W - 20 - 20, from_top(top_pad, 20), 20, 20))
        y = top_pad + title_h
        self.status.setFrame_(NSMakeRect(text_x, from_top(y + 1, status_h), ISLAND_W - text_x - 20, status_h))
        y += status_h + 8
        self.field.setFrame_(NSMakeRect(x, from_top(y, FIELD_H), ISLAND_W - 2 * x, FIELD_H))
        y += FIELD_H + 10
        self.picture.setHidden_(not (answer_open and self.picture_h))
        self.picture.setFrame_(NSMakeRect(x, from_top(y, self.picture_h), ISLAND_W - 2 * x, self.picture_h))
        y += self.picture_h + 10 if self.picture_h else 0
        self.scroll.setFrame_(NSMakeRect(x, from_top(y, ANSWER_H), ISLAND_W - 2 * x, ANSWER_H))
        self.scroll.setHidden_(not answer_open)
        self.scroll.contentView().scrollToPoint_((0, 0))  # a sideways offset from the first, tiny layout clips the text
        self.scroll.reflectScrolledClipView_(self.scroll.contentView())
        self.glass.setFrame_(NSMakeRect(0, 0, ISLAND_W, height))
        self.style_layers(height, top_pad)
        if animate:
            NSAnimationContext.beginGrouping()
            NSAnimationContext.currentContext().setDuration_(ANIMATION_SECONDS)
            self.panel.animator().setFrame_display_(rect, True)
            NSAnimationContext.endGrouping()
        else:
            self.panel.setFrame_display_(rect, True)
        # The shadow is cached from the window's shape: refresh it once the resize settles, or it stays a
        # rectangle with square corners around the rounded island.
        self.panel.invalidateShadow()
        AppHelper.callLater(ANIMATION_SECONDS + 0.05, self.panel.invalidateShadow)

    @objc.python_method
    def style_layers(self, height: float, top_pad: float) -> None:
        """Gradient and rim for the island's current size. No implicit animation: they resize with the panel."""
        if self.cursor_mode:
            solid = 0.0
        else:
            solid = min((OVERHANG + (top_pad - OVERHANG - 10) + BLACK_UNTIL_PAD) / height, 0.9)  # through the notch
        black = lambda alpha: Quartz.CGColorCreateGenericGray(0.0, alpha)  # noqa: E731
        Quartz.CATransaction.begin()
        Quartz.CATransaction.setDisableActions_(True)
        self.fade.setFrame_(((0, 0), (ISLAND_W, height)))
        self.fade.setColors_([black(0.45), black(0.45), black(BOTTOM_ALPHA)] if self.cursor_mode else [black(1.0), black(1.0), black(BOTTOM_ALPHA)])
        self.fade.setLocations_([0.0, solid, 1.0])
        self.rim.setFrame_(((0, 0), (ISLAND_W, height)))
        self.rim.setPath_(Quartz.CGPathCreateWithRoundedRect(((0.5, 0.5), (ISLAND_W - 1, height - 1)), CORNER, CORNER, None))
        Quartz.CATransaction.commit()

    # ---- opening and closing ----------------------------------------------------------------------
    @objc.python_method
    def present(self, mode: str, title: str, status: str, item: dict | None, take_focus: bool) -> None:
        self.mode, self.item, self.answered, self.opened_at = mode, item, False, time.time()
        self.title.setStringValue_(title)
        self.status.setStringValue_(status)
        self.field.setStringValue_("")
        self.text.setString_("")
        self.picture_h = 0.0
        self.picture.setImage_(None)
        self.field.setPlaceholderString_("Reply…" if mode == "nudge" else "Ask about what's on your screen…")
        if not self.expanded:
            if self.cursor_mode:
                mouse = NSEvent.mouseLocation()
                self.anchor = (mouse.x, mouse.y)
            self.content.setAlphaValue_(0.0)
            self.layout(False, animate=False)
            start = self.rest_rect()
            self.panel.setFrame_display_(NSMakeRect(start.origin.x, start.origin.y, start.size.width, start.size.height), False)
            self.panel.orderFrontRegardless()
        self.expanded = True
        self.layout(False)
        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(ANIMATION_SECONDS)
        self.content.animator().setAlphaValue_(1.0)
        NSAnimationContext.endGrouping()
        if take_focus:
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            self.panel.makeKeyAndOrderFront_(None)
            self.panel.makeFirstResponder_(self.field)

    @objc.python_method
    def collapse(self, outcome: str | None = None) -> None:
        if not self.expanded:
            return
        if self.mode == "nudge" and self.item is not None and outcome:
            inbox.log_outcome(self.item, outcome)
        self.expanded, self.item = False, None
        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(ANIMATION_SECONDS)
        self.content.animator().setAlphaValue_(0.0)
        start = self.rest_rect()
        self.panel.animator().setFrame_display_(NSMakeRect(start.origin.x, start.origin.y, start.size.width, start.size.height), True)
        NSAnimationContext.endGrouping()
        AppHelper.callLater(ANIMATION_SECONDS + 0.05, self.finish_collapse)

    @objc.python_method
    def finish_collapse(self) -> None:
        if not self.expanded:
            self.panel.orderOut_(None)
            if self.queue:
                self.showNext()

    @objc.python_method
    def showNext(self) -> None:
        item = self.queue.pop(0)
        self.present("nudge", item["message"], "", item, take_focus=False)  # never steals focus from your typing
        sound = NSSound.soundNamed_("Pop")
        if sound is not None:
            sound.play()

    # ---- actions ----------------------------------------------------------------------------------
    def openPrompt_(self, _sender) -> None:
        if self.expanded and self.mode == "prompt":
            self.collapse()
            return
        if self.expanded:
            self.collapse("dismissed")
        self.ocr_thread = capture_screen()  # BEFORE showing: the island itself must not be in the shot
        status = "Screen captured" if self.ocr_thread else "No screen context (private app or paused)"
        self.present("prompt", "Ask about your screen", status, None, take_focus=True)

    def statusClicked_(self, sender) -> None:
        event = NSApplication.sharedApplication().currentEvent()
        # The button fires on mouse DOWN, so that is the event to look for (a mouse-up never arrives here).
        if event is not None and (event.type() == NSEventTypeRightMouseDown or event.modifierFlags() & CONTROL_FLAG):
            menu = NSMenu.alloc().init()
            follow = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Follow cursor", "toggleCursorMode:", "")
            follow.setTarget_(self)
            follow.setState_(1 if self.cursor_mode else 0)
            menu.addItem_(follow)
            menu.addItemWithTitle_action_keyEquivalent_("Quit hi", "terminate:", "q")
            self.status_item.setMenu_(menu)
            self.status_item.button().performClick_(None)
            self.status_item.setMenu_(None)
            return
        self.openPrompt_(None)

    def toggleCursorMode_(self, _sender) -> None:
        """Switch between hanging from the notch and opening at the mouse pointer; remembered in ~/.hi/.env."""
        if self.expanded:
            self.collapse("answered" if self.answered else "dismissed")
        self.cursor_mode = not self.cursor_mode
        write_env_var("ISLAND_MODE", "cursor" if self.cursor_mode else "notch")
        if self.pill is not None:
            self.pill.orderOut_(None) if self.cursor_mode else self.pill.orderFrontRegardless()

    @objc.python_method
    def hotkeyPressed(self) -> None:
        """Control+Option+Z: open the island at the pointer (in notch mode it opens at the notch as usual)."""
        self.openPrompt_(None)

    def closeClicked_(self, _sender) -> None:
        self.collapse("answered" if self.answered else "dismissed")

    @objc.python_method
    def clickedElsewhere(self) -> None:
        """A click outside closes a prompt (never a nudge you have not looked at yet)."""
        if self.expanded and self.mode == "prompt" and not self.field.currentEditor():
            self.collapse()
        elif self.expanded and self.mode == "prompt" and not str(self.field.stringValue()).strip():
            self.collapse()

    def control_textView_doCommandBySelector_(self, _control, _view, selector) -> bool:
        if str(selector) == "cancelOperation:":  # Esc
            self.collapse("answered" if self.answered else "dismissed")
            return True
        return False

    def submit_(self, _sender) -> None:
        text = str(self.field.stringValue()).strip()
        if not text:
            return
        self.field.setStringValue_("")
        self.text.setString_("…")
        self.answered, self.opened_at = True, time.time()
        self.layout(True)
        if self.mode == "nudge":
            now.PINNED.unlink(missing_ok=True)  # a reply is about the notification, not an earlier capture
            text = f'(You sent me this notification: "{self.item["message"]}")\n{text}'
        threading.Thread(target=self.answer, args=(text,), daemon=True).start()

    @objc.python_method
    def show_picture(self, path: str) -> None:
        """Show a diagram or chart the assistant made (an SVG or PNG) above the answer text."""
        image = NSImage.alloc().initWithContentsOfFile_(path)
        if image is None or image.size().width <= 0:
            return
        width = ISLAND_W - 40
        self.picture.setImage_(image)
        self.picture_h = min(width * image.size().height / image.size().width, MAX_PICTURE_H)
        self.layout(True)

    @objc.python_method
    def answer(self, text: str) -> None:
        from hi.fast_commands import maybe_fast_reply

        shown: list[str] = []

        def append(delta: str) -> None:
            shown.append(delta)
            AppHelper.callAfter(self.text.setString_, "".join(shown))

        try:
            if self.mode == "prompt" and (fast := maybe_fast_reply(text)):  # timers, volume, bluetooth: no model
                AppHelper.callAfter(self.text.setString_, fast[1])
                return
            if self.mode == "prompt" and self.ocr_thread:
                self.ocr_thread.join(timeout=10)  # the pinned screen text must exist before the model reads it
            stream_answer(text, append, lambda s: AppHelper.callAfter(self.status.setStringValue_, s),
                          lambda path: AppHelper.callAfter(self.show_picture, path))
            AppHelper.callAfter(self.status.setStringValue_, "")
        except Exception as e:
            AppHelper.callAfter(self.text.setString_, f"Can't reach hi's backend ({e}). Run `hi` to start it.")

    def applicationWillTerminate_(self, _notification) -> None:
        self.supervisor.stop()  # closing the menu bar app stops everything it started

    def tick_(self, _timer) -> None:
        self.supervisor.check()
        self.keep_pill_placed()
        items, self.offset = inbox.read_from(self.offset)
        self.queue.extend(items)
        if not self.expanded and self.queue:
            self.showNext()
        elif self.expanded and self.mode == "nudge":
            idle = time.time() - self.opened_at
            engaged = self.panel.isKeyWindow() or str(self.field.stringValue()).strip()
            if self.answered and idle > LINGER_AFTER_ANSWER:
                self.collapse("answered")  # an answered nudge lingers a few minutes so it can be read
            elif not self.answered and not engaged and idle > IGNORED_AFTER:
                self.collapse("ignored")
