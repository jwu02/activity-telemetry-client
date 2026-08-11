from __future__ import annotations

import platform

# Physical key labels for a UK Mac QWERTY keyboard, indexed by macOS virtual keycode.
LABEL_FOR_KEYCODE_MACOS: dict[int, str] = {
    # Letters
    0: "A", 1: "S", 2: "D", 3: "F", 4: "H", 5: "G", 6: "Z", 7: "X",
    8: "C", 9: "V", 11: "B", 12: "Q", 13: "W", 14: "E", 15: "R",
    16: "Y", 17: "T",
    # Numbers
    18: "1", 19: "2", 20: "3", 21: "4", 22: "6", 23: "5",
    25: "9", 26: "7", 28: "8", 29: "0",
    # Punctuation / symbols
    10: "Section", 24: "Equal", 27: "Minus", 30: "Right Bracket",
    31: "O", 32: "U", 33: "Left Bracket", 34: "I", 35: "P",
    37: "L", 38: "J", 39: "Quote", 40: "K", 41: "Semicolon",
    42: "Backslash", 43: "Comma", 44: "Slash", 45: "N", 46: "M",
    47: "Period", 50: "Grave",
    # Modifiers / editing
    36: "Return", 48: "Tab", 49: "Space", 51: "Delete", 53: "Escape",
    54: "Right Cmd", 55: "Left Cmd", 56: "Left Shift", 57: "Caps Lock",
    58: "Left Option", 59: "Left Ctrl", 60: "Right Shift",
    61: "Right Option", 62: "Right Ctrl", 63: "Fn",
    # Function keys
    64: "F17", 79: "F18", 80: "F19", 90: "F20", 96: "F5", 97: "F6",
    98: "F7", 99: "F3", 100: "F8", 101: "F9", 103: "F11", 105: "F13",
    106: "F16", 107: "F14", 109: "F10", 111: "F12", 113: "F15",
    118: "F4", 120: "F2", 122: "F1",
    # Navigation
    114: "Help", 115: "Home", 116: "Page Up", 117: "Forward Delete",
    119: "End", 121: "Page Down", 123: "Left Arrow", 124: "Right Arrow",
    125: "Down Arrow", 126: "Up Arrow",
    # Keypad
    65: "Keypad .", 67: "Keypad *", 69: "Keypad +", 71: "Keypad Clear",
    75: "Keypad /", 76: "Keypad Enter", 78: "Keypad -", 81: "Keypad =",
    82: "Keypad 0", 83: "Keypad 1", 84: "Keypad 2", 85: "Keypad 3",
    86: "Keypad 4", 87: "Keypad 5", 88: "Keypad 6", 89: "Keypad 7",
    91: "Keypad 8", 92: "Keypad 9",
    # Media
    72: "Volume Up", 73: "Volume Down", 74: "Mute",
    # Misc
    52: "Numpad Enter",
}

# Physical key labels for a UK Mac QWERTY keyboard, indexed by Windows virtual keycode.
# Only keys that physically exist on the M3 Air 13" UK keyboard are included.
LABEL_FOR_KEYCODE_WINDOWS: dict[int, str] = {
    # Letters
    0x41: "A", 0x42: "B", 0x43: "C", 0x44: "D", 0x45: "E",
    0x46: "F", 0x47: "G", 0x48: "H", 0x49: "I", 0x4A: "J",
    0x4B: "K", 0x4C: "L", 0x4D: "M", 0x4E: "N", 0x4F: "O",
    0x50: "P", 0x51: "Q", 0x52: "R", 0x53: "S", 0x54: "T",
    0x55: "U", 0x56: "V", 0x57: "W", 0x58: "X", 0x59: "Y",
    0x5A: "Z",
    # Numbers
    0x30: "0", 0x31: "1", 0x32: "2", 0x33: "3", 0x34: "4",
    0x35: "5", 0x36: "6", 0x37: "7", 0x38: "8", 0x39: "9",
    # Modifiers
    0xA0: "Left Shift", 0xA1: "Right Shift",
    0xA2: "Left Ctrl", 0xA3: "Right Ctrl",
    0xA4: "Left Option", 0xA5: "Right Option",
    0x5B: "Left Cmd", 0x5C: "Right Cmd",
    # Navigation
    0x25: "Left Arrow", 0x26: "Up Arrow", 0x27: "Right Arrow", 0x28: "Down Arrow",
    0x21: "Page Up", 0x22: "Page Down", 0x23: "End", 0x24: "Home",
    0x2E: "Forward Delete",
    # Function keys
    0x70: "F1", 0x71: "F2", 0x72: "F3", 0x73: "F4",
    0x74: "F5", 0x75: "F6", 0x76: "F7", 0x77: "F8",
    0x78: "F9", 0x79: "F10", 0x7A: "F11", 0x7B: "F12",
    0x7C: "F13", 0x7D: "F14", 0x7E: "F15", 0x7F: "F16",
    0x80: "F17", 0x81: "F18", 0x82: "F19", 0x83: "F20",
    # Punctuation (UK Mac physical labels at each VK position)
    0xC0: "Section",   # key left of 1 — US: `/~, UK PC: `/¬, UK Mac: §/±
    0xBB: "Equal",
    0xBD: "Minus",
    0xDB: "Left Bracket",
    0xDD: "Right Bracket",
    0xBA: "Semicolon",
    0xDE: "Quote",
    0xDC: "Backslash",
    0xBC: "Comma",
    0xBE: "Period",
    0xBF: "Slash",
    # Special
    0x0D: "Return",
    0x09: "Tab",
    0x20: "Space",
    0x08: "Delete",    # Backspace on Windows → Delete on Mac
    0x1B: "Escape",
    0x14: "Caps Lock",
    # Keypad (from external keyboards; M3 Air has no numpad but macOS
    # mapping includes these for consistency)
    0x60: "Keypad 0", 0x61: "Keypad 1", 0x62: "Keypad 2",
    0x63: "Keypad 3", 0x64: "Keypad 4", 0x65: "Keypad 5",
    0x66: "Keypad 6", 0x67: "Keypad 7", 0x68: "Keypad 8",
    0x69: "Keypad 9",
    0x6A: "Keypad *", 0x6B: "Keypad +",
    0x6D: "Keypad -", 0x6E: "Keypad .", 0x6F: "Keypad /",
    # Media
    0xAD: "Mute", 0xAE: "Volume Down", 0xAF: "Volume Up",
}


def label_for_keycode(code: int) -> str | None:
    if platform.system() == "Windows":
        return LABEL_FOR_KEYCODE_WINDOWS.get(code)
    return LABEL_FOR_KEYCODE_MACOS.get(code)
