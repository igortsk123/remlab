"""Q8 свода №13: КОНТЕКСТ ПОЛОСЫ ЗА СПИНКОЙ ДИВАНА — единый расчёт для валидатора, скоринга и
ключа выбора (Codex 17.08: вместо трёх независимых логик — `sofa_dead_gap`, `empty_wall_behind_sofa`
и `residual_bands` — один класс зазора с доказательством).

Классы (пороги — данные `occupancy.dynamic.window_sofa.back_gap_policy`, provenance там же):
  hugged     — диван прижат к стене (< air_min): нормально у ГЛУХОЙ стены;
  air        — «воздух» 15–30 см: норма перед ОКНОМ (Livingetc 6–8", Ideal Home ~12");
  route      — ≥91 см чистой ширины И полоса связана с проходом комнаты (3 ft, Livingetc);
  functional — полосу занимает осмысленный блок зоны (консоль/скамья/чтение/столовая),
               перекрывающий проекцию дивана достаточно (не «случайное кашпо» — Codex);
  orphan     — всё остальное между air и route: бесхозная полоса, в которую не пройти
               и в которой ничего нет (замечание владельца: «диван далеко от окна»).

Радиатор считается ЛИЦЕВОЙ ГРАНЬЮ (Codex): зазор меряется до неё, а не до стены.
"""
from __future__ import annotations

from shapely.geometry import Polygon

from .geometry import base_role, footprint, opening_polygon, radiator_polygon, room_polygon
from .models import Placement, Room

FUNCTIONAL_ZONES = ('storage', 'dining', 'reading', 'quiet', 'bay_armchair')
# «Наполнение» полосы — предмет с ФУНКЦИЕЙ (хранение/посадка/стол), а не декор: одиночное
# кашпо, ваза или случайно заехавший стул полосу не легализуют (Codex 17.08). Роль засчитывается
# и без метки зоны — комод за спинкой функционален сам по себе (эталонные раскладки тестов).
FUNCTIONAL_ROLES = ('комод', 'стеллаж', 'витрина', 'шкаф', 'тв-тумба', 'стенка',
                    'банкетка', 'скамья', 'стол обеденный', 'консоль')
MIN_STRIP_COVER = 0.5      # блок обязан закрыть ≥50% проекции спинки, иначе это не «наполнение»


def _policy() -> dict:
    from .clearances import rules as _rules
    ws = (_rules().get('dynamic', {}) or {}).get('window_sofa', {}) or {}
    p = ws.get('back_gap_policy') or {}
    return {'air': list(p.get('air_cm') or [15, 30]),
            'route_min': float(p.get('route_min_cm') or 91),
            'window_overlap_min': float(p.get('window_overlap_min_cm') or 30)}


def _back_strip(room: Room, sofa: Placement, depth: float) -> Polygon:
    """Полоса ЗА спинкой на глубину depth в пределах проекции дивана."""
    import math
    r = math.radians(sofa.rot)
    bx, by = -math.sin(r), -math.cos(r)          # вектор «назад»
    x0, y0, x1, y1 = footprint(sofa).bounds
    if abs(by) > abs(bx):                        # спинка вдоль оси y
        y = (y0 - depth, y0) if by < 0 else (y1, y1 + depth)
        return Polygon([(x0, y[0]), (x1, y[0]), (x1, y[1]), (x0, y[1])])
    x = (x0 - depth, x0) if bx < 0 else (x1, x1 + depth)
    return Polygon([(x[0], y0), (x[0], y1), (x[1], y1), (x[1], y0)])


def back_wall_of(room: Room, sofa: Placement) -> str:
    from .geometry import facing_vector
    fx, fy = facing_vector(sofa.rot)
    return ("south" if fy > 0 else "north") if abs(fy) > abs(fx) else ("west" if fx > 0 else "east")


def strip_behind_depth(room: Room, sofa: Placement, extra: list[Placement] | None = None) -> float | None:
    """Глубина СВОБОДНОЙ полосы за спинкой дивана ПОСЛЕ вычета предметов `extra` (консоль).
    Нужна контракту консоли (R8, 19.08): паспорт обещает маршрут за консолью, и его надо
    мерить, а не декларировать. None — если диван не у стены или полосы нет."""
    if sofa.item is None:
        return None
    wall = back_wall_of(room, sofa)
    x0, y0, x1, y1 = footprint(sofa).bounds
    gap = {"south": y0, "north": room.depth_cm - y1,
           "west": x0, "east": room.width_cm - x1}[wall]
    if gap <= 0:
        return 0.0
    used = 0.0
    strip = _back_strip(room, sofa, gap)
    for p in (extra or []):
        fp = footprint(p)
        if not fp.intersects(strip):
            continue
        bx0, by0, bx1, by1 = fp.bounds
        # сколько полосы съел предмет: от кромки дивана до дальней кромки предмета
        used = max(used, {"south": y0 - by0, "north": by1 - y1,
                          "west": x0 - bx0, "east": bx1 - x1}[wall])
    return max(0.0, round(float(gap - used), 1))


def back_gap_context(room: Room, ps: list[Placement]) -> dict | None:
    """{gap_cm, class, wall, window_backed, radiator_gap_cm, filled_by} — или None (нет дивана)."""
    sofa = next((p for p in ps if base_role(p.role) == 'диван'), None)
    if sofa is None or sofa.item is None:
        return None
    pol = _policy()
    wall = back_wall_of(room, sofa)
    x0, y0, x1, y1 = footprint(sofa).bounds
    gap = {"south": y0, "north": room.depth_cm - y1,
           "west": x0, "east": room.width_cm - x1}[wall]
    gap = max(0.0, round(float(gap), 1))
    # окно за спинкой: перекрытие проёма проекцией дивана
    span = (x0, x1) if wall in ("south", "north") else (y0, y1)
    win = None
    for op in room.openings:
        if op.kind != 'window' or op.wall != wall:
            continue
        ov = min(span[1], op.offset_cm + op.width_cm) - max(span[0], op.offset_cm)
        if ov >= pol['window_overlap_min']:
            win = op
            break
    # радиатор на ТОЙ ЖЕ стене в проекции дивана — зазор до его лицевой грани (Codex)
    rad_gap = None
    strip_full = _back_strip(room, sofa, max(gap, 1.0))
    for rad in (room.radiators or []):
        rp = radiator_polygon(room, rad)
        if rp.intersects(strip_full):
            rad_gap = round(float(footprint(sofa).distance(rp)), 1)
            break
    eff = rad_gap if rad_gap is not None else gap
    # наполнение полосы: блок зоны, перекрывающий ≥50% проекции спинки
    filled_by = None
    if gap > 1:
        strip = _back_strip(room, sofa, gap)
        area = strip.area or 1.0
        for p in ps:
            if p is sofa or base_role(p.role) == 'ковёр':
                continue
            if getattr(p, 'tpl_id', '') not in FUNCTIONAL_ZONES \
                    and not str(getattr(p, 'tpl_variant', '')).startswith('console_behind_sofa') \
                    and base_role(p.role) not in FUNCTIONAL_ROLES:
                continue
            if footprint(p).intersection(strip).area / area >= MIN_STRIP_COVER:
                filled_by = p.role
                break
    # связность полосы с проходом комнаты (грубо: остаётся ≥route_min чистой ширины)
    lo, hi = pol['air']
    if filled_by is not None:
        klass = 'functional'
    elif eff >= pol['route_min']:
        klass = 'route'
    elif eff < lo:
        klass = 'hugged'
    elif eff <= hi:
        klass = 'air'
    else:
        klass = 'orphan'
    return {'gap_cm': gap, 'effective_gap_cm': eff, 'class': klass, 'wall': wall,
            'window_backed': bool(win), 'radiator_gap_cm': rad_gap, 'filled_by': filled_by,
            # Г-диван: «спинка» идёт по ДВУМ направлениям, а полоса считается по габаритному
            # прямоугольнику — для него класс остаётся диагностикой (жёсткое правило не
            # применяется; геометрию угла держат CORNER_SOFA_HUG/ADRIFT). 18.08: без этого
            # правило душило ВСЕ ступени с Г-диваном (set113: 57 м², ни один диван не встал)
            'corner_sofa': bool(getattr(sofa.item, 'corner', False))}


def is_orphan(room: Room, ps: list[Placement]) -> bool:
    ctx = back_gap_context(room, ps)
    return bool(ctx and ctx['class'] == 'orphan')
