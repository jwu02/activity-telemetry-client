# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Activity Telemetry Client is a macOS Python daemon that collects mouse, keyboard, and (optionally) frontmost-application activity and flushes batched documents to MongoDB Atlas.

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
- `FLUSH_INTERVAL_SECONDS` — flush interval (defaults to `60`).
- `MOUSE_DPI` — mouse DPI used to convert pixel distance to meters (defaults to `72`).

The app whitelist is hardcoded in `telemetry/config.py` (`APP_WHITELIST`). Bundle IDs for some apps are mapped to whitelist names in `telemetry/collectors/apps.py` (`BUNDLE_ID_TO_APP_NAME`) because `NSWorkspace.frontmostApplication().localizedName()` can vary.

## macOS permissions

The client requires macOS Privacy & Security permissions:

- **Input Monitoring** — required for the mouse listener.
- **Accessibility** — required for the keyboard listener.
- **Accessibility** — required to read the frontmost application.

`telemetry/permissions.py` checks these at startup. `main.py` disables the corresponding collector when a permission is missing rather than exiting.

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

### Key modules

- `telemetry/config.py` — `Config` dataclass and `load_config()`. Fails fast with `sys.exit(1)` if `MONGO_URI` is missing or numeric env vars are invalid.
- `telemetry/state.py` — `TelemetryState`, a thread-safe counter and map store with typed increment helpers.
- `telemetry/storage.py` — `Storage` wraps `pymongo.MongoClient` and inserts flush documents. Accepts an optional `_client` argument for tests.
- `telemetry/keymap.py` — macOS virtual-keycode → UK Mac QWERTY physical-label map used by the keyboard collector.
- `telemetry/collectors/mouse.py` — `pynput` mouse listener; counts clicks and accumulates Euclidean movement distance converted to meters via `MOUSE_DPI`.
- `telemetry/collectors/keyboard.py` — `pynput` keyboard listener; maps keycodes to labels via `keymap.py` and ignores unmapped keys.
- `telemetry/collectors/apps.py` — Polls `NSWorkspace` every second and records elapsed time for whitelisted apps. Uses `NSAutoreleasePool` because AppKit calls run on a background thread.
- `telemetry/permissions.py` — macOS-only permission checks using `Quartz` and `ApplicationServices`.

## Testing

Tests use `pytest` and `mongomock` for MongoDB-flush tests. Collector tests exercise the callback methods directly without starting the real OS listeners, so they can run on any platform. Tests in `tests/test_main.py` patch `load_config`, `Storage`, and the collector classes to verify `Runner` lifecycle behavior without macOS APIs.

## Design docs

Implementation history and original design specs live in `docs/superpowers/plans/` and `docs/superpowers/specs/`. They describe the intended full feature set (including the app collector) but may differ from the current wiring in `main.py`.
