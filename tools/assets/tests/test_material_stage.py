#!/usr/bin/env python3
"""Этап 08 «материал» (paint-photo-fill-01, T-20261121-170/1; форма без частей и наследование граней — /4): класс → PBR-рецепт по частям, запекание в UV общего листа, GLB с sheen/transmission.
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
    inf = MS.resolve_parts(parts, {**_cls("fabric", 0.9), "parts": {"legs": {"class": "wood_solid", "reason": "Материал каркаса=Дерево", "inferred": True}}}, R)
    ok(inf[1]["class"] == "wood_solid" and inf[1]["source"] == "catalog:legs-inferred" and R["confidence"]["legs_catalog_inferred"] < R["confidence"]["legs_catalog"] and inf[1]["confident"], "ножки по каркасу (своего поля нет): класс дерева, источник legs-inferred, уверенность ниже явной, но уверен")
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


def _lamp_mesh():
    """Синтетический торшер (Y вверх): плоская подставка, тонкая стойка, шарик-плафон наверху."""
    import trimesh
    rot = trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0])
    base = trimesh.creation.cylinder(radius=0.2, height=0.01, sections=48)
    base.apply_transform(rot)
    base.apply_translation([0, 0.005, 0])
    pole = trimesh.creation.cylinder(radius=0.008, height=1.2, sections=12)
    pole.apply_transform(rot)
    pole.apply_translation([0, 0.61, 0])
    shade = trimesh.creation.icosphere(subdivisions=3, radius=0.05)
    shade.apply_translation([0, 1.3, 0])
    parts = []
    for part in (base, pole, shade):                                   # как в TRELLIS — густая сетка: у стойки тоже сотни граней, а не 24
        v, f = trimesh.remesh.subdivide_to_size(part.vertices, part.faces, max_edge=0.015)
        parts.append(trimesh.Trimesh(v, f, process=False))
    return trimesh.util.concatenate(parts)


def test_shapes_without_stage3():
    import part_shapes as psh
    mc, mp = MS._siblings()
    m = _lamp_mesh()
    kind, up, rep = psh.face_shapes(m.vertices, m.faces, R["geometry"])
    cen = m.vertices[m.faces].mean(axis=1)
    pole = (np.abs(cen[:, 0]) < 0.02) & (cen[:, 1] > 0.1) & (cen[:, 1] < 1.1)
    ok((kind[pole] == psh.LINEAR).mean() > 0.9, "тонкая стойка — linear (≥90% граней)")
    ok((kind[cen[:, 1] > 1.25] == psh.BLOB).mean() > 0.9, "шарик наверху — blob")
    part, parts, _ = MS.geometry_shape_parts(m, mp, {}, R)
    roles = {p["role"] for p in parts}
    ok({"shape:linear", "shape:blob-top"} <= roles, f"части по форме: стойка и плафон наверху найдены ({sorted(roles)})")
    cls = _cls("metal", 0.9, shade="glass")
    res = MS.resolve_parts(parts, cls, R, parts_known=True)
    by = {p["role"]: res[p["id"]] for p in parts}
    ok(by["shape:blob-top"]["class"] == "glass" and by["shape:blob-top"]["confident"], "плафон наверху — стекло из каталога, уверен")
    ok(by["shape:linear"]["class"] == "metal" and by["shape:linear"]["confident"], "стойка — металл, уверен")
    big = max(parts, key=lambda p: p["face_share"])
    ok(res[big["id"]]["class"] == "metal" and res[big["id"]]["confident"], "главная часть — корпус из каталога")
    wood = MS.resolve_parts(parts, _cls("wood_solid", 0.9), R, parts_known=True)
    lin = next(p for p in parts if p["role"] == "shape:linear")
    ok(wood[lin["id"]]["class"] == "wood_solid" and wood[lin["id"]]["class"] != "metal", "в каталоге нет металла — стойка берёт материал корпуса, а не металл")
    extra = [dict(p) for p in parts]
    extra[0] = dict(extra[0], face_share=0.9)                              # главная — не стойка: тогда стойка идёт веткой формы
    mm = MS.resolve_parts(extra, _cls("wood_solid", 0.9), R, parts_known=True)
    li = next(p for p in extra if p["role"] == "shape:linear")
    ok(extra[0]["role"] != "shape:linear" and mm[li["id"]]["source"] == "geometry:body", "ветка формы: нет металла в каталоге — источник «geometry:body», причина названа")
    _, _, rep2 = psh.face_shapes(m.vertices * 10.0, m.faces, R["geometry"])
    ok(rep2["share"] == rep["share"], "масштаб модели ничего не меняет: пороги — доли габарита")


def test_top_zone_shade():
    import trimesh
    import part_shapes as psh  # noqa: F401
    mc, mp = MS._siblings()
    m = _lamp_mesh()
    big = trimesh.creation.icosphere(subdivisions=4, radius=0.13)        # шар крупнее радиуса окрестности: кусок поверхности на вид плоский
    big.apply_translation([0, 1.45, 0])
    v, f = trimesh.remesh.subdivide_to_size(big.vertices, big.faces, max_edge=0.02)
    m = trimesh.util.concatenate([m, trimesh.Trimesh(v, f, process=False)])
    part, parts, _ = MS.geometry_shape_parts(m, mp, {}, R)
    cen = m.vertices[m.faces].mean(axis=1)
    top = next((p for p in parts if p["role"] == "shape:blob-top"), None)
    ok(top is not None and (part[cen[:, 1] > 1.35] == top["id"]).mean() > 0.95, "крупный плафон наверху — ≥95% граней в одной части «верх» (не пятнами)")
    for shade_cls in ("glass", "fabric"):
        res = MS.resolve_parts(parts, _cls("metal", 0.9, shade=shade_cls), R, parts_known=True)
        by = {p["role"]: res[p["id"]] for p in parts}
        ok(by["shape:blob-top"]["class"] == shade_cls and by["shape:blob-top"]["confident"], f"верх берёт класс плафона из каталога: {shade_cls}")
    res = MS.resolve_parts(parts, _cls("metal", 0.9), R, parts_known=True)
    by = {p["role"]: res[p["id"]] for p in parts}
    ok(by["shape:blob-top"]["class"] == "metal", "плафона в каталоге нет — верх остаётся материалом корпуса, стекла не придумываем")


def test_stand_junction_is_metal():
    import trimesh
    mc, mp = MS._siblings()
    rot = trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0])
    base = _lamp_mesh()
    cap = trimesh.creation.cylinder(radius=0.011, height=0.05, sections=12)    # цоколь на стойке под плафоном: чуть толще стойки (1,4 её радиуса)
    cap.apply_transform(rot)
    cap.apply_translation([0, 1.225, 0])
    v, f = trimesh.remesh.subdivide_to_size(cap.vertices, cap.faces, max_edge=0.015)
    big = trimesh.creation.icosphere(subdivisions=4, radius=0.13)
    big.apply_translation([0.0, 1.5, 0.0])
    v2, f2 = trimesh.remesh.subdivide_to_size(big.vertices, big.faces, max_edge=0.02)
    m = trimesh.util.concatenate([base, trimesh.Trimesh(v, f, process=False), trimesh.Trimesh(v2, f2, process=False)])
    part, parts, _ = MS.geometry_shape_parts(m, mp, {}, R)
    cen = m.vertices[m.faces].mean(axis=1)
    near = (np.hypot(cen[:, 0], cen[:, 2]) > 0.0095) & (np.hypot(cen[:, 0], cen[:, 2]) <= 0.012) & (cen[:, 1] > 1.2) & (cen[:, 1] < 1.25)   # боковые грани цоколя
    role_of = {p["id"]: p["role"] for p in parts}
    share_top = float(np.mean([role_of[i] == "shape:blob-top" for i in part[near]])) if near.any() else 1.0
    ok(near.sum() > 10 and share_top < 0.05, f"стык стойки с цоколем (у оси, верхняя зона) — не плафон (в плафоне {share_top:.0%} из {int(near.sum())} граней)")
    res = MS.resolve_parts(parts, _cls("metal", 0.9, shade="glass"), R, parts_known=True)
    by = {p["role"]: res[p["id"]] for p in parts}
    ok(by["shape:blob-top"]["class"] == "glass" and by["shape:linear"]["class"] == "metal", "плафон — стекло, стойка с цоколем — металл")
    far = (np.hypot(cen[:, 0], cen[:, 2]) > 0.05) & (cen[:, 1] > 1.4)
    ok(float(np.mean([role_of[i] == "shape:blob-top" for i in part[far]])) > 0.95, "плафон вдали от оси остался плафоном")
    g2 = dict(R["geometry"]); g2.pop("stand_k")
    R2 = dict(R); R2["geometry"] = g2
    part2, parts2, _ = MS.geometry_shape_parts(m, mp, {}, R2)
    role2 = {p["id"]: p["role"] for p in parts2}
    ok(float(np.mean([role2[i] == "shape:blob-top" for i in part2[near]])) > 0.3, "без stand_k правило выключено (тест различает: цоколь был бы плафоном)")
    t = trimesh.creation.box(extents=[0.9, 0.04, 0.5]); t.apply_translation([0, 0.72, 0])
    legs4 = []
    for sx in (-0.4, 0.4):
        for sz in (-0.2, 0.2):
            L = trimesh.creation.cylinder(radius=0.015, height=0.7, sections=10); L.apply_transform(rot); L.apply_translation([sx, 0.35, sz]); legs4.append(L)
    tab = trimesh.util.concatenate(legs4 + [t])
    v3, f3 = trimesh.remesh.subdivide_to_size(tab.vertices, tab.faces, max_edge=0.02)
    tab = trimesh.Trimesh(v3, f3, process=False)
    part3, parts3, _ = MS.geometry_shape_parts(tab, mp, {}, R)
    c3 = tab.vertices[tab.faces].mean(axis=1)
    ok(MS.stand_near_axis(tab, np.where((np.abs(c3[:, 1] - 0.35) < 0.3), 1, 3), np.clip(c3[:, 1] / 0.74, 0, 1), R["geometry"], 1).sum() == 0, "четыре ножки по углам — не «одна стойка»: правило молчит (столешница не станет стойкой)")


def test_unsure_parts_report():
    import trimesh
    m = trimesh.creation.box(extents=[1.0, 1.0, 1.0])
    m = trimesh.Trimesh(*trimesh.remesh.subdivide_to_size(m.vertices, m.faces, max_edge=0.1), process=False)
    cen = m.vertices[m.faces].mean(axis=1)
    part = np.where(cen[:, 1] > 0.2, 1, 0).astype(np.int64)                   # верхняя полоса куба — часть 1, остальное — главная 0
    col = lambda L: {"lab_median": [L, 0.0, 0.0]}   # noqa: E731
    parts = [{"id": 0, "face_share": float((part == 0).mean()), "role": "part-0", "vl": None, "colour": col(70.0)},
             {"id": 1, "face_share": float((part == 1).mean()), "role": "part-1", "vl": None, "colour": col(30.0)}]
    res = MS.resolve_parts(parts, _cls("fabric", 0.9), R, parts_known=True)
    rep_in = [dict(r, id=i, role=parts[i]["role"], face_share=parts[i]["face_share"]) for i, r in sorted(res.items())]
    out = MS.unsure_parts_report(m, part, rep_in, parts, R)
    ok(len(out) == 1 and out[0]["id"] == 1, "в отчёт идут только неуверенные части (главная и «цвет как у главной» — нет)")
    d = out[0]
    ok(abs(d["de_main"] - 40.0) < 0.2 and d["main_id"] == 0, f"ΔE к главной части посчитан: {d['de_main']}")
    ok(d["where"]["label"].startswith("верх") and 0.6 < d["where"]["up"] < 1.0, f"верхняя полоса — «верх» по центроиду ({d['where']})")
    ok(0.1 < d["area_share"] < 0.6 and d["face_share"] > 0.1, "доля площади и граней названа")
    ok(d["lab"] == [30.0, 0.0, 0.0] and "ΔE" in d["reason"], "цвет Lab и причина — в отчёте")


def test_soft_body_inherits_upholstery():
    col = lambda L: {"lab_median": [L, 0.0, 0.0]}   # noqa: E731
    parts = [{"id": 0, "face_share": 0.5, "role": "part-0", "vl": None, "colour": col(70.0)},
             {"id": 1, "face_share": 0.25, "role": "part-1", "vl": None, "colour": col(25.0)},      # подушка тёмного цвета: ΔE 45 к главной
             {"id": 2, "face_share": 0.2, "role": "part-2", "vl": None, "colour": None},            # цвета нет вообще
             {"id": 3, "face_share": 0.05, "role": "legs", "vl": None, "colour": col(40.0)}]
    for grp in ("seating", "bed"):
        cls = dict(_cls("velour", 0.9, legs="metal"), group=grp)
        res = MS.resolve_parts(parts, cls, R, parts_known=True)
        ok(res[1]["class"] == "velour" and res[1]["confident"] and res[1]["source"] == "body-soft", f"{grp}: тёмная часть корпуса — та же обивка, уверен (ΔE не решает)")
        ok(res[2]["class"] == "velour" and res[2]["confident"], f"{grp}: часть без цвета — тоже обивка")
        ok(res[3]["class"] == "metal" and res[3]["source"] == "catalog:legs", f"{grp}: ножки — отдельный класс из каталога, обивку не наследуют")
    nograph = dict(_cls("ldsp", 0.9), group="case")
    res = MS.resolve_parts(parts, nograph, R, parts_known=True)
    ok(res[1]["source"] == "unsure" and not res[1]["confident"], "шкаф/комод: правило мягкой мебели не действует — отличающийся цвет остаётся «не уверен»")
    res = MS.resolve_parts(parts, _cls("velour", 0.9), R, parts_known=True)
    ok(res[1]["source"] == "unsure", "группа не названа — прежняя политика (цвет решает)")
    near = [dict(p) for p in parts]; near[1] = dict(near[1], colour=col(66.0))
    res = MS.resolve_parts(near, dict(_cls("velour", 0.9), group="seating"), R, parts_known=True)
    ok(res[1]["source"] == "body-soft", "у мягкой мебели и близкий цвет — обивка по правилу корпуса (цвет не участвует)")
    forms = [{"id": 0, "face_share": 0.6, "role": "part-0", "vl": None, "colour": col(70.0)}, {"id": 1, "face_share": 0.4, "role": "shape:blob-top", "vl": None, "colour": col(10.0)}]
    res = MS.resolve_parts(forms, dict(_cls("velour", 0.9, shade="glass"), group="seating"), R, parts_known=True)
    ok(res[1]["class"] == "glass", "часть формы (плафон из каталога) правилом корпуса не перекрывается")


def test_stage3_roles():
    col = lambda L: {"lab_median": [L, 0.0, 0.0]}   # noqa: E731
    def prt(i, share, role, ch, L):
        return {"id": i, "face_share": share, "role": role, "material_channel": ch, "vl": None, "colour": col(L)}
    parts = [prt(0, 0.4, "body", "main", 70.0), prt(1, 0.2, "top", "main", 20.0), prt(2, 0.15, "facade", "main", 90.0), prt(3, 0.1, "legs", "legs", 5.0),
             prt(4, 0.06, "frame", "frame", 5.0), prt(5, 0.04, "handles", "handles", 5.0), prt(6, 0.03, "shade", "shade", 5.0), prt(7, 0.02, "unknown", None, 5.0)]
    cls = dict(_cls("ldsp", 0.9, legs="metal", frame="steel", handles="metal", shade="glass"), group="case")
    cls["parts"]["frame"]["class"] = "metal"
    res = MS.resolve_parts(parts, cls, R, parts_known=True)
    for i in (1, 2):
        ok(res[i]["class"] == "ldsp" and res[i]["source"] == "role:main" and res[i]["confident"], f"роль {parts[i]['role']} — основной класс товара, цвет (ΔE) не решает")
    ok(res[0]["source"].startswith("catalog:"), "главная часть — прежней веткой главной")
    ok(res[3]["class"] == "metal" and res[3]["source"] == "catalog:legs", "ножки — канал каталога (прежняя ветка)")
    ok(res[4]["class"] == "metal" and res[4]["source"] == "role:frame", "каркас — канал «frame» каталога")
    ok(res[5]["class"] == "metal" and res[5]["source"] == "role:handles", "ручки — канал «handles» каталога")
    ok(res[6]["class"] == "glass" and res[6]["source"] == "role:shade", "плафон — канал «shade» каталога")
    ok(res[7]["source"] == "unsure" and not res[7]["confident"], "unknown — прежняя политика: чёрный кусок с другим цветом — «не уверен»")
    bare = dict(_cls("ldsp", 0.9), group="case")
    res = MS.resolve_parts(parts, bare, R, parts_known=True)
    ok(res[4]["source"] == "unsure" and res[5]["source"] == "unsure" and res[6]["source"] == "unsure", "канала нет в каталоге — роль каналом не становится: прежняя политика, стекло/металл не придумываем")
    glass = [dict(p) for p in parts]; glass[7] = dict(glass[7], role="glass_mirror", material_channel=None)
    res = MS.resolve_parts(glass, cls, R, parts_known=True)
    ok(res[7]["class"] != "glass", "роль glass_mirror без канала стеклом не становится")
    # у стола: top — каталожный материал столешницы (класс товара)
    tab = dict(_cls("glass", 0.9, legs="metal"), group="table")
    pt = [prt(0, 0.7, "top", "main", 60.0), prt(1, 0.3, "legs", "legs", 10.0)]
    res = MS.resolve_parts(pt, tab, R, parts_known=True)
    ok(res[0]["class"] == "glass" and res[1]["class"] == "metal", "стол: столешница — класс по каталогу (стекло), ножки — металл")
    pm = [prt(0, 0.6, "body", "main", 70.0), prt(1, 0.3, "unknown", None, 20.0), prt(2, 0.1, "body", "main", 10.0)]
    legs = np.array([False] * 10)
    import copy
    pm2 = copy.deepcopy(pm)
    for q in pm2:
        q["legs_share"] = 0
    part_arr = np.array([0] * 6 + [1] * 3 + [2], dtype=np.int64)
    leg_mask = np.array([False] * 6 + [True] * 4)
    MS.mark_legs(pm2, part_arr, leg_mask, 0.6)
    ok(pm2[2]["role"] == "body" and pm2[1]["role"] == "legs", "роль этапа 3 (body с каналом) геометрией ножек не перекрывается; unknown — добирается геометрией")


def test_top_zone_bigger_than_body():
    parts = [{"id": 0, "face_share": 0.2, "role": "shape:blob", "vl": None, "colour": None},
             {"id": 1, "face_share": 0.5, "role": "shape:blob-top", "vl": None, "colour": None},
             {"id": 2, "face_share": 0.3, "role": "shape:linear", "vl": None, "colour": None}]
    res = MS.resolve_parts(parts, _cls("metal", 0.9, shade="fabric"), R, parts_known=True)
    ok(res[1]["class"] == "fabric" and res[1]["source"] == "geometry:top", "верх — самая большая часть, но с плафоном в каталоге он плафон (ткань), а не «главная часть» металл")
    ok(res[2]["class"] == "metal" and res[2]["source"].startswith("catalog:"), "главной становится крупнейшая из остальных частей (здесь стойка 30%)")
    res = MS.resolve_parts(parts, _cls("metal", 0.9), R, parts_known=True)
    ok(res[1]["class"] == "metal", "плафона в каталоге нет — верх по-прежнему главная часть")


def test_inherit_unseen():
    import trimesh
    m = trimesh.creation.icosphere(subdivisions=3, radius=1.0)
    cen = m.vertices[m.faces].mean(axis=1)
    part = np.where(cen[:, 0] < 0, 0, 1).astype(np.int64)
    part[(cen[:, 0] > 0.2) & (cen[:, 1] > 0.4)] = -1
    part[(cen[:, 0] < -0.5) & (cen[:, 1] < -0.4)] = 99          # номер, которого нет в parts.json — тоже «не видна»
    new, mask = MS.inherit_unseen(m, part, [0, 1])
    ok(mask.sum() == ((part == -1) | (part == 99)).sum() and set(np.unique(new)) == {0, 1}, "грань без части (−1 и неизвестный номер) получила часть соседа")
    ok((new[mask & (cen[:, 0] > 0)] == 1).all() and (new[mask & (cen[:, 0] < 0)] == 0).all(), "берёт ближайшую: правая сторона — часть 1, левая — часть 0")
    same, mask0 = MS.inherit_unseen(m, np.zeros(len(part), dtype=np.int64), [0])
    ok(not mask0.any() and (same == 0).all(), "всё видно — ничего не меняется")
    try:
        MS.inherit_unseen(m, np.full(len(part), -1), [0])
        ok(False, "ни одной грани с частью — отказ")
    except ValueError:
        ok(True, "ни одной грани с частью — отказ, наследовать не от кого")


def test_stage_geometry_and_inherited():
    try:
        MS._paint_stage()
    except SystemExit:
        print("  – paint_stage.py не найден: сквозная проверка пропущена")
        return
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "lamp.glb")
        _tiny_glb(src)
        product = {"sid": "x", "name": "Светильник напольный", "role": "торшер", "params": {"Материал корпуса": "Металл", "Материал плафона": "Стекло"}}
        doc = MS.run_stage(src, os.path.join(d, "run"), "sku-g", product, frame=False)
        m = doc["metrics"]
        ok(doc["extra"]["parts_source"] == "geometry" and "inherited_share" in m and m["inherited_share"]["value"] == 0.0, "без этапа 3: части по форме, inherited_share в check.json (0 — все грани разложены)")
        ok(m["recipe_share"]["value"] == 1.0, "без этапа 3: у всех граней рецепт")
        ok(isinstance(doc["extra"].get("catalog_parts_not_located"), list), "check.json называет материалы каталога, которых форма не нашла (уверенность не равна «проверено»)")
        ok(isinstance(doc["extra"].get("shape"), dict) and "share" in doc["extra"]["shape"], "check.json хранит разбивку формы")


if __name__ == "__main__":
    for t in (test_rules_complete, test_no_ids_in_code, test_resolve, test_legs_and_colour, test_bake, test_patch_glb, test_stage_end_to_end, test_shapes_without_stage3, test_top_zone_shade, test_stand_junction_is_metal, test_unsure_parts_report, test_soft_body_inherits_upholstery, test_stage3_roles, test_top_zone_bigger_than_body, test_inherit_unseen, test_stage_geometry_and_inherited):
        print(t.__name__)
        t()
    print(f"material_stage tests: ошибок {FAIL}")
    sys.exit(1 if FAIL else 0)
