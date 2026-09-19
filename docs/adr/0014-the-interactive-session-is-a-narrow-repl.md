# The interactive session is a narrow REPL over the shared command registry

Bare `jwoo` on a TTY opens an *Interactive session* (ADR-0005 fixed the boundary; this ADR
fixes what sits on the other side of it). It is a read-eval-print loop in the Claude Code
house style: a `jwoo>` prompt that accepts registered commands, plus `/help` and `/exit`.
It carries no conversational state — no resumable context, no natural-language input, and
no shell escape. This ADR also settles the one thing the session needs from outside itself:
how it knows whether the telemetry daemon is alive.

**Commands dispatch in-process through the shared registry.** ADR-0005 required one registry
backing both front-ends so `/sync opencode` and `jwoo sync opencode` cannot drift; the only
mechanism that actually delivers that is calling the same function directly. The session
shells out to nothing. Subprocess dispatch was rejected outright: it re-parses shell
semantics from a string, reduces a command's result to an exit code and scraped stderr, and
makes the shared registry a fiction — the two front-ends would then share a binary name
rather than code, which is exactly the drift ADR-0005 exists to prevent.

**Config and the rate card are re-read before each command.** Both are hand-editable
files, and a long-running session that caches them silently disagrees with a `jwoo status`
run in another terminal. The files are tiny and a load is free, so the session never holds
a stale copy. Only `sync` and `export` care, but the rule is stated once rather than as an
exception.

**Commands are synchronous; the session hosts no standing process.** Bounded commands
(`sync`, a one-shot `export`, every report) run inline and block the prompt — progress
chrome for a two-second operation is worse than silence. Notably **`export --follow` is not
available inside the session.** ADR-0013 rejected a resident process for catch-up on
measured cost, and hosting a `--follow` drain would reintroduce one and hand it the
session's lifetime; the launchd timer plus the drivers' inline drains already keep the
outbox moving. `--follow` stays a subcommand for when a foreground drainer is explicitly
wanted, and the session reports the outbox from local reads instead.

**Errors print, then mark degraded status.** A failing command never ends the session, but
it also never merely scrolls away: the failure is recorded in the same `failures` table
`jwoo status` reads, and the opening header surfaces it. ADR-0006 accepted `ingest` exiting
0 only on the condition that failure is counted and visible where a person would look; a
session that prints an error and forgets it would be a second place where silence hides
data loss.

**The daemon is observed, never controlled, and `track` publishes the state that makes
observing possible.** The session does not start or stop `jwoo track`. macOS permissions
attach to the launch context, so a daemon spawned by the session inherits the session's
grants and dies with it unless deliberately orphaned — at which point the session lies
about what it controls, and two live daemons double every figure in `telemetry`. But
observation was impossible as written: `TelemetryState` exposes only `snapshot()` and
`has_activity()`, nothing is written to disk, and an idle daemon logs nothing at all, so a
wedged daemon and a working one were indistinguishable. So `track` writes a small
runtime-state file, rewritten after each flush and removed on clean shutdown:

```json
{ "pid": 48213, "started_at": "…", "last_flush_at": "…",
  "flushes": 412, "last_error": null }
```

at `$XDG_STATE_HOME/jwoo/daemon.json`, else `~/.local/state/jwoo/daemon.json` — a
**new** location, since ADR-0005 covers config and ADR-0011 covers data and neither
generalises. The file is a liveness and health record only: it adds no collection, no
document shape, and no route through the canonical store, so the map's parked "does
telemetry ever route through SQLite" question is untouched. A present file whose pid is
dead is a *crashed* daemon and is reported distinctly from one that was never started —
that distinction is the point, because the crashed-but-silent daemon is the failure mode
that is invisible today.

**Considered and rejected:** a prompt that accepts arbitrary text (a natural-language or
shell-like query surface is a parser, a grammar, and a test surface, and ADR-0005 already
provides `--json` for scripting); resumable conversational context (it collides with
*Harness session* in the glossary, which `CONTEXT.md` draws deliberately, and forces an
on-disk context format plus a "which context am I in" display); a repainting dashboard
(`jwoo` is the dashboard — the map puts a new one out of scope — and a line that repaints
while you type fights the prompt); a live Mongo probe to answer "is Mongo reachable" at
launch (a slow or blocked Atlas connection would freeze the session on open; the durable
export breaker in `failures(kind='export')` answers the same question from a local read);
and a `!` shell escape (it makes the session a shell, gives the REPL a mutation surface,
and turns "shell out to the subcommand" into the answer to every session limitation).

**Consequences:** the session is small enough to be uninteresting, which is the intent —
everything it does, the non-interactive surface already does. Exact output formats for the
header and per-command result lines are specified in the build spec, not here.
