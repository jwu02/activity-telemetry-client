from __future__ import annotations

import math

from pynput import mouse

from telemetry.config import Config
from telemetry.state import TelemetryState

METERS_PER_INCH = 0.0254


def pixels_to_meters(pixels: float, dpi: int) -> float:
    return pixels * (METERS_PER_INCH / dpi)


class MouseCollector:
    def __init__(self, state: TelemetryState, config: Config) -> None:
        self._state = state
        self._config = config
        self._listener: mouse.Listener | None = None
        self._last_position: tuple[int, int] | None = None

    def start(self) -> None:
        if self._listener is not None:
            return
        self._listener = mouse.Listener(
            on_click=self._on_click,
            on_move=self._on_move,
        )
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def _on_click(self, x: int, y: int, button: mouse.Button, pressed: bool) -> None:
        if not pressed:
            return
        if button == mouse.Button.left:
            self._state.add_left_click()
        elif button == mouse.Button.right:
            self._state.add_right_click()

    def _on_move(self, x: int, y: int) -> None:
        if self._last_position is not None:
            last_x, last_y = self._last_position
            distance_px = math.hypot(x - last_x, y - last_y)
            distance_m = pixels_to_meters(distance_px, self._config.mouse_dpi)
            self._state.add_mouse_movement(distance_m)
        self._last_position = (x, y)
