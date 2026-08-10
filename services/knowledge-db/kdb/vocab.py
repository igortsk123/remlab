"""PHASE 3 — vocabulary/alias registry (сущности + квалификаторы).

Concept identity != label. CORE-типы (62 из корпуса, словарь v1.2) — фиксированные
ID CORE_ENTITY_<type>. 636 proposed_entity_type маппятся LLM-батчами в
EXACT/SYNONYM/NARROWER/RELATED к CORE или в новые концепты (anchor —
лексикографически меньший member). Канон — registries/vocabulary_map.json (git),
реплей без сети. Relation-лейблы остаются source-faithful (UNRESOLVED допустим —
family-подписи KB5b работают на pre-vocabulary слотах).
"""
from __future__ import annotations

import re
from pathlib import Path

from .canonical import derived_id
from .io import load_json_strict, write_json
from .llm import MODEL_CHEAP, LLMStats, call_json

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = REPO_ROOT / "remlab_knowledge_db_v1" / "registries" / \
    "vocabulary_map.json"

_STATUSES = ["EXACT", "SYNONYM", "NARROWER", "BROADER", "RELATED", "NEW_CONCEPT"]

_SYS = (
    "You maintain a controlled vocabulary of interior/architectural entity types "
    "for a furniture-layout knowledge base. For each PROPOSED type, map it to the "
    "closest CORE type from the provided list:\n"
    "- EXACT: same concept, different label;\n"
    "- SYNONYM: same concept, common synonym;\n"
    "- NARROWER: proposed is a subtype of the core type;\n"
    "- BROADER: proposed is broader than the core type;\n"
    "- RELATED: related but not substitutable;\n"
    "- NEW_CONCEPT: no reasonable core match. Then give canonical_label — a "
    "snake_case canonical name for the NEW concept (merge obvious synonyms by "
    "using the same canonical_label).\n"
    "core='' unless status maps to a core type."
)

_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["index", "status", "core", "canonical_label"],
        "properties": {
            "index": {"type": "integer"},
            "status": {"type": "string", "enum": _STATUSES},
            "core": {"type": "string"},
            "canonical_label": {"type": "string"}}}}},
}

_MOBILITY_WHEELCHAIR = re.compile(r"wheel\s*_?chair", re.I)


def norm_label(s: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(s).strip().lower()).strip("_")[:80]


def normalize_mobility(v: str | None) -> str | None:
    """Правило-нормализация qualifier-значений (5+ орфографий wheelchair)."""
    if v in (None, "", "unknown"):
        return None
    if _MOBILITY_WHEELCHAIR.search(str(v)):
        return "wheelchair_user"
    return norm_label(v)


def load_registry() -> dict:
    if REGISTRY_PATH.exists():
        return load_json_strict(REGISTRY_PATH)["proposed_entity_types"]
    return {}


def save_registry(reg: dict) -> None:
    write_json(REGISTRY_PATH, {
        "artifact": "vocabulary_map_registry",
        "note": "канон LLM-маппинга proposed_entity_type; подписи/канон "
                "реплеятся отсюда без сети",
        "proposed_entity_types": {k: reg[k] for k in sorted(reg)},
    })


def _batch(core_types: list[str], proposed: list[str],
           stats: LLMStats) -> dict:
    user = ("CORE types: " + ", ".join(sorted(core_types)) +
            "\nPROPOSED:\n" +
            "\n".join(f"{i}: {p}" for i, p in enumerate(proposed)))
    obj = call_json(MODEL_CHEAP, _SYS, user, "vocab_map", _SCHEMA, stats)
    out = {}
    for it in obj.get("items", []):
        i = it.get("index")
        if isinstance(i, int) and 0 <= i < len(proposed):
            core = it["core"] if it["core"] in core_types else ""
            status = it["status"]
            if status not in ("NEW_CONCEPT",) and not core:
                status = "NEW_CONCEPT"  # маппинг без валидного core невозможен
            out[proposed[i]] = {
                "status": status, "core": core or None,
                "canonical_label": norm_label(it["canonical_label"])
                or proposed[i],
                "basis": "LLM", "model": MODEL_CHEAP}
    return out


def build_vocabulary(core_types: list[str], proposed_types: list[str],
                     stats: LLMStats, batch_size: int = 25) -> tuple[dict, dict]:
    """-> (реестр proposed->verdict, отчёт). Пилот-партия как в conditions."""
    reg = load_registry()
    uniq = sorted({norm_label(p) for p in proposed_types if p})
    missing = [p for p in uniq if p not in reg]
    report = {"unique_proposed": len(uniq), "from_registry": len(uniq) - len(missing),
              "llm_needed": len(missing), "llm_done": 0, "failed_batches": 0}

    batches = [missing[i:i + batch_size] for i in range(0, len(missing), batch_size)]
    for bi, b in enumerate(batches):
        try:
            verdicts = _batch(core_types, b, stats)
        except Exception as e:  # noqa: BLE001 — счётчик, не молчание
            report["failed_batches"] += 1
            print(f"ОТКАЗ vocab-батча {bi + 1}/{len(batches)}: {e}")
            if bi == 0:
                raise SystemExit("БЛОК: пилот vocab-маппинга провалился")
            continue
        if bi == 0 and len(verdicts) < len(b) * 0.9:
            raise SystemExit(f"БЛОК: пилот vocab ответил {len(verdicts)}/{len(b)}")
        reg.update(verdicts)
        report["llm_done"] += len(verdicts)
    save_registry(reg)

    # присвоение concept_id: CORE — фиксированные; NEW — по origin_anchor
    # (лексикографически меньший member группы canonical_label)
    groups: dict[str, list[str]] = {}
    for p in uniq:
        v = reg.get(p)
        if v and v["status"] == "NEW_CONCEPT":
            groups.setdefault(v["canonical_label"], []).append(p)
    concept_ids = {}
    for label, members in groups.items():
        anchor = sorted(members)[0]
        concept_ids[label] = derived_id("CONC", {"kind": "entity",
                                                 "origin_anchor": anchor})
    report["new_concepts"] = len(concept_ids)
    report["mapped_to_core"] = sum(1 for p in uniq
                                   if reg.get(p, {}).get("core"))
    return {"proposed": reg, "new_concept_ids": concept_ids}, report
