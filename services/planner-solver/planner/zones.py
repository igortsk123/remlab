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

import re

import json
import os
from collections import Counter
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
        # C-1 свода №11 (Кодекс §11): route_width_cm РЕАЛЬНО потребляется — полоса
        # входа не уже маршрутной ширины из данных (для двери 90 идентично прежним ±20)
        _pad = max(20.0, (w_route - op.width_cm) / 2)
        lo = op.offset_cm - _pad
        hi = op.offset_cm + op.width_cm + _pad
        if op.wall == 'south':
            parts.append(box(lo, 0, hi, depth))
        elif op.wall == 'north':
            parts.append(box(lo, room.depth_cm - depth, hi, room.depth_cm))
        elif op.wall == 'west':
            parts.append(box(0, lo, depth, hi))
        else:
            parts.append(box(room.width_cm - depth, lo, room.width_cm, hi))
        parts.append(swing_polygon(room, op))
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


def pick_ladder(room: Room, roles_available: set[str] | dict,
                skip: int = 0, diag: list | None = None) -> list[dict]:
    """ЛЕСТНИЦА шаблонов посадки (план seating-template-ladder, владелец 13.08):
    упорядоченный список групп «от самой вместительной к соло», доступных по
    инвентарю сета. Спуск по лестнице = смена ШАБЛОНА (не вычитание предметов).
    Порядок — данные (`zones.json → seating_ladder`), не код.

    V4-B1 (свод №10, Q37): band-список — НЕ жёсткий whitelist, а ВЕРХНИЙ КАП
    масштаба + предпочтение. Прежде `gid not in band['groups']` выкидывал
    sofa_armchair в комнатах >18 м² целиком (band'ы max25/30/999 его не содержат),
    и солвер при одном кресле падал сразу к sofa_pouf — 149/269 сцен, у 137 кресло
    оставалось в банке (аудит советника, подтверждено скаутом 1-в-1). Теперь:
    ступени БОГАЧЕ богатейшей band-ступени по-прежнему недоступны (масштаб к
    площади), но ВНИЗ лестница закрыта полностью — sofa_armchair пробуется ДО
    sofa_pouf в любой комнате. Победу решают геометрия и медиа-минимум, не фильтр.

    diag (V4-B2): если передан список — на каждую ступень глобальной лестницы
    пишется {id, band_pref, inventory_complete, eligible} для seating_search."""
    from collections import Counter
    zr = zone_rules()
    um2 = usable_m2(room)
    band = next(b for b in zr['inventory_prior']['bands_usable_m2'] if um2 <= b['max'])
    groups = {g['id']: g for g in zr['seating_groups']}
    have = Counter(dict(roles_available)) if isinstance(roles_available, dict) \
        else Counter({r: 999 for r in roles_available})
    ladder = [g for g in zr.get('seating_ladder', {}).get('ladder', []) if g in groups
              and groups[g].get('status') != 'shadow_alternative']   # Q3: shadow — вне production-лестницы
    band_set = set(band['groups'])
    _first = next((i for i, g in enumerate(ladder) if g in band_set), 0)
    out = []
    for i, gid in enumerate(ladder):
        cap_ok = gid in band_set or i >= _first     # кап сверху, замыкание вниз
        g = groups[gid]
        need = Counter(r.split(' ')[0] for r in g['roles']['required']
                       if r.split(' ')[0] in SEATING_ROLES)
        inv_ok = all(have.get(role, 0) >= n for role, n in need.items())
        if diag is not None:
            diag.append({'id': gid, 'band_pref': gid in band_set,
                         'inventory_complete': inv_ok,
                         'eligible': cap_ok and inv_ok})
        if cap_ok and inv_ok:
            out.append(g)
    if skip:
        # dining_sacrifice: спуск на N ступеней ниже — жертва мест ради второй зоны
        out = out[skip:] if skip < len(out) else out[-1:]
    return out or [groups['sofa_solo' if have.get('диван', 0) > 0 else 'armchair_pair']]


def _secondary_scope_roles(room: Room) -> set:
    """Q1 свода №13: роли, не участвующие в лестнице ГЛАВНОЙ посадки (данные
    zone_priority.secondary_scope_roles + _by_mode[room_mode]): кресло 3/4 всегда
    (второй pod/quiet), «диван 2» — в small/transitional (двухдиванные ступени там
    вытесняют столовую)."""
    zp = zone_rules().get('zone_priority', {}) or {}
    sec = set(zp.get('secondary_scope_roles', []))
    try:
        from .room_map import room_mode as _rm
        sec |= set((zp.get('secondary_scope_roles_by_mode') or {}).get(_rm(room), []))
    except Exception:
        pass
    return sec


def scenario_needs(**overrides) -> dict:
    """P0 свода №12: статусы обязательных зон — ВХОД сценария (rules/zones.json →
    zone_priority.scenario_needs), не константа. Возвращает {'media': 'required'|
    'preferred'|'off', 'dining': ...}: дефолт из данных, override из kw солвера
    (media_need=/dining_need=). Неизвестное значение → дефолт (не тихий off)."""
    zp = zone_rules().get('zone_priority', {})
    sn = zp.get('scenario_needs', {})
    out = {}
    for zone in ('media', 'dining'):
        spec = sn.get(f'{zone}_need', {})
        allowed = set(spec.get('values', ['required', 'preferred', 'off']))
        val = overrides.get(f'{zone}_need') or spec.get('default') \
            or (zp.get('status') or {}).get(zone, 'preferred')
        out[zone] = val if val in allowed else spec.get('default', 'preferred')
    return out


def solve_zoned(room: Room, items, **kw):
    """P1 свода №12: финальный медиа-контракт поверх _solve_zoned_impl — MEDIA_MISSING
    hard на ГОТОВОМ плане (внутри validate() правило не живёт: било бы промежуточные
    блоки посадки до шага медиа)."""
    outs, gid = _solve_zoned_impl(room, items, **kw)
    from . import validate as _valF
    for _l in outs or []:
        _miss = _valF.check_media_required_final(_l.placements)
        if _miss:
            _l.violations = list(_l.violations) + _miss
            if isinstance(getattr(_l, 'meta', None), dict):
                _l.meta['infeasible_reason'] = {
                    'code': 'MEDIA_MISSING', 'zone': 'media',
                    'why': 'media_need=required, носитель в банке, ни одна ступень/вейвер/'
                           'альтернативная позиция не дала носителя (владелец №177)'}
    return outs, gid


def _solve_zoned_impl(room: Room, items, **kw):
    """Обёртка dining_sacrifice (правило владельца 14.08, разбор Плана №19):
    столовая не встала, стол в банке → пересбор с посадкой на СТУПЕНЬ НИЖЕ;
    принимаем, только если столовая встала, медиа сохранена и качество не хуже
    (гейт not_worse). Остаток после столовой — зонам хранения (порядок цепочки
    прежний). Конфиг — rules/zones.json → dining_sacrifice."""
    outs, gid = _solve_zoned_core(room, items, **kw)
    cfg = zone_rules().get('dining_sacrifice', {})
    _needs = scenario_needs(**{k: v for k, v in kw.items() if k in ('media_need', 'dining_need')})
    for _l in outs or []:                       # P0 свода №12: вход сценария в артефакте (все пути)
        if isinstance(getattr(_l, 'meta', None), dict):
            _l.meta.setdefault('scenario_needs', dict(_needs))
    if not cfg.get('enabled', False) or '+din' in gid or _needs['dining'] == 'off':
        return outs, gid
    if not outs or not outs[0].placements:
        return outs, gid
    bank = set(outs[0].skipped_optional or [])
    if 'стол обеденный' not in bank:
        return outs, gid
    from .quality import not_worse as _nw
    from .quality import scene_quality as _sq
    base_q = _sq(room, outs[0].placements)
    _media0 = any(p.role.split(' ')[0] in ('тв-тумба', 'стенка', 'камин')
                  for p in outs[0].placements)
    # Кодекс (разбор dining 220→218, set18-base): max_steps_down — число РЕАЛЬНО
    # достижимых деградаций посадки, а не инвентарных строк лестницы: недостижимые
    # (inventory-complete, hard_valid=0) ступени поглощали шаги, и до compact_sectional,
    # где столовая встаёт, цикл не доходил. Считаем шаг только когда со skip лестница
    # приняла ДРУГУЮ реально вставшую ступень (по gid); skip идёт по всем строкам.
    _max_down = int(cfg.get('max_steps_down', 2))
    _real_steps = 0
    _seen_gids = {(gid or '').split('+')[0]}
    _ladder_len = len(pick_ladder(room, dict(Counter(
        i.role.split(' ')[0] for i in items if i.role not in _secondary_scope_roles(room)))))
    for _skip in range(1, max(_max_down, _ladder_len) + 1):
        if _real_steps >= _max_down:
            break
        outs2, gid2 = _solve_zoned_core(room, items, _ladder_skip=_skip, **kw)
        _g2 = (gid2 or '').split('+')[0]
        # LEVEL A (владелец: «диван из банка стоит всегда») старше столовой: жертва ступени
        # не имеет права спуститься до БЕЗДИВАННОЙ группы, пока диван в банке (регресс после
        # перевода max_steps_down на реальные деградации: sacr6 → armchair_pair, set47/39)
        if outs2 and outs2[0].placements and any(i.role == 'диван' for i in items) \
                and not any(p.role.split(' ')[0] == 'диван' for p in outs2[0].placements):
            continue
        if outs2 and outs2[0].placements and _g2 and _g2 not in _seen_gids and '+notpl' not in (gid2 or ''):
            _seen_gids.add(_g2)
            _real_steps += 1          # реально вставшая новая ступень = 1 шаг вниз
        if not outs2 or not outs2[0].placements or '+din' not in gid2:
            continue
        if _media0 and not any(p.role.split(' ')[0] in ('тв-тумба', 'стенка', 'камин')
                               for p in outs2[0].placements):
            continue
        if not _nw(base_q, _sq(room, outs2[0].placements)):
            continue
        if os.environ.get('ZONES_DEBUG'):
            import sys as _sd
            print(f'ZDBG dining_sacrifice: ступень −{_skip} — столовая встала, '
                  f'качество не хуже (принято)', file=_sd.stderr, flush=True)
        if isinstance(outs2[0].meta.get('dining'), dict):    # пакет B: объяснимость
            outs2[0].meta['dining']['sacrifice_step'] = _skip
            outs2[0].meta['dining']['why_selected'] = 'preferred_coverage+sacrifice'
        return outs2, gid2 + f'+sacr{_skip}'
    return outs, gid


# Посадочные роли, состав которых диктует ГРУППА (Z3); прочее (media/хранение/декор/обеденная)
# группой не фильтруется — их судьбу решают ярусы наполнения и сам beam
SEATING_ROLES = {'диван', 'кресло', 'пуф'}
# пристенные роли считаются за ПОЛОВИНУ футпринта (веб-свод 11.08: они не режут пол)
WALL_HUGGING_ROLES = {'стенка', 'тв-тумба', 'комод', 'стеллаж', 'витрина', 'шкаф', 'камин'}


def _base(role: str) -> str:
    return role.split(' ')[0] if role.split(' ')[-1].isdigit() else role




def _residual_R(room, seat) -> float:
    """Остаток за спинкой дивана до стены (машина R, large-room свод §5)."""
    import math as _m
    r = _m.radians(seat.rot)
    d2 = (seat.item.d_cm if seat.item else 95.0) / 2
    bx = seat.x - _m.sin(r) * d2
    by = seat.y - _m.cos(r) * d2
    return {0: by, 180: room.depth_cm - by,
            90: bx, 270: room.width_cm - bx}.get(int(seat.rot) % 360, 0.0)


def _behind_decision(room, seat) -> str:
    """Решение по остатку R — ЕДИНАЯ таблица residual_bands по режиму формы
    (elongated — свод №4, иначе large-набор; конфликт-сверка: двойников нет)."""
    from .invariants import TEMPLATES
    from .room_map import room_shape
    R = _residual_R(room, seat)
    bands = TEMPLATES.get('residual_bands', {})
    key = 'elongated' if room_shape(room) in ('elongated', 'strongly') else 'large'
    for band in bands.get(key, []):
        if R <= float(band['max']):
            return band['decision']
    return 'nothing'



def _actual_step(block, requested, zr) -> dict:
    """Фактическая ступень по СОСТАВУ поставленного блока (тег gid обязан отражать
    фактику — рефери P0.1; лестница могла принять позицию с законной схемой меньшего
    состава, и запрошенная ступень в теге вводила в заблуждение)."""
    from collections import Counter
    _seatish = ('диван', 'кресло', 'пуф', 'торшер')
    placed = Counter(p.role.split(' ')[0] for p in block
                     if p.role.split(' ')[0] in _seatish)
    best = requested
    for g in sorted(zr['seating_groups'], key=lambda g: -float(g.get('seats', 0))):
        req = Counter(r.split(' ')[0] for r in g['roles'].get('required', [])
                      if r.split(' ')[0] in _seatish)
        opt = Counter(r.split(' ')[0] for r in g['roles'].get('optional', [])
                      if r.split(' ')[0] in _seatish)
        # ЭКЗЕМПЛЯРЫ, не множества: «диван 2» ≠ второй экземпляр «дивана» в base-виде
        # ронял матч в двухдиванные группы при одном диване (тест P0.1)
        if all(placed.get(k, 0) >= n for k, n in req.items()) and                 all(placed.get(k, 0) <= req.get(k, 0) + opt.get(k, 0)
                    for k in placed):
            return g
    return best


def _behind_reserved(room, block, keep) -> bool:
    """Полоса за спинкой резервируется под столовую ТОЛЬКО когда машина R говорит
    dining_mandatory (заменяет бинарный запрет floating-без-столовой 13.08)."""
    seat = next((p for p in (block or []) if p.role.split(' ')[0] == 'диван'), None)
    if seat is None:
        return False
    if 'стол обеденный' in {p.role.split(' ')[0] for p in (block or [])}:
        return False
    if not any(i.role == 'стол обеденный' for i in keep):
        return False
    return _behind_decision(room, seat) in ('dining_mandatory', 'second_zone_mandatory')


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


def _fp0(p):
    from .geometry import footprint as _f
    return _f(p)


def _uu0(polys):
    from shapely.ops import unary_union as _u
    return _u(polys)


def _media_lookahead(room, keep, blk, occ0, m0, pm, needs, usable_poly):
    """P1 свода №12: выбор позиции носителя с пробой столовой на остатке.
    Возвращает вариант медиа (list[Placement]) — m0, если lookahead неприменим/не помог.
    Применяется только когда: dining_need != off, стол в банке, m0 существует,
    lookahead включён в данных. Пробуем до K вариантов носителя (один класс оси —
    place_media(top=K) отдаёт hard-чистые в лексо-порядке); первый, при котором
    place_dining на остатке даёт стол, — победитель; иначе m0."""
    cfg = zone_rules().get('media_lookahead', {})
    if not cfg.get('enabled', True) or m0 is None:
        return m0
    if needs.get('dining') == 'off':
        return m0
    if not any(i.role == 'стол обеденный' for i in keep):
        return m0
    from .template import place_dining as _pd
    from .geometry import footprint as _fpL
    from shapely.ops import unary_union as _uuL
    K = int(cfg.get('top_k', 3))
    try:
        opts = pm(room, keep, usable_poly.difference(occ0), fixed=blk, top=K)
    except TypeError:
        return m0
    opts = opts if (opts and isinstance(opts[0], list)) else ([opts] if opts else [])
    if len(opts) <= 1:
        return m0
    um2 = usable_m2(room)
    for cand in opts:
        occ1 = _uuL([_fpL(p) for p in list(blk) + list(cand)
                     if p.role.split(' ')[0] != 'ковёр'])
        keep1 = [i for i in keep if i.role not in {p.role for p in cand}]
        try:
            din = _pd(room, keep1, usable_poly.difference(occ1), um2,
                      fixed=list(blk) + list(cand))
        except Exception:
            din = None
        if din:
            if os.environ.get('ZONES_DEBUG') and cand is not opts[0]:
                import sys as _sl
                print('ZDBG media_lookahead: носитель с меньшей осью съедал столовую — '
                      'взят вариант, при котором столовая встаёт', file=_sl.stderr, flush=True)
            _axis_diag_update(cand, blk, chosen_rank=opts.index(cand), tried=len(opts))
            return cand
    _axis_diag_update(m0, blk, chosen_rank=0, tried=len(opts))
    return m0


def _axis_diag_update(media, blk, *, chosen_rank: int, tried: int) -> None:
    """P1: offset_cm в диагностике оси — от ФАКТИЧЕСКИ выбранного носителя (при top>1
    place_media его не пишет) + след lookahead (какой по рангу вариант взят)."""
    from . import template as _tm
    d = getattr(_tm, 'LAST_MEDIA_AXIS', None)
    if not isinstance(d, dict) or not media:
        return
    try:
        from .quality import focus_offset_cm as _foc
        seat = next((p for p in blk if p.role.split(' ')[0] == 'диван'), None)
        car = next((p for p in media if p.role.split(' ')[0] in ('тв-тумба', 'стенка')), None)
        if seat is not None and car is not None:
            off = _foc([seat, car])
            if off is not None:
                d['offset_cm'] = round(off, 1)
        d['lookahead'] = {'tried': tried, 'chosen_rank': chosen_rank}
    except Exception:
        pass


def _solve_zoned_core(room: Room, items, _ladder_skip: int = 0, **kw):
    """Z3, уровень 1 (MVP): сначала выбирается посадочная ГРУППА по полезной площади, затем
    beam решает предметы; посадочные роли вне группы не размещаются «лишь бы стоять», а честно
    уходят в skipped_optional. Старый solve() нетронут — A/B на перегоне.

    Возвращает (layouts, group_id)."""
    _WR_DIAG: dict = {}      # Q10-0: диагноз оконного уголка (пробовали/нечего/не влезло)
    from collections import Counter

    from .beam import solve
    from .invariants import phantom_dimensions
    from .quality import not_worse as _not_worse
    from .quality import scene_quality as _quality
    from . import template as _tplmod
    _tplmod.LAST_DINING_DIAG = None      # пакет B: свежий диагноз dining на каждый прогон
    _tplmod.LAST_MIRROR_STATS = None     # V3-H: счётчики зеркал — per solve
    _tplmod.LAST_SEATING_SEARCH = None   # V4-B2: трейс лестницы — per solve
    _needs_eff = scenario_needs(**{k: v for k, v in kw.items()
                                    if k in ('media_need', 'dining_need')})  # P0 свода №12
    from . import validate as _valmodN
    _valmodN.MEDIA_NEED[0] = _needs_eff['media']
    _valmodN.MEDIA_BANK_HAS_CARRIER[0] = any(
        i.role.split(' ')[0] in ('тв-тумба', 'стенка') for i in items)   # P1 свода №12
    _tplmod.LAST_AXIS_DIAG = None        # V4-D: контракт осей — per solve
    _tplmod.LAST_MEDIA_AXIS = None
    from . import validate as _valmod
    _valmod.SCREEN_WINDOW_WAIVED[0] = False   # C-8: вейвер экрана — per solve, не env
    avail = {_base(i.role) for i in items}
    # Q1 свода №13: роли secondary-scope (кресло 3/4 — второй pod/quiet, данные
    # zone_priority.secondary_scope_roles) НЕ считаются в лестнице главной посадки —
    # иначе банк с 4 креслами уводит лестницу в sofa_4armchairs, хотя композитор
    # предназначал пару второй зоне (Кодекс, ревью v7 §3)
    _sec = _secondary_scope_roles(room)
    counts = Counter(_base(i.role) for i in items if i.role not in _sec)
    group = pick_group(room, dict(counts))
    if os.environ.get('ZONES_DEBUG'):
        import sys as _sys
        print(f"ZDBG usable={usable_m2(room):.1f} avail={sorted(avail)} group={group['id']}",
              file=_sys.stderr, flush=True)
    # E1 (M-E, свод №5): состав фильтруем по ОБЪЕДИНЕНИЮ ролей всех ступеней
    # лестницы, а не по одной группе pick_group — иначе кресла выбрасывались до
    # спуска, и ступень armchair_pair («без дивана») была недостижима: диван,
    # который никуда не встал, оставлял сцену пустой при живых креслах
    _steps_all = [group] + pick_ladder(room, dict(counts))
    allowed = {_base(r) for g in _steps_all
               for r in list(g['roles']['required']) +
               list(g['roles'].get('optional', []))}
    # Роли ВТОРИЧНЫХ шаблонов (нук, кресло-в-эркере) — из паспортов, не из лестницы:
    # кресло, которое не берёт ни одна ступень band'а, легально живёт нуком/эркером
    # (bay-nook-templates 14.08; раньше отсев состава делал эти шаблоны недостижимыми)
    from .invariants import TEMPLATES as _TT2
    for _zid in ('reading', 'bay_armchair'):
        _z2 = _TT2.get('zones', {}).get(_zid, {})
        allowed |= {_base(r) for r in list(_z2.get('required', [])) +
                    list(_z2.get('optional', []))}
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
        from .template import place_media, place_template
        # ЛЕСТНИЦА ШАБЛОНОВ (план seating-template-ladder, владелец 13.08): пробуем
        # группы от вместительной к соло; каждый шаблон ставится ЦЕЛИКОМ, не встал —
        # СЛЕДУЮЩАЯ ступень (смена шаблона, а не выкидывание предметов из большого).
        if os.environ.get('LAYOUT_LADDER', '1') != '0':
            # СПУСК С ПРОВЕРКОЙ МИНИМУМА (владелец 13.08, план №20: «медиа +
            # коммуникативная — минимум везде»). Ступень, которая встала, но не
            # оставила места носителю ТВ, НЕ принимается сразу: пробуем следующую;
            # если ни одна не дала минимум — берём первую вставшую (fallback).
            _has_bearer0 = any(_base(i.role) in ('тв-тумба', 'стенка') for i in keep)
            _fb_block = _fb_group = None
            # V4-B2 (свод №10): seating_search — трейс лестницы (аналог dining_search)
            _seat_diag: list = []
            _ladder_steps = pick_ladder(room, dict(counts), skip=_ladder_skip,
                                        diag=_seat_diag)
            # P2 свода №12: ГИПОТЕЗА посадки от beam-драйвера — лестница ограничена
            # её ступенью, блок берётся готовым (медиа-минимум/цепочка — как обычно)
            _hyp = kw.get('_hyp')
            if _hyp:
                _ladder_steps = [g for g in _ladder_steps if g['id'] == _hyp['group']] \
                    or [next((g for g in zone_rules().get('seating_groups', [])
                              if g['id'] == _hyp['group']), None)]
                _ladder_steps = [g for g in _ladder_steps if g]
            _sseek = {d['id']: dict(d) for d in _seat_diag}
            _tplmod.LAST_SEATING_SEARCH = _sseek

            def _media_comfort(blk, m0) -> str:
                """C-3 свода №11 (Кодекс Q-C): класс дистанции медиа-минимума —
                'comfort' (в вилке до min(soft_hi,hi)) или 'far'. Границы и замер —
                КАНОН (tv.distance_range + фронт-зазор, как validate)."""
                from .geometry import base_role as _brc, footprint as _fpc
                from .tv import distance_range as _drc
                _sofa = next((p for p in blk if p.role.split(' ')[0] == 'диван'),
                             blk[0] if blk else None)
                _car = next((p for p in m0 if p.role.split(' ')[0]
                             in ('тв-тумба', 'стенка')), None)
                if _sofa is None or _car is None or _car.item is None:
                    return 'far'
                lo, hi, soft_hi = _drc(_car.item.w_cm or 120.0,
                                       bearer=_brc(_car.role))
                g = _fpc(_sofa).distance(_fpc(_car))
                return 'comfort' if g <= min(soft_hi, hi) else 'far'

            # ДВУХПРОХОДНАЯ ЛЕСТНИЦА (C-3): pass 1 — принимаются только ступени с
            # медиа-минимумом класса COMFORT (богатая FAR-группа не побеждает
            # компактную comfort автоматически); pass 2 — FAR-разрешение с явным
            # трейсом. Существующие границы, нового скора нет.
            _m0 = None
            _any_sofa_step_valid = False      # LEVEL A: была ли хоть одна вставшая диванная ступень
            for _need_comfort in (True, False):
              if block is not None:
                  break
              for _g in _ladder_steps:
                _se = _sseek.setdefault(_g['id'], {'id': _g['id']})
                # LEVEL A (владелец: «диван из банка стоит всегда») ВЫШЕ comfort-first:
                # в comfort-проходе бездиванные ступени пропускаются, пока диван
                # доступен — иначе пара кресел с comfort-медиа обходила диванные
                # FAR-ступени (регресс C-3: set61-bay/set77-trapezoid)
                # Q3 свода №13 (set80-L): LEVEL A действует в ОБОИХ проходах — бездиванная
                # ступень с медиа-минимумом не решение, пока диван в банке; честнее
                # MEDIA_MISSING на диванной ступени, чем гостиная без дивана.
                if any(i.role == 'диван' for i in keep) \
                        and 'диван' not in {r.split(' ')[0]
                                            for r in _g['roles']['required']} \
                        and (_need_comfort or _fb_block is not None or _any_sofa_step_valid):
                    # бездиванная — только если НИ ОДНА диванная ступень не встала вовсе
                    # (иначе комната пустая — тест quiet_zone); тогда честный последний фолбэк
                    continue
                _blk = (list(_hyp['block']) if _hyp
                        else place_template(room, _g['id'], keep, usable_polygon(room)))
                _se['generated'] = 1
                _se['hard_valid'] = 1 if _blk else 0
                if _blk and 'диван' in {r.split(' ')[0] for r in _g['roles']['required']}:
                    _any_sofa_step_valid = True
                if not _blk:
                    continue
                if _has_bearer0:
                    from .template import place_media as _pm0
                    _occ0 = _uu0([_fp0(p) for p in _blk if p.role.split(' ')[0] != 'ковёр'])
                    _m0 = _pm0(room, keep,
                               usable_polygon(room).difference(_occ0), fixed=_blk)
                    # P1 свода №12 (каузальный пруф set25-bay): позиция носителя внутри
                    # ОДНОГО класса оси может съесть регион столовой (0.0 см оси vs 3.0 см
                    # + столовая). Медиа-минимум не видит dining (ставится позже, необратимо)
                    # → пробуем top-K носителей и берём тот, при котором preferred-столовая
                    # ВСТАЁТ (покрытие зоны выше косметики оси — наш порядок ярусов).
                    # Мини-«взгляд вперёд» до P2; K и условия — rules/zones.json.
                    _m0 = _media_lookahead(room, keep, _blk, _occ0, _m0, _pm0,
                                           _needs_eff, usable_polygon(room))
                    _se['media_min'] = 1 if _m0 else 0
                    if not _m0:
                        if _fb_block is None:
                            _fb_block, _fb_group = _blk, _g
                        if os.environ.get('ZONES_DEBUG'):
                            import sys as _sl
                            print(f"ZDBG лестница: ступень {_g['id']} встала, но БЕЗ "
                                  f"медиа — пробуем следующую", file=_sl.stderr, flush=True)
                        continue
                    _mcls = _media_comfort(_blk, _m0)
                    _se['media_class'] = _mcls
                    if _need_comfort and _mcls == 'far':
                        if os.environ.get('ZONES_DEBUG'):
                            import sys as _sl
                            print(f"ZDBG лестница: ступень {_g['id']} даёт только FAR "
                                  f"— comfort-first, пробуем следующую",
                                  file=_sl.stderr, flush=True)
                        continue
                _se['winner'] = True
                block, group = _blk, _actual_step(_blk, _g, zone_rules())
                if _has_bearer0 and _m0:
                    # ПРОБА = ФАКТ: медиа из проверки минимума входит в раскладку сразу
                    # (повторный place_media в цепочке видел бы другой free после
                    # резервов — проба проходила, а зона не вставала: план №14)
                    _r0 = {p.role for p in _m0}
                    block = list(block) + list(_m0)
                    keep = [it for it in keep if it.role not in _r0]
                if os.environ.get('ZONES_DEBUG'):
                    import sys as _sl
                    print(f"ZDBG лестница: ступень {_g['id']} принята (минимум собрался)",
                          file=_sl.stderr, flush=True)
                break
            if block is None:
                # ЛЕСТНИЦА ДИВАНОВ (владелец 13.08, планы 145/236/252: «надо было
                # выбирать не угловой диван, а прямой — тогда не в угол, а в верхнюю
                # половину, затем медиа, внизу столовая»). Угловой главный диван не
                # дал минимума ни на одной ступени — пробуем те же ступени с ПРЯМЫМ
                # диваном из банка («диван 2»), угловой уходит в неиспользованное.
                # ищем в ИСХОДНОМ составе: «диван 2» мог быть отфильтрован группой
                _d1 = next((i for i in items if i.role == 'диван'), None)
                _d2 = next((i for i in items if i.role == 'диван 2'), None)
                if _d1 is not None and getattr(_d1, 'corner', False) \
                        and _d2 is not None and not getattr(_d2, 'corner', False):
                    _keep2 = [i for i in keep if _base(i.role) != 'диван']
                    _keep2.append(_d2.model_copy(update={'role': 'диван', 'corner': False}))
                    if os.environ.get('ZONES_DEBUG'):
                        import sys as _sl
                        print('ZDBG лестница диванов: пробуем ПРЯМОЙ вместо углового',
                              file=_sl.stderr, flush=True)
                    for _g in pick_ladder(room, dict(counts), skip=_ladder_skip):
                        _blk = place_template(room, _g['id'], _keep2, usable_polygon(room))
                        if not _blk:
                            continue
                        from .template import place_media as _pm1
                        _occ1 = _uu0([_fp0(p) for p in _blk
                                      if p.role.split(' ')[0] != 'ковёр'])
                        _m1 = _pm1(room, _keep2,
                                   usable_polygon(room).difference(_occ1), fixed=_blk)
                        if _m1:
                            keep = _keep2
                            block, group = list(_blk) + list(_m1), _g
                            keep = [it for it in keep
                                    if it.role not in {p.role for p in block}]
                            if os.environ.get('ZONES_DEBUG'):
                                import sys as _sl
                                print('ZDBG лестница диванов: прямой вместо углового — '
                                      'минимум собрался', file=_sl.stderr, flush=True)
                            break
            if block is None and _fb_block is not None:
                block, group = _fb_block, _fb_group
                if '_sseek' in dir():
                    _sseek.setdefault(_fb_group['id'], {}).setdefault(
                        'winner', 'fallback_no_media')
                # Пакет D свода №8: прежде чем принять ступень БЕЗ медиа — вейвер
                # SCREEN_OVER_WINDOW (контурные комнаты: единственная стена носителя
                # оконная; «носитель должен быть везде» — владелец 12.08 —
                # приоритетнее запрета экрана на проёме). Явный флаг, не тихо:
                # тег +tvw добавит сама цепочка (медиа встанет обычным шагом).
                if _has_bearer0 and os.environ.get(
                        'LAYOUT_SCREEN_WINDOW_WAIVER', '1') != '0':
                    from . import validate as _valmodW
                    _valmodW.SCREEN_WINDOW_WAIVED[0] = True
                    from .template import place_media as _pmw
                    _occw = _uu0([_fp0(p) for p in block
                                  if p.role.split(' ')[0] != 'ковёр'])
                    _mw = _pmw(room, keep,
                               usable_polygon(room).difference(_occw), fixed=block)
                    if _mw:   # P1 свода №12: тот же взгляд вперёд на столовую (set25-bay: +tvw)
                        _mw = _media_lookahead(room, keep, block, _occw, _mw, _pmw,
                                               _needs_eff, usable_polygon(room))
                    if _mw:
                        block = list(block) + list(_mw)
                        keep = [it for it in keep
                                if it.role not in {p.role for p in _mw}]
                        if os.environ.get('ZONES_DEBUG'):
                            import sys as _sl
                            print('ZDBG лестница: медиа встала ПО ВЕЙВЕРУ экрана '
                                  '(+tvw)', file=_sl.stderr, flush=True)
                    else:
                        _valmodW.SCREEN_WINDOW_WAIVED[0] = False
                # V3-D (свод №9, frozen-core / known-issue set80-L): и вейвер не дал
                # носитель → перебираем АЛЬТЕРНАТИВНЫЕ ПОЗИЦИИ той же ступени: вырезаем
                # выбранную позицию посадки из полигона и переигрываем шаблон; медиа-
                # минимум проверяется на каждой альтернативе (≤2 попыток — дёшево и
                # срабатывает только когда сцена уже теряла носитель совсем)
                if _has_bearer0 and not any(
                        p.role.split(' ')[0] in ('тв-тумба', 'стенка') for p in block):
                    _carve = None
                    _blk_cur = block
                    for _alt in range(2):
                        _seat_a = next((p for p in _blk_cur
                                        if p.role.split(' ')[0] == 'диван'),
                                       _blk_cur[0] if _blk_cur else None)
                        if _seat_a is None:
                            break
                        _pad = _fp0(_seat_a).buffer(25)
                        _carve = _pad if _carve is None else _carve.union(_pad)
                        _blk_a = place_template(
                            room, group['id'], keep,
                            usable_polygon(room).difference(_carve))
                        if not _blk_a:
                            break
                        _occ_a = _uu0([_fp0(p) for p in _blk_a
                                       if p.role.split(' ')[0] != 'ковёр'])
                        _m_a = place_media(room, keep,
                                           usable_polygon(room).difference(_occ_a),
                                           fixed=_blk_a)
                        if _m_a:
                            block = list(_blk_a) + list(_m_a)
                            keep = [it for it in keep
                                    if it.role not in {p.role for p in _m_a}]
                            from . import validate as _valmodA
                            _valmodA.SCREEN_WINDOW_WAIVED[0] = False
                            if os.environ.get('ZONES_DEBUG'):
                                import sys as _sl
                                print(f'ZDBG лестница: альтернативная позиция №{_alt+1} '
                                      f'ступени {group["id"]} дала медиа-минимум',
                                      file=_sl.stderr, flush=True)
                            break
                        _blk_cur = _blk_a
                if os.environ.get('ZONES_DEBUG'):
                    import sys as _sl
                    print(f"ZDBG лестница: минимум не собрался ни на одной ступени — "
                          f"fallback {group['id']}", file=_sl.stderr, flush=True)
        # ДИЗАЙНЕРСКИЙ ПОРЯДОК (свод владельца 12.08): фокус-стена важнее удобной
        # позиции дивана. Прямая постановка «медиа первой» в тесных комнатах не встаёт
        # (обе зоны помещаются лишь в согласованной паре), поэтому порядок реализован
        # ЖЁСТКИМ ТРЕБОВАНИЕМ в схеме посадки: позиция дивана принимается, только если
        # носителю ТВ остаётся чистое место (`place_template` → require_bearer,
        # LAYOUT_FOCUS_MANDATORY). Эксперимент «медиа первой» остаётся под флагом.
        if block is None and os.environ.get('LAYOUT_LADDER', '1') != '0':
            pass                          # лестница исчерпана — ниже минимальная схема
        media_opts = []
        if os.environ.get('LAYOUT_FOCUS_FIRST', '0') != '0':
            _m = place_media(room, keep, usable_polygon(room), fixed=None, top=8)
            # top>1 отдаёт СПИСОК вариантов позиции медиа-блока
            media_opts = _m if (_m and isinstance(_m[0], list)) else ([_m] if _m else [])
        for media_first in (media_opts if block is None else []):
            _occ = _uu0([_fp0(p) for p in media_first if p.role.split(' ')[0] != 'ковёр'])
            _blk = place_template(room, group['id'], keep,
                                  usable_polygon(room).difference(_occ),
                                  fixed=media_first)
            if _blk:
                block = list(media_first) + list(_blk)
                keep = [it for it in keep if it.role not in {p.role for p in media_first}]
                break
        if not block and os.environ.get('LAYOUT_LADDER', '1') == '0':
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
        # ЦЕПОЧКА ЗОН ПО ПРИОРИТЕТУ (канон порядка — zones.json `zone_priority`,
        # ADR-0094; коридор `fill_policy.target_pct` — ДИАГНОСТИКА и триггер
        # второго прохода добора, не гейт — свод №8 v2 §1, ADR-0091).
        from .template import (place_decor, place_fireplace, place_media,
                               place_media_fireplace, place_quiet,
                               place_bay_armchair, place_reading, place_storage,
                               place_window_reading)
        _fp_pol = zone_rules().get('fill_policy', {})
        _lo, _hi = _fp_pol.get('target_pct', [30, 45])
        _half = set(WALL_HUGGING_ROLES)
        _room_m2 = room.width_cm * room.depth_cm / 10_000

        def _fill_pct(pls):
            # C-7: единая диагностическая семантика — geometry.floor_fill_diag_pct
            from .geometry import floor_fill_diag_pct as _ffd
            return _ffd(room, pls, wall_hugging_roles=_half)

        def _din(r, k, f, fixed=None):
            return place_dining(r, k, f, usable_m2(r), fixed=fixed)
        # ПОРЯДОК ФОКУСОВ (экзамен 11.08: камин избыточен в 72 сценах 40+ м² —
        # медиа-зона забирала стену первой). Канон: камин — фокус помещения; в
        # просторных комнатах он идёт ПЕРВЫМ, в малых приоритет у медиа.
        # МЕДИА ВСЕГДА ПЕРВЕЕ КАМИНА (правило владельца 12.08: «каминная зона — доп.
        # зона с ПОНИЖЕННЫМ приоритетом фокуса относительно медиа»). Прежнее исключение
        # для просторных комнат отменено: экран задаёт ось взгляда, камин к ней
        # пристраивается (на противоположной или смежной стене, но в углу обзора).
        _fp_first = False
        # ОБА ФОКУСА НА ОДНОЙ СТЕНЕ (заявка владельца 11.08, веб подтвердил
        # side-by-side): сперва пробуем совмещённую зону «носитель + камин», и
        # только если не встала — раздельные зоны в порядке приоритета.
        _order = ((place_fireplace, '+fp'), (place_media, '+tv')) if _fp_first \
            else ((place_media, '+tv'), (place_fireplace, '+fp'))
        _media_in = any(p.role.split(' ')[0] in ('тв-тумба', 'стенка') for p in (block or []))
        if _media_in and '+tv' not in tpl_tag:
            # пакет D: медиа, вставшая по вейверу экрана, помечается явно (+tvw)
            from . import validate as _valmodT
            tpl_tag += ('+tvw' if _valmodT.SCREEN_WINDOW_WAIVED[0] else '+tv')
        for placer, tag in ((place_media_fireplace, '+tvfp'), _order[0], _order[1],
                            (_din, '+din'),
                            # C-1 свода №11 (Кодекс §4): порядок исполнения =
                            # zone_priority.order — SEATING_EXTRA (тихая/чтение/эркер)
                            # ДО ХРАНЕНИЯ; прежде storage дважды съедал стены и
                            # остаточный регион до place_quiet (одна из причин
                            # «вторая зона не встаёт» из свода №10 J)
                            # Q10b: оконный уголок — ПЕРЕД общим reading (у окна кресло ценнее,
                            # чем у произвольной стены), но после обязательных зон
                            (place_quiet, '+qz'), (place_window_reading, '+wr'),
                            (place_reading, '+rd'),
                            (place_bay_armchair, '+bay'),
                            (place_storage, '+st'),
                            # НЕ БОЛЕЕ ДВУХ зон хранения на гостиную (владелец 12.08)
                            (place_storage, '+st2'),
                            (place_decor, '+dc')):
            occ2 = _uu([_fp(p) for p in block if p.role != 'ковёр'])
            _free_z = usable_polygon(room).difference(occ2)
            # ПРИОРИТЕТ МЕДИА НАД ХРАНЕНИЕМ (правило владельца 12.08, set7-bay:
            # стеллаж занял стену напротив дивана, а тумба осталась в банке).
            # Пока носитель ТВ не поставлен, стена напротив посадки за ним
            # зарезервирована — остальные зоны туда не лезут.
            # R2 (rules-consistency-audit): применимость резерва — по ТАБЛИЦЕ
            # приоритетов зон (zones.json zone_priority), не по хардкоду тегов:
            # резерв зоны-владельца отнимает место только у зон НИЖЕ приоритетом
            _zp = zone_rules().get('zone_priority', {})
            _zo, _zt = _zp.get('order', []), _zp.get('tags', {})
            def _zidx(t):
                zz = _zt.get(t)
                return _zo.index(zz) if zz in _zo else len(_zo)
            # V3-A (свод №9 P0, план №269): КАРДИНАЛЬНОСТЬ media из данных —
            # носитель уже в блоке (в т.ч. поставлен лестницей по вейверу +tvw) →
            # media-теги пропускаются, второй носитель НЕ добирается
            # V4-A свода №10: паспорт media_wall counts_as_storage — стенка даёт
            # вертикаль хранения; ВТОРАЯ зона хранения при ней не добирается
            if tag == '+st2' and any(p.role.split(' ')[0] == 'стенка' for p in block):
                continue
            _cardc = (_zp.get('cardinality') or {}).get(_zt.get(tag, '')) or {}
            if _cardc.get('rule') in ('at_most_one_carrier', 'exactly_one_carrier', 'exactly_one_carrier_when_required') and any(
                    p.role.split(' ')[0] in tuple(_cardc.get('carrier_roles') or ())
                    for p in block):
                continue
            if _zidx(tag) > _zidx('+tv') and _tv_wall_reserved(room, block, keep):
                _free_z = _free_z.difference(_tv_wall_strip(room, block))
            # ЗА СПИНКОЙ ОТОДВИНУТОГО ДИВАНА — СТОЛОВАЯ (веб-канон RU: диван спинкой к
            # обеденной зоне — типовой приём зонирования; вторая зона гостиной чаще
            # всего именно столовая/барная — inmyroom.ru, 4happyhome.ru).
            # Пока столовая не поставлена, полосу за спинкой держим за ней.
            # медиа-зона ПРИОРИТЕТНЕЕ столовой (12.08): полосу за спинкой у неё не отнимаем
            if _zidx(tag) > _zidx('+din') and _behind_reserved(room, block, keep):
                _free_z = _free_z.difference(_behind_sofa_strip(room, block))
            # P0 свода №12: need=off — зона сценарием выключена, placer не зовём
            if _needs_eff.get(_zt.get(tag, '')) == 'off':
                if os.environ.get('ZONES_DEBUG'):
                    import sys as _sdo
                    print(f'ZDBG зона {tag}: need=off — пропуск', file=_sdo.stderr, flush=True)
                continue
            extra = placer(room, keep, _free_z, fixed=block)
            if tag == '+wr':
                # Q10-0: диагноз оконного уголка (пробовали/нечего/не влезло) — в meta плана
                try:
                    _WR_DIAG.update(getattr(_tplmod, 'WINDOW_DIAG', {}) or {})
                    _WR_DIAG['placed'] = bool(extra)
                except Exception:
                    pass
            if extra is None and os.environ.get('ZONES_DEBUG'):
                import sys as _sdz
                print(f'ZDBG зона {tag}: placer вернул None (roles в банке: '
                      f'{sorted({i.role for i in keep})})', file=_sdz.stderr, flush=True)
            # ГЕЙТ ДЕГРАДАЦИИ (свод владельца 12.08): зона принимается, только если не
            # ухудшила достигнутое — маршрут ≥75 см, «щели» уже 45 см не выросли, фокус
            # не сбился. Заполнение пола (fill) больше НЕ цель, а диагностика: прежний
            # бюджет заставлял добивать площадь, отсюда кашпо в щели и кресло, портящее
            # проход. Пруфы и пороги — rules/zones.json → quality_gate.
            # Пакет F свода №8: статус зоны — ИЗ ДАННЫХ (zone_priority.status), не
            # хардкод-тройка тегов. required-зоны (медиа/фокус) гейт не проходят —
            # формализация прежнего поведения; preferred/optional — гейт not_worse.
            _zst = (_zp.get('status') or {}).get(_zt.get(tag, ''), 'optional')
            # P0 свода №12: need сценария переопределяет статус зоны (media/dining)
            _zst = _needs_eff.get(_zt.get(tag, ''), _zst)
            if extra and _zst != 'required':
                _q_before = _quality(room, block)
                _q_after = _quality(room, block + extra)
                if not _not_worse(_q_before, _q_after):
                    if os.environ.get('ZONES_DEBUG'):
                        import sys as _s
                        print(f'ZDBG зона {tag} ОТКЛОНЕНА гейтом качества: маршрут '
                              f"{_q_before['circulation']:.0f}→{_q_after['circulation']:.0f} см, "
                              f"щели {_q_before['sliver_m2']:.2f}→{_q_after['sliver_m2']:.2f} м²",
                              file=_s.stderr, flush=True)
                    if tag == '+wr':
                        try:                       # Q10-0: «пробовали и не влезло» ≠ «не пробовали»
                            lay.meta.setdefault('window_nook', {}).update(_tplmod.WINDOW_DIAG)
                        except Exception:
                            pass
                    if tag == '+qz':
                        # Q5 (Codex): отказ гейта качества — в QUIET_DIAG, иначе сертификат
                        # second_pod показывал «placed», а зоны в плане нет
                        try:
                            _tplmod.QUIET_DIAG['quality_rejected'] = True
                            _tplmod.QUIET_DIAG.pop('placed', None)
                        except Exception:
                            pass
                    if tag == '+din':
                        _dd0 = getattr(_tplmod, 'LAST_DINING_DIAG', None)
                        if _dd0 is not None:
                            _dd0['gate_rejected'] = True   # пакет B: причина «не встала»
                            # V3-B: ТОЧНАЯ ось гейта + вектора до/после (объяснимость)
                            from .quality import failed_axes as _faxes
                            _rnd = lambda d: {k: (round(v, 2) if isinstance(
                                v, (int, float)) else v) for k, v in d.items()}
                            _dd0['gate'] = {'failed_axes': _faxes(_q_before, _q_after),
                                            'before': _rnd(_q_before),
                                            'after': _rnd(_q_after)}
                            _kls = _dd0.get('mode_path') or _dd0.get('mode')
                            if _kls and _dd0.get('search', {}).get(_kls) is not None:
                                _dd0['search'][_kls]['quality_valid'] = 0
                        # Пакет C: остров отвергнут гейтом качества (маршрут/щели/фокус)
                        # → честный retry классом EDGE с ЯВНОЙ причиной (тихого edge нет:
                        # причина обязана попасть в диагноз — свод №8 v2, ключевой инвариант)
                        from .template import place_dining as _pd_edge
                        _prev_diag = dict(_dd0) if _dd0 else None
                        _extra_e = _pd_edge(room, keep, _free_z, usable_m2(room),
                                            fixed=block, classes=('edge',))
                        # V3-B (вопрос рефери по №216): диагноз ПЕРВОЙ попытки (проба
                        # острова, счётчики island-классов, ось гейта) сохраняется при
                        # retry — иначе island_feasible пересчитывался на суженном free
                        _dde = getattr(_tplmod, 'LAST_DINING_DIAG', None)
                        if _dde is not None and _prev_diag is not None:
                            _dde['island_feasible'] = _prev_diag.get('island_feasible')
                            _dde['island_reject'] = _prev_diag.get('island_reject')
                            if _prev_diag.get('gate'):
                                _dde['gate'] = _prev_diag['gate']
                            for _k in ('full_island', 'compact_island'):
                                if (_prev_diag.get('search') or {}).get(_k):
                                    _dde.setdefault('search', {})[_k] = \
                                        _prev_diag['search'][_k]
                        if _extra_e and _not_worse(_q_before,
                                                   _quality(room, block + _extra_e)):
                            if _dde is not None:
                                # V3-E: mode остаётся топологией из place_dining
                                _dde['fallback_reason'] = 'island_rejected_by_quality_gate'
                                _dde.pop('gate_rejected', None)
                            extra = _extra_e
                        else:
                            if _dde is not None:
                                _dde['gate_rejected'] = True   # retry тоже не прошёл
                            extra = None
                    else:
                        extra = None
            if extra:
                roles2 = {p.role for p in extra}
                keep = [it for it in keep if it.role not in roles2]
                block = block + extra
                _refine_mod.LOCKED |= roles2
                tpl_tag += tag
        # ПОСЛЕДНЯЯ ПОПЫТКА ДЛЯ НОСИТЕЛЯ (правило владельца 12.08: «либо тумба, либо
        # стенка должна быть везде»). Если после всей цепочки фокус-стена пуста, а
        # носитель лежит в банке — ставим его с ослабленными условиями: без требования
        # центровки, ковру можно уйти под него глубже, годятся угловые позиции.
        if any(_base(i.role) in ('тв-тумба', 'стенка') for i in keep) and not any(
                p.role.split(' ')[0] in ('тв-тумба', 'стенка') for p in (block or [])):
            # V3-A: второй носитель не добираем — кардинальность media (свод №9 P0)
            from .template import place_media as _pm
            occ3 = _uu([_fp(p) for p in block if p.role != 'ковёр'])
            _extra = _pm(room, keep, usable_polygon(room).difference(occ3),
                         fixed=block, relaxed=True)
            if _extra:
                roles3 = {p.role for p in _extra}
                keep = [it for it in keep if it.role not in roles3]
                block = block + _extra
                _refine_mod.LOCKED |= roles3
                tpl_tag += '+tv2'
            elif os.environ.get('LAYOUT_SCREEN_WINDOW_WAIVER', '1') != '0':
                # Пакет D свода №8: вейвер SCREEN_OVER_WINDOW. Носитель не встал
                # НИГДЕ (контурные комнаты: единственная пригодная стена — оконная).
                # Правило владельца 12.08 «носитель должен быть везде» приоритетнее
                # запрета экрана на проёме → повтор с выключенным hard, явный тег
                # +tvw (не «тихое» ослабление). Флаг снимает validate только в этом
                # процессе решения; сбрасывается на старте каждого solve.
                from . import validate as _valmod2
                _valmod2.SCREEN_WINDOW_WAIVED[0] = True
                _extra = _pm(room, keep, usable_polygon(room).difference(occ3),
                             fixed=block, relaxed=True)
                if _extra:
                    roles3 = {p.role for p in _extra}
                    keep = [it for it in keep if it.role not in roles3]
                    block = block + _extra
                    _refine_mod.LOCKED |= roles3
                    tpl_tag += '+tvw'
                else:
                    from . import validate as _valmodB
                    _valmodB.SCREEN_WINDOW_WAIVED[0] = False

        # ПЛАВАЮЩИЙ ДИВАН БЕЗ СТОЛОВОЙ ЗА СПИНКОЙ — НЕЛЬЗЯ (владелец 13.08, планы
        # №4/№7: «делишь комнату — вторая зона столовая, или не делать вовсе»).
        # Если диван отодвинут (>90 см до стены), а столовая в итоге НЕ встала —
        # пробуем пересобрать посадку заново БЕЗ «плавающих» позиций (только у стен).
        _din_placed = '+din' in tpl_tag
        if (block and not _din_placed and os.environ.get('LAYOUT_NO_ORPHAN_SPLIT', '1') != '0'):
            _seat0 = next((p for p in block if p.role.split(' ')[0] == 'диван'), None)
            if _seat0 is not None and _behind_decision(room, _seat0) in (
                    'dining_mandatory', 'second_zone_mandatory'):
                from .template import place_template as _pt2
                # C-8 свода №11 (Кодекс §12): параметр wall_only вместо подмены
                # модульной функции middle_candidates (нерентерабельная мутация)
                _blk2 = _pt2(room, group['id'],
                             [i for i in items if i.role in
                              {p.role for p in block} | {it.role for it in keep}],
                             usable_polygon(room), wall_only=True)
                if _blk2:
                    if os.environ.get('ZONES_DEBUG'):
                        import sys as _s9
                        print('ZDBG плавающий диван без столовой — пересобрано у стены',
                              file=_s9.stderr, flush=True)
                    # пересборка: заново прогнать цепочку зон нельзя дёшево — берём
                    # пристенную посадку и достраиваем хранение/декор на новом free
                    block = _blk2
                    keep = [it for it in items if it.role not in {p.role for p in block}]
                    tpl_tag = '+tpl-wall'
                    from shapely.ops import unary_union as _uu9

                    from .geometry import footprint as _fp9
                    for placer9, tag9 in ((place_media, '+tv'), (place_storage, '+st'),
                                          (place_storage, '+st2'), (place_decor, '+dc')):
                        occ9 = _uu9([_fp9(p) for p in block if p.role != 'ковёр'])
                        extra9 = placer9(room, keep, usable_polygon(room).difference(occ9),
                                         fixed=block)
                        if extra9:
                            r9 = {p.role for p in extra9}
                            keep = [it for it in keep if it.role not in r9]
                            block = block + extra9
                            _refine_mod.LOCKED |= r9
                            tpl_tag += tag9

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
        # пакет B свода №8: диагноз dining → meta (почему выбран режим / почему нет)
        _ddiag = getattr(_tplmod, 'LAST_DINING_DIAG', None)
        if _ddiag is not None:
            _ddiag = dict(_ddiag)
            if '+din' in tpl_tag:
                _seatp = next((p for p in block if p.role.split(' ')[0] == 'диван'), None)
                _mand = _seatp is not None and _behind_decision(room, _seatp) in (
                    'dining_mandatory', 'second_zone_mandatory')
                _ddiag['why_selected'] = ('mandatory_residual_R' if _mand
                                          else 'preferred_coverage')
                _mk = _ddiag.get('mode_path') or _ddiag.get('mode')   # V3-B/E
                if _mk and isinstance((_ddiag.get('search') or {}).get(_mk), dict):
                    _ddiag['search'][_mk]['quality_valid'] = 1
            else:
                _ddiag['why_selected'] = 'not_placed'
                _ddiag['mode'] = None
                # пакет C: зона нужна (стол в банке), шаблон не встал ни одним
                # классом — структурное событие TEMPLATE_GAP (свод №8 v2 §13)
                if any(it.role == 'стол обеденный' for it in keep):
                    from .room_map import room_mode, room_shape
                    # V3-G свода №9 (PACKAGE H рефери): ТАКСОНОМИЯ вместо валового
                    # TEMPLATE_GAP — «регион невозможен» ≠ «шаблона нет» ≠ «гейт»:
                    #   NO_FEASIBLE_REGION — проба региона (стол+envelope) отрицательна;
                    #   QUALITY_REJECTED — кандидаты hard-valid были, убил гейт качества;
                    #   TEMPLATE_GAP — регион есть, кандидаты были, hard-valid ноль
                    #                  (истинная дыра библиотеки/кандидатов).
                    _sr = _ddiag.get('search') or {}
                    _hv = sum((_sr.get(k) or {}).get('hard_valid', 0)
                              for k in ('full_island', 'compact_island', 'edge'))
                    if not _ddiag.get('island_feasible'):
                        _gtype = 'NO_FEASIBLE_REGION'
                    elif _ddiag.get('gate_rejected') or _hv > 0:
                        _gtype = 'QUALITY_REJECTED'
                    else:
                        _gtype = 'TEMPLATE_GAP'
                    _ddiag['gap'] = {
                        'type': _gtype, 'zone': 'dining',
                        'requested_mode': 'island',
                        'room_class': f'{room_mode(room)}/{room_shape(room)}',
                        'reason': ('quality_gate' if _ddiag.get('gate_rejected')
                                   else _ddiag.get('island_reject') or 'no_fit')}
            lay.meta['dining'] = _ddiag
        _mst = getattr(_tplmod, 'LAST_MIRROR_STATS', None)
        if _mst is not None:
            lay.meta['mirror'] = dict(_mst)   # V3-H: счётчики зеркал в экспорт
        _ssk = getattr(_tplmod, 'LAST_SEATING_SEARCH', None)
        if _ssk is not None:
            lay.meta['seating_search'] = _ssk   # V4-B2: трейс лестницы в экспорт
        _axd = getattr(_tplmod, 'LAST_AXIS_DIAG', None) or {}
        _axm = getattr(_tplmod, 'LAST_MEDIA_AXIS', None)
        if _axd or _axm:                        # V4-D: контракт осей в экспорт
            lay.meta['axis_contract'] = {**_axd,
                                         **({'media': _axm} if _axm else {})}
        outs = [lay]
        lay.meta['scenario_needs'] = dict(_needs_eff)   # P0 свода №12 (template-only путь)
        if _WR_DIAG:
            lay.meta['window_nook'] = dict(_WR_DIAG)     # Q10-0: диагноз оконного уголка
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
                # Пакет F свода №8 (v2 §1.1): «fill<нижней границы» лишь РАСШИРЯЕТ
                # поиск — основание принять добор то же, что у любой зоны: не хуже
                # по осям качества (маршрут/щели/фокус), не «поместилось»
                from .quality import not_worse as _nw3, scene_quality as _sq3
                if not _nw3(_sq3(room, outs[0].placements),
                            _sq3(room, list(outs[0].placements) + got)):
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
    # П8 (MASTER-tv-sofa-pair): топ-3 пары ТВ↔диван — в атрибут раскладки (артефакт/лог)
    try:
        _med0 = next((i for i in items if _base(i.role) in ('стенка', 'тв-тумба')), None)
        _sof0 = next((i for i in items if i.role == 'диван'), None)
        if _med0 is not None and _sof0 is not None:
            from .room_map import build_room_map
            from .tv_sofa import generate_pairs
            _prs = generate_pairs(room, build_room_map(room), _med0, _sof0, top_k=3)
            for lay in outs:
                lay.meta = getattr(lay, 'meta', {}) or {}
                lay.meta['tv_sofa_pairs'] = [
                    {'wall': p.media_wall, 'score': p.score, 'dist': p.dist_cm,
                     'angle': p.angle_deg, 'scheme': p.sofa_scheme} for p in _prs]
    except Exception:
        pass
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
        lay.meta['scenario_needs'] = dict(_needs_eff)   # P0 свода №12: вход сценария в артефакте
        if _WR_DIAG:
            lay.meta['window_nook'] = dict(_WR_DIAG)     # Q10-0: диагноз оконного уголка
    return outs, group['id'] + tpl_tag


# --- Лексикографическая оценка (правка владельца 07.08): эстетика не компенсирует проход ---
LEVELS = ('hard_feasibility', 'circulation', 'functional_relationships', 'zone_quality',
          'aesthetics')
_TERM_LEVEL = {
    # circulation: проходы, связность, щели-непроходимости
    'sliver_gap': 'circulation', 'sofa_dead_gap': 'circulation',
    'sofa_back_context': 'circulation',   # Q8: полоса за спинкой — про проходимость, не эстетику
    'free_space_fragmentation': 'circulation', 'soft_rule_main_path_tight': 'circulation',
    'soft_rule_zone_buffer': 'circulation',
    # functional: связи предметов
    'sofa_tv_dist': 'functional_relationships',
    'sofa_table_dist': 'functional_relationships',   # C-1 (Кодекс §8): точное имя терма
    'seats_group': 'functional_relationships',       # целостность посадочной группы
    'storage_spacing': 'zone_quality',               # ряд хранения — качество зоны
    'sofa_faces_tv': 'functional_relationships', 'tv_faces_sofa': 'functional_relationships',
    'media_axis_offset': 'functional_relationships',   # P1 свода №12: тай-брейк оси внутри класса
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


# ---------------------------------------------------------------------------
# P2 свода №12: BEAM ПО ПЛАНИРОВОЧНЫМ ГИПОТЕЗАМ (владелец: «плохо перебираются
# комбинации — применяется первая попавшаяся»; Кодекс §3: greedy на уровне ступеней).
# Гипотеза = (ступень лестницы, вариант блока посадки: схема/позиция/зеркало).
# Каждая гипотеза достраивается ПОЛНОЙ цепочкой (медиа → dining → …) прежними
# кирпичами, готовые планы сравниваются ЛЕКСИКОГРАФИЧЕСКИ; старый результат — всегда
# гипотеза №0 (инвариант «не хуже прежнего»). Числа — rules/zones.json → beam.
# ---------------------------------------------------------------------------

def _back_orphan(room: Room, ps) -> bool:
    """Q8: класс полосы за спинкой дивана = orphan (`planner/back_gap.py`)."""
    try:
        from .back_gap import back_gap_context
        ctx = back_gap_context(room, list(ps))
        return bool(ctx and ctx['class'] == 'orphan' and not ctx.get('corner_sofa'))
    except Exception:
        return False


def template_degradation(ps) -> tuple:
    """Codex 17.08 (владелец №31 set16-base): степень отхода посадочного шаблона от канона —
    (max_level, count). 0 — канон (столик по центру, номинальный зазор); 1 — допустимый fallback
    (комфортный неноминальный зазор 36); 2 — сдвиг столика вдоль дивана / крайний зазор 32|48.
    Читает пометки tpl_variant (`+table_axis_shifted`, `+gapNN`) — ставит template.place_template."""
    lvl, cnt = 0, 0
    for p in ps:
        v = getattr(p, 'tpl_variant', '') or ''
        if getattr(p, 'tpl_id', '') != 'seating' or not v:
            continue
        l = 0
        if '+table_axis_shifted' in v:
            l = 2
        m = re.search(r'\+gap(\d+)', v)
        if m:
            g = int(m.group(1))
            l = max(l, 2 if g in (32, 48) else 1)
        if l:
            lvl = max(lvl, l)
            cnt += 1
    return (lvl, cnt)


def _main_path_violations(lay) -> int:
    """MAIN_PATH_TIGHT — soft в validate; как ярус ключа ВЫШЕ деградации шаблона: канон не должен
    побеждать вариант, реально сохраняющий проход 90 см (Codex 17.08)."""
    return sum(1 for v in getattr(lay, 'violations', []) or [] if getattr(v, 'code', '') == 'MAIN_PATH_TIGHT')


def plan_key(room: Room, lay, needs: dict, seat_rank: int = 0) -> tuple:
    """Ключ сравнения ГОТОВОГО плана (меньше — лучше):
    (hard, missing_required, -covered_preferred, circulation, functional, zone_q, aesthetics).
    Обязательность зон — из scenario_needs/zone_priority.status (данные)."""
    from .score import score_layout
    from .validate import Severity
    ps = list(lay.placements)
    hard = sum(1 for v in lay.violations if v.severity is Severity.HARD)
    zp = zone_rules().get('zone_priority', {})
    status = dict(zp.get('status') or {})
    status['media'] = needs.get('media', status.get('media'))
    status['dining'] = needs.get('dining', status.get('dining'))
    from .geometry import base_role as _br
    roles = {_br(p.role) for p in ps}
    have = {'media': bool(roles & {'тв-тумба', 'стенка'}),
            'dining': 'стол обеденный' in roles,
            'seating': bool(roles & {'диван', 'кресло'})}
    missing_req = sum(1 for z, st in status.items()
                      if st == 'required' and z in have and not have[z])
    covered_pref = sum(1 for z, st in status.items()
                       if st == 'preferred' and have.get(z))
    lk = lexo_key(hard, len(getattr(lay, 'unplaced', []) or []),
                  score_layout(room, ps).terms)
    # lk = (hard_feasibility, circulation, functional, zone_quality, aesthetics)
    # Богатство посадки (LEVEL A / лестница: sofa_2armchairs выше sectional_armchair)
    # — иначе beam спускался бы по лестнице: меньше предметов → меньше штрафов
    # circulation (пруф set87-pylons). seat_rank = позиция ступени в порядке банка.
    # (seat_rank — из драйвера: позиция ступени в pick_ladder, больший = богаче)
    # Класс оси медиа (P1): centered(0) < offset(1) < relaxed/corner(2) — выше
    # circulation-суммы: 128 см сбоку не компенсируется парой см прохода.
    axis_cls = _axis_class(lay)
    # Codex 17.08 (владелец №31): main-path контракт → деградация шаблона (канон важнее допуска)
    # — ВЫШЕ мягких термов (circulation +1 не должен двигать столик с центра дивана)
    # Q8 (владелец 17.08 + Codex): БЕСХОЗНАЯ полоса за спинкой (31–90 пусто) — категориальный
    # ярус ВЫШЕ мягких термов (в т.ч. дистанции ТВ): движок обязан прижать диван в норму
    # 15–30 или оставить настоящий проход ≥91, если такой вариант вообще достижим
    _orphan = int(bool(_back_orphan(room, ps)))
    return (hard, missing_req, -covered_pref, -seat_rank, axis_cls,
            _main_path_violations(lay), template_degradation(ps), _orphan) + tuple(lk[1:])


EXTERNAL_SEAT_ZONES = ('quiet', 'reading', 'bay_armchair')   # зоны, где кресло — полноценное место


def realized_capacity(lay, gid: str) -> float:
    """Q10 (Codex 19.08): ФАКТИЧЕСКАЯ вместимость плана = паспортные места выбранной главной
    группы + валидные места ВНЕ её (кресла атомарных зон quiet/reading/bay_armchair).
    Чинит системную ошибку «место считается богатством только внутри главной группы»:
    sofa_lamp(3) + кресло у окна(1) = sofa_armchair(4), а не «беднее на ступень».
    План уже hard-valid, значит контракты зон (в т.ч. window_anchor) выполнены."""
    from .geometry import base_role as _br
    ps = list(lay.placements)
    seats = 0.0
    _g0 = (gid or '').split('+')[0]
    for g in zone_rules().get('seating_groups', []):
        if g['id'] == _g0:
            seats = float(g.get('seats') or 0)
            break
    ext = sum(1 for p in ps if _br(p.role) == 'кресло'
              and getattr(p, 'tpl_id', '') in EXTERNAL_SEAT_ZONES)
    return seats + ext


def primary_sofa_missing(lay, items) -> int:
    """Бинарный контракт LEVEL A для ключа: диван в банке есть, а в плане его нет.
    Если диван недостижим ни в одной гипотезе — ярус одинаков у всех, и он нейтрален."""
    from .geometry import base_role as _br
    if not any(_br(i.role) == 'диван' for i in (items or [])):
        return 0
    return 0 if any(_br(p.role) == 'диван' for p in lay.placements) else 1


def plan_key_capacity(room: Room, lay, needs: dict, gid: str, items) -> tuple:
    """ТЕНЬ Q10: тот же ключ, что production-v1, но вместо НОМИНАЛЬНОЙ ступени лестницы
    (`-seat_rank`) — фактическая вместимость плана, и отдельный ярус «диван поставлен».
    Порядок по Codex: hard → missing_required → primary_sofa_missing → -covered_pref →
    -capacity → axis → main_path → degradation → orphan → мягкие термы."""
    from .models import Severity as _Sev
    ps = list(lay.placements)
    hard = sum(1 for v in lay.violations if v.severity is _Sev.HARD)
    status = (zone_rules().get('zone_priority', {}) or {}).get('status', {})
    from .geometry import base_role as _br
    roles = {_br(p.role) for p in ps}
    have = {'media': bool(roles & {'тв-тумба', 'стенка'}), 'dining': 'стол обеденный' in roles,
            'seating': bool(roles & {'диван', 'кресло'})}
    missing_req = sum(1 for z, st in status.items() if st == 'required' and z in have and not have[z])
    covered_pref = sum(1 for z, st in status.items() if st == 'preferred' and have.get(z))
    from .score import score_layout as _sl
    lk = lexo_key(hard, len(getattr(lay, 'unplaced', []) or []), _sl(room, ps).terms)
    return (hard, missing_req, primary_sofa_missing(lay, items), -covered_pref,
            -realized_capacity(lay, gid), _axis_class(lay), _main_path_violations(lay),
            template_degradation(ps), int(bool(_back_orphan(room, ps)))) + tuple(lk[1:])


def plan_key_v2(room: Room, lay, needs: dict, reach: dict | None = None) -> tuple:
    """Q4 свода №13 (SHADOW до слепого раунда 2/Q7): ключ ГОТОВОГО плана по ярусам, как
    ранжирует владелец (слепая оценка раунд 1 + Codex). Меньше — лучше. Пороги —
    rules/zones.json view_contracts; ярусы со status=hypothesis участвуют только при
    beam.shadow_hypothesis_tiers (решение владельца: shadow).
    (hard, missing_required, unplaced_required,
     entry_sightline_violation, media_seat_violation_if_reachable, dining_view_cone_violation,
     small_room_corner_violation, missing_reachable_valid_preferred,
     frontal_composition_deficit, seating_deficit,
     -realized_armchairs, -realized_valid_flex_seats, -has_actual_footrest,
     axis_class, circulation, functional, zone_quality, aesthetics)"""
    from .score import score_layout
    from .validate import Severity
    from .geometry import base_role as _br
    from .view_metrics import view_metrics as _vm
    ps = list(lay.placements)
    hard = sum(1 for v in lay.violations if v.severity is Severity.HARD)
    unplaced = len(getattr(lay, 'unplaced', []) or [])
    zp = zone_rules().get('zone_priority', {})
    vc = zone_rules().get('view_contracts', {}) or {}
    reach = reach or {}
    status = dict(zp.get('status') or {})
    status['media'] = needs.get('media', status.get('media'))
    status['dining'] = needs.get('dining', status.get('dining'))
    roles = {_br(p.role) for p in ps}
    m = _vm(room, ps)
    seat = m.get('seating') or {}
    have = {'media': bool(roles & {'тв-тумба', 'стенка'}), 'dining': 'стол обеденный' in roles,
            'seating': bool(roles & {'диван', 'кресло'}),
            'storage': bool(roles & {'стеллаж', 'витрина', 'комод', 'шкаф', 'стенка'})}
    missing_req = sum(1 for z, st in status.items() if st == 'required' and z in have and not have[z])

    def _active(key):
        spec = vc.get(key) or {}
        return spec.get('status') == 'measured' or bool(reach.get('shadow_hyp'))
    entry_gap = m.get('entry_sightline_gap_cm')
    entry_min = float((vc.get('entry_sightline_min_gap_cm') or {}).get('value', 76))
    entry_viol = int(_active('entry_sightline_min_gap_cm') and entry_gap is not None and entry_gap < entry_min)
    ang_max = float((vc.get('media_seat_angle_max_deg') or {}).get('value', 45))
    angs = m.get('armchair_tv_angles') or []
    media_seat_ok = any(a <= ang_max for a in angs) if angs else None
    # контракт — только если сертификат говорит, что media-кресло достижимо в этой сцене
    media_seat_viol = int(_active('media_seat_angle_max_deg') and bool(reach.get('media_seat_reachable'))
                          and bool(angs) and not media_seat_ok)
    dvc = vc.get('dining_view_cone') or {}
    cone = m.get('dining_view_cone_overlap_pct')
    dining_cone_viol = int(_active('dining_view_cone') and cone is not None
                           and cone > float(dvc.get('overlap_max_pct', 10)))
    corner_viol = 0
    try:
        crn = float((vc.get('small_room_corner_hug_below_m2') or {}).get('value', 30))
        zs = (getattr(lay, 'meta', None) or {}).get('zones') or {}
        cc = (zs.get('seating') or {}).get('corner_class') if isinstance(zs.get('seating'), dict) else None
        if room.width_cm * room.depth_cm / 10_000 < crn and cc == 'adrift':
            corner_viol = 1
    except Exception:
        pass
    covered_pref = 0
    for z, st in status.items():
        if st != 'preferred':
            continue
        ok = have.get(z, False)
        if z == 'dining' and ok and dining_cone_viol:
            ok = False                          # столовая в конусе — НЕ покрытие
        covered_pref += int(bool(ok))
    n_pref = sum(1 for st in status.values() if st == 'preferred')
    missing_pref = n_pref - covered_pref
    fcm = (vc.get('frontal_companions_min') or {}).get('by_area_m2') or {}
    m2 = room.width_cm * room.depth_cm / 10_000
    need_c = 0
    for k, v in sorted(((float(k), int(v)) for k, v in fcm.items())):
        if m2 >= k:
            need_c = v
    frontal_def = max(0, need_c - len(m.get('frontal_companions') or [])) if _active('frontal_companions_min') else 0
    # Q5 (Codex, разбор регресса): КАТЕГОРИАЛЬНЫЙ large_enrichment_deficit — в ≥25 м² план
    # «обогащён», если есть ЛЮБОЕ из: связная пара кресел (≥2 valid) | второй диван | валидный
    # второй pod (+qz). Сырой -valid_armchairs НЕ ставится выше второго дивана (кресла — не
    # самоцель, №174/192). Дефицит только если обогащение достижимо (по кандидатам beam).
    _si = m.get('seat_intents') or {}
    _valid_arm = int(_si.get('valid_count', seat.get('armchairs', 0)))
    _enriched = (_valid_arm >= 2) or (int(seat.get('sofas', 0)) >= 2) \
        or any(getattr(p, 'tpl_id', '') == 'quiet' for p in ps)
    _need_enrich = m2 >= 25
    _reach_enrich = reach.get('enrichment_reachable')
    seat_def = int(_need_enrich and not _enriched and (_reach_enrich is None or bool(_reach_enrich)))
    lk = lexo_key(hard, unplaced, score_layout(room, ps).terms)
    return (hard, missing_req, unplaced,
            entry_viol, media_seat_viol, dining_cone_viol, corner_viol,
            missing_pref, frontal_def, seat_def,
            -int(seat.get('sofas', 0) >= 2 or _valid_arm >= 2),   # Codex 16.08: сырой -valid_arm ярусом убран
            -int(seat.get('flex_seats', 0)), -int(seat.get('footrest', 0) > 0),
            _axis_class(lay), _main_path_violations(lay), template_degradation(ps),
            int(bool(_back_orphan(room, ps)))) + tuple(lk[1:])


def _axis_class(lay) -> int:
    ax = ((getattr(lay, 'meta', None) or {}).get('axis_contract') or {}).get('media') or {}
    c = ax.get('class')
    return {'centered': 0, 'offset': 1}.get(c, 2 if c else 1)


def solve_zoned_beam(room: Room, items, **kw):
    """P2: драйвер beam. Возвращает (outs, gid) как solve_zoned; в meta лучшего —
    'beam': {hypotheses, chosen, keys, certificate}. Выключен в данных → solve_zoned.

    Q8 (Codex 18.08): правило отступа за спинкой — жёсткое, но НЕ выше обязательных зон.
    Если с ним обязательная медиа-зона недостижима (`MEDIA_MISSING` при носителе в банке),
    прогон повторяется с ослабленным отступом, и в трейс пишется `back_gap_forced` —
    «нормальный отступ и обязательная зона несовместимы в этой геометрии»."""
    _outs, _gid = _solve_zoned_beam_inner(room, items, **kw)
    try:
        if _outs and _outs[0].placements and os.environ.get('NO_SOFA_SLIVER') != '1' \
                and any(v.code == 'MEDIA_MISSING' for v in _outs[0].violations):
            os.environ['NO_SOFA_SLIVER'] = '1'
            try:
                _o2, _g2 = _solve_zoned_beam_inner(room, items, **kw)
            finally:
                os.environ.pop('NO_SOFA_SLIVER', None)
            if _o2 and _o2[0].placements and not any(v.code == 'MEDIA_MISSING' for v in _o2[0].violations):
                _o2[0].meta.setdefault('beam', {})['back_gap_forced'] = \
                    'orphan_allowed: обязательная медиа-зона недостижима при нормальном отступе'
                return _o2, _g2
    except Exception:
        pass
    return _outs, _gid


def _solve_zoned_beam_inner(room: Room, items, **kw):
    cfg = zone_rules().get('beam', {})
    if not cfg.get('enabled', False) or os.environ.get('LAYOUT_BEAM', '1') == '0':
        return solve_zoned(room, items, **kw)
    K_steps = int(cfg.get('ladder_steps', 2))
    K_blocks = int(cfg.get('blocks_per_step', 3))
    try:                                   # бюджет по режиму комнаты (данные)
        from .room_map import room_mode as _rmode
        _bm = (cfg.get('budget_by_mode') or {}).get(_rmode(room)) or {}
        _xl = (cfg.get('budget_by_mode') or {}).get('large_xl') or {}
        if _xl and _rmode(room) == 'large' and \
                room.width_cm * room.depth_cm / 10_000 >= float(_xl.get('min_m2', 40)):
            _bm = _xl                        # очень большие: гипотеза дорогая (set111)
        K_steps = int(_bm.get('ladder_steps', K_steps))
        K_blocks = int(_bm.get('blocks_per_step', K_blocks))
    except Exception:
        pass
    needs = scenario_needs(**{k: v for k, v in kw.items() if k in ('media_need', 'dining_need')})
    # гипотеза №0 — прежний greedy-результат (всегда среди кандидатов)
    base_outs, base_gid = solve_zoned(room, items, **kw)
    cands = []
    from collections import Counter as _C
    _base = lambda r: r.split(' ')[0]
    _sec = _secondary_scope_roles(room)
    counts = _C(_base(i.role) for i in items if i.role not in _sec)   # Q1: secondary вне лестницы
    steps_all = pick_ladder(room, dict(counts))
    n_all = len(steps_all)
    _rank = {g['id']: n_all - i for i, g in enumerate(steps_all)}   # верх лестницы — больший ранг
    if base_outs and base_outs[0].placements:
        _g0 = (base_gid or '').split('+')[0]
        cands.append(('greedy', base_gid, base_outs,
                      plan_key(room, base_outs[0], needs, seat_rank=_rank.get(_g0, 0))))
    # ступени лестницы (те же, что видит greedy) — верхние K_steps
    from .template import place_template as _pt
    # Кодекс (разбор dining 220→218): бюджет ступеней — по ступеням, реально давшим
    # ≥1 гипотезу, а не по первым K инвентарным строкам: недостижимые (inventory-
    # complete, hard_valid=0) ступени съедали бюджет, и достижимые sofa_lamp/compact_
    # sectional не перечислялись (set12-long). Общий фикс класса «мёртвые
    # альтернативы вытесняют достижимый поиск».
    steps = steps_all
    # Q3 свода №13: планировщик СЕМЕЙСТВ композиций (данные beam.composition_families):
    # в large/XL сначала предпочтительные семейства (pair_sides/u/two_sofa/compact+quiet),
    # по одной лучшей позиции на семейство; полный прогон цепочки — под жёстким лимитом
    # max_full_attempts; contributing = семейство дало ПОЛНЫЙ валидный план.
    _fam_cfg = cfg.get('composition_families') or {}
    _mode_key = _rmode(room) if '_rmode' in dir() else 'small'
    try:
        from .room_map import room_mode as _rmode2
        _mode_key = _rmode2(room)
        if _mode_key == 'large' and room.width_cm * room.depth_cm / 10_000 >= \
                float(((cfg.get('budget_by_mode') or {}).get('large_xl') or {}).get('min_m2', 40)):
            _mode_key = 'large_xl'
    except Exception:
        pass
    _fam_order = list((_fam_cfg.get('preferred_order') or {}).get(_mode_key, []))
    if _mode_key not in (cfg.get('family_enabled_modes') or ['large', 'large_xl']):
        _fam_order = []                       # small/transitional — обычный beam
    _max_full = int((cfg.get('full_chain_cap') or {}).get(_mode_key, 4))   # ЕДИНЫЙ cap
    _cert = {'families': {}, 'one_sided': {'allowed': None, 'reason': None},
             'budget': {'cap': _max_full, 'attempted': 0, 'exhausted': False}, 'mode': _mode_key}
    _step_by_id = {g['id']: g for g in steps_all}
    _fam_done = 0
    # P3 свода №12: режимы медиа как гипотезы — 'installation' только в large и при
    # носителе+компаньонах в банке (иначе дубликат)
    _media_modes = ['single']
    try:
        from .room_map import room_mode as _rmi
        _roles = {i.role.split(' ')[0] for i in items}
        if _rmi(room) == 'large' and (_roles & {'стенка', 'тв-тумба'}) \
                and (_roles & {'витрина', 'стеллаж', 'комод'}) \
                and os.environ.get('LAYOUT_MEDIA_INSTALLATION', '1') != '0':
            _media_modes.append('installation')
    except Exception:
        pass
    _seen = set()
    _contrib = 0
    _full_attempts = 0

    def _family_shapes(fam):
        spec = _fam_cfg.get(fam) or {}
        out_ = []
        for gid in spec.get('groups', []):
            if gid not in _step_by_id:
                continue
            g_ = _step_by_id[gid]
            if g_.get('status') == 'shadow_alternative':
                continue                       # sofa_4armchairs — только shadow (Q3)
            sh_all = list(g_.get('shapes') or ['default'])
            sh = spec.get('shapes')
            if sh == '*' or sh is None:
                sh_sel = [x for x in sh_all if x not in (spec.get('shapes_exclude') or [])]
            else:
                sh_sel = [x for x in sh_all if x in sh]
            if sh_sel:
                out_.append((g_, tuple(sh_sel)))
        return out_

    def _full_ok(outs_):
        if not outs_ or not outs_[0].placements:
            return False
        from .validate import Severity as _Sv
        if any(v.severity is _Sv.HARD for v in outs_[0].violations):
            return False
        roles_ = {p.role.split(' ')[0] for p in outs_[0].placements}
        if needs.get('media') == 'required' and any(i.role.split(' ')[0] in ('тв-тумба', 'стенка') for i in items) \
                and not (roles_ & {'тв-тумба', 'стенка'}):
            return False
        return True

    for fam in _fam_order:
        if _full_attempts >= _max_full:
            _cert['budget']['exhausted'] = True
            break
        spec = _fam_cfg.get(fam) or {}
        rec = _cert['families'].setdefault(fam, {'inventory_complete': False, 'block_generated': 0,
                                                 'full_attempted': 0, 'full_valid': 0, 'reject_codes': []})
        pairs = _family_shapes(fam)
        _req_roles = spec.get('requires_roles') or []
        if _req_roles and not all(any(i.role == rr for i in items) for rr in _req_roles):
            rec['reject_codes'].append('inventory_incomplete:requires_roles')
            pairs = []                                # Q5: reserved-слот освобождается
        if not pairs:
            rec['reject_codes'].append('inventory_incomplete')
            continue
        rec['inventory_complete'] = True
        for g_, shapes_ in pairs:
            if _full_attempts >= _max_full:
                break
            _fk = int(((cfg.get('family_enumerate_k') or {}).get(fam)
                       or (cfg.get('family_enumerate_k') or {}).get('_default') or 1))
            variants = _pt(room, g_['id'], list(items), usable_polygon(room),
                           enumerate_k=_fk, shape_filter=shapes_) or []
            if not variants:
                # Q5 (Codex, разбор two_sofa 32×block_infeasible): различать НЕПОДДЕРЖИВАЕМЫЙ подтип
                # (угловой главный диван — guard build_block) от реальной геометрии
                _main_sofa = next((i for i in items if i.role == 'диван'), None)
                if getattr(_main_sofa, 'corner', False) and fam == 'two_sofa':
                    rec['reject_codes'].append(f"unsupported_subtype:corner_main:{g_['id']}")
                else:
                    rec['reject_codes'].append(f"block_infeasible:{g_['id']}")
                continue
            rec['block_generated'] += len(variants)
            blk = variants[0]
            key = tuple(sorted((q.role, round(q.x), round(q.y), int(q.rot) % 360) for q in blk))
            if key in _seen:
                continue
            _seen.add(key)
            _full_attempts += 1
            _cert['budget']['attempted'] = _full_attempts
            rec['full_attempted'] += 1
            try:
                outs, gid = solve_zoned(room, items, _hyp={'group': g_['id'], 'block': blk}, **kw)
            except Exception as e:
                rec['reject_codes'].append(f'chain_error:{type(e).__name__}')
                continue
            if not _full_ok(outs):
                rec['reject_codes'].append('full_chain_invalid')
                continue
            if spec.get('require_zone') and spec['require_zone'] not in (gid or ''):
                rec['reject_codes'].append(f"missing_zone:{spec['require_zone']}")
                if 'qz' in str(spec['require_zone']):
                    from . import template as _tqd
                    rec['quiet_diag'] = dict(getattr(_tqd, 'QUIET_DIAG', {}) or {})
                continue
            rec['full_valid'] += 1
            _fam_done += 1
            _nm = f"{fam}:{g_['id']}#{getattr(blk[0], 'tpl_variant', '') or shapes_[0]}"
            cands.append((_nm, gid, outs,
                          plan_key(room, outs[0], needs, seat_rank=_rank.get(g_['id'], 0))))
            break                                # одна лучшая позиция на семейство
    # Q5 свода №13: сертификат ВТОРОГО POD (для 40+ м² — обязателен): full_valid | inventory_gap |
    # quality_rejected | template_infeasible | search_budget_exhausted — из записи семейства
    # compact_media_plus_quiet (в полной цепочке place_quiet уже вызывается; второй прогон не нужен)
    _sp = _cert['families'].get('compact_media_plus_quiet') or {}
    _sp_state = ('full_valid' if _sp.get('full_valid', 0) > 0
                 else 'inventory_gap' if any(str(c).startswith('inventory_incomplete') for c in _sp.get('reject_codes', []))
                 else 'quality_rejected' if (_sp.get('quiet_diag') or {}).get('quality_rejected')
                 else 'pod_not_placed' if any('missing_zone' in str(c) for c in _sp.get('reject_codes', []))
                 else 'template_infeasible' if _sp.get('block_generated', 0) == 0 and _sp.get('inventory_complete')
                 else 'search_budget_exhausted' if _sp.get('inventory_complete') and _sp.get('full_attempted', 0) == 0
                 else ('not_applicable' if not _fam_order else 'quality_rejected'))
    _cert['second_pod'] = {'state': _sp_state,
                           'quiet_diag': (None if _sp_state == 'full_valid' else _sp.get('quiet_diag')),
                           'required': bool(room.width_cm * room.depth_cm / 10_000 >=
                                            float((zone_rules().get('seating_pods') or {}).get('second_pod_certificate_min_m2', 40)))}
    # one-sided fallback: разрешён только если ВСЕ предпочтительные семейства сертифицированно недостижимы
    _pref = [f for f in _fam_order]
    _all_unreach = bool(_pref) and all(
        (not _cert['families'].get(f, {}).get('inventory_complete'))
        or _cert['families'].get(f, {}).get('block_generated', 0) == 0
        or (_cert['families'].get(f, {}).get('full_attempted', 0) >= 1
            and _cert['families'].get(f, {}).get('full_valid', 0) == 0)
        for f in _pref)
    _cert['one_sided']['allowed'] = bool(_all_unreach and not _cert['budget']['exhausted'])
    _cert['one_sided']['reason'] = ('preferred_certified_unreachable' if _all_unreach
                                    else ('preferred_family_unattempted' if not _pref else 'preferred_reachable'))
    if _cert['budget']['exhausted'] and not _all_unreach:
        _cert['one_sided']['reason'] = 'SEARCH_GAP_COMPOSITION'
    _step_tries = 0
    _fam_valid_total = sum(1 for v in _cert['families'].values() if v.get('full_valid', 0) > 0)
    _skip_general = bool(_fam_order) and _fam_valid_total >= int(cfg.get('fallback_min_full_valid_families', 2))
    # BREADTH-FIRST (Codex, бюджет Q3): сперва перечисление (дёшево, без полных цепочек) по
    # contributing-ступеням, затем полные прогоны по РАНГАМ — все #0, потом все #1… — чтобы при
    # малом cap столовая/зона на ДРУГОЙ ступени нашлась раньше вторых позиций первой (set9/14/8/26:
    # dining была 8–9-й гипотезой при depth-first).
    _enum_by_step = []
    for g in ([] if _skip_general else steps):
        if _contrib >= K_steps or _step_tries >= 2 * K_steps:
            break
        if g.get('status') == 'shadow_alternative':
            continue                    # Q3: sofa_4armchairs — только shadow-контрфактуал
        _step_tries += 1
        variants = _pt(room, g['id'], list(items), usable_polygon(room),
                       enumerate_k=K_blocks) or []
        if variants:
            _contrib += 1
            _enum_by_step.append((g, variants))
    _max_rank = max((len(v) for _, v in _enum_by_step), default=0)
    for _rank_i in range(_max_rank):
      for g, variants in _enum_by_step:
        if _rank_i >= len(variants) or _full_attempts >= _max_full:
            continue
        vi, blk = _rank_i, variants[_rank_i]
        if True:
            key = tuple(sorted((q.role, round(q.x), round(q.y), int(q.rot) % 360) for q in blk))
            if key in _seen:
                continue
            _seen.add(key)
            # инсталляция — только для ПЕРВОГО варианта блока ступени (бюджет large:
            # ×2 на все варианты дало TIMEOUT set111-base/pylons)
            for _mm in (_media_modes if vi == 0 else ['single']):
                if _full_attempts >= _max_full:      # ЕДИНЫЙ cap: family + general + /inst
                    break
                # one-sided формы — только по сертификату (Q3)
                _var0 = (getattr(blk[0], 'tpl_variant', '') or '').split('+')[0]
                _os = _fam_cfg.get('one_sided_fallback') or {}
                _is_one_sided = (g['id'] in _os.get('groups', []) and _var0 in _os.get('shapes', [])) or \
                    (g['id'] in (_os.get('also') or {}).get('groups', []) and _var0 in (_os.get('also') or {}).get('shapes', []))
                if _is_one_sided and _fam_order and not _cert['one_sided']['allowed']:
                    continue
                from . import template as _tmm
                _tmm.MEDIA_MODE[0] = _mm
                try:
                    _full_attempts += 1
                    outs, gid = solve_zoned(room, items, _hyp={'group': g['id'], 'block': blk}, **kw)
                except Exception as e:           # гипотеза упала — не роняем сцену
                    if os.environ.get('ZONES_DEBUG'):
                        import sys as _s
                        print(f'ZDBG beam: гипотеза {g["id"]}#{vi}/{_mm} упала: {e!r}',
                              file=_s.stderr, flush=True)
                    continue
                finally:
                    _tmm.MEDIA_MODE[0] = 'single'
                if not outs or not outs[0].placements:
                    continue
                if _mm == 'installation' and not any(
                        getattr(p, 'tpl_variant', '') == 'installation' for p in outs[0].placements):
                    continue                     # инсталляция не встала — дубликат single, не считаем
                _var_nm = (getattr(blk[0], 'tpl_variant', '') or '').split('+')[0]
                _nm = f'{g["id"]}#{vi}' + (f':{_var_nm}' if _var_nm and _var_nm != 'default' else '') \
                    + ('/inst' if _mm == 'installation' else '')
                _cert['budget']['attempted'] = _full_attempts
                cands.append((_nm, gid, outs,
                              plan_key(room, outs[0], needs, seat_rank=_rank.get(g['id'], 0))))
    if not cands:
        return base_outs, base_gid
    # детерминированный порядок: ключ, затем стабильный индекс (greedy первым при равенстве)
    # Q4 свода №13: plan_key_v2 (SHADOW) — считаем для всех кандидатов и пишем в trace;
    # выбор по v2 включается данными (beam.plan_key_version == 'v2') только после Q7
    # LAYOUT_PLAN_KEY=v2 — временный переключатель для СЛЕПОЙ ОЦЕНКИ Q7 (пары v1 vs v2);
    # production-значение остаётся в данных (beam.plan_key_version) и меняется только по итогу Q7
    _pkv = os.environ.get('LAYOUT_PLAN_KEY') or str(cfg.get('plan_key_version', 'v1'))
    def _valid_arm_of(c):
        try:
            from .view_metrics import valid_connected_armchairs as _vca
            return int(_vca(room, list(c[2][0].placements)).get('valid_count', 0))
        except Exception:
            return 0
    _reach_arm = max((_valid_arm_of(c) for c in cands if c[2] and c[3][0] == 0), default=None)
    def _enriched_of(c):
        try:
            ps_ = list(c[2][0].placements)
            sofas_ = sum(1 for p in ps_ if p.role.split(' ')[0] == 'диван')
            return sofas_ >= 2 or _valid_arm_of(c) >= 2 or any(getattr(p, 'tpl_id', '') == 'quiet' for p in ps_)
        except Exception:
            return False
    _reach_enrich = any(_enriched_of(c) for c in cands if c[2] and c[3][0] == 0) if cands else None
    _reach = {'armchairs_reachable': _reach_arm, 'enrichment_reachable': _reach_enrich,
              'media_seat_reachable': any(
                  (getattr(p, 'tpl_variant', '') or '').split('+')[0] in ('media_parallel', 'media_half', 'media_bridge')
                  for c in cands for p in (c[2][0].placements if c[2] else [])),
              'shadow_hyp': bool(cfg.get('shadow_hypothesis_tiers', False))}
    # Q9 (тень, Codex 18.08): ключ ПРИОРОВ ПРАКТИКИ по каждой гипотезе — только измерение,
    # production-выбор не трогаем до слепых пар (включение = отдельное решение владельца)
    _pp = []
    for c in cands:
        try:
            from .opportunities import practice_prior_key as _ppk
            _pp.append(_ppk(room, list(c[2][0].placements)) if c[2] else None)
        except Exception:
            _pp.append(None)
    _cap = []
    for c in cands:
        try:
            _cap.append(plan_key_capacity(room, c[2][0], needs, c[1], items) if c[2] else None)
        except Exception as _e:
            if os.environ.get('ZONES_DEBUG'):
                import sys as _sc
                print(f'ZDBG capacity-ключ не посчитан: {type(_e).__name__}: {_e}', file=_sc.stderr, flush=True)
            _cap.append(None)
    _v2 = []
    for c in cands:
        try:
            _v2.append(plan_key_v2(room, c[2][0], needs, reach=_reach))
        except Exception:
            _v2.append(None)
    if _pkv == 'v2' and cands and all(v is not None for v in _v2):
        order = sorted(range(len(cands)), key=lambda i: (_v2[i], i))
    else:
        order = sorted(range(len(cands)), key=lambda i: (cands[i][3], i))
    best_i = order[0]
    name, gid, outs, key = cands[best_i]
    trace = {'hypotheses': [{'name': c[0], 'gid': c[1], 'key': list(c[3]),
                             'key_v2': (list(_v2[i]) if _v2[i] is not None else None)} for i, c in enumerate(cands)],
             'plan_key_version': _pkv,
             'v2_would_choose': (cands[sorted(range(len(cands)), key=lambda i: (_v2[i], i))[0]][0]
                                 if cands and all(v is not None for v in _v2) else None),
             'capacity_would_choose': (cands[sorted(range(len(cands)), key=lambda i: (_cap[i], i))[0]][0]
                                       if cands and all(x is not None for x in _cap) else None),
             'capacity_keys': [list(x) if x is not None else None for x in _cap],
             'practice_prior_shadow': [list(x) if x is not None else None for x in _pp],
             'prior_would_choose': (cands[sorted(range(len(cands)), key=lambda i: (_pp[i], i))[0]][0]
                                    if cands and all(x is not None for x in _pp) else None),
             'chosen': name, 'chosen_key': list(key),
             'greedy_key': list(cands[0][3]) if cands[0][0] == 'greedy' else None,
             'improved': bool(cands[0][0] == 'greedy' and best_i != 0)}
    # сертификат: классы, недостижимые НИ В ОДНОЙ гипотезе (для объяснимости)
    cert = {}
    for zname, tag in (('dining', '+din'), ('media', '+tv'), ('quiet', '+qz')):
        cert[zname] = any(tag in c[1] for c in cands)
    trace['reachable'] = cert
    trace['composition_certificate'] = _cert     # Q3: семейства/бюджет/one-sided
    for l in outs:
        if isinstance(getattr(l, 'meta', None), dict):
            l.meta['beam'] = trace
            # ОБЪЯСНИМОСТЬ (тест pouf_wins_are_explained, V4-B2): трейс лестницы
            # победителя дополняется записями о КАЖДОЙ перебранной beam-ступени
            # (generated/hard_valid/лучший ключ) — «почему богаче не победила»
            ss = l.meta.get('seating_search')
            if isinstance(ss, dict):
                for c in cands:
                    gname = c[0].split('#')[0] if c[0] != 'greedy' else (c[1] or '').split('+')[0]
                    rec = ss.setdefault(gname, {'id': gname})
                    rec['generated'] = 1
                    okh = int(c[3][0] == 0 and c[3][1] == 0)
                    rec['hard_valid'] = max(int(rec.get('hard_valid') or 0), okh)
                    bk = list(c[3])
                    if rec.get('beam_best_key') is None or bk < rec['beam_best_key']:
                        rec['beam_best_key'] = bk
                # победитель beam — единственный winner в трейсе
                win_group = name.split('#')[0] if name != 'greedy' else (gid or '').split('+')[0]
                for gk, rec2 in ss.items():
                    if not isinstance(rec2, dict):
                        continue
                    if gk == win_group:
                        rec2['winner'] = True
                        rec2['beam_winner'] = name
                    elif rec2.get('winner'):
                        rec2['winner'] = False
                        rec2['lost_to_beam'] = name
    return outs, gid
