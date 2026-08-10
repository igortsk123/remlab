"""Волна KB7 (PHASE 8) — 08_retrieval_config.json + smoke трёх планов."""
from __future__ import annotations

from pathlib import Path

from . import DERIVED_SCHEMA_VERSION, PIPELINE_VERSION
from .io import write_json
from .phase5a import EMB_MODEL
from .query import KBQuery

SMOKE_CONTEXTS = [
    {"room_type": "living_room", "zone_types": ["conversation", "tv_media"]},
    {"room_type": "bedroom", "zone_types": ["sleeping", "storage"]},
    {"room_type": "kitchen", "zone_types": ["cooking", "food_preparation"]},
]


def run_phase7(staging: Path) -> dict:
    q = KBQuery(staging)
    smoke = []
    for ctx in SMOKE_CONTEXTS:
        a = q.plane_a(ctx)
        c = q.plane_c(ctx)
        smoke.append({"context": ctx, "plane_a_counts": a["counts"],
                      "plane_c_bundle": c["counts"]["bundle"]})
        if not a["buckets"]["definite_matches"]:
            raise SystemExit(f"БЛОК: PLANE A пуст для {ctx} — predicate "
                             "coverage или индекс сломаны")
    b_demo = q.plane_b("минимальная ширина прохода коридор", top_k=5)

    config = {
        "artifact": "08_retrieval_config",
        "pipeline_version": PIPELINE_VERSION,
        "derived_schema_version": DERIVED_SCHEMA_VERSION,
        "planes": {
            "A": {"goal": "CONSTRAINT_ENUMERATION/COMPLETENESS_FIRST",
                  "implementation": "kdb.query.KBQuery.plane_a",
                  "semantics": "полный structured-скан 07b; MATCH/MISMATCH/"
                               "UNKNOWN; бакеты не удаляются ранжированием",
                  "buckets": ["definite_matches", "evaluable_definite_matches",
                              "contextual_matches",
                              "cross_scope_source_references",
                              "applicable_but_not_evaluable",
                              "possible_unknowns"]},
            "B": {"goal": "DISCOVERY_QA/RELEVANCE_FIRST",
                  "implementation": "kdb.query.KBQuery.plane_b",
                  "channels": ["bm25(retrieval_text+ru_alias)",
                               "structured filter boosts (open-world)"],
                  "vector_channel": {"status": "available_offline",
                                     "note": "эмбеддинги используются в 3E; "
                                             "для query-времени включаются "
                                             "переиндексацией npz"}},
            "C": {"goal": "LAYOUT_JUDGE_CONTEXT",
                  "implementation": "kdb.query.KBQuery.plane_c",
                  "inputs": ["layout_fact_snapshot", "validator_snapshot",
                             "project_context", "design/user goals"],
                  "geometry_boundary": "сцену читаем ТОЛЬКО из snapshot; "
                                       "retrieval-проза геометрию не задаёт",
                  "priorities": ["P1_SOURCE_BACKBONE", "P1_CLOSURE",
                                 "P2_NOT_EVALUABLE", "P2_SEMANTIC_GUIDANCE",
                                 "P3_CROSS_SCOPE"]},
        },
        "embeddings": {
            "provider": "fastembed==0.8.0 (onnxruntime==1.28.0)",
            "model": EMB_MODEL,
            "dimensions": 384,
            "pooling_note": "mean pooling (fastembed>=0.6 поведение)",
            "text_template": "kdb.pairing.atom_text / retrieval_text",
            "language_handling": "EN текст + RU алиасы (registries/ru_aliases)",
            "storage": "npz вне git (регенерируемо)",
        },
        "tunables": {"plane_b_top_k": 15, "plane_c_budget_items": 60,
                     "note": "eval-дефолты, не семантические константы"},
        "smoke": smoke,
        "plane_b_demo_ru_query": b_demo,
    }
    write_json(staging / "08_retrieval_config.json", config)
    return {"smoke": smoke, "plane_b_demo_hits": len(b_demo)}
