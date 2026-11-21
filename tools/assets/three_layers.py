#!/usr/bin/env python3
"""Ш4 «части тремя слоями» — проба ВХОЛОСТУЮ рядом с нынешним этапом 03 (paint-photo-fill-01 § «Порядок v3», T-181).

Слои на грань: `semantic_part` (кто это), `material_region` (из чего), `surface_zone` (front/side/rear/underside/interior).
Источник семантики и материала — ФОТО магазина: SAM2 по фото → камерой этапа 04 (`stages/render_view0/ids.npz`: пиксель холста → грань)
на ВИДИМЫЕ грани → на невидимое по форме (связность, плоскости), конфликт → unknown.

Шаг `photo`: SAM2 по фото на холсте этапа 04 → карта областей `photo_regions.npz` + кадр.
Запуск (pakardev, venv scout, под heavy-slot):
    python3 tools/assets/three_layers.py photo --run <e2eHD папка прогона> --sku <имя> --photo <rgba.png> --out <папка>
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "scout"))
sys.path.insert(0, os.path.join(HERE, "..", "scout", "salad", "trellis"))
import parts_sam as ps  # noqa: E402
import parts_vote as pv  # noqa: E402

BG_SHARE = 0.5      # маска, у которой ≥ половины площади вне вырезки предмета, — фон/реквизит


def canvas_rgb(photo_path: str, cv: dict, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Фото → холст этапа 04 (n×n): цвет на сером фоне и маска предмета. Та же карта, что `pose_fit.canvas_P`."""
    import pose_fit as PF
    import stage_loss as SL
    from PIL import Image

    rgba = np.array(Image.open(photo_path).convert("RGBA"))
    P = PF.canvas_P(cv, n)
    a = SL.warp_inv((rgba[..., 3] / 255.0).astype(np.float32), P, (n, n))
    chans = [SL.warp_inv(rgba[..., c].astype(np.float32), P, (n, n)) for c in range(3)]
    a = np.clip(np.asarray(a, np.float32), 0, 1)
    rgb = np.stack([np.asarray(c, np.float32) for c in chans], axis=-1)
    rgb = (rgb * a[..., None] + 128 * (1 - a[..., None])).clip(0, 255).astype(np.uint8)
    return rgb, a > 0.5


def cmd_photo(args) -> int:
    from PIL import Image

    pose = json.load(open(os.path.join(args.run, "pose.json"), encoding="utf-8"))
    n = int(pose["px"])
    rgb, obj = canvas_rgb(args.photo, pose["canvas"], n)
    ids = np.load(os.path.join(args.run, "stages", "render_view0", "ids.npz"))["ids"]
    rules = pv.load_rules()
    model, proc = ps.load_sam(rules["sam"]["model"])
    masks = ps.sam_masks(model, proc, rgb, obj, rules)
    # маски, легшие на фон/реквизит (вне вырезки): доля площади вне предмета ≥ BG_SHARE → отбрасываем и считаем (директор 21.11)
    out_share = [float((m & ~obj).sum()) / max(1, int(m.sum())) for m in masks]
    bg = [i for i, s in enumerate(out_share) if s >= BG_SHARE]
    masks_all, masks = masks, [m for i, m in enumerate(masks) if i not in set(bg)]
    lab = pv.label_map(masks, obj, rules)
    os.makedirs(args.out, exist_ok=True)
    json.dump({"sku": args.sku, "masks_total": len(masks_all), "masks_on_background": len(bg), "bg_share_threshold": BG_SHARE,
               "out_share": [round(s, 3) for s in out_share]}, open(os.path.join(args.out, f"{args.sku}.photo_masks.json"), "w"), ensure_ascii=False)
    np.savez_compressed(os.path.join(args.out, f"{args.sku}.photo_regions.npz"), lab=lab.astype(np.int16), obj=obj, ids=ids)
    Image.fromarray(rgb).save(os.path.join(args.out, f"{args.sku}.canvas.png"))
    over = rgb.copy()
    pal = np.array(ps.PALETTE, np.uint8)
    for k in np.unique(lab[lab >= 0]):
        over[lab == k] = (0.4 * over[lab == k] + 0.6 * pal[int(k) % len(pal)]).astype(np.uint8)
    over[~obj] = 255
    Image.fromarray(over).save(os.path.join(args.out, f"{args.sku}.photo_regions.png"))
    print(f"{args.sku}: масок SAM2 {len(masks_all)}, из них на фоне/реквизите {len(bg)} (отброшены), областей {int(lab.max()) + 1 if (lab >= 0).any() else 0}, предмет {int(obj.sum())} px, граней на фото {len(np.unique(ids[ids >= 0]))}")
    return 0

ZONES = ["front", "side", "rear", "top", "underside", "interior"]
SMOOTH_COS = float(np.cos(np.radians(40)))        # соседние грани «одной поверхности», если нормали различаются < 40°
SHARE_MIN = 0.6                                    # грань берёт область фото, если ≥ 60 % её размеченных пикселей — одна область
GROUP_AB, GROUP_L = 6.0, 30.0                      # материал-группа: области фото близки по (a,b) ≤ 6 и по L* ≤ 30 (тень не делит ткань)
TRUST_AGREE, TRUST_SEEN = 0.8, 0.2                 # «доверенная» часть нынешнего 03 — как в similar_to_trusted
EDGE_PX = 2


def face_region_from_photo(ids: np.ndarray, lab: np.ndarray, nf: int) -> tuple[np.ndarray, np.ndarray, dict]:
    """Пиксели холста → грани: у каждой видимой на фото грани — область SAM2 с наибольшим числом пикселей, если её доля ≥ SHARE_MIN, иначе −1 (спор).
    Возврат: область по граням (−2 — не видна на фото, −1 — спор/без области), число размеченных пикселей на грань, счётчики."""
    ok = (ids >= 0) & (lab >= 0)
    nreg = int(lab.max()) + 1 if (lab >= 0).any() else 1
    pair = ids[ok].astype(np.int64) * nreg + lab[ok].astype(np.int64)
    cnt = np.bincount(pair, minlength=nf * nreg).reshape(nf, nreg)
    tot = cnt.sum(axis=1)
    reg = np.full(nf, -2, np.int32)
    seen_photo = np.zeros(nf, bool)
    seen_photo[np.unique(ids[ids >= 0])] = True
    reg[seen_photo] = -1
    has = tot > 0
    top = cnt.argmax(axis=1)
    share = np.where(has, cnt[np.arange(nf), top] / np.maximum(tot, 1), 0.0)
    take = has & (share >= SHARE_MIN)
    reg[take] = top[take]
    return reg, tot, {"faces_on_photo": int(seen_photo.sum()), "faces_labelled": int(has.sum()), "faces_taken": int(take.sum()), "faces_conflict": int((has & ~take).sum())}


def propagate(reg: np.ndarray, adj, normals: np.ndarray, max_rounds: int = 400) -> tuple[np.ndarray, dict]:
    """Невидимое — по форме: метка идёт по соседним граням с почти одной нормалью (< 40°), волнами; двое претендуют разными метками → −1 (спор, дальше не идёт); не дошли → −3."""
    nf = len(reg)
    coo = adj.tocoo()
    rows, cols = coo.row, coo.col
    smooth = (normals[rows] * normals[cols]).sum(axis=1) >= SMOOTH_COS
    rows, cols = rows[smooth], cols[smooth]
    lab = np.where(reg >= 0, reg, -3).astype(np.int32)
    lab[reg == -1] = -1                                  # спор на фото остаётся спором
    big = np.iinfo(np.int32).max
    rounds = 0
    for rounds in range(1, max_rounds + 1):
        claim = (lab[rows] >= 0) & (lab[cols] == -3)
        if not claim.any():
            break
        lo = np.full(nf, big, np.int64)
        hi = np.full(nf, -1, np.int64)
        np.minimum.at(lo, cols[claim], lab[rows][claim])
        np.maximum.at(hi, cols[claim], lab[rows][claim])
        got = hi >= 0
        lab[got & (lo == hi)] = lo[got & (lo == hi)]
        lab[got & (lo != hi)] = -1
    return lab, {"rounds": rounds, "unreached": int((lab == -3).sum()), "conflict_after": int((lab == -1).sum())}


def material_groups(canvas_rgb_img: np.ndarray, lab_img: np.ndarray, obj: np.ndarray) -> tuple[dict, dict]:
    """Области фото → материал-группы по цвету самого фото: близки по (a,b) и L* — одна группа. Возврат: region→group, group→{lab, regions, px}."""
    import parts_colour as pcol

    rid = [int(r) for r in np.unique(lab_img[lab_img >= 0])]
    info = {}
    for r in rid:
        m = (lab_img == r) & obj
        if m.sum() < 30:
            continue
        L = pcol.rgb_to_lab(canvas_rgb_img[m].astype(np.float32))
        info[r] = (np.median(L, axis=0), int(m.sum()))
    order = sorted(info, key=lambda r: -info[r][1])
    groups: list[dict] = []
    r2g = {}
    for r in order:
        lb, px = info[r]
        best, bd = None, 1e9
        for gi, g in enumerate(groups):
            dab = float(np.hypot(*(lb[1:] - g["lab"][1:])))
            if dab <= GROUP_AB and abs(float(lb[0] - g["lab"][0])) <= GROUP_L and dab < bd:
                best, bd = gi, dab
        if best is None:
            groups.append({"lab": lb.copy(), "regions": [r], "px": px})
            r2g[r] = len(groups) - 1
        else:
            g = groups[best]
            g["lab"] = (g["lab"] * g["px"] + lb * px) / (g["px"] + px)
            g["px"] += px
            g["regions"].append(r)
            r2g[r] = best
    return r2g, {gi: {"lab": [round(float(x), 1) for x in g["lab"]], "regions": g["regions"], "px": g["px"]} for gi, g in enumerate(groups)}


def smooth_normals(normals: np.ndarray, areas: np.ndarray, adj, iters: int = 8) -> np.ndarray:
    """Нормали граней усредняются по соседям (шум TRELLIS на узоре давал «крапинку» зон): iters шагов среднего по смежности, взвешено площадью."""
    wn = normals * areas[:, None]
    for _ in range(iters):
        wn = adj @ wn + wn
    n = np.linalg.norm(wn, axis=1, keepdims=True)
    return wn / np.maximum(1e-12, n)


def surface_zones(normals: np.ndarray, reg_photo: np.ndarray, areas: np.ndarray, seen_orbit: np.ndarray) -> np.ndarray:
    """surface_zone по осям формы и направлению на камеру фото: front/rear — угол к камере; top/underside — по оси вверх (y); interior — не видна ни одному кадру облёта."""
    vis = reg_photo != -2
    d = (normals[vis] * areas[vis, None]).sum(axis=0)
    d = d / max(1e-9, float(np.linalg.norm(d)))
    nd = normals @ d
    ny = normals[:, 1]
    z = np.full(len(normals), ZONES.index("side"), np.int8)
    z[nd >= 0.5] = ZONES.index("front")
    z[nd <= -0.5] = ZONES.index("rear")
    z[ny >= 0.7] = ZONES.index("top")
    z[ny <= -0.7] = ZONES.index("underside")
    z[~seen_orbit & (ny > -0.7)] = ZONES.index("interior")
    return z


def edge_agreement(label_img: np.ndarray, grey: np.ndarray, obj: np.ndarray) -> dict:
    """Границы карты меток (внутри предмета) против независимого сигнала — краёв самого фото (градиент яркости, верхние 10 % по предмету)."""
    from scipy import ndimage

    gy, gx = np.gradient(ndimage.gaussian_filter(grey.astype(np.float32), 1.0))
    g = np.hypot(gx, gy)
    edge = (g >= np.percentile(g[obj], 90)) & obj
    edge_near = ndimage.binary_dilation(edge, iterations=EDGE_PX)
    L = label_img
    b = np.zeros(L.shape, bool)
    for dy, dx in ((0, 1), (1, 0)):
        a = L[: L.shape[0] - dy, : L.shape[1] - dx]
        c = L[dy:, dx:]
        diff = (a != c) & (a >= 0) & (c >= 0)
        b[: L.shape[0] - dy, : L.shape[1] - dx] |= diff
    n = int(b.sum())
    return {"boundary_px": n, "on_photo_edge": round(float((b & edge_near).sum()) / max(1, n), 3), "baseline_edge_near_share": round(float(edge_near[obj].mean()), 3)}


def cmd_layers(args) -> int:
    import trimesh
    from PIL import Image

    import material_class  # noqa: F401  (проверка, что каталог-классы доступны)
    import paint_run_all as RA
    import parts_refine as pr
    import parts_roles as pro

    d, sku, out = args.run, args.sku, args.out
    shape = trimesh.load(os.path.join(d, "02-prep", "shape.glb"), force="mesh", process=False)
    V, F = np.asarray(shape.vertices), np.asarray(shape.faces)
    z = np.load(os.path.join(d, "03-parts", "parts.npz"))
    part, agree, seen = z["part"].astype(np.int64), z["agree"].astype(np.float32), z["seen"].astype(bool)
    nf = len(F)
    assert len(part) == nf, "форма и части не совпали по граням"
    pj = json.load(open(os.path.join(d, "03-parts", "parts.json"), encoding="utf-8"))
    pinfo = {int(p["id"]): p for p in pj["parts"]}
    pz = np.load(os.path.join(out, f"{sku}.photo_regions.npz"))
    lab_img, obj, ids = pz["lab"].astype(np.int32), pz["obj"], pz["ids"]
    rgb = np.array(Image.open(os.path.join(out, f"{sku}.canvas.png")).convert("RGB"))
    tri = V[F]
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    areas = np.linalg.norm(nrm, axis=1) / 2
    nrm = nrm / np.maximum(1e-12, np.linalg.norm(nrm, axis=1, keepdims=True))
    import part_shapes as shp  # noqa: F401
    import parts_vote as pv2
    adj = pv2.weld_adjacency(V, F)

    reg, ntot, c1 = face_region_from_photo(ids, lab_img, nf)
    r2g, groups = material_groups(rgb, lab_img, obj)
    sem, c2 = propagate(reg, adj, nrm)
    mat = np.full(nf, -3, np.int32)
    for r, g in r2g.items():
        mat[sem == r] = g
    mat[sem == -1] = -1
    # материал-спор/пробел внутри одного материала (узор делит область SAM на куски): соседи с ОДНОЙ группой отдают её; спор только если претендуют РАЗНЫЕ группы
    m_in = np.where(mat >= 0, mat, np.where(sem == -2, -2, -3)).astype(np.int32)
    mat2, c3 = propagate(np.where(mat >= 0, mat, -2).astype(np.int32), adj, nrm)
    mat = np.where(mat >= 0, mat, np.where(mat2 >= 0, mat2, np.where(mat2 == -1, -1, -3))).astype(np.int32)
    nrm_s = smooth_normals(nrm, areas, adj)
    zone = surface_zones(nrm_s, reg, areas, seen)

    # текущие роли и каналы по частям нынешнего 03
    role_f = np.array([pinfo[int(p)]["role"] if int(p) in pinfo else "unknown" for p in part])
    chan_f = np.array([str(pinfo[int(p)].get("material_channel") or "") if int(p) in pinfo else "" for p in part])
    trusted = (role_f != "unknown") & (agree >= TRUST_AGREE) & seen
    w = areas * seen

    def share_unknown(unk: np.ndarray) -> float:
        return round(float((w * unk).sum() / max(1e-12, w.sum())) * 100, 1)

    m_cur = share_unknown(role_f == "unknown")
    m_new = share_unknown(mat < 0)
    # утечка материала (мерка владельца): в группе грани доверенных частей 03 ДЕРЕВО и ТКАНЬ по классам каталога вместе (шпон↔массив — одно дерево, не утечка).
    cat = {r["sid"]: r for r in json.load(open(args.catalog, encoding="utf-8"))}
    chs_s, cc_s = RA.catalog_channels(cat.get(sku))
    ccd = dict(kv.split("=", 1) for kv in cc_s.split(",") if "=" in kv)

    def family(cls: str) -> str:
        c = (cls or "").lower()
        if any(k in c for k in ("wood", "veneer", "ldsp", "mdf", "plywood", "bamboo", "rattan")):
            return "wood"
        if any(k in c for k in ("fabric", "velour", "velvet", "boucle", "leather", "linen", "cloth", "chenille")):
            return "cloth"
        return "other" if c else "none"

    fam_ch = {c: family(ccd.get(c, "")) for c in set(chan_f.tolist())}
    fam_f = np.array([fam_ch.get(c, "none") for c in chan_f])
    leak, leak_rows = 0.0, []
    for g in sorted(set(mat[mat >= 0].tolist())):
        sel = (mat == g) & trusted & np.isin(fam_f, ("wood", "cloth"))
        if sel.sum() == 0:
            continue
        fam_w = {f: float(w[sel & (fam_f == f)].sum()) for f in ("wood", "cloth")}
        tot = sum(fam_w.values())
        maj = max(fam_w, key=fam_w.get)
        minor = tot - fam_w[maj]
        leak += minor
        leak_rows.append({"group": int(g), "family_share": {k: round(v / max(1e-12, tot), 3) for k, v in fam_w.items()}, "majority": maj, "minor_share": round(minor / max(1e-12, tot), 3)})
    leak_share = round(leak / max(1e-12, float((w * trusted).sum())) * 100, 1)
    no_class = round(float((w * trusted * (fam_f == "none")).sum() / max(1e-12, (w * trusted).sum())) * 100, 1)
    # утечка нынешнего 03 тем же ключом: у него «канал» части и есть решение, утечки внутри части нет по построению; считаем смешение каналов ВНУТРИ части — 0
    grey = rgb.astype(np.float32).mean(axis=2)
    cur_img = np.where(ids >= 0, part[np.maximum(ids, 0)], -1)
    new_img = np.where(ids >= 0, sem[np.maximum(ids, 0)], -1)
    metrics = {
        "sku": sku, "faces": nf, "photo": c1, "propagate": c2, "groups": groups,
        "visible_without_role_pct": {"current_03": m_cur, "three_layers_material": m_new},
        "material_leak_pct_of_trusted": leak_share, "leak_by_group": leak_rows, "trusted_03_channel_without_catalog_class_pct": no_class, "catalog": {"channels": chs_s, "classes": cc_s},
        "zones_share_pct": {ZONES[i]: round(float(areas[zone == i].sum() / areas.sum()) * 100, 1) for i in range(len(ZONES))},
        "edge_agreement": {"current_03": edge_agreement(cur_img, grey, obj), "three_layers": edge_agreement(new_img, grey, obj), "photo_regions": edge_agreement(lab_img, grey, obj)},
    }
    cam = json.load(open(os.path.join(d, "04-camera", "check.json"), encoding="utf-8"))
    cam_ok = bool(cam.get("passed"))
    metrics["camera_passed"] = cam_ok
    metrics["camera_iou"] = (cam.get("metric") or {}).get("value")
    metrics["abstained"] = not cam_ok            # камера этапа 04 не прошла → карта «пиксель фото → грань» ложная → слои НЕ строятся, остаётся нынешний 03
    mpath = os.path.join(out, f"{sku}.layers.json")
    json.dump(metrics, open(mpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    np.savez_compressed(os.path.join(out, f"{sku}.layers.npz"), sem=sem.astype(np.int16), mat=mat.astype(np.int16), zone=zone)
    print(f"{sku}: камера 04 {'прошла' if cam_ok else 'НЕ ПРОШЛА → воздержание (слои не годны)'} (IoU {metrics['camera_iou']})")
    print(f"{sku}: без роли (видимые) {m_cur}% → {m_new}% | утечка дерево↔ткань {leak_share}% (у 03 каналы без класса: {no_class}%) | границы на краях фото: 03 {metrics['edge_agreement']['current_03']['on_photo_edge']} · три слоя {metrics['edge_agreement']['three_layers']['on_photo_edge']} · фото {metrics['edge_agreement']['photo_regions']['on_photo_edge']} (фон {metrics['edge_agreement']['photo_regions']['baseline_edge_near_share']})")
    print("   групп материала:", len(groups), "· спорных граней на фото:", c1["faces_conflict"], "· не дошла метка:", c2["unreached"])
    if not args.no_frame:
        make_frame(args, V, F, part, role_f, sem, mat, zone, rgb, lab_img, ids, groups)
    return 0


def make_frame(args, V, F, part, role_f, sem, mat, zone, rgb, lab_img, ids, groups):
    """Кадр «нынешнее | три слоя»: верх — фото и вид камеры фото (области, роли 03, материал, зоны через карту граней); ниже — облёт: роли 03 / материал-группы / зоны."""
    from PIL import Image

    orbit = os.path.join(args.run, "work", "orbit")
    info = json.load(open(os.path.join(orbit, "orbit.json"), encoding="utf-8"))
    names = [v["name"] for v in info["views"]]
    order = ps.ROLE_ORDER
    cur = np.array([order.index(r) if r in order else order.index("unknown") for r in role_f], np.int32)
    HATCH = 99
    matp = np.where(mat >= 0, mat % 11, HATCH).astype(np.int32)
    zonep = zone.astype(np.int32)

    def row(lbl, hatch):
        tiles = []
        for n in names[0:8:2] if len(names) >= 8 else names[:4]:
            rgbv, mask, u, v, vis, _cos = ps.load_view(orbit, n)
            tiles.append(ps.paint_frame(orbit, n, lbl, u, v, vis, rgbv, mask, hatch=hatch))
        return np.concatenate(tiles, axis=1)

    legend_cur = [(("no role (unknown)" if r == "unknown" else r), ("hatch" if r == "unknown" else ps.PALETTE[i % len(ps.PALETTE)])) for i, r in enumerate(order)]
    legend_mat = [(f"mat{g} L{groups[g]['lab'][0]:.0f}", ps.PALETTE[g % 11 % len(ps.PALETTE)]) for g in sorted(groups)[:10]] + [("no material (unknown)", "hatch")]
    legend_zone = [(ZONES[i], ps.PALETTE[i % len(ps.PALETTE)]) for i in range(len(ZONES))]
    r1 = ps.add_legend(row(cur, order.index("unknown")), legend_cur)
    r2 = ps.add_legend(row(matp, HATCH), legend_mat)
    r3 = ps.add_legend(row(zonep, None), legend_zone)
    # верх: вид камеры фото
    def via_ids(lbl_f, hatch_val):
        img = np.where(ids >= 0, lbl_f[np.maximum(ids, 0)], -1)
        col = np.zeros(img.shape + (3,), np.uint8) + 255
        pal = np.array(ps.PALETTE, np.uint8)
        for k in np.unique(img[img >= 0]):
            col[img == k] = (200, 200, 200) if k == hatch_val else pal[int(k) % len(pal)]
        return (0.35 * rgb + 0.65 * col).astype(np.uint8) * (img >= 0)[..., None] + rgb * (img < 0)[..., None]
    n = rgb.shape[0]
    sc = r1.shape[1] // 4
    ph = [rgb, via_ids(cur, order.index("unknown")), via_ids(matp, HATCH), via_ids(zonep, -5)]
    top = np.concatenate([np.asarray(Image.fromarray(x.astype(np.uint8)).resize((sc, sc))) for x in ph], axis=1)
    top = ps.add_legend(top, [("photo", (255, 255, 255)), ("03 roles", (230, 57, 70)), ("material (3 layers)", (6, 214, 160)), ("zones", (233, 196, 106))])
    full = np.concatenate([top, r1, r2, r3], axis=0)
    Image.fromarray(full).save(os.path.join(args.out, f"{args.sku}.layers.png"))
    print("   кадр:", os.path.join(args.out, f"{args.sku}.layers.png"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("photo")
    r.add_argument("--run", required=True)
    r.add_argument("--sku", required=True)
    r.add_argument("--photo", required=True)
    r.add_argument("--out", required=True)
    r.set_defaults(fn=cmd_photo)
    l = sub.add_parser("layers")
    l.add_argument("--run", required=True)
    l.add_argument("--sku", required=True)
    l.add_argument("--out", required=True)
    l.add_argument("--no-frame", action="store_true")
    l.add_argument("--catalog", default=os.path.expanduser("~/remlab-logs/t169-4/catalog_all.json"))
    l.set_defaults(fn=cmd_layers)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
