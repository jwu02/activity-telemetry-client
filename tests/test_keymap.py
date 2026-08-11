from telemetry.keymap import label_for_keycode, LABEL_FOR_KEYCODE_MACOS

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
