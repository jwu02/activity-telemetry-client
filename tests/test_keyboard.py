from unittest.mock import MagicMock
from telemetry.state import TelemetryState
from telemetry.config import Config
from telemetry.collectors.keyboard import KeyboardCollector

def make_config() -> Config:
    return Config(
        mongo_uri="",
        db_name="test",
        collection_name="telemetry",
        flush_interval_seconds=300,
        mouse_dpi=72,
        app_whitelist=set(),
    )

def test_keycode_extraction_from_vk():
    state = TelemetryState()
    cfg = make_config()
    collector = KeyboardCollector(state, cfg)
    key = MagicMock()
    key.vk = 0  # "A"
    collector._on_press(key)
    snap = state.snapshot_and_clear()
    assert snap["keys"]["A"] == 1

def test_unmapped_key_is_ignored():
    state = TelemetryState()
    cfg = make_config()
    collector = KeyboardCollector(state, cfg)
    key = MagicMock()
    key.vk = 999
    collector._on_press(key)
    snap = state.snapshot_and_clear()
    assert snap["keys"] == {}
