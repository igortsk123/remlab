#!/usr/bin/env python3
"""Срез плиты-подложки у черновиков TRELLIS (T-20261121-170/2): синтетика из trimesh, сети и чужих моделей нет.
Запуск: python3 tools/scout/tests/test_plate_strip.py   (нужны numpy, scipy, trimesh, Pillow)"""
import os
import re
import sys

import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import plate_strip as PS  # noqa: E402

R = PS.load_rules()
FAIL = 0


def ok(cond, name):
    global FAIL
    print(("  ✓ " if cond else "  ✗ ") + name)
    FAIL += 0 if cond else 1


def _box(sx, sy, sz, cx, cy, cz):
    m = trimesh.creation.box(extents=(sx, sy, sz))
    m.apply_translation((cx, cy, cz))
    return m


def _product():
    """Стол на 4 ножках и тонкая столешница-лист (отдельный кусок, высоко): всё это — товар, срезать нельзя."""
    parts = [_box(0.6, 0.01, 0.4, 0, 0.3, 0)]                                  # столешница: плоская, но не на дне и меньше плиты
    for sx in (-0.25, 0.25):
        for sz in (-0.15, 0.15):
            parts.append(_box(0.04, 0.3, 0.04, sx, 0.15, sz))
    return trimesh.util.concatenate(parts)


def _plates(n_crumbs=40, seed=3):
    """3 листа 1×0,002×1 на дне (y от −0,004 до 0) и мелкие плоские обломки на том же уровне."""
    rng = np.random.default_rng(seed)
    parts = [_box(1.0, 0.002, 1.0, 0, -0.001, 0), _box(0.95, 0.001, 0.9, 0, -0.002, 0), _box(1.0, 0.001, 1.0, 0, -0.003, 0)]
    for _ in range(n_crumbs):
        x, z = rng.uniform(-0.48, 0.48, 2)
        parts.append(_box(0.03, 0.001, 0.03, x, -0.0015, z))
    return trimesh.util.concatenate(parts)


def _with_plate():
    return trimesh.util.concatenate([_product(), _plates()])


def test_strip():
    m = _with_plate()
    prod = _product()
    out, rep = PS.strip_mesh(m, R)
    ok(rep["plate_found"] and rep["plates"] == 3 and rep["crumbs"] == 40 and not rep["refused"], "3 листа и 40 обломков найдены")
    ok(len(out.faces) == len(prod.faces), "осталось ровно столько граней, сколько в товаре")
    ok(np.allclose(np.sort(out.extents), np.sort(prod.extents), atol=1e-6), "габарит после = габарит товара (плита не в счёте)")
    ok(rep["extents_before"][0] > 0.99 and max(rep["extents_after"]) < 0.7, "габарит до ≈ 1 м, после — товар")
    ok(rep["up_axis"] == 1 and rep["footprint_ratio"] < 0.4, "вертикаль Y найдена сама; след товара вдвое–втрое меньше следа плиты")
    ok(0.0 <= rep["gap_to_plate_frac"] <= R["max_gap_to_plate_frac"], "товар стоит на плите (зазор в допуске)")
    ok(out.faces.max() < len(out.vertices), "лишние вершины выброшены, индексы целы")
    top = out.vertices[:, 1].max()
    ok(abs(top - prod.vertices[:, 1].max()) < 1e-9, "столешница (плоская, но высоко) осталась")
    mt = PS.plate_metrics(rep, R)
    ok(mt["remaining_face_share"]["value"] > 0.05 and mt["gap_to_plate_frac"]["op"] == "<=" and mt["plate_found"]["value"] is True, "мерки check.json на месте")


def test_no_plate_untouched():
    p = _product()
    out, rep = PS.strip_mesh(p, R)
    ok(out is p and not rep["plate_found"] and not rep["refused"], "чистый черновик: плиты нет, модель та же")
    ok(PS.plate_metrics(rep, R) == {"plate_found": {"value": False}}, "без плиты этап не краснеет (одна справочная мерка)")


def test_rug_is_not_plate():
    rug = _box(1.0, 0.02, 1.0, 0, 0.01, 0)                                      # толще порога — не лист
    out, rep = PS.strip_mesh(rug, R)
    ok(out is rug and not rep["plate_found"], "ковёр толщиной 2 % L — не плита")
    flat = trimesh.util.concatenate([_box(1.0, 0.002, 1.0, 0, 0, 0)])           # сама плоская вещь, кроме неё ничего нет
    out, rep = PS.strip_mesh(flat, R)
    ok(out is flat and rep["refused"], "модель целиком плоская: срез отказан с причиной, ничего не удалено")
    ok(PS.plate_metrics(rep, R)["refused"]["op"] == "==", "отказ виден в мерках (красный этап)")


def test_product_through_plate_and_canopy():
    lamp = trimesh.util.concatenate([_product(), _plates(), _box(0.2, 0.2, 0.2, 0, 0.05, 0)])        # основание торшера пронизывает лист: от −0,05 до 0,15
    out, rep = PS.strip_mesh(lamp, R)
    ok(rep["plate_found"] and rep["gap_to_plate_frac"] < 0 and rep["above_share"] >= R["min_above_share"], "основание ушло под лист — плита всё равно найдена, зазор отрицательный")
    ok(out.vertices[:, 1].min() < -0.04, "основание под листом сохранено")
    canopy = trimesh.util.concatenate([_box(1.0, 0.006, 1.0, 0, 1.0, 0), _box(0.6, 0.5, 0.4, 0, 0.5, 0), _box(0.05, 1.0, 0.05, 0.45, 0.5, 0.45)])
    out, rep = PS.strip_mesh(canopy, R)
    ok(out is canopy and not rep["plate_found"] and "flat_max" in rep, "лист сверху с товаром ПОД ним (балдахин) — не плита")
    table = trimesh.util.concatenate([_box(1.0, 0.008, 0.9, 0, 0.7, 0)] + [_box(0.05, 0.7, 0.05, sx, 0.35, sz) for sx in (-0.45, 0.45) for sz in (-0.4, 0.4)])
    out, rep = PS.strip_mesh(table, R)
    ok(out is table and not rep["plate_found"], "столешница-лист на ножках — не плита")


def test_pedestal_base_is_not_plate():
    """Стол-тюльпан: тонкий диск основания 0,65 м внизу, шире него — столешница. Диск не плита (товар не меньше листа) — режем нельзя."""
    rot = trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0])             # у trimesh ось цилиндра — Z; нам нужна Y
    base = trimesh.creation.cylinder(radius=0.325, height=0.008, sections=48)
    base.apply_transform(rot)
    base.apply_translation((0, 0.004, 0))
    stem = _box(0.08, 0.9, 0.08, 0, 0.45, 0)
    top = trimesh.creation.cylinder(radius=0.39, height=0.02, sections=48)
    top.apply_transform(rot)
    top.apply_translation((0, 0.99, 0))
    tulip = trimesh.util.concatenate([base, stem, top])
    out, rep = PS.strip_mesh(tulip, R)
    ok(out is tulip and not rep["plate_found"] and "основание" in rep["flat_max"].get("not_plate", ""), "тюльпан: диск основания не плита, модель не тронута")
    prof = np.array([[0, 0], [0.325, 0], [0.325, 0.008], [0.04, 0.012], [0.04, 0.97], [0.39, 0.98], [0.39, 1.0], [0, 1.0]])
    one = trimesh.creation.revolve(prof, sections=48)                                # цельный стол: диск основания — часть общей поверхности
    one.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
    one = trimesh.Trimesh(one.vertices, one.faces, process=False)
    out, rep = PS.strip_mesh(trimesh.util.concatenate([one, _plates(n_crumbs=10)]), R)
    ok(rep["plate_found"] and rep["plates"] == 3 and len(out.faces) == len(one.faces), "цельный тюльпан с настоящей плитой под ним: плита срезана, основание цело")


def test_numpy_components_equal_scipy():
    m = _with_plate()
    a = PS._components(m.faces, len(m.vertices), use_scipy=True)
    b = PS._components(m.faces, len(m.vertices), use_scipy=False)
    same = len(np.unique(a)) == len(np.unique(b)) and len(np.unique(np.c_[a, b], axis=0)) == len(np.unique(a))
    ok(same, "куски без scipy (как в Blender) совпадают с scipy: те же разбиение и число кусков")
    rm_a, rep_a = PS.analyze(m.vertices, m.faces, R)
    ok(rep_a["plate_found"] and int(rm_a.sum()) > 0, "analyze отдаёт маску граней на удаление (для вызова из Blender)")


def test_axis_auto():
    m = _with_plate()
    zup = trimesh.Trimesh(vertices=m.vertices[:, [0, 2, 1]], faces=m.faces, process=False)   # вертикаль — Z
    out, rep = PS.strip_mesh(zup, R)
    ok(rep["up_axis"] == 2 and rep["plates"] == 3 and len(out.faces) == len(_product().faces), "модель с вертикалью Z: ось и плиты найдены сами")
    fixed = dict(R, up_axis=1)
    _rm, rep2 = PS.analyze(zup.vertices, zup.faces, fixed)
    ok(not rep2["plate_found"], "ось задана неверно вручную — плиты не нашли (правило подчиняется данным)")


def test_texture_kept():
    from PIL import Image
    base = _with_plate()
    uv = np.column_stack([(base.vertices[:, 0] + 0.5).clip(0, 1), (base.vertices[:, 2] + 0.5).clip(0, 1)])
    tex = Image.fromarray(np.random.default_rng(0).integers(0, 255, (16, 16, 4), dtype=np.uint8))
    base.visual = trimesh.visual.TextureVisuals(uv=uv, material=trimesh.visual.material.PBRMaterial(baseColorTexture=tex))
    out, rep = PS.strip_mesh(base, R)
    ok(rep["plate_found"] and len(out.visual.uv) == len(out.vertices), "UV остались по числу вершин")
    ok(getattr(out.visual.material, "baseColorTexture", None) is not None, "текстура цвета не потеряна")
    keep = np.unique(np.asarray(out.faces))
    ok(len(keep) == len(out.vertices), "нет вершин без граней")


def test_rules_and_no_ids():
    ok(PS.check() == 0, "правила целы")
    src = open(os.path.join(HERE, "..", "plate_strip.py"), encoding="utf-8").read() + open(PS.RULES_PATH, encoding="utf-8").read()
    ok(not re.findall(r"\b\d{5,6}[_:]\d{10,}\b", src), "ID товаров в коде и правилах нет")


if __name__ == "__main__":
    for t in (test_strip, test_no_plate_untouched, test_rug_is_not_plate, test_product_through_plate_and_canopy, test_pedestal_base_is_not_plate, test_numpy_components_equal_scipy, test_axis_auto, test_texture_kept, test_rules_and_no_ids):
        print(t.__name__)
        t()
    print(f"plate_strip tests: ошибок {FAIL}")
    sys.exit(1 if FAIL else 0)
