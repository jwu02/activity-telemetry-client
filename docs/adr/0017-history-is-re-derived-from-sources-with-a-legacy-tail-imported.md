# History is re-derived from sources, with the unreachable legacy tail imported

The canonical store must be populated once, from the 5,114 documents already in the site's
`ai_usage` collection and the three harnesses' own sources. These are **not** interchangeable
sources, and the migration turns on one asymmetry: **sources expire, Mongo does not.**

Measured on this machine at the time of writing:

| Source | Reaches back to | Note |
| --- | --- | --- |
| Claude transcripts | 2026-08-03 | Claude Code deletes transcripts after 30 days |
| OpenCode database | 2026-04-26 | full history |
| DSH session logs | 2026-08-24 | full history, never yet ingested |

while `ai_usage` holds Claude documents back to 2026-07-20. **The oldest 463 Claude documents
have no transcript behind them any more**, so "re-derive everything from source" cannot
reproduce them — the instruction silently means "and lose them."

**The rule is per-harness, and self-computing: re-derive from source wherever a source reaches;
import legacy documents only for the window no source covers.** Rather than pinning three
hand-picked cutover dates, a legacy document is imported (and exported) only if its `recorded_at`
is strictly earlier than that harness's earliest reachable source record. For OpenCode and DSH
that window is empty and the import reduces to a no-op; for Claude it is everything before
2026-08-03. A date constant would rot; the computed boundary cannot.

**The imported tail enters the canonical store as events, not as a side-channel write to Mongo.**
ADR-0011 makes SQLite canonical and Mongo its replica, and ADR-0012 forbids `export` from ever
inserting a document the store does not hold. Writing these documents straight to Atlas would
leave the store permanently unable to reproduce its own replica, and `export`'s upsert-only rule
could never repair them. So a one-shot importer reads the dump, writes `events` rows, and the
ordinary drain carries them out like any other event. The tail's identity is synthesized as
`legacy:<harness>:<mongo _id>` — ADR-0003's grammar with a legacy scope — which is unique and
stable, so an interrupted import resumes instead of double-inserting. Every such row carries
`ingested_via = "migration:legacy"`, which keeps the one known defect visible and repairable:
**their timestamps are turn-end stamps, not request stamps** (see Consequences).

**Verification is token conservation, asserted at 0.5%, per harness per token type.** The legacy
per-turn pipeline and the new per-request pipeline were measured against each other over the
shared window and agree to **0.2–0.4%** on input, output, and cache-read tokens. That headroom is
what makes a 0.5% gate meaningful: loose enough to absorb the boundary effects below, tight enough
that a parser regression cannot slip through. **Document counts are deliberately not compared** —
the old path stored one document per *turn* and the new one per *request*, a 7.4× difference in
the window measured, so comparing them would fail by construction and teach nothing.

**The dump is the rollback artifact and the delete waits on verification.** `ai_usage` is dumped
whole to `$XDG_DATA_HOME/jwoo/` (`0700`, zstd) before anything is destroyed. The order is dump →
import → export → reconcile → *then* delete; if reconciliation fails, nothing has been lost. The
dump is redundant with SQLite from the moment the import succeeds, so its deletion is gated on
`recompute` shipping, not on a date — `recompute` is what can re-price or repair those rows
without it.

**Cutover swaps the hook once; there is no concurrent dual-write phase.** Running the old hook
alongside the new path buys nothing the backfill does not already provide, because the new path
re-derives from sources after the fact — and the old hook writes into the same collection the new
export targets, so running both only widens the window in which the site's figures are inflated.
The window matters more than it sounds: the site's totals, by-model, by-project, and by-harness
pipelines carry **no `$match`**, so old and new documents sum together with nothing to filter by.

**Consequences, in the order they bite:**

- **The site's lifetime figures stay whole, but its request density steps.** Re-derivation yields
  ~7.4 documents where the old path yielded one, because a turn is many requests. Token and cost
  totals survive; any *count of events* changes meaning at the cutover. This is a property of the
  old path being wrong, not of the new one.
- **The imported tail's timestamps are turn-end stamps.** A legacy Claude turn's `recorded_at` is
  the last request's timestamp, so a turn spanning midnight lands wholly on one side. This is
  invisible at month scale and is exactly what `ingested_via = "migration:legacy"` exists to mark,
  should a future pass want to spread them.
- **The migration scripts ship in the CLI repo, not in `ai-usage`.** That repo is deleted as soon
  as its code is ported, which would take the import and reconciliation tooling with it. They are
  one-shot utilities, not part of the CLI's surface: no subcommand wraps them.
- **The legacy collection proved clean, which is what makes the dump sufficient.** DSH: 98
  documents, 98 distinct `message_id`. OpenCode: zero duplicates. Claude: 11 duplicate documents
  in 3,111 (0.4%), all same-second artifacts of the legacy ±5s find-then-insert dedup. A re-insert
  from the dump therefore reproduces the prior state exactly, which is the whole basis for
  trusting it as the rollback artifact.

**Considered and rejected:** re-deriving everything from source (loses the 463-document
pre-2026-08-03 Claude tail, and with it an unknown slice of the site's lifetime totals);
importing the entire legacy collection as canonical history (simplest and most faithful to the
current numbers, but it makes an un-aliased, turn-bucketed, un-provenanced pipeline the permanent
source of truth for the very data this effort exists to replace); keeping the legacy documents
alongside the new ones indefinitely (they never collide — `_id = identity` — so nothing breaks,
but every all-time figure on the site stays permanently inflated by double counting, with no
mechanism that could ever notice).
