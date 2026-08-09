from telemetry.state import TelemetryState


def test_click_counters():
    state = TelemetryState()
    state.add_left_click()
    state.add_left_click()
    state.add_right_click()
    snap = state.snapshot_and_clear()
    assert snap["mouse"]["leftClicks"] == 2
    assert snap["mouse"]["rightClicks"] == 1

    next_snap = state.snapshot_and_clear()
    assert next_snap["mouse"]["leftClicks"] == 0


def test_key_and_app_accumulation():
    state = TelemetryState()
    state.add_key_press("A")
    state.add_key_press("A")
    state.add_key_press("Return")
    state.add_app_time("Visual Studio Code", 1.0)
    state.add_app_time("Visual Studio Code", 2.5)
    snap = state.snapshot_and_clear()
    assert snap["keys"]["A"] == 2
    assert snap["keys"]["Return"] == 1
    assert snap["apps"]["Visual Studio Code"] == 3.5


def test_snapshot_does_not_clear():
    state = TelemetryState()
    state.add_left_click()
    snap1 = state.snapshot()
    snap2 = state.snapshot()
    assert snap1["mouse"]["leftClicks"] == 1
    assert snap2["mouse"]["leftClicks"] == 1
    state.clear()
    assert state.snapshot()["mouse"]["leftClicks"] == 0


def test_clear_empties_state():
    state = TelemetryState()
    state.add_key_press("A")
    state.add_app_time("Google Chrome", 2.0)
    state.clear()
    snap = state.snapshot()
    assert snap["keys"] == {}
    assert snap["apps"] == {}


def test_key_counts_are_sorted_to_prevent_leaking_insertion_order():
    state = TelemetryState()
    # Add keys in a non-alphabetical order.
    state.add_key_press("Z")
    state.add_key_press("A")
    state.add_key_press("M")
    snap = state.snapshot()
    assert list(snap["keys"].keys()) == ["A", "M", "Z"]


def test_has_activity_reports_keyboard_or_mouse_only():
    state = TelemetryState()
    assert not state.has_activity()

    state.add_left_click()
    assert state.has_activity()
    state.clear()

    state.add_right_click()
    assert state.has_activity()
    state.clear()

    state.add_mouse_movement(0.001)
    assert state.has_activity()
    state.clear()

    state.add_key_press("A")
    assert state.has_activity()
    state.clear()

    # App time alone does not count as activity.
    state.add_app_time("Visual Studio Code", 1.0)
    assert not state.has_activity()
