from pynput.mouse import Button

from telemetry.config import Config
from telemetry.state import TelemetryState
from telemetry.collectors.mouse import MouseCollector, pixels_to_meters


def make_config(dpi: int = 72) -> Config:
    return Config(
        mongo_uri="",
        db_name="test",
        collection_name="telemetry",
        flush_interval_seconds=300,
        mouse_dpi=dpi,
        app_whitelist=set(),
    )


def test_pixels_to_meters_at_72_dpi():
    # 72 pixels = 1 inch = 0.0254 meters
    assert abs(pixels_to_meters(72, 72) - 0.0254) < 1e-9


def test_click_callbacks_update_state():
    state = TelemetryState()
    cfg = make_config()
    collector = MouseCollector(state, cfg)
    collector._on_click(0, 0, Button.left, True)
    collector._on_click(0, 0, Button.left, True)
    collector._on_click(0, 0, Button.right, True)
    snap = state.snapshot_and_clear()
    assert snap["leftClicks"] == 2
    assert snap["rightClicks"] == 1


def test_move_callback_tracks_distance():
    state = TelemetryState()
    cfg = make_config(dpi=72)
    collector = MouseCollector(state, cfg)
    collector._on_move(0, 0)
    collector._on_move(72, 0)
    snap = state.snapshot_and_clear()
    assert abs(snap["movementMeters"] - 0.0254) < 1e-6
