"""Hard-валидация раскладки: объяснимые нарушения вместо «да/нет».

Каждая проверка возвращает Violation с кодом, ролями и фактическим числом — это вход
для объяснений top-K (Э5) и для регресс-метрик (Collision-Free / In-Boundary, LayoutVLM).
"""
from __future__ import annotations

from shapely.geometry import Polygon
from shapely.ops import unary_union

from .clearances import (LOW_ITEM_MAX_H_CM, NEVER_BLOCKING_ROLES, band_scale, distances,
                         passage_min_cm, rules)
from .geometry import (
    access_zone,
    facing_vector,
    footprint,
    free_space,
    opening_polygon,
    radiator_polygon,
    front_gap,
    relative_position,
    room_polygon,
    static_blockers,
    swing_polygon,
)
from .models import Item, Layout, Placement, Room, Severity, Violation

EPS = 1.0  # см: допуск на округления (Holodeck EPSILON=1 см в наших единицах)


def _v(code: str, msg: str, roles: list[str], value: float | None = None, expected: str | None = None,
       severity: Severity = Severity.HARD) -> Violation:
    return Violation(code=code, severity=severity, message=msg, roles=roles, value=value, expected=expected)


def check_boundary(room: Room, ps: list[Placement]) -> list[Violation]:
    rp = room_polygon(room).buffer(EPS)
    out = []
    for p in ps:
        fp = footprint(p)
        if not rp.contains(fp):
            out.append(_v("OUT_OF_ROOM", f"«{p.role}» выходит за пределы комнаты", [p.role],
                          round(fp.difference(rp).area / 100, 1), "0 м² вне комнаты"))
    return out


def check_collisions(ps: list[Placement]) -> list[Violation]:
    out = []
    for i, a in enumerate(ps):
        if a.role.split(' ')[0] == "ковёр":
            continue   # подложка: мебель СТОИТ на ковре (front-legs канон)
        fa = footprint(a)
        for b in ps[i + 1:]:
            if b.role.split(' ')[0] == "ковёр":
                continue
            inter = fa.intersection(footprint(b)).area
            if inter > EPS * EPS:
                out.append(_v("COLLISION", f"«{a.role}» пересекается с «{b.role}»", [a.role, b.role],
                              round(inter / 100, 1), "0 м² пересечения"))
    return out


def check_openings(room: Room, ps: list[Placement]) -> list[Violation]:
    out = []
    for op in room.openings:
        swing = swing_polygon(room, op)
        if swing.is_empty:
            continue
        for p in ps:
            if footprint(p).intersects(swing.buffer(-EPS)):
                out.append(_v("DOOR_SWING", f"«{p.role}» стоит в зоне открывания двери", [p.role],
                              None, f"дуга {op.swing_cm:.0f} см свободна"))
        # окно не перекрываем высокой мебелью — проверка по высоте (h выше подоконника)
    for op in room.openings:
        if op.kind != "window":
            continue
        win = opening_polygon(room, op)
        for p in ps:
            h = (p.item.h_cm if p.item else None) or 0
            if h > max(op.sill_cm, 80) and footprint(p).distance(win) < 10:
                out.append(_v("WINDOW_BLOCKED", f"«{p.role}» ({h:.0f} см) перекрывает окно", [p.role],
                              h, f"ниже подоконника {op.sill_cm:.0f} см"))
    return out


def check_radiators(room: Room, ps: list[Placement]) -> list[Violation]:
    hard = distances().get("sofa_to_radiator_wall", [15, 20])[0]
    out = []
    for rad in room.radiators:
        zone = radiator_polygon(room, rad).buffer(hard)
        for p in ps:
            if footprint(p).intersects(zone.buffer(-EPS)):
                out.append(_v("RADIATOR", f"«{p.role}» ближе {hard:.0f} см к радиатору", [p.role],
                              hard, f"≥{hard:.0f} см"))
    return out


def check_access(ps: list[Placement]) -> list[Violation]:
    """Функциональная зона (подход/ноги/фасады) не должна быть занята другим предметом.

    Члены ОДНОЙ функциональной группы (стол↔стулья, диван↔кресло/пуф) зоны друг друга не
    блокируют (ProcTHOR asset-group; тот же принцип в candidates.free_space). Без этого
    обеденная группа была геометрически невозможна: стул обязан ≤40 см (CHAIR_ORPHAN), но
    ближе 55 попадал в «отодвинуть стул» стола → ACCESS_BLOCKED (найдено 08.08)."""
    from .candidates import group_of
    from .geometry import base_role as _brole
    out = []
    for a in ps:
        zone = access_zone(a)
        if zone.is_empty:
            continue
        ga = group_of(a.role)
        for b in ps:
            if b is a or b.role in NEVER_BLOCKING_ROLES:
                continue
            if _brole(b.role) in ga:
                continue
            bh = (b.item.h_cm if b.item else None)
            if bh is not None and bh <= LOW_ITEM_MAX_H_CM:
                continue   # низкий предмет (столик/пуф) подход не перекрывает
            inter = zone.intersection(footprint(b)).area
            if inter > 100:  # >0.01 м² — не округление
                out.append(_v("ACCESS_BLOCKED",
                              f"«{b.role}» перекрывает подход к «{a.role}»", [a.role, b.role],
                              round(inter / 100, 1), "зона подхода свободна"))
    return out


MAIN_PATH_ROLES = frozenset({"диван", "тв-тумба", "столик", "стол обеденный"})


def check_passages(room: Room, ps: list[Placement], kind: str = "secondary") -> list[Violation]:
    """Связность: до КАЖДОГО предмета — минимальный проход (наш `passage_absolute_min_tight`),
    до предметов главного маршрута (диван/ТВ/столы) — полноценный вторичный проход.

    Раньше 60 см требовалось до всего подряд — в 18 м² с полным сетом это невыполнимо, и
    движок честно, но бесполезно отказывался ставить стеллаж (свод: тесный проход 46–61 см).
    """
    need = float(distances().get("passage_absolute_min_tight", [46, 61])[0])
    free = free_space(room, ps, with_clearance=False)
    for b in static_blockers(room):
        free = free.difference(b)
    core = free.buffer(-need / 2)  # эрозия: остаётся то, где проходит человек
    if core.is_empty:
        return [_v("NO_PASSAGE", f"в комнате не осталось прохода {need:.0f} см", [], 0, f"≥{need:.0f} см")]
    parts = [core] if core.geom_type == "Polygon" else list(core.geoms)
    doors = [swing_polygon(room, op) for op in room.openings if op.kind in ("door", "balcony")]
    entry = unary_union([d for d in doors if not d.is_empty]) if doors else None
    if entry is None or entry.is_empty:
        main = max(parts, key=lambda g: g.area)
    else:
        touching = [g for g in parts if g.buffer(need).intersects(entry)]
        if not touching:
            return [_v("DOOR_UNREACHABLE", "от двери нет прохода в комнату", [], None, f"≥{need:.0f} см")]
        main = max(touching, key=lambda g: g.area)
    out = []
    for p in ps:
        if p.role.split(' ')[0] == "ковёр":
            continue   # подложка: по ковру ходят, «проход к ковру» не нужен
        if ((p.item.h_cm if p.item else None) or 999) <= LOW_ITEM_MAX_H_CM:
            continue   # низкое (столик/пуф) достают С ПОСАДКИ — пеший коридор 46 не нужен
        reach = footprint(p).buffer(need / 2 + EPS)
        if not reach.intersects(main):
            out.append(_v("UNREACHABLE", f"к «{p.role}» нет прохода {need:.0f} см", [p.role],
                          need, f"≥{need:.0f} см"))
    wide = passage_min_cm(kind)                      # главный маршрут — полноценный проход
    core_w = free.buffer(-wide / 2)
    if not core_w.is_empty:
        parts_w = [core_w] if core_w.geom_type == "Polygon" else list(core_w.geoms)
        main_w = max(parts_w, key=lambda g: g.area)
        for p in ps:
            if p.role not in MAIN_PATH_ROLES:
                continue
            if not footprint(p).buffer(wide / 2 + EPS).intersects(main_w):
                out.append(_v("MAIN_PATH_TIGHT", f"к «{p.role}» проход уже {wide:.0f} см", [p.role],
                              wide, f"≥{wide:.0f} см", Severity.SOFT))
    else:
        out.append(_v("MAIN_PATH_TIGHT", f"в комнате нет прохода {wide:.0f} см", [], 0,
                      f"≥{wide:.0f} см", Severity.SOFT))
    return out


def _zone_gap(sofa: Placement, other: Placement) -> float:
    """Дистанция зоны: от фронта посадочного места (у Г-дивана — длинной секции)."""
    if sofa.item is not None and sofa.item.corner:
        return front_gap(sofa, other)
    return footprint(sofa).distance(footprint(other))


def _inst(ps: list[Placement], base: str) -> list[Placement]:
    """Все экземпляры базовой роли: «кресло», «кресло 2», … (Z4: составы содержат пары)."""
    from .geometry import base_role
    return [p for p in ps if base_role(p.role) == base]


def _by_base(ps: list[Placement]) -> dict:
    """role→placement, где экземпляры схлопнуты к базовой роли (первый — канонический якорь);
    точечные правила «у дивана/у кресла» получают якорь, циклы по экземплярам — через _inst.

    Носитель ТВ (правило владельца 08.08): в стенке всегда есть место под ТВ по центру —
    при составе БЕЗ тв-тумбы стенка алиасится под ключ «тв-тумба», и ВСЕ ТВ-правила
    (дистанция/ось/facing/sightline/блики) работают от стенки. Реальная роль предмета
    остаётся «стенка» (bearer различается по placement.role, напр. в check_distances)."""
    from .geometry import base_role
    out = {}
    for p in ps:
        out.setdefault(base_role(p.role), p)
    if "тв-тумба" not in out and "стенка" in out:
        out["тв-тумба"] = out["стенка"]
    return out


def check_distances(room: Room, ps: list[Placement]) -> list[Violation]:
    """Дистанции пар: диван↔ТВ — диагональ/FOV (приор экран/тумба 0.70–0.90, W2+Q2);
    диван↔столик — фикс-эргономика (hard 32–50, комфорт 36–46, W2). Area-шкалы — только
    legacy-фолбэк (узкая тумба <60 см)."""
    by = _by_base(ps)
    out = []
    if "диван" in by and "тв-тумба" in by:
        g = _zone_gap(by["диван"], by["тв-тумба"])
        # W2 + рефери Q2 (08.08): ТВ — не SKU, его рисует генератор, поэтому валидна дистанция,
        # под которую СУЩЕСТВУЕТ диагональ, совместимая с тумбой. Приор экран/тумба — вилка
        # 0.70–0.90 (не точка 0.70: RTINGS выбирает размер от дистанции/FOV, тумба — только
        # clamp; практика стендов — стенд на пару дюймов шире экрана). Генератор при отрисовке
        # идёт distance-first: diag ≈ g/1.6 (FOV ~30°), clamp в [0.70..0.90]·тумба.
        bearer = by["тв-тумба"]
        stand_w = bearer.item.w_cm or 0
        if stand_w >= 60:
            # T6: одна каноническая ТВ-функция на все слои (planner/tv.py, рефери §21);
            # носитель «стенка» — диагональ от ниши, не от всей ширины (правило владельца 08.08)
            from .geometry import base_role as _br2
            from .tv import distance_range
            lo, hi, soft_hi = distance_range(stand_w, bearer=_br2(bearer.role))
        else:
            tv = band_scale("sofa_tv_cm", room.band, distances().get("sofa_tv_cm", [180, 300]))
            lo, hi = tv[0], max(tv[1], float(distances().get("sofa_tv_hard_max", 400)))
            soft_hi = tv[1]
        if g < lo or g > hi:
            out.append(_v("SOFA_TV_DIST", f"диван↔ТВ {g:.0f} см вне шкалы (диагональ-метод)",
                          ["диван", "тв-тумба"], round(g), f"{lo:.0f}–{hi:.0f} см"))
        elif g > soft_hi:
            out.append(_v("SOFA_TV_FAR", f"диван↔ТВ {g:.0f} см — дальше комфортного",
                          ["диван", "тв-тумба"], round(g), f"≤{soft_hi:.0f} см", Severity.SOFT))
    if "диван" in by and "столик" in by:
        g = _zone_gap(by["диван"], by["столик"])
        # W2 (аудит 08.08): досягаемость руки НЕ зависит от площади комнаты — фикс-вилки:
        # hard 32–50 (fallback tight-space), комфорт 36–46 (soft) — из zones.json/сводов.
        t_hard = distances().get("sofa_coffee_table_hard", [32, 50])
        t_pref = distances().get("sofa_coffee_table", [36, 46])
        if not (t_hard[0] <= g <= t_hard[1]):
            out.append(_v("SOFA_TABLE_DIST", f"диван↔столик {g:.0f} см вне вилки", ["диван", "столик"],
                          round(g), f"{t_hard[0]:.0f}–{t_hard[1]:.0f} см"))
        elif not (t_pref[0] <= g <= t_pref[1]):
            out.append(_v("SOFA_TABLE_COMFORT", f"диван↔столик {g:.0f} см — вне комфортной вилки",
                          ["диван", "столик"], round(g),
                          f"{t_pref[0]:.0f}–{t_pref[1]:.0f} см", Severity.SOFT))
    if "диван" in by:
        lim = distances().get("seats_group_max", 200)   # единый порог для обоих движков
        for arm in _inst(ps, "кресло"):
            # D5: кресло камин-уголка (вторичная зона) — законно далеко от дивана
            if _in_fireplace_zone(ps, arm):
                continue
            g = footprint(by["диван"]).distance(footprint(arm))
            if g > lim:
                out.append(_v("SEATS_TOO_FAR", f"диван↔{arm.role} {g:.0f} см — зона разорвана",
                              ["диван", arm.role], round(g), f"≤{lim:.0f} см"))
    return out


# Мебель хранения/техники живёт спинкой к стене — из ДАННЫХ (рефери 08.08 Q4: subtype-флаги
# requires_wall_back / room_divider_capable вместо «всей корпусной»; divider-capable
# освобождается от NOT_AT_WALL, когда в продукте появятся open-plan сценарии).
# Фолбэк — прежний список (ProcTHOR onEdge + вердикт владельца «шкаф посреди комнаты нельзя»).
def _wall_only_roles() -> frozenset:
    from .clearances import rules as _rules
    lr = _rules().get("layout_rules", {})
    req = lr.get("requires_wall_back")
    if not req:
        return frozenset({"тв-тумба", "шкаф", "комод", "стенка", "витрина", "стеллаж", "камин"})
    return frozenset(req) - frozenset(lr.get("room_divider_capable_active") or [])


WALL_ONLY_ROLES = frozenset({"тв-тумба", "шкаф", "комод", "стенка", "витрина", "стеллаж", "камин"})
WALL_TOUCH_MAX_CM = 20.0


def check_wall_only(room: Room, ps: list[Placement]) -> list[Violation]:
    """Корпусная мебель стоит СПИНКОЙ к стене, а не «касается стены каким-нибудь боком».

    Раньше хватало любой ближайшей стороны — и комод вставал перпендикулярно, торча в комнату
    как перегородка, формально «у стены» (вердикт владельца 2026-08-03).
    """
    out = []
    wall_only = _wall_only_roles()
    for p in ps:
        if p.role not in wall_only:
            continue
        x0, y0, x1, y1 = footprint(p).bounds
        fx, fy = facing_vector(p.rot)
        # спинка — сторона, противоположная «лицу»
        if abs(fy) > abs(fx):
            back = y1 if fy < 0 else y0
            d = (room.depth_cm - back) if fy < 0 else back
        else:
            back = x1 if fx < 0 else x0
            d = (room.width_cm - back) if fx < 0 else back
        if d > WALL_TOUCH_MAX_CM:
            out.append(_v("NOT_AT_WALL", f"«{p.role}» стоит спинкой не к стене ({d:.0f} см)", [p.role],
                          round(d), f"спинка ≤{WALL_TOUCH_MAX_CM:.0f} см до стены"))
    return out


def _in_fireplace_zone(ps: list[Placement], arm: Placement) -> bool:
    """D5: кресло принадлежит камин-уголку (вторичная зона, не член дивановой дуги).
    Дистанция и конус — из zones.json secondary_zone (L2: код читает данные, не наоборот)."""
    import math as _m

    from .zones import zone_rules

    by = _by_base(ps)
    fpl = by.get("камин")
    if fpl is None or arm.item is None:
        return False
    sz = zone_rules()["zones"]["seating_media"]["fireplace"]["secondary_zone"]
    lo, hi = sz["armchair_dist_cm"]      # 20+: фланг по бокам камина, 280: предел уголка
    cone = float(sz["cone_deg"])
    d = footprint(arm).distance(footprint(fpl))
    if not (lo <= d <= hi):
        return False
    afx, afy = facing_vector(arm.rot)
    fc, ac = footprint(fpl).centroid, footprint(arm).centroid
    # фланговое кресло развёрнуто «чуть внутрь» — смотрит на точку ПЕРЕД камином,
    # поэтому конус меряем к зоне камина (центр + фронт)
    ffx, ffy = facing_vector(fpl.rot)
    tx = fc.x + ffx * 120
    ty = fc.y + ffy * 120
    for px, py in ((fc.x, fc.y), (tx, ty)):
        vx, vy = px - ac.x, py - ac.y
        n = _m.hypot(vx, vy)
        if n > 1 and (vx * afx + vy * afy) / n >= _m.cos(_m.radians(cone)):
            return True
    return False


def check_facing(ps: list[Placement]) -> list[Violation]:
    """«Диван параллельно телеку» (правило владельца): фронты встречные + боковое перекрытие.

    Соответствует MILP-констрейнту Holodeck «относительные позиции — в локальной системе цели,
    боковой разброс ≤ полуширины цели».
    """
    by = _by_base(ps)
    if "диван" not in by or "тв-тумба" not in by:
        return []
    sofa, tv = by["диван"], by["тв-тумба"]
    if (int(sofa.rot) - int(tv.rot)) % 360 != 180:
        return [_v("FACING_MISMATCH", "диван и ТВ не смотрят друг на друга", ["диван", "тв-тумба"],
                   None, "фронты встречные (разница 180°)")]
    sx0, sy0, sx1, sy1 = footprint(sofa).bounds
    tx0, ty0, tx1, ty1 = footprint(tv).bounds
    if int(sofa.rot) % 180 == 0:          # ось зоны вертикальная → перекрытие по X
        ov = min(sx1, tx1) - max(sx0, tx0)
        need = 0.3 * min(sx1 - sx0, tx1 - tx0)
    else:                                  # ось горизонтальная → перекрытие по Y
        ov = min(sy1, ty1) - max(sy0, ty0)
        need = 0.3 * min(sy1 - sy0, ty1 - ty0)
    if ov < need:
        return [_v("TV_OFF_AXIS", "ТВ смещён с оси дивана", ["диван", "тв-тумба"],
                   round(max(ov, 0)), f"перекрытие ≥{need:.0f} см")]
    return []


# За спинкой дивана — только НИЗКОЕ (консоль/комод до ~90 см). Высокий шкаф/стеллаж вплотную
# за диваном читается как «диван задвинули к шкафу» (вердикт владельца 2026-08-02; в DFS-движке
# это была «бронь тыла» ADR-0050 — при переносе в beam правило потерялось).
def _lr(key, default):
    """Именованное правило расстановки из файла правил (не из кода — урок 46)."""
    return rules().get("layout_rules", {}).get(key, default)


BEHIND_SOFA_MAX_H_CM = float(_lr("behind_sofa_max_h_cm", 90))


def check_behind_sofa(room: Room, ps: list[Placement]) -> list[Violation]:
    by = _by_base(ps)
    sofa = by.get("диван")
    if sofa is None or sofa.item is None:
        return []
    strip = _behind_strip(room, sofa)   # локальная полоса (рефери 08.08 Q3)
    out = []
    for p in ps:
        if p is sofa or p.item is None:
            continue
        h = p.item.h_cm or 0
        if h > BEHIND_SOFA_MAX_H_CM and footprint(p).intersection(strip).area > 400:
            out.append(_v("TALL_BEHIND_SOFA", f"«{p.role}» ({h:.0f} см) стоит за спинкой дивана",
                          [p.role, "диван"], h, f"за диваном только ниже {BEHIND_SOFA_MAX_H_CM:.0f} см"))
    return out


# ФУНКЦИОНАЛЬНЫЕ ЗОНЫ (R1, [[layout-rules-v2]]): зона — деривативная от якорей, поэтому работает
# инкрементально внутри beam и на любом контуре комнаты (Э8-совместимо). Разговорная зона =
# конверт(диван, ТВ[, столик]); обеденная = конверт(стол, стулья). Правила: столовая группа не
# лезет в разговорную зону, высокое хранение — не в обеденную (вердикты владельца 2026-08-07:
# «стол за диваном», «зачем стеллаж в обеденной зоне»).
ZONE_BUFFER_CM = 30.0
STORAGE_HIGH_ROLES = ("стеллаж", "витрина", "стенка", "шкаф")


def _zone(ps: list[Placement], roles: tuple[str, ...]):
    from shapely.ops import unary_union
    fps = [footprint(p) for p in ps if p.role in roles or p.role.split(' ')[0] in roles]
    if not fps:
        return None
    return unary_union(fps).convex_hull.buffer(ZONE_BUFFER_CM)


def check_functional_zones(room: Room, ps: list[Placement]) -> list[Violation]:
    out = []
    living = _zone(ps, ("диван", "тв-тумба", "столик"))
    dining = _zone(ps, ("стол обеденный", "стул"))
    if living is not None:
        for p in ps:
            if p.role != "стол обеденный" and not p.role.startswith("стул"):
                continue
            f = footprint(p)
            if f.intersection(living).area > 0.2 * f.area:
                out.append(_v("DINING_IN_LIVING_ZONE",
                              f"«{p.role}» внутри разговорной зоны — столовая группа живёт отдельно",
                              [p.role, "диван"]))
    if dining is not None:
        for p in ps:
            if p.role not in STORAGE_HIGH_ROLES or p.item is None:
                continue
            if (p.item.h_cm or 0) <= 90:
                continue
            f = footprint(p)
            if f.intersection(dining).area > 0.2 * f.area:
                out.append(_v("STORAGE_IN_DINING_ZONE",
                              f"«{p.role}» внутри обеденной зоны — хранению там не место",
                              [p.role, "стол обеденный"]))
    return out


# За спинкой дивана — МЁРТВАЯ зона для функционального и декора (вердикт владельца 2026-08-07:
# «предметы расставляются не там, где функционально нужны, типа кашпо за диваном»).
# Разрешено там только низкое хранение/консоль (check_behind_sofa) — посадка, столы и декор вон.
# Камина в списке НЕТ (рефери 08.08 Q3): focal-behind ловится угловым чеком
# FIREPLACE_FAR_FROM_SEATING (сектор 75°), а не полосой. Обеденной группы (стол/стул) тоже
# НЕТ (рефери 08.08: floating sofa — легитимный разделитель зон, dining за спинкой — норма
# open-plan; стол в разговорной зоне ловит DINING_IN_LIVING_ZONE, проходы — циркуляция).
DEAD_BEHIND_ROLES = ("кашпо", "торшер", "столик", "пуф", "кресло", "лампа", "ваза")

# Боковой запас локальной полосы: покрывает «торшер за плечом» (вердикт 07.08, сет 25),
# но не запрещает легитимное использование дальних краёв комнаты (рефери 08.08 Q3:
# room-wide полоса конфликтует с диваном-разделителем и зонированием open-plan)
BEHIND_LATERAL_MARGIN_CM = 100.0


def _behind_strip(room: Room, sofa: Placement):
    """Локальная полоса за спинкой дивана: ширина дивана + боковой запас, в глубину до стены
    (рефери 08.08 Q3 — local projection, не вся ширина комнаты)."""
    from shapely.geometry import box as _box

    m = BEHIND_LATERAL_MARGIN_CM
    fx, fy = facing_vector(sofa.rot)
    x0, y0, x1, y1 = footprint(sofa).bounds
    if abs(fy) > abs(fx):
        lo, hi = max(0.0, x0 - m), min(room.width_cm, x1 + m)
        return _box(lo, 0, hi, y0) if fy > 0 else _box(lo, y1, hi, room.depth_cm)
    lo, hi = max(0.0, y0 - m), min(room.depth_cm, y1 + m)
    return (_box(0, lo, x0, hi) if fx > 0
            else _box(x1, lo, room.width_cm, hi))


def check_dead_zone_behind_sofa(room: Room, ps: list[Placement]) -> list[Violation]:
    by = _by_base(ps)
    sofa = by.get("диван")
    if sofa is None or sofa.item is None:
        return []
    strip = _behind_strip(room, sofa)
    out = []
    for p in ps:
        if p.role.split(' ')[0] not in DEAD_BEHIND_ROLES and p.role not in DEAD_BEHIND_ROLES:
            continue
        if footprint(p).intersection(strip).area > 0.5 * footprint(p).area:
            out.append(_v("DEAD_ZONE_BEHIND_SOFA",
                          f"«{p.role}» за спинкой дивана — функциональному и декору там не место",
                          [p.role, "диван"]))
    return out


def check_sofa_aim(room: Room, ps: list[Placement]) -> list[Violation]:
    """Диван смотрит НА ТВ: прицел ≤30° hard (priors 18 804 сцен: p50 7°, p90 22° + запас).

    Вердикт владельца («где-то диван не напротив ТВ») + данные R2 [[layout-rules-v2]]."""
    import math as _m

    by = _by_base(ps)
    sofa, tv = by.get("диван"), by.get("тв-тумба")
    if sofa is None or tv is None:
        return []
    fx, fy = facing_vector(sofa.rot)
    vx, vy = tv.x - sofa.x, tv.y - sofa.y
    n = _m.hypot(vx, vy) or 1.0
    aim = _m.degrees(_m.acos(max(-1.0, min(1.0, (fx * vx + fy * vy) / n))))
    lim = float(distances().get("sofa_tv_aim_deg_max", 30))
    if aim > lim:
        return [_v("SOFA_AIM_OFF_TV", f"диван смотрит мимо ТВ на {aim:.0f}°",
                   ["диван", "тв-тумба"], round(aim), f"≤{lim:.0f}° (дизайнеры: p90 22°)")]
    return []


def check_chairs_at_table(room: Room, ps: list[Placement]) -> list[Violation]:
    """Стул живёт у обеденного стола: обеденный стул дальше 40 см — брак (priors: вплотную, p50 3 шт).

    Только роль «стул» (обеденный); кресло/акцентное — другая роль, правило его не касается."""
    tbl = next((p for p in ps if p.role == "стол обеденный"), None)
    chairs = [p for p in ps if p.role.startswith("стул")]
    if tbl is None or not chairs:
        return []
    out = []
    for ch in chairs:
        d = footprint(ch).distance(footprint(tbl))
        if d > 40:
            out.append(_v("CHAIR_ORPHAN", f"стул в {d:.0f} см от обеденного стола",
                          [ch.role, "стол обеденный"], round(d),
                          "≤40 см (priors 18 804 сцен: вплотную, p50 5)"))
    return out


SOFA_SLIVER_MIN_CM = 20.0


def check_sofa_sliver(room: Room, ps: list[Placement]) -> list[Violation]:
    """Щель за спинкой дивана 20–76 см запрещена ЖЁСТКО: или вплотную (<20), или проход ≥76.

    Правило владельца 2026-08-02 («промежуточная щель — запрещена»); раньше жило только мягким
    штрафом sofa_dead_gap, и валидная раскладка могла выйти с непроходимой щелью (А5).
    Щель, заполненная хранением/консолью, щелью не считается (диван «по центру» с хранением сзади).
    """
    import os as _os

    from shapely.geometry import box as _box

    if _os.environ.get("NO_SOFA_SLIVER") == "1":   # диагностика/калибровка
        return []
    by = _by_base(ps)
    sofa = by.get("диван")
    if sofa is None or sofa.item is None:
        return []
    fx, fy = facing_vector(sofa.rot)
    x0, y0, x1, y1 = footprint(sofa).bounds
    if abs(fy) > abs(fx):
        d = y0 if fy > 0 else room.depth_cm - y1
        strip = _box(x0, 0, x1, y0) if fy > 0 else _box(x0, y1, x1, room.depth_cm)
    else:
        d = x0 if fx > 0 else room.width_cm - x1
        strip = _box(0, y0, x0, y1) if fx > 0 else _box(x1, y0, room.width_cm, y1)
    passage = float(distances().get("sofa_to_wall_passage", 76))
    if SOFA_SLIVER_MIN_CM <= d < passage:
        filled = any(footprint(p).intersection(strip).area > 400 for p in ps if p is not sofa)
        if not filled:
            return [_v("SOFA_SLIVER", f"щель за спинкой дивана {d:.0f} см — ни вплотную, ни проход",
                       ["диван"], round(d), f"<{SOFA_SLIVER_MIN_CM:.0f} см или ≥{passage:.0f} см")]
    return []


_ROOM_BAND = [None]      # текущий бэнд; ставится в beam.solve (T6: лениво в validate —
                         # заражение следующей сцены процесса, урок 206) и дублируется в validate()


def check_zone(ps: list[Placement]) -> list[Violation]:
    """Разговорная зона — не набор «где-то рядом»: столик перед диваном, кресло в зоне.

    Боковой разброс ограничен полушириной якоря (+запас) — правило Holodeck-MILP;
    кресло допускается сбоку-впереди (дуга ADR-0051), но не за спинкой дивана.
    """
    by = _by_base(ps)
    sofa = by.get("диван")
    if sofa is None or sofa.item is None:
        return []
    half = sofa.item.w_cm / 2
    # P0.4/P0.5 (рефери 08.08): у Г/П-дивана считаем не bbox, а АКТИВНУЮ посадку
    # (conversation cavity): плечо занимает −lateral (см. candidates.seat_center) —
    # активный центр смещён на +section/2, активная ширина = w − section
    if sofa.item.corner:
        act_lat = sofa.item.corner_section_cm / 2
        act_w = max(sofa.item.w_cm - sofa.item.corner_section_cm, 80.0)
    else:
        act_lat, act_w = 0.0, sofa.item.w_cm
    out = []
    tbl = by.get("столик")
    if tbl is not None:
        fwd, lat = relative_position(sofa, tbl)
        dev = abs(lat - act_lat)
        if fwd <= 0:
            out.append(_v("TABLE_BEHIND_SOFA", "столик не перед диваном", ["диван", "столик"],
                          round(fwd), "перед фронтом дивана"))
        elif dev > 0.20 * act_w:
            # P0.5: >20% активной ширины — группа потеряла ось (set66); было 37.5% от bbox
            out.append(_v("TABLE_OFF_AXIS",
                          f"столик смещён на {dev:.0f} см от центра посадки",
                          ["диван", "столик"], round(dev), f"≤{0.20 * act_w:.0f} см (20% посадки)"))
        elif dev > 0.10 * act_w:
            out.append(_v("COFFEE_TABLE_OFF_CENTER",
                          f"столик смещён на {dev:.0f} см от центра посадки (10–20%)",
                          ["диван", "столик"], round(dev),
                          f"≤{0.10 * act_w:.0f} см (10% посадки)", Severity.SOFT))
        # I1-чеки (канон rug rules): ковёр заякорен на группе — не «отрешён»
        rg0 = by.get("ковёр")
        if rg0 is not None and rg0.item is not None:
            _, rlat = relative_position(sofa, rg0)
            rug_along = max(rg0.item.w_cm, rg0.item.d_cm)
            inter = footprint(sofa).intersection(footprint(rg0))
            # передние ножки дивана на ковре: перекрытие по глубине 10–45 см
            depth_over = (inter.area / rug_along) if not inter.is_empty else 0.0
            if abs(rlat - act_lat) > 0.20 * act_w or not (5 <= depth_over <= 50):
                out.append(_v("RUG_DETACHED",
                              "ковёр отвязан от посадки (центр/заход под ножки вне канона)",
                              ["диван", "ковёр"], round(abs(rlat - act_lat)),
                              "центр по посадке, заход под передние ножки 10–45 см",
                              Severity.SOFT))
            if tbl is not None and tbl.item is not None:
                rfp = footprint(rg0)
                tfp = footprint(tbl)
                margin = rfp.exterior.distance(tfp) if rfp.contains(tfp) else -1
                if margin < 30:
                    out.append(_v("RUG_TABLE_MARGIN",
                                  "столик не в центре ковра (поле ковра <30 см вокруг)",
                                  ["столик", "ковёр"], round(max(margin, 0)),
                                  "столик на ковре, поле ≥30 см", Severity.SOFT))
        # RUG_ORIENTATION (вердикт владельца 08.08): ковёр — длинной стороной параллельно
        # фронту дивана (как столик)
        rg = by.get("ковёр")
        if rg is not None and rg.item is not None and \
                max(rg.item.w_cm, rg.item.d_cm) >= 1.2 * min(rg.item.w_cm, rg.item.d_cm):
            long_ok = (rg.item.w_cm >= rg.item.d_cm) == \
                (int(rg.rot) % 180 == int(sofa.rot) % 180)
            if not long_ok:
                out.append(_v("RUG_ORIENTATION",
                              "ковёр короткой стороной к дивану — развернуть длинной",
                              ["диван", "ковёр"], None, "длинная сторона параллельна фронту",
                              Severity.SOFT))
        # D1 (вердикт владельца set55 + веб-канон 2Modern/CarpentryShop): прямоугольный
        # столик — ДЛИННОЙ стороной параллельно фронту дивана
        if tbl.item is not None and max(tbl.item.w_cm, tbl.item.d_cm) >= \
                1.25 * min(tbl.item.w_cm, tbl.item.d_cm):
            long_along_front = (tbl.item.w_cm >= tbl.item.d_cm) == \
                (int(tbl.rot) % 180 == int(sofa.rot) % 180)
            if not long_along_front:
                out.append(_v("TABLE_ORIENTATION",
                              "столик короткой стороной к дивану — развернуть длинной",
                              ["диван", "столик"], None, "длинная сторона параллельна фронту"))
    pouf = by.get("пуф")
    if pouf is not None:
        fwd, lat = relative_position(sofa, pouf)
        if fwd <= 0:
            out.append(_v("POUF_BEHIND_SOFA", "пуф стоит за диваном", ["диван", "пуф"],
                          round(fwd), "перед фронтом дивана"))
        elif abs(lat) > half:
            out.append(_v("POUF_OUT_OF_ZONE", f"пуф в {abs(lat):.0f} см вбок от оси дивана", ["пуф"],
                          round(abs(lat)), f"в пределах ширины дивана (≤{half:.0f} см)"))
        elif tbl is not None and (footprint(pouf).distance(footprint(tbl))
                                  > distances().get("pouf_table_max", 60)):
            out.append(_v("POUF_FAR_FROM_TABLE",
                          f"пуф в {footprint(pouf).distance(footprint(tbl)):.0f} см от столика",
                          ["пуф", "столик"], None,
                          f"≤{distances().get('pouf_table_max', 60)} см: пуф — подставка для ног"))
        if footprint(pouf).distance(footprint(sofa)) > distances().get("sofa_pouf_max", 180):
            out.append(_v("SOFA_POUF_FAR",
                          f"пуф в {footprint(pouf).distance(footprint(sofa)):.0f} см от дивана",
                          ["диван", "пуф"], None,
                          f"≤{distances().get('sofa_pouf_max', 180)} см — пуф в зоне"))
    # ВСЕ экземпляры кресел (ревью рефери 08.08, set55/84 «кресло у витрины неясно зачем»):
    # прежний by.get("кресло") видел только первый — «кресло 2» уходило из зоны безнаказанно,
    # и каждая посадка обязана принадлежать зоне (EVERY_SEAT_BELONGS_TO_ZONE)
    for arm in _inst(ps, "кресло"):
        if arm.item is None:
            continue
        if tbl is not None and _lr("armchair_to_table_same_as_sofa", True):
            # T6: фикс-эргономика и для кресла (последний потребитель area-шкалы sofa_table_cm
            # вычищен — рефери §23 «кресло всё ещё зависит от площади, диван уже нет»)
            lo_t, hi_t = distances().get("sofa_coffee_table", [36, 46])
            g = footprint(arm).distance(footprint(tbl))
            if not (lo_t - 5 <= g <= hi_t + 60):
                out.append(_v("ARMCHAIR_TABLE_DIST", f"«{arm.role}» в {g:.0f} см от столика — вне зоны",
                              [arm.role, "столик"], round(g),
                              f"{lo_t:.0f}–{hi_t + 60:.0f} см (зона вокруг столика)"))
        # D5 (вторичная зона): кресло камин-уголка — дуговые чеки не применяются
        if _in_fireplace_zone(ps, arm):
            continue
        rg4 = by.get("ковёр")
        if rg4 is not None and footprint(arm).intersection(footprint(rg4)).area < arm.item.w_cm * 10:
            out.append(_v("ARMCHAIR_OFF_RUG",
                          f"«{arm.role}» не на ковре группы (передние ножки должны заходить)",
                          [arm.role, "ковёр"], None, "передние ножки на ковре",
                          Severity.SOFT))
        # D3 (вердикт владельца set59 + Swyft/Dimensions): кресло НЕ у ТВ-носителя —
        # там оно спиной/боком к экрану и вне разговорной дуги
        tvb = by.get("тв-тумба") or by.get("стенка")
        if tvb is not None and footprint(arm).distance(footprint(tvb)) < \
                float(rules().get("dynamic", {}).get("armchair_clearances", {})
                      .get("not_at_tv_wall_gap_cm", 80)):
            out.append(_v("ARMCHAIR_AT_TV_WALL",
                          f"«{arm.role}» вплотную к ТВ-носителю — вне разговорной дуги",
                          [arm.role], None, "кресло напротив/по диагонали от дивана"))
            continue
        fwd, lat = relative_position(sofa, arm)
        if fwd < -20:
            out.append(_v("ARMCHAIR_BEHIND_SOFA", f"«{arm.role}» стоит за диваном", ["диван", arm.role],
                          round(fwd), "в зоне перед диваном"))
            continue
        # P0.4 (рефери 08.08): у Г/П-дивана кресло — только со стороны conversation opening;
        # боковой предел меряем от АКТИВНОГО центра (плечо — закрытая сторона)
        if tbl is not None:
            fwd_t, _ = relative_position(sofa, tbl)
            if fwd - fwd_t > 60 + arm.item.d_cm / 2:
                out.append(_v("ARMCHAIR_OUT_OF_ZONE",
                              f"«{arm.role}» уехало вперёд столика к медиастене",
                              ["диван", arm.role], round(fwd - fwd_t),
                              "не дальше линии столика (+60 см)"))
                continue
        if abs(lat - act_lat) > act_w / 2 + arm.item.w_cm + 60:
            out.append(_v("ARMCHAIR_OUT_OF_ZONE", f"«{arm.role}» в {abs(lat - act_lat):.0f} см от посадки",
                          ["диван", arm.role], round(abs(lat - act_lat)),
                          f"≤{act_w / 2 + arm.item.w_cm + 60:.0f} см от центра посадки"))
            continue
        # P0.3 (рефери 08.08): кресло — участник беседы: его луч взгляда обязан пересекать
        # столик (с запасом) или разговорный центр перед активным фронтом дивана
        import math as _m

        afx, afy = facing_vector(arm.rot)
        ac = footprint(arm).centroid
        # конус взгляда ≤45°: цель — столик, разговорный центр или ТВ-носитель (media-сценарий)
        sfx, sfy = facing_vector(sofa.rot)
        latx, laty = -sfy, sfx     # +lateral в мировых координатах
        gap = (distances().get("sofa_coffee_table", [36, 46])[1] + 30)
        cc = (sofa.x + latx * act_lat + sfx * (sofa.item.d_cm / 2 + gap),
              sofa.y + laty * act_lat + sfy * (sofa.item.d_cm / 2 + gap))
        tgt_pts = [cc]
        if tbl is not None:
            tgt_pts.append((footprint(tbl).centroid.x, footprint(tbl).centroid.y))
        tv_b = by.get("тв-тумба") or by.get("стенка")
        if tv_b is not None:
            tgt_pts.append((footprint(tv_b).centroid.x, footprint(tv_b).centroid.y))
        def _in_cone(px, py):
            vx, vy = px - ac.x, py - ac.y
            n = _m.hypot(vx, vy)
            return n <= 30 or (vx * afx + vy * afy) / max(n, 1e-6) >= _m.cos(_m.radians(45))
        matched = [i for i, (px, py) in enumerate(tgt_pts) if _in_cone(px, py)]
        if not matched:
            out.append(_v("ARMCHAIR_NOT_FACING_GROUP",
                          f"«{arm.role}» не смотрит в разговорный центр группы",
                          [arm.role], None, "луч взгляда через столик/центр беседы"))
        elif tbl is not None and matched == [len(tgt_pts) - 1]:
            # E4 (вердикт владельца set66 + CHITA/Bellona): взгляд ТОЛЬКО на ТВ через
            # комнату — не членство; кресло обязано быть при столике группы (reach ≤106)
            g4 = footprint(arm).distance(footprint(tbl))
            if g4 > 106:
                out.append(_v("ARMCHAIR_NOT_FACING_GROUP",
                              f"«{arm.role}» смотрит на ТВ издалека, столик вне reach ({g4:.0f} см)",
                              [arm.role, "столик"], round(g4), "в группе: столик ≤106 см"))
    # F1 (канон пары кресел): пара в conversation-группе — зеркально относительно оси
    # диван→фокус ИЛИ бок-о-бок (зазор 30–45, один разворот); иначе — мягкий штраф
    # пара не разрывается между зонами: ровно один из двух у камина — брак паттерна
    _arms_any = [a for a in _inst(ps, "кресло") if a.item is not None]
    if len(_arms_any) == 2:
        _fz = [_in_fireplace_zone(ps, a) for a in _arms_any]
        if _fz.count(True) == 1:
            out.append(_v("PAIR_PATTERN",
                          "пара кресел разорвана между зонами (одно у камина, одно у дивана)",
                          [a.role for a in _arms_any], None,
                          "оба во фланг камина ИЛИ оба в разговорной группе", Severity.SOFT))
    arms_all = [a for a in _inst(ps, "кресло")
                if a.item is not None and not _in_fireplace_zone(ps, a)]
    if len(arms_all) >= 2:
        a1, a2 = arms_all[0], arms_all[1]
        f1, l1 = relative_position(sofa, a1)
        f2, l2 = relative_position(sofa, a2)
        mirror = abs((l1 - act_lat) + (l2 - act_lat)) <= 60 and abs(f1 - f2) <= 60
        gap12 = footprint(a1).distance(footprint(a2))
        side_by_side = gap12 <= 60 and int(a1.rot) % 360 == int(a2.rot) % 360
        if not (mirror or side_by_side):
            out.append(_v("PAIR_PATTERN",
                          "пара кресел стоит вразнобой — ни зеркала, ни бок-о-бок",
                          [a1.role, a2.role], None,
                          "зеркально к оси или рядом (зазор 30–45)", Severity.SOFT))
    return out


def _view_corridor(sofa: Placement, tv: Placement):
    """Полоса обзора диван→экран ШИРИНОЙ НОСИТЕЛЯ (не convex hull двух предметов: у П-дивана
    341 см hull накрывал полкомнаты и ложно ловил фланги камина у ТВ-стены — G-разбор 08.08)."""
    from shapely.geometry import LineString

    sc = footprint(sofa).centroid
    tc = footprint(tv).centroid
    # ширина полосы = ЭКРАН (~70% носителя, Q2-приор), не носитель целиком: кресла,
    # канонично фланкирующие ТВ/камин, не должны ловиться как «между диваном и экраном»
    w = 0.70 * (tv.item.w_cm if tv.item else 120)
    return LineString([(sc.x, sc.y), (tc.x, tc.y)]).buffer(w / 2)


def check_sightline(ps: list[Placement]) -> list[Violation]:
    """Линия взгляда диван→ТВ не должна быть перекрыта (Infinigen: «экран не загорожен»)."""
    by = _by_base(ps)
    sofa, tv = by.get("диван"), by.get("тв-тумба")
    if sofa is None or tv is None or sofa.item is None or tv.item is None:
        return []
    corridor = _view_corridor(sofa, tv)
    out = []
    for p in ps:
        # сам носитель (тумба ИЛИ стенка-алиас) и сам диван коридор не «блокируют»
        if p is tv or p is sofa or p.role in ("диван", "тв-тумба", "ковёр", "столик"):
            continue
        h = (p.item.h_cm if p.item else None) or 0
        if h <= 60:                     # ниже линии взгляда сидящего — не мешает
            continue
        if footprint(p).intersection(corridor).area > 400:
            out.append(_v("SIGHTLINE_BLOCKED", f"«{p.role}» перекрывает вид на ТВ", [p.role, "тв-тумба"],
                          None, "коридор диван↔ТВ свободен"))
    return out


ZONE_ROLES = frozenset({"диван", "столик", "кресло", "пуф", "ковёр", "торшер"})


def check_layout_rules(room: Room, ps: list[Placement]) -> list[Violation]:
    """Правила, потерянные при переносе из DFS-движка (см. layout_rules в файле правил)."""
    by = _by_base(ps)
    out: list[Violation] = []
    tv = by.get("тв-тумба")
    sofa = by.get("диван")

    def wall_of(p: Placement) -> str | None:
        x0, y0, x1, y1 = footprint(p).bounds
        d = {"west": x0, "south": y0, "east": room.width_cm - x1, "north": room.depth_cm - y1}
        w = min(d, key=d.get)
        return w if d[w] <= 25 else None

    if tv is not None and _lr("tv_not_on_window_wall", True):
        tvw = wall_of(tv)
        if tvw and any(o.kind == "window" and o.wall == tvw for o in room.openings):
            out.append(_v("TV_ON_WINDOW_WALL", "ТВ на стене с окном — блики в экран", ["тв-тумба"],
                          None, "ТВ на глухой стене", Severity.SOFT))
    # Ревью рефери 08.08 (set59/84): стенка = носитель ТВ → отдельная тумба при стенке —
    # дубль носителя. Составы новее правила это не кладут (compose-mutex); код ловит ЛЕГАСИ
    # сеты. S1 до пересборки волны A8, после — поднять в H1 (план referee-hardening).
    if "стенка" in by and "тв-тумба" in by and by["стенка"] is not by["тв-тумба"]:
        out.append(_v("TV_STAND_WITH_WALL_UNIT",
                      "стенка и отдельная ТВ-тумба — два носителя ТВ",
                      ["стенка", "тв-тумба"], None, "носитель один: стенка", Severity.SOFT))
    if tv is not None:
        tvw = wall_of(tv)
        hmin = float(_lr("tall_storage_not_on_tv_wall_h_cm", 110))
        for p in ps:
            if p is tv:
                continue   # носитель ТВ (стенка-алиас, правило владельца 08.08) сам себя не штрафует
            if p.role in ("шкаф", "стенка", "стеллаж", "витрина") and (p.item.h_cm or 0) >= hmin \
                    and wall_of(p) == tvw and tvw is not None:
                out.append(_v("TALL_ON_TV_WALL", f"«{p.role}» на стене ТВ — стена перегружена",
                              [p.role, "тв-тумба"], None, "высокое хранение на другой стене",
                              Severity.SOFT))
        # Правило «камин не на ТВ-стене» ОТМЕНЕНО (вердикт владельца 07.08, сет 104): оно
        # выталкивало камин за спину дивана — абсурд. Практика: ТВ над/рядом с камином — норма;
        # «за спиной» ловит DEAD_ZONE_BEHIND_SOFA (камин в DEAD_BEHIND_ROLES).
        if "камин" in by and _lr("fireplace_not_on_tv_wall", False) and wall_of(by["камин"]) == tvw:
            out.append(_v("FIREPLACE_ON_TV_WALL", "камин и ТВ на одной стене — два центра внимания",
                          ["камин", "тв-тумба"], None, "камин на другой стене", Severity.SOFT))
    if sofa is not None and tv is not None and "пуф" in by and _lr("pouf_out_of_view_axis", True):
        corridor = _view_corridor(sofa, tv)
        if footprint(by["пуф"]).intersection(corridor).area > 900:
            out.append(_v("POUF_IN_VIEW_AXIS", "пуф стоит на оси просмотра диван↔ТВ", ["пуф"],
                          None, "сбоку от оси"))
    # E5 (вердикт владельца set113 + Wayfair/Houzz «unobstructed view у каждой посадки»):
    # НИКАКАЯ посадка не стоит между диваном и экраном — расширение пуфового правила
    if sofa is not None and tv is not None:
        corridor = _view_corridor(sofa, tv)
        for arm in _inst(ps, "кресло"):
            if footprint(arm).intersection(corridor).area > 900:
                out.append(_v("SEAT_IN_VIEW_AXIS",
                              f"«{arm.role}» между диваном и экраном — загораживает просмотр",
                              [arm.role], None, "сбоку от оси, углом к ТВ"))
    if sofa is not None and sofa.item is not None and sofa.item.corner \
            and _lr("corner_sofa_must_be_in_corner", True):
        x0, y0, x1, y1 = footprint(sofa).bounds
        # жёстко — хотя бы одна секция у стены; «оба плеча в углу» поощряется скорингом
        # (в глубокой комнате Г обязан отплывать к ТВ, иначе не выполняется шкала — ADR-0050)
        near_x = min(x0, room.width_cm - x1) <= 25
        near_y = min(y0, room.depth_cm - y1) <= 25
        room_m2 = room.width_cm * room.depth_cm / 10_000
        if room_m2 < 30 and not (near_x and near_y):
            # E7 (вердикт владельца set117 + Castlery/Swyft): в малых/средних Г-диван стоит
            # УГЛОМ В УГОЛ — обе секции вдоль двух смежных стен
            out.append(_v("CORNER_SOFA_ADRIFT", "Г-диван не углом в угол (обе секции к стенам)",
                          ["диван"], None, "вдоль двух смежных стен", Severity.SOFT))
        elif not (near_x or near_y):
            # в больших floating разрешён, но плечо к стене (ADR-0050)
            out.append(_v("CORNER_SOFA_ADRIFT", "угловой диван стоит посреди комнаты", ["диван"],
                          None, "хотя бы одна секция к стене", Severity.SOFT))
    if "кресло" in by and sofa is not None and by.get("столик") is not None:
        # кресло стоит НА ЛИНИИ столика (полукруг вокруг зоны), а не глубже — иначе оно уезжает
        # к ТВ-тумбе и читается как часть ТВ-зоны (вердикт владельца 2026-08-03). Проверка «та же
        # стена» не годится: в углу предмет числится по соседней стене и правило не срабатывало.
        fwd_a, _ = relative_position(sofa, by["кресло"])
        fwd_t, _ = relative_position(sofa, by["столик"])
        if fwd_a > fwd_t + 80:
            out.append(_v("ARMCHAIR_TOO_DEEP", "кресло уехало за столик, к ТВ-зоне", ["кресло", "столик"],
                          round(fwd_a - fwd_t), "не дальше 80 см за линию столика"))
    if "стул" in by and "стол обеденный" not in by and _lr("chair_requires_dining_table", True):
        out.append(_v("CHAIR_WITHOUT_TABLE", "стул без обеденного стола", ["стул"], None,
                      "стул ставится только к столу"))
    buf = float(_lr("zone_buffer_cm", 40))  # T6: фолбэк = значению данных (65 был остатком DFS-эры)
    if sofa is not None and buf > 0:
        zone = footprint(sofa)
        if "столик" in by:
            zone = zone.union(footprint(by["столик"]))
        zone = zone.buffer(buf)
        for p in ps:
            if p.role in ZONE_ROLES or p.item is None:
                continue
            if (p.item.h_cm or 0) <= 60:      # низкий декор зону не ломает
                continue
            if footprint(p).intersection(zone).area > 900:
                out.append(_v("ZONE_BUFFER", f"«{p.role}» вплотную к разговорной зоне", [p.role],
                              None, f"≥{buf:.0f} см от дивана/столика", Severity.SOFT))
    return out


def check_floor_cap(room: Room, ps: list[Placement]) -> list[Violation]:
    from .geometry import floor_used_pct

    cap = band_scale("floor_cap_pct", room.band, [26, 50])
    used = floor_used_pct(room, ps)
    if used > cap[1] + 0.5:
        # Рефери 08.08 (Q5): процент сам по себе не брак — физику ловят коллизии/проходы/
        # двери/доступ; плотность — операционный приор (S1), не hard
        return [_v("FLOOR_OVERFILL", f"мебель занимает {used:.0f}% пола", [], round(used, 1),
                   f"≤{cap[1]:.0f}%", Severity.SOFT)]
    return []


def check_decor_anchoring(room: Room, ps: list[Placement]) -> list[Violation]:
    """E2/E3 (вердикты владельца set66 + Outlight/Lightopia, MyPlantin/MaisonDePax):
    торшер живёт У ПОСАДКИ (рядом/чуть позади дивана или кресла), кашпо — периметр/угол/
    окно/фланг крупной мебели; центр комнаты — антипаттерн для обоих."""
    out = []
    seats = ([p for p in ps if p.role.split(' ')[0] in ("диван", "кресло")])
    for p in ps:
        base = p.role.split(' ')[0]
        if base == "торшер" and seats:
            d = min(footprint(p).distance(footprint(sp)) for sp in seats)
            if d > 90:
                out.append(_v("LAMP_ORPHAN", f"торшер в {d:.0f} см от посадки — далековато",
                              [p.role], round(d), "60–90 см от посадки", Severity.SOFT))
        if base == "кашпо":
            x0, y0, x1, y1 = footprint(p).bounds
            wall_gap = min(x0, y0, room.width_cm - x1, room.depth_cm - y1)
            big = [q for q in ps
                   if q.role.split(' ')[0] in ("диван", "стенка", "шкаф", "стеллаж", "комод",
                                               "витрина", "тв-тумба", "камин")]
            flank = min((footprint(p).distance(footprint(q)) for q in big), default=999)
            if wall_gap > 70 and flank > 50:
                out.append(_v("PLANT_IN_OPEN_FLOOR",
                              f"кашпо в открытом полу ({wall_gap:.0f} см от стен)",
                              [p.role], round(wall_gap),
                              "периметр/угол/окно/фланг мебели", Severity.SOFT))
    return out


def check_service_surface(room: Room, ps: list[Placement]) -> list[Violation]:
    """A1 (исследование рефери 08.08, H&G «every seat needs a surface» + Function2Scene
    reach/activity_support): у каждого primary-места (диван, каждый экземпляр кресла) —
    поверхность (столик/приставной/консоль) в досягаемости. Coverage-правило: одна поверхность
    обслуживает соседние места; «каждому креслу свой стол» НЕ требуется. Параметры —
    zones.json group_scheme.service_surface."""
    from .zones import zone_rules

    ss = zone_rules().get("group_scheme", {}).get("service_surface", {})
    if not ss:
        return []
    reach = float(ss.get("reach_cm", 75))
    surf_roles = set(ss.get("surface_roles", ["столик", "приставной"]))
    surfaces = [footprint(p) for p in ps
                if p.role in surf_roles or p.role.split(' ')[0] in surf_roles]
    if not surfaces:
        surfaces = []
    out = []
    for p in ps:
        base = p.role.split(' ')[0]
        if base not in ("диван", "кресло"):
            continue
        fp = footprint(p)
        if not any(fp.distance(s) <= reach for s in surfaces):
            out.append(_v("SERVICE_SURFACE",
                          f"у «{p.role}» нет поверхности в {reach:.0f} см — напиток ставить некуда",
                          [p.role], None, f"столик/приставной в ≤{reach:.0f} см", Severity.SOFT))
    return out


def check_fireplace_seating(room: Room, ps: list[Placement]) -> list[Violation]:
    """P0.7 (рефери 08.08, финальный свод): камин — focal-элемент, не filler; H1.
    Разрешён, только если он в focal-зоне ХОТЬ ОДНОЙ посадки: (A) primary — главный диван
    в вилке distance_to_seating_cm и секторе primary_sector_deg; (B) secondary — кресло в
    камин-уголке (secondary_zone). Ни A, ни B → HARD (кандидатный гейт _fireplace_scenario
    такие места и не предлагает — код ловит легаси/чужие пути). Все числа — zones.json;
    текст нарушения строится из них же (L2: один источник, дрифт текстов невозможен)."""
    import math as _m

    from .zones import zone_rules

    by = _by_base(ps)
    fp = by.get("камин")
    if fp is None:
        return []
    # secondary: кресло в камин-зоне (окно+конус из secondary_zone) — фокус обеспечен
    if any(_in_fireplace_zone(ps, a) for a in _inst(ps, "кресло")):
        return []
    seats = [by["диван"]] if "диван" in by else []
    if not seats:
        return []
    fz = zone_rules()["zones"]["seating_media"]["fireplace"]
    lo, hi = fz["distance_to_seating_cm"]
    sec = fz.get("primary_sector_deg", {})
    sec_sofa = float(sec.get("диван", 35))
    sec_other = float(sec.get("прочая_посадка", 45))
    ffp = footprint(fp)
    # G2-пересмотр (веб-проверка 08.08): угловой камин ЛЕГАЛЕН (corner electric fireplace —
    # признанный класс), но ТОЛЬКО как настоящий фокус: посадка обязана быть ориентирована
    # НА него (E6, set113: камин ПЕРЕД посадкой, сектор primary_sector_deg) — либо кресла-фланг.
    for seat in seats:
        d = footprint(seat).distance(ffp)
        if not (lo <= d <= hi):
            continue
        fx, fy = facing_vector(seat.rot)
        sc, fc = footprint(seat).centroid, ffp.centroid
        vx, vy = fc.x - sc.x, fc.y - sc.y
        n = _m.hypot(vx, vy)
        sector = sec_sofa if seat.role.split(' ')[0] == 'диван' else sec_other
        if n <= 1 or (vx * fx + vy * fy) / n >= _m.cos(_m.radians(sector)):
            return []   # камин в focal-зоне этой посадки — сценарий есть
    return [_v("FIREPLACE_FAR_FROM_SEATING",
               f"камин вне focal-зоны любой посадки (вилка {lo:.0f}–{hi:.0f}, "
               f"сектор {sec_sofa:.0f}°/{sec_other:.0f}°)",
               ["камин"], None, "primary- или secondary-focal зона")]


def check_window_sofa(room: Room, ps: list[Placement]) -> list[Violation]:
    """Вердикт владельца 08.08 (set91: диван вплотную к окну) + рефери Q7 — раздельно:
    доступ/радиатор уже H0 (WINDOW_BLOCKED/RADIATOR); здесь мягкое — зазор спинка↔окно S1
    (tight-минимум из window_sofa) и «спинка выше низа стекла» S2."""
    by = _by_base(ps)
    sofa = by.get("диван")
    if sofa is None or sofa.item is None:
        return []
    from .clearances import rules as _rules
    ws = _rules().get("dynamic", {}).get("window_sofa", {})
    gap_min = float((ws.get("min_offset_from_window_cm") or [15, 20])[0])
    fx, fy = facing_vector(sofa.rot)
    back_wall = ("south" if fy > 0 else "north") if abs(fy) > abs(fx) else \
                ("west" if fx > 0 else "east")
    x0, y0, x1, y1 = footprint(sofa).bounds
    out = []
    for op in room.openings:
        if op.kind != "window" or op.wall != back_wall:
            continue
        # поперечное перекрытие проёма спинкой
        span = (x0, x1) if op.wall in ("south", "north") else (y0, y1)
        if min(span[1], op.offset_cm + op.width_cm) - max(span[0], op.offset_cm) < 30:
            continue
        gap = {"south": y0, "north": room.depth_cm - y1,
               "west": x0, "east": room.width_cm - x1}[op.wall]
        if gap < gap_min:
            out.append(_v("SOFA_WINDOW_GAP",
                          f"диван спинкой к окну в {gap:.0f} см — воздуха/шторам нет",
                          ["диван"], round(gap), f"≥{gap_min:.0f} см", Severity.SOFT))
        if op.sill_cm > 0 and (sofa.item.h_cm or 0) > op.sill_cm:
            out.append(_v("SOFA_BACK_ABOVE_SILL",
                          f"спинка {sofa.item.h_cm:.0f} см выше низа стекла ({op.sill_cm:.0f})",
                          ["диван"], sofa.item.h_cm, f"≤{op.sill_cm:.0f} см", Severity.SOFT))
        break
    return out


def check_sofa_pair_geometry(ps: list[Placement]) -> list[Violation]:
    """W2 kb-rules-merge (владелец 10.08; урок ручного демо 57.5 м²): пара диванов
    легальна ЛИЦОМ-К-ЛИЦУ (sofa_facing_sofa) или Г-стыком ТОРЕЦ-К-ТОРЦУ. Фронт
    одного дивана, упирающийся в БОК/СПИНКУ другого, — блокировка: сидящие смотрят
    в заднюю панель соседа (S1)."""
    import math as _m
    import os as _os

    from .geometry import base_role

    if _os.environ.get("KDB_DISABLE_SOFA_PAIR"):   # отладка/изоляция A-B
        return []
    sofas = [p for p in ps if base_role(p.role) == "диван" and p.item is not None]
    if len(sofas) < 2:
        return []
    out: list[Violation] = []
    for a in sofas:
        for b in sofas:
            if a is b:
                continue
            ang = (a.rot - b.rot) % 360
            if 150 <= ang <= 210:      # лицом-к-лицу: дистанцию держит facing-чек
                continue
            r = _m.radians(a.rot)
            fx, fy = _m.sin(r), _m.cos(r)
            fz = Placement(role="_front", rot=a.rot,
                           x=a.x + fx * (a.item.d_cm / 2 + 60),
                           y=a.y + fy * (a.item.d_cm / 2 + 60),
                           item=Item(role="_front", w_cm=a.item.w_cm,
                                     d_cm=120, h_cm=1))
            fb = footprint(b)
            inter = footprint(fz).intersection(fb)
            if fb.area > 0 and inter.area > 0.2 * fb.area:
                out.append(_v("SOFA_BLOCKS_SOFA",
                              f"фронт «{a.role}» упирается в бок/спинку «{b.role}» "
                              f"(перекрытие {inter.area / fb.area:.0%})",
                              [a.role, b.role], None,
                              "лицом-к-лицу или Г-стык торец-к-торцу",
                              severity=Severity.SOFT))
    return out


def validate(room: Room, placements: list[Placement], *, passage: str = "secondary") -> Layout:
    _ROOM_BAND[0] = room.band
    vs: list[Violation] = []
    vs += check_boundary(room, placements)
    vs += check_collisions(placements)
    vs += check_openings(room, placements)
    vs += check_radiators(room, placements)
    vs += check_access(placements)
    vs += check_passages(room, placements, passage)
    vs += check_distances(room, placements)
    vs += check_facing(placements)
    vs += check_wall_only(room, placements)
    vs += check_zone(placements)
    vs += check_sightline(placements)
    vs += check_behind_sofa(room, placements)
    vs += check_sofa_sliver(room, placements)
    vs += check_dead_zone_behind_sofa(room, placements)
    vs += check_sofa_aim(room, placements)
    vs += check_sofa_pair_geometry(placements)
    vs += check_chairs_at_table(room, placements)
    vs += check_functional_zones(room, placements)
    vs += check_layout_rules(room, placements)
    vs += check_floor_cap(room, placements)
    vs += check_fireplace_seating(room, placements)
    vs += check_window_sofa(room, placements)
    vs += check_service_surface(room, placements)
    vs += check_decor_anchoring(room, placements)
    from .geometry import floor_used_pct

    return Layout(room=room, placements=placements, violations=vs,
                  floor_used_pct=round(floor_used_pct(room, placements), 1))
