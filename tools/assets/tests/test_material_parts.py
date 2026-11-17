#!/usr/bin/env python3
"""Маска частей мебели для рендера (render-materials-01, шаг 3, T-20261117-14/3): ножки отделяются геометрией, не уверены — слоя нет.
Сети нет, чужих мешей нет: синтетика из trimesh (тело на 4 ножках, сплошной ящик, тело на ножках с рейками, сплошной ящик на 1 ножке).
Запуск: python3 tools/assets/tests/test_material_parts.py   (нужны numpy, scipy, trimesh)"""
import json
import os
import sys

import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import material_parts as MP  # noqa: E402

RULES = MP.load_rules()


def _box(sx, sy, sz, cx, cy, cz):
    m = trimesh.creation.box(extents=(sx, sy, sz))
    m.apply_translation((cx, cy, cz))
    return m


def _legged(leg_h=0.25, rails=False):
    """Тело 2×0,5×1 на 4 ножках 0,06×leg_h×0,06 по углам; рейки (rails) — тонкие бруски по периметру на 70% высоты ножек."""
    parts = [_box(2.0, 0.5, 1.0, 0, leg_h + 0.25, 0)]
    for sx in (-0.9, 0.9):
        for sz in (-0.4, 0.4):
            parts.append(_box(0.06, leg_h, 0.06, sx, leg_h / 2, sz))
    if rails:
        y = leg_h * 0.7
        for sz in (-0.4, 0.4):
            parts.append(_box(1.8, 0.03, 0.03, 0, y, sz))
        for sx in (-0.9, 0.9):
            parts.append(_box(0.03, 0.03, 0.8, sx, y, 0))
    return trimesh.util.concatenate(parts)


def test_rules_complete():
    for k in ("appliesToFamilies", "grid", "legs", "confidence", "reasons"):
        assert k in RULES, k
    assert RULES["confidence"]["apply"] > RULES["confidence"]["splitBase"]


def test_legs_split_with_cut_between_legs_and_body():
    mesh = _legged()
    rec = MP.judge(MP.analyze(mesh, RULES), RULES, None)
    assert rec["status"] == "split", rec
    assert rec["islands"] == 4
    height = mesh.extents[1]
    # ножки 0..0,25 из 1,0 (с учётом тела 0,5): разрез между верхом ножек и низом тела
    assert 0.08 < rec["cutFrac"] <= 0.25 / height + 0.03, rec["cutFrac"]
    legs = MP.legs_face_mask(mesh, rec)
    cy = mesh.triangles_center[:, 1] - mesh.bounds[0][1]
    assert legs.any() and not legs.all()
    assert cy[legs].max() <= 0.25 + 0.03          # в маске только то, что ниже тела
    assert cy[~legs].min() >= 0.0
    assert (cy[cy > 0.30] > 0).all() and not legs[cy > 0.30].any()   # тело не в ножках
    assert rec["apply"] is True and rec["confidence"] >= RULES["confidence"]["apply"]
    assert "ножек" in rec["reason"]


def test_solid_box_is_whole():
    mesh = _box(2.0, 0.6, 1.0, 0, 0.3, 0)
    rec = MP.judge(MP.analyze(mesh, RULES), RULES, None)
    assert rec["status"] == "whole", rec
    assert not MP.legs_face_mask(mesh, rec).any()
    assert MP.upholstery_face_mask(mesh, rec).all()
    assert rec["apply"] is True


def test_product_names_legs_but_geometry_whole_lowers_confidence_and_says_so():
    """Товар называет материал ножек, а под цоколем их не отделить: уверенность ниже, в причине — это сказано (слой на всю поверхность)."""
    mesh = _box(2.0, 0.6, 1.0, 0, 0.3, 0)
    plain = MP.judge(MP.analyze(mesh, RULES), RULES, None)
    rec = MP.judge(MP.analyze(mesh, RULES), RULES, True)
    assert rec["status"] == "whole"
    assert rec["confidence"] < plain["confidence"]
    assert "ножек" in rec["reason"] and "не отделить" in rec["reason"]


def test_ground_shadow_plate_is_not_the_object():
    """Плоский лист-тень у пола (запечён в часть мешей) не делает предмет «цоколем»: ножки над ним находятся."""
    mesh = trimesh.util.concatenate([_legged(), _box(2.6, 0.004, 1.6, 0, 0.002, 0)])
    rec = MP.judge(MP.analyze(mesh, RULES), RULES, None)
    assert rec["status"] == "split", rec
    assert rec["metrics"].get("plateLayers", 0) >= 1


def test_headboard_panel_on_floor_is_not_a_plinth():
    """Изголовье стоит на полу во всю ширину: тонкая панель, не цоколь — ножки рамы находятся, а низ панели ножкой не красится (нейтраль)."""
    mesh = trimesh.util.concatenate([_legged(), _box(2.0, 0.9, 0.05, 0, 0.45, -0.75)])
    rec = MP.judge(MP.analyze(mesh, RULES), RULES, None)
    assert rec["status"] == "split", rec
    assert rec["islands"] == 4 and rec["metrics"].get("panels") == 1
    legs, neu = MP.legs_face_mask(mesh, rec), MP.neutral_face_mask(mesh, rec)
    c = mesh.triangles_center
    panel_low = (c[:, 2] < -0.7) & (c[:, 1] < 0.1)
    assert panel_low.any() and not legs[panel_low].any() and neu[panel_low].all()
    assert legs[(np.abs(c[:, 0]) > 0.85) & (c[:, 1] < 0.2) & (c[:, 2] > -0.5)].any()


def test_thin_posts_are_neutral_at_any_height_but_volume_is_not():
    """Стойки спинки (сечение ≈ 4 см) выше разреза нейтральны, объёмное сиденье и спинка (≈ 12 см) — обивка: толщина по меш-стенкам, не по высоте."""
    parts = [_legged(), _box(0.8, 0.12, 0.8, 0, 0.9, 0)]                  # сиденье 12 см толщиной над ножками
    for sx in (-0.35, 0.35):                                                 # две стойки 4×4 см от сиденья до спинки
        parts.append(_box(0.04, 0.5, 0.04, sx, 1.21, -0.35))
    parts.append(_box(0.8, 0.14, 0.1, 0, 1.5, -0.35))                      # спинка-панель 14×10 см
    mesh = trimesh.util.concatenate(parts)
    rec = MP.judge(MP.analyze(mesh, RULES), RULES, None)
    thin, info = MP.thin_face_mask(mesh, RULES, longest_cm=110.0)
    c = mesh.triangles_center
    post = (np.abs(np.abs(c[:, 0]) - 0.35) < 0.03) & (c[:, 1] > 1.0) & (c[:, 1] < 1.4) & (np.abs(mesh.face_normals[:, 1]) < 0.5)   # боковые грани стойки
    seat = (np.abs(c[:, 0]) < 0.3) & (c[:, 1] > 0.8) & (c[:, 1] < 0.98) & (np.abs(c[:, 2]) < 0.3)
    assert post.any() and thin[post].mean() > 0.8, thin[post].mean()
    assert seat.any() and thin[seat].mean() < 0.2, thin[seat].mean()
    neu = MP.neutral_face_mask(mesh, rec, thin)
    assert neu[post].all() or neu[post].mean() > 0.8
    assert info["thinCm"] == RULES["thin"]["thinCm"] and info["thinAreaPct"] > 0


def test_thin_threshold_scales_with_real_size():
    """Один и тот же меш: на «большом» предмете сечение в см больше, поэтому не тонкое; на «малом» — тонкое (размер из каталога/роли)."""
    mesh = trimesh.util.concatenate([_legged(), _box(0.04, 0.5, 0.04, 0.3, 1.0, 0)])
    small, _ = MP.thin_face_mask(mesh, RULES, longest_cm=60.0)
    big, _ = MP.thin_face_mask(mesh, RULES, longest_cm=400.0)
    assert small.sum() >= big.sum()
    assert MP._real_longest_cm(RULES, "стул", None, {})[1] == "role"
    assert MP._real_longest_cm(RULES, "стул", "x", {"x": (50, 50, 90)}) == (90.0, "catalog")


def test_star_base_is_not_a_plinth():
    """Крестовина у пола с узкой опорой над ней — не цоколь: не «вся поверхность обивка», слой не кладём."""
    parts = [_box(1.0, 0.4, 1.0, 0, 0.75, 0), _box(0.12, 0.5, 0.12, 0, 0.3, 0)]
    parts += [_box(1.0, 0.03, 0.08, 0, 0.015, 0), _box(0.08, 0.03, 1.0, 0, 0.015, 0)]
    rec = MP.judge(MP.analyze(trimesh.util.concatenate(parts), RULES), RULES, None)
    assert rec["status"] == "unsure" and rec["apply"] is False, rec


def test_product_legs_agree_raises_confidence_absent_is_neutral():
    mesh = _legged()
    a = MP.judge(MP.analyze(mesh, RULES), RULES, None)["confidence"]
    b = MP.judge(MP.analyze(mesh, RULES), RULES, True)["confidence"]
    assert b > a


def test_rails_give_neutral_band_not_fabric():
    """Рейки между ножками и телом: дерево или обивка — не различить; полоса нейтральная, слой на неё не кладём."""
    mesh = _legged(leg_h=0.40, rails=True)
    rec = MP.judge(MP.analyze(mesh, RULES), RULES, None)
    assert rec["status"] == "split", rec
    neu = MP.neutral_face_mask(mesh, rec)
    legs = MP.legs_face_mask(mesh, rec)
    up = MP.upholstery_face_mask(mesh, rec)
    assert not (legs & neu).any() and not (up & (legs | neu)).any()
    assert (legs | neu | up).all()
    assert rec["bandTopFrac"] >= rec["cutFrac"]


def test_single_pedestal_is_unsure():
    mesh = trimesh.util.concatenate([_box(1.0, 0.4, 1.0, 0, 0.7, 0), _box(0.1, 0.5, 0.1, 0, 0.25, 0)])
    rec = MP.judge(MP.analyze(mesh, RULES), RULES, None)
    assert rec["status"] == "unsure" and rec["apply"] is False
    assert not MP.legs_face_mask(mesh, rec).any()


def test_committed_result_is_built_by_these_rules():
    assert MP.check() == 0


def test_non_soft_classes_are_skipped_in_data():
    doc = json.load(open(MP.ASSIGN_PATH, encoding="utf-8"))
    cls = json.load(open(MP.CLASS_ASSIGN_PATH, encoding="utf-8"))["meshes"]
    classes = json.load(open(MP.CLASSES_PATH, encoding="utf-8"))
    for mid, rec in doc["meshes"].items():
        fam = MP._family_of(cls[mid].get("class"), classes)
        assert (rec["status"] == "skip") == (fam not in RULES["appliesToFamilies"]), (mid, fam, rec["status"])
        if rec["apply"]:
            assert rec["status"] in ("split", "whole") and rec["confidence"] >= RULES["confidence"]["apply"]


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:  # noqa: BLE001
                fails += 1
                print("FAIL", name, repr(e)[:300])
    sys.exit(1 if fails else 0)
