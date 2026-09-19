# Activity Telemetry Client

The context for the personal-telemetry effort: a Python daemon collecting mouse/keyboard activity, and the AI-usage ingestion engine being specified to replace the current scripts — one CLI, one canonical local store, one export path to the website's MongoDB.

## Language

### The tool

**The CLI**:
`jwoo-cli` — the unified tool this effort specifies: runs the telemetry daemon as a subcommand and the usage-ingestion engine. Invoked as the `jwoo` command.
_Avoid_: llm-sync (old working name), the client, the script.

**Telemetry**:
Mouse/keyboard/app activity counts flushed per interval by the daemon — a separate data path from usage events.

**The website**:
The Next.js consumer (`jwoo`) reading Mongo aggregations; the only reader of exported data.

**Interactive session**:
The REPL that bare `jwoo` opens on a terminal: a front-end over the same commands as the non-interactive subcommands, not a separate surface. It observes the *Daemon* but never starts or stops it.
_Avoid_: session (unqualified — see *Harness session*), shell, TUI (it is not a full-screen interface). See [ADR-0014](./docs/adr/0014-the-interactive-session-is-a-narrow-repl.md).

**Daemon state**:
The runtime record the *Daemon* publishes about itself — pid, start time, last flush, flush count, last error — so a *Telemetry* daemon that has crashed is distinguishable from one that was never started. A liveness and health record only; it is not an *Event* and never enters the *Canonical store*.
_Avoid_: heartbeat, health, status (the `status` command reads this and much besides).

### Usage ingestion

**Harness**:
An AI coding tool that produces usage events (Claude Code, OpenCode, DSH).
_Avoid_: agent, provider.

**Event**:
One LLM API request's recorded usage — the atomic unit of the usage store.
_Avoid_: turn, record, entry.

**Turn**:
One user-to-assistant exchange; a derivation over events (one turn spans one or more events), never a stored unit.

**Chunk**:
One written fragment of a harness response as a source stores it — a single content block, so one response arrives as several chunks sharing one request's id.
_Avoid_: fragment, entry, line.

**Frame**:
One independently decodable, checksummed unit of a DSH session log — the granularity a tailer advances by and at which corruption is detected. Distinct from a *chunk*, which is a response fragment rather than a storage unit.
_Avoid_: chunk, block. See [ADR-0010](./docs/adr/0010-dsh-is-read-from-its-canonical-session-log.md).

**Harness session**:
One run of a harness: the scope a `session_id` names, spanning one or more turns and their events.
_Avoid_: session (unqualified — see *Interactive session*), conversation.

**Source**:
A harness's data origin that a parser reads (hook payload, transcript, session log, database).
_Avoid_: feed, stream.

**Driver**:
The per-harness reader that turns a *Source* into the raw records the parser consumes — enumerating
them, and assembling whatever the *Source* does not hand over directly. It is the seam a *Fixture*
tests, because most traps are properties of a source rather than of a record.
_Avoid_: reader, loader, adapter (that word is taken by export's row→document function). See
[ADR-0016](./docs/adr/0016-parser-fixtures-are-captured-from-real-data-and-scalar-reduced.md).

**Ingest**:
The fast path: a hook hands the CLI its harness's own raw payload, and the CLI parses, prices, and stores it.
_Avoid_: import (reserved for migration).

**Sync**:
Reconciliation: re-read a source's full history and store what's missing; idempotent by event identity. The standing path — run on a timer, it is what keeps a source current.
_Avoid_: backfill (the old scripts' name).

**Watch**:
_Historical._ The abandoned standing path: tail sources in the background and ingest as new data
appears. The tool runs no resident process, so catch-up is *Sync* on a timer.
_Avoid_: unless describing the design as it was before [ADR-0013](./docs/adr/0013-there-is-no-watch-command-and-no-standing-process.md), which is the only place this word still applies.

**Event identity**:
What makes two events the same event for dedup purposes: the harness-scoped id of the API request when the source carries one, else the event's content fingerprint within a coarse time bucket. One value on every event; ingest, watch, and sync all dedup through it.

**Reduction**:
Turning a *Source*'s real data into a *Fixture* by replacing every string value with a deterministic placeholder derived from it, while every number, boolean, and null — and the structure itself — is preserved exactly.
_Avoid_: redaction, scrubbing, anonymisation (each names what it removes; *Reduction* also names what it keeps, which is the point). See [ADR-0016](./docs/adr/0016-parser-fixtures-are-captured-from-real-data-and-scalar-reduced.md).

**Fixture**:
A miniature *Source* and the events it must yield, captured from real data and reduced — the unit that proves a parser and the driver that feeds it still agree. A fixture is not a simulator: it is one recorded case, and the events it expects are part of it.
_Avoid_: mock, stub, sample, golden file.

**Scenario**:
One named *Fixture* — a single recorded case, identified by the trap or behaviour it pins (`interleaved-lines`, `duplicate-usage`).
_Avoid_: test case, example.

### Pricing

**Rate card**:
A dated pricing entry: a model match, an effective date range, and rates — flat or time-of-day banded.
_Avoid_: price table, PRICING.

**Band**:
A time-of-day window within a rate card (e.g. peak), in a stated timezone.

**Stored cost**:
The cost recorded on an event at ingest, priced by the rate card in effect at the request's instant; never recomputed implicitly.

### Storage

**Canonical store**:
The local SQLite database — the source of truth for events.
_Avoid_: database (ambiguous with the website's Mongo).

**Outbox**:
The events already committed to the canonical store but not yet replicated to MongoDB; `export` drains it.
_Avoid_: queue, backlog, pending.

**Export**:
Replication from the canonical store into MongoDB Atlas, preserving the website's document contracts.

**Drain**:
One pass of export: the outbox's pending events upserted into MongoDB.
_Avoid_: flush (the daemon's word for its own write to Mongo), sync, push.

**Replica**:
MongoDB's standing relative to the canonical store: every event is copied there, and it is never the source of truth.
_Avoid_: mirror, backup.

**Parity**:
An exported document's agreement with the website's contract — field names, types, and nullability alike.
_Avoid_: fidelity, compatibility. Drift is the failure of parity, not a synonym for it.

**Legacy tail**:
The slice of the website's existing `ai_usage` documents that no *Source* reaches any more — for
Claude, everything before the transcripts' 30-day horizon. Imported once as ordinary *Events* so
the *Canonical store* stays complete; distinguished by its turn-end timestamps and its
`migration:legacy` provenance, not by a separate table.
_Avoid_: backfill (the old scripts' name), history, old data. See
[ADR-0017](./docs/adr/0017-history-is-re-derived-from-sources-with-a-legacy-tail-imported.md).
