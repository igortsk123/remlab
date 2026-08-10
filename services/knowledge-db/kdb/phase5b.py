"""Волна KB5b (PHASE 4/5/6/6B) — семьи, конфликты, canonical, зависимости.

Ключевые инварианты:
- F35: семья НЕ по связности — каждый член удовлетворяет resolved-подписи;
  merge подписей только при консистентности (SAME-ребро есть, DIFFERENT-рёбер
  между группами нет), иначе split + review;
- крит.№7 плана: подписи строятся ТОЛЬКО из замороженных реестров (vocab,
  family_signature_map) — пересборка с холодным LLM-кэшем даёт те же ID;
- F36: разные значения/силы — одна семья; F39: canonical scope-однороден;
- 6B: mandatory closure только у VERIFIED-рёбер (структурные sibling-связи);
  LLM-рёбра — PROVISIONAL, включаются с меткой.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from . import identity as ident
from .canonical import derived_id, jcs_sha256
from .io import load_json_strict, read_jsonl, write_json, write_jsonl
from .pairing import reference_concept, subject_concept
from .verdicts import scope_signature
from .vocab import load_registry as load_vocab

REPO_ROOT = Path(__file__).resolve().parents[3]
FAMSIG_PATH = REPO_ROOT / "remlab_knowledge_db_v1" / "registries" / \
    "family_signature_map.json"

CONFLICT_RELS = {"TRUE_CONFLICT", "POTENTIAL_CONFLICT",
                 "SAME_PRIMARY_QUANTITY_WITH_EQUIVALENCY_DISCREPANCY"}
DEP_CLOSURE = {  # спека 6B: классы closure по типу ребра
    "QUALIFIES": "BIDIRECTIONAL_MANDATORY",
    "EXCEPTION_TO": "BIDIRECTIONAL_MANDATORY",
    "OVERRIDES_IN_SCOPE": "BIDIRECTIONAL_MANDATORY",
    "TRADEOFF_WITH": "BIDIRECTIONAL_MANDATORY",
    "LIMITS_APPLICABILITY_OF": "TARGET_TO_MODIFIER",
    "VALUE_REFERENCE_TO": "SOURCE_TO_REFERENCED",
    "PREREQUISITE_FOR": "SOURCE_TO_REFERENCED",
    "EXPLAINS": "SUPPLEMENTAL",
    "ILLUSTRATES": "SUPPLEMENTAL",
}


def _norm(s) -> str | None:
    if s in (None, "", "unknown"):
        return None
    return " ".join(str(s).split()).lower()[:80]


def family_candidate_signature(atom: dict, vocab_map: dict) -> dict:
    """ЧТО за вопрос (без ответа/силы/провенанса; scope — на уровне variant)."""
    k = atom["slot"].get("k")
    if k == "M":
        return {
            "k": "M",
            "subject": subject_concept(atom, vocab_map),
            "reference": reference_concept(atom, vocab_map),
            "quantity_kind": atom["claim"].get("quantity_kind"),
            "metric": _norm(atom["claim"].get("metric")),
            "measured_from": _norm(atom["claim"].get("measured_from")),
            "measured_to": _norm(atom["claim"].get("measured_to")),
        }
    if k == "R_PRESENCE":
        return {"k": "R_PRESENCE",
                "subject": subject_concept(atom, vocab_map)
                or _norm(atom["claim"].get("target_hint")),
                "quantifier": "EXISTS_MIN"}
    return {"k": "R",
            "subject": subject_concept(atom, vocab_map),
            "relation_type": atom["claim"].get("relation_type"),
            "relation_label": _norm(atom["claim"].get("source_relation_label")),
            "dimension_type": atom["claim"].get("dimension_type"),
            "fingerprint": atom["parent_record"].get("context_fingerprint")}


def scoped_variant_signature(atom: dict, overlays: list[dict]) -> dict:
    from .phase4 import overlay_matches
    sig = scope_signature(atom)
    inherited = sorted(
        f"{o['qualifier_predicate']['qualifier']}="
        f"{o['qualifier_predicate']['value']}"
        for o in overlays if overlay_matches(o, atom))
    return {
        "rooms": sig["rooms"], "zones": sig["zones"],
        "qualifiers": sig["qualifiers"],
        "inherited_overlay_qualifiers": inherited,
        "condition": _norm(atom["slot"].get("condition")),
        "value_type": atom["claim"].get("value_type"),
    }


def _load_famsig_registry() -> dict:
    if FAMSIG_PATH.exists():
        return load_json_strict(FAMSIG_PATH)["equivalences"]
    return {}


def _save_famsig_registry(reg: dict) -> None:
    write_json(FAMSIG_PATH, {
        "artifact": "family_signature_map",
        "note": "канон эквивалентности candidate-подписей семей: key -> anchor "
                "(лексикографически меньший ключ группы). Merge только при "
                "консистентности SAME/DIFFERENT-рёбер (F35).",
        "equivalences": {k: reg[k] for k in sorted(reg)},
    })


def build_families(atoms: list[dict], pairs_04a: list[dict],
                   vocab_map: dict) -> tuple[dict, dict, list]:
    """-> (atom_id->family_id, family_id->{...}, review[])."""
    cand_key = {}
    for a in atoms:
        cand_key[a["atomic_claim_id"]] = jcs_sha256(
            family_candidate_signature(a, vocab_map))

    same_edges: dict[tuple[str, str], int] = defaultdict(int)
    diff_edges: dict[tuple[str, str], int] = defaultdict(int)
    for row in pairs_04a:
        if row.get("verdict_status") in ("DETERMINISTIC", "LLM"):
            k1, k2 = cand_key.get(row["a"]), cand_key.get(row["b"])
            if not k1 or not k2 or k1 == k2:
                continue
            e = (min(k1, k2), max(k1, k2))
            if row.get("same_question") == "SAME":
                same_edges[e] += 1
            elif row.get("same_question") == "DIFFERENT":
                diff_edges[e] += 1

    reg = _load_famsig_registry()
    review: list = []
    # merge кандидатов: SAME-рёбра без противоречащих DIFFERENT
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            a, b = sorted([rx, ry])
            parent[b] = a

    # применяем сохранённые эквивалентности (prior wins)
    for k, anchor in reg.items():
        union(k, anchor)
    for e, n_same in sorted(same_edges.items()):
        n_diff = diff_edges.get(e, 0)
        if n_diff == 0 and n_same >= 1:
            union(*e)
        elif n_diff > 0:
            review.append({"kind": "INCONSISTENT_SIGNATURE_EDGE",
                           "keys": list(e), "same": n_same, "diff": n_diff})
    # НЕ-транзитивная проверка: внутри итоговой группы не должно быть
    # DIFFERENT-рёбер (inconsistent triangle -> split запрещаем merge)
    groups: dict[str, list[str]] = defaultdict(list)
    for k in set(list(cand_key.values()) + list(parent)):
        groups[find(k)].append(k)
    for root, members in list(groups.items()):
        ms = set(members)
        bad = [e for e in diff_edges
               if e[0] in ms and e[1] in ms and diff_edges[e] > 0]
        if bad:
            # откат merge всей группы к отдельным ключам + review
            for k in members:
                parent[k] = k
            review.append({"kind": "TRIANGLE_SPLIT", "keys": sorted(ms)[:6],
                           "edges": len(bad)})

    # финальные anchors + persist
    new_reg = {}
    groups = defaultdict(list)
    for k in set(cand_key.values()):
        groups[find(k)].append(k)
    for root, members in groups.items():
        anchor = min(members)
        for m in members:
            if m != anchor:
                new_reg[m] = anchor
    reg.update(new_reg)
    _save_famsig_registry(reg)

    fam_of: dict[str, str] = {}
    families: dict[str, dict] = {}
    for a in atoms:
        k = cand_key[a["atomic_claim_id"]]
        anchor = reg.get(k, k)
        fid = derived_id("FAM", {"resolved_signature": anchor})
        fam_of[a["atomic_claim_id"]] = fid
        fam = families.setdefault(fid, {
            "claim_family_id": fid, "signature_anchor": anchor,
            "member_ids": [], "candidate_keys": set()})
        fam["member_ids"].append(a["atomic_claim_id"])
        fam["candidate_keys"].add(k)
    for f in families.values():
        f["member_ids"].sort()
        f["member_count"] = len(f["member_ids"])
        f["membership_fingerprint_sha256"] = jcs_sha256(f["member_ids"])
        f["candidate_keys"] = sorted(f["candidate_keys"])
    return fam_of, families, review


def run_phase5b(staging: Path) -> dict:
    atoms = read_jsonl(staging / "02_atomic_claims.jsonl")
    by_id = {a["atomic_claim_id"]: a for a in atoms}
    pairs = read_jsonl(staging / "04a_semantic_comparison_candidates.jsonl")
    overlays = [o for o in read_jsonl(staging / "03d_source_scope_overlays.jsonl")]
    origins = {o["atomic_claim_id"]: o for o in
               read_jsonl(staging / "03b2_claim_corroboration_origins.jsonl")}
    vocab_map = load_vocab()

    fam_of, families, review = build_families(atoms, pairs, vocab_map)

    # F35: DIFFERENT-вердикты ВНУТРИ семьи. Для смердженных (несколько
    # candidate-подписей) это chaining-ошибка -> БЛОК; для одно-подписных —
    # разногласие судьи с подписью (EXAMPLE-ряды таблиц и т.п.) -> REVIEW,
    # семья помечается, не рвётся молча.
    cand_key_of = {}
    for a in atoms:
        cand_key_of[a["atomic_claim_id"]] = jcs_sha256(
            family_candidate_signature(a, vocab_map))
    same_key_diff: dict[str, int] = {}
    cross_key_diff: dict[str, int] = {}
    for row in pairs:
        if row.get("same_question") == "DIFFERENT" \
                and fam_of.get(row["a"]) == fam_of.get(row["b"]):
            fid = fam_of[row["a"]]
            if cand_key_of[row["a"]] == cand_key_of[row["b"]]:
                # разногласие судьи с подписью ВНУТРИ одного слота -> REVIEW
                same_key_diff[fid] = same_key_diff.get(fid, 0) + 1
            else:
                # DIFFERENT между смердженными подписями = chaining-ошибка
                cross_key_diff[fid] = cross_key_diff.get(fid, 0) + 1
    for fid, cnt in sorted(same_key_diff.items()):
        families[fid]["signature_consistency"] = "REVIEW_JUDGE_DISAGREEMENT"
        families[fid]["internal_different_pairs"] = cnt
    for fid, cnt in sorted(cross_key_diff.items()):
        review.append({"kind": "CHAINING_IN_MERGED_FAMILY",
                       "family": fid, "different_pairs": cnt})
    if cross_key_diff:
        raise SystemExit(f"БЛОК: chaining в {len(cross_key_diff)} семьях — "
                         "DIFFERENT между смердженными подписями")

    # --- 6B: зависимости ---
    dep_rows = []
    for row in pairs:
        dep = row.get("dependency")
        if not dep or dep == "NONE":
            continue
        a, b = row["a"], row["b"]
        if row.get("dep_direction") == "B_TO_A":
            frm, to = b, a
        else:
            frm, to = a, b
        same_rec = (by_id[a]["observation"]["record_id"]
                    == by_id[b]["observation"]["record_id"]
                    and by_id[a]["observation"]["logical_package_key"]
                    == by_id[b]["observation"]["logical_package_key"])
        status = "VERIFIED_STRUCTURAL" if same_rec else "PROVISIONAL_LLM"
        dep_rows.append({
            "edge_id": derived_id("DEP", {"from": frm, "to": to, "type": dep}),
            "from_atomic_claim_id": frm, "to_atomic_claim_id": to,
            "type": dep,
            "direction": row.get("dep_direction"),
            "closure_class": DEP_CLOSURE.get(dep, "SUPPLEMENTAL"),
            "verification_status": status,
            "mandatory_closure": status == "VERIFIED_STRUCTURAL"
            and DEP_CLOSURE.get(dep) == "BIDIRECTIONAL_MANDATORY",
            "basis": row.get("verdict_status"),
        })
    seen_edges = set()
    dep_rows = [d for d in dep_rows
                if not (d["edge_id"] in seen_edges or seen_edges.add(d["edge_id"]))]

    # --- PHASE 5: конфликты (scope-aware, dependency-check) ---
    dep_pairs = {tuple(sorted([d["from_atomic_claim_id"],
                               d["to_atomic_claim_id"]]))
                 for d in dep_rows if d["type"] in ("QUALIFIES", "EXCEPTION_TO",
                                                    "OVERRIDES_IN_SCOPE",
                                                    "LIMITS_APPLICABILITY_OF")}
    conflict_members: dict[str, dict] = {}
    for row in pairs:
        if row.get("relationship") not in CONFLICT_RELS:
            continue
        if row.get("scope_relation") not in ("EQUIVALENT", "OVERLAPPING"):
            continue  # DISJOINT/UNKNOWN не конфликт (F38)
        if tuple(sorted([row["a"], row["b"]])) in dep_pairs:
            continue  # general+exception — не конфликт
        fid = fam_of.get(row["a"])
        if fid != fam_of.get(row["b"]):
            continue  # конфликт только внутри comparable вопроса
        svs = jcs_sha256({"a": scoped_variant_signature(by_id[row["a"]], overlays),
                          "b": scoped_variant_signature(by_id[row["b"]], overlays),
                          "scope_relation": row["scope_relation"]})
        cid = derived_id("CONF", {"family": fid, "conflict_scope": svs})
        grp = conflict_members.setdefault(cid, {
            "conflict_group_id": cid, "claim_family_id": fid,
            "scope_relation": row["scope_relation"],
            "member_ids": set(), "pair_rows": [],
            "subtype": row.get("relationship"),
            "resolution_status": "UNRESOLVED"})
        grp["member_ids"].update([row["a"], row["b"]])
        grp["pair_rows"].append({"pair_id": row["pair_id"],
                                 "relationship": row["relationship"],
                                 "adversarial": row.get("adversarial")})
    conflict_rows = []
    for cid, g in sorted(conflict_members.items()):
        members = sorted(g["member_ids"])
        conflict_rows.append({
            **{k: g[k] for k in ("conflict_group_id", "claim_family_id",
                                 "scope_relation", "subtype",
                                 "resolution_status")},
            "member_ids": members, "member_count": len(members),
            "membership_fingerprint_sha256": jcs_sha256(members),
            "pair_rows": sorted(g["pair_rows"], key=lambda r: r["pair_id"]),
            "member_values": [{
                "atomic_claim_id": m,
                "value": (by_id[m].get("numeric_view") or {}).get("value"),
                "range": (by_id[m].get("numeric_view") or {}).get("range"),
                "strength": by_id[m]["strength"]["effective"],
            } for m in members],
        })

    # --- PHASE 6: canonical (scope-однородные варианты) ---
    canon: dict[str, dict] = {}
    for a in atoms:
        fid = fam_of[a["atomic_claim_id"]]
        svs = scoped_variant_signature(a, overlays)
        cid = derived_id("CANON", {"family": fid, "scoped_variant": svs})
        c = canon.setdefault(cid, {
            "canonical_claim_id": cid, "claim_family_id": fid,
            "scoped_variant_signature": svs,
            "effective_source_scope_signature": jcs_sha256(svs),
            "member_ids": [], "production_policy_status":
                "UNDECIDED_IN_THIS_PIPELINE"})
        c["member_ids"].append(a["atomic_claim_id"])
    for cid, c in canon.items():
        ms = sorted(c["member_ids"])
        c["member_ids"] = ms
        c["member_count"] = len(ms)
        c["membership_fingerprint_sha256"] = jcs_sha256(ms)
        c["judge_backbone_member_ids"] = [
            m for m in ms if by_id[m]["utility"]["judge_backbone_eligible"]]
        c["supplemental_member_ids"] = [
            m for m in ms if m not in set(c["judge_backbone_member_ids"])]
        c["utility_classes_union"] = sorted({
            u for m in ms for u in by_id[m]["utility"]["classes"]})
        c["strengths"] = sorted({by_id[m]["strength"]["effective"] for m in ms
                                 if by_id[m]["strength"]["effective"]})
        c["value_variants"] = [{
            "atomic_claim_id": m,
            "value": (by_id[m].get("numeric_view") or {}).get("value"),
            "range": (by_id[m].get("numeric_view") or {}).get("range"),
            "unit": (by_id[m].get("numeric_view") or {}).get("canonical_unit"),
            "operator": by_id[m]["claim"].get("comparison_operator"),
            "strength": by_id[m]["strength"]["effective"],
        } for m in ms]
        c["provenance"] = {
            "document_count": 1,
            "work_count": 1,
            "lineage_group_count": 1,
            "claim_origin_count": len({origins[m]["origin_group_id"]
                                       for m in ms if m in origins}),
            "unresolved_origin_count": sum(
                1 for m in ms if m in origins and origins[m]["unresolved"]),
            "source_document_ids": [ident.SOURCE_DOCUMENT_ID],
        }
        c["conflict_group_ids"] = sorted({
            r["conflict_group_id"] for r in conflict_rows
            if set(r["member_ids"]) & set(ms)})
        c["dependency_edge_ids"] = sorted({
            d["edge_id"] for d in dep_rows
            if d["from_atomic_claim_id"] in set(ms)
            or d["to_atomic_claim_id"] in set(ms)})

    # --- запись + гейты ---
    fam_rows = []
    for fid, f in sorted(families.items()):
        fam_rows.append({**{k: f[k] for k in (
            "claim_family_id", "signature_anchor", "member_ids", "member_count",
            "membership_fingerprint_sha256", "candidate_keys")},
            "signature_consistency": f.get("signature_consistency", "OK"),
            "internal_different_pairs": f.get("internal_different_pairs", 0)})
    write_jsonl(staging / "04_claim_groups.jsonl", fam_rows)
    write_jsonl(staging / "05_conflict_groups.jsonl", conflict_rows)
    write_jsonl(staging / "06_canonical_knowledge.jsonl",
                [canon[k] for k in sorted(canon)])
    write_jsonl(staging / "06b_claim_dependency_graph.jsonl",
                sorted(dep_rows, key=lambda d: d["edge_id"]))

    # гейт: каждый атом ровно в одной семье и одном canonical
    assert len(fam_of) == len(atoms)
    member_total = sum(f["member_count"] for f in families.values())
    if member_total != len(atoms):
        raise SystemExit(f"БЛОК: члены семей {member_total} != атомов {len(atoms)}")
    canon_total = sum(c["member_count"] for c in canon.values())
    if canon_total != len(atoms):
        raise SystemExit(f"БЛОК: члены canonical {canon_total} != {len(atoms)}")
    # scope-однородность canonical: по построению одна svs — проверим явно
    for c in canon.values():
        sigs = {jcs_sha256(scoped_variant_signature(by_id[m], overlays))
                for m in c["member_ids"]}
        if len(sigs) != 1:
            raise SystemExit(f"БЛОК: canonical {c['canonical_claim_id'][:16]} "
                             "scope-гетерогенен")

    report = {
        "families": len(families),
        "families_judge_disagreement_review": sum(
            1 for f in families.values()
            if f.get("signature_consistency") == "REVIEW_JUDGE_DISAGREEMENT"),
        "families_multi_member": sum(1 for f in families.values()
                                     if f["member_count"] > 1),
        "canonical": len(canon),
        "canonical_multi_member": sum(1 for c in canon.values()
                                      if c["member_count"] > 1),
        "conflict_groups": len(conflict_rows),
        "dependency_edges": len(dep_rows),
        "dependency_verified": sum(1 for d in dep_rows
                                   if d["verification_status"]
                                   == "VERIFIED_STRUCTURAL"),
        "review_items": len(review),
    }
    write_json(staging / "kb5b_report.json", {**report, "review": review[:200]})
    return report
