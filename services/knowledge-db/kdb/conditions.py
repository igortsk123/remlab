"""Нормализация free-text условий в поддержанные предикаты (predicate coverage).

Классы:
- APPLICABILITY_QUALIFIER (mobility/jurisdiction/activity/dwelling_feature) —
  становится PREDICATE-узлом applicability AST;
- TARGET_STATE_CONDITION — условие ЦЕЛИ/состояния, не applicability: уходит
  на сторону constraint (evaluation NOT_EVALUABLE без данных), AST-узел UNKNOWN
  снимается;
- EXAMPLE_MARKER — worked example, example_only;
- UNCLASSIFIED — остаётся UNKNOWN (C15: opaque не становится MATCH).

Канон вердиктов — реестр remlab_knowledge_db_v1/registries/
condition_normalization_map.json (в git); LLM зовётся только для условий,
которых нет в реестре (replay без сети). Пилот-партия перед массовым прогоном
(правило test-before-spend), молчаливых except нет.
"""
from __future__ import annotations

import re
from pathlib import Path

from .io import load_json_strict, write_json
from .llm import MODEL_CHEAP, LLMStats, call_json

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = REPO_ROOT / "remlab_knowledge_db_v1" / "registries" / \
    "condition_normalization_map.json"

_RULES = [
    ("MOBILITY", re.compile(r"wheelchair|accessib|universal design|\bada\b|"
                            r"grab bar|roll-in|mobility", re.I),
     {"class": "APPLICABILITY_QUALIFIER",
      "predicate": {"qualifier": "mobility_context",
                    "value": "wheelchair_or_accessible"}}),
    ("VISITABILITY", re.compile(r"visitab", re.I),
     {"class": "APPLICABILITY_QUALIFIER",
      "predicate": {"qualifier": "dwelling_feature", "value": "visitability"}}),
    ("JURISDICTION", re.compile(r"united states|north americ|\bu\.?s\.?\b|"
                                r"american household", re.I),
     {"class": "APPLICABILITY_QUALIFIER",
      "predicate": {"qualifier": "jurisdiction", "value": "us_north_america"}}),
    ("EXAMPLE", re.compile(r"worked example|example (?:given|shown|in the source)|"
                           r"as printed|prototype (?:kitchen|layout|plan)", re.I),
     {"class": "EXAMPLE_MARKER", "predicate": None}),
]

_LLM_CLASSES = ["APPLICABILITY_QUALIFIER_MOBILITY",
                "APPLICABILITY_QUALIFIER_JURISDICTION",
                "APPLICABILITY_QUALIFIER_ACTIVITY",
                "APPLICABILITY_QUALIFIER_DWELLING_FEATURE",
                "TARGET_STATE_CONDITION", "EXAMPLE_MARKER", "AMBIGUOUS"]

_SYS = (
    "You classify short condition strings extracted from an interior-design "
    "reference book. Each condition qualifies a dimensional/design claim. "
    "Decide what the condition restricts:\n"
    "- APPLICABILITY_QUALIFIER_MOBILITY: applies only in wheelchair/accessible/"
    "universal-design scenarios;\n"
    "- APPLICABILITY_QUALIFIER_JURISDICTION: restricts region/market/legal "
    "jurisdiction (e.g. United States);\n"
    "- APPLICABILITY_QUALIFIER_ACTIVITY: restricts to a human activity/social "
    "situation (e.g. conversation, dining, working);\n"
    "- APPLICABILITY_QUALIFIER_DWELLING_FEATURE: restricts to dwellings with a "
    "feature (visitable dwelling, multi-story...);\n"
    "- TARGET_STATE_CONDITION: describes the OBJECT/its state/subtype the number "
    "applies to (e.g. 'swinging doors', 'ramp serving a required egress door', "
    "'drawer open') — room applicability is NOT restricted;\n"
    "- EXAMPLE_MARKER: marks a worked example / value as printed in source;\n"
    "- AMBIGUOUS: cannot decide.\n"
    "For ACTIVITY/DWELLING_FEATURE give a short snake_case value; else value=''."
)

_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["items"],
    "properties": {"items": {
        "type": "array",
        "items": {"type": "object", "additionalProperties": False,
                  "required": ["index", "cls", "value"],
                  "properties": {
                      "index": {"type": "integer"},
                      "cls": {"type": "string", "enum": _LLM_CLASSES},
                      "value": {"type": "string"}}}}},
}


def norm_condition(s: str) -> str:
    return " ".join(str(s).split()).lower()[:300]


def load_registry() -> dict:
    if REGISTRY_PATH.exists():
        return load_json_strict(REGISTRY_PATH)["conditions"]
    return {}


def save_registry(reg: dict) -> None:
    write_json(REGISTRY_PATH, {
        "artifact": "condition_normalization_map",
        "note": "канон LLM/rule-вердиктов; подписи и AST реплеятся отсюда "
                "без сети (крит.№7 плана)",
        "conditions": {k: reg[k] for k in sorted(reg)},
    })


def _rule_classify(cond_norm: str) -> dict | None:
    for name, pat, verdict in _RULES:
        if pat.search(cond_norm):
            return {**verdict, "basis": f"RULE:{name}"}
    return None


def _llm_to_verdict(cls: str, value: str) -> dict:
    if cls == "TARGET_STATE_CONDITION":
        return {"class": "TARGET_STATE_CONDITION", "predicate": None}
    if cls == "EXAMPLE_MARKER":
        return {"class": "EXAMPLE_MARKER", "predicate": None}
    if cls == "AMBIGUOUS":
        return {"class": "UNCLASSIFIED", "predicate": None}
    qualifier = {"APPLICABILITY_QUALIFIER_MOBILITY":
                 ("mobility_context", "wheelchair_or_accessible"),
                 "APPLICABILITY_QUALIFIER_JURISDICTION":
                 ("jurisdiction", "us_north_america")}.get(cls)
    if qualifier:
        return {"class": "APPLICABILITY_QUALIFIER",
                "predicate": {"qualifier": qualifier[0], "value": qualifier[1]}}
    q = ("activity_context" if cls.endswith("ACTIVITY") else "dwelling_feature")
    v = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_") or "unspecified"
    return {"class": "APPLICABILITY_QUALIFIER",
            "predicate": {"qualifier": q, "value": v[:60]}}


def _llm_batch(conds: list[str], stats: LLMStats) -> dict:
    user = "Conditions:\n" + "\n".join(f"{i}: {c}" for i, c in enumerate(conds))
    obj = call_json(MODEL_CHEAP, _SYS, user, "condition_classes", _SCHEMA, stats)
    out = {}
    for item in obj.get("items", []):
        i = item.get("index")
        if isinstance(i, int) and 0 <= i < len(conds):
            v = _llm_to_verdict(item["cls"], item.get("value", ""))
            out[conds[i]] = {**v, "basis": "LLM", "model": MODEL_CHEAP}
    return out


def classify_conditions(all_conditions: list[str], stats: LLMStats,
                        batch_size: int = 25) -> tuple[dict, dict]:
    """-> (реестр {norm: verdict}, отчёт). Пилот: 1-я партия проверяется
    (валидность классов, полнота ответов) до продолжения."""
    reg = load_registry()
    uniq = sorted({norm_condition(c) for c in all_conditions if c and c.strip()})
    missing = [c for c in uniq if c not in reg]

    for c in list(missing):
        v = _rule_classify(c)
        if v:
            reg[c] = v
            missing.remove(c)

    report = {"unique_conditions": len(uniq),
              "from_registry": len(uniq) - len(missing),
              "rule_classified": sum(1 for v in reg.values()
                                     if str(v.get("basis", "")).startswith("RULE")),
              "llm_needed": len(missing), "llm_done": 0, "llm_failed_batches": 0,
              "pilot": None}

    batches = [missing[i:i + batch_size] for i in range(0, len(missing), batch_size)]
    for bi, batch in enumerate(batches):
        try:
            verdicts = _llm_batch(batch, stats)
        except Exception as e:  # noqa: BLE001 — счётчик + явный отчёт, не молчание
            report["llm_failed_batches"] += 1
            print(f"ОТКАЗ LLM-батча {bi + 1}/{len(batches)}: {e}")
            if bi == 0:
                raise SystemExit("БЛОК: пилот-партия классификации условий "
                                 "провалилась — массовый прогон отменён")
            continue
        if bi == 0:
            answered = len(verdicts)
            ok = answered >= len(batch) * 0.9
            report["pilot"] = {"batch_size": len(batch), "answered": answered,
                               "passed": ok}
            if not ok:
                raise SystemExit(f"БЛОК: пилот ответил на {answered}/{len(batch)}"
                                 " — проверь промпт/схему до массового прогона")
        reg.update(verdicts)
        report["llm_done"] += len(verdicts)

    save_registry(reg)
    classified = sum(1 for c in uniq if reg.get(c, {}).get("class",
                     "UNCLASSIFIED") != "UNCLASSIFIED")
    report["classified"] = classified
    report["coverage"] = round(classified / max(len(uniq), 1), 4)
    return reg, report
