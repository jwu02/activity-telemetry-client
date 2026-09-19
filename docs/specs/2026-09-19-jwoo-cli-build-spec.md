# jwoo-cli Build Spec

**Date:** 2026-09-19
**Status:** Approved
**Decision record:** `docs/adr/0001`–`0017`. This spec restates them at build precision; where an ADR
gives reasoning, this document gives instructions.

**Why `docs/specs/` and not `docs/superpowers/specs/`:** the four existing specs are dated
single-change designs (`YYYY-MM-DD-slug-design.md`, 650–825 words) describing deltas to the current
telemetry daemon. This is a whole-system build spec for a tool that does not exist yet, and it is a
first-class artifact alongside `CONTEXT.md` and `docs/adr/` rather than part of the superpowers
import. The telemetry daemon's existing specs stay where they are.

---

## Goal

One installable Python CLI, `jwoo-cli`, invoked as `jwoo`, replacing both current projects:

- it runs the mouse/keyboard telemetry daemon as the `track` subcommand, unchanged on the wire; and
- it is the AI-usage ingestion engine — hook and sync drivers → per-harness parsers → per-API-request
  events → SQLite (canonical, unique-index dedup) → MongoDB Atlas, so the website keeps working.

Every decision below is locked. A build session should not have to re-ask any of it.

## Decisions, and the ADRs that own them

| ADR | Decision | § |
|---|---|---|
| 0001 | SQLite canonical; Mongo is a replica | [Storage](#storage) |
| 0002 | Cost computed at ingest from rate cards, stored | [Pricing](#pricing) |
| 0003 | Identity = harness-scoped per-request id; fingerprint fallback | [Events](#events) |
| 0004 | Rate cards are dated half-open TOML ranges | [Rate card file](#rate-card-file) |
| 0005 | Files live in XDG user directories | [Config & paths](#config--paths) |
| 0006 | `ingest` fail-soft; failures counted and surfaced | [Exit codes](#exit-codes) |
| 0007 | Commit first, drain after, upsert by identity | [Export](#export) |
| 0008 | Claude Code = transcript chunk groups | [Claude Code](#claude-code) |
| 0009 | OpenCode = its SQLite database | [OpenCode](#opencode) |
| 0010 | DSH = its canonical session log | [DSH](#dsh) |
| 0011 | One strict WAL SQLite file; keeps every event | [Storage](#storage) |
| 0012 | Export upserts, never deletes; majority write | [Export](#export) |
| 0013 | No `watch`, no standing process; `sync --all` on a timer | [Driver wiring](#driver-wiring) |
| 0014 | Interactive session = narrow REPL | [Interactive session](#interactive-session) |
| 0015 | Four report subcommands; `sync --all` | [Reports](#reports) |
| 0016 | Fixtures captured from real data, scalar-reduced | [Testing](#testing) |
| 0017 | Re-derive history; import the unreachable legacy tail | [Cutover](#cutover-runbook) |

## Dependencies

`pyproject.toml` (PEP 621, hatchling), `[project.scripts] jwoo = "jwoo_cli.__main__:main"`, committed
`uv.lock`. Python floor **3.12**. Install with `uv tool install -e .` (or `pipx install -e .`). Never
published to PyPI.

Flat and required: `pymongo`, `pynput`, and `pyobjc-framework-*` behind a `sys_platform == 'darwin'`
marker. One extra: `dsh` → `backports.zstd` (≥1.7.0). Extras are otherwise rejected — they
manufacture half-installed states whose only symptom is an ImportError at runtime. The zstd binding
is the sole exception because exactly one parser needs it.

`tomllib`, `sqlite3`, and `zoneinfo` are stdlib.

---

## Command surface

```
jwoo [--config PATH] [-v] [--json] [--tz TZ] <command>
```

Nine commands, flat, no namespacing — no verb collides, and the command string lives in
`~/.claude/settings.json` and in the launchd plist forever.

| Command | Purpose |
|---|---|
| `jwoo` (bare) | On a TTY: the interactive session (§[Interactive session](#interactive-session)). Not a TTY: print usage, exit non-zero, **never wait on input** |
| `jwoo track` | The telemetry daemon. `--interval SECONDS`, `--once` |
| `jwoo ingest <harness>` | The fast path. Raw payload on **stdin**, or `--file PATH` |
| `jwoo sync <harness>` \| `--all` | Reconciliation. `--since DATE` narrows |
| `jwoo export` | Drain the outbox to Mongo. `--follow` |
| `jwoo status` | Read-only diagnostic. `--brief` |
| `jwoo today` | Cost and tokens so far today, per model, with cache-hit rate |
| `jwoo month` | The same, month-to-date |
| `jwoo projects` | All-time cost by `cwd`, folded to project labels |
| `jwoo events` | Most recent events, one line each |

**`<harness>` is a required positional** on `ingest` and `sync` — never a flag, never defaulted. A
hook always knows which harness it is, so a required positional turns "which harness am I?" from a
runtime question into a parse error. `sync --all` is mutually exclusive with the positional and is
the timer's invocation (ADR-0015).

**There is no `watch` command** (ADR-0013). `Watch` is historical vocabulary.

**`recompute` is reserved and unbuilt** — the name does not appear in v1.

### The registry

One shared in-process command registry backs both front-ends: session slash commands call the same
functions the subcommands call, so `/sync opencode` and `jwoo sync opencode` cannot drift. This is
the reason the session shells out to nothing (ADR-0014).

### Exit codes

| Command | On failure |
|---|---|
| `ingest` | **Exit 0.** Reason logged, failure counted (ADR-0006) |
| `sync`, `export`, `track` | **Fail loud** — non-zero with a message |
| `export --follow` | Never exits on drain failure |
| `export` invoked with no `mongo_uri` | Non-zero, "no mongo_uri configured" |

The unifying rule: **the exit code reflects whether the thing the user asked for happened.** Inline,
the user asked for an ingest and the drain is opportunistic; explicit, the user asked for a drain.

**The Claude shim trap:** on `Stop`, a non-zero exit does not report an error — it **blocks the turn
and continues the conversation**. Python's `argparse` exits 2 on a bad argument, so the shim must
trap every exception, including `SystemExit`, and exit 0. This is sharper than "fail-soft": a
non-zero exit here is a disrupted conversation, not a missed datapoint.

---

## Architecture

Six pipeline stages. **Stage 2 is the only per-harness stage, and it is a pure function over one raw
record** — no I/O, no clock, no config reads. Stages 1 and 6 are the only ones that differ by driver.

| # | Stage | Scope | Does |
|---|---|---|---|
| 1 | Enumerate | per-driver | yields raw records + provenance (harness, source path, session id) |
| 2 | **Parse** | **per-harness** | raw record → zero or more events |
| 3 | Normalize | shared | alias resolution (ADR-0004), `recorded_at` fallback, schema conformance |
| 4 | Price | shared | rate-card lookup at the event's instant (ADR-0002) |
| 5 | Store | shared | `INSERT OR IGNORE` against the unique index |
| 6 | Export | shared | drain unexported rows to Mongo, then mark |

A new harness costs one enumerate path plus one pure parse function and nothing else.

**Identity is the only dedup, and it is the only correctness mechanism.** Every driver hands its
parser a set of raw records; the unique index discards what is already stored. Losing state costs a
re-read, never an event.

### Driver wiring

| Harness | `ingest` (hook) | `sync` |
|---|---|---|
| Claude Code | yes — `Stop`, `SubagentStop`, `StopFailure`, `SessionEnd` | yes |
| OpenCode | yes — plugin on `message.updated` | yes |
| DSH | **no** — no hook | yes |

**Every pass reads its source from zero.** No cursors, no offsets, no watermarks, no incremental
logic. This is affordable because a complete pass costs ~2.3 s of CPU (Claude 1.98 s warm, OpenCode
~260 ms, DSH ~80 ms), and it deletes an entire failure class: a corrupt, stale, or shrink-reset
cursor stops existing rather than needing handling.

**Catch-up is `jwoo sync --all` on a launchd timer**, default every 5 minutes. This is the standing
path. `sync` re-reads full history and dedups by identity, so it repairs a dropped hook, a crashed
process, a `SessionEnd` that never fired, and a parser bug alike.

### Transaction boundary

One SQLite transaction per source per cycle, **committed before any network I/O**. Then the Mongo
upsert, then a second transaction marking `exported_at`.

**The mark is only ever written after a confirmed upsert.** A crash between the two re-pushes on the
next drain, harmless because Mongo `_id = identity` makes the upsert idempotent. Marking
`exported_at` in the same transaction as the insert is forbidden: a crash before the push would leave
a row claiming to be exported with nothing to retry it.

---

## Storage

The canonical store is **one SQLite file**, `$XDG_DATA_HOME/jwoo/jwoo.db`, else
`~/.local/share/jwoo/jwoo.db`; directory `0700`; overridable by `store.path`.

Every connection comes from one `open_store()` factory, so pragmas cannot drift between commands:

```
journal_mode = WAL        busy_timeout = 5000       foreign_keys = ON
synchronous  = FULL
```

`synchronous=FULL` rather than WAL's usual `NORMAL`: ADR-0007's commit-then-drain ordering is only
load-bearing if the commit survives a power cut. The cost is one fsync per source per cycle, not per
event.

**No application-level locking** — `busy_timeout` is the whole story, and a writer that still loses
the race exits 0 with a counted failure. **No `VACUUM` in v1.** `jwoo status` runs `PRAGMA
quick_check`.

### DDL

Every table is `STRICT` (local SQLite is 3.51; `STRICT` needs 3.37), turning a flattener type bug
into an error at the store boundary instead of a silently mistyped row.

```sql
CREATE TABLE events (
    id                        INTEGER PRIMARY KEY,   -- outbox FIFO key
    identity                  TEXT NOT NULL UNIQUE,
    harness                   TEXT NOT NULL,         -- display name: "Claude Code"
    model                     TEXT,                  -- null ⇒ null cost
    cwd                       TEXT,
    prompt_tokens             INTEGER NOT NULL,
    completion_tokens         INTEGER NOT NULL,
    total_tokens              INTEGER NOT NULL,
    prompt_cache_hit_tokens   INTEGER NOT NULL,
    prompt_cache_miss_tokens  INTEGER NOT NULL,
    cost_yuan                 REAL,
    recorded_at               TEXT NOT NULL,         -- ISO-8601 UTC
    ingested_via              TEXT NOT NULL CHECK (ingested_via IN ('hook','watch','sync')),
    ingested_at               TEXT NOT NULL,
    exported_at               TEXT,                  -- null ⇒ pending
    session_id                TEXT,
    message_id                TEXT,
    turn                      INTEGER,
    step                      INTEGER,
    delegation_depth          INTEGER,
    reasoning_tokens          INTEGER
) STRICT;

CREATE UNIQUE INDEX events_identity ON events(identity);
CREATE INDEX events_pending ON events(id) WHERE exported_at IS NULL;

CREATE TABLE source_state (
    harness    TEXT NOT NULL,
    source_key TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (harness, source_key)
) STRICT, WITHOUT ROWID;

CREATE TABLE failures (
    kind         TEXT PRIMARY KEY,
    count        INTEGER NOT NULL,
    last_at      TEXT NOT NULL,
    last_detail  TEXT
) STRICT;
```

Three things worth stating because they look like omissions:

- **`events` is a surrogate-rowid table**, not `WITHOUT ROWID`. The rowid is the outbox's FIFO
  ordering key, so the drain is `WHERE exported_at IS NULL ORDER BY id` and cannot be scrambled by
  two events sharing a `recorded_at`.
- **Indexes stay at two.** No index on `recorded_at`, `cwd`, or `harness` — nothing queries them yet,
  and indexes are additive later.
- **The one `CHECK` is `ingested_via`**, our own closed vocabulary. Token arithmetic gets none, since
  clamps belong in the flatteners rather than in a constraint that can reject a row a harness
  legitimately produced. `'watch'` survives in the vocabulary as dead vocabulary; narrowing a `CHECK`
  is not an additive migration, so it drops the next time the schema is rewritten for a real reason.

`source_state` holds **no cursor**. It exists so `updated_at` can tell `status` when a pass last
succeeded — the only externally visible symptom a stopped timer has. `DELETE FROM source_state` stays
the documented "re-read everything" escape hatch.

`failures` is durable because every hook is a fresh process: an in-memory count dies with the turn
that made it. Two kinds are used in v1: `ingest` and `export`.

### Migrations

An ordered in-code list, `MIGRATIONS: list[Callable[[Connection], None]]`, with
`PRAGMA user_version == len(MIGRATIONS)` as the target. **Each migration applies inside its own
transaction together with its version bump**, so schema and version cannot disagree after a crash.
Forward-only, no downgrades. A store whose `user_version` **exceeds** the binary's refuses to run
with a clear error.

Migration 1 is the full DDL above. First-run creation needs no special path: it is `user_version = 0`
on an empty file, and opening with `BEGIN IMMEDIATE` before the checks means SQLite's own write lock
serializes two processes racing to create it.

### Retention

**The store keeps every event, and export adds no TTL to `ai_usage`.** A year of events is
single-digit megabytes; deleting is the one unrecoverable operation here. The Mongo half matters more
than it looks: the website's aggregation is a bare `$group` sum with no date `$match`, so a TTL would
not age out a stale window — it would silently shrink every all-time figure.

---

## Events

### Identity

Every event carries exactly one `identity` TEXT (NOT NULL, UNIQUE):

```
<harness-slug>:message:<per-request id>          -- claude:  opencode:  dsh:
<harness-slug>:fingerprint:<hash(...)>           -- only when the source delivers no id
```

The fallback hash is over `model + the five token counts + a 60 s bucket of recorded_at`.

Message ids are **opaque strings** — formats vary by upstream route (bare UUIDs, `msg_…`,
`chatcmpl-…`, even for one model), so nothing may parse or validate them. No harness in scope reaches
the fallback: all three always carry an id.

The fallback's two failure modes (identical back-to-back requests collapsing; the same fingerprint
from two harnesses) are impossible for keyed events and survive only within the rare id-less class,
narrowed to same harness + same minute.

**Considered and rejected:** the content fingerprint as *primary* identity (it needs time-bucketing
to be an index at all, and keeps both failure modes); `UNIQUE(harness, source_id)` (SQLite treats
NULLs as distinct in unique indexes, so it silently stops deduping exactly the fallback rows);
dropping id-less events (a silent undercount a cheap fallback covers).

### Field rules

**The five token counts are inclusive by construction:**

```
prompt_cache_hit_tokens + prompt_cache_miss_tokens == prompt_tokens
prompt_tokens + completion_tokens == total_tokens
```

Each harness's flattening is written to satisfy this. `reasoning_tokens` is **informational
provenance only** — it is a subset of completion on both OpenCode and DSH, and is never added to any
token total. The historical OpenCode bug was exactly this double-count.

`total_tokens` is **stored as the source reports it when the source carries one**; derive
`prompt + completion` only when it does not. OpenCode is the one source whose `tokens.total` is
independently derived, and the corpus prose disagrees about its formula — so verify the invariant
against the real db (`tokens.total == input + output + reasoning + cache.read + cache.write` on all
1909 rows carrying one) before storing it. If it does not hold, derive instead. **The website sums
`total_tokens`, so a wrong formula here is a wrong headline figure.**

`model` null ⇒ `cost_yuan` null. `recorded_at` is NOT NULL, with an **ingest-instant fallback** when
the source carries no timestamp — pricing needs an instant to select a card.

`turn`, `step`, `delegation_depth` are DSH provenance, carried for parity with the documents already
in `ai_usage`. `session_id` and `message_id` are stored on every harness that has them.

**No `source_path` and no `raw_json`.** The sources remain the raw store and `sync` re-reads them.
This also means a future `recompute` needs only stored columns.

### Normalization

Applied identically by every driver, between parse and price:

1. **Alias resolution** — model id → canonical name via the rate card's `[aliases]` table. This is a
   distinct step *before* pricing, not part of it (ADR-0004).
2. **`recorded_at` fallback** — the source's timestamp, else the ingest instant.
3. **Schema conformance** — the five counts present and inclusive.

---

## Rate card file

TOML, hand-edited. It ships **inside the package** as the default;
`~/.config/jwoo/rate-card.toml` is a **full-file override** when it exists; `rate_card` in
`config.toml` beats both. Full-file override, **never a merge** — merging reintroduces exactly the
overlap and gap questions ADR-0004 exists to make decidable.

Bundled so a fresh install prices correctly with zero setup and new-model pricing arrives with an
upgrade; overridable outside `site-packages` so `uv tool upgrade` cannot eat a hand-edited file.

### Shape

```toml
schema   = 1
currency = "CNY"

[aliases]
"deepseek/deepseek-flash"            = "deepseek-v4.1-flash"
"deepseek-v4-pro-202606"             = "deepseek-v4-pro"
"deepseek-v4-pro-0813"               = "deepseek-v4-pro"
"deepseek-v4-flash-0731"             = "deepseek-v4-flash"
"deepseek/deepseek-v4-flash-vision-exp" = "deepseek-v4-flash-vision-exp"

[[card]]
match = "glm-5.3-flash"
from  = 2026-01-01
to    = 2026-08-01          # exclusive; the discount card starts on this date
miss  = 1.0
out   = 4.0

[[card]]
match = "glm-5.3-flash"
from  = 2026-08-01
miss  = 0.5
out   = 2.0

[[card]]
match = "deepseek-v4-pro"
tz    = "Asia/Shanghai"
miss  = 4.0
hit   = 0.4
out   = 16.0
default = "offpeak"

[[card.band]]
name  = "peak"
start = "09:00"
end   = "12:00"
miss  = 8.0
hit   = 0.8
out   = 32.0
```

- **Matching is a substring key, longest match first, file order breaking ties.** This is today's
  semantics, and it is what stops `glm-5.3` matching `glm-5.3-flash`.
- **Both axes are half-open** — `[from, to)` and `09:00 <= t < 12:00` — so a `to` and the next
  `from` can be the same day, and touching bands do not collide.
- **One `tz` per card** governs both its windows and its date boundaries.
- Rates are **CNY per 1M tokens**. `hit` is optional and falls back to `miss` (the `p.hit ?? p.miss`
  the JS already has).
- `glm-5.3-flash`'s limited-time discount is **two cards meeting at a date boundary**, not a special
  case. The later one is open-ended, so the price stays discounted until someone adds a card from the
  day the promo ends.
- **The shipped `[aliases]` must reproduce the five `MODEL_ALIASES` mappings exactly.** The existing
  5,084 documents are named by them; a divergent alias splits one model's row on the site while every
  total stays correct.
- **Catch-alls stay deleted.** `moonshot-v1` and a bare `deepseek-v4` price null from here on. An
  unpriced model in the run summary is better than a plausible wrong number.

### Validation

**Load errors** (naming both offenders): overlapping date ranges for one `match`; overlapping
windows within a card; unknown keys anywhere; a banded card without `tz` or without `default`; a
window that would span midnight.

**Warning:** an interior gap — the loader cannot distinguish "we did not track this model yet" from
"typo".

**At ingest:** an instant no card covers, or a model no card matches, yields **null `cost_yuan` plus
a flag**, aggregated **once per distinct model per run** — never once per event, and never an error.

### Pricing arithmetic

The port matches `computeCostYuan` **bit for bit** on 1990 generated cases covering every
band-boundary instant (`08:59:59 / 09:00:00 / 11:59:59 / 12:00:00 / 13:59:59 / 14:00:00 / 17:59:59 /
18:00:00` Beijing), the `?? 0` nullish defaults, the `hit ?? miss` fallback, the
`Math.round(x * 1e6) / 1e6` rounding, and the `hit + miss > prompt` case. A plausible number the port
copies rather than diverges from — any guard belongs where the token columns are written.

`parity_check.py` plus the committed `fixtures.json` (2386 cases) is promoted to the real test suite.
It is stdlib-only and **node-free**, so parity stays enforceable after the JS oracle is gone.
`gen_fixtures.mjs` and `check_demo.mjs` retire to `tools/`, not shipped and not in CI.

### The one behaviour to reproduce deliberately

A **malformed rate card stores the event with `cost_yuan = NULL`** and counts a pricing failure.
Tokens are irreplaceable, cost is recoverable; refusing to store a valid event because a price file
is malformed inverts the priority and turns a cosmetic config error into data loss. A card that fails
to load behaves as "no card matched", which ADR-0004 already defines as null.

---

## Sources

Each harness gets one pure parser (raw record → zero or more events) behind one enumerate path.

### Claude Code

**Source:** the session transcripts under `~/.claude/projects` (`harnesses.claude.projects_root`).
No hook carries usage — `Stop`/`SubagentStop` payloads contain no `usage`, `model`, or
`total_cost_usd` field *by schema*; nothing is nulled by a proxy. `ApiReqDone` is fiction.

**The raw record is the chunk group** — the entries sharing one `message.id`. One group → exactly one
event.

**Grouping keys on `message.id`, never on adjacency.** 3,925 groups have non-assistant lines
physically interleaved between their assistant entries (6,298 `tool_result` blocks, 43 synthetic
`isMeta` user blocks). A driver grouping by adjacency misfires on ~20% of the corpus.

**Usage comes from the first entry whose `message.stop_reason` is non-null.** Interim chunks carry
`output_tokens: 0` under a null `stop_reason`; in 23,348 of 23,348 groups bearing a finish marker
that first entry already carries the group's full `output_tokens`. Emitting from the group's *first*
entry instead stores `output_tokens: 0` for 1,923 of 25,174 groups (7.6%) — permanently, because the
unique index makes it so.

Null `stop_reason` occurs **only as a leading prefix** (0 violations across the corpus), which is
what makes first-non-null sound.

**Completeness needs no clock.** A group is complete iff it is **not the file's trailing group**, or
it contains a non-null `stop_reason`. Streaming only appends at the end, so a partial group is always
the trailing one: skip the trailing group when it has no finish marker, and let the next pass re-read
it — free, because `sync` starts from zero and identity dedups. The residual deferrals are the 1,815
all-null groups, which are aborted requests with zero output tokens; they emit once a later entry
proves they ended, and they should, since the prompt tokens were burned.

**Enumerate must descend to depth 4** — `<project>/<uuid>.jsonl` *alongside*
`<project>/<uuid>/subagents/agent-<hex>.jsonl`. A `*/*.jsonl` glob silently misses 16.5% of corpus
bytes.

**Flattening:**

| Event field | Source |
|---|---|
| `message_id` | `message.id` |
| `session_id` | `sessionId` (camelCase; the `session_id` snake_case alias disagrees on some entries) |
| `model` | `message.model`, then aliased |
| `cwd` | **the entry's own `cwd`** — 31% of transcripts contain more than one, so session-level attribution puts worktree and subdirectory work on the wrong project |
| the five counts | `message.usage` |
| `recorded_at` | the entry's timestamp |

**Skip `<synthetic>` entries** (84 in the corpus, zero-filled usage, `service_tier: null`) on model.

**Identity is global** — `claude:message:<message.id>` — *not* per-file. 72 ids appear in two files
each; those are compaction/resume copies of the same request, not a second one.

**Keep the observed `version` as provenance.** The transcript format is officially internal and
version-breaking; a parser fix is applied by deleting that harness's rows and re-syncing — idempotent
by identity, and bounded by the retention window below.

**Hook wiring** — `~/.claude/settings.json`, hand-edited at an absolute path (hook execution does not
guarantee the shell's `PATH`):

| Event | Why |
|---|---|
| `Stop`, `SubagentStop` | the turn ended |
| `StopFailure` | a turn ending in an API error need not fire `Stop` |
| `SessionEnd` | sweeps a session's trailing group |

Synchronous, `timeout: 10`, shim command exactly `jwoo ingest claude` with **no env at all**.
`MONGO_URI` and `HARNESS_NAME` both leave `settings.json`. No `install-hooks` command.

**Free win:** the turn disappears from the parser entirely — no user-message boundaries, no per-turn
summing, no `isMeta` handling — so the three undercount bugs documented in `usage-lib.mjs` die
structurally rather than being ported carefully.

### OpenCode

**Source:** `~/.local/share/opencode/opencode.db` (read-only; `harnesses.opencode.db`). The cleanest
of the three: the stored assistant message **is** one API request. No grouping, no slicing, no turn
reconstruction.

**The driver assembles the record; the parser stays pure.** The `message.data` blob contains **no
`id` and no `sessionID`**, so they come from columns and a join:

- **sync** reads the `message` table, takes `id` from the `message.id` column, adds `sessionID` from
  the row and `cwd` from the `session` join, and treats the row's `data` blob as the base.
- **ingest** reads the plugin's event envelope from stdin and takes `data.info` **unwrapped**.

> The envelope's payload path is `$.info`, **not** `$.properties.info`. The `properties` wrapper
> describes the plugin hook argument, not what the database persists. A parser written against
> `properties.info` yields zero rows.

**Flattening** (the `data` blob's assistant shape carries `role`, `time.completed`, `parentID`,
`modelID`, `providerID`, `cost`, `tokens{input,output,reasoning,cache{read,write}}`, `finish`):

```
prompt_tokens            = tokens.input + tokens.cache.write + tokens.cache.read
completion_tokens        = tokens.output + tokens.reasoning
prompt_cache_hit_tokens  = tokens.cache.read
prompt_cache_miss_tokens = tokens.input + tokens.cache.write
total_tokens             = tokens.total (see the invariant check under Events)
```

The existing backfill added `reasoning` to the **prompt** side while passing `tokens.total` through
unchanged, so `prompt + completion ≠ total` and reasoning was counted twice. `total_tokens` — the
only column the website sums — stayed correct either way; what changes is the two columns that
compose it. This mapping restores the invariant.

**Completeness gates on `time.completed`, not `finish`.** The markers disagree: `time.completed` is
missing on 3 of 1956 rows, `finish` on 47. Gating on `finish` would discard all 47; gating on
`time.completed` lets 44 aborted requests emit — and they should, because **`tokens.input` is present
on 100% of rows, aborted ones included.** The abort is not what withheld the usage. Sync sweeps the
residue with SQL: a message with `time.completed IS NULL` whose `time_created` is older than a
safety margin is provably over and emits anyway.

**`input = 0` is not a liveness test** — 52 rows carry it, but only 3 are real requests (all
`kimi-k2.5`, prompt entirely cache-served); the other 49 are zero/aborted rows.

**`cwd` comes from the `session` join** (`session.directory`), which is 100% redundant with
`path.cwd` — unlike Claude, where one file can hold several. Do not read `session.model`: it is a
JSON *string* with a different inner key and is NULL on older sessions.

**OpenCode's own `cost` is provenance only** — the rate card stays authoritative.

**Identity** is `opencode:message:<message.id>`, no session scoping needed: globally unique, no
cross-session duplication, and **no `request_id` of any kind exists** in this source.

**Plugin** — `~/.config/opencode/plugins/`, hand-installed per machine, no `install-hooks` command:

- signals only on `properties.info.role === "assistant" && properties.info.time.completed !== undefined`;
- pipes its own envelope verbatim to `jwoo ingest opencode` — **no shell logic in the plugin**;
- is **fire-and-forget** (OpenCode does not await the hook), so it catches its own errors;
- is instantiated **once per directory**, filtering on `location.directory`.

`session.next.step.ended` — a durable per-step event carrying `cost` and `tokens` — is defined but
fires on zero local rows. It is the shape to migrate toward; a future parser can be added alongside
without disturbing identity, since both yield the same `message.id`.

### DSH

**Source:** `~/.dsh/sessions/<project-key>/<session-id>/session.jsonl.zstd` (`harnesses.dsh.home`,
`DSH_HOME` overriding). The log is DSH's canonical append-only record: one JSON event per line, one
`assistant/message` event per committed LLM API request. All 321 local events carry usage; 0 do not.
No completion gating and no abort special-casing — unlike Claude and OpenCode respectively.

**This is a port of a design that never ran.** `dsh-mongodb-usage-hook.mjs` imports `dshUsageToFlat`,
which `usage-lib.mjs` does not export — an ESM load-time failure — and Node v22.14.0 has no
`zstdDecompressSync`. **None of the 321 existing DSH requests are in Mongo.** Two places where the
JS's intent was wrong are corrected rather than ported.

**The headline trap: DSH's counts are disjoint, and the field names lie.** DSH's own adapter is
explicit:

```js
inputTokens:  usage.prompt_tokens - (cacheRead ?? 0)   // cache reads SUBTRACTED OUT
outputTokens: usage.completion_tokens                  // INCLUDES reasoning
```

So `inputTokens` is the **cache-miss** count, not the prompt. Reading it as `prompt_tokens` — the
mapping the field name invites — undercounts prompt tokens **112×** and cost **2.26×** on the real
corpus (CNY 4.07 → 1.80 across 321 events). The data corroborates independently: 314 of 321 events
have `cacheReadTokens > inputTokens`, impossible under an inclusive convention.

```
prompt_tokens            = inputTokens + cacheReadTokens
prompt_cache_miss_tokens = inputTokens
prompt_cache_hit_tokens  = cacheReadTokens
completion_tokens        = outputTokens
total_tokens             = prompt_tokens + completion_tokens
```

`reasoningTokens` is a **subset** of `outputTokens`, stored as provenance and never added to any
total. This was an inference from DeepSeek's schema with no local `total` to disambiguate, so it was
probed against all 321 events and holds: `reasoningTokens > outputTokens` occurs 0 times, max ratio
0.9832, and `outputTokens == 0` never occurs.

**`cacheWriteTokens` never appears** (0 of 321) and DeepSeek has no cache-write billing, so the DSH
path carries no cache-write column. In the OpenCode formula above, `tokens.cache.write` is likewise
generally absent — treat a missing cache-write as 0.

**The second trap: `assistant/chunk` carries the same usage.** Usage sits at **`data.chunk.usage`**,
not `data.usage`, with values deep-equal to the request's `assistant/message` — the same request
carried twice, 1:1 in every session (321/321, 0 differences), not a running total. **The commit point
is `assistant/message`, and only that.** A reader that scans for usage *anywhere* double-counts every
request. The naive error is different and worse-behaved: a lookup at `data.usage` finds **0 of 3,231**
chunk lines — a silent empty result, not a wrong number.

The usage chunk's `seq` is **exactly `message.seq − 2`** in every pair — a stable relationship a test
can assert.

**Flattening:**

| Event field | Source |
|---|---|
| `message_id` | `data.message.id` (a UUID; 321 unique, none shared across files) |
| `session_id` | the `session` header's `id`, which agrees with the log's path segment |
| `cwd`, `delegation_depth` | the `session` header |
| `model` | `data.message.model`, then aliased |
| the five counts | `data.usage`, reconstructed as above |
| `recorded_at` | the message's timestamp |

**The `session` header appears exactly once per file, at offset 0.** Read it on every pass.

**A project-key directory name encodes the source's absolute path** (`--Users-<name>-Developer-…--`),
so the path to a log is itself identifying — which is why DSH fixtures are reduced rather than
captured verbatim.

### Decoding zstd frames

`backports.zstd` — zero dependencies, the only candidate exposing `get_frame_size` / `get_frame_info`,
and API-identical to the stdlib `compression.zstd` added in 3.14, so the 3.12 floor costs nothing
later. Rejected: `zstandard` (viable and more mature, but lacks the frame-size API) and `pyzstd` (a
shim over `backports.zstd` adding two dependencies for zero capability).

Frames are independently decodable and **checksummed by construction** — the writer sets
`ZSTD_c_checksumFlag: 1`, so a flipped payload byte raises rather than decoding to silently wrong
bytes.

**Partial and corrupt are distinguishable without heuristics:** `decompressobj().decompress()` never
raises on truncation, returning `eof=False`; it always raises `ZstdError` on corruption. **Error
messages are not matched — they are not an API.**

**The JS magic-scan rule is discarded.** Inferring frame boundaries by scanning for `0x28B52FFD` is
unsound: that sequence occurs legitimately inside compressed payload (raw blocks store literals
verbatim), so it would "skip a corrupt frame" that was never a frame and silently discard good
events. Python uses `unused_data` to land exactly on each frame end; on a real `ZstdError` it skips
exactly one frame via the header's `get_frame_size`, falling back to a magic-scan resync **only** when
the header itself is unreadable.

**A torn trailing frame is withheld, never prefix-recovered.** DSH's own reader can recover the
readable prefix, but that prefix is re-decoded once the frame completes (every line processed twice),
and an un-finalised frame is precisely the data carrying no checksum. Stop at the last complete frame
and retry next pass.

DSH truncates the log to the last complete frame on crash repair, so shrink is expected and
irrelevant — every pass starts at zero.

**Accepted limitation:** `session/title-llm-request` and `web/deepseek-search-llm-request` are
genuine billed calls to `api.deepseek.com` whose usage **the log never records**. No reader of this
source can price them. This is a boundary of the log's content, not a parsing choice — recorded so it
is not rediscovered as a missing-events bug.

---

## Export

**Upsert-only, forever.** `export` never deletes, drops, or rebuilds, and ships no
`--rebuild`/`--re-push` flag: deletion is the one unrecoverable operation here, the upsert already
makes re-export free, and a capability whose blast radius is the entire collection must not sit
behind a flag a typo can reach. **Repair is `UPDATE events SET exported_at = NULL` followed by a
normal drain.**

**Every driver that commits a transaction then drains** — `ingest`, `sync`. The only thing that
differs is how much latency each can afford: `ingest` blocks a turn, so it gets the tight budget;
`sync` has nothing waiting, so its budget is generous.

### The exported document

The stored row, remapped. **Every `events` column ships except three** — `id`, `ingested_via`, and
`ingested_at` — with `identity` renamed to `_id`. Concretely: the site's fields (`harness`, `cwd`,
`model`, `cost_yuan`, the five token counts, `recorded_at`) plus the **six DSH-parity extras**
(`session_id`, `message_id`, `turn`, `step`, `delegation_depth`, `reasoning_tokens`).

`exported_at` is also dropped — it is outbox bookkeeping. This is stated as a rule rather than a
field count because ADR-0012's prose says "nine site fields" and then lists ten; the list is right
and the number is not, and the rule above is what the parity test should assert against.

```json
{
  "_id": "claude:message:msg_01ABC…",
  "harness": "Claude Code",
  "cwd": "/Users/…/activity-telemetry-client",
  "model": "deepseek-v4.1-flash",
  "cost_yuan": 0.0412,
  "prompt_tokens": 41230,
  "completion_tokens": 1810,
  "total_tokens": 43040,
  "prompt_cache_hit_tokens": 39000,
  "prompt_cache_miss_tokens": 2230,
  "recorded_at": "2026-09-19T09:12:44.587Z",
  "session_id": "…", "message_id": "msg_01ABC…",
  "turn": null, "step": null, "delegation_depth": null,
  "reasoning_tokens": null
}
```

**`ingested_via` and `ingested_at` are NOT pushed.** They explain the CLI's behaviour, and the
canonical store is where that belongs.

**`recorded_at` must cross a type boundary: ISO-8601 TEXT → BSON `Date`, truncated to
milliseconds.** The site's time-series pipeline does `$match` on `recorded_at` and `$dateTrunc` on
`$recorded_at`, so a string **breaks the charts while every totals figure still sums correctly** — a
partial, silent failure that raises nothing anywhere. Live documents carry ms precision, so ms is
parity, not loss.

**Nulls are pushed as explicit `null`**, not omitted (`model`, `cwd`, `cost_yuan`), so the document
is a faithful replica of the row rather than a shape that varies by row.

**`model` is pushed exactly as stored.** Aliasing happens at ingest; re-aliasing at export would make
the replica disagree with the row it replicates.

**`harness` is three frozen literals** — `claude` → `Claude Code`, `opencode` → `OpenCode`,
`dsh` → `DeepSeek Harness` — matching the collection's current `distinct('harness')`. The site groups
by `$harness` and renders one row per distinct value, so an env var that can rename a harness splits
every historical figure in two. `HARNESS_NAME` is ignored entirely; the workaround vars
(`DSH_HARNESS_NAME`, `OPENCODE_HARNESS_NAME`) are deleted by construction.

### The drain

- **Cap:** 500 documents inline, in **chunks of 100**, `ordered=False`.
- **Timeout:** `serverSelectionTimeoutMS`/`connectTimeoutMS` ≈ 1.5 s, `socketTimeoutMS` ≈ 2 s.
- A chunk reporting write errors **stops** the drain — if Mongo is unhealthy the next chunk fails
  too, and retrying inline is exactly the latency ADR-0007 forbids.
- Each chunk's successful `_id`s are marked in **one SQLite transaction**, so a crash mid-drain loses
  nothing: marked chunks stay marked, the rest stay pending.
- **`E11000` is success wearing an error's clothes** — a concurrent drain upserting the same `_id`.
  One retry, then treat as written.
- **`w: "majority"`** is set explicitly rather than inherited. Under the default `w: 1` the ack is
  primary-only, and a primary dying before replication leaves the document absent from Mongo while
  the store says exported — unrepairable, because nothing would reveal which document vanished.
  `retryWrites` and `journal` are set explicitly for the same reason.

### The circuit breaker

Durable, in `failures(kind='export')`, **because the process isn't**: every hook is a fresh process,
so an in-memory breaker trips and dies with the turn — every turn would still pay the full connect
timeout while the network is down.

Skip the inline drain when `count > 0 AND now - last_at < 60 s`. An attempt succeeds only if every
document in it was confirmed, so `count` resets to 0 **only on a fully-clean drain**; a partial write
keeps it tripped with its own `last_detail`. **`--follow` ignores the breaker** — it has no turn to
block.

`--follow` polls every 5 s, backing off to 60 s after consecutive failures, resetting to 5 s the
moment there is work. It never exits on drain failure.

### Index

`export` creates `{recorded_at: 1}` on `ai_usage` idempotently, **once per export process**. The
collection has only `_id_` today, so every time-series query the site runs is a collection scan, and
per-request events raise the document count rather than lowering it. Not a one-off script: the site's
charts should not depend on someone remembering to run it.

### Config and scope

`mongo_uri` is **optional for the usage engine**. Absent: the inline drain is a silent no-op and
`status` reports `export disabled: no mongo_uri`. **An explicitly invoked `jwoo export` fails loudly**
with that message — a silent no-op on a command a human typed reads as success. `track` keeps
fail-fast, because Mongo is the daemon's only store, not a replica.

The export client **cannot reuse `telemetry/storage.py`'s construction** — it builds
`MongoClient(config.mongo_uri)` with no timeout options at all. Build a bounded client for this path.

**Scope fence:** export reads and writes **only** `ai_usage`. `telemetry` and `keyboard_heatmap` stay
on the daemon's direct path — never read, never indexed, never TTL'd.

### Parity is a test, not a hope

The site is bare `$group` sums with **no coalescing**, so a renamed or missing field sums to `0`
silently. Over every fixture event the test asserts:

- the **key set exactly** — no more, no fewer, *including* that `ingested_via`/`ingested_at` are
  absent (this is the assertion that catches a later "helpfully add more fields" regression);
- per-key types — `recorded_at` is a `datetime` and not a `str`, tokens are `int`, `cost_yuan` is
  `float | None`;
- `_id == identity`;
- one hand-written **golden document** compared for full equality, so a value bug is caught and not
  merely a shape bug.

The adapter is a pure row→document function, so **the parity test needs no database.**

---

## Status and reports

### `jwoo status`

One read-only command, reporting:

- effective config path, and **each value's origin** (default / file / env / flag);
- canonical-store path, event count, last successful ingest, ingest failure count;
- rate-card path in effect, plus its ADR-0004 load warnings;
- Mongo reachability, the outbox's **pending count**, the **age of its oldest pending event**,
  `MAX(exported_at)` as the last successful export, the breaker's state, and the disabled line;
- telemetry permission state.

Oldest-pending **age** earns its place: a count cannot distinguish one slow turn from three weeks of
backlog, and a stalled drain is the failure this path has. "Last successful export" is **derived**
(`SELECT MAX(exported_at) FROM events`) rather than recorded in a column, so it cannot drift.

`--brief` is the same function with a flag, so the session header is provably a subset of what you
can get in full rather than a second implementation to drift. `--json` is supported.

### Reports

| Command | Question | Window |
|---|---|---|
| `today` | cost and tokens so far today, per model, with cache-hit rate | local midnight → now |
| `month` | the same, month-to-date | local month start → now |
| `projects` | all-time cost by `cwd`, folded to project labels | all time |
| `events` | the most recent events, one line each — model, cost, `cwd`, time | most recent N |

**Windows are local time**; `--tz` overrides. Exported `recorded_at` is UTC by contract with the
website, but the local query surface is a different consumer and "today" means local midnight to
local midnight. Reports are otherwise **stateless** — each computes its own bounds and never inherits
a hidden filter set by an earlier command. A CLI whose output depends on what you typed three
commands ago is a CLI you cannot trust.

`projects` **reuses `projectForCwd`'s substring folding** so the CLI and the site agree on what a
project is. `today` is the window the website structurally cannot show — its shortest range is a
rolling 24 h and its totals/by-model/by-project/by-harness pipelines carry **no `$match` at all** —
which makes it a materially new answer rather than a smaller one. `events` is the one view the site
has nothing like.

Reports read **the canonical store**, never Mongo: reading the replica would make the CLI's answers
depend on the drain having run.

**No query grammar.** A fixed set is the point of a front door: you reach for `/today` because you
already know it exists, and four named views over a nine-column table does not need a flag language.

Rendering is **ANSI text**, colour auto-off when not a TTY or when `NO_COLOR` is set.

---

## Interactive session

Bare `jwoo` on a TTY opens a command REPL: a `jwoo>` prompt accepting registered commands, plus
`/help` and `/exit`. **Not a TTY: print usage and exit non-zero without ever waiting on input** —
hooks, cron, and `launchd` all run with no terminal, and a bare `jwoo` that blocks on a prompt in
those contexts is a hang with no output.

**Commands dispatch in-process through the shared registry.** The session shells out to nothing:
subprocess dispatch would re-parse shell semantics from a string, reduce a command's result to an
exit code and scraped stderr, and make the shared registry a fiction — the two front-ends would share
a binary name rather than code.

**Config and the rate card are re-read before each command.** Both are hand-editable, and a
long-running session that caches them silently disagrees with a `jwoo status` run in another
terminal.

**Commands run blocking**, with no progress chrome for a two-second `sync`. **The session hosts no
standing process: `export --follow` is deliberately not available inside it** — hosting a drain would
reintroduce the resident process ADR-0013 rejected and hand it the session's lifetime.

**Errors print, then mark degraded status** — recorded in the same `failures` table `jwoo status`
reads. A session that prints an error and forgets it would be a second place where silence hides
data loss.

**Writing commands print one summary line, always, including when the count is zero** —
`sync claude: 0 new, 111,321 scanned` — because "found nothing" and "silently failed" currently look
identical. The numbers are illustrative; the rule is not.

**No** natural-language input, **no** `!` shell escape, **no** resumable context. *Session*
unqualified already collides with *Harness session* in the glossary.

**`/help` is generated from the registry, never hand-written**, and marks session-only commands
distinctly from shared ones.

### The opening header

Three lines at most, **all from local reads, no network at launch** — a slow or blocked Atlas
connection would freeze the session on open, and the durable export breaker answers "is Mongo
reachable" without leaving the machine:

```
jwoo · 12,431 events · 0 pending · last sync 09:12
rate card: packaged · mongo: last export failed 4m ago (3×)
warning: canonical store is empty — try `jwoo sync claude`
```

The third line appears only when there is genuinely nothing, and suggests the next action rather than
reporting zeroes. This header **is** `jwoo status --brief`.

### The daemon relationship — observed, never controlled

The session never starts or stops `jwoo track`. macOS permissions attach to the launch context, so a
daemon spawned by the session inherits the session's grants and dies with it unless deliberately
orphaned — at which point the session lies about what it controls, and two live daemons double every
figure in `telemetry`.

**`track` publishes the state that makes observing possible.** `TelemetryState` exposes only
`snapshot()` and `has_activity()`; nothing is on disk; an idle daemon logs nothing at all — so wedged
and working are indistinguishable. So `track` writes a runtime-state file at
`$XDG_STATE_HOME/jwoo/daemon.json`, else `~/.local/state/jwoo/daemon.json` — a **new** location,
since ADR-0005 covers config and ADR-0011 covers data and neither generalises.

```json
{ "pid": 48213, "started_at": "…", "last_flush_at": "…", "flushes": 412, "last_error": null }
```

Rewritten after each flush, removed on clean shutdown. **A present file whose pid is dead is a
*crashed* daemon, reported distinctly from one never started** — that distinction is the point. This
is a liveness and health record only: no collection, no document shape, no route through the
canonical store.

---

## The telemetry daemon

`jwoo track` runs the existing daemon unchanged: the same collectors, the same flush loop, the same
**direct-to-Mongo** path, the same swallow-a-failed-flush-and-retry-next-interval behaviour (state is
not cleared on a failed flush).

- `--interval SECONDS` overrides `telemetry.flush_interval_seconds`.
- `--once` runs one flush interval and exits — the only sane way to test the daemon without waiting
  five minutes.
- `track` is **fail-loud** and fails fast when `mongo_uri` is unset, because Mongo is its only store.

`telemetry/` ports into `jwoo_cli/telemetry/` with its collectors, `keymap.py`, and `permissions.py`
intact. **`AppCollector` stays unwired and `APP_WHITELIST` stays a constant** — see
[Not in v1](#not-in-v1).

**Collection names and TTLs are package constants, not config.** `telemetry`, `keyboard_heatmap`, and
the 1-year / 30-day TTLs are the website's document contract; exposing them turns a fixed contract
into a user preference. `scripts/create_ttl_indexes.py` ports as `tools/create_ttl_indexes.py`.

**Supervision is a plist template in the package** plus a documented `launchctl load -w …` line. No
`install-agent` subcommand — that would be building tooling, and the map rules it out. The telemetry
daemon's own launchd supervision is out of scope for this effort.

---

## Config & paths

`~/.config/jwoo/config.toml` (overridable by `--config`). Precedence:
**defaults < config file < environment variables < CLI flags**.

```toml
rate_card = "~/.config/jwoo/rate-card.toml"   # optional; replaces the packaged default

[mongo]
uri      = "mongodb+srv://…"                  # optional for the usage engine; secrets live here
database = "activity-telemetry"               # file mode 0600

[store]
path = "~/.local/share/jwoo/jwoo.db"

[sync]
interval_minutes = 5                          # the launchd timer's interval; no `watch` exists

[telemetry]
flush_interval_seconds = 300
mouse_dpi              = 72

[harnesses.claude]
projects_root = "~/.claude/projects"

[harnesses.dsh]
home = "~/.dsh"                               # DSH_HOME still overrides

[harnesses.opencode]
db = "~/.local/share/opencode/opencode.db"    # OPENCODE_DB still overrides
```

**Environment-variable names stay the existing ones** — `MONGO_URI`, `ACTIVITY_DB_NAME`,
`FLUSH_INTERVAL_SECONDS`, `MOUSE_DPI`, plus `DSH_HOME` — rather than being renamed to match the TOML
keys. That keeps the `env` block in `~/.claude/settings.json` working untouched, which is what keeps
the cutover to a command-string change.

`.env` and `.env.example` are **retired**; a `config.toml.example` carrying the full surface replaces
them.

| Path | Contents |
|---|---|
| `~/.config/jwoo/config.toml` | settings, mode `0600` |
| `~/.config/jwoo/rate-card.toml` | optional full-file rate-card override |
| `$XDG_DATA_HOME/jwoo/jwoo.db` | the canonical store, dir `0700` |
| `$XDG_STATE_HOME/jwoo/daemon.json` | daemon liveness record |
| `$XDG_DATA_HOME/jwoo/` | the pre-migration `ai_usage` dump (`0700`, zstd) |

**`HARNESS_NAME` is ignored entirely.** Claude Code exports it into every hook, which is why the
existing scripts invented `DSH_HARNESS_NAME` and `OPENCODE_HARNESS_NAME` so a DSH ingest running
inside a Claude hook wouldn't be mislabelled. The harness is never ambiguous at the call site, so the
only thing an ambient variable can do is corrupt an export-exact field. All three go.

### Packaging layout

```
jwoo_cli/
  __main__.py          entry point; bare-jwoo TTY gate
  cli.py               the shared command registry
  config.py            load_config(), precedence, origin tracking
  pricing/
    ratecard.py        TOML load, validation, computeCostYuan port
    rate-card.toml     the packaged default
  store.py             open_store(), migrations, DDL
  pipeline.py          the six stages
  sources/
    claude/{parser.py,driver.py}
    opencode/{parser.py,driver.py}
    dsh/{parser.py,driver.py,decoder.py,shim.py}
  export.py            row→document adapter, drain, durable breaker
  session.py           the REPL
  telemetry/           ported daemon (collectors, keymap, permissions)
  launchd/             plist template
tools/                 one-shot: migration, fixture capture, index creation
tests/
  fixtures/<harness>/<scenario>/
```

---

## Testing

### Fixtures

The fixture seam is **the driver, not the parser**, because most traps are properties of a *source*
rather than a record. One scenario directory holds a miniature **source** plus the events it must
yield; the test runs the real driver over it. A parser-only fixture cannot see the corpus's largest
grouping trap, because a chunk group handed in directly has already had the interleaving stripped
away.

Fixtures are **captured from real local data and then reduced** — never hand-authored, never
committed verbatim. The reduction rule is one sentence:

> **Every string value is replaced by a deterministic placeholder derived from a hash of the original
> and formatted to match that original's shape; every number, boolean, and null is preserved exactly,
> and so is the structure.**

Same input yields the same placeholder on any machine, so ids stay unique and identity strings stay
constructive; shape is preserved, so a path stays absolute, a UUID stays a UUID, and a model name
stays a substring the rate card can still `match`. Nothing survives that could carry a prompt, a file
path, a branch name, or a credential. Raw captures are never committed, so the "no raw payloads" rule
holds repo-wide.

**Why captured:** the `output_tokens: 0` trap in one line — hand-authoring encodes what the author
*believes* the source does, and 1,923 groups were believed to carry zero output until the corpus was
counted.

**Why reduced:** the minimum raw record is small (812 B Claude, 745 B OpenCode, 195 B DSH), but *every
one is dirty* — the literal `jwu02` appears 192,545 times across Claude's corpus, all 1,956 OpenCode
assistant rows carry `path.cwd`, DSH's project-key directory names encode the full home path, and the
Claude corpus contains `ghp_`/`AKIA`-shaped substrings.

### Layout

`tests/fixtures/<harness>/<scenario>/`, with per-harness source shapes that **must not be flattened**:

- **Claude** — a transcript tree keeping `<project>/<uuid>.jsonl` *alongside*
  `<project>/<uuid>/subagents/agent-<hex>.jsonl`. Depth-4 descent is itself a trap.
- **DSH** — **real `.zstd` bytes**. Re-compressing a reduced JSONL produces *different frames*, and
  frame boundaries are what is under test.
- **OpenCode** — a fresh SQLite file with a committed `schema.sql` and exactly two tables (`message`,
  `session`), reproducing the `data` blob's **absence** of `id`/`sessionID` — which *is* the assembly
  test.

Plus `expected.json` (full stored event objects, so a schema change breaks every scenario loudly) and
`provenance.json` (script version, capture date, source path with the home directory stripped, and
any mutation).

**The capture script is evidence, not a build step**: run by hand, output committed and thereafter
authoritative, never in CI. The corpus is live — one read watched Claude's group count drift ~20
units while it ran. **No `--snapshot` regenerate flag**: it would make accepting a real regression the
path of least resistance.

**Synthetic scenarios must say so.** The torn-frame and corrupt-frame cases have no real instance, so
they are built by mutating a real frame and their `provenance.json` declares `synthetic` with the
mutation recorded.

**A reduced DSH fixture cannot speak for DSH's writer** — reduction re-emits the frames, so it proves
things about *frame-walking*, never about how DSH chose to cut frames. State this in the fixture's own
`expected.json`.

### Trap coverage

A `TRAPS` manifest in the test module — trap name → scenario path → one-line claim — with a test
asserting every declared path exists, so a trap cannot silently lose its fixture. **18 scenarios:**

| Harness | Traps |
|---|---|
| Claude | interleaved non-assistant lines; undercount exposure; leading-prefix selection; trailing-group deferral; depth-4 descent; multi-`cwd` per file; cross-file identity dedup |
| OpenCode | `time.completed` gating; reasoning→completion mapping; `input == 0` ≠ dead row; `cache.read`/`cache.write` shape; driver assembly |
| DSH | `data.chunk.usage` duplicate; disjoint counts; contiguous frames; torn frame; corrupt frame; magic-bytes-inside-payload |

Statistical counts (the 0.9832 ratio ceiling, 3,115 first-entry instances) stay in the ADRs as
evidence — encoding them as fixtures would turn the suite into a database nobody maintains.

### Other suites

| Suite | Asserts |
|---|---|
| `test_pricing_parity.py` | the 2386 committed cases vs `computeCostYuan`, node-free |
| `test_ratecard.py` | load errors, the gap warning, the once-per-model-per-run flag |
| `test_store.py` | migrations, `STRICT`, the partial index, the unique index, `user_version` refusal |
| `test_export.py` | parity: key set, types, `_id`, the golden document — **no database needed** |
| `test_identity.py` | dedup across re-ingest; the fingerprint fallback |
| `test_config.py` | precedence ordering and origin reporting |

`test_main.py`-style lifecycle tests patch config and collectors rather than touching macOS APIs.

---

## Cutover runbook

The asymmetry the whole plan turns on: **sources expire, Mongo does not.**

| Source | Reaches back to |
|---|---|
| Claude transcripts | 2026-08-03 |
| OpenCode database | 2026-04-26 |
| DSH session logs | 2026-08-24 |

`ai_usage` holds Claude documents back to 2026-07-20, so **the oldest 463 have no transcript behind
them** and "re-derive everything" would silently mean "and lose them."

**The rule is per-harness and self-computing:** re-derive from source wherever a source reaches;
import legacy documents **only if `recorded_at` is strictly earlier than that harness's earliest
reachable source record.** Empty for OpenCode and DSH; everything before 2026-08-03 for Claude. A
date constant would rot; the computed boundary cannot.

**The tail enters the canonical store as `events`, never as a side-channel write to Atlas.** Writing
straight to Mongo would leave the store permanently unable to reproduce its own replica, and
`export`'s upsert-only rule could never repair it. Identity is `legacy:<harness>:<mongo _id>` —
unique, stable, so an interrupted import resumes instead of double-inserting. Every such row carries
`ingested_via = "migration:legacy"`, marking its one known defect: **turn-end timestamps, not request
timestamps.**

### Order

| # | Step | Rollback |
|---|---|---|
| 1 | CLI built; parsers pass fixture tests | — |
| 2 | **Dump** `ai_usage` → `$XDG_DATA_HOME/jwoo/`, `0700`, zstd | none needed |
| 3 | Importer writes the unreachable tail into `events` | delete the `migration:legacy` rows |
| 4 | `jwoo sync --all` backfills the store; `export` drains | clear `exported_at` / delete new rows |
| 5 | **Reconcile** against the dump (token conservation ≤ 0.5%) | **nothing destroyed yet** |
| 6 | Swap `Stop`/`SubagentStop` hook → `jwoo ingest claude`; install the launchd timer | restore `settings.json`; `launchctl unload` |
| 7 | Run live 7 days | revert step 6 |
| 8 | **Delete the legacy documents** | re-insert from the dump |

**Step 8 is the only irreversible one**, and it happens only after step 5 passes.

### Verification

**Token conservation at 0.5%, per harness per token type, against the dump.** The legacy per-turn and
new per-request pipelines were measured against each other over the shared window and agree to
**0.2–0.4%** on input, output, and cache-read tokens — that headroom is what makes 0.5% meaningful:
loose enough to absorb boundary effects, tight enough that a parser regression cannot slip through.

**Document counts are deliberately excluded.** The old path stored one document per *turn* and the new
one per *request* — 7.4× in the window measured — so comparing them fails by construction and teaches
nothing.

The legacy collection was confirmed clean, which is what makes a dump sufficient as a rollback
artifact: DSH 98 docs / 98 distinct `message_id`; OpenCode zero duplicates; Claude 11 duplicates in
3,111, all same-second artifacts of the legacy ±5 s find-then-insert.

### What the cutover touches

There is **no concurrent dual-write phase**. Running the old hook alongside the new path buys nothing
the backfill does not already provide, and both write into the same collection the site reads — whose
pipelines carry **no `$match`**, so a parallel window inflates every headline figure with nothing to
filter by.

**Only Claude has live traffic to cut over.** DSH has never run (the script fails at ESM load; none
of the 321 requests are in Mongo), and OpenCode has no hook wired today. The Claude hook in
`~/.claude/settings.json` is the one genuine rollback point, and it is a one-line command-string
change.

Two credentials retire at cutover, both plaintext today: the `MONGO_URI` in `settings.json`'s `env`
block, and the literal `mongoUri` in `~/.dsh/profiles/web/cordis.patch.yml`. Also to remove: the
configured-but-dead `dsh-mongo-usage-sync` plugin entry in that same file (its symlink target does not
exist), and the deployed scripts under `~/.claude/scripts/` — cutover must replace an installed
artifact, not just a repo.

**The migration scripts ship in the CLI repo**, as `tools/migration/` — one-shot utilities, no
subcommand wraps them. The `ai-usage` repo is deleted as soon as its code is ported, which would take
the import and reconciliation tooling with it.

### Two facts worth carrying into the build

- **The transcript ceiling moves.** Claude Code's cleanup deletes after 30 days by default, so the
  rebuild window shrinks with every day this sits. (`cleanupPeriodDays` is currently set to `99999`
  on this machine, so nothing is being pruned today — but the runbook should not depend on that.)
- **The site's figures stay whole, but its request density steps.** Re-derivation yields ~7.4
  documents where the old path yielded one. Token and cost totals survive; any *count of events*
  changes meaning at the cutover. This is a property of the old path being wrong, not of the new one.
- **`ai_usage` becomes a mixed-`_id` collection** — every existing document has an ObjectId `_id`,
  every exported one has the identity string. Harmless to the site (which never reads `_id`), but
  "replica or legacy" is decidable only by `_id` type, which is exactly what step 8 uses.

---

## Not in v1

Four items the map carried as fog are resolved here as **declared deferrals**, so a build session
never has to ask about them. None is built.

- **Telemetry through the canonical store.** Mouse/keyboard documents keep the daemon's
  direct-to-Mongo flush path. No route through SQLite, no export, no change to `telemetry` /
  `keyboard_heatmap`. The two data paths share config keys and nothing else.
- **`recompute`.** The name is reserved; nothing is built. **Consequence to carry:** ADR-0017 gates
  the pre-migration dump's deletion on `recompute` shipping, so with `recompute` unbuilt **the dump
  is retained indefinitely.** That is the correct outcome — the dump is the only repair path for the
  `migration:legacy` rows' turn-end timestamps — but it must be stated, not left implicit.
- **App-usage time.** `AppCollector` stays unwired; `APP_WHITELIST` stays a constant. Wiring it would
  add a document shape the website does not read, making it a data-contract decision in its own
  right. Tracked in state, never flushed.
- **Windows.** The usage engine is POSIX-path-only — `$XDG_DATA_HOME`, `~/.config`, `~/.local/state`.
  `jwoo track` keeps its existing partial Windows collectors, but the CLI's config and store paths
  need a Windows decision before the usage engine could run there, and that decision is not made.

### Out of scope entirely

Not deferred-until-later — ruled beyond this effort, and not to be reintroduced by a build session:

- **A new dashboard UI or a CLI-served HTTP API.** The existing website is the only consumer.
- **Changing the website's read shape.** Export reproduces the current contracts exactly.
- **The `notes` / knowledge-graph collection.** A different project.
- **New harness integrations** (Codex, Gemini CLI, …). The seam is designed; none is built.
- **Archiving the `ai-usage` repo.** Its code is ported and the repo is deleted; there is nothing to
  sequence around.
- **An `install-agent` subcommand, an OTLP receiver, and a `watch` command.** Each was considered and
  rejected on the record; none returns.
