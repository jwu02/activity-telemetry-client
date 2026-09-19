# `ingest` drains the canonical store to MongoDB; export is live, not scheduled

The website reads only MongoDB and has to update live: a scheduled batch job leaves the
day's usage invisible until the next run, and a daemon-only drainer makes liveness depend
on a process whose death is invisible. So the canonical store carries an **outbox** —
every event row has a nullable `exported_at` — and `ingest` drains unexported rows to Mongo
best-effort *after* committing them to SQLite, bounded by a short timeout and a circuit
breaker that skips the drain for a while once an attempt has failed. A standing drainer
(`jwoo export --follow`) catches whatever the inline attempt missed.

Three properties make this safe, and each is load-bearing:

- **The commit comes first.** SQLite is written before any network I/O, so an unreachable
  network can never lose an event.
- **The mark comes last.** `exported_at` is written only after a confirmed upsert, so
  "exported" is a claim the store can be trusted on — which is what makes `jwoo status`
  meaningful. A crash between the upsert and the mark re-pushes on the next drain.
- **Re-pushing is free.** Export upserts with Mongo `_id` = the event's `identity`
  (ADR-0003), so a drain is idempotent and may run as often as it likes. Delivery is
  at-least-once with idempotent apply, never exactly-once by coordination.

**Considered and rejected:** exporting synchronously *before* the commit (a network failure
then loses the event outright — the failure mode ADR-0001 exists to eliminate); draining
inline with no timeout or breaker (a hotel wifi adds seconds to every turn, and a hook
blocks the turn while it waits); a daemon-only drainer (liveness depends on a process whose
death is silent — the trap ADR-0006 names); and keeping export a purely manual command (the
website goes stale between runs, which is the thing this ADR is for).

**Consequences:** `ingest` is no longer network-free, so "fast and non-fatal" is enforced by
the timeout and breaker rather than by construction. The `events` table gains an
`exported_at` column plus a partial index over pending rows, amending the schema ADR-0003
locked. Hook latency becomes partly a function of the network while Mongo is healthy, and
near-zero once the breaker trips. A retroactive recompute now has a free repair path for
already-exported documents: clear `exported_at` and let the drain re-upsert them.
