# Claude Code's source is the transcript, read as per-request chunk groups

`jwoo` reads Claude Code usage from the session transcripts under `~/.claude/projects`.
No hook carries it: `Stop` and `SubagentStop` are per-turn, and their documented payloads
contain no `usage`, `model`, or `total_cost_usd` field at all — so the "the proxy nulls those
fields" reading that motivated the current hook is a misdiagnosis, and no rewiring repairs it.
The `ApiReqDone` `PostToolUse` branch is fiction (not a hook event, and not a valid tool name —
MCP tools are always `mcp__`-namespaced); it was never reachable, because no `PostToolUse` hook
is wired. **Considered and rejected:** OpenTelemetry's `claude_code.api_request`, which *is* the
documented per-request path and carries model, the four token counts, cost, and `request_id` —
but it is a push stream with no replay, so it can serve neither `sync` nor crash recovery nor a
history rebuild, and capturing it needs a standing OTLP receiver, the daemon ADR-0007 exists to
avoid; it is recorded as a candidate on the supervisor question rather than discarded. Also
rejected: the Agent SDK's `getSessionMessages()`, whose typed envelope is version-tolerant but
whose `message` payload is typed `unknown` — the fields this parser actually depends on stay
undocumented either way, so the dependency buys no reduction in the real risk.

What a transcript yields is not turns but requests. One API response is written as several
entries — one per content block — that share a `message.id`; they are always contiguous (0
violations across 18,990 ids) and always agree on `message.model`. So the parser's raw record is
the **chunk group**, and it emits exactly one event per group. Usage is read from the **first
entry whose `message.stop_reason` is non-null**: interim chunks carry `output_tokens: 0` under a
null `stop_reason`, and in 23,348 of 23,348 groups bearing a finish marker that first entry
already carries the group's full `output_tokens`. Emitting from the group's *first* entry instead
— which the unique `identity` index would then make permanent — stores `output_tokens: 0` for
1,923 of 25,174 groups (7.6%), every one of them a request whose output was non-zero: the
documented undercount class returning by a new route. Grouping is
*slicing*, not parsing, so it belongs to the per-driver enumerate path; the parser stays a pure
function over the group.

> **Partially amended by [ADR-0013](./0013-there-is-no-watch-command-and-no-standing-process.md):**
> this ADR was written with `hook + sync` wired and `watch` deliberately not, which ADR-0013
> confirms — there is no `watch` command, and Claude is hook + sync. Two things below change. The
> "holds the cursor short of it" mechanism is replaced by re-deriving the deferral on every pass,
> since sync no longer keeps a cursor; and OpenTelemetry's "recorded as a candidate on the
> supervisor question" resolves to *not now* — with no standing process, an OTLP receiver has no
> host. Everything about chunk groups, the finish-marker rule, and identity is untouched.

**Completeness needs no clock, because streaming only ever appends to the end of a file.** A group
is complete iff it is not the file's trailing group, or it contains a non-null `stop_reason`. So a
read that lands mid-response defers the trailing group and holds the cursor short of it, rather
than trusting a `Stop` to mean the writer has flushed — the docs state the transcript is written
asynchronously and may lag the in-memory conversation, and that the final message is not
guaranteed to be present at `Stop` time on all versions. The residual deferrals are the 1,815
all-null groups, which are aborted requests with zero output tokens; they are emitted once a later
entry proves they ended, and they should be, since the prompt tokens were burned regardless.
**Considered and rejected:** an mtime-based quiescence threshold (works, but puts a clock in a
rule that does not need one), and treating a non-zero `Stop` exit as a completeness signal (it is
not one, and it is actively dangerous — see below).

**Consequences:** the turn disappears from the parser entirely — no user-message boundaries, no
per-turn summing, no `isMeta` handling — so the three undercount bugs documented in `usage-lib.mjs`
die structurally rather than being ported carefully. Identity stays the global
`claude:message:<message.id>` (ADR-0003), *not* the per-file key suggested by the corpus survey:
compacted and resumed sessions copy prior entries into a new file, and those copies are the same
API request, not a second one. Enumerate must descend to depth 4 (`<project>/<uuid>/subagents/
agent-<hex>.jsonl`), where 218 files and 9,700 assistant entries carry their own ids; a
`*/*.jsonl` glob silently misses 16.5% of corpus bytes. `cwd` is read per entry, not per session —
31% of transcripts contain more than one, and reading it from the first user message (as the old
script does) attributes worktree and subdirectory work to the wrong project. The transcript format
is officially internal and version-breaking, so the observed `version` is kept as provenance and a
parser fix is applied by deleting that harness's rows and re-syncing, which identity makes
idempotent and which the 30-day retention window bounds. Finally, the hook that invokes this
parser **must be structurally incapable of exiting 2**: on `Stop`, exit 2 does not report an error,
it blocks the turn and continues the conversation. A bare `argparse` shim can reach that code path
on a bad argument, so the shim traps everything and exits 0.
