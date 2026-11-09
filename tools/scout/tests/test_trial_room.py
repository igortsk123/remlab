"""Проба агента: адаптер плана → гостиная по ЯДРУ контура (план agent-trial-03-living, L-A; T-20261109-12). Без сети и базы.

Синтетические планы в контракте `contracts/trial.ts:floorplanResult` (см, x вправо, y вниз по листу):
  Г-комната (хвост с дверью → стык-проход, мебель на стыке → `route_blocked`), эркер с единственным окном (не отказ,
  окно-пролёт), вход через гостиную, общая дверь двух комнат и дверь соседа у угла, неоднозначный проём → отказ,
  проёмы по стенам панели (T-25: в толще стены → привязка, ширина по следу, два равных ребра и слитая перемычка → отказ,
  дверь в полу соседа — его; дверь над нишей → вход в ядро при проходе, без прохода или без пола перед ней → отказ),
  контроль `orthogonalize` (поворот — ок, косая стена — `contour_distorted`), прочие отказы, перевод моделей стенда
  по схеме `tests/fixtures/trial-result.schema.json`.
    ~/venvs/scout/bin/python -m pytest tools/scout/tests/test_trial_room.py -q"""
import json
import math
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import trial_room as TR  # noqa: E402
from planner.models import Item, Placement  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
BENCH = '/home/pakar/remlab-logs/floorplan-bench/blind-run-1400'


def room(rid, kind, contour, name=''):
    xs, ys = [p[0] for p in contour], [p[1] for p in contour]
    return {'id': rid, 'name': name or kind, 'kind': kind, 'contour': [list(p) for p in contour],
            'bbox': {'x': min(xs), 'y': min(ys), 'w': max(xs) - min(xs), 'd': max(ys) - min(ys)}, 'areaM2': 0, 'flags': []}


def op(kind, c, w, exterior=False):
    return {'kind': kind, 'c': list(c), 'widthCm': w, 'exterior': exterior}


def result(rooms, openings, status='listing'):
    return {'version': 1, 'units': 'cm', 'source': {'mime': 'image/png', 'pages': 1, 'usedPages': 1, 'imageW': 1, 'imageH': 1},
            'scale': {'status': status, 'ppm': 50, 'inliers': 3, 'n': 3},
            'panels': [{'id': 'p0', 'title': 'Ground', 'rooms': rooms, 'walls': [], 'openings': openings}],
            'flags': [], 'timings': {}, 'costUsd': 0}


RECT = [(0, 0), (500, 0), (500, 400), (0, 400)]


def refusal(res):
    with pytest.raises(TR.Refusal) as e:
        TR.adapt(res)
    return e.value.code


def place(role, x, y, w, d, rot=0):
    return Placement(role=role, x=x, y=y, rot=rot, item=Item(role=role, w_cm=w, d_cm=d, h_cm=80))


# ───────────────────────── Г-комната ─────────────────────────

L_ROOM = [(0, 0), (600, 0), (600, 400), (250, 400), (250, 650), (0, 650)]


def l_result():
    return result([room('r1', 'living', L_ROOM)], [op('window', (300, 0), 150, True), op('door', (125, 650), 90)])


def test_l_room_core_and_tail_passage():
    ad = TR.adapt(l_result())
    c = ad['candidates'][0]
    assert c['rect'] == [0, 0, 600, 400]                       # ядро — большая часть, не столбец хвоста
    assert [r['kind'] for r in c['residues']] == ['passage']   # хвост с дверью — проход
    assert c['residues'][0]['depth_cm'] == 250
    assert c['core_share'] == pytest.approx(24 / 30.25, abs=0.002)
    # столбец 250×650 режет окно пополам — отклонён с причиной
    assert any(any(r.startswith('opening_cut_by_core') for r in x['reasons']) for x in ad['rejected'])
    sop = TR.solver_openings(c, TR.rules())
    j = [o for o in sop if o.get('_junction') == 'passage']
    assert len(j) == 1 and j[0]['kind'] == 'door' and j[0]['swing_cm'] == 0   # стык виден резерву маршрута
    assert j[0]['offset_cm'] == 0 and j[0]['width_cm'] == 250
    assert [o['kind'] for o in sop if not o.get('_junction')] == ['window']


def test_l_room_post_check_route():
    ad = TR.adapt(l_result())
    c = ad['candidates'][0]
    assert TR.post_check(ad, c, [])['ok']
    # шкаф 250×100 вдоль всего стыка с хвостом — дверь хвоста отрезана от комнаты
    blocked = TR.post_check(ad, c, [place('шкаф', 125, 350, 250, 100)])
    assert not blocked['ok'] and 'route_blocked' in [p['code'] for p in blocked['problems']]
    # тот же шкаф шириной 150 — проход 100 см остаётся
    ok = TR.post_check(ad, c, [place('шкаф', 75, 350, 150, 100)])
    assert ok['ok'], ok['problems']


def test_post_check_door_arcs_both_sides_and_contour():
    ad = TR.adapt(l_result())
    c = ad['candidates'][0]
    # ядро — от (0,0), дверь хвоста — у y=650 (кадр полного контура) → в кадре ядра предмет ставим под ней
    near_door = TR.post_check(ad, c, [place('стул', 125 + 40, 650 - 30, 40, 40)])
    codes = {p['code'] for p in near_door['problems']}
    assert 'door_swing_blocked' in codes and 'door_passage_blocked' in codes
    # другая петля — тот же результат: дуга с обеих сторон (петли в контракте нет)
    other = TR.post_check(ad, c, [place('стул', 125 - 40, 650 - 30, 40, 40)])
    assert 'door_swing_blocked' in {p['code'] for p in other['problems']}
    out = TR.post_check(ad, c, [place('тумба', 450, 500, 60, 40)])   # за стеной, в «вырезе» Г
    assert 'out_of_contour' in {p['code'] for p in out['problems']}


# ───────────────────────── эркер с единственным окном ─────────────────────────

BAY = [(0, 90), (150, 90), (150, 0), (350, 0), (350, 90), (500, 90), (500, 490), (0, 490)]


def test_bay_with_only_window_is_light_not_refusal():
    ad = TR.adapt(result([room('r1', 'living', BAY)], [op('window', (250, 0), 180, True), op('door', (250, 490), 90)]))
    c = ad['candidates'][0]
    assert c['rect'] == [0, 90, 500, 490]
    assert [r['kind'] for r in c['residues']] == ['bay']
    assert c['light_on_core'] and 'window_in_bay' in c['flags']
    sop = TR.solver_openings(c, TR.rules())
    bay = [o for o in sop if o.get('_junction') == 'bay']
    assert len(bay) == 1 and bay[0]['kind'] == 'window' and bay[0]['offset_cm'] == 150 and bay[0]['width_cm'] == 200
    assert [o['kind'] for o in sop if not o.get('_junction')] == ['door']


def test_shallow_bay_window_projects_to_core_side():
    """Ниша мельче прохода (60) — окно проецируется на сторону ядра, остаток — `recess`."""
    shallow = [(0, 40), (150, 40), (150, 0), (350, 0), (350, 40), (500, 40), (500, 440), (0, 440)]
    ad = TR.adapt(result([room('r1', 'living', shallow)], [op('window', (250, 0), 180, True), op('door', (250, 440), 90)]))
    c = ad['candidates'][0]
    assert [r['kind'] for r in c['residues']] == ['recess']
    win = [x for x in c['openings'] if x['o']['kind'] == 'window']
    assert len(win) == 1 and win[0]['offset_cm'] == 160 and win[0]['width_cm'] == 180


# ───────────────────────── вход через гостиную ─────────────────────────

def test_entrance_through_living():
    ad = TR.adapt(result([room('r1', 'living', RECT)], [op('window', (250, 0), 150, True), op('door', (100, 400), 90, True)]))
    assert 'entrance_in_living' in ad['flags']
    sop = TR.solver_openings(ad['candidates'][0], TR.rules())
    door = [o for o in sop if o['kind'] == 'door']
    assert len(door) == 1 and door[0]['is_entrance'] and door[0]['swing_cm'] == 90


def test_patio_door_is_light_not_entrance():
    ad = TR.adapt(result([room('r1', 'living', RECT)], [op('door', (250, 0), 180, True), op('door', (100, 400), 90)]))
    assert 'light_from_patio_door' in ad['flags'] and 'entrance_in_living' not in ad['flags']
    patio = [o for o in TR.solver_openings(ad['candidates'][0], TR.rules()) if o['width_cm'] == 180][0]
    assert not patio['is_entrance'] and patio['swing_cm'] == 90      # двустворчатая: створка — половина


# ───────────────────────── общая дверь двух комнат ─────────────────────────

def shared_result():
    living = room('r1', 'living', [(0, 0), (490, 0), (490, 400), (0, 400)])
    hall = room('r2', 'hall', [(510, 0), (700, 0), (700, 400), (510, 400)])
    return result([living, hall], [op('window', (245, 0), 150, True), op('door', (500, 200), 90),
                                   op('door', (525, 410), 70), op('door', (700, 100), 80, True)])


def test_shared_door_belongs_to_both_neighbour_door_to_neighbour():
    res = shared_result()
    p = res['panels'][0]
    cfg = TR.rules()
    ours, amb = TR._openings_of(p, p['rooms'][0], cfg)
    assert sorted(o['_idx'] for o in ours) == [0, 1] and amb == []
    hall, hamb = TR._openings_of(p, p['rooms'][1], cfg)
    assert 1 in [o['_idx'] for o in hall]                       # общая дверь — и прихожей тоже
    ad = TR.adapt(res)
    walls = sorted((x['o']['kind'], x['wall']) for x in ad['candidates'][0]['openings'])
    assert walls == [('door', 'east'), ('window', 'south')]


# ───────────────────────── неоднозначный проём → отказ ─────────────────────────

def test_ambiguous_opening_off_wall():
    assert refusal(result([room('r1', 'living', RECT)], [op('window', (250, 0), 150, True), op('door', (250, 445), 90)])) \
        == 'opening_ambiguous'


def test_ambiguous_opening_past_corner():
    """Центр на стене, но ширина выходит за угол — не угадываем."""
    assert refusal(result([room('r1', 'living', RECT)], [op('window', (480, 0), 160, True), op('door', (100, 400), 90)])) \
        == 'opening_ambiguous'


# ───────────────────────── проёмы по геометрии стен панели (T-20261109-25) ─────────────────────────

def lintel(x0, y0, x1, y1, z=(210, 260)):
    """Кусок перемычки (или подоконника) над проёмом — его след в стене."""
    return {'z0': z[0], 'z1': z[1], 'polys': [{'outer': [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], 'holes': []}]}


def with_walls(res, *bands):
    res['panels'][0]['walls'] = list(bands)
    return res


def test_opening_in_thick_wall_snaps_to_edge():
    """Дверь по оси толстой стены (центр в 45 см от пола, дальше допуска 35): след в перемычке 40 см толщины, ближняя
    грань — в 25 см от ребра, параллельного следу → наша, центр на грани, флаг `opening_snapped`. Без стен — отказ."""
    base = [op('window', (250, 0), 150, True), op('door', (250, 445), 90)]
    assert refusal(result([room('r1', 'living', RECT)], base)) == 'opening_ambiguous'
    res = with_walls(result([room('r1', 'living', RECT)], base), lintel(205, 425, 295, 465))
    ad = TR.adapt(res)
    assert 'opening_snapped' in ad['flags'] and 'opening_width_from_walls' not in ad['flags']
    d = [o for o in TR.openings_of(res['panels'][0], res['panels'][0]['rooms'][0], TR.rules())[0] if o['_idx'] == 1][0]
    assert d['c'] == [250.0, 425.0] and d['widthCm'] == 90.0 and d['_fix'] == ['opening_snapped']
    assert [(x['o']['kind'], x['wall']) for x in ad['candidates'][0]['openings'] if x['o']['kind'] == 'door'] == [('door', 'north')]


def test_opening_width_from_wall_footprint():
    """Окно распознано шириной 600 при стене 500 (как G, спальня 4: 501 см при проёме ~90) — ширина по следу в подоконнике
    и перемычке, флаг `opening_width_from_walls`; следы двух полос согласны."""
    ops = [op('window', (250, -5), 600, True), op('door', (100, 400), 90)]
    assert refusal(result([room('r1', 'living', RECT)], ops)) == 'opening_ambiguous'
    res = with_walls(result([room('r1', 'living', RECT)], ops), lintel(200, -15, 300, 5, (0, 90)), lintel(200, -15, 300, 5))
    ad = TR.adapt(res)
    assert {'opening_snapped', 'opening_width_from_walls'} <= set(ad['flags'])
    win = [x for x in ad['candidates'][0]['openings'] if x['o']['kind'] == 'window']
    assert len(win) == 1 and win[0]['width_cm'] == 100 and win[0]['wall'] == 'south'


def test_footprint_between_two_equal_edges_stays_ambiguous():
    """След между двумя параллельными рёбрами на равном расстоянии (узкая полоса комнаты) — не угадываем."""
    strip = [(0, 0), (400, 0), (400, 40), (200, 40), (200, 400), (0, 400)]
    res = with_walls(result([room('r1', 'bedroom', strip)], [op('door', (300, 20), 600)]), lintel(250, 15, 350, 25))
    p = res['panels'][0]
    ours, amb, flags = TR.openings_of(p, p['rooms'][0], TR.rules())
    assert ours == [] and [o['_idx'] for o in amb] == [0] and flags == []


def test_merged_lintel_is_no_footprint():
    """Две перемычки слились в Г (как E, спальня 2: двери 12 и 14) — след неровный, ширину и ось не берём: отказ остаётся."""
    lshape = {'z0': 210, 'z1': 260, 'polys': [{'outer': [[150, -15], [350, -15], [350, 5], [170, 5], [170, 120], [150, 120]],
                                               'holes': []}]}
    res = with_walls(result([room('r1', 'living', RECT)], [op('window', (250, -5), 600, True), op('door', (100, 400), 90)]), lshape)
    assert refusal(res) == 'opening_ambiguous'


def test_door_inside_neighbour_floor_is_neighbours():
    """Дверь в 45 см от нашей стены, но в полу соседней комнаты глубже допуска и не в стене (как G, спальня 6) — его проём,
    флаг `opening_foreign`; без соседа — по-прежнему отказ (`test_ambiguous_opening_off_wall`)."""
    hall = room('r2', 'hall', [(0, 400), (500, 400), (500, 700), (0, 700)])
    res = result([room('r1', 'living', RECT), hall], [op('window', (250, 0), 150, True), op('door', (100, 400), 90),
                                                       op('door', (250, 445), 90)])
    ad = TR.adapt(res)
    assert 'opening_foreign' in ad['flags'] and sorted(o['src'] for o in ad['ops']) == [0, 1]
    # та же дверь в стене (кусок стены полной высоты у центра) — не «чужая», отказ
    res['panels'][0]['walls'] = [lintel(0, 430, 500, 460, (0, 260))]
    assert refusal(res) == 'opening_ambiguous'


NICHE = [(0, 0), (500, 0), (500, 400), (100, 400), (100, 150), (0, 150)]   # ниша 100×150 слева сверху, ядро 400×400


def test_door_partly_in_niche_enters_core():
    """Дверь 200 см на верхней стене, 70 см её — над нишей: ядро 400×400 нишу не включает; на сторону ядра приходится
    130 см ≥ прохода → дверь на стороне ядра обрезанной (флаг `entry_via_niche`), створка не шире общей части,
    полная дверь — в `post_check` по полному контуру."""
    ad = TR.adapt(result([room('r1', 'living', NICHE)], [op('door', (130, 0), 200), op('window', (500, 250), 120, True)]))
    c = ad['candidates'][0]
    assert c['rect'] == [100, 0, 500, 400] and 'entry_via_niche' in c['flags']
    door = [x for x in c['openings'] if x['o']['kind'] == 'door']
    assert len(door) == 1 and door[0]['niche'] and door[0]['offset_cm'] == 0 and door[0]['width_cm'] == 130
    sd = [o for o in TR.solver_openings(c, TR.rules()) if o['kind'] == 'door']
    assert sd[0]['width_cm'] == 130 and sd[0]['swing_cm'] == 100
    assert TR.post_check(ad, c, [])['ok']
    blocked = TR.post_check(ad, c, [place('комод', 30, 30, 60, 40)])     # у стены перед дверью (кадр ядра: x 0 = край ниши)
    assert 'door_passage_blocked' in {p['code'] for p in blocked['problems']}


def test_door_in_niche_without_passage_is_cut():
    """На сторону ядра — 50 см (меньше прохода 60): входа прямо в ядро нет — отказ `opening_cut_by_core` как раньше."""
    assert refusal(result([room('r1', 'living', NICHE)], [op('door', (90, 0), 120), op('window', (500, 250), 120, True)])) \
        == 'opening_cut_by_core'


def test_niche_entry_needs_floor_in_front():
    """Свисающая часть двери — за углом ядра у стены, не над полом комнаты: не вход через нишу."""
    from shapely.geometry import box
    P = box(100, 0, 500, 400)
    o = {'kind': 'door', 'c': (130, 0), 'w': 200, 'axis': 'x'}
    assert TR._niche_entry(o, (100, 0, 500, 400), P, ('cut', 'south', 30, 230), 60) is None
    assert TR._niche_entry(dict(o, kind='window'), (100, 0, 500, 400), TR.Polygon(NICHE), ('cut', 'south', 30, 230), 60) is None
    got = TR._niche_entry(o, (100, 0, 500, 400), TR.Polygon(NICHE), ('cut', 'south', 30, 230), 60)
    assert got and got['width_cm'] == 130 and got['offset_cm'] == 0


def test_far_opening_ignored():
    ad = TR.adapt(result([room('r1', 'living', RECT)], [op('window', (250, 0), 150, True), op('door', (100, 400), 90),
                                                         op('door', (250, 470), 90)]))
    assert sorted(o['src'] for o in ad['ops']) == [0, 1]


# ───────────────────────── контроль orthogonalize ─────────────────────────

def _rotz(pts, deg, c=(250, 200)):
    a = math.radians(deg)
    return [(c[0] + (x - c[0]) * math.cos(a) - (y - c[1]) * math.sin(a),
             c[1] + (x - c[0]) * math.sin(a) + (y - c[1]) * math.cos(a)) for x, y in pts]


def test_rotated_room_is_straightened_with_control():
    pts = _rotz(RECT, 10)
    w, d = _rotz([(250, 0), (100, 400)], 10)
    ad = TR.adapt(result([room('r1', 'living', [(round(x, 1), round(y, 1)) for x, y in pts])],
                         [op('window', w, 150, True), op('door', d, 90)]))
    ctl = ad['room']['control']
    assert abs(abs(ctl['angle_deg']) - 10) < 1.0
    assert ctl['area_change'] < 0.01 and ctl['iou'] > 0.97
    c = ad['candidates'][0]
    assert abs(c['w'] - 500) <= 5 and abs(c['d'] - 400) <= 5
    assert sorted(x['o']['kind'] for x in c['openings']) == ['door', 'window']


def test_slanted_wall_refused():
    """Стена под ~27° к оси: выпрямление меняет площадь на десятки процентов — отказ, а не «лесенка»."""
    assert refusal(result([room('r1', 'living', [(0, 0), (500, 0), (500, 400), (0, 150)])],
                          [op('window', (250, 0), 150, True), op('door', (500, 200), 90)])) == 'contour_distorted'


def test_small_noise_is_kept():
    noisy = [(0, 0), (250, 3), (500, 0), (502, 200), (500, 400), (0, 398)]
    ad = TR.adapt(result([room('r1', 'living', noisy)], [op('window', (250, 0), 150, True), op('door', (100, 400), 90)]))
    assert ad['room']['control']['area_change'] < 0.02


# ───────────────────────── прочие отказы ─────────────────────────

def test_refusals():
    base = [op('window', (250, 0), 150, True), op('door', (100, 400), 90)]
    assert refusal(result([room('r1', 'living', RECT)], base, status='not_verified')) == 'scale_unverified'
    assert refusal(result([room('r1', 'bedroom', RECT), room('r2', 'other', [(600, 0), (900, 0), (900, 300), (600, 300)])],
                          base)) == 'no_living'
    assert refusal(result([room('r1', 'living', RECT)], [op('door', (100, 400), 90)])) == 'living_no_window'
    assert refusal(result([room('r1', 'living', RECT)], [op('window', (250, 0), 150, True)])) == 'no_entry'
    small = [(0, 0), (260, 0), (260, 260), (0, 260)]
    assert refusal(result([room('r1', 'living', small)], [op('window', (130, 0), 120, True), op('door', (130, 260), 80)])) \
        == 'living_core_small'


def test_living_guessed_from_other_with_window():
    ad = TR.adapt(result([room('r1', 'other', RECT)], [op('window', (250, 0), 150, True), op('door', (100, 400), 90)]))
    assert 'living_guessed' in ad['flags']


def test_thresholds_from_rules_not_literals():
    cfg = TR.rules()
    assert TR.passage_cm() == 60.0                     # planner/clearances.py — общий с validate
    assert TR.bay_max_depth_cm() == 120.0              # templates.json contour_features
    for k in ('opening_near_cm', 'opening_far_cm', 'ortho_area_change_max', 'ortho_iou_min', 'core_min_side_cm',
              'patio_door_min_cm', 'double_door_min_cm', 'core_share_diag'):
        assert k in cfg and f'_{k}' in cfg or k in ('ortho_iou_min', 'core_min_side_cm', 'core_share_diag'), k


def test_group_fits_uses_band_distance():
    n = TR.need_group(band='31-40')
    assert n['tv_min_cm'] == 220
    L = n['sofa'][1] + n['tv_min_cm'] + n['bearer'][1]
    assert TR.group_fits(n['sofa'][0], L, n) and not TR.group_fits(n['sofa'][0], L - 1, n)


# ───────────────────────── модели стенда → floorplanResult по схеме ─────────────────────────

def _check(schema, v, path='$', root=None):
    """Мини-проверка JSON Schema (подмножество, которое даёт zod-to-json-schema для контракта)."""
    root = root or schema
    errs = []
    if '$ref' in schema:
        node = root
        for k in schema['$ref'].lstrip('#/').split('/'):
            node = node[k]
        return _check(node, v, path, root)
    if 'anyOf' in schema:
        return [] if any(not _check(s, v, path, root) for s in schema['anyOf']) else [f'{path}: anyOf']
    t = schema.get('type')
    py = {'object': dict, 'array': list, 'string': str, 'boolean': bool, 'null': type(None)}
    if t in py and not isinstance(v, py[t]):
        return [f'{path}: не {t}']
    if t in ('number', 'integer') and (isinstance(v, bool) or not isinstance(v, (int, float))):
        return [f'{path}: не {t}']
    if t == 'integer' and int(v) != v:
        errs.append(f'{path}: не целое')
    if 'const' in schema and v != schema['const']:
        errs.append(f'{path}: const')
    if 'enum' in schema and v not in schema['enum']:
        errs.append(f'{path}: enum {v}')
    if 'minimum' in schema and v < schema['minimum']:
        errs.append(f'{path}: minimum')
    if 'exclusiveMinimum' in schema and v <= schema['exclusiveMinimum']:
        errs.append(f'{path}: exclusiveMinimum')
    if 'maxLength' in schema and len(v) > schema['maxLength']:
        errs.append(f'{path}: maxLength')
    if 'minLength' in schema and len(v) < schema['minLength']:
        errs.append(f'{path}: minLength')
    if t == 'object':
        props = schema.get('properties') or {}
        for k in schema.get('required') or []:
            if k not in v:
                errs.append(f'{path}.{k}: нет')
        for k, x in v.items():
            if k in props:
                errs += _check(props[k], x, f'{path}.{k}', root)
            elif schema.get('additionalProperties') is False:
                errs.append(f'{path}.{k}: лишнее')
            elif isinstance(schema.get('additionalProperties'), dict):
                errs += _check(schema['additionalProperties'], x, f'{path}.{k}', root)
    if t == 'array':
        if 'minItems' in schema and len(v) < schema['minItems']:
            errs.append(f'{path}: minItems')
        if 'maxItems' in schema and len(v) > schema['maxItems']:
            errs.append(f'{path}: maxItems')
        if isinstance(schema.get('items'), dict):
            for i, x in enumerate(v):
                errs += _check(schema['items'], x, f'{path}[{i}]', root)
    return errs


SCHEMA = json.load(open(os.path.join(ROOT, 'tests', 'fixtures', 'trial-result.schema.json'), encoding='utf-8'))


def test_schema_checker_catches_errors():
    good = result([room('r1', 'living', RECT)], [op('window', (250, 0), 150, True)])
    assert _check(SCHEMA, good) == []
    bad = json.loads(json.dumps(good))
    bad['scale']['status'] = 'maybe'
    bad['panels'][0]['openings'][0]['kind'] = 'arch'
    assert len(_check(SCHEMA, bad)) == 2


def test_bench_converter_matches_schema():
    m = {'panel': 'Ground Floor', 'ppm': 42.5,
         'rooms': [{'id': 3, 'names': ['Lounge']}, {'id': 4, 'names': ['Kitchen/Diner']}],
         'floors': [{'room': 3, 'outer': [[0, 0], [5, 0], [5, 4], [0, 4]]},
                    {'room': 4, 'outer': [[5.2, 0], [8, 0], [8, 4], [5.2, 4]]}],
         'bands': [{'z0': 0, 'z1': 2.6, 'polys': [{'outer': [[0, 0], [8, 0], [8, 0.2]], 'holes': []}]}],
         'openings': [{'kind': 'window', 'c': [2.5, 0], 'width_m': 1.5, 'exterior': True},
                      {'kind': 'door', 'c': [5.1, 2], 'width_m': 0.9}, {'kind': 'stair', 'c': [1, 1], 'width_m': 1}]}
    res = TR.from_bench_models([m])
    assert _check(SCHEMA, res) == []
    rooms = res['panels'][0]['rooms']
    assert [r['kind'] for r in rooms] == ['living', 'kitchen'] and rooms[0]['areaM2'] == 20.0
    assert res['panels'][0]['openings'][1]['widthCm'] == 90.0 and len(res['panels'][0]['openings']) == 2
    ad = TR.adapt(res)
    assert ad['room']['id'] == 'r3' and ad['candidates'][0]['area_m2'] == 20.0


@pytest.mark.parametrize('name', ['D/model-D-1.json', 'E/model-E-0.json'])
def test_bench_models_adapt(name):
    """Входные модели стенда D и E (не эталоны): перевод по схеме и ядро без отказа."""
    path = os.path.join(BENCH, name)
    if not os.path.exists(path):
        pytest.skip('нет моделей стенда на этой машине')
    res = TR.from_bench_models([json.load(open(path, encoding='utf-8'))])
    assert _check(SCHEMA, res) == []
    ad = TR.adapt(res)
    c = ad['candidates'][0]
    assert TR.group_fits(c['w'], c['d'], TR.need_group())
    assert ad['room']['control']['area_change'] <= TR.rules()['ortho_area_change_max']
    json.dumps(TR.summary(ad), default=str)
