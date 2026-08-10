"""Вердикты пар: детерминированная предклассификация + LLM-судья (3 слоя спеки:
same_question / relationship / scope; зависимость — отдельным полем).

Канон вердиктов — registries/pair_verdicts.jsonl (git), ключ — хэш пары
ВЕРСИЙ атомов (правка экстракции => новый вердикт, ID пары стабилен).
Пилот-партия с экстраполяцией стоимости ДО массового прогона; прогноз
печатается владельцу; >$60 — стоп.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from .canonical import derived_id, jcs_sha256
from .io import read_jsonl, write_jsonl
from .llm import MODEL_CHEAP, LLMStats, call_json

REPO_ROOT = Path(__file__).resolve().parents[3]
VERDICTS_PATH = REPO_ROOT / "remlab_knowledge_db_v1" / "registries" / \
    "pair_verdicts.jsonl"
PROMPT_VERSION = "pv1"

RELATIONSHIPS = ["EXACT_DUPLICATE", "SEMANTIC_DUPLICATE", "COMPATIBLE_VARIANT",
                 "COMPLEMENTARY", "SCOPED_VARIANT", "POTENTIAL_CONFLICT",
                 "TRUE_CONFLICT", "RELATED_NOT_SAME",
                 "SAME_PRIMARY_QUANTITY_WITH_EQUIVALENCY_DISCREPANCY",
                 "UNRESOLVED"]
SCOPES = ["EQUIVALENT", "OVERLAPPING", "DISJOINT", "UNKNOWN"]
DEPS = ["NONE", "QUALIFIES", "EXCEPTION_TO", "LIMITS_APPLICABILITY_OF",
        "OVERRIDES_IN_SCOPE", "TRADEOFF_WITH", "VALUE_REFERENCE_TO",
        "PREREQUISITE_FOR", "EXPLAINS", "ILLUSTRATES"]

_SYS = (
    "You compare pairs of atomic claims extracted from ONE interior-design "
    "book. For each pair decide three SEPARATE layers:\n"
    "1) same_question: do they answer the SAME semantic question (same subject "
    "role, same measured relation), regardless of numeric answer/strength? "
    "SAME|DIFFERENT|UNRESOLVED.\n"
    "2) scope_relation between their applicability scopes (rooms/zones/"
    "conditions): EQUIVALENT|OVERLAPPING|DISJOINT|UNKNOWN.\n"
    "3) relationship: EXACT_DUPLICATE (same value restated), SEMANTIC_DUPLICATE,"
    " COMPATIBLE_VARIANT (min vs preferred etc.), COMPLEMENTARY (different "
    "aspects of one thing), SCOPED_VARIANT (same question, different scope), "
    "POTENTIAL_CONFLICT (differing values, needs check), TRUE_CONFLICT (source "
    "genuinely contradicts itself for the SAME scope), RELATED_NOT_SAME, "
    "UNRESOLVED.\n"
    "Also dependency: does one claim qualify/except/limit/override/explain the "
    "other (QUALIFIES, EXCEPTION_TO, LIMITS_APPLICABILITY_OF, OVERRIDES_IN_SCOPE,"
    " TRADEOFF_WITH, VALUE_REFERENCE_TO, PREREQUISITE_FOR, EXPLAINS, "
    "ILLUSTRATES) — else NONE; direction A_TO_B means A modifies B.\n"
    "Rules: DISJOINT scopes can NEVER be TRUE_CONFLICT or duplicates. "
    "General rule + its exception is EXCEPTION_TO, not conflict. Min vs "
    "preferred is COMPATIBLE_VARIANT, not conflict."
)

_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["pairs"],
    "properties": {"pairs": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["index", "same_question", "scope_relation",
                     "relationship", "dependency", "dep_direction"],
        "properties": {
            "index": {"type": "integer"},
            "same_question": {"type": "string",
                              "enum": ["SAME", "DIFFERENT", "UNRESOLVED"]},
            "scope_relation": {"type": "string", "enum": SCOPES},
            "relationship": {"type": "string", "enum": RELATIONSHIPS},
            "dependency": {"type": "string", "enum": DEPS},
            "dep_direction": {"type": "string",
                              "enum": ["A_TO_B", "B_TO_A", "BIDIRECTIONAL",
                                       "NONE"]}}}}},
}


def pair_id(aid1: str, aid2: str) -> str:
    a, b = sorted([aid1, aid2])
    return derived_id("PAIR", {"a": a, "b": b, "purpose": "SEMANTIC_COMPARISON"})


def verdict_key(ver1: str, ver2: str) -> str:
    a, b = sorted([ver1, ver2])
    return jcs_sha256({"a": a, "b": b, "prompt": PROMPT_VERSION})


# ---------- детерминированные scope-подписи и предклассификация ----------

def _qual_predicates(node: dict, acc: set) -> None:
    op = node.get("op")
    if op in ("AND", "OR"):
        for c in node["children"]:
            _qual_predicates(c, acc)
    elif op == "PREDICATE" and node.get("field") not in ("room_type",
                                                         "zone_types",
                                                         "residential_domain"):
        acc.add((node["field"], str(node.get("eq"))))
    elif op == "UNKNOWN":
        acc.add(("__unknown__", node.get("reason", "")[:40]))


def scope_signature(atom: dict) -> dict:
    rooms = sorted({b.get("room_type") or "" for b in
                    atom["applicability"]["branches"]})
    zones = sorted({z for b in atom["applicability"]["branches"]
                    for z in (b.get("zone_types") or [])})
    quals: set = set()
    _qual_predicates(atom["applicability"]["ast"], quals)
    return {"rooms": rooms, "zones": zones,
            "qualifiers": sorted(f"{k}={v}" for k, v in quals)}


def scope_relation_det(s1: dict, s2: dict) -> str:
    if any(q.startswith("__unknown__") for q in s1["qualifiers"] + s2["qualifiers"]):
        return "UNKNOWN"
    r1, r2 = set(s1["rooms"]), set(s2["rooms"])
    universal = {"universal_residential", ""}
    if s1 == s2:
        return "EQUIVALENT"
    if (r1 & r2) or (r1 & universal) or (r2 & universal):
        return "OVERLAPPING"
    return "DISJOINT"


def _num_key(atom: dict):
    nv = atom.get("numeric_view") or {}
    if nv.get("status", "").startswith("OK"):
        return (nv.get("dimension"), nv.get("value"), tuple(nv.get("range") or []))
    return None


def _slot_core(atom: dict) -> str:
    s = dict(atom["slot"])
    s.pop("condition", None)
    return jcs_sha256(s)


def preclassify(a1: dict, a2: dict) -> dict | None:
    """Детерминированный вердикт, где он безопасен; None -> нужен LLM."""
    same_rec = (a1["observation"]["logical_package_key"],
                a1["observation"]["record_id"]) == \
               (a2["observation"]["logical_package_key"],
                a2["observation"]["record_id"])
    s1, s2 = scope_signature(a1), scope_signature(a2)
    srel = scope_relation_det(s1, s2)
    core_eq = _slot_core(a1) == _slot_core(a2)
    cond_eq = (a1["slot"].get("condition") or None) == \
              (a2["slot"].get("condition") or None)
    n1, n2 = _num_key(a1), _num_key(a2)

    if same_rec and not core_eq:
        # разные аспекты одной записи: COMPLEMENTARY, кандидат в QUALIFIES
        # оставляем LLM только пары с одинаковым quantity_kind (там зависимость)
        if a1["claim"].get("quantity_kind") != a2["claim"].get("quantity_kind"):
            return {"same_question": "DIFFERENT",
                    "relationship": "COMPLEMENTARY",
                    "scope_relation": srel, "dependency": "NONE",
                    "dep_direction": "NONE", "basis": "DET:sibling_diff_qk"}
        return None
    if core_eq and cond_eq:
        if srel == "EQUIVALENT" and n1 and n1 == n2:
            return {"same_question": "SAME",
                    "relationship": "SEMANTIC_DUPLICATE",
                    "scope_relation": srel, "dependency": "NONE",
                    "dep_direction": "NONE", "basis": "DET:same_slot_value_scope"}
        if srel == "DISJOINT":
            return {"same_question": "SAME", "relationship": "SCOPED_VARIANT",
                    "scope_relation": srel, "dependency": "NONE",
                    "dep_direction": "NONE", "basis": "DET:same_slot_disjoint"}
    if srel == "DISJOINT" and not core_eq:
        return {"same_question": "DIFFERENT",
                "relationship": "RELATED_NOT_SAME",
                "scope_relation": srel, "dependency": "NONE",
                "dep_direction": "NONE", "basis": "DET:disjoint_diff_slot"}
    return None


# ---------- LLM-судья ----------

def _atom_brief(atom: dict) -> str:
    c = atom["claim"]
    subj = (c.get("subject") or {}).get("source_label") or \
        (c.get("entities") or [{}])[0].get("source_label", "") \
        if c.get("entities") else (c.get("subject") or {}).get("source_label", "")
    val = c.get("value_original")
    rng = c.get("range_original")
    scope = scope_signature(atom)
    parts = [
        f"subj={subj!r}",
        f"metric={c.get('metric') or c.get('presence_phrase', '')!r}",
        f"op={c.get('comparison_operator')}",
        f"val={val if val is not None else rng}{c.get('unit_original') or ''}",
        f"vt={c.get('value_type')}", f"strength={atom['strength']['effective']}",
        f"cond={((atom['slot'].get('condition') or '') or '-')[:60]!r}",
        f"rooms={','.join(scope['rooms'])[:60]}",
        f"quals={';'.join(scope['qualifiers'])[:60]}",
        f"concept={str(atom['parent_record'].get('concept') or '')[:110]!r}",
    ]
    return " ".join(parts)


def load_verdict_registry() -> dict:
    if VERDICTS_PATH.exists():
        return {r["verdict_key"]: r for r in read_jsonl(VERDICTS_PATH)}
    return {}


def save_verdict_registry(reg: dict) -> None:
    rows = [reg[k] for k in sorted(reg)]
    write_jsonl(VERDICTS_PATH, rows)


def judge_pairs(pairs: list[tuple[dict, dict]], stats: LLMStats,
                batch_size: int = 8,
                pilot_size: int = 96,
                budget_usd: float = 60.0,
                model: str = MODEL_CHEAP,
                save: bool = True) -> tuple[dict, dict]:
    """-> ({verdict_key: verdict}, отчёт). save=False — для параллельных
    чанков: реестр сохраняет ЕДИНСТВЕННЫЙ writer выше (гонка снапшотов)."""
    reg = load_verdict_registry()
    todo = []
    for a1, a2 in pairs:
        k = verdict_key(a1["atomic_claim_version_uid"],
                        a2["atomic_claim_version_uid"])
        if k not in reg:
            todo.append((k, a1, a2))
    report = {"pairs_total": len(pairs), "from_registry": len(pairs) - len(todo),
              "llm_needed": len(todo), "llm_done": 0, "failed_batches": 0,
              "forecast_usd": None, "pilot": None}

    def run_batch(batch) -> int:
        user = "Pairs:\n" + "\n".join(
            f"[{i}] A: {_atom_brief(a1)}\n    B: {_atom_brief(a2)}"
            for i, (_, a1, a2) in enumerate(batch))
        obj = call_json(model, _SYS, user, "pair_verdicts", _SCHEMA, stats)
        got = 0
        for it in obj.get("pairs", []):
            i = it.get("index")
            if isinstance(i, int) and 0 <= i < len(batch):
                k, a1, a2 = batch[i]
                # инвариант F37/38: DISJOINT не бывает dup/conflict
                rel = it["relationship"]
                if it["scope_relation"] == "DISJOINT" and rel in (
                        "EXACT_DUPLICATE", "SEMANTIC_DUPLICATE", "TRUE_CONFLICT"):
                    rel = "SCOPED_VARIANT" if it["same_question"] == "SAME" \
                        else "RELATED_NOT_SAME"
                reg[k] = {"verdict_key": k,
                          "pair_id": pair_id(a1["atomic_claim_id"],
                                             a2["atomic_claim_id"]),
                          "a": a1["atomic_claim_id"], "b": a2["atomic_claim_id"],
                          "same_question": it["same_question"],
                          "scope_relation": it["scope_relation"],
                          "relationship": rel,
                          "dependency": it["dependency"],
                          "dep_direction": it["dep_direction"],
                          "basis": "LLM", "model": model,
                          "prompt_version": PROMPT_VERSION}
                got += 1
        return got

    batches = [todo[i:i + batch_size] for i in range(0, len(todo), batch_size)]
    n_pilot_batches = max(1, min(len(batches), pilot_size // batch_size))
    spent_before = stats.cost_usd
    for bi, batch in enumerate(batches):
        try:
            got = run_batch(batch)
        except Exception as e:  # noqa: BLE001 — счётчик отказов, не молчание
            report["failed_batches"] += 1
            print(f"ОТКАЗ judge-батча {bi + 1}/{len(batches)}: {e}")
            if bi < n_pilot_batches:
                raise SystemExit("БЛОК: пилот вердиктов пар провалился")
            continue
        report["llm_done"] += got
        if bi + 1 == n_pilot_batches and len(batches) > n_pilot_batches:
            pilot_cost = stats.cost_usd - spent_before
            per_batch = pilot_cost / n_pilot_batches
            forecast = per_batch * len(batches)
            report["pilot"] = {"batches": n_pilot_batches,
                               "answered": report["llm_done"],
                               "cost_usd": round(pilot_cost, 4)}
            report["forecast_usd"] = round(forecast, 2)
            print(f"ПРОГНОЗ (после пилота {n_pilot_batches} батчей, "
                  f"${pilot_cost:.3f}): полный прогон ~${forecast:.2f} "
                  f"({len(batches)} батчей, {len(todo)} пар)")
            if forecast > budget_usd:
                if save:
                    save_verdict_registry(reg)
                raise SystemExit(f"БЛОК: прогноз ${forecast:.2f} > бюджета "
                                 f"${budget_usd} — эскалация владельцу")
    if save:
        save_verdict_registry(reg)
    out = {}
    for a1, a2 in pairs:
        k = verdict_key(a1["atomic_claim_version_uid"],
                        a2["atomic_claim_version_uid"])
        if k in reg:
            out[k] = reg[k]
    return out, report
