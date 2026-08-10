"""PHASE 2B — dual numeric comparison view.

Инварианты: source-представление неприкосновенно; comparison view строится
ТОЛЬКО из value_original/range_original + unit_original (Decimal, пиновая
таблица конверсий); source normalized_* — не истина сравнения, а объект
сверки. Неоднозначное -> AMBIGUOUS/UNAVAILABLE, без догадок.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

CONVERSION_TABLE_VERSION = "kdb-conv-1"
# фактор -> канон единица измерения по dimension
_LENGTH_CM = {  # unit_original (нормализованный) -> см
    "in": Decimal("2.54"), "inch": Decimal("2.54"), "inches": Decimal("2.54"),
    '"': Decimal("2.54"), "mm": Decimal("0.1"), "cm": Decimal("1"),
    "m": Decimal("100"), "ft": Decimal("30.48"), "feet": Decimal("30.48"),
    "foot": Decimal("30.48"),
}
_AREA_M2 = {
    "sq ft": Decimal("0.09290304"), "sq_ft": Decimal("0.09290304"),
    "ft2": Decimal("0.09290304"), "square foot": Decimal("0.09290304"),
    "square feet": Decimal("0.09290304"), "sqft": Decimal("0.09290304"),
    "sq in": Decimal("0.00064516"), "sq_in": Decimal("0.00064516"),
    "in2": Decimal("0.00064516"), "m2": Decimal("1"), "sq m": Decimal("1"),
    "cm2": Decimal("0.0001"),
}
_PASSTHROUGH = {  # dimension -> (единица, множитель 1)
    "percent": ("percent", "PERCENT"), "%": ("percent", "PERCENT"),
    "count": ("count", "COUNT"), "deg": ("deg", "ANGLE"),
    "degree": ("deg", "ANGLE"), "degrees": ("deg", "ANGLE"),
    "usd": ("usd", "MONEY"), "USD": ("usd", "MONEY"),
    "w": ("W", "POWER"), "W": ("W", "POWER"),
}

_FTIN = re.compile(r"^(\d+)'-(\d+(?:\.\d+)?)\"?$")
_RATIO = re.compile(r"^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$")
_PLUS = re.compile(r"^(\d+(?:\.\d+)?)-?plus$", re.I)
_NUM = re.compile(r"^-?\d+(?:\.\d+)?$")


def parse_scalar(v, unit_norm: str | None) -> tuple[str, Decimal | None, dict]:
    """-> (status, value, extras). status: OK | OPEN_GTE | RATIO | AMBIGUOUS."""
    if v is None:
        return "NONE", None, {}
    if isinstance(v, (int, float)):
        return "OK", Decimal(str(v)), {}
    s = str(v).strip()
    if _NUM.match(s):
        return "OK", Decimal(s), {}
    m = _FTIN.match(s)
    if m:  # футы-дюймы -> дюймы (единица длины подменяется на in)
        inches = Decimal(m.group(1)) * 12 + Decimal(m.group(2))
        return "OK", inches, {"reparsed_unit": "in"}
    m = _RATIO.match(s)
    if m:
        try:
            return "RATIO", Decimal(m.group(1)) / Decimal(m.group(2)), \
                {"ratio": [m.group(1), m.group(2)]}
        except (InvalidOperation, ZeroDivisionError):
            return "AMBIGUOUS", None, {}
    m = _PLUS.match(s)
    if m:
        return "OPEN_GTE", Decimal(m.group(1)), {}
    return "AMBIGUOUS", None, {}


def _unit_norm(u: str | None) -> str | None:
    if u is None:
        return None
    return str(u).strip().lower().replace("²", "2")


def to_canonical(value: Decimal, unit_norm: str | None,
                 reparsed: str | None) -> tuple[str, str, Decimal] | None:
    """-> (dimension, canonical_unit, canonical_value) | None (не знаем юнит)."""
    u = reparsed or unit_norm
    if u in _LENGTH_CM:
        return "LENGTH", "cm", value * _LENGTH_CM[u]
    if u in _AREA_M2:
        return "AREA", "m2", value * _AREA_M2[u]
    if u in _PASSTHROUGH:
        unit, dim = _PASSTHROUGH[u]
        return dim, unit, value
    if u in (None, "", "null"):
        return None
    return None


def _pct_diff(a: Decimal, b: Decimal) -> Decimal:
    if b == 0:
        return abs(a - b)
    return abs(a - b) / abs(b) * 100


def build_numeric_view(claim: dict) -> dict:
    """claim — measurement-faithful копия из атома (KB2)."""
    unit = _unit_norm(claim.get("unit_original"))
    out: dict = {"conversion_table_version": CONVERSION_TABLE_VERSION,
                 "unit_original_normalized": unit}

    vals = {}
    reparsed = None
    st_v, v, extras_v = parse_scalar(claim.get("value_original"), unit)
    reparsed = extras_v.get("reparsed_unit")
    rng = claim.get("range_original") or [None, None]
    st_lo, lo, ex_lo = parse_scalar(rng[0] if len(rng) > 0 else None, unit)
    st_hi, hi, ex_hi = parse_scalar(rng[1] if len(rng) > 1 else None, unit)
    reparsed = reparsed or ex_lo.get("reparsed_unit") or ex_hi.get("reparsed_unit")

    if "AMBIGUOUS" in (st_v, st_lo, st_hi):
        out["status"] = "AMBIGUOUS"
        out["comparison"] = "UNKNOWN"
        return out
    if v is None and lo is None and hi is None:
        out["status"] = "UNAVAILABLE"
        out["comparison"] = "NOT_COMPARABLE"
        return out

    canon = None
    for val in (v, lo, hi):
        if val is not None:
            canon = to_canonical(val, unit, reparsed)
            break
    if canon is None:
        if st_v == "RATIO" or (st_lo == "RATIO") or (st_hi == "RATIO"):
            out["status"] = "OK"
            out["dimension"] = "RATIO"
            out["canonical_unit"] = "ratio"
            out["value"] = str(v) if v is not None else None
            out["range"] = [str(lo) if lo is not None else None,
                            str(hi) if hi is not None else None]
            out["comparison"] = "NOT_COMPARABLE"
            return out
        out["status"] = "UNAVAILABLE"
        out["comparison"] = "NOT_COMPARABLE"
        out["reason"] = f"unit {unit!r} вне пиновой таблицы"
        return out

    dim, cunit, _ = canon
    conv = lambda x: (to_canonical(x, unit, reparsed)[2] if x is not None else None)  # noqa: E731
    cv, clo, chi = conv(v), conv(lo), conv(hi)
    out.update({
        "status": "OK" if st_v != "OPEN_GTE" else "OK_OPEN_GTE",
        "dimension": dim, "canonical_unit": cunit,
        "value": str(cv) if cv is not None else None,
        "range": [str(clo) if clo is not None else None,
                  str(chi) if chi is not None else None],
        "operator": claim.get("comparison_operator"),
    })

    # сверка с source-normalized (не перезаписываем, только классифицируем)
    src_cu = _unit_norm(claim.get("canonical_unit"))
    src_v = claim.get("normalized_value")
    src_rng = claim.get("normalized_range") or [None, None]
    if src_cu != cunit or (src_v is None and src_rng[0] is None
                           and (len(src_rng) < 2 or src_rng[1] is None)):
        out["comparison"] = "NOT_COMPARABLE"
        return out

    def cmp_pair(mine: Decimal | None, theirs) -> str | None:
        if mine is None or theirs is None:
            return None
        try:
            d = _pct_diff(mine, Decimal(str(theirs)))
        except InvalidOperation:
            return "UNKNOWN"
        if d <= Decimal("0.5"):
            return "CONSISTENT"
        if d <= Decimal("3"):
            return "ROUNDING_COMPATIBLE"
        return "CONFLICTING"

    verdicts = [x for x in (
        cmp_pair(cv, src_v),
        cmp_pair(clo, src_rng[0] if len(src_rng) > 0 else None),
        cmp_pair(chi, src_rng[1] if len(src_rng) > 1 else None)) if x]
    if not verdicts:
        out["comparison"] = "NOT_COMPARABLE"
    elif "CONFLICTING" in verdicts:
        out["comparison"] = "CONFLICTING"
        note = (claim.get("conversion_note") or "")
        out["conflict_subtype"] = ("INTERNAL_UNIT_EQUIVALENCY_CONFLICT"
                                   if note else "EXTRACTION_NORMALIZATION_SUSPECT")
    elif "ROUNDING_COMPATIBLE" in verdicts:
        out["comparison"] = "ROUNDING_COMPATIBLE"
    elif "UNKNOWN" in verdicts:
        out["comparison"] = "UNKNOWN"
    else:
        out["comparison"] = "CONSISTENT"
    return out
