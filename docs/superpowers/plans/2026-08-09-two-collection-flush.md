# Two-Collection Flush Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the flush output into a flat `telemetry` collection (mouse metrics + total keys) and a `keyboard_heatmap` collection (per-key counts), dropping `apps` from the flushed documents.

**Architecture:** `TelemetryState` owns the metric schema (`snapshot()` returns the flat shape and derives `keysPressed`); `Config` gains a `heatmap_collection_name` field; `Storage` opens two collections and `flush()` writes up to two documents sharing one `createdAt`. The Runner only needs a variable rename — its `None`-means-retry logic is unchanged.

**Tech Stack:** Python, `pymongo`, `mongomock`, `pytest`.

## Global Constraints

- Match existing style: `from __future__ import annotations`, PEP 604 unions (`X | None`), builtin generics (`dict[str, int]`), 4-space indent.
- Document field names are camelCase (`leftClicks`, `keysPressed`, `keyboard_heatmap`, `createdAt`).
- `keyboard_heatmap` key counts must be sorted alphabetically in `snapshot()` (preserves the anti-leak property).
- Heatmap collection name is `"keyboard_heatmap"` (hardcoded in `load_config`, no new env var).
- `apps` is retained in `TelemetryState` (for the unwired `AppCollector` and its tests) but must NOT appear in any flushed document.
- Do not modify `telemetry/collectors/apps.py` or `tests/test_apps.py`.
- `main.py` retry semantics stay: a `None` return from `flush()` means the Runner does not clear state.

Spec: `docs/superpowers/specs/2026-08-09-two-collection-flush-design.md`

---

### Task 1: Config — add `heatmap_collection_name`

**Files:**
- Modify: `telemetry/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config.heatmap_collection_name: str`, defaulting to `"keyboard_heatmap"`. `load_config()` sets it explicitly.

- [ ] **Step 1: Write the failing test**

In `tests/test_config.py`, in `test_load_config_reads_env`, add this line right after the existing `assert cfg.collection_name == "telemetry"`:

```python
    assert cfg.heatmap_collection_name == "keyboard_heatmap"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `AttributeError: 'Config' object has no attribute 'heatmap_collection_name'`

- [ ] **Step 3: Add the field and set it in `load_config`**

In `telemetry/config.py`, add the field to the `Config` dataclass after `collection_name`:

```python
@dataclass(frozen=True)
class Config:
    mongo_uri: str
    db_name: str
    collection_name: str
    heatmap_collection_name: str = "keyboard_heatmap"
    flush_interval_seconds: int
    mouse_dpi: int
    app_whitelist: set[str]
```

In `load_config()`, in the returned `Config(...)`, add a line after `collection_name="telemetry",`:

```python
        heatmap_collection_name="keyboard_heatmap",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add telemetry/config.py tests/test_config.py
git commit -m "feat: add heatmap_collection_name to config"
```

---

### Task 2: State — `snapshot()` returns the flat schema with `keysPressed`

**Files:**
- Modify: `telemetry/state.py` (the `snapshot` method)
- Modify: `tests/test_state.py` (shape assertions + new `keysPressed` checks)
- Modify: `tests/test_main.py` (the two snapshot assertions in `test_runner_preserves_state_when_flush_fails`)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `TelemetryState.snapshot() -> dict[str, Any]` with keys `leftClicks`, `rightClicks`, `movementMeters`, `keysPressed`, `keyboard_heatmap`, `apps`. The rest of the `TelemetryState` API (`add_*`, `has_activity`, `clear`, `snapshot_and_clear`) is unchanged.

- [ ] **Step 1: Update the tests to the new shape (the failing tests)**

In `tests/test_state.py`, replace the shape accessors:

- In `test_click_counters`: `snap["mouse"]["leftClicks"]` → `snap["leftClicks"]` (both occurrences), `snap["mouse"]["rightClicks"]` → `snap["rightClicks"]`, `next_snap["mouse"]["leftClicks"]` → `next_snap["leftClicks"]`.
- In `test_key_and_app_accumulation`: `snap["keys"]["A"]` → `snap["keyboard_heatmap"]["A"]`, `snap["keys"]["Return"]` → `snap["keyboard_heatmap"]["Return"]`, and add `assert snap["keysPressed"] == 3` after the heatmap assertions.
- In `test_snapshot_does_not_clear`: `snap1["mouse"]["leftClicks"]` → `snap1["leftClicks"]` (and `snap2`), and the final `state.snapshot()["mouse"]["leftClicks"]` → `state.snapshot()["leftClicks"]`.
- In `test_clear_empties_state`: `snap["keys"]` → `snap["keyboard_heatmap"]`, and add `assert snap["keysPressed"] == 0`.
- In `test_key_counts_are_sorted_to_prevent_leaking_insertion_order`: `list(snap["keys"].keys())` → `list(snap["keyboard_heatmap"].keys())`.

The `snap["apps"]` assertions in `test_key_and_app_accumulation` and `test_clear_empties_state` stay as-is. `test_has_activity_reports_keyboard_or_mouse_only` is unchanged.

In `tests/test_main.py`, in `test_runner_preserves_state_when_flush_fails`, replace:

```python
    assert snap["mouse"]["leftClicks"] == 1
    assert snap["keys"]["A"] == 1
```

with:

```python
    assert snap["leftClicks"] == 1
    assert snap["keyboard_heatmap"]["A"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_state.py tests/test_main.py -v`
Expected: FAIL on `KeyError: 'leftClicks'` (snapshot still returns the old nested shape)

- [ ] **Step 3: Rewrite `snapshot()`**

In `telemetry/state.py`, replace the `snapshot` method body:

```python
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "leftClicks": self._left_clicks,
                "rightClicks": self._right_clicks,
                "movementMeters": round(self._mouse_meters, 4),
                "keysPressed": sum(self._keys.values()),
                # Sort key counts alphabetically so insertion order does not
                # leak information about keystroke sequences.
                "keyboard_heatmap": dict(sorted(self._keys.items())),
                "apps": dict(self._apps),
            }
```

`clear()`, `has_activity()`, `_keys`, `_apps`, and `add_app_time` are unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_state.py tests/test_main.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add telemetry/state.py tests/test_state.py tests/test_main.py
git commit -m "feat: snapshot returns flat telemetry schema with keysPressed"
```

---

### Task 3: Storage — `flush()` writes two collections; Runner handles list result

**Files:**
- Modify: `telemetry/storage.py`
- Modify: `tests/test_storage.py`
- Modify: `main.py` (rename `doc_id` → `flush_result`)

**Interfaces:**
- Consumes: `Config.heatmap_collection_name` (Task 1), the flat snapshot shape from `TelemetryState.snapshot()` (Task 2).
- Produces: `Storage.flush(snapshot: dict[str, Any]) -> list[str] | None` — list of inserted doc ids on success, `None` on any insert failure. `Storage.__init__` opens `self._collection` (telemetry) and `self._heatmap_collection`. Runner treats a `None` return as "don't clear, retry".

- [ ] **Step 1: Rewrite the failing tests**

Replace the contents of `tests/test_storage.py` with:

```python
import mongomock
from datetime import datetime
from unittest.mock import MagicMock, patch

from telemetry.config import Config
from telemetry.storage import Storage


def make_config():
    return Config(
        mongo_uri="",
        db_name="test",
        collection_name="telemetry",
        heatmap_collection_name="keyboard_heatmap",
        flush_interval_seconds=300,
        mouse_dpi=72,
        app_whitelist=set(),
    )


def test_flush_writes_telemetry_and_heatmap_documents():
    client = mongomock.MongoClient()
    storage = Storage(make_config(), _client=client)
    snapshot = {
        "leftClicks": 1,
        "rightClicks": 2,
        "movementMeters": 0.5,
        "keysPressed": 3,
        "keyboard_heatmap": {"A": 2, "Return": 1},
        "apps": {"Visual Studio Code": 5.0},
    }
    result = storage.flush(snapshot)
    assert result is not None
    assert len(result) == 2

    telemetry_docs = list(client["test"]["telemetry"].find())
    heatmap_docs = list(client["test"]["keyboard_heatmap"].find())
    assert len(telemetry_docs) == 1
    assert len(heatmap_docs) == 1

    telemetry = telemetry_docs[0]
    heatmap = heatmap_docs[0]
    assert isinstance(telemetry["createdAt"], datetime)
    assert isinstance(heatmap["createdAt"], datetime)
    assert telemetry["createdAt"] == heatmap["createdAt"]
    assert telemetry["leftClicks"] == 1
    assert telemetry["rightClicks"] == 2
    assert telemetry["movementMeters"] == 0.5
    assert telemetry["keysPressed"] == 3
    assert "apps" not in telemetry
    assert heatmap["A"] == 2
    assert heatmap["Return"] == 1


def test_flush_skips_heatmap_document_when_no_keys():
    client = mongomock.MongoClient()
    storage = Storage(make_config(), _client=client)
    snapshot = {
        "leftClicks": 1,
        "rightClicks": 0,
        "movementMeters": 0.0,
        "keysPressed": 0,
        "keyboard_heatmap": {},
        "apps": {},
    }
    result = storage.flush(snapshot)
    assert result is not None
    assert len(result) == 1
    assert len(list(client["test"]["telemetry"].find())) == 1
    assert len(list(client["test"]["keyboard_heatmap"].find())) == 0


def test_flush_returns_none_when_heatmap_insert_fails():
    client = mongomock.MongoClient()
    storage = Storage(make_config(), _client=client)
    snapshot = {
        "leftClicks": 1,
        "rightClicks": 0,
        "movementMeters": 0.0,
        "keysPressed": 1,
        "keyboard_heatmap": {"A": 1},
        "apps": {},
    }
    with patch.object(
        storage._heatmap_collection, "insert_one", side_effect=RuntimeError("boom")
    ):
        assert storage.flush(snapshot) is None


def test_close_calls_client_close():
    client = MagicMock()
    storage = Storage(make_config(), _client=client)
    storage.close()
    client.close.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_storage.py -v`
Expected: FAIL on `KeyError: 'leftClicks'` (old `flush` reads `snapshot["mouse"]`)

- [ ] **Step 3: Rewrite `Storage`**

Replace the `__init__` and `flush` methods in `telemetry/storage.py`:

```python
    def __init__(self, config: Config, _client: MongoClient | None = None) -> None:
        self._config = config
        self._client = _client or MongoClient(config.mongo_uri)
        self._collection = self._client[config.db_name][config.collection_name]
        self._heatmap_collection = self._client[config.db_name][config.heatmap_collection_name]

    def flush(self, snapshot: dict[str, Any]) -> list[str] | None:
        now = datetime.now(timezone.utc)
        telemetry_doc = {
            "createdAt": now,
            "leftClicks": snapshot["leftClicks"],
            "rightClicks": snapshot["rightClicks"],
            "movementMeters": snapshot["movementMeters"],
            "keysPressed": snapshot["keysPressed"],
        }
        documents = [(self._collection, telemetry_doc)]
        heatmap = snapshot.get("keyboard_heatmap", {})
        if heatmap:
            heatmap_doc = {"createdAt": now, **heatmap}
            documents.append((self._heatmap_collection, heatmap_doc))
        inserted_ids: list[str] = []
        try:
            for collection, document in documents:
                result = collection.insert_one(document)
                inserted_ids.append(str(result.inserted_id))
        except Exception as exc:
            logger.exception("Failed to flush telemetry: %s", exc)
            return None
        logger.info("Flushed telemetry documents: %s", inserted_ids)
        return inserted_ids
```

The `from datetime import datetime, timezone` import is already present.

- [ ] **Step 4: Adapt the Runner variable name**

In `main.py`, in `_flush_once`, replace:

```python
        doc_id = self.storage.flush(snapshot)
        if doc_id is None:
            logger.error("Flush failed; counters will retry on next flush")
            return
```

with:

```python
        flush_result = self.storage.flush(snapshot)
        if flush_result is None:
            logger.error("Flush failed; counters will retry on next flush")
            return
```

In `stop()`, replace:

```python
            doc_id = self.storage.flush(snapshot)
            if doc_id is None:
                logger.error("Final flush failed: %s", snapshot)
```

with:

```python
            flush_result = self.storage.flush(snapshot)
            if flush_result is None:
                logger.error("Final flush failed: %s", snapshot)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_storage.py tests/test_main.py -v`
Expected: PASS (the Runner lifecycle tests still use `storage.flush.return_value = "fake-id"`, which is non-`None`, so the retry logic is exercised unchanged)

- [ ] **Step 6: Commit**

```bash
git add telemetry/storage.py tests/test_storage.py main.py
git commit -m "feat: flush telemetry and keyboard_heatmap into separate collections"
```

---

### Task 4: Docs — update CLAUDE.md data schema + full-suite verification

**Files:**
- Modify: `CLAUDE.md` (the "Data schema" section under Architecture)

- [ ] **Step 1: Rewrite the Data schema section**

In `CLAUDE.md`, replace the whole `### Data schema` section (from the `### Data schema` heading through the closing code fence and the field-names sentence) with:

````markdown
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
````

- [ ] **Step 2: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: PASS (all files)

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document two-collection flush schema"
```
