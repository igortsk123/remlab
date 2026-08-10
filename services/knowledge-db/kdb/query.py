"""PLANE A/B/C — запросные планы поверх артефактов KB (PHASE 8).

PLANE A (completeness-first): полный structured-скан applicability-индекса,
бакеты не удаляются релевантностью; PLANE B (relevance-first): BM25 + точные
алиасы + структурные бусты (open-world фильтры); PLANE C: bounded Judge-бандл
из backbone + guidance + обязательного closure (конфликт всегда обеими
сторонами; геометрию из прозы не выводим — вход только snapshot-контекст).
"""
from __future__ import annotations

from pathlib import Path

from .io import read_jsonl
from .pairing import BM25, tokenize
from .phase6 import eval_ast


class KBQuery:
    def __init__(self, staging: Path):
        self.staging = staging
        self.retr = read_jsonl(staging / "07_retrieval_records.jsonl")
        self.idx = read_jsonl(staging / "07b_applicability_index.jsonl")
        self.closure = {r["canonical_claim_id"]: r for r in
                        read_jsonl(staging / "07c_context_closure_index.jsonl")}
        self.canon = {c["canonical_claim_id"]: c for c in
                      read_jsonl(staging / "06_canonical_knowledge.jsonl")}
        self.retr_by_canon = {r["canonical_claim_id"]: r for r in self.retr}
        self._bm25 = None

    # ---------------- PLANE A ----------------
    def plane_a(self, ctx: dict) -> dict:
        buckets = {k: [] for k in (
            "definite_matches", "evaluable_definite_matches",
            "contextual_matches", "cross_scope_source_references",
            "applicable_but_not_evaluable", "possible_unknowns")}
        for row in self.idx:
            res = [eval_ast(ast, ctx) for ast in row["applicability_ast_members"]]
            cid = row["canonical_claim_id"]
            svs = self.canon[cid]["scoped_variant_signature"]
            inh = svs.get("inherited_overlay_qualifiers") or []
            # 3D: наследованные оверлей-квалификаторы (US-нормы и т.п.) —
            # explicit compatibility: MISMATCH -> cross-scope, не definite
            overlay_state = "UNRESTRICTED"
            for qv in inh:
                fld, val = qv.split("=", 1)
                have = ctx.get(fld)
                if have is None:
                    overlay_state = "UNKNOWN"
                elif str(have) != val:
                    overlay_state = "MISMATCH"
                    break
            if "MATCH" in res and overlay_state == "MISMATCH":
                buckets["cross_scope_source_references"].append(cid)
                continue
            if "MATCH" in res:
                if overlay_state == "UNKNOWN":
                    buckets["contextual_matches"].append(cid)
                buckets["definite_matches"].append(cid)
                if row["runtime_evaluability"] == "EVALUABLE" \
                        and overlay_state != "UNKNOWN":
                    buckets["evaluable_definite_matches"].append(cid)
                else:
                    buckets["applicable_but_not_evaluable"].append(cid)
            elif "UNKNOWN" in res:
                buckets["possible_unknowns"].append(cid)
            else:
                if inh and any(q.startswith(("jurisdiction=", "market_basis="))
                               for q in inh):
                    buckets["cross_scope_source_references"].append(cid)
        # routing views по utility (не удаляют, а группируют)
        def _by_class(cls: str) -> list[str]:
            return [cid for cid in buckets["definite_matches"]
                    if cls in self.canon[cid]["utility_classes_union"]]
        views = {
            "source_constraint_guidance_matches":
                _by_class("SOURCE_CONSTRAINT_GUIDANCE"),
            "source_semantic_guidance_candidates":
                _by_class("SEMANTIC_DESIGN_GUIDANCE"),
            "source_supplemental_references": sorted(
                set(_by_class("EXAMPLE_REFERENCE"))
                | set(_by_class("HISTORICAL_CONTEXT"))
                | set(_by_class("MODELING_REFERENCE"))),
        }
        return {"context": ctx, "buckets": buckets, "routing_views": views,
                "counts": {k: len(v) for k, v in buckets.items()}}

    # ---------------- PLANE B ----------------
    def _ensure_bm25(self):
        if self._bm25 is None:
            docs = [tokenize((r["retrieval_text"] or "") + " " +
                             (r["ru_alias"] or "")) for r in self.retr]
            self._bm25 = BM25(docs)

    def plane_b(self, query: str, top_k: int = 15,
                filters: dict | None = None) -> list[dict]:
        self._ensure_bm25()
        q = tokenize(query)
        scores: dict[int, float] = {}
        import math
        for t in set(q):
            df = self._bm25.df.get(t, 0)
            if not df:
                continue
            idf = math.log(1 + (self._bm25.N - df + 0.5) / (df + 0.5))
            for j, tf in self._bm25.postings[t]:
                scores[j] = scores.get(j, 0.0) + idf * tf
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        out = []
        for j, s in ranked:
            r = self.retr[j]
            if filters:  # open-world: absent metadata НЕ отсекает (C15)
                ok = True
                for k, v in filters.items():
                    have = r["filters"].get(k)
                    if have and v not in have:
                        ok = False
                if not ok:
                    continue
            out.append({"canonical_claim_id": r["canonical_claim_id"],
                        "score": round(s, 3),
                        "text": r["retrieval_text"][:160],
                        "ru": (r["ru_alias"] or "")[:120]})
            if len(out) >= top_k:
                break
        return out

    # ---------------- PLANE C ----------------
    def plane_c(self, layout_fact_snapshot: dict,
                goals_query: str | None = None,
                budget_items: int = 60) -> dict:
        a = self.plane_a(layout_fact_snapshot)
        backbone = [cid for cid in a["routing_views"]
                    ["source_constraint_guidance_matches"]
                    if self.canon[cid]["judge_backbone_member_ids"]]
        guidance = a["routing_views"]["source_semantic_guidance_candidates"]
        if goals_query:
            hits = {h["canonical_claim_id"] for h in
                    self.plane_b(goals_query, top_k=20)}
            guidance = [c for c in guidance if c in hits] + \
                       [c for c in guidance if c not in hits]
        bundle, seen = [], set()

        def add(cid, prio, why):
            if cid in seen:
                return
            seen.add(cid)
            bundle.append({"canonical_claim_id": cid, "priority": prio,
                           "why": why,
                           "strengths": self.canon[cid]["strengths"],
                           "has_conflicts": bool(
                               self.canon[cid]["conflict_group_ids"])})

        for cid in backbone[:budget_items]:
            add(cid, "P1_SOURCE_BACKBONE", "in-scope constraint guidance")
            # обязательный closure: конфликт всегда обеими сторонами (7C)
            for other in self.closure[cid]["mandatory_closure_ids"]:
                add(other, "P1_CLOSURE", "conflict/dependency counterpart")
        for cid in a["buckets"]["applicable_but_not_evaluable"][:20]:
            add(cid, "P2_NOT_EVALUABLE", "applicable, нет runtime-сигнала")
        for cid in guidance[:15]:
            add(cid, "P2_SEMANTIC_GUIDANCE", "semantic design guidance")
        for cid in a["buckets"]["cross_scope_source_references"][:10]:
            add(cid, "P3_CROSS_SCOPE", "другой рынок/юрисдикция — справочно")
        return {"layout_fact_snapshot": layout_fact_snapshot,
                "bundle": bundle,
                "counts": {"backbone": len(backbone),
                           "bundle": len(bundle)},
                "note": "production PASS/FAIL остаётся за validator_snapshot; "
                        "бандл — знание источника, не политика"}
