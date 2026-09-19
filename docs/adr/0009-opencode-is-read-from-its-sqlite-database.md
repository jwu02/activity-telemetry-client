# OpenCode's source is its SQLite database — the assistant message row

`jwoo` reads OpenCode usage from `~/.local/share/opencode/opencode.db` (overridable via
`OPENCODE_DB`). It is the only harness whose source is a database, and it is the cleanest of the
three: the stored assistant message *is* one API request — probe-verified on 1956 local rows,
`cost`, `tokens`, `modelID`, `providerID`, `path.cwd` and `parentID` all present on 100% of them,
and exactly 1909 `step-finish` parts existing one-per-message, never more. No grouping, no
slicing, no turn reconstruction: the raw record is the message object itself. **Considered and
rejected:** the `opencode serve` SSE stream, whose TUI server is on a random port and whose
standalone instance would not see the TUI's sessions.

## Two entry points, one record shape, assembled by the driver

The same message is reachable two ways, and they do **not** hand over the same object. The
`message` table's `data` column is a JSON blob that contains **no `id` and no `sessionID`** —
`json_extract` returns NULL for all 1956 assistant rows. Conversely the durable `event` table
stores its payload with exactly two top-level keys, `sessionID` and `info`, *unwrapped*: the
`properties` wrapper in the research's `properties.info` describes the **plugin hook argument**,
not what the database persists, and a parser written against it yields zero rows.

So each driver assembles the record before the parser sees it — assembly is I/O, which drivers
already own, and it keeps the parser a pure function of one object, exactly as ADR-0007 requires:

- **sync / watch** read `message`, take `id` from the `message.id` column, add `sessionID` from
  the row and `cwd` from the `session` join, and treat the row's `data` blob as the base.
- **ingest** reads the plugin's event envelope from stdin and takes `data.properties.info`
  verbatim — it already carries `id` and its own `path.cwd`.

Where both paths have data they agree exactly: the stored event's `info` minus `id`/`sessionID`
is JSON-identical to the row's `data` in all 229 cases that have both.

## `watch` is wired for OpenCode — the triad is not uniform

> **Amended by [ADR-0013](./0013-there-is-no-watch-command-and-no-standing-process.md):** there is
> no `watch` command. Everything below about the `event` table, its `seq`, and `event_sequence`
> stands as written and is why the tail was *possible*; it is no longer a source anything reads.
> The `message`-table sync path described here is unchanged and is now the only OpenCode path
> besides the hook.

The map's charting notes recorded "the hook/watch/sync triad is fixed for all three harnesses."
That is now false in both directions: Claude Code wires hook + sync and deliberately not watch,
and OpenCode wires all three. The sources differ, so the drivers differ; uniformity was an
assumption, not a requirement.

The plugin fast path is wired as a thin trigger, `jwoo ingest opencode`, with the plugin piping
its own event envelope on stdin — **no shell logic in the plugin**, mirroring Claude's shim
contract and putting every extraction step in Python. The plugin is fire-and-forget (OpenCode does
not await the hook, so the plugin catches its own errors) and is instantiated **once per
directory**, filtering on `location.directory`, so N open project directories yield N instances
that between them see every directory. The plugin signals only on
`properties.info.role === "assistant" && properties.info.time.completed !== undefined`. Installing
it stays a hand-edited per-machine step, as with `~/.claude/settings.json` — no `install-hooks`
subcommand, which would amend the six-subcommand surface.

Watch earns its place here because OpenCode is the one source in this effort with a **proper
append-only cursor**: the durable `event` table (`aggregate_id` = sessionID, a per-session
monotonic `seq`, unique on `(aggregate_id, seq)`), with `event_sequence` holding the high-water
mark. Its cursor is an opaque `source_state` blob of per-aggregate `seq`, and it reads forward
from it. Sync carries **no watermark at all** — it enumerates the `message` table and dedups by
identity, because the `event` table has no timestamp column and `message` has no leading
`time_created` index (only the composite `session_id, time_created, id`), so a watermark would
cost a redundant index for nothing when identity dedup already makes re-reads free.

The catch, and the reason watch cannot be the only path: **the event log is not a superset of the
message table.** Only 22 of 101 local sessions have events, starting 2026-06-10, while messages
reach back to 2026-04-25 and are still written. Watch is a latency optimisation over sync, never a
correctness requirement — losing its cursor costs a re-read, never an event.

## Completeness is `time.completed`, not `finish`

`message.updated` fires repeatedly while streaming (~3.7× per message locally), so the fast path
must gate. The two available markers disagree: `time.completed` is missing on 3 of 1956 assistant
rows, `finish` on 47 (35 `MessageAbortedError`, 12 aborted), and `tokens.total` on exactly those
same 47. Gating on `finish` would discard all 47; gating on `time.completed` lets 44 aborted
requests emit. They emit because **`tokens.input` is present on 100% of rows, aborted ones
included** — the token data is not what the abort withheld, so the usage is real and discarding it
repeats the undercount class ADR-0008 went to some lengths to eliminate. The cost is that a
degenerate aborted row carries a missing-side token as 0 and a present-side token as real, so
`prompt + completion = total` does not hold for it; that is accepted rather than papered over.

Sync sweeps the residue with the same deferral logic Claude uses, expressed in SQL: a message
with `time.completed IS NULL` whose `time_created` is older than a safety margin is provably over
and emits anyway.

**`input = 0` is not a liveness test** — 52 rows carry it, but only 3 are real requests (all
`kimi-k2.5`, prompt entirely cache-served, e.g. `cache.read=13031, output=1377, total=14408`); the
other 49 are zero/aborted rows.

## Reasoning tokens belong to completion, not to the prompt

The five token columns come from DeepSeek's schema, so this harness's split is settled by it:
`reasoning_tokens` is *part of* `completion_tokens`, and `prompt_cache_hit_tokens` /
`prompt_cache_miss_tokens` partition the prompt. OpenCode reports the same quantities under
different names, with `tokens.total` derived as
`input + output + reasoning + cache.read + cache.write` (probe: 0 mismatches against all 1909 rows
carrying one). The mapping is therefore `prompt = input + cache.write + cache.read` and
`completion = output + reasoning`, with `tokens.total` passed through as `total_tokens`.

The existing backfill adds `reasoning` to the **prompt** side while passing `tokens.total` through
unchanged, so `prompt + completion ≠ total` and reasoning is counted twice. `total_tokens` — the
only column the website sums — stays correct either way; what changes is the two columns that
compose it. The new mapping restores the invariant.

## Identity and provenance

Identity is `opencode:message:<message.id>` (ADR-0003), and unlike Claude it needs no correction:
`message.id` is globally unique with no cross-session duplication, so no `(session, id)` scoping is
needed. OpenCode carries **no `request_id`** of any kind — the one local `LIKE '%request_id%'` hit
is a false positive inside a diff string in a user message. `session.version` and the database's
`user_version` are kept as provenance for drift, and a parser fix is applied by deleting that
harness's rows and re-syncing, idempotent by identity. `session.next.step.ended` — a durable
per-step event carrying `cost` and `tokens` directly, defined but firing on zero local rows — is
the shape to migrate toward; a future parser can be added alongside without disturbing identity,
since both yield the same `message.id`.
