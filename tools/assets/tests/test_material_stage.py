#!/usr/bin/env python3
"""Этап 08 «материал» (paint-photo-fill-01, T-20261121-170/1): класс → PBR-рецепт по частям, запекание в UV общего листа, GLB с sheen/transmission.
Сети, Blender и чужих моделей нет: синтетика из trimesh (куб с UV и картой цвета). Кадр (Blender) здесь не проверяется — только `--no-frame` путь.
Запуск: python3 tools/assets/tests/test_material_stage.py   (нужны numpy, scipy, trimesh, Pillow; для проверки check.json — tools/scout/paint_stage.py или PAINT_STAGE_DIR)"""
import json
import os
import re
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.append(os.path.join(HERE, "..", "..", "scout"))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use("test_material_stage")
import material_stage as MS  # noqa: E402

R = MS.load_recipes()
FAIL = 0


def ok(cond, name):
    global FAIL
    print(("  ✓ " if cond else "  ✗ ") + name)
    FAIL += 0 if cond else 1


def _cls(cls="velour", conf=0.9, **parts):
    return {"class": cls, "stage": "params", "confidence": conf, "reason": f"Материал={cls}", "parts": {k: {"class": v, "reason": f"{k}={v}"} for k, v in parts.items()}}


def test_rules_complete():
    ok(MS.check() == 0, "рецепты: каждому классу каталога — рецепт, значения 0..1, метки Qwen ведут в известные классы")
    ok(R["recipes"]["glass"]["transmission"] == 1.0 and R["recipes"]["metal"]["metallic"] >= 0.85, "стекло прозрачно, металл — металл")
    ok(all(R["recipes"][c]["sheen"] > 0 for c in ("velour", "velvet", "fabric")) and R["recipes"]["wood_solid"]["sheen"] == 0, "ткань с ворсом, дерево без")


def test_no_ids_in_code():
    bad = []
    for f in ("material_stage.py", "material_frame_blender.py"):
        s = open(os.path.join(HERE, "..", f), encoding="utf-8").read()
        bad += re.findall(r"\b\d{5,6}[_:]\d{10,}\b", s)
    bad += re.findall(r"\b\d{5,6}[_:]\d{10,}\b", open(MS.RECIPES_PATH, encoding="utf-8").read())
    ok(not bad, "ID товаров в коде и рецептах нет")


def test_resolve():
    parts = [{"id": 0, "face_share": 0.8, "role": "part-0", "colour": {"lab_median": [60, 5, 5]}},
             {"id": 1, "face_share": 0.1, "role": "legs", "colour": {"lab_median": [30, 0, 0]}},
             {"id": 2, "face_share": 0.06, "role": "part-2", "colour": {"lab_median": [62, 6, 4]}},
             {"id": 3, "face_share": 0.04, "role": "part-3", "colour": {"lab_median": [20, 30, 30]}}]
    res = MS.resolve_parts(parts, _cls("velour", 0.9, legs="metal"), R)
    ok(res[0]["class"] == "velour" and res[0]["source"].startswith("catalog:") and res[0]["confident"], "главная часть — класс товара")
    ok(res[1]["class"] == "metal" and res[1]["source"] == "catalog:legs", "ножки по геометрии берут класс «материал ножек» из каталога")
    ok(res[2]["class"] == "velour" and res[2]["source"] == "colour≈main", "часть без метки с цветом как у главной — тот же класс")
    ok(res[3]["class"] == R["fallback_class"] and res[3]["source"] == "unsure" and not res[3]["confident"], "цвет другой, метки нет — «не уверен», запасной рецепт")
    parts2 = [dict(p) for p in parts]
    parts2[3]["vl"] = "Стеклянный плафон"
    ok(MS.resolve_parts(parts2, _cls("metal", 0.9), R)[3]["class"] == "glass", "метка Qwen3-VL важнее цвета")
    nolegs = MS.resolve_parts(parts, _cls("velour", 0.9), R)
    ok(nolegs[1]["source"] != "catalog:legs", "каталог про ножки молчит — классом ножек он не называется")
    lost = MS.resolve_parts([{"id": 0, "face_share": 1.0, "role": "part-0"}], _cls("metal", 0.9, shade="glass"), R, parts_known=False)
    ok(not lost[0]["confident"] and "частей этапа 3 нет" in lost[0]["reason"], "без частей этапа 3 и с плафоном другого материала в каталоге — «не уверен»")
    weak = MS.resolve_parts([{"id": 0, "face_share": 1.0, "role": "part-0"}], _cls("neutral", 0.2), R)
    ok(not weak[0]["confident"], "класс товара из роли (низкая уверенность) — не уверен")


def test_legs_and_colour():
    part = np.array([0] * 8 + [1] * 4 + [2] * 4)
    legs = np.array([False] * 8 + [True] * 4 + [False, False, True, False])
    parts = [{"id": 0, "face_share": 0.5, "role": "part-0"}, {"id": 1, "face_share": 0.25, "role": "part-1"}, {"id": 2, "face_share": 0.25, "role": "part-2"}]
    MS.mark_legs(parts, part, legs, 0.6)
    ok(parts[1]["role"] == "legs" and parts[2]["role"] == "part-2" and parts[0]["role"] == "part-0", "часть этапа 3 на ножках по геометрии (≥60 %) — legs; главная и «чуть задела» — нет")
    lab = MS.rgb_to_lab(np.array([[255, 255, 255], [0, 0, 0], [255, 0, 0]], dtype=np.uint8))
    ok(abs(lab[0, 0] - 100) < 0.5 and abs(lab[1, 0]) < 0.5 and lab[2, 1] > 70, "перевод цвета в Lab: белый 100, чёрный 0, красный — в «красную» сторону")


def test_bake():
    uv = np.array([[0.0, 0.0], [0.5, 0.0], [0.0, 1.0], [0.5, 1.0], [1.0, 0.0], [1.0, 1.0], [0.5, 0.0], [0.5, 1.0]])
    faces = np.array([[0, 1, 2], [1, 3, 2], [6, 4, 5], [6, 5, 7]])         # левая половина листа — грани 0,1; правая — 2,3
    table = MS.class_table(R, ["wood_solid", "glass"])
    lab = MS.rasterize_labels(uv, faces, np.array([1, 1, 2, 2]), 64)
    ok(lab[32, 8] == 1 and lab[32, 56] == 2 and (lab > 0).all(), "растр: левая половина — класс 1, правая — класс 2, пустых нет (поля залиты)")
    uv2 = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 0.5]])                  # треугольник у НИЗА листа (V вверх): строки 32..63 нижней половины
    lab2 = MS.rasterize_labels(uv2, np.array([[0, 1, 2]]), np.array([1]), 64)
    ok(lab2[60, 4] == 1, "V вверх: v=0 — нижняя строка растра")
    m = MS.bake_maps(lab, table, R)
    g, b = m["mr"][32, 8, 1], m["mr"][32, 8, 2]
    ok(abs(g / 255 - R["recipes"]["wood_solid"]["roughness"]) < 0.01 and b == 0, "карта: шероховатость дерева в G, металла нет")
    ok(m["trans"][32, 56, 0] == 255 and m["trans"][32, 8, 0] == 0 and m["hasTransmission"] and not m["hasSheen"], "стекло прозрачно, дерево нет; sheen нет")
    tf = MS.class_table(R, ["velour"])
    mf = MS.bake_maps(np.ones((8, 8), np.uint8), tf, R)
    ok(mf["hasSheen"] and 0 < mf["sheenRoughness"] <= 1 and not mf["hasTransmission"], "ткань: sheen есть, прозрачности нет")
    try:
        MS.class_table(R, ["no_such"])
        ok(False, "неизвестный класс отвергнут")
    except KeyError:
        ok(True, "неизвестный класс отвергнут")


def _tiny_glb(path):
    import trimesh
    from PIL import Image
    box = trimesh.creation.box(extents=(1, 0.5, 0.5))
    rng = np.random.default_rng(1)
    tex = Image.fromarray(rng.integers(0, 255, (32, 32, 4), dtype=np.uint8))
    uv = np.column_stack([(box.vertices[:, 0] + 0.5), (box.vertices[:, 2] + 0.25) * 2.0]).clip(0, 1)
    box.visual = trimesh.visual.TextureVisuals(uv=uv, material=trimesh.visual.material.PBRMaterial(baseColorTexture=tex))
    box.export(path)
    return box


def test_patch_glb():
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "a.glb"), os.path.join(d, "b.glb")
        _tiny_glb(src)
        table = MS.class_table(R, ["velour", "glass"])
        lab = np.ones((16, 16), np.uint8)
        lab[:, 8:] = 2
        maps = MS.bake_maps(lab, table, R)
        info = MS.patch_glb(src, dst, maps)
        doc, _ = MS.read_glb(dst)
        m0 = doc["materials"][0]
        ok(set(info["extensions"]) == {"KHR_materials_sheen", "KHR_materials_transmission"} and "KHR_materials_sheen" in m0["extensions"], "GLB: sheen и transmission записаны расширениями")
        ok("metallicRoughnessTexture" in m0["pbrMetallicRoughness"], "GLB: карта metallicRoughness есть")
        ok(MS.image_sha(src) == MS.image_sha(dst) and MS.image_sha(src) is not None, "карта цвета — байт в байт как была")
        ok(MS.geometry_sha(src) == MS.geometry_sha(dst), "форма и развёртка — байт в байт как были")
        import trimesh
        back = trimesh.load(dst, force="mesh", process=False)
        ok(len(back.faces) == 12, "результат открывается и читается")
        # повторный проход по уже запечённому (перевыпуск этапа): снова валидный GLB
        dst2 = os.path.join(d, "c.glb")
        MS.patch_glb(dst, dst2, maps)
        ok(MS.geometry_sha(dst2) == MS.geometry_sha(src), "перевыпуск: второй проход не портит геометрию")


def test_stage_end_to_end():
    try:
        MS._paint_stage()
    except SystemExit:
        print("  – paint_stage.py не найден (ветка paint-fill не влита): сквозная проверка check.json пропущена")
        return
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "m.glb")
        _tiny_glb(src)
        product = {"sid": "x", "name": "Кресло Тест Велюр", "role": "кресло", "params": {"Материал обивки": "велюр", "Материал ножек": "Металл"}}
        doc = MS.run_stage(src, os.path.join(d, "run"), "sku-1", product, frame=False)
        ok(doc["stage"] == "08-material" and doc["metrics"]["recipe_share"]["value"] == 1.0, "этап 08: все грани получили рецепт")
        ok(doc["metrics"]["color_unchanged"]["ok"] and doc["metrics"]["geometry_unchanged"]["ok"], "check.json: цвет и геометрия не тронуты")
        ok(os.path.exists(os.path.join(d, "run", "sku-1", "08-material", "material.glb")), "material.glb записан")
        ok(isinstance(doc["extra"]["parts"], list) and doc["extra"]["parts"][0]["class"] == "velour", "check.json: класс по частям с источником")
        again = MS.run_stage(src, os.path.join(d, "run"), "sku-1", product, frame=False)
        ok(again["extra"]["parts"] == doc["extra"]["parts"] and again["extra"]["glb"] == doc["extra"]["glb"], "перевыпуск даёт тот же результат")


if __name__ == "__main__":
    for t in (test_rules_complete, test_no_ids_in_code, test_resolve, test_legs_and_colour, test_bake, test_patch_glb, test_stage_end_to_end):
        print(t.__name__)
        t()
    print(f"material_stage tests: ошибок {FAIL}")
    sys.exit(1 if FAIL else 0)
