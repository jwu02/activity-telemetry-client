# Parser fixtures are captured from real data, then scalar-reduced

Every parser in this effort is a pure function over one raw record, but **almost none of the
traps it must survive live inside it**. Claude's chunk grouping, its interleaved-line problem,
and its completeness rule are properties of a *transcript file*; DSH's duplicate usage, torn
frames, and corrupt-frame skip are properties of a *stream of zstd frames*; OpenCode's record is
assembled by the driver from a row and a join. So the fixture's seam is **the driver**, not the
parser: one scenario directory holds a miniature *source* plus the events that source must yield,
and the test runs the real driver over it. A parser-only fixture cannot see 3,925 of the corpus's
chunk groups, because a group passed in directly has already had the interleaving stripped away.

Fixtures are **captured from the real corpus on this machine and then reduced**, never
hand-authored and never committed verbatim. The reduction rule is one sentence:

> **Every string value is replaced by a deterministic placeholder derived from a hash of the
> original and formatted to match that original's shape; every number, boolean, and null is
> preserved exactly, and so is the structure.**

Same input yields the same placeholder on any machine, so ids stay unique and identity strings
stay constructive; shape is preserved, so a path stays absolute, a UUID stays a UUID, and a model
name stays a substring the rate card can still `match`. Nothing survives that could carry a
prompt, a file path, a branch name, or a credential.

**Why captured rather than hand-authored.** The `output_tokens: 0` trap is the argument in one
line: hand-authoring encodes what the author *believes* the source does, and 1,923 groups were
believed to carry zero output until the corpus was actually counted. The same holds for
everything the probes turned up that no ADR predicted — 3,925 groups with non-assistant lines
interleaved between their assistant entries, null `stop_reason` occurring *only* as a leading
prefix (0 violations), DSH's usage chunk sitting at exactly `seq − 2` and byte-identical to the
message's. None of those were designed; all were discovered by reading real data.

**Why reduced rather than committed verbatim.** The minimum raw record a parser needs is small —
812 B for Claude, 745 B for OpenCode's assembled record, 195 B for a DSH chunk — but *every one of
them is dirty*: the literal token `jwu02` appears 192,545 times across Claude's corpus, all 1,956
OpenCode assistant rows carry `path.cwd`, DSH's project-key directory names encode the full home
path so even the file path is identifying, and the Claude corpus contains `ghp_`/`AKIA`-shaped
substrings. ADR-0003 guarantees the canonical store keeps no raw payloads, which would make a
verbatim fixture **the only place source text lands in this repo**. Reduction happens at capture
time and the raw capture is never committed, so the dirty form does not exist in git at all.

**Consequences, in the order they bite:**

- **A fixture is a directory**, `tests/fixtures/<harness>/<scenario>/`, holding the source in
  whatever shape that harness actually reads and an `expected.json`. The source shape is
  per-harness and *must not be flattened*: Claude's tree keeps `<project>/<uuid>.jsonl` alongside
  `<project>/<uuid>/subagents/agent-<hex>.jsonl`, because depth-4 descent is itself a trap
  (`*/*.jsonl` misses 16.5% of corpus bytes); DSH commits real `.zstd` bytes, because re-compressing
  a reduced JSONL produces different frames and the frame boundaries are the thing under test;
  OpenCode is a fresh SQLite file with a committed `schema.sql` and exactly two tables, `message`
  and `session`, reproducing the absence of `id` and `sessionID` from the `data` blob — which *is*
  the assembly test.
- **The capture script is evidence, not a build step.** It is run by hand, its output is committed
  and thereafter authoritative, and it never runs in CI: the corpus is live, and a single read
  watched Claude's group count drift ~20 units while it ran. Each scenario carries a
  `provenance.json` naming the script and version, the capture date, the source path with the home
  directory stripped, and any mutation applied. Re-running is a deliberate act during review.
- **Synthetic scenarios must say so.** The torn-trailing-frame and corrupt-frame cases have no real
  instance — there are 0 corrupt frames in 321 clean events — so they are built by mutating a real
  frame. Their `provenance.json` declares `synthetic` and records the mutation, so nothing is
  smuggled in as captured when it was constructed.
- **DSH fixtures cannot speak for DSH's writer.** Because reduction re-emits the frames, a reduced
  DSH fixture proves things about *frame-walking*, never about how DSH chose to cut frames. This is
  stated in the fixture's own `expected.json` rather than left to be rediscovered.
- **`expected.json` holds full events, plus a stated claim.** Full events so a schema change breaks
  every scenario loudly instead of passing forty scenarios that each check two fields; and for trap
  scenarios an extra assertion layer that writes the trap down in words ("two lines carry identical
  usage and only one event results"). A bare snapshot documents nothing — six months on, nobody can
  tell a regression from a correction — and a `--snapshot` regenerate flag would make accepting a
  real regression the path of least resistance.
- **Coverage is a checklist, not a distribution.** A `TRAPS` manifest in the test module maps trap
  name → scenario path → one-line claim, and a test asserts every declared path exists. Statistical
  counts (the 3,115 first-entry instances, the 0.9832 ratio ceiling) stay in the ADRs as evidence;
  encoding them as fixtures would turn the suite into a database that nobody maintains.

**Considered and rejected:** hand-authored fixtures (safe, but they encode assumptions — exactly
the failure that produced the `output_tokens: 0` class); verbatim captures (highest fidelity, and
uncommittable — see above); static placeholders such as a fixed `<string>` vocabulary (safe and
trivially auditable, but it destroys uniqueness, so every `message.id` collapses to one value and
grouping, identity, and dedup tests all go degenerate); base64-encoding binary payloads into a
single JSON envelope (uniform, but it makes every DSH fixture unreadable and undebuggable, in the
harness with the most traps); a nightly job regenerating fixtures and asserting agreement with the
live corpus (deterministically produces a diff on every run, by construction).
