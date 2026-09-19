# The canonical store is one strict WAL SQLite file that keeps every event

The canonical store (ADR-0001) is realized as a single SQLite file at
`$XDG_DATA_HOME/jwoo/jwoo.db`, defaulting to `~/.local/share/jwoo/jwoo.db`, in a
directory created `0700` and overridable by a `db_path` config key. `~/.local/share`
is where the XDG convention already puts tool data on this machine (`opencode`), and
it matches ADR-0005's decision to take config to `~/.config/jwoo/` rather than to a
macOS-native location — using `~/Library/Application Support` for the data half only
would be the worse inconsistency. There is no store to migrate: today's scripts
persist no local state at all (the `.ds_usage_state.json` entry in `.gitignore` is
residue from an abandoned design), so the file starts empty.

Every connection comes from one `open_store()` factory: `journal_mode=WAL` and
`busy_timeout=5000` (ADR-0006), `foreign_keys=ON`, and **`synchronous=FULL`**. FULL is
a deliberate departure from the `NORMAL` that WAL deployments usually pair with:
ADR-0007's "the commit comes first" is only load-bearing if the commit survives a
power cut, and transactions here are per-source-per-cycle rather than per-event, so
the cost is one fsync per ingest rather than one per API request. The WAL's defaults
handle checkpointing; there is no `VACUUM` in v1. Every table is declared `STRICT` —
the local SQLite is 3.51 and `STRICT` needs only 3.37 — which turns a flattener's type
bug into an error at the store boundary instead of a silently mistyped row.

The `events` table is a surrogate-rowid table — `id INTEGER PRIMARY KEY` beside
`identity TEXT NOT NULL UNIQUE`, exactly as ADR-0003 words it — rather than
`WITHOUT ROWID`. The rowid is not decoration: it is the outbox's FIFO ordering key, so
the drain is `WHERE exported_at IS NULL ORDER BY id` and cannot be scrambled by two
events sharing a `recorded_at`. Indexes stay at two: the implicit unique index on
`identity` (the whole correctness upgrade over find-then-insert) and one partial
index, `events_pending ON events(id) WHERE exported_at IS NULL`. No index on
`recorded_at`, `cwd`, or `harness` — nothing queries them yet, and indexes are
additive later. The only `CHECK` is on `ingested_via IN ('hook','watch','sync')`, our
own closed vocabulary; token arithmetic gets none, since clamps belong in the
flatteners rather than in a constraint that can reject a row a harness legitimately
produced (ADR-0003).

`source_state` is `WITHOUT ROWID` on `(harness, source_key)` — the one table where the
key is the row — with `updated_at`. `updated_at` is what lets `status` report a source
whose last successful pass has gone stale, the only externally visible symptom a
catch-up timer that has stopped firing has (ADR-0006). It holds **no cursor**:
[ADR-0013](./0013-there-is-no-watch-command-and-no-standing-process.md) removes the
standing process, so every pass reads its source from zero and there is no tail
position to store. This supersedes the `cursor BLOB` column this ADR originally
locked, whose stated justification (DSH's zstd frame header, ADR-0010) evaporated
with the tailer that would have resumed from it. ADR-0006's failure counts get their own table —
`failures(kind, count, last_at, last_detail)` — because every hook is a fresh process
and an in-memory count dies with the turn that made it; everything else `status`
shows is derived from `events` and `source_state`.

Migrations are an ordered in-code list with `PRAGMA user_version == len(MIGRATIONS)`
as the target, each applying inside its own transaction together with its version
bump, so schema and version cannot disagree after a crash. Forward-only, no
downgrades. A store whose `user_version` exceeds the binary's refuses to run rather
than operating on a schema it does not understand — the one failure a version integer
can actually catch. First-run creation needs no special path: opening with
`BEGIN IMMEDIATE` before the checks means SQLite's own write lock serializes two
processes racing to create the file, and the loser finds the schema already present.

**Retention: the store keeps every event, and export adds no TTL to `ai_usage`.** A
year of events is single-digit megabytes, so there is no space argument, and the
store's justification is being the copy that outlives its sources — deleting is the
only unrecoverable operation here, while the conservative choice is free because
deleting later is always available. The Mongo half is the surprising one: `telemetry`
expires at a year and `keyboard_heatmap` at a month, so a reader will reasonably ask
why `ai_usage` has none. Three reasons. The website's aggregation is a bare `$group`
sum over the cost and token fields with no date `$match`, so a TTL would not age out
a stale window — it would silently shrink every all-time figure. There is no TTL
today, so adding one is a new destructive behavior on the site's only data rather
than the preservation of an existing contract. And with SQLite canonical (ADR-0001),
Mongo is a replica, which makes history recoverable by re-export — so if retention is
ever wanted it belongs in a documented export-side policy, not as a side effect of
the drain.

**Considered and rejected:** `~/Library/Application Support` for the data directory
(consistent with macOS, inconsistent with the config path ADR-0005 already chose);
`synchronous=NORMAL` (the standard WAL pairing, but it re-opens exactly the loss
window ADR-0007's commit-then-drain ordering exists to close, to save one fsync per
source per cycle); `WITHOUT ROWID` for `events` (identity-clustered and one index
lighter, but every secondary index would then carry a full-length identity string,
and the outbox would lose its stable FIFO key); a `TEXT` cursor column (forces an
encoding decision into every driver, and DSH's header is genuinely binary); a generic
key-value `state` table absorbing both `source_state` and `failures` (the two have
different shapes and different lifetimes — per-source cursors are deleted wholesale to
force a re-read, counters must survive that); importing a migration tool such as
alembic (ADR-0003 already chose `user_version`); and application-level locking across
concurrent hook/sync/export processes (`busy_timeout` is the whole story, and a
writer that still loses the race exits 0 with a counted failure per ADR-0006).

**Consequences:** the drain doubles as the off-machine backup, since every event
reaches Mongo — so v1 specifies no separate backup mechanism for a store that is now
the sole durable copy of anything whose source has aged out. `STRICT` and the 3.37
floor are stated as facts about the local interpreter, not assumptions about every
machine. `DELETE FROM source_state` stays the documented "re-read everything" escape
hatch, and a retroactive recompute needs nothing new from the schema: clear
`exported_at` and the partial index makes the re-push free.
