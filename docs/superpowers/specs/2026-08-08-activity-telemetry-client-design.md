# Activity Telemetry Client — Design

## Goal
Build a local Python terminal client for macOS that collects user activity data and writes batched documents to MongoDB Atlas every 5 minutes.

## Collected data
- **Mouse**
  - Left-click count
  - Right-click count
  - Movement distance in meters
- **Keyboard**
  - Count per physical key on a UK Mac QWERTY layout
- **Application time**
  - Seconds spent in the frontmost app, restricted to a whitelist

## Architecture

```
activity-telemetry-client/
├── main.py                  # entry point + lifecycle
├── requirements.txt
├── .env                     # MongoDB URI (already present, not committed)
└── telemetry/
    ├── __init__.py
    ├── config.py            # env vars, whitelist, intervals
    ├── state.py             # locked counters & key/app maps
    ├── storage.py           # MongoDB Atlas flush logic
    ├── keymap.py            # mac UK QWERTY code → label map
    └── collectors/
        ├── __init__.py
        ├── mouse.py         # pynput mouse listener
        ├── keyboard.py      # pynput keyboard listener
        └── apps.py          # frontmost-app poller
```

### Runtime flow
1. `main.py` loads config and creates a `TelemetryState` instance.
2. It starts three daemon threads:
   - Mouse listener
   - Keyboard listener
   - App poller (1-second loop)
3. The main thread sleeps in 5-minute chunks, then calls `storage.flush(state)`.
4. On `SIGINT`/`SIGTERM`, `main.py` signals shutdown, joins threads, runs a final flush, and exits.

Each collector only writes to `TelemetryState`; `storage.py` only reads and resets it during a flush.

## Components

| Module | Responsibility |
|---|---|
| `config.py` | Load `MONGODB_URI`, `DATABASE_NAME`, `FLUSH_INTERVAL_SECONDS`, and the app whitelist from `.env`. Validate on startup and fail fast with a clear message. |
| `state.py` | Single `TelemetryState` class holding `leftClicks`, `rightClicks`, `mouseMeters`, `keys: dict[str,int]`, `apps: dict[str,float]`, plus a `threading.Lock`. Provides typed increment helpers so collectors never touch the lock directly. |
| `keymap.py` | Static mapping from macOS key codes to UK Mac QWERTY physical labels (`A`, `S`, `Return`, `Left Shift`, etc.). Used by the keyboard collector to normalize keys. |
| `collectors/mouse.py` | Start/stop a `pynput` mouse listener. On click, increment the correct counter. On move, add Euclidean distance to `mouseMeters` using a configurable DPI → meters conversion (`MOUSE_DPI` in `.env`; defaults to 72 DPI). |
| `collectors/keyboard.py` | Start/stop a `pynput` keyboard listener. Map every press to a key label via `keymap.py`; ignore unmapped keys. Increment count in state. |
| `collectors/apps.py` | Every second ask macOS for the frontmost app. If it is in the whitelist, add one second to that app’s total in state. |
| `storage.py` | Build a document from the current state, insert it into MongoDB Atlas, then clear the flushed counters from state. Returns the inserted document ID for logging. |
| `main.py` | Wire everything together, schedule flushes, handle shutdown signals, and log progress to stdout. |

## Data flow & schema

Each flush produces one MongoDB document:

```json
{
  "createdAt": "2026-08-08T10:05:00Z",
  "mouse": {
    "leftClicks": 120,
    "rightClicks": 8,
    "movementMeters": 42.5
  },
  "keys": {
    "A": 45,
    "Return": 12,
    "Left Shift": 30
  },
  "apps": {
    "Visual Studio Code": 180,
    "Google Chrome": 120
  }
}
```

- `createdAt` is the flush timestamp.
- Only keys actually pressed during the interval are included; the frontend merges against the full keymap when rendering the heatmap.
- If a flush fails, counters are **not** reset, so the next flush retries the same data.

## Error handling & permissions

### macOS permissions
- Keyboard and mouse monitoring need **Input Monitoring** permission.
- Reading the frontmost app needs **Accessibility** permission.
- The script logs a clear message and exits if permissions are missing.

### Failure modes
- **MongoDB unreachable on flush:** keep counters in memory, retry on next flush, log the error.
- **Process crash / SIGINT:** catch `KeyboardInterrupt` and `SIGTERM`; run a final flush before exiting. If the final flush fails, log the unsent data.
- **Collector thread dies:** each thread runs in a `try/except`; on exception it logs and signals shutdown.
- **Invalid `.env`:** validate config at startup and exit with a helpful message.

### Logging
Use the stdlib `logging` module. Log startup, each flush success/failure, permission warnings, and shutdown.

## Testing strategy
1. **Unit tests for pure functions**
   - `keymap.py`: every mac key code maps to a UK QWERTY label.
   - `state.py`: increment helpers update counters correctly under concurrency.
   - `storage.py`: document builder produces the expected MongoDB shape.
2. **Integration test for storage**
   - Insert a sample document into MongoDB Atlas (or a local MongoDB) and assert it can be read back.
3. **Manual smoke test**
   - Run the script for a few minutes, click/type/switch apps, then verify a document appears in Atlas with sensible counts.

Collectors depend on abstractions (`TelemetryState`, config objects) so they can be unit tested without mocking macOS APIs.

## Dependencies
- `pynput` — global mouse and keyboard listeners
- `pymongo` — MongoDB Atlas client
- `pyobjc-framework-Cocoa` — querying the frontmost macOS application
- `python-dotenv` — loading `.env` settings
