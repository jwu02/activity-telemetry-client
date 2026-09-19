# There is no `watch` command; catch-up is `sync` on a timer

The usage engine runs **no standing process**. The driver set is `hook` and `sync` only:
`ingest` for the two harnesses with a fast path (Claude Code, OpenCode), `sync` for all three,
and nothing that tails. Catch-up is `jwoo sync --all` on a launchd timer, default every 5
minutes, running a **full re-read** of every source with no incremental logic.

This removes the `watch` subcommand from the surface ADR-0005 locked at six. It is the only
subcommand that ever required a resident process, and the entire justification for one — latency
below the polling interval — does not survive measurement. A complete pass over the whole local
corpus costs **~2.3 s of CPU**: Claude's 699 transcripts and 372 MB parse in 1.98 s warm (111,321
entries, 0 unreadable), OpenCode's 34 MB database reads in ~260 ms, and DSH's 9 zstd logs and 4.4
MB decompress in ~80 ms. A stat-only sweep that proves nothing changed is 1.4 ms. Paying a
resident process — idle RSS, a PID to supervise, a crash mode, and a stale-cursor failure class —
to accelerate a 2.3-second idempotent operation that runs every five minutes is not a trade worth
making, and the timer's interval is the only lever: it already goes to one minute with no code
change if the fetches are ever missed for that long.

**The backstop is the point, and it is the same backstop.** `sync` re-reads a source's full
history and dedups by identity (ADR-0003), so it repairs a dropped hook, a crashed process, a
`SessionEnd` that never fired, and a parser bug alike. A tailer would have needed its own
per-harness cursor, its own logic for each source's failure mode, and its own answer to a missing
root.

**Considered and rejected:** keeping `watch` as a thin `while True: sync_all(); sleep(n)` loop
(the data would be identical to the timer's, so it buys nothing but a resident process);
keeping `watch` as a real tailer for OpenCode and DSH (whose only edge over `sync` is latency,
which the timer delivers without the process); an incremental sync that stats the tree and parses
only files whose mtime moved (an idle pass drops to near-free, but at two always-slightly-stale
sources of truth — the stored position and the filesystem — to save four seconds an hour); and
shipping an `install-agent` subcommand to write the launchd plist (a template and documented
`launchctl` steps are reversible in one `bootout`, and the surface stays at five).

**Consequences, in the order they bite:**

- **`Watch` is now historical vocabulary.** ADRs 0008, 0009, and 0010 each record a `watch`
  wiring decision — Claude deliberately unwired, OpenCode fully wired, DSH wired alongside sync —
  and each is amended by this one. The tails were correctly designed and then correctly abandoned
  when the standing process was ruled out; the source facts and identity decisions those ADRs rest
  on are untouched. `CONTEXT.md` marks *Watch* historical in the same way *Sync* marks *Backfill*.
- **The cursor concept is deleted, and with it the failure class.** `source_state` keeps its
  `(harness, source_key)` key and `updated_at` — which is what `status` reads to report a source
  that has stopped advancing (ADR-0011) — but loses its role as a tail position. Every pass reads
  from zero, so nothing needs DSH's log-path → `{offset, header}` map, no driver needs the
  `cursor BLOB` column (`ADR-0010`'s stored-not-re-derived header existed only because a resuming
  tailer never re-sees offset 0), and a corrupt, stale, or shrink-reset cursor is no longer a
  failure mode to handle because there is no cursor to corrupt.
- **Per-harness driver tables change shape.** Claude: hook + sync. OpenCode: hook + sync (the
  `event` table and its `seq` high-water mark stop being a watch source; ADR-0009's finding that
  `event` is *not* a superset of `message` is now a footnote rather than a reason to keep both).
  DSH: sync only.
- **`source_state`'s rows are rewritten every pass.** Freshness is now "when did a pass last
  succeed", not "where did a tail stop", so a died-mid-pass process leaves the previous pass's
  `updated_at` and `status` ages it normally.
- **Worst-case staleness is the interval plus the hook, not zero.** While a turn is active the
  hook keeps the site current, and the timer covers what hooks miss. Transient staleness is not
  lost data: an event is durable in SQLite the moment any path commits it, and the next pass
  sweeps anything a failed hook dropped (ADR-0006's accepted trap).
- **`'watch'` stays in `ingested_via`'s `CHECK` as dead vocabulary.** ADR-0011 closed that
  vocabulary at `('hook','watch','sync')`; no row can now carry `'watch'`, and the value survives
  only because narrowing a `CHECK` is not an additive migration. It is dropped the next time the
  schema is rewritten for a real reason, not for this one.
- **The telemetry daemon is deliberately excluded.** `track` is resident because it listens to
  input at 0% CPU until you type; the usage engine must not be. Their opposite resource profiles
  are an argument against folding them into one service at cutover.
