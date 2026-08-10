"""PHASE 3/3B/3B2/3C/3D (волна KB4) — семантические реестры.

Артефакты: 03_vocabulary_map.json, 03b_cited_authority_registry.json,
03b2_claim_corroboration_origins.jsonl, 03c_scope_semantics_registry.json,
03d_source_scope_overlays.jsonl.
"""
from __future__ import annotations

from pathlib import Path

from . import identity as ident
from .authority import (authority_id, bindings_for, classify_origin,
                        normalize_authorities, raw_key)
from .canonical import derived_id
from .io import read_jsonl, write_json, write_jsonl
from .llm import LLMStats
from .phase2 import evidence_locus
from .vocab import build_vocabulary, normalize_mobility

# 3C: что runtime RemLab умеет оценивать СЕЙЧАС (см. core/layout.md)
RUNTIME_CAPABILITIES = {
    "room_type_context": "EVALUABLE",          # тип комнаты известен солверу
    "zone_types_context": "EVALUABLE",         # зоны строит zones.py
    "residential_domain": "EVALUABLE",         # всегда жилая
    "jurisdiction": "EVALUABLE_STATIC",        # project_context (рынок RU)
    "mobility_context": "NOT_EVALUABLE",       # нет сигнала в рантайме
    "activity_context": "PARTIALLY_EVALUABLE", # зоны ~ активности
    "dwelling_feature": "NOT_EVALUABLE",
}

# 3D: верифицированные source-wide оверлеи (регрессия 5 спеки; гл.1)
_PROXEMIC_DIMS = ["CLEARANCE", "CIRCULATION", "REACH", "BODY_DIMENSION",
                  "RELATIVE_FURNITURE_DISTANCE", "VIEWING_DISTANCE",
                  "ACTIVITY_ZONE"]


def _overlay_rows(atoms: list[dict]) -> list[dict]:
    """Строит 3 верифицированных оверлея с якорями из записей R014/R075/R076
    (гл.1) + кандидаты по fingerprint-паттернам (не верифицируются автоматом)."""
    by_rec = {}
    for a in atoms:
        key = (a["observation"]["logical_package_key"],
               a["observation"]["record_id"])
        by_rec.setdefault(key, a)

    def rec_anchor(rid: str):
        for (lpk, r), a in by_rec.items():
            if r == rid and "::ch01::" in lpk:
                return a
        return None

    rows = []
    spec = [
        ("R014", "APPLICABILITY_QUALIFIER",
         {"qualifier": "jurisdiction", "value": "us_north_america"},
         {"field": "dimension_type", "in": _PROXEMIC_DIMS},
         "Whole-source North-American нормы: только clearance/ergonomic/"
         "proxemic классы (не вся книга)"),
        ("R075", "INTERPRETATION_CONVENTION", None,
         {"field": "*", "in": None},
         "Юнит-конвенция книги (imperial primary + SI) — parsing/interpretation,"
         " НЕ applicability-ограничение"),
        ("R076", "APPLICABILITY_QUALIFIER",
         {"qualifier": "market_basis", "value": "us_north_america_market"},
         {"field": "dimension_type", "in": ["FURNITURE_DIMENSION"]},
         "NA-рынок мебели/техники: только size-claims мебели и приборов"),
    ]
    for rid, effect, qualifier, selector, note in spec:
        a = rec_anchor(rid)
        if a is None:
            raise SystemExit(f"БЛОК: не найден оверлей-источник {rid}")
        rows.append({
            "overlay_id": derived_id("OVL", {
                "doc": ident.SOURCE_DOCUMENT_ID, "record_slot": rid,
                "effect": effect, "selector": selector}),
            "source_document_id": ident.SOURCE_DOCUMENT_ID,
            "source_record_id": rid,
            "anchor_locus_uid": a["anchor"]["locus_uid"],
            "evidence_locus_uids": a["bindings"]["evidence_locus_uids"],
            "kind": "SOURCE_WIDE_SCOPE" if effect != "INTERPRETATION_CONVENTION"
                    else "SOURCE_WIDE_CONVENTION",
            "effect": effect,
            "qualifier_predicate": qualifier,
            "target_selector_ast": selector,
            "extent": "SOURCE_DOCUMENT",
            "status": "VERIFIED",
            "verification_basis": "spec mandatory regression 5 + source evidence",
            "notes": note,
        })
    # кандидаты (не верифицируем автоматически)
    for (lpk, rid), a in sorted(by_rec.items()):
        fp = (a["parent_record"].get("context_fingerprint") or "")
        if (fp.startswith(("SCOPE__", "SOURCE_CONVENTION__"))
                and rid not in ("R014", "R075", "R076")):
            rows.append({
                "overlay_id": derived_id("OVL", {
                    "doc": ident.SOURCE_DOCUMENT_ID, "record_slot": rid,
                    "effect": "CANDIDATE", "selector": {"fp": fp}}),
                "source_document_id": ident.SOURCE_DOCUMENT_ID,
                "source_record_id": rid,
                "anchor_locus_uid": a["anchor"]["locus_uid"],
                "evidence_locus_uids": a["bindings"]["evidence_locus_uids"],
                "kind": "SOURCE_WIDE_SCOPE",
                "effect": "RETRIEVAL_CONTEXT_ONLY",
                "qualifier_predicate": None,
                "target_selector_ast": None,
                "extent": "SOURCE_DOCUMENT",
                "status": "CANDIDATE_UNVERIFIED",
                "verification_basis": f"fingerprint {fp}",
                "notes": "кандидат: требует human/verify перед активацией",
            })
    return rows


def _atom_dim(atom: dict) -> str | None:
    return (atom["claim"].get("dimension_type")
            or atom["parent_record"].get("dimension_type"))


def overlay_matches(overlay: dict, atom: dict) -> bool:
    """Селектор оверлея по атому (safe, без eval). Матчатся только VERIFIED
    APPLICABILITY_QUALIFIER; конвенции интерпретации — никогда."""
    sel = overlay.get("target_selector_ast")
    if not sel or overlay["status"] != "VERIFIED" \
            or overlay["effect"] != "APPLICABILITY_QUALIFIER":
        return False
    if sel["field"] == "*":
        return True
    if sel["field"] == "dimension_type":
        return _atom_dim(atom) in set(sel["in"] or [])
    return False


def run_phase4(staging: Path) -> dict:
    atoms = read_jsonl(staging / "02_atomic_claims.jsonl")
    stats = LLMStats()

    # --- 03: словарь сущностей (subject/reference измерений + entities записей) ---
    core_types: set[str] = set()
    proposed: set[str] = set()

    def _collect(ent: dict | None) -> None:
        ent = ent or {}
        if ent.get("entity_type"):
            core_types.add(ent["entity_type"])
        if ent.get("proposed_entity_type"):
            proposed.add(ent["proposed_entity_type"])

    for a in atoms:
        _collect(a["claim"].get("subject"))
        _collect(a["claim"].get("reference"))
        for ent in a["claim"].get("entities") or []:
            _collect(ent)
    vocab, vocab_report = build_vocabulary(sorted(core_types), sorted(proposed),
                                           stats)

    concepts = [{"concept_id": f"CORE_ENTITY_{t}", "kind": "entity",
                 "label": t, "status": "CORE"} for t in sorted(core_types)]
    for label, cid in sorted(vocab["new_concept_ids"].items()):
        concepts.append({"concept_id": cid, "kind": "entity", "label": label,
                         "status": "PROVISIONAL_NEW"})
    write_json(staging / "03_vocabulary_map.json", {
        "artifact": "03_vocabulary_map",
        "vocabulary_version_source": ident.EXPECTED_VOCABULARY_VERSION,
        "concepts": concepts,
        "proposed_mappings": vocab["proposed"],
        "qualifier_normalization": {"mobility_context_rule":
                                    "wheelchair* -> wheelchair_user"},
        "report": vocab_report,
    })

    # --- 3B: авторитеты ---
    pairs = []
    for a in atoms:
        p = a["parent_record"]
        if (p.get("cited_authority_name") or "").strip():
            pairs.append((p["cited_authority_name"],
                          p.get("cited_authority_year_or_edition") or ""))
    reg, auth_report = normalize_authorities(sorted(set(pairs)), stats)

    authorities: dict[str, dict] = {}
    all_bindings: list[dict] = []
    for a in atoms:
        for b in bindings_for(a, reg):
            all_bindings.append(b)
    for key in sorted(reg):
        for c in reg[key]["components"]:
            aid = authority_id(c["canonical"], c.get("edition", ""))
            entry = authorities.setdefault(aid, {
                "authority_id": aid, "canonical_name": c["canonical"],
                "kind": c.get("kind", "UNKNOWN"),
                "edition": c.get("edition", "") or None,
                "unresolved_identity": bool(c.get("unresolved")),
                "raw_variants": [], "binding_count": 0})
            entry["raw_variants"].append(key)
    for b in all_bindings:
        if b["authority_id"] in authorities:
            authorities[b["authority_id"]]["binding_count"] += 1
    write_json(staging / "03b_cited_authority_registry.json", {
        "artifact": "03b_cited_authority_registry",
        "authorities": [authorities[k] for k in sorted(authorities)],
        "atomic_bindings": sorted(
            all_bindings, key=lambda b: (b["atomic_claim_id"],
                                         b["authority_id"])),
        "report": auth_report,
    })

    # --- 3B2: origins ---
    origins = []
    for a in atoms:
        o = classify_origin(a, reg)
        origins.append({"atomic_claim_id": a["atomic_claim_id"],
                        "source_assertion_uid": a["source_assertion_uid"], **o})
    origins.sort(key=lambda r: r["atomic_claim_id"])
    write_jsonl(staging / "03b2_claim_corroboration_origins.jsonl", origins)

    # --- 3C: scope-реестр ---
    rooms = sorted({b.get("room_type") for a in atoms
                    for b in a["applicability"]["branches"]
                    if b.get("room_type")})
    zones = sorted({z for a in atoms for b in a["applicability"]["branches"]
                    for z in (b.get("zone_types") or []) if z})
    write_json(staging / "03c_scope_semantics_registry.json", {
        "artifact": "03c_scope_semantics_registry",
        "room_concepts": rooms,
        "zone_concepts": zones,
        "scope_qualifiers": ["jurisdiction", "mobility_context",
                             "activity_context", "dwelling_feature",
                             "market_basis", "residential_domain"],
        "runtime_capabilities": RUNTIME_CAPABILITIES,
        "applicability_subsumption_edges": [],  # только APPROVED; пока пусто
        "notes": "universal_residential — domain-маркер, не литеральная комната "
                 "(C18); наследование только по APPROVED-рёбрам (C19)",
    })

    # --- 3D: оверлеи ---
    overlays = _overlay_rows(atoms)
    write_jsonl(staging / "03d_source_scope_overlays.jsonl", overlays)

    n_ext = sum(1 for o in origins
                if o["origin_kind"] == "CITED_EXTERNAL_ASSERTION")
    return {
        "vocab": vocab_report,
        "authorities": {"identities": len(authorities),
                        "bindings": len(all_bindings), **auth_report},
        "origins": {"total": len(origins), "external": n_ext,
                    "analyzed": len(origins) - n_ext,
                    "unresolved": sum(1 for o in origins if o["unresolved"])},
        "overlays": {"verified": sum(1 for o in overlays
                                     if o["status"] == "VERIFIED"),
                     "candidates": sum(1 for o in overlays
                                       if o["status"] != "VERIFIED")},
        "llm": stats.as_dict(),
    }
