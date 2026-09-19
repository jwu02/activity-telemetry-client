# Queries are four flat subcommands, and `sync` gains `--all`

ADR-0005 locked the subcommand surface at five (`track`, `ingest`, `sync`, `export`,
`status`) and [Name the CLI](https://github.com/jwu02/activity-telemetry-client/issues/2)
assigned the local query surface to the interactive-session ticket rather than deciding it
there. This ADR settles it: **four report subcommands** — `today`, `month`, `projects`,
`events` — plus `status --brief`, and one amendment to the locked surface that is unrelated
to reports but was already exposed before this ADR was written.

`today`, `month`, `projects`, and `events` are **flat subcommands, not session-only slash
commands.** ADR-0005's shared registry is the reason: a report reachable only inside the
session is a second implementation of the same query, and `--json` inherited from the
global flags makes the non-interactive form worth having on its own. The session's `/today`
is a thin wrapper over `jwoo today`, exactly as `/sync` is over `jwoo sync` (ADR-0014).

**`status --brief` is the session's opening header.** ADR-0005 already specified `jwoo
status` down to reporting each config value's origin; giving the session a separate
abbreviated status would be a second thing to drift. The brief form is the same function
with a flag, so the header is provably a subset of what you can get in full.

**The reports, and what each answers:**

| Command | Question |
|---|---|
| `jwoo today` | cost and tokens so far today, per model, with cache-hit rate |
| `jwoo month` | the same, month-to-date |
| `jwoo projects` | all-time cost by `cwd`, folded to project labels |
| `jwoo events` | the most recent events, one line each — model, cost, `cwd`, time |

`today` is the window the website structurally cannot show: its shortest range is a rolling
24 hours and its totals, by-model, by-project and by-harness pipelines carry **no `$match`
at all** (`jwoo/lib/ai-usage/aggregation.ts`), so "today so far" is a materially new answer
rather than a smaller one. `projects` reuses `projectForCwd`'s substring folding so the CLI
and the site agree on what a project is. `events` is the one view the site has nothing like,
and it is cheap because the store holds exactly the nine site fields plus provenance — no
raw payloads (ADR-0003). Per-model and per-harness breakdowns get no commands: `today`
already prints per-model lines, and `harness` has three values.

**Windows are local time, `--tz` overrides.** Exported `recorded_at` is UTC by contract
with the website (ADR-0012), but the local query surface is a different consumer and
"today" means local midnight to local midnight. Reports are otherwise **stateless**: each
computes its own bounds per invocation rather than inheriting a hidden filter set by an
earlier command.

**`sync` gains `--all`, reconciling ADR-0013 with ADR-0005.** ADR-0013 specifies catch-up
as `jwoo sync --all` on a launchd timer, but ADR-0005 requires a harness positional on
`sync` and `watch`'s removal left no all-harnesses form. `--all` is mutually exclusive with
the harness positional and is the timer's invocation. It is recorded here rather than in
its own ADR because it is the same kind of change to the same locked decision, and
splitting two amendments of ADR-0005 across two documents would make the current surface
something a reader has to reconstruct.

**`recompute` stays reserved and unbuilt**, per ADR-0005 — this ADR adds no query grammar,
so it does not reopen that.

**Considered and rejected:** a single `jwoo report <window> [--by model|project|harness]`
(a flag grammar is a small query language to design, document and test, for a tool whose
stated job is saving keystrokes); reports reachable only inside the session (two
implementations of one query, and it forfeits `--json`); report commands that fetch from
Mongo so the CLI and the site show identical numbers (the canonical store is SQLite —
ADR-0001 — and reading the replica would make the CLI's answers depend on the drain having
run); a per-session or per-turn report (the site has no session dimension and neither does
the event schema); and adding the reports to the map's **Out of scope** fence, which covers
a new dashboard UI and an HTTP API, not a terminal read of the local store — the map's own
Notes had already assigned this surface here.

**Consequences:** the subcommand count goes from five to nine, which is the largest single
addition to a surface the map otherwise kept deliberately closed. The justification is that
all four are reads over a table that already exists, sharing one adapter and one folding
function with the site, and none of them introduces state. `jwoo status --json` remains the
machine-readable entry point for anything the reports do not cover.
