# Two-Collection Flush Schema Design

Date: 2026-08-09
Status: Approved (design review)

## Problem

The client currently flushes one document per interval into the `telemetry`
collection:

```json
{
  "createdAt": "2026-08-08T10:05:00Z",
  "mouse": { "leftClicks": 120, "rightClicks": 8, "movementMeters": 42.5 },
  "keys": { "A": 45, "Return": 12 },
  "apps": { "Visual Studio Code": 180 }
}
```

We want the storage schema to split into **two collections**:

- `telemetry` — flat mouse metrics plus a total key-press count.
- `keyboard_heatmap` — per-key press frequencies.

`apps` usage time is dropped from the flush. The `AppCollector` is implemented
but not wired into `main.py`, so app-usage tracking remains in place (state +
collector + tests) but is not persisted until the collector ships later.

## Target schema

One flush interval produces up to two documents.

### `telemetry` collection (one document per flush)

```json
{
  "createdAt": "2026-08-08T10:05:00Z",
  "leftClicks": 120,
  "rightClicks": 8,
  "movementMeters": 42.5,
  "keysPressed": 57
}
```

`keysPressed` is the total number of key presses in the interval — the sum of
all per-key counts in the heatmap.

### `keyboard_heatmap` collection (one document per flush, only when keys were pressed)

```json
{
  "createdAt": "2026-08-08T10:05:00Z",
  "A": 45,
  "Return": 12
}
```

Each key label maps to its count. The heatmap document is **skipped when no
keys were pressed** so the collection does not accumulate empty `{createdAt}`
shells.

Both documents share a single `createdAt` timestamp so they can be joined by
time window if ever needed. There is no shared batch ID — the documents are
otherwise independent.

## Architecture and responsibilities

`TelemetryState` owns the metric schema; `Storage` owns persistence.

### `telemetry/state.py`

`snapshot()` now returns the flat metric set:

```python
{
    "leftClicks": ...,
    "rightClicks": ...,
    "movementMeters": ...,       # rounded to 4 decimal places, as today
    "keysPressed": sum(keys),    # derived total
    "keyboard_heatmap": {...},   # dict(sorted(keys.items())) — preserves the
                                 # alphabetical sort that prevents leaking
                                 # keystroke insertion order
    "apps": {...},               # retained for the unwired AppCollector; NOT flushed
}
```

Unchanged: `_keys`, `_apps`, `add_app_time`, `clear()`, `has_activity()`.
App-usage counts continue to accumulate in state so `AppCollector` and its
tests keep working, but `Storage` never writes them.

### `telemetry/config.py`

Add a `heatmap_collection_name: str` field (default `"keyboard_heatmap"`),
hardcoded in `load_config()` exactly like `collection_name` is today. No new
environment variable.

### `telemetry/storage.py`

`Storage.__init__` opens two collections from the shared client:

- `config.collection_name` → the `telemetry` collection
- `config.heatmap_collection_name` → the `keyboard_heatmap` collection

`flush(snapshot) -> list[str] | None`:

1. Compute one `now = datetime.now(timezone.utc)`.
2. Build the `telemetry` document: `createdAt`, `leftClicks`, `rightClicks`,
   `movementMeters`, `keysPressed`.
3. If `snapshot["keyboard_heatmap"]` is non-empty, build the heatmap document:
   `createdAt` plus each key→count pair.
4. Insert the telemetry document, then the heatmap document if present.
5. Return the list of inserted document ids on success, or `None` if any insert
   raises (logged).

### `main.py`

`Runner` needs no behavior change. `_flush_once` and the final flush in `stop()`
already treat a `None` return from `flush()` as "do not clear state; retry next
flush". The `doc_id` variable is renamed to `flush_result` for clarity.

## Error handling

A failed flush returns `None`; the Runner leaves state uncleared so the data
retries on the next flush interval. This matches the existing behavior.

Known caveat: inserts are sequential, not transactional. If the telemetry
insert succeeds but the heatmap insert fails, the batch is treated as failed and
the next flush re-inserts the telemetry document — a duplicate. This is
acceptable for a 60-second-interval personal daemon on transient failures and is
not worth the complexity of a Mongo transaction (which also requires a replica
set).

## Testing

- **`tests/test_state.py`** — update assertions to the flat shape:
  `snapshot["leftClicks"]`, `snapshot["keyboard_heatmap"]["A"]`, etc.; add
  `keysPressed` assertions (total and after clear) and keep the sorted-heatmap
  and apps assertions.
- **`tests/test_storage.py`** — assert both collections receive the correct
  documents; the empty-heatmap case writes no heatmap document; telemetry and
  heatmap documents share the same `createdAt`; a failing insert returns `None`.
- **`tests/test_main.py`** — update the two direct snapshot assertions
  (`snap["mouse"]["leftClicks"]` → `snap["leftClicks"]`,
  `snap["keys"]["A"]` → `snap["keyboard_heatmap"]["A"]`). Runner lifecycle
  tests use a mocked `Storage` and are otherwise unaffected.
- **`tests/test_apps.py`** — unchanged; app counts remain in the snapshot.
- **`tests/test_config.py`** — add an assertion that
  `cfg.heatmap_collection_name == "keyboard_heatmap"`.

## Documentation

- **`CLAUDE.md`** — rewrite the "Data schema" section to describe the two
  collections and both document shapes.

## Out of scope

- Wiring `AppCollector` into `main.py` (separate change).
- Persisting app-usage time (deferred until the app collector ships, when a
  schema decision can be made with that feature in mind).
- Transactions / duplicate protection across the two inserts.
