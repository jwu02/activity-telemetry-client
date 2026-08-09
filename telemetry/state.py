from __future__ import annotations

import threading
from typing import Any


class TelemetryState:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._left_clicks = 0
        self._right_clicks = 0
        self._mouse_meters = 0.0
        self._keys: dict[str, int] = {}
        self._apps: dict[str, float] = {}

    def add_left_click(self) -> None:
        with self._lock:
            self._left_clicks += 1

    def add_right_click(self) -> None:
        with self._lock:
            self._right_clicks += 1

    def add_mouse_movement(self, meters: float) -> None:
        with self._lock:
            self._mouse_meters += meters

    def add_key_press(self, label: str) -> None:
        with self._lock:
            self._keys[label] = self._keys.get(label, 0) + 1

    def add_app_time(self, app_name: str, seconds: float) -> None:
        with self._lock:
            self._apps[app_name] = self._apps.get(app_name, 0.0) + seconds

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "mouse": {
                    "leftClicks": self._left_clicks,
                    "rightClicks": self._right_clicks,
                    "movementMeters": round(self._mouse_meters, 4),
                },
                # Sort key counts alphabetically so insertion order does not
                # leak information about keystroke sequences.
                "keys": dict(sorted(self._keys.items())),
                "apps": dict(self._apps),
            }

    def has_activity(self) -> bool:
        with self._lock:
            return (
                self._left_clicks > 0
                or self._right_clicks > 0
                or self._mouse_meters > 0.0
                or bool(self._keys)
            )

    def clear(self) -> None:
        with self._lock:
            self._left_clicks = 0
            self._right_clicks = 0
            self._mouse_meters = 0.0
            self._keys.clear()
            self._apps.clear()

    def snapshot_and_clear(self) -> dict[str, Any]:
        with self._lock:
            snapshot = self.snapshot()
            self.clear()
            return snapshot
