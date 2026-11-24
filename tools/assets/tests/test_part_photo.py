#!/usr/bin/env python3
"""Цвет части с фото (T-20261121-169/9в ❷): источник «видимого» — этап 6 (known.png + visible.glb), ворота камеры, отступ от стыка, блики, «мало пикселей — нет данных»,
холостой прогон не меняет карту, применение меняет ТОЛЬКО остров своей части (соседняя часть и всё вне острова байт в байт), стекло в составном берёт цвет части с фото.
Сети, Blender и чужих моделей нет — синтетика. Запуск: python3 tools/assets/tests/test_part_photo.py   (numpy, scipy, trimesh, Pillow, opencv)"""
import copy
import io
import json
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.append(os.path.join(HERE, "..", "..", "scout"))
import remlab_tmp  # noqa: E402
remlab_tmp.use("test_part_photo")
import material_stage as MS  # noqa: E402
from PIL import Image  # noqa: E402
import trimesh  # noqa: E402

REC = MS.load_recipes()
PP = REC["part_photo"]
FAIL = 0
N = 128


def ok(cond, name):
    global FAIL
    print(("  ✓ " if cond else "  ✗ ") + name)
    FAIL += 0 if cond else 1


def two_part_glb(path, tex):
    """Две отдельные грани-пары (квадраты) на листе N×N: часть 0 — левая половина листа, часть 1 — правая; зазор 3 % листа между ними."""
    verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [2, 0, 0], [3, 0, 0], [2, 1, 0], [3, 1, 0]], float)
    faces = np.array([[0, 1, 2], [1, 3, 2], [4, 5, 6], [5, 7, 6]])
    uvs = np.array([[0.05, 0.05], [0.48, 0.05], [0.05, 0.95], [0.48, 0.95], [0.52, 0.05], [0.95, 0.05], [0.52, 0.95], [0.95, 0.95]])
    m = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    m.visual = trimesh.visual.TextureVisuals(uv=uvs, material=trimesh.visual.material.PBRMaterial(baseColorTexture=Image.fromarray(tex)))
    m.export(path)


def stage_files(d, iou=0.9, cam_passed=True, known=None, vis_tex=None, base_tex=None):
    """Папка этапов: 04-camera/check.json, 06-visible/{check.json, known.png, visible.glb}, 03-parts/{parts.npz, parts.json}, 07-fill/filled.glb."""
    os.makedirs(os.path.join(d, "04-camera"), exist_ok=True)
    os.makedirs(os.path.join(d, "06-visible"), exist_ok=True)
    os.makedirs(os.path.join(d, "03-parts"), exist_ok=True)
    json.dump({"passed": cam_passed}, open(os.path.join(d, "04-camera", "check.json"), "w"))
    json.dump({"passed": False, "metric": {"name": "silhouette_iou", "value": iou, "threshold": 0.85, "op": ">="}}, open(os.path.join(d, "06-visible", "check.json"), "w"))
    Image.fromarray(known).save(os.path.join(d, "06-visible", "known.png"))
    two_part_glb(os.path.join(d, "06-visible", "visible.glb"), vis_tex)
    os.makedirs(os.path.join(d, "07-fill"), exist_ok=True)
    two_part_glb(os.path.join(d, "07-fill", "filled.glb"), base_tex)
    np.savez(os.path.join(d, "03-parts", "parts.npz"), part=np.array([0, 0, 1, 1]))
    json.dump({"parts": [{"id": 0, "role": "body", "material_channel": "main", "face_share": 0.5}, {"id": 1, "role": "body", "material_channel": "main", "face_share": 0.5}]}, open(os.path.join(d, "03-parts", "parts.json"), "w"))


BRASS = (190, 150, 80)
# карта «было»: обе части чёрные (TRELLIS потерял латунь)
base_tex = np.full((N, N, 4), 255, np.uint8)
base_tex[..., :3] = (18, 18, 20)
# карта этапа 6: известные тексели левой части — латунь + блик (6 % почти белых) + рамка по краю острова другого цвета (отступ её срезает);
# правая часть: известных мало (< min_pixels) — «нет данных»
vis_tex = base_tex.copy()
known = np.zeros((N, N), np.uint8)
y0, y1, x0, x1 = int(0.05 * N), int(0.95 * N), int(0.05 * N), int(0.48 * N)
vis_tex[y0:y1, x0:x1, :3] = BRASS
vis_tex[y0:y1, x0:x0 + 2, :3] = (255, 0, 255)                         # рамка по краю: смешение с краем силуэта — отступ inset_px её отрезает
known[y0:y1, x0:x1] = 255
rng = np.random.default_rng(3)
hot = rng.random((y1 - y0, x1 - x0)) < 0.06
sub = vis_tex[y0:y1, x0:x1, :3]
sub[hot] = (250, 250, 245)                                            # блики
known[int(0.5 * N):int(0.5 * N) + 5, int(0.6 * N):int(0.6 * N) + 5] = 255      # правая часть: 25 известных текселей
vis_tex[int(0.5 * N):int(0.5 * N) + 5, int(0.6 * N):int(0.6 * N) + 5, :3] = (10, 200, 10)

with tempfile.TemporaryDirectory() as d:
    # 1. ворота
    stage_files(d, iou=0.9, cam_passed=True, known=known, vis_tex=vis_tex, base_tex=base_tex)
    sig, kn, vis = MS.photo_signal(d, PP)
    ok(sig["gate"] == "open" and kn is not None and vis is not None and kn.dtype == bool, "ворота открыты: этап 4 passed, silhouette_iou 0,9 ≥ 0,85, known.png и visible.glb есть")
    stage_files(d, iou=0.9, cam_passed=False, known=known, vis_tex=vis_tex, base_tex=base_tex)
    sig2, kn2, _v = MS.photo_signal(d, PP)
    ok(sig2["gate"] == "closed" and kn2 is None and "этап 4" in sig2["why"], "этап 4 не passed → ворота закрыты, камере не верим")
    stage_files(d, iou=0.80, cam_passed=True, known=known, vis_tex=vis_tex, base_tex=base_tex)
    sig3, kn3, _v = MS.photo_signal(d, PP)
    ok(sig3["gate"] == "closed" and kn3 is None and sig3["silhouette_iou"] == 0.80, "silhouette_iou 0,80 < 0,85 → ворота закрыты")
    stage_files(d, iou=0.9, cam_passed=True, known=known, vis_tex=vis_tex, base_tex=base_tex)
    os.remove(os.path.join(d, "06-visible", "known.png"))
    sig4, _k, _v = MS.photo_signal(d, PP)
    ok(sig4["gate"] == "closed" and "known.png" in sig4["why"], "нет known.png → ворота закрыты")

    # 2. цвет частей
    stage_files(d, iou=0.9, cam_passed=True, known=known, vis_tex=vis_tex, base_tex=base_tex)
    sig, kn, vis = MS.photo_signal(d, PP)
    mesh = trimesh.load(os.path.join(d, "07-fill", "filled.glb"), force="mesh", process=False)
    uv, faces = np.asarray(mesh.visual.uv, dtype=np.float64), np.asarray(mesh.faces)
    base = MS._base_image(*MS.read_glb(os.path.join(d, "07-fill", "filled.glb")))
    cols = MS.part_photo_colours(uv, faces, np.array([0, 0, 1, 1]), [0, 1], base, kn, vis, PP)
    a, b = cols[0], cols[1]
    ok(a["photo"] is not None and np.linalg.norm(MS.rgb_to_lab(np.array([a["photo"]], dtype=float))[0] - MS.rgb_to_lab(np.array([BRASS], dtype=float))[0]) < 3.0, f"часть 0: цвет с фото = латунь (получено {a['photo']}); блики 6 % и розовая рамка по краю не портят медиану")
    ok(a["was"] is not None and max(a["was"]) < 30 and a["dE"] > PP["dE_apply"], f"часть 0: «было» — чёрное, ΔE к фото {a['dE']} > порога {PP['dE_apply']}")
    ok(b["photo"] is None and b["photo_px"] < PP["min_pixels"] and b["dE"] is None, f"часть 1: известных текселей {b['photo_px']} < {PP['min_pixels']} → нет данных (цвет не выдумываем)")
    ok(not (a["island"] & b["island"]).any(), "острова частей не пересекаются")
    ok(a["core_px"] < a["island_px"], "ядро острова меньше острова: отступ inset_px от стыка и края")

    # 3. холостой прогон: карта цвета байт в байт, в check.json — «что было бы»
    prod = {"sid": "x", "name": "Торшер Тест", "role": "торшер", "params": {"Материал корпуса": "Металл"}}
    src = os.path.join(d, "07-fill", "filled.glb")
    run = os.path.join(d, "run")
    doc = MS.run_stage(src, run, "dry", prod, parts_dir=os.path.join(d, "03-parts"), frame=False, stages_dir=d)
    pp = doc["extra"]["part_photo"]
    out = os.path.join(run, "dry", "08-material", "material.glb")
    ok(pp["apply"] is False and pp["gate"] == "open", "холостой: apply=false, ворота открыты")
    wa = [p for p in pp["parts"] if p["part"] == 0][0]
    ok(wa["would_apply"] is True and wa["applied"] is False and wa["photo"] is not None, "холостой: часть 0 «would_apply», но applied=false")
    ok(MS.image_sha(src) == MS.image_sha(out) and doc["metrics"]["color_unchanged"]["value"] is True, "холостой: карта цвета байт в байт")

    # 4. применение: меняется только остров части 0
    R2 = copy.deepcopy(REC)
    R2["part_photo"]["apply"] = True
    orig = MS.load_recipes
    MS.load_recipes = lambda *a_, **k_: R2
    try:
        doc2 = MS.run_stage(src, run, "app", prod, parts_dir=os.path.join(d, "03-parts"), frame=False, stages_dir=d)
    finally:
        MS.load_recipes = orig
    out2 = os.path.join(run, "app", "08-material", "material.glb")
    A0 = np.asarray(MS._base_image(*MS.read_glb(src)))
    A1 = np.asarray(MS._base_image(*MS.read_glb(out2)))
    isl0, isl1 = a["island"], b["island"]
    pa = [p for p in doc2["extra"]["part_photo"]["parts"] if p["part"] == 0][0]
    ok(pa["applied"] is True, "применение: часть 0 applied")
    med = np.median(A1[isl0][:, :3], axis=0)
    ok(np.linalg.norm(MS.rgb_to_lab(np.array([med], dtype=float))[0] - MS.rgb_to_lab(np.array([BRASS], dtype=float))[0]) < 6.0, f"остров части 0 сдвинут к цвету фото (медиана {med.astype(int).tolist()})")
    ok((A1[isl1] == A0[isl1]).all(), "утечка в соседнюю часть = 0: остров части 1 байт в байт (у неё нет данных)")
    import texel_pad as TP                      # путь к tools/scout добавил material_stage (pad_base_color)
    cov = TP.coverage_from_uv(uv, faces, A0.shape[0])
    outside = ~isl0 & cov
    ok((A1[outside] == A0[outside]).all(), "вне острова части 0 покрытые тексели байт в байт (поля, чужие тексели не тронуты)")
    mt2 = doc2["metrics"]
    ok(mt2["texel_band_unfilled"]["ok"] is True and mt2["texel_band_unfilled"]["value"] == 0 and doc2["extra"]["texel_fill"]["uncovered_pct"] > 0, "check.json 08: мерка texel_band_unfilled = 0 (зелёная), отчёт texel_fill с долей непокрытых")
    gap = ~cov
    ok(gap.any() and (A1[gap] != A0[gap]).any(), "непокрытые тексели (зазор) залиты цветом соседей — это единственное, что вне острова меняется (T-20261125-70)")
    ok(doc2["metrics"]["color_unchanged"]["value"] is True and doc2["metrics"]["geometry_unchanged"]["ok"], "метрики этапа: цвет вне маски не тронут, форма не тронута")
    ok((A0[..., 3] == A1[..., 3]).all(), "альфа карты не тронута")
    doc3 = None
    R2["part_photo"]["apply"] = True
    MS.load_recipes = lambda *a_, **k_: R2
    try:
        doc3 = MS.run_stage(src, run, "app", prod, parts_dir=os.path.join(d, "03-parts"), frame=False, stages_dir=d)
    finally:
        MS.load_recipes = orig
    ok(doc3["extra"]["glb"] == doc2["extra"]["glb"] and MS.image_sha(out2) == MS.image_sha(os.path.join(run, "app", "08-material", "material.glb")), "перевыпуск даёт тот же результат")

    # 5. закрытые ворота: измерения нет, карта не тронута даже при apply
    stage_files(d, iou=0.5, cam_passed=True, known=known, vis_tex=vis_tex, base_tex=base_tex)
    R2["part_photo"]["apply"] = True
    MS.load_recipes = lambda *a_, **k_: R2
    try:
        doc4 = MS.run_stage(src, run, "shut", prod, parts_dir=os.path.join(d, "03-parts"), frame=False, stages_dir=d)
    finally:
        MS.load_recipes = orig
    ok(doc4["extra"]["part_photo"]["gate"] == "closed" and doc4["extra"]["part_photo"]["parts"] == [] and MS.image_sha(src) == MS.image_sha(os.path.join(run, "shut", "08-material", "material.glb")),
       "ворота закрыты (IoU 0,5): частей в отчёте нет, карта байт в байт даже при apply=true")

# 6. стекло в составном: фото части решает тон (reconcile), только при apply
with tempfile.TemporaryDirectory() as d:
    stage_files(d, iou=0.9, cam_passed=True, known=known, vis_tex=vis_tex, base_tex=base_tex)
    json.dump({"parts": [{"id": 0, "role": "body", "material_channel": "main", "face_share": 0.5}, {"id": 1, "role": "shade", "material_channel": "shade", "face_share": 0.5}]}, open(os.path.join(d, "03-parts", "parts.json"), "w"))
    # у «плафона» (часть 1) известные текселей много — зелёное стекло на фото
    known2, vis2 = known.copy(), vis_tex.copy()
    xx0, xx1 = int(0.53 * N), int(0.94 * N)
    known2[y0:y1, xx0:xx1] = 255
    vis2[y0:y1, xx0:xx1, :3] = (60, 170, 110)
    Image.fromarray(known2).save(os.path.join(d, "06-visible", "known.png"))
    two_part_glb(os.path.join(d, "06-visible", "visible.glb"), vis2)
    prodl = {"sid": "l", "name": "Торшер Тест", "role": "торшер", "params": {"Материал корпуса": "Металл", "Материал плафона": "Стекло", "Цвет плафона": "Синий"}}
    src = os.path.join(d, "07-fill", "filled.glb")
    run = os.path.join(d, "run")
    dd = MS.run_stage(src, run, "dry", prodl, parts_dir=os.path.join(d, "03-parts"), frame=False, stages_dir=d)
    gts = dd["extra"]["glass_tone"]
    ok(gts and gts[0]["source"] == "catalog" and gts[0]["photo"] is None, "холостой: стекло берёт каталожный тон (фото части не используется)")
    R3 = copy.deepcopy(REC)
    R3["part_photo"]["apply"] = True
    MS.load_recipes = lambda *a_, **k_: R3
    try:
        da = MS.run_stage(src, run, "app", prodl, parts_dir=os.path.join(d, "03-parts"), frame=False, stages_dir=d)
    finally:
        MS.load_recipes = orig
    gta = da["extra"]["glass_tone"][0]
    ok(gta["source"] == "photo" and gta["photo"] is not None and abs(gta["photo"][1] - 170) < 4, f"apply: тон стекла в составном = цвет части с фото ({gta['photo']}), каталог — в `catalogue`")
    ok(gta["conflict"] == "catalog:photo-conflict", "расхождение каталога («Синий») с фото (зелёное) помечено catalog:photo-conflict, а не молча проглочено")
    ok(da["metrics"]["color_unchanged"]["value"] is True, "метрика: вне островов тона цвет не тронут")

# 6б. ограничитель света: часть, чьи известные тексели — смесь тёмного и светлого (разброс L* > l_spread_max), не применяется; ровная латунь — применяется
with tempfile.TemporaryDirectory() as d:
    vis_mix = base_tex.copy()
    vis_mix[y0:y1, x0:x1, :3] = (200, 160, 90)
    half = np.arange(y0, y1) % 2 == 0                                   # чередование строк: тёмная бронза / светлая латунь
    vis_mix[y0:y1, x0:x1][half, :, :3] = (60, 45, 25)
    stage_files(d, iou=0.9, cam_passed=True, known=known, vis_tex=vis_mix, base_tex=base_tex)
    prod = {"sid": "x", "name": "Торшер Тест", "role": "торшер", "params": {"Материал корпуса": "Металл"}}
    doc = MS.run_stage(os.path.join(d, "07-fill", "filled.glb"), os.path.join(d, "run"), "mix", prod, parts_dir=os.path.join(d, "03-parts"), frame=False, stages_dir=d)
    pm = [p for p in doc["extra"]["part_photo"]["parts"] if p["part"] == 0][0]
    ok(pm["L_spread"] is not None and pm["L_spread"] > PP["l_spread_max"], f"смесь тёмного и светлого: разброс L* {pm['L_spread']} > {PP['l_spread_max']}")
    ok(pm["dE"] is not None and pm["dE"] > PP["dE_apply"] and pm["would_apply"] is False and "skipped" in pm, "ΔE больше порога, но would_apply=false и в check.json причина skipped")
    stage_files(d, iou=0.9, cam_passed=True, known=known, vis_tex=vis_tex, base_tex=base_tex)
    doc = MS.run_stage(os.path.join(d, "07-fill", "filled.glb"), os.path.join(d, "run"), "flat", prod, parts_dir=os.path.join(d, "03-parts"), frame=False, stages_dir=d)
    pf = [p for p in doc["extra"]["part_photo"]["parts"] if p["part"] == 0][0]
    ok(pf["L_spread"] is not None and pf["L_spread"] <= PP["l_spread_max"] and pf["would_apply"] is True and "skipped" not in pf, f"ровная латунь с бликами: разброс {pf['L_spread']} ≤ порога, would_apply остаётся true")

# 7. код и рецепты
ok(os.path.exists(os.path.join(HERE, "..", "material_stage.py")) and "apply" in PP and PP["apply"] is False, "по умолчанию apply=false (холостой) — включение только после просмотра директором")
txt = open(os.path.join(HERE, "..", "material_stage.py"), encoding="utf-8").read() + open(os.path.join(HERE, "..", "..", "..", "data", "flat3d", "material-recipes.json"), encoding="utf-8").read()
import re  # noqa: E402
ok(not re.search(r"\b\d{9,}\b", txt), "ID товаров в коде и рецептах нет")
ok("project_" not in txt and "render_persp" not in txt, "новой проекции фото в material_stage нет — источник «видимого» один (этап 6)")
ok(MS.check() == 0, "material_stage check: рецепты целы")
print(f"test_part_photo: ошибок {FAIL}")
sys.exit(1 if FAIL else 0)
