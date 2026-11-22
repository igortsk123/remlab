#!/usr/bin/env python3
"""Цвет sheen ткани = сила класса × цвет ткани (T-20261121-169, серость тёмного бархата у дивана Денди: серый sheen давал L +12 и хрома −3).
Синтетика: растр класса + альбедо → карта sheen (линейный свет), выключатель `sheen_tint.on`, floor для очень тёмных текселей, GLB: карта цвета и геометрия байт в байт,
sheenColor-карта в GLB = сила × цвет ткани; ID товаров в коде нет. Запуск: python3 tools/assets/tests/test_sheen_tint.py   (numpy, Pillow, trimesh)"""
import copy
import io
import json
import os
import re
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.append(os.path.join(HERE, "..", "..", "scout"))
import remlab_tmp  # noqa: E402
remlab_tmp.use("test_sheen_tint")
import material_stage as MS  # noqa: E402
from PIL import Image  # noqa: E402
import trimesh  # noqa: E402

REC = MS.load_recipes()
FAIL = 0


def ok(cond, name):
    global FAIL
    print(("  ✓ " if cond else "  ✗ ") + name)
    FAIL += 0 if cond else 1


def srgb_to_lin(v):
    return np.power(np.asarray(v, dtype=float) / 255.0, 2.2)


# 1. юнит: растр одного класса + альбедо
N = 32
lab = np.ones((N, N), dtype=np.int64)
table = ["velour"]
S = REC["recipes"]["velour"]["sheen"]
dark_blue = np.zeros((N, N, 3), np.uint8)
dark_blue[...] = (20, 45, 80)
alb = Image.fromarray(dark_blue)
m = MS.bake_maps(lab, table, REC, alb)
px = m["sheen"][0, 0].astype(float)
lin = srgb_to_lin(px)
ok(lin[2] > lin[1] > lin[0], f"sheen карты окрашен цветом ткани: R<G<B (линейно {np.round(lin, 3).tolist()})")
ok(abs(lin.max() - S) < 0.02, f"сила по макс. каналу = sheen рецепта {S} (получено {lin.max():.3f}): нормировка по макс. каналу, цвет не гасит силу")
want = S * srgb_to_lin((20, 45, 80)) / srgb_to_lin((20, 45, 80)).max()
ok(np.abs(lin - want).max() < 0.02, "цвет sheen = сила × lin(цвет)/max(lin(цвет))")
grey = copy.deepcopy(REC)
grey["sheen_tint"]["on"] = False
mg = MS.bake_maps(lab, table, grey, alb)
ok((mg["sheen"][..., 0] == mg["sheen"][..., 1]).all() and (mg["sheen"][..., 1] == mg["sheen"][..., 2]).all(), "sheen_tint.on=false → серый, как раньше")
mn = MS.bake_maps(lab, table, REC, None)
ok((mn["sheen"][..., 0] == mn["sheen"][..., 2]).all(), "нет альбедо → серый (путь без карты цвета не падает)")
black = Image.fromarray(np.zeros((N, N, 3), np.uint8))
mb = MS.bake_maps(lab, table, REC, black)
ok(mb["sheen"].max() == 0, "чёрное альбедо → sheen 0 (floor: пустую темноту не раздуваем до полной силы)")
nearblack = Image.fromarray(np.full((N, N, 3), 8, np.uint8))
mnb = MS.bake_maps(lab, table, REC, nearblack)
ok(srgb_to_lin(mnb["sheen"][0, 0]).max() < S * 0.5, f"почти чёрное (8/255): sheen ослаблен floor'ом ({srgb_to_lin(mnb['sheen'][0, 0]).max():.3f} < {S * 0.5:.3f})")
big = Image.fromarray(np.repeat(np.repeat(dark_blue, 4, axis=0), 4, axis=1))
mbig = MS.bake_maps(lab, table, REC, big)
ok(mbig["sheen"].shape == m["sheen"].shape and np.abs(mbig["sheen"].astype(int) - m["sheen"].astype(int)).max() <= 2, "альбедо другого размера приводится к размеру карт")
ok(m["hasSheen"] and mg["hasSheen"], "hasSheen по классу: карта есть и с тоном, и без")

# 2. GLB: два острова, обивка велюр — карта цвета и форма байт в байт, карта sheen — цвет ткани
def box_glb(path, rgb):
    box = trimesh.creation.box(extents=(1, 0.5, 0.5))
    uv = np.column_stack([(box.vertices[:, 0] + 0.5), (box.vertices[:, 2] + 0.25) * 2.0]).clip(0, 1)
    tex = Image.fromarray(np.dstack([np.full((64, 64, 3), rgb, np.uint8), np.full((64, 64), 255, np.uint8)]))
    box.visual = trimesh.visual.TextureVisuals(uv=uv, material=trimesh.visual.material.PBRMaterial(baseColorTexture=tex))
    box.export(path)


def sheen_px(glb):
    doc, binb = MS.read_glb(glb)
    ext = doc["materials"][0]["extensions"]["KHR_materials_sheen"]
    img = doc["images"][doc["textures"][ext["sheenColorTexture"]["index"]]["source"]]
    bv = doc["bufferViews"][img["bufferView"]]
    a = np.asarray(Image.open(io.BytesIO(binb[bv.get("byteOffset", 0):bv.get("byteOffset", 0) + bv["byteLength"]])).convert("RGB"))
    return a, ext


prod = {"sid": "s", "name": "Диван Тест", "role": "диван", "params": {"Материал обивки": "Велюр"}}
with tempfile.TemporaryDirectory() as d:
    src = os.path.join(d, "sofa.glb")
    box_glb(src, (20, 45, 80))
    doc = MS.run_stage(src, os.path.join(d, "run"), "t", prod, frame=False)
    out = os.path.join(d, "run", "t", "08-material", "material.glb")
    a, ext = sheen_px(out)
    c = srgb_to_lin(a[a.shape[0] // 2, a.shape[1] // 2])
    ok(c[2] > c[1] > c[0] and abs(c.max() - S) < 0.03, f"в GLB карта sheen = сила × цвет ткани (линейно {np.round(c, 3).tolist()})")
    ok(MS.image_sha(src) == MS.image_sha(out), "карта цвета (альбедо) байт в байт")
    ok(doc["metrics"]["color_unchanged"]["value"] is True and doc["metrics"]["geometry_unchanged"]["ok"], "метрики этапа: цвет и форма не тронуты")
    ok(ext["sheenRoughnessFactor"] == REC["recipes"]["velour"]["sheenRoughness"], "sheenRoughness из рецепта")
    # выключатель: серый sheen в том же GLB
    R2 = copy.deepcopy(REC)
    R2["sheen_tint"]["on"] = False
    orig = MS.load_recipes
    MS.load_recipes = lambda *a_, **k_: R2
    try:
        MS.run_stage(src, os.path.join(d, "run"), "g", prod, frame=False)
    finally:
        MS.load_recipes = orig
    ag, _e = sheen_px(os.path.join(d, "run", "g", "08-material", "material.glb"))
    ok((ag[..., 0] == ag[..., 2]).all(), "выключатель: on=false даёт серую карту sheen")
    # перевыпуск даёт тот же результат
    MS.run_stage(src, os.path.join(d, "run"), "t2", prod, frame=False)
    ok(MS.image_sha(os.path.join(d, "run", "t2", "08-material", "material.glb")) == MS.image_sha(out) and (sheen_px(os.path.join(d, "run", "t2", "08-material", "material.glb"))[0] == a).all(), "перевыпуск: тот же результат")

# 3. рецепты и код
st = REC["sheen_tint"]
ok(isinstance(st["on"], bool) and 0 < st["floor"] <= 1, "рецепт sheen_tint: on bool, floor 0..1")
ok(REC["recipes"]["velour"]["sheen"] <= 0.4, f"sheen велюра ≤ 0,4 (замер на тёмном синем диване: L ≤ +5 при цвете ткани; сейчас {REC['recipes']['velour']['sheen']})")
txt = open(os.path.join(HERE, "..", "material_stage.py"), encoding="utf-8").read() + open(os.path.join(HERE, "..", "..", "..", "data", "flat3d", "material-recipes.json"), encoding="utf-8").read()
ok(not re.search(r"\b\d{9,}\b", txt), "ID товаров в коде и рецептах нет")
ok(MS.check() == 0, "material_stage check: рецепты целы")
print(f"test_sheen_tint: ошибок {FAIL}")
sys.exit(1 if FAIL else 0)
