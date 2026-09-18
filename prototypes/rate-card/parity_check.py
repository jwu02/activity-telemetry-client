#!/usr/bin/env python3
"""PROTOTYPE — does the ported pricing match ai-usage/usage-lib.mjs exactly?

    node prototypes/rate-card/gen_fixtures.mjs > prototypes/rate-card/fixtures.json
    python prototypes/rate-card/parity_check.py

Sections 1-3 check the port against ground truth generated from the real JS.
Section 4 checks the new behaviour that has no JS counterpart: dated ranges and
load-time validation.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ratecard import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    RateCardError,
    compute_cost_yuan,
    load_rate_card,
    normalize_model,
)

HERE = Path(__file__).parent
DISCOUNT_START = date(2026, 8, 1)

# glm-5.3-flash is the one model whose card carries a date range, so the JS
# (which has no date dimension) cannot be its oracle. It gets its own section.
# Compare on the normalized name: the fixture set includes casing, whitespace
# and [1m]-suffixed spellings that all land on the same card.
DATED_MODELS = {"glm-5.3-flash"}


def is_dated(model: str | None) -> bool:
    return normalize_model(model) in DATED_MODELS

failures: list[str] = []
checks = 0


def check(ok: bool, label: str, detail: str = "") -> None:
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}{(' — ' + detail) if detail else ''}")


def main() -> int:
    fixtures = json.loads((HERE / "fixtures.json").read_text())
    card_file = load_rate_card(HERE / "rate-card.toml")

    print(f"fixtures: {fixtures['count']} from {fixtures['source']}")
    print(f"card file: {len(card_file.cards)} cards, "
          f"{len(card_file.aliases)} aliases — loaded clean\n")

    # ── 1. alias parity ────────────────────────────────────────────────────
    alias_bad = []
    for f in fixtures["fixtures"]:
        got = card_file.canonical_model_name(f["model"])
        if got != f["canonical"]:
            alias_bad.append((f["model"], f["canonical"], got))
    check(not alias_bad, "alias table matches canonicalModelName()",
          f"{len(alias_bad)} mismatches, e.g. {alias_bad[:3]}")
    print(f"1. alias parity ................ "
          f"{'ok' if not alias_bad else 'FAIL'} ({fixtures['count']} cases)")

    # ── 2. price/cost parity (models with no date dimension) ───────────────
    price_bad, cost_bad, n = [], [], 0
    for f in fixtures["fixtures"]:
        if is_dated(f["model"]):
            continue
        n += 1
        at = datetime.fromisoformat(f["at"].replace("Z", "+00:00"))
        resolved = card_file.resolve(f["model"], at)
        got_price = (
            None
            if resolved is None
            else {
                "miss": resolved.rates.miss,
                "hit": resolved.rates.hit,
                "out": resolved.rates.out,
            }
        )
        want_price = f["price"]
        if got_price != want_price:
            price_bad.append((f["model"], f["at"], want_price, got_price))
        # The JS never aliases inside computeCostYuan, so the port must not
        # either — the fixture passes the raw model name.
        got_cost = compute_cost_yuan(f["model"], f["flat"], at, card_file)
        if got_cost != f["cost"]:
            cost_bad.append((f["model"], f["at"], f["cost"], got_cost))
    check(not price_bad, "band/rate selection matches resolvePrice()",
          f"{len(price_bad)} mismatches, e.g. {price_bad[:3]}")
    check(not cost_bad, "cost matches computeCostYuan() bit for bit",
          f"{len(cost_bad)} mismatches, e.g. {cost_bad[:3]}")
    print(f"2. price parity ................ "
          f"{'ok' if not price_bad else 'FAIL'} ({n} cases)")
    print(f"   cost parity ................. "
          f"{'ok' if not cost_bad else 'FAIL'} ({n} cases)")

    # ── 3. the dated card, against its own expectation ─────────────────────
    dated_bad, n = [], 0
    for f in fixtures["fixtures"]:
        if not is_dated(f["model"]):
            continue
        n += 1
        at = datetime.fromisoformat(f["at"].replace("Z", "+00:00"))
        resolved = card_file.resolve(f["model"], at)
        want = (0.4, 0.115, 1.4) if at.date() >= DISCOUNT_START else (0.8, 0.23, 2.8)
        got = None if resolved is None else (
            resolved.rates.miss, resolved.rates.hit, resolved.rates.out)
        if got != want:
            dated_bad.append((f["at"], want, got))
    check(not dated_bad, "the glm-5.3-flash discount switches on its start date",
          f"{len(dated_bad)} mismatches, e.g. {dated_bad[:3]}")
    print(f"3. dated-range behaviour ....... "
          f"{'ok' if not dated_bad else 'FAIL'} ({n} cases, "
          f"switch at {DISCOUNT_START})")

    # ── 4. load-time validation ────────────────────────────────────────────
    print("\n4. validation rules:")
    print(validate())

    print(f"\n{checks} checks, {len(failures)} failing")
    for f in failures:
        print(f"  FAIL {f}")
    return 1 if failures else 0


HEADER = 'schema = 1\ncurrency = "CNY"\n'

CASES: list[tuple[str, str, str | None, str | None]] = [
    # (label, toml body, expect_error_substring, expect_warning_substring)
    (
        "two cards overlap for one model",
        '[[card]]\nmatch="glm-5.3"\nfrom=2026-01-01\nto=2026-06-01\nrates={miss=1,hit=1,out=1}\n'
        '[[card]]\nmatch="glm-5.3"\nfrom=2026-05-01\nrates={miss=2,hit=2,out=2}\n',
        "overlap", None,
    ),
    (
        "an interior gap for one model",
        '[[card]]\nmatch="glm-5.3"\nto=2026-06-01\nrates={miss=1,hit=1,out=1}\n'
        '[[card]]\nmatch="glm-5.3"\nfrom=2026-07-01\nrates={miss=2,hit=2,out=2}\n',
        None, "nothing is in effect",
    ),
    (
        "adjacent ranges (to == next from) are legal",
        '[[card]]\nmatch="glm-5.3"\nto=2026-06-01\nrates={miss=1,hit=1,out=1}\n'
        '[[card]]\nmatch="glm-5.3"\nfrom=2026-06-01\nrates={miss=2,hit=2,out=2}\n',
        None, None,
    ),
    (
        "a typo'd rate key",
        '[[card]]\nmatch="glm-5.3"\nrates={miss=1,hitt=1,out=1}\n',
        "unknown rate key", None,
    ),
    (
        "a typo'd card key",
        '[[card]]\nmatch="glm-5.3"\nratess={miss=1,hit=1,out=1}\n',
        "unknown key", None,
    ),
    (
        "rates missing `miss`",
        '[[card]]\nmatch="glm-5.3"\nrates={hit=1,out=1}\n',
        "must set `miss`", None,
    ),
    (
        "a negative rate",
        '[[card]]\nmatch="glm-5.3"\nrates={miss=-1,hit=1,out=1}\n',
        "must not be negative", None,
    ),
    (
        "banded card with no tz",
        '[[card]]\nmatch="glm-5.3"\ndefault={miss=1,hit=1,out=1}\n'
        '[[card.band]]\nwithin=["09:00-12:00"]\nrates={miss=2,hit=2,out=2}\n',
        "`tz`", None,
    ),
    (
        "banded card with no default",
        '[[card]]\nmatch="glm-5.3"\ntz="Asia/Shanghai"\n'
        '[[card.band]]\nwithin=["09:00-12:00"]\nrates={miss=2,hit=2,out=2}\n',
        "must set `default`", None,
    ),
    (
        "overlapping bands in one card",
        '[[card]]\nmatch="glm-5.3"\ntz="Asia/Shanghai"\ndefault={miss=1,hit=1,out=1}\n'
        '[[card.band]]\nwithin=["09:00-13:00"]\nrates={miss=2,hit=2,out=2}\n'
        '[[card.band]]\nwithin=["12:00-15:00"]\nrates={miss=3,hit=3,out=3}\n',
        "overlap", None,
    ),
    (
        "a midnight-spanning window",
        '[[card]]\nmatch="glm-5.3"\ntz="Asia/Shanghai"\ndefault={miss=1,hit=1,out=1}\n'
        '[[card.band]]\nwithin=["22:00-02:00"]\nrates={miss=2,hit=2,out=2}\n',
        "must start before it ends", None,
    ),
    (
        "one card flat AND banded",
        '[[card]]\nmatch="glm-5.3"\nrates={miss=1,hit=1,out=1}\n'
        '[[card.band]]\nwithin=["09:00-12:00"]\nrates={miss=2,hit=2,out=2}\n',
        "not both", None,
    ),
    (
        "two identical unbounded cards (caught as an overlap)",
        '[[card]]\nmatch="glm-5.3"\nrates={miss=1,hit=1,out=1}\n'
        '[[card]]\nmatch="glm-5.3"\nrates={miss=2,hit=2,out=2}\n',
        "overlap", None,
    ),
    (
        "the same model twice with different, disjoint ranges",
        '[[card]]\nmatch="glm-5.3"\nfrom=2026-01-01\nto=2026-02-01\n'
        'rates={miss=1,hit=1,out=1}\n'
        '[[card]]\nmatch="glm-5.3"\nfrom=2026-03-01\n'
        'rates={miss=2,hit=2,out=2}\n',
        None, "nothing is in effect",
    ),
    (
        "an unknown timezone",
        '[[card]]\nmatch="glm-5.3"\ntz="Mars/Olympus"\ndefault={miss=1,hit=1,out=1}\n'
        '[[card.band]]\nwithin=["09:00-12:00"]\nrates={miss=2,hit=2,out=2}\n',
        "unknown timezone", None,
    ),
    (
        "from after to",
        '[[card]]\nmatch="glm-5.3"\nfrom=2026-06-01\nto=2026-01-01\n'
        'rates={miss=1,hit=1,out=1}\n',
        "must be before", None,
    ),
    (
        "no cards at all",
        "",
        "at least one", None,
    ),
]


def validate() -> str:
    """Run the validation table; returns a printable report."""
    lines = []
    for label, body, want_err, want_warn in CASES:
        doc = HEADER + body
        try:
            with tempfile.NamedTemporaryFile(
                "w", suffix=".toml", delete=False
            ) as fh:
                fh.write(doc)
                path = Path(fh.name)
            try:
                loaded = load_rate_card(path)
                got_err, warns = None, loaded.warnings
            finally:
                path.unlink()
        except RateCardError as exc:
            got_err, warns = str(exc), []

        if want_err is not None:
            ok = got_err is not None and want_err in got_err
            shown = f"rejected: {got_err}" if got_err else "ACCEPTED (should reject)"
        elif want_warn is not None:
            match = [w for w in warns if want_warn in w]
            ok = got_err is None and bool(match)
            shown = f"warns: {match[0]}" if match else f"no warning ({warns})"
        else:
            ok = got_err is None and not warns
            shown = "accepted cleanly" if ok else f"{got_err or warns}"

        check(ok, f"validation: {label}", shown)
        lines.append(f"   {'ok  ' if ok else 'FAIL'} {label:<44} {shown}")

    # currency and schema are top-level, so they get their own lines.
    for label, body, want in [
        ("currency other than CNY", 'schema=1\ncurrency="USD"\n'
         '[[card]]\nmatch="glm-5.3"\nrates={miss=1,hit=1,out=1}\n', "currency"),
        ("unknown schema version", 'schema=2\ncurrency="CNY"\n'
         '[[card]]\nmatch="glm-5.3"\nrates={miss=1,hit=1,out=1}\n', "schema"),
        ("unknown top-level key", 'schema=1\ncurrency="CNY"\nrates=1\n'
         '[[card]]\nmatch="glm-5.3"\nrates={miss=1,hit=1,out=1}\n',
         "unknown top-level"),
    ]:
        try:
            with tempfile.NamedTemporaryFile(
                "w", suffix=".toml", delete=False
            ) as fh:
                fh.write(body)
                path = Path(fh.name)
            try:
                load_rate_card(path)
                got = None
            finally:
                path.unlink()
        except RateCardError as exc:
            got = str(exc)
        ok = got is not None and want in got
        check(ok, f"validation: {label}", got or "ACCEPTED (should reject)")
        lines.append(f"   {'ok  ' if ok else 'FAIL'} {label:<44} "
                     f"{'rejected: ' + got if got else 'ACCEPTED (should reject)'}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
