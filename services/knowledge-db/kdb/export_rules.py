"""W0 (kb-rules-merge): классификация прод-параметров движка против source-KB.

Для каждого параметра occupancy.json — курируемый запрос к KB (PLANE B + фильтр
по dimension), извлечение числовых вилок из canonical-вариантов и механический
вердикт: SUPPORTED | TOO_STRICT | TOO_WEAK | CONTRADICTED | SEMANTIC_ONLY |
NO_KB_DATA | REVIEW_OWNER. Плюс MISSING-кандидаты: правила книги, которых в
движке нет. Выход — docs/kb-rules-classification.md (+ .json для тестов):
конфликтные строки решает владелец, прод не трогаем (это W0).

Запуск: ~/venvs/kdb/bin/python -m kdb.export_rules   (из services/knowledge-db)
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from .io import read_jsonl, write_json
from .query import KBQuery

REPO_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = REPO_ROOT / "remlab_knowledge_db_v1" / "runs" / "r20260810a"
OCCUPANCY = REPO_ROOT / "services" / "planner-solver" / "rules" / "occupancy.json"
OUT_MD = REPO_ROOT / "docs" / "kb-rules-classification.md"
OUT_JSON = REPO_ROOT / "docs" / "kb-rules-classification.json"

# параметр движка -> как искать в KB и как сравнивать.
# strengths_ok: какие силы KB-утверждений принимаем в сравнение.
MAPPING = [
    dict(param="sofa_coffee_table_hard", query="cocktail table sofa distance edge",
         dims={"RELATIVE_FURNITURE_DISTANCE", "CLEARANCE"}, subject_any=("sofa",),
         compare="review",
         review_note="классовое различие: книжные 30–46 — RECOMMENDED-диапазон "
                     "удобства (реализован в preferred [40,45]); hard [32,50] — "
                     "наш физический допуск. Bisect 10.08: сужение hard до 46 "
                     "валит set45/set71 и портит soft у 14 сцен — приёмка 252 "
                     "держит [32,50]"),
    dict(param="sofa_coffee_table_preferred", query="cocktail table sofa distance edge",
         dims={"RELATIVE_FURNITURE_DISTANCE", "CLEARANCE"}, subject_any=("sofa",),
         compare="inside_kb"),
    dict(param="sofa_tv_cm", query="television viewing distance screen",
         dims={"VIEWING_DISTANCE", "RELATIVE_FURNITURE_DISTANCE"},
         subject_any=("seat", "sofa"), compare="range_overlap"),
    dict(param="passage_main", query="hallway width minimum residential code",
         dims={"CIRCULATION"}, subject_any=("hallway", "circulation"),
         compare="min_within"),
    dict(param="passage_secondary_min", query="clear space circulation furniture 32",
         dims={"CIRCULATION", "CLEARANCE"}, subject_any=(), compare="review",
         review_note="книжные 81–91 см — основные пути/доступность; прямого "
                     "аналога «вторичного прохода между мебелью» книга не даёт"),
    dict(param="dining_chair_pullout", query="dining chair pullout clearance table",
         dims={"CLEARANCE", "ACTIVITY_ZONE"}, subject_any=("chair", "dining"),
         compare="range_overlap"),
    dict(param="dining_table_to_wall_no_pass",
         query="dining table wall clearance no passage",
         dims={"CLEARANCE", "CIRCULATION"}, subject_any=("dining", "table"),
         compare="min_within"),
    dict(param="dining_table_to_wall_with_pass",
         query="dining table wall clearance passage behind seated",
         dims={"CLEARANCE", "CIRCULATION"}, subject_any=("dining", "table"),
         compare="min_within"),
    dict(param="facing_seats", query="conversation distance between facing seats",
         dims={"RELATIVE_FURNITURE_DISTANCE", "BODY_DIMENSION", "ACTIVITY_ZONE"},
         subject_any=(), compare="range_overlap"),
    dict(param="conversation_circle_max_cm",
         query="face-to-face interaction circle diameter",
         dims={"ACTIVITY_ZONE"}, subject_any=("circle", "interaction", "cluster"),
         compare="max_within"),
    dict(param="fireplace_clear", query="fireplace clearance traffic front",
         dims={"CLEARANCE"}, subject_any=("fireplace", "hearth"),
         compare="review",
         review_note="найденные 41–51 см — глубина пода/выступа, не зона "
                     "трафика перед камином; прямого аналога параметра нет"),
    dict(param="legroom_front_of_seat", query="single seat zone depth upholstered",
         dims={"ACTIVITY_ZONE", "CLEARANCE"}, subject_any=("seat",),
         compare="review"),
    dict(param="wardrobe_hinged_front_min", query="closet door clearance front dressing",
         dims={"CLEARANCE", "CIRCULATION"}, subject_any=("closet", "wardrobe"),
         compare="min_within"),
    dict(param="door_to_furniture", query="door swing furniture route blank wall",
         dims=set(), subject_any=("door",), compare="semantic"),
    dict(param="rug_longer_than_sofa", query="rug size under sofa front legs",
         dims=set(), subject_any=("rug",), compare="no_kb_expected"),
    dict(param="rug_beyond_sofa_side", query="rug size beside sofa area",
         dims=set(), subject_any=("rug",), compare="no_kb_expected"),
]

# правила книги, которых в движке НЕТ -> кандидаты MISSING
MISSING_CANDIDATES = [
    dict(name="conversation_cluster_diameter_preferred",
         query="conversation cluster diameter overall",
         note="предпочтительный габарит разговорной зоны; у движка есть только "
              "верх face-to-face круга (305)"),
    dict(name="single_seat_envelope_depth",
         query="single seat zone depth upholstered",
         note="конверт одного посадочного места (сиденье+ноги)"),
    dict(name="seat_width_middle_position",
         query="seated person middle place width",
         note="ширина места в середине дивана — для честного подсчёта посадок"),
    dict(name="tv_cabinet_depth_typical",
         query="cabinet below flat-screen television depth",
         note="типовая глубина тумбы под ТВ — для подбора в композиторе"),
]

STRENGTH_RANK = {"REQUIRED_MINIMUM": 3, "RECOMMENDED_MINIMUM": 2, "MAXIMUM": 2,
                 "PREFERRED": 1, "TYPICAL_RANGE": 1}


def _kb_numbers(kq: KBQuery, atoms_by_id: dict, row: dict,
                top_k: int = 12) -> list[dict]:
    """Числовые свидетельства KB по запросу строки маппинга (см)."""
    hits = kq.plane_b(row["query"], top_k=top_k)
    out = []
    for h in hits:
        c = kq.canon[h["canonical_claim_id"]]
        m0 = atoms_by_id[c["member_ids"][0]]
        dim = (m0["parent_record"].get("dimension_type")
               or m0["claim"].get("dimension_type"))
        if row["dims"] and dim not in row["dims"]:
            continue
        subj = ((m0["claim"].get("subject") or {}).get("source_label") or "").lower()
        if row["subject_any"] and not any(t in subj or t in h["text"].lower()
                                          for t in row["subject_any"]):
            continue
        for v in c.get("value_variants", []):
            if v.get("unit") != "cm":
                continue
            strength = v.get("strength")
            if strength not in STRENGTH_RANK:
                continue
            lo = hi = None
            if v.get("value"):
                lo = hi = Decimal(v["value"])
            rng = v.get("range") or [None, None]
            if rng[0]:
                lo = Decimal(rng[0])
            if len(rng) > 1 and rng[1]:
                hi = Decimal(rng[1])
            if lo is None and hi is None:
                continue
            page = m0["anchor"].get("master_page")
            out.append({"canonical": c["canonical_claim_id"][:20],
                        "lo": float(lo) if lo is not None else None,
                        "hi": float(hi) if hi is not None else None,
                        "strength": strength,
                        "operator": v.get("operator"),
                        "page_master": page,
                        "page_printed": (page - 14) if page else None,
                        "text": h["text"][:120]})
    return out


def _current_range(val) -> tuple[float, float]:
    if isinstance(val, list):
        return float(val[0]), float(val[1])
    return float(val), float(val)


def _verdict(row: dict, cur_lo: float, cur_hi: float,
             ev: list[dict]) -> tuple[str, str]:
    mode = row["compare"]
    if mode == "no_kb_expected":
        return ("NO_KB_DATA" if not ev else "REVIEW_OWNER",
                "книга ковровых правил не даёт — прод-канон из других источников"
                if not ev else "неожиданно нашлись данные — смотреть глазами")
    if mode == "semantic":
        return ("SEMANTIC_ONLY",
                "книга даёт качественное правило (без числа) — движок реализует "
                "его геометрически")
    if not ev:
        return "NO_KB_DATA", "релевантных числовых утверждений не найдено"
    if mode == "review":
        return "REVIEW_OWNER", row.get("review_note",
                                       "метрики книги и движка различаются по смыслу")
    los = [e["lo"] for e in ev if e["lo"] is not None]
    his = [e["hi"] for e in ev if e["hi"] is not None]
    kb_lo = min(los) if los else min(his)
    kb_hi = max(his) if his else max(los)
    if mode == "inside_kb":
        if kb_lo - 1 <= cur_lo and cur_hi <= kb_hi + 1:
            return "SUPPORTED", f"текущее [{cur_lo:g},{cur_hi:g}] внутри KB [{kb_lo:g},{kb_hi:g}]"
        return "REVIEW_OWNER", f"текущее [{cur_lo:g},{cur_hi:g}] vs KB [{kb_lo:g},{kb_hi:g}]"
    if mode == "min_within":
        req = [e for e in ev if e["strength"] == "REQUIRED_MINIMUM"]
        base = min((e["lo"] or e["hi"]) for e in req) if req else kb_lo
        if cur_lo >= base - 1:
            return "SUPPORTED", f"минимум движка {cur_lo:g} ≥ книжного {base:g}"
        if cur_lo >= base * 0.8:
            return "REVIEW_OWNER", f"минимум движка {cur_lo:g} чуть ниже книжного {base:g}"
        return "TOO_WEAK", f"минимум движка {cur_lo:g} заметно ниже книжного {base:g}"
    if mode == "max_within":
        if cur_hi <= kb_hi + 1:
            return "SUPPORTED", f"потолок движка {cur_hi:g} ≤ книжного {kb_hi:g}"
        return "REVIEW_OWNER", f"потолок движка {cur_hi:g} > книжного {kb_hi:g}"
    # range_overlap
    if cur_hi < kb_lo or cur_lo > kb_hi:
        return "CONTRADICTED", f"[{cur_lo:g},{cur_hi:g}] не пересекается с KB [{kb_lo:g},{kb_hi:g}]"
    if kb_lo - 1 <= cur_lo and cur_hi <= kb_hi + 1:
        return "SUPPORTED", f"внутри книжной вилки [{kb_lo:g},{kb_hi:g}]"
    if cur_lo > kb_lo and cur_hi > kb_hi:
        return "REVIEW_OWNER", f"сдвинуто вверх от KB [{kb_lo:g},{kb_hi:g}]"
    if cur_lo < kb_lo and cur_hi < kb_hi:
        return "TOO_STRICT" if cur_hi < kb_hi else "REVIEW_OWNER", \
            f"ниже книжной вилки [{kb_lo:g},{kb_hi:g}]"
    return "SUPPORTED", f"пересекается с KB [{kb_lo:g},{kb_hi:g}] (шире)"


def main() -> int:
    kq = KBQuery(SNAPSHOT)
    atoms_by_id = {a["atomic_claim_id"]: a
                   for a in read_jsonl(SNAPSHOT / "02_atomic_claims.jsonl")}
    occ = json.load(open(OCCUPANCY))["distances_cm"]

    rows = []
    for row in MAPPING:
        cur = occ.get(row["param"])
        if cur is None:
            continue
        cur_lo, cur_hi = _current_range(cur)
        ev = _kb_numbers(kq, atoms_by_id, row)
        verdict, why = _verdict(row, cur_lo, cur_hi, ev)
        rows.append({"param": row["param"], "current": cur,
                     "verdict": verdict, "why": why,
                     "evidence": ev[:5], "query": row["query"]})

    missing = []
    for mc in MISSING_CANDIDATES:
        hits = kq.plane_b(mc["query"], top_k=3)
        ev = []
        for h in hits:
            c = kq.canon[h["canonical_claim_id"]]
            m0 = atoms_by_id[c["member_ids"][0]]
            page = m0["anchor"].get("master_page")
            vv = [v for v in c.get("value_variants", []) if v.get("unit") == "cm"
                  and (v.get("value") or any(v.get("range") or []))]
            if vv:
                ev.append({"text": h["text"][:130],
                           "page_printed": (page - 14) if page else None,
                           "values": vv[:2]})
        missing.append({"name": mc["name"], "note": mc["note"],
                        "evidence": ev[:2]})

    counts: dict = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

    lines = [
        "# Классификация прод-правил против source-KB (W0, kb-rules-merge)",
        "",
        f"Снапшот KB: `runs/r20260810a` · параметров разобрано: {len(rows)} из "
        f"{len([k for k in occ if not k.startswith('_')])} в distances_cm "
        "(остальные — вне книжной тематики или NOT_MAPPED_YET) · "
        f"итог: {counts}",
        "",
        "Правило W0: прод НЕ меняется этим документом. SUPPORTED — фиксируем "
        "пруф; REVIEW_OWNER/TOO_* / CONTRADICTED — решение владельца построчно.",
        "",
        "| Параметр | Движок | Вердикт | Почему | Пруф (печ. стр.) |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        pages = sorted({e["page_printed"] for e in r["evidence"]
                        if e.get("page_printed")})[:4]
        ev0 = r["evidence"][0]["text"] if r["evidence"] else "—"
        lines.append(f"| `{r['param']}` | {r['current']} | **{r['verdict']}** | "
                     f"{r['why']} | {', '.join(map(str, pages)) or '—'} |")
    lines += ["", "## MISSING-кандидаты (в книге есть, в движке нет)", ""]
    for m in missing:
        pg = ", ".join(str(e["page_printed"]) for e in m["evidence"]
                       if e.get("page_printed"))
        lines.append(f"- **{m['name']}** — {m['note']} (пруф: печ. стр. {pg or '—'})")
    lines += ["", "_Сгенерировано kdb.export_rules; вердикты механические, "
              "спорные строки — владельцу._", ""]

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    write_json(OUT_JSON, {"rows": rows, "missing": missing, "counts": counts})
    print(f"OK: {len(rows)} строк, вердикты: {counts}; -> {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
