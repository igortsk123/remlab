#!/usr/bin/env python3
"""Срез плиты-подложки у черновиков TRELLIS (paint-photo-fill-01, этап 02-prep; T-20261121-170/2).

ЗАЧЕМ. В «сыром» GLB от TRELLIS под товаром лежат большие плоские листы во весь куб 1×1 м (3 листа по 70–180 тыс. граней) и тысячи мелких плоских обломков
на том же уровне. Они съедают габарит (товар на кадре и в упрощении 150 тыс. граней — крохотный), портят упрощение, развёртку и цвет (грани плиты тянут текстуру), а на кадре
выглядят как «ковёр из крошки». Это дефект ВСЕХ черновиков, поэтому правило общее: найти плоский горизонтальный лист(ы) на дне модели и крошку на его уровне, срезать,
записать, что и сколько срезано; ни одного ID товара.

КАК (всё считается по связным кускам — грани, которые делят вершины):
1) вертикаль — там, где самый большой плоский кусок тоньше всего (у glTF это Y; `up_axis` в правилах можно задать числом);
2) плита = кусок толщиной ≤ `thin_frac`·L, оба горизонтальных размера ≥ `plate_span_frac`·L, и ТОВАР В ОСНОВНОМ НАД ним (≥ `min_above_share` площади остальных кусков выше слоя плиты;
   основание, чуть ушедшее под лист, — норма). Так столешница-лист (товар под ней) и балдахин не принимаются за плиту. L — наибольший габарит всей модели;
   плита БОЛЬШЕ товара: след товара ≤ `max_footprint_ratio` от следа листа (у настоящих плит 1–24 %, у ложных — диска основания, плинта — 100 %: кадры 21.11 показали «обгрызенное» основание тюльпана);
3) крошка = плоский кусок целиком в слое плиты ± допуск;
4) нет плиты — модель не трогаем (`plate_found=false` — это нормально для чистого черновика); после среза осталось меньше `min_remain_face_share` — модель САМА плоская вещь (ковёр),
   не трогаем и пишем причину; всё остальное остаётся байт в байт (грани не меняются, лишние вершины выбрасываются).
Все пороги — `tools/scout/rules/plate-strip.json`.

Для этапа 02: до упрощения вызвать `analyze(vertices, faces)` → (маска граней на удаление, отчёт) — чистый numpy, работает и в python Blender (`sg_prep_shape.py`), удалить грани маской; либо `strip_mesh(mesh)` (trimesh);
`plate_metrics(report)` — мерки для check.json этапа 02-prep.
Запуск (тяжёлое — под heavy-slot; 460 тыс. граней ≈ 1–2 ГБ):
    python3 tools/scout/plate_strip.py strip --glb in.glb --out out.glb [--run RUN --sku SKU --stage 02-plate]
    python3 tools/scout/plate_strip.py survey --glb a.glb b.glb … [--json отчёт.json]   # только счёт, без записи моделей
    python3 tools/scout/plate_strip.py check                                              # правила целы (CI)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(HERE, "rules", "plate-strip.json")


def load_rules(path: str = RULES_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _components_numpy(f: np.ndarray, n_verts: int) -> np.ndarray:
    """Метка связного куска на вершину — только numpy (в python Blender нет scipy): подвешивание корней + прыжки по указателям до устойчивости."""
    a = np.r_[f[:, 0], f[:, 1], f[:, 2]]
    b = np.r_[f[:, 1], f[:, 2], f[:, 0]]
    lab = np.arange(n_verts)
    while True:
        la, lb = lab[a], lab[b]
        m = np.minimum(la, lb)
        new = lab.copy()
        np.minimum.at(new, la, m)
        np.minimum.at(new, lb, m)
        while True:
            nn = new[new]
            if (nn == new).all():
                break
            new = nn
        if (new == lab).all():
            return lab
        lab = new


def _components(faces: np.ndarray, n_verts: int, use_scipy: bool = True) -> np.ndarray:
    """Номер связного куска для каждой грани (грани делят вершины — один кусок). scipy есть — быстрее; нет (Blender) — numpy."""
    f = np.asarray(faces)
    vl = None
    if use_scipy:
        try:
            from scipy import sparse
            from scipy.sparse.csgraph import connected_components

            a = np.r_[f[:, 0], f[:, 1], f[:, 2]]
            b = np.r_[f[:, 1], f[:, 2], f[:, 0]]
            g = sparse.coo_matrix((np.ones(len(a), dtype=np.int8), (a, b)), shape=(n_verts, n_verts))
            _, vl = connected_components(g, directed=False)
        except ImportError:
            vl = None
    if vl is None:
        vl = _components_numpy(f, n_verts)
    _, inv = np.unique(vl[f[:, 0]], return_inverse=True)
    return inv


def analyze(vertices: np.ndarray, faces: np.ndarray, rules: dict | None = None) -> tuple[np.ndarray, dict]:
    """→ (remove: bool на грань, отчёт). Ничего не меняет; `remove` пуст (все False), если плиты нет или срез отказан (причина в отчёте)."""
    rules = rules or load_rules()
    V = np.asarray(vertices, dtype=np.float64)
    F = np.asarray(faces)
    nf = len(F)
    rep: dict = {"faces_before": int(nf), "plate_found": False, "refused": ""}
    remove = np.zeros(nf, dtype=bool)
    if nf == 0:
        rep["refused"] = "в модели нет граней"
        return remove, rep
    fl = _components(F, len(V))
    k = int(fl.max()) + 1
    tri = V[F]                                              # (nf, 3, 3)
    lo = np.full((k, 3), np.inf)
    hi = np.full((k, 3), -np.inf)
    for ax in range(3):
        np.minimum.at(lo[:, ax], fl, tri[:, :, ax].min(axis=1))
        np.maximum.at(hi[:, ax], fl, tri[:, :, ax].max(axis=1))
    ext = hi - lo
    gl, gh = lo.min(axis=0), hi.max(axis=0)
    L = float((gh - gl).max())
    if L <= 0:
        rep["refused"] = "модель без объёма"
        return remove, rep
    thin_max, span_min, tol = rules["thin_frac"] * L, rules["plate_span_frac"] * L, rules["level_tol_frac"] * L
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = 0.5 * np.linalg.norm(cross, axis=1)
    rep.update({"L": round(L, 5), "components": k, "extents_before": [round(float(x), 5) for x in (gh - gl)]})

    # вертикаль
    up = rules.get("up_axis", "auto")
    if up == "auto":
        srt = np.sort(ext, axis=1)
        flat = srt[:, 0] <= thin_max
        if not flat.any():
            rep["up_axis"] = 1
            return remove, rep
        j = int(np.argmax(np.where(flat, srt[:, 1] * srt[:, 2], -1.0)))
        up = int(np.argmin(ext[j]))
    up = int(up)
    h = [a for a in range(3) if a != up]
    rep["up_axis"] = up
    ext_up, ext_h = ext[:, up], ext[:, h]
    gmin = float(lo[:, up].min())
    cand = (ext_up <= thin_max) & (ext_h.min(axis=1) >= span_min)
    thin = ext_up <= thin_max                               # справка: «крошка без листа» (плиты нет, а плоские обломки у дна есть) видна по этим числам
    rep["thin_comps"] = int(thin.sum())
    rep["thin_at_floor"] = int((thin & (lo[:, up] <= gmin + tol)).sum())
    if cand.any():                                          # справка для разбора «почему не плита»: самый большой плоский лист
        j = int(np.argmax(np.where(cand, ext_h[:, 0] * ext_h[:, 1], -1.0)))
        rep["flat_max"] = {"span": [round(float(x), 3) for x in ext_h[j]], "thick": round(float(ext_up[j]), 4), "level_rel": round(float(lo[j, up] - gmin) / L, 3)}
    if not cand.any():
        return remove, rep
    floor_lo = float(lo[cand, up].min())                    # плита — нижний слой больших листов; остальные листы (балдахин, столешница) — товар
    plate = cand & (lo[:, up] <= floor_lo + tol)
    slab_lo0, slab_hi0 = float(lo[plate, up].min()), float(hi[plate, up].max())
    comp_area = np.bincount(fl, weights=area, minlength=k)
    center = 0.5 * (lo[:, up] + hi[:, up])
    rest = ~plate
    if not rest.any():
        rep.update({"plate_found": True, "plates": int(plate.sum()), "crumbs": 0, "refused": "в модели только плоские листы: модель сама плоская — не трогаем"})
        return remove, rep
    above_share = float(comp_area[rest & (center >= slab_hi0 - tol)].sum() / max(comp_area[rest].sum(), 1e-12)) if rest.any() else 0.0
    rep["above_share"] = round(above_share, 4)
    if above_share < rules["min_above_share"]:
        rep["refused"] = ""
        rep["flat_max"]["not_plate"] = f"товар ниже листа (над ним {above_share:.0%} < {rules['min_above_share']:.0%}) — столешница/балдахин, не плита"
        return remove, rep
    slab_lo, slab_hi = float(lo[plate, up].min()), float(hi[plate, up].max())
    crumb = ~plate & (ext_up <= thin_max) & (lo[:, up] >= slab_lo - tol) & (hi[:, up] <= slab_hi + tol)
    rm_comp = plate | crumb
    rm_face = rm_comp[fl]
    keep_share = 1.0 - float(rm_face.sum()) / nf
    rep.update({"plate_found": True, "plates": int(plate.sum()), "crumbs": int(crumb.sum()), "slab": [round(slab_lo, 5), round(slab_hi, 5)],
                "plate_thickness_max": round(float(ext_up[plate].max()), 5), "plate_span": [round(float(ext_h[plate].min()), 4), round(float(ext_h[plate].max()), 4)]})
    if keep_share < rules["min_remain_face_share"]:
        rep["refused"] = f"после среза осталось {keep_share:.1%} граней (< {rules['min_remain_face_share']:.0%}): модель сама плоская — не трогаем"
        return remove, rep
    kept_comp = ~rm_comp
    alo, ahi = lo[kept_comp].min(axis=0), hi[kept_comp].max(axis=0)
    hb = (gh - gl)[h]
    ha = (ahi - alo)[h]
    fp_ratio = float(ha[0] * ha[1] / (hb[0] * hb[1]))
    if fp_ratio > rules["max_footprint_ratio"]:             # лист не больше товара, который на нём стоит: это основание/плинт самого товара, не плита-подложка
        rep.update({"plate_found": False, "footprint_ratio": round(fp_ratio, 4)})
        rep["flat_max"]["not_plate"] = f"след товара {fp_ratio:.0%} от следа листа (> {rules['max_footprint_ratio']:.0%}) — основание товара, не плита"
        for k_ in ("plates", "crumbs", "slab", "plate_thickness_max", "plate_span"):
            rep.pop(k_, None)
        return remove, rep
    remove = rm_face
    rep.update({
        "faces_after": int(nf - remove.sum()),
        "face_share_removed": round(float(remove.sum()) / nf, 4),
        "area_share_removed": round(float(area[remove].sum() / area.sum()), 4),
        "extents_after": [round(float(x), 5) for x in (ahi - alo)],
        "footprint_ratio": round(fp_ratio, 4),
        "gap_to_plate_frac": round(float(alo[up] - slab_lo) / L, 4),     # < 0: основание товара ушло под лист
    })
    return remove, rep


def strip_mesh(mesh, rules: dict | None = None):
    """trimesh-меш → (новый меш без плиты и крошки, отчёт). Плиты нет/отказ — вернётся тот же объект. Текстура, UV и материал сохраняются."""
    import trimesh

    remove, rep = analyze(mesh.vertices, mesh.faces, rules)
    if not remove.any():
        return mesh, rep
    out = trimesh.Trimesh(vertices=np.asarray(mesh.vertices), faces=np.asarray(mesh.faces)[~remove], visual=mesh.visual, process=False)
    out.remove_unreferenced_vertices()
    return out, rep


def plate_metrics(rep: dict, rules: dict | None = None) -> dict:
    """Мерки для check.json этапа (формат `paint_stage.write_check(metrics=…)`). Без плиты — только справочная мерка «плиты не было» (этап не краснеет)."""
    rules = rules or load_rules()
    m: dict = {"plate_found": {"value": bool(rep.get("plate_found"))}}
    if rep.get("plate_found") and not rep.get("refused"):
        m["remaining_face_share"] = {"value": round(1.0 - rep["face_share_removed"], 4), "threshold": rules["min_remain_face_share"], "op": ">="}
        m["gap_to_plate_frac"] = {"value": rep["gap_to_plate_frac"], "threshold": rules["max_gap_to_plate_frac"], "op": "<="}
        m["above_share"] = {"value": rep["above_share"], "threshold": rules["min_above_share"], "op": ">="}
        m["footprint_ratio"] = {"value": rep["footprint_ratio"], "threshold": rules["max_footprint_ratio"], "op": "<="}
        m["area_share_removed"] = {"value": rep["area_share_removed"]}
    elif rep.get("refused"):
        m["refused"] = {"value": 1, "threshold": 0, "op": "=="}
    return m


def _paint_stage():
    cands = [HERE, os.environ.get("PAINT_STAGE_DIR", ""),
             os.path.join(os.path.expanduser("~"), "igor", "remlab", ".claude", "worktrees", "paint-fill-1120", "tools", "scout")]
    for d in cands:
        if d and os.path.exists(os.path.join(d, "paint_stage.py")):
            sys.path.insert(0, d)
            import paint_stage
            return paint_stage
    raise SystemExit("нет paint_stage.py: tools/scout или PAINT_STAGE_DIR")


def run_strip(glb: str, out: str, run: str | None = None, sku: str | None = None, stage: str = "02-plate") -> dict:
    import trimesh

    t0 = time.time()
    rules = load_rules()
    mesh = trimesh.load(glb, force="mesh", process=False)
    res, rep = strip_mesh(mesh, rules)
    if res is not mesh:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        res.export(out)
    rep["seconds"] = round(time.time() - t0, 1)
    rep["written"] = res is not mesh
    if run and sku:
        ps = _paint_stage()
        sd = ps.stage_dir(run, sku, stage)
        why = rep.get("refused", "")
        ps.write_check(sd, stage, sku, passed=None if not why else False, reason=why, metrics=plate_metrics(rep, rules), seconds=time.time() - t0,
                       outputs=[os.path.basename(out)] if rep["written"] else [], report=rep, rules_file="tools/scout/rules/plate-strip.json")
    return rep


def check() -> int:
    r = load_rules()
    bad = []
    for k, lo_, hi_ in (("thin_frac", 0, 0.1), ("plate_span_frac", 0.2, 1.0), ("level_tol_frac", 0, 0.2), ("min_remain_face_share", 0, 0.5), ("max_gap_to_plate_frac", 0, 0.5), ("min_above_share", 0.5, 1.0), ("max_footprint_ratio", 0.05, 1.0)):
        v = r.get(k)
        if not isinstance(v, (int, float)) or not lo_ < v <= hi_:
            bad.append(f"{k}={v!r} вне ({lo_}; {hi_}]")
    if r.get("up_axis") not in ("auto", 0, 1, 2):
        bad.append(f"up_axis={r.get('up_axis')!r}")
    for b in bad:
        print("ОШИБКА:", b)
    print("plate_strip check:", "ок" if not bad else f"{len(bad)} замечаний")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("strip")
    s.add_argument("--glb", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--run")
    s.add_argument("--sku")
    s.add_argument("--stage", default="02-plate")
    v = sub.add_parser("survey")
    v.add_argument("--glb", nargs="+", required=True)
    v.add_argument("--json")
    sub.add_parser("check")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        return check()
    if a.cmd == "strip":
        rep = run_strip(a.glb, a.out, a.run, a.sku, a.stage)
        print(json.dumps(rep, ensure_ascii=False))
        return 1 if rep.get("refused") else 0
    import trimesh
    rules = load_rules()
    rows = []
    for p in a.glb:
        t0 = time.time()
        try:
            m = trimesh.load(p, force="mesh", process=False)
            _rm, rep = analyze(m.vertices, m.faces, rules)
            del m
        except Exception as e:  # noqa: BLE001 — счётчик отказов: файл не роняет обход
            rep = {"error": f"{type(e).__name__}: {str(e)[:150]}"}
        rep["file"] = os.path.basename(p)
        rep["seconds"] = round(time.time() - t0, 1)
        rows.append(rep)
        print(json.dumps({k: rep.get(k) for k in ("file", "faces_before", "plate_found", "plates", "crumbs", "face_share_removed", "area_share_removed", "extents_before", "extents_after", "gap_to_plate_frac", "above_share", "flat_max", "thin_comps", "thin_at_floor", "refused", "error", "seconds")}, ensure_ascii=False), flush=True)
    n = len(rows)
    found = sum(1 for r in rows if r.get("plate_found"))
    print(f"ИТОГО: файлов {n}, с плитой {found}, без {sum(1 for r in rows if not r.get('plate_found') and 'error' not in r)}, отказов среза {sum(1 for r in rows if r.get('refused'))}, ошибок чтения {sum(1 for r in rows if 'error' in r)}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
