#!/usr/bin/env python3
"""СХЕМЫ ШАБЛОНОВ СПАЛЬНИ В МАСШТАБЕ — эскизный инструмент для показа владельцу, НЕ солвер
(план `.memory_bank/plans/bedroom-groups-01.md` Т0, задача T-20261112-38; каталог P1–P10 —
`.memory_bank/_intake/codex/2026-11-12-bedroom-templates-answer.md`).

Что делает: для 8 комнат (демо 597×293 и 450×293, UK 377×561 / 396×360 / 244×333, экзамен r10 и r12, условная
300×300) и назначений couple / single / guest / office / child:7-12 (+ single_narrow) перебирает целые составы
по уровням (A → B → …) с РЕАЛЬНЫМИ размерами товаров банка `sets-bedroom.json`, проверяет проходы и рисует вид сверху
в масштабе: стены, дверь с дугой, окно, радиатор, предметы, зоны проходов, путь от двери; нарушение — красной штриховкой.
Числа норм — из `services/planner-solver/rules/occupancy.json` (distances_cm); проход у двери 76 — как в
`planner/validate.py:check_openings`; путь дверь→кровать/окно 75 — из ответа Codex (M4(2)).

  python bedroom_schemes.py OUT_DIR      # → OUT_DIR/*.png, sheet-1.png (sheet-2.png), matrix.md, results.json

Только чтение банка и правил; солвер не вызывается и не меняется.
"""
import json
import math
import os
import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
MAIN_SCOUT = Path('/home/pakar/igor/remlab/tools/scout')   # sets-bedroom.json не в git — берём из основной копии


def data_path(name):
    p = HERE / name
    return p if p.exists() else MAIN_SCOUT / name


# ---------------------------------------------------------------- нормы (одно число — одно место: occupancy.json)
OCC = json.load(open(ROOT / 'services/planner-solver/rules/occupancy.json'))['distances_cm']
SIDE = float(OCC['bed_side_passage'])            # 75 — бок кровати
FOOT = float(OCC['bed_foot_min'])                # 60 — изножье
HEADZ = float(OCC['bed_head_zone'])              # 50 — место тумбы у изголовья
WARD = float(OCC['wardrobe_hinged_front_min'])   # 90 — перед распашным шкафом
DRESS = float(OCC['dresser_front'][0])           # 76 — перед комодом
DESKZ = float(OCC['desk_chair_clear'])           # 75 — место под стул
DESK_WIN = float(OCC['desk_window_max'])         # 100 — стол от окна (мягко)
RAD_SOFT = float(OCC['bed_radiator_soft'])       # 50 — кровать от радиатора (мягко)
RAD_HARD = float(OCC['sofa_to_radiator_wall'][0])  # 15 — жёсткий зазор у радиатора (validate.check_radiators)
FLOOR_MAX = float(OCC['bedroom_floor_max_pct'])  # 45 % пола (мягко)
DOOR_PASS = 76.0     # planner/validate.py:check_openings — полоса 76 перед дверью (число в коде, не в occupancy)
ROUTE = 75.0         # путь дверь→кровать/окно/стол: Codex/M4(2) 75; в брифе 76 (= passage_secondary_comfort[0])
SAFE_GAP = 3.0       # planner/geometry.py:SAFE_GAP_CM — запас у дуги двери
NS_GAP = 2.0         # зазор кровать–тумба (Codex g=0–5)
WALL_GAP = 10.0      # бок «у стены» — зазор ≤ 10 (bedroom_checks.WALL_GAP_CM)
OPEN_REACH = 45.0    # сколько выдвигается ящик / описывает створка шкафа (эскиз; в правилах нормы нет)
EPS = 0.5
STEP = 10

WALLS = ('south', 'north', 'west', 'east')
WALL_RU = {'north': 'северной', 'south': 'южной', 'west': 'западной', 'east': 'восточной'}
WALL_SHORT = {'north': 'С', 'south': 'Ю', 'west': 'З', 'east': 'В'}
OPPOSITE = {'north': 'south', 'south': 'north', 'west': 'east', 'east': 'west'}

# ---------------------------------------------------------------- товары: реальные SKU банка (sid → размеры из банка)
SKU_IDS = {
    'bed_couple': '112923:3989998131928467167',       # Нордик 160 — самая узкая рама пары в банке (165×203)
    'bed_couple_wide': '114667:13118255813066192472',  # Босс 180 — самая широкая рама пары (192×220)
    'bed_guest': '112923:6700908129700351368',         # Нордик 140 (145×203)
    'bed_single': '112923:11797479388540303245',       # Лория 120 (130×210)
    'bed_narrow': '114667:15381579979776203224',       # Белла Мини 90×200 (рама 108×218) — единственная рама ≤110
    'ns': '112923:8554737095566366752',                # Этчер 45×44
    'ns_compact': '112923:17511413518849295620',       # Мостар 36×38 — самая узкая тумба банка
    'ward_l': '112923:9463680740073283809',            # Висмар 3-153×52
    'ward_m': '112923:10869926247520426495',           # Монсон 3-135×52
    'ward_s': '112923:11239866153546807017',           # Шелтон 2-91×50
    'dresser': '112923:10046668357069746202',          # Монсон комод 80×41 (h 82)
}
COND = {   # роли, которых в банке НЕТ (стол/стул выключены — Codex «Покрытие банком»): рисуем пунктиром как условные
    'desk': {'name': 'Стол рабочий — НЕТ В БАНКЕ (условно 100×50)', 'w': 100.0, 'd': 50.0, 'h': 75.0, 'sid': None},
    'chair': {'name': 'Стул рабочий — НЕТ В БАНКЕ (условно 45×45)', 'w': 45.0, 'd': 45.0, 'h': 85.0, 'sid': None},
}


def load_skus():
    sets = json.load(open(data_path('sets-bedroom.json')))
    idx = {}
    for s in sets:
        for src in ('items', 'alternates'):
            for _role, it in (s.get(src) or {}).items():
                for x in (it if isinstance(it, list) else [it]):
                    if isinstance(x, dict) and x.get('sid') and x.get('w'):
                        idx[x['sid']] = x
    out = {}
    for k, sid in SKU_IDS.items():
        x = idx[sid]
        out[k] = {'name': x['name'].replace('\t', ' '), 'w': float(x['w']), 'd': float(x['d']),
                  'h': float(x.get('h') or 0), 'sid': sid, 'cond': False}
    for k, x in COND.items():
        out[k] = dict(x, cond=True)
    return out, len(sets)


# ---------------------------------------------------------------- комнаты
def _room(rid, title, src, W, D, openings, radiators, notes):
    doors, wins = [], []
    for o in openings:
        op = {'wall': o['wall'], 'off': float(o['offset_cm']), 'width': float(o['width_cm'])}
        if o['kind'] == 'door':
            op['swing'] = float(o.get('swing_cm', o['width_cm']))
            op['hinge'] = o.get('hinge', 'left')
            doors.append(op)
        else:
            op['sill'] = float(o.get('sill_cm', 85))
            wins.append(op)
    rads = [{'wall': r['wall'], 'off': float(r['offset_cm']), 'width': float(r['width_cm']),
             'depth': float(r.get('depth_cm', 12))} for r in radiators]
    return {'id': rid, 'title': title, 'src': src, 'W': float(W), 'D': float(D), 'doors': doors, 'wins': wins,
            'rads': rads, 'notes': notes}


def load_rooms():
    rooms = {}
    f = json.load(open(data_path('flat215-bedrooms.json')))
    for r in f['rooms']:
        k = (r['id'], r['variant'])
        if k == ('bedroom-1', 'registry-17.5'):
            rooms['demo597'] = _room('demo597', 'Демо · спальня 1 · 597×293', 'flat215-bedrooms.json bedroom-1:registry-17.5',
                                     r['w'], r['d'], r['openings'], r['radiators'],
                                     ['петли двери на чертеже не видны — условно у угла', 'радиаторы — типовое решение'])
        if k == ('bedroom-2', 'drawing-180'):
            rooms['demo450'] = _room('demo450', 'Демо · спальня 2 · 450×293', 'flat215-bedrooms.json bedroom-2:drawing-180',
                                     r['w'], r['d'], r['openings'], r['radiators'], [])
    uk = json.load(open(data_path('uk-bedrooms.json')))
    names = {'bedroom-one': ('uk377', 'UK Bedroom One · 377×561'), 'bedroom-two': ('uk396', 'UK Bedroom Two · 396×360'),
             'bedroom-three': ('uk244', 'UK Bedroom Three · 244×333')}
    for r in uk['rooms']:
        rid, title = names[r['id']]
        rooms[rid] = _room(rid, title, f"uk-bedrooms.json {r['id']}", r['w'], r['d'], r['openings'], r['radiators'],
                           ['проёмы правдоподобные, не замер (плана в объявлении нет)', 'петли двери и глубина радиатора 12 — условно'])
    ex = json.load(open(data_path('bedroom-scenes.json')))['rooms']
    for k, title in (('r10', 'Экзамен r10 · 330×300'), ('r12', 'Экзамен r12 · 400×300')):
        r = ex[k]
        rooms[k] = _room(k, title, f'bedroom-scenes.json {k}', r['w'], r['d'], r['openings'], r['radiators'],
                         ['сцена экзамена (синтетика)'])
    rooms['sq300'] = _room('sq300', 'Новая · 300×300 (условная)', 'нет источника — условная',
                           300, 300,
                           [{'kind': 'door', 'wall': 'west', 'offset_cm': 105, 'width_cm': 90, 'swing_cm': 90, 'hinge': 'left'},
                            {'kind': 'window', 'wall': 'north', 'offset_cm': 75, 'width_cm': 150, 'sill_cm': 85}],
                           [{'wall': 'north', 'offset_cm': 90, 'width_cm': 120, 'depth_cm': 12}],
                           ['УСЛОВНАЯ: дверь посередине западной стены, окно по центру северной, радиатор под ним'])
    order = ['demo597', 'demo450', 'uk377', 'uk396', 'uk244', 'r10', 'r12', 'sq300']
    return [rooms[k] for k in order]


# ---------------------------------------------------------------- геометрия (прямоугольники x0,y0,x1,y1; x — восток, y — север)
def wall_len(room, wall):
    return room['W'] if wall in ('south', 'north') else room['D']


def band(room, wall, off, w, d0, d1):
    """Полоса у стены: вдоль стены [off, off+w], вглубь комнаты [d0, d1]."""
    W, D = room['W'], room['D']
    if wall == 'south':
        return (off, d0, off + w, d1)
    if wall == 'north':
        return (off, D - d1, off + w, D - d0)
    if wall == 'west':
        return (d0, off, d1, off + w)
    return (W - d1, off, W - d0, off + w)


def wall_point(room, wall, off, depth=0.0):
    W, D = room['W'], room['D']
    return {'south': (off, depth), 'north': (off, D - depth), 'west': (depth, off), 'east': (W - depth, off)}[wall]


def inter(a, b):
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return (x0, y0, x1, y1) if x1 - x0 > EPS and y1 - y0 > EPS else None


def rdist(a, b):
    dx = max(b[0] - a[2], a[0] - b[2], 0.0)
    dy = max(b[1] - a[3], a[1] - b[3], 0.0)
    return math.hypot(dx, dy)


def pdist(px, py, r):
    dx = max(r[0] - px, 0.0, px - r[2])
    dy = max(r[1] - py, 0.0, py - r[3])
    return math.hypot(dx, dy)


def expand(r, m):
    return (r[0] - m, r[1] - m, r[2] + m, r[3] + m)


def inside(r, room):
    return r[0] >= -EPS and r[1] >= -EPS and r[2] <= room['W'] + EPS and r[3] <= room['D'] + EPS


def clip(r, room):
    return inter(r, (0, 0, room['W'], room['D']))


def area(r):
    return (r[2] - r[0]) * (r[3] - r[1])


def door_geo(room, d):
    """Дуга двери как в planner/geometry.py:swing_polygon: четверть круга у петли, r = min(swing, width) + 3."""
    r = min(d['swing'], d['width']) + SAFE_GAP
    if d['hinge'] == 'left':
        hinge = d['off']
        qbox = band(room, d['wall'], d['off'] - SAFE_GAP, r, 0, r)
    else:
        hinge = d['off'] + d['width']
        qbox = band(room, d['wall'], d['off'] + d['width'] + SAFE_GAP - r, r, 0, r)
    hx, hy = wall_point(room, d['wall'], hinge)
    return {'hinge': (hx, hy), 'r': r, 'qbox': qbox, 'strip': band(room, d['wall'], d['off'], d['width'], 0, DOOR_PASS)}


def swing_hit(rect, g):
    q = inter(rect, g['qbox'])
    if q and pdist(g['hinge'][0], g['hinge'][1], q) < g['r'] - EPS:
        return q
    return None


def swing_cover(rect, g, step=5.0):
    """Доля площади rect под дугой двери (сетка step см)."""
    q = inter(rect, g['qbox'])
    if not q:
        return 0.0
    xs = np.arange(rect[0] + step / 2, rect[2], step)
    ys = np.arange(rect[1] + step / 2, rect[3], step)
    if not len(xs) or not len(ys):
        return 0.0
    X, Y = np.meshgrid(xs, ys)
    qb = g['qbox']
    m = (X >= qb[0]) & (X <= qb[2]) & (Y >= qb[1]) & (Y <= qb[3]) & \
        (np.hypot(X - g['hinge'][0], Y - g['hinge'][1]) < g['r'])
    return float(m.mean())


FOOT_SWING_HARD = 0.15   # дуга двери закрывает ≥15 % полосы у изножья — створка перекрывает подход (T-31: ~35 %)


# ---------------------------------------------------------------- предметы и зоны
def item(room, role, kind, sku, wall, off, group, zone=None):
    it = {'role': role, 'kind': kind, 'sku': sku, 'wall': wall, 'off': off, 'group': group,
          'rect': band(room, wall, off, sku['w'], 0, sku['d']), 'zones': []}
    if zone:
        code, depth, label = zone
        it['zones'].append({'code': code, 'rect': band(room, wall, off, sku['w'], sku['d'], sku['d'] + depth),
                            'label': label, 'kind': kind, 'wall': wall})
    return it


def sleep_group(room, sk, variant, wall, off, ns_side=None):
    """Группа «сон»: кровать изголовьем к стене + тумбы. variant: pair|compact_pair|one_side|solo|corner|narrow_wall."""
    bed = sk['bed']
    B, L = bed['w'], bed['d']
    b = item(room, 'кровать', 'bed', bed, wall, off, 'sleep')
    b['variant'] = variant
    b['side_zone'] = {'lo': band(room, wall, off - SIDE, SIDE, 0, L), 'hi': band(room, wall, off + B, SIDE, 0, L)}
    b['foot_zone'] = band(room, wall, off, B, L, L + FOOT)
    b['gap'] = {'lo': off, 'hi': wall_len(room, wall) - off - B}
    out = [b]
    sides = []
    if variant in ('pair', 'compact_pair'):
        sides = ['lo', 'hi']
    elif ns_side:
        sides = [ns_side]
    ns = sk.get('ns')
    for i, s in enumerate(sides):
        o = off - NS_GAP - ns['w'] if s == 'lo' else off + B + NS_GAP
        out.append(item(room, 'тумба' + (' 2' if i else ''), 'ns', ns, wall, o, 'sleep'))
    return out


def storage_item(room, kind, sku, wall, off):
    if kind == 'wardrobe':
        return item(room, 'шкаф', 'wardrobe', sku, wall, off, 'wardrobe', ('WARDROBE_FRONT', WARD, f'{WARD:.0f}'))
    return item(room, 'комод', 'dresser', sku, wall, off, 'dresser', ('DRESSER_FRONT', DRESS, f'{DRESS:.0f}'))


def desk_group(room, sk, wall, off):
    desk = item(room, 'стол', 'desk', sk['desk'], wall, off, 'work', ('DESK_CHAIR', DESKZ, f'{DESKZ:.0f}'))
    ch = sk['chair']
    c = {'role': 'стул', 'kind': 'chair', 'sku': ch, 'wall': wall, 'off': off + (sk['desk']['w'] - ch['w']) / 2,
         'group': 'work', 'zones': [],
         'rect': band(room, wall, off + (sk['desk']['w'] - ch['w']) / 2, ch['w'], sk['desk']['d'] + 5,
                      sk['desk']['d'] + 5 + ch['d'])}
    return [desk, c]


# ---------------------------------------------------------------- проверки
def V(code, text, regions=(), hard=True, pen=0.0):
    return {'code': code, 'text': text, 'regions': [r for r in regions if r], 'hard': hard, 'pen': pen}


def static_checks(room, geo, it, purpose):
    """Нарушения предмета относительно комнаты (стены, дверь, радиатор, окно) — не зависят от других предметов."""
    out = []
    r = it['rect']
    if not inside(r, room):
        out.append(V('OUT_OF_ROOM', f'«{it["role"]}» выходит за стену', [clip(r, room)]))
    for g in geo['doors']:
        h = swing_hit(r, g)
        if h:
            out.append(V('DOOR_SWING', f'«{it["role"]}» в дуге двери', [h]))
        h = inter(r, g['strip'])
        if h:
            out.append(V('DOOR_PASSAGE', f'«{it["role"]}» в проходе у двери ({DOOR_PASS:.0f})', [h]))
    for rr in geo['rads']:
        if rdist(r, rr) < RAD_HARD - EPS:
            out.append(V('RADIATOR', f'«{it["role"]}» ближе {RAD_HARD:.0f} см к радиатору', [inter(r, expand(rr, RAD_HARD))]))
    for w, ws in zip(room['wins'], geo['wins']):
        if it['sku']['h'] > max(w['sill'], 80) and rdist(r, ws) < 10 - EPS:
            out.append(V('WINDOW_BLOCKED', f'«{it["role"]}» ({it["sku"]["h"]:.0f} см) закрывает окно', [inter(r, expand(ws, 10))]))
    for z in it['zones']:
        if not inside(z['rect'], room):
            out.append(V(z['code'], f'перед «{it["role"]}» нет {z["label"]} см — стена', [z['rect']]))
        for rr in geo['rads']:     # строже солвера: его check_access радиатор в фронт-зоне не видит
            near = band(room, z['wall'], it['off'], it['sku']['w'], it['sku']['d'], it['sku']['d'] + OPEN_REACH)
            h = inter(near, rr)
            if h:      # ящик/створка выдвигается ~45 см — радиатор там мешает открыть
                out.append(V(z['code'], f'перед «{it["role"]}» радиатор ближе {OPEN_REACH:.0f} см — ящик/дверца упрётся', [h]))
            elif inter(z['rect'], rr):
                out.append(V(z['code'] + '_RAD', f'радиатор в дальней части прохода перед «{it["role"]}»', hard=False, pen=10))
    if it['kind'] == 'bed':
        bed_w = it['wall']
        for g in geo['doors']:     # Codex P1 «плохой результат»: изножье в дуге двери — створка бьёт по проходу
            h = swing_hit(it['foot_zone'], g)
            if h:
                cov = swing_cover(it['foot_zone'], g)
                if cov >= FOOT_SWING_HARD:
                    out.append(V('BED_FOOT_IN_SWING', f'изножье кровати в дуге двери (дуга закрывает {cov * 100:.0f} % прохода)', [h]))
                else:   # угол полосы задет краем дуги — бывает, мягко
                    out.append(V('BED_FOOT_SWING_EDGE', 'край дуги двери задевает угол прохода у изножья', hard=False, pen=20))
            for sd in ('lo', 'hi'):
                if swing_hit(it['side_zone'][sd], g):
                    out.append(V('BED_SIDE_IN_SWING', 'проход у бока кровати в дуге двери', hard=False, pen=40))
        if not inside(it['foot_zone'], room):
            out.append(V('BED_FOOT_PASSAGE', f'у изножья нет {FOOT:.0f} см — стена', [it['foot_zone']]))
        for rr in geo['rads']:
            h = inter(it['foot_zone'], rr)
            if h:
                out.append(V('BED_FOOT_PASSAGE', 'у изножья радиатор', [h]))
            if rdist(r, rr) < RAD_SOFT - EPS:
                out.append(V('BED_NEAR_RADIATOR', f'кровать ближе {RAD_SOFT:.0f} см к радиатору', hard=False, pen=30))
        head = band(room, bed_w, it['off'], it['sku']['w'], 0, 1)
        for d in room['doors']:
            if d['wall'] == bed_w:
                if inter(expand(head, 2), band(room, d['wall'], d['off'], d['width'], 0, 1)):
                    out.append(V('BED_HEAD_WALL', 'изголовье закрывает дверь', [head]))
                out.append(V('BED_DOOR_WALL', 'изголовье на стене двери', hard=False, pen=60))
        for w, ws in zip(room['wins'], geo['wins']):
            if w['wall'] == bed_w:
                span = band(room, bed_w, it['off'] - 50, it['sku']['w'] + 100, 0, 1)
                if inter(expand(span, 1), expand(ws, 1)):
                    out.append(V('BED_HEAD_WINDOW', 'изголовье под окном (P6 — исключение)', hard=False, pen=400))
                else:
                    out.append(V('HEAD_WALL_WINDOW', 'изголовье на стене окна', hard=False, pen=40))
    return out


def pair_checks(a, b):
    """Нарушения между двумя предметами: наложение и чужие фронт-зоны (своя группа зон друг другу не мешает)."""
    out = []
    h = inter(a['rect'], b['rect'])
    if h:
        out.append(V('OVERLAP', f'«{a["role"]}» налезает на «{b["role"]}»', [h]))
    for x, y in ((a, b), (b, a)):
        for z in x['zones']:
            if x['group'] == y['group']:
                continue
            h = inter(z['rect'], y['rect'])
            if h:
                out.append(V(z['code'], f'перед «{x["role"]}» нет {z["label"]} см — мешает «{y["role"]}»', [h]))
    for x, y in ((a, b), (b, a)):           # кровать: изножье и «шкаф/комод вплотную к боку у изголовья»
        if x['kind'] != 'bed' or y['group'] == 'sleep':
            continue
        h = inter(x['foot_zone'], y['rect'])
        if h:
            out.append(V('BED_FOOT_PASSAGE', f'у изножья нет {FOOT:.0f} см — мешает «{y["role"]}»', [h]))
    return out


def bed_side_checks(room, geo, items, purpose):
    """Боковые проходы: паре — оба бока по 75; остальным — хотя бы один, второй — к стене (≤10) или тоже 75."""
    out = []
    beds = [i for i in items if i['kind'] == 'bed']
    if not beds:
        return out
    b = beds[0]
    blockers = [i for i in items if i['group'] != 'sleep']
    state = {}
    for s in ('lo', 'hi'):
        z = b['side_zone'][s]
        regs = []
        if not inside(z, room):
            regs.append(z if b['gap'][s] > WALL_GAP else None)
        for rr in geo['rads']:
            regs.append(inter(z, rr))
        for o in blockers:
            h = inter(z, o['rect'])
            if h:
                regs.append(h)
        regs = [r for r in regs if r]
        if b['gap'][s] <= WALL_GAP:
            state[s] = ('wall', [])
        elif not regs and inside(z, room):
            state[s] = ('ok', [])
        else:
            state[s] = ('bad', regs or [clip(z, room)])
        # шкаф/комод вплотную к боку у изголовья: зона тумбы (50) — только для тумбы (Codex no_storage_in_sleep_side_zone)
        hz = band(room, b['wall'], b['off'] - SIDE if s == 'lo' else b['off'] + b['sku']['w'], SIDE, 0, HEADZ)
        for o in blockers:
            h = inter(hz, o['rect'])
            if h and o['kind'] in ('wardrobe', 'dresser', 'desk', 'chair'):
                out.append(V('STORAGE_IN_BED_SIDE', f'«{o["role"]}» у бока кровати в зоне тумбы', [h]))
    both = purpose == 'couple'
    if both:
        for s in ('lo', 'hi'):
            if state[s][0] != 'ok':
                out.append(V('BED_SIDE_PASSAGE', f'нет прохода {SIDE:.0f} у бока кровати (пара — с двух сторон)',
                             state[s][1] or [b['side_zone'][s]]))
    else:
        oks = [s for s in state if state[s][0] == 'ok']
        if not oks:
            regs = [r for s in state for r in state[s][1]]
            out.append(V('BED_SIDE_PASSAGE', f'нет прохода {SIDE:.0f} ни с одного бока', regs))
        for s in state:
            if state[s][0] == 'bad' and oks:
                out.append(V('BED_DEAD_GAP', 'второй бок — ни проход, ни стена (щель)', hard=False, pen=60))
        if purpose in ('single_narrow',) and not any(state[s][0] == 'wall' for s in state):
            out.append(V('BED_NARROW_OFF_WALL', 'узкая кровать не боком к стене', hard=False, pen=150))
    b['side_state'] = {s: state[s][0] for s in state}
    return out


def soft_layout(room, geo, items, purpose):
    out = []
    for it in items:
        if it['kind'] in ('wardrobe', 'dresser'):
            for z in it['zones']:
                for g in geo['doors']:
                    if swing_hit(z['rect'], g):
                        out.append(V('FRONT_IN_SWING', f'фасад «{it["role"]}» в дуге двери', hard=False,
                                     pen=25 if it['kind'] == 'wardrobe' else 10))
            L = wall_len(room, it['wall'])
            out.append(V('STORAGE_MIDWALL', '', hard=False, pen=0.03 * min(it['off'], L - it['off'] - it['sku']['w'])))
            if it['kind'] == 'wardrobe':
                out.append(V('WARDROBE_SIZE', '', hard=False, pen=it.get('size_pen', 0)))
        if it['kind'] == 'desk':
            dmin = min([rdist(it['rect'], ws) for ws in geo['wins']] or [999])
            if dmin > DESK_WIN:
                out.append(V('DESK_FAR_FROM_WINDOW', f'стол дальше {DESK_WIN:.0f} см от окна', hard=False, pen=80 + 0.2 * dmin))
            else:
                out.append(V('DESK_NEAR', '', hard=False, pen=0.1 * dmin))
        if it['kind'] == 'bed':
            L = wall_len(room, it['wall'])
            if it['variant'] in ('pair', 'compact_pair', 'one_side', 'solo'):
                c = it['off'] + it['sku']['w'] / 2
                out.append(V('BED_OFF_CENTER', '', hard=False, pen=0.1 * abs(c - L / 2)))
            else:
                if min(it['gap'].values()) > WALL_GAP:
                    out.append(V('BED_NOT_CORNER', 'односпальная не в углу (P8 — угол)', hard=False, pen=30))
    return out


def evaluate(room, geo, items, purpose, cache):
    vs = []
    for it in items:
        key = (it['kind'], it['wall'], it['off'], it['sku']['w'], it['sku']['d'])
        if key not in cache:
            cache[key] = static_checks(room, geo, it, purpose)
        vs += cache[key]
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i]['group'] == items[j]['group'] and items[i]['group'] in ('sleep', 'work'):
                continue
            vs += pair_checks(items[i], items[j])
    vs += bed_side_checks(room, geo, items, purpose)
    vs += soft_layout(room, geo, items, purpose)
    return vs


def score(vs):
    hard = [v for v in vs if v['hard']]
    return (len(hard), sum(v['pen'] for v in vs))


# ---------------------------------------------------------------- маршруты (сетка 1 см, коридор ROUTE)
def free_mask(room, geo, items):
    W, D = int(room['W']), int(room['D'])
    xs = np.arange(W) + 0.5
    ys = np.arange(D) + 0.5
    X, Y = np.meshgrid(xs, ys)
    r = ROUTE / 2 - 0.5
    free = (X >= r) & (X <= W - r) & (Y >= r) & (Y <= D - r)
    obs = [i['rect'] for i in items] + list(geo['rads'])
    for o in obs:
        dx = np.maximum(np.maximum(o[0] - X, X - o[2]), 0)
        dy = np.maximum(np.maximum(o[1] - Y, Y - o[3]), 0)
        free &= (dx * dx + dy * dy) >= r * r
    return free, X, Y


def route_targets(room, geo, items, X, Y):
    """Цели: кровать (паре — оба бока), окно (каждое), стол."""
    t = []
    beds = [i for i in items if i['kind'] == 'bed']
    if beds:
        b = beds[0]
        st = b.get('side_state', {})
        sides = [s for s in ('lo', 'hi') if st.get(s) == 'ok']
        for s in sides:
            z = b['side_zone'][s]
            hz = band(room, b['wall'], b['off'] - SIDE if s == 'lo' else b['off'] + b['sku']['w'], SIDE, HEADZ, b['sku']['d'])
            m = (X >= hz[0]) & (X <= hz[2]) & (Y >= hz[1]) & (Y <= hz[3])
            t.append(('bed_' + s, 'кровать', m))
    for k, (w, ws) in enumerate(zip(room['wins'], geo['wins'])):
        z = band(room, w['wall'], w['off'] + 20, max(w['width'] - 40, 10), 0, 90)
        m = (X >= z[0]) & (X <= z[2]) & (Y >= z[1]) & (Y <= z[3])
        t.append((f'win{k}', 'окно', m))
    chairs = [i for i in items if i['kind'] == 'chair']
    if chairs:
        c = chairs[0]['rect']
        dx = np.maximum(np.maximum(c[0] - X, X - c[2]), 0)
        dy = np.maximum(np.maximum(c[1] - Y, Y - c[3]), 0)
        t.append(('desk', 'стол', (dx * dx + dy * dy) <= 46 * 46))
    return t


def check_routes(room, geo, items, purpose, want_paths=False):
    free, X, Y = free_mask(room, geo, items)
    lab, _n = ndimage.label(free)
    out, paths = [], []
    starts = []
    for d in room['doors']:
        sx, sy = wall_point(room, d['wall'], d['off'] + d['width'] / 2, ROUTE / 2 + 1)
        starts.append((int(sy), int(sx)))
    targets = route_targets(room, geo, items, X, Y)
    for (sy, sx) in starts:
        L0 = lab[sy, sx] if 0 <= sy < lab.shape[0] and 0 <= sx < lab.shape[1] else 0
        bed_ok = None
        for key, name, m in targets:
            ok = bool(L0 and np.any(m & (lab == L0)))
            if key.startswith('bed'):
                bed_ok = ok if bed_ok is None else (bed_ok and ok if purpose == 'couple' else bed_ok or ok)
                if purpose == 'couple' and not ok:
                    out.append(V('ROUTE_BED', f'нет пути {ROUTE:.0f} от двери к боку кровати', []))
            elif not ok:
                code = 'ROUTE_WINDOW' if key.startswith('win') else 'ROUTE_DESK'
                out.append(V(code, f'нет пути {ROUTE:.0f} от двери к «{name}»', []))
            if want_paths and ok:
                paths.append((key, bfs_path(free, (sy, sx), m)))
        if purpose != 'couple' and bed_ok is False:
            out.append(V('ROUTE_BED', f'нет пути {ROUTE:.0f} от двери к кровати', []))
    return out, paths


def bfs_path(free, start, target):
    """Кратчайший путь по сетке 2 см (для рисунка)."""
    f = free[::2, ::2]
    tg = target[::2, ::2] & f
    sy, sx = start[0] // 2, start[1] // 2
    if not (0 <= sy < f.shape[0] and 0 <= sx < f.shape[1]) or not f[sy, sx]:
        return []
    H, Wd = f.shape
    prev = -np.ones(f.shape, dtype=np.int64)
    prev[sy, sx] = sy * Wd + sx
    q = deque([(sy, sx)])
    end = None
    while q:
        y, x = q.popleft()
        if tg[y, x]:
            end = (y, x)
            break
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < H and 0 <= nx < Wd and f[ny, nx] and prev[ny, nx] < 0:
                prev[ny, nx] = y * Wd + x
                q.append((ny, nx))
    if not end:
        return []
    pts = []
    y, x = end
    while True:
        pts.append((x * 2 + 1.0, y * 2 + 1.0))
        p = prev[y, x]
        py, px = divmod(int(p), Wd)
        if (py, px) == (y, x):
            break
        y, x = py, px
    return pts[::-1]


# ---------------------------------------------------------------- уровни (целые составы, Codex «levels»)
LEVELS = {
    'couple': [
        ('A', 'pair', 'кровать + 2 тумбы + шкаф + комод', {'bed': 'bed_couple', 'ns': 'ns', 'ward': ['ward_l', 'ward_m', 'ward_s'], 'dresser': True}),
        ('B', 'pair', 'кровать + 2 тумбы + шкаф', {'bed': 'bed_couple', 'ns': 'ns', 'ward': ['ward_l', 'ward_m', 'ward_s']}),
        ('C', 'compact_pair', 'кровать + 2 узкие тумбы + комод', {'bed': 'bed_couple', 'ns': 'ns_compact', 'dresser': True}),
        ('D', 'one_side', 'кровать + 1 тумба + комод', {'bed': 'bed_couple', 'ns': 'ns_compact', 'dresser': True}),
        # T-31 демо 450×293: рама 165 нигде не встаёт без нарушения (изножье в дуге двери / бок < 75) — шаг вниз по размеру кровати
        ('E', 'pair', 'кровать 140 + 2 тумбы + шкаф + комод', {'bed': 'bed_guest', 'ns': 'ns', 'ward': ['ward_l', 'ward_m', 'ward_s'], 'dresser': True}),
        ('F', 'compact_pair', 'кровать 140 + 2 узкие тумбы + комод', {'bed': 'bed_guest', 'ns': 'ns_compact', 'dresser': True}),
        ('G', 'compact_pair', 'кровать + 2 узкие тумбы, БЕЗ хранения (набор неполный)', {'bed': 'bed_couple', 'ns': 'ns_compact'}),
    ],
    'single': [
        ('A', 'corner', 'кровать в углу + тумба + шкаф + комод', {'bed': 'bed_single', 'ns': 'ns', 'ward': ['ward_m', 'ward_s'], 'dresser': True}),
        ('B', 'corner', 'кровать + тумба + шкаф', {'bed': 'bed_single', 'ns': 'ns', 'ward': ['ward_m', 'ward_s']}),
        ('C', 'corner', 'кровать + тумба + комод', {'bed': 'bed_single', 'ns': 'ns', 'dresser': True}),
        ('D', 'corner', 'кровать + комод', {'bed': 'bed_single', 'dresser': True}),
        ('E', 'corner', 'только кровать (набор неполный)', {'bed': 'bed_single'}),
    ],
    'guest': [
        ('A', 'corner', 'кровать 140 в углу + тумба + шкаф + комод', {'bed': 'bed_guest', 'ns': 'ns', 'ward': ['ward_m', 'ward_s'], 'dresser': True}),
        ('B', 'corner', 'кровать 140 + тумба + комод', {'bed': 'bed_guest', 'ns': 'ns', 'dresser': True}),
        ('C', 'corner', 'кровать 140 + комод', {'bed': 'bed_guest', 'dresser': True}),
        ('D', 'corner', 'только кровать 140 (набор неполный)', {'bed': 'bed_guest'}),
    ],
    'single_narrow': [
        ('A', 'narrow_wall', 'узкая 90 боком к стене + тумба + узкий шкаф', {'bed': 'bed_narrow', 'ns': 'ns_compact', 'ward': ['ward_s']}),
        ('B', 'narrow_wall', 'узкая 90 + тумба + комод', {'bed': 'bed_narrow', 'ns': 'ns_compact', 'dresser': True}),
        ('C', 'narrow_wall', 'узкая 90 + комод', {'bed': 'bed_narrow', 'dresser': True}),
        ('D', 'narrow_wall', 'только узкая 90 (набор неполный)', {'bed': 'bed_narrow'}),
    ],
    'office': [
        ('A', 'corner', 'стол+стул у окна + кровать 120 + шкаф', {'desk': True, 'bed': 'bed_single', 'ward': ['ward_m', 'ward_s']}),
        ('B', 'corner', 'стол+стул + кровать 120 + комод', {'desk': True, 'bed': 'bed_single', 'dresser': True}),
        ('C', 'corner', 'стол+стул + кровать 120', {'desk': True, 'bed': 'bed_single'}),
        ('D', None, 'стол+стул + шкаф (без кровати)', {'desk': True, 'ward': ['ward_m', 'ward_s']}),
    ],
    'child:7-12': [
        ('A', 'corner', 'стол+стул у окна + кровать 90 + тумба + шкаф', {'desk': True, 'bed': 'bed_narrow', 'ns': 'ns_compact', 'ward': ['ward_s']}),
        ('B', 'corner', 'стол+стул + кровать 90 + комод', {'desk': True, 'bed': 'bed_narrow', 'dresser': True}),
        ('C', 'corner', 'стол+стул + кровать 90', {'desk': True, 'bed': 'bed_narrow'}),
    ],
}
PURPOSE_RU = {'couple': 'пара', 'single': 'один взрослый', 'guest': 'гостевая', 'single_narrow': 'UK single (узкая)',
              'office': 'спальня-кабинет', 'child:7-12': 'детская 7–12'}
TPL_RU = {'P1': 'пара, ось напротив двери', 'P2': 'пара, изголовье сбоку от двери', 'P3': 'длинная узкая, кровать поперёк',
          'P4': 'длинная узкая, кровать вдоль', 'P5': 'малый квадрат', 'P6': 'изголовье у окна (исключение)',
          'P7': 'спальня-кабинет', 'P8': 'кровать в углу', 'P9': 'UK single у стены', 'P10': 'детская 7–12'}
CODE_RU = {
    'OUT_OF_ROOM': 'не влезает в стены', 'OVERLAP': 'предметы налезают друг на друга', 'DOOR_SWING': 'предмет в дуге двери',
    'DOOR_PASSAGE': f'предмет в проходе у двери ({DOOR_PASS:.0f})', 'RADIATOR': f'ближе {RAD_HARD:.0f} см к радиатору',
    'WINDOW_BLOCKED': 'высокий предмет закрывает окно', 'BED_SIDE_PASSAGE': f'нет прохода {SIDE:.0f} у бока кровати',
    'BED_FOOT_PASSAGE': f'нет {FOOT:.0f} у изножья', 'WARDROBE_FRONT': f'нет {WARD:.0f} перед шкафом',
    'DRESSER_FRONT': f'нет {DRESS:.0f} перед комодом', 'DESK_CHAIR': f'нет {DESKZ:.0f} под стул у стола',
    'STORAGE_IN_BED_SIDE': 'шкаф/комод вплотную к боку кровати', 'BED_HEAD_WALL': 'изголовье закрывает проём',
    'BED_FOOT_IN_SWING': 'изножье кровати в дуге двери',
    'ROUTE_BED': f'нет пути {ROUTE:.0f} от двери к кровати', 'ROUTE_WINDOW': f'нет пути {ROUTE:.0f} от двери к окну',
    'ROUTE_DESK': f'нет пути {ROUTE:.0f} от двери к столу',
}


def wall_offsets(room, wall, w, step=STEP, extra=()):
    L = wall_len(room, wall)
    if w > L + EPS:
        return []
    xs = set(range(0, int(L - w) + 1, step))
    xs.add(round(L - w, 1))
    for x in extra:
        if 0 <= x <= L - w:
            xs.add(round(x, 1))
    ops = [o for o in room['doors'] + room['wins'] + room['rads'] if o['wall'] == wall]
    for o in ops:
        for x in (o['off'] - w - 1, o['off'] + o['width'] + 1, o['off'] - w - 16, o['off'] + o['width'] + 16):
            if 0 <= x <= L - w:
                xs.add(round(x, 1))
    for d in room['doors']:   # вплотную к дуге двери на соседних стенах
        r = min(d['swing'], d['width']) + SAFE_GAP + 1
        for x in (r, L - r - w):
            if 0 <= x <= L - w:
                xs.add(round(x, 1))
    return sorted(xs)


def gen_sleep(room, sk, variant):
    out = []
    bed = sk['bed']
    geo = room['_geo']
    B = bed['w']
    for wall in WALLS:
        L = wall_len(room, wall)
        # шаг 5 + «впритык» к краям препятствий (полоса двери, дуга, радиатор ± 15): у пары в малой комнате
        # запас бывает в 2 см (r10), шагом его не поймать
        ax = (0, 2) if wall in ('south', 'north') else (1, 3)
        snaps = [SIDE, L - B - SIDE, (L - B) / 2]
        obst = [g['strip'] for g in geo['doors']] + [g['qbox'] for g in geo['doors']] + \
               [expand(r, RAD_HARD) for r in geo['rads']] + list(geo['rads'])
        for o in obst:
            a, b = o[ax[0]], o[ax[1]]
            snaps += [b, b + SIDE, a - B, a - B - SIDE]
        for off in wall_offsets(room, wall, B, step=5, extra=snaps):
            if variant in ('corner', 'narrow_wall'):
                choices = [None]
                if 'ns' in sk:
                    choices = ['lo', 'hi']
            elif variant == 'one_side':
                choices = ['lo', 'hi']
            else:
                choices = [None]
            for c in choices:     # narrow_wall не у стены — мягко (BED_NARROW_OFF_WALL), как в солвере
                out.append(sleep_group(room, sk, variant, wall, off, c))
    return out


def gen_wall_items(room, kind, skus):
    out = []
    for k, sku in enumerate(skus):
        for wall in WALLS:
            for off in wall_offsets(room, wall, sku['w']):
                it = storage_item(room, kind, sku, wall, off)
                it['size_pen'] = 8 * k
                out.append([it])
    return out


def gen_desk(room, sk):
    return [desk_group(room, sk, wall, off) for wall in WALLS for off in wall_offsets(room, wall, sk['desk']['w'])]


def sig(items):
    return tuple(sorted((i['kind'], i['wall'], int(i['off'] // 30), i['sku']['w']) for i in items if i['kind'] != 'chair'))


def search(room, geo, purpose, level, skus, beam=36, bed_override=None, bed_wall=None):
    """bed_wall — принудительно изголовье на эту стену (для схемы «было» как в демо)."""
    _lid, variant, _desc, spec = level
    sk = {}
    if spec.get('bed'):
        sk['bed'] = skus[bed_override or spec['bed']]
    if spec.get('ns'):
        sk['ns'] = skus[spec['ns']]
    if spec.get('desk'):
        sk['desk'], sk['chair'] = skus['desk'], skus['chair']
    stages = []
    if spec.get('desk'):
        stages.append(('desk', gen_desk(room, sk)))
    if spec.get('bed'):
        cands = gen_sleep(room, sk, variant)
        if bed_wall:     # (стена, 'center') — как ставит прод-солвер: по центру стены (bedroom.json bed_center_wall)
            wall, mode = bed_wall
            def _ok(c):
                b = next((i for i in c if i['kind'] == 'bed'), None)
                if not b or b['wall'] != wall:
                    return False
                return mode != 'center' or abs(b['off'] - (wall_len(room, wall) - b['sku']['w']) / 2) <= 3
            cands = [c for c in cands if _ok(c)]
        stages.append(('sleep', cands))
    if spec.get('ward'):
        stages.append(('wardrobe', gen_wall_items(room, 'wardrobe', [skus[w] for w in spec['ward']])))
    if spec.get('dresser'):
        stages.append(('dresser', gen_wall_items(room, 'dresser', [skus['dresser']])))
    cache = {}
    states = [([], (0, 0.0))]
    for name, cands in stages:
        nxt = {}
        for items, _ in states:
            for c in cands:
                its = items + [dict(x) for x in c]
                vs = evaluate(room, geo, its, purpose, cache)
                sc = score(vs)
                k = sig(its)
                if k not in nxt or sc < nxt[k][1]:
                    nxt[k] = (its, sc)
        ranked = sorted(nxt.values(), key=lambda t: t[1])
        if name in ('sleep', 'desk'):        # разнообразие: лучшие по каждой стене, иначе луч съедает одна стена
            per = {}
            keep = []
            for its, sc in ranked:
                w = [i['wall'] for i in its if i['kind'] in ('bed', 'desk')]
                key = tuple(w)
                if per.get(key, 0) < beam // 4 + 2:
                    per[key] = per.get(key, 0) + 1
                    keep.append((its, sc))
            ranked = keep
        # путь от двери проверяем уже на частичном составе: иначе луч заполняют составы, где шкаф отрезал окно
        good, bad, checks = [], [], 0
        for its, sc in ranked:
            if len(good) >= beam or checks >= 160:
                break
            if sc[0] == 0:
                checks += 1
                evaluate(room, geo, its, purpose, cache)        # обновить side_state кровати
                rv, _ = check_routes(room, geo, its, purpose)
                if rv:
                    bad.append((its, (sc[0] + len(rv), sc[1])))
                    continue
            good.append((its, sc))
        states = (good + sorted(bad, key=lambda t: t[1]))[:beam] if good else ranked[:beam]
    best = None
    dbg = os.environ.get('SCHEMES_DEBUG') == f"{room['id']}|{purpose}|{level[0]}"
    for items, sc in states:
        vs = evaluate(room, geo, items, purpose, cache)
        if sc[0] == 0:
            rv, _ = check_routes(room, geo, items, purpose)
            vs = vs + rv
        if dbg:
            print('DBG', sc, [(i['kind'], i['wall'], i['off']) for i in items], [v['code'] for v in vs if v['hard']])
        sc2 = score(vs)
        if best is None or sc2 < best[1]:
            best = (items, sc2, vs)
        if sc2[0] == 0:
            break
    items, sc, vs = best
    if sc[0] > 0:   # для рисунка «почему не влезло» — маршруты тоже
        rv, _ = check_routes(room, geo, items, purpose)
        vs = vs + [v for v in rv if v['code'] not in {x['code'] for x in vs}]
        sc = score(vs)
    return {'items': items, 'score': sc, 'vs': vs, 'ok': sc[0] == 0, 'level': level, 'purpose': purpose, 'sk': sk}


def classify(room, res):
    p = res['purpose']
    if p == 'office':
        return 'P7'
    if p.startswith('child'):
        return 'P10'
    if p == 'single_narrow':
        return 'P9'
    beds = [i for i in res['items'] if i['kind'] == 'bed']
    if not beds:
        return '—'
    b = beds[0]
    W, D = room['W'], room['D']
    aspect = max(W, D) / min(W, D)
    short_head = wall_len(room, b['wall']) <= min(W, D) + EPS
    if p in ('single', 'guest'):
        if aspect >= 1.4 and short_head is False:
            return 'P4' if min(b['gap'].values()) <= WALL_GAP else 'P8'
        return 'P8'
    if any(v['code'] == 'BED_HEAD_WINDOW' for v in res['vs']):
        return 'P6'
    if W * D / 1e4 <= 11.5:
        return 'P5'
    if aspect >= 1.4 and short_head:
        return 'P3'
    if any(d['wall'] == OPPOSITE[b['wall']] for d in room['doors']):
        return 'P1'
    return 'P2'


def describe(room, res):
    parts = []
    for it in res['items']:
        w = WALL_RU[it['wall']]
        L = wall_len(room, it['wall'])
        if it['kind'] == 'bed':
            tags = []
            if any(d['wall'] == it['wall'] for d in room['doors']):
                tags.append('стена двери')
            if any(x['wall'] == it['wall'] for x in room['wins']):
                tags.append('стена окна')
            if any(d['wall'] == OPPOSITE[it['wall']] for d in room['doors']):
                tags.append('напротив двери')
            if not tags:
                tags.append('глухая')
            corner = min(it['gap'].values()) <= WALL_GAP
            parts.append(f"изголовье на {w} стене ({', '.join(tags)}){', в углу' if corner else ''}")
        elif it['kind'] == 'wardrobe':
            parts.append(f"шкаф {it['sku']['w']:.0f} на {w}")
        elif it['kind'] == 'dresser':
            parts.append(f"комод на {w}")
        elif it['kind'] == 'desk':
            parts.append(f"стол на {w}")
    return '; '.join(parts)


def hard_reasons(res):
    seen = []
    for v in res['vs']:
        if v['hard']:
            t = CODE_RU.get(v['code'], v['code'])
            if t not in seen:
                seen.append(t)
    return seen


# ---------------------------------------------------------------- рисунок (PIL)
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
FONTB = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
_fc = {}


def font(sz, bold=False):
    k = (sz, bold)
    if k not in _fc:
        _fc[k] = ImageFont.truetype(FONTB if bold else FONT, sz)
    return _fc[k]


ZONE_COL = {'side': (67, 160, 71, 70), 'foot': (67, 160, 71, 45), 'WARDROBE_FRONT': (30, 136, 229, 60),
            'DRESSER_FRONT': (142, 36, 170, 55), 'DESK_CHAIR': (251, 140, 0, 65), 'door': (255, 193, 7, 80)}
ITEM_COL = {'bed': (215, 196, 163), 'ns': (166, 124, 82), 'wardrobe': (144, 164, 174), 'dresser': (179, 157, 219),
            'desk': (255, 224, 178), 'chair': (255, 204, 128)}
ITEM_RU = {'bed': 'Кровать', 'ns': 'Тумба', 'wardrobe': 'Шкаф', 'dresser': 'Комод', 'desk': 'Стол', 'chair': 'Стул'}
ITEM_SHORT = {'bed': 'Кр', 'ns': 'Т', 'wardrobe': 'Ш', 'dresser': 'К', 'desk': 'Ст', 'chair': 'с'}


class Canvas:
    def __init__(self, room, s, ml, mt, extra_w=0, extra_h=0, mr=40, mb=50, min_w=0):
        self.room, self.s, self.ml, self.mt = room, s, ml, mt
        self.w = max(int(ml + room['W'] * s + mr + extra_w), min_w)
        self.h = int(mt + room['D'] * s + mb + extra_h)
        self.img = Image.new('RGB', (self.w, self.h), (255, 255, 255))
        self.ov = Image.new('RGBA', (self.w, self.h), (0, 0, 0, 0))

    def P(self, x, y):
        return (self.ml + x * self.s, self.mt + (self.room['D'] - y) * self.s)

    def R(self, r):
        x0, y0 = self.P(r[0], r[3])
        x1, y1 = self.P(r[2], r[1])
        return [x0, y0, x1, y1]


def draw_hatch(cv, regions, col=(220, 0, 0)):
    if not regions:
        return
    mask = Image.new('L', (cv.w, cv.h), 0)
    md = ImageDraw.Draw(mask)
    for r in regions:
        r = clip(r, cv.room) or r
        md.rectangle(cv.R(r), fill=255)
    hatch = Image.new('RGBA', (cv.w, cv.h), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hatch)
    for k in range(-cv.h, cv.w, 9):
        hd.line([(k, 0), (k + cv.h, cv.h)], fill=col + (235,), width=2)
    hd2 = Image.new('RGBA', (cv.w, cv.h), (0, 0, 0, 0))
    hd2.paste(hatch, (0, 0), mask)
    cv.img.paste(hd2, (0, 0), hd2)
    d = ImageDraw.Draw(cv.img)
    for r in regions:
        r = clip(r, cv.room) or r
        d.rectangle(cv.R(r), outline=col, width=2)


def text_c(d, xy, txt, f, fill=(20, 20, 20)):
    bb = d.multiline_textbbox((0, 0), txt, font=f, align='center')
    d.multiline_text((xy[0] - (bb[2] - bb[0]) / 2, xy[1] - (bb[3] - bb[1]) / 2), txt, font=f, fill=fill, align='center')


def render(room, res, s, compact=False, title=None, subtitle=None, foot_lines=None, paths=None):
    fs = 15 if compact else 14
    mt = 96 if compact else 92
    cv = Canvas(room, s, ml=56, mt=mt, mr=36, mb=40 + (len(foot_lines or []) * (fs + 9) + 12),
                min_w=640 if compact else 980)
    W, D = room['W'], room['D']
    geo = room['_geo']
    d = ImageDraw.Draw(cv.img)
    # сетка 50 см
    for x in range(0, int(W) + 1, 50):
        d.line([cv.P(x, 0), cv.P(x, D)], fill=(225, 225, 225) if x % 100 else (200, 200, 200), width=1)
    for y in range(0, int(D) + 1, 50):
        d.line([cv.P(0, y), cv.P(W, y)], fill=(225, 225, 225) if y % 100 else (200, 200, 200), width=1)
    # подписи сетки
    fsm = font(11 if not compact else 12)
    for x in range(0, int(W) + 1, 100):
        text_c(d, (cv.P(x, 0)[0], cv.P(x, 0)[1] + 14), str(x), fsm, (120, 120, 120))
    for y in range(0, int(D) + 1, 100):
        p = cv.P(0, y)
        text_c(d, (p[0] - 22, p[1]), str(y), fsm, (120, 120, 120))
    # зоны (полупрозрачно)
    od = ImageDraw.Draw(cv.ov)
    zlabels = []
    for g in geo['doors']:
        od.rectangle(cv.R(g['strip']), fill=ZONE_COL['door'])
        zlabels.append((g['strip'], f'{DOOR_PASS:.0f}', None))
    for it in res['items']:
        if it['kind'] == 'bed':
            st = it.get('side_state', {})
            for sd in ('lo', 'hi'):
                if st.get(sd) == 'wall':
                    continue
                z = clip(it['side_zone'][sd], room)
                if z:
                    od.rectangle(cv.R(z), fill=ZONE_COL['side'])
                    zlabels.append((z, f'{SIDE:.0f}', None))
            z = clip(it['foot_zone'], room)
            if z:
                od.rectangle(cv.R(z), fill=ZONE_COL['foot'])
                zlabels.append((z, f'{FOOT:.0f}', None))
        for z in it['zones']:
            zc = clip(z['rect'], room)
            if zc:
                od.rectangle(cv.R(zc), fill=ZONE_COL[z['code']])
                zlabels.append((zc, z['label'], z.get('wall')))
    cv.img.paste(cv.ov, (0, 0), cv.ov)
    d = ImageDraw.Draw(cv.img)
    # дуги дверей
    for dd, g in zip(room['doors'], geo['doors']):
        hx, hy = g['hinge']
        r = min(dd['swing'], dd['width'])
        bb = cv.R((hx - r, hy - r, hx + r, hy + r))
        # PIL: углы по часовой от +x экрана (y экрана вниз, север — вверху)
        if dd['wall'] == 'south':
            a0, a1 = (270, 360) if dd['hinge'] == 'left' else (180, 270)
        elif dd['wall'] == 'north':
            a0, a1 = (0, 90) if dd['hinge'] == 'left' else (90, 180)
        elif dd['wall'] == 'west':
            a0, a1 = (270, 360) if dd['hinge'] == 'left' else (0, 90)
        else:
            a0, a1 = (180, 270) if dd['hinge'] == 'left' else (90, 180)
        d.arc(bb, a0, a1, fill=(120, 90, 0), width=2)
        # створка в открытом положении — перпендикулярно стене
        inx, iny = {'south': (0, 1), 'north': (0, -1), 'west': (1, 0), 'east': (-1, 0)}[dd['wall']]
        d.line([cv.P(hx, hy), cv.P(hx + inx * r, hy + iny * r)], fill=(120, 90, 0), width=3)
    # предметы
    for it in res['items']:
        r = cv.R(it['rect'])
        col = ITEM_COL[it['kind']]
        if it['sku'].get('cond'):
            d.rectangle(r, fill=col)
            x0, y0, x1, y1 = r
            for k in range(int(x0), int(x1), 10):   # пунктир — условный предмет (нет в банке)
                d.line([(k, y0), (min(k + 5, x1), y0)], fill=(200, 80, 0), width=2)
                d.line([(k, y1), (min(k + 5, x1), y1)], fill=(200, 80, 0), width=2)
            for k in range(int(y0), int(y1), 10):
                d.line([(x0, k), (x0, min(k + 5, y1))], fill=(200, 80, 0), width=2)
                d.line([(x1, k), (x1, min(k + 5, y1))], fill=(200, 80, 0), width=2)
        else:
            d.rectangle(r, fill=col, outline=(60, 60, 60), width=2)
    # нарушения — красная штриховка
    draw_hatch(cv, [rg for v in res['vs'] if v['hard'] for rg in v['regions']])
    d = ImageDraw.Draw(cv.img)
    # маршруты
    pcol = {'bed': (27, 94, 32), 'win': (13, 71, 161), 'desk': (230, 81, 0)}
    for key, pts in (paths or []):
        if len(pts) < 2:
            continue
        c = pcol['bed' if key.startswith('bed') else 'win' if key.startswith('win') else 'desk']
        pp = [cv.P(x, y) for x, y in pts[::3]] + [cv.P(*pts[-1])]
        for i in range(0, len(pp) - 1, 2):
            d.line([pp[i], pp[i + 1]], fill=c, width=3)
        ex, ey = pp[-1]
        d.ellipse([ex - 5, ey - 5, ex + 5, ey + 5], fill=c)
    # стены
    x0, y0 = cv.P(0, D)
    x1, y1 = cv.P(W, 0)
    d.rectangle([x0, y0, x1, y1], outline=(30, 30, 30), width=5)
    for dd in room['doors']:
        a = cv.P(*wall_point(room, dd['wall'], dd['off']))
        b = cv.P(*wall_point(room, dd['wall'], dd['off'] + dd['width']))
        d.line([a, b], fill=(255, 255, 255), width=7)
    for w in room['wins']:
        a = cv.P(*wall_point(room, w['wall'], w['off']))
        b = cv.P(*wall_point(room, w['wall'], w['off'] + w['width']))
        d.line([a, b], fill=(79, 195, 247), width=8)
    for rr in geo['rads']:
        d.rectangle(cv.R(rr), fill=(255, 112, 67), outline=(191, 54, 12))
    # подписи зон
    fz = font(12 if not compact else 13, True)
    for z, lab, zw in zlabels:
        rr = cv.R(z)
        if (rr[2] - rr[0]) > 22 and (rr[3] - rr[1]) > 14:
            cx, cy = (rr[0] + rr[2]) / 2, (rr[1] + rr[3]) / 2
            k = 9 * cv.s       # подпись фронт-зоны — у дальнего края, чтобы не налезала на стул/предмет
            if zw == 'south':
                cy = rr[1] + k
            elif zw == 'north':
                cy = rr[3] - k
            elif zw == 'west':
                cx = rr[2] - k
            elif zw == 'east':
                cx = rr[0] + k
            text_c(d, (cx, cy), lab, fz, (60, 60, 60))
    # подписи предметов
    fi = font(fs, True)
    fi2 = font(fs - 2)
    for it in res['items']:
        r = cv.R(it['rect'])
        wpx, hpx = r[2] - r[0], r[3] - r[1]
        dims = f"{it['sku']['w']:.0f}×{it['sku']['d']:.0f}"
        name = ITEM_RU[it['kind']]
        if it['kind'] == 'bed':
            short = it['sku']['name'].replace('Кровать divan.ru ', '').replace('Кровать+ПМ ', '').split(' Велюр')[0]
            short = ' '.join(short.split()[:2])
            txt = f"{name}\n{short}\n{dims}"
        elif it['sku'].get('cond'):
            txt = f"{name}\nнет в банке" if wpx > 80 else ITEM_SHORT[it['kind']]
        else:
            txt = f"{name}\n{dims}"
        bb = d.multiline_textbbox((0, 0), txt, font=fi, align='center')
        rt = f"{name} {dims}"          # узкий высокий предмет (шкаф боком на схеме) — подпись поворотом, размер не теряется
        rb = d.textbbox((0, 0), rt, font=fi2)
        if (bb[2] - bb[0] > wpx - 4 or bb[3] - bb[1] > hpx - 4) and hpx > wpx and \
                rb[2] - rb[0] <= hpx - 6 and rb[3] - rb[1] <= wpx - 4 and not it['sku'].get('cond'):
            lab = Image.new('RGBA', (int(rb[2] - rb[0]) + 4, int(rb[3]) + 4), (255, 255, 255, 0))
            ImageDraw.Draw(lab).text((2 - rb[0], 1), rt, font=fi2, fill=(20, 20, 20))
            lab = lab.rotate(90, expand=True)
            cv.img.paste(lab, (int((r[0] + r[2] - lab.width) / 2), int((r[1] + r[3] - lab.height) / 2)), lab)
            d = ImageDraw.Draw(cv.img)
        elif bb[2] - bb[0] > wpx - 4 or bb[3] - bb[1] > hpx - 4:
            txt = f"{ITEM_SHORT[it['kind']]}\n{dims}"
            bb = d.multiline_textbbox((0, 0), txt, font=fi2, align='center')
            if bb[2] - bb[0] > wpx - 2 or bb[3] - bb[1] > hpx - 2:
                txt = ITEM_SHORT[it['kind']]
            text_c(d, ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2), txt, fi2)
        else:
            text_c(d, ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2), txt, fi)
    # подписи проёмов
    fo = font(12 if not compact else 13)
    for w in room['wins']:
        p = cv.P(*wall_point(room, w['wall'], w['off'] + w['width'] / 2))
        dx, dy = {'south': (0, 14), 'north': (0, -14), 'west': (-26, 0), 'east': (26, 0)}[w['wall']]
        text_c(d, (p[0] + dx, p[1] + dy), f"окно\n{w['width']:.0f}" if w['wall'] in ('west', 'east') else f"окно {w['width']:.0f}", fo, (13, 71, 161))
    for dd in room['doors']:
        p = cv.P(*wall_point(room, dd['wall'], dd['off'] + dd['width'] / 2))
        dx, dy = {'south': (0, 14), 'north': (0, -14), 'west': (-26, 0), 'east': (26, 0)}[dd['wall']]
        text_c(d, (p[0] + dx, p[1] + dy), f"дверь\n{dd['width']:.0f}" if dd['wall'] in ('west', 'east') else f"дверь {dd['width']:.0f}", fo, (120, 90, 0))
    # размеры комнаты
    fdim = font(14 if not compact else 15, True)
    text_c(d, ((x0 + x1) / 2, y0 - 34), f'{W:.0f} см', fdim, (40, 40, 40))
    d.line([(x0, y0 - 22), (x1, y0 - 22)], fill=(80, 80, 80), width=1)
    for xx in (x0, x1):
        d.line([(xx, y0 - 27), (xx, y0 - 17)], fill=(80, 80, 80), width=1)
    dimv = Image.new('RGBA', (120, 24), (255, 255, 255, 0))
    ImageDraw.Draw(dimv).text((2, 2), f'{D:.0f} см', font=fdim, fill=(40, 40, 40))
    dimv = dimv.rotate(90, expand=True)
    cv.img.paste(dimv, (int(x0 - 54), int((y0 + y1) / 2 - 60)), dimv)
    text_c(d, (x1 + 18, y0 - 34), 'С↑', font(13, True), (90, 90, 90))
    # заголовок
    d.text((10, 6), title or room['title'], font=font(20 if compact else 19, True), fill=(10, 10, 10))
    if subtitle:
        d.text((10, 32), subtitle, font=font(15 if compact else 14), fill=(50, 50, 50))
    # низ
    y = y1 + 26
    for ln in foot_lines or []:
        col = (198, 40, 40) if ln.startswith('✗') else (27, 94, 32) if ln.startswith('✓') else (60, 60, 60)
        d.text((10, y), ln, font=font(fs), fill=col)
        y += fs + 9
    return cv.img


# ---------------------------------------------------------------- прогон
MAIN_PURPOSE = {'demo597': 'couple', 'demo450': 'couple', 'uk377': 'couple', 'uk396': 'couple', 'uk244': 'single_narrow',
                'r10': 'couple', 'r12': 'couple', 'sq300': 'couple'}
EXTRA = [('demo450', 'office'), ('uk244', 'child:7-12')]   # показать P7 и P10 на реальных комнатах
BYLO = {'demo450': ('north', 'center')}   # T-31: как стоит пара в демо сейчас (изголовье напротив двери, по центру стены)
MATRIX_PURPOSES = ['couple', 'single', 'guest', 'office', 'child:7-12', 'single_narrow']


def run_purpose(room, purpose, skus):
    """Уровни по порядку; первый, где всё проходит, — выбранный. Отвергнутые — с причинами."""
    tried = []
    for lev in LEVELS[purpose]:
        res = search(room, room['_geo'], purpose, lev, skus)
        tried.append(res)
        if res['ok']:
            return res, tried
    return None, tried


def fmt_vs(res):
    return [v['text'] for v in res['vs'] if v['hard']]


def foot_for(room, res, skus, fail_note=None):
    lines = []
    lev = res['level']
    lines.append(f"Состав ({lev[0]}): {lev[2]}")
    for it in res['items']:
        if it['kind'] == 'chair':
            continue
        s = it['sku']
        sid = f" · {s['sid']}" if s.get('sid') else ''
        lines.append(f"  {ITEM_RU[it['kind']]}: {s['name']} · {s['w']:.0f}×{s['d']:.0f}{sid}")
    if res['ok']:
        lines.append(f"✓ проходы {SIDE:.0f}/{FOOT:.0f}/{WARD:.0f}/{DRESS:.0f}, дверь и путь {ROUTE:.0f} к кровати и окну — проходят")
    else:
        for t in hard_reasons(res)[:4]:
            lines.append(f"✗ {t}")
    used = sum(area(i['rect']) for i in res['items']) / (room['W'] * room['D']) * 100
    lines.append(f"Мебель занимает {used:.0f} % пола (норма ≤ {FLOOR_MAX:.0f} %)")
    soft = [v['text'] for v in res['vs'] if not v['hard'] and v['text']]
    if soft:
        lines.append('Мягко: ' + '; '.join(dict.fromkeys(soft)))
    for n in room['notes']:
        lines.append('Условно: ' + n)
    if fail_note:
        lines.append(fail_note)
    return lines


def main(out, only=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    skus, nsets = load_skus()
    rooms = [r for r in load_rooms() if not only or r['id'] in only]
    for room in rooms:
        room['_geo'] = {'doors': [door_geo(room, d) for d in room['doors']],
                        'rads': [band(room, r['wall'], r['off'], r['width'], 0, r['depth']) for r in room['rads']],
                        'wins': [band(room, w['wall'], w['off'], w['width'], 0, 1) for w in room['wins']]}
    results = {}
    for room in rooms:
        for p in MATRIX_PURPOSES:
            best, tried = run_purpose(room, p, skus)
            results[(room['id'], p)] = (best, tried)
            print(room['id'], p, best['level'][0] if best else 'ОТКАЗ', '|', '; '.join(hard_reasons(tried[0])) if tried and not tried[0]['ok'] else '', flush=True)
        if True:
            best = results[(room['id'], 'couple')][0]
            lev = best['level'] if best else LEVELS['couple'][-1]
            wide = search(room, room['_geo'], 'couple', lev, skus, bed_override='bed_couple_wide')
            results[(room['id'], 'couple_wide')] = (wide if wide['ok'] else None, [wide])
    # «было» (находка T-31): в демо-спальне 450×293 пара стоит изголовьем к северной стене, напротив двери
    was = {}
    for rid, wall in BYLO.items():
        room = next((r for r in rooms if r['id'] == rid), None)
        if room:
            w = search(room, room['_geo'], 'couple', LEVELS['couple'][0], skus, bed_wall=wall)
            w['bylo'] = True
            was[rid] = w
    # рисунки
    panels = []
    for room in rooms:
        jobs = [(MAIN_PURPOSE[room['id']], 'main')] + [(p, 'extra') for rid, p in EXTRA if rid == room['id']]
        for p, kind in jobs:
            best, tried = results[(room['id'], p)]
            a = tried[0]
            drawn = []
            if p == 'couple' and room['id'] in was:
                drawn.append((was[room['id']], 'БЫЛО (демо): кровать по центру — изножье в дуге двери'))
            if best is not None and best is a:
                drawn.append((best, 'ПО ШАБЛОНУ: та же стена, кровать сдвинута от двери'
                              if drawn else None))
            else:
                if not drawn:     # «было» уже показывает, где ломается уровень A
                    drawn.append((a, 'основной уровень A не влезает — красным, где ломается'))
                if best is not None:
                    drawn.append((best, f'ПО ШАБЛОНУ: запасной уровень {best["level"][0]} ({best["level"][2]})'
                                  if drawn and drawn[0][0].get('bylo') else f'запасной уровень {best["level"][0]}'))
                elif p == 'couple':
                    alt, _t = results[(room['id'], 'single')]
                    if alt is not None:
                        drawn.append((alt, 'паре не хватает места ни на одном уровне → для одного (P8)'))
            for res, note in drawn:
                tpl = classify(room, res)
                res['tpl'] = tpl
                tag = (f"{room['id']}-{res['purpose'].replace(':', '')}-{res['level'][0]}"
                       f"{'-bylo' if res.get('bylo') else ''}{'-fail' if not res['ok'] else ''}")
                _rv, paths = check_routes(room, room['_geo'], res['items'], res['purpose'], want_paths=True)
                verdict = '✓ влезает' if res['ok'] else '✗ НЕ влезает'
                title = f"{'БЫЛО · ' if res.get('bylo') else ''}{room['title']} — {tpl} · {res['level'][0]}"
                sub = (f"назначение: {PURPOSE_RU[res['purpose']]} · шаблон {tpl} ({TPL_RU.get(tpl, tpl)}) · "
                       f"сон: {res['level'][1] or 'без кровати'} · {verdict}")
                img = render(room, res, 2.0, title=title, subtitle=sub, foot_lines=foot_for(room, res, skus, note), paths=paths)
                fn = out / f'{tag}.png'
                img.save(fn)
                panels.append({'room': room, 'res': res, 'paths': paths, 'file': fn.name, 'note': note, 'tpl': tpl})
                print('png', fn, flush=True)
    make_sheets(out, panels)
    write_matrix(out, rooms, results, skus, nsets, panels, was)


def make_sheets(out, panels):
    colw = 640
    per = 8
    for si in range(0, len(panels), per):
        chunk = panels[si:si + per]
        imgs = []
        for pn in chunk:
            room, res = pn['room'], pn['res']
            s = min((colw - 100) / room['W'], 520 / room['D'])
            verdict = '✓ влезает' if res['ok'] else '✗ ' + (hard_reasons(res)[0] if hard_reasons(res) else 'не влезает')
            short = room['title'].replace('Демо · ', 'Демо ').replace(' (условная)', '*')
            title = f"{'БЫЛО · ' if res.get('bylo') else ''}{short} — {pn['tpl']} · {res['level'][0]}"
            sub = f"{PURPOSE_RU[res['purpose']]}: {res['level'][2]}"
            fl = [verdict]
            if pn['note']:
                fl.append(pn['note'])
            img = render(room, res, s, compact=True, title=title, subtitle=sub[:70], foot_lines=fl, paths=pn['paths'])
            imgs.append(img)
        rows = [imgs[i:i + 2] for i in range(0, len(imgs), 2)]
        H = sum(max(im.height for im in r) + 16 for r in rows) + 70
        sheet = Image.new('RGB', (colw * 2 + 30, H), (255, 255, 255))
        d = ImageDraw.Draw(sheet)
        n = si // per + 1
        d.text((14, 12), f'Спальня: шаблоны на реальных комнатах (масштаб, сетка 50 см) · лист {n}', font=font(24, True), fill=(0, 0, 0))
        d.text((14, 44), 'зелёное — проход 75/60 у кровати · синее — 90 перед шкафом · фиолетовое — 76 перед комодом · жёлтое — дверь · красная штриховка — нарушение',
               font=font(13), fill=(70, 70, 70))
        y = 70
        for r in rows:
            x = 10
            for im in r:
                sheet.paste(im, (x, y))
                d.rectangle([x, y, x + im.width - 1, y + im.height - 1], outline=(200, 200, 200))
                x += colw + 10
            y += max(im.height for im in r) + 16
        sheet.save(out / f'sheet-{n}.png')
        print('sheet', out / f'sheet-{n}.png', flush=True)


def write_matrix(out, rooms, results, skus, nsets, panels, was=None):
    L = []
    L.append('# Спальня: матрица «комната × назначение» (T-20261112-38, эскиз — не солвер)')
    L.append('')
    L.append(f'Товары — реальные размеры из банка `sets-bedroom.json` ({nsets} наборов): пара — {skus["bed_couple"]["name"]} '
             f'{skus["bed_couple"]["w"]:.0f}×{skus["bed_couple"]["d"]:.0f} (самая узкая рама пары в банке); тумбы {skus["ns"]["w"]:.0f}×{skus["ns"]["d"]:.0f} '
             f'и узкие {skus["ns_compact"]["w"]:.0f}×{skus["ns_compact"]["d"]:.0f}; шкафы {skus["ward_l"]["w"]:.0f}/{skus["ward_m"]["w"]:.0f}/{skus["ward_s"]["w"]:.0f}; '
             f'комод {skus["dresser"]["w"]:.0f}×{skus["dresser"]["d"]:.0f}; один — {skus["bed_single"]["name"]} {skus["bed_single"]["w"]:.0f}×{skus["bed_single"]["d"]:.0f}; '
             f'гостевая — {skus["bed_guest"]["name"]} {skus["bed_guest"]["w"]:.0f}×{skus["bed_guest"]["d"]:.0f}; узкая/детская — {skus["bed_narrow"]["name"]} '
             f'{skus["bed_narrow"]["w"]:.0f}×{skus["bed_narrow"]["d"]:.0f}. Стол и стул в банке НЕТ — условные 100×50 и 45×45.')
    L.append('')
    L.append(f'Нормы: бок кровати {SIDE:.0f} (паре — с двух сторон), изножье {FOOT:.0f}, шкаф {WARD:.0f}, комод {DRESS:.0f}, '
             f'место под стул {DESKZ:.0f}, полоса у двери {DOOR_PASS:.0f}, путь дверь→кровать/окно/стол {ROUTE:.0f}, радиатор ≥{RAD_HARD:.0f}. '
             'Уровень — целый состав (A лучше всего); «отказ» = ни один уровень не прошёл.')
    L.append('')
    for room in rooms:
        L.append(f"## {room['title']}  ({room['W'] * room['D'] / 1e4:.1f} м²)")
        if room['notes']:
            L.append('Условно: ' + '; '.join(room['notes']) + '.')
        L.append('')
        L.append('| Назначение | Шаблон · уровень | Почему так | Что отвергнуто и почему |')
        L.append('|---|---|---|---|')
        for p in MATRIX_PURPOSES:
            best, tried = results[(room['id'], p)]
            rej = []
            for t in tried:
                if t is best:
                    break
                rej.append(f"{t['level'][0]} ({t['level'][2]}): {', '.join(hard_reasons(t)[:2]) or '—'}")
            if best:
                tpl = classify(room, best)
                lev = f"**{tpl}** · {best['level'][0]} · {best['level'][1] or 'без кровати'}"
                why = f"{TPL_RU.get(tpl, tpl)}: {describe(room, best)}"
                if p == 'couple':
                    wide, _ = results[(room['id'], 'couple_wide')]
                    why += f"; с самой широкой рамой банка 192×220 — {'тоже влезает' if wide else 'НЕ влезает'}"
            else:
                lev = '**отказ**'
                why = 'ни один состав не проходит проверки'
            L.append(f"| {PURPOSE_RU[p]} | {lev} | {why} | {'<br>'.join(rej) or '—'} |")
        L.append('')
        if was and room['id'] in was:
            w = was[room['id']]
            best = results[(room['id'], 'couple')][0]
            L.append('**Было → по шаблону (пара, находка T-31):**')
            L.append('')
            L.append('| | Как стоит | Что не так / что стало |')
            L.append('|---|---|---|')
            def _bx(res):
                b = next(i for i in res['items'] if i['kind'] == 'bed')
                return f"кровать {b['sku']['w']:.0f} на x {b['rect'][0]:.0f}–{b['rect'][2]:.0f}, y {b['rect'][1]:.0f}–{b['rect'][3]:.0f}"
            L.append(f"| Было (демо сейчас, по центру стены) | {describe(room, w)}; {_bx(w)} | {', '.join(hard_reasons(w)) or 'проходит'} |")
            if best:
                tpl = classify(room, best)
                L.append(f"| По шаблону {tpl} · {best['level'][0]} | {describe(room, best)}; {_bx(best)} | дуга двери задевает лишь угол полосы у изножья; "
                         "проходы у обоих боков, путь к кровати и окну — проходят |")
            else:
                L.append('| По шаблону | отказ | ни один уровень не проходит |')
            L.append('')
    L.append('## Рисунки')
    for pn in panels:
        L.append(f"- `{pn['file']}` — {pn['room']['title']}, {PURPOSE_RU[pn['res']['purpose']]}, {pn['tpl']} · {pn['res']['level'][0]}"
                 f"{' (НЕ влезает)' if not pn['res']['ok'] else ''}")
    (out / 'matrix.md').write_text('\n'.join(L) + '\n')
    js = {}
    for (rid, p), (best, tried) in results.items():
        js[f'{rid}|{p}'] = {'level': best['level'][0] if best else None, 'tpl': classify(next(r for r in rooms if r['id'] == rid), best) if best else None,
                            'rejected': [{'level': t['level'][0], 'reasons': hard_reasons(t)} for t in tried if t is not best]}
    (out / 'results.json').write_text(json.dumps(js, ensure_ascii=False, indent=1))
    print('matrix', out / 'matrix.md')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1], sys.argv[2].split(',') if len(sys.argv) > 2 else None)   # 2-й аргумент — отбор комнат (отладка)
