"""PHASE 2C — symbolic/relational constraints: allow-list парсер, без eval.

Source-строка сохраняется всегда; AST строится только когда надёжно.
Статусы: PARSED | PARTIALLY_PARSED | OPAQUE. Worked example (value_type=EXAMPLE)
не универсализируется: example_only=true.
"""
from __future__ import annotations

import re

_CMP = re.compile(r"(<=|>=|<<|>>|=|<|>)")
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$", re.I)
_NUM = re.compile(r"^-?\d+(?:\.\d+)?$")
_RATIO = re.compile(r"^(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)$")
_FUNC = re.compile(r"^([a-z_][a-z0-9_]*)\((.*)\)$", re.I | re.S)

_KIND_BY_OP = {"<=": "INEQUALITY", ">=": "INEQUALITY", "<": "INEQUALITY",
               ">": "INEQUALITY", "<<": "QUALITATIVE_RELATION",
               ">>": "QUALITATIVE_RELATION", "=": "EQUALITY"}


def _parse_operand(s: str) -> dict:
    """Операнд: число | ratio | идентификатор | произведение | функция | opaque."""
    s = s.strip()
    if _NUM.match(s):
        return {"t": "num", "v": s}
    m = _RATIO.match(s)
    if m:
        return {"t": "ratio", "num": m.group(1), "den": m.group(2)}
    if _IDENT.match(s):
        return {"t": "var", "name": s.lower()}
    if "*" in s:
        parts = [p.strip() for p in s.split("*")]
        ops = [_parse_operand(p) for p in parts]
        if all(o["t"] != "opaque" for o in ops):
            return {"t": "mul", "args": ops}
    if "/" in s:
        parts = [p.strip() for p in s.split("/")]
        if len(parts) == 2:
            ops = [_parse_operand(p) for p in parts]
            if all(o["t"] in ("var", "num") for o in ops):
                return {"t": "div", "args": ops}
    m = _FUNC.match(s)
    if m:
        return {"t": "func", "name": m.group(1).lower(),
                "arg_text": m.group(2).strip()[:200]}
    return {"t": "opaque", "text": s[:200]}


def build_symbolic_view(expr: str, value_type: str | None) -> dict:
    src = str(expr)
    out: dict = {"source_expression": src,
                 "example_only": value_type == "EXAMPLE"}
    parts = _CMP.split(src)
    # parts: operand, op, operand, op, operand...
    if len(parts) < 3:
        out.update({"parse_status": "OPAQUE", "kind": "QUALITATIVE_RELATION"
                    if any(w in src.lower() for w in
                           ("cost", "varies", "relative", "effectiveness"))
                    else "OTHER"})
        return out

    operands = [_parse_operand(p) for p in parts[0::2]]
    ops = [p for p in parts[1::2]]
    n_opaque = sum(1 for o in operands if o["t"] in ("opaque", "func"))
    if n_opaque == 0:
        status = "PARSED"
    elif n_opaque < len(operands):
        status = "PARTIALLY_PARSED"
    else:
        status = "PARTIALLY_PARSED" if ops else "OPAQUE"

    if len(ops) > 1:
        kind = "ORDERING"
    else:
        kind = _KIND_BY_OP.get(ops[0], "OTHER")
        if kind == "EQUALITY" and any(o["t"] in ("mul", "div") for o in operands):
            kind = "FORMULA"
        if kind == "INEQUALITY" and any(o["t"] == "mul" for o in operands):
            kind = "PROPORTION"
        if any(o["t"] == "func" and o["name"] == "cost" for o in operands):
            kind = "QUALITATIVE_RELATION"
    if out["example_only"]:
        kind = "EXAMPLE"
    out.update({"parse_status": status, "kind": kind,
                "comparators": ops, "operands": operands})
    return out
