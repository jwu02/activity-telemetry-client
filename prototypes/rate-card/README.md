# PROTOTYPE — the rate-card file

Throwaway. Answers [Design the rate-card file format](https://github.com/jwu02/activity-telemetry-client/issues/4):
_can a dated, banded rate card be expressed as a hand-edited file, validated on
load, and priced identically to today's `usage-lib.mjs`?_

Everything here covers today's `PRICING` map, including the glm-5.3-flash
limited-time discount as a dated range.

## Files

| file | what it is |
| --- | --- |
| `demo.html` | **start here.** Double-click it. Drive the resolution by hand, or run the guided walkthroughs. |
| `rate-card.toml` | the proposed file, in full, with the comments kept |
| `rate-card.json`, `rate-card.yaml` | the same shape in the other two candidate formats, abridged, for comparison |
| `ratecard.py` | the ported logic — the part worth keeping |
| `parity_check.py` | checks `ratecard.py` against the real JS, and exercises every validation rule |
| `gen_fixtures.mjs` | generates ground truth by driving the real `usage-lib.mjs` |
| `check_demo.mjs` | checks the logic embedded in `demo.html` against the same ground truth |
| `fixtures.json` | generated: 2386 cases derived from `ai-usage/usage-lib.mjs` |

## Running the checks

```bash
node prototypes/rate-card/gen_fixtures.mjs > prototypes/rate-card/fixtures.json
python prototypes/rate-card/parity_check.py
node prototypes/rate-card/check_demo.mjs
```

`parity_check.py` prints 24 checks. Current result: **24 passing**

```
1. alias parity ................ ok (2386 cases)
2. price parity ................ ok (1990 cases)
   cost parity ................. ok (1990 cases)
3. dated-range behaviour ....... ok (396 cases, switch at 2026-08-01)
4. validation rules ............ 19 cases, all as intended
```

## What the prototype settles

**Format: TOML.** `tomllib` is stdlib (no dependency), dates are a real type
rather than strings a loader must parse and validate, and comments survive — the
`EDIT these rates` line and every provenance URL in today's file are load-bearing
and JSON cannot carry them. The only cost is that band blocks are a little
nested. YAML keeps comments but needs PyYAML and makes date-vs-string depend on
which YAML version the library implements.

**Shape: a card is `match` + optional date range + either flat rates or
`default` + windows.** The DeepSeek entries keep exactly today's model — a
default rate with named windows over it — and `glm-5.3-flash`'s discount becomes
two cards that meet at a date boundary. Dates are half-open, matching the
windows, so `to` and the next `from` can be the same day with no overlap and no
gap.

**Validation, at load:** overlapping date ranges for one `match` are a **hard
error** (the loader refuses the file and names both cards); interior gaps are a
**warning**, because the loader cannot distinguish "we did not track this model
yet" from "typo"; unknown keys are errors, so a misspelled `hit` cannot silently
disappear; banded cards must name a `tz` and a `default`.

**At ingest:** a model that matches nothing prices `null` and is flagged — it is
not an error. Flagging should be **once per distinct model per run**, not once
per event.

**Currency: CNY only**, declared once at the top of the file. `currency = "USD"`
is rejected rather than converted. The stored column is `cost_yuan`, and an FX
source is a subsystem nobody has asked for.

**Parity: achieved.** 1990 cases match `computeCostYuan` bit for bit, including
every band-boundary instant (``08:59:59/09:00:00/11:59:59/12:00:00/13:59:59/14:00:00/17:59:59/18:00:00`
Beijing), the `hit ?? miss` fallback, the `?? 0` nullish defaults, the
`Math.round(x * 1e6) / 1e6` rounding, and the negative-"fresh" case where
`hit + miss` exceeds `prompt`.

Parity deliberately does **not** cover two things, because the JS has no
counterpart for either:

- **Date ranges.** New behaviour, checked separately in section 3.
- **Aliasing.** `computeCostYuan` never aliases; the callers do, before pricing.
  The card file's alias table is therefore an ingest-path step, not part of
  pricing — see the drift note below.

## What the prototype found on the way

Things that are true today and worth a decision, independent of format:

1. **The pending edit drops the catch-all entries.** The working tree deletes
   `kimi`, `moonshot`, `kimi-k2` and `kimi-k1.5`. `moonshot-v1` used to price
   from the generic `moonshot` key; it now prices `null`. Substring matching
   means a card doubles as a family catch-all, so this is recoverable — but it
   is a silent historical-price change.
2. **`deepseek-v4` used to price at `deepseek-v4-pro` rates.** The change from
   `m.includes(k) || k.includes(m)` to `m === k || m.includes(k)` is what makes
   `glm-5.3` stop matching `glm-5.3-flash` — correct — but as a side effect a
   bare family name like `deepseek-v4` no longer matches anything.
3. **Two call sites never alias.** `backfill-claude-usage.mjs` and
   `mongodb-usage-hook.mjs` call `canonicalModelName` first;
   `backfill-opencode-usage.mjs` and `dsh-mongodb-usage-hook.mjs` pass the model
   straight to `computeCostYuan`. OpenCode models therefore never fold onto
   their canonical names. Making aliasing one explicit ingest-path step fixes
   this by construction.
4. **`hit + miss > prompt` produces a plausible number, not an error.** The port
   copies this deliberately rather than diverging. A guard belongs where the
   token columns are written.

## Decisions confirmed on review

- **Format: TOML.** As above.
- **Gaps: warn at load, null at ingest.** Overlaps remain a hard error.
- **Catch-alls stay deleted.** Findings 1 and 2 are accepted, not fixed: an
  unpriced model appearing in the run summary beats a plausible wrong number.
  `moonshot-v1` and a bare `deepseek-v4` price null from here on.
- **The discount start date stays a placeholder.** `2026-08-01` in
  `rate-card.toml` is marked `TODO(confirm)`; the real date gets filled in when
  the file lands in the real codebase. The discount card is open-ended, so when
  the promo ends someone adds a card from that day carrying the list rates back.

## Left open

- **Where the file lives.** The sample sits at the prototype path; the real
  location depends on the packaging decision, and hand-editing a file inside
  `site-packages` is a bad default.
