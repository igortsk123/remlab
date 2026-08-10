"""Волна KB6 (PHASE 7/7B/7C) — retrieval-слои поверх canonical.

- 07_retrieval_records.jsonl: единицы retrieval = scope-однородные canonical
  варианты (не family-unions); RU-алиасы — derived metadata (числа/якоря
  не переводятся);
- 07b_applicability_index.jsonl: completeness-first индекс + трёхзначный
  матчинг MATCH/MISMATCH/UNKNOWN (OR между ветками, AND внутри; unknown
  селектор ≠ wildcard; optional UNSPECIFIED — без предиката; OPAQUE не
  становится MATCH); оракул — полноскановый reference evaluator по атомам;
- 07c_context_closure_index.jsonl: fixed-point closure по verified-рёбрам
  (варианты семьи, конфликт-группы целиком, mandatory-зависимости).
"""
from __future__ import annotations

from pathlib import Path

from .canonical import derived_id
from .io import read_jsonl, write_json, write_jsonl
from .llm import MODEL_CHEAP, LLMStats, call_json
from .phase4 import RUNTIME_CAPABILITIES

REPO_ROOT = Path(__file__).resolve().parents[3]
RU_ALIAS_PATH = REPO_ROOT / "remlab_knowledge_db_v1" / "registries" / \
    "ru_aliases.json"

_RU_SYS = (
    "Translate short interior-design retrieval phrases from English to Russian "
    "for search aliases. Keep terminology natural for интерьер/ремонт domain. "
    "Numbers/units unchanged. Return concise phrases, no explanations."
)
_RU_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["index", "ru"],
        "properties": {"index": {"type": "integer"},
                       "ru": {"type": "string"}}}}},
}


# ---------- retrieval text ----------

def _canonical_text(c: dict, by_id: dict) -> str:
    m0 = by_id[c["member_ids"][0]]
    claim = m0["claim"]
    subj = (claim.get("subject") or {}).get("source_label") or \
        (claim.get("entities") or [{}])[0].get("source_label") \
        if claim.get("entities") else (claim.get("subject") or {}).get("source_label")
    svs = c["scoped_variant_signature"]
    vals = []
    for v in c.get("value_variants", [])[:4]:
        if v.get("value"):
            vals.append(f"{v['operator'] or ''} {v['value']}{v['unit'] or ''}"
                        f" [{v['strength']}]")
        elif v.get("range") and any(v["range"]):
            vals.append(f"{v['range'][0]}..{v['range'][1]}{v['unit'] or ''}"
                        f" [{v['strength']}]")
    parts = [
        subj or claim.get("presence_phrase") or "",
        claim.get("metric") or "",
        "; ".join(vals),
        "rooms: " + ",".join(svs.get("rooms") or []),
        ("cond: " + svs["condition"]) if svs.get("condition") else "",
        str(m0["parent_record"].get("concept") or "")[:160],
    ]
    return " | ".join(p for p in parts if p)[:500]


def _ru_aliases(texts: dict[str, str], stats: LLMStats) -> dict[str, str]:
    """cid -> ru. Канон — registries/ru_aliases.json (git), реплей без сети."""
    import os

    from .io import load_json_strict, write_json as _wj
    reg = {}
    if RU_ALIAS_PATH.exists():
        reg = load_json_strict(RU_ALIAS_PATH)["aliases"]
    missing = [(cid, t) for cid, t in sorted(texts.items()) if cid not in reg]
    batches = [missing[i:i + 20] for i in range(0, len(missing), 20)]
    failed = 0
    for bi, b in enumerate(batches):
        if os.environ.get("KDB_NO_LLM"):
            break
        user = "Phrases:\n" + "\n".join(
            f"{i}: {t[:220]}" for i, (_, t) in enumerate(b))
        try:
            obj = call_json(MODEL_CHEAP, _RU_SYS, user, "ru_aliases",
                            _RU_SCHEMA, stats)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ОТКАЗ ru-alias батча {bi + 1}/{len(batches)}: {e}")
            if bi == 0:
                raise SystemExit("БЛОК: пилот RU-алиасов провалился")
            continue
        for it in obj.get("items", []):
            i = it.get("index")
            if isinstance(i, int) and 0 <= i < len(b):
                reg[b[i][0]] = it["ru"][:300]
    _wj(RU_ALIAS_PATH, {"artifact": "ru_aliases",
                        "note": "RU-поисковые алиасы canonical-вариантов "
                                "(derived metadata; цитаты/числа не трогаем)",
                        "aliases": {k: reg[k] for k in sorted(reg)}})
    return reg


# ---------- applicability matching (7B) ----------

def _eval_pred(node: dict, ctx: dict) -> str:
    """-> MATCH | MISMATCH | UNKNOWN для одного предиката."""
    f = node.get("field")
    if f == "residential_domain":
        return "MATCH"  # рантайм RemLab всегда жилой
    if f == "room_type":
        want = node.get("eq")
        have = ctx.get("room_type")
        if have is None:
            return "UNKNOWN"
        return "MATCH" if have == want else "MISMATCH"
    if f == "zone_types":
        want = set(node.get("overlaps") or [])
        have = ctx.get("zone_types")
        if have is None:
            return "UNKNOWN"
        return "MATCH" if want & set(have) else "MISMATCH"
    cap = RUNTIME_CAPABILITIES.get(f)
    have = ctx.get(f)
    if have is None:
        # NOT_EVALUABLE qualifier без данных -> UNKNOWN (не negative!)
        return "UNKNOWN"
    return "MATCH" if str(have) == str(node.get("eq")) else "MISMATCH"


def eval_ast(node: dict, ctx: dict) -> str:
    op = node.get("op")
    if op == "TRUE":
        return "MATCH"
    if op == "UNKNOWN":
        return "UNKNOWN"
    if op == "PREDICATE":
        return _eval_pred(node, ctx)
    if op == "AND":
        res = [eval_ast(c, ctx) for c in node["children"]]
        if "MISMATCH" in res:
            return "MISMATCH"
        if "UNKNOWN" in res:
            return "UNKNOWN"
        return "MATCH"
    if op == "OR":
        res = [eval_ast(c, ctx) for c in node["children"]]
        if "MATCH" in res:
            return "MATCH"
        if "UNKNOWN" in res:
            return "UNKNOWN"
        return "MISMATCH"
    return "UNKNOWN"


def run_phase6(staging: Path) -> dict:
    atoms = read_jsonl(staging / "02_atomic_claims.jsonl")
    by_id = {a["atomic_claim_id"]: a for a in atoms}
    canon = read_jsonl(staging / "06_canonical_knowledge.jsonl")
    conflicts = read_jsonl(staging / "05_conflict_groups.jsonl")
    deps = read_jsonl(staging / "06b_claim_dependency_graph.jsonl")

    canon_of_atom = {m: c["canonical_claim_id"] for c in canon
                     for m in c["member_ids"]}
    stats = LLMStats()

    # --- 07: retrieval records ---
    texts = {c["canonical_claim_id"]: _canonical_text(c, by_id) for c in canon}
    ru = _ru_aliases(texts, stats)
    retr = []
    for c in canon:
        cid = c["canonical_claim_id"]
        svs = c["scoped_variant_signature"]
        m0 = by_id[c["member_ids"][0]]
        retr.append({
            "retrieval_id": derived_id("RETR", {"canonical": cid,
                                                "variant": "base",
                                                "lang": "en+ru"}),
            "canonical_claim_id": cid,
            "claim_family_id": c["claim_family_id"],
            "retrieval_text": texts[cid],
            "ru_alias": ru.get(cid),
            "filters": {
                "rooms": svs.get("rooms") or [],
                "zones": svs.get("zones") or [],
                "qualifiers": svs.get("qualifiers") or [],
                "inherited_overlay_qualifiers":
                    svs.get("inherited_overlay_qualifiers") or [],
                "dimension_type": m0["parent_record"].get("dimension_type")
                or m0["claim"].get("dimension_type"),
                "quantity_kind": m0["claim"].get("quantity_kind"),
                "strengths": c["strengths"],
                "utility_classes": c["utility_classes_union"],
                "has_conflicts": bool(c["conflict_group_ids"]),
                "has_dependencies": bool(c["dependency_edge_ids"]),
            },
            "judge_backbone_member_count": len(c["judge_backbone_member_ids"]),
            "member_count": c["member_count"],
            "source_trace": {"members": c["member_ids"][:20]},
        })
    retr.sort(key=lambda r: r["retrieval_id"])
    write_jsonl(staging / "07_retrieval_records.jsonl", retr)

    # --- 07b: exhaustive applicability index ---
    idx_rows = []
    for c in canon:
        cid = c["canonical_claim_id"]
        members = c["member_ids"]
        m0 = by_id[members[0]]
        caps = sorted({f for m in members
                       for f in _required_caps(by_id[m])})
        evaluable = all(RUNTIME_CAPABILITIES.get(f, "NOT_EVALUABLE")
                        .startswith("EVALUABLE") for f in caps)
        idx_rows.append({
            "canonical_claim_id": cid,
            "member_ids": members,
            "applicability_ast_members": [by_id[m]["applicability"]["ast"]
                                          for m in members],
            "runtime_capabilities_required": caps,
            "runtime_evaluability": "EVALUABLE" if evaluable
            else "NOT_FULLY_EVALUABLE",
            "utility_classes": c["utility_classes_union"],
            "judge_backbone_eligible_members":
                c["judge_backbone_member_ids"],
            "quantification_kind": (m0.get("views", {})
                                    .get("quantification_view", {})
                                    .get("kind")),
            "target_absence_is_violation_candidate":
                (m0.get("views", {}).get("constraint_target_view", {})
                 .get("target_absence_is_violation_candidate", False)),
        })
    idx_rows.sort(key=lambda r: r["canonical_claim_id"])
    write_jsonl(staging / "07b_applicability_index.jsonl", idx_rows)

    # --- oracle: индексный матч vs полноскановый reference (0 FN) ---
    test_contexts = [
        {"room_type": "living_room", "zone_types": ["conversation", "tv_media"]},
        {"room_type": "bedroom", "zone_types": ["sleeping", "storage"]},
        {"room_type": "kitchen", "zone_types": ["cooking", "food_preparation"]},
        {"room_type": "bathroom", "zone_types": ["bathing_shower", "toilet"]},
        {"room_type": "hallway", "zone_types": ["circulation"],
         "jurisdiction": "us_north_america"},
    ]
    oracle_report = []
    for ctx in test_contexts:
        idx_match = set()
        for row in idx_rows:
            res = [eval_ast(ast, ctx) for ast in row["applicability_ast_members"]]
            if "MATCH" in res:
                idx_match.add(row["canonical_claim_id"])
        ref_match = set()
        for a in atoms:  # reference: полноскановый проход по атомам
            if eval_ast(a["applicability"]["ast"], ctx) == "MATCH":
                ref_match.add(canon_of_atom[a["atomic_claim_id"]])
        fn = ref_match - idx_match
        oracle_report.append({"context": ctx, "index_matches": len(idx_match),
                              "reference_matches": len(ref_match),
                              "false_negatives": len(fn)})
        if fn:
            raise SystemExit(f"БЛОК: oracle нашёл {len(fn)} false negatives "
                             f"для контекста {ctx}")

    # --- 07c: closure (fixed-point, cycle-safe) ---
    fam_variants: dict[str, list[str]] = {}
    for c in canon:
        fam_variants.setdefault(c["claim_family_id"], []).append(
            c["canonical_claim_id"])
    conf_of_canon: dict[str, set] = {}
    for g in conflicts:
        cids = {canon_of_atom[m] for m in g["member_ids"]}
        for cid in cids:
            conf_of_canon.setdefault(cid, set()).update(cids)
    dep_edges_canon: dict[str, set] = {}
    dep_supp_canon: dict[str, set] = {}
    for d in deps:
        f, t = canon_of_atom[d["from_atomic_claim_id"]], \
            canon_of_atom[d["to_atomic_claim_id"]]
        if f == t:
            continue
        target = dep_edges_canon if d["mandatory_closure"] else dep_supp_canon
        target.setdefault(f, set()).add(t)
        target.setdefault(t, set()).add(f)

    closure_rows = []
    for c in canon:
        cid = c["canonical_claim_id"]
        mandatory = set()
        frontier = {cid}
        seen = {cid}
        while frontier:  # fixed point, циклы гасятся seen-set
            nxt = set()
            for x in frontier:
                nxt |= conf_of_canon.get(x, set())
                nxt |= dep_edges_canon.get(x, set())
            nxt -= seen
            mandatory |= nxt
            seen |= nxt
            frontier = nxt
        closure_rows.append({
            "canonical_claim_id": cid,
            "family_variant_ids": sorted(x for x in
                                         fam_variants[c["claim_family_id"]]
                                         if x != cid)[:50],
            "mandatory_closure_ids": sorted(mandatory),
            "supplemental_closure_ids": sorted(
                dep_supp_canon.get(cid, set()) - mandatory)[:50],
        })
    closure_rows.sort(key=lambda r: r["canonical_claim_id"])
    write_jsonl(staging / "07c_context_closure_index.jsonl", closure_rows)

    report = {
        "retrieval_records": len(retr),
        "ru_aliases": sum(1 for r in retr if r["ru_alias"]),
        "applicability_rows": len(idx_rows),
        "evaluable_rows": sum(1 for r in idx_rows
                              if r["runtime_evaluability"] == "EVALUABLE"),
        "oracle": oracle_report,
        "closure_rows": len(closure_rows),
        "closure_nonempty": sum(1 for r in closure_rows
                                if r["mandatory_closure_ids"]),
        "llm": stats.as_dict(),
    }
    write_json(staging / "kb6_report.json", report)
    return report


def _required_caps(atom: dict) -> set:
    caps = {"room_type_context"}
    import json as _j
    s = _j.dumps(atom["applicability"]["ast"])
    for f in ("mobility_context", "jurisdiction", "activity_context",
              "dwelling_feature", "market_basis"):
        if f'"{f}"' in s:
            caps.add(f)
    if '"zone_types"' in s:
        caps.add("zone_types_context")
    return caps
