# Cross-Platform Windows Support Design

**Date:** 2026-08-11
**Status:** Approved

## Context

The activity telemetry client currently only works on macOS. It needs to support
Windows as well for keyboard, mouse, and frontmost-application collection. The
frontend will display a replica of the MacBook Air M3 13-inch UK keyboard
layout, so key labels in the heatmap must use UK Mac physical key names
regardless of the OS.

## Design decisions

- **Key labels:** Always UK Mac physical labels (e.g., "Left Cmd", "Left Option").
  Windows keys without a Mac equivalent (Print Screen, Scroll Lock, etc.) are
  excluded from the heatmap. Modifier naming follows current UK Mac conventions
  exactly — "Left Option" (not "Left Alt"), "Left Cmd" (not "Left Win").
- **Approach:** Single-file platform dispatch (not split modules, not a full OS
  abstraction layer). Follows the existing pattern in `permissions.py`.
- **App collector Windows API:** `ctypes` + Win32. No extra pip dependencies.
- **Scope:** Full cross-platform — keyboard, mouse, permissions, and app
  collector all adapted.

## Architecture

### 1. Keymap (`telemetry/keymap.py`)

Add a `LABEL_FOR_KEYCODE_WINDOWS` dictionary mapping Windows virtual key codes
to UK Mac physical labels. `label_for_keycode()` dispatches on
`platform.system()`:

```python
import platform

def label_for_keycode(code: int) -> str | None:
    if platform.system() == "Windows":
        return LABEL_FOR_KEYCODE_WINDOWS.get(code)
    return LABEL_FOR_KEYCODE_MACOS.get(code)
```

The Windows dict covers only keys that physically exist on the M3 Air 13" UK
keyboard:

| Category | Keys | Windows VK range |
|---|---|---|
| Letters | A–Z | 0x41–0x5A |
| Numbers | 0–9 | 0x30–0x39 |
| Modifiers | Left/Right Shift, Ctrl, Alt→Option, Win→Cmd, Fn | 0xA0–0xA5, 0xFF |
| Navigation | Arrows, Home, End, PgUp, PgDn, Delete, Forward Delete | 0x21–0x2E |
| Function keys | F1–F20 | 0x70–0x87 |
| Punctuation | Grave, Minus, Equal, Brackets, Semicolon, Quote, Backslash, Comma, Period, Slash, Section | various |
| Special | Return, Tab, Space, Escape, Caps Lock | various |
| Keypad | 0–9, +, -, *, /, ., Enter, Clear, = | 0x60–0x6F, various |
| Media | Volume Up/Down, Mute | 0xAF, 0xAE, 0xAD |

Windows-only keys **excluded:** Print Screen, Scroll Lock, Pause, Insert,
Context Menu, Browser keys, OEM-specific keys not on the UK Mac layout.

The existing dict is renamed to `LABEL_FOR_KEYCODE_MACOS` for clarity.

### 2. Keyboard collector (`telemetry/collectors/keyboard.py`)

No changes. The collector already uses `pynput` (cross-platform) and calls
`label_for_keycode()`, which becomes platform-aware. The `_keycode_for()`
helper works with both macOS and Windows pynput key objects, which both expose
`.vk` attributes.

### 3. Mouse collector (`telemetry/collectors/mouse.py`)

No changes. Already fully cross-platform via `pynput`.

### 4. Permissions (`telemetry/permissions.py`)

No logic changes. Already returns `None, None` checkers on non-Darwin, so
`check_permissions()` returns `[]` on Windows. The warning message in
`main.py`'s `run()` becomes platform-aware to avoid saying "Missing macOS
permissions" on Windows.

### 5. App collector (`telemetry/collectors/apps.py`)

The single `AppCollector` class gains a Windows code path. At import time or
init time, the module detects the platform and selects a private
`_get_frontmost_name` implementation:

**macOS path (unchanged):** `NSWorkspace.frontmostApplication()` →
`bundleIdentifier` / `localizedName`

**Windows path (new):** ctypes calls to Win32:
1. `GetForegroundWindow()` → HWND
2. `GetWindowThreadProcessId()` → PID
3. `OpenProcess()` + `QueryFullProcessImageName()` → executable path
4. Basename without `.exe` → process identifier (like `bundleIdentifier`)
5. Fallback: `GetWindowText()` → window title (like `localizedName`)

A `PROCESS_NAME_TO_APP_NAME` dict maps known Windows process names to display
names:

```python
PROCESS_NAME_TO_APP_NAME: dict[str, str] = {
    "chrome": "Google Chrome",
    "Code": "Visual Studio Code",
    "Ghostty": "Ghostty",
    "anki": "Anki",
    "Notion": "Notion",
    "Obsidian": "Obsidian",
}
```

On Windows, no `NSAutoreleasePool` is needed — that code path only runs on
macOS.

The `_record` method, polling loop, `start`/`stop`, and threading model are
identical across platforms.

### 6. Main runner (`main.py`)

Minimal change: make the permission warning message platform-aware. The
`Runner.__init__`, `_keyboard_enabled()`, `_mouse_enabled()`, and lifecycle
methods need no changes — they already handle empty `missing_permissions`
correctly.

### 7. Configuration (`telemetry/config.py`)

No changes. Configuration is OS-agnostic.

## Testing

All tests remain mock-based and runnable on any platform. No Windows CI
required.

- **`tests/test_keymap.py`:** Add Windows VK lookup tests alongside existing
  macOS tests. Both dicts exercise the same `label_for_keycode()` with
  different VK ranges.
- **`tests/test_keyboard.py`:** Add test cases with Windows-range VK codes.
  Existing mock-based pattern works unchanged.
- **`tests/test_apps.py`:** Add Windows-path tests that mock `ctypes` calls
  (windll, GetForegroundWindow, etc.). Shared polling/record tests stay as-is.
- **`tests/test_permissions.py`:** Verify non-macOS returns `[]`.
- **`tests/test_main.py`:** No structural changes needed. Existing patched
  tests work regardless of platform.

## Files changed

| File | Change |
|---|---|
| `telemetry/keymap.py` | Add `LABEL_FOR_KEYCODE_WINDOWS`, rename macos dict, platform dispatch |
| `telemetry/collectors/apps.py` | Add Windows ctypes path, `PROCESS_NAME_TO_APP_NAME` dict |
| `main.py` | Platform-aware permission warning message |
| `telemetry/permissions.py` | No logic change (already handles non-macOS) |
| `tests/test_keymap.py` | Windows VK test cases |
| `tests/test_keyboard.py` | Windows VK integration cases |
| `tests/test_apps.py` | Windows ctypes mock tests |
| `tests/test_permissions.py` | Non-macOS return test |

## Out of scope

- Linux support (no Linux keymap or app collector path)
- Wiring the app collector into `main.py` (still unwired per existing CLAUDE.md note)
- Changing the frontend keyboard layout
