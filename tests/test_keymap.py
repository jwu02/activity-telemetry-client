from telemetry.keymap import label_for_keycode, LABEL_FOR_KEYCODE_MACOS, LABEL_FOR_KEYCODE_WINDOWS

def test_known_letters():
    assert label_for_keycode(0) == "A"
    assert label_for_keycode(1) == "S"
    assert label_for_keycode(12) == "Q"
    assert label_for_keycode(37) == "L"

def test_known_modifiers():
    assert label_for_keycode(49) == "Space"
    assert label_for_keycode(36) == "Return"
    assert label_for_keycode(56) == "Left Shift"
    assert label_for_keycode(55) == "Left Cmd"

def test_unknown_keycode():
    assert label_for_keycode(999) is None

def test_all_labels_are_strings():
    for code, label in LABEL_FOR_KEYCODE_MACOS.items():
        assert isinstance(code, int)
        assert isinstance(label, str)

from unittest.mock import patch

# label_for_keycode dispatches on platform.system(), so Windows-VK lookups
# must run under a patched "Windows" platform (tests run on macOS too).


def _windows_label(code: int) -> str | None:
    with patch("telemetry.keymap.platform.system", return_value="Windows"):
        return label_for_keycode(code)


def test_windows_keycode_letters():
    assert _windows_label(0x41) == "A"
    assert _windows_label(0x5A) == "Z"
    assert _windows_label(0x4D) == "M"


def test_windows_keycode_numbers():
    assert _windows_label(0x30) == "0"
    assert _windows_label(0x35) == "5"
    assert _windows_label(0x39) == "9"


def test_windows_keycode_modifiers():
    assert _windows_label(0xA0) == "Left Shift"
    assert _windows_label(0xA1) == "Right Shift"
    assert _windows_label(0xA2) == "Left Ctrl"
    assert _windows_label(0xA4) == "Left Option"
    assert _windows_label(0x5B) == "Left Cmd"
    assert _windows_label(0x5C) == "Right Cmd"


def test_windows_keycode_navigation():
    assert _windows_label(0x25) == "Left Arrow"
    assert _windows_label(0x26) == "Up Arrow"
    assert _windows_label(0x27) == "Right Arrow"
    assert _windows_label(0x28) == "Down Arrow"
    assert _windows_label(0x21) == "Page Up"
    assert _windows_label(0x22) == "Page Down"
    assert _windows_label(0x23) == "End"
    assert _windows_label(0x24) == "Home"
    assert _windows_label(0x2E) == "Forward Delete"


def test_windows_keycode_function_keys():
    assert _windows_label(0x70) == "F1"
    assert _windows_label(0x7B) == "F12"
    assert _windows_label(0x83) == "F20"


def test_windows_keycode_punctuation():
    assert _windows_label(0xC0) == "Section"
    assert _windows_label(0xBB) == "Equal"
    assert _windows_label(0xBD) == "Minus"
    assert _windows_label(0xDB) == "Left Bracket"
    assert _windows_label(0xDD) == "Right Bracket"
    assert _windows_label(0xBA) == "Semicolon"
    assert _windows_label(0xDE) == "Quote"
    assert _windows_label(0xDC) == "Backslash"
    assert _windows_label(0xBC) == "Comma"
    assert _windows_label(0xBE) == "Period"
    assert _windows_label(0xBF) == "Slash"


def test_windows_keycode_special():
    assert _windows_label(0x0D) == "Return"
    assert _windows_label(0x09) == "Tab"
    assert _windows_label(0x20) == "Space"
    assert _windows_label(0x08) == "Delete"
    assert _windows_label(0x1B) == "Escape"
    assert _windows_label(0x14) == "Caps Lock"


def test_windows_keycode_keypad():
    assert _windows_label(0x60) == "Keypad 0"
    assert _windows_label(0x69) == "Keypad 9"
    assert _windows_label(0x6A) == "Keypad *"
    assert _windows_label(0x6B) == "Keypad +"
    assert _windows_label(0x6D) == "Keypad -"
    assert _windows_label(0x6E) == "Keypad ."
    assert _windows_label(0x6F) == "Keypad /"


def test_windows_keycode_media():
    assert _windows_label(0xAD) == "Mute"
    assert _windows_label(0xAE) == "Volume Down"
    assert _windows_label(0xAF) == "Volume Up"


def test_windows_unknown_keycode_returns_none():
    assert _windows_label(0x2C) is None   # Print Screen — excluded
    assert _windows_label(0x91) is None   # Scroll Lock — excluded
    assert _windows_label(0x13) is None   # Pause — excluded
    assert _windows_label(0x2D) is None   # Insert — excluded
    assert _windows_label(0x5D) is None   # Context Menu — excluded
    assert _windows_label(999) is None    # Bogus code


def test_windows_keycode_dispatch():
    """label_for_keycode dispatches on platform.system()."""
    with patch("telemetry.keymap.platform.system", return_value="Windows"):
        assert label_for_keycode(0x41) == "A"
        assert label_for_keycode(0x0D) == "Return"
        assert label_for_keycode(0x5B) == "Left Cmd"

    with patch("telemetry.keymap.platform.system", return_value="Darwin"):
        assert label_for_keycode(0) == "A"        # macOS VK for A
        assert label_for_keycode(36) == "Return"   # macOS VK for Return


def test_windows_all_labels_are_strings():
    for code, label in LABEL_FOR_KEYCODE_WINDOWS.items():
        assert isinstance(code, int)
        assert isinstance(label, str)
