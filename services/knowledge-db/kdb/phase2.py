"""PHASE 2/2A — атомарная проекция + стабильные assertion/atomic ID.

Выход: 02_atomic_claims.jsonl (ПРЕДВАРИТЕЛЬНЫЙ — поля 2B-2E дописывает KB3
пере-эмиссией с теми же ID), 02a_source_assertion_revision_registry.jsonl.

Режимы проекции (детерминированные, без LLM — обоснование в плане):
- MEASUREMENT_BOUND: 1 атом = 1 measurement; привязки строго по
  measurement.context_ids/evidence_ids (инвариант B9), measurement-локальные
  поля правят (B10), родительские качества — parent metadata (B11).
- RECORD_SEMANTIC: 1 атом = 1 record БЕЗ measurements; привязки = все
  контексты/evidence записи (запись и есть пропозиция).
Presence/cardinality-атомы для записей С измерениями добавляет фаза 2D (KB3).

Identity (2A):
- SELOC: DERIVED_ID("SELOC", {doc, master_page, section, figure, table,
  row, col, fig_dim, anchor_norm, kind}) — без package-локальных ID;
- slot: source-faithful, pre-vocabulary; без численного ответа;
- SASSERT: DERIVED_ID("SASSERT", {doc, anchor_locus, slot});
- ATOM: DERIVED_ID("ATOM", {source_assertion_uid});
- ATOMV: версия (значения/условия/сила + observation) — меняется при
  правке экстракции, ATOM — нет.
Коллизия (два измерения -> один SASSERT) = два разных claim на одном
локусе с одинаковым слотом: дискриминатор-ординал по (value, range) +
флаг REVIEW_SLOT_COLLISION (регрессия 7 спеки: «distinct claims on same
page => distinct slots»; ординал зависит от значения — потому REVIEW).
"""
from __future__ import annotations

import json
from pathlib import Path

from . import identity as ident
from .canonical import derived_id
from .io import load_json_strict, write_jsonl

OPTIONAL_QUALIFIERS = ["population", "sex", "age_group", "percentile", "posture",
                       "mobility_context", "clothing_or_equipment"]
MEAS_STATE_QUALIFIERS = ["person_state", "object_state", "population", "percentile"]


def _norm_anchor(s: str | None) -> str | None:
    if not s:
        return None
    return " ".join(str(s).split()).lower()[:160]


def _entity_sig(e: dict | None) -> dict:
    e = e or {}
    return {
        "family": e.get("entity_family"),
        "type": e.get("entity_type"),
        "proposed": e.get("proposed_entity_type"),
        "label": _norm_anchor(e.get("source_label")),
    }


def evidence_locus(doc_id: str, ev: dict) -> tuple[str, str, dict]:
    """-> (locus_uid, quality, payload-для-аудита)."""
    master = ev.get("source_page_master_file")
    payload = {
        "doc": doc_id,
        "master_page": master,
        "printed_page_fallback": None if master is not None
        else ev.get("source_page_printed"),
        "section": ev.get("source_section"),
        "figure": ev.get("source_figure"),
        "table": ev.get("source_table"),
        "row": ev.get("table_row_label"),
        "col": ev.get("table_column_label"),
        "fig_dim": ev.get("figure_dimension_label"),
        "anchor": _norm_anchor(ev.get("source_anchor")),
        "kind": ev.get("evidence_type"),
    }
    if master is not None and (payload["anchor"] or payload["figure"] or payload["table"]):
        quality = "HIGH"
    elif master is not None:
        quality = "MEDIUM"
    else:
        quality = "LOW"
    return derived_id("SELOC", payload), quality, payload


def _anchor_rank(ev: dict) -> tuple:
    """Приоритет якоря (спека 2A): table cell > figure dim > anchored text > прочее."""
    if ev.get("source_table") and (ev.get("table_row_label") or ev.get("table_column_label")):
        r = 0
    elif ev.get("figure_dimension_label"):
        r = 1
    elif ev.get("source_anchor"):
        r = 2
    else:
        r = 3
    return (r,)


def _pick_anchor(doc_id: str, evs: list[dict]) -> tuple[str, str, dict, dict]:
    """Детерминированный выбор anchor-локуса; tie -> лексикографически меньший UID."""
    scored = []
    for ev in evs:
        uid, quality, payload = evidence_locus(doc_id, ev)
        scored.append((_anchor_rank(ev), uid, quality, payload, ev))
    scored.sort(key=lambda t: (t[0], t[1]))
    _, uid, quality, payload, ev = scored[0]
    return uid, quality, payload, ev


def _slot_measurement(m: dict) -> dict:
    return {
        "k": "M",
        "subject": _entity_sig(m.get("subject")),
        "reference": _entity_sig(m.get("reference")),
        "metric": m.get("metric"),
        "quantity_kind": m.get("quantity_kind"),
        "value_type": m.get("value_type"),
        "comparison_operator": m.get("comparison_operator"),
        "measured_from": m.get("measured_from") or None,
        "measured_to": m.get("measured_to") or None,
        "condition": _norm_anchor(m.get("condition")) or None,
        "states": {q: m.get(q) for q in MEAS_STATE_QUALIFIERS
                   if m.get(q) not in (None, "", "unknown")},
    }


def _slot_record(r: dict) -> dict:
    return {
        "k": "R",
        "context_fingerprint": r.get("context_fingerprint"),
        "relation_type": r.get("relation_type"),
        "source_relation_label": r.get("source_relation_label"),
        "dimension_type": r.get("dimension_type"),
        "condition": _norm_anchor(r.get("condition")) or None,
        "subjects": sorted((json.dumps(_entity_sig(e), sort_keys=True,
                                       ensure_ascii=False)
                            for e in r.get("entities", [])))[:8],
    }


def _qualifier_view(src: dict, keys: list[str]) -> dict:
    out = {}
    for q in keys:
        v = src.get(q)
        if v in (None, "", "unknown"):
            out[q] = {"status": "UNSPECIFIED_BY_SOURCE"}
        else:
            out[q] = {"status": "SPECIFIED", "value": v}
    return out


def _branch_ast(ctx: dict, extra_opaque: str | None) -> dict:
    """AND-ветка одного контекста (C14: внутри ветки AND)."""
    preds: list[dict] = []
    room = ctx.get("room_type")
    if room == "universal_residential":
        preds.append({"op": "PREDICATE", "field": "residential_domain",
                      "test": "TRUE_FOR_DWELLING"})
    elif room in (None, "", "unknown"):
        preds.append({"op": "UNKNOWN", "reason": "UNRESOLVED_SELECTOR:room_type"})
    else:
        preds.append({"op": "PREDICATE", "field": "room_type", "eq": room})
    zones = [z for z in (ctx.get("zone_types") or []) if z and z != "unknown"]
    unknown_zones = [z for z in (ctx.get("zone_types") or []) if z == "unknown"]
    if zones:
        preds.append({"op": "PREDICATE", "field": "zone_types",
                      "overlaps": sorted(zones)})
    elif unknown_zones:
        preds.append({"op": "UNKNOWN", "reason": "UNRESOLVED_SELECTOR:zone_types"})
    cond = (ctx.get("condition") or "").strip()
    if cond:
        preds.append({"op": "UNKNOWN",
                      "reason": "OPAQUE_CONDITION_PENDING_NORMALIZATION",
                      "condition_raw": cond})
    if extra_opaque:
        preds.append({"op": "UNKNOWN",
                      "reason": "OPAQUE_MEASUREMENT_CONDITION",
                      "condition_raw": extra_opaque})
    if not preds:
        return {"op": "TRUE"}
    if len(preds) == 1:
        return preds[0]
    return {"op": "AND", "children": preds}


def _applicability(contexts: list[dict], meas_condition: str | None) -> dict:
    branches = [_branch_ast(c, meas_condition) for c in contexts]
    if not branches:
        ast: dict = {"op": "TRUE"}
    elif len(branches) == 1:
        ast = branches[0]
    else:
        ast = {"op": "OR", "children": branches}  # C14: контексты = OR-ветки
    return {
        "ast": ast,
        "branches": [{
            "context_id": c.get("context_id"),
            "room_type": c.get("room_type"),
            "zone_types": c.get("zone_types"),
            "condition_raw": c.get("condition") or None,
            "assignment_basis": c.get("assignment_basis"),
            "needs_verification": c.get("needs_verification", False),
        } for c in contexts],
    }


def _parent_meta(r: dict) -> dict:
    return {
        "knowledge_type": r.get("knowledge_type"),
        "dimension_type": r.get("dimension_type"),
        "relation_type": r.get("relation_type"),
        "source_relation_label": r.get("source_relation_label"),
        "record_source_claim_strength": r.get("source_claim_strength"),
        "remlab_candidate_use": r.get("remlab_candidate_use"),
        "source_authority": r.get("source_authority"),
        "cited_authority_name": r.get("cited_authority_name"),
        "cited_authority_year_or_edition": r.get("cited_authority_year_or_edition"),
        "cited_authority_locator": r.get("cited_authority_locator"),
        "context_fingerprint": r.get("context_fingerprint"),
        "record_qualifiers": _qualifier_view(r, OPTIONAL_QUALIFIERS),
        "local_duplicate_of": r.get("local_duplicate_of"),
        "local_conflicts_with": r.get("local_conflicts_with") or [],
        "record_needs_verification": r.get("needs_verification", False),
        "verification_reason": r.get("verification_reason") or None,
        "concept": r.get("concept"),
        "rule_plain_language": r.get("rule_plain_language"),
        "notes": r.get("notes") or None,
    }


def _measurement_claim(m: dict) -> dict:
    keep = ["metric", "quantity_kind", "value_type", "source_claim_strength",
            "comparison_operator", "value_original", "range_original",
            "unit_original", "normalized_value", "normalized_range",
            "canonical_unit", "relationship_expression", "conversion_note",
            "condition", "person_state", "object_state", "population",
            "percentile", "confidence", "needs_verification", "notes",
            "measured_from", "measured_to"]
    out = {k: m.get(k) for k in keep}
    out["subject"] = m.get("subject")
    out["reference"] = m.get("reference")
    return out


def build_atomics(merged: dict) -> tuple[list[dict], list[dict], dict]:
    doc_id = ident.SOURCE_DOCUMENT_ID
    atomics: list[dict] = []
    by_assertion: dict[str, list[dict]] = {}

    for pkg in merged["packages"]:
        if not pkg["active_for_semantic_projection"]:
            continue
        pcu = pkg["package_content_uid"]
        lpk = pkg["logical_package_key"]
        for r in pkg["raw"].get("records", []):
            rid = r["record_id"]
            ev_by_id = {e["evidence_id"]: e for e in r.get("evidence", [])}
            ctx_by_id = {c["context_id"]: c for c in r.get("applicability_contexts", [])}
            measurements = r.get("measurements", [])
            if measurements:
                for m in measurements:
                    evs = [ev_by_id[eid] for eid in m.get("evidence_ids", [])]
                    ctxs = [ctx_by_id[cid] for cid in m.get("context_ids", [])]
                    anchor_uid, q, anchor_payload, _ = _pick_anchor(doc_id, evs)
                    slot = _slot_measurement(m)
                    strength = m.get("source_claim_strength")
                    strength_origin = "MEASUREMENT"
                    if strength in (None, "", "unknown", "UNKNOWN"):
                        strength = r.get("source_claim_strength")
                        strength_origin = "RECORD"
                    atom = {
                        "projection_mode": "MEASUREMENT_BOUND",
                        "observation": {"package_content_uid": pcu,
                                        "logical_package_key": lpk,
                                        "record_id": rid,
                                        "measurement_id": m["measurement_id"]},
                        "anchor": {"locus_uid": anchor_uid,
                                   "locus_identity_quality": q,
                                   **{k: anchor_payload[k] for k in
                                      ("master_page", "section", "figure",
                                       "table", "row", "col", "anchor")}},
                        "slot": slot,
                        "bindings": {
                            "context_ids": m.get("context_ids", []),
                            "evidence_ids": m.get("evidence_ids", []),
                            "evidence_locus_uids": sorted(
                                evidence_locus(doc_id, e)[0] for e in evs),
                        },
                        "applicability": _applicability(
                            ctxs, _norm_anchor(m.get("condition"))),
                        "qualifiers": _qualifier_view(
                            m, MEAS_STATE_QUALIFIERS + ["sex", "age_group"]),
                        "claim": _measurement_claim(m),
                        "strength": {"effective": strength,
                                     "origin": strength_origin,
                                     "parent_record_strength":
                                         r.get("source_claim_strength")},
                        "parent_record": _parent_meta(r),
                        "flags": {
                            "needs_verification": bool(
                                m.get("needs_verification")
                                or r.get("needs_verification")),
                            "has_relationship_expression":
                                bool(m.get("relationship_expression")),
                            "review": [],
                        },
                    }
                    key = json.dumps(slot, sort_keys=True, ensure_ascii=False)
                    by_assertion.setdefault(anchor_uid + "\x00" + key, []).append(atom)
            else:
                evs = list(r.get("evidence", []))
                ctxs = list(r.get("applicability_contexts", []))
                anchor_uid, q, anchor_payload, _ = _pick_anchor(doc_id, evs)
                slot = _slot_record(r)
                atom = {
                    "projection_mode": "RECORD_SEMANTIC",
                    "observation": {"package_content_uid": pcu,
                                    "logical_package_key": lpk,
                                    "record_id": rid,
                                    "measurement_id": None},
                    "anchor": {"locus_uid": anchor_uid,
                               "locus_identity_quality": q,
                               **{k: anchor_payload[k] for k in
                                  ("master_page", "section", "figure",
                                   "table", "row", "col", "anchor")}},
                    "slot": slot,
                    "bindings": {
                        "context_ids": [c["context_id"] for c in ctxs],
                        "evidence_ids": [e["evidence_id"] for e in evs],
                        "evidence_locus_uids": sorted(
                            evidence_locus(doc_id, e)[0] for e in evs),
                    },
                    "applicability": _applicability(ctxs, None),
                    "qualifiers": _qualifier_view(r, OPTIONAL_QUALIFIERS),
                    "claim": {
                        "concept": r.get("concept"),
                        "rule_plain_language": r.get("rule_plain_language"),
                        "relation_type": r.get("relation_type"),
                        "source_relation_label": r.get("source_relation_label"),
                        "dimension_type": r.get("dimension_type"),
                        "condition": r.get("condition") or None,
                        "entities": r.get("entities") or [],
                    },
                    "strength": {"effective": r.get("source_claim_strength"),
                                 "origin": "RECORD",
                                 "parent_record_strength":
                                     r.get("source_claim_strength")},
                    "parent_record": _parent_meta(r),
                    "flags": {"needs_verification": bool(r.get("needs_verification")),
                              "has_relationship_expression": False,
                              "review": []},
                }
                key = json.dumps(slot, sort_keys=True, ensure_ascii=False)
                by_assertion.setdefault(anchor_uid + "\x00" + key, []).append(atom)

    # 2A: mint стабильных ID; коллизии -> ординал + REVIEW
    registry: list[dict] = []
    n_collisions = 0
    for group_key, group in by_assertion.items():
        anchor_uid = group[0]["anchor"]["locus_uid"]
        slot = group[0]["slot"]
        if len(group) > 1:
            n_collisions += 1
            group.sort(key=lambda a: json.dumps(
                [a["claim"].get("value_original"),
                 a["claim"].get("range_original"),
                 a["observation"]["record_id"]],
                ensure_ascii=False, sort_keys=True))
        for i, atom in enumerate(group):
            slot_payload = {"slot": slot}
            if len(group) > 1:
                slot_payload["collision_ordinal"] = i
                atom["flags"]["review"].append("REVIEW_SLOT_COLLISION")
            sassert = derived_id("SASSERT", {
                "doc": ident.SOURCE_DOCUMENT_ID,
                "anchor_locus": anchor_uid,
                **slot_payload})
            atom_id = derived_id("ATOM", {"source_assertion_uid": sassert})
            version_uid = derived_id("ATOMV", {
                "atomic_claim_id": atom_id,
                "values": {k: atom["claim"].get(k) for k in
                           ("value_original", "range_original", "unit_original",
                            "normalized_value", "normalized_range",
                            "canonical_unit", "relationship_expression",
                            "condition")},
                "strength": atom["strength"]["effective"],
                "observation": atom["observation"],
            })
            atom["source_assertion_uid"] = sassert
            atom["atomic_claim_id"] = atom_id
            atom["atomic_claim_version_uid"] = version_uid
            atom["source_document_id"] = ident.SOURCE_DOCUMENT_ID
            atom["source_work_id"] = ident.SOURCE_WORK_ID
            atom["source_independence_group_id"] = ident.SOURCE_INDEPENDENCE_GROUP_ID
            atomics.append(atom)
            registry.append({
                "source_assertion_uid": sassert,
                "atomic_claim_id": atom_id,
                "assertion_anchor_locus_uid": anchor_uid,
                "locus_identity_quality": atom["anchor"]["locus_identity_quality"],
                "revision_status": "SINGLE",
                "slot_collision": len(group) > 1,
                "observations": [atom["observation"]],
                "observation_count": 1,
                "evidence_locus_count": len(atom["bindings"]["evidence_locus_uids"]),
                "support_document_count": 1,
            })

    stats = {
        "atomics_total": len(atomics),
        "measurement_bound": sum(1 for a in atomics
                                 if a["projection_mode"] == "MEASUREMENT_BOUND"),
        "record_semantic": sum(1 for a in atomics
                               if a["projection_mode"] == "RECORD_SEMANTIC"),
        "slot_collision_groups": n_collisions,
        "collision_rate": round(n_collisions / max(len(by_assertion), 1), 4),
    }
    return atomics, registry, stats


def run_phase2(staging: Path) -> dict:
    merged = load_json_strict(staging / "01_raw_merged.json")
    atomics, registry, stats = build_atomics(merged)

    # гейты
    seen_meas = set()
    for a in atomics:
        o = a["observation"]
        if o["measurement_id"]:
            k = (o["package_content_uid"], o["record_id"], o["measurement_id"])
            if k in seen_meas:
                raise SystemExit(f"БЛОК: measurement в двух атомах: {k}")
            seen_meas.add(k)
    if len(seen_meas) != merged["corpus_totals"]["measurements"]:
        raise SystemExit(f"БЛОК: measurement-атомов {len(seen_meas)} != "
                         f"{merged['corpus_totals']['measurements']}")
    ids = [a["atomic_claim_id"] for a in atomics]
    if len(ids) != len(set(ids)):
        raise SystemExit("БЛОК: неуникальные atomic_claim_id")

    atomics.sort(key=lambda a: (a["observation"]["logical_package_key"],
                                a["observation"]["record_id"],
                                a["observation"]["measurement_id"] or ""))
    registry.sort(key=lambda r: r["source_assertion_uid"])
    write_jsonl(staging / "02_atomic_claims.jsonl", atomics)
    write_jsonl(staging / "02a_source_assertion_revision_registry.jsonl", registry)
    return stats
