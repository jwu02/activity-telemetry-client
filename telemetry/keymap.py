# Physical key labels for a UK Mac QWERTY keyboard, indexed by macOS virtual keycode.
LABEL_FOR_KEYCODE: dict[int, str] = {
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

def label_for_keycode(code: int) -> str | None:
    return LABEL_FOR_KEYCODE.get(code)
