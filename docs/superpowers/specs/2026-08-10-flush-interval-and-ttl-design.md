# Flush Interval and Collection TTL Design

Date: 2026-08-10
Status: Approved (design review)

## Problem

The client flushes telemetry every 60 seconds and documents are retained in
MongoDB Atlas indefinitely. This design:

1. Changes the flush interval to 5 minutes (300 seconds).
2. Adds time-to-live (TTL) expiration so documents age out of Atlas:
   - `telemetry` documents expire after 1 year.
   - `keyboard_heatmap` documents expire after 1 month.
3. Applies the TTL configuration to the existing MongoDB Atlas database.

## Background: how TTL works in MongoDB

MongoDB expires documents with a **TTL index**: a collection-level index on a
date field with an `expireAfterSeconds` value. A background monitor deletes
documents whose indexed date is older than `expireAfterSeconds` (the monitor
runs roughly every 60 seconds, so documents linger at most ~a minute past
expiry). This is not a per-document field; it is enforced by the collection
index. The client's documents already carry a `createdAt` UTC datetime, which
is the required date field, so no schema change is needed.

## Target configuration

### Flush interval

- Default for `FLUSH_INTERVAL_SECONDS` changes from `60` to `300`.
- `.env.example` documents the knob with `FLUSH_INTERVAL_SECONDS=300`.
- The user's real `.env` does not set the variable, so the new default applies
  with no edit required.

### TTL

| Collection           | Index field | `expireAfterSeconds` | Duration |
| -------------------- | ----------- | -------------------: | -------- |
| `telemetry`          | `createdAt` | `31536000`           | 1 year   |
| `keyboard_heatmap`   | `createdAt` | `2592000`            | 30 days  |

## Architecture and responsibilities

### `telemetry/config.py`

Add two fields to the `Config` dataclass with defaults (so existing test
`make_config()` constructions continue to work):

```python
collection_ttl_seconds: int = 31536000  # 1 year
heatmap_ttl_seconds: int = 2592000      # 30 days
```

`load_config()` hardcodes both values in the `Config(...)` constructor, exactly
like `collection_name` and `heatmap_collection_name` are today. No new
environment variables.

### `telemetry/storage.py`

`Storage.__init__` creates the TTL indexes idempotently after opening the two
collections:

```python
for collection, ttl in (
    (self._collection, config.collection_ttl_seconds),
    (self._heatmap_collection, config.heatmap_ttl_seconds),
):
    try:
        collection.create_index("createdAt", expireAfterSeconds=ttl)
    except Exception as exc:
        logger.warning("Failed to create TTL index on %s: %s", collection.name, exc)
```

- `create_index` is idempotent: an identical-spec rerun is a no-op, so this is
  safe on every start and self-heals if a collection is ever dropped/recreated.
- Index creation failure is non-fatal for the daemon (logged warning). The
  one-off migration script is the loud failure path for the existing database.

### `scripts/create_ttl_indexes.py` (new)

A one-off maintenance script that reuses `load_config()` for `MONGO_URI` and
the database name, creates both TTL indexes, and prints the resulting index
names. Fails loudly (uncaught exceptions) because it is a maintenance task, not
the daemon.

## Error handling

- **Startup index creation**: failures log a warning; the daemon continues.
  Telemetry still flushes without TTL if the client's Mongo user lacks index
  permissions.
- **Migration script**: failures raise and exit non-zero so the operator
  notices.
- **Flush behavior**: unchanged. A failed flush still returns `None` and
  `main.py` leaves state uncleared to retry next interval. The sequential-insert
  duplicate caveat is unchanged.

## Testing

- **`tests/test_storage.py`** — assert `Storage` calls `create_index` with
  `expireAfterSeconds=31536000` on `telemetry` and `2592000` on
  `keyboard_heatmap`. (Uses mongomock if it tracks indexes, otherwise a mock
  asserting the calls.)
- **`tests/test_config.py`** — update the default flush-interval assertion
  (`60` → `300`); add assertions for the TTL defaults.
- Existing `make_config()` helpers in other test files pass named arguments and
  are unaffected by the new defaulted fields.

## Documentation

- **`CLAUDE.md`** — Configuration section: `FLUSH_INTERVAL_SECONDS` "defaults to
  `300`". Data-schema section: add a "Data retention (TTL)" note describing the
  per-collection expiry enforced by MongoDB TTL indexes on `createdAt`.
- **`.env.example`** — add `FLUSH_INTERVAL_SECONDS=300`.
- **This design doc** — committed to `docs/superpowers/specs/`.

## Out of scope

- Wiring the `AppCollector` into `main.py` (separate change).
- Persisting app-usage time (deferred until the app collector ships).
- Transactions / duplicate protection across the two inserts.
- Making TTL values env-configurable (YAGNI; hardcoded defaults).
