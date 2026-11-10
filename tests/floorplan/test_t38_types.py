"""T-20261110-38: план застройщика РФ («Этажи») — комнаты без названий, только площади; серые перегородки при чёрных наружных.

Тип комнаты — от VLM в том же вопросе подписей (`labels4`: по мебели/сантехнике, владелец TG 896), имя из типа
(`bench.load_vlm`), вид результата (`pipeline.vlm_kind`), сверка с напечатанной площадью (`pipeline.area_label_off`), балкон
с пониженной площадью — вне опоры масштаба (`pipeline.outdoor_share`), высота потолков из объявления (`listing.ceiling_height`,
`pipeline.apply_ceiling`), серые перегородки (`fpcore.grey_partitions`). Лёгкие: без сети, без стенда."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import bench  # noqa: E402
import fpcore as fc  # noqa: E402
import listing  # noqa: E402
import pipeline as pl  # noqa: E402

ETAGI = 'Площадь\n68,8 м2\nВысота потолков\n3,1 м\n'


def test_room_meta_types_areas_and_reduced():
    m = bench.room_meta({'type': 'Kitchen-Living', 'type_src': 'furniture', 'area_m2': 20.8})
    assert m == {'vtype': 'kitchen_living', 'vtype_src': 'furniture', 'area_m2': 20.8, 'area_reduced_m2': None}
    m = bench.room_meta({'type': 'balcony', 'type_src': 'furniture', 'area_m2': 2.7, 'area_reduced_m2': 0.8})
    assert m['vtype'] == 'balcony' and m['area_reduced_m2'] == 0.8
    assert bench.room_meta({'area_reduced_m2': 3.0, 'area_m2': 2.0})['area_reduced_m2'] is None   # «пониженная» не меньше
    assert bench.room_meta({'type': 'spaceship', 'area_m2': 5})['vtype'] == 'other'                # площадь есть — комната
    assert bench.room_meta({'type': 'spaceship', 'type_src': 'magic'}) == {'vtype': None, 'vtype_src': None, 'area_m2': None,
                                                                           'area_reduced_m2': None}
    assert bench.room_meta({'area_m2': True})['area_m2'] is None and bench.room_meta({'area_m2': 9000})['area_m2'] is None


def test_load_vlm_labels4_names_unlabelled_rooms_from_type(tmp_path, monkeypatch):
    rooms = [{'name': '', 'pt': [500, 500], 'type': 'kitchen_living', 'type_src': 'furniture', 'area_m2': 20.8},
             {'name': '', 'pt': [100, 100], 'type': 'hall', 'type_src': 'position', 'area_m2': 4.3},
             {'name': 'Кабинет', 'pt': [200, 200], 'type': 'study', 'type_src': 'name'},
             {'name': '', 'pt': [300, 300]}]                                   # ни названия, ни типа — не подпись
    (tmp_path / 'raw-T-labels4.txt').write_text(json.dumps({'rooms': rooms, 'areas': [68.8], 'titles': []}))
    monkeypatch.setenv('FP_LABELS', 'labels4')
    v = bench.load_vlm('T', str(tmp_path), (1000, 1000))
    by = {q['name']: q for q in v['labels']}
    assert sorted(by) == ['Hall', 'Kitchen-living room', 'Кабинет']
    assert by['Kitchen-living room']['name_src'] == 'type' and by['Kitchen-living room']['area_m2'] == 20.8
    assert by['Hall']['vtype_src'] == 'position' and 'name_src' not in by['Кабинет']


def test_load_vlm_old_kinds_unchanged(tmp_path, monkeypatch):
    """Старый кэш (labels3) — те же поля, что до T-38: без типа и площади."""
    (tmp_path / 'raw-T-labels3.txt').write_text(json.dumps({'rooms': [{'name': 'Kitchen', 'pt': [1, 1], 'dims_m': [3, 4]},
                                                                      {'name': '', 'pt': [2, 2]}]}))
    monkeypatch.setenv('FP_LABELS', 'labels3')
    v = bench.load_vlm('T', str(tmp_path), (1000, 1000))
    assert [sorted(q) for q in v['labels']] == [['dims', 'name', 'note', 'pt', 'unsure']] * 2


@pytest.mark.parametrize('g, kind, want', [
    ({'vtype': 'kitchen_living', 'vtype_src': 'furniture', 'name_src': 'type'}, 'other', ('living', ['kind_by_furniture'])),
    ({'vtype': 'hall', 'vtype_src': 'position', 'name_src': 'type'}, 'other', ('hall', ['kind_by_position'])),
    ({'vtype': 'wc', 'name_src': 'type'}, 'other', ('bathroom', ['kind_by_vlm'])),
    ({'vtype': 'wardrobe', 'vtype_src': 'furniture', 'name_src': 'type'}, 'other', ('other', ['kind_by_furniture'])),
    ({'vtype': 'bathroom'}, 'other', ('bathroom', ['kind_by_vlm'])),                 # «Санузел» правилами не узнан
    ({'vtype': 'bedroom'}, 'living', ('living', [])),                                # узнанное по названию — не трогаем
    ({'vtype': 'balcony', 'area_reduced_m2': 0.8, 'name_src': 'type'}, 'other', ('other', ['outdoor', 'area_reduced',
                                                                                         'kind_by_vlm'])),
    ({}, 'bedroom', ('bedroom', [])),
])
def test_vlm_kind(g, kind, want):
    assert pl.vlm_kind(kind, g) == want


def test_area_label_off_and_ok():
    G = {'A': {'area_m2': 5.1}, 'B': {'area_m2': 4.0}, 'C': {}}
    assert pl.area_label_off(['A'], G, 5.0) == 'area_label_ok'
    assert pl.area_label_off(['A'], G, 2.0) == 'area_label_off'
    assert pl.area_label_off(['A', 'B'], G, 8.6) == 'area_label_ok'              # слитые — по сумме
    assert pl.area_label_off(['A', 'C'], G, 2.0) is None                         # у одной из слитых подписи нет
    assert pl.area_label_off(['A'], G, 5.55) == 'area_label_ok'                  # 0,45 м² — в допуске 0,5


def test_outdoor_share_balcony_reduced_area_out_of_scale():
    rows = [{'vtype': 'kitchen_living', 'area_m2': 20.8}, {'vtype': 'bedroom', 'area_m2': 14.9}, {'vtype': 'bedroom', 'area_m2': 12.8},
            {'vtype': 'bathroom', 'area_m2': 5.1}, {'vtype': 'bathroom', 'area_m2': 4.0}, {'vtype': 'hall', 'area_m2': 4.3},
            {'vtype': 'corridor', 'area_m2': 3.8}, {'vtype': 'wardrobe', 'area_m2': 2.3},
            {'vtype': 'balcony', 'area_m2': 2.7, 'area_reduced_m2': 0.8}]
    area = listing.total_area(ETAGI)
    assert area['m2'] == 68.8 and area['conv'] == 'rooms'
    a, fl = pl.outdoor_share({'rooms': rows}, area)
    assert a['m2'] == 68.0 and fl == ['area_less_outdoor']
    off = dict(area, m2=75.0)                                                     # сумма не сходится — не трогаем
    assert pl.outdoor_share({'rooms': rows}, off) == (off, [])
    no_balc = [r for r in rows if r['vtype'] != 'balcony']
    assert pl.outdoor_share({'rooms': no_balc}, dict(area, m2=68.0)) == (dict(area, m2=68.0), [])
    assert pl.outdoor_share({'rooms': rows}, dict(area, conv='gia')) == (dict(area, conv='gia'), [])   # UK GIA — без вычета
    assert pl.outdoor_share({'rooms': rows}, None) == (None, [])


@pytest.mark.parametrize('text, want', [
    (ETAGI, 3.1), ('Высота потолков: 2,7 м', 2.7), ('высота потолков 270 см', 2.7), ('Потолки 280', 2.8),
    ('Ceiling height 2.6 m', 2.6), ('Высота потолков 12 м', None), ('Потолки 2,7 м\nВысота потолков 3 м', None),
    ('Высота потолков 3,1 м\nПотолки 310 см', 3.1), ('Площадь 68,8 м2', None), ('', None),
])
def test_ceiling_height(text, want):
    assert listing.ceiling_height(text) == want


def test_total_area_plain_ploshchad_key_but_not_kitchen():
    assert listing.total_area('Площадь\n68,8 м2')['m2'] == 68.8
    assert listing.total_area('Площадь кухни\n12 м2') is None


def test_apply_ceiling_raises_full_height_walls_only():
    h0 = round(bench.H_WALL * 100, 1)
    res = {'panels': [{'walls': [{'z0': 0, 'z1': h0, 'polys': []}, {'z0': 0, 'z1': 90.0, 'polys': []}]}]}
    out = pl.apply_ceiling(json.loads(json.dumps(res)), 3.1)
    assert [w['z1'] for w in out['panels'][0]['walls']] == [310.0, 90.0] and out['ceilingCm'] == 310.0
    assert pl.apply_ceiling(json.loads(json.dumps(res)), None) == res


def _sheet(grey_t=6, outer_t=16, grey=140):
    """Квартира 400×300: чёрные наружные стены `outer_t`, серая перегородка `grey_t` посередине, мебель волосяной линией."""
    g = np.full((300, 400), 255, np.uint8)
    g[:outer_t, :] = g[-outer_t:, :] = g[:, :outer_t] = g[:, -outer_t:] = 40
    g[outer_t:-outer_t, 200:200 + grey_t] = grey
    g[100, 40:150] = grey                                                         # стол — линия в 1 px
    return np.pad(g, 20, constant_values=255)                                     # поле листа: стена не у края картинки


def test_grey_partitions_found_on_thick_dark_sheet():
    g = _sheet()
    dark = (g < 125).astype(np.uint8)
    add, info = fc.grey_partitions(g, dark, 125)
    assert info['used'] and info['t'] >= 12 and 4 <= info['tp'] < 0.6 * info['t']
    assert add[170, 222] and not add[120, 100] and not add[170, 120]              # перегородка — да, мебель и пол — нет (поле 20)


def test_grey_stroke_inside_wall_gap_is_opening_not_partition():
    """Регресс rpJz…/yb3…: серая линия окна/порога в разрыве тёмной стены (стена за обоими концами по оси) — не перегородка;
    перегородка торцом к стенам (за концом — толщина стены и поле) — остаётся."""
    g = _sheet()
    g[20:36, 80:160] = 255                                                        # окно в верхней стене (поле 20)
    g[26:32, 80:160] = 140                                                        # его серая линия по оси стены
    add, info = fc.grey_partitions(g, (g < 125).astype(np.uint8), 125)
    assert info['used'] and add[170, 222]                                         # перегородка — да
    assert not add[28, 120]                                                       # линия окна — нет
    d = (g < 125).astype(np.uint8)
    only = np.zeros_like(d)
    only[26:32, 80:160] = 1
    assert not fc.drop_wall_gap_fill(only, d, 16.0).any()


def test_grey_partitions_skipped_on_thin_walls_or_noise():
    g = _sheet(outer_t=6)
    assert not fc.grey_partitions(g, (g < 125).astype(np.uint8), 125)[1]['used']     # лист тонких стен — как было
    g = _sheet(grey=200)
    add, info = fc.grey_partitions(g, (g < 125).astype(np.uint8), 125)
    assert not info['used'] and not add.any()                                     # светлее порога серого — не стена
    g = _sheet()
    assert not fc.grey_partitions(g, (g < 170).astype(np.uint8), 170)[1]['used']     # порог тёмного уже выше серого


def _door_case(right_id: int, right_w: int = 49, exterior: bool = False, right_out: bool = False):
    """Стена x = 50..52 с закрытием y 20..35; слева комната 1, справа `right_id` шириной `right_w` (дальше — стена)."""
    H, W = 60, 110
    final = np.zeros((H, W), np.uint8)
    final[:, 50:53] = 1
    lab_g = np.zeros((H, W), np.int32)
    lab_g[20:36, 50:53] = 1
    lab = np.zeros((H, W), np.int32)
    lab[:, :50] = 1
    final[:, 53 + right_w:] = 1
    lab[:, 53:53 + right_w] = right_id
    outside = np.zeros((H, W), bool)
    if right_out:
        outside[:, 53:53 + right_w] = True
    areas = np.bincount(lab.ravel(), minlength=3)
    g = fc.Gap(1, 51.0, 27.5, 16.0, 3.0, 'door', 0.0, exterior, (50, 20, 3, 16))
    return g, lab_g, lab, final, outside, areas


def test_pocket_doors_room_both_sides_stays_pocket_or_one_side_is_wall(monkeypatch):
    monkeypatch.delenv('FP_POCKET', raising=False)
    g, *a = _door_case(2)
    bench.pocket_doors([g], *a, pocket_px=500)
    assert g.kind == 'door'                                                       # две комнаты — дверь
    g, *a = _door_case(2, right_w=5)                                              # полость 300 px < 500 — стена
    bench.pocket_doors([g], *a, pocket_px=500)
    assert g.kind == 'wall'
    g, *a = _door_case(1)                                                         # по обе стороны одна комната — не проход
    bench.pocket_doors([g], *a, pocket_px=500)
    assert g.kind == 'wall'
    g, *a = _door_case(2, right_w=5, exterior=True, right_out=True)               # наружа малой не считается
    bench.pocket_doors([g], *a, pocket_px=500)
    assert g.kind == 'door'
    g, *a = _door_case(2, right_w=8)                                              # 480 px < 500, но шире порога ширины —
    bench.pocket_doors([g], *a, pocket_px=500, pocket_w_px=6)                     # шкаф с дверцей, не щель в стене
    assert g.kind == 'door'
    g, *a = _door_case(2, right_w=5)
    bench.pocket_doors([g], *a, pocket_px=500, pocket_w_px=12)
    assert g.kind == 'wall'
    monkeypatch.setenv('FP_POCKET', '0')
    g, *a = _door_case(2, right_w=5)
    bench.pocket_doors([g], *a, pocket_px=500)
    assert g.kind == 'door'                                                       # выключатель — как было


def test_area_rerun_only_on_sheets_with_printed_room_areas(monkeypatch):
    """Повтор стен на масштабе площади — только у листа с площадями комнат (РФ); британский лист без них — как было."""
    called = []
    monkeypatch.setattr(pl, 'area_scale', lambda *a, **k: called.append(1) or {'ok': True, 'ppm': 74.9})
    monkeypatch.setattr(pl, '_models', lambda *a, **k: [])
    monkeypatch.delenv('FP_AREA_RERUN', raising=False)
    area = {'m2': 68.8, 'conv': 'rooms'}
    uk = {'rooms': [{'name': 'Lounge'}, {'name': 'Hall', 'area_m2': None}]}
    assert pl.area_rerun_ppm({}, None, 'T', uk, area, 80.0) is None and not called
    ru = {'rooms': [{'vtype': 'bedroom', 'area_m2': 14.9}, {'vtype': 'hall', 'area_m2': 4.3}]}
    assert pl.area_rerun_ppm({}, None, 'T', ru, area, 80.0) == 74.9
    assert pl.area_rerun_ppm({}, None, 'T', ru, area, 75.5) is None               # ближе 4 % — без повтора
    monkeypatch.setenv('FP_AREA_RERUN', '0')
    assert pl.area_rerun_ppm({}, None, 'T', ru, area, 80.0) is None


def test_same_room_gaps_only_removed_closures_inside_one_room():
    g, lab_g, lab, *_ = _door_case(1)                                             # закрытие снято, по обе стороны — комната 1
    lab = lab.copy()
    lab[20:36, 50:53] = 1
    rm = lab_g == 1
    assert (bench.same_room_gaps(lab_g, [g], rm, lab) == rm).all()
    g, lab_g, lab, *_ = _door_case(2)                                             # граница min-cut: по сторонам разные — проём
    assert not bench.same_room_gaps(lab_g, [g], lab_g == 1, lab).any()
    g, lab_g, lab, *_ = _door_case(1)                                             # круг закрытие не снимал — не смотрим
    assert not bench.same_room_gaps(lab_g, [g], np.zeros_like(lab_g, bool), lab).any()


def test_shrink_gaps_drops_short_stub_keeps_rest():
    lab_g = np.zeros((40, 80), np.int32)
    lab_g[10:14, 5:65] = 1                                                        # закрытие 60 px
    g = fc.Gap(1, 34.5, 11.5, 60.0, 4.0, 'door', 0.0, False, (5, 10, 60, 4))
    removed = np.zeros_like(lab_g, bool)
    removed[:, 15:65] = True                                                      # снято всё, кроме 10 px
    lg, gs = bench.shrink_gaps(lab_g, [g], removed, stub_px=16)
    assert gs == [] and not lg.any()                                              # обрубок 10 px < 16 — не проём
    lg, gs = bench.shrink_gaps(lab_g, [g], removed)
    assert len(gs) == 1 and gs[0].length == pytest.approx(10, abs=1)              # без порога — остаток как был
