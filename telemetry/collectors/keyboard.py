from __future__ import annotations

import logging
import sys
import threading

from pynput.keyboard import Key, KeyCode, Listener

from telemetry.config import Config
from telemetry.state import TelemetryState

# macOS fn/globe key (keycode 0x3F). pynput has no Key.fn on macOS, and the
# key is delivered to an event tap as kCGEventFlagsChanged (never a keyDown),
# so pynput only reports releases. _FnGlobeWatcher watches the flags directly.
_FN_KEYCODE = 0x3F  # kVK_Function
# Flag bit macOS sets in the event flags while the fn key is held. Measured
# with a raw Quartz tap: press = 0x00800100, release = 0x00000100. This bit is
# not a documented public constant; if a future macOS moves it, update here.
_FN_FLAG = 0x00800000
_FN_LABEL = "Fn"

if sys.platform == "darwin":
    try:
        from Quartz import (  # noqa: F401
            CFMachPortCreateRunLoopSource,
            CFRunLoopAddSource,
            CFRunLoopGetCurrent,
            CFRunLoopRun,
            CFRunLoopStop,
            CGEventGetFlags,
            CGEventGetIntegerValueField,
            CGEventMaskBit,
            CGEventTapCreate,
            CGEventTapEnable,
            kCFAllocatorDefault,
            kCFRunLoopCommonModes,
            kCGEventFlagsChanged,
            kCGEventTapOptionListenOnly,
            kCGHIDEventTap,
            kCGHeadInsertEventTap,
            kCGKeyboardEventKeycode,
        )
    except ImportError:  # Quartz unavailable: fn/globe watcher is a no-op
        _HAVE_QUARTZ = False
    else:
        _HAVE_QUARTZ = True
else:
    _HAVE_QUARTZ = False

logger = logging.getLogger(__name__)

# Mapping from pynput Key enum to human-readable labels for non-character keys.
_SPECIAL_KEY_LABELS: dict[Key, str] = {
    # Editing
    Key.enter: "Return",
    Key.space: "Space",
    Key.tab: "Tab",
    Key.esc: "Escape",
    Key.backspace: "Delete",
    Key.delete: "Forward Delete",
    # Modifiers
    # pynput aliases Key.shift_l → Key.shift, Key.ctrl_l → Key.ctrl, etc.,
    # so the _l variants are listed first and the _r variants are distinct.
    Key.shift: "Left Shift",
    Key.shift_r: "Right Shift",
    Key.ctrl: "Left Ctrl",
    Key.ctrl_r: "Right Ctrl",
    Key.alt: "Left Option",
    Key.alt_r: "Right Option",
    Key.cmd: "Left Cmd",
    Key.cmd_r: "Right Cmd",
    # Navigation
    Key.up: "Up Arrow",
    Key.down: "Down Arrow",
    Key.left: "Left Arrow",
    Key.right: "Right Arrow",
    Key.home: "Home",
    Key.end: "End",
    Key.page_up: "Page Up",
    Key.page_down: "Page Down",
    # Lock
    Key.caps_lock: "Caps Lock",
    # Function keys (M3 MacBook Air has F1–F12 only)
    Key.f1: "F1", Key.f2: "F2", Key.f3: "F3", Key.f4: "F4",
    Key.f5: "F5", Key.f6: "F6", Key.f7: "F7", Key.f8: "F8",
    Key.f9: "F9", Key.f10: "F10", Key.f11: "F11", Key.f12: "F12",
    # Media
    Key.media_volume_up: "Volume Up",
    Key.media_volume_down: "Volume Down",
    Key.media_volume_mute: "Mute",
}


class _FnGlobeWatcher:
    """Detects the macOS fn/globe key, which pynput cannot report.

    The fn key is delivered to an event tap as ``kCGEventFlagsChanged`` with
    keycode 63; the macOS fn flag bit is set while the key is held. A
    listen-only HID event tap watches those events and counts one press per
    press/release cycle. On non-macOS (or without Quartz) ``start()`` is a
    no-op.
    """

    def __init__(self, state: TelemetryState) -> None:
        self._state = state
        self._fn_down = False
        self._thread: threading.Thread | None = None
        self._runloop = None
        self._ready = threading.Event()

    def start(self) -> None:
        if not _HAVE_QUARTZ or self._thread is not None:
            return
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run, name="fn-globe-watcher", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        # Give the tap thread a moment to start its run loop so the stop
        # takes effect instead of being dropped on a not-yet-running loop.
        self._ready.wait(timeout=1.0)
        if self._runloop is not None:
            CFRunLoopStop(self._runloop)
        thread.join(timeout=2.0)
        self._thread = None
        self._runloop = None

    def _run(self) -> None:
        # No autorelease pool needed here: like pynput's own listener, the
        # Quartz event tap callback manages its own autoreleased objects, and
        # a manual pool would be released twice (pyobjc also releases it on
        # GC), crashing with a double-release error.
        tap = CGEventTapCreate(
            kCGHIDEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionListenOnly,
            CGEventMaskBit(kCGEventFlagsChanged),
            self._on_quartz_event,
            None,
        )
        if tap is None:
            # Missing Accessibility permission. The keyboard listener already
            # requires it, so this only guards against a late denial.
            logger.warning(
                "fn/globe key watcher could not create an event tap "
                "(Accessibility permission missing); fn presses will not be tracked"
            )
            return
        source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0)
        self._runloop = CFRunLoopGetCurrent()
        CFRunLoopAddSource(self._runloop, source, kCFRunLoopCommonModes)
        CGEventTapEnable(tap, True)
        self._ready.set()
        CFRunLoopRun()
        CGEventTapEnable(tap, False)

    def _on_quartz_event(self, _proxy, _event_type, event, _refcon):
        keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
        flags = CGEventGetFlags(event)
        self._handle_flags(keycode, flags)
        return event

    def _handle_flags(self, keycode: int, flags: int) -> None:
        if keycode != _FN_KEYCODE:
            return
        fn_down = bool(flags & _FN_FLAG)
        if fn_down and not self._fn_down:
            self._state.add_key_press(_FN_LABEL)
        self._fn_down = fn_down


class KeyboardCollector:
    def __init__(self, state: TelemetryState, config: Config) -> None:
        self._state = state
        self._listener: Listener | None = None
        # Labels of keys currently held down. macOS auto-repeats key-down
        # events while a key is held, so a key already in this set is a repeat
        # and must not be counted again.
        self._held_keys: set[str] = set()
        self._fn_globe = _FnGlobeWatcher(state)

    def start(self) -> None:
        if self._listener is not None:
            return
        self._listener = Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.start()
        self._fn_globe.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        self._fn_globe.stop()

    def _on_press(self, key: Key | KeyCode | None) -> None:
        label = self._label_for_key(key)
        if label is None:
            return
        if label in self._held_keys:
            # Auto-repeat from holding the key down; don't count it again.
            return
        self._held_keys.add(label)
        self._state.add_key_press(label)

    def _on_release(self, key: Key | KeyCode | None) -> None:
        label = self._label_for_key(key)
        if label is not None:
            self._held_keys.discard(label)

    @staticmethod
    def _label_for_key(key: Key | KeyCode | None) -> str | None:
        if key is None:
            return None

        # Printable characters: use the resolved character value,
        # normalising letters to uppercase so that 'a' and 'A' are
        # merged into a single bucket.
        # On macOS with pynput this respects the active keyboard layout
        # and modifier state (Shift, Option, etc.).
        char = getattr(key, "char", None)
        if isinstance(char, str) and char and char.isprintable():
            return char.upper()

        # Special / function keys: map from the Key enum.
        if isinstance(key, Key):
            return _SPECIAL_KEY_LABELS.get(key)

        # KeyCode with no printable character (e.g. keypad keys on some
        # platforms, or unmapped keys).  Ignore these.
        return None
