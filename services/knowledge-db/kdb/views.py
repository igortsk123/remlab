"""PHASE 2D/2E — activation/target/quantification views + downstream utility.

D21-23: активация отдельна от constraint-оценки; сущности — не триггеры;
отсутствие target'а не гасит presence/cardinality. 2E: классы utility — не
policy; Judge-backbone eligibility — member-level.
"""
from __future__ import annotations

import re

_NO_UNIT = (r"(?!\s*(?:mm|cm|m2|m\b|in\b|inch|inches|ft\b|feet|foot|sq|square|"
            r"percent|%|deg|degrees|watt|lumen))")
PRESENCE_PATTERNS = [
    re.compile(r"\b(?:at least|not less than|no fewer than)\s+(one|two|\d)\b"
               + _NO_UNIT + r".{0,80}?\b(?:per|for each|in each|every)\b",
               re.I | re.S),
    re.compile(r"\b(?:at least|not less than|no fewer than)\s+(one|two|\d)\b"
               + _NO_UNIT + r"\s+([a-z\- ]{3,40}?)\s+"
               r"(?:must|shall|should|is required|are required)", re.I),
    re.compile(r"\b(one|two|\d)\b" + _NO_UNIT +
               r"\s+([a-z\- ]{3,40}?)\s+must be provided\b", re.I),
]

_QUANT_BY_OP = {"GTE": "EXISTS_MIN", "GT": "EXISTS_MIN", "EQUAL": "EXACT_COUNT",
                "LTE": "EXISTS_MAX", "LT": "EXISTS_MAX",
                "BETWEEN_INCLUSIVE": "EXISTS_MIN", "APPROX": "EXACT_COUNT",
                "NONE": "EXACT_COUNT"}

UTILITY_CONSTRAINT = "SOURCE_CONSTRAINT_GUIDANCE"
BACKBONE_STRENGTHS = {"REQUIRED_MINIMUM", "RECOMMENDED_MINIMUM", "MAXIMUM",
                      "PREFERRED", "TYPICAL_RANGE"}


def build_views(atom: dict) -> dict:
    claim = atom["claim"]
    mode = atom["projection_mode"]
    subject = claim.get("subject") if mode == "MEASUREMENT_BOUND" else None
    reference = claim.get("reference") if mode == "MEASUREMENT_BOUND" else None

    entity_roles = []
    if subject and any(subject.get(k) for k in
                       ("entity_family", "entity_type", "proposed_entity_type")):
        entity_roles.append({"entity": subject, "role": "CONSTRAINT_TARGET"})
    if reference and any((reference or {}).get(k) not in (None, "", "unknown")
                         for k in ("entity_family", "entity_type",
                                   "proposed_entity_type", "source_label")):
        entity_roles.append({"entity": reference, "role": "REFERENCE_CONTEXT"})

    activation = {
        "selector": "APPLICABILITY_AST",
        "trigger_semantics": "SCOPE_ONLY",  # D23: сущности не триггеры
        "runtime_capabilities_required": ["room_type_context"],
    }
    target = {
        "constrained_target": subject,
        "reference_target": reference,
        "prohibited_target": None,
        "target_absence_is_violation_candidate":
            claim.get("quantity_kind") == "COUNT",
    }
    if claim.get("quantity_kind") == "COUNT":
        quant = {"kind": _QUANT_BY_OP.get(claim.get("comparison_operator"),
                                          "OTHER"),
                 "source_phrase": None,
                 "basis": "COUNT_MEASUREMENT"}
    else:
        quant = {"kind": "NONE", "basis": "SCALAR_CONSTRAINT"}
    return {"activation_view": activation, "constraint_target_view": target,
            "quantification_view": quant, "entity_roles": entity_roles}


def detect_presence(record: dict) -> dict | None:
    """Детерминированный кандидат presence/cardinality в прозе записи.
    Возвращает {phrase, quantifier, target_hint} | None."""
    text = " ".join(str(record.get(k) or "") for k in
                    ("concept", "rule_plain_language"))
    for pat in PRESENCE_PATTERNS:
        m = pat.search(text)
        if m:
            n = m.group(1).lower()
            count = {"one": 1, "two": 2}.get(n)
            if count is None:
                try:
                    count = int(n)
                except ValueError:
                    count = 1
            target = (m.group(2).strip().lower()
                      if m.lastindex and m.lastindex >= 2 else None)
            start = max(0, m.start() - 40)
            return {"phrase": text[start:m.end() + 40].strip()[:200],
                    "min_count": count,
                    "target_hint": target}
    return None


def build_utility(atom: dict) -> dict:
    p = atom["parent_record"]
    claim = atom["claim"]
    use = p.get("remlab_candidate_use")
    ktype = p.get("knowledge_type")
    strength = atom["strength"]["effective"]
    example_only = (strength == "EXAMPLE"
                    or claim.get("value_type") == "EXAMPLE")

    classes: list[str] = []
    if use in ("HARD_CANDIDATE", "SOFT_CANDIDATE") and not example_only:
        classes.append(UTILITY_CONSTRAINT)
    if use == "SEMANTIC_CANDIDATE" or ktype == "SEMANTIC":
        classes.append("SEMANTIC_DESIGN_GUIDANCE")
    if example_only:
        classes.append("EXAMPLE_REFERENCE")
    if use == "REFERENCE_ONLY" and not example_only:
        text = f"{p.get('concept') or ''} {p.get('notes') or ''}".lower()
        nv = atom.get("numeric_view") or {}
        if "histor" in text or "1900" in text:
            classes.append("HISTORICAL_CONTEXT")
        elif nv.get("dimension") == "MONEY" or "cost" in text:
            classes.append("MODELING_REFERENCE")
        else:
            classes.append("UNRESOLVED_UTILITY")
    if not classes:
        classes.append("UNRESOLVED_UTILITY")

    eligible = (UTILITY_CONSTRAINT in classes
                and strength in BACKBONE_STRENGTHS
                and not example_only)
    reason = ("in-scope source constraint, сила " + str(strength)
              if eligible else
              ("example_only" if example_only else
               f"классы {classes}, сила {strength}"))
    return {"classes": classes, "judge_backbone_eligible": eligible,
            "eligibility_reason": reason}
