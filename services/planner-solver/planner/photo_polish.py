"""РАССТАНОВКА ПОД СЪЁМКУ (план demo-05 п.2a, разбор Codex 15.10).

Торшер шаблон ставит у одного и того же торца дивана (`template._add_lamp`, сторона −1 в осях блока) — комнаты и двери
шаблон не знает. В демо (сканди, джапанди 15.10) торшер оказался у торца, ближнего к входу, и стоял между любой точкой
съёмки и диваном: камера окна не находила кадра, где диван целиком и перед ним ничего высокого. Правило дизайнера:
торшер — у торца, ДАЛЬНЕГО от входа.

Шаг работает с готовой расстановкой (после выбора плана, до экспорта) и не ломает проверенное: переносит только одиночный
торшер посадки у прямого дивана, отражая его ПОПЕРЕЧНУЮ координату относительно оси дивана (продольная — «за плечом» —
остаётся), и принимает перенос, только если полная проверка (`validate`) не дала новых жёстких нарушений, а торшер остался
в вилке «у посадки». Пороги — `rules/zones.json → photo_layout`.
"""
from __future__ import annotations

import math

from .geometry import _wall_point, footprint
from .models import Placement, Room


def _cfg() -> dict:
    from .zones import zone_rules
    return {'enabled': True, 'min_gain_cm': 20.0, 'max_end_gap_cm': 60.0, **(zone_rules().get('photo_layout') or {})}


def _base(role: str) -> str:
    return role.split(' ')[0]


def entrance_center(room: Room):
    """Центр входной двери комнаты (первая дверь) — точка, от которой торшер уводится."""
    for op in room.openings:
        if op.kind == 'door':
            return _wall_point(room, op.wall, op.offset_cm + op.width_cm / 2)
    return None


def lamp_far_from_entry(room: Room, placements: list[Placement], validate_fn) -> tuple[list[Placement], str, set]:
    """→ (расстановка, пояснение, принятые исключения {(код, роли)}). Ничего не меняется — та же расстановка, пустое
    пояснение и пустое множество."""
    import os as _os
    dbg = (lambda *a: print('PHOTO_DBG', *a, flush=True)) if _os.environ.get('PHOTO_DEBUG') else (lambda *a: None)
    cfg = _cfg()
    if not cfg.get('enabled', True):
        return placements, '', set()
    door = entrance_center(room)
    lamps = [p for p in placements if _base(p.role) == 'торшер']
    sofas = [p for p in placements if _base(p.role) == 'диван' and p.item is not None and not p.item.corner]
    # пары торшеров зеркальны по схеме, торшеры уголка чтения и эркера — свои правила: не трогаем
    if door is None or len(lamps) != 1 or not sofas or lamps[0].item is None:
        dbg('нет двери/торшера/дивана', door, len(lamps), len(sofas))
        return placements, '', set()
    lamp = lamps[0]
    dbg('tpl', lamp.tpl_id, 'лампа', lamp.x, lamp.y, 'диваны', [(s.x, s.y, s.rot, s.item.w_cm) for s in sofas], 'дверь', door)
    if (lamp.tpl_id or '') not in ('', 'seating') and 'sofa' not in (lamp.tpl_id or ''):
        return placements, '', set()
    sofa = min(sofas, key=lambda s: math.hypot(s.x - lamp.x, s.y - lamp.y))
    r = math.radians(sofa.rot)
    ux, uy = math.cos(r), -math.sin(r)            # ось ширины дивана (`geometry.footprint`: поворот на −rot)
    vx, vy = math.sin(r), math.cos(r)             # ось глубины (лицо — `geometry.py`)
    dx, dy = lamp.x - sofa.x, lamp.y - sofa.y
    a, b = dx * ux + dy * uy, dx * vx + dy * vy
    dbg('a', a, 'b', b)
    if abs(a) - sofa.item.w_cm / 2 > cfg['max_end_gap_cm'] or abs(a) < sofa.item.w_cm / 2:
        return placements, '', set()                     # не у торца — это другой торшер (за спинкой, в углу)
    nx, ny = sofa.x - a * ux + b * vx, sofa.y - a * uy + b * vy
    gain = math.hypot(nx - door.x, ny - door.y) - math.hypot(lamp.x - door.x, lamp.y - door.y)
    dbg('новая', nx, ny, 'выигрыш', gain)
    if gain < cfg['min_gain_cm']:
        return placements, '', set()
    moved = lamp.model_copy(update={'x': nx, 'y': ny})
    cand = [moved if p is lamp else p for p in placements]
    # не наезжает на других (ковёр — пол) и не выходит за комнату — дешёвая проверка до полной
    fp = footprint(moved)
    for p in cand:
        if p is moved or p.item is None or _base(p.role) == 'ковёр':
            continue
        if fp.distance(footprint(p)) < 5.0:
            dbg('наезд на', p.role)
            return placements, '', set()

    def hard(ps):
        lay = validate_fn(room, ps)
        return {(v.code, tuple(sorted(v.roles))) for v in lay.violations if getattr(v, 'severity', '') == 'hard'}

    new_hard = hard(cand) - hard(placements)
    # ТОРШЕР ПОСАДКИ ВКЛЮЧАЮТ С ДИВАНА (разбор Codex 15.10): у торца вплотную коридор 46 см к нему не нужен — как к низким
    # предметам в `validate.check_passages`. Допускается РОВНО это новое нарушение и только при торшере ≤ seat_adjacent_cm
    # от следа дивана; любое другое новое hard (радиатор, коллизия, дверь) по-прежнему отменяет перенос
    allowed = set()
    if new_hard == {('UNREACHABLE', (moved.role,))} and fp.distance(footprint(sofa)) <= cfg.get('seat_adjacent_cm', 25.0):
        allowed, new_hard = new_hard, set()
    if new_hard:
        dbg('новые hard', new_hard)
        return placements, '', set()
    return cand, f'торшер у дальнего от входа торца дивана: +{gain:.0f} см от двери', allowed
