# Cross-Platform Windows Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Windows support to the activity telemetry client for keyboard, mouse, permissions, and app collection, producing UK Mac physical key labels regardless of OS.

**Architecture:** Single-file platform dispatch — `keymap.py` and `apps.py` each contain both macOS and Windows implementations in the same file, dispatching on `platform.system()`. No new modules, no extra pip dependencies (ctypes + Win32 for the app collector).

**Tech Stack:** Python 3.x, pynput (already cross-platform), ctypes (stdlib, for Windows app collector), AppKit/Foundation (macOS-only app collector path, unchanged), pymongo (unchanged)

## Global Constraints

- Key labels: UK Mac physical labels only (e.g. "Left Option", "Left Cmd"). Windows keys without a Mac equivalent on the M3 Air 13" UK keyboard are excluded.
- Windows app collector MUST use `ctypes` + Win32 — no `pywin32` dependency.
- All tests remain mock-based and runnable on any platform (macOS or Linux CI).
- App collector remains unwired from `main.py`.
- No Linux keymap or app collector path.

---

### Task 1: Keymap — add Windows VK dict and platform dispatch

**Files:**
- Modify: `telemetry/keymap.py`

**Interfaces:**
- Produces: `LABEL_FOR_KEYCODE_MACOS: dict[int, str]` (renamed from `LABEL_FOR_KEYCODE`), `LABEL_FOR_KEYCODE_WINDOWS: dict[int, str]`, `label_for_keycode(code: int) -> str | None` (platform-dispatching)

- [ ] **Step 1: Rename current dict and add platform dispatch to `label_for_keycode()`**

```python
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
```

- [ ] **Step 2: Update test_keymap.py import to use renamed dict**

In `tests/test_keymap.py`, change the import line from:
```python
from telemetry.keymap import label_for_keycode, LABEL_FOR_KEYCODE
```
To:
```python
from telemetry.keymap import label_for_keycode, LABEL_FOR_KEYCODE_MACOS
```

And change every `LABEL_FOR_KEYCODE` reference in test bodies to `LABEL_FOR_KEYCODE_MACOS` (one occurrence in `test_all_labels_are_strings`).

- [ ] **Step 3: Run existing tests to verify nothing broke**

Run: `python -m pytest tests/test_keymap.py tests/test_keyboard.py -v`
Expected: All existing tests PASS.

- [ ] **Step 4: Commit**

```bash
git add telemetry/keymap.py tests/test_keymap.py
git commit -m "feat: add Windows keycode mapping with platform dispatch"
```

---

### Task 2: App collector — add Windows ctypes path

**Files:**
- Modify: `telemetry/collectors/apps.py`

**Interfaces:**
- Consumes: `platform.system()` for dispatch
- Produces: `PROCESS_NAME_TO_APP_NAME: dict[str, str]`, `AppCollector._frontmost_app_name()` (platform-dispatched via `_IS_DARWIN` flag)
- Existing public API unchanged: `AppCollector(state, config, poll_interval, shutdown_event)`, `.start()`, `.stop()`, `._record()`, `._run()`, `._frontmost_app_name()`

- [ ] **Step 1: Restructure imports for cross-platform safety**

Replace the top-level AppKit/Foundation imports with a conditional block. The file currently has:

```python
from AppKit import NSWorkspace
from Foundation import NSAutoreleasePool
```

Replace with:

```python
import ctypes
import os
import platform
from ctypes import wintypes

_IS_DARWIN = platform.system() == "Darwin"
if _IS_DARWIN:
    from AppKit import NSWorkspace
    from Foundation import NSAutoreleasePool

# ctypes.windll exists only on Windows. Tests patch this module attribute
# on any platform; leave it None off-Windows so import never fails.
_WINDLL = ctypes.windll if platform.system() == "Windows" else None
```

- [ ] **Step 2: Add Windows frontmost-app implementation**

Add after the `BUNDLE_ID_TO_APP_NAME` dict:

```python
# Windows process-name → display-name mapping, equivalent to
# BUNDLE_ID_TO_APP_NAME on macOS.
PROCESS_NAME_TO_APP_NAME: dict[str, str] = {
    "chrome": "Google Chrome",
    "Code": "Visual Studio Code",
    "Ghostty": "Ghostty",
    "anki": "Anki",
    "Notion": "Notion",
    "Obsidian": "Obsidian",
}


def _basename_exe(exe_path: str) -> str:
    """Return the executable basename without extension, cross-platform.

    Windows paths use backslashes; os.path.basename is host-dependent, so
    normalize separators before splitting.
    """
    return exe_path.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]


def _get_window_process_id(user32, hwnd: int) -> int | None:
    """Return the process ID that owns the given window handle."""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value or None


def _process_display_name_from_pid(kernel32, pid: int) -> str | None:
    """Return the mapped display name for a process, or None if unmapped."""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h_process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h_process:
        return None
    try:
        size = wintypes.DWORD(260)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(h_process, 0, buf, ctypes.byref(size)):
            process_name = _basename_exe(buf.value)
            return PROCESS_NAME_TO_APP_NAME.get(process_name)
    finally:
        kernel32.CloseHandle(h_process)
    return None


def _frontmost_app_name_windows() -> str | None:
    """Return the frontmost application name on Windows using ctypes/Win32."""
    user32 = _WINDLL.user32
    kernel32 = _WINDLL.kernel32

    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None

    # Prefer a mapped display name from the process executable path.
    pid = _get_window_process_id(user32, hwnd)
    if pid is not None:
        mapped = _process_display_name_from_pid(kernel32, pid)
        if mapped is not None:
            return mapped

    # Fallback: use window title (similar to localizedName on macOS).
    length = user32.GetWindowTextLengthW(hwnd) + 1
    buf = ctypes.create_unicode_buffer(length)
    user32.GetWindowTextW(hwnd, buf, length)
    title = buf.value
    return title if title else None
```

- [ ] **Step 3: Add platform dispatch to `_frontmost_app_name()`**

Replace the current `_frontmost_app_name()` method with one that dispatches:

```python
def _frontmost_app_name(self) -> str | None:
    if _IS_DARWIN:
        return self._frontmost_app_name_darwin()
    return _frontmost_app_name_windows()
```

Rename the existing `_frontmost_app_name()` to `_frontmost_app_name_darwin()`:

```python
def _frontmost_app_name_darwin(self) -> str | None:
    # NSWorkspace/AppKit calls from a background thread need an
    # autorelease pool, otherwise returned Objective-C objects can be
    # released before PyObjC bridges their values (e.g. localizedName
    # or bundleIdentifier returning None for some apps).
    pool = NSAutoreleasePool.alloc().init()
    try:
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            logger.debug("NSWorkspace returned no frontmost application")
            return None
        bundle_id = app.bundleIdentifier()
        localized_name = app.localizedName()
        if bundle_id and bundle_id in BUNDLE_ID_TO_APP_NAME:
            mapped_name = BUNDLE_ID_TO_APP_NAME[bundle_id]
            logger.debug(
                "Mapped frontmost app bundle ID %r (localizedName=%r) -> %r",
                bundle_id,
                localized_name,
                mapped_name,
            )
            return mapped_name
        logger.debug(
            "Using frontmost app localizedName=%r (bundle ID=%r)",
            localized_name,
            bundle_id,
        )
        return localized_name
    finally:
        pool.drain()
```

- [ ] **Step 4: Update `_run()` to use the renamed method**

Change `frontmost = self._frontmost_app_name()` to call the dispatcher — but it already calls `self._frontmost_app_name()`, which now dispatches. No change needed.

- [ ] **Step 5: Run existing tests to verify macOS path still works**

Run: `python -m pytest tests/test_apps.py -v`
Expected: All existing tests PASS (they mock `NSWorkspace`, so they still exercise the Darwin path).

- [ ] **Step 6: Commit**

```bash
git add telemetry/collectors/apps.py
git commit -m "feat: add Windows app collector via ctypes/Win32"
```

---

### Task 3: Main — platform-aware permission warning

**Files:**
- Modify: `main.py`

**Interfaces:**
- Consumes: `platform.system()` (already available from stdlib)
- Existing public API unchanged: `run()`, `Runner`

- [ ] **Step 1: Make the permission warning message platform-agnostic**

In `main.py`, change the `run()` function's warning message — just remove "macOS" from the string:

Current:
```python
def run() -> None:
    missing = check_permissions()
    if missing:
        logger.warning(
            "Missing macOS permissions: %s. "
            "Mouse/keyboard tracking will be disabled. "
            "Grant them in System Settings -> Privacy & Security for full telemetry.",
            ", ".join(missing),
        )
    runner = Runner(missing_permissions=missing)
    runner.start()
```

Replace with:
```python
def run() -> None:
    missing = check_permissions()
    if missing:
        logger.warning(
            "Missing permissions: %s. "
            "Mouse/keyboard tracking will be disabled. "
            "Grant them in System Settings -> Privacy & Security for full telemetry.",
            ", ".join(missing),
        )
    runner = Runner(missing_permissions=missing)
    runner.start()
```

(Just remove "macOS" from the message — it's now a generic warning that reads fine on both platforms.)

- [ ] **Step 2: Run main tests to verify no regressions**

Run: `python -m pytest tests/test_main.py -v`
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "fix: make permission warning platform-agnostic"
```

---

### Task 4: Tests — keymap Windows VK lookup

**Files:**
- Modify: `tests/test_keymap.py`

**Interfaces:**
- Consumes: `label_for_keycode`, `LABEL_FOR_KEYCODE_MACOS`, `LABEL_FOR_KEYCODE_WINDOWS` from `telemetry.keymap`

- [ ] **Step 1: Add `LABEL_FOR_KEYCODE_WINDOWS` to the import**

In `tests/test_keymap.py`, add `LABEL_FOR_KEYCODE_WINDOWS` to the existing import (already updated in Task 1):
```python
from telemetry.keymap import label_for_keycode, LABEL_FOR_KEYCODE_MACOS, LABEL_FOR_KEYCODE_WINDOWS
```

- [ ] **Step 2: Add Windows VK lookup tests**

Append to the test file:

```python
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
```

- [ ] **Step 3: Run new keymap tests**

Run: `python -m pytest tests/test_keymap.py -v`
Expected: All tests PASS (including existing macOS tests).

- [ ] **Step 4: Commit**

```bash
git add tests/test_keymap.py
git commit -m "test: add Windows keycode lookup and dispatch tests"
```

---

### Task 5: Tests — keyboard collector Windows VK integration

**Files:**
- Modify: `tests/test_keyboard.py`

**Interfaces:**
- Consumes: `KeyboardCollector` from `telemetry.collectors.keyboard`

- [ ] **Step 1: Add `patch` to the import and append Windows-VK tests**

Update the existing import in `tests/test_keyboard.py`:
```python
from unittest.mock import MagicMock, patch
```

Append to the test file:

```python
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
```

- [ ] **Step 2: Run keyboard tests**

Run: `python -m pytest tests/test_keyboard.py -v`
Expected: All tests PASS (6 total: 2 existing + 4 new).

- [ ] **Step 3: Commit**

```bash
git add tests/test_keyboard.py
git commit -m "test: add Windows VK keyboard collector integration tests"
```

---

### Task 6: Tests — app collector Windows path

**Files:**
- Modify: `tests/test_apps.py`

**Interfaces:**
- Consumes: `AppCollector`, `PROCESS_NAME_TO_APP_NAME` from `telemetry.collectors.apps`, `_frontmost_app_name_windows` from `telemetry.collectors.apps`

- [ ] **Step 1: Add import for the Windows helper**

Update the import line at the top of the test file from:
```python
from telemetry.collectors.apps import AppCollector, BUNDLE_ID_TO_APP_NAME
```
To:
```python
from telemetry.collectors.apps import AppCollector, BUNDLE_ID_TO_APP_NAME, PROCESS_NAME_TO_APP_NAME, _frontmost_app_name_windows
```

- [ ] **Step 2: Add Windows app collector tests**

Append to the test file:

```python
# --- Windows app collector tests ---
#
# All Windows-path tests patch `telemetry.collectors.apps._WINDLL` (the
# module-global that is None off-Windows) rather than ctypes.windll, so they
# run on any platform. ctypes.windll itself does not exist on macOS.


def _windll_context(exe_path=None, title="My App Window"):
    """Return a patched _WINDLL mock + its MagicMock, wired for a window."""
    mock_windll = MagicMock()
    mock_windll.user32.GetForegroundWindow.return_value = 0x12345
    mock_windll.user32.GetWindowTextLengthW.return_value = len(title)
    mock_windll.kernel32.OpenProcess.return_value = 0xABC  # truthy handle
    if exe_path is not None:
        # QueryFullProcessImageNameW writes the exe path into the unicode buffer.
        mock_windll.kernel32.QueryFullProcessImageNameW.side_effect = (
            lambda hproc, flags, buf, size: setattr(buf, "value", exe_path)
        )
    mock_windll.user32.GetWindowTextW.side_effect = (
        lambda hwnd, buf, length: setattr(buf, "value", title)
    )
    return patch("telemetry.collectors.apps._WINDLL", mock_windll), mock_windll


def test_process_name_mapping_targets_are_whitelisted():
    """Every Windows process name mapping must point to an app in the default whitelist."""
    from telemetry.config import APP_WHITELIST

    mapped = set(PROCESS_NAME_TO_APP_NAME.values())
    not_whitelisted = mapped - set(APP_WHITELIST)
    assert not not_whitelisted, f"Process name mapping targets not whitelisted: {not_whitelisted}"


def test_frontmost_app_name_windows_maps_known_process():
    """When the exe name matches a mapping, return the display name."""
    windll_patch, _mock_windll = _windll_context(
        exe_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    )
    with windll_patch, \
         patch("telemetry.collectors.apps._get_window_process_id", return_value=42):
        result = _frontmost_app_name_windows()
    assert result == "Google Chrome"


def test_frontmost_app_name_windows_falls_back_to_window_title():
    """When the exe name isn't mapped, fall back to the window title."""
    windll_patch, _mock_windll = _windll_context(
        exe_path=r"C:\Program Files\Spotify\spotify.exe", title="Spotify Premium"
    )
    with windll_patch, \
         patch("telemetry.collectors.apps._get_window_process_id", return_value=42):
        result = _frontmost_app_name_windows()
    assert result == "Spotify Premium"


def test_frontmost_app_name_windows_returns_none_when_no_window():
    """When there's no foreground window, return None."""
    windll_patch, mock_windll = _windll_context()
    mock_windll.user32.GetForegroundWindow.return_value = 0
    with windll_patch:
        result = _frontmost_app_name_windows()
    assert result is None


def test_frontmost_app_name_windows_handles_openprocess_failure():
    """When OpenProcess fails, fall back to window title."""
    windll_patch, mock_windll = _windll_context(title="My App Window")
    mock_windll.kernel32.OpenProcess.return_value = 0  # falsy handle
    with windll_patch, \
         patch("telemetry.collectors.apps._get_window_process_id", return_value=42):
        result = _frontmost_app_name_windows()
    assert result == "My App Window"


def test_frontmost_app_name_windows_returns_none_with_blank_title():
    """When the window title is empty, return None (no mapping, no title)."""
    windll_patch, _mock_windll = _windll_context(title="")
    with windll_patch, \
         patch("telemetry.collectors.apps._get_window_process_id", return_value=None):
        result = _frontmost_app_name_windows()
    assert result is None


def test_basename_exe_cross_platform():
    """Basename extraction works for Windows paths on any host OS."""
    from telemetry.collectors.apps import _basename_exe

    assert _basename_exe(r"C:\Program Files\Google\Chrome\Application\chrome.exe") == "chrome"
    assert _basename_exe("/usr/bin/code") == "code"
    assert _basename_exe("C:\\Windows\\System32\\notepad.exe") == "notepad"
```

- [ ] **Step 3: Run app collector tests**

Run: `python -m pytest tests/test_apps.py -v`
Expected: All tests PASS (existing macOS + new Windows tests).

- [ ] **Step 4: Commit**

```bash
git add tests/test_apps.py
git commit -m "test: add Windows app collector ctypes mock tests"
```

---

### Task 7: Tests — permissions on non-macOS

**Files:**
- Modify: `tests/test_permissions.py`

**Interfaces:**
- Consumes: `check_permissions` from `telemetry.permissions`

- [ ] **Step 1: Add non-macOS permission test**

Append to the test file:

```python
def test_check_permissions_returns_empty_on_non_macos():
    """On non-macOS, the checkers are None so check_permissions returns []."""
    with patch("telemetry.permissions._input_monitoring_checker", None), \
         patch("telemetry.permissions._accessibility_checker", None):
        assert check_permissions() == []
```

- [ ] **Step 2: Run permissions tests**

Run: `python -m pytest tests/test_permissions.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_permissions.py
git commit -m "test: add non-macOS permissions empty-return test"
```

---

### Task 8: Final integration — run full test suite

- [ ] **Step 1: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS. No regressions.

- [ ] **Step 2: Verify git status is clean and all changes committed**

Run: `git status`
Expected: Clean working tree (all changes committed).

- [ ] **Step 3: Show commit log**

Run: `git log --oneline -8`
Expected: 7 new commits on top of current HEAD.
