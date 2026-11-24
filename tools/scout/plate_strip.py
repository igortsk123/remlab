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
    python3 tools/scout/plate_strip.py left --glb a.glb b.glb …                            # сторож «плита осталась» на готовых моделях (без записи)

СТОРОЖ `plate_left(vertices, faces)` (T-20261124-07). Срез выше работает по плоским кускам у сырого 01 и после упрощения до 150 тыс. граней плиту часто не находит (6 из 17 у черновиков 20.11:
лист уже не плоский кусок). А плита, дошедшая до 08 и сайта, — это серый/чёрный лист шире товара (на карте глянца — чёрное зеркало). Поэтому на ГОТОВОЙ модели плиту ищет другой счёт — по следу:
нижний слой горизонтальных граней (самый большой по площади в нижних `zone_frac`·L) покрывает ≥ `min_cover` сетки следа, над слоем занято ≤ `max_above_share` покрытых клеток, а след товара над слоем ≤ `max_above_footprint` следа (кашпо-ящик с дном во весь след — не плита). Только счёт и отчёт, модель не меняет;
этап 08 (material_stage) кладёт его мерку `plate_left` в check.json (≠ 0 → этап красный). Пороги — блок `left_check` в rules/plate-strip.json.
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


def _fragments(tri: np.ndarray, area: np.ndarray, max_area: float, passes: int = 8) -> tuple[np.ndarray, np.ndarray]:
    """Крупные грани делим на 4 (по серединам рёбер), пока площадь куска > max_area → (центры кусков, площади). Нужно, чтобы большой лист из пары треугольников
    засчитывался во всех клетках сетки, а не в одной (у плотных сеток 150 тыс. граней делить нечего)."""
    cs, as_ = [], []
    cur_t, cur_a = tri, area
    for _ in range(passes):
        big = cur_a > max_area
        cs.append(cur_t[~big].mean(axis=1))
        as_.append(cur_a[~big])
        if not big.any():
            cur_t = cur_t[:0]
            break
        t = cur_t[big]
        a, b, c = t[:, 0], t[:, 1], t[:, 2]
        ab, bc, ca = (a + b) / 2, (b + c) / 2, (c + a) / 2
        cur_t = np.concatenate([np.stack([a, ab, ca], 1), np.stack([ab, b, bc], 1), np.stack([ca, bc, c], 1), np.stack([ab, bc, ca], 1)])
        cur_a = np.tile(cur_a[big] / 4.0, 4)
    if len(cur_t):
        cs.append(cur_t.mean(axis=1))
        as_.append(cur_a)
    return np.concatenate(cs), np.concatenate(as_)


def plate_left(vertices: np.ndarray, faces: np.ndarray, rules: dict | None = None) -> dict:
    """Сторож «плита осталась» на готовой модели → отчёт {plate_left, cover, above_share, level_rel, layer_faces, L}. Только счёт; модель не меняется."""
    lc = (rules or load_rules())["left_check"]
    V = np.asarray(vertices, dtype=np.float64)
    F = np.asarray(faces)
    rep: dict = {"plate_left": False, "cover": 0.0, "above_share": 1.0}
    if len(F) == 0:
        rep["refused"] = "в модели нет граней"
        return rep
    lo, hi = V.min(axis=0), V.max(axis=0)
    L = float((hi - lo).max())
    up = int(lc["up_axis"])
    h = [a for a in range(3) if a != up]
    if L <= 0 or (hi - lo)[h[0]] <= 0 or (hi - lo)[h[1]] <= 0:
        rep["refused"] = "модель без объёма"
        return rep
    tri = V[F]
    c = tri.mean(axis=1)
    cr = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ar = 0.5 * np.linalg.norm(cr, axis=1)
    ny = np.abs(cr[:, up]) / np.maximum(2.0 * ar, 1e-15)
    y = c[:, up] - lo[up]
    hor = ny >= lc["normal_min"]
    zb = max(int(lc["zone_frac"] / lc["bin_frac"]), 1)
    bi = np.clip((y / (lc["bin_frac"] * L)).astype(np.int64), 0, 10 ** 9)
    sel = hor & (bi < zb)
    hist = np.zeros(zb)
    np.add.at(hist, bi[sel], ar[sel])
    ystar = (int(np.argmax(hist)) + 0.5) * lc["bin_frac"] * L
    tol = lc["level_tol_frac"] * L
    layer = hor & (np.abs(y - ystar) <= tol)
    above = y > ystar + tol
    n = int(lc["grid"])
    ex, ez = (hi - lo)[h[0]], (hi - lo)[h[1]]
    cell = (ex / n) * (ez / n)

    def occupancy(mask):
        fc, fa = _fragments(tri[mask], ar[mask], 0.25 * cell)
        ix = np.clip(((fc[:, h[0]] - lo[h[0]]) / ex * n).astype(np.int64), 0, n - 1)
        iz = np.clip(((fc[:, h[1]] - lo[h[1]]) / ez * n).astype(np.int64), 0, n - 1)
        a = np.zeros((n, n))
        np.add.at(a, (ix, iz), fa)
        return a

    low_c = occupancy(layer) >= lc["cell_fill"] * cell
    ab_c = occupancy(above) >= lc["above_cell_fill"] * cell
    n_low = int(low_c.sum())
    cover = n_low / float(n * n)
    above_share = float((ab_c & low_c).sum()) / max(n_low, 1)
    if ab_c.any():                                          # габарит занятых клеток над слоем, доля следа (крошка мельче клетки не в счёте)
        ix, iz = np.nonzero(ab_c)
        footprint = float((ix.max() - ix.min() + 1) * (iz.max() - iz.min() + 1)) / float(n * n)
    else:
        footprint = None                                    # над слоем пусто: плоская вещь (ковёр), не плита
    plate = bool(cover >= lc["min_cover"] and above_share <= lc["max_above_share"] and footprint is not None and footprint <= lc["max_above_footprint"])
    rep.update({"plate_left": plate, "cover": round(cover, 4), "above_share": round(above_share, 4), "above_footprint": None if footprint is None else round(footprint, 4),
                "level_rel": round(ystar / L, 4), "layer_faces": int(layer.sum()), "L": round(L, 5)})
    return rep


def left_metrics(rep: dict) -> dict:
    """Мерки для check.json этапа: `plate_left` = 0 (порог ≤ 0); справочно — покрытие и занятость над слоем."""
    m = {"plate_left": {"value": int(bool(rep.get("plate_left"))), "threshold": 0, "op": "<="},
         "plate_cover": {"value": rep.get("cover")}, "plate_above_share": {"value": rep.get("above_share")}, "plate_above_footprint": {"value": rep.get("above_footprint")}}
    if rep.get("refused"):                                  # сторож не смог посчитать (пустая модель/без объёма) — не «чисто», а красный отказ с причиной
        m["plate_left_refused"] = {"value": 1, "threshold": 0, "op": "=="}
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
    lc = r.get("left_check") or {}
    for k, lo_, hi_ in (("zone_frac", 0, 0.5), ("bin_frac", 0, 0.05), ("level_tol_frac", 0, 0.1), ("normal_min", 0.5, 1.0), ("cell_fill", 0, 1.0), ("above_cell_fill", 0, 1.0), ("min_cover", 0.5, 1.0), ("max_above_share", 0, 1.0), ("max_above_footprint", 0, 1.0)):
        v = lc.get(k)
        if not isinstance(v, (int, float)) or not lo_ < v <= hi_:
            bad.append(f"left_check.{k}={v!r} вне ({lo_}; {hi_}]")
    if lc.get("up_axis") not in (0, 1, 2):
        bad.append(f"left_check.up_axis={lc.get('up_axis')!r}")
    if not isinstance(lc.get("grid"), int) or not 4 <= lc["grid"] <= 200:
        bad.append(f"left_check.grid={lc.get('grid')!r}")
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
    lf = sub.add_parser("left")
    lf.add_argument("--glb", nargs="+", required=True)
    lf.add_argument("--json")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        return check()
    if a.cmd == "left":
        import trimesh
        rules = load_rules()
        rows = []
        for p in a.glb:
            try:
                m = trimesh.load(p, force="mesh", process=False, skip_materials=True)
                rep = plate_left(m.vertices, m.faces, rules)
                del m
            except Exception as e:  # noqa: BLE001 — счётчик отказов: файл не роняет обход
                rep = {"error": f"{type(e).__name__}: {str(e)[:150]}"}
            rep["file"] = p
            rows.append(rep)
            print(json.dumps(rep, ensure_ascii=False), flush=True)
        print(f"ИТОГО: файлов {len(rows)}, с плитой {sum(1 for r in rows if r.get('plate_left'))}, ошибок чтения {sum(1 for r in rows if 'error' in r)}")
        if a.json:
            with open(a.json, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, indent=1)
        return 0
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
