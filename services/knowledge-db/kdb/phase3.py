"""PHASE 2B-2E (волна KB3) — обогащение и финализация 02_atomic_claims.jsonl.

Пере-эмиссия с СОХРАНЕНИЕМ стабильных ID (крит-находка ревью плана):
- numeric_view (2B), symbolic_view (2C), views (2D), utility (2E);
- нормализация условий: AST-узлы UNKNOWN(OPAQUE_*) заменяются предикатами /
  снимаются в constraint-side по реестру condition_normalization_map;
- presence-атомы (2D) для записей С измерениями, где проза несёт
  cardinality-пропозицию, не покрытую COUNT-измерением (регрессия 4 спеки).
"""
from __future__ import annotations

import copy
from pathlib import Path

from . import identity as ident
from .canonical import derived_id
from .conditions import classify_conditions, norm_condition
from .io import load_json_strict, read_jsonl, write_jsonl
from .llm import LLMStats
from .phase2 import (_applicability, _parent_meta, _pick_anchor,
                     _qualifier_view, evidence_locus)
from .symbolic import build_symbolic_view
from .units import build_numeric_view
from .views import build_utility, build_views, detect_presence


def _collect_conditions(atoms: list[dict]) -> list[str]:
    conds = []
    for a in atoms:
        for b in a["applicability"]["branches"]:
            if b.get("condition_raw"):
                conds.append(b["condition_raw"])
        mc = (a["claim"].get("condition") or "") if a["claim"] else ""
        if mc.strip():
            conds.append(mc)
    return conds


def _apply_condition_map(node: dict, reg: dict, moved: list[dict]) -> dict:
    """Рекурсивная замена UNKNOWN(OPAQUE_*) по реестру нормализации."""
    op = node.get("op")
    if op in ("AND", "OR"):
        children = [_apply_condition_map(c, reg, moved)
                    for c in node["children"]]
        children = [c for c in children if c.get("op") != "TRUE"]
        if not children:
            return {"op": "TRUE"}
        if len(children) == 1:
            return children[0]
        return {"op": op, "children": children}
    if op == "UNKNOWN" and str(node.get("reason", "")).startswith("OPAQUE"):
        cond = node.get("condition_raw", "")
        v = reg.get(norm_condition(cond))
        if not v or v.get("class") == "UNCLASSIFIED":
            return node
        if v["class"] == "APPLICABILITY_QUALIFIER":
            p = v["predicate"]
            return {"op": "PREDICATE", "field": p["qualifier"],
                    "eq": p["value"], "basis": v.get("basis")}
        # TARGET_STATE_CONDITION / EXAMPLE_MARKER: снимаем с applicability
        moved.append({"condition_raw": cond, "class": v["class"],
                      "basis": v.get("basis")})
        return {"op": "TRUE"}
    return node


def _presence_atoms(merged: dict, existing_assertions: set[str]) -> tuple[list, list]:
    atoms, registry = [], []
    for pkg in merged["packages"]:
        pcu = pkg["package_content_uid"]
        lpk = pkg["logical_package_key"]
        for r in pkg["raw"].get("records", []):
            ms = r.get("measurements", [])
            if not ms:
                continue  # записи без измерений уже целиком RECORD_SEMANTIC
            if any(m.get("quantity_kind") == "COUNT" for m in ms):
                continue  # cardinality уже покрыта измерением
            hit = detect_presence(r)
            if not hit:
                continue
            evs = list(r.get("evidence", []))
            ctxs = list(r.get("applicability_contexts", []))
            anchor_uid, q, anchor_payload, _ = _pick_anchor(
                ident.SOURCE_DOCUMENT_ID, evs)
            slot = {"k": "R_PRESENCE",
                    "context_fingerprint": r.get("context_fingerprint"),
                    "quantifier": "EXISTS_MIN",
                    "min_count": hit["min_count"],
                    "target_hint": hit["target_hint"]}
            sassert = derived_id("SASSERT", {
                "doc": ident.SOURCE_DOCUMENT_ID,
                "anchor_locus": anchor_uid, "slot": slot})
            if sassert in existing_assertions:
                continue
            atom_id = derived_id("ATOM", {"source_assertion_uid": sassert})
            version_uid = derived_id("ATOMV", {
                "atomic_claim_id": atom_id,
                "values": {"min_count": hit["min_count"],
                           "phrase": hit["phrase"]},
                "strength": r.get("source_claim_strength"),
                "observation": {"package_content_uid": pcu,
                                "record_id": r["record_id"],
                                "measurement_id": None},
            })
            atom = {
                "atomic_claim_id": atom_id,
                "atomic_claim_version_uid": version_uid,
                "source_assertion_uid": sassert,
                "projection_mode": "RECORD_SEMANTIC",
                "source_document_id": ident.SOURCE_DOCUMENT_ID,
                "source_work_id": ident.SOURCE_WORK_ID,
                "source_independence_group_id": ident.SOURCE_INDEPENDENCE_GROUP_ID,
                "observation": {"package_content_uid": pcu,
                                "logical_package_key": lpk,
                                "record_id": r["record_id"],
                                "measurement_id": None},
                "anchor": {"locus_uid": anchor_uid,
                           "locus_identity_quality": q,
                           **{k: anchor_payload[k] for k in
                              ("master_page", "section", "figure", "table",
                               "row", "col", "anchor")}},
                "slot": slot,
                "bindings": {"context_ids": [c["context_id"] for c in ctxs],
                             "evidence_ids": [e["evidence_id"] for e in evs],
                             "evidence_locus_uids": sorted(
                                 evidence_locus(ident.SOURCE_DOCUMENT_ID, e)[0]
                                 for e in evs)},
                "applicability": _applicability(ctxs, None),
                "qualifiers": _qualifier_view(
                    r, ["population", "sex", "age_group", "percentile",
                        "posture", "mobility_context", "clothing_or_equipment"]),
                "claim": {"presence_phrase": hit["phrase"],
                          "min_count": hit["min_count"],
                          "target_hint": hit["target_hint"],
                          "relation_type": r.get("relation_type"),
                          "dimension_type": r.get("dimension_type")},
                "strength": {"effective": r.get("source_claim_strength"),
                             "origin": "RECORD",
                             "parent_record_strength":
                                 r.get("source_claim_strength")},
                "parent_record": _parent_meta(r),
                "flags": {"needs_verification": True,
                          "has_relationship_expression": False,
                          "review": ["PRESENCE_PATTERN_AUTO"]},
                "views": {
                    "activation_view": {"selector": "APPLICABILITY_AST",
                                        "trigger_semantics": "SCOPE_ONLY",
                                        "runtime_capabilities_required":
                                            ["room_type_context"]},
                    "constraint_target_view": {
                        "constrained_target": None,
                        "reference_target": None,
                        "prohibited_target": None,
                        "target_hint": hit["target_hint"],
                        "target_absence_is_violation_candidate": True},
                    "quantification_view": {"kind": "EXISTS_MIN",
                                            "min": hit["min_count"],
                                            "source_phrase": hit["phrase"],
                                            "basis": "PROSE_PATTERN"},
                    "entity_roles": []},
            }
            atom["utility"] = build_utility(atom)
            atoms.append(atom)
            registry.append({
                "source_assertion_uid": sassert,
                "atomic_claim_id": atom_id,
                "assertion_anchor_locus_uid": anchor_uid,
                "locus_identity_quality": q,
                "revision_status": "SINGLE",
                "slot_collision": False,
                "observations": [atom["observation"]],
                "observation_count": 1,
                "evidence_locus_count": len(atom["bindings"]["evidence_locus_uids"]),
                "support_document_count": 1,
            })
    return atoms, registry


def run_phase3(staging: Path) -> dict:
    atoms = read_jsonl(staging / "02_atomic_claims.jsonl")
    registry = read_jsonl(staging / "02a_source_assertion_revision_registry.jsonl")
    merged = load_json_strict(staging / "01_raw_merged.json")

    # уже финализировано? защищаемся от двойного обогащения
    if atoms and "utility" in atoms[0]:
        raise SystemExit("БЛОК: 02_atomic_claims.jsonl уже финализирован (KB3)")

    llm_stats = LLMStats()
    reg, cond_report = classify_conditions(_collect_conditions(atoms), llm_stats)

    n_numeric = {"CONSISTENT": 0, "ROUNDING_COMPATIBLE": 0, "CONFLICTING": 0,
                 "NOT_COMPARABLE": 0, "UNKNOWN": 0}
    n_symbolic: dict = {}
    for a in atoms:
        if a["projection_mode"] == "MEASUREMENT_BOUND":
            nv = build_numeric_view(a["claim"])
            a["numeric_view"] = nv
            n_numeric[nv["comparison"]] = n_numeric.get(nv["comparison"], 0) + 1
            expr = a["claim"].get("relationship_expression")
            if expr:
                sv = build_symbolic_view(expr, a["claim"].get("value_type"))
                a["symbolic_view"] = sv
                n_symbolic[sv["parse_status"]] = \
                    n_symbolic.get(sv["parse_status"], 0) + 1
        a["views"] = build_views(a)
        moved: list[dict] = []
        new_ast = _apply_condition_map(
            copy.deepcopy(a["applicability"]["ast"]), reg, moved)
        a["applicability"]["ast"] = new_ast
        if moved:
            a["claim"]["conditions_structured"] = moved
            if any(m["class"] == "EXAMPLE_MARKER" for m in moved):
                a["flags"]["example_marker_condition"] = True
        a["utility"] = build_utility(a)

    existing = {a["source_assertion_uid"] for a in atoms}
    presence, presence_reg = _presence_atoms(merged, existing)
    atoms.extend(presence)
    registry.extend(presence_reg)

    atoms.sort(key=lambda a: (a["observation"]["logical_package_key"],
                              a["observation"]["record_id"],
                              a["observation"]["measurement_id"] or "",
                              a["slot"].get("k", "")))
    registry.sort(key=lambda r: r["source_assertion_uid"])
    write_jsonl(staging / "02_atomic_claims.jsonl", atoms)
    write_jsonl(staging / "02a_source_assertion_revision_registry.jsonl", registry)

    stats = {
        "atomics_total": len(atoms),
        "presence_atoms": len(presence),
        "numeric_comparison": n_numeric,
        "symbolic_statuses": n_symbolic,
        "condition_report": cond_report,
        "predicate_coverage": cond_report["coverage"],
        "llm": llm_stats.as_dict(),
    }
    if cond_report["coverage"] < 0.6:
        raise SystemExit(f"БЛОК: predicate_coverage "
                         f"{cond_report['coverage']} < 0.6 (гейт KB3)")
    return stats
