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
    'стул': I('стул', 45, 52, 90), 'стул 2': I('стул 2', 45, 52, 90),
    'стул 3': I('стул 3', 45, 52, 90), 'стул 4': I('стул 4', 45, 52, 90),
    'банкетка': I('банкетка', 130, 42, 46, caps={'guaranteed_seats': 2, 'dining_seat_capable': True,
                                                 'wall_seat_capable': True}),
    'кашпо': I('кашпо', 35, 35, 90),
}


BAY_RECT = (120.0, 300.0, 320.0, 420.0)     # ниша эркера в room_of('bay') — по контуру комнаты


def room_of(kind: str) -> Room:
    """Мини-сцена под якорь канона."""
    door = Opening(kind='door', wall='west', offset_cm=40, width_cm=90, swing_cm=90)
    win = Opening(kind='window', wall='north', offset_cm=140, width_cm=160, sill_cm=80)
    if kind == 'window':
        return Room(width_cm=440, depth_cm=420, openings=[door, win])
    if kind == 'plain':
        # 560×430: широкие формы посадки (медиа-параллель, мостик) помещаются целиком, а дистанция
        # диван↔ТВ остаётся в вилке просмотра — референс не должен уезжать в «просторную» сцену
        return Room(width_cm=560, depth_cm=430, openings=[door])
    if kind == 'window2':
        # два окна на одной стене — якорь схемы media_between_windows (простенок между проёмами)
        return Room(width_cm=560, depth_cm=430, openings=[
            door, Opening(kind='window', wall='north', offset_cm=60, width_cm=120, sill_cm=80),
            Opening(kind='window', wall='north', offset_cm=380, width_cm=120, sill_cm=80)])
    if kind == 'media':
        # 560×370: медиа-формы (кресло к экрану) нужен носитель в вилке просмотра 150–320 см —
        # в 430-глубокой комнате ТВ у дальней стены уезжает за 320 и контекст пропадал,
        # а канон «кресло к ТВ» без ТВ нелегален по определению
        return Room(width_cm=560, depth_cm=370, openings=[door])
    if kind == 'window_rad':
        return Room(width_cm=440, depth_cm=420, openings=[door, win],
                    radiators=[Radiator(wall='north', offset_cm=140, width_cm=160, depth_cm=15)])
    if kind == 'big':
        return Room(width_cm=620, depth_cm=560, openings=[door])
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
    return out


def _bbox(block, rot: float):
    """Габарит блока — ОБЩИЙ helper солвера (`template.block_bbox`). Своя копия здесь была
    ошибкой: витрина считала иначе и маскировала дефекты боевого поиска (Codex 19.08)."""
    return T.block_bbox(block, rot)


def block_scene(kind: str, block, wall: str = 'north', rot: float | None = None, margin: float = 12.0):
    """Поставить канон ТАК, КАК ЭТО СТОИТ В РЕАЛЬНОСТИ (замечание владельца 19.08): спиной к
    стене (или в центре для острова), по центру стены, ЦЕЛИКОМ внутри комнаты и мимо дуги двери.
    Референс не имеет права нарушать то, что мы требуем от рабочих планов."""
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
    rp, sw = room_polygon(room), None
    try:
        sw = swing_polygon(room, next(o for o in room.openings if o.kind == 'door'))
    except Exception:
        sw = None
    # сдвиг вдоль стены, если попали в дугу двери; проверяем полное вхождение в комнату
    from shapely.geometry import box as _bx
    best = None
    for shift in (0, 40, -40, 80, -80, 120, -120):
        tx, ty = (cx + shift, cy) if wall in ('north', 'south', 'center') else (cx, cy + shift)
        rect = _bx(tx - bw / 2, ty - bd / 2, tx + bw / 2, ty + bd / 2)
        if rp.contains(rect) and (sw is None or not rect.intersects(sw)):
            best = (tx, ty); break
    if best is None:
        if kind != 'big':            # композиция шире мини-сцены — берём просторную комнату
            return block_scene('big', block, wall=wall, rot=rot, margin=margin)
        return room, None            # честно: канон не помещается даже в просторной
    tx, ty = best
    return room, block.to_world(tx - ox, ty - oy, rot)


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
                       ('sofa_2armchairs', 'media_bridge'), ('sofa_lamp', 'default'),
                       ('sofa_pouf', 'pouf_table')):
        _kit = dict(seat_kit)
        if shape == 'tandem_l':
            # зеркальный тандем сажает торшер в карман между диваном и креслами — к нему
            # не остаётся прохода 46 см (боевой UNREACHABLE). Торшер в этой схеме опционален,
            # канон — про кресла в тандеме, поэтому показываем без него
            _kit.pop('торшер', None)
        if shape in ('media_parallel', 'bridge', 'media_bridge'):
            _kit.pop('пуф', None)                     # эти формы собираются без пуфа
            _kit['тв-тумба'] = CAT['тв-тумба'].model_copy()   # медиа-формы ориентируются на носитель
            _kit.pop('ковёр', None)   # bridge/media-формы разносят кресла под 45°: ковра-«клея»
            # в каталоге такой ширины нет — канон показываем без ковра (в бою ковёр берётся по факту)
        b = T.build_block(gid, _kit, variant=shape)
        if b is not None:
            b.tpl_variant = shape      # форма должна быть на предметах: контракты судят по ней
        r, ps = block_scene('media' if shape in ('media_parallel', 'media_bridge') else 'plain',
                            b, wall='south')
        out.append({'zone': 'seating', 'id': shape, 'title': f'посадка: {shape} ({gid})',
                    'room': r, 'ps': ps})
    # у двух диванов без кресел вариант `square` геометрически совпадает с `default` (ветка
    # square расставляет только кресла) — честные имена карточек: Г-стык влево / вправо
    for _cid, _var, _ttl in (('L_left', 'default', 'посадка: два дивана Г-стыком влево'),
                             ('L_right', 'L_right', 'посадка: два дивана Г-стыком вправо')):
        b = T.build_block('sofa_loveseat', by('диван', 'диван 2', 'столик', 'ковёр'), variant=_var)
        if b is not None:
            b.tpl_variant = _cid
        r, ps = block_scene('plain', b, wall='south')
        out.append({'zone': 'seating', 'id': _cid, 'title': _ttl, 'room': r, 'ps': ps})

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
        out.append({'zone': 'quiet', 'id': var, 'title': 'тихая зона: пара кресел + столик', 'room': r, 'ps': ps})
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
    out.append({'zone': 'media', 'id': 'media_installation', 'title': 'медиа: инсталляция с корпусами',
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
    r, ps = block_scene('window2', b, wall='north')
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
    _sf = Placement(role='диван', x=280, y=250, rot=180, item=CAT['диван']); _sf.tpl_id = 'seating'
    _tb = Placement(role='столик', x=280, y=250 - 47.5 - 42.5 - 30, rot=0.0, item=CAT['столик'])
    _tb.tpl_id = 'seating'
    _rg = Placement(role='ковёр', x=280, y=145, rot=0.0, item=I('ковёр', 260, 180, 1)); _rg.tpl_id = 'seating'
    _st = Placement(role='комод', x=280, y=_room_sh.depth_cm - 12 - 20, rot=180.0,
                    item=I('комод', 120, 40, 80))
    _st.tpl_id = 'storage'; _st.tpl_variant = 'storage_shallow'
    out.append({'zone': 'storage', 'id': 'storage_shallow', 'title': 'хранение: неглубокое за диваном',
                'room': _room_sh, 'ps': [_rg, _sf, _tb, _st]})
    # диван плавающий (в этом и смысл консоли), но полоса ЗА консолью обязана быть настоящим
    # маршрутом: при y=250 за консолью оставалось 90 см — ровно на кромке route_min=91 (Q8)
    _sofa = Placement(role='диван', x=220, y=240, rot=180, item=CAT['диван']); _sofa.tpl_id = 'seating'
    # у плавающего дивана есть свой столик — иначе эталон ловит SERVICE_SURFACE (и сцена
    # перестаёт быть похожей на жизнь: диван посреди комнаты без поверхности не бывает)
    _tbl = Placement(role='столик', x=220, y=240 - (95 / 2 + 40 + 30), rot=0.0, item=CAT['столик'])
    _tbl.tpl_id = 'seating'
    # КОВЁР (замечание владельца 19.08 «а тут ковёр где потерян»): у плавающей группы ковёр —
    # не декор, а то, что делает остров островом; кладём под передние ножки дивана и столик,
    # НЕ под консоль (она работает со стороны прохода)
    _rug = Placement(role='ковёр', x=220, y=240 - (95 / 2 + 40 + 30) + 10, rot=0.0,
                     item=I('ковёр', 260, 180, 1))
    _rug.tpl_id = 'seating'
    r, ps = placer_scene('plain', T.place_console_behind_sofa, ['комод'],
                         fixed_ps=[_rug, _sofa, _tbl])
    out.append({'zone': 'storage', 'id': 'console_behind_sofa',
                'title': 'хранение: консоль за плавающим диваном', 'room': r, 'ps': ps})

    # ---------- ОСТАЛЬНЫЕ АКТИВНЫЕ СХЕМЫ ПАСПОРТА (полнота библиотеки, владелец 19.08)
    # square — «кресла столбиком сбоку столика»: без кресел форма совпадает с default,
    # поэтому показываем на группе С КРЕСЛАМИ, где она и отличается
    # без ковра: у «столбика» кресла стоят вне ковра любой каталожной ширины (ARMCHAIR_OFF_RUG) —
    # ковёр в этой форме берётся по факту, канон показываем без него
    b = T.build_block('sofa_loveseat_2armchairs',
                      by('диван', 'диван 2', 'кресло', 'кресло 2', 'столик'), variant='square')
    if b is not None:
        b.tpl_variant = 'square'
    r, ps = block_scene('big', b, wall='south')
    out.append({'zone': 'seating', 'id': 'square', 'title': 'посадка: кресла столбиком сбоку столика',
                'room': r, 'ps': ps})
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
    out.append({'zone': 'seating', 'id': 'floating_pair', 'title': 'посадка: плавающая пара диван↔носитель',
                'room': _fr, 'ps': [_fg, _fs, _ft, _fv]})
    # носитель ПО ДИАГОНАЛИ В УГЛУ — общий генератор углов солвера
    b = T.build_media(by('тв-тумба', 'кашпо'))
    r, ps = corner_scene('plain', b, corner='NE', rot=225.0)
    out.append({'zone': 'media', 'id': 'media_corner', 'title': 'медиа: носитель по диагонали в углу',
                'room': r, 'ps': ps})
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
                'title': 'медиа: носитель + хранение одним рядом (= media_installation)', 'room': r, 'ps': ps})
    # зона fireplace_solo (отдельный паспорт): очаг без корпусов
    r, ps = placer_scene('big', T.place_fireplace, ['камин'])
    out.append({'zone': 'fireplace_solo', 'id': 'solo', 'title': 'камин: соло (отдельная зона)',
                'room': r, 'ps': ps})
    return out


# КОНТЕКСТ ПО СХЕМАМ (правило 19.08): предмет-свидетель допустим ТОЛЬКО там, где схема
# ОПРЕДЕЛЕНА относительно него и без него нечитаема. Всё остальное — шум на референсе
# («зачем диван?» — владелец). Формы посадки определены поворотом к экрану → носитель ТВ;
# media_centered — «по оси дивана» → диван; консоль «за диваном» несёт диван в самой сцене.
CONTEXT_OF = {
    'seating.default': 'tv_wall', 'seating.u': 'tv_wall', 'seating.bridge': 'tv_wall',
    'seating.tandem_r': 'tv_wall', 'seating.media_parallel': 'tv_wall',
    'seating.media_bridge': 'tv_wall', 'seating.pouf_table': 'tv_wall',
    'seating.L_left': 'tv_wall', 'seating.L_right': 'tv_wall',
    'media.media_centered': 'facing_sofa',
}


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
            p = passport(c['zone'], c['id'])
            meta = ''.join(f"<div><b>{k}:</b> {html.escape(str(p[k]))}</div>"
                           for k in ('when', 'why', 'status') if p.get(k))
            cards.append(f"<section class='sleep'><h2>{html.escape(c['title'])} "
                         f"<small>{html.escape(name)}</small></h2>"
                         f"<p class='none'>схема объявлена в паспорте, но НЕ реализована — "
                         f"рисовать нечего</p><div class='meta'>{meta}</div></section>")
            continue
        _ck = CONTEXT_OF.get(name)
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
        _allow = set((passport(c['zone'], c['id']) or {}).get('allowed_soft') or [])
        _unexpected = [v for v in _soft if v not in _allow]
        if _unexpected:
            print(f'  ВНИМАНИЕ {name}: неожиданные мягкие: ' + ', '.join(_unexpected[:5]))
        elif _soft:
            print(f'  {name}: мягкие по паспорту (допустимо): ' + ', '.join(sorted(_soft)))
        if _bad:
            print(f'  ВНИМАНИЕ {name}: {_bad}')
        if c['ps'] and not _bad:
            render_artifact(artifact(c['room'], c['ps'], c.get('ctx')), png, band='31-40')
            img = f"<img src='{name}.png' alt='{html.escape(name)}'>"
        else:
            img = f"<p class='none'>референс не показан: {html.escape(_bad or 'схема не собралась')}</p>"
        p = passport(c['zone'], c['id'])
        meta = ''.join(f"<div><b>{k}:</b> {html.escape(str(p[k]))}</div>"
                       for k in ('when', 'why', 'status') if p.get(k))
        cards.append(f"<section><h2>{html.escape(c['title'])} <small>{html.escape(name)}</small></h2>"
                     f"{img}<div class='meta'>{meta or '<i>паспорт не найден</i>'}</div></section>")
    style = ("body{margin:0;background:#fff;color:#1A1F1C;font:17px/1.5 system-ui}"
             ".wrap{max-width:1050px;margin:0 auto;padding:20px 14px 60px}h1{font-size:23px}"
             "section{border-top:1px solid #E4E6E2;padding:18px 0}h2{font-size:19px;margin:0 0 10px}"
             "h2 small{color:#5C655E;font-weight:400;font-size:14px}"
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
    _miss = coverage_gate({f"{c['zone']}.{c['id']}" for c in _all})
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
