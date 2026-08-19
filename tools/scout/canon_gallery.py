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


def room_of(kind: str) -> Room:
    """Мини-сцена под якорь канона."""
    door = Opening(kind='door', wall='south', offset_cm=30, width_cm=90, swing_cm=90)
    win = Opening(kind='window', wall='north', offset_cm=140, width_cm=160, sill_cm=80)
    if kind == 'window':
        return Room(width_cm=440, depth_cm=420, openings=[door, win])
    if kind == 'window_rad':
        return Room(width_cm=440, depth_cm=420, openings=[door, win],
                    radiators=[Radiator(wall='north', offset_cm=140, width_cm=160, depth_cm=15)])
    if kind == 'bay':
        return Room(width_cm=440, depth_cm=420, openings=[door, win],
                    contour=[[0, 0], [440, 0], [440, 300], [320, 300], [320, 420], [120, 420],
                             [120, 300], [0, 300]])
    return Room(width_cm=440, depth_cm=420, openings=[door])


def artifact(room: Room, ps: list[Placement]) -> dict:
    out = {'_room': {'w': room.width_cm, 'd': room.depth_cm,
                     'm2': round(room.width_cm * room.depth_cm / 10_000, 1),
                     'openings': [{'kind': o.kind, 'wall': o.wall, 'offset_cm': o.offset_cm,
                                   'width_cm': o.width_cm, 'swing_cm': getattr(o, 'swing_cm', 90),
                                   'sill_cm': getattr(o, 'sill_cm', 0)} for o in room.openings],
                     'radiators': [{'wall': r.wall, 'offset_cm': r.offset_cm, 'width_cm': r.width_cm,
                                    'depth_cm': r.depth_cm} for r in (room.radiators or [])],
                     'contour': room.contour},
           '_zones': {}}
    for p in ps:
        out[p.role] = {'x': p.x, 'z': p.y, 'rot': p.rot,
                       'w': p.item.w_cm if p.item else 50, 'd': p.item.d_cm if p.item else 50,
                       'h': (p.item.h_cm if p.item else 80),
                       'tpl_id': getattr(p, 'tpl_id', ''), 'tpl_variant': getattr(p, 'tpl_variant', '')}
    return out


def block_scene(kind: str, block, x=None, y=None, rot=180.0):
    """Поставить блок в центр мини-сцены (для канонов-блоков)."""
    room = room_of(kind)
    if block is None:
        return None, None
    x = room.width_cm / 2 if x is None else x
    y = room.depth_cm - 120 if y is None else y
    return room, block.to_world(x, y, rot)


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


def canons() -> list[dict]:
    """Каноны: (zone, id) → сцена. Порядок = порядок паспорта."""
    out = []
    by = lambda *rs: {r: CAT[r].model_copy() for r in rs}

    # ---------- SEATING (формы блока посадки)
    seat_kit = by('диван', 'кресло', 'кресло 2', 'столик', 'ковёр', 'торшер', 'пуф')
    for gid, shape in (('sofa_armchair', 'default'), ('sofa_2armchairs', 'facing'),
                       ('sofa_2armchairs', 'u'), ('sofa_2armchairs', 'bridge'),
                       ('sofa_2armchairs', 'tandem_r'), ('sofa_armchair', 'media_parallel'),
                       ('sofa_2armchairs', 'media_bridge'), ('sofa_lamp', 'default'),
                       ('sofa_pouf', 'pouf_table')):
        _kit = dict(seat_kit)
        if shape in ('media_parallel', 'bridge', 'media_bridge'):
            _kit.pop('пуф', None)                     # эти формы собираются без пуфа
        b = T.build_block(gid, _kit, variant=shape)
        r, ps = block_scene('plain', b)
        out.append({'zone': 'seating', 'id': shape, 'title': f'посадка: {shape} ({gid})',
                    'room': r, 'ps': ps})
    b = T.build_block('sofa_loveseat', by('диван', 'диван 2', 'столик', 'ковёр'), variant='default')
    r, ps = block_scene('plain', b)
    out.append({'zone': 'seating', 'id': 'square', 'title': 'посадка: два дивана Г-стыком', 'room': r, 'ps': ps})
    b = T.build_block('sofa_loveseat', by('диван', 'диван 2', 'столик', 'ковёр'), variant='L_right')
    r, ps = block_scene('plain', b)
    out.append({'zone': 'seating', 'id': 'L_right', 'title': 'посадка: Г-стык зеркально', 'room': r, 'ps': ps})

    # ---------- DINING
    for cid, kit, chairs, sides in (('dining_island', ('стол обеденный', 'стул', 'стул 2', 'стул 3', 'стул 4'), 4, 'all'),
                                    ('dining_against_wall', ('стол обеденный', 'стул', 'стул 2'), 2, 'front')):
        b = T.build_dining(by(*kit), chairs, sides=sides)
        r, ps = block_scene('plain', b)
        out.append({'zone': 'dining', 'id': cid, 'title': f'столовая: {cid}', 'room': r, 'ps': ps})
    rnd = by('стол обеденный', 'стул', 'стул 2', 'стул 3', 'стул 4')
    rnd['стол обеденный'] = I('стол обеденный', 110, 110, 75, round_shape=True)
    b = T.build_dining(rnd, 4, sides='all')
    r, ps = block_scene('plain', b)
    out.append({'zone': 'dining', 'id': 'dining_round_compact', 'title': 'столовая: круглый компактный', 'room': r, 'ps': ps})
    b = T.build_edge_nook(by('банкетка', 'стол обеденный', 'стул', 'стул 2'), variant='edge_nook_4')
    r, ps = block_scene('plain', b, y=140, rot=0.0)
    out.append({'zone': 'dining', 'id': 'dining_edge_nook', 'title': 'столовая: уголок с банкеткой', 'room': r, 'ps': ps})

    # ---------- QUIET
    for var, kit in (('quiet_chat', ('кресло 3', 'кресло 4', 'столик 2')), ):
        b = T.build_quiet(by(*kit), variant=var)
        r, ps = block_scene('plain', b, rot=0.0)
        out.append({'zone': 'quiet', 'id': var, 'title': 'тихая зона: пара кресел + столик', 'room': r, 'ps': ps})
    b = T.build_quiet(by('кресло 3', 'кресло 4'), variant='fireplace_flank', fireplace=CAT['камин'])
    r, ps = block_scene('plain', b, y=60, rot=0.0)
    out.append({'zone': 'quiet', 'id': 'fireplace_flank', 'title': 'тихая зона: пара кресел у камина', 'room': r, 'ps': ps})

    # ---------- READING (якоря)
    r, ps = placer_scene('window_rad', T.place_window_reading, ['кресло', 'торшер', 'приставной'],
                         fixed_ps=[sofa_at(room_of('window_rad'), y=140)])
    out.append({'zone': 'reading', 'id': 'window_anchor', 'title': 'чтение: кресло у окна', 'room': r, 'ps': ps})
    # уголок в углу и кресло в эркере рисуем КОМПОЗИЦИЕЙ (тот же build_reading): канон — это
    # состав и взаимное расположение; поиск позиции проверяется на боевых сценах, не в витрине
    _rb = T.build_reading(by('кресло', 'торшер', 'приставной'))
    if _rb is not None:
        _rb.tpl_variant = 'corner_vignette'
    r, ps = block_scene('plain', _rb, x=150, y=300, rot=135.0)
    out.append({'zone': 'reading', 'id': 'corner_vignette',
                'title': 'чтение: уголок в углу (кресло + свет + столик)', 'room': r, 'ps': ps})
    _bb = T.build_reading(by('кресло', 'торшер'))
    if _bb is not None:
        _bb.tpl_variant = 'bay_anchor'
    r, ps = block_scene('bay', _bb, x=220, y=370, rot=180.0)
    out.append({'zone': 'reading', 'id': 'bay_anchor', 'title': 'чтение: кресло в эркере', 'room': r, 'ps': ps})

    # ---------- FIREPLACE / MEDIA / STORAGE / DECOR
    b = T.build_fireplace(by('камин', 'стеллаж', 'витрина'))
    r, ps = block_scene('plain', b, y=60, rot=0.0)
    out.append({'zone': 'fireplace', 'id': 'storage_flanks', 'title': 'камин: симметрия корпусами', 'room': r, 'ps': ps})
    b = T.build_media_fireplace(by('тв-тумба', 'камин'))
    r, ps = block_scene('plain', b, y=60, rot=0.0)
    out.append({'zone': 'media', 'id': 'fireplace_side_by_side', 'title': 'медиа: ТВ и камин рядом', 'room': r, 'ps': ps})
    b = T.build_media(by('тв-тумба', 'стеллаж', 'витрина'))
    r, ps = block_scene('plain', b, y=60, rot=0.0)
    out.append({'zone': 'media', 'id': 'media_centered', 'title': 'медиа: носитель с компаньонами', 'room': r, 'ps': ps})
    b = T.build_storage(by('комод', 'стеллаж'), max_items=2)
    r, ps = block_scene('plain', b, y=60, rot=0.0)
    out.append({'zone': 'storage', 'id': 'storage_perimeter', 'title': 'хранение: ряд по периметру', 'room': r, 'ps': ps})
    r, ps = placer_scene('plain', T.place_decor, ['кашпо'], fixed_ps=[sofa_at(room_of('plain'), y=140)])
    out.append({'zone': 'decor', 'id': 'corner_plant', 'title': 'декор: растение в углу', 'room': r, 'ps': ps})
    _sofa = Placement(role='диван', x=220, y=250, rot=180, item=CAT['диван']); _sofa.tpl_id = 'seating'
    r, ps = placer_scene('plain', T.place_console_behind_sofa, ['комод'], fixed_ps=[_sofa])
    out.append({'zone': 'storage', 'id': 'console_behind_sofa', 'title': 'хранение: консоль за диваном', 'room': r, 'ps': ps})
    return out


def passport(zone: str, cid: str) -> dict:
    z = (TPL.get('zones') or {}).get(zone) or {}
    for s in (z.get('schemes') or []):
        if s.get('id') == cid:
            return s
    return {}


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    cards = []
    for c in canons():
        name = f"{c['zone']}.{c['id']}"
        png = os.path.join(OUT, name + '.png')
        if c['ps']:
            render_artifact(artifact(c['room'], c['ps']), png, band='31-40')
            img = f"<img src='{name}.png' alt='{html.escape(name)}'>"
        else:
            img = "<p class='none'>схема не собралась в мини-сцене (нужен другой якорь/состав)</p>"
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
    print(f'OK: {len(cards)} канонов → {OUT}')
    if '--publish' in sys.argv:
        subprocess.run(f"cd {os.path.dirname(OUT)} && tar czf /tmp/canon.tgz canon-gallery && "
                       "scp -q -P 22222 /tmp/canon.tgz root@89.167.127.0:/tmp/ && "
                       "ssh -p 22222 root@89.167.127.0 'cd /tmp && rm -rf canon-gallery && tar xzf canon.tgz && "
                       "rm -rf /opt/remlab/test/canons && mv canon-gallery /opt/remlab/test/canons && rm canon.tgz' && "
                       "rm -f /tmp/canon.tgz", shell=True, check=True)
        print('опубликовано: /test/canons/')


if __name__ == '__main__':
    main()
