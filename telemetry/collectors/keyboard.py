from __future__ import annotations

from pynput.keyboard import Key, KeyCode, Listener

from telemetry.config import Config
from telemetry.state import TelemetryState

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


class KeyboardCollector:
    def __init__(self, state: TelemetryState, config: Config) -> None:
        self._state = state
        self._listener: Listener | None = None
        # Labels of keys currently held down. macOS auto-repeats key-down
        # events while a key is held, so a key already in this set is a repeat
        # and must not be counted again.
        self._held_keys: set[str] = set()

    def start(self) -> None:
        if self._listener is not None:
            return
        self._listener = Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

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
