# Export upserts by identity, never deletes, and confirms the mark with a majority write

ADR-0007 fixed the *shape* of the drain — commit first, mark last, upsert with Mongo
`_id` = the event's `identity` — and left its mechanics unstated. Four of them turn out
to be load-bearing: the circuit breaker has to survive a process that dies every turn,
the mark has to be true across a primary failover, the exported document has to differ
from the stored row in exactly two ways, and the export path must not be able to destroy
the website's only data.

**The drain is incremental and destructive only in SQLite.** `export` upserts; it never
deletes, drops, or rebuilds, and ships no `--rebuild`/`--re-push` flag. Repairing a bad
export is `UPDATE events SET exported_at = NULL` followed by a normal drain — the escape
hatch ADR-0011 already documented. A full re-push is therefore always available and never
reachable by a flag that a typo can point at the whole collection. The migration's
historical rebuild is a different thing: one-time, involving legacy per-turn documents
that cannot be expressed as per-request events, and owned by the migration ticket rather
than by a standing command.

**The exported document is the stored row, remapped.** Exactly the nine site fields
(`harness`, `cwd`, `model`, `cost_yuan`, the five token counts, `recorded_at`) plus
`_id = identity` plus the six DSH-parity provenance extras (`session_id`, `message_id`,
`turn`, `step`, `delegation_depth`, `reasoning_tokens`) that today's DSH writer already
emits. `ingested_via` and `ingested_at` are **not** pushed: they explain the CLI's
behaviour, and the canonical store is where that belongs. `model` is pushed exactly as
stored — ADR-0004 makes aliasing an ingest step, and re-aliasing at export would make
the replica disagree with the row it replicates.

Two conversions are not optional. `recorded_at` is ISO-8601 TEXT in SQLite and must
arrive as a BSON `Date` truncated to milliseconds: the site's time-series pipeline does
`$match` on `recorded_at` and `$dateTrunc` on `$recorded_at`, so a string breaks the
charts while every totals figure still sums correctly — a partial failure that raises
nothing anywhere. And nulls (`model`, `cwd`, `cost_yuan`) are pushed as explicit `null`
rather than omitted, so the document is a faithful replica of the row instead of a shape
that varies by row. `$sum` ignores non-numerics either way, so the site is indifferent.

**The drain is bounded by client timeouts and a document cap, not by a deadline.** The
inline drain inherits the turn's budget — the Claude hook's is `timeout: 10` (ADR-0008) —
so it gets `serverSelectionTimeoutMS`/`connectTimeoutMS` ≈ 1.5 s, `socketTimeoutMS` ≈ 2 s,
and a cap of 500 documents, in chunks of 100 with `ordered=False`. A chunk that reports
write errors stops the drain: if Mongo is unhealthy the next chunk fails too, and retrying
inline is exactly the latency ADR-0007 forbids. `replaceOne(..., upsert=True)` racing
another drain on the same `_id` can raise `E11000`, which is success wearing an error's
clothes — one retry, then treat as written. The cap is the *inline* budget; `sync` commits
far more than a turn can, so its drain is generous — every driver that
commits a transaction then drains, because "events were committed" is what makes a drain
appropriate and the only thing that differs between drivers is how much latency they can
afford.

**The circuit breaker lives in the store, because the process doesn't.** Every hook is a
fresh process, so an in-memory breaker trips and dies with the turn — every turn would
still pay the full connect timeout while the network is down, the failure ADR-0007 exists
to prevent. The breaker is the durable `failures(kind='export')` row, which
ADR-0011's schema already provides: skip the inline drain when `count > 0 AND
now - last_at < 60 s`. An attempt succeeds only if every document in it was confirmed, so
`count` resets to 0 only on a fully-clean drain and a partial write keeps it tripped with
its own `last_detail`. `--follow` ignores the breaker — it has no turn to block.

**`exported_at` is written only after a majority-confirmed upsert.** ADR-0007's third
bullet claims the mark "can be trusted"; under the default `w: 1` that claim is a
primary-only ack, and a primary that dies before replicating leaves the document absent
from Mongo while the store says exported — with nothing to ever re-push it. That is the
one silent-loss path in a design whose point is that there isn't one, and it is not
repairable, because nothing would reveal which document vanished. So the export path sets
`w: "majority"` explicitly rather than inheriting a driver default; a few milliseconds on
a 100-document batch buys the property the ADR already claims. `retryWrites` and
`journal` are set explicitly for the same reason — a guarantee stated in code, not implied
by a driver version.

**The export path is a separate code path with shared config.** It reads and writes only
`ai_usage`. `MONGO_URI`/`ACTIVITY_DB_NAME` keep their names (ADR-0005) so the existing
environment keeps working, and `mongo_uri` is **optional** for the usage engine: absent,
the inline drain is a silent no-op and `status` says so — but an explicitly invoked
`jwoo export` fails loudly with a "no mongo_uri configured" message, because a silent
no-op on a command a human typed reads as success. `track` is unchanged: Mongo is the
daemon's only store, so it keeps failing fast. `telemetry` and `keyboard_heatmap` stay
on the daemon's direct path — export never reads them, never indexes them, never touches
their TTLs. The export client cannot borrow `telemetry/storage.py`'s construction, which
passes no timeout options at all; it is built for this path.

`export` creates `{recorded_at: 1}` on `ai_usage` idempotently, once per export process.
The collection has no index today beyond `_id`, so every time-series query the site runs
is a collection scan, and per-request events raise the document count rather than lowering
it. `status` reports the outbox's pending count, the age of its oldest pending event, the
time of the last successful export (`MAX(exported_at)`, derived rather than recorded so
it cannot drift), the breaker's state, and the disabled line. Oldest-pending *age* is the
one that earns its place: a count cannot distinguish one slow turn from three weeks of
backlog, and a stalled drain is the failure this path has.

`--follow` polls every 5 s, backing off to 60 s after consecutive failures and resetting
to 5 s the moment there is work. It never exits on drain failure. A one-shot `jwoo export`
exits nonzero on a failed drain; the inline drain keeps ADR-0006's exit 0 with a counted
failure. The unifying rule: the exit code reflects whether the thing the user asked for
happened — inline, the user asked for an ingest and the drain is opportunistic; explicit,
the user asked for a drain.

**Parity is a test, not a hope**, because the site is bare `$group` sums with no
coalescing: a renamed or missing field sums to 0 silently, so drift is invisible rather
than loud. Over every fixture event the parity test asserts the exported document's key
set exactly (no more, no fewer — including that `ingested_via` and `ingested_at` are
absent, the assertion that catches a later "helpfully add more fields" regression),
per-key types (`recorded_at` is a `datetime` and not a `str`, tokens are `int`,
`cost_yuan` is `float | None`), `_id == identity`, and one hand-written golden document
compared for full equality so a value bug is caught and not merely a shape bug. The
adapter is a pure row→document function, so the parity test needs no database. The
fixtures it consumes are the fixture ticket's to capture and redact; this ADR decides only
what is asserted against them.

**Harness display names are three frozen literals** — `claude` → `Claude Code`,
`opencode` → `OpenCode`, `dsh` → `DeepSeek Harness` — matching the three values already
in the collection. They are a contract with the site, not a per-machine preference: the
site groups by `$harness` and renders one row per distinct value, so an env var that can
rename a harness splits every historical figure in two. For the same reason the shipped
rate card's `[aliases]` must reproduce the five `MODEL_ALIASES` mappings exactly — the
existing 5,084 documents are named by them, and a divergent alias splits one model's row
while every total stays correct.

**Considered and rejected:** a `--rebuild` flag or a shadow-collection swap (deletion is
the one unrecoverable operation here, the upsert already makes re-export free, and the
migration's rebuild is one-time and belongs to its own ticket); a detached `jwoo export
--once` child spawned by `ingest` (the hook would pay ~20 ms regardless of the network,
but the hook's exit would no longer mean the outbox was attempted, and it reintroduces a
daemon by the back door); a wall-clock deadline over the whole drain (client timeouts plus
a document cap bound the same thing without a worker thread); an in-process breaker (dies
with the turn that tripped it); reinterpreting `failures.last_at` as "last attempt" so one
row could serve both the breaker and the status report (it makes `last_at` mean two things
depending on `count`, which is how a status display starts lying); a `last_success_at`
column by additive migration (a record of an attempt that can disagree with the table it
describes); re-aliasing `model` at export (makes the replica disagree with the row);
pushing all eight provenance fields (the two internals have no precedent in the site's
collection and describe the CLI, not the request); and index creation by a one-off script
rather than by `export` (the site's charts should not depend on someone remembering to
run it).

**Consequences:** `ingest` stays network-touching, so ADR-0006's "fast and non-fatal" is
enforced by the cap, the timeouts, and the durable breaker rather than by construction.
A majority write concern makes the inline drain a few milliseconds slower per 100
documents while Mongo is healthy. `ai_usage` becomes a mixed-`_id` collection during the
transition — every existing document has an ObjectId, every exported one has the identity
string — which is harmless to the site (it never reads `_id`) but means "replica or
legacy" is decidable only by `_id` type; the migration ticket inherits that fact, along
with the question of what to do about existing documents whose `model` strings predate the
canonical map. `status` gains a scan of `events` for `MAX(exported_at)`, unindexed by
design at this size.
