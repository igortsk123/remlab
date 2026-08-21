#!/usr/bin/env python3
"""Q11: ВИЗУАЛЬНАЯ БИБЛИОТЕКА КАНОНОВ — каждая схема паспорта нарисована ТЕМ ЖЕ кодом,
что и рабочие планы (`render_plan.render_artifact`): не текстовый реестр, а планы.

Для каждого канона: мини-сцена с нужным якорем (окно/эркер/камин/угол/стена), реальный
builder или placer из `planner/template.py`, рендер в PNG + карточка с паспортом
(когда применяется, почему, статус, роли). Схемы без реализации помечаются «спит».

  canon_gallery.py [--publish]      # → ~/scout-scenes/canon-gallery, /test/canons/
"""
from __future__ import annotations

import html
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))
OUT = os.path.expanduser('~/scout-scenes/canon-gallery')

from planner.models import Item, Opening, Placement, Radiator, Room  # noqa: E402
from planner import template as T  # noqa: E402
from planner.zones import usable_polygon  # noqa: E402
from planner.geometry import footprint  # noqa: E402
from render_plan import render_artifact  # noqa: E402

TPL = json.load(open(os.path.join(HERE, '..', '..', 'services', 'planner-solver',
                                  'rules', 'templates.json'), encoding='utf-8'))


def I(role, w, d, h=80, **kw):
    return Item(role=role, w_cm=w, d_cm=d, h_cm=h, **kw)


CAT = {
    'стеллаж 2': I('стеллаж 2', 80, 35, 190),
    'диван': I('диван', 220, 95, 85), 'диван 2': I('диван 2', 180, 90, 85),
    'кресло': I('кресло', 80, 82, 80), 'кресло 2': I('кресло 2', 80, 82, 80),
    'кресло 3': I('кресло 3', 78, 80, 80), 'кресло 4': I('кресло 4', 78, 80, 80),
    'столик': I('столик', 110, 60, 45), 'столик 2': I('столик 2', 55, 55, 45),
    'приставной': I('приставной', 45, 45, 55), 'пуф': I('пуф', 60, 60, 42),
    'ковёр': I('ковёр', 290, 200, 1), 'торшер': I('торшер', 35, 35, 165),
    'тв-тумба': I('тв-тумба', 150, 40, 50), 'стенка': I('стенка', 260, 45, 190),
    'камин': I('камин', 120, 40, 100), 'комод': I('комод', 120, 40, 80),
    'стеллаж': I('стеллаж', 80, 35, 190), 'витрина': I('витрина', 80, 40, 190),
    'стол обеденный': I('стол обеденный', 140, 80, 75),
    # «консоль» — НЕ новая роль каталога, а способность узкого низкого комода
    # (group_scheme.console: d≤40, h≤спинки, длина ≥2/3 дивана — аудит Юли №46/Codex:
    # прежний комод 120×40×80 при диване 220 давал 55% длины и читался чужим)
    'консоль': I('комод', 150, 35, 75),
    'стул': I('стул', 45, 52, 90), 'стул 2': I('стул 2', 45, 52, 90),
    'стул 3': I('стул 3', 45, 52, 90), 'стул 4': I('стул 4', 45, 52, 90),
    'банкетка': I('банкетка', 130, 42, 46, caps={'guaranteed_seats': 2, 'dining_seat_capable': True,
                                                 'wall_seat_capable': True}),
    'кашпо': I('кашпо', 35, 35, 90),
}


BAY_RECT = (120.0, 300.0, 320.0, 420.0)     # ниша эркера в room_of('bay') — по контуру комнаты


def room_of(kind: str) -> Room:
    """Мини-сцена под якорь канона. Суффикс `_de` — та же комната, но дверь на ВОСТОЧНОЙ
    стене: зеркальные формы показываются в той дверной ситуации, где они уместны
    (аудит Юли №6/№18/№52 — вторая посадка не должна вставать спинками ко входу)."""
    door = Opening(kind='door', wall='west', offset_cm=40, width_cm=90, swing_cm=90)
    win = Opening(kind='window', wall='north', offset_cm=140, width_cm=160, sill_cm=80)
    if kind.endswith('_de'):
        kind = kind[:-3]
        if kind == 'plain':
            return Room(width_cm=560, depth_cm=430, openings=[
                Opening(kind='door', wall='east', offset_cm=300, width_cm=90, swing_cm=90)])
        if kind == 'big':
            return Room(width_cm=620, depth_cm=560, openings=[
                Opening(kind='door', wall='east', offset_cm=430, width_cm=90, swing_cm=90)])
    if kind == 'window':
        return Room(width_cm=440, depth_cm=420, openings=[door, win])
    if kind == 'plain':
        # 560×430: широкие формы посадки (медиа-параллель, мостик) помещаются целиком, а дистанция
        # диван↔ТВ остаётся в вилке просмотра — референс не должен уезжать в «просторную» сцену.
        # Дверь — у ДАЛЬНЕГО (северного) конца стены (аудит Юли №1/№3: проём вплотную к
        # композиции у южной стены зажимал вход; в мини-сцене вход обязан быть свободным)
        return Room(width_cm=560, depth_cm=430, openings=[
            Opening(kind='door', wall='west', offset_cm=300, width_cm=90, swing_cm=90)])
    if kind == 'bay_wide':
        # широкий эркер (ниша 260×110): пара кресел помещается целиком; в узкой нише 200 см
        # пара честно не собирается — там канон одиночного кресла
        return Room(width_cm=520, depth_cm=440, openings=[
            door, Opening(kind='window', wall='north', offset_cm=150, width_cm=220, sill_cm=80)],
            contour=[[0, 0], [520, 0], [520, 330], [390, 330], [390, 440], [130, 440],
                     [130, 330], [0, 330]])
    if kind == 'window2':
        # два окна на одной стене — якорь схемы media_between_windows (простенок между проёмами)
        return Room(width_cm=560, depth_cm=430, openings=[
            door, Opening(kind='window', wall='north', offset_cm=60, width_cm=120, sill_cm=80),
            Opening(kind='window', wall='north', offset_cm=380, width_cm=120, sill_cm=80)])
    if kind == 'media':
        # 560×370: медиа-формы (кресло к экрану) нужен носитель в вилке просмотра 150–320 см —
        # в 430-глубокой комнате ТВ у дальней стены уезжает за 320 и контекст пропадал,
        # а канон «кресло к ТВ» без ТВ нелегален по определению. Дверь остаётся у южного
        # конца: с дверью у северного торшер медиа-форм терял подход (UNREACHABLE)
        return Room(width_cm=560, depth_cm=370, openings=[door])
    if kind == 'window_rad':
        return Room(width_cm=440, depth_cm=420, openings=[door, win],
                    radiators=[Radiator(wall='north', offset_cm=140, width_cm=160, depth_cm=15)])
    if kind == 'big':
        # дверь — у дальнего (северного) конца западной стены (№1/№3)
        return Room(width_cm=620, depth_cm=560, openings=[
            Opening(kind='door', wall='west', offset_cm=430, width_cm=90, swing_cm=90)])
    if kind == 'chamfer':
        # комната со СКОСАМИ всех углов (реальный случай: трапеции/скосы, set5-trapezoid):
        # угловые кандидаты гибнут, и боевой place_reading честно доходит до «кресло у
        # стены» — сцена для wall_vignette (аудит Юли №31: карточка была пиксельным
        # дублем corner_vignette, потому что в пустом прямоугольнике угол всегда выигрывал)
        _ch, _W, _D = 160.0, 560.0, 430.0
        return Room(width_cm=560, depth_cm=430, openings=[
            Opening(kind='door', wall='west', offset_cm=175, width_cm=90, swing_cm=90)],
            contour=[[_ch, 0], [_W - _ch, 0], [_W, _ch], [_W, _D - _ch], [_W - _ch, _D],
                     [_ch, _D], [0, _D - _ch], [0, _ch]])
    if kind == 'bay':
        return Room(width_cm=440, depth_cm=420, openings=[door, win],
                    contour=[[0, 0], [440, 0], [440, 300], [320, 300], [320, 420], [120, 420],
                             [120, 300], [0, 300]])
    return Room(width_cm=440, depth_cm=420, openings=[door])


def artifact(room: Room, ps: list[Placement], ctx: list[str] | None = None) -> dict:
    out = {'_room': {'w': room.width_cm, 'd': room.depth_cm,
                     'm2': round(room.width_cm * room.depth_cm / 10_000, 1),
                     'openings': [{'kind': o.kind, 'wall': o.wall, 'offset_cm': o.offset_cm,
                                   'width_cm': o.width_cm, 'swing_cm': getattr(o, 'swing_cm', 90),
                                   'sill_cm': getattr(o, 'sill_cm', 0)} for o in room.openings],
                     'radiators': [{'wall': r.wall, 'offset_cm': r.offset_cm, 'width_cm': r.width_cm,
                                    'depth_cm': r.depth_cm} for r in (room.radiators or [])],
                     'contour': room.contour},
           '_zones': {}, '_context': list(ctx or [])}
    for p in ps:
        out[p.role] = {'x': p.x, 'z': p.y, 'rot': p.rot,
                       'w': p.item.w_cm if p.item else 50, 'd': p.item.d_cm if p.item else 50,
                       'h': (p.item.h_cm if p.item else 80),
                       'tpl_id': getattr(p, 'tpl_id', ''), 'tpl_variant': getattr(p, 'tpl_variant', '')}
        if p.item is not None and getattr(p.item, 'corner', False):
            # Г-диван: без этих полей рендер восстановит прямоугольник, и столик в вырезе
            # будет читаться как наложение (аудит Юли №14, sectional)
            out[p.role].update({'corner': True,
                                'corner_section_cm': p.item.corner_section_cm,
                                'corner_left': bool(getattr(p.item, 'corner_left', False))})
    return out


def _bbox(block, rot: float):
    """Габарит блока — ОБЩИЙ helper солвера (`template.block_bbox`). Своя копия здесь была
    ошибкой: витрина считала иначе и маскировала дефекты боевого поиска (Codex 19.08)."""
    return T.block_bbox(block, rot)


ROUTE_TARGET_CM = 91.0     # главный проход: NKBA 36" (Homes&Gardens; Q8 route_min=91)
ROUTE_MIN_CM = 75.0        # продовый минимум качества маршрута (zones.py: quality_min)


def _door_corridor(room):
    """Входной коридор двери: проём + дуга + глоток маршрута вглубь комнаты. Блок,
    зажимающий этот коридор ближе ROUTE_MIN, зажимает и главный маршрут (аудит Юли №1/№3:
    «у двери должно быть пространство»; Codex 21.08 — мерить фактический проход, а не
    дистанцию до проёма)."""
    from shapely.geometry import box as _bx
    door = next((o for o in room.openings if o.kind == 'door'), None)
    if door is None:
        return None
    depth = float(getattr(door, 'swing_cm', 90) or 90) + 30.0
    o, w = door.offset_cm, door.width_cm
    W, D = room.width_cm, room.depth_cm
    if door.wall == 'west':
        return _bx(0, o, depth, o + w)
    if door.wall == 'east':
        return _bx(W - depth, o, W, o + w)
    if door.wall == 'south':
        return _bx(o, 0, o + w, depth)
    return _bx(o, D - depth, o + w, D)


def block_scene(kind: str, block, wall: str = 'north', rot: float | None = None,
                margin: float = 12.0, center: str = 'bbox'):
    """Поставить канон ТАК, КАК ЭТО СТОИТ В РЕАЛЬНОСТИ (замечание владельца 19.08): спиной к
    стене (или в центре для острова), по центру стены, ЦЕЛИКОМ внутри комнаты и мимо дуги двери.
    Референс не имеет права нарушать то, что мы требуем от рабочих планов.

    21.08 (аудит Юли №1/№3): блок дополнительно уступает ДВЕРИ — из допустимых сдвигов вдоль
    стены выбирается ближайший к центру, дающий зазор до входного коридора ≥91 см (цель) или
    хотя бы ≥75 (минимум качества маршрута); раньше проверялась только дуга.
    21.08 (№41/№57): `center='anchor'` — на ось стены центрируется ЯКОРЬ блока (носитель),
    а не общий габарит: кашпо-спутник больше не стаскивает тумбу с оси простенка."""
    from planner.geometry import room_polygon, swing_polygon
    room = room_of(kind)
    if block is None:
        return None, None
    # rot: фасад блока смотрит В КОМНАТУ от выбранной стены
    rot = {'north': 180.0, 'south': 0.0, 'west': 90.0, 'east': 270.0, 'center': 0.0}[wall] \
        if rot is None else rot
    bw, bd, ox, oy = _bbox(block, rot)
    W, D = room.width_cm, room.depth_cm
    if wall == 'north':
        cx, cy = W / 2, D - margin - bd / 2
    elif wall == 'south':
        cx, cy = W / 2, margin + bd / 2
    elif wall == 'west':
        cx, cy = margin + bw / 2, D / 2
    elif wall == 'east':
        cx, cy = W - margin - bw / 2, D / 2
    else:
        cx, cy = W / 2, D / 2
    if center == 'anchor':
        # ось держит ЯКОРЬ: смещаем цель bbox так, чтобы на cx/cy лёг центр якоря
        if wall in ('north', 'south', 'center'):
            cx += ox
        else:
            cy += oy
    rp, sw = room_polygon(room), None
    try:
        sw = swing_polygon(room, next(o for o in room.openings if o.kind == 'door'))
    except Exception:
        sw = None
    corr = _door_corridor(room)
    # сдвиг вдоль стены: полное вхождение КАЖДОГО предмета (bbox блока недооценивает
    # кресла под 45° — block_bbox не расширяет их диагональ), мимо дуги, и лучший
    # достижимый зазор к коридору двери (ярус 91 → 75 → «хотя бы легально»);
    # внутри яруса побеждает минимальный сдвиг (композиция остаётся у центра стены)
    from shapely.geometry import box as _bx
    from shapely.ops import unary_union as _uu
    best = None
    for shift in (0, 40, -40, 80, -80, 120, -120, 160, -160, 200, -200):
        tx, ty = (cx + shift, cy) if wall in ('north', 'south', 'center') else (cx, cy + shift)
        _ps_try = block.to_world(tx - ox, ty - oy, rot)
        _fps = [footprint(p) for p in _ps_try]
        _rp_in = rp.buffer(0.5)
        if any(not _rp_in.contains(f) for f in _fps):   # строго, как validate OUT_OF_ROOM
            continue
        if sw is not None and any(f.intersects(sw) for p, f in zip(_ps_try, _fps)
                                  if p.role.split(' ')[0] != 'ковёр'):
            continue
        _hull = _uu([f for p, f in zip(_ps_try, _fps) if p.role.split(' ')[0] != 'ковёр'])
        _clear = _hull.distance(corr) if corr is not None else 1e9
        _tier = 0 if _clear >= ROUTE_TARGET_CM else (1 if _clear >= ROUTE_MIN_CM else 2)
        _key = (_tier, abs(shift))
        if best is None or _key < best[0]:
            best = (_key, (tx, ty))
    if best is None:
        if kind not in ('big', 'big_de'):   # композиция шире мини-сцены — просторная комната
            _big = 'big_de' if kind.endswith('_de') else 'big'
            return block_scene(_big, block, wall=wall, rot=rot, margin=margin, center=center)
        return room, None            # честно: канон не помещается даже в просторной
    tx, ty = best[1]
    return room, block.to_world(tx - ox, ty - oy, rot)


def door_side_scene(kind: str, block, wall: str = 'south'):
    """Сцена для ЗЕРКАЛЬНОЙ формы: из комнат «дверь запад / дверь восток» берётся та, где
    вторичные посадки (кресла, второй диван) дальше от входного коридора — сторона зеркала
    определяется маршрутом, а не жёстким правилом (аудит Юли №6/№18/№52; в бою то же
    решают гипотезы зеркал + ярус главного маршрута, zones.py)."""
    best = None
    for k in (kind, kind + '_de'):
        r, ps = block_scene(k, block, wall=wall)
        if not ps:
            continue
        corr = _door_corridor(r)
        sec = [p for p in ps if p.role in ('кресло', 'кресло 2', 'кресло 3', 'кресло 4',
                                           'диван 2')]
        d = min((footprint(p).distance(corr) for p in sec), default=0.0) \
            if corr is not None else 0.0
        if best is None or d > best[0]:
            best = (d, r, ps)
    return (best[1], best[2]) if best else (room_of(kind), None)


def corner_scene(kind: str, block, corner: str = 'NW', rot: float = 135.0, margin: float = 10.0):
    """Канон «в углу» обязан СТОЯТЬ В УГЛУ (замечание владельца 19.08 «почему не в углу?»):
    габарит блока прижимается к двум стенам выбранного угла, лицо — по диагонали в комнату."""
    from planner.geometry import room_polygon, swing_polygon
    from shapely.geometry import box as _bx
    room = room_of(kind)
    if block is None:
        return room, None
    bw, bd, ox, oy = _bbox(block, rot)
    W, D = room.width_cm, room.depth_cm
    rp = room_polygon(room)
    try:
        sw = swing_polygon(room, next(o for o in room.openings if o.kind == 'door'))
    except Exception:
        sw = None
    for m in (margin, margin + 15, margin + 30):
        cx = (m + bw / 2) if corner[1] == 'W' else (W - m - bw / 2)
        cy = (D - m - bd / 2) if corner[0] == 'N' else (m + bd / 2)
        rect = _bx(cx - bw / 2, cy - bd / 2, cx + bw / 2, cy + bd / 2)
        if rp.contains(rect) and (sw is None or not rect.intersects(sw)):
            return room, block.to_world(cx - ox, cy - oy, rot)
    return room, None


def bay_scene(block, rot: float = 180.0, margin: float = 12.0):
    """Канон «в эркере» обязан стоять В НИШЕ (замечание владельца «кресло далеко не в эркере»):
    габарит блока целиком внутри выступа контура, спинка к наружной кромке, лицо в комнату.
    Прямоугольник ниши совпадает с контуром `room_of('bay')` — комната наша, гадать не надо."""
    from planner.geometry import room_polygon, swing_polygon
    from shapely.geometry import box as _bx
    room = room_of('bay')
    if block is None:
        return room, None
    x0, y0, x1, y1 = BAY_RECT
    bw, bd, ox, oy = _bbox(block, rot)
    rp = room_polygon(room)
    try:
        sw = swing_polygon(room, next(o for o in room.openings if o.kind == 'door'))
    except Exception:
        sw = None
    cx, cy = (x0 + x1) / 2, y1 - margin - bd / 2
    rect = _bx(cx - bw / 2, cy - bd / 2, cx + bw / 2, cy + bd / 2)
    inside_bay = rect.intersection(_bx(x0, y0, x1, y1)).area / max(rect.area, 1e-6)
    if not (rp.contains(rect) and (sw is None or not rect.intersects(sw)) and inside_bay > 0.75):
        return room, None       # честно: канон не влез в нишу — не рисуем «эркер» у другой стены
    return room, block.to_world(cx - ox, cy - oy, rot)


def placer_scene(kind: str, placer, roles: list[str], fixed_roles: list[str] | None = None,
                 fixed_ps: list[Placement] | None = None):
    room = room_of(kind)
    items = [CAT[r].model_copy() for r in roles if r in CAT]
    fixed = list(fixed_ps or [])
    free = usable_polygon(room)
    if fixed:
        from shapely.ops import unary_union
        free = free.difference(unary_union([footprint(p) for p in fixed if p.role != 'ковёр']))
    ps = placer(room, items, free, fixed=fixed)
    return (room, (fixed + list(ps)) if ps else None)


def sofa_at(room: Room, y=None) -> Placement:
    p = Placement(role='диван', x=room.width_cm / 2, y=(y if y is not None else 120),
                  rot=0, item=CAT['диван'])
    p.tpl_id = 'seating'
    return p


def with_context(room, ps, kind: str):
    """Контекст «как в жизни» (владелец 19.08): камин/медиа/хранение показываем ВМЕСТЕ с диваном
    напротив, посадку — с носителем ТВ у противоположной стены. Контекст рисуется бледнее по
    смыслу карточки, но геометрия честная: он тоже обязан быть внутри комнаты и вне дуги двери."""
    from planner.geometry import room_polygon, swing_polygon
    if not ps:
        return ps, []
    rp = room_polygon(room)
    try:
        sw = swing_polygon(room, next(o for o in room.openings if o.kind == 'door'))
    except Exception:
        sw = None
    ys = [p.y for p in ps]
    # ОСЬ — ГЛАВНЫЙ ДИВАН (замечание владельца 19.08 «почему ТВ не центрирована относительно
    # дивана»; так же считает и боевой движок — seat_axis_origin в geometry.py): носитель ставим
    # по оси взгляда главного дивана, а не по габариту группы и не по центру стены
    _sofas = [p for p in ps if p.role.split(' ')[0] == 'диван' and p.item]
    _main = max(_sofas, key=lambda p: p.item.w_cm) if _sofas else None
    if _main is None:      # контекстный диван встаёт по оси ЯКОРЯ канона (носитель ТВ / камин),
        # а не по среднему всех предметов: кашпо-акцент сбоку уводило «центрированный» ТВ с оси
        _anchor = next((p for p in ps if p.role.split(' ')[0] in ('тв-тумба', 'стенка', 'камин')), None)
        cx = _anchor.x if _anchor is not None else sum(p.x for p in ps) / len(ps)
    else:
        cx = _main.x
    xs = [p.x for p in ps]
    north = sum(ys) / len(ys) > room.depth_cm / 2      # канон стоит у северной стены?
    add = []
    if kind == 'facing_sofa':
        it = CAT['диван'].model_copy()
        tb = CAT['столик'].model_copy()
        # диван НАПРОТИВ канона ставим не «на глаз»: дистанция до носителя в комфортной вилке
        # (иначе эталон сам ловит SOFA_TV_FAR), полоса за спинкой — настоящий проход ≥95 см
        # (Q8: 31–90 см пустоты — щель), и столик перед диваном (без поверхности — SERVICE_SURFACE)
        _edge = (min(p.y - (p.item.d_cm / 2 if p.item else 0) for p in ps) if north
                 else max(p.y + (p.item.d_cm / 2 if p.item else 0) for p in ps))
        _sgn = 1.0 if north else -1.0
        y = _edge - _sgn * (240.0 + it.d_cm / 2)
        _back = (y - it.d_cm / 2) if north else (room.depth_cm - y - it.d_cm / 2)
        if _back < 95.0:                       # не хватило глубины — прижимаем по правилу прохода
            y = (95.0 + it.d_cm / 2) if north else (room.depth_cm - 95.0 - it.d_cm / 2)
        p = Placement(role='диван', x=cx, y=y, rot=(0 if north else 180), item=it)
        p.tpl_id = 'seating'
        pt = Placement(role='столик', x=cx, y=y + _sgn * (it.d_cm / 2 + 40.0 + tb.d_cm / 2),
                       rot=0.0, item=tb)
        pt.tpl_id = 'seating'
        add = [p, pt]
    elif kind == 'tv_wall':
        it = CAT['тв-тумба'].model_copy()
        # носитель ВСЕГДА у стены (иначе это не медиа-зона, а предмет посреди комнаты);
        # если вилка дистанции просмотра не выдерживается — контекст просто не показываем
        _far = (room.depth_cm - 12 - it.d_cm / 2) if not north else (12 + it.d_cm / 2)
        p = Placement(role='тв-тумба', x=cx, y=_far, rot=(180 if not north else 0), item=it)
        p.tpl_id = 'media'
        _sofa = next((q for q in ps if q.role.split(' ')[0] == 'диван'), None)
        if _sofa is not None:
            _d = footprint(_sofa).distance(footprint(p))
            if not (150 <= _d <= 320):
                return list(ps), []
        add = [p]
    ok = []
    for p in add:
        fp = footprint(p)
        if not (rp.contains(fp) and (sw is None or not fp.intersects(sw))):
            continue
        if any(footprint(q).intersects(fp) for q in ps):
            continue
        ok.append(p)     # контекст — часть реальной сцены; общий рендер проверит валидатор
    return list(ps) + ok, [p.role for p in ok]


def hard_violations(room, ps) -> list[str]:
    """Референс проходит ТОТ ЖЕ валидатор, что и рабочие планы (владелец 19.08: «там хватает
    косяков» — значит проверять надо машиной, а не глазами)."""
    from planner.validate import validate
    from planner.models import Severity
    try:
        return [v.code for v in validate(room, list(ps)).violations if v.severity is Severity.HARD]
    except Exception as e:
        return [f'ERR:{type(e).__name__}']


def check_render(room, ps) -> str | None:
    """Сторож витрины: референс не имеет права выходить за стены, лезть на дугу двери или
    пересекаться сам с собой (замечание владельца 19.08)."""
    from planner.geometry import room_polygon, swing_polygon
    if not ps:
        return 'схема не собралась'
    rp = room_polygon(room)
    sw = None
    try:
        sw = swing_polygon(room, next(o for o in room.openings if o.kind == 'door'))
    except Exception:
        pass
    for p in ps:
        fp = footprint(p)
        if rp.intersection(fp).area < fp.area * 0.995:
            return f'«{p.role}» выходит за стены'
        if sw is not None and fp.intersects(sw) and p.role.split(' ')[0] != 'ковёр':
            return f'«{p.role}» на дуге двери'
    for i, a in enumerate(ps):
        for b in ps[i + 1:]:
            if a.role.split(' ')[0] == 'ковёр' or b.role.split(' ')[0] == 'ковёр':
                continue
            if footprint(a).intersection(footprint(b)).area > 300:
                return f'«{a.role}» × «{b.role}» пересекаются'
    return None


def canons() -> list[dict]:
    """Каноны: (zone, id) → сцена. Порядок = порядок паспорта."""
    out = []
    by = lambda *rs: {r: CAT[r].model_copy() for r in rs}

    # ---------- SEATING (формы блока посадки)
    seat_kit = by('диван', 'кресло', 'кресло 2', 'столик', 'ковёр', 'торшер', 'пуф')
    for gid, shape in (('sofa_armchair', 'default'), ('sofa_2armchairs', 'facing'),
                       ('sofa_2armchairs', 'u'), ('sofa_2armchairs', 'bridge'),
                       ('sofa_2armchairs', 'tandem_r'), ('sofa_2armchairs', 'tandem_l'),
                       ('sofa_2armchairs', 'bulky'), ('sofa_armchair', 'media_parallel'),
                       ('sofa_2armchairs', 'media_bridge'), ('sofa_armchair', 'media_half'),
                       ('sofa_lamp', 'default'), ('sofa_2armchairs', 'default'),
                       ('armchair_pair', 'default'), ('compact_sectional', 'default'),
                       ('sofa_pouf', 'default'), ('sofa_solo', 'default'),
                       ('sofa_pouf', 'pouf_table')):
        _kit = dict(seat_kit)
        # СОСТАВ ПО ПАСПОРТУ ГРУППЫ (аудит Юли №14/15/16: карточки solo/pouf/sectional были
        # неразличимы — один kit на все группы; zones.json roles.required): у solo нет
        # спутников, у pouf пуф обязателен, у lamp свет вместо кресел, у пары кресел —
        # паспортный ПРИСТАВНОЙ (решение владельца 21.08 по №13), sectional — УГЛОВОЙ
        # диван (паспорт sofa_subtype «углов», признак Item.corner)
        _GROUP_KIT = {
            'sofa_solo': ('диван', 'столик', 'ковёр'),
            'sofa_pouf': ('диван', 'пуф', 'столик', 'ковёр'),
            'sofa_lamp': ('диван', 'торшер', 'столик', 'ковёр'),
            'armchair_pair': ('кресло', 'кресло 2', 'приставной', 'ковёр'),
        }
        if gid in _GROUP_KIT:
            _kit = by(*_GROUP_KIT[gid])
        elif gid == 'compact_sectional':
            _kit = {'диван': I('диван', 240, 160, 85, corner=True, corner_section_cm=90),
                    'столик': CAT['столик'].model_copy(), 'ковёр': CAT['ковёр'].model_copy()}
        if shape == 'tandem_l':
            # зеркальный тандем сажает торшер в карман между диваном и креслами — к нему
            # не остаётся прохода 46 см (боевой UNREACHABLE). Торшер в этой схеме опционален,
            # канон — про кресла в тандеме, поэтому показываем без него
            _kit.pop('торшер', None)
        if shape in ('media_parallel', 'media_half', 'bridge', 'media_bridge'):
            _kit.pop('пуф', None)                     # эти формы собираются без пуфа
            _kit['тв-тумба'] = CAT['тв-тумба'].model_copy()   # медиа-формы ориентируются на носитель
            _kit.pop('ковёр', None)   # bridge/media-формы разносят кресла под 45°: ковра-«клея»
            # в каталоге такой ширины нет — канон показываем без ковра (в бою ковёр берётся по факту)
        b = T.build_block(gid, _kit, variant=shape)
        if b is not None:
            b.tpl_variant = shape      # форма должна быть на предметах: контракты судят по ней
        _sk = 'media' if shape in ('media_parallel', 'media_bridge') else 'plain'
        if shape in ('tandem_r', 'tandem_l'):
            # зеркальный тандем — в дверной ситуации, где кресла на стороне ОТ входа
            r, ps = door_side_scene(_sk, b, wall='south')
        elif gid == 'compact_sectional' and b is not None:
            # угловой диван живёт В УГЛУ (CORNER_SOFA_ADRIFT): блок прижимаем к юго-западному
            # углу; зеркало Г-секции выбираем то, которое чек не считает «отбившимся»
            r, ps = None, None
            for _cl in (True, False):
                b = T.build_block(gid, {**_kit, 'диван': I('диван', 240, 160, 85, corner=True,
                                                          corner_section_cm=90, corner_left=_cl)},
                                  variant=shape)
                if b is None:
                    continue
                b.tpl_variant = shape
                _rc2 = room_of('plain')
                _bw2, _bd2, _ox2, _oy2 = _bbox(b, 0.0)
                _try = b.to_world(14 + _bw2 / 2 - _ox2, 14 + _bd2 / 2 - _oy2, 0.0)
                if check_render(_rc2, _try) or hard_violations(_rc2, _try) \
                        or 'CORNER_SOFA_ADRIFT' in soft_violations(_rc2, _try):
                    continue
                r, ps = _rc2, _try
                break
        else:
            r, ps = block_scene(_sk, b, wall='south')
        # ID карточки — (группа, форма): одна и та же форма `default` у РАЗНЫХ групп — это разные
        # композиции (диван+кресло, диван+торшер, два дивана визави). Раньше карточки писались в
        # один файл и затирали друг друга (находка аудита Codex 19.08)
        # passport_id — id КАНОНА (после слияния зеркал и переименований форма ≠ канон)
        out.append({'zone': 'seating', 'id': f'{gid}.{shape}',
                    'passport_id': (_GROUP_CANON.get(gid, shape) if shape == 'default'
                                    else PASSPORT_OF.get(shape) or shape),
                    'title': f'посадка: {shape} ({gid})' + (
                        ' · сторона — по маршруту от двери'
                        if shape in ('tandem_r', 'tandem_l') else ''),
                    'room': r, 'ps': ps})
    # у двух диванов без кресел вариант `square` геометрически совпадает с `default` (ветка
    # square расставляет только кресла) — честные имена карточек: Г-стык влево / вправо
    for _cid, _var, _ttl in (('L_left', 'default', 'посадка: два дивана Г-стыком влево'),
                             ('L_right', 'L_right', 'посадка: два дивана Г-стыком вправо')):
        b = T.build_block('sofa_loveseat', by('диван', 'диван 2', 'столик', 'ковёр'), variant=_var)
        if b is not None:
            b.tpl_variant = _cid
        # сцена — по двери (аудит Юли №18: второй диван вставал спинкой ко входу)
        r, ps = door_side_scene('plain', b, wall='south')
        out.append({'zone': 'seating', 'id': _cid, 'passport_id': 'two_sofa_l_joint',
                    'title': _ttl + ' · сторона — по маршруту от двери', 'room': r, 'ps': ps})

    # ---------- DINING
    for cid, kit, chairs, sides in (('dining_island', ('стол обеденный', 'стул', 'стул 2', 'стул 3', 'стул 4'), 4, 'all'),
                                    ('dining_against_wall', ('стол обеденный', 'стул', 'стул 2'), 2, 'front')):
        b = T.build_dining(by(*kit), chairs, sides=sides)
        r, ps = block_scene('plain', b, wall=('center' if cid == 'dining_island' else 'north'))
        out.append({'zone': 'dining', 'id': cid, 'title': f'столовая: {cid}', 'room': r, 'ps': ps})
    rnd = by('стол обеденный', 'стул', 'стул 2', 'стул 3', 'стул 4')
    rnd['стол обеденный'] = I('стол обеденный', 110, 110, 75, round_shape=True)
    b = T.build_dining(rnd, 4, sides='all')
    r, ps = block_scene('plain', b, wall='center')
    out.append({'zone': 'dining', 'id': 'dining_round_compact', 'title': 'столовая: круглый компактный', 'room': r, 'ps': ps})
    b = T.build_edge_nook(by('банкетка', 'стол обеденный', 'стул', 'стул 2'), variant='edge_nook_4')
    r, ps = block_scene('plain', b, wall='north')
    out.append({'zone': 'dining', 'id': 'dining_edge_nook', 'title': 'столовая: уголок с банкеткой', 'room': r, 'ps': ps})

    # ---------- QUIET
    for var, kit in (('quiet_chat', ('кресло 3', 'кресло 4', 'столик 2')), ):
        b = T.build_quiet(by(*kit), variant=var)
        r, ps = block_scene('plain', b, wall='north')
        out.append({'zone': 'quiet', 'id': var, 'passport_id': 'paired_conversation',
                    'title': 'тихая зона: парная беседа (два кресла + общая поверхность)',
                    'room': r, 'ps': ps})
    # с приставным столиком: пара кресел без поверхности — SERVICE_SURFACE на самом эталоне
    b = T.build_quiet(by('кресло 3', 'кресло 4', 'приставной', 'столик 2'),
                      variant='fireplace_flank', fireplace=CAT['камин'])
    if b is not None:
        b.tpl_variant = 'fireplace_flank'
    r, ps = block_scene('plain', b, wall='south')
    out.append({'zone': 'quiet', 'id': 'fireplace_flank', 'title': 'тихая зона: пара кресел у камина', 'room': r, 'ps': ps})

    # ---------- READING (якоря)
    # диван из сцены убран (владелец 19.08: «зачем диван, если это канон "кресло у окна"»):
    # плейсер разворачивает кресло в комнату и без главной группы — якорь здесь ОКНО
    r, ps = placer_scene('window_rad', T.place_window_reading, ['кресло', 'торшер', 'приставной'])
    out.append({'zone': 'reading', 'id': 'window_anchor', 'title': 'чтение: кресло у окна', 'room': r, 'ps': ps})
    # УГОЛ и ЭРКЕР — через БОЕВОЙ плейсер (Codex 19.08: витрина со своей геометрией маскирует
    # дефекты поиска). Позиции даёт `place_reading`: в углу — угловая раскладка (свет в вершину),
    # в эркере — общий генератор `_bay_candidates` с каскадом состава.
    r, ps = placer_scene('plain', T.place_reading, ['кресло', 'торшер', 'приставной'])
    out.append({'zone': 'reading', 'id': 'corner_vignette',
                'title': 'чтение: уголок в углу (кресло + свет + столик)', 'room': r, 'ps': ps})
    r, ps = placer_scene('bay', T.place_reading, ['кресло', 'торшер', 'приставной'])
    out.append({'zone': 'reading', 'id': 'bay_anchor', 'title': 'чтение: кресло в эркере', 'room': r, 'ps': ps})

    # ПАРА кресел у окна и в эркере (Q12, аудит Codex: практика знает обе формы)
    _pair_roles = ['кресло', 'кресло 2', 'приставной']
    _rw2 = Room(width_cm=520, depth_cm=430, openings=[
        Opening(kind='door', wall='west', offset_cm=40, width_cm=90, swing_cm=90),
        Opening(kind='window', wall='north', offset_cm=120, width_cm=200, sill_cm=80)])
    ps = T.place_window_reading(_rw2, [CAT[r].model_copy() for r in _pair_roles], usable_polygon(_rw2))
    out.append({'zone': 'reading', 'id': 'window_pair', 'title': 'чтение: пара кресел у окна',
                'room': _rw2, 'ps': ps})
    _rb3 = room_of('bay_wide')
    ps = T.place_reading(_rb3, [CAT[r].model_copy() for r in _pair_roles], usable_polygon(_rb3))
    out.append({'zone': 'reading', 'id': 'bay_pair', 'title': 'чтение: пара кресел в эркере',
                'room': _rb3, 'ps': ps})
    # кресло у СТЕНЫ полным комплектом (бывший скрытый fallback без паспорта).
    # Сцена — комната со скосами: в пустом прямоугольнике боевой плейсер всегда берёт
    # угол, и карточка выходила дублем corner_vignette (аудит Юли №31)
    _rw3 = room_of('chamfer')
    ps = T.place_reading(_rw3, [CAT[r].model_copy() for r in ('кресло', 'торшер', 'приставной')],
                         usable_polygon(_rw3))
    out.append({'zone': 'reading', 'id': 'wall_vignette',
                'title': 'чтение: кресло у стены (углы комнаты со скосами — заняты)',
                'room': _rw3, 'ps': ps})
    # растение У ОКНА (сбоку от проёма)
    r, ps = placer_scene('window', T.place_decor, ['кашпо'])
    out.append({'zone': 'decor', 'id': 'window_plant', 'title': 'декор: растение у окна',
                'room': r, 'ps': ps})

    # чтение у камина: ОДНО кресло + очаг (владелец 19.08 — отдельный канон, не «пара минус одно»)
    _fp = Placement(role='камин', x=280, y=402, rot=180.0, item=CAT['камин']); _fp.tpl_id = 'fireplace'
    r, ps = placer_scene('plain', T.place_reading, ['кресло', 'приставной'], fixed_ps=[_fp])
    out.append({'zone': 'reading', 'id': 'fireplace_anchor', 'title': 'чтение: кресло у камина',
                'room': r, 'ps': ps})

    # ---------- FIREPLACE / MEDIA / STORAGE / DECOR
    b = T.build_fireplace(by('камин', 'стеллаж', 'стеллаж 2'))
    r, ps = block_scene('big', b, wall='north')   # вилка «камин↔посадка» 200–450 требует простора
    out.append({'zone': 'fireplace', 'id': 'storage_flanks', 'title': 'камин: симметрия корпусами', 'room': r, 'ps': ps})
    b = T.build_media_fireplace(by('тв-тумба', 'камин'))
    r, ps = block_scene('big', b, wall='north')
    out.append({'zone': 'media', 'id': 'fireplace_side_by_side', 'title': 'медиа: ТВ и камин рядом', 'room': r, 'ps': ps})
    # build_media НЕ добавляет корпуса (только напольный акцент-кашпо) — прежнее название
    # «носитель с компаньонами» обещало то, чего в схеме нет; корпусная композиция — отдельный
    # паспорт media_installation, ему и своя карточка
    b = T.build_media(by('тв-тумба', 'кашпо'))
    r, ps = block_scene('plain', b, wall='north')     # обычная гостиная, не зал: дистанция в вилке
    out.append({'zone': 'media', 'id': 'media_centered', 'title': 'медиа: носитель по оси дивана',
                'room': r, 'ps': ps})
    _mi = (TPL.get('zones', {}).get('media', {}).get('schemes') or [])
    _mi = next((x.get('params') or {} for x in _mi if x.get('id') == 'media_installation'), {})
    b = T.build_media_installation(by('тв-тумба', 'витрина', 'стеллаж'), wall_len_cm=620.0, params=_mi)
    if b is not None:
        b.tpl_variant = 'installation'   # корпуса рядом с ТВ — это и есть схема, не «перегрузка стены»
    r, ps = block_scene('big', b, wall='north')
    out.append({'zone': 'media', 'id': 'media_installation',
                'passport_id': 'freestanding_media_storage_run',
                'title': 'медиа: носитель + корпуса одним рядом (свободностоящие)',
                'room': r, 'ps': ps})
    b = T.build_fireplace(by('камин', 'кашпо'))
    r, ps = block_scene('big', b, wall='north')
    out.append({'zone': 'fireplace', 'id': 'plant_flanks', 'title': 'камин: фланги-растения', 'room': r, 'ps': ps})
    r, ps = placer_scene('big', T.place_fireplace, ['камин'])
    out.append({'zone': 'fireplace', 'id': 'solo', 'title': 'камин: соло у стены', 'room': r, 'ps': ps})
    b = T.build_media(by('тв-тумба', 'кашпо'), mirror=True)
    r, ps = block_scene('plain', b, wall='north')
    out.append({'zone': 'media', 'id': 'media_mirror', 'title': 'медиа: акцент зеркально', 'room': r, 'ps': ps})
    # якорь схемы — ПРОСТЕНОК между двумя окнами (комната window2: проёмы 60–180 и 380–500,
    # простенок 180–380); носитель встаёт по его центру
    b = T.build_media(by('тв-тумба', 'кашпо'))
    # ЦЕНТР ПРОСТЕНКА держит ЯКОРЬ-тумба, кашпо в центрировании не участвует
    # (аудит Юли №41: спутник в bbox стаскивал тумбу с оси)
    r, ps = block_scene('window2', b, wall='north', center='anchor')
    out.append({'zone': 'media', 'id': 'media_between_windows', 'title': 'медиа: носитель между окон',
                'room': r, 'ps': ps})
    b = T.build_storage(by('комод', 'стеллаж'), max_items=2)
    r, ps = block_scene('big', b, wall='north')
    out.append({'zone': 'storage', 'id': 'storage_perimeter', 'title': 'хранение: ряд по периметру', 'room': r, 'ps': ps})
    r, ps = placer_scene('plain', T.place_decor, ['кашпо'])
    out.append({'zone': 'decor', 'id': 'corner_plant', 'title': 'декор: растение в углу', 'room': r, 'ps': ps})
    r, ps = placer_scene('bay', T.place_decor, ['кашпо'])
    out.append({'zone': 'decor', 'id': 'bay_plant', 'title': 'декор: растение в эркере', 'room': r, 'ps': ps})
    # НЕГЛУБОКОЕ хранение в полосе за спинкой дивана: комод ≤40 см у стены, высота ≤ спинки
    # (иначе TALL_SOLID_BEHIND_SOFA); диван плавающий, между ним и комодом остаётся маршрут
    _room_sh = room_of('plain')
    # 19.08 (замечание владельца): между спинкой и корпусом было 80 см — это НАША ЖЕ «сирота»
    # (31–90 см, Q8), которую спасал только признак «полосу занимает хранение». На эталоне так
    # нельзя: либо вплотную (это схема консоли), либо настоящий маршрут ≥91 см
    _sf = Placement(role='диван', x=280, y=228, rot=180, item=CAT['диван']); _sf.tpl_id = 'seating'
    _tb = Placement(role='столик', x=280, y=228 - 47.5 - 42.5 - 30, rot=0.0, item=CAT['столик'])
    _tb.tpl_id = 'seating'
    _rg = Placement(role='ковёр', x=280, y=123, rot=0.0, item=I('ковёр', 260, 180, 1)); _rg.tpl_id = 'seating'
    _st = Placement(role='комод', x=280, y=_room_sh.depth_cm - 12 - 20, rot=180.0,
                    item=I('комод', 120, 40, 80))
    _st.tpl_id = 'storage'; _st.tpl_variant = 'storage_shallow'
    out.append({'zone': 'storage', 'id': 'storage_shallow', 'title': 'хранение: неглубокое за диваном',
                'room': _room_sh, 'ps': [_rg, _sf, _tb, _st]})
    # диван плавающий (в этом и смысл консоли), но полоса ЗА консолью обязана быть настоящим
    # маршрутом: при y=250 за консолью оставалось 90 см — ровно на кромке route_min=91 (Q8)
    # x=310: дверь мини-сцены теперь у северного конца западной стены, и резерв входного
    # коридора (зона `entry` солвера, ~треть ширины) накрывал прежнюю позицию x=220
    _sofa = Placement(role='диван', x=310, y=240, rot=180, item=CAT['диван']); _sofa.tpl_id = 'seating'
    # у плавающего дивана есть свой столик — иначе эталон ловит SERVICE_SURFACE (и сцена
    # перестаёт быть похожей на жизнь: диван посреди комнаты без поверхности не бывает)
    _tbl = Placement(role='столик', x=310, y=240 - (95 / 2 + 40 + 30), rot=0.0, item=CAT['столик'])
    _tbl.tpl_id = 'seating'
    # КОВЁР (замечание владельца 19.08 «а тут ковёр где потерян»): у плавающей группы ковёр —
    # не декор, а то, что делает остров островом; кладём под передние ножки дивана и столик,
    # НЕ под консоль (она работает со стороны прохода)
    _rug = Placement(role='ковёр', x=310, y=240 - (95 / 2 + 40 + 30) + 10, rot=0.0,
                     item=I('ковёр', 260, 180, 1))
    _rug.tpl_id = 'seating'
    r, ps = placer_scene('plain', T.place_console_behind_sofa, ['консоль'],
                         fixed_ps=[_rug, _sofa, _tbl])
    out.append({'zone': 'storage', 'id': 'console_behind_sofa',
                'title': 'хранение: консоль за плавающим диваном (узкий низкий комод ≥⅔ дивана)',
                'room': r, 'ps': ps})

    # ---------- КАНОНЫ, У КОТОРЫХ НЕ БЫЛО ПАСПОРТА (аудит Codex 19.08)
    # два дивана ВИЗАВИ — классическая разговорная композиция (без ТВ в составе)
    b = T.build_block('sofa_facing_sofa', by('диван', 'диван 2', 'столик', 'ковёр'), variant='default')
    if b is not None:
        b.tpl_variant = 'vis_a_vis_sofas'
    r, ps = block_scene('big', b, wall='south')
    out.append({'zone': 'seating', 'id': 'vis_a_vis_sofas',
                'title': 'посадка: два дивана визави (беседа)', 'room': r, 'ps': ps})
    # СТЕНКА как носитель: занимает стену целиком, флангов не имеет
    b = T.build_media(by('стенка'))
    if b is not None:
        b.tpl_variant = 'media_wall'
    r, ps = block_scene('big', b, wall='north')
    out.append({'zone': 'media', 'id': 'wall_unit_centered',
                'title': 'медиа: стенка (носитель + хранение одним корпусом)', 'room': r, 'ps': ps})

    # ---------- Q12-4: РАЗБУЖЕННЫЕ СХЕМЫ (скамья у окна / в эркере, угловая башня)
    _bench = I('банкетка', 130, 42, 46, caps={'guaranteed_seats': 2, 'wall_seat_capable': True,
                                              'dining_seat_capable': True})
    r, ps = placer_scene('window', T.place_window_seat, [])
    if ps is None:
        _rw = room_of('window')
        ps = T.place_window_seat(_rw, [_bench.model_copy()], usable_polygon(_rw))
        r = _rw
    out.append({'zone': 'window_seat', 'id': 'bench_under_window',
                'title': 'скамья под окном (без радиатора — иначе схема не собирается)',
                'room': r, 'ps': ps})
    _rb2 = room_of('bay')
    ps = T.place_window_seat(_rb2, [_bench.model_copy()], usable_polygon(_rb2))
    out.append({'zone': 'window_seat', 'id': 'bay_bench', 'title': 'скамья в эркере (прямая, покупная)',
                'room': _rb2, 'ps': ps})
    _rt2 = room_of('plain')
    ps = T.place_storage(_rt2, [I('стеллаж', 80, 35, 190)], usable_polygon(_rt2))
    out.append({'zone': 'storage', 'id': 'corner_tower',
                'title': 'хранение: угловая башня (корпус вдоль стены угла)', 'room': _rt2, 'ps': ps})

    # ---------- ОСТАЛЬНЫЕ АКТИВНЫЕ СХЕМЫ ПАСПОРТА (полнота библиотеки, владелец 19.08)
    # square — «кресла столбиком сбоку столика»: без кресел форма совпадает с default,
    # поэтому показываем на группе С КРЕСЛАМИ, где она и отличается
    # ковёр возвращён (владелец 19.08 «тут ковра нет, пропал»): прятать предмет, чтобы обойти
    # мягкое замечание, — это и есть подгон витрины. Берём ковёр, который РЕАЛЬНО накрывает
    # композицию со столбиком кресел (350×250 — ходовой размер, не выдумка)
    _sqk = by('диван', 'диван 2', 'кресло', 'кресло 2', 'столик')
    _sqk['ковёр'] = I('ковёр', 350, 250, 1)
    for _sqv, _sqt in (('square', 'посадка: трёхсторонняя группа (кресла парой сбоку столика)'),
                       ('square_r', 'посадка: трёхсторонняя группа зеркально')):
        b = T.build_block('sofa_loveseat_2armchairs', dict(_sqk), variant=_sqv)
        if b is not None:
            b.tpl_variant = _sqv
        # сцена — по двери (аудит Юли №52: второй диван закрывал вход спинкой)
        r, ps = door_side_scene('big', b, wall='south')
        out.append({'zone': 'seating', 'id': _sqv, 'passport_id': 'three_sided_conversation',
                    'title': _sqt + ' · сторона — по маршруту от двери', 'room': r, 'ps': ps})
    # компактный зазор столика (36 см — нижняя граница нормы) для тесных комнат
    b = T.build_block('sofa_armchair', by('диван', 'кресло', 'столик', 'ковёр'), variant='default',
                      table_gap=float(((TPL.get('geometry') or {}).get('coffee_gap_compact_cm') or {}).get('v') or 36.0))
    if b is not None:
        b.tpl_variant = 'gap_compact'
    r, ps = block_scene('plain', b, wall='south')
    out.append({'zone': 'seating', 'id': 'gap_compact', 'title': 'посадка: компактный зазор столика (36 см)',
                'room': r, 'ps': ps})
    # диван СПИНКОЙ К ОКНУ — законно, когда подоконник выше спинки (полоса за спинкой по Q8)
    # спинка НИЖЕ подоконника (иначе SOFA_BACK_ABOVE_SILL) и воздух 15–30 см до окна (Q8)
    _wb = by('диван', 'кресло', 'столик', 'ковёр')
    _wb['диван'] = I('диван', 220, 95, 75)
    b = T.build_block('sofa_armchair', _wb, variant='default')
    if b is not None:
        b.tpl_variant = 'window_back'
    r, ps = block_scene('window', b, wall='north', margin=22.0)
    out.append({'zone': 'seating', 'id': 'window_back', 'title': 'посадка: диван спинкой к окну',
                'room': r, 'ps': ps})
    # плавающая пара «диван↔носитель» посреди комнаты (не у стены) — зонирование простора
    _fr = room_of('big')
    _fs = Placement(role='диван', x=_fr.width_cm / 2, y=200, rot=0.0, item=CAT['диван']); _fs.tpl_id = 'seating'
    _ft = Placement(role='столик', x=_fr.width_cm / 2, y=200 + 47.5 + 42.5 + 30, rot=0.0,
                    item=CAT['столик']); _ft.tpl_id = 'seating'
    # ковёр — по контуру пары «диван+столик» (иначе он «отрешён» от группы: RUG_DETACHED)
    # заход под передние ножки дивана 20 см (канон 10–45) и поле ≥30 см вокруг столика
    _fg = Placement(role='ковёр', x=_fr.width_cm / 2, y=200 + 47.5 - 20 + 80,
                    rot=0.0, item=I('ковёр', 290, 160, 1))
    _fg.tpl_id = 'seating'
    _fv = Placement(role='тв-тумба', x=_fr.width_cm / 2, y=_fr.depth_cm - 12 - 20, rot=180.0,
                    item=CAT['тв-тумба']); _fv.tpl_id = 'media'
    for _p in (_fs, _ft, _fv):
        _p.tpl_variant = 'floating_pair'
    out.append({'zone': 'seating', 'id': 'floating_pair',
                'passport_id': 'floating_sofa_opposite_media',
                'title': 'посадка: диван напротив носителя (плавающая пара)',
                'room': _fr, 'ps': [_fg, _fs, _ft, _fv]})
    # носитель ПО ДИАГОНАЛИ В УГЛУ — якорь ставит БОЕВОЙ генератор углов
    # (`_corner_candidates`), зеркало выбираем так, чтобы кашпо ушло на ОТКРЫТУЮ
    # сторону комнаты, а не на диагональную ось за тумбой (аудит Юли №57)
    _rc = room_of('plain')
    _freec = usable_polygon(_rc)
    _psc = None
    _ccn = next((c for c in T._corner_candidates(_rc, CAT['тв-тумба'], _freec)
                 if int(c.placement.rot) == 225), None)     # тот же угол, что раньше (NE)
    if _ccn is not None:
        _tvc = Placement(role='тв-тумба', x=_ccn.placement.x, y=_ccn.placement.y,
                         rot=225.0, item=CAT['тв-тумба'].model_copy())
        _tvc.tpl_id = 'media'
        # кашпо — СБОКУ у одной из стен угла, НЕ на диагональной оси за тумбой
        # (аудит Юли №57): вдоль северной стены левее тумбы или вдоль восточной ниже
        for _kx, _ky in ((_tvc.x - 150, _rc.depth_cm - 14 - 17.5),
                         (_rc.width_cm - 14 - 17.5, _tvc.y - 150)):
            _kpc = Placement(role='кашпо', x=_kx, y=_ky, rot=0.0,
                             item=CAT['кашпо'].model_copy())
            _kpc.tpl_id = 'media'
            if not check_render(_rc, [_tvc, _kpc]):
                _psc = [_tvc, _kpc]
                break
        _psc = _psc or [_tvc]
    out.append({'zone': 'media', 'id': 'media_corner',
                'title': 'медиа: носитель по диагонали в углу (кашпо сбоку, не на оси)',
                'room': _rc, 'ps': _psc})
    # носитель у КОСЯКА проёма (простенок рядом с дверью/окном)
    b = T.build_media(by('тв-тумба', 'кашпо'))
    r, ps = block_scene('window', b, wall='south')
    out.append({'zone': 'media', 'id': 'media_at_jamb', 'title': 'медиа: носитель у косяка проёма',
                'room': r, 'ps': ps})
    # media_storage_combo — тот же атом, что media_installation (паспорт: implemented_as)
    _mi2 = next((x.get('params') or {} for x in (TPL.get('zones', {}).get('media', {}).get('schemes') or [])
                 if x.get('id') == 'media_installation'), {})
    b = T.build_media_installation(by('тв-тумба', 'витрина', 'стеллаж'), wall_len_cm=620.0, params=_mi2)
    if b is not None:
        b.tpl_variant = 'installation'
    r, ps = block_scene('big', b, wall='north')
    out.append({'zone': 'media', 'id': 'media_storage_combo',
                'passport_id': 'freestanding_media_storage_run',
                'title': 'медиа: носитель + хранение одним рядом (= media_installation)', 'room': r, 'ps': ps})
    # зона fireplace_solo (отдельный паспорт): очаг без корпусов
    r, ps = placer_scene('big', T.place_fireplace, ['камин'])
    out.append({'zone': 'fireplace_solo', 'id': 'solo', 'title': 'камин: соло (отдельная зона)',
                'room': r, 'ps': ps})

    # ---------- НОВЫЕ СХЕМЫ 21.08 (решение владельца по аудиту Юли №35)
    # камин и ТВ на СМЕЖНЫХ (перпендикулярных) стенах: оба фокуса в одном угле обзора,
    # огонь не отражается в экране (Houzz «7 ways», Homes&Gardens)
    b = T.build_media(by('тв-тумба'))
    r, ps = block_scene('big', b, wall='north', center='anchor')
    _fbA = T._valid(T.Block(CAT['камин'].model_copy()), 'fireplace_solo')
    _r2A, _fpsA = block_scene('big', _fbA, wall='east')
    ps = (list(ps) + list(_fpsA)) if (ps and _fpsA) else None
    for _p in (ps or []):
        _p.tpl_variant = 'fireplace_tv_adjacent_walls'
    out.append({'zone': 'media', 'id': 'fireplace_tv_adjacent_walls',
                'title': 'медиа: ТВ и камин на смежных стенах', 'room': r, 'ps': ps})
    # ТВ НАД КАМИНОМ без тумбы (разбужена по решению владельца 21.08): камин — носитель
    # экрана; сам экран — служебная часть шаблона (§14), рисуется оверлеем
    _fbB = T._valid(T.Block(CAT['камин'].model_copy()), 'fireplace_solo')
    r, ps = block_scene('big', _fbB, wall='north')
    for _p in (ps or []):
        _p.tpl_variant = 'tv_over_fireplace'
    out.append({'zone': 'media', 'id': 'tv_over_fireplace',
                'title': 'медиа: ТВ над камином (тумба не нужна)', 'room': r, 'ps': ps})
    return out


# КОНТЕКСТ ПО СХЕМАМ (правило 19.08): предмет-свидетель допустим ТОЛЬКО там, где схема
# ОПРЕДЕЛЕНА относительно него и без него нечитаема. Всё остальное — шум на референсе
# («зачем диван?» — владелец). Формы посадки определены поворотом к экрану → носитель ТВ;
# media_centered — «по оси дивана» → диван; консоль «за диваном» несёт диван в самой сцене.
# форма в коде → id канона в паспорте (зеркала и переименования не создают новых канонов)
PASSPORT_OF = {
    'default': None, 'tandem_r': 'side_pair', 'tandem_l': 'side_pair',
    'L_right': 'two_sofa_l_joint', 'square': 'three_sided_conversation',
    'square_r': 'three_sided_conversation', 'facing': 'armchair_pair_opposite_sofa',
    'bulky': 'deep_armchairs_opposite', 'floating_pair': 'floating_sofa_opposite_media',
}
_GROUP_CANON = {'sofa_armchair': 'sofa_single_flank', 'sectional_armchair': 'sofa_single_flank',
                'sofa_2armchairs': 'sofa_pair_sides', 'sofa_4armchairs': 'sofa_pair_sides',
                'armchair_pair': 'armchair_pair_vis_a_vis', 'compact_sectional': 'sectional_solo',
                'sofa_pouf': 'sofa_pouf_group', 'sofa_lamp': 'sofa_lamp_group',
                'sofa_solo': 'sofa_solo_group', 'sofa_facing_sofa': 'vis_a_vis_sofas'}

CONTEXT_OF = {
    'seating.default': 'tv_wall', 'seating.u': 'tv_wall', 'seating.bridge': 'tv_wall',
    'seating.tandem_r': 'tv_wall', 'seating.media_parallel': 'tv_wall',
    'seating.media_bridge': 'tv_wall', 'seating.media_half': 'tv_wall',
    'seating.pouf_table': 'tv_wall',
    'seating.L_left': 'tv_wall', 'seating.L_right': 'tv_wall',
    'media.media_centered': 'facing_sofa',
    'media.wall_unit_centered': 'facing_sofa',
    'media.tv_over_fireplace': 'facing_sofa',
    # adjacent_walls — БЕЗ контекст-дивана: в мини-сцене продиктованная витриной посадка
    # не попадает камину в focal-сектор 75° (FIREPLACE_FAR_FROM_SEATING); в бою угол
    # обзора обеспечивает place_media_fireplace (перпендикулярные кандидаты + _view_filter)
}


def add_tv_overlay(art: dict, ps, card_id: str) -> None:
    """ТЕЛЕВИЗОР-РЕФЕРЕНС (решение владельца 21.08): на каждом носителе рисуем экран
    подходящего размера. Экран — СЛУЖЕБНАЯ часть шаблона (свод №8 v2 §14, `planner/tv.py`):
    отдельным предметом в сцену НЕ входит, в ps и в валидацию не попадает — только
    пунктирный оверлей поверх носителя. Диагональ: дистанция до ближайшего дивана / 1.6
    (RTINGS) с clamp долей ширины носителя; без посадки в сцене — середина clamp.
    Для `tv_over_fireplace` носителем экрана выступает КАМИН (та же доля ширины)."""
    import math as _mm

    from planner import tv as TV
    _bearers = ('камин',) if card_id == 'tv_over_fireplace' else ('тв-тумба', 'стенка')
    sofas = [p for p in ps if p.role.split(' ')[0] == 'диван' and p.item is not None]
    for p in ps:
        base = p.role.split(' ')[0]
        if base not in _bearers or p.item is None:
            continue
        if base == 'стенка':
            w_lo = TV.screen_width_cm(p.item.w_cm, 'стенка', 'min')
            w_hi = TV.screen_width_cm(p.item.w_cm, 'стенка', 'max')
            d_lo, d_hi = w_lo / TV.ASPECT_W, w_hi / TV.ASPECT_W
        else:
            d_lo, d_hi = TV.diag_from_stand(p.item.w_cm)
        diag = (d_lo + d_hi) / 2
        if sofas:
            # дистанция просмотра — как её меряет валидатор: между габаритами
            _s = min(sofas, key=lambda q: footprint(q).distance(footprint(p)))
            dist = footprint(_s).distance(footprint(p))
            if dist > 0:
                diag = min(max(dist / 1.6, d_lo), d_hi)
        w = diag * TV.ASPECT_W
        _r = _mm.radians(p.rot)
        fx, fy = _mm.sin(_r), _mm.cos(_r)             # фасад носителя
        role = f'тв {int(round(diag / 2.54))}″'
        art[role] = {'x': p.x - fx * (p.item.d_cm / 2 - 4.0),
                     'z': p.y - fy * (p.item.d_cm / 2 - 4.0),
                     'rot': p.rot, 'w': w, 'd': 8, 'h': 120,
                     'tpl_id': 'media', 'tpl_variant': 'screen_ref'}
        art['_context'] = list(art.get('_context') or []) + [role]


def soft_violations(room, ps) -> list[str]:
    """Мягкие нарушения на эталоне (Codex 19.08): S1/S2 на референсе — тоже дефект, просто
    не запрещающий сборку. Показываем их, чтобы «чисто» не означало «мы просто не смотрели»."""
    from planner.validate import validate
    from planner.models import Severity
    try:
        return sorted({v.code for v in validate(room, list(ps)).violations
                       if v.severity is not Severity.HARD})
    except Exception as e:
        return [f'ERR:{type(e).__name__}']


ZN = json.load(open(os.path.join(HERE, '..', '..', 'services', 'planner-solver',
                                 'rules', 'zones.json'), encoding='utf-8'))


def passport(zone: str, cid: str) -> dict:
    """Паспорт схемы. Формы ПОСАДКИ живут не только в templates.json: варианты блока
    (media_parallel, media_bridge, L_left/L_right…) объявлены в zones.json как `shapes`
    групп — раньше такие карточки выходили «паспорт не найден» (Codex 19.08)."""
    z = (TPL.get('zones') or {}).get(zone) or {}
    for s in (z.get('schemes') or []):
        if s.get('id') == cid:
            return s
    if zone == 'seating':
        _g = [g['id'] for g in (ZN.get('seating_groups') or [])
              if cid in (g.get('shapes') or []) and g.get('status', 'active') == 'active']
        if _g:
            return {'when': 'форма блока посадки для групп: ' + ', '.join(_g),
                    'why': ZN.get('_shapes_why', 'состав и форма группы — паспорт zones.json'),
                    'status': 'implemented_as: template.build_block (variant=%s)' % cid}
    return {}


def sleeping_schemes() -> list[dict]:
    """Схемы паспорта БЕЗ реализации (status: sleeping) — им тоже нужна карточка с честной
    пометкой: «не реализовано и почему». Отсутствие карточки читается как «схемы нет»."""
    out = []
    for zname, z in (TPL.get('zones') or {}).items():
        for sch in (z.get('schemes') or []):
            if str(sch.get('status', '')).startswith('sleeping'):
                out.append({'zone': zname, 'id': sch['id'], 'sleeping': True,
                            'title': f"{zname}: {sch['id']} — СПИТ",
                            'room': None, 'ps': None})
    return out


def coverage_gate(cards_ids: set) -> list[str]:
    """Каждая активная схема паспорта обязана иметь карточку (владелец 19.08 «это же каноны»)."""
    miss = []
    for zname, z in (TPL.get('zones') or {}).items():
        for sch in (z.get('schemes') or []):
            if str(sch.get('status', '')).startswith('sleeping'):
                continue
            if f"{zname}.{sch['id']}" not in cards_ids:
                miss.append(f"{zname}.{sch['id']}")
    return miss


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    cards = []
    _all = canons()
    _have = {f"{c['zone']}.{c['id']}" for c in _all}
    _all += [c for c in sleeping_schemes() if f"{c['zone']}.{c['id']}" not in _have]
    for c in _all:
        name = f"{c['zone']}.{c['id']}"
        png = os.path.join(OUT, name + '.png')
        c['ctx'] = []
        if c.get('sleeping'):
            p = passport(c['zone'], c.get('passport_id') or c['id'])
            meta = ''.join(f"<div><b>{k}:</b> {html.escape(str(p[k]))}</div>"
                           for k in ('when', 'why', 'status') if p.get(k))
            cards.append(f"<section class='sleep'><h2><span class='num'>#{len(cards) + 1}</span> "
                         f"{html.escape(c['title'])} "
                         f"<small>{html.escape(name)}</small></h2>"
                         f"<p class='none'>схема объявлена в паспорте, но НЕ реализована — "
                         f"рисовать нечего</p><div class='meta'>{meta}</div></section>")
            continue
        _ck = CONTEXT_OF.get(name) or CONTEXT_OF.get(f"{c['zone']}.{c.get('passport_id') or ''}")
        if c['ps'] and _ck:
            c['ps'], c['ctx'] = with_context(c['room'], c['ps'], _ck)
            if not c['ctx']:
                # обязательный свидетель не встал (дистанция/габарит) — это дефект сцены,
                # а не повод молча опубликовать канон без того, относительно чего он определён
                print(f'  ВНИМАНИЕ {name}: контекст «{_ck}» не поставлен — схема без свидетеля')
        _bad = check_render(c['room'], c['ps']) if c['ps'] else 'схема не собралась'
        _hard = hard_violations(c['room'], c['ps']) if (c['ps'] and not _bad) else []
        if _hard:
            _bad = 'нарушения правил: ' + ', '.join(sorted(set(_hard))[:4])
        _soft = soft_violations(c['room'], c['ps']) if (c['ps'] and not _bad) else []
        # ДОПУСТИМЫЕ отклонения — явным списком в паспорте схемы (`allowed_soft`), а не молчанием:
        # «чисто» обязано означать «проверено», а не «мы не смотрели» (Codex 19.08)
        _allow = set((passport(c['zone'], c.get('passport_id') or c['id']) or {}).get('allowed_soft') or [])
        _unexpected = [v for v in _soft if v not in _allow]
        if _unexpected:
            print(f'  ВНИМАНИЕ {name}: неожиданные мягкие: ' + ', '.join(_unexpected[:5]))
        elif _soft:
            print(f'  {name}: мягкие по паспорту (допустимо): ' + ', '.join(sorted(_soft)))
        if _bad:
            print(f'  ВНИМАНИЕ {name}: {_bad}')
        if c['ps'] and not _bad:
            _art = artifact(c['room'], c['ps'], c.get('ctx'))
            add_tv_overlay(_art, c['ps'], c['id'])   # телевизор-референс (владелец 21.08)
            render_artifact(_art, png, band='31-40')
            img = f"<img src='{name}.png' alt='{html.escape(name)}'>"
        else:
            img = f"<p class='none'>референс не показан: {html.escape(_bad or 'схема не собралась')}</p>"
        p = passport(c['zone'], c['id'])
        meta = ''.join(f"<div><b>{k}:</b> {html.escape(str(p[k]))}</div>"
                       for k in ('when', 'why', 'status') if p.get(k))
        cards.append(f"<section><h2><span class='num'>#{len(cards) + 1}</span> "
                     f"{html.escape(c['title'])} <small>{html.escape(name)}</small></h2>"
                     f"{img}<div class='meta'>{meta or '<i>паспорт не найден</i>'}</div></section>")
    style = ("body{margin:0;background:#fff;color:#1A1F1C;font:17px/1.5 system-ui}"
             ".wrap{max-width:1050px;margin:0 auto;padding:20px 14px 60px}h1{font-size:23px}"
             "section{border-top:1px solid #E4E6E2;padding:18px 0}h2{font-size:19px;margin:0 0 10px}"
             "h2 small{color:#5C655E;font-weight:400;font-size:14px}"
             "h2 .num{color:#3B76A2;font-weight:600}"
             "img{max-width:100%;border:1px solid #ECEEEA;border-radius:4px}"
             ".meta{font-size:15px;color:#3A423C;margin-top:8px}.meta div{margin:3px 0}"
             ".none{color:#a33}.head{margin:10px 0;padding:10px 12px;border-left:3px solid #3B76A2;"
             "background:#F4F7FA;font-size:15.5px}")
    head = ("<div class='head'>Каждый канон нарисован ТЕМ ЖЕ кодом, что и рабочие планы: это не "
            "картинки от руки, а результат шаблона в мини-комнате с нужным якорем (окно, эркер, "
            "камин, угол, стена). Под планом — паспорт: когда применяется, почему так, статус.</div>")
    page = ("<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<meta name='robots' content='noindex'><meta http-equiv='cache-control' content='no-store'>"
            f"<title>Каноны зон — планы</title><style>{style}</style></head><body><div class='wrap'>"
            f"<h1>Каноны зон — визуальная библиотека</h1>{head}{''.join(cards)}</div></body></html>")
    open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write(page)
    _miss = coverage_gate({f"{c['zone']}.{c.get('passport_id') or c['id']}" for c in _all})
    if _miss:
        print('  ВНИМАНИЕ полнота библиотеки: активные схемы без карточки — ' + ', '.join(_miss))
    print(f'OK: {len(cards)} канонов → {OUT}'
          + ('' if _miss else '; покрытие паспорта полное'))
    if '--publish' in sys.argv:
        subprocess.run(f"cd {os.path.dirname(OUT)} && tar czf /tmp/canon.tgz canon-gallery && "
                       "scp -q -P 22222 /tmp/canon.tgz root@89.167.127.0:/tmp/ && "
                       "ssh -p 22222 root@89.167.127.0 'cd /tmp && rm -rf canon-gallery && tar xzf canon.tgz && "
                       "rm -rf /opt/remlab/test/canons && mv canon-gallery /opt/remlab/test/canons && rm canon.tgz' && "
                       "rm -f /tmp/canon.tgz", shell=True, check=True)
        print('опубликовано: /test/canons/')


if __name__ == '__main__':
    main()
