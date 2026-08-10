# Flush Interval and Collection TTL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change the flush interval default to 5 minutes and add MongoDB TTL indexes so `telemetry` documents expire after 1 year and `keyboard_heatmap` documents expire after 30 days, applied to the existing Atlas collections.

**Architecture:** Config owns the interval and TTL constants. `Storage` idempotently creates the TTL indexes at startup (non-fatal on failure). A one-off script applies the same indexes to the existing Atlas database and is run once now.

**Tech Stack:** Python 3, pymongo, python-dotenv, pytest, mongomock.

## Global Constraints

- Flush interval default: **300 seconds** (5 minutes).
- `telemetry` TTL: **31536000** seconds (1 year), index field `createdAt`.
- `keyboard_heatmap` TTL: **2592000** seconds (30 days), index field `createdAt`.
- TTL values are hardcoded in `Config` — no new environment variables.
- Daemon-side index-creation failure is **non-fatal** (log a warning, keep running); the migration script fails loudly.
- Follow existing patterns: `Config` dataclass + `load_config()`, `Storage` accepts `_client` for tests, tests use `pytest` + `mongomock`.
- The user's real `.env` is gitignored and must NOT be modified.

---

### Task 1: Config — flush default 300 and TTL fields

**Files:**
- Modify: `telemetry/config.py:7-15` (dataclass), `telemetry/config.py:56-68` (`load_config`)
- Test: `tests/test_config.py:14`, `tests/test_config.py:6-16`

**Interfaces:**
- Consumes: nothing new.
- Produces: `Config.collection_ttl_seconds: int` (default `31536000`), `Config.heatmap_ttl_seconds: int` (default `2592000`), and `Config.flush_interval_seconds` defaulting to `300`. Later tasks read these fields.

- [ ] **Step 1: Update the failing tests**

In `tests/test_config.py`:

1. Change line 14 from `assert cfg.flush_interval_seconds == 60` to:
```python
    assert cfg.flush_interval_seconds == 300
```
2. In `test_load_config_reads_env`, after the `mouse_dpi` assertion, add:
```python
    assert cfg.collection_ttl_seconds == 31536000
    assert cfg.heatmap_ttl_seconds == 2592000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: `test_load_config_reads_env` FAILS — `assert 60 == 300` and `AttributeError: 'Config' object has no attribute 'collection_ttl_seconds'`.

- [ ] **Step 3: Implement the config changes**

In `telemetry/config.py`, add two defaulted fields to the `Config` dataclass (after `heatmap_collection_name`):
```python
    heatmap_collection_name: str = "keyboard_heatmap"
    collection_ttl_seconds: int = 31536000  # 1 year
    heatmap_ttl_seconds: int = 2592000      # 30 days
```

In `load_config()`, change the flush default `60` → `300`:
```python
        flush_interval_seconds=_require_positive_int(
            os.getenv("FLUSH_INTERVAL_SECONDS"), 300, "FLUSH_INTERVAL_SECONDS"
        ),
```

And add the TTL values to the `Config(...)` constructor, alongside the hardcoded collection names:
```python
        heatmap_collection_name="keyboard_heatmap",
        collection_ttl_seconds=31536000,
        heatmap_ttl_seconds=2592000,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add telemetry/config.py tests/test_config.py
git commit -m "feat: default flush interval to 5 minutes, add collection TTL config"
```

---

### Task 2: Storage — create TTL indexes at startup

**Files:**
- Modify: `telemetry/storage.py:11-18` (`__init__`), add `_create_ttl_indexes`
- Test: `tests/test_storage.py`

**Interfaces:**
- Consumes: `Config.collection_ttl_seconds`, `Config.heatmap_ttl_seconds` (from Task 1).
- Produces: On construction, `Storage` creates a TTL index named `createdAt_1` on both the telemetry and heatmap collections. No behavior change to `flush()`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_storage.py` (imports already present: `mongomock`, `Storage`, `make_config`; add `from unittest.mock import MagicMock` if not already imported — it is, line 4):

```python
def test_storage_creates_ttl_indexes():
    client = mongomock.MongoClient()
    Storage(make_config(), _client=client)

    telemetry_indexes = {
        i["name"]: i for i in client["test"]["telemetry"].list_indexes()
    }
    heatmap_indexes = {
        i["name"]: i for i in client["test"]["keyboard_heatmap"].list_indexes()
    }
    assert telemetry_indexes["createdAt_1"]["expireAfterSeconds"] == 31536000
    assert heatmap_indexes["createdAt_1"]["expireAfterSeconds"] == 2592000


def test_ttl_index_creation_failure_is_non_fatal():
    client = MagicMock()
    collection = MagicMock()
    collection.create_index.side_effect = RuntimeError("index permission denied")
    client.__getitem__.return_value.__getitem__.return_value = collection

    # Storage.__init__ must not raise when index creation fails.
    storage = Storage(make_config(), _client=client)

    assert storage._collection is collection
```

- [ ] **Step 2: Run tests to verify the primary one fails**

Run: `pytest tests/test_storage.py::test_storage_creates_ttl_indexes -v`
Expected: FAIL — `KeyError: 'createdAt_1'` (no index created yet).

- [ ] **Step 3: Implement index creation in Storage**

In `telemetry/storage.py`, after the two collection attributes are set in `__init__`, call a new helper and define it:
```python
        self._collection = self._client[config.db_name][config.collection_name]
        self._heatmap_collection = self._client[config.db_name][
            config.heatmap_collection_name
        ]
        self._create_ttl_indexes()

    def _create_ttl_indexes(self) -> None:
        for collection, ttl in (
            (self._collection, self._config.collection_ttl_seconds),
            (self._heatmap_collection, self._config.heatmap_ttl_seconds),
        ):
            try:
                collection.create_index("createdAt", expireAfterSeconds=ttl)
            except Exception as exc:
                logger.warning(
                    "Failed to create TTL index on %s: %s",
                    collection.name,
                    exc,
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_storage.py -v`
Expected: PASS (5 passed — the new 2 plus the existing 3).

- [ ] **Step 5: Commit**

```bash
git add telemetry/storage.py tests/test_storage.py
git commit -m "feat: create TTL indexes on telemetry and keyboard_heatmap at startup"
```

---

### Task 3: Migration script + apply to existing Atlas database

**Files:**
- Create: `scripts/create_ttl_indexes.py`

**Interfaces:**
- Consumes: `Config.collection_name`, `Config.heatmap_collection_name`, `Config.collection_ttl_seconds`, `Config.heatmap_ttl_seconds`, `Config.db_name`, `Config.mongo_uri` (all via `load_config()` from Task 1).
- Produces: TTL indexes on the existing Atlas collections, verified via `list_indexes()`.

No pytest for this script — it is a one-off operator tool; verification is the live run against Atlas (authorized: user chose "I run it against Atlas now"). If the connection fails, stop and report; do not silently continue.

- [ ] **Step 1: Write the script**

Create `scripts/create_ttl_indexes.py`:
```python
"""One-off: create TTL indexes on the existing Atlas collections.

Run from the repository root:  python scripts/create_ttl_indexes.py
Requires MONGO_URI (and optionally ACTIVITY_DB_NAME) in .env.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pymongo import MongoClient

from telemetry.config import load_config


def main() -> None:
    cfg = load_config()
    client = MongoClient(cfg.mongo_uri)
    try:
        for name, ttl in (
            (cfg.collection_name, cfg.collection_ttl_seconds),
            (cfg.heatmap_collection_name, cfg.heatmap_ttl_seconds),
        ):
            index_name = client[cfg.db_name][name].create_index(
                "createdAt", expireAfterSeconds=ttl
            )
            print(f"Created TTL index on {name}: {index_name}")

        print("Verification (TTL indexes):")
        for name in (cfg.collection_name, cfg.heatmap_collection_name):
            for idx in client[cfg.db_name][name].list_indexes():
                if "expireAfterSeconds" in idx:
                    print(
                        f"  {name}: name={idx['name']} "
                        f"expireAfterSeconds={idx['expireAfterSeconds']}"
                    )
    finally:
        client.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the script against Atlas**

Run: `source .venv/bin/activate && python scripts/create_ttl_indexes.py`
Expected: prints `Created TTL index on telemetry: createdAt_1` and `Created TTL index on keyboard_heatmap: createdAt_1`, followed by the verification listing showing `expireAfterSeconds=31536000` for `telemetry` and `expireAfterSeconds=2592000` for `keyboard_heatmap`.
If it errors (bad URI, no permission), report the failure and stop.

- [ ] **Step 3: Commit**

```bash
git add scripts/create_ttl_indexes.py
git commit -m "feat: add one-off script to create TTL indexes on existing collections"
```

---

### Task 4: Documentation

**Files:**
- Modify: `.env.example`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: the final default interval (300) and TTL values from Task 1.
- Produces: updated docs; no code behavior.

- [ ] **Step 1: Document the flush interval knob**

In `.env.example`, add a line documenting the new default (place it after `ACTIVITY_DB_NAME`):
```
ACTIVITY_DB_NAME=activity-telemetry
FLUSH_INTERVAL_SECONDS=300
```

- [ ] **Step 2: Update CLAUDE.md**

1. In the Configuration section, change:
   `FLUSH_INTERVAL_SECONDS` — flush interval (defaults to `60`).
   to:
   `FLUSH_INTERVAL_SECONDS` — flush interval (defaults to `300`).
2. In the "Data schema" section, after the existing schema block text, add a "Data retention (TTL)" paragraph:
   ```
   Documents are automatically expired by MongoDB TTL indexes on `createdAt`:
   `telemetry` documents are deleted after 1 year and `keyboard_heatmap`
   documents after 1 month. `Storage` creates these indexes idempotently at
   startup; `scripts/create_ttl_indexes.py` applies them to an existing
   database.
   ```

- [ ] **Step 3: Verify and commit**

Run: `pytest tests/ -v`
Expected: all tests pass.

```bash
git add .env.example CLAUDE.md
git commit -m "docs: document 5-minute flush default and collection TTL retention"
```

---

## Self-Review

- **Spec coverage:** flush default 300 → Task 1; TTL config fields → Task 1; startup index creation → Task 2; migration script + apply to Atlas → Task 3; `.env.example`, CLAUDE.md, and testing → Tasks 1, 2, 4. No spec requirement left unassigned.
- **Placeholder scan:** every code step contains concrete, copy-pasteable code; the migration script is verified by its live run, which is stated explicitly.
- **Type consistency:** `Config.collection_ttl_seconds` / `Config.heatmap_ttl_seconds` names match across Tasks 1, 2, and 3; `_create_ttl_indexes` is defined in Task 2 and only used there; storage test asserts `expireAfterSeconds` 31536000/2592000, matching the config defaults.
