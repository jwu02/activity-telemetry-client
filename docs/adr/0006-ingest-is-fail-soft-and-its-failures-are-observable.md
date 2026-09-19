# `ingest` exits 0 on failure; its failures are recorded so `status` can surface them

`jwoo ingest` is invoked from harness hooks, where a non-zero exit or a thrown error can
disrupt the user's turn. Today's `mongodb-usage-hook.mjs` already exits 0 silently when
`MONGO_URI` is unset, and that property is worth preserving deliberately rather than by
accident. So `ingest` is **fail-soft**: any internal failure — unreadable config,
unparseable payload, store unavailable — exits 0, with the reason written to a log.
`sync`, `watch`, `export`, and `track` are **fail-loud**, because they are run deliberately
and a silent failure there is merely an unreported one.

**The trap this accepts:** "exit 0, logged to a file nobody reads" is silent data loss,
which is the failure mode ADR-0001 exists to eliminate. The mitigation is therefore
load-bearing rather than optional — ingest failures increment a counter in the canonical
store, and `jwoo status` reports the last successful ingest alongside the failure count, so
the silence is detectable in the one place a person would actually look.

**Considered and rejected:** failing loud everywhere (a hook that throws in someone's
session is worse than a missed datapoint, and the harness gives no good place to surface
it); failing soft everywhere (a `sync` that quietly did nothing is indistinguishable from
one that worked); and exiting non-zero from `ingest` while swallowing the error (the worst
of both — it breaks the turn *and* reports nothing).
