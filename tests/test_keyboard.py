from unittest.mock import MagicMock, patch
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
    assert snap["keyboard_heatmap"]["A"] == 1

def test_unmapped_key_is_ignored():
    state = TelemetryState()
    cfg = make_config()
    collector = KeyboardCollector(state, cfg)
    key = MagicMock()
    key.vk = 999
    collector._on_press(key)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"] == {}


# KeyboardCollector._on_press resolves labels through label_for_keycode(),
# which dispatches on platform.system(). Windows-VK tests must run under a
# patched "Windows" platform (tests run on macOS too).


def _press_windows_vk(collector, vk, via_value=False):
    key = MagicMock()
    if via_value:
        del key.vk  # No direct vk attribute
        key.value = MagicMock()
        key.value.vk = vk
    else:
        key.vk = vk
    with patch("telemetry.keymap.platform.system", return_value="Windows"):
        collector._on_press(key)


def test_keycode_extraction_from_windows_vk():
    """KeyboardCollector maps Windows-range VK codes through the keymap."""
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    _press_windows_vk(collector, 0x41)  # Windows VK for "A"
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["A"] == 1


def test_windows_modifier_vk():
    """Windows modifier VKs map to UK Mac label names."""
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    _press_windows_vk(collector, 0x5B)  # Left Win → Left Cmd
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["Left Cmd"] == 1


def test_windows_unmapped_key_is_ignored():
    """Windows-only keys (Print Screen, Scroll Lock, etc.) are ignored."""
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    _press_windows_vk(collector, 0x2C)  # Print Screen — excluded from Windows dict
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"] == {}


def test_windows_keycode_extraction_from_value_vk():
    """On Windows pynput, the VK may be at key.value.vk."""
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    _press_windows_vk(collector, 0x0D, via_value=True)  # Return
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["Return"] == 1
