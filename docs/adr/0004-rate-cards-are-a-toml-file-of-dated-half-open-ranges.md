# Rate cards are a TOML file of dated, half-open ranges

The rate card is one hand-edited TOML file in the repo (`tomllib`, stdlib, no dependency). It
declares `schema` and `currency` once, an `[aliases]` table for relay-station model ids, and a
list of `[[card]]` entries. A card is a `match` — a substring key, longest match first, file order
breaking ties, exactly today's semantics — plus rates, plus two optional axes: an effective date
range and, within it, time-of-day bands. Ranges and band windows are both **half-open**
(`[from, to)`, `09:00 <= t < 12:00`), so `to` and the next card's `from` may be the same day, and
a band and its neighbour may touch without overlapping. A card carries one `tz` governing both
its windows and its date boundaries. Rates are CNY per 1M tokens, `miss`/`hit`/`out`, with `hit`
optional and falling back to `miss` — the `p.hit ?? p.miss` the JS already has.

`glm-5.3-flash`'s limited-time discount is two cards meeting at a date boundary rather than a
special case: list rates with a `to`, discount rates with a `from`. The discount card is
open-ended, so the price stays discounted until someone adds a card from the day it ends.

**Validation at load:** overlapping date ranges for one `match` and overlapping windows within a
card are hard errors naming both offenders; an interior gap is a warning, not an error; unknown
keys anywhere are errors (so a misspelled `hit` cannot silently bill cache hits at the miss rate);
a banded card must name a `tz` and a `default`; a window that would span midnight is rejected
rather than given wrap-around semantics.

**At ingest:** an instant no card covers, or a model no card matches, yields a null `cost_yuan` and
a flag — not an error and not a guess. Flagging is aggregated once per distinct model per run, not
once per event.

**Considered and rejected:** JSON (strictly better parsing, but it cannot carry the `EDIT these
rates` comment or the provenance URLs that make this file maintainable — those are load-bearing);
YAML (keeps comments, but needs PyYAML and makes date-vs-string depend on whether the library
implements YAML 1.1 or 1.2); inclusive `to` and wrap-around windows (both cost more confusion than
they save once every other boundary in the file is half-open); a per-entry `currency` with an FX
source (the stored column is `cost_yuan`; nothing needs a second currency); hard-erroring gaps
(the loader cannot distinguish "we did not track this model yet" from "typo"); restoring the
generic `kimi` / `moonshot` catch-alls the old map carried (an unpriced model showing up in the
run summary is better than a plausible wrong number — this accepts that `moonshot-v1` and a bare
`deepseek-v4` now price null).

**Consequences:** the ported arithmetic matches `computeCostYuan` bit for bit on 1990 generated
cases covering every band-boundary instant, the nullish defaults, the rounding, and the
`hit + miss > prompt` case — a plausible number the port copies rather than diverges from, so any
guard belongs where the token columns are written. Two things have no JS counterpart and so fall
outside parity: the date ranges themselves, and aliasing. `computeCostYuan` never aliases, so the
`[aliases]` table is an **ingest-path step applied before pricing**, not part of pricing — making
it one explicit step fixes an existing drift where `backfill-claude-usage.mjs` and
`mongodb-usage-hook.mjs` alias but `backfill-opencode-usage.mjs` and `dsh-mongodb-usage-hook.mjs`
pass the model straight through.
