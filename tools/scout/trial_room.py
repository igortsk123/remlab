#!/usr/bin/env python3
"""ПРОБА АГЕНТА: ГОСТИНАЯ ПО ЗАГРУЖЕННОМУ ПЛАНУ — адаптер `floorplanResult` → комната солвера по ЯДРУ контура
(план agent-trial-03-living, L-A; T-20261109-12; поправки Codex 09.11 главнее «Решения» плана).

Вход — результат стенда (`contracts/trial.ts:floorplanResult`: см, x вправо, y вниз по листу = «вглубь» сцены). Шаги:
  1. гостиная — `kind == 'living'` (самая большая); нет — самая большая `other` с окном → флаг `living_guessed`;
  2. контур → к оси + `room_bridge.orthogonalize`; КОНТРОЛЬ: изменение площади, IoU, сдвиг наших проёмов (`contour_distorted`);
  3. проёмы панели → этой комнате, привязка в ИСХОДНЫХ координатах: вся ширина проёма (пробы по ней) у границы контура
     в допуске. У границы, но не целиком и не чужой — отказ `opening_ambiguous` (не угадываем);
  4. ядро — несколько кандидатов `planner.geometry.largest_free_rectangles` (не только [0]); остатки вне ядра
     классифицируются ДО решения: `recess` (мельче прохода — проёмы проецируются на сторону ядра), `bay` (эркер с окном:
     стык = окно-пролёт), `passage` (в остатке дверь: стык = дверь БЕЗ полотна — её видит резерв маршрута солвера
     `zones.route_reserve`), `tail` (хвост комнаты — тоже проход), `nook` (мелочь — стена);
  5. допуск ядра — по проверяемым условиям: внутри контура; обязательная группа (диван + ТВ на дистанции полосы) влезает
     реальными габаритами; ни один проём не разрезан ядром; есть вход. `core_share` (70 %) — только диагностика;
  6. `post_check` — после солвера по ПОЛНОМУ контуру: мебель в контуре, дуги дверей с ОБЕИХ сторон свободны (петель в
     контракте нет), вход и все нужные стыки связаны проходом `passage_min_cm` после мебели.
Радиаторы и камины НЕ выдумываются (в контракте их нет). Пороги — `rules/trial-room.json`.

  ~/venvs/scout/bin/python trial_room.py <floorplanResult.json> [--json]
  ~/venvs/scout/bin/python trial_room.py --bench model-D-1.json [...] [--json]     # модели стенда (метры) → floorplanResult
"""
from __future__ import annotations

import json
import math
import os
import re
import sys

from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
SOLVER = os.path.join(HERE, '..', '..', 'services', 'planner-solver')
if SOLVER not in sys.path:
    sys.path.insert(0, SOLVER)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import room_bridge as _RBR  # noqa: E402

RULES_PATH = os.path.join(HERE, 'rules', 'trial-room.json')
WALLS = ('south', 'north', 'west', 'east')
# ЗАКРЫТЫЙ СПИСОК ОТКАЗОВ (честный отказ с причиной — гостиная остаётся серой, страница пишет почему)
REFUSALS = {
    'no_living': 'в плане нет гостиной и нет жилой комнаты с окном',
    'scale_unverified': 'масштаб плана не проверен — расставлять мебель по нему нельзя',
    'living_no_window': 'у гостиной нет ни окна, ни остеклённой наружной двери',
    'contour_distorted': 'выпрямление контура слишком меняет комнату или сдвигает проёмы',
    'opening_ambiguous': 'проём у стены гостиной не сопоставлен однозначно',
    'living_core_small': 'обязательная группа гостиной (диван и ТВ) не влезает ни в одно ядро',
    'opening_cut_by_core': 'каждое пригодное ядро режет проём пополам',
    'no_entry': 'у гостиной нет входа (двери или прохода)',
    'no_core': 'в контуре нет прямоугольного ядра с нужными сторонами',
}


class Refusal(Exception):
    def __init__(self, code: str, detail: str = ''):
        assert code in REFUSALS, code
        super().__init__(f'{code}: {detail or REFUSALS[code]}')
        self.code, self.detail = code, detail or REFUSALS[code]


def rules() -> dict:
    return json.load(open(RULES_PATH, encoding='utf-8'))


def passage_cm() -> float:
    """Ширина прохода после мебели — та же функция, что у `validate` (`planner/clearances.py`), своего числа нет."""
    from planner.clearances import passage_min_cm
    return float(passage_min_cm('secondary'))


def bay_max_depth_cm() -> float:
    from planner.invariants import TEMPLATES
    return float((TEMPLATES.get('contour_features') or {}).get('bay_max_depth_cm', 120))


# ───────────────────────── модели стенда (метры) → floorplanResult (только для замера L-C и тестов) ─────────────────────────

def kind_of(names: list, cfg: dict | None = None) -> str:
    """Тип комнаты по подписи листа. Порядок важен: «Kitchen/Diner» — кухня, «Bathroom/Landing» — санузел."""
    cfg = cfg or rules()
    s = ' '.join(names or []).lower()
    for kind, key in (('kitchen', 'kitchen_name_re'), ('bathroom', 'bathroom_name_re'), ('bedroom', 'bedroom_name_re'),
                      ('living', 'living_name_re'), ('hall', 'hall_name_re')):
        if s and re.search(cfg[key], s):
            return kind
    return 'other'


def _ring_cm(ring: list) -> list:
    return [[round(x * 100, 1), round(y * 100, 1)] for x, y in ring]


def from_bench_models(models: list[dict]) -> dict:
    """Модели слепого стенда (`model-*.json`: метры, `floors` с номером комнаты, `openings` с `width_m`) → floorplanResult v1
    в см, как схема `tests/fixtures/trial-result.schema.json`. Масштаб стенда снят по подписям листа — `listing`."""
    panels = []
    for i, m in enumerate(models):
        names = {r['id']: r.get('names') or [] for r in m.get('rooms') or []}
        rooms = []
        for fl in m.get('floors') or []:
            rid = fl.get('room')
            ring = _ring_cm(fl['outer'])
            xs, ys = [p[0] for p in ring], [p[1] for p in ring]
            nm = names.get(rid) or []
            rooms.append({'id': f'r{rid}', 'name': ' / '.join(nm)[:80], 'kind': kind_of(nm), 'contour': ring,
                          'bbox': {'x': min(xs), 'y': min(ys), 'w': max(xs) - min(xs), 'd': max(ys) - min(ys)},
                          'areaM2': round(Polygon(ring).area / 1e4, 2), 'flags': []})
        walls = [{'z0': b['z0'] * 100, 'z1': b['z1'] * 100,
                  'polys': [{'outer': _ring_cm(p['outer']), 'holes': [_ring_cm(h) for h in p.get('holes') or []]}
                            for p in b.get('polys') or []]} for b in m.get('bands') or []]
        ops = [{'kind': o['kind'], 'c': [round(o['c'][0] * 100, 1), round(o['c'][1] * 100, 1)],
                'widthCm': round(o['width_m'] * 100, 1), 'exterior': bool(o.get('exterior'))}
               for o in m.get('openings') or [] if o.get('kind') in ('door', 'window', 'opening')]
        panels.append({'id': f"p{i}", 'title': str(m.get('panel') or '')[:120], 'rooms': rooms, 'walls': walls,
                       'openings': ops})
    return {'version': 1, 'units': 'cm',
            'source': {'mime': 'image/jpeg', 'pages': 1, 'usedPages': 1, 'imageW': 1, 'imageH': 1},
            'scale': {'status': 'listing', 'ppm': round(float(models[0].get('ppm') or 1), 3), 'inliers': 0, 'n': 0},
            'panels': panels, 'flags': ['bench_model'], 'timings': {}, 'costUsd': 0}


# ───────────────────────── 1. какая комната — гостиная ─────────────────────────

def _openings_of(panel: dict, room: dict, cfg: dict) -> tuple[list, list]:
    """Проёмы панели, привязанные к комнате в ИСХОДНЫХ координатах → (наши, неоднозначные).

    Наш: центр ≤ near от границы пола И вся ширина (пробы вдоль ближайшего ребра) ≤ near от неё. Между near и far, не наш
    и не лёг целиком к другой комнате панели — неоднозначный. Дверь общей стены наша и соседа — это нормально."""
    poly = Polygon(room['contour']).buffer(0)
    near, far, k = float(cfg['opening_near_cm']), float(cfg['opening_far_cm']), int(cfg['opening_samples'])
    others = [Polygon(r['contour']).buffer(0) for r in panel['rooms'] if r is not room]
    ours, amb = [], []
    for j, op in enumerate(panel.get('openings') or []):
        c = Point(op['c'])
        d0 = poly.exterior.distance(c)
        if d0 > far:
            continue
        if _covers(poly, op, near, k) and d0 <= near:
            # «наружная» — только если и по геометрии за стеной нет другой комнаты панели: распознавание ставит
            # exterior=True всем дверям подряд (модель стенда E — 18 из 18), а от него зависят вход и свет патио
            inner = any(o.exterior.distance(c) <= far for o in others)
            ours.append(dict(op, _idx=j, _d=round(d0, 1), exterior=bool(op.get('exterior')) and not inner,
                             _exterior_src=bool(op.get('exterior'))))
            continue
        if any(o.exterior.distance(c) <= near and _covers(o, op, near, k) for o in others):
            continue                                   # целиком у соседа — его проём
        amb.append(dict(op, _idx=j, _d=round(d0, 1)))
    return ours, amb


def _edge_dir(poly: Polygon, pt: Point) -> tuple[float, float]:
    """Направление ближайшего к точке ребра контура (единичный вектор)."""
    cs = list(poly.exterior.coords)
    best, bd = (1.0, 0.0), 1e18
    for a, b in zip(cs, cs[1:]):
        seg = LineString([a, b])
        d = seg.distance(pt)
        if d < bd and seg.length > 1e-6:
            bd, best = d, ((b[0] - a[0]) / seg.length, (b[1] - a[1]) / seg.length)
    return best


def _covers(poly: Polygon, op: dict, near: float, k: int) -> bool:
    """Вся ширина проёма — у границы контура: k проб от косяка до косяка (на 5 см внутрь) в пределах near."""
    c = Point(op['c'])
    ux, uy = _edge_dir(poly, c)
    half = max(0.0, float(op['widthCm']) / 2 - 5.0)
    for i in range(k):
        t = -half + (2 * half) * i / max(1, k - 1)
        if poly.exterior.distance(Point(c.x + ux * t, c.y + uy * t)) > near:
            return False
    return True


def _light(ours: list, cfg: dict) -> tuple[bool, list]:
    flags = []
    if any(o['kind'] == 'window' for o in ours):
        return True, flags
    if any(o['kind'] == 'door' and o.get('exterior') and o['widthCm'] >= cfg['patio_door_min_cm'] for o in ours):
        return True, ['light_from_patio_door']
    return False, flags


def pick_living(result: dict, cfg: dict | None = None) -> tuple[dict, dict, list]:
    """→ (панель, комната, флаги). Несколько гостиных — самая большая (флаг `living_many`)."""
    cfg = cfg or rules()
    cands = [(p, r) for p in result['panels'] for r in p['rooms'] if r.get('kind') == 'living']
    flags = []
    if not cands:
        guess = []
        for p in result['panels']:
            for r in p['rooms']:
                if r.get('kind') == 'other' and _light(_openings_of(p, r, cfg)[0], cfg)[0]:
                    guess.append((p, r))
        if not guess:
            raise Refusal('no_living')
        cands, flags = guess, ['living_guessed']
    if len(cands) > 1:
        flags.append('living_many')
    p, r = max(cands, key=lambda pr: Polygon(pr[1]['contour']).area)
    return p, r, flags


# ───────────────────────── 2. контур к оси с контролем ─────────────────────────

def _rot(pts, ang):
    ca, sa = math.cos(-ang), math.sin(-ang)
    return [(x * ca - y * sa, x * sa + y * ca) for x, y in pts]


def _snap5(pts: list) -> list:
    """Вершины — на сетку 5 см: `largest_free_rectangles` квантует координаты к 5 см, и прямоугольник с вершины 448
    (→ 450) выходил бы за стену и отбрасывался — у произвольного плана ядра не находилось вовсе. Сдвиг ≤ 2,5 см
    (входит в контроль площади). Повторы и вершины на прямой убираются."""
    q = [(5 * round(x / 5), 5 * round(y / 5)) for x, y in pts]
    out = []
    for p in q:
        if not out or p != out[-1]:
            out.append(p)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    # замыкание `orthogonalize` оставляет косое ребро, если расхождение меньше его MERGE_CM (12 см): (755,60)→(750,675) —
    # солвер поддерживает только осевые рёбра, ставим угол ступенькой по короткой стороне
    fixed = []
    for i, a in enumerate(out):
        b = out[(i + 1) % len(out)]
        fixed.append(a)
        if a[0] != b[0] and a[1] != b[1]:
            fixed.append((a[0], b[1]) if abs(b[0] - a[0]) <= abs(b[1] - a[1]) else (b[0], a[1]))
    out = fixed
    changed = True
    while changed and len(out) > 3:
        changed = False
        for i in range(len(out)):
            a, b, c = out[i - 1], out[i], out[(i + 1) % len(out)]
            if (a[0] == b[0] == c[0]) or (a[1] == b[1] == c[1]):
                out.pop(i)
                changed = True
                break
    return [list(p) for p in out]


def ortho_frame(contour: list, cfg: dict | None = None) -> dict:
    """Контур листа → осевой контур солвера (CCW, от (0,0)) и преобразование точек листа в него.

    `room_bridge.orthogonalize` сам поворачивает к доминантной оси и нормирует в (0,0); тот же поворот применяем к проёмам,
    сдвиг — по совмещению центров масс. Контроль (Codex 09.11): |ΔS|/S ≤ ortho_area_change_max и IoU ≥ ortho_iou_min."""
    cfg = cfg or rules()
    x0, y0 = min(p[0] for p in contour), min(p[1] for p in contour)
    src = [(x - x0, y - y0) for x, y in contour]
    a1 = _RBR.dominant_angle(src)
    s1 = _rot(src, a1)
    ortho = _snap5(_RBR.orthogonalize([list(p) for p in s1]))
    a2 = _RBR.dominant_angle([tuple(p) for p in s1])
    s2 = _rot(s1, a2)
    P = orient(Polygon(ortho).buffer(0), 1.0)
    S = Polygon(s2).buffer(0)
    dx, dy = S.centroid.x - P.centroid.x, S.centroid.y - P.centroid.y

    def T(pt):
        q = _rot(_rot([(pt[0] - x0, pt[1] - y0)], a1), a2)[0]
        return (q[0] - dx, q[1] - dy)
    S_in = Polygon([T(p) for p in contour]).buffer(0)
    a_src, a_ort = S_in.area, P.area
    iou = P.intersection(S_in).area / max(P.union(S_in).area, 1.0)
    ctl = {'area_src_m2': round(a_src / 1e4, 2), 'area_ortho_m2': round(a_ort / 1e4, 2),
           'area_change': round(abs(a_ort - a_src) / max(a_src, 1.0), 4), 'iou': round(iou, 3),
           'angle_deg': round(math.degrees(a1 + a2), 2), 'vertices': [len(contour), len(ortho)]}
    if ctl['area_change'] > cfg['ortho_area_change_max'] or iou < cfg['ortho_iou_min']:
        raise Refusal('contour_distorted', f"площадь {ctl['area_src_m2']}→{ctl['area_ortho_m2']} м², IoU {ctl['iou']}")
    return {'poly': P, 'contour': [[round(x), round(y)] for x, y in list(P.exterior.coords)[:-1]], 'T': T, 'control': ctl}


def _place_opening(P: Polygon, op: dict, T, cfg: dict) -> dict:
    """Проём листа → кадр осевого контура: центр, ширина, направление ребра, внутренняя нормаль."""
    c = T(op['c'])
    pt = Point(c)
    d = P.exterior.distance(pt)
    if d > cfg['opening_near_cm'] + 10:
        raise Refusal('contour_distorted', f"{op['kind']} {op['widthCm']:.0f} см уехал от стены на {d:.0f} см после выпрямления")
    ux, uy = _edge_dir(P, pt)
    ux, uy = (round(ux), round(uy)) if abs(ux) + abs(uy) > 0 else (1, 0)
    nin = (-uy, ux)                                   # CCW: внутрь — слева от направления ребра
    # знак нормали проверяем по факту: шаг внутрь от ближайшей точки границы должен попасть в пол
    q = P.exterior.interpolate(P.exterior.project(pt))
    if not P.contains(Point(q.x + nin[0] * 5, q.y + nin[1] * 5)):
        nin = (-nin[0], -nin[1])
    w = float(op['widthCm'])
    kind = op['kind']
    o = {'kind': kind, 'c': (round(c[0], 1), round(c[1], 1)), 'w': w, 'axis': 'x' if ux else 'y', 'n_in': nin,
         'exterior': bool(op.get('exterior')), 'src': op['_idx'], 'edge_q': (q.x, q.y)}
    if kind == 'door':
        o['leaf'] = min(w / 2 if w >= cfg['double_door_min_cm'] else w, cfg['door_leaf_max_cm'])
    return o


# ───────────────────────── 3. ядро и остатки ─────────────────────────

def _side(rect, wall):
    x0, y0, x1, y1 = rect
    return {'south': ('x', y0, x0, x1, -1), 'north': ('x', y1, x0, x1, +1),
            'west': ('y', x0, y0, y1, -1), 'east': ('y', x1, y0, y1, +1)}[wall]


def _on_core(o: dict, rect, P: Polygon, recess: float, near: float):
    """Проём на стороне ядра (как есть или в мелкой нише перед ней) → ('on', стена, смещение, ширина) | ('cut', стена) | None."""
    for wall in WALLS:
        axis, line, a, b, sgn = _side(rect, wall)
        if o['axis'] != axis:
            continue
        along, across = (o['c'][0], o['c'][1]) if axis == 'x' else (o['c'][1], o['c'][0])
        out = (across - line) * sgn                    # >0 — снаружи ядра
        if out < -near or out > recess + near:         # recess = 0 — только прямо на стороне ядра
            continue
        lo, hi = along - o['w'] / 2, along + o['w'] / 2
        if hi <= a + 1 or lo >= b - 1:
            continue
        # проём, вынесенный дальше допуска near (из мелкой ниши), проецируется, только если между стороной ядра и
        # нишей — пол, а не стена соседнего угла; в пределах near центр просто лежит в толще стены
        if out > near:
            far_edge = across - sgn * near
            gap = box(max(lo, a), min(line, far_edge), min(hi, b), max(line, far_edge)) if axis == 'x' else \
                box(min(line, far_edge), max(lo, a), max(line, far_edge), min(hi, b))
            if not P.buffer(1.0).contains(gap.buffer(-0.5) if gap.area > 4 else gap.centroid):
                continue
        if lo < a - 5 or hi > b + 5:
            return ('cut', wall)
        lo, hi = max(lo, a), min(hi, b)
        return ('on', wall, round(lo - a, 1), round(hi - lo, 1))
    return None


SLIVER_CM = 20.0   # остаток уже — дрожь стены после выпрямления, а не часть комнаты: морфологическое «открытие» его снимает


def _residue_parts(P: Polygon, rect) -> list:
    rest = P.difference(box(*rect))
    if rest.is_empty:
        return []
    h = SLIVER_CM / 2
    rest = rest.buffer(-h, join_style=2).buffer(h, join_style=2).intersection(rest)
    parts = [rest] if rest.geom_type == 'Polygon' else [g for g in getattr(rest, 'geoms', []) if g.geom_type == 'Polygon']
    return [g for g in parts if g.area > 100.0]


def _junctions(g: Polygon, rect) -> list:
    """Стыки остатка с ядром: [(стена, от, до)] вдоль сторон ядра."""
    out = []
    for wall in WALLS:
        axis, line, a, b, _ = _side(rect, wall)
        seg = LineString([(a, line), (b, line)]) if axis == 'x' else LineString([(line, a), (line, b)])
        inter = seg.intersection(g.buffer(0.5))
        for piece in ([inter] if inter.geom_type == 'LineString' else list(getattr(inter, 'geoms', []))):
            if piece.geom_type != 'LineString' or piece.length < 5:
                continue
            vs = [c[0] if axis == 'x' else c[1] for c in piece.coords]
            lo, hi = min(vs), max(vs)
            lo = a if lo <= a + 0.5 else lo + 0.5           # снять запас buffer(0.5) у внутренних концов стыка
            hi = b if hi >= b - 0.5 else hi - 0.5
            out.append((wall, round(lo - a, 1), round(hi - a, 1)))
    return out


def _depth(g: Polygon, rect, juncs: list) -> float:
    x0, y0, x1, y1 = rect
    gx0, gy0, gx1, gy1 = g.bounds
    d = 0.0
    for wall, _, _ in juncs:
        d = max(d, {'south': y0 - gy0, 'north': gy1 - y1, 'west': x0 - gx0, 'east': gx1 - x1}[wall])
    return round(d, 1)


def need_group(dims: dict | None = None, band: str = '14-16') -> dict:
    """Обязательная группа гостиной реальными габаритами: диван и носитель ТВ на минимальной дистанции полосы.
    Без габаритов — типовые (`typical-dims.json`), дистанция — `occupancy.json dynamic.sofa_tv_cm`."""
    td = json.load(open(os.path.join(HERE, 'typical-dims.json'), encoding='utf-8'))
    occ = json.load(open(os.path.join(HERE, 'occupancy.json'), encoding='utf-8'))['dynamic']['sofa_tv_cm']
    dims = dims or {}
    sw, sd = dims.get('диван') or td['диван']
    bw, bd = dims.get('тв') or dims.get('тв-тумба') or td['тв-тумба']
    return {'sofa': [sw, sd], 'bearer': [bw, bd], 'tv_min_cm': float((occ.get(band) or [180])[0])}


def group_fits(w: float, d: float, need: dict) -> bool:
    L = need['sofa'][1] + need['tv_min_cm'] + need['bearer'][1]
    W = max(need['sofa'][0], need['bearer'][0])
    return (W <= w and L <= d) or (W <= d and L <= w)


def core_candidate(P: Polygon, rect, ops: list, need: dict, cfg: dict) -> dict:
    """Один кандидат ядра: проёмы на его сторонах, классификация остатков, стыки для солвера, причины отказа."""
    near = float(cfg['opening_near_cm'])
    recess = passage_cm()
    bay_max = bay_max_depth_cm()
    x0, y0, x1, y1 = rect
    W, D = x1 - x0, y1 - y0
    cand = {'rect': [x0, y0, x1, y1], 'w': W, 'd': D, 'area_m2': round(W * D / 1e4, 2),
            'core_share': round(W * D / max(P.area, 1.0), 3), 'openings': [], 'residues': [], 'reasons': [], 'flags': []}
    if not P.buffer(0.5).contains(box(*rect)):
        cand['reasons'].append('core_outside')
    parts = [(g, _junctions(g, rect)) for g in _residue_parts(P, rect)]
    parts = [(g, j, _depth(g, rect, j)) for g, j in parts if j]
    rest_ops = []
    for o in ops:
        pt = Point(o['c'])
        home = min(parts, key=lambda t: t[0].distance(pt)) if parts else None
        # на стороне ядра — прямо на ней; в мелкой нише (остаток мельче прохода) — проецируется на сторону
        allow = recess if (home is not None and home[2] <= recess and home[0].distance(pt) <= near) else 0.0
        r = _on_core(o, rect, P, allow, near)
        if r is None:
            rest_ops.append(o)
        elif r[0] == 'cut':
            cand['reasons'].append(f"opening_cut_by_core:{o['kind']}@{r[1]}")
        else:
            cand['openings'].append({'o': o, 'wall': r[1], 'offset_cm': r[2], 'width_cm': r[3]})
    for g, juncs, dep in parts:
        mine = [o for o in rest_ops if g.distance(Point(o['c'])) <= near
                and min(parts, key=lambda t: t[0].distance(Point(o['c'])))[0] is g]
        doors = [o for o in mine if o['kind'] in ('door', 'opening')]
        wins = [o for o in mine if o['kind'] == 'window']
        if dep <= recess and not doors and not wins:
            kind = 'recess'
        elif doors:
            kind = 'passage'
        elif wins:
            kind = 'bay' if dep <= bay_max else 'tail'
        elif dep > recess and g.area / 1e4 >= cfg['tail_min_m2']:
            kind = 'tail'
        else:
            kind = 'nook'
        cand['residues'].append({'kind': kind, 'area_m2': round(g.area / 1e4, 2), 'depth_cm': dep,
                                 'junctions': juncs, 'openings': [o['src'] for o in mine], 'poly': g})
    placed = {id(x['o']) for x in cand['openings']}
    in_res = {o['src'] for r in cand['residues'] for o in rest_ops if o['src'] in r['openings']}
    lost = [o for o in rest_ops if id(o) not in placed and o['src'] not in in_res]
    if lost:
        cand['reasons'].append('opening_unplaced:' + ','.join(f"{o['kind']}{o['src']}" for o in lost))
    has_entry = any(x['o']['kind'] in ('door', 'opening') for x in cand['openings']) or \
        any(r['kind'] in ('passage', 'tail') for r in cand['residues'])
    if not has_entry:
        cand['reasons'].append('no_entry')
    if not group_fits(W, D, need):
        cand['reasons'].append('living_core_small')
    cand['light_on_core'] = any(x['o']['kind'] == 'window' for x in cand['openings']) or \
        any(r['kind'] == 'bay' for r in cand['residues'])
    if not cand['light_on_core']:
        if any(r['kind'] == 'tail' and any(o['src'] in r['openings'] and o['kind'] == 'window' for o in rest_ops)
               for r in cand['residues']):
            cand['flags'].append('window_in_tail')
        elif any(x['o']['kind'] == 'door' and x['o']['exterior'] for x in cand['openings']):
            cand['flags'].append('light_from_patio_door')
    if any(r['kind'] == 'bay' for r in cand['residues']) and not any(x['o']['kind'] == 'window' for x in cand['openings']):
        cand['flags'].append('window_in_bay')
    if cand['core_share'] < cfg['core_share_diag']:
        cand['flags'].append('core_share_low')
    return cand


def solver_openings(cand: dict, cfg: dict, hinge: str = 'left') -> list:
    """Проёмы ядра для `SCENE_OPENINGS` солвера (`planner/models.py:Opening`): двери — с дугой (петля `hinge`, вторая сторона —
    в `post_check`), портал `opening` и стык с проходом/хвостом — `door` без полотна (swing 0: резерв маршрута, без дуги),
    стык с эркером — окно-пролёт."""
    out = []
    for x in cand['openings']:
        o = x['o']
        base = {'wall': x['wall'], 'offset_cm': x['offset_cm'], 'width_cm': x['width_cm']}
        if o['kind'] == 'window':
            out.append(dict(base, kind='window', sill_cm=cfg['window_sill_cm'], height_cm=cfg['window_height_cm']))
        elif o['kind'] == 'opening':
            out.append(dict(base, kind='door', swing_cm=0))
        else:
            ent = bool(o['exterior']) and o['w'] < cfg['patio_door_min_cm']
            out.append(dict(base, kind='door', swing_cm=round(o['leaf']), hinge=hinge, is_entrance=ent))
    for r in cand['residues']:
        for wall, a, b in r['junctions']:
            if b - a < 5:
                continue
            if r['kind'] in ('passage', 'tail'):
                out.append({'kind': 'door', 'wall': wall, 'offset_cm': a, 'width_cm': round(b - a, 1), 'swing_cm': 0,
                            '_junction': r['kind']})
            elif r['kind'] == 'bay':
                out.append({'kind': 'window', 'wall': wall, 'offset_cm': a, 'width_cm': round(b - a, 1),
                            'sill_cm': cfg['window_sill_cm'], 'height_cm': cfg['window_height_cm'], '_junction': 'bay'})
    return out


def adapt(result: dict, need: dict | None = None, cfg: dict | None = None) -> dict:
    """floorplanResult → гостиная: {room, ops, candidates (допущенные, по порядку), rejected, flags}. Отказ — `Refusal`."""
    cfg = cfg or rules()
    if (result.get('scale') or {}).get('status') == 'not_verified':
        raise Refusal('scale_unverified')
    panel, room, flags = pick_living(result, cfg)
    ours, amb = _openings_of(panel, room, cfg)
    if amb:
        raise Refusal('opening_ambiguous', '; '.join(f"{o['kind']} {o['widthCm']:.0f} см в {o['_d']:.0f} см от стены"
                                                     for o in amb))
    light, lf = _light(ours, cfg)
    if not light:
        raise Refusal('living_no_window')
    flags += lf
    if any(o['kind'] == 'door' and o.get('exterior') and o['widthCm'] < cfg['patio_door_min_cm'] for o in ours):
        flags.append('entrance_in_living')
    fr = ortho_frame(room['contour'], cfg)
    P = fr['poly']
    ops = [_place_opening(P, o, fr['T'], cfg) for o in ours]
    need = need or need_group()
    from planner.geometry import largest_free_rectangles
    rects = [g.bounds for g in largest_free_rectangles(P, min_side_cm=cfg['core_min_side_cm'], limit=24)]
    if not rects:
        raise Refusal('no_core')
    cands = [core_candidate(P, r, ops, need, cfg) for r in rects[:int(cfg['core_candidates'])]]
    ok = [c for c in cands if not c['reasons']]
    ok.sort(key=lambda c: (not c['light_on_core'], -c['area_m2']))
    if not ok:
        why = [r.split(':')[0] for c in cands for r in c['reasons']]
        code = next((k for k in ('living_core_small', 'opening_cut_by_core', 'no_entry') if k in why), 'no_core')
        raise Refusal(code, '; '.join(f"ядро {c['w']:.0f}×{c['d']:.0f}: {', '.join(c['reasons'])}" for c in cands))
    return {'panel': panel['id'], 'room': {'id': room['id'], 'name': room['name'], 'kind': room['kind'],
                                           'contour': fr['contour'], 'control': fr['control']},
            'poly': P, 'ops': ops, 'candidates': ok, 'rejected': [c for c in cands if c['reasons']], 'flags': flags}


# ───────────────────────── 4. проверка после солвера — по ПОЛНОМУ контуру ─────────────────────────

def to_full(cand: dict, placements: list) -> list:
    """Расстановка в кадре ядра → кадр полного контура (сдвиг на угол ядра)."""
    from planner.models import Placement
    x0, y0 = cand['rect'][0], cand['rect'][1]
    return [Placement(role=p.role, x=p.x + x0, y=p.y + y0, rot=p.rot, item=p.item, elev_cm=p.elev_cm) for p in placements]


def door_zone(o: dict, depth: float) -> Polygon:
    """Полоса перед проёмом вглубь комнаты (вся ширина) глубиной depth — в кадре полного контура."""
    qx, qy = o['edge_q']
    nx, ny = o['n_in']
    if o['axis'] == 'x':
        a, b = o['c'][0] - o['w'] / 2, o['c'][0] + o['w'] / 2
        return box(a, min(qy, qy + ny * depth), b, max(qy, qy + ny * depth))
    a, b = o['c'][1] - o['w'] / 2, o['c'][1] + o['w'] / 2
    return box(min(qx, qx + nx * depth), a, max(qx, qx + nx * depth), b)


def door_arcs(o: dict) -> Polygon:
    """Дуги створки с ОБЕИХ возможных петель (контракт петлю не несёт; Codex 09.11): два четверть-круга от косяков."""
    qx, qy = o['edge_q']
    r = float(o.get('leaf') or 0) + 5.0
    if r <= 5.0:
        return Polygon()
    strip = door_zone(o, r)
    if o['axis'] == 'x':
        j = [Point(o['c'][0] - o['w'] / 2, qy), Point(o['c'][0] + o['w'] / 2, qy)]
    else:
        j = [Point(qx, o['c'][1] - o['w'] / 2), Point(qx, o['c'][1] + o['w'] / 2)]
    return strip.intersection(unary_union([p.buffer(r, quad_segs=8) for p in j]))


def post_check(ad: dict, cand: dict, placements_core: list) -> dict:
    """Расстановка ядра → проверки по ПОЛНОМУ контуру: {ok, problems: [{code, …}], route: …}."""
    from planner.geometry import footprint
    from planner.validate import is_flat_floor
    P = ad['poly']
    ps = to_full(cand, placements_core)
    solid = [(p, footprint(p)) for p in ps if not is_flat_floor(p)]
    probs = []
    inside = P.buffer(0.5)
    for p, fp in solid:
        if not inside.contains(fp):
            probs.append({'code': 'out_of_contour', 'role': p.role})
    doors = [o for o in ad['ops'] if o['kind'] in ('door', 'opening')]
    for o in doors:
        zones = [('door_swing_blocked', door_arcs(o)), ('door_passage_blocked', door_zone(o, 76.0))]
        for code, z in zones:
            if z.is_empty:
                continue
            zi = z.buffer(-0.5)
            for p, fp in solid:
                if fp.intersection(zi).area > 1.0:
                    probs.append({'code': code, 'role': p.role, 'door': o['src']})
    need = passage_cm()
    free = P.difference(unary_union([fp for _, fp in solid])) if solid else P
    core = free.buffer(-need / 2)
    comps = [] if core.is_empty else ([core] if core.geom_type == 'Polygon' else list(core.geoms))
    targets = []
    for o in doors:
        qx, qy = o['edge_q']
        targets.append((f"{o['kind']}{o['src']}", Point(qx + o['n_in'][0] * (need / 2 + 5), qy + o['n_in'][1] * (need / 2 + 5))
                        .buffer(need / 2 + 2)))
    for i, r in enumerate(cand['residues']):
        if r['kind'] in ('passage', 'tail'):
            targets.append((f"{r['kind']}{i}", r['poly']))
    # главный кусок свободного пола — самый большой (там, где диванная группа); каждый вход и стык обязан до него дойти.
    # Иначе дверь хвоста, отрезанная от комнаты шкафом, «связана» сама с собой и проверка молчит
    main_k = max(range(len(comps)), key=lambda k: comps[k].area) if comps else None
    lost = sorted(n for n, t in targets if main_k is None or not comps[main_k].intersects(t))
    route = {'need_cm': need, 'targets': sorted(n for n, _ in targets), 'components': len(comps)}
    if targets and lost:
        probs.append({'code': 'route_blocked', 'targets': lost})
        route['lost'] = lost
    return {'ok': not probs, 'problems': probs, 'route': route}


# ───────────────────────── вывод ─────────────────────────

def summary(ad: dict) -> dict:
    """Сериализуемая сводка адаптера (без shapely)."""
    def cand(c):
        return {k: v for k, v in c.items() if k not in ('openings', 'residues')} | {
            'openings': [{'kind': x['o']['kind'], 'src': x['o']['src'], 'wall': x['wall'], 'offset_cm': x['offset_cm'],
                          'width_cm': x['width_cm']} for x in c['openings']],
            'residues': [{k: v for k, v in r.items() if k != 'poly'} for r in c['residues']]}
    return {'panel': ad['panel'], 'room': ad['room'], 'flags': ad['flags'],
            'ops': [{k: v for k, v in o.items()} for o in ad['ops']],
            'candidates': [cand(c) for c in ad['candidates']], 'rejected': [cand(c) for c in ad['rejected']]}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        print(__doc__)
        return 0
    if '--bench' in sys.argv:
        res = from_bench_models([json.load(open(a, encoding='utf-8')) for a in args])
    else:
        res = json.load(open(args[0], encoding='utf-8'))
    try:
        ad = adapt(res)
    except Refusal as e:
        print(json.dumps({'refusal': e.code, 'detail': e.detail}, ensure_ascii=False))
        return 2
    s = summary(ad)
    if '--json' in sys.argv:
        print(json.dumps(s, ensure_ascii=False, indent=1, default=str))
    else:
        c = s['candidates'][0]
        print(f"{s['room']['name']} ({s['room']['id']}): ядро {c['w']:.0f}×{c['d']:.0f} = {c['area_m2']} м² "
              f"(доля {c['core_share']}); остатки {[r['kind'] for r in c['residues']]}; флаги {s['flags'] + c['flags']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
