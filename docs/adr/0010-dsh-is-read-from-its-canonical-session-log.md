# DSH's source is its canonical session log — the `assistant/message` event

`jwoo` reads DSH usage from `~/.dsh/sessions/<project-key>/<session-id>/session.jsonl.zstd`
(root overridable). **Corrected:** this ADR originally said `$DSH_HOME/sessions`; `DSH_HOME` is
unset on this machine and neither `~/.local/share/dsh` nor `~/.config/dsh` exists, so the default
root is the `~/.dsh` fallback. Note also that a **project-key directory name encodes the source's
absolute path** (`--Users-<name>-Developer-...--`), so the path to a log is itself identifying —
which is why DSH fixtures are reduced rather than captured verbatim
([ADR-0016](./0016-parser-fixtures-are-captured-from-real-data-and-scalar-reduced.md)).
The log is DSH's canonical, append-only record: one JSON event per line, one
`assistant/message` event per committed LLM API request. Probe-verified on the 9 local session
logs holding 321 `assistant/message` events: **every one carries a usage object** (0 without),
every one carries `data.message.id`, and the `session` header appears exactly once per file. No
grouping, no slicing, no turn reconstruction — the same clean shape ADR-0009 found in OpenCode,
reached through a file instead of a database.

The harness `id` is `dsh`, and identity is `dsh:message:<data.message.id>` (ADR-0003). No
correction is needed: `message.id` is a UUID, 321 unique, none shared across files. The 60s
content-fingerprint fallback is unreachable on this source.

## The JS tailer has never run, and cannot

This is a port of a design that was never executed. `dsh-mongodb-usage-hook.mjs` imports
`dshUsageToFlat` from `./usage-lib.mjs`, which exports no such symbol — an ESM named-import
failure at load time, so the script cannot start. Independently, the installed Node is v22.14.0,
where `zlib.zstdDecompressSync` is `undefined`; the decoder at its heart never existed either. The
`--watch` mode documented in its own header is installed nowhere. **None of the 321 existing DSH
requests are in Mongo.** Everything below is therefore a fresh design that inherits the JS file's
*intent*, and the two places where that intent was wrong are called out rather than ported.

## DSH's token counts are disjoint, and the field names lie

This is the source's load-bearing trap. DSH's own adapter is explicit
(`@deepseek-ai/dsh-llm-deepseek`, `mapUsage`):

```js
inputTokens: usage.prompt_tokens - (cacheRead ?? 0),   // cache reads SUBTRACTED OUT
outputTokens: usage.completion_tokens,                  // INCLUDES reasoning
```

with the doc comment "DeepSeek's `prompt_tokens` INCLUDES cache hits … the harness TokenUsage
convention is DISJOINT counts, so cache reads are subtracted out of `inputTokens`."

So `inputTokens` is the **cache-miss** count, not the prompt. Reading it as `prompt_tokens` — the
mapping the field name invites, and the one the never-written `dshUsageToFlat` would most
plausibly have made — undercounts prompt tokens by **112×** and cost by **2.26×** on the real
corpus (CNY 4.07 → 1.80 across 321 events). The data corroborates the source independently:
**314 of 321 events have `cacheReadTokens > inputTokens`**, which is impossible if `inputTokens`
were inclusive.

The canonical store's schema is inclusive by construction (ADR-0003: `hit + miss == prompt`,
`prompt + completion == total`), so the reconstruction is forced:

```
prompt_tokens             = inputTokens + cacheReadTokens
prompt_cache_miss_tokens  = inputTokens
prompt_cache_hit_tokens   = cacheReadTokens
completion_tokens         = outputTokens
total_tokens              = prompt_tokens + completion_tokens
```

`reasoningTokens` is a **subset** of `outputTokens` (the same relationship ADR-0009 had to undo on
OpenCode), so it is stored as an informational provenance column and never added to any token
total. **This was an inference from DeepSeek's schema with no local disambiguator** — DSH's usage
object carries no `total` field — so it was probed against all 321 real events, and the inference
holds: `reasoningTokens > outputTokens` occurs **0 times**, the maximum ratio is **0.9832** with 25
events above 0.9 and none crossing 1, and `outputTokens == 0` never occurs while
`reasoningTokens == 0` occurs 103 times. Additive is arithmetically impossible given `output` is
never 0 and reasoning tracks just under it — the signature of a partition of a fixed total, not of
two independent addends. `cacheWriteTokens` never appears — 0 of 321 — and DeepSeek has no cache-write billing, so
the DSH path carries no cache-write column rather than a permanently-null one.

A second trap sits adjacent: **`assistant/chunk` events also carry a usage object**, at
`data.chunk.usage` — **not** at `data.usage` — with values identical to the request's
`assistant/message`. It is the same request carried twice, 1:1 in every session — not a running
total. A tailer that selects "any event with usage" double-counts every request. The commit point
is `assistant/message`, and only that.

**Probe-confirmed on the current corpus, and sharper than originally stated.** The nesting matters
more than the duplication: `usage` is attached to the chunk whose `data.chunk.type == "usage"`, so
a lookup at `data.usage` finds **0 of 3,231** chunk lines — not a wrong number, nothing at all. Of
the two errors a reader can make, the naive one is a silent empty result rather than a
double-count, and the double-count needs a reader that scans for usage *anywhere* rather than at a
path. The 1:1 pairing is exact in all 9 sessions (321 `assistant/message` against 321 usage
chunks); the usage dicts are deep-equal in all 321 pairs with zero differences; and the usage
chunk's `seq` is **exactly `message.seq − 2` in every pair, no exceptions** — a stable relationship
a test can assert, and the anchor [ADR-0016](./0016-parser-fixtures-are-captured-from-real-data-and-scalar-reduced.md)'s
duplicate-usage scenario is built on.

## `sync` and `watch` are wired; there is no hook

> **Amended by [ADR-0013](./0013-there-is-no-watch-command-and-no-standing-process.md):** there is
> no `watch` command; DSH is sync-only, and the section below is the reason it has no hook rather
> than a reason to keep a tail. **The cursor section is superseded** — with every pass reading
> from offset 0, the header is re-derived on each read rather than stored, and no `{offset, header}`
> map exists. The decoder rules (checksummed frames, `unused_data` boundaries, the discarded
> magic-scan) are unaffected.

DSH has no shell-hook mechanism comparable to Claude Code's `settings.json`. It has a Cordis
plugin system (`dsh plugin --profile <name>`, profiles of pnpm-installed bundles plus a
`cordis.patch.yml`), and a `sessionTelemetry` service whose `SessionTelemetrySink` backend
receives per-event records — so a fast path is *possible*. **Considered and rejected**, for three
compounding reasons: the service accepts **one backend per context and a duplicate load throws**,
so a jwoo backend would have to displace the shipped OTel backend rather than sit beside it; the
record handed over is a redacted `SessionTelemetryRecord` projection, not the harness's raw
payload, which contradicts ADR-0007's "hooks pipe their harness's own raw payload verbatim"; and
the API is prerelease (`@deepseek-ai/dsh@0.1.1-rc.2`). A lighter `ctx.on('session/event')` seam
exists but carries the same install cost.

Against all of that, the canonical log is durable and replayable, so `sync` already provides
recovery and a plugin would buy only latency — latency `watch` already delivers by tailing the log
directly. This is the same conclusion ADR-0009 reached about OpenCode's watcher: watch is a
latency optimisation over sync, **never a correctness requirement**. Losing its cursor costs a
re-read, never an event.

## The cursor is a byte offset plus the session header

`source_state` holds one opaque blob for `dsh`: a JSON map of session-log path →
`{offset, header}`, where `header` is the parsed `session` line (`cwd`, `createdAt`,
`delegationDepth`; the session id is the log's path segment and the header's `id`, which agree).

The header is stored, not re-derived, because of a bug the JS design would have hit the moment it
persisted anything: the `session` header sits at **offset 0 only**, so a restart resuming from a
saved offset never sees it, and every subsequent event silently loses its `cwd`. The JS tailer
escaped this only because its state was in-memory and it always restarted at zero.

On size regression the file's entry is reset to offset 0 and re-read. DSH truncates the log to the
last complete frame on crash repair (`"Truncate the log file to offset bytes and fsync (discard
the crash tail)"`), so shrink is a real, expected event rather than a defensive guard. Recovery is
idempotent by identity: a truncation costs a re-read and never an event.

## Decoding: `backports.zstd`, and a corrupt rule that deliberately diverges

Frames are independently decodable and, decisively, **checksummed by construction** — the writer
sets `ZSTD_c_checksumFlag: 1` (`dsh-session-persistence-jsonl`), and `zstd -l` confirms XXH64 with
0 skipped frames across all nine logs. This matters because zstd writes no checksum by default: a
flipped payload byte would otherwise decode to silently wrong bytes with no error. Here it raises.

The decoder is `backports.zstd` (zero dependencies; the only candidate exposing the
`ZSTD_findFrameCompressedSize` / `ZSTD_getFrameHeader` equivalents, `get_frame_size` and
`get_frame_info`; API-identical to the stdlib `compression.zstd` added in 3.14, so the 3.12 floor
costs nothing later). **Considered and rejected:** `zstandard` (viable and more mature, but lacks
the frame-size API), and `pyzstd` (now a shim over `backports.zstd` that adds two dependencies for
zero capability).

Partial and corrupt frames are **distinguishable without heuristics**: `decompressobj().decompress()`
never raises on truncation of 1–10 bytes or header-only input, returning `eof=False`, and always
raises `ZstdError` on corruption. Error messages are not matched — they are not an API.

**The JS corrupt rule is discarded.** It inferred frame boundaries by scanning for the
`0x28B52FFD` magic, and on a decode failure skipped to the next magic — which is unsound, because
that byte sequence occurs legitimately inside compressed payload (raw blocks store literals
verbatim), so it would "skip a corrupt frame" that was never a frame and silently discard good
events. The Python decoder uses `unused_data` to land exactly on each frame end and never
magic-scans on the happy path; on a real `ZstdError` it skips exactly one frame using the header's
`get_frame_size`, falling back to a magic-scan resync only when the header itself is unreadable.
Parity with the JS matters for cost arithmetic (ADR-0004), not for the decoder — keeping this rule
to preserve parity would be cargo-culting a bug.

A **torn trailing frame is withheld, never partially recovered.** DSH's own reader can recover the
readable prefix of an incomplete frame (`decompressZstdPrefix`; `ZSTD_e_flush` deliberately
suppresses final-frame and checksum completion, so partial input decodes without error). The
tailer does not, because that prefix is re-decoded once the frame completes — every line in it
processed twice — and because an un-finalised frame is precisely the data that carries no
checksum. The offset stops at the last complete frame and the next poll retries.

## Known limitation: auxiliary LLM calls are invisible

`session/title-llm-request` and `web/deepseek-search-llm-request` are genuine billed requests to
`https://api.deepseek.com/anthropic/v1/messages` with `model: deepseek-v4-flash` — 4 in one
session of nine. The log records the **request but never its usage**, so no reader of this source
can price them. This is a boundary of the log's content, not a parsing choice, and it is recorded
here so it is not later rediscovered as a "missing events" bug.
