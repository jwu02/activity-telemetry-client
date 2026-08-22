from unittest.mock import MagicMock

from pynput.keyboard import Key, KeyCode

from telemetry.config import Config
from telemetry.collectors.keyboard import KeyboardCollector
from telemetry.state import TelemetryState


def make_config() -> Config:
    return Config(
        mongo_uri="",
        db_name="test",
        collection_name="telemetry",
        flush_interval_seconds=300,
        mouse_dpi=72,
        app_whitelist=set(),
    )


# ---------------------------------------------------------------------------
# Character-producing keys
# ---------------------------------------------------------------------------

def test_printable_character_lowercase_normalised_to_uppercase():
    """Lowercase letters are folded to uppercase so 'a' and 'A' merge."""
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    key = KeyCode.from_char("a")
    collector._on_press(key)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["A"] == 1
    assert snap["keysPressed"] == 1


def test_printable_character_uppercase():
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    key = KeyCode.from_char("A")
    collector._on_press(key)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["A"] == 1


def test_lowercase_and_uppercase_merge():
    """Both 'a' and 'A' increment the same 'A' bucket."""
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    for key in [KeyCode.from_char("a"), KeyCode.from_char("A"), KeyCode.from_char("a")]:
        collector._on_press(key)
        collector._on_release(key)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["A"] == 3
    assert snap["keysPressed"] == 3


def test_printable_character_uk_shifted_symbol():
    """UK Shift+3 produces '£', not the physical keycap label '3'."""
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    key = KeyCode.from_char("£")  # £
    collector._on_press(key)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["£"] == 1


def test_printable_character_option_symbol():
    """Option-modified keys produce their actual symbol, e.g. Option+2 → '€'."""
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    key = KeyCode.from_char("€")  # €
    collector._on_press(key)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["€"] == 1


def test_printable_digit():
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    key = KeyCode.from_char("1")
    collector._on_press(key)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["1"] == 1


def test_printable_shifted_digit():
    """Shift+1 produces '!' on UK layout."""
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    key = KeyCode.from_char("!")
    collector._on_press(key)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["!"] == 1


def test_accumulates_multiple_distinct_presses():
    """Press/release cycles for the same key each count once."""
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    key = KeyCode.from_char("e")
    for _ in range(5):
        collector._on_press(key)
        collector._on_release(key)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["E"] == 5
    assert snap["keysPressed"] == 5


def test_held_key_autorepeat_counts_once():
    """Auto-repeat events while a key is held down are not counted."""
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    key = KeyCode.from_char("e")
    collector._on_press(key)
    collector._on_press(key)  # auto-repeat from holding
    collector._on_press(key)  # auto-repeat from holding
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["E"] == 1
    assert snap["keysPressed"] == 1


def test_held_special_key_counts_once():
    """Holding Delete (backspace) produces many repeats but counts once."""
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    collector._on_press(Key.backspace)
    collector._on_press(Key.backspace)  # auto-repeat
    collector._on_press(Key.backspace)  # auto-repeat
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["Delete"] == 1


def test_release_then_press_counts_again():
    """After a release, pressing the same key again counts again."""
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    key = KeyCode.from_char("a")
    collector._on_press(key)
    collector._on_release(key)
    collector._on_press(key)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["A"] == 2


def test_release_after_modifier_change_clears_held():
    """The held-set uses the counted label, so a release event carrying a
    different KeyCode (e.g. after Shift was released mid-hold) still clears
    the key, and a later press is counted again."""
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    collector._on_press(KeyCode.from_char("A"))    # held with Shift
    collector._on_press(KeyCode.from_char("A"))    # auto-repeat
    collector._on_release(KeyCode.from_char("a"))  # release after Shift up
    collector._on_press(KeyCode.from_char("a"))    # fresh press
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["A"] == 2


# ---------------------------------------------------------------------------
# Special / function keys (Key enum)
# ---------------------------------------------------------------------------

def test_special_key_return():
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    collector._on_press(Key.enter)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["Return"] == 1


def test_special_key_space():
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    collector._on_press(Key.space)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["Space"] == 1


def test_special_key_tab():
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    collector._on_press(Key.tab)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["Tab"] == 1


def test_special_key_escape():
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    collector._on_press(Key.esc)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["Escape"] == 1


def test_special_key_backspace():
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    collector._on_press(Key.backspace)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["Delete"] == 1


def test_special_key_forward_delete():
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    collector._on_press(Key.delete)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["Forward Delete"] == 1


def test_special_key_arrows():
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    for arrow in [Key.up, Key.down, Key.left, Key.right]:
        collector._on_press(arrow)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["Up Arrow"] == 1
    assert snap["keyboard_heatmap"]["Down Arrow"] == 1
    assert snap["keyboard_heatmap"]["Left Arrow"] == 1
    assert snap["keyboard_heatmap"]["Right Arrow"] == 1


def test_special_key_modifiers():
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    # pynput aliases shift_l → shift, ctrl_l → ctrl, etc., so generic
    # and _l forms are the same object.  We test one of each distinct
    # modifier (generic alias covers _l) plus the distinct _r variants.
    for mod in [
        Key.shift, Key.shift_r,
        Key.ctrl, Key.ctrl_r,
        Key.alt, Key.alt_r,
        Key.cmd, Key.cmd_r,
    ]:
        collector._on_press(mod)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["Left Shift"] == 1
    assert snap["keyboard_heatmap"]["Right Shift"] == 1
    assert snap["keyboard_heatmap"]["Left Ctrl"] == 1
    assert snap["keyboard_heatmap"]["Right Ctrl"] == 1
    assert snap["keyboard_heatmap"]["Left Option"] == 1
    assert snap["keyboard_heatmap"]["Right Option"] == 1
    assert snap["keyboard_heatmap"]["Left Cmd"] == 1
    assert snap["keyboard_heatmap"]["Right Cmd"] == 1


def test_special_key_function_keys():
    """F1–F12 are on the M3 MacBook Air keyboard."""
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    for fk in [Key.f1, Key.f2, Key.f3, Key.f4, Key.f5, Key.f6,
               Key.f7, Key.f8, Key.f9, Key.f10, Key.f11, Key.f12]:
        collector._on_press(fk)
    snap = state.snapshot_and_clear()
    for i in range(1, 13):
        assert snap["keyboard_heatmap"][f"F{i}"] == 1


def test_f13_to_f20_ignored():
    """F13–F20 don't exist on the built-in keyboard and are ignored."""
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    for fk in [Key.f13, Key.f14, Key.f15, Key.f16,
               Key.f17, Key.f18, Key.f19, Key.f20]:
        collector._on_press(fk)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"] == {}


def test_special_key_navigation():
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    for nav in [Key.home, Key.end, Key.page_up, Key.page_down]:
        collector._on_press(nav)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["Home"] == 1
    assert snap["keyboard_heatmap"]["End"] == 1
    assert snap["keyboard_heatmap"]["Page Up"] == 1
    assert snap["keyboard_heatmap"]["Page Down"] == 1


def test_special_key_caps_lock():
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    collector._on_press(Key.caps_lock)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["Caps Lock"] == 1


def test_special_key_media():
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    for mk in [Key.media_volume_up, Key.media_volume_down, Key.media_volume_mute]:
        collector._on_press(mk)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"]["Volume Up"] == 1
    assert snap["keyboard_heatmap"]["Volume Down"] == 1
    assert snap["keyboard_heatmap"]["Mute"] == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_unmapped_key_ignored():
    """KeyCode with no char and a vk not in the special-key enum is ignored."""
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    key = KeyCode.from_vk(999)
    collector._on_press(key)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"] == {}


def test_none_key_ignored():
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    collector._on_press(None)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"] == {}


def test_release_unmapped_or_none_key_no_error():
    """Releasing keys we never counted (unmapped/None) is a safe no-op."""
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    collector._on_release(KeyCode.from_vk(999))
    collector._on_release(None)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"] == {}


def test_non_printable_char_ignored():
    """Control characters (e.g. \x01) should be ignored even if char is set."""
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    key = MagicMock()
    key.char = "\x01"
    collector._on_press(key)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"] == {}


def test_char_attribute_is_none():
    """Key with char=None falls through to special-key mapping (and is ignored
    if not in the mapping)."""
    state = TelemetryState()
    collector = KeyboardCollector(state, make_config())
    key = MagicMock()
    key.char = None
    collector._on_press(key)
    snap = state.snapshot_and_clear()
    assert snap["keyboard_heatmap"] == {}


def test_label_for_key_with_none():
    assert KeyboardCollector._label_for_key(None) is None
