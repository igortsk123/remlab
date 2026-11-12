#!/usr/bin/env python3
"""СХЕМЫ ШАБЛОНОВ ПРИХОЖЕЙ В МАСШТАБЕ — эскизный инструмент для показа владельцу, НЕ солвер
(T-20261112-70, план `.memory_bank/plans/living-full-01.md` Т3; правило шаблонов — `.memory_bank/domain/room-templates.md`;
каталог шаблонов H1–H9 — ответ советника `.memory_bank/_intake/codex/2026-11-12-hall-templates-answer.md`).

Что делает: для 19 прихожих (демо-квартира 215 — чертёж, реестр и Г-вариант, коридоры 0,9–1,6 м, тамбур, малые 2–4 м²,
холл 2,5×3,5, Г-образная, ниша, радиатор, вход в углу и сбоку, двери санузлов, UK-дом с лестницей) идёт по семействам и веткам
хранения из `selection` паспорта и в каждой ветке перебирает ЦЕЛЫЕ составы по уровням
`services/planner-solver/rules/room-templates/hall.json` (A → … → E) с РЕАЛЬНЫМИ размерами товаров банка-кандидата
`sets-hall.next.json` и рисует вид сверху в масштабе: «БЫЛО» (раскладка нынешнего движка `planner/hall.py:solve_hall` на наборе
сканди) рядом с «ПО ШАБЛОНУ». На листе: сетка 50 см, размеры стен, вход и двери (полоса 76 и дуга — жёлтым), фронты (купе 50 /
распашной 90 — синим, обувница 50 — фиолетовым, банкетка 60 — оранжевым), площадка у входа 120 — пунктиром, дорожки от входа
до каждой двери и предмета пунктиром, узкое место пути числом, нарушения — красной штриховкой, шифр шаблона и уровень.

Нормы — те же, что у движка: проверка раскладки — `planner/hall_checks.py:validate_hall` (проход `hall_passage_min`, фронты,
двери, площадка, обувь у входа), кандидаты мест — `planner/bedroom.py:_slots`, дешёвые проверки — `planner/hall.py:_fits`.
Шаблон добавляет только СОСТАВ (уровни паспорта) и предпочтения мест (хранение у глухой стены / в нише, обувь у входа,
зеркало над низким, консоль напротив хранения в холле). Движок прихожей и пороги этот скрипт не меняет.

Итог шаблона дополнительно проходит честную растровую мерку пути `hall_passage_min` от входа: `hall_checks.route_ok` склеивает
куски свободного пола через зону у входа и пропускает щель 80 у самой двери как 85 (найдено T-70; движок не менялся).

  ~/venvs/scout/bin/python hall_schemes.py OUT_DIR [--only id,id] [--jobs N]
  # → OUT_DIR/<комната>.png, sheet-N.png, matrix.md, results.json

Только чтение банка и правил. Без сети и БД.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SOLVER = ROOT / 'services' / 'planner-solver'
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SOLVER))
import bedroom_schemes as bs  # noqa: E402
from bedroom_schemes import font, text_c  # noqa: E402
from planner import room_templates as RT  # noqa: E402
from planner.bedroom import _slots, _wall_point  # noqa: E402
from planner.geometry import base_role, footprint, room_polygon, swing_polygon  # noqa: E402
from planner.hall import ORDER, WEIGHT, _fits, _pass_ok, _place, _State, _Statics, _zone, solve_hall  # noqa: E402
from planner.hall_checks import (door_front, entrance, entry_landing, is_low, is_wall_mirror,  # noqa: E402
                                 validate_hall)
from planner.models import Item, Opening, Radiator, Room, Severity  # noqa: E402

OCC = bs.OCC
P_HARD = float(OCC['hall_passage_min'])                 # 85 — проход от входа (жёстко у движка)
P_COMF = float(OCC['hall_passage_comfort'])             # 90 — комфорт (мягко)
P_COMPACT = 75.0     # ADM M4(1) 1.15 / табл. 1.1: местное сужение 750 мм (Codex T-70 § 1) — ключа в occupancy.json НЕТ, только мерка
P_TARGET = 90.0      # ADM M4(1)/M4(2): коридор 900 мм — цель (Codex T-70); = hall_passage_comfort
DOOR_FRONT = float(OCC['passage_secondary_comfort'][0])  # 76 — полоса перед каждой дверью
ENTRY = float(OCC['hall_entry_depth'])                  # 120 — площадка у входа
SHOE_MAX = float(OCC['hall_shoe_entry_max'])            # 150
MIRROR_MAX = float(OCC['hall_mirror_exit_max'])         # 300
FRONT = {'шкаф-купе': float(OCC['wardrobe_sliding_front'][0]), 'шкаф': float(OCC['wardrobe_hinged_front_min']),
         'прихожая': float(OCC['wardrobe_hinged_front_min']), 'обувница': float(OCC['shoe_cabinet_front']),
         'банкетка': float(OCC['bench_legroom'])}
BEAM = 16
PASSPORT = RT.load('hall')
CARRIER_ROLES = ('обувница', 'консоль', 'банкетка')

RU = {'шкаф-купе': 'Купе', 'шкаф': 'Шкаф', 'прихожая': 'Модуль', 'вешалка': 'Вешалка', 'обувница': 'Обувница',
      'банкетка': 'Банкетка', 'консоль': 'Консоль', 'зеркало': 'Зеркало'}
SHORT = {'шкаф-купе': 'Купе', 'шкаф': 'Шкаф', 'прихожая': 'Мод', 'вешалка': 'Веш', 'обувница': 'Обув',
         'банкетка': 'Банк', 'консоль': 'Конс', 'зеркало': 'Зерк'}
COL = {'шкаф-купе': (144, 164, 174), 'шкаф': (120, 144, 156), 'прихожая': (144, 164, 174), 'вешалка': (188, 170, 164),
       'обувница': (179, 157, 219), 'банкетка': (255, 204, 128), 'консоль': (215, 196, 163), 'зеркало': (79, 195, 247)}
ZCOL = {'шкаф-купе': (30, 136, 229, 60), 'шкаф': (30, 136, 229, 60), 'прихожая': (30, 136, 229, 60),
        'обувница': (142, 36, 170, 55), 'банкетка': (251, 140, 0, 65), 'door': (255, 193, 7, 85)}
CODE_RU = {
    'HALL_NO_PASSAGE': f'от входа нет прохода {P_HARD:.0f}', 'HALL_DOOR_UNREACHABLE': f'нет прохода {P_HARD:.0f} к двери',
    'HALL_UNREACHABLE': f'к предмету нет прохода {P_HARD:.0f}', 'HALL_DOOR_FRONT': f'предмет в полосе {DOOR_FRONT:.0f} у двери',
    'HALL_ACCESS_BLOCKED': 'фронт предмета перекрыт', 'HALL_ACCESS_WALL': 'фронт упирается в стену',
    'HALL_NOT_AT_WALL': 'не спинкой к стене', 'COLLISION': 'предметы налезают', 'DOOR_SWING': 'предмет в дуге двери',
    'RADIATOR': 'у радиатора', 'WINDOW_BLOCKED': 'закрыто окно', 'OUT_OF_ROOM': 'не влезает в стены',
    'HALL_PASSAGE_TIGHT': f'проход уже {P_COMF:.0f} (мягко)', 'HALL_ENTRY_TIGHT': f'занята площадка {ENTRY:.0f} у входа (мягко)',
    'HALL_SHOE_FAR': f'обувь дальше {SHOE_MAX:.0f} от входа (мягко)', 'HALL_MIRROR_FAR': f'зеркало дальше {MIRROR_MAX:.0f} (мягко)',
    'HALL_ROOM_NARROW': 'стены уже нормы (свойство квартиры, мягко)',
}


# ---------------------------------------------------------------- комнаты (x — восток, y — север; offset от юга/запада)
def _d(wall, off, w, swing=0, ent=False, hinge='left'):
    o = {'kind': 'door', 'wall': wall, 'offset_cm': off, 'width_cm': w, 'swing_cm': swing, 'hinge': hinge}
    if ent:
        o['is_entrance'] = True
    return o


def load_rooms():
    scenes = json.load(open(HERE / 'hall-scenes.json'))['rooms']
    flat = {r['variant']: r for r in json.load(open(HERE / 'flat215-hall.json'))['rooms']}
    out = []

    def add(rid, title, src, spec, notes=(), **kw):
        r = {'id': rid, 'title': title, 'src': src, 'w': spec['w'], 'd': spec['d'], 'contour': spec.get('contour'),
             'openings': [{k: v for k, v in o.items() if not k.startswith('_')} for o in spec['openings']],
             'radiators': [{k: v for k, v in x.items() if not k.startswith('_')} for x in spec.get('radiators', [])],
             'notes': list(notes)}
        r.update(kw)
        out.append(r)

    add('demo', 'Демо · прихожая 153×620 (чертёж №180)', 'flat215-hall.json drawing-180', flat['drawing-180'],
        ['вход — юг (владелец 06.11); двери в кухню и гостиную открываются в комнаты, санузел — в прихожую'], demo=True)
    add('demo_l', 'Демо · Г-вариант 380×620 (полоса 80)', 'flat215-hall.json l-doors', flat['l-doors'],
        ['гипотеза чертежа: вдоль санузлов полоса 80 см (Г-образная)'])
    add('c110', 'Узкий коридор · 110×400', 'hall-scenes.json c110x400', scenes['c110x400'])
    add('c120', 'Коридор · 120×450, дверь санузла в торце', 'hall-scenes.json c120x450', scenes['c120x450'])
    add('c140', 'Коридор · 140×500, двери на обеих стенах', 'hall-scenes.json c140x500', scenes['c140x500'])
    add('c160', 'Длинный коридор · 160×600, пять дверей', 'hall-scenes.json c160x600', scenes['c160x600'])
    add('rad140', 'Коридор с радиатором · 140×450', 'hall-scenes.json rad140x450', scenes['rad140x450'])
    add('khr', 'Малая · 170×160 (2,7 м², как в хрущёвке)', 'синтетика: малая 2–3 м² (бриф)',
        {'w': 170, 'd': 160, 'openings': [_d('south', 10, 85, ent=True), _d('east', 15, 60, 60, hinge='left'),
                                           _d('east', 85, 60, 60, hinge='left'), _d('north', 75, 80)]},
        ['условная: двери ванной и туалета (60) открываются в прихожую, дверь в комнату — в комнату'])
    add('sq200', 'Квадратная · 200×200 (4 м², три двери)', 'hall-scenes.json sq200', scenes['sq200'])
    add('wide', 'Просторный холл · 250×350 (8,75 м²)', 'hall-scenes.json wide250x350', scenes['wide250x350'])
    add('l250', 'Г-образная · 250×300 (коридор 1,2 м + поворот)', 'hall-scenes.json l250x300', scenes['l250x300'])
    add('niche', 'С нишей · 170×450 + ниша 65×200', 'синтетика: большая с нишей (бриф)',
        {'w': 235, 'd': 450, 'contour': [[0, 0], [170, 0], [170, 200], [235, 200], [235, 400], [170, 400], [170, 450], [0, 450]],
         'openings': [_d('south', 40, 90, ent=True), _d('west', 150, 80), _d('west', 320, 80), _d('north', 40, 80)]},
        ['условная: ниша 65×200 на восточной стене (под встроенный шкаф)'], niche=(170.0, 200.0, 235.0, 400.0))
    add('corner', 'Вход в углу · 150×400', 'hall-scenes.json corner150x400', scenes['corner150x400'])
    add('bath150', 'Коридор 150×400, две двери санузлов внутрь', 'hall-scenes.json bath150x400', scenes['bath150x400'])
    add('west180', 'Боковой вход · 180×300', 'hall-scenes.json entr_west180x300', scenes['entr_west180x300'])
    add('reg150', 'Демо по реестру · 150×620, вход с востока', 'flat215-hall.json registry-93', flat['registry-93'])
    add('c90', 'Очень узкий · 90×400', 'hall-scenes.json c90x400', scenes['c90x400'])
    add('tiny', 'Тамбур · 100×120', 'hall-scenes.json tiny100x120', scenes['tiny100x120'])
    add('uk', 'UK дом · Hall 210×500 с лестницей', '~/remlab-logs/floorplan-bench/run-1221 A ground «Hall» (10,24 м² с лестницей)',
        {'w': 210, 'd': 500, 'contour': [[0, 0], [210, 0], [210, 500], [118, 500], [118, 380], [0, 380]],
         'openings': [_d('south', 59, 90, 90, ent=True, hinge='left'), _d('west', 52, 80), _d('west', 153, 80),
                      _d('west', 279, 80), _d('east', 145, 85), _d('north', 130, 75)]},
        ['контур — разбор плана дома A; лестница 118×120 у северо-западного угла и проёмы — по картинке, приблизительно',
         'входная дверь в Англии открывается ВНУТРЬ (дуга 90)'], stairs=(0.0, 380.0, 118.0, 500.0))
    return out


def to_room(r) -> Room:
    return Room(width_cm=r['w'], depth_cm=r['d'], contour=r.get('contour'),
                openings=[Opening(**o) for o in r['openings']], radiators=[Radiator(**x) for x in r['radiators']])


def facts(r, room: Room) -> dict:
    poly = room_polygon(room)
    rect = r.get('contour') is None
    short = min(r['w'], r['d']) if rect else None
    area = poly.area / 1e4
    doors = [o for o in r['openings'] if o['kind'] == 'door']
    walls = {o['wall'] for o in doors if not o.get('is_entrance')}
    aspect = max(r['w'], r['d']) / min(r['w'], r['d'])
    # флаги формы — ПРОДУКТОВЫЕ классификаторы листа (ключей occupancy.json нет — список в отчёте T-70):
    #   micro: короткая сторона < 100 или площадь < 1,5 м²; squareish: прямоугольник, стороны ≤ 1,75 : 1 и площадь < 6 м²;
    #   door_dense: вытянутый (≥ 2 : 1), дверей ≥ 3 вместе со входом и межкомнатные — на двух и более стенах
    micro = rect and (short < 100 or area < 1.5)
    return {'area_m2': round(area, 2), 'short_cm': short, 'doors': len(doors),
            'shape_l': bool(r.get('contour')) and not r.get('niche') and not r.get('stairs'),
            'has_niche': bool(r.get('niche')), 'has_stairs': bool(r.get('stairs')), 'micro': bool(micro),
            'squareish': bool(rect and not micro and aspect <= 1.75 and area < 6),
            'door_dense': bool(rect and aspect >= 2 and len(doors) >= 3 and len(walls) >= 2)}


# ---------------------------------------------------------------- товары (банк-кандидат сборщика прихожей, 5 стилей)
def load_pool():
    sets = json.load(open(bs.data_path('sets-hall.next.json')))
    pool = {}
    for s in sets:
        groups = [(r, [it]) for r, it in s['items'].items()] + list((s.get('alternates') or {}).items())
        for role, its in groups:
            for it in its:
                if not it.get('w') or not it.get('d'):
                    continue
                k = (role, round(it['w']), round(it['d']))
                pool.setdefault(k, {'role': role, 'w': float(it['w']), 'd': float(it['d']), 'h': float(it.get('h') or 0),
                                    'name': it.get('name', ''), 'style': s['style']})
    by = {}
    for x in pool.values():
        by.setdefault(x['role'], []).append(x)
    return sets, by


def choose_skus(by, role):
    """2–3 типоразмера роли: самый крупный, ходовой и самый мелкий (узкий) — шаблон берёт крупный, где встаёт."""
    xs = sorted(by.get(role, []), key=lambda x: (-x['w'] * x['d'], x['name']))
    if role == 'вешалка':     # вешалка-хранение: стойка (В ≥ 150) и настенная — обе
        xs = sorted(xs, key=lambda x: (-x['h'], -x['w']))
    if not xs:
        return []
    slim = min(xs, key=lambda x: (x['d'], x['w']))
    mid = xs[len(xs) // 2]
    out = []
    for x in (xs[0], mid, slim):
        if x not in out:
            out.append(x)
    return out


def item_of(sku) -> Item:
    return Item(role=sku['role'], w_cm=sku['w'], d_cm=sku['d'], h_cm=sku['h'] or None)


# ---------------------------------------------------------------- перебор по шаблону
def solid_edge(S: _Statics, slot) -> bool:
    ax, ay, bx, by = slot[5]
    ln = LineString([(ax, ay), (bx, by)])
    return not any(ln.distance(o) < 2 for o in S.openings)


def pref(r, tid, room, S, p, slot, placed):
    """Предпочтения шаблона (мягкие), очки — больше лучше."""
    role = base_role(p.role)
    fp = footprint(p)
    ent = entrance(room)
    from planner.hall_checks import dist_to_entry
    d = dist_to_entry(room, p) if ent is not None else 0.0
    sc = 0.0
    if role in ('шкаф-купе', 'шкаф', 'прихожая'):
        sc += 2.0 if solid_edge(S, slot) else 0.0
        frac, L = slot[3], slot[4]
        corner = min(frac * L - p.item.w_cm / 2, L - frac * L - p.item.w_cm / 2)
        sc += 0.6 if corner < 1 else 0.0
        sc += 0.004 * p.item.w_cm - 0.002 * min(d, 500)
        if r.get('niche') and fp.within(box(*r['niche']).buffer(1)):
            sc += 6.0
    elif role in ('обувница', 'банкетка', 'вешалка'):
        sc += -0.01 * min(d, 400) + 0.002 * p.item.w_cm
        if role == 'банкетка' and any(base_role(q.role) == 'обувница' and footprint(q).distance(fp) < 15 for q in placed):
            sc += 0.6
    elif role == 'консоль':
        sc += 1.0 if solid_edge(S, slot) else 0.0
        stor = [q for q in placed if base_role(q.role) in ('шкаф-купе', 'шкаф', 'прихожая')]
        if tid == 'H3' and stor and int(stor[0].rot) % 360 != int(p.rot) % 360:
            sc += 1.5
        sc -= 0.003 * min(d, 500)
    elif role == 'зеркало':
        sc += -0.004 * min(d, 600) + (1.5 if mirror_ok(p, placed, 'over_low') else 0.0)
    return sc


def mirror_ok(p, placed, variant):
    """over_low — висит над обувницей/консолью/банкеткой (носитель из паспорта); on_wall — на свободной стене."""
    over = [q for q in placed if base_role(q.role) in CARRIER_ROLES and is_low(q)
            and footprint(q).intersection(footprint(p)).area > 1.0]
    if variant == 'over_low':
        return bool(over)
    return not any(footprint(q).intersection(footprint(p)).area > 1.0 for q in placed)


def search_level(r, room, S, tid, lv, by, base=None):
    tpl = next(t for t in PASSPORT['templates'] if t['id'] == tid)
    places, err = RT.compile_level(PASSPORT, tpl, lv['id'], base=base)
    assert not err, err
    in_niche = bool(base)        # надстройка H7: закрытое хранение — целиком в нише
    # порядок постановки — как у движка (`planner/hall.py:ORDER`): крупное → у входа → вешалка → зеркало
    places = sorted(places, key=lambda p: (ORDER.index(p['role']) if p['role'] in ORDER else 99, p['id']))
    states = [_State([], [], 0.0, [])]
    for pl in places:
        role = pl['role']
        skus = choose_skus(by, role)
        if not skus:
            return None, f'в банке нет «{role}»'
        nxt = []
        for st in states:
            for sku in skus:
                it = item_of(sku)
                for slot in _slots(room, it):
                    p = _place(role, it, slot[0], slot[1], slot[2], f'{tid}-{lv["id"]}')
                    if is_wall_mirror(p):
                        low = max([q.item.h_cm for q in st.placed if is_low(q) and footprint(q).intersection(footprint(p)).area > 1.0]
                                  or [0.0])
                        if low:
                            p = _place(role, it, slot[0], slot[1], slot[2], f'{tid}-{lv["id"]}', low)
                        # над низкой (паспорт over_low); не встала низкая/высокая обувница — на свободную стену, состав тот же
                        if not (mirror_ok(p, st.placed, pl['variant'])
                                or (pl['variant'] == 'over_low' and mirror_ok(p, st.placed, 'on_wall'))):
                            continue
                    if in_niche and pl['group'] == 'storage' and not footprint(p).within(box(*r['niche']).buffer(1)):
                        continue
                    if not _fits(st, S, p):
                        continue
                    z = _zone(p)
                    keep = st.keep + ([(role, z)] if z is not None else [])
                    nxt.append(_State(st.placed + [p], keep, st.score + pref(r, tid, room, S, p, slot, st.placed), st.skipped))
        if not nxt:
            return None, f'«{RU.get(role, role)}» не встаёт ни на одну стену без нарушения (дуги, полосы 76 у дверей, фронта)'
        nxt.sort(key=_State.key)
        kept, seen = [], set()
        for st in nxt:
            k = tuple((p.role, round(p.x), round(p.y), p.rot) for p in st.placed)
            if k in seen:
                continue
            seen.add(k)
            if not _pass_ok(room, st.placed):
                continue
            kept.append(st)
            if len(kept) >= BEAM:
                break
        if not kept:
            return None, f'«{RU.get(role, role)}» встаёт только поперёк прохода {P_HARD:.0f} от входа'
        states = kept
    need = min(P_HARD, float(best_width(room, [])) or P_HARD)   # стены уже нормы — мерка по пустой комнате (как у движка)
    # итог — проверки движка + честная мерка пути (растр): `hall_checks.route_ok` склеивает куски свободного пола через
    # «рот» входа глубиной ~87 см, и щель 80 у входа проходит как 85 (подтверждено на c160/bath150/corner, T-70)
    for st in states:
        lay = validate_hall(room, st.placed)
        if any(v.severity is Severity.HARD for v in lay.violations):
            continue
        paths, _p = route_paths(room, st.placed, need)
        if paths and all(x[2] for x in paths):
            return {'placed': st.placed, 'violations': lay.violations, 'score': st.score}, None
    if any(not any(v.severity is Severity.HARD for v in validate_hall(room, st.placed).violations) for st in states[:3]):
        return None, f'движок пропускает, но честный путь {need:.0f} от входа рвётся (щель у входа)'
    lay = validate_hall(room, states[0].placed)
    bad = sorted({CODE_RU.get(v.code, v.code) for v in lay.violations if v.severity is Severity.HARD})
    return None, 'нарушение: ' + ', '.join(bad)


def level_value(tpl, lv, base=None):
    """Ценность состава для покупателя — вес движка по ролям (`planner/hall.py:WEIGHT`): хранение важнее обуви и т. д."""
    places, _ = RT.compile_level(PASSPORT, tpl, lv['id'], base=base)
    return sum(WEIGHT.get(p['role'], 1.0) for p in places)


def _tpl(tid):
    return next(t for t in PASSPORT['templates'] if t['id'] == tid)


def run_room(r, by):
    room = to_room(r)
    f = facts(r, room)
    order = RT.select(PASSPORT, f)
    S = _Statics(room)
    tried, cands = [], []
    h7 = _tpl('H7')
    for rank, tid in enumerate(order):
        tpl = _tpl(tid)
        # надстройка H7 «ниша»: сперва база + купе в нише (уровни базы сверху вниз), потом база как есть
        runs = []
        if f.get('has_niche') and tid in h7['applies_to']:
            runs.append('H7')
        runs.append(None)
        for mod in runs:
            for lv in tpl['levels']:
                if not RT.when_ok(lv.get('when'), f):
                    continue
                if mod:
                    got, why = search_level(r, room, S, 'H7', h7['levels'][0], by, base=(tpl, lv['id']))
                    name, val = f'{tid}+H7', level_value(h7, h7['levels'][0], base=(tpl, lv['id'])) + 0.5
                else:
                    got, why = search_level(r, room, S, tid, lv, by)
                    name, val = tid, level_value(tpl, lv)
                tried.append({'tpl': name, 'level': lv['id'], 'ok': got is not None, 'why': why or ''})
                if got:
                    cands.append((-val, rank, name, lv, got))
                    break        # лучший уровень этого варианта найден — дальше
            if any(c[2] == f'{tid}+H7' for c in cands):
                break
    if not cands:
        return {'room': r, 'facts': f, 'order': order, 'tried': tried, 'tpl': None, 'level': None, 'placed': [],
                'violations': [], 'ok': False}
    cands.sort(key=lambda c: (c[0], c[1]))
    _v, _rank, tid, lv, got = cands[0]
    return {'room': r, 'facts': f, 'order': order, 'tried': tried, 'tpl': tid, 'level': lv['id'], 'level_label': lv.get('label', ''),
            'placed': got['placed'], 'violations': got['violations'], 'ok': True,
            'mirror_variant': (lv.get('use') or {}).get('mirror', ''), 'cands': [(c[2], c[3]['id'], -c[0]) for c in cands]}


def bylo(r, kit):
    room = to_room(r)
    lay = solve_hall(room, [Item(role=k, w_cm=v['w'], d_cm=v['d'], h_cm=v.get('h') or None) for k, v in kit.items()])
    return {'placed': lay.placements, 'violations': lay.violations, 'skipped': lay.skipped_optional, 'unplaced': lay.unplaced,
            'reason': lay.meta.get('reason', []), 'ok': lay.ok}


# ---------------------------------------------------------------- дорожки и узкое место (растр 2 см)
G = 2.0


def free_space(room: Room, placed):
    poly = room_polygon(room)
    x0, y0, x1, y1 = poly.bounds
    nx, ny = int(math.ceil((x1 - x0) / G)), int(math.ceil((y1 - y0) / G))
    xs = x0 + (np.arange(nx) + 0.5) * G
    ys = y0 + (np.arange(ny) + 0.5) * G
    X, Y = np.meshgrid(xs, ys)
    from shapely import contains_xy
    obs = [footprint(p) for p in placed if not is_wall_mirror(p)]
    inside = contains_xy(poly, X, Y)
    for o in obs:
        inside &= ~contains_xy(o.buffer(0.01), X, Y)
    # край растра — тоже стена: без рамки у прямоугольной комнаты нет ни одной «занятой» клетки и мерка уходит в небо
    edt = ndimage.distance_transform_edt(np.pad(inside, 1))[1:-1, 1:-1] * G
    return X, Y, inside, edt


def targets(room: Room, placed):
    ent = entrance(room)
    out = []
    for op in room.openings:
        if op is ent or op.kind != 'door':
            continue
        out.append(('door', f'дверь {op.width_cm:.0f}', door_front(room, op)))
    for p in placed:
        z = _zone(p)
        fp = footprint(p)
        if is_wall_mirror(p):
            fp = unary_union([fp] + [footprint(q) for q in placed if is_low(q) and footprint(q).intersection(fp).area > 1.0])
        out.append(('item', RU.get(base_role(p.role), p.role), z if z is not None and not z.is_empty else fp.buffer(30)))
    return out


def route_paths(room: Room, placed, need=P_HARD):
    """Путь от входа до каждой цели: ширина `need` (центр пути — не ближе need/2 к стене/мебели); узкое место — мин. 2·edt."""
    X, Y, inside, edt = free_space(room, placed)
    from shapely import contains_xy
    ent = entrance(room)
    if ent is None:
        return [], None
    mouth = door_front(room, ent)
    ok = edt >= need / 2 - G          # растр 2 см: допуск в одну клетку, иначе мерка занижает на 5 см
    lab, _n = ndimage.label(ok)
    sm = contains_xy(mouth, X, Y) & ok
    if not sm.any():
        return [], None
    a = bs_mid(room, ent)
    cand = np.argwhere(sm)
    starts = cand[[int(np.argmin((X[sm] - a[0]) ** 2 + (Y[sm] - a[1]) ** 2))]]   # одна точка: у середины входной двери
    ids = {int(lab[starts[0][0], starts[0][1]])}
    out, pinch = [], None
    for kind, name, region in targets(room, placed):
        tm = contains_xy(region.buffer(need / 2), X, Y) & ok & np.isin(lab, list(ids))
        if not tm.any():
            out.append((kind, name, None))
            continue
        c = region.centroid                       # одна цель: ближайшая к середине полосы двери / зоны подхода
        k = int(np.argmin(np.where(tm, (X - c.x) ** 2 + (Y - c.y) ** 2, np.inf)))
        tm = np.zeros_like(tm)
        tm.flat[k] = True
        path = _bfs(ok, starts, tm)
        if path:
            vals = [(edt[iy, ix] * 2, (X[iy, ix], Y[iy, ix])) for iy, ix in path[len(path) // 8: len(path) - len(path) // 8 or None]]
            if vals:
                m = min(vals, key=lambda v: v[0])
                if pinch is None or m[0] < pinch[0]:
                    pinch = m
        out.append((kind, name, [(X[iy, ix], Y[iy, ix]) for iy, ix in path] if path else None))
    return out, pinch


def bs_mid(room: Room, op):
    a = _wall_point(room, op.wall, op.offset_cm)
    b = _wall_point(room, op.wall, op.offset_cm + op.width_cm)
    return ((a.x + b.x) / 2, (a.y + b.y) / 2)


def _bfs(free, starts, target):
    from collections import deque
    H, W = free.shape
    prev = -np.ones(free.shape, dtype=np.int64)
    q = deque()
    for sy, sx in starts[:: max(1, len(starts) // 20)]:
        prev[sy, sx] = sy * W + sx
        q.append((sy, sx))
    end = None
    while q:
        y, x = q.popleft()
        if target[y, x]:
            end = (y, x)
            break
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < H and 0 <= nx < W and free[ny, nx] and prev[ny, nx] < 0:
                prev[ny, nx] = y * W + x
                q.append((ny, nx))
    if end is None:
        return []
    pts, (y, x) = [], end
    while True:
        pts.append((y, x))
        py, px = divmod(int(prev[y, x]), W)
        if (py, px) == (y, x):
            break
        y, x = py, px
    return pts[::-1]


def best_width(room: Room, placed):
    """Самый широкий проход от входа ко ВСЕМ целям (шаг 5 см) — мерка для строки «узкое место»."""
    for w in (100, 95, 90, 85, 80, 75, 70, 65, 60):
        paths, _ = route_paths(room, placed, w)
        if paths and all(p[2] for p in paths):
            return w
    return 0


# ---------------------------------------------------------------- рисование
def poly_px(cv, g):
    return [cv.P(x, y) for x, y in g.exterior.coords]


def dashed(d, pts, col, w=2, on=7, off=5):
    acc, draw = 0.0, True
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        t = 0.0
        while t < seg:
            step = min((on if draw else off) - acc, seg - t)
            if draw:
                a, b = t / seg, (t + step) / seg
                d.line([(x0 + (x1 - x0) * a, y0 + (y1 - y0) * a), (x0 + (x1 - x0) * b, y0 + (y1 - y0) * b)], fill=col, width=w)
            t += step
            acc += step
            if acc >= (on if draw else off) - 1e-6:
                acc, draw = 0.0, not draw


def hatch(cv, geoms, col=(220, 0, 0)):
    geoms = [g for g in geoms if g is not None and not g.is_empty]
    if not geoms:
        return
    mask = Image.new('L', (cv.w, cv.h), 0)
    md = ImageDraw.Draw(mask)
    for g in geoms:
        for gg in getattr(g, 'geoms', [g]):
            md.polygon(poly_px(cv, gg), fill=255)
    hl = Image.new('RGBA', (cv.w, cv.h), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hl)
    for k in range(-cv.h, cv.w, 9):
        hd.line([(k, 0), (k + cv.h, cv.h)], fill=col + (235,), width=2)
    lay = Image.new('RGBA', (cv.w, cv.h), (0, 0, 0, 0))
    lay.paste(hl, (0, 0), mask)
    cv.img.paste(lay, (0, 0), lay)
    d = ImageDraw.Draw(cv.img)
    for g in geoms:
        for gg in getattr(g, 'geoms', [g]):
            d.polygon(poly_px(cv, gg), outline=col, width=2)


def render(r, placed, violations, s, title, subtitle, foot, ok, show_paths=True, bw=0, sub2=''):
    room = to_room(r)
    poly = room_polygon(room)
    W, D = float(r['w']), float(r['d'])
    fs = 13
    rr = {'W': W, 'D': D}
    lines = len(foot)
    cv = bs.Canvas(rr, s, ml=64, mt=112, mr=30, mb=40 + lines * (fs + 7) + 10, min_w=430)
    d = ImageDraw.Draw(cv.img)
    # вне контура — серым
    outside = box(0, 0, W, D).difference(poly)
    for g in getattr(outside, 'geoms', [outside]):
        if not g.is_empty:
            d.polygon(poly_px(cv, g), fill=(236, 236, 236))
    for x in range(0, int(W) + 1, 50):
        d.line([cv.P(x, 0), cv.P(x, D)], fill=(225, 225, 225) if x % 100 else (205, 205, 205), width=1)
    for y in range(0, int(D) + 1, 50):
        d.line([cv.P(0, y), cv.P(W, y)], fill=(225, 225, 225) if y % 100 else (205, 205, 205), width=1)
    fsm = font(10)
    for x in range(0, int(W) + 1, 100):
        text_c(d, (cv.P(x, 0)[0], cv.P(x, 0)[1] + 13), str(x), fsm, (130, 130, 130))
    for y in range(0, int(D) + 1, 100):
        text_c(d, (cv.P(0, y)[0] - 40, cv.P(0, y)[1]), str(y), fsm, (130, 130, 130))
    if r.get('stairs'):
        st = box(*r['stairs'])
        d.polygon(poly_px(cv, st), fill=(245, 240, 230), outline=(150, 140, 120))
        x0, y0, x1, y1 = r['stairs']
        for yy in np.arange(y0 + 20, y1, 20):
            d.line([cv.P(x0, yy), cv.P(x1, yy)], fill=(170, 160, 140), width=1)
        text_c(d, cv.P((x0 + x1) / 2, (y0 + y1) / 2), 'лестница\n(вверх)', font(11), (110, 100, 80))
    if r.get('niche'):
        x0, y0, x1, y1 = r['niche']
        text_c(d, (cv.P(x1, (y0 + y1) / 2)[0] + 14, cv.P(x1, (y0 + y1) / 2)[1]), 'н\nи\nш\nа', font(10), (110, 110, 110))
    # зоны
    od = ImageDraw.Draw(cv.ov)
    ent = entrance(room)
    for op in room.openings:
        if op.kind != 'door':
            continue
        strip = door_front(room, op).intersection(poly)
        if not strip.is_empty:
            od.polygon(poly_px(cv, strip), fill=ZCOL['door'])
        sw = swing_polygon(room, op)
        if not sw.is_empty:
            od.polygon(poly_px(cv, sw), fill=(255, 160, 0, 90))
    for p in placed:
        z = _zone(p)
        if z is not None and not z.is_empty:
            od.polygon(poly_px(cv, z), fill=ZCOL.get(base_role(p.role), (30, 136, 229, 60)))
    cv.img.paste(cv.ov, (0, 0), cv.ov)
    d = ImageDraw.Draw(cv.img)
    land = entry_landing(room) if ent is not None else None
    if land is not None and not land.is_empty:
        pts = poly_px(cv, land.intersection(poly))
        dashed(d, pts, (200, 140, 0), w=1, on=4, off=4)
    # стены
    d.line(poly_px(cv, poly), fill=(40, 40, 40), width=4)
    if r.get('stairs'):
        x0, y0, x1, y1 = r['stairs']
        d.line([cv.P(x0, y0), cv.P(x1, y0), cv.P(x1, y1)], fill=(150, 140, 120), width=2)
    # проёмы
    for op in room.openings:
        if op.kind != 'door':
            continue
        a = bs.wall_point(rr, op.wall, op.offset_cm)
        b = bs.wall_point(rr, op.wall, op.offset_cm + op.width_cm)
        d.line([cv.P(*a), cv.P(*b)], fill=(255, 255, 255), width=6)
        col = (198, 40, 40) if op is ent else (120, 120, 120)
        d.line([cv.P(*a), cv.P(*b)], fill=col, width=2)
        mid = cv.P((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        lab = 'ВХОД' if op is ent else f'{op.width_cm:.0f}'
        off = {'south': (0, 12), 'north': (0, -12), 'west': (-20, 0), 'east': (20, 0)}[op.wall]
        text_c(d, (mid[0] + off[0], mid[1] + off[1]), lab, font(11, op is ent), col)
    for x in room.radiators:
        rb = bs.band(rr, x.wall, x.offset_cm, x.width_cm, 0, x.depth_cm)
        d.rectangle(cv.R(rb), fill=(239, 83, 80), outline=(150, 30, 30))
    # предметы (сначала пол, потом зеркала)
    for p in sorted(placed, key=lambda q: is_wall_mirror(q)):
        role = base_role(p.role)
        fp = footprint(p)
        if is_wall_mirror(p):
            pts = poly_px(cv, fp)
            d.polygon(pts, fill=COL['зеркало'], outline=(1, 87, 155))
            c = fp.centroid
            n = (math.sin(math.radians(p.rot)), math.cos(math.radians(p.rot)))
            under = [o for o in placed if not is_wall_mirror(o) and footprint(o).intersection(fp).area > 1]
            over = any(is_low(o) for o in under)
            dep = max([o.item.d_cm for o in under] or [0.0]) + 14 / s + 6
            q = cv.P(c.x + n[0] * dep, c.y + n[1] * dep)
            text_c(d, q, f'зерк.{p.item.w_cm:.0f}' + (' над' if over else ''), font(10, True), (1, 87, 155))
            continue
        d.polygon(poly_px(cv, fp), fill=COL.get(role, (200, 200, 200)), outline=(60, 60, 60))
        c = fp.centroid
        x0, y0, x1, y1 = fp.bounds
        vert = (y1 - y0) > (x1 - x0)
        txt = f'{SHORT.get(role, role)}\n{p.item.w_cm:.0f}×{p.item.d_cm:.0f}'
        tf = font(10 if min(x1 - x0, y1 - y0) * s < 34 else 11)
        if vert and (x1 - x0) * s < 46:
            im = Image.new('RGBA', (int((y1 - y0) * s) + 4, int((x1 - x0) * s) + 4), (0, 0, 0, 0))
            id_ = ImageDraw.Draw(im)
            text_c(id_, (im.width / 2, im.height / 2), txt.replace('\n', ' '), tf)
            im = im.rotate(90, expand=True)
            px, py = cv.P(c.x, c.y)
            cv.img.paste(im, (int(px - im.width / 2), int(py - im.height / 2)), im)
            d = ImageDraw.Draw(cv.img)
        else:
            text_c(d, cv.P(c.x, c.y), txt, tf)
    # нарушения
    bad = {}
    for v in violations:
        if v.severity is Severity.HARD:
            for role in v.roles:
                bad[role] = True
    hatch(cv, [footprint(p) for p in placed if p.role in bad])
    if not placed and not ok:
        hatch(cv, [poly.buffer(-2)])
    # дорожки
    # дорожки — шириной лучшего прохода (центр пути не ближе bw/2 к стене и мебели), красное число — узкое место на них
    paths, pinch = route_paths(room, placed, max(bw, 60)) if show_paths else ([], None)
    for kind, name, pts in paths:
        if not pts:
            continue
        col = (21, 101, 192) if kind == 'door' else (46, 125, 50)
        dashed(d, [cv.P(x, y) for x, y in pts[::3]], col, w=2)
    if pinch:
        px, py = cv.P(*pinch[1])
        v = float(bw) if bw else pinch[0]     # мерка — ширина, с которой путь проходит целиком (шаг 5); место — где теснее всего
        pc = (46, 125, 50) if v >= P_TARGET else (230, 120, 0) if v >= P_COMPACT else (198, 40, 40)
        d.ellipse([px - 4, py - 4, px + 4, py + 4], outline=pc, width=2)
        lab = f'{v:.0f}'
        tw = d.textlength(lab, font=font(12, True))
        d.rectangle([px + 6, py - 9, px + 10 + tw, py + 8], fill=(255, 255, 255))
        d.text((px + 8, py - 8), lab, font=font(12, True), fill=pc)
    # размеры стен
    text_c(d, (cv.P(W, D)[0] + 18, cv.P(W, D)[1] - 10), f'{W:.0f}', font(11, True), (60, 60, 60))
    text_c(d, (cv.P(W, D / 2)[0] + 14, cv.P(W, D / 2)[1]), f'{D:.0f}', font(11, True), (60, 60, 60))
    # заголовок и подвал
    d.text((12, 8), title, font=font(15, True), fill=(20, 20, 20))
    d.text((12, 30), subtitle, font=font(13, True), fill=(46, 125, 50) if ok else (198, 40, 40))
    d.text((12, 49), sub2, font=font(11), fill=(60, 60, 60))
    d.text((12, 68), 'сетка 50 см · пунктир от входа: синий — к дверям, зелёный — к предметам', font=font(10), fill=(110, 110, 110))
    d.text((12, 81), 'в кружке — узкое место, см: зел. ≥ 90 · оранж. 75–89 · красн. < 75',
           font=font(10), fill=(110, 110, 110))
    y = cv.h - (lines * (fs + 7)) - 14
    for ln in foot:
        col = (198, 40, 40) if ln.startswith('✗') else (46, 125, 50) if ln.startswith('✓') else (50, 50, 50)
        d.text((12, y), ln, font=font(fs - 1, ln.startswith(('✓', '✗'))), fill=col)
        y += fs + 7
    return cv.img, pinch


def wrap(text, n=58):
    out, cur = [], ''
    for w in text.split(' '):
        if len(cur) + len(w) + 1 > n and cur:
            out.append(cur)
            cur = '   ' + w
        else:
            cur = (cur + ' ' + w).strip(' ') if cur else w
    if cur:
        out.append(cur)
    return out


def items_line(placed):
    xs = [f'{RU.get(base_role(p.role), p.role)} {p.item.w_cm:.0f}×{p.item.d_cm:.0f}' for p in placed]
    return wrap('Состав: ' + ', '.join(xs) if xs else 'Состав: —')


def soft_line(vs):
    soft = sorted({CODE_RU.get(v.code, v.code) for v in vs if v.severity is Severity.SOFT})
    return wrap('Мягко: ' + '; '.join(soft)) if soft else []


def hard_line(vs):
    hard = []
    for v in vs:
        if v.severity is Severity.HARD:
            t = CODE_RU.get(v.code, v.code)
            if v.roles:
                t += ' («' + '», «'.join(RU.get(base_role(x), x) for x in v.roles) + '»)'
            hard.append(t)
    return sorted(set(hard))


TPL_RU = {t['id']: t.get('label', t['id']) for t in PASSPORT.get('templates', [])}


def tpl_label(name):
    base, _, mod = name.partition('+')
    fam, _, br = TPL_RU.get(base, base).split(' · ', 1)[-1].rpartition(' · ')
    return f"{fam} · {'купе в нише (H7)' if mod else br}"


def panel_pair(r, res, was, s):
    bw = best_width(to_room(r), was['placed']) if was['placed'] else 0
    hard = hard_line(was['violations'])
    f1 = items_line(was['placed'])
    if was['skipped']:
        f1 += wrap('Не встало: ' + ', '.join(RU.get(base_role(x), x) for x in was['skipped']))
    if hard:
        f1 = [f'✗ {h}' for h in hard] + f1
    elif was['placed']:
        f1 = [f'✓ движок: 0 жёстких · проход ≥ {bw} см'] + f1
    else:
        f1 = ['✗ движок: отказ ' + ', '.join(was['reason'])] + f1
    f1 += soft_line(was['violations'])
    img1, _ = render(r, was['placed'], was['violations'], s, r['title'], 'БЫЛО — движок hall-v1 сейчас', f1,
                     not hard and bool(was['placed']), bw=bw, sub2='набор сканди целиком; неудобное движок выкидывает по одному')
    if res['ok']:
        bw2 = best_width(to_room(r), res['placed'])
        f2 = [f'✓ влезает · проход ≥ {bw2} см (цель {P_TARGET:.0f}, местно {P_COMPACT:.0f})'] + items_line(res['placed'])
        mir = [q for q in res['placed'] if base_role(q.role) == 'зеркало']
        if mir and 'over_low' in str(res.get('mirror_variant', '')) and not any(
                is_low(o) and footprint(o).intersection(footprint(mir[0])).area > 1 for o in res['placed']):
            f2 += wrap('Зеркало — на свободной стене: низкой мебели под ним нет (обувница высокая или не встала)')
        f2 += soft_line(res['violations'])
        skip = [t for t in res['tried'] if not t['ok'] and t['tpl'] == res['tpl']]
        for t in skip[:2]:
            f2 += wrap(f"уровень {t['level']} не встал: {t['why']}")
        sub = f"ПО ШАБЛОНУ {res['tpl']} · уровень {res['level']}"
        sub2 = tpl_label(res['tpl'])
    else:
        bw2 = 0
        f2 = ['✗ отказ: ни одна ветка хранения не встала']
        seen = set()
        for t in res['tried']:
            if t['level'] == 'E' and t['why'] not in seen:
                seen.add(t['why'])
                f2 += wrap(f"{t['tpl']}: {t['why']}")
            if len(seen) >= 3:
                break
        sub = 'ПО ШАБЛОНУ — честный отказ'
        sub2 = 'ни одно семейство не дало целый состав'
    img2, _ = render(r, res['placed'], res['violations'], s, r['title'], sub, f2, res['ok'], bw=bw2, sub2=sub2)
    h = max(img1.height, img2.height)
    out = Image.new('RGB', (img1.width + img2.width + 12, h), (255, 255, 255))
    out.paste(img1, (0, 0))
    out.paste(img2, (img1.width + 12, 0))
    ImageDraw.Draw(out).line([(img1.width + 6, 10), (img1.width + 6, h - 10)], fill=(200, 200, 200), width=2)
    return out, bw, bw2


def make_sheets(out, pngs, per=4):
    files = []
    for k in range(0, len(pngs), per):
        ims = [Image.open(p) for p in pngs[k:k + per]]
        cols = 2
        rows = (len(ims) + 1) // 2
        cw = max(i.width for i in ims)
        rh = [max(i.height for i in ims[j * 2:j * 2 + 2]) for j in range(rows)]
        sheet = Image.new('RGB', (cw * cols + 20, sum(rh) + 10 * rows), (255, 255, 255))
        y = 0
        for j in range(rows):
            for c in range(cols):
                i = j * 2 + c
                if i < len(ims):
                    sheet.paste(ims[i], (c * (cw + 20), y))
            y += rh[j] + 10
        f = out / f'sheet-{k // per + 1}.png'
        sheet.save(f)
        files.append(f.name)
    return files


def why_line(res):
    f = res['facts']
    bits = []
    if f['has_stairs']:
        bits.append('лестница в зале')
    if f['has_niche']:
        bits.append('ниша под шкаф')
    if f['shape_l']:
        bits.append('Г-образная')
    for k, t in (('micro', 'микро'), ('squareish', 'почти квадрат'), ('door_dense', 'двери на 2+ стенах')):
        if f.get(k):
            bits.append(t)
    if f['short_cm']:
        bits.append(f"ширина {f['short_cm']:.0f}")
    bits.append(f"{f['area_m2']:.1f} м²")
    bits.append(f"дверей {f['doors']}")
    fails = [f"{t['tpl']}-{t['level']}: {t['why']}" for t in res['tried'] if not t['ok']]
    return ', '.join(bits), fails


def one_room(args):
    r, out = args
    sets, by = load_pool()
    kit = next(s for s in sets if s['style'] == 'сканди')['items']
    res = run_room(r, by)
    was = bylo(r, kit)
    s = min(1.15, 560.0 / r['d'], 380.0 / r['w'])
    img, bw, bw2 = panel_pair(r, res, was, s)
    f = Path(out) / f"{r['id']}.png"
    img.save(f)
    return r, res, was, bw, bw2, f


def main(out, only=None, jobs=1):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rooms = [r for r in load_rooms() if not only or r['id'] in only]
    rows, pngs, js = [], [], []
    if jobs > 1:
        import multiprocessing as mp
        with mp.Pool(jobs) as pool:
            done = pool.map(one_room, [(r, str(out)) for r in rooms], chunksize=1)
    else:
        done = [one_room((r, str(out))) for r in rooms]
    for r, res, was, bw, bw2, f in done:
        pngs.append(f)
        facts_s, fails = why_line(res)
        rows.append((r, res, was, facts_s, fails, bw, bw2))
        js.append({'room': r['id'], 'title': r['title'], 'src': r['src'], 'facts': res['facts'], 'order': res['order'],
                   'template': res['tpl'], 'level': res['level'], 'ok': res['ok'], 'tried': res['tried'],
                   'placed': [{'role': p.role, 'x': p.x, 'y': p.y, 'rot': p.rot, 'w': p.item.w_cm, 'd': p.item.d_cm,
                               'h': p.item.h_cm, 'elev': p.elev_cm} for p in res['placed']],
                   'soft': sorted({v.code for v in res['violations'] if v.severity is Severity.SOFT}),
                   'bylo': {'placed': [{'role': p.role, 'x': p.x, 'y': p.y, 'rot': p.rot, 'w': p.item.w_cm, 'd': p.item.d_cm}
                                       for p in was['placed']], 'skipped': was['skipped'], 'reason': was['reason'],
                            'hard': sorted({v.code for v in was['violations'] if v.severity is Severity.HARD}),
                            'soft': sorted({v.code for v in was['violations'] if v.severity is Severity.SOFT})},
                   'width_bylo': bw, 'width_tpl': bw2})
        print(f"{r['id']:8s} {res['tpl'] or '—'}-{res['level'] or '✗'}  было: {len(was['placed'])} шт. "
              f"{'✓' if was['ok'] else '✗'}  проход было {bw} / шаблон {bw2}", flush=True)
    sheets = make_sheets(out, pngs)
    write_matrix(out, rows, sheets)
    (out / 'results.json').write_text(json.dumps(js, ensure_ascii=False, indent=1))


def write_matrix(out, rows, sheets):
    L = ['# Прихожая — комната → шаблон → уровень → почему (T-20261112-70)', '',
         f'Паспорт: `services/planner-solver/rules/room-templates/hall.json` (тень). Листы: {", ".join(sheets)}; по комнате — `<id>.png` '
         '(слева «было» — движок hall-v1 на наборе сканди, справа — по шаблону).',
         f'Проверки — как у движка (`planner/hall_checks.py`, ключи occupancy.json не менялись): проход от входа {P_HARD:.0f} жёстко, '
         f'{P_COMF:.0f} комфорт; на листе ширина пути окрашена по таблице Codex/ADM M4(1): цель {P_TARGET:.0f}, местно {P_COMPACT:.0f}; полоса '
         f'{DOOR_FRONT:.0f} у каждой двери; фронт купе {FRONT["шкаф-купе"]:.0f}, распашного {FRONT["шкаф"]:.0f}, обувницы '
         f'{FRONT["обувница"]:.0f}, банкетки {FRONT["банкетка"]:.0f}; площадка у входа {ENTRY:.0f}. Товары — банк-кандидат '
         '`sets-hall.next.json` (5 стилей + запасные), размеры настоящие.', '',
         '| Комната | Факты | Порядок семейств | Шаблон · уровень | Состав по шаблону | Проход, см (было → шаблон) | Было (движок) | Другие ветки, что встали | Почему не выше |',
         '|---|---|---|---|---|---|---|---|---|']
    for r, res, was, facts_s, fails, bw, bw2 in rows:
        comp = ', '.join(f"{RU.get(base_role(p.role), p.role)} {p.item.w_cm:.0f}×{p.item.d_cm:.0f}" for p in res['placed']) or '—'
        wasc = ', '.join(RU.get(base_role(p.role), p.role) for p in was['placed']) or 'отказ'
        hard = hard_line(was['violations'])
        if hard:
            wasc += ' · ✗ ' + '; '.join(hard)
        if was['skipped']:
            wasc += ' · не встало: ' + ', '.join(RU.get(base_role(x), x) for x in was['skipped'])
        tl = f"**{res['tpl']} · {res['level']}**" if res['ok'] else '**✗ отказ**'
        fam = ' → '.join(dict.fromkeys(t.split('.')[0] for t in res['order']))
        alt = ', '.join(f'{n}-{lv}' for n, lv, _v in res.get('cands', []) if n != res['tpl']) or '—'
        own = [x for x in fails if x.split('-')[0] == res['tpl']]
        L.append(f"| {r['title']} | {facts_s} | {fam} | {tl} | {comp} | {bw or '—'} → {bw2 or '—'} | {wasc} | {alt} | "
                 f"{'; '.join(own[:2]) or ('—' if res['ok'] else '; '.join(fails[-2:]))} |")
    L += ['', '## Шаблоны паспорта', '']
    for t in PASSPORT['templates']:
        L.append(f"- **{t['id']}** — {t.get('label', '')}: уровни " +
                 ' → '.join(f"{lv['id']} ({lv.get('label', '')})" for lv in t['levels']))
    (out / 'matrix.md').write_text('\n'.join(L) + '\n')


if __name__ == '__main__':
    a = sys.argv[1:]
    only = a[a.index('--only') + 1].split(',') if '--only' in a else None
    jobs = int(a[a.index('--jobs') + 1]) if '--jobs' in a else 1
    main(a[0] if a and not a[0].startswith('--') else 'hall-schemes-out', only, jobs)
