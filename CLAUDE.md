# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Activity Telemetry Client is a Python daemon (macOS primary, with partial Windows support in the collectors) that collects mouse, keyboard, and (optionally) frontmost-application activity and flushes batched documents to MongoDB Atlas.

## Common commands

All commands assume you are in the repository root and have activated the virtual environment.

```bash
# Setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# Run the client
python main.py

# Run all tests
python -m pytest tests/ -v

# Run a single test file or test
python -m pytest tests/test_state.py -v
python -m pytest tests/test_state.py::test_click_counters -v
```

## Configuration

Configuration is loaded from `.env` (see `.env.example`). Required and notable variables:

- `MONGO_URI` — required MongoDB connection string.
- `ACTIVITY_DB_NAME` — database name (defaults to `activity-telemetry`).
- `FLUSH_INTERVAL_SECONDS` — flush interval (defaults to `300`).
- `MOUSE_DPI` — mouse DPI used to convert pixel distance to meters (defaults to `72`).

The app whitelist is hardcoded in `telemetry/config.py` (`APP_WHITELIST`). `telemetry/collectors/apps.py` maps OS-specific identities to whitelist names: `BUNDLE_ID_TO_APP_NAME` on macOS (because `NSWorkspace.frontmostApplication().localizedName()` can vary by locale/install) and `PROCESS_NAME_TO_APP_NAME` on Windows (lowercased exe basenames).

## macOS permissions

The client requires macOS Privacy & Security permissions:

- **Input Monitoring** — required for the mouse listener and the keyboard listener.
- **Accessibility** — required for the keyboard listener and to read the frontmost application.

`telemetry/permissions.py` checks these at startup; `main.py` disables the corresponding collector when a permission is missing rather than exiting. The keyboard listener is only started when both Input Monitoring and Accessibility are present. These checks are macOS-only — on other platforms `check_permissions()` returns an empty list.

## Architecture

### Runtime flow

`main.py` constructs a `Runner` that:

1. Loads `Config` from `.env`.
2. Creates a shared `TelemetryState` and a `Storage` instance.
3. Starts collectors as daemon threads.
4. Sleeps in `flush_interval_seconds` chunks, snapshots state, and calls `storage.flush(snapshot)`.
5. On `SIGINT`/`SIGTERM`, stops collectors and runs a final flush.

Collectors write only to `TelemetryState`; `Storage` reads the snapshot and never touches collector internals. If a flush fails, `main.py` does **not** call `state.clear()`, so the data retries on the next flush.

### Important: app collector is implemented but not wired

`telemetry/collectors/apps.py` contains a working `AppCollector` with tests, but `main.py` currently only wires `MouseCollector` and `KeyboardCollector`. To enable application-time tracking, instantiate `AppCollector` in `Runner.__init__`, start/stop it alongside the other collectors, and update `tests/test_main.py` accordingly.

### Data schema

Each flush interval writes up to two documents, sharing one `createdAt` timestamp.

`telemetry` collection (one document per flush):

```json
{
  "createdAt": "2026-08-08T10:05:00Z",
  "leftClicks": 120,
  "rightClicks": 8,
  "movementMeters": 42.5,
  "keysPressed": 57
}
```

`keyboard_heatmap` collection (one document per flush, only when keys were pressed):

```json
{
  "createdAt": "2026-08-08T10:05:00Z",
  "A": 45,
  "Return": 12
}
```

`keysPressed` is the total key presses in the interval (sum of the heatmap
counts). Field names are camelCase. `TelemetryState.snapshot()` sorts the
heatmap alphabetically so insertion order does not leak keystroke timing.
App-usage time is still tracked in state for the unwired `AppCollector` but is
not flushed.

The telemetry and heatmap inserts are sequential, not transactional: if the
heatmap insert fails, `flush()` returns `None` and the next flush interval
re-inserts a duplicate telemetry document. This is accepted for this daemon.

The schema changed from nested `mouse`/`keys`/`apps` fields to flat
`telemetry` fields plus a separate `keyboard_heatmap` collection, so existing
documents in the collection may be a mixed shape while old data ages out.

Documents are automatically expired by MongoDB TTL indexes on `createdAt`:
`telemetry` documents are deleted after 1 year and `keyboard_heatmap`
documents after 1 month. `Storage` creates these indexes idempotently at
startup; `scripts/create_ttl_indexes.py` applies them to an existing
database.

### Key modules

- `telemetry/config.py` — `Config` dataclass and `load_config()`. Fails fast with `sys.exit(1)` if `MONGO_URI` is missing or numeric env vars are invalid.
- `telemetry/state.py` — `TelemetryState`, a thread-safe counter and map store with typed increment helpers.
- `telemetry/storage.py` — `Storage` wraps `pymongo.MongoClient` and inserts flush documents. Accepts an optional `_client` argument for tests.
- `telemetry/keymap.py` — virtual-keycode → UK Mac QWERTY physical-label maps for macOS (`LABEL_FOR_KEYCODE_MACOS`) and Windows VK (`LABEL_FOR_KEYCODE_WINDOWS`), dispatched via `platform.system()`. Not currently used by the keyboard collector (which tracks key values directly); referenced by its own tests.
- `telemetry/collectors/mouse.py` — `pynput` mouse listener; counts clicks and accumulates Euclidean movement distance converted to meters via `MOUSE_DPI`.
- `telemetry/collectors/keyboard.py` — `pynput` keyboard listener that counts key *values*, not physical positions: printable keys use the uppercased `char`, special/function keys map through `_SPECIAL_KEY_LABELS`. A `_held_keys` set de-dupes macOS key auto-repeat, so holding a key counts once until release. Unmapped keys are ignored. On macOS the fn/globe key (keycode 63) is *not* delivered to pynput as a press — it arrives only as a `kCGEventFlagsChanged`, which pynput reports as a release. A dedicated `_FnGlobeWatcher` Quartz event tap (`kCGHIDEventTap`, listen-only) detects the fn flag bit and counts each fn press as `Fn`; it is a no-op on non-macOS.
- `telemetry/collectors/apps.py` — Polls the frontmost app and records elapsed time for whitelisted apps. On macOS polls `NSWorkspace` (using `NSAutoreleasePool` because AppKit calls run on a background thread); on Windows uses `ctypes`/Win32 (`GetForegroundWindow` → process exe name → `PROCESS_NAME_TO_APP_NAME`, window title as fallback).
- `telemetry/permissions.py` — macOS permission checks using `Quartz` and `ApplicationServices`; guarded so it imports and returns an empty list on non-macOS.

## Testing

Tests use `pytest` and `mongomock` for MongoDB-flush tests. Collector tests exercise the callback methods directly without starting the real OS listeners, so they can run on any platform. Tests in `tests/test_main.py` patch `load_config`, `Storage`, and the collector classes to verify `Runner` lifecycle behavior without macOS APIs.

## Design docs

Implementation history and original design specs live in `docs/superpowers/plans/` and `docs/superpowers/specs/`. They describe the intended full feature set (including the app collector) but may differ from the current wiring in `main.py`.

## Agent skills

### Issue tracker

Issues and specs live as GitHub issues, managed with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles map to identically-named labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
