"""PROTOTYPE — the liftable half. Pure module, no I/O beyond loading a file.

Answers: can a dated, banded rate card be expressed in TOML, validated on load,
and priced identically to ai-usage/usage-lib.mjs's computeCostYuan?

Deliberate parity choices (see parity_check.py):
  * the five NOT-NULL/optional token fields are read exactly as the JS does,
    including the `?? 0` nullish defaults and the `hit ?? miss` rate fallback;
  * the arithmetic runs in the same order and rounds the same way (half-up on
    the value scaled by 1e6), so results match bit for bit;
  * matching is substring, longest key first, with file order breaking ties —
    the JS relies on Array.sort being stable, and Python's sorted() is too.

   python prototypes/rate-card/parity_check.py      # check against usage-lib.mjs
"""
from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import NoReturn
from zoneinfo import ZoneInfo

SUPPORTED_SCHEMA = 1
SUPPORTED_CURRENCY = "CNY"
DAY_START = time(0, 0)
DAY_END = time(23, 59, 59, 999999)


class RateCardError(Exception):
    """The rate-card file is malformed, ambiguous, or incomplete."""


# ── Model-name handling (mirrors usage-lib.mjs) ────────────────────────────


def normalize_model(model: str | None) -> str:
    """Strip a [1m]-style context suffix, trim, lowercase."""
    if not model:
        return ""
    out, depth = [], 0
    for ch in model:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return "".join(out).strip().lower()


def js_round(x: float) -> float:
    """JS Math.round: half-up, including for negatives."""
    return math.floor(x + 0.5)


# ── The rate card ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Rates:
    miss: float
    hit: float
    out: float


@dataclass(frozen=True)
class Band:
    start: time
    end: time
    rates: Rates

    def covers(self, t: time) -> bool:
        return self.start <= t < self.end


@dataclass(frozen=True)
class Card:
    match: str
    tz: ZoneInfo
    start: date | None  # None = since forever
    end: date | None  # None = until further notice
    rates: Rates | None  # flat cards
    default: Rates | None  # banded cards: the fall-through rate
    bands: tuple[Band, ...]
    line: int  # for error messages

    @property
    def key(self) -> str:
        return normalize_model(self.match)

    def covers_date(self, d: date) -> bool:
        if self.start is not None and d < self.start:
            return False
        return not (self.end is not None and d >= self.end)

    def rates_at(self, at: datetime) -> tuple[Rates, str | None]:
        """Pick the rates for an instant, with the name of the band matched."""
        if self.rates is not None:
            return self.rates, None
        local = at.astimezone(self.tz).time()
        for band in self.bands:
            if band.covers(local):
                return band.rates, f"{band.start:%H:%M}-{band.end:%H:%M}"
        assert self.default is not None  # enforced at load
        return self.default, None


@dataclass(frozen=True)
class Resolved:
    """What a model + instant priced to: the card, the rates, the band."""

    match: str
    rates: Rates
    band: str | None
    tz: ZoneInfo
    card: Card


class RateCardFile:
    def __init__(
        self,
        cards: list[Card],
        aliases: dict[str, str],
        warnings: list[str],
        path: Path | None = None,
    ) -> None:
        self.cards = cards
        self.aliases = aliases
        self.warnings = warnings
        self.path = path
        # Longest key first; sorted() is stable, so ties keep file order,
        # matching the JS's stable Array.sort.
        self._by_length = sorted(cards, key=lambda c: -len(c.key))

    # — model identity —

    def canonical_model_name(self, model: str | None) -> str | None:
        if not model:
            return model
        return self.aliases.get(model.strip().lower(), model)

    # — pricing —

    def card_for(self, model: str | None, at: datetime) -> Card | None:
        """The card in effect for `model` at `at`, or None if unpriced."""
        m = normalize_model(model)
        if not m:
            return None
        for card in self._by_length:
            key = card.key
            if not key:
                continue
            if m != key and key not in m:
                continue
            if card.covers_date(at.astimezone(card.tz).date()):
                return card
        return None

    def resolve(self, model: str | None, at: datetime) -> Resolved | None:
        card = self.card_for(model, at)
        if card is None:
            return None
        rates, band = card.rates_at(at)
        return Resolved(card.match, rates, band, card.tz, card)


# ── Loading & validation ───────────────────────────────────────────────────

_TOP_KEYS = {"schema", "currency", "aliases", "card"}
_CARD_KEYS = {"match", "tz", "from", "to", "rates", "default", "band"}


def _fail(where: str, msg: str) -> NoReturn:
    raise RateCardError(f"{where}: {msg}")


def _parse_rates(raw: object, where: str) -> Rates:
    if not isinstance(raw, dict):
        _fail(where, f"rates must be a table, got {type(raw).__name__}")
    unknown = set(raw) - {"miss", "hit", "out"}
    if unknown:
        _fail(where, f"unknown rate key(s) {sorted(unknown)}; expected miss/hit/out")
    for required in ("miss", "out"):
        if required not in raw:
            _fail(where, f"rates must set `{required}`")
    vals: dict[str, float] = {}
    for key in ("miss", "hit", "out"):
        if key not in raw:
            continue
        v = raw[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            _fail(where, f"rate `{key}` must be a number, got {type(v).__name__}")
        if v < 0:
            _fail(where, f"rate `{key}` must not be negative, got {v}")
        vals[key] = float(v)
    # `hit` may be omitted: cache hits then bill at the miss rate, as the JS
    # does with `p.hit ?? p.miss`.
    vals.setdefault("hit", vals["miss"])
    return Rates(miss=vals["miss"], hit=vals["hit"], out=vals["out"])


def _parse_window(spec: str, where: str) -> tuple[time, time]:
    parts = spec.split("-")
    if len(parts) != 2:
        _fail(where, f"window {spec!r} must look like '09:00-12:00'")
    start_s, end_s = (p.strip() for p in parts)
    try:
        start = time.fromisoformat(start_s)
        end = time.fromisoformat(end_s)
    except ValueError as exc:
        _fail(where, f"window {spec!r} has an unparseable time: {exc}")
    if start >= end:
        _fail(
            where,
            f"window {spec!r} must start before it ends; split a "
            "midnight-spanning window into two",
        )
    return start, end


def load_rate_card(path: str | Path) -> RateCardFile:
    path = Path(path)
    with path.open("rb") as fh:
        try:
            doc = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            raise RateCardError(f"{path}: not valid TOML: {exc}") from exc

    unknown = set(doc) - _TOP_KEYS
    if unknown:
        _fail(str(path), f"unknown top-level key(s) {sorted(unknown)}")

    schema = doc.get("schema")
    if schema != SUPPORTED_SCHEMA:
        _fail(str(path), f"schema must be {SUPPORTED_SCHEMA}, got {schema!r}")

    currency = doc.get("currency", SUPPORTED_CURRENCY)
    if currency != SUPPORTED_CURRENCY:
        _fail(
            str(path),
            f"currency must be {SUPPORTED_CURRENCY!r}, got {currency!r}; "
            "other currencies would need an FX rate source, which this file "
            "deliberately does not have",
        )

    raw_aliases = doc.get("aliases", {})
    if not isinstance(raw_aliases, dict):
        _fail(str(path), "aliases must be a table")
    aliases: dict[str, str] = {}
    for k, v in raw_aliases.items():
        if not isinstance(v, str):
            _fail(str(path), f"alias {k!r} must map to a string")
        aliases[k.strip().lower()] = v

    raw_cards = doc.get("card", [])
    if not isinstance(raw_cards, list) or not raw_cards:
        _fail(str(path), "the file must define at least one [[card]]")

    cards: list[Card] = []
    for i, raw in enumerate(raw_cards, start=1):
        where = f"{path} card #{i}"
        if not isinstance(raw, dict):
            _fail(where, "must be a table")
        unknown = set(raw) - _CARD_KEYS
        if unknown:
            _fail(where, f"unknown key(s) {sorted(unknown)}")

        match = raw.get("match")
        if not isinstance(match, str) or not match.strip():
            _fail(where, "`match` must be a non-empty string")
        where = f"{path} card #{i} (match={match!r})"

        start, end = raw.get("from"), raw.get("to")
        for label, v in (("from", start), ("to", end)):
            if v is not None and not isinstance(v, date):
                _fail(where, f"`{label}` must be a TOML date, got {v!r}")
        if start and end and start >= end:
            _fail(where, f"`from` ({start}) must be before `to` ({end})")

        flat = raw.get("rates")
        bands_raw = raw.get("band") or []
        default_raw = raw.get("default")
        if not isinstance(bands_raw, list):
            _fail(where, "`band` must be an array of tables")

        if flat is not None and (bands_raw or default_raw is not None):
            _fail(where, "a card is either flat (`rates`) or banded, not both")
        if flat is None and not bands_raw:
            _fail(where, "a card must set `rates`, or `band` entries plus `default`")

        tz_name = raw.get("tz", "UTC")
        try:
            tz = ZoneInfo(tz_name)
        except Exception as exc:  # ZoneInfoNotFoundError, ValueError
            _fail(where, f"unknown timezone {tz_name!r}: {exc}")

        rates = default = None
        bands: list[Band] = []
        if flat is not None:
            rates = _parse_rates(flat, where)
        else:
            if default_raw is None:
                _fail(
                    where,
                    "banded cards must set `default`, otherwise times outside "
                    "every window are unpriced",
                )
            default = _parse_rates(default_raw, f"{where} default")
            if "tz" not in raw:
                _fail(
                    where,
                    "banded cards must name a `tz`; band times are meaningless "
                    "without one",
                )
            for j, band_raw in enumerate(bands_raw, start=1):
                bwhere = f"{where} band #{j}"
                if not isinstance(band_raw, dict):
                    _fail(bwhere, "must be a table")
                unknown = set(band_raw) - {"within", "rates"}
                if unknown:
                    _fail(bwhere, f"unknown key(s) {sorted(unknown)}")
                within = band_raw.get("within")
                if isinstance(within, str):
                    within = [within]
                if not isinstance(within, list) or not within:
                    _fail(bwhere, "`within` must be a non-empty list of windows")
                brates = _parse_rates(band_raw.get("rates"), bwhere)
                for spec in within:
                    if not isinstance(spec, str):
                        _fail(bwhere, f"window must be a string, got {spec!r}")
                    b_start, b_end = _parse_window(spec, bwhere)
                    bands.append(Band(b_start, b_end, brates))

        cards.append(
            Card(
                match=match,
                tz=tz,
                start=start,
                end=end,
                rates=rates,
                default=default,
                bands=tuple(bands),
                line=i,
            )
        )

    warnings = _check_overlaps_and_gaps(cards, str(path))
    return RateCardFile(cards, aliases, warnings, path)


def _check_overlaps_and_gaps(cards: list[Card], where: str) -> list[str]:
    """Ranges for one `match` may not overlap; interior gaps are warned about."""
    warnings: list[str] = []
    by_key: dict[str, list[Card]] = {}
    for card in cards:
        by_key.setdefault(card.key, []).append(card)

    for group in by_key.values():
        # Bands within one card.
        for card in group:
            spans = sorted(card.bands, key=lambda b: b.start)
            for a, b in zip(spans, spans[1:]):
                if b.start < a.end:
                    raise RateCardError(
                        f"{where} card #{card.line} (match={card.match!r}): "
                        f"bands {a.start:%H:%M}-{a.end:%H:%M} and "
                        f"{b.start:%H:%M}-{b.end:%H:%M} overlap"
                    )

        # Date ranges across the group.
        lo = date.min
        hi = date.max
        spans = sorted(group, key=lambda c: (c.start or lo, c.end or hi))
        for a, b in zip(spans, spans[1:]):
            a_end = a.end or hi
            b_start = b.start or lo
            if b_start < a_end:
                raise RateCardError(
                    f"{where} (match={a.match!r}): date ranges overlap — "
                    f"card #{a.line} runs to {a.end}, card #{b.line} starts "
                    f"{b.start}. Pricing would be ambiguous."
                )
            if b_start > a_end:
                warnings.append(
                    f"{where} (match={a.match!r}): nothing is in effect from "
                    f"{a_end} to {b_start}; events in that gap price null"
                )

    # No separate duplicate check: two cards sharing a match and a range
    # necessarily overlap, so the rule above already rejects them.
    return warnings


# ── Pricing an event ───────────────────────────────────────────────────────


def compute_cost_yuan(
    model: str | None,
    flat: dict | None,
    at: datetime,
    card_file: RateCardFile,
) -> float | None:
    """Port of usage-lib.mjs computeCostYuan, priced from a card file."""
    if not flat or flat.get("prompt_tokens") is None:
        return None
    resolved = card_file.resolve(model, at)
    if resolved is None:
        return None
    r = resolved.rates
    hit = flat.get("prompt_cache_hit_tokens")
    hit = 0 if hit is None else hit
    miss = flat.get("prompt_cache_miss_tokens")
    miss = 0 if miss is None else miss
    completion = flat.get("completion_tokens")
    completion = 0 if completion is None else completion
    fresh = flat["prompt_tokens"] - hit - miss
    cost = (
        (fresh + miss) * r.miss + hit * r.hit + completion * r.out
    ) / 1e6
    return js_round(cost * 1e6) / 1e6


def price_event(
    model: str | None, flat: dict | None, at: datetime, card_file: RateCardFile
) -> tuple[str | None, float | None]:
    """The ingest path end to end: alias the model, then price it.

    Returns (stored_model_name, cost_yuan). The stored name is the aliased one,
    so events group under a single name.
    """
    canonical = card_file.canonical_model_name(model)
    return canonical, compute_cost_yuan(canonical, flat, at, card_file)


def utc(*args: int) -> datetime:
    """Terse explicit-UTC constructor for re-runnable examples."""
    return datetime(*args, tzinfo=timezone.utc)
