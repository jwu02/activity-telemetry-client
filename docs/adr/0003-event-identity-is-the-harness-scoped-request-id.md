# Event identity is the harness-scoped per-request id, with a time-bucketed fingerprint fallback

Every event carries one `identity` TEXT (NOT NULL, UNIQUE) that the SQLite index dedups on:
`<harness-slug>:message:<per-request id>` (`claude:message:…`, `opencode:message:…`, `dsh:message:…`),
or — only when a source delivers no id —
`<harness-slug>:fingerprint:<hash(model + the five token counts + a 60 s bucket of recorded_at)>`.
Natural keys make the racy find-then-insert fingerprint + ±5 s window of the old scripts
(ADR-0001) unnecessary: hook, watch, and sync can re-ingest the same request idempotently, and
the fingerprint's known failure modes (identical back-to-back requests collapsing; one harness's
event dropped because another harness's identical-content event was seen first) are impossible
for keyed events and survive only within the rare id-less class, narrowed to same harness +
same minute.

**Considered and rejected:** the content fingerprint as primary identity (it needs time-bucketing
to be an index at all, and keeps both failure modes); a UNIQUE(harness, source_id) tuple (SQLite
treats NULLs as distinct in unique indexes, so it silently stops deduping exactly the fallback
rows); dropping id-less events (a silent undercount for a rare class a cheap fallback covers).

**Consequences:** message ids are opaque strings — their format varies by upstream route (bare
UUIDs, `msg_…`, `chatcmpl-…`), so nothing may parse or validate them. The schema around identity
(field list, nullability, provenance extras) is recorded on the ticket's resolution; versioning
is `PRAGMA user_version` with additive-only migrations, and a breaking change rebuilds the
canonical store from sources via sync rather than migrating in place.
