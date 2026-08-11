"""Э2: генератор позиций-кандидатов.

Стратегия по роли (а не по конкретному товару — правило владельца «только масштабируемое»):
у стены / в углу / относительно якоря (зона-билдер как anchor-based generation) / в середине
свободного прямоугольника. Ориентации — только осевые. Кандидаты, не влезающие в свободный
полигон, отбрасываются ДО скоринга (ProcTHOR: фильтр размера предшествует сэмплингу).

ПРАВИЛО АТОМАРНОСТИ ШАБЛОНА (владелец, 11.08 — действует во всём движке):
    ШАБЛОН СТАВИТСЯ ЦЕЛИКОМ ИЛИ НЕ СТАВИТСЯ ВОВСЕ.
Выбрасывать предмет ИЗ шаблона запрещено. Не влез — берём ДРУГОЙ шаблон меньшего
состава (столовая 6→4→2, хранение 3→2→1, посадка диван+2 кресла→диван+кресло→соло).
Формулировка «предмет не поставился» недопустима: не ставится ШАБЛОН. Предметы
комплекта вне выбранного шаблона — ИЗБЫТОК КОМПЛЕКТА, не ошибка расстановки.
Пруф и примеры: services/planner-solver/rules/zones.json → template_atomicity.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import Polygon
from shapely.prepared import prep

from .clearances import (LOW_ITEM_MAX_H_CM, NEVER_BLOCKING_ROLES, band_scale, distances,
                         rules)
from .geometry import base_role, blocked_footprint, footprint, free_space, largest_free_rectangles, room_polygon
from .models import Item, Placement, Room

GRID_CM = 25.0          # шаг скольжения вдоль стены (Holodeck DFS работал на 15 см;
                        # 25 см достаточно: локальное уточнение Э4 добирает точность)
WALL_GAP_CM = 5.0       # технологический зазор от стены (ProcTHOR padding 5 см)

# приоритет размещения: якоря зоны первыми (PT: PRIORITY_ASSET_TYPES для LivingRoom)
# ТВ-зона первой: ТВ-тумба самая ограниченная (только у стены) и задаёт ось зоны —
# ProcTHOR ставит Television первым в PRIORITY_ASSET_TYPES гостиной по той же причине.
# порядок: ось зоны (ТВ, диван) → крупное пристенное хранение → наполнение зоны → мелочь
# ЯДРО ЗОНЫ ВПЕРЁД (гейт 11.08): ковёр и столик — часть посадочной зоны, а не
# наполнение. Прежний порядок ставил корпусную мебель (шкаф/комод/витрина/стеллаж)
# раньше них, и после обогащения сетов ядро оставалось без места: 26 сцен без ковра,
# 17 без столика. Теперь: ось зоны (ТВ, диван) → ядро зоны → посадка → хранение → мелочь.
ROLE_ORDER = ["тв-тумба", "диван", "стенка", "камин", "столик", "ковёр", "кресло",
              "пуф", "шкаф", "комод", "витрина", "стеллаж", "стол обеденный", "стул",
              "торшер", "кашпо"]

WALLS = ("north", "south", "west", "east")
# роли, которым разрешён «отплыв» от стены (наш narrow_room.float_from_wall + проход за спинкой)
FLOATABLE = frozenset({"диван"})
FLOAT_OFFSETS_CM = (0.0, 80.0, 130.0, 180.0)   # 0 = к стене; далее — только с проходом ≥76 см
# поворот, при котором «лицо» смотрит от стены внутрь комнаты
WALL_FACING_ROT = {"north": 180, "south": 0, "west": 90, "east": 270}


@dataclass(frozen=True)
class Candidate:
    placement: Placement
    kind: str          # wall | corner | anchor | middle
    note: str = ""
    # L2 (мета-план layout-v5): структурная топология кандидата. Управляющая логика читает ЕЁ,
    # note — только человекочитаемая подпись (раньше фильтр парсил русские подстроки note).
    # Значения: pair_mirror | pair_side | pair_fireplace_flank | fireplace_flank | arc | ...
    topology: str = ""
    # L3: joint-кандидат группы — доп. размещения, ставящиеся АТОМАРНО вместе с placement
    # (пара кресел одним ходом луча). Пустой кортеж = обычный одиночный кандидат.
    extra: tuple[Placement, ...] = ()


def role_rank(role: str) -> int:
    role = base_role(role)
    return ROLE_ORDER.index(role) if role in ROLE_ORDER else len(ROLE_ORDER)


def order_items(items: list[Item], *, corner_sofa_first: bool = True) -> list[Item]:
    """H3-фикс (08.08, set113): стенка-НОСИТЕЛЬ ТВ (тумбы в составе нет) размещается в
    приоритете тумбы — ПЕРВОЙ: иначе диван ориентируется в никуда, и все позиции стенки
    бьются о его прицел (FACING/AIM/DIST) — богатый состав рушился каскадом до 3 предметов."""
    """Порядок размещения: сначала якоря зоны, внутри группы — крупные первыми.

    С Г-диваном порядок обратный: ДИВАН определяет комнату (канон «строго в угол»), а ТВ-тумба
    якорится к нему. При старом порядке ТВ вставала по центру стены первой, и ВСЕ угловые
    позиции дивана гибли на шкале диван↔ТВ — Г-диван оседал посреди стены (перегон 2026-08-06).
    В БОЛЬШОЙ комнате угол и шкала ТВ несовместимы — там beam пере-решает старым порядком
    (`corner_sofa_first=False`), это делает solve()."""
    has_corner_sofa = (corner_sofa_first
                       and any(it.role == "диван" and it.corner for it in items))

    has_stand = any(it.role == "тв-тумба" for it in items)
    wall_unit_is_bearer = (not has_stand) and any(it.role == "стенка" for it in items)

    def rank(it: Item) -> float:
        if has_corner_sofa and it.role == "диван":
            return -1
        if wall_unit_is_bearer and it.role == "стенка":
            return -0.5    # приоритет носителя ТВ (как у тумбы), после Г-дивана-якоря
        return role_rank(it.role)

    return sorted(items, key=lambda it: (rank(it), -(it.w_cm * it.d_cm)))


def _dims_for_rot(item: Item, rot: float) -> tuple[float, float]:
    return (item.d_cm, item.w_cm) if int(rot) % 180 == 90 else (item.w_cm, item.d_cm)


class _Fitter:
    """Подготовленная геометрия свободного места: contains() в разы дешевле сырого полигона."""

    def __init__(self, room: Room, free: Polygon):
        self.free = prep(free.buffer(1))

    def __call__(self, cand: Placement) -> bool:
        return self.free.contains(footprint(cand))


def _fits(room: Room, cand: Placement, free) -> bool:
    return free(cand) if callable(free) else _Fitter(room, free)(cand)


def wall_candidates(room: Room, item: Item, free: Polygon, *, step: float = GRID_CM) -> list[Candidate]:
    """Скольжение спинкой вдоль КАЖДОГО РЕБРА контура (Э8: работает и на Г/П-контурах).

    Для прямоугольника рёбра совпадают с 4 стенами (та же геометрия, что и раньше). Косые
    рёбра пока пропускаются ([[layout-polygon-rooms]], следующий шаг — неквантованные повороты)."""
    import math as _m

    from .geometry import room_edges
    # T3 (solver-speed, п.1): АДАПТИВНЫЙ ШАГ — крупная комната перебирается грубее,
    # точность добивает refine (он двигает предметы шагами 10 см и мельче).
    # Ступени по площади: ≤40 м² — базовый 25 см; 40–60 — ×2; >60 — ×3.
    # Дополнительно шаг не мельче 1/12 габарита предмета: скользить диван 285 см
    # с шагом 25 см бессмысленно — соседние позиции неразличимы для правил.
    if step <= GRID_CM:
        _m2 = room.width_cm * room.depth_cm / 10_000
        if _m2 > 60:
            step *= 3
        elif _m2 > 40:
            step *= 2
        step = max(step, min(item.w_cm, item.d_cm) / 12.0)
    out: list[Candidate] = []
    for ei, ((x1, y1), (x2, y2)) in enumerate(room_edges(room)):
        ex, ey = x2 - x1, y2 - y1
        elen = _m.hypot(ex, ey)
        if elen < 40:
            continue
        if abs(ex) > 1 and abs(ey) > 1:
            continue                      # косое ребро — Э8 следующий шаг
        nx, ny = -ey / elen, ex / elen    # внутренняя нормаль (контур CCW)
        rot = _m.degrees(_m.atan2(nx, ny)) % 360
        # T3-фикс (10.08): предмет у стены ВСЕГДА идёт шириной вдоль ребра, глубиной поперёк
        # (фасад параллелен стене). Прежний _dims_for_rot давал МИРОВЫЕ x/y-экстенты — для
        # вертикальных рёбер «вдоль/поперёк» инвертировались, кандидат висел в w/2 от стены
        # и гиб (SLIVER): эмпирика 252 сцен — ноль диванов r90/270, полкомнаты недоступно.
        w, d = item.w_cm, item.d_cm
        if w + 2 * WALL_GAP_CM > elen:
            continue
        lo, hi = WALL_GAP_CM + w / 2, elen - WALL_GAP_CM - w / 2
        n = max(1, int((hi - lo) // step))
        offs = [lo + i * (hi - lo) / n for i in range(n + 1)]
        floats = FLOAT_OFFSETS_CM if item.role in FLOATABLE else (0.0,)
        for off in offs:
            for fl in floats:
                dist = d / 2 + fl
                x = x1 + ex / elen * off + nx * dist
                y = y1 + ey / elen * off + ny * dist
                p = Placement(role=item.role, x=x, y=y, rot=rot, item=item)
                if not _fits(room, p, free):
                    continue
                if fl == 0:
                    is_corner = off <= lo + step / 2 or off >= hi - step / 2
                    out.append(Candidate(p, "corner" if is_corner else "wall", f"ребро {ei}"))
                else:
                    out.append(Candidate(p, "wall", f"ребро {ei}, отплыв {fl:.0f} см"))
    return out


def _wall_xy(room: Room, wall: str, off: float, depth: float, *, float_cm: float = 0.0) -> tuple[float, float]:
    if wall == "south":
        return off, WALL_GAP_CM + depth / 2 + float_cm
    if wall == "north":
        return off, room.depth_cm - WALL_GAP_CM - depth / 2 - float_cm
    if wall == "west":
        return WALL_GAP_CM + depth / 2 + float_cm, off
    return room.width_cm - WALL_GAP_CM - depth / 2 - float_cm, off


def middle_candidates(room: Room, item: Item, free: Polygon, *, limit: int = 6,
                      fitter=None) -> list[Candidate]:
    """Центры крупнейших свободных прямоугольников (PT: макс. прямоугольники открытого полигона)."""
    out: list[Candidate] = []
    fit = fitter or _Fitter(room, free)
    for rect in largest_free_rectangles(free, min_side_cm=min(item.w_cm, item.d_cm), limit=limit):
        cx, cy = rect.centroid.x, rect.centroid.y
        for rot in (0, 90):
            p = Placement(role=item.role, x=cx, y=cy, rot=rot, item=item)
            if _fits(room, p, fit):
                out.append(Candidate(p, "middle", f"{rect.area / 10_000:.1f} м²"))
    return out


def anchor_candidates(room: Room, item: Item, placed: list[Placement], free: Polygon) -> list[Candidate]:
    """Позиции относительно уже поставленных якорей — перенос зона-билдера (ADR-0050/0051)."""
    by = {p.role: p for p in placed}
    if "тв-тумба" not in by and "стенка" in by:
        by["тв-тумба"] = by["стенка"]   # стенка = носитель ТВ (правило владельца 08.08)
    role = item.role
    # Экземпляры ролей («стул 2», «пуф 2») обязаны получать ТЕ ЖЕ якорные позиции, что и
    # базовая роль: сравнение по точному имени оставляло «стул 2..4» без мест у стола —
    # обеденная группа массово гибла на «минимум 2 стула» (вердикт владельца 08.08)
    rb = base_role(role)
    out: list[Candidate] = []

    def seat_center(anchor: Placement) -> tuple[float, float]:
        """Центр СВОБОДНОГО сегмента посадки: у Г-дивана короткое плечо занимает часть ширины,
        и столик, центрированный по всей ширине, влезает прямо в плечо (был провал сетов 38/97)."""
        if anchor.item is None or not anchor.item.corner:
            return anchor.x, anchor.y
        fx, fy = _face_dir(anchor.rot)
        # плечо занимает локальный +x, что в мировых координатах = −lateral (см. relative_position),
        # поэтому центр свободного сегмента смещаем на +lateral
        lat = anchor.item.corner_section_cm / 2
        return anchor.x + lat * (-fy), anchor.y + lat * fx

    def add(x: float, y: float, rot: float, note: str, topology: str = ""):
        # позицию от якоря КЛАМПИМ в комнату: якорь может стоять у самого края (ТВ в углу),
        # и предмет напротив вылезал за стену — кандидат молча пропадал (сеты 50+ теряли диван)
        w, d = _dims_for_rot(item, rot)
        x = min(max(x, WALL_GAP_CM + w / 2), room.width_cm - WALL_GAP_CM - w / 2)
        y = min(max(y, WALL_GAP_CM + d / 2), room.depth_cm - WALL_GAP_CM - d / 2)
        p = Placement(role=role, x=x, y=y, rot=rot, item=item)
        if _fits(room, p, free):
            out.append(Candidate(p, "anchor", note, topology))

    sofa = by.get("диван")
    tv = by.get("тв-тумба")
    if base_role(role) == "диван" and tv is not None:
        # диван напротив ТВ: ось зоны задана тумбой; дистанция — КАНОНИЧЕСКАЯ ТВ-функция
        # (verify T6: генератор обязан предлагать то, что validate примет — рефери §23);
        # узкая тумба <60 см — legacy area-шкала, как и в validate
        if (tv.item.w_cm or 0) >= 60:
            from .tv import distance_range
            lo, hi, _ = distance_range(tv.item.w_cm, bearer=base_role(tv.role))
        else:
            lo, hi = band_scale("sofa_tv_cm", room.band, distances().get("sofa_tv_cm", [180, 300]))
        fx, fy = _face_dir(tv.rot)
        tfp = footprint(tv)
        rot = (tv.rot + 180) % 360
        w, d = _dims_for_rot(item, rot)
        for frac in (0.15, 0.35, 0.55, 0.75, 0.9):
            gap = min(max(lo + (hi - lo) * frac, lo + 3), hi - 3)   # держим запас от границ шкалы
            from .geometry import seating_front_offset
            off = gap + _half_along(tfp, fx, fy) + seating_front_offset(item)
            add(tv.x + fx * off, tv.y + fy * off, rot, f"напротив ТВ, {gap:.0f} см")
    if rb == "тв-тумба" and sofa is not None:
        if (item.w_cm or 0) >= 60:
            from .tv import distance_range
            lo, hi, _ = distance_range(item.w_cm)
        else:
            lo, hi = band_scale("sofa_tv_cm", room.band, distances().get("sofa_tv_cm", [180, 300]))
        fx, fy = _face_dir(sofa.rot)
        sfp = footprint(sofa)
        for frac in (0.35, 0.5, 0.75):
            gap = min(max(lo + (hi - lo) * frac, lo + 3), hi - 3)
            w, d = _dims_for_rot(item, (sofa.rot + 180) % 360)
            scx, scy = seat_center(sofa)
            cx = scx + fx * (gap + _half_along(sfp, fx, fy) + d / 2)
            cy = scy + fy * (gap + _half_along(sfp, fx, fy) + d / 2)
            add(cx, cy, (sofa.rot + 180) % 360, f"напротив дивана, {gap:.0f} см")
    if rb == "столик" and sofa is not None:
        # T6: диван↔столик — фикс-эргономика (W2), area-шкала sofa_table_cm вычищена и из
        # ГЕНЕРАЦИИ кандидатов (рефери §23: генератор предлагал позиции, которые валидатор
        # уже не принимает — хорошая раскладка могла не попасть в пространство поиска)
        lo, hi = distances().get("sofa_coffee_table", [36, 46])
        fx, fy = _face_dir(sofa.rot)
        sfp = footprint(sofa)
        from .geometry import seating_front_offset
        scx, scy = seat_center(sofa)
        for gap in (lo + 3, (lo + hi) / 2, hi - 3):
            off = gap + seating_front_offset(sofa.item) + _dims_for_rot(item, sofa.rot)[1] / 2
            add(scx + fx * off, scy + fy * off, sofa.rot, f"перед диваном, {gap:.0f} см")
    if base_role(role) == "кресло" and role != "кресло" and by.get("камин") is not None:
        # F1+: первый уже у камина → второй — ЗЕРКАЛО относительно оси камина (другой фланг),
        # пара не разрывается между зонами (вердикт владельца set113)
        first = by.get("кресло")
        fpl0 = by["камин"]
        if first is not None and first.item is not None:
            ffx0, ffy0 = _face_dir(fpl0.rot)
            dfx, dfy = first.x - fpl0.x, first.y - fpl0.y
            lat_f = dfx * (-ffy0) + dfy * ffx0
            fwd_f = dfx * ffx0 + dfy * ffy0
            if abs(lat_f) > 20 and footprint(first).distance(footprint(fpl0)) <= 280:
                mx = fpl0.x + ffx0 * fwd_f + (-ffy0) * (-lat_f)
                my = fpl0.y + ffy0 * fwd_f + ffx0 * (-lat_f)
                tx, ty = fpl0.x + ffx0 * 150, fpl0.y + ffy0 * 150
                add(mx, my, _rot_towards(mx, my, tx, ty), "пара: другой фланг камина", "pair_fireplace_flank")
    if base_role(role) == "кресло" and role != "кресло" and sofa is not None:
        # F1 (канон пары): второе кресло — ЗЕРКАЛО первого относительно оси диван→фокус
        # или БОК-О-БОК с ним (зазор 30–45) — пара ставится паттерном, не одиночками
        first = by.get("кресло")
        if first is not None and first.item is not None:
            sfx0, sfy0 = _face_dir(sofa.rot)
            fwd0 = (first.x - sofa.x) * sfx0 + (first.y - sofa.y) * sfy0
            lat0 = (first.x - sofa.x) * (-sfy0) + (first.y - sofa.y) * sfx0
            act0 = (sofa.item.corner_section_cm / 2) if sofa.item.corner else 0.0
            mlat = 2 * act0 - lat0
            mx = sofa.x + sfx0 * fwd0 + (-sfy0) * mlat
            my = sofa.y + sfy0 * fwd0 + sfx0 * mlat
            # зеркальный разворот: отражаем направление взгляда первого кресла
            f1x, f1y = _face_dir(first.rot)
            l1 = f1x * (-sfy0) + f1y * sfx0
            mrot = math.degrees(math.atan2(f1x - 2 * l1 * (-sfy0),
                                           f1y - 2 * l1 * sfx0)) % 360
            add(mx, my, round(mrot / 90) * 90 % 360, "пара: зеркало первого кресла", "pair_mirror")
            # бок-о-бок канонен ТОЛЬКО когда кресла НАПРОТИВ дивана (лицом к нему):
            # для боковых кресел он строил «лесенку в затылок» вдоль стены (вердикт 08.08)
            if int(first.rot) % 360 == int(sofa.rot + 180) % 360:
                for gap in (30.0, 45.0):
                    off = first.item.w_cm / 2 + item.w_cm / 2 + gap
                    for sgn in (-1.0, 1.0):
                        px = first.x + (-f1y) * off * sgn
                        py = first.y + f1x * off * sgn
                        add(px, py, first.rot, "пара: бок-о-бок", "pair_side")
    if base_role(role) == "кресло" and by.get("камин") is not None:
        # D5 (fireplace corner): кресло перед камином, лицом к нему — вторичная зона.
        # Дистанция — от КРОМОК с учётом безопасной зоны камина (fireplace_clear 100 см):
        # центр кресла = фронт камина + клиренс + запас + полглубины кресла
        # Канон (decorilla/willis, 08.08): кресла ПО БОКАМ камина, развёрнуты чуть внутрь
        # (классическая U: диван напротив камина, кресла фланкируют) + резерв «перед камином»
        fpl = by["камин"]
        ffx, ffy = _face_dir(fpl.rot)
        lx, ly = -ffy, ffx           # боковое направление вдоль стены камина
        clear = float(distances().get("fireplace_clear", [100, 150])[0])
        fw = (fpl.item.w_cm if fpl.item else 110)
        fd = (fpl.item.d_cm if fpl.item else 35)
        fwd0 = fd / 2 + item.d_cm / 2 + 30      # чуть вперёд от линии камина
        for sgn in (-1.0, 1.0):                  # фланги: слева/справа от камина
            for lat in (fw / 2 + item.w_cm / 2 + 25, fw / 2 + item.w_cm / 2 + 70):
                px = fpl.x + lx * lat * sgn + ffx * fwd0
                py = fpl.y + ly * lat * sgn + ffy * fwd0
                # развёрнуто «чуть внутрь»: на точку перед камином, а не на сам камин
                tx, ty = fpl.x + ffx * (clear + fd), fpl.y + ffy * (clear + fd)
                add(px, py, _rot_towards(px, py, tx, ty), "фланг камина (вторая зона)", "fireplace_flank")
        base_off = fd / 2 + clear + item.d_cm / 2
        for extra in (10.0, 60.0):
            gap = base_off + extra
            for side in (-0.35, 0.0, 0.35):
                px = fpl.x + ffx * gap + (-ffy) * gap * side
                py = fpl.y + ffy * gap + ffx * gap * side
                add(px, py, _rot_towards(px, py, fpl.x, fpl.y), "у камина (вторая зона)", "fireplace_front")
    if base_role(role) == "кресло" and sofa is not None:
        # D3 (Swyft/Dimensions): позиции НАПРОТИВ дивана, слегка внутрь — канонная
        # разговорная посадка (в дополнение к дуге 135–225)
        sfx, sfy = _face_dir(sofa.rot)
        scx0, scy0 = seat_center(sofa)
        # E5: в media-комнате «напротив дивана» стоит ЭКРАН — позиции только если ТВ-носителя
        # нет на оси взгляда дивана (иначе кресло залезает в коридор просмотра, set113)
        _tvb = by.get("тв-тумба") or by.get("стенка")
        _axis_tv = False
        if _tvb is not None:
            _vx, _vy = _tvb.x - sofa.x, _tvb.y - sofa.y
            _nn = math.hypot(_vx, _vy)
            _axis_tv = _nn > 1 and (_vx * sfx + _vy * sfy) / _nn > 0.5
        if not _axis_tv:
            for gap in (170.0, 210.0, 244.0):
                for side in (-0.3, 0.3):
                    px = scx0 + sfx * gap + (-sfy) * (sofa.item.w_cm / 3) * side
                    py = scy0 + sfy * gap + sfx * (sofa.item.w_cm / 3) * side
                    add(px, py, (_rot_towards(px, py, scx0, scy0)), "напротив дивана", "opposite_sofa")
    if base_role(role) == "кресло" and sofa is not None:
        out += _arc_candidates(room, item, by, free, sofa)
    if rb == "пуф" and ("столик" in by or sofa is not None):
        anchor = by.get("столик") or sofa
        # каноничное место — ЗА столиком (столик между диваном и пуфом): продолжение оси
        # диван→столик; плюс сбоку от столика вне оси просмотра
        if anchor.role == "столик" and sofa is not None:
            ddx, ddy = anchor.x - sofa.x, anchor.y - sofa.y
            n = max((ddx * ddx + ddy * ddy) ** 0.5, 1e-6)
            ux, uy = ddx / n, ddy / n
            aw, ad = _dims_for_rot(anchor.item, anchor.rot)
            iw, id_ = _dims_for_rot(item, anchor.rot)
            ahalf = abs(ux) * aw / 2 + abs(uy) * ad / 2
            ihalf = abs(ux) * iw / 2 + abs(uy) * id_ / 2
            for gap in (25.0, 45.0):
                add(anchor.x + ux * (gap + ahalf + ihalf), anchor.y + uy * (gap + ahalf + ihalf),
                    anchor.rot, f"за столиком, {gap:.0f} см")
        for ang in (90, 270):                      # сбоку от столика, ВНЕ оси просмотра
            fx, fy = _face_dir((anchor.rot + ang) % 360)
            # отступ — по ФАКТИЧЕСКОЙ полуширине вдоль направления, а не по max-габариту:
            # max-формула давала футпринт-гэп 61–80 см при пороге pouf_table_max=60, и пуф
            # массово браковался (перегон 2026-08-06, А5)
            rot_i = (anchor.rot + ang + 180) % 360
            aw, ad = _dims_for_rot(anchor.item, anchor.rot)
            iw, id_ = _dims_for_rot(item, rot_i)
            ahalf = abs(fx) * aw / 2 + abs(fy) * ad / 2
            ihalf = abs(fx) * iw / 2 + abs(fy) * id_ / 2
            for gap in (25.0, 45.0):
                add(anchor.x + fx * (gap + ahalf + ihalf), anchor.y + fy * (gap + ahalf + ihalf),
                    rot_i, f"сбоку от столика, {gap:.0f} см")
    if rb == "кашпо":
        # Функциональные места декора (вердикт владельца 2026-08-07: «кашпо за диваном» — брак):
        # у окна, сбоку от ТВ-тумбы, у кресла — ВИДИМЫЕ точки зоны, не мёртвые углы.
        half = max(item.w_cm, item.d_cm) / 2
        for op in room.openings:
            if op.kind != "window":
                continue
            mid = op.offset_cm + op.width_cm / 2
            off = half + 18
            wx, wy = {"south": (mid, off), "north": (mid, room.depth_cm - off),
                      "west": (off, mid), "east": (room.width_cm - off, mid)}[op.wall]
            add(wx, wy, 0, "у окна")
        tvs = by.get("тв-тумба")
        if tvs is not None:
            fx, fy = _face_dir((tvs.rot + 90) % 360)
            tw, td = _dims_for_rot(tvs.item, tvs.rot)
            gap = 22 + half + max(tw, td) / 2
            for sgn in (1, -1):
                add(tvs.x + sgn * fx * gap, tvs.y + sgn * fy * gap, tvs.rot, "сбоку от ТВ")
        arm = by.get("кресло")
        if arm is not None:
            afp = footprint(arm)
            ax0, ay0, ax1, ay1 = afp.bounds
            for cx, cy in ((ax0 - 16 - half, (ay0 + ay1) / 2), (ax1 + 16 + half, (ay0 + ay1) / 2)):
                add(cx, cy, 0, "у кресла")
    if rb == "торшер":
        for anchor in (by.get("кресло"), sofa):
            if anchor is None:
                continue
            afp = footprint(anchor)
            x0, y0, x1, y1 = afp.bounds
            for cx, cy in ((x0 - 20 - item.w_cm / 2, y0 + item.d_cm / 2),
                           (x1 + 20 + item.w_cm / 2, y0 + item.d_cm / 2)):
                add(cx, cy, anchor.rot, f"у «{anchor.role}»")
            # F2 (канон BenQ/EDISHINE): «слегка позади, свет через плечо» — задние углы посадки
            afx, afy = _face_dir(anchor.rot)
            for sgn in (-1.0, 1.0):
                bx = anchor.x + (-afy) * ((x1 - x0) / 2 + 25) * sgn - afx * ((y1 - y0) / 2 - 5)
                by_ = anchor.y + afx * ((x1 - x0) / 2 + 25) * sgn - afy * ((y1 - y0) / 2 - 5)
                add(bx, by_, anchor.rot, f"за плечом «{anchor.role}»")
    if rb == "стул" and "стол обеденный" in by:
        # Стул К КРОМКЕ стола (+2 см), не «под стол» (−8 давал пересечение футпринтов — _fits
        # браковал ВСЕ якоря, стулья массово не вставали). Длинная сторона даёт ДВА места
        # симметрично от центра — стулья выровнены по сторонам (вердикт владельца 08.08).
        t = by["стол обеденный"]
        tw, td = _dims_for_rot(t.item, t.rot)
        for dx, dy, rot in ((0, -1, 0), (0, 1, 180), (-1, 0, 90), (1, 0, 270)):
            side = tw if dy else td
            offs = (-side / 4, side / 4) if side >= 2 * (item.w_cm + 10) else (0.0,)
            for o in offs:
                cx = t.x + dx * (tw / 2 + item.d_cm / 2 + 2) + (o if dy else 0.0)
                cy = t.y + dy * (td / 2 + item.d_cm / 2 + 2) + (0.0 if dy else o)
                add(cx, cy, rot, "у обеденного стола")
    return out


def _arc_candidates(room: Room, item: Item, by: dict, free: Polygon, sofa: Placement) -> list[Candidate]:
    """Кресло полукругом вокруг разговорной зоны (ADR-0051, схема ProcTHOR)."""
    scheme = rules().get("dynamic", {}).get("armchair_clearances", {}).get("placement_scheme", {})
    lo, hi = scheme.get("arc_deg_from_tv_axis", [135, 225])
    jit = scheme.get("jitter_deg", 35)
    center = by.get("столик") or sofa
    cx, cy = center.x, center.y
    # зазор кресло↔столик = зазор диван↔столик (фикс-эргономика W2; area-шкала вычищена, T6)
    lo_t, hi_t = distances().get("sofa_coffee_table", [36, 46])
    gap_t = (lo_t + hi_t) / 2
    base = max(item.w_cm, item.d_cm) / 2 + gap_t + max(center.item.w_cm, center.item.d_cm) / 2
    out: list[Candidate] = []
    for th in (lo, hi, lo + jit, hi - jit, lo - jit, hi + jit):
        for k in (1.0, 1.35):  # лесенку держит fwd-предел «не дальше столика+60», не радиус
            r = math.radians(th)
            # 180° — сторона дивана, 0° — сторона ТВ (ось зоны совпадает с «лицом» дивана)
            ax, ay = _face_dir(sofa.rot)          # направление «лица» дивана = ось зоны на ТВ
            R = base * k
            px = cx + R * (ax * math.cos(r) + ay * math.sin(r))
            py = cy + R * (ay * math.cos(r) - ax * math.sin(r))
            rot = _rot_towards(px, py, cx, cy)
            p = Placement(role=item.role, x=px, y=py, rot=rot, item=item)
            if _fits(room, p, free):
                out.append(Candidate(p, "anchor", f"дуга {th:.0f}°", "arc"))
                break   # для угла берём ближайший подходящий радиус
    return out


def _face_dir(rot: float) -> tuple[float, float]:
    r = math.radians(rot)
    return (round(math.sin(r), 6), round(math.cos(r), 6))


def _half_along(poly: Polygon, fx: float, fy: float) -> float:
    x0, y0, x1, y1 = poly.bounds
    return (x1 - x0) / 2 if abs(fx) > abs(fy) else (y1 - y0) / 2


def _rot_towards(x: float, y: float, tx: float, ty: float) -> int:
    dx, dy = tx - x, ty - y
    if abs(dx) > abs(dy):
        return 90 if dx > 0 else 270
    return 0 if dy > 0 else 180


# Функциональные группы: внутри группы зоны подхода друг друга не блокируют (стул ДОЛЖЕН стоять
# в зоне «отодвинуть стул» у стола, кресло — у фронта дивана). Идея ProcTHOR: asset group ставится
# целиком, margin применяется к группе, а не к её членам.
GROUPS = (frozenset({"диван", "столик", "кресло", "пуф"}),
          frozenset({"стол обеденный", "стул"}))
ZONE_GROUP = GROUPS[0]


def group_of(role: str) -> frozenset[str]:
    role = base_role(role)   # «стул 2..4»/«кресло 2» — члены той же группы, что и базовая роль
    for g in GROUPS:
        if role in g:
            return g
    return frozenset()


def is_low(item: Item) -> bool:
    """Низкий/проходной предмет: столик, пуф, ковёр — им можно стоять в чужой зоне подхода."""
    return item.role in NEVER_BLOCKING_ROLES or (item.h_cm or 999) <= LOW_ITEM_MAX_H_CM


def corner_snap_candidates(room: Room, item: Item, free) -> list[Candidate]:
    """Г-диван — явные позиции «двумя секциями в угол» (канон владельца, layout-quality п.1).

    Скольжение вдоль стен даёт углы случайно (на перегоне 2026-08-06 — 1 кандидат из 48),
    поэтому Г-диван вставал посреди стены. Здесь все 4 угла × 4 поворота; развёрнутые лицом
    в стену варианты гибнут на обычных проверках."""
    if item.corner is not True:
        return []
    from .geometry import room_polygon
    verts = list(room_polygon(room).exterior.coords)[:-1]   # Э8: углы = ВЕРШИНЫ контура
    out: list[Candidate] = []
    for rot in (0, 90, 180, 270):
        w, d = _dims_for_rot(item, rot)
        for vx, vy in verts:
            for sx in (1, -1):
                for sy in (1, -1):
                    p = Placement(role=item.role, x=vx + sx * (WALL_GAP_CM + w / 2),
                                  y=vy + sy * (WALL_GAP_CM + d / 2), rot=rot, item=item)
                    if _fits(room, p, free):     # вне контура/в пилоне — отфильтрует сам
                        out.append(Candidate(p, "corner", f"угол ({vx:.0f},{vy:.0f})"))
    return out


# Декор и пуф — ТОЛЬКО у своих якорей (вердикты владельца 07.08, сеты 17/25: торшер за плечом
# дивана, кашпо-сирота у стены, пуф у стены вдали от столика). Нет валидного якорного места —
# роль честно пропускается: лучше без торшера, чем торшер в мёртвом углу.
ANCHOR_ONLY_ROLES = frozenset({"пуф", "торшер", "кашпо"})


def _fireplace_scenario(cands: list[Candidate], placed: list[Placement], room: Room = None) -> list[Candidate]:
    """Ревью рефери 08.08 (set113 «камин в дальнем углу по диагонали»): камин — focal-элемент,
    не optional-filler «где нашлось место». Кандидат допустим, только если с ГЛАВНОЙ посадки
    он в вилке дистанции (zones fireplace.distance_to_seating_cm) И в секторе видимости ≤75°.
    Ни одного такого места нет → роль честно дропается ярусом (optional), а не ставится в угол."""
    import math as _m

    sofa = next((p for p in placed if base_role(p.role) == "диван"), None)
    if sofa is None:
        return cands
    try:
        import json as _json
        import os as _os
        zr = _json.load(open(_os.path.join(_os.path.dirname(__file__), '..', 'rules',
                                           'zones.json')))
        fz = zr['zones']['seating_media']['fireplace']
        lo, hi = fz['distance_to_seating_cm']
        sector = float(fz.get('primary_sector_deg', {}).get('диван', 35))
    except Exception:
        lo, hi, sector = 200, 450, 35.0
    fx, fy = _face_dir(sofa.rot)
    sfp = footprint(sofa)
    keep = []
    for c in cands:
        ffp = footprint(c.placement)
        # G2-пересмотр (веб 08.08): угловой камин легален; фокус обеспечивает primary-сектор
        # (число — zones.json primary_sector_deg, единый источник с валидатором — L2)
        d = sfp.distance(ffp)
        if not (lo <= d <= hi):
            continue
        vx, vy = ffp.centroid.x - sfp.centroid.x, ffp.centroid.y - sfp.centroid.y
        n = _m.hypot(vx, vy)
        if n > 1 and (vx * fx + vy * fy) / n < _m.cos(_m.radians(sector)):
            continue
        keep.append(c)
    return keep


def generate(room: Room, item: Item, placed: list[Placement], *, limit: int = 48) -> list[Candidate]:
    """Все кандидаты для предмета при текущем состоянии комнаты (дедуп по сетке 10 см)."""
    ignore = group_of(item.role)
    free_poly = free_space(room, placed, with_clearance=not is_low(item), ignore_access_of=ignore)
    free = _Fitter(room, free_poly)
    if item.role in ANCHOR_ONLY_ROLES:
        cands = anchor_candidates(room, item, placed, free)
        seen0: set[tuple] = set()
        out0: list[Candidate] = []
        for c in cands:
            key = (round(c.placement.x / 10), round(c.placement.y / 10), int(c.placement.rot) % 360)
            if key not in seen0:
                seen0.add(key)
                out0.append(c)
        return out0[:limit]
    if item.corner and not getattr(item, 'corner_side_fixed', False):
        # G1 (вердикт владельца set119 «диван обратной буквой Г»): сторона угла не задана
        # SKU → пробуем ОБА зеркала, поиск выберет вписывающееся углом к углу
        mirrored = item.model_copy(update={'corner_left': not item.corner_left})
        m_c = corner_snap_candidates(room, mirrored, free)
        m_c += anchor_candidates(room, mirrored, placed, free)
        m_c += wall_candidates(room, mirrored, free)
    else:
        m_c = []
    cands = corner_snap_candidates(room, item, free)   # углы ПЕРВЫМИ: дедуп оставит именно их
    cands += anchor_candidates(room, item, placed, free)
    # G3 (вердикт владельца set113: «кресла не симметричны — референсы разные»): второе
    # кресло ставится ТОЛЬКО парными кандидатами (зеркало/бок-о-бок/другой фланг камина из
    # anchor_candidates) — generic-стены ему запрещены; не влезло парно → честный дроп
    _is_instance = base_role(item.role) == "кресло" and item.role != "кресло"
    _first_placed = any(p.role == "кресло" for p in placed)
    if _is_instance and not _first_placed:
        return []   # пара строится ТОЛЬКО от первого кресла (лазейка «второй на дугу» закрыта)
    if _is_instance:
        # L2: фильтр по структурному полю topology (раньше — по русским подстрокам note);
        # поведение то же: парные позиции + фланги камина (generic-фланг легален для второго)
        cands = [c for c in cands
                 if c.topology.startswith("pair_") or c.topology == "fireplace_flank"]
    else:
        cands += wall_candidates(room, item, free)
    cands += m_c
    if base_role(item.role) == "ковёр":
        sofa0 = next((p for p in placed if base_role(p.role) == "диван"), None)
        if sofa0 is not None and sofa0.item is not None:
            # I1 (канон Lulu&Georgia/E.Henderson): ковёр — дериватив якоря: центр по активной
            # посадке, задний край на 25–30 см ПОД передними ножками, длинной стороной ∥ фронту
            import math as _m
            r0 = _m.radians(sofa0.rot)
            fx0, fy0 = _m.sin(r0), _m.cos(r0)
            act = (sofa0.item.corner_section_cm / 2) if sofa0.item.corner else 0.0
            rug_along = max(item.w_cm, item.d_cm)
            rug_deep = min(item.w_cm, item.d_cm)
            rot0 = int(sofa0.rot) % 180 if item.w_cm >= item.d_cm else (int(sofa0.rot) + 90) % 180
            front = sofa0.item.d_cm / 2
            out_c = []
            from .geometry import room_polygon
            rp = room_polygon(room).buffer(1)
            # L6 (сцены set98/set1-bay: диван у боковой стены — центрированный ковёр вылезал
            # боком за комнату, кандидатов 0, ковёр-якорь терялся): боковой КЛАМП в комнату
            # (сдвиг вдоль фронта легален — центр по посадке preferred, сдвиг лучше потери) и
            # запасные заходы глубже 30 (вариант канона «вся мебель на ковре», zones rug.variants)
            for overlap in (25.0, 30.0, 45.0, 60.0, 80.0):
                fwd_c = front - overlap + rug_deep / 2
                px = sofa0.x + fx0 * fwd_c + (-fy0) * act
                py = sofa0.y + fy0 * fwd_c + fx0 * act
                if abs(fy0) > abs(fx0):   # фронт вдоль оси Y → боковая ось X
                    px = min(max(px, rug_along / 2 + 2), room.width_cm - rug_along / 2 - 2)
                else:
                    py = min(max(py, rug_along / 2 + 2), room.depth_cm - rug_along / 2 - 2)
                pl = Placement(role=item.role, x=px, y=py, rot=rot0, item=item)
                # ковёр — ПОДЛОЖКА: пересекается с мебелью по определению; проверяем только
                # вхождение в комнату, не в «свободный» полигон
                if rp.contains(footprint(pl)):
                    out_c.append(Candidate(pl, "anchor", f"под ножки дивана, заход {overlap:.0f}"))
                if len(out_c) >= 3:       # канон-заходы 25/30 первыми; глубже — только фолбэк
                    break
            return out_c[:limit]
        return []
    if item.role in ("стол обеденный", "столик"):
        cands += middle_candidates(room, item, free_poly, fitter=free)
        # D1: столик в middle-позициях — длинной стороной по фронту дивана, не 0/90 вслепую
        if base_role(item.role) == "столик":
            sofa0 = next((p for p in placed if base_role(p.role) == "диван"), None)
            if sofa0 is not None:
                cands = [c for c in cands
                         if c.kind != "middle" or int(c.placement.rot) % 180 == int(sofa0.rot) % 180]
    if base_role(item.role) == "камин":
        cands = _fireplace_scenario(cands, placed, room)
    seen: set[tuple] = set()
    out: list[Candidate] = []
    for c in cands:
        key = (round(c.placement.x / 10), round(c.placement.y / 10), int(c.placement.rot) % 360)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
        if len(out) >= limit:
            break
    return out


def pair_candidates(room: Room, item: Item, partner: Item, placed: list[Placement],
                    *, limit_first: int = 12, limit: int = 24) -> list[Candidate]:
    """L3 (MASTER-layout-v5): joint-генерация ПАРЫ кресел — обе позы одним кандидатом.

    Снимает порядковую зависимость «№2 только от уже выбранного №1» (V5 §17–18): плохой выбор
    первого кресла схлопывал пространство второго (`generate` инстанса без первого → []).
    Формулы позиций переиспользуются: для каждой позы первого кресла (дуга/фланг/напротив
    дивана) вторая поза строится тем же деривативным путём `generate(partner, ...)` — т.е.
    пары идентичны тем, что луч мог найти последовательно, но видны АТОМАРНО и конкурируют
    с одиночными ветками честно. Валидация/скоринг пары — на совокупности (beam)."""
    out: list[Candidate] = []
    for c1 in generate(room, item, placed)[:limit_first]:
        for c2 in generate(room, partner, placed + [c1.placement]):
            # generate() инстанса уже отфильтрован до pair_*/fireplace_flank (гейт L2)
            out.append(Candidate(c1.placement, "anchor",
                                 f"пара joint: {c1.note} + {c2.note}",
                                 f"pair_joint:{c2.topology or '?'}",
                                 (c2.placement,)))
            if len(out) >= limit:
                return out
    return out
