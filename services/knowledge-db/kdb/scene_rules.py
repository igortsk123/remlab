"""Применимые правила базы для сцены (вход судейского конвейера W4).

Отбор: PLANE A definite-matches по контексту комнаты, только операционные
(constraint guidance) + верх semantic guidance; текст — RU-алиас (или EN) с
силой утверждения. Владелец 10.08: судье — ТОЛЬКО применимые, не все 2755.

  ~/venvs/kdb/bin/python -m kdb.scene_rules '{"room_type":"living_room",
      "zone_types":["conversation","tv_media"],"jurisdiction":"us_north_america"}'
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .query import KBQuery

SNAPSHOT = Path(__file__).resolve().parents[3] / "remlab_knowledge_db_v1" / \
    "runs" / "r20260810a"

STRENGTH_RU = {"REQUIRED_MINIMUM": "минимум по коду",
               "RECOMMENDED_MINIMUM": "рекомендуемый минимум",
               "MAXIMUM": "максимум", "PREFERRED": "предпочтительно",
               "TYPICAL_RANGE": "типовой диапазон"}


def scene_rules(ctx: dict, limit_constraint: int = 60,
                limit_semantic: int = 15) -> list[str]:
    kq = KBQuery(SNAPSHOT)
    a = kq.plane_a(ctx)
    lines: list[str] = []
    for cid in a["routing_views"]["source_constraint_guidance_matches"][:limit_constraint]:
        r = kq.retr_by_canon.get(cid)
        if not r:
            continue
        c = kq.canon[cid]
        strengths = ", ".join(STRENGTH_RU.get(s, s) for s in c["strengths"][:2])
        text = (r.get("ru_alias") or r["retrieval_text"])[:180]
        lines.append(f"- {text}" + (f" [{strengths}]" if strengths else ""))
    for cid in a["routing_views"]["source_semantic_guidance_candidates"][:limit_semantic]:
        r = kq.retr_by_canon.get(cid)
        if r:
            lines.append(f"- (принцип) {(r.get('ru_alias') or r['retrieval_text'])[:160]}")
    return lines


if __name__ == "__main__":
    ctx = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {
        "room_type": "living_room",
        "zone_types": ["conversation", "tv_media", "relaxation"],
        "jurisdiction": "us_north_america"}
    print("\n".join(scene_rules(ctx)))
