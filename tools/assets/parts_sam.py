#!/usr/bin/env python3
"""Этап 3 «части меша» целиком на одном товаре (paint-photo-fill-01, T-20261120-169): кадры облёта → SAM2 → голосование на грани → сверка с геометрией → `03-parts/`.

Блоки: `parts_orbit_blender.py` (кадры и видимость граней, Blender) → здесь SAM2 (HF transformers `Sam2Model`, Apache, без дообучения, CPU) → `parts_vote.py` (чистая математика).
Имя/класс части (Qwen3-VL) — ОТДЕЛЬНЫЙ шаг с потолком; здесь заглушка: роль `legs` из геометрии, остальное `part-N`, поле `vl` пустое.
Запуск (pakardev, venv scout; тяжёлое — под heavy-slot):
    python3 tools/assets/parts_sam.py run --glb <model.glb> --orbit <папка облёта> --run <папка прогона> --sku <имя> [--limit N]
Выход `<run>/<sku>/03-parts/`: parts.npz (part, agree по граням), parts.json (части: доля граней, роль, заглушка имени), check.json (общий формат `tools/scout/paint_stage.py`),
frame.png — кадры облёта с раскраской по частям (контрольный кадр этапа)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "scout"))
import parts_refine as pr  # noqa: E402
import parts_vote as pv  # noqa: E402

PALETTE = [(230, 57, 70), (69, 123, 157), (42, 157, 143), (233, 196, 106), (131, 56, 236), (244, 162, 97), (6, 214, 160), (255, 0, 110), (90, 90, 90), (0, 180, 216), (200, 120, 200), (120, 200, 60)]


def load_sam(name: str):
    import torch
    from transformers import Sam2Model, Sam2Processor

    torch.set_num_threads(int(os.environ.get("SAM_THREADS", "4")))
    proc = Sam2Processor.from_pretrained(name)
    model = Sam2Model.from_pretrained(name).eval()
    return model, proc


def sam_masks(model, proc, rgb: np.ndarray, obj_mask: np.ndarray, rules: dict) -> list[np.ndarray]:
    """Области SAM2 на кадре: сетка точек внутри предмета → маски → отбор по качеству → слияние почти одинаковых. Список булевых HxW."""
    import torch
    from PIL import Image

    s = rules["sam"]
    h, w = obj_mask.shape
    ys, xs = np.nonzero(obj_mask)
    if len(ys) == 0:
        return []
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    g = s["grid"]
    gx = np.linspace(x0, x1, g + 2)[1:-1]
    gy = np.linspace(y0, y1, g + 2)[1:-1]
    pts = [(float(x), float(y)) for y in gy for x in gx if obj_mask[int(y), int(x)]]
    if not pts:
        return []
    img = Image.fromarray(rgb)
    out, scores = [], []
    batch = 16
    with torch.inference_mode():
        first = proc(images=img, input_points=[[[list(pts[0])]]], input_labels=[[[1]]], return_tensors="pt")
        emb = model.get_image_embeddings(first["pixel_values"])
        for i in range(0, len(pts), batch):
            chunk = pts[i:i + batch]
            inp = proc(images=img, input_points=[[[list(p)] for p in chunk]], input_labels=[[[1] for _ in chunk]], return_tensors="pt")
            res = model(image_embeddings=emb, input_points=inp["input_points"], input_labels=inp["input_labels"], multimask_output=True)
            masks = proc.post_process_masks(res.pred_masks, inp["original_sizes"], binarize=True)[0]   # [точки, 3, H, W]
            iou = res.iou_scores[0]                                                                    # [точки, 3]
            for k in range(masks.shape[0]):
                for j in range(masks.shape[1]):
                    if float(iou[k, j]) >= s["iou_min"]:
                        out.append(masks[k, j].numpy().astype(bool))
                        scores.append(float(iou[k, j]))
    order = np.argsort(-np.array(scores))
    keep: list[np.ndarray] = []
    for i in order:
        m = out[i]
        if m.sum() < 25:
            continue
        dup = False
        for kk in keep:
            inter = (m & kk).sum()
            if inter / max(1, (m | kk).sum()) >= s["dedupe_iou"]:
                dup = True
                break
        if not dup:
            keep.append(m)
        if len(keep) >= s["max_masks_per_view"]:
            break
    return keep


def input_colour(mesh) -> tuple[bool, float | None]:
    """Есть ли у входа цветная текстура и каков разброс яркости по её непустым пикселям (0–255)."""
    tex = getattr(getattr(mesh.visual, "material", None), "baseColorTexture", None)
    if tex is None:
        return False, None
    a = np.array(tex.convert("RGBA"))
    px = a[a[..., 3] > 127][:, :3].astype(np.float32)
    if len(px) == 0:
        return True, 0.0
    return True, float(px.mean(axis=1).std())


def load_view(orbit: str, name: str):
    from PIL import Image

    rgba = np.array(Image.open(os.path.join(orbit, f"rgba_{name}.png")).convert("RGBA"))
    mask = rgba[..., 3] > 127
    a = (rgba[..., 3:4] / 255.0)
    rgb = (rgba[..., :3] * a + 128 * (1 - a)).astype(np.uint8)          # серый фон, предмет как есть
    z = np.load(os.path.join(orbit, f"vis_{name}.npz"))
    return rgb, mask, z["u"], z["v"], z["vis"], z["cos"]


def paint_frame(orbit: str, name: str, part: np.ndarray, u: np.ndarray, v: np.ndarray, vis: np.ndarray, rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Кадр, раскрашенный по частям: цвета граней разносятся на пиксели ближайшего центра видимой грани (по сетке пикселей), картинка предмета — подложка."""
    from scipy import ndimage

    h, w = mask.shape
    lab = np.full((h, w), -1, dtype=np.int32)
    iu, iv = u[vis].astype(int), v[vis].astype(int)
    ok = (iu >= 0) & (iu < w) & (iv >= 0) & (iv < h)
    lab[iv[ok], iu[ok]] = part[vis][ok]
    idx = ndimage.distance_transform_edt(lab < 0, return_distances=False, return_indices=True)
    full = lab[idx[0], idx[1]]
    col = np.zeros((h, w, 3), dtype=np.uint8)
    for p in np.unique(full[full >= 0]):
        col[full == p] = PALETTE[int(p) % len(PALETTE)]
    out = (0.35 * rgb + 0.65 * col).astype(np.uint8)
    out[~mask] = 255
    return out


def run(args) -> int:
    import trimesh
    from PIL import Image

    import material_parts as mp
    import paint_stage as ps

    rules = pv.load_rules()
    t0 = time.time()
    sdir = ps.stage_dir(args.run, args.sku, "03-parts")
    os.makedirs(sdir, exist_ok=True)
    info = json.load(open(os.path.join(args.orbit, "orbit.json"), encoding="utf-8"))
    mesh = mp.load_mesh(args.glb)
    nf = len(mesh.faces)
    if info["faces"] != nf:
        ps.write_check(sdir, "03-parts", args.sku, passed=False, reason=f"число граней Blender {info['faces']} ≠ меша {nf}", seconds=time.time() - t0)
        return 1
    has_tex, tex_std = input_colour(mesh)
    ok_in, why_in = pv.colour_verdict(has_tex, tex_std, rules)
    if not ok_in:                                                        # без цвета SAM2 не запускаем: отказ с причиной, дальше товар не идёт
        ps.write_check(sdir, "03-parts", args.sku, passed=False, reason=why_in, seconds=time.time() - t0,
                       metrics={"input_texture_std": {"value": tex_std, "threshold": rules["check"]["input_min_texture_std"], "op": ">=", "ok": False}},
                       has_texture=has_tex)
        print(json.dumps({"ok": False, "reason": why_in}, ensure_ascii=False))
        return 2
    model, proc = load_sam(rules["sam"]["model"])
    names = [v["name"] for v in info["views"]][: args.limit or None]
    regions, viss, weights, frames = [], [], [], []
    per_view_regions = []
    for name in names:
        rgb, mask, u, v, vis, cos = load_view(args.orbit, name)
        masks = sam_masks(model, proc, rgb, mask, rules)
        lm = pv.label_map(masks, mask, rules)
        reg = pv.view_face_regions(lm, u, v, vis)
        regions.append(reg)
        viss.append(vis)
        weights.append(cos * vis)
        frames.append((name, rgb, mask, u, v, vis))
        per_view_regions.append(len(np.unique(lm[lm >= 0])))
        print(f"кадр {name}: масок {len(masks)}, областей {per_view_regions[-1]}, {time.time() - t0:.0f} с", flush=True)
    res = pv.run_vote(regions, viss, weights, mesh.vertices, mesh.faces, rules)
    part = res["part"]
    lab_face = None
    try:                                                              # цвет граней — для слияния пёстрых кусков по цвету
        import parts_colour as pcol
        tex0 = np.array(mesh.visual.material.baseColorTexture.convert("RGB"))
        lab_face = pcol.rgb_to_lab(pcol.face_rgb(np.array(mesh.visual.uv), mesh.faces, tex0))
    except Exception:
        lab_face = None
    refine_rep = {}
    try:
        part, refine_rep = pr.refine(part, mesh.vertices, mesh.faces, res["adj"], lab_face, rules, res["agree"], res["seen_any"])
        res["agree"] = pv.final_agreement(res["acc"], res["raw_part"], part)
    except Exception as e:                                           # доводка не удалась — остаются части голосования, причина в check.json
        refine_rep = {"error": str(e)[:200]}
    q = pv.quality(part, res["agree"], res["seen_any"], rules, refine_rep.get("linear_in_blob_part_share"))
    # геометрия ножек
    rec = geom = None
    try:
        grules = mp.load_rules()
        rec = mp.analyze(mesh, grules)
        legs = mp.legs_face_mask(mesh, rec)
        geom = pv.geometry_overlap(part, legs, rules)
        geom["status"] = rec.get("status")
    except Exception as e:  # геометрия не ответила — части остаются, сверки нет
        geom = {"error": str(e)[:200]}
    colours, mixed = {}, []
    try:                                                              # цвет частей по текстуре входа — сверка «в части два разных цвета»; сбой не роняет этап
        import parts_colour as pcol
        tex = np.array(mesh.visual.material.baseColorTexture.convert("RGB"))
        colours = pcol.part_colours(part, pcol.face_rgb(np.array(mesh.visual.uv), mesh.faces, tex))
        mixed = pcol.mixed_parts(colours, rules)
    except Exception as e:
        colours = {"error": str(e)[:160]}
    ids, cnt = np.unique(part[part >= 0], return_counts=True)
    parts = []
    for p, c in sorted(zip(ids, cnt), key=lambda t: -t[1]):
        role = (geom or {}).get("roles", {}).get(int(p), {}).get("role") if geom else None
        parts.append({"id": int(p), "face_share": round(float(c) / nf, 4), "role": role or f"part-{int(p)}", "vl": None, "colour": colours.get(int(p))})
    np.savez_compressed(os.path.join(sdir, "parts.npz"), part=part.astype(np.int16), agree=res["agree"].astype(np.float16))
    json.dump({"faces": nf, "n_views": len(names), "regions_per_view": per_view_regions, "n_parts_raw": res["n_parts_raw"], "parts": parts, "geometry": geom, "refine": refine_rep},
              open(os.path.join(sdir, "parts.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tiles = [paint_frame(args.orbit, n, part, u, v, vis, rgb, mask) for (n, rgb, mask, u, v, vis) in (frames[0:8:2] if len(frames) >= 8 else frames[:4])]
    Image.fromarray(np.concatenate(tiles, axis=1)).save(os.path.join(sdir, "frame.png"))
    metrics = {
        "faces_with_part_share": {"value": q["faces_with_part_share"], "threshold": rules["check"]["min_faces_with_part"], "op": ">=", "ok": q["faces_with_part_share"] >= rules["check"]["min_faces_with_part"]},
        "n_parts": {"value": q["n_parts"], "threshold": f"{rules['check']['min_parts']}–{rules['check']['max_parts']}", "op": "in", "ok": rules["check"]["min_parts"] <= q["n_parts"] <= rules["check"]["max_parts"]},
        "frames_agreement_mean": {"value": q["frames_agreement_mean"], "threshold": rules["check"]["min_agreement"], "op": ">=", "ok": q["frames_agreement_mean"] >= rules["check"]["min_agreement"]},
    }
    if "linear_in_blob_part_share" in q:
        metrics["linear_in_blob_part_share"] = {"value": q["linear_in_blob_part_share"], "threshold": rules["check"]["max_linear_in_blob"], "op": "<=",
                                                "ok": q["linear_in_blob_part_share"] <= rules["check"]["max_linear_in_blob"]}
    ps.write_check(sdir, "03-parts", args.sku, passed=q["ok"], metric={"name": "n_parts", **metrics["n_parts"]}, reason=q["reason"], metrics=metrics, seconds=time.time() - t0,
                   outputs=["parts.npz", "parts.json"], frame="frame.png", faces_seen_by_views_share=q["faces_seen_by_views_share"], part_face_shares=q["part_face_shares"], geometry=geom, mixed_colour_parts=mixed, refine=refine_rep)
    print(json.dumps({"ok": q["ok"], "reason": q["reason"], "n_parts": q["n_parts"], "agree": q["frames_agreement_mean"], "with_part": q["faces_with_part_share"], "geometry": geom and {k: v for k, v in geom.items() if k != "roles"}}, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run")
    r.add_argument("--glb", required=True)
    r.add_argument("--orbit", required=True)
    r.add_argument("--run", required=True)
    r.add_argument("--sku", required=True)
    r.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
