"""Z3 (MASTER-zones-first): зоны-first примитивы — полезная площадь, выбор посадочной группы,
маршрутный резерв, лексикографическая оценка.

Порядок решений (своды владельца 07.08): геометрия → маршруты → focal point → группа как
система → media → хранение → декор. Здесь — фундамент уровня 1; блочное размещение зон
наращивается поверх этих примитивов.

ПРАВИЛО АТОМАРНОСТИ ШАБЛОНА (владелец, 11.08 — действует во всём движке):
    ШАБЛОН СТАВИТСЯ ЦЕЛИКОМ ИЛИ НЕ СТАВИТСЯ ВОВСЕ.
Выбрасывать предмет ИЗ шаблона запрещено. Не влез — берём ДРУГОЙ шаблон меньшего
состава (столовая 6→4→2, хранение 3→2→1, посадка диван+2 кресла→диван+кресло→соло).
Формулировка «предмет не поставился» недопустима: не ставится ШАБЛОН. Предметы
комплекта вне выбранного шаблона — ИЗБЫТОК КОМПЛЕКТА, не ошибка расстановки.
Пруф и примеры: services/planner-solver/rules/zones.json → template_atomicity.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from .geometry import room_polygon, static_blockers, swing_polygon
from .models import Room

_RULES = os.path.join(os.path.dirname(__file__), '..', 'rules', 'zones.json')


@lru_cache(maxsize=1)
def zone_rules() -> dict:
    return json.load(open(_RULES))


def route_reserve(room: Room) -> Polygon:
    """Резерв циркуляции ДО мебели (первоклассная зона, свод 07.08): полоса от каждой двери
    вглубь комнаты (ширина двери + маршрутная ширина), длиной до трети глубины комнаты.
    Не «весь маршрут» (его достроит связность-эрозия), а гарантированный вход."""
    zr = zone_rules()['zones']['circulation']
    w_route = float(zr['route_width_cm'][0])
    parts = []
    for op in room.openings:
        if op.kind != 'door':
            continue
        depth = min(max(room.depth_cm, room.width_cm) / 3, 250.0)
        lo = op.offset_cm - 20
        hi = op.offset_cm + op.width_cm + 20
        if op.wall == 'south':
            parts.append(box(lo, 0, hi, depth))
        elif op.wall == 'north':
            parts.append(box(lo, room.depth_cm - depth, hi, room.depth_cm))
        elif op.wall == 'west':
            parts.append(box(0, lo, depth, hi))
        else:
            parts.append(box(room.width_cm - depth, lo, room.width_cm, hi))
        parts.append(swing_polygon(room, op))
    _ = w_route  # ширина маршрута обеспечена запасом ±20 к ширине двери
    return unary_union(parts) if parts else Polygon()


def usable_polygon(room: Room) -> Polygon:
    """Полезная площадь размещения = контур − дуги дверей − радиаторы − входной резерв.

    Свод №2 (07.08): состав выбирается по USABLE area, не по room_area — две комнаты 16 м²
    с разной геометрией имеют разную вместимость."""
    poly = room_polygon(room)
    blockers = list(static_blockers(room)) + [route_reserve(room)]
    out = poly.difference(unary_union(blockers))
    return out if isinstance(out, Polygon) else max(out.geoms, key=lambda g: g.area)


def usable_m2(room: Room) -> float:
    return usable_polygon(room).area / 10_000


def pick_group(room: Room, roles_available: set[str] | dict, seats_target: int | None = None) -> dict:
    """Выбор посадочной группы: band по usable-площади → самая вместительная группа band'а,
    чьи обязательные роли доступны в каталоге сета. Футпринты — reference (правка владельца),
    физику проверит размещение.

    T3-фикс (10.08, корень пустых band50+): доступность считается по ЧИСЛУ ЭКЗЕМПЛЯРОВ,
    не по базовой роли — «two_sofas_…» при одном диване в сете выбиралась как max-seats,
    была нереализуема, и P0.1-фолбэк проваливался до «диван соло», срезая живые кресла
    (set112: 8 ролей в skipped на 57.5 м²). roles_available: set (счёт=1) или dict
    {база: сколько экземпляров}."""
    from collections import Counter
    zr = zone_rules()
    um2 = usable_m2(room)
    band = next(b for b in zr['inventory_prior']['bands_usable_m2'] if um2 <= b['max'])
    groups = {g['id']: g for g in zr['seating_groups']}
    # dict = точные счёты экземпляров (строгая проверка); set = только базовые роли,
    # количество неизвестно → «роль есть — качество решит подбор» (прежняя семантика)
    have = Counter(dict(roles_available)) if isinstance(roles_available, dict) \
        else Counter({r: 999 for r in roles_available})
    candidates = []
    for gid in band['groups']:
        g = groups[gid]
        req = list(g['roles']['required'])
        # Доступность — по ПОСАДОЧНЫМ ролям (set113: отсутствие столика в составе каскадно
        # рубило все группы до «только диван»); столик/декор группу не фильтруют.
        need = Counter(r.split(' ')[0] for r in req if r.split(' ')[0] in SEATING_ROLES)
        if all(have.get(role, 0) >= n for role, n in need.items()):
            candidates.append(g)
    if not candidates:
        candidates = [groups['sofa_armchair'] if have.get('диван', 0) > 0
                      else groups['armchair_pair']]
    if seats_target:
        fit = [g for g in candidates if g['seats'] >= seats_target]
        candidates = fit or candidates
    return max(candidates, key=lambda g: g['seats'])


# Посадочные роли, состав которых диктует ГРУППА (Z3); прочее (media/хранение/декор/обеденная)
# группой не фильтруется — их судьбу решают ярусы наполнения и сам beam
SEATING_ROLES = {'диван', 'кресло', 'пуф'}
# пристенные роли считаются за ПОЛОВИНУ футпринта (веб-свод 11.08: они не режут пол)
WALL_HUGGING_ROLES = {'стенка', 'тв-тумба', 'комод', 'стеллаж', 'витрина', 'шкаф', 'камин'}


def _base(role: str) -> str:
    return role.split(' ')[0] if role.split(' ')[-1].isdigit() else role




def _behind_reserved(room, block, keep) -> bool:
    """Диван стоит НЕ у стены и в банке есть обеденный стол — место за спинкой его."""
    seat = next((p for p in (block or []) if p.role.split(' ')[0] == 'диван'), None)
    if seat is None:
        return False
    if 'стол обеденный' in {p.role.split(' ')[0] for p in (block or [])}:
        return False
    if not any(i.role == 'стол обеденный' for i in keep):
        return False
    return _sofa_is_floating(room, seat)


def _sofa_is_floating(room, seat, gap_cm: float = 90.0) -> bool:
    """Диван «плавает», если за его спинкой больше 90 см до стены (проход + место зоны)."""
    import math as _m
    r = _m.radians(seat.rot)
    bx = seat.x - _m.sin(r) * ((seat.item.d_cm if seat.item else 95.0) / 2)
    by = seat.y - _m.cos(r) * ((seat.item.d_cm if seat.item else 95.0) / 2)
    back = {0: by, 180: room.depth_cm - by, 90: bx, 270: room.width_cm - bx}
    return back.get(int(seat.rot) % 360, 0.0) > gap_cm


def _behind_sofa_strip(room, block):
    """Полоса ЗА спинкой дивана — место второй зоны (столовой)."""
    from shapely.geometry import box as _box

    from .geometry import room_polygon as _rp
    seat = next((p for p in (block or []) if p.role.split(' ')[0] == 'диван'), None)
    if seat is None:
        return _box(0, 0, 0, 0)
    d = (seat.item.d_cm if seat.item else 95.0) / 2
    W, D = room.width_cm, room.depth_cm
    r = int(seat.rot) % 360
    strip = {0: _box(0, 0, W, max(seat.y - d, 0)),                # смотрит на север → тыл южнее
             180: _box(0, min(seat.y + d, D), W, D),
             90: _box(0, 0, max(seat.x - d, 0), D),
             270: _box(min(seat.x + d, W), 0, W, D)}.get(r)
    if strip is None:
        return _box(0, 0, 0, 0)
    return strip.intersection(_rp(room))


def _tv_wall_reserved(room, block, keep) -> bool:
    """Носитель ТВ есть в банке, но ещё не поставлен — стена под него занята «в кредит»."""
    placed = {p.role.split(' ')[0] for p in (block or [])}
    if 'тв-тумба' in placed or 'стенка' in placed:
        return False
    return any(i.role.split(' ')[0] in ('тв-тумба', 'стенка') for i in keep)


def _tv_wall_strip(room, block):
    """Полоса у стены, В КОТОРУЮ СМОТРИТ посадка: место медиа-зоны.

    Ширина полосы — 60 см (глубина тумбы с запасом на плинтус и провода).
    Нет посадки — полосы нет (резервировать нечего).
    """
    from shapely.geometry import box as _box
    from .geometry import room_polygon as _rp
    seat = next((p for p in (block or []) if p.role.split(' ')[0] == 'диван'), None)
    if seat is None:
        return _box(0, 0, 0, 0)
    r = int(seat.rot) % 360
    W, D, T = room.width_cm, room.depth_cm, 60.0
    strip = {0: _box(0, D - T, W, D),          # диван смотрит на север
             180: _box(0, 0, W, T),            # на юг
             90: _box(W - T, 0, W, D),         # на восток
             270: _box(0, 0, T, D)}.get(r)
    if strip is None:
        return _box(0, 0, 0, 0)
    return strip.intersection(_rp(room))


def solve_zoned(room: Room, items, **kw):
    """Z3, уровень 1 (MVP): сначала выбирается посадочная ГРУППА по полезной площади, затем
    beam решает предметы; посадочные роли вне группы не размещаются «лишь бы стоять», а честно
    уходят в skipped_optional. Старый solve() нетронут — A/B на перегоне.

    Возвращает (layouts, group_id)."""
    from collections import Counter

    from .beam import solve
    from .invariants import phantom_dimensions
    avail = {_base(i.role) for i in items}
    counts = Counter(_base(i.role) for i in items)
    group = pick_group(room, dict(counts))
    if os.environ.get('ZONES_DEBUG'):
        import sys as _sys
        print(f"ZDBG usable={usable_m2(room):.1f} avail={sorted(avail)} group={group['id']}",
              file=_sys.stderr, flush=True)
    allowed = {_base(r) for r in group['roles']['required']} | \
              {_base(r) for r in group['roles'].get('optional', [])}
    keep, dropped = [], []
    for it in items:
        # ПУФ ставится ТОЛЬКО внутри схемы посадки (владелец 12.08: зона из одного
        # предмета — не шаблон; отдельно стоящий пуф читался как случайный). (11.08:
        # перед/сбоку дивана по веб-своду). Раньше фильтр посадочных ролей выбрасывал
        # его до цепочки зон — отсюда «пуф пропущен» в 168 сценах.
        if (_base(it.role) in SEATING_ROLES and _base(it.role) not in allowed
                and _base(it.role) != 'пуф'):
            dropped.append(it.role)
        else:
            keep.append(it)
    # T3 (solver-speed, владелец 10.08): сперва пробуем ШАБЛОН разговорной зоны — блок
    # с запечённой геометрией (столик/кресла/ковёр привязаны к дивану). Удался — члены
    # блока уходят из перебора (fixed), beam доставляет остальное. Нет — прежний путь.
    from . import refine as _refine_mod
    _refine_mod.LOCKED = set()        # чистый старт на каждую сцену (детерминизм)
    block = None
    if os.environ.get('LAYOUT_TEMPLATES', '1') != '0':
        from .template import place_template
        block = place_template(room, group['id'], keep, usable_polygon(room))
    if os.environ.get('LAYOUT_ONLY_TEMPLATES', '1') != '0' and not block:
        # НЕТ ПОДХОДЯЩЕГО ШАБЛОНА (замечание владельца 11.08: «ковёр/столик не могут
        # теряться поодиночке — их нет как отдельных шаблонов»). Раньше сцена
        # проваливалась в поштучный перебор — он и терял ядро зоны. Теперь: пробуем
        # минимальную схему «диван соло», а если и она не встала — сцена честно
        # остаётся без раскладки и попадает в список «нужен новый шаблон».
        from .template import place_template as _pt
        block = _pt(room, 'compact_sectional', keep, usable_polygon(room))
        _min_used = bool(block)
        if not block:
            from .validate import validate as _val0
            lay0 = _val0(room, [])
            lay0.unplaced = []
            lay0.skipped_optional = sorted({it.role for it in items})
            if os.environ.get('ZONES_DEBUG'):
                import sys as _s0
                print('ZDBG НЕТ ШАБЛОНА под этот состав/комнату — сцена пуста',
                      file=_s0.stderr, flush=True)
            return [lay0], group['id'] + '+notpl'

    # ЕДИНАЯ ЦЕПОЧКА ЗОН для ОБОИХ путей (баг 12.08, замечания владельца по
    # set6-long/set7-bay/set5-trapezoid: при минимальной схеме цепочка зон не
    # выполнялась вовсе — комната оставалась без медиа и хранения, хотя место было)
    tpl_tag = ('+tpl-min' if locals().get('_min_used') else '+tpl') if block else ''
    if block:
        block_roles = {p.role for p in block}
        _refine_mod.LOCKED |= block_roles      # шаблон нерушим: доводка их не двигает
        keep = [it for it in keep if it.role not in block_roles]
        # столовая зона тоже блоком (владелец 10.08) — на free без разговорного блока;
        # стулья по band: ≤18 м² — 2, ≤30 — 4, дальше 6
        from shapely.ops import unary_union as _uu

        from .geometry import footprint as _fp
        from .template import place_dining
        # ЦЕПОЧКА ЗОН ПО ПРИОРИТЕТУ + БЮДЖЕТ ПЛОЩАДИ (решение владельца 11.08,
        # пруфы — zones.json `fill_policy`): порядок посадка → медиа → камин →
        # столовая → хранение → тихая зона → чтение; перед каждой зоной считаем
        # ПРОГНОЗ заполнения (пристенные ×0.5) и пропускаем зону, если она выводит
        # комнату выше верхней границы коридора 30–45% — следующая (меньшая) зона
        # ещё может влезть.
        from .template import (place_decor, place_fireplace, place_media,
                               place_media_fireplace, place_quiet,
                               place_reading, place_storage)
        _fp_pol = zone_rules().get('fill_policy', {})
        _lo, _hi = _fp_pol.get('target_pct', [30, 45])
        _half = set(WALL_HUGGING_ROLES)
        _room_m2 = room.width_cm * room.depth_cm / 10_000

        def _fill_pct(pls):
            a = 0.0
            for p in pls:
                if p.role == 'ковёр':
                    continue                      # подложка пол не занимает
                fa = _fp(p).area / 10_000
                a += fa * (0.5 if _base(p.role) in _half else 1.0)
            return a / _room_m2 * 100

        def _din(r, k, f, fixed=None):
            return place_dining(r, k, f, usable_m2(r), fixed=fixed)
        # ПОРЯДОК ФОКУСОВ (экзамен 11.08: камин избыточен в 72 сценах 40+ м² —
        # медиа-зона забирала стену первой). Канон: камин — фокус помещения; в
        # просторных комнатах он идёт ПЕРВЫМ, в малых приоритет у медиа.
        _fp_first = (room.width_cm * room.depth_cm > 32 * 10_000
                     and any(_base(i.role) == 'камин' for i in keep))
        # ОБА ФОКУСА НА ОДНОЙ СТЕНЕ (заявка владельца 11.08, веб подтвердил
        # side-by-side): сперва пробуем совмещённую зону «носитель + камин», и
        # только если не встала — раздельные зоны в порядке приоритета.
        _order = ((place_fireplace, '+fp'), (place_media, '+tv')) if _fp_first \
            else ((place_media, '+tv'), (place_fireplace, '+fp'))
        for placer, tag in ((place_media_fireplace, '+tvfp'), _order[0], _order[1],
                            (_din, '+din'), (place_storage, '+st'),
                            # НЕ БОЛЕЕ ДВУХ зон хранения на гостиную (владелец 12.08)
                            (place_storage, '+st2'),
                            (place_quiet, '+qz'), (place_reading, '+rd'),
                            (place_decor, '+dc')):
            occ2 = _uu([_fp(p) for p in block if p.role != 'ковёр'])
            _free_z = usable_polygon(room).difference(occ2)
            # ПРИОРИТЕТ МЕДИА НАД ХРАНЕНИЕМ (правило владельца 12.08, set7-bay:
            # стеллаж занял стену напротив дивана, а тумба осталась в банке).
            # Пока носитель ТВ не поставлен, стена напротив посадки за ним
            # зарезервирована — остальные зоны туда не лезут.
            if tag not in ('+tv', '+tvfp') and _tv_wall_reserved(room, block, keep):
                _free_z = _free_z.difference(_tv_wall_strip(room, block))
            # ЗА СПИНКОЙ ОТОДВИНУТОГО ДИВАНА — СТОЛОВАЯ (веб-канон RU: диван спинкой к
            # обеденной зоне — типовой приём зонирования; вторая зона гостиной чаще
            # всего именно столовая/барная — inmyroom.ru, 4happyhome.ru).
            # Пока столовая не поставлена, полосу за спинкой держим за ней.
            if tag not in ('+din',) and _behind_reserved(room, block, keep):
                _free_z = _free_z.difference(_behind_sofa_strip(room, block))
            extra = placer(room, keep, _free_z, fixed=block)
            if extra and _fill_pct(block + extra) > _hi:
                if os.environ.get('ZONES_DEBUG'):
                    import sys as _s
                    print(f'ZDBG зона {tag} пропущена: заполнение стало бы '
                          f'{_fill_pct(block + extra):.0f}% > {_hi}%',
                          file=_s.stderr, flush=True)
                extra = None                      # зона не влезает в бюджет — пробуем следующую
            if extra:
                roles2 = {p.role for p in extra}
                keep = [it for it in keep if it.role not in roles2]
                block = block + extra
                _refine_mod.LOCKED |= roles2
                tpl_tag += tag
    # ПРАВИЛО ВЛАДЕЛЬЦА 11.08: «если это не шаблон — ставить нельзя; не хватает
    # шаблонов — создаём новые». Раскладка собирается ТОЛЬКО из зонных блоков;
    # то, что не попало ни в один блок, честно уходит в пропущенное, а не
    # раскидывается поштучным перебором (он и портил геометрию зон).
    if block and os.environ.get('LAYOUT_ONLY_TEMPLATES', '1') != '0':
        from .validate import validate as _val
        lay = _val(room, block)
        # ИНВАРИАНТ АТОМАРНОСТИ: все члены применённых шаблонов обязаны стоять
        _missing_block = {p.role for p in block} - {p.role for p in lay.placements}
        assert not _missing_block, f'шаблон разобран: не хватает {_missing_block}'
        lay.unplaced = []
        lay.skipped_optional = sorted({it.role for it in keep} | set(dropped))
        outs = [lay]
        if os.environ.get('ZONES_DEBUG'):
            import sys as _s
            print(f'ZDBG только-шаблоны: поставлено {len(block)} из блоков, '
                  f'пропущено {len(lay.skipped_optional)}', file=_s.stderr, flush=True)
        return outs, group['id'] + tpl_tag

    # H3 (08.08): большие комнаты с богатым составом — ДВУХПРОХОДНОЕ размещение:
    # проход 1 — ядро (группа+носитель ТВ+столик+ковёр), проход 2 — достройка (обеденная,
    # камин, хранение, спутники) на зафиксированном ядре. Один проход beam на 19 предметах
    # в 57 м² рушился каскадом (то диван без стенки, то стенка без дивана).
    room_m2 = room.width_cm * room.depth_cm / 10_000
    if room_m2 >= 26 and len(keep) + (len(block) if block else 0) > 8:
        has_stand = any(i.role == 'тв-тумба' for i in keep)
        core_bases = {'диван', 'кресло', 'тв-тумба', 'столик', 'ковёр'}
        core, rest = [], []
        for it in keep:
            b = _base(it.role)
            if b in core_bases or (b == 'стенка' and not has_stand):
                core.append(it)
            else:
                rest.append(it)
        outs1 = solve(room, core, fixed=block, **kw)
        if outs1 and rest:
            base_ps = list(outs1[0].placements)
            # предметы ядра, не вставшие в проходе 1 (ковёр и т.п.), едут во второй проход —
            # иначе терялись в шве двухпрохода без следа (вердикт 08.08: «ковра нет»)
            lost1 = set(outs1[0].unplaced) | set(outs1[0].skipped_optional)
            rest = rest + [it for it in core if it.role in lost1]
            outs = solve(room, rest, fixed=base_ps, **kw)
            if outs:
                carry = set(outs1[0].skipped_optional)
                for lay in outs:
                    lay.skipped_optional = sorted(set(lay.skipped_optional) | carry)
            else:
                outs = outs1
        else:
            outs = outs1 or solve(room, keep, fixed=block, **kw)
    else:
        outs = solve(room, keep, fixed=block, **kw)
    # ОБОГАЩЕНИЕ ДО НИЖНЕЙ ГРАНИЦЫ (правило владельца 11.08): комната ниже коридора
    # выглядит пустой (замер: 15–25% при цели 30%). Если после всех зон заполнение
    # < нижней границы, ВТОРОЙ проход по зонам с остатком предметов — вдруг что-то
    # не встало из-за порядка, а не из-за места.
    if block and outs and keep:
        from .models import Severity as _Sev
        from .validate import validate
        _cur = _fill_pct(outs[0].placements)
        if _cur < _lo:
            _occ3 = _uu([_fp(p) for p in outs[0].placements if p.role != 'ковёр'])
            _free3 = usable_polygon(room).difference(_occ3)
            for placer2, tag2 in ((place_storage, '+st2'), (place_decor, '+dc2'),
                                  (place_reading, '+rd2')):
                got = placer2(room, keep, _free3, fixed=list(outs[0].placements))
                if not got:
                    continue
                trial = validate(room, list(outs[0].placements) + got)
                if any(v.severity is _Sev.HARD for v in trial.violations):
                    continue
                roles3 = {p.role for p in got}
                keep = [it for it in keep if it.role not in roles3]
                outs[0].placements = list(outs[0].placements) + got
                outs[0].violations = trial.violations
                _refine_mod.LOCKED |= roles3
                tpl_tag += tag2
                _occ3 = _uu([_fp(p) for p in outs[0].placements if p.role != 'ковёр'])
                _free3 = usable_polygon(room).difference(_occ3)
                if _fill_pct(outs[0].placements) >= _lo:
                    break
            if os.environ.get('ZONES_DEBUG'):
                import sys as _s
                print(f'ZDBG обогащение: {_cur:.0f}% → {_fill_pct(outs[0].placements):.0f}% '
                      f'(цель ≥{_lo}%)', file=_s.stderr, flush=True)

    # P0.1 (рефери 08.08, set59/113): потерян REQUIRED-слот группы → НЕ удерживать остатки
    # старой группы, а выбрать лучшую валидную effective-группу и пере-решить один раз
    # только её составом («не удерживать предмет потому, что он помещается»).
    if outs:
        placed_roles = {p.role for p in outs[0].placements}
        if os.environ.get('ZONES_DEBUG'):
            import sys as _s
            print(f"ZDBG после beam: block={'да' if block else 'нет'} "
                  f"placed={sorted(placed_roles)} unplaced={outs[0].unplaced}",
                  file=_s.stderr, flush=True)
        req = set(group['roles']['required'])
        if not (req <= placed_roles):
            groups = {g['id']: g for g in zone_rules()['seating_groups']}
            # Матчинг фолбэка — по ПОСАДОЧНЫМ ролям: отсутствие столика в СОСТАВЕ (дефицит
            # каталога) не повод резать живые кресла до «только диван» (set113: fallback
            # требовал столик, которого в сете нет, и убивал оба размещённых кресла)
            def _seats_of(g):
                return {r for r in g['roles']['required'] if _base(r) in SEATING_ROLES}
            req_seats = _seats_of(group)
            fallback = None
            for gid, g in sorted(groups.items(), key=lambda kv: -kv[1]['seats']):
                r2 = _seats_of(g)
                if r2 and r2 < req_seats and r2 <= placed_roles:
                    fallback = g
                    break
            if fallback is not None:
                allowed2 = set(fallback['roles']['required']) | set(fallback['roles'].get('optional', []))
                keep2, dropped2 = [], list(dropped)
                for it in keep:
                    if _base(it.role) in SEATING_ROLES and it.role not in allowed2 \
                            and _base(it.role) not in allowed2:
                        dropped2.append(it.role)
                    else:
                        keep2.append(it)
                if len(keep2) < len(keep):
                    outs2 = solve(room, keep2, **kw)
                    if outs2 and set(fallback['roles']['required']) <= \
                            {p.role for p in outs2[0].placements}:
                        for lay in outs2:
                            lay.skipped_optional = sorted(set(lay.skipped_optional) | set(dropped2))
                        return outs2, fallback['id']
                else:
                    # состав уже совпадает с fallback-группой — честно меняем ТОЛЬКО метку
                    # (сет не должен заявлять группу, которой физически нет)
                    for lay in outs:
                        lay.skipped_optional = sorted(set(lay.skipped_optional) | set(dropped))
                    return outs, fallback['id']
    if os.environ.get('ZONES_DEBUG'):
        import sys as _s
        print(f"ZDBG итог: block={'да' if block else 'нет'} tag={tpl_tag} "
              f"placed={sorted(p.role for p in outs[0].placements)} "
              f"unplaced={outs[0].unplaced}", file=_s.stderr, flush=True)
    for lay in outs:
        lay.skipped_optional = sorted(set(lay.skipped_optional) | set(dropped))
    # ЗАПРЕТ ФАНТОМНЫХ ГАБАРИТОВ (ADR template-integrity): габарит поставленного
    # предмета обязан совпадать с SKU из сета. Солвер не имеет права «ужать» товар,
    # чтобы он влез — это мебель, которой нет в каталоге, и неверная смета.
    _src = {}
    for it in items:
        _src.setdefault(it.role, it)
    for lay in outs:
        _bad = phantom_dimensions(lay.placements, _src)
        if _bad:
            raise AssertionError('ФАНТОМНЫЕ ГАБАРИТЫ (габарит ≠ SKU): ' + '; '.join(_bad))
    return outs, group['id'] + tpl_tag


# --- Лексикографическая оценка (правка владельца 07.08): эстетика не компенсирует проход ---
LEVELS = ('hard_feasibility', 'circulation', 'functional_relationships', 'zone_quality',
          'aesthetics')
_TERM_LEVEL = {
    # circulation: проходы, связность, щели-непроходимости
    'sliver_gap': 'circulation', 'sofa_dead_gap': 'circulation',
    'free_space_fragmentation': 'circulation', 'soft_rule_main_path_tight': 'circulation',
    'soft_rule_zone_buffer': 'circulation',
    # functional: связи предметов
    'sofa_tv_dist': 'functional_relationships', 'sofa_table': 'functional_relationships',
    'sofa_faces_tv': 'functional_relationships', 'tv_faces_sofa': 'functional_relationships',
    'armchair_faces_tv': 'functional_relationships',
    'armchair_zone_radius': 'functional_relationships',
    'armchair_not_at_tv': 'functional_relationships',
    'dining_off_wall': 'functional_relationships', 'dining_by_window': 'functional_relationships',
    # zone quality: наполнение/фокус/за спинкой
    'floor_overfill': 'zone_quality', 'empty_wall_behind_sofa': 'zone_quality',
    'corner_sofa_hug': 'zone_quality', 'soft_rule_corner_sofa_adrift': 'zone_quality',
    'soft_rule_tall_on_tv_wall': 'zone_quality', 'soft_rule_tv_on_window_wall': 'zone_quality',
    'soft_rule_fireplace_on_tv_wall': 'zone_quality',
    # aesthetics: выравнивание/центрирование
    'wall_hug': 'aesthetics', 'pair_symmetry': 'aesthetics', 'table_centering': 'zone_quality', 'functional_coverage': 'zone_quality', 'soft_rule_pair_pattern': 'zone_quality', 'axis_alignment': 'aesthetics', 'wall_centering': 'aesthetics',
}


def lexo_key(hard_count: int, unplaced_required: int, terms: dict) -> tuple:
    """Кортеж для сравнения вариантов: (hard, circulation, functional, zone, aesthetics).
    Меньше — лучше. Неизвестный терм консервативно падает в zone_quality."""
    lv = {k: 0.0 for k in LEVELS}
    lv['hard_feasibility'] = float(hard_count * 100 + unplaced_required * 40)
    for name, val in terms.items():
        lv[_TERM_LEVEL.get(name, 'zone_quality')] += float(val)
    return tuple(round(lv[k], 3) for k in LEVELS)
