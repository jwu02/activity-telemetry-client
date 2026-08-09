from __future__ import annotations

from pynput import keyboard

from telemetry.config import Config
from telemetry.keymap import label_for_keycode
from telemetry.state import TelemetryState


def _keycode_for(key) -> int | None:
    if hasattr(key, "vk") and key.vk is not None:
        return key.vk
    if hasattr(key, "value") and hasattr(key.value, "vk") and key.value.vk is not None:
        return key.value.vk
    return None


class KeyboardCollector:
    def __init__(self, state: TelemetryState, config: Config) -> None:
        self._state = state
        self._listener: keyboard.Listener | None = None

    def start(self) -> None:
        if self._listener is not None:
            return
        self._listener = keyboard.Listener(on_press=self._on_press)
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def _on_press(self, key) -> None:
        code = _keycode_for(key)
        if code is None:
            return
        label = label_for_keycode(code)
        if label is None:
            return
        self._state.add_key_press(label)
