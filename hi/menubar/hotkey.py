"""A system-wide hotkey through Carbon's RegisterEventHotKey: unlike an NSEvent global monitor it needs no
Input Monitoring or Accessibility permission, and it swallows the key combo so the app in front doesn't see it."""

from __future__ import annotations

import ctypes
import ctypes.util
from typing import Callable

CARBON = "/System/Library/Frameworks/Carbon.framework/Carbon"
K_EVENT_CLASS_KEYBOARD, K_EVENT_HOTKEY_PRESSED = 0x6B657962, 5  # 'keyb', pressed
CONTROL_KEY, OPTION_KEY = 1 << 12, 1 << 11
Z = 6  # kVK_ANSI_Z


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class _HotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_keep: list = []  # the callback must outlive this function or Carbon calls freed memory


def register(callback: Callable[[], None], key_code: int = Z, modifiers: int = CONTROL_KEY | OPTION_KEY) -> bool:
    """Call `callback` on the main thread's run loop whenever the combo is pressed. False if it can't be registered."""
    carbon = ctypes.CDLL(CARBON)
    carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
    target = carbon.GetApplicationEventTarget()

    def on_press(_call_ref, _event, _data) -> int:
        callback()
        return 0

    handler = _HANDLER(on_press)
    spec = _EventTypeSpec(K_EVENT_CLASS_KEYBOARD, K_EVENT_HOTKEY_PRESSED)
    carbon.InstallEventHandler.argtypes = [ctypes.c_void_p, _HANDLER, ctypes.c_uint32, ctypes.POINTER(_EventTypeSpec), ctypes.c_void_p, ctypes.c_void_p]
    if carbon.InstallEventHandler(target, handler, 1, ctypes.byref(spec), None, None) != 0:
        return False
    ref = ctypes.c_void_p()
    carbon.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, _HotKeyID, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    status = carbon.RegisterEventHotKey(key_code, modifiers, _HotKeyID(0x68696869, 1), target, 0, ctypes.byref(ref))
    _keep.extend([handler, ref])
    return status == 0
