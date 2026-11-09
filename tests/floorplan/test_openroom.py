"""T-20261109-16: замыкание открытых комнат (openroom), семейства углов комнаты (C-3), отсев безымянных обрывков."""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import bench  # noqa: E402
import fpcore as fc  # noqa: E402
import openroom as orm  # noqa: E402

PPM = 20.0   # 20 px на метр


def open_sheet(gap_m=1.6, faint=False, tint=False):
    """Лист 300×240: комната 5×4 м (100×80 px, x 50–150, y 50–130), стены 4 px; правая стена с проёмом gap_m
    посередине (открытая планировка в соседнюю комнату справа, 5×4 м, x 150–250). faint — тонкая линия складной
    двери в проёме; tint — пол обеих комнат залит серым 218 на белом листе. → (gray, final)."""
    g = np.full((240, 300), 255, np.uint8)
    if tint:
        g[50:130, 50:250] = 218
    final = np.zeros_like(g)
    for (y0, y1, x0, x1) in ((48, 52, 48, 252), (128, 132, 48, 252), (48, 132, 48, 52), (48, 132, 248, 252)):
        final[y0:y1, x0:x1] = 1
    gp = int(gap_m * PPM)
    yc = 90
    final[48:yc - gp // 2, 148:152] = 1
    final[yc + gp // 2:132, 148:152] = 1
    g[final > 0] = 0
    if faint:
        g[yc - gp // 2:yc + gp // 2, 150] = 120     # складная дверь: тонкая серая линия
    return g, final


def test_tint_barrier_only_for_filled_floor():
    g, _ = open_sheet(tint=True)
    t = orm.tint_barrier(g, (100, 90), 12, 255.0)
    assert t is not None and t[10, 10] and not t[90, 100]
    g2, _ = open_sheet(tint=False)
    assert orm.tint_barrier(g2, (100, 90), 12, 255.0) is None


def test_tint_barrier_off_when_panel_floors_white():
    """Сглаженный текст у подписи на белом полу — не заливка: медиана комнат панели белая."""
    g, _ = open_sheet(tint=True)
    assert orm.tint_barrier(g, (100, 90), 12, 255.0, floor=254.0) is None
    assert orm.tint_barrier(g, (100, 90), 12, 255.0, floor=218.0) is not None


def test_attached_lines_drops_free_standing_furniture():
    wall = np.zeros((100, 100), bool)
    wall[10:14, 10:90] = True
    faint = np.zeros((100, 100), bool)
    faint[14:40, 50] = True                          # от стены вниз — складная дверь
    faint[60:80, 30] = True; faint[60:80, 60] = True; faint[60, 30:61] = True; faint[80, 30:61] = True  # остров
    a = orm.attached_lines(faint, wall)
    assert a[30, 50] and not a[70, 30]


def test_hull_mask_keeps_room_inside_building():
    final = np.zeros((100, 100), np.uint8)
    final[20:24, 20:80] = 1; final[20:80, 20:24] = 1; final[76:80, 20:50] = 1
    h = orm.hull_mask(final)
    assert h[50, 40] and not h[5, 5] and not h[90, 90]


def test_enclose_box_stays_inside_hull():
    """Рамка не уходит за здание: открытая сторона у края листа закрывается по оболочке, а не по пустому листу."""
    g, final = open_sheet(gap_m=3.0)
    inside = orm.hull_mask(final)
    comp, info = orm.enclose_box(final, np.zeros(final.shape, np.int32), [], g, (100, 90), (5.0, 4.0), PPM,
                                 [0.0, 90.0], 255.0, other_pts=[(200, 90)], t_int=4, inside=inside)
    assert comp is not None, info
    assert not (comp & ~inside).any()


def test_seed_component_takes_majority_of_disk():
    free = np.ones((60, 60), bool)
    free[:, 30] = False
    m, _ = orm.seed_component(free, (20, 30), 6)
    assert m[30, 10] and not m[30, 50]
    assert orm.seed_component(np.zeros((20, 20), bool), (10, 10), 3)[0] is None


def test_enclose_lines_bridges_open_side_by_wall_continuation():
    g, final = open_sheet(gap_m=1.6)
    lab = np.zeros(final.shape, np.int32)
    comp, info = orm.enclose_lines(final, lab, [], g, (100, 90), (5.0, 4.0), PPM, [0.0, 90.0], 255.0,
                                   other_pts=[(200, 90)], other_areas_px=[])
    assert comp is not None, info
    assert info['L_m'] >= 1.8                       # 1,6 м — не дверь: нужна «арка/открытая планировка»
    a = comp.sum() / PPM / PPM
    assert abs(a - 20.0) / 20.0 <= 0.15
    assert not comp[90, 200]                        # в соседнюю не протекло


def test_enclose_lines_uses_faint_line_first():
    g, final = open_sheet(gap_m=1.6, faint=True)
    lab = np.zeros(final.shape, np.int32)
    comp, info = orm.enclose_lines(final, lab, [], g, (100, 90), (5.0, 4.0), PPM, [0.0, 90.0], 255.0,
                                   other_pts=[(200, 90)], other_areas_px=[])
    assert comp is not None and info['L_m'] == 0.0


def test_enclose_lines_refuses_leak_into_other_label():
    g, final = open_sheet(gap_m=3.6)                 # проём почти во всю стену — продолжения стены нет
    lab = np.zeros(final.shape, np.int32)
    comp, why = orm.enclose_lines(final, lab, [], g, (100, 90), (5.0, 4.0), PPM, [0.0, 90.0], 255.0,
                                  other_pts=[(200, 90)], other_areas_px=[])
    assert comp is None and isinstance(why, str)


def test_enclose_lines_tint_edge_closes_open_side():
    """Навес: нижней стены нет, пол залит — граница по краю заливки."""
    g = np.full((240, 300), 255, np.uint8)
    g[50:130, 50:150] = 218
    final = np.zeros_like(g)
    final[48:52, 48:152] = 1; final[48:130, 48:52] = 1; final[48:130, 148:152] = 1
    g[final > 0] = 0
    comp, info = orm.enclose_lines(final, np.zeros(final.shape, np.int32), [], g, (100, 90), (5.0, 4.0), PPM,
                                   [0.0, 90.0], 255.0, other_pts=[], other_areas_px=[])
    assert comp is not None and info['tint']
    assert abs(comp.sum() / PPM / PPM - 20.0) / 20.0 <= 0.15


def test_enclose_box_places_label_rectangle_on_walls():
    g, final = open_sheet(gap_m=3.0)
    lab = np.zeros(final.shape, np.int32)
    comp, info = orm.enclose_box(final, lab, [], g, (100, 90), (5.0, 4.0), PPM, [0.0, 90.0], 255.0,
                                 other_pts=[(200, 90)], t_int=4)
    assert comp is not None, info
    assert abs(comp.sum() / PPM / PPM - 20.0) / 20.0 <= 0.15
    assert not comp[90, 200]


def test_enclose_box_refuses_unsupported_frame():
    g = np.full((240, 300), 255, np.uint8)
    final = np.zeros_like(g)
    comp, why = orm.enclose_box(final, np.zeros(final.shape, np.int32), [], g, (150, 120), (5.0, 4.0), PPM,
                                [0.0, 90.0], 255.0, other_pts=[], t_int=4)
    assert comp is None and 'не легла' in why


def test_point_inside_rejects_callout_outside_walls():
    """Подпись-выноска над планом (B: Walk-in Wardrobe, Wardrobe) — вне оболочки стен, замыкать её нельзя."""
    _, final = open_sheet(gap_m=1.6)
    h = orm.hull_mask(final)
    assert orm.point_inside(h, (100, 90))
    assert not orm.point_inside(h, (100, 10)) and not orm.point_inside(h, (-5, 500))
    assert orm.point_inside(None, (100, 10))


def test_is_max_note():
    assert orm.is_max_note('max') and orm.is_max_note('into bay') and orm.is_max_note('MAX')
    assert not orm.is_max_note(None) and not orm.is_max_note('') and not orm.is_max_note('unsure')


def test_enclose_box_max_label_tolerates_wall_nib():
    """Мерка «max» — габарит: выступ стены на ~4 % рамки не отменяет комнату; при обычной мерке — отказ (порог 3 %)."""
    g, final = open_sheet(gap_m=3.0)
    final[60:76, 70:88] = 1
    lab = np.zeros(final.shape, np.int32)
    args = (final, lab, [], g, (100, 95), (5.0, 4.0), PPM, [0.0, 90.0], 255.0)
    comp, why = orm.enclose_box(*args, other_pts=[(200, 90)], t_int=4)
    assert comp is None and 'не легла' in why
    comp, info = orm.enclose_box(*args, other_pts=[(200, 90)], t_int=4, max_extent=True)
    assert comp is not None, info
    assert not comp[68, 80]                               # выступ — не пол


def test_enclose_box_frame_may_overhang_hull_a_little():
    """Угол рамки мимо эркера (за оболочкой до 15 % рамки) не отменяет комнату; пол за оболочку не выходит."""
    g, final = open_sheet(gap_m=3.0)
    inside = np.ones(final.shape, bool)
    for y in range(50, 72):
        inside[y, 52:52 + (72 - y)] = False               # срезан левый верхний угол комнаты, ~4 % рамки
    comp, info = orm.enclose_box(final, np.zeros(final.shape, np.int32), [], g, (100, 95), (5.0, 4.0), PPM,
                                 [0.0, 90.0], 255.0, other_pts=[(200, 90)], t_int=4, inside=inside)
    assert comp is not None, info
    assert 0 < info['beyond'] <= orm.BOX_OUTSIDE
    assert not (comp & ~inside).any()


def test_enclose_box_refuses_frame_far_beyond_hull():
    g, final = open_sheet(gap_m=3.0)
    inside = np.zeros(final.shape, bool)
    inside[40:80, :] = True                               # оболочка — полоса 40 px: половина рамки (80 px) вне её при любом сдвиге
    comp, why = orm.enclose_box(final, np.zeros(final.shape, np.int32), [], g, (100, 60), (5.0, 4.0), PPM,
                                [0.0, 90.0], 255.0, other_pts=[(200, 90)], t_int=4, inside=inside)
    assert comp is None and 'за оболочкой' in why


def test_virtual_boundary_only_off_wall():
    g, final = open_sheet(gap_m=1.6)
    comp = np.zeros(final.shape, bool)
    comp[52:128, 52:148] = True
    vb = orm.virtual_boundary(comp, final, 4)
    ys, xs = np.nonzero(vb)
    assert len(xs) and (xs >= 147).all() and (abs(ys - 90) <= 18).all()


def test_room_families_adds_axis_edge_in_rotated_panel():
    """Крыло повёрнуто на 5,7° (семейства панели 5,7/95,7), комната внутри — по осям листа: семейство 0 добавляется."""
    m = np.zeros((200, 200), np.uint8)
    m[40:160, 30:170] = 1
    fs = fc.room_families(m, [5.7, 95.7], 30)
    assert any(fc.angdiff(f, 0.0) < 1.0 for f in fs) and any(fc.angdiff(f, 90.0) < 1.0 for f in fs)
    fs2 = fc.room_families(m, [0.0, 90.0], 30)
    assert len(fs2) == 2                            # своё семейство уже есть — ничего не добавляется


def test_room_families_ignores_arc():
    m = np.zeros((200, 200), np.uint8)
    cv2.circle(m, (100, 100), 70, 1, -1)
    assert len(fc.room_families(m, [0.0, 90.0], 30)) == 2


def test_contour_lines_fams_at_overrides_panel_families():
    m = np.zeros((200, 200), np.uint8)
    m[40:160, 30:170] = 1
    cnt = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0][0]
    panel = fc.contour_lines(cnt, [5.7, 95.7])
    room = fc.contour_lines(cnt, [5.7, 95.7], fams_at=lambda span: [0.0, 90.0, 5.7, 95.7])
    assert any(fc.angdiff(s['ang'], 5.7) < 0.1 for s in panel if s['len'] > 50)
    assert all(min(fc.angdiff(s['ang'], 0.0), fc.angdiff(s['ang'], 90.0)) < 0.1 for s in room if s['len'] > 50)


def test_skew_stats_fams_of_per_polygon():
    sq = np.array([[0, 0], [100, 0], [100, 80], [0, 80]], float)
    polys = [(sq, [])]
    assert fc.skew_stats(polys, [5.7, 95.7], 10)['skew_polys'] == 1
    assert fc.skew_stats(polys, [5.7, 95.7], 10, fams_of=lambda k, p, q: [0.0, 90.0])['skew_polys'] == 0


def test_fragment_rule_drops_small_or_narrow_unnamed():
    assert bench.is_fragment(1.2, 1.3) and bench.is_fragment(3.6, 0.9)
    assert not bench.is_fragment(2.0, 1.4) and not bench.is_fragment(3.0, None)
    topo = {'extra_rooms': 4, 'extra_areas_m2': [1.1, 3.7, 2.4, 1.0], '_extra_ids': [5, 6, 7, 8],
            '_extra_w': [1.1, 0.95, 1.3, 0.8]}
    t = bench.name_extras(topo, [{'room': 8, 'name': 'WC'}])
    assert t['extra_rooms'] == 2 and t['extra_unnamed_m2'] == [2.4] and t['extra_named'] == [None, 'WC']
    assert t['fragments_m2'] == [1.1, 3.7]


def test_inscribed_width():
    m = np.zeros((50, 80), bool)
    m[10:30, 10:70] = True
    assert abs(bench.inscribed_width(m) - 20) <= 2
