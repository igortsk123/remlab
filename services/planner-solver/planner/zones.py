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
    ladder = [g for g in zr.get('seating_ladder', {}).get('ladder', []) if g in groups]
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


def solve_zoned(room: Room, items, **kw):
    """Обёртка dining_sacrifice (правило владельца 14.08, разбор Плана №19):
    столовая не встала, стол в банке → пересбор с посадкой на СТУПЕНЬ НИЖЕ;
    принимаем, только если столовая встала, медиа сохранена и качество не хуже
    (гейт not_worse). Остаток после столовой — зонам хранения (порядок цепочки
    прежний). Конфиг — rules/zones.json → dining_sacrifice."""
    outs, gid = _solve_zoned_core(room, items, **kw)
    cfg = zone_rules().get('dining_sacrifice', {})
    if not cfg.get('enabled', False) or '+din' in gid:
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
    for _skip in range(1, int(cfg.get('max_steps_down', 2)) + 1):
        outs2, gid2 = _solve_zoned_core(room, items, _ladder_skip=_skip, **kw)
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


def _solve_zoned_core(room: Room, items, _ladder_skip: int = 0, **kw):
    """Z3, уровень 1 (MVP): сначала выбирается посадочная ГРУППА по полезной площади, затем
    beam решает предметы; посадочные роли вне группы не размещаются «лишь бы стоять», а честно
    уходят в skipped_optional. Старый solve() нетронут — A/B на перегоне.

    Возвращает (layouts, group_id)."""
    from collections import Counter

    from .beam import solve
    from .invariants import phantom_dimensions
    from .quality import not_worse as _not_worse
    from .quality import scene_quality as _quality
    from . import template as _tplmod
    _tplmod.LAST_DINING_DIAG = None      # пакет B: свежий диагноз dining на каждый прогон
    _tplmod.LAST_MIRROR_STATS = None     # V3-H: счётчики зеркал — per solve
    _tplmod.LAST_SEATING_SEARCH = None   # V4-B2: трейс лестницы — per solve
    os.environ.pop('_SCREEN_WINDOW_WAIVED', None)   # пакет D: вейвер экрана — per solve
    avail = {_base(i.role) for i in items}
    counts = Counter(_base(i.role) for i in items)
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
            _sseek = {d['id']: dict(d) for d in _seat_diag}
            _tplmod.LAST_SEATING_SEARCH = _sseek
            for _g in _ladder_steps:
                _se = _sseek.setdefault(_g['id'], {'id': _g['id']})
                _blk = place_template(room, _g['id'], keep, usable_polygon(room))
                _se['generated'] = 1
                _se['hard_valid'] = 1 if _blk else 0
                if not _blk:
                    continue
                if _has_bearer0:
                    from .template import place_media as _pm0
                    _occ0 = _uu0([_fp0(p) for p in _blk if p.role.split(' ')[0] != 'ковёр'])
                    _m0 = _pm0(room, keep,
                               usable_polygon(room).difference(_occ0), fixed=_blk)
                    _se['media_min'] = 1 if _m0 else 0
                    if not _m0:
                        if _fb_block is None:
                            _fb_block, _fb_group = _blk, _g
                        if os.environ.get('ZONES_DEBUG'):
                            import sys as _sl
                            print(f"ZDBG лестница: ступень {_g['id']} встала, но БЕЗ "
                                  f"медиа — пробуем следующую", file=_sl.stderr, flush=True)
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
                    os.environ['_SCREEN_WINDOW_WAIVED'] = '1'
                    from .template import place_media as _pmw
                    _occw = _uu0([_fp0(p) for p in block
                                  if p.role.split(' ')[0] != 'ковёр'])
                    _mw = _pmw(room, keep,
                               usable_polygon(room).difference(_occw), fixed=block)
                    if _mw:
                        block = list(block) + list(_mw)
                        keep = [it for it in keep
                                if it.role not in {p.role for p in _mw}]
                        if os.environ.get('ZONES_DEBUG'):
                            import sys as _sl
                            print('ZDBG лестница: медиа встала ПО ВЕЙВЕРУ экрана '
                                  '(+tvw)', file=_sl.stderr, flush=True)
                    else:
                        os.environ.pop('_SCREEN_WINDOW_WAIVED', None)
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
                            os.environ.pop('_SCREEN_WINDOW_WAIVED', None)
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
                               place_bay_armchair, place_reading, place_storage)
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
            tpl_tag += ('+tvw' if os.environ.get('_SCREEN_WINDOW_WAIVED') == '1'
                        else '+tv')
        for placer, tag in ((place_media_fireplace, '+tvfp'), _order[0], _order[1],
                            (_din, '+din'), (place_storage, '+st'),
                            # НЕ БОЛЕЕ ДВУХ зон хранения на гостиную (владелец 12.08)
                            (place_storage, '+st2'),
                            (place_quiet, '+qz'), (place_reading, '+rd'),
                            (place_bay_armchair, '+bay'),
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
            _cardc = (_zp.get('cardinality') or {}).get(_zt.get(tag, '')) or {}
            if _cardc.get('rule') == 'exactly_one_carrier' and any(
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
            extra = placer(room, keep, _free_z, fixed=block)
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
                os.environ['_SCREEN_WINDOW_WAIVED'] = '1'
                _extra = _pm(room, keep, usable_polygon(room).difference(occ3),
                             fixed=block, relaxed=True)
                if _extra:
                    roles3 = {p.role for p in _extra}
                    keep = [it for it in keep if it.role not in roles3]
                    block = block + _extra
                    _refine_mod.LOCKED |= roles3
                    tpl_tag += '+tvw'
                else:
                    os.environ.pop('_SCREEN_WINDOW_WAIVED', None)

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
                try:
                    import planner.candidates as _cmod
                    _orig_mid = _cmod.middle_candidates
                    _cmod.middle_candidates = lambda *a, **k: []   # только пристенные
                    _blk2 = _pt2(room, group['id'],
                                 [i for i in items if i.role in
                                  {p.role for p in block} | {it.role for it in keep}],
                                 usable_polygon(room))
                finally:
                    _cmod.middle_candidates = _orig_mid
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
