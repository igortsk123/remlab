#!/usr/bin/env python3
"""СХЕМЫ ШАБЛОНОВ ГОСТИНОЙ В МАСШТАБЕ — эскизный инструмент для показа владельцу, НЕ солвер
(план `.memory_bank/plans/living-full-01.md` Т0, задача T-20261112-46; каталог LR-C1…L2 — ответ советника
`.memory_bank/_intake/codex/2026-11-12-living-full-templates-answer.md`, разделы 1–3 и 6).

Что делает: для 8 комнат (демо 439×325, малые 350×400 и 300×500, UK lounge 377×420, «Этажи» кухня-гостиная 20,8 м²,
Г-образная 30,25 м², прямоугольная 33 м², 41,6 м²) выбирает шаблон по площади, пропорциям и назначению, перебирает целые
составы по уровням (A → B → …) с РЕАЛЬНЫМИ размерами товаров банка `sets3.json` и рисует вид сверху в масштабе: сетка 50 см,
стены, дверь с дугой, окно, радиатор, предметы, зоны (76 у двери и перед комодом, 60 у стульев, 91 у кухни), пути от двери
(91 — к дивану, кухне и столовой; 76 — к окну; 60 — к креслу и комоду), ось взгляда на ТВ с дистанцией, ковёр с передними
ножками, люстра в центре зоны, шторы, картины на стене; мелочи (подушки, плед, ваза, лампа) — значками на носителе и
врезкой носителя крупно. Нарушение — красной штриховкой; не прошёл уровень — следующий.
Нормы — `services/planner-solver/rules/occupancy.json` (distances_cm). Общая геометрия и рисование — из
`bedroom_schemes.py` (импортом): полосы у стен, дуги дверей, штриховка, путь по сетке, шрифты, холст.

  python living_schemes.py OUT_DIR      # → OUT_DIR/*.png, sheet-1..3.png, matrix.md, results.json

Только чтение банка и правил; солвер не вызывается и не меняется. Без сети и БД.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bedroom_schemes as bs  # noqa: E402
import slot_rules  # noqa: E402
from bedroom_schemes import (EPS, OPPOSITE, RAD_HARD, DOOR_PASS, WALLS, WALL_RU, V, Canvas, area, band,  # noqa: E402
                             bfs_path, clip, door_geo, draw_hatch, expand, font, inter, rdist, swing_hit, text_c,
                             wall_len, wall_offsets, wall_point)

ROOT = HERE.parent.parent
OCC = bs.OCC
P_MAIN = float(OCC['passage_main'][0])                 # 91 — главный маршрут
P_SEC = float(OCC['passage_secondary_comfort'][0])     # 76 — вторичный
P_LOC = float(OCC['passage_secondary_min'])            # 60 — локальный подход
COFFEE_GAP = float(OCC['sofa_coffee_table_preferred'][0])   # 40 — диван → столик
TV_MIN = float(OCC['sofa_tv_cm'][0])                   # 180
TV_HARD = float(OCC['sofa_tv_hard_max'])               # 400
TV_DIAG_MIN = float(OCC['sofa_tv_diagonals'][0])       # 1,2 диагонали
TV_PREF = float(OCC['tv_distance_diag_preferred'])     # 1,6 диагонали
RUG_WALL = float(OCC['rug_to_wall'][0])                # 30
RUG_WALL_SMALL = float(OCC['rug_to_wall_small_room_le16m2'])   # 15 (комната ≤ 16 м²)
ARM_GAP = float(OCC['side_table_to_armrest'][0])       # 5 — торшер у подлокотника
DRESS = float(OCC['dresser_front'][0])                 # 76 — перед комодом
CHAIR_ZONE = max(float(OCC['dining_chair_pullout'][0]), P_LOC)   # 60 — отодвинуть стул (55) / подход (60)
RUG_TUCK = 25.0      # ковёр заходит под фронт дивана (передние ножки на ковре; Codex «tuck_cm»: 25)
ARM_TABLE = 35.0     # кресло от края столика (эскиз; Codex: кресло ≤ 240 от группы)
SEAT_EYE = 0.55      # глаза сидящего — 0,55 глубины дивана от спинки (эскиз)
PLANT_SOFT = 60.0    # кашпо от мебели (Codex: «предпочтительно 60»)
SECTION_D = 95.0     # глубина основной секции углового дивана (у товара — только габарит; условно)
SCREEN_FRAC = 0.9    # экран ≤ 0,9 ширины тумбы (как `lib/viewer3d/scene-extras.ts:tvSpec`)

TPL_RU = {'C1': 'компактная, диван и ТВ напротив', 'C2': 'вытянутая, посадка вдоль длинной стены', 'C3': 'угловой диван',
          'M1': 'диван + кресло', 'O1': 'кухня-гостиная, диван-разделитель', 'O2': 'кухня-гостиная, всё у стен',
          'L1': 'большая П-композиция (два кресла)', 'L2': 'два дивана Г + кресло'}
CODE_RU = {
    'OUT_OF_ROOM': 'не влезает в стены', 'OVERLAP': 'предметы налезают друг на друга', 'DOOR_SWING': 'предмет в дуге двери',
    'DOOR_PASSAGE': f'предмет в проходе у двери ({DOOR_PASS:.0f})', 'PORTAL': 'предмет в проходе в пристройку',
    'RADIATOR': f'ближе {RAD_HARD:.0f} см к радиатору', 'WINDOW_BLOCKED': 'высокий предмет закрывает окно',
    'DRESSER_FRONT': f'нет {DRESS:.0f} перед комодом', 'CHAIR_ZONE': f'нет {CHAIR_ZONE:.0f} отодвинуть стул',
    'KITCHEN_AISLE': f'занят проход {P_MAIN:.0f} у кухни', 'RUG_TABLE': 'столик не целиком на ковре',
    'RUG_OUT': 'ковёр не влезает', 'RUG_UNDER': 'ковёр заходит под комод/тумбу/кашпо','OVERLAP_RUG': 'столовая на ковре гостиной', 'TV_FAR': f'ТВ дальше {TV_HARD:.0f} см',
    'TV_NEAR': f'ТВ ближе {TV_DIAG_MIN:.1f} диагонали', 'TV_WINDOW': 'ТВ-тумба закрывает окно',
    'ROUTE_SEAT': f'нет пути {P_MAIN:.0f} от двери к дивану', 'ROUTE_WINDOW': f'нет пути {P_SEC:.0f} от двери к окну',
    'ROUTE_DINING': f'нет пути {P_MAIN:.0f} к столовой', 'ROUTE_KITCHEN': f'нет пути {P_MAIN:.0f} к кухне',
    'ROUTE_ARM': f'нет подхода {P_LOC:.0f} к креслу', 'ROUTE_DRESSER': f'нет подхода {P_LOC:.0f} к комоду',
    'SEAT_OFF_RUG': 'посадка не стоит передними ножками на ковре',
    'RUG_GAP': 'дыра каталога: в банке нет ковра нужного размера',
}
_INV = json.load(open(HERE.parent.parent / 'services/planner-solver/rules/templates.json'))['invariants']['seats_front_legs_on_rug']
SEAT_RUG_MIN = 0.02   # templates.json invariants.seats_front_legs_on_rug: «перекрытие ≥2% футпринта» (число — в тексте check)
SEAT_RUG_TUCK = float(_INV['tuck_cm'])   # 15
SOLID = ('sofa', 'sofa2', 'table', 'tv', 'arm', 'lamp', 'dresser', 'dtable', 'chair', 'plant', 'pouf', 'kitchen')


# ---------------------------------------------------------------- выбор шаблона (чистые функции — под тест)
def pillow_count(sofa_w):
    """Подушки по ширине дивана — запасное правило Codex §3 (паспорта сиденья нет): 2 до 189, 3 при 190–253, 4 от 254."""
    return 2 if sofa_w < 190 else 3 if sofa_w < 254 else 4


def choose_templates(area_m2, aspect, kitchen=False, annex=False):
    """Порядок шаблонов для комнаты и почему (Codex §2, §6). Первый, у которого проходит хоть один уровень, — выбранный."""
    if kitchen:
        return ['O1', 'O2'], f'кухня-гостиная {area_m2:.1f} м²: диван-разделитель спинкой к кухне, иначе всё у стен'
    if annex:
        return ['L1', 'M1'], f'Г-образная {area_m2:.1f} м²: П-композиция в основном прямоугольнике, хвост — столовая'
    if area_m2 >= 38:
        return ['L2', 'L1'], f'{area_m2:.1f} м² ≥ 38: два дивана Г (визави при ТВ нельзя), иначе П с двумя креслами'
    if area_m2 >= 28:
        return ['L1', 'M1', 'C3'], f'{area_m2:.1f} м² (28–38): П-композиция, диван + два кресла, полное хранение'
    if area_m2 >= 16:
        if aspect >= 1.4:
            return ['C2', 'M1'], f'{area_m2:.1f} м², вытянутая 1:{aspect:.2f}: посадка вдоль длинной стены'
        return ['M1', 'C3', 'C1'], f'{area_m2:.1f} м² (16–28): диван + кресло'
    if aspect >= 1.4:
        return ['C2', 'C1'], f'{area_m2:.1f} м² < 16, вытянутая 1:{aspect:.2f}: посадка вдоль длинной стены, проход сбоку'
    return ['C1', 'C2'], f'{area_m2:.1f} м² < 16, пропорции 1:{aspect:.2f}: диван и ТВ на противоположных стенах'


def dining_seats(area_m2):
    """Мест за столом — по общей площади комнаты (`slot_rules.seats_for_room`, zones.json `seats_by_room_m2`: <22 → 2,
    <40 → 4, ≥40 → 6; ADR-0270), одно число с подбором комплекта."""
    cfg = ((slot_rules.slot_envelopes().get('slots') or {}).get('стол обеденный')) or {}
    return int(slot_rules.seats_for_room(cfg, area_m2))


def levels_for(room, tpl):
    """Целые составы по порядку; ничего не выбрасываем поштучно.
    < 16 м² (канон `core/lr-checklist.md`: кресло, ваза, кашпо — от 16 м²): A — без кресла, ваза и кашпо по желанию, стол
    на 2; B — без вазы и кашпо; C — компактный стол на 2 (самый малый в банке); D — ещё и торшер вместо «комод + лампа»
    (хранение — ТВ-тумба: комод только если нет иного хранения); E — без столовой, последним и с причиной.
    ≥ 16 м²: A — всё, стол по площади; B — стол на 2 места меньше (на 2 — компактный); D — торшер вместо «комод + лампа».
    Места для столовой на каждом уровне перебираются все (`complete`)."""
    big = room['area'] >= 16
    n = dining_seats(room['area'])
    narm = {'C1': 1, 'C2': 1, 'C3': 0, 'M1': 1, 'O1': 1, 'O2': 1, 'L1': 2, 'L2': 1}[tpl]
    if not big:
        A = {'arm': 0, 'light': 'dresser', 'vase': True, 'plant': True, 'dining': n, 'sofa2': False, 'optional': ('vase', 'plant')}
        B = dict(A, vase=False, plant=False, optional=())
        C = dict(B, compact=True)
        D = dict(C, light='floor')
        E = dict(D, dining=0, compact=False)
        out = [('A', A), ('B', B), ('C', C), ('D', D), ('E', E)]
    else:
        A = {'arm': narm, 'light': 'dresser', 'vase': True, 'plant': True, 'dining': n, 'sofa2': tpl == 'L2'}
        B = dict(A, dining=n - 2) if n > 2 else dict(A, compact=True)
        out = [('A', A), ('B', B), ('D', dict(B, light='floor'))]
    return [(k, v, level_desc(v, room)) for k, v in out]


def level_desc(L, room):
    p = ['диван', 'столик', 'ковёр', 'ТВ']
    if L.get('sofa2'):
        p.append('2-й диван')
    if L['arm']:
        p.append(f"кресло ×{L['arm']}" if L['arm'] > 1 else 'кресло')
    p.append('комод + лампа' if L['light'] == 'dresser' else 'торшер')
    if L['dining']:
        ch = 'стула' if L['dining'] < 5 else 'стульев'
        p.append(f"{'компактный стол' if L.get('compact') else 'стол'} + {L['dining']} {ch}")
    else:
        p.append('без столовой')
    opt = L.get('optional') or ()
    for k, ru in (('vase', 'ваза'), ('plant', 'кашпо')):
        if L[k]:
            p.append(f'{ru} (если влезет)' if k in opt else ru)
    return ' + '.join(p)


# ---------------------------------------------------------------- товары банка
BANDS = [(17, '14-16'), (21, '17-20'), (26, '21-25'), (31, '26-30'), (41, '31-40'), (1e9, '41-50')]
GROUPS = {'C1': ['sofa_lamp', 'sofa_solo', 'sofa_pouf'], 'C2': ['sofa_lamp', 'sofa_solo', 'sofa_pouf'],
          'M1': ['sofa_armchair', 'sofa_2armchairs', 'sectional_armchair'], 'O1': ['sofa_armchair', 'sofa_2armchairs'],
          'O2': ['sofa_armchair', 'sofa_2armchairs'], 'L1': ['sofa_2armchairs', 'sofa_loveseat_2armchairs'],
          'L2': ['two_sofas_2armchairs'], 'C3': []}
ROLES = ['диван', 'диван 2', 'столик', 'ковёр', 'тв-тумба', 'кресло', 'комод', 'лампа', 'торшер', 'стол обеденный', 'стул',
         'кашпо', 'ваза', 'подушка', 'подушка 2', 'плед', 'люстра', 'шторы']


def _sku(it, sset):
    x = it[0] if isinstance(it, list) else it
    w, d = x.get('w'), x.get('d')
    dia = x.get('dia')
    return {'name': str(x.get('name', '')).replace('\t', ' ').strip(), 'w': float(w or dia or 0), 'd': float(d or dia or w or 0),
            'h': float(x.get('h') or 0), 'dia': float(dia or 0), 'sid': f"{x.get('mid')}:{x.get('eid')}",
            'set': sset['set_id'], 'style': sset['style'], 'band': sset['band']}


def load_sets():
    return json.load(open(bs.data_path('sets3.json')))


def set_order(sets, area_m2, tpl, style):
    """Наборы по предпочтению: стиль + полоса площади + группа шаблона → стиль + полоса → полоса + группа → стиль + группа →
    соседние полосы. Угловому (C3) нужен угловой диван — без него набор не берём."""
    band_ = next(b for lim, b in BANDS if area_m2 < lim)
    bi = [b for _l, b in BANDS].index(band_)
    near_b = {b for _l, b in BANDS[max(0, bi - 1):bi + 2]}

    def corner(s):
        return 'углов' in s['items']['диван']['name'].lower()

    def grp(s):
        if tpl == 'C3':
            return corner(s)
        return s['group'] in GROUPS[tpl] and not corner(s)
    straight = (lambda s: tpl != 'C3' and not corner(s))     # прямой диван — шаблонам, кроме C3 (угловой рисуется буквой Г)
    keys = [lambda s: s['style'] == style and s['band'] == band_ and grp(s),
            lambda s: s['style'] == style and s['band'] == band_ and straight(s),
            lambda s: s['band'] == band_ and grp(s),
            lambda s: s['style'] == style and grp(s) and s['band'] in near_b,
            lambda s: s['band'] in near_b and grp(s),
            lambda s: s['band'] in near_b and straight(s)]
    out = []
    for k in keys:
        out += [s for s in sets if k(s) and s not in out]
    return out


def core_fits(room, sk, tpl):
    """Быстрый отсев по габаритам из данных: диван + 40 + столик + 76 (проход) + тумба поперёк комнаты, диван — по длине стены;
    в большой комнате диван может отойти от стены на 91 (проход за спинкой), но ТВ — не дальше 400."""
    return core_need(room, sk, tpl)[0]


def core_need(room, sk, tpl):
    """(влезает, текст): сколько нужно поперёк комнаты под ядро и сколько есть — для подписи «почему не влезает»."""
    so, ta, tv = sk.get('диван'), sk.get('столик'), sk.get('тв-тумба')
    if not (so and ta and tv and sk.get('ковёр')):
        return False, 'в наборе нет дивана, столика, тумбы или ковра'
    if tpl == 'L2' and not sk.get('диван 2'):
        return False, 'в наборе нет второго дивана'
    box = room['box']
    sd = min(SECTION_D, so['d']) if tpl == 'C3' else so['d']
    best = None
    for s, v0 in seat_walls(room, tpl):
        across, L = (box['D'] if s in ('south', 'north') else box['W']), wall_len(box, s)
        if so['w'] > L or tv['w'] > L:
            continue
        need = v0 + sd + COFFEE_GAP + min(ta['w'], ta['d']) + P_SEC + tv['d']
        far = across - tv['d'] / 2 - (v0 + SEAT_EYE * sd)
        if need <= across and (far <= TV_HARD or across - P_MAIN - tv['d'] / 2 - SEAT_EYE * sd <= TV_HARD):
            return True, ''
        parts = ([f'{v0:.0f} за спинкой (кухня/проход)'] if v0 else []) + [f'диван {sd:.0f}', f'{COFFEE_GAP:.0f}',
                                                              f'столик {min(ta["w"], ta["d"]):.0f}', f'{P_SEC:.0f}', f'тумба {tv["d"]:.0f}']
        txt = f"поперёк нужно {' + '.join(parts)} = {need:.0f} см, есть {across:.0f}"
        if best is None or need - across < best[0]:
            best = (need - across, txt)
    return False, best[1] if best else 'диван или тумба длиннее стены'


def pick_skus(sets, area_m2, tpl, style, room=None, k=1):
    """Набор банка нужной полосы площади и группы шаблона, который по габаритам влезает в комнату; недостающие роли — из
    других наборов того же стиля (своя полоса первой), потом любого. Габариты — из данных товара. k > 1 — список до k
    подходящих (если ни один не подходит — первый по порядку, чтобы показать, где ломается)."""
    order = set_order(sets, area_m2, tpl, style)
    out, first = [], None
    for s in order:
        sk = _fill(sets, s)
        first = first or sk
        if room is None or core_fits(room, sk, tpl):
            out.append(sk)
            if len(out) >= k:
                break
    if not out and first:
        out = [first]
    if k == 1:
        return out[0] if out else None
    return out


def _fill(sets, main):
    order = [main] + [s for s in sets if s is not main and s['style'] == main['style'] and s['band'] == main['band']] + \
            [s for s in sets if s['style'] == main['style'] and s['band'] != main['band']] + [s for s in sets if s['style'] != main['style']]
    sk = {}
    for role in ROLES:
        for s in order:
            it = s['items'].get(role)
            if it:
                x = _sku(it, s)
                if role in ('диван 2',) and s is not main:
                    break
                if x['w'] or role in ('люстра', 'шторы', 'плед'):
                    sk[role] = x
                    break
    sk['_set'] = main
    for role, key, lo in (('стол обеденный', 'стол компакт', 70.0), ('стул', 'стул компакт', 35.0)):
        x = smallest(sets, role, main['style'], lo)
        if x:
            sk[key] = x
    return sk


def smallest(sets, role, style, lo):
    """Самый малый по площади товар роли в банке (свой стиль первым), обе стороны не меньше lo — компактная столовая."""
    best = None
    for s in sets:
        it = s['items'].get(role)
        if not it:
            continue
        x = _sku(it, s)
        if min(x['w'], x['d']) < lo:
            continue
        key = (x['style'] != style, x['w'] * x['d'])
        if best is None or key < best[0]:
            best = (key, x)
    return best[1] if best else None


def bank_rugs(sets):
    """Ковры банка по возрастанию площади (уникальные габариты)."""
    out = {}
    for s in sets:
        it = s['items'].get('ковёр')
        if it:
            x = _sku(it, s)
            out.setdefault((x['w'], x['d']), x)
    return [out[k] for k in sorted(out, key=lambda k: k[0] * k[1])]


# ---------------------------------------------------------------- комнаты (координаты: x — восток, y — север, см)
def _flip(ops, D):
    """Страница /demo (`flat215.json`) считает y сверху вниз: смещение по западной/восточной стене переводим в «от юга»."""
    out = []
    for o in ops:
        o = dict(o)
        if o['wall'] in ('west', 'east'):
            o['offset_cm'] = D - o['offset_cm'] - o['width_cm']
        out.append(o)
    return out


def _mk(rid, title, src, W, D, openings, radiators, notes, **kw):
    r = bs._room(rid, title, src, W, D, openings, radiators, notes)
    r.update(kw)
    r.setdefault('floor', [(0.0, 0.0, float(W), float(D))])
    r['area'] = sum(area(f) for f in r['floor']) / 1e4
    r.setdefault('box', None)
    return r


def load_rooms():
    f = json.load(open(HERE / 'flat215.json'))
    lv = next(r for r in f['rooms'] if r['id'] == 'living')
    D = lv['d']
    ops = _flip(lv['openings'], D)
    rads = _flip([dict(x, kind='radiator') for x in lv['radiators']], D)
    for o in ops:
        if o['kind'] == 'door':
            o['hinge'] = 'right'     # дуга «справа снизу» на чертеже: петля у северного края проёма (условно)
    rooms = [
        _mk('demo', 'Демо · гостиная 439×325', 'flat215.json living', lv['w'], D, ops, rads,
            ['петля двери на чертеже не видна — условно', 'радиатор под окном — типовое решение']),
        _mk('s350', 'Малая · 350×400 (14 м²)', 'синтетика (Codex §6: дверь в углу)', 350, 400,
            [{'kind': 'door', 'wall': 'south', 'offset_cm': 255, 'width_cm': 80, 'swing_cm': 80, 'hinge': 'right'},
             {'kind': 'window', 'wall': 'north', 'offset_cm': 100, 'width_cm': 150, 'sill_cm': 85}],
            [{'wall': 'north', 'offset_cm': 85, 'width_cm': 180, 'depth_cm': 12}], ['условная: дверь в углу, окно по центру']),
        _mk('s300', 'Малая вытянутая · 300×500 (15 м²)', 'синтетика (Codex §6)', 300, 500,
            [{'kind': 'door', 'wall': 'south', 'offset_cm': 10, 'width_cm': 80, 'swing_cm': 80, 'hinge': 'left'},
             {'kind': 'window', 'wall': 'north', 'offset_cm': 75, 'width_cm': 150, 'sill_cm': 85}],
            [{'wall': 'north', 'offset_cm': 60, 'width_cm': 180, 'depth_cm': 12}], ['условная: дверь в углу торца, окно напротив']),
        _mk('uk377', 'UK lounge · 377×420 (15,8 м²)', 'e2e/trial.spec.ts:44 (только размер)', 377, 420,
            [{'kind': 'door', 'wall': 'south', 'offset_cm': 285, 'width_cm': 80, 'swing_cm': 80, 'hinge': 'right'},
             {'kind': 'window', 'wall': 'north', 'offset_cm': 105, 'width_cm': 170, 'sill_cm': 80}],
            [{'wall': 'north', 'offset_cm': 100, 'width_cm': 180, 'depth_cm': 12}],
            ['в репо есть только размер 3,77×4,20 — проёмы правдоподобные, не замер']),
        _mk('etagi', '«Этажи» · кухня-гостиная 20,8 м² (520×400)', 'tests/floorplan/test_area_labels.py:17 (площадь 20,8)', 520, 400,
            [{'kind': 'door', 'wall': 'east', 'offset_cm': 30, 'width_cm': 90, 'swing_cm': 90, 'hinge': 'left'},
             {'kind': 'window', 'wall': 'west', 'offset_cm': 110, 'width_cm': 150, 'sill_cm': 85}],
            [{'wall': 'west', 'offset_cm': 95, 'width_cm': 180, 'depth_cm': 12}],
            ['контур и проёмы условные: в репо только площадь 20,8 м² (контур 20,26)',
             'кухня — условная линия 260×60 вдоль северной стены (как на эскизе O1 советника)'],
            kitchen={'wall': 'north', 'off': 0.0, 'len': 260.0, 'depth': 60.0}),
        _mk('lroom', 'Г-образная · 30,25 м² (600×400 + хвост 250×250)', 'tools/scout/tests/test_trial_bundle.py:319', 600, 650,
            [{'kind': 'window', 'wall': 'south', 'offset_cm': 225, 'width_cm': 150, 'sill_cm': 85},
             {'kind': 'door', 'wall': 'north', 'offset_cm': 80, 'width_cm': 90, 'swing_cm': 90, 'hinge': 'left'}],
            [{'wall': 'south', 'offset_cm': 210, 'width_cm': 180, 'depth_cm': 12}],
            ['контур и проёмы — из теста (окно и дверь хвоста); радиатор и петля — условно'],
            floor=[(0.0, 0.0, 600.0, 400.0), (0.0, 400.0, 250.0, 650.0)], annex=(0.0, 400.0, 250.0, 650.0),
            portal=(0.0, 400.0, 250.0, 400.0),
            poly=[(0, 0), (600, 0), (600, 400), (250, 400), (250, 650), (0, 650)]),
        _mk('r33', 'Прямоугольная · 33 м² (660×500)', 'синтетика (Codex §6: 30–35 м²)', 660, 500,
            [{'kind': 'door', 'wall': 'south', 'offset_cm': 555, 'width_cm': 90, 'swing_cm': 90, 'hinge': 'right'},
             {'kind': 'window', 'wall': 'north', 'offset_cm': 110, 'width_cm': 170, 'sill_cm': 85},
             {'kind': 'window', 'wall': 'north', 'offset_cm': 390, 'width_cm': 170, 'sill_cm': 85}],
            [{'wall': 'north', 'offset_cm': 105, 'width_cm': 180, 'depth_cm': 12},
             {'wall': 'north', 'offset_cm': 385, 'width_cm': 180, 'depth_cm': 12}], ['условная: два окна на северной, дверь в углу']),
        _mk('r41', 'Большая · 41,6 м² (800×520)', 'синтетика (Codex §6: 40+ м²)', 800, 520,
            [{'kind': 'door', 'wall': 'east', 'offset_cm': 30, 'width_cm': 90, 'swing_cm': 90, 'hinge': 'left'},
             {'kind': 'window', 'wall': 'north', 'offset_cm': 140, 'width_cm': 180, 'sill_cm': 85},
             {'kind': 'window', 'wall': 'north', 'offset_cm': 480, 'width_cm': 180, 'sill_cm': 85}],
            [{'wall': 'north', 'offset_cm': 140, 'width_cm': 180, 'depth_cm': 12},
             {'wall': 'north', 'offset_cm': 480, 'width_cm': 180, 'depth_cm': 12}], ['условная: два окна, дверь у юго-восточного угла']),
    ]
    for r in rooms:
        r['_geo'] = {'doors': [door_geo(r, d) for d in r['doors']],
                     'rads': [band(r, x['wall'], x['off'], x['width'], 0, x['depth']) for x in r['rads']],
                     'wins': [band(r, w['wall'], w['off'], w['width'], 0, 1) for w in r['wins']]}
        if r.get('annex'):   # композиция гостиной — в основном прямоугольнике; хвост — столовая
            box = dict(r, W=600.0, D=400.0, doors=[], floor=[(0.0, 0.0, 600.0, 400.0)])
            r['box'] = box
        else:
            r['box'] = r
        k = r.get('kitchen')
        if k:
            r['_geo']['kitchen'] = band(r, k['wall'], k['off'], k['len'], 0, k['depth'])
            r['_geo']['aisle'] = band(r, k['wall'], k['off'], k['len'], k['depth'], k['depth'] + P_MAIN)
        if r.get('portal'):
            p = r['portal']
            r['_geo']['portal'] = (p[0], p[1] - P_MAIN, p[2], p[1])     # полоса 91 перед проходом в хвост
    return rooms


def floor_ok(room, rect):
    tot = sum(area(x) for f in room['floor'] if (x := inter(rect, f)))
    return tot >= area(rect) - 4.0


# ---------------------------------------------------------------- предметы
def obj(kind, role, sku, rect, group, **kw):
    it = {'kind': kind, 'role': role, 'sku': sku, 'rect': rect, 'rects': [rect], 'group': group, 'zones': []}
    it.update(kw)
    return it


def frame(box, s):
    """Рамка посадки: u — вдоль стены s, v — вглубь комнаты; противоположная стена — та же ось u."""
    across = box['D'] if s in ('south', 'north') else box['W']
    return across, (lambda u0, u1, v0, v1: band(box, s, u0, u1 - u0, v0, v1)), \
        (lambda u0, u1, v0, v1: band(box, OPPOSITE[s], u0, u1 - u0, v0, v1))


def core(room, sk, tpl, s, a, v0, chaise_hi=True, tvo=0.0):
    """Ядро: диван спинкой к стене s (или на v0 от неё — разделитель), столик на 40 по оси, ковёр (передние ножки на нём),
    ТВ-тумба на противоположной стене по той же оси."""
    box = room['box']
    across, F, G = frame(box, s)
    so, ta, ru, tv = sk['диван'], sk['столик'], sk['ковёр'], sk['тв-тумба']
    Sw, Sd = so['w'], so['d']
    items = []
    corner = tpl == 'C3'
    if corner:
        sd = min(SECTION_D, Sd)
        main = F(a, a + Sw, v0, v0 + sd)
        ch = F(a + Sw - sd, a + Sw, v0, v0 + Sd) if chaise_hi else F(a, a + sd, v0, v0 + Sd)
        sofa = obj('sofa', 'диван', so, main, 'seat', s=s, u0=a, v0=v0, depth=sd)
        sofa['rects'] = [main, ch]
        sofa['bbox'] = F(a, a + Sw, v0, v0 + Sd)
        c = (a + a + Sw - sd) / 2 if chaise_hi else (a + sd + a + Sw) / 2
        front = v0 + sd
    else:
        sofa = obj('sofa', 'диван', so, F(a, a + Sw, v0, v0 + Sd), 'seat', s=s, u0=a, v0=v0, depth=Sd)
        c = a + Sw / 2
        front = v0 + Sd
    items.append(sofa)
    Tw, Td = max(ta['w'], ta['d']), min(ta['w'], ta['d'])
    t0 = front + COFFEE_GAP
    table = obj('table', 'столик', ta, F(c - Tw / 2, c + Tw / 2, t0, t0 + Td), 'seat')
    items.append(table)
    Rw, Rd = max(ru['w'], ru['d']), min(ru['w'], ru['d'])
    rv0 = front - RUG_TUCK            # передние ножки на ковре; упирается в тумбу — глубже под диван (не дальше спинки)
    lim = across - tv['d'] - 10
    if rv0 + Rd > lim:
        rv0 = max(v0 + 5, lim - Rd)
    rug = obj('rug', 'ковёр', ru, F(c - Rw / 2, c + Rw / 2, rv0, rv0 + Rd), 'seat')
    items.append(rug)
    Vw, Vd = tv['w'], tv['d']
    tc = c + tvo         # тумба может уйти вдоль стены (дверь, окно) — экран повёрнут к дивану, угол ≤ 30° (sofa_tv_aim_deg_max)
    tvs = obj('tv', 'тв-тумба', tv, G(tc - Vw / 2, tc + Vw / 2, 0, Vd), 'media')
    items.append(tvs)
    eye = v0 + SEAT_EYE * (SECTION_D if corner else Sd)
    dist = math.hypot(across - Vd / 2 - eye, tvo)
    scr = min(SCREEN_FRAC * Vw, dist / TV_PREF * 0.8716)
    meta = {'s': s, 'c': c, 'tvc': tc, 'tvo': tvo, 'a': a, 'v0': v0, 'front': front, 'across': across, 'dist': dist, 'screen_w': scr,
            'diag': scr / 0.8716, 'eye': eye, 'F': F, 'G': G, 't': (t0, t0 + Td, Tw), 'corner': corner, 'chaise_hi': chaise_hi}
    return items, meta


def flank_cands(meta, sku, side, kind, role, sofa):
    """Места кресла на фланге: зазор до столика 20/35/50, сдвиг вдоль v −30…+30 (не дальше 240 от группы — Codex M1)."""
    out = []
    for gap in (ARM_TABLE, 20.0, 50.0):
        for dv in (0.0, -30.0, 30.0):
            it = flank(meta, sku, side, kind, role, sofa, gap=gap, dv=dv)
            if it is not None:
                out.append(it)
    return out


def flank(meta, sku, side, kind, role, sofa=None, gap=ARM_TABLE, dv=0.0):
    """Кресло (или 2-й диван — Г) на фланге столика, лицом к нему: глубина — вдоль u, ширина — вдоль v. Если по ширине
    заходит на основной диван — отодвигается за его подлокотник (+10)."""
    t0, t1, Tw = meta['t']
    vc = (t0 + t1) / 2 + dv
    ARM_TABLE = gap
    c = meta['c']
    W_, D_ = sku['w'], sku['d']
    v0, v1 = vc - W_ / 2, vc + W_ / 2
    sw = sofa['sku']['w'] if sofa else 0
    over = sofa is not None and v0 < meta['front']
    if side == 'hi':
        u0 = c + Tw / 2 + ARM_TABLE
        if over:
            u0 = max(u0, sofa['u0'] + sw + 10)
        r = meta['F'](u0, u0 + D_, v0, v1)
    else:
        u1 = c - Tw / 2 - ARM_TABLE
        if over:
            u1 = min(u1, sofa['u0'] - 10)
        r = meta['F'](u1 - D_, u1, v0, v1)
    return obj(kind, role, sku, r, 'seat', side=side)


def floor_lamp(meta, sku, sofa, side):
    Lw, Ld = max(sku['w'], 20.0), max(sku['d'], 20.0)
    a, Sw, v0 = sofa['u0'], sofa['sku']['w'], meta['v0']
    if side == 'lo':
        r = meta['F'](a - ARM_GAP - Lw, a - ARM_GAP, v0 + 5, v0 + 5 + Ld)
    else:
        r = meta['F'](a + Sw + ARM_GAP, a + Sw + ARM_GAP + Lw, v0 + 5, v0 + 5 + Ld)
    return obj('lamp', 'торшер', sku, r, 'light', side=side)


def dresser_cands(room, sku):
    box = room['box']
    out = []
    for wall in WALLS:
        for off in wall_offsets(box, wall, sku['w'], step=10):
            it = obj('dresser', 'комод', sku, band(box, wall, off, sku['w'], 0, sku['d']), 'store', wall=wall, off=off)
            it['zones'].append({'code': 'DRESSER_FRONT', 'rect': band(box, wall, off, sku['w'], sku['d'], sku['d'] + DRESS),
                                'label': f'{DRESS:.0f}', 'wall': wall})
            out.append(it)
    return out


def dining_group(room, tbl, chair, n, cx, cy, along_x, adj=None):
    """Стол + n стульев на длинных сторонах (2 — по одному, 4 — по два); за стулом — 60 отодвинуть (55) / подойти.
    adj=(sx, sy) при n=2 — стулья на двух СОСЕДНИХ сторонах (стол в углу, как на /demo): sx — сторона по x, sy — по y."""
    tw, td = (max(tbl['w'], tbl['d']), min(tbl['w'], tbl['d']))
    if not along_x:
        tw, td = td, tw
    T = (cx - tw / 2, cy - td / 2, cx + tw / 2, cy + td / 2)
    g = [obj('dtable', 'стол обеденный', tbl, T, 'dining')]
    cw, cd = chair['w'], chair['d']
    tuck = min(15.0, cd / 3)
    if adj and n == 2:
        sx, sy = adj
        x0 = T[2] - tuck if sx > 0 else T[0] + tuck - cd
        y0 = T[3] - tuck if sy > 0 else T[1] + tuck - cd
        pairs = [((x0, cy - cw / 2, x0 + cd, cy + cw / 2),
                  (T[2], cy - cw / 2, T[2] + CHAIR_ZONE, cy + cw / 2) if sx > 0 else (T[0] - CHAIR_ZONE, cy - cw / 2, T[0], cy + cw / 2)),
                 ((cx - cw / 2, y0, cx + cw / 2, y0 + cd),
                  (cx - cw / 2, T[3], cx + cw / 2, T[3] + CHAIR_ZONE) if sy > 0 else (cx - cw / 2, T[1] - CHAIR_ZONE, cx + cw / 2, T[1]))]
        for rr, zz in pairs:
            c_ = obj('chair', 'стул', chair, rr, 'dining')
            c_['zones'].append({'code': 'CHAIR_ZONE', 'rect': zz, 'label': f'{CHAIR_ZONE:.0f}', 'wall': None})
            g.append(c_)
        return g
    long_x = tw >= td
    per = 2 if n == 6 else max(1, n // 2)      # на 6: по 2 на длинных + по торцам (61 см кромки на едока)
    if n == 6:
        for side in (-1, 1):
            if long_x:
                x0 = T[2] - tuck if side > 0 else T[0] + tuck - cd
                r = (x0, cy - cw / 2, x0 + cd, cy + cw / 2)
                z = (T[2], cy - cw / 2, T[2] + CHAIR_ZONE, cy + cw / 2) if side > 0 else (T[0] - CHAIR_ZONE, cy - cw / 2, T[0], cy + cw / 2)
            else:
                y0 = T[3] - tuck if side > 0 else T[1] + tuck - cd
                r = (cx - cw / 2, y0, cx + cw / 2, y0 + cd)
                z = (cx - cw / 2, T[3], cx + cw / 2, T[3] + CHAIR_ZONE) if side > 0 else (cx - cw / 2, T[1] - CHAIR_ZONE, cx + cw / 2, T[1])
            c_ = obj('chair', 'стул', chair, r, 'dining')
            c_['zones'].append({'code': 'CHAIR_ZONE', 'rect': z, 'label': f'{CHAIR_ZONE:.0f}', 'wall': None})
            g.append(c_)
    if n == 4 and max(tw, td) < 2 * cw + 10:      # квадратный/маленький стол: по стулу на каждую сторону
        for side in (-1, 1):
            y0 = T[3] - tuck if side > 0 else T[1] + tuck - cd
            r = (cx - cw / 2, y0, cx + cw / 2, y0 + cd)
            z = (cx - cw / 2, T[3], cx + cw / 2, T[3] + CHAIR_ZONE) if side > 0 else (cx - cw / 2, T[1] - CHAIR_ZONE, cx + cw / 2, T[1])
            x0 = T[2] - tuck if side > 0 else T[0] + tuck - cd
            r2 = (x0, cy - cw / 2, x0 + cd, cy + cw / 2)
            z2 = (T[2], cy - cw / 2, T[2] + CHAIR_ZONE, cy + cw / 2) if side > 0 else (T[0] - CHAIR_ZONE, cy - cw / 2, T[0], cy + cw / 2)
            for rr, zz in ((r, z), (r2, z2)):
                c_ = obj('chair', 'стул', chair, rr, 'dining')
                c_['zones'].append({'code': 'CHAIR_ZONE', 'rect': zz, 'label': f'{CHAIR_ZONE:.0f}', 'wall': None})
                g.append(c_)
        return g
    for side in (-1, 1):
        for k in range(per):
            if long_x:
                ux = cx + (k - (per - 1) / 2) * (tw / per)
                y0 = T[3] - tuck if side > 0 else T[1] + tuck - cd
                r = (ux - cw / 2, y0, ux + cw / 2, y0 + cd)
                z = (ux - cw / 2, T[3], ux + cw / 2, T[3] + CHAIR_ZONE) if side > 0 else (ux - cw / 2, T[1] - CHAIR_ZONE, ux + cw / 2, T[1])
            else:
                uy = cy + (k - (per - 1) / 2) * (td / per)
                x0 = T[2] - tuck if side > 0 else T[0] + tuck - cd
                r = (x0, uy - cw / 2, x0 + cd, uy + cw / 2)
                z = (T[2], uy - cw / 2, T[2] + CHAIR_ZONE, uy + cw / 2) if side > 0 else (T[0] - CHAIR_ZONE, uy - cw / 2, T[0], uy + cw / 2)
            c = obj('chair', 'стул', chair, r, 'dining')
            c['zones'].append({'code': 'CHAIR_ZONE', 'rect': z, 'label': f'{CHAIR_ZONE:.0f}', 'wall': None})
            g.append(c)
    return g


def dining_cands(room, sk, n, taken=(), compact=False):
    """Стол + стулья по сетке 15 см в двух поворотах — ВСЕ места комнаты (углы, стены, у окна, середина); сразу отбрасываем,
    где стол вне пола или на уже стоящем предмете. compact — самый малый стол и стул банка."""
    tbl = sk.get('стол компакт') if compact else sk['стол обеденный']
    ch = sk.get('стул компакт') if compact else sk['стул']
    tbl, ch = tbl or sk['стол обеденный'], ch or sk['стул']
    reg = (0.0, 0.0, room['W'], room['D'])      # в Г-образной хвост предпочтительнее (мягко, `soft_checks`), но не обязателен
    out = []
    lays = [(a, None) for a in (True, False)]
    if n == 2:      # стол в углу/у стены — стулья на соседних сторонах
        lays += [(True, (sx, sy)) for sx in (-1, 1) for sy in (-1, 1)]
    a_, b_ = max(tbl['w'], tbl['d']), min(tbl['w'], tbl['d'])
    for along, adj in lays:
        hw, hd = (a_ / 2, b_ / 2) if along else (b_ / 2, a_ / 2)
        # сетка 15 см + места вплотную к стенам (2 см): сетка не попадает «к стене», а угол у стены — главное место малой
        xs = sorted(set(list(np.arange(reg[0] + 30, reg[2] - 29, 15)) + [reg[0] + hw + 2, reg[2] - hw - 2]))
        ys = sorted(set(list(np.arange(reg[1] + 30, reg[3] - 29, 15)) + [reg[1] + hd + 2, reg[3] - hd - 2]))
        for cx in xs:
            for cy in ys:
                g = dining_group(room, tbl, ch, n, float(cx), float(cy), along, adj)
                if not floor_ok(room, g[0]['rect']) or any(inter(g[0]['rect'], t) for t in taken):
                    continue
                out.append(g)
    return out


def plant_cands(room, sku):
    Dp = max(sku['w'], sku['dia'], 25.0)
    box = room['box']
    W, D = box['W'], box['D']
    pts = [(5, 5), (W - 5 - Dp, 5), (5, D - 5 - Dp), (W - 5 - Dp, D - 5 - Dp)]
    for w in room['wins']:
        for u in (w['off'] - 8 - Dp, w['off'] + w['width'] + 8):
            if w['wall'] in ('south', 'north'):
                pts.append((u, 5 if w['wall'] == 'south' else D - 5 - Dp))
            else:
                pts.append((5 if w['wall'] == 'west' else W - 5 - Dp, u))
    if room.get('annex'):
        a = room['annex']
        pts += [(a[0] + 5, a[1] + 5), (a[2] - 5 - Dp, a[3] - 5 - Dp)]
    return [obj('plant', 'кашпо', sku, (x, y, x + Dp, y + Dp), 'decor') for x, y in pts]


# ---------------------------------------------------------------- проверки
def static_checks(room, it):
    geo = room['_geo']
    out = []
    k = it['kind']
    for r in it['rects']:
        if not floor_ok(room, r):
            out.append(V('RUG_OUT' if k == 'rug' else 'OUT_OF_ROOM', f'«{it["role"]}» выходит за стену', [clip(r, room)]))
    if k == 'rug':
        m = RUG_WALL_SMALL if room['area'] <= 16 else RUG_WALL
        r = it['rect']
        gap = min(r[0], r[1], room['W'] - r[2], room['D'] - r[3]) if not room.get('annex') else min(r[0], r[1], 600 - r[2])
        if 0 <= gap < m - EPS:
            out.append(V('RUG_WALL', f'ковёр в {gap:.0f} см от стены (норма {m:.0f})', hard=False, pen=0.5 * (m - gap)))
        if geo.get('kitchen'):
            h = inter(it['rect'], geo['kitchen'])
            if h:
                out.append(V('OVERLAP', 'ковёр на кухонной линии', [h]))
        return out
    for r in it['rects']:
        for g in geo['doors']:
            h = swing_hit(r, g)
            if h:
                out.append(V('DOOR_SWING', f'«{it["role"]}» в дуге двери', [h]))
            h = inter(r, g['strip'])
            if h:
                out.append(V('DOOR_PASSAGE', f'«{it["role"]}» в проходе у двери ({DOOR_PASS:.0f})', [h]))
        if geo.get('portal'):
            h = inter(r, geo['portal'])
            if h:
                out.append(V('PORTAL', f'«{it["role"]}» в проходе в хвост ({P_MAIN:.0f})', [h]))
        for rr in geo['rads']:
            if rdist(r, rr) < RAD_HARD - EPS:
                out.append(V('RADIATOR', f'«{it["role"]}» ближе {RAD_HARD:.0f} см к радиатору', [inter(r, expand(rr, RAD_HARD))]))
        if k not in ('lamp', 'plant', 'tv'):
            for w, ws in zip(room['wins'], geo['wins']):
                if it['sku']['h'] > max(w['sill'], 80) and rdist(r, ws) < 10 - EPS:
                    out.append(V('WINDOW_BLOCKED', f'«{it["role"]}» ({it["sku"]["h"]:.0f} см) закрывает окно', [inter(r, expand(ws, 10))]))
        if geo.get('kitchen') and k != 'kitchen':
            h = inter(r, geo['kitchen'])
            if h:
                out.append(V('OVERLAP', f'«{it["role"]}» на кухонной линии', [h]))
            h = inter(r, geo['aisle'])
            if h:
                out.append(V('KITCHEN_AISLE', f'«{it["role"]}» в проходе {P_MAIN:.0f} у кухни', [h]))
    if k == 'tv':     # тумба на стене окна перед окном — экран закрывает окно
        for w, ws in zip(room['wins'], geo['wins']):
            if rdist(it['rect'], ws) < 2 and inter(expand(it['rect'], 1), expand(ws, 1)):
                out.append(V('TV_WINDOW', 'ТВ-тумба перед окном', [inter(expand(it['rect'], 1), expand(ws, 12))]))
    for z in it['zones']:
        if not floor_ok(room, z['rect']):
            out.append(V(z['code'], f'перед «{it["role"]}» нет {z["label"]} см — стена', [clip(z['rect'], room)]))
        for rr in geo['rads']:
            h = inter(z['rect'], rr)
            if h:
                out.append(V(z['code'], f'перед «{it["role"]}» радиатор', [h]))
        if geo.get('kitchen'):
            h = inter(z['rect'], geo['kitchen'])
            if h:
                out.append(V(z['code'], f'перед «{it["role"]}» кухня', [h]))
    return out


def pair_checks(a, b):
    out = []
    ka, kb = a['kind'], b['kind']
    if 'rug' in (ka, kb):
        o = b if ka == 'rug' else a
        rug = a if ka == 'rug' else b
        if o['group'] == 'dining':
            h = inter(rug['rect'], o['rect'])
            if h:
                out.append(V('OVERLAP_RUG', 'столовая на ковре гостиной', [h]))
        elif o['kind'] in ('dresser', 'tv', 'plant'):
            h = inter(rug['rect'], o['rect'])
            if h and area(h) > 25:
                out.append(V('RUG_UNDER', f'ковёр заходит под «{o["role"]}»', [h]))
        return out
    if a['group'] == b['group'] == 'dining':
        return out
    for ra in a['rects']:
        for rb in b['rects']:
            h = inter(ra, rb)
            if h:
                out.append(V('OVERLAP', f'«{a["role"]}» налезает на «{b["role"]}»', [h]))
    for x, y in ((a, b), (b, a)):
        for z in x['zones']:
            for ry in y['rects']:
                h = inter(z['rect'], ry)
                if h:
                    out.append(V(z['code'], f'перед «{x["role"]}» нет {z["label"]} см — мешает «{y["role"]}»', [h]))
    return out


def core_checks(room, items, meta):
    out = []
    if meta is None:
        return out
    table = next(i for i in items if i['kind'] == 'table')
    rug = next(i for i in items if i['kind'] == 'rug')
    t, r = table['rect'], rug['rect']
    if not (r[0] <= t[0] + EPS and r[1] <= t[1] + EPS and r[2] >= t[2] - EPS and r[3] >= t[3] - EPS):
        out.append(V('RUG_TABLE', 'столик не целиком на ковре', [t]))
    for it in items:      # передние ножки всей посадки на ковре (templates.json `seats_front_legs_on_rug`)
        if it['kind'] in ('sofa', 'sofa2', 'arm'):
            fp = sum(area(x) for x in it['rects'])
            ov = sum(area(inter(x, r) or (0, 0, 0, 0)) for x in it['rects'])
            # канон: ≥ 2 % футпринта; и не меньше половины полосы tuck_cm (15) по фронту — иначе «касается краем»
            need = max(SEAT_RUG_MIN * fp, 0.5 * SEAT_RUG_TUCK * it['sku']['w'])
            if fp and ov < need - EPS:
                out.append(V('SEAT_OFF_RUG', f'«{it["role"]}» не стоит передними ножками на ковре', list(it['rects'])))
    d, diag = meta['dist'], meta['diag']
    if d > TV_HARD:
        out.append(V('TV_FAR', f'ТВ в {d:.0f} см (> {TV_HARD:.0f})', []))
    if d < max(TV_MIN * 0.75, TV_DIAG_MIN * diag):
        out.append(V('TV_NEAR', f'ТВ в {d:.0f} см', []))
    out.append(V('TV_DIST', '', hard=False, pen=0.15 * abs(d - TV_PREF * diag)))
    if meta.get('tvo'):
        ang = math.degrees(math.atan2(abs(meta['tvo']), d))
        out.append(V('TV_AIM', f'ТВ сдвинута на {abs(meta["tvo"]):.0f} см вбок, экран под {ang:.0f}°', hard=False, pen=0.3 * abs(meta['tvo'])))
    box = room['box']
    L = wall_len(box, meta['s'])
    out.append(V('SOFA_OFF_CENTER', '', hard=False, pen=0.04 * abs(meta['c'] - L / 2)))
    opp = OPPOSITE[meta['s']]
    if any(w['wall'] == opp for w in room['wins']):
        out.append(V('SOFA_FACES_WINDOW', 'диван смотрит в окно, ТВ на стене окна', hard=False, pen=60))
    if not room.get('annex') and any(dd['wall'] == opp for dd in room['doors']):
        out.append(V('MEDIA_DOOR_WALL', 'ТВ на стене двери', hard=False, pen=10))
    return out


def soft_checks(room, items):
    out = []
    solid = [i for i in items if i['kind'] in SOLID]
    for it in items:
        if it['kind'] == 'plant':
            dmin = min([rdist(it['rect'], o['rect']) for o in solid if o is not it] or [999])
            if dmin < PLANT_SOFT:
                out.append(V('PLANT_NEAR', f'кашпо в {dmin:.0f} см от мебели (лучше {PLANT_SOFT:.0f})', hard=False, pen=0.1 * (PLANT_SOFT - dmin)))
            wd = min([rdist(it['rect'], w) for w in room['_geo']['wins']] or [0])
            out.append(V('PLANT_WIN', '', hard=False, pen=0.02 * wd))
        if it['kind'] == 'dtable':
            ref = room['_geo'].get('kitchen') or room.get('annex') or (room['_geo']['wins'][0] if room['_geo']['wins'] else None)
            if ref:
                out.append(V('DINING_FAR', '', hard=False, pen=0.05 * rdist(it['rect'], ref)))
        if it['kind'] == 'dresser':
            L = wall_len(room['box'], it['wall'])
            out.append(V('STORAGE_MIDWALL', '', hard=False, pen=0.02 * min(it['off'], L - it['off'] - it['sku']['w'])))
    return out


def evaluate(room, items, meta, cache):
    vs = []
    for it in items:
        key = (it['kind'], tuple(round(x, 1) for r in it['rects'] for x in r))
        if key not in cache:
            cache[key] = static_checks(room, it)
        vs += cache[key]
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            vs += pair_checks(items[i], items[j])
    vs += core_checks(room, items, meta)
    vs += soft_checks(room, items)
    return vs


def score(vs):
    return (sum(1 for v in vs if v['hard']), sum(v['pen'] for v in vs))


# ---------------------------------------------------------------- пути (сетка 1 см; коридор ширины w — центр не ближе w/2)
def grids(room, items, g=1):
    """Сетка g см: проверка путей — 2 см (быстро), рисунок пути — 1 см (`bfs_path` спальни ждёт 1 см)."""
    W, D = int(round(room['W'] / g)), int(round(room['D'] / g))
    X, Y = np.meshgrid((np.arange(W) + 0.5) * g, (np.arange(D) + 0.5) * g)
    fl = np.zeros((D, W), bool)
    for f in room['floor']:
        fl |= (X >= f[0]) & (X <= f[2]) & (Y >= f[1]) & (Y <= f[3])
    obs = [r for i in items if i['kind'] in SOLID for r in i['rects']] + list(room['_geo']['rads'])
    if room['_geo'].get('kitchen'):
        obs.append(room['_geo']['kitchen'])
    occ = ~fl
    for o in obs:
        occ |= (X >= o[0]) & (X <= o[2]) & (Y >= o[1]) & (Y <= o[3])
    dist = ndimage.distance_transform_edt(np.pad(~occ, 1))[1:-1, 1:-1] * g
    return X, Y, dist


def near(X, Y, rect, m):
    dx = np.maximum(np.maximum(rect[0] - X, X - rect[2]), 0)
    dy = np.maximum(np.maximum(rect[1] - Y, Y - rect[3]), 0)
    return dx * dx + dy * dy <= m * m


ROUTE_COL = {P_MAIN: (27, 94, 32), P_SEC: (13, 71, 161), P_LOC: (230, 81, 0)}


def route_targets(room, items):
    """(код, ширина, цель-функция): к дивану/кухне/столовой — 91, к окну — 76, к креслу/комоду — 60."""
    t = []
    sofa = next((i for i in items if i['kind'] == 'sofa'), None)
    if sofa:
        t.append(('ROUTE_SEAT', P_MAIN, 'диван', lambda X, Y, w, s=sofa: near(X, Y, s.get('bbox', s['rect']), w / 2 + 30)))
    for k, w in enumerate(room['_geo']['wins']):
        z = band(room, room['wins'][k]['wall'], room['wins'][k]['off'] + 20, max(room['wins'][k]['width'] - 40, 10), 0, 90)
        t.append(('ROUTE_WINDOW', P_SEC, 'окно', lambda X, Y, w_, z=z: (X >= z[0]) & (X <= z[2]) & (Y >= z[1]) & (Y <= z[3])))
    dt = next((i for i in items if i['kind'] == 'dtable'), None)
    if dt:
        wdt = P_MAIN if (room.get('kitchen') or room.get('annex')) else P_SEC
        t.append(('ROUTE_DINING', wdt, 'столовая', lambda X, Y, w, r=dt['rect']: near(X, Y, r, w / 2 + 75)))
    if room['_geo'].get('aisle'):
        a = room['_geo']['aisle']
        t.append(('ROUTE_KITCHEN', P_MAIN, 'кухня', lambda X, Y, w, a=a: (X >= a[0]) & (X <= a[2]) & (Y >= a[1]) & (Y <= a[3])))
    for it in items:
        if it['kind'] in ('arm', 'sofa2'):
            t.append(('ROUTE_ARM', P_LOC, it['role'], lambda X, Y, w, r=it['rect']: near(X, Y, r, w / 2 + 25)))
        if it['kind'] == 'dresser':
            z = it['zones'][0]['rect']
            t.append(('ROUTE_DRESSER', P_LOC, 'комод', lambda X, Y, w, z=z: (X >= z[0]) & (X <= z[2]) & (Y >= z[1]) & (Y <= z[3])))
    return t


def check_routes(room, items, want_paths=False):
    g = 1 if want_paths else 2
    X, Y, dist = grids(room, items, g)
    out, paths = [], []
    labs = {}
    for code, w, name, fn in route_targets(room, items):
        if w not in labs:
            free = dist >= w / 2
            labs[w] = (free, ndimage.label(free)[0])
        free, lab = labs[w]
        ok_any = False
        for d in room['doors']:
            sx, sy = wall_point(room, d['wall'], d['off'] + d['width'] / 2, w / 2 + 1)
            iy, ix = int(min(max(sy, 0), room['D'] - 1) / g), int(min(max(sx, 0), room['W'] - 1) / g)
            iy, ix = min(iy, lab.shape[0] - 1), min(ix, lab.shape[1] - 1)
            L0 = lab[iy, ix]
            m = fn(X, Y, w)
            ok = bool(L0 and np.any(m & (lab == L0)))
            if ok:
                ok_any = True
                if want_paths:
                    paths.append((code, w, bfs_path(free, (iy, ix), m)))
        if not ok_any:
            out.append(V(code, f'нет пути {w:.0f} от двери к «{name}»', []))
    return out, paths


# ---------------------------------------------------------------- перебор
def seat_walls(room, tpl):
    box = room['box']
    walls = list(WALLS)
    if tpl in ('C2',):
        L = max(box['W'], box['D'])
        walls = [w for w in WALLS if abs(wall_len(box, w) - L) < 1]
    k = room.get('kitchen')
    if tpl == 'O1' and k:
        # диван-разделитель: спинкой к кухне через проход 91, либо спинкой к зоне кухни-столовой (стол за спинкой),
        # ТВ — на стене напротив, не на кухонной (эскиз O1 советника)
        out = [(k['wall'], k['depth'] + P_MAIN)]
        for w in WALLS:
            if w != k['wall'] and OPPOSITE[w] != k['wall']:
                out += [(w, float(v)) for v in (150, 180, 210, 240)]
        return out
    if tpl == 'O2' and k:
        walls = [w for w in WALLS if w != k['wall']]
    return [(w, 0.0) for w in walls]


def search(room, tpl, lid, L, sk, keep=12, force=None):
    cache = {}
    cores = []
    so = sk['диван']
    variants = [True, False] if tpl == 'C3' else [True]
    for s, v0 in (force or seat_walls(room, tpl)):
        box = room['box']
        Lw = wall_len(box, s)
        across = box['D'] if s in ('south', 'north') else box['W']
        offs = wall_offsets(box, s, so['w'], step=10, extra=[(Lw - so['w']) / 2]) if v0 == 0 else \
            [x for x in np.arange(0, Lw - so['w'] + 1, 10)] + [(Lw - so['w']) / 2]
        # спинка у стены; у радиатора — на 15 от него (occupancy: sofa_to_radiator_wall); в большой — плавает с проходом за спинкой
        v0s = [v0] + ([P_SEC, P_MAIN] if v0 == 0 and across >= 450 else [])
        if v0 == 0 and across >= 550:      # очень широкая: диван отходит так, чтобы до экрана ≈ 3,3 м
            v0s.append(round(across - sk['тв-тумба']['d'] / 2 - SEAT_EYE * so['d'] - 330))
        for a in offs:
            for vv in v0s:
                if vv == 0:
                    span = band(box, s, a, so['w'], 0, 1)
                    rd = [x['depth'] for x, g in zip(room['rads'], room['_geo']['rads']) if x['wall'] == s and inter(expand(span, 1), g)]
                    if rd:
                        vv = max(rd) + RAD_HARD
                for ch in variants:
                    for tvo in (0.0, -20.0, 20.0, -40.0, 40.0):
                        its, meta = core(room, sk, tpl, s, float(a), vv, ch, tvo)
                        vs = evaluate(room, its, meta, cache)
                        cores.append((score(vs), its, meta))
    cores.sort(key=lambda t: t[0])
    per, top, seen = {}, [], set()
    for sc, its, meta in cores:     # разнообразие: лучшие на каждой стене, разные места дивана и ТВ (под углы столовой)
        k = meta['s']
        pos = (k, round(meta['c'] / 20), round((meta.get('tvo') or 0) / 20), round(meta['v0'] / 20))
        if sc[0] == 0 and pos in seen:
            continue
        if per.get(k, 0) < max(2, keep // 2):
            per[k] = per.get(k, 0) + 1
            seen.add(pos)
            top.append((sc, its, meta))
        if len(top) >= keep:
            break
    best = None
    for _sc, its, meta in top:
        for res in complete(room, tpl, L, sk, its, meta, cache):
            if best is None or res['score'] < best['score']:
                best = res
            if res['score'][0] == 0 and best is res:
                pass
        if best and best['score'][0] == 0:
            break
    best['tpl'], best['lid'], best['L'], best['desc'] = tpl, lid, L, level_desc(L, room)
    best['ok'] = best['score'][0] == 0
    return best


def greedy(room, items, meta, cands, cache, n=1, routes=True, tries=8, spread=None):
    """Лучшее место по проверкам; из первых `tries` без жёстких нарушений берём первое, где проходят пути от двери
    (пути с частью предметов — необходимое условие: остальное их только сужает). spread (см) — разные места: из
    кандидатов в одной клетке spread×spread берём лучший, чтобы n мест были по всей комнате, а не соседями."""
    sc = []
    for c in cands:
        cc = c if isinstance(c, list) else [c]
        vs = evaluate(room, items + cc, meta, cache)
        sc.append((score(vs), cc))
    sc.sort(key=lambda t: t[0])
    if spread:
        seen, uniq = set(), []
        for s_, cc in sc:
            r = cc[0]['rect']
            key = (round((r[0] + r[2]) / 2 / spread), round((r[1] + r[3]) / 2 / spread))
            if key not in seen:
                seen.add(key)
                uniq.append((s_, cc))
        sc = uniq
    if routes:
        good = []
        for s_, cc in sc[:tries]:
            if s_[0]:
                break
            if not check_routes(room, items + cc)[0]:
                good.append(cc)
                if len(good) >= n:
                    break
        if good:
            return good
    return [c for _s, c in sc[:n]]


def complete(room, tpl, L, sk, core_items, meta, cache):
    """Добавить к ядру кресла/2-й диван, свет, комод, столовую, кашпо — жадно лучшее место; выдать до 4 составов с путями."""
    sofa = core_items[0]
    base = list(core_items)
    sides = ['hi', 'lo']
    outs = []
    combos = []
    if L.get('sofa2') and sk.get('диван 2'):
        for sd in sides:
            combos.append([(sd, 'sofa2')] + ([(OPPOSITE_SIDE[sd], 'arm')] if L['arm'] else []))
    elif L['arm'] >= 2:
        combos.append([('hi', 'arm'), ('lo', 'arm')])
    elif L['arm'] == 1:
        combos += [[('hi', 'arm')], [('lo', 'arm')]]
    else:
        combos.append([])
    for combo in combos:
        its = list(base)
        used = set()
        for sd, kind in combo:
            sku = sk['диван 2'] if kind == 'sofa2' else sk.get('кресло')
            if sku:
                its += greedy(room, its, meta, flank_cands(meta, sku, sd, kind, '2-й диван' if kind == 'sofa2' else 'кресло', sofa),
                              cache)[0]
                used.add(sd)
        its = fit_rug(room, its, meta, cache)
        din_opts = [[]]     # крупное первым: столовая, потом хранение и свет, кашпо — в оставшийся угол
        if L['dining'] and sk.get('стол обеденный') and sk.get('стул'):
            taken = [r for i in its for r in i['rects']] + list(room['_geo']['rads']) + \
                ([room['_geo']['kitchen']] if room['_geo'].get('kitchen') else [])
            # все свободные места: разные клетки 60 см по всей комнате, каждое — до конца состава
            din_opts = greedy(room, its, meta, dining_cands(room, sk, L['dining'], taken, L.get('compact')), cache,
                              n=12, tries=40, spread=60)
        opt = L.get('optional') or ()
        for dg in din_opts:
            full = its + dg
            skipped = []
            if L['light'] == 'floor' and sk.get('торшер'):
                free_sides = [x for x in ('lo', 'hi') if x not in used] or ['lo', 'hi']
                full += greedy(room, full, meta, [floor_lamp(meta, sk['торшер'], sofa, x) for x in free_sides], cache)[0]
            if L['light'] == 'dresser' and sk.get('комод'):
                full += greedy(room, full, meta, dresser_cands(room, sk['комод']), cache)[0]
            if L['plant'] and sk.get('кашпо'):
                pl = greedy(room, full, meta, plant_cands(room, sk['кашпо']), cache)[0]
                if 'plant' not in opt or score(evaluate(room, full + pl, meta, cache))[0] == 0:
                    full += pl          # «по желанию»: кашпо, которому нет места, не ставим
                else:
                    skipped.append('кашпо')
            vs = evaluate(room, full, meta, cache)
            sc = score(vs)
            if sc[0] == 0:
                rv, _ = check_routes(room, full)
                vs = vs + rv
                sc = score(vs)
            outs.append({'items': full, 'vs': vs, 'score': sc, 'meta': meta, 'skipped': skipped})
            if sc[0] == 0:
                break
    return outs


OPPOSITE_SIDE = {'hi': 'lo', 'lo': 'hi'}


def fit_rug(room, its, meta, cache):
    """Посадка стоит — ковёр сдвигаем вдоль стены дивана (до ±60 см, шаг 5), если так передние ножки кресел и 2-го дивана
    встают на ковёр; столик остаётся целиком на ковре (проверки те же). Без нарушения посадки — ковёр не трогаем."""
    ri = next(i for i, x in enumerate(its) if x['kind'] == 'rug')

    def bad(lst):
        vs = evaluate(room, lst, meta, cache)
        sc = score(vs)
        return (sc[0], sum(1 for v in vs if v['hard'] and v['code'] == 'SEAT_OFF_RUG'), sc[1])
    base = bad(its)
    if not base[1]:
        return its
    r = its[ri]['rect']
    along_x = meta['s'] in ('south', 'north')
    best = (base, its)
    for du in sorted(np.arange(-60, 61, 5), key=abs):
        if not du:
            continue
        r2 = (r[0] + du, r[1], r[2] + du, r[3]) if along_x else (r[0], r[1] + du, r[2], r[3] + du)
        cand = list(its)
        cand[ri] = dict(its[ri], rect=r2, rects=[r2])
        b = bad(cand)
        if b < best[0]:
            best = (b, cand)
    return best[1]


def search_rugs(room, tpl, lid, L, sk, rugs):
    """Расстановка с ковром набора; если посадка не стоит ножками на ковре — ковры банка крупнее по очереди. Нет такого
    ковра — красная отметка «дыра каталога» (templates.json `seats_front_legs_on_rug`)."""
    res = search(room, tpl, lid, L, sk)
    res['sk'] = sk
    if res['ok'] or not any(v['code'] == 'SEAT_OFF_RUG' and v['hard'] for v in res['vs']):
        return res
    own = sk['ковёр']
    tried = []
    for rug in rugs:
        if rug['w'] * rug['d'] <= own['w'] * own['d'] + EPS:
            continue
        sk2 = dict(sk)
        sk2['ковёр'] = rug
        r2 = search(room, tpl, lid, L, sk2)
        r2['sk'] = sk2
        tried.append(f"{rug['w']:.0f}×{rug['d']:.0f}")
        if r2['ok']:
            r2['notes'] = [f"ковёр набора {own['w']:.0f}×{own['d']:.0f} мал для посадки — взят больше из банка "
                           f"{rug['w']:.0f}×{rug['d']:.0f}"]
            return r2
        if r2['score'] < res['score']:
            res = r2
    big = max(rugs, key=lambda x: x['w'] * x['d'])
    res['vs'].insert(0, V('RUG_GAP', f"дыра каталога: в банке нет ковра, на котором стоит вся посадка "
                                     f"(пробовали {', '.join(tried) or 'нет крупнее'}; самый большой {big['w']:.0f}×{big['d']:.0f})", []))
    res['ok'] = False
    return res


def run_room(room, sets, style):
    tpls, why = choose_templates(room['area'], max(room['W'], room['D']) / min(room['W'], room['D']) if not room.get('annex') else 1.5,
                                 bool(room.get('kitchen')), bool(room.get('annex')))
    tried = []
    chosen = None
    rugs = bank_rugs(sets)
    for tpl in tpls:
        sks = pick_skus(sets, room['area'], tpl, style, room, k=4)
        if not sks:
            tried.append({'tpl': tpl, 'skip': 'в банке нет набора под шаблон'})
            continue
        fit, why_not = core_need(room, sks[0], tpl)
        for lid, L, _d in levels_for(room, tpl):
            best_l = None
            for sk in sks:
                res = search_rugs(room, tpl, lid, L, sk, rugs)
                if not fit:
                    res['vs'].insert(0, V('CORE_TIGHT', why_not, []))
                    res['ok'] = False
                if best_l is None or res['score'] < best_l['score'] or res['ok']:
                    best_l = res
                if res['ok']:
                    break
            best_l.setdefault('notes', [])
            if best_l.get('skipped'):
                best_l['notes'].append(f"{', '.join(best_l['skipped'])} — по желанию, места нет: не ставим")
            if L['dining'] == 0 and tried and tried[-1].get('tpl') == tpl:
                why_d = '; '.join(hard_reasons(tried[-1])[:2]) or 'не влезает'
                best_l['notes'].append(f"без столовой: стол на 2 (и компактный) не встал ни на одно место — {why_d}")
            tried.append(best_l)
            if best_l['ok']:
                chosen = best_l
                break
            if not fit:          # ядро не влезает поперёк — уровни меньше не помогут (они не трогают ядро)
                break
        if chosen:
            break
    return chosen, tried, why


def hard_reasons(res):
    seen = []
    for v in res['vs']:
        if v['hard']:
            t = CODE_RU.get(v['code'], v['text'])
            if t not in seen:
                seen.append(t)
    return seen


# ---------------------------------------------------------------- «было» — /demo сейчас
KIND_OF = {'диван': 'sofa', 'столик': 'table', 'пуф': 'pouf', 'торшер': 'lamp', 'ковёр': 'rug', 'тв-тумба': 'tv',
           'стол обеденный': 'dtable', 'стул': 'chair', 'кресло': 'arm', 'комод': 'dresser', 'кашпо': 'plant'}


def bylo(room, data_file, style='сканди'):
    d = json.load(open(data_file))
    v = next(x for x in d['variants'] if x.get('room_id') == 'living' and x.get('style') == style)
    D = room['D']
    items = []
    for i in v['items']:
        base = i['role'].split(' ')[0] if i['role'] not in KIND_OF else i['role']
        kind = KIND_OF.get(i['role']) or KIND_OF.get(base)
        if not kind:
            continue
        rot = int(round(float(i.get('rot') or 0))) % 180
        w, dd = float(i['w']), float(i['d'])
        ex, ey = (w, dd) if rot == 0 else (dd, w)
        cx, cy = float(i['x']), D - float(i['y'])
        sku = {'name': (i.get('sku') or {}).get('name', i['role']), 'w': w, 'd': dd, 'h': float(i.get('h') or 0), 'dia': 0.0}
        it = obj(kind, i['role'], sku, (cx - ex / 2, cy - ey / 2, cx + ex / 2, cy + ey / 2),
                 'dining' if kind in ('dtable', 'chair') else 'seat', rot=float(i.get('rot') or 0))
        items.append(it)
    sofa = next(i for i in items if i['kind'] == 'sofa')
    tv = next(i for i in items if i['kind'] == 'tv')
    r = sofa['rot'] * math.pi / 180
    fx, fy = math.sin(r), -math.cos(r)      # перёд дивана в координатах схемы (страница: (sin, cos) при y вниз)
    scx, scy = (sofa['rect'][0] + sofa['rect'][2]) / 2, (sofa['rect'][1] + sofa['rect'][3]) / 2
    ex, ey = scx - fx * sofa['sku']['d'] * (0.5 - SEAT_EYE), scy - fy * sofa['sku']['d'] * (0.5 - SEAT_EYE)
    tcx, tcy = (tv['rect'][0] + tv['rect'][2]) / 2, (tv['rect'][1] + tv['rect'][3]) / 2
    dist = math.hypot(tcx - ex, tcy - ey)
    scr = min(SCREEN_FRAC * tv['sku']['w'], dist / TV_PREF * 0.8716)
    meta = {'dist': dist, 'diag': scr / 0.8716, 'screen_w': scr, 'eye_pt': (ex, ey), 'tv_pt': (tcx, tcy), 'bylo': True}
    cache = {}
    vs = []
    for it in items:
        vs += static_checks(room, it)
    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            vs += pair_checks(items[a], items[b])
    rv, paths = check_routes(room, items, want_paths=True)
    vs += rv
    listed = [x['role'] for x in v.get('decor') or []]
    res = {'items': items, 'vs': vs, 'score': score(vs), 'meta': meta, 'bylo': True, 'ok': score(vs)[0] == 0,
           'tpl': '—', 'lid': 'было', 'desc': '/demo сейчас (сканди)', 'L': None, 'paths': paths, 'listed': listed}
    del cache
    return res


# ---------------------------------------------------------------- рисунок
ITEM_COL = {'sofa': (176, 190, 197), 'sofa2': (176, 190, 197), 'table': (188, 170, 164), 'tv': (121, 85, 72),
            'arm': (159, 168, 218), 'lamp': (255, 241, 118), 'dresser': (179, 157, 219), 'dtable': (255, 224, 178),
            'chair': (255, 204, 128), 'plant': (129, 199, 132), 'pouf': (207, 216, 220), 'rug': (239, 235, 233)}
ITEM_RU = {'sofa': 'Диван', 'sofa2': 'Диван 2', 'table': 'Столик', 'tv': 'ТВ-тумба', 'arm': 'Кресло', 'lamp': 'Торшер',
           'dresser': 'Комод', 'dtable': 'Стол', 'chair': 'с', 'plant': 'К', 'pouf': 'Пуф', 'rug': 'Ковёр'}
ITEM_SHORT = {'sofa': 'Д', 'sofa2': 'Д2', 'table': 'Ст', 'tv': 'ТВ', 'arm': 'Кр', 'lamp': 'Т', 'dresser': 'Км', 'dtable': 'Ст',
              'chair': 'с', 'plant': 'К', 'pouf': 'П', 'rug': ''}
ZONE_COL = {'DRESSER_FRONT': (142, 36, 170, 50), 'CHAIR_ZONE': (251, 140, 0, 55), 'door': (255, 193, 7, 80),
            'aisle': (96, 125, 139, 45), 'portal': (255, 193, 7, 60)}


def draw_door(cv, room, dd, g, d):
    hx, hy = g['hinge']
    r = min(dd['swing'], dd['width'])
    bb = cv.R((hx - r, hy - r, hx + r, hy + r))
    a0, a1 = {('south', 'left'): (270, 360), ('south', 'right'): (180, 270), ('north', 'left'): (0, 90),
              ('north', 'right'): (90, 180), ('west', 'left'): (270, 360), ('west', 'right'): (0, 90),
              ('east', 'left'): (180, 270), ('east', 'right'): (90, 180)}[(dd['wall'], dd['hinge'])]
    d.arc(bb, a0, a1, fill=(120, 90, 0), width=2)
    inx, iny = {'south': (0, 1), 'north': (0, -1), 'west': (1, 0), 'east': (-1, 0)}[dd['wall']]
    d.line([cv.P(hx, hy), cv.P(hx + inx * r, hy + iny * r)], fill=(120, 90, 0), width=3)


def dashed(d, p0, p1, col, w=2, on=8, off=6):
    L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    if L < 1:
        return
    ux, uy = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
    t = 0.0
    while t < L:
        t1 = min(t + on, L)
        d.line([(p0[0] + ux * t, p0[1] + uy * t), (p0[0] + ux * t1, p0[1] + uy * t1)], fill=col, width=w)
        t = t1 + off


def sofa_frame(sofa):
    """Ось дивана: спинка (u вдоль стены), перёд — направление в комнату. Для «было» — из rot."""
    r = sofa['rect']
    s = sofa.get('s')
    if s is None:
        rot = int(round(sofa.get('rot', 0))) % 360
        s = {0: 'north', 180: 'south', 90: 'east', 270: 'west'}.get(rot, 'south')   # страница: rot 0 — задом к y=0 (север)
    return s, r


def soft_marks(res):
    """Мелочи на носителях: подушки и плед на диване, ваза на столике, лампа на комоде; картины — над диваном или комодом."""
    out = []
    items = res['items']
    sofa = next((i for i in items if i['kind'] == 'sofa'), None)
    if res.get('bylo') or not sofa:
        return out
    s, r = sofa_frame(sofa)
    n = pillow_count(sofa['sku']['w'])
    depth = sofa.get('depth', sofa['sku']['d'])
    u0, v0 = sofa['u0'], sofa['v0']
    Sw = sofa['sku']['w'] - (SECTION_D if res['meta'].get('corner') and res['meta'].get('chaise_hi') else 0)
    u_start = u0 + (SECTION_D if res['meta'].get('corner') and not res['meta'].get('chaise_hi') else 0)
    arm, edge = 15.0, 10.0
    pw = 45.0
    U = Sw - 2 * arm - 2 * edge
    gap = (U - n * pw) / max(n - 1, 1) if n > 1 else 0
    F = res['meta']['F']
    for k in range(n):
        a = u_start + arm + edge + k * (pw + gap) if n > 1 else u_start + Sw / 2 - pw / 2
        out.append(('pillow', F(a, a + pw, v0 + 22, v0 + 22 + 14)))
    side_hi = not any(i['kind'] == 'arm' and i.get('side') == 'hi' for i in items)
    ua = u0 + sofa['sku']['w'] - arm if side_hi else u0
    out.append(('throw', F(ua - 4, ua + arm + 4, v0 + depth * 0.25, v0 + depth * 0.25 + 45)))
    if res['L']['vase']:
        vs = res['sk'].get('ваза') or {'w': 16}
        dv = max(vs['w'], 10)
        m = max(8.0, dv / 2 + 3)
        t0, t1, Tw = res['meta']['t']
        c = res['meta']['c']
        out.append(('vase', F(c - Tw / 2 + m, c - Tw / 2 + m + dv, t0 + m, t0 + m + dv)))
    dr = next((i for i in items if i['kind'] == 'dresser'), None)
    if dr and res['sk'].get('лампа'):
        lw = max(res['sk']['лампа']['w'], 20)
        rr = band(res['room']['box'], dr['wall'], dr['off'] + dr['sku']['w'] - 8 - lw, lw, 6, 6 + lw)
        out.append(('lamp', rr))
    # картины: над диваном (глухой участок), иначе над комодом
    seg = F(res['meta']['c'] - sofa['sku']['w'] / 3, res['meta']['c'] + sofa['sku']['w'] / 3, 0, 4)
    room = res['room']
    blocked = any(inter(expand(seg, 2), expand(o, 2)) for o in room['_geo']['wins']) or \
        any(o['wall'] == s and inter(expand(seg, 2), band(room, o['wall'], o['off'], o['width'], 0, 4)) for o in room['doors'])
    if res['meta']['v0'] > 0:
        blocked = True
    if not blocked:
        out.append(('art', seg, s))
    elif dr:
        out.append(('art', band(room['box'], dr['wall'], dr['off'] + dr['sku']['w'] / 6, dr['sku']['w'] * 2 / 3, 0, 4), dr['wall']))
    return out


def wrap(text, f, maxw, indent='    '):
    """Перенос по ширине в пикселях: строка длиннее листа не обрезается."""
    d = ImageDraw.Draw(Image.new('RGB', (4, 4)))
    out, cur = [], ''
    for wd in text.split(' '):
        t = (cur + ' ' + wd) if cur else wd
        if cur and d.textlength(t, font=f) > maxw:
            out.append(cur)
            cur = indent + wd
        else:
            cur = t
    out.append(cur)
    return out


def render(room, res, s, compact=False, title=None, subtitle=None, foot_lines=None, paths=None, inset=True):
    fs = 15 if compact else 14
    ins_w = 0 if (compact or not inset or res.get('bylo')) else 330
    min_w = 640 if compact else 1020
    tw = max(int(56 + room['W'] * s + 36 + ins_w), min_w) - 20
    subs = wrap(subtitle or '', font(15 if compact else 14), tw)
    mt = 72 + 20 * len(subs)
    foot_lines = [x for ln in (foot_lines or []) for x in wrap(ln, font(fs), tw)]
    cv = Canvas(room, s, ml=56, mt=mt, mr=36 + ins_w, mb=58 + (len(foot_lines) * (fs + 9) + 12), min_w=min_w)
    W, D = room['W'], room['D']
    geo = room['_geo']
    d = ImageDraw.Draw(cv.img)
    for x in range(0, int(W) + 1, 50):
        d.line([cv.P(x, 0), cv.P(x, D)], fill=(225, 225, 225) if x % 100 else (200, 200, 200), width=1)
    for y in range(0, int(D) + 1, 50):
        d.line([cv.P(0, y), cv.P(W, y)], fill=(225, 225, 225) if y % 100 else (200, 200, 200), width=1)
    fsm = font(11 if not compact else 12)
    for x in range(0, int(W) + 1, 100):
        text_c(d, (cv.P(x, 0)[0], cv.P(x, 0)[1] + 14), str(x), fsm, (120, 120, 120))
    for y in range(0, int(D) + 1, 100):
        p = cv.P(0, y)
        text_c(d, (p[0] - 22, p[1]), str(y), fsm, (120, 120, 120))
    # пустота вне контура (Г-образная)
    if room.get('poly'):
        for f in [(250, 400, 600, 650)]:
            d.rectangle(cv.R(f), fill=(236, 236, 236))
    od = ImageDraw.Draw(cv.ov)
    zl = []
    for g in geo['doors']:
        od.rectangle(cv.R(clip(g['strip'], room) or g['strip']), fill=ZONE_COL['door'])
        zl.append((g['strip'], f'{DOOR_PASS:.0f}', None))
    if geo.get('portal'):
        od.rectangle(cv.R(geo['portal']), fill=ZONE_COL['portal'])
        zl.append((geo['portal'], f'{P_MAIN:.0f}', None))
    if geo.get('aisle'):
        od.rectangle(cv.R(geo['aisle']), fill=ZONE_COL['aisle'])
        zl.append((geo['aisle'], f'{P_MAIN:.0f} у кухни', None))
    for it in res['items']:
        for z in it['zones']:
            zc = clip(z['rect'], room)
            if zc:
                od.rectangle(cv.R(zc), fill=ZONE_COL[z['code']])
                if z['code'] != 'CHAIR_ZONE':
                    zl.append((zc, z['label'], z.get('wall')))
    cv.img.paste(cv.ov, (0, 0), cv.ov)
    d = ImageDraw.Draw(cv.img)
    for dd, g in zip(room['doors'], geo['doors']):
        draw_door(cv, room, dd, g, d)
    if geo.get('kitchen'):
        k = geo['kitchen']
        d.rectangle(cv.R(k), fill=(207, 216, 220), outline=(84, 110, 122), width=2)
        rr = cv.R(k)
        text_c(d, ((rr[0] + rr[2]) / 2, (rr[1] + rr[3]) / 2), 'КУХНЯ\n(условно)', font(fs - 2, True), (55, 71, 79))
    # ковёр — под всем
    for it in res['items']:
        if it['kind'] == 'rug':
            rr = cv.R(it['rect'])
            d.rectangle(rr, fill=ITEM_COL['rug'], outline=(141, 110, 99), width=2)
            for k in range(int(rr[0]) + 6, int(rr[2]) - 4, 12):
                d.line([(k, rr[1] + 3), (k, rr[1] + 7)], fill=(141, 110, 99), width=1)
    for it in res['items']:
        if it['kind'] == 'rug':
            continue
        for r in it['rects']:
            col = ITEM_COL.get(it['kind'], (220, 220, 220))
            rr = cv.R(r)
            if it['kind'] == 'plant':
                d.ellipse(rr, fill=col, outline=(46, 125, 50), width=2)
            else:
                d.rectangle(rr, fill=col, outline=(60, 60, 60), width=2)
        if it['kind'] == 'sofa' and len(it['rects']) > 1:     # угловой — убрать шов
            pass
    # ТВ: экран у задней кромки тумбы + ось взгляда
    tv_lab = None
    meta = res['meta']
    tv = next((i for i in res['items'] if i['kind'] == 'tv'), None)
    sofa = next((i for i in res['items'] if i['kind'] == 'sofa'), None)
    if tv and sofa and meta:
        if res.get('bylo'):
            e, t = meta['eye_pt'], meta['tv_pt']
        else:
            F, G = meta['F'], meta['G']
            er = F(meta['c'] - 1, meta['c'] + 1, meta['eye'] - 1, meta['eye'] + 1)
            tc = meta.get('tvc', meta['c'])
            tr = G(tc - 1, tc + 1, tv['sku']['d'] / 2 - 1, tv['sku']['d'] / 2 + 1)
            e, t = ((er[0] + er[2]) / 2, (er[1] + er[3]) / 2), ((tr[0] + tr[2]) / 2, (tr[1] + tr[3]) / 2)
            sc = G(tc - meta['screen_w'] / 2, tc + meta['screen_w'] / 2, 3, 7)
            d.rectangle(cv.R(sc), fill=(20, 20, 20))
        dashed(d, cv.P(*e), cv.P(*t), (69, 39, 160), 2)
        tv_lab = (cv.P(t[0] + (e[0] - t[0]) * 0.22, t[1] + (e[1] - t[1]) * 0.22),
                  f"{meta['dist'] / 100:.1f} м".replace('.', ','))
    # мелочи
    marks = soft_marks(res)
    for kind, rr, *_w in marks:
        R = cv.R(rr)
        if kind == 'pillow':
            d.rectangle(R, fill=(255, 171, 145), outline=(191, 54, 12))
        elif kind == 'throw':
            d.rectangle(R, fill=(161, 136, 127), outline=(78, 52, 46))
            for k in range(int(R[0]), int(R[2]), 4):
                d.line([(k, R[1]), (k, R[3])], fill=(121, 85, 72), width=1)
        elif kind == 'vase':
            d.ellipse(R, fill=(100, 181, 246), outline=(13, 71, 161), width=2)
        elif kind == 'lamp':
            d.ellipse(R, fill=(255, 235, 59), outline=(245, 127, 23), width=2)
    # люстра — центр ковра (зона посадки); подвес над столом
    rug = next((i for i in res['items'] if i['kind'] == 'rug'), None)
    if rug and not res.get('bylo'):
        lu = res['sk'].get('люстра') or {}
        dia = lu.get('dia') or lu.get('w') or 50
        cx, cy = (rug['rect'][0] + rug['rect'][2]) / 2, (rug['rect'][1] + rug['rect'][3]) / 2
        R = cv.R((cx - dia / 2, cy - dia / 2, cx + dia / 2, cy + dia / 2))
        for k in range(0, 360, 24):          # люстра — на потолке: пунктирный круг + точка подвеса
            d.arc(R, k, k + 12, fill=(245, 127, 23), width=3)
        d.ellipse([(R[0] + R[2]) / 2 - 4, (R[1] + R[3]) / 2 - 4, (R[0] + R[2]) / 2 + 4, (R[1] + R[3]) / 2 + 4], fill=(245, 127, 23))
        dt = next((i for i in res['items'] if i['kind'] == 'dtable'), None)
        if dt and (room.get('kitchen') or room.get('annex') or room['area'] >= 20):
            cx, cy = (dt['rect'][0] + dt['rect'][2]) / 2, (dt['rect'][1] + dt['rect'][3]) / 2
            R = cv.R((cx - 22, cy - 22, cx + 22, cy + 22))
            for k in range(0, 360, 30):
                d.arc(R, k, k + 15, fill=(245, 127, 23), width=3)
    draw_hatch(cv, [rg for v in res['vs'] if v['hard'] for rg in v['regions']])
    d = ImageDraw.Draw(cv.img)
    for code, w, pts in (paths or []):
        if len(pts) < 2:
            continue
        c = ROUTE_COL.get(w, (60, 60, 60))
        pp = [cv.P(x, y) for x, y in pts[::3]] + [cv.P(*pts[-1])]
        for i in range(0, len(pp) - 1, 2):
            d.line([pp[i], pp[i + 1]], fill=c, width=3)
        ex, ey = pp[-1]
        d.ellipse([ex - 5, ey - 5, ex + 5, ey + 5], fill=c)
    # стены
    if room.get('poly'):
        pts = [cv.P(x, y) for x, y in room['poly']] + [cv.P(*room['poly'][0])]
        d.line(pts, fill=(30, 30, 30), width=5, joint='curve')
        p = room['portal']
        d.line([cv.P(p[0], p[1]), cv.P(p[2], p[3])], fill=(150, 150, 150), width=1)
    else:
        d.rectangle([*cv.P(0, D), *cv.P(W, 0)], outline=(30, 30, 30), width=5)
    for dd in room['doors']:
        d.line([cv.P(*wall_point(room, dd['wall'], dd['off'])), cv.P(*wall_point(room, dd['wall'], dd['off'] + dd['width']))],
               fill=(255, 255, 255), width=7)
    for w in room['wins']:
        d.line([cv.P(*wall_point(room, w['wall'], w['off'])), cv.P(*wall_point(room, w['wall'], w['off'] + w['width']))],
               fill=(79, 195, 247), width=8)
    for rr in geo['rads']:
        d.rectangle(cv.R(rr), fill=(255, 112, 67), outline=(191, 54, 12))
    # шторы — пакеты по краям каждого окна, перед радиатором
    if not res.get('bylo'):
        for w in room['wins']:
            for u0 in (w['off'] - 20, w['off'] + w['width'] - 8):
                R = cv.R(band(room, w['wall'], u0, 28, 13, 23))
                x0, y0, x1, y1 = R
                d.rectangle(R, fill=(225, 190, 231), outline=(123, 31, 162))
                if x1 - x0 > y1 - y0:
                    for k in range(int(x0) + 2, int(x1), 5):
                        d.line([(k, y0), (k, y1)], fill=(123, 31, 162), width=1)
                else:
                    for k in range(int(y0) + 2, int(y1), 5):
                        d.line([(x0, k), (x1, k)], fill=(123, 31, 162), width=1)
    fz =font(12 if not compact else 13, True)
    for z, lab, zw in zl:
        rr = cv.R(z)
        if (rr[2] - rr[0]) > 22 and (rr[3] - rr[1]) > 14:
            cx, cy = (rr[0] + rr[2]) / 2, (rr[1] + rr[3]) / 2
            k = 9 * cv.s
            if zw == 'south':
                cy = rr[1] + k
            elif zw == 'north':
                cy = rr[3] - k
            elif zw == 'west':
                cx = rr[2] - k * 2.5
            elif zw == 'east':
                cx = rr[0] + k
            text_c(d, (cx, cy), lab, fz, (60, 60, 60))
    fi, fi2 = font(fs, True), font(fs - 2)
    for it in res['items']:
        r = cv.R(it.get('bbox', it['rect']) if it['kind'] != 'sofa' else it['rect'])
        wpx, hpx = r[2] - r[0], r[3] - r[1]
        dims = f"{it['sku']['w']:.0f}×{it['sku']['d']:.0f}"
        if it['kind'] == 'rug':
            txt = f"ковёр {dims}"
            text_c(d, ((r[0] + r[2]) / 2, r[3] - 10), txt, font(fs - 3), (93, 64, 55))
            continue
        txt = f"{ITEM_RU[it['kind']]}\n{dims}"
        bb = d.multiline_textbbox((0, 0), txt, font=fi, align='center')
        cy = (r[1] + r[3]) / 2 + (8 if it['kind'] == 'sofa' and not res.get('bylo') else 0)
        if bb[2] - bb[0] > wpx - 8 or bb[3] - bb[1] > hpx - 8:
            txt = f"{ITEM_SHORT[it['kind']]}\n{dims}"
            bb = d.multiline_textbbox((0, 0), txt, font=fi2, align='center')
            if bb[2] - bb[0] > wpx - 8 or bb[3] - bb[1] > hpx - 8:
                txt = ITEM_SHORT[it['kind']]
            text_c(d, ((r[0] + r[2]) / 2, cy), txt, fi2)
        else:
            text_c(d, ((r[0] + r[2]) / 2, cy), txt, fi)
    for kind, rr, *w_ in marks:      # картины — коричневая полоса по стене (2/3 ширины носителя)
        if kind != 'art':
            continue
        bx = room['box']          # в Г-образной стена — основного прямоугольника, не хвоста
        x0_, y0_, x1_, y1_ = rr
        if w_[0] in ('south', 'north'):
            yy = 0 if w_[0] == 'south' else bx['D']
            d.line([cv.P(x0_, yy), cv.P(x1_, yy)], fill=(141, 85, 36), width=9)
        else:
            xx = 0 if w_[0] == 'west' else bx['W']
            d.line([cv.P(xx, y0_), cv.P(xx, y1_)], fill=(141, 85, 36), width=9)
    if tv_lab:
        (lx, ly), lab = tv_lab
        f_ = font(fs - 2, True)
        bb = d.textbbox((0, 0), lab, font=f_)
        d.rectangle([lx + 4, ly - 10, lx + 10 + bb[2] - bb[0], ly + 10], fill=(255, 255, 255), outline=(69, 39, 160))
        d.text((lx + 7, ly - 9), lab, font=f_, fill=(69, 39, 160))
    fo = font(12 if not compact else 13)
    OFS = {'south': (0, 32), 'north': (0, -14), 'west': (-26, 0), 'east': (26, 0)}   # юг — ниже цифр шкалы
    for w in room['wins']:
        p = cv.P(*wall_point(room, w['wall'], w['off'] + w['width'] / 2))
        dx, dy = OFS[w['wall']]
        text_c(d, (p[0] + dx, p[1] + dy), f"окно\n{w['width']:.0f}" if w['wall'] in ('west', 'east') else f"окно {w['width']:.0f}", fo, (13, 71, 161))
    for dd in room['doors']:
        p = cv.P(*wall_point(room, dd['wall'], dd['off'] + dd['width'] / 2))
        dx, dy = OFS[dd['wall']]
        text_c(d, (p[0] + dx, p[1] + dy), f"дверь\n{dd['width']:.0f}" if dd['wall'] in ('west', 'east') else f"дверь {dd['width']:.0f}", fo, (120, 90, 0))
    x0, y0 = cv.P(0, D)
    x1, y1 = cv.P(W, 0)
    fdim = font(14 if not compact else 15, True)
    text_c(d, ((x0 + x1) / 2, y0 - 34), f'{W:.0f} см', fdim, (40, 40, 40))
    d.line([(x0, y0 - 22), (x1, y0 - 22)], fill=(80, 80, 80), width=1)
    dimv = Image.new('RGBA', (120, 24), (255, 255, 255, 0))
    ImageDraw.Draw(dimv).text((2, 2), f'{D:.0f} см', font=fdim, fill=(40, 40, 40))
    dimv = dimv.rotate(90, expand=True)
    busy = [(cv.P(0, o['off'] + o['width'])[1] - 22, cv.P(0, o['off'])[1] + 22)
            for o in room['wins'] + room['doors'] if o['wall'] == 'west']
    for yc in ((y0 + y1) / 2, y0 + (y1 - y0) * 0.2, y0 + (y1 - y0) * 0.8):   # размер — где на западной стене нет подписи проёма
        if not any(a < yc + 60 and yc - 60 < b for a, b in busy):
            cv.img.paste(dimv, (int(x0 - 54), int(yc - 60)), dimv)
            break
    text_c(d, (x1 + 18, y0 - 34), 'С↑', font(13, True), (90, 90, 90))
    d.text((10, 6), title or room['title'], font=font(20 if compact else 19, True), fill=(10, 10, 10))
    for i, ln in enumerate(subs if subtitle else []):
        d.text((10, 32 + 20 * i), ln, font=font(15 if compact else 14), fill=(50, 50, 50))
    if ins_w:
        draw_inset(cv.img, res, x1 + 40, y0, ins_w - 20)
    y = y1 + 44
    col = (60, 60, 60)
    for ln in foot_lines:
        if not ln.startswith('    '):
            col = (198, 40, 40) if ln.startswith('✗') else (27, 94, 32) if ln.startswith('✓') else (60, 60, 60)
        d.text((10, y), ln, font=font(fs), fill=col)
        y += fs + 9
    return cv.img


def draw_inset(img, res, x, y, w):
    """Врезка носителей крупно: диван (подушки по ширине, плед на подлокотнике), столик (ваза в задней четверти), комод (лампа)."""
    d = ImageDraw.Draw(img)
    sk = res['sk']
    so = sk['диван']
    k = w / max(so['w'], 1)
    d.text((x, y), 'Мелочи на носителях (врезка)', font=font(14, True), fill=(20, 20, 20))
    y += 24
    n = pillow_count(so['w'])
    sw, sdp = so['w'] * k, min(so['d'], SECTION_D) * k
    d.rectangle([x, y, x + sw, y + sdp], fill=ITEM_COL['sofa'], outline=(60, 60, 60), width=2)
    d.rectangle([x, y, x + sw, y + 16 * k], fill=(144, 164, 174))      # спинка
    for side in (0, 1):
        ax = x if side == 0 else x + sw - 15 * k
        d.rectangle([ax, y, ax + 15 * k, y + sdp], fill=(144, 164, 174))
    pw = 45 * k
    U = sw - 2 * 15 * k - 2 * 10 * k
    gap = (U - n * pw) / max(n - 1, 1)
    for i in range(n):
        px = x + 25 * k + i * (pw + gap)
        d.rectangle([px, y + 18 * k, px + pw, y + 32 * k], fill=(255, 171, 145), outline=(191, 54, 12), width=2)
    d.rectangle([x + sw - 19 * k, y + sdp * 0.25, x + sw + 4 * k, y + sdp * 0.25 + 45 * k], fill=(161, 136, 127), outline=(78, 52, 46))
    txt = '\n'.join(wrap(f"подушки ×{n} (диван {so['w']:.0f} см: 2 до 190, 3 до 254, 4 шире), 8–12 от подлокотника; "
                         f"плед — на подлокотнике, свес 35–60", font(12), w, ''))
    d.multiline_text((x, y + sdp + 4), txt, font=font(12), fill=(60, 60, 60))
    y += sdp + 12 + 16 * (txt.count('\n') + 1)
    ta = sk['столик']
    Tw, Td = max(ta['w'], ta['d']) * k, min(ta['w'], ta['d']) * k
    d.rectangle([x, y, x + Tw, y + Td], fill=ITEM_COL['table'], outline=(60, 60, 60), width=2)
    if res['L'] and res['L']['vase']:
        vs = sk.get('ваза') or {'w': 16}
        dv = max(vs['w'], 10)
        m = max(8.0, dv / 2 + 3)
        d.ellipse([x + m * k, y + m * k, x + (m + dv) * k, y + (m + dv) * k], fill=(100, 181, 246), outline=(13, 71, 161), width=2)
    vt = f"столик {ta['w']:.0f}×{ta['d']:.0f}"
    if res['L'] and res['L']['vase']:
        vt += f"\nваза Ø{(sk.get('ваза') or {}).get('w', 0):.0f}:\nзадняя четверть,\nот края ≥ 8"
    d.multiline_text((x + Tw + 8, y), vt, font=font(12), fill=(60, 60, 60))
    y += max(Td, 16 * (vt.count('\n') + 1)) + 18
    dr = sk.get('комод')
    if dr and res['L'] and res['L']['light'] == 'dresser':
        Dw, Dd = dr['w'] * k, dr['d'] * k
        d.rectangle([x, y, x + Dw, y + Dd], fill=ITEM_COL['dresser'], outline=(60, 60, 60), width=2)
        lw = max((sk.get('лампа') or {}).get('w', 20), 20) * k
        d.ellipse([x + Dw - 8 * k - lw, y + 6 * k, x + Dw - 8 * k, y + 6 * k + lw], fill=(255, 235, 59), outline=(245, 127, 23), width=2)
        d.multiline_text((x + Dw + 8, y), f"комод {dr['w']:.0f}×{dr['d']:.0f}\nлампа Ø{(sk.get('лампа') or {}).get('w', 0):.0f}:\nзадняя четверть",
                         font=font(12), fill=(60, 60, 60))
    elif res['L'] and res['L']['light'] == 'floor':
        d.multiline_text((x, y), 'свет — торшер у подлокотника\n(лампе нет носителя — уровень D)', font=font(12), fill=(60, 60, 60))


# ---------------------------------------------------------------- подписи
def wall_roles(room):
    """Роли стен: дверь / окно (+ радиатор) / кухня / проход в хвост / глухая."""
    out = []
    for w in ('north', 'south', 'west', 'east'):
        r = [f"дверь {x['width']:.0f}" for x in room['doors'] if x['wall'] == w]
        r += [f"окно {x['width']:.0f}" for x in room['wins'] if x['wall'] == w]
        if any(x['wall'] == w for x in room['rads']):
            r.append('радиатор')
        if room.get('kitchen') and room['kitchen']['wall'] == w:
            r.append('кухня')
        if room.get('portal') and w == 'north':
            r.append('проход в хвост')
        out.append(f"{WALL_RU.get(w, w)} — {' + '.join(r) if r else 'глухая'}")
    return 'Стены: ' + '; '.join(out)


def foot_for(room, res, note=None):
    L = [wall_roles(room)]
    if res.get('bylo'):
        L.append('Было: расстановка /demo, стиль сканди (как сейчас на сайте)')
        kinds = {i['kind'] for i in res['items']}
        miss = [n for k, n in (('arm', 'кресло'), ('dresser', 'хранение (комод)'), ('plant', 'кашпо'))if k not in kinds]
        miss += ['лампа', 'люстра', 'плед']
        L.append('Нет в составе: ' + ', '.join(miss))
    else:
        L.append(f"Состав ({res['lid']}): {res['desc']}")
    shown = set()
    for it in res['items']:
        if it['kind'] in shown and it['kind'] in ('chair',):
            continue
        shown.add(it['kind'])
        s = it['sku']
        extra = ''
        if it['kind'] == 'chair':
            extra = f" ×{sum(1 for x in res['items'] if x['kind'] == 'chair')}"
        L.append(f"  {ITEM_RU[it['kind']] if it['kind'] != 'chair' else 'Стул'}{extra}: {s['name'][:70]} · {s['w']:.0f}×{s['d']:.0f}")
    if not res.get('bylo'):
        sk = res['sk']
        small = [f"подушки ×{pillow_count(sk['диван']['w'])}", 'плед' if sk.get('плед') else 'плед — НЕТ в наборе (условно)']
        if res['L']['vase']:
            small.append('ваза на столике')
        if res['L']['light'] == 'dresser':
            small.append('лампа на комоде')
        small += ['люстра над центром ковра', f"шторы ({(sk.get('шторы') or {}).get('name', '—')[:30]})", 'картины — отметка на стене (подбор отдельным каталогом)']
        L.append('  На носителях: ' + ', '.join(small))
        L.append(f"  Набор банка: {sk['_set']['set_id']} · {sk['_set']['style']} · полоса {sk['_set']['band']} м²")
        for nt in res.get('notes') or []:
            L.append(f"  ! {nt}")
    m = res['meta']
    L.append(f"ТВ: {m['dist']:.0f} см от глаз до экрана = {m['dist'] / max(m['diag'], 1):.1f} диагонали (норма {TV_DIAG_MIN}–2,5, лучше {TV_PREF}); "
             f"экран {m['screen_w']:.0f} см ({m['diag'] / 2.54:.0f}″) ≤ 0,9 тумбы")
    if res['ok']:
        L.append(f"✓ дверь, радиатор, окно; пути: к дивану {P_MAIN:.0f}, к окну {P_SEC:.0f}, к креслу/комоду {P_LOC:.0f}"
                 + (f", к кухне и столовой {P_MAIN:.0f}" if room.get('kitchen') or room.get('annex') else '') + ' — проходят')
    else:
        for t in hard_reasons(res)[:4]:
            L.append(f"✗ {t}")
    if res.get('bylo') and res.get('listed'):
        L.append('В корзине, но без места на плане и в 3D: ' + ', '.join(res['listed']))
    soft = [v['text'] for v in res['vs'] if not v['hard'] and v['text']]
    if soft:
        L.append('Мягко: ' + '; '.join(dict.fromkeys(soft)))
    for n in room['notes']:
        L.append('Условно: ' + n)
    if note:
        L.append(note)
    return L


# ---------------------------------------------------------------- прогон
STYLE = {'demo': 'сканди', 's350': 'джапанди', 's300': 'минимализм', 'uk377': 'современный', 'etagi': 'сканди',
         'lroom': 'неоклассика', 'r33': 'лофт', 'r41': 'современный'}


def main(out, only=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    sets = load_sets()
    rooms = [r for r in load_rooms() if not only or r['id'] in only]
    results = {}
    panels = []
    data_file = HERE.parent.parent / '.t46' / 'demo-data.json'
    for room in rooms:
        best, tried, why = run_room(room, sets, STYLE[room['id']])
        results[room['id']] = (best, tried, why)
        print(room['id'], best['tpl'] + '·' + best['lid'] if best else 'ОТКАЗ', '|',
              '; '.join(f"{t.get('tpl')}·{t.get('lid')}: {', '.join(hard_reasons(t)[:2])}" for t in tried if t is not best and 'vs' in t),
              flush=True)
        drawn = []
        if room['id'] == 'demo' and data_file.exists():
            b = bylo(room, data_file)
            b['room'] = room
            drawn.append((b, 'БЫЛО: /demo сейчас'))
            results['demo_bylo'] = b
        first = next((t for t in tried if 'vs' in t), None)
        if best is not None and first is not best:
            drawn.append((first, f"первый отвергнутый: {first['tpl']} · {first['lid']} — красным, где ломается"))
        if best is not None:
            drawn.append((best, f"ПО ШАБЛОНУ: {best['tpl']} · {best['lid']}"))
        elif first is not None:
            drawn.append((first, 'ни один уровень не прошёл'))
        for res, note in drawn:
            res['room'] = room
            if res.get('bylo'):
                paths = res['paths']
            else:
                _rv, paths = check_routes(room, res['items'], want_paths=True)
            verdict = '✓ влезает' if res['ok'] else '✗ НЕ влезает'
            tag = f"{room['id']}-{'bylo' if res.get('bylo') else res['tpl'] + '-' + res['lid']}{'-fail' if not res['ok'] else ''}"
            title = (f"БЫЛО · {room['title']} — /demo сейчас" if res.get('bylo') else
                     f"{'ПО ШАБЛОНУ · ' if res is best else ''}{room['title']} — {res['tpl']} · {res['lid']}")
            sub = (f"{why[:95]}" if not res.get('bylo') else 'как стоит сейчас на /demo (сканди)') + f" · {verdict}"
            s = min(2.0, 900 / room['W'], 700 / room['D'])
            img = render(room, res, s, title=title, subtitle=sub, foot_lines=foot_for(room, res, None if res.get('bylo') or res is best else note),
                         paths=paths)
            fn = out / f'{tag}.png'
            img.save(fn)
            panels.append({'room': room, 'res': res, 'paths': paths, 'file': fn.name, 'note': note,
                           'kind': 'bylo' if res.get('bylo') else 'best' if res is best else 'rej'})
            print('png', fn, flush=True)
    make_sheets(out, panels)
    write_matrix(out, rooms, results, panels)


def make_sheets(out, panels, per=6):
    colw = 640
    n = 0
    for si in range(0, len(panels), per):
        chunk = panels[si:si + per]
        imgs = []
        for pn in chunk:
            room, res = pn['room'], pn['res']
            s = min((colw - 100) / room['W'], 470 / room['D'])
            verdict = '✓ влезает' if res['ok'] else '✗ ' + (hard_reasons(res)[0] if hard_reasons(res) else 'не влезает')
            short = room['title'].split(' (')[0]
            dm = ImageDraw.Draw(Image.new('RGB', (4, 4)))
            parts = room['title'].split(' (')[0].split(' · ')
            for k in range(len(parts), 0, -1):       # заголовок — сколько влезает в панель
                short = ' · '.join(parts[:k])
                title = {'bylo': f"БЫЛО · {short} — /demo сейчас",
                         'best': f"ПО ШАБЛОНУ · {short} — {res['tpl']} · {res['lid']}",
                         'rej': f"{short} — {res['tpl']} · {res['lid']} (отвергнут)"}[pn['kind']]
                if dm.textlength(title, font=font(20, True)) <= colw - 24:
                    break
            sub = res['desc'] if not res.get('bylo') else 'нет кресла, хранения, лампы, люстры, кашпо; мелочи без места'
            m = res['meta']
            fl = [verdict, f"ТВ {m['dist'] / 100:.1f} м = {m['dist'] / max(m['diag'], 1):.1f} диаг"]
            if res.get('bylo') and res.get('listed'):
                fl.append('без места: ' + ', '.join(res['listed'])[:60])
            imgs.append(render(room, res, s, compact=True, title=title, subtitle=sub, foot_lines=fl, paths=pn['paths'], inset=False))
        rows = [imgs[i:i + 2] for i in range(0, len(imgs), 2)]
        H = sum(max(im.height for im in r) + 16 for r in rows) + 92
        sheet = Image.new('RGB', (colw * 2 + 30, H), (255, 255, 255))
        d = ImageDraw.Draw(sheet)
        n += 1
        d.text((14, 12), f'Гостиная: шаблоны на реальных комнатах (масштаб, сетка 50 см) · лист {n}', font=font(24, True), fill=(0, 0, 0))
        d.text((14, 44), f'пути: зелёный — {P_MAIN:.0f} к дивану/кухне/столовой · синий — {P_SEC:.0f} к окну · оранжевый — {P_LOC:.0f} к креслу/комоду',
               font=font(13), fill=(70, 70, 70))
        d.text((14, 64), 'жёлтое — 76 у двери · фиолетовое — 76 перед комодом · сиреневый пунктир — ось взгляда на ТВ · красная штриховка — нарушение',
               font=font(13), fill=(70, 70, 70))
        y = 92
        for r in rows:
            x = 10
            for im in r:
                sheet.paste(im, (x, y))
                d.rectangle([x, y, x + im.width - 1, y + im.height - 1], outline=(200, 200, 200))
                x += colw + 10
            y += max(im.height for im in r) + 16
        sheet.save(out / f'sheet-{n}.png')
        print('sheet', out / f'sheet-{n}.png', flush=True)


def write_matrix(out, rooms, results, panels):
    L = ['# Гостиная: матрица «комната → шаблон → уровень → почему» (T-20261112-46, эскиз — не солвер)', '',
         f'Нормы (`occupancy.json`): путь от двери к дивану {P_MAIN:.0f}, к окну {P_SEC:.0f}, к креслу и комоду {P_LOC:.0f}; кухня и '
         f'столовая в кухне-гостиной — {P_MAIN:.0f}; полоса у двери {DOOR_PASS:.0f}; перед комодом {DRESS:.0f}; стул — {CHAIR_ZONE:.0f}; '
         f'столик {COFFEE_GAP:.0f} от дивана; ковёр заходит под диван на {RUG_TUCK:.0f}, столик целиком на ковре; ТВ {TV_DIAG_MIN}–2,5 '
         f'диагонали (лучше {TV_PREF}), не дальше {TV_HARD:.0f}; радиатор ≥ {RAD_HARD:.0f}. Уровень — целый состав: A всё, B столовая '
         'меньше, C (< 16 м²) без кресла/вазы/кашпо, D торшер вместо «комод + лампа».', '']
    L += ['| Комната | Шаблон · уровень | Почему этот шаблон | Отвергнуто и почему |', '|---|---|---|---|']
    for room in rooms:
        best, tried, why = results[room['id']]
        rej = []
        for t in tried:
            if t is best:
                break
            if 'vs' in t:
                rej.append(f"{t['tpl']}·{t['lid']}: {', '.join(hard_reasons(t)[:2]) or '—'}")
            else:
                rej.append(f"{t['tpl']}: {t.get('skip')}")
        lev = f"**{best['tpl']} · {best['lid']}** ({best['desc']})" if best else '**отказ**'
        L.append(f"| {room['title']} | {lev} | {TPL_RU.get(best['tpl'], '') if best else ''}: {why} | {'<br>'.join(rej) or '—'} |")
    L.append('')
    b = results.get('demo_bylo')
    if b:
        best = results['demo'][0]
        L += ['## Демо: было → по шаблону', '', '| | Что не так / что стало |', '|---|---|',
              f"| Было (/demo сейчас, сканди) | по проходам {', '.join(hard_reasons(b)) or 'проходит'}, но состав неполный: нет кресла, "
              f"хранения, лампы, люстры, кашпо, пледа; в корзине без места на плане: {', '.join(b['listed'])} |"]
        if best:
            L.append(f"| По шаблону {best['tpl']} · {best['lid']} | проходит; подушки ×{pillow_count(best['sk']['диван']['w'])}, плед, ваза, "
                     'лампа, люстра, шторы, картины — у каждого носитель и место |')
        L.append('')
    L.append('## Рисунки')
    for pn in panels:
        r = pn['res']
        L.append(f"- `{pn['file']}` — {pn['room']['title']}, {r['tpl']} · {r['lid']}{' (НЕ влезает)' if not r['ok'] else ''}")
    (out / 'matrix.md').write_text('\n'.join(L) + '\n')
    js = {}
    for room in rooms:
        best, tried, why = results[room['id']]
        js[room['id']] = {'tpl': best['tpl'] if best else None, 'level': best['lid'] if best else None, 'why': why,
                          'rejected': [{'tpl': t.get('tpl'), 'level': t.get('lid'), 'reasons': hard_reasons(t) if 'vs' in t else [t.get('skip')]}
                                       for t in tried if t is not best]}
    (out / 'results.json').write_text(json.dumps(js, ensure_ascii=False, indent=1))
    print('matrix', out / 'matrix.md')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1], sys.argv[2].split(',') if len(sys.argv) > 2 else None)
