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
from .models import Layout, Placement, Room, Severity, Violation

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
        fa = footprint(a)
        for b in ps[i + 1:]:
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
    """Функциональная зона (подход/ноги/фасады) не должна быть занята другим предметом."""
    out = []
    for a in ps:
        zone = access_zone(a)
        if zone.is_empty:
            continue
        for b in ps:
            if b is a or b.role in NEVER_BLOCKING_ROLES:
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


def check_distances(room: Room, ps: list[Placement]) -> list[Violation]:
    """Шкалы проекта от площади: диван↔ТВ, диван↔столик (решения владельца)."""
    by = {p.role: p for p in ps}
    out = []
    tv = band_scale("sofa_tv_cm", room.band, distances().get("sofa_tv_cm", [180, 300]))
    tbl = band_scale("sofa_table_cm", room.band, distances().get("sofa_coffee_table", [36, 50]))
    if "диван" in by and "тв-тумба" in by:
        g = _zone_gap(by["диван"], by["тв-тумба"])
        # СЛИШКОМ БЛИЗКО — жёстко (глаза), СЛИШКОМ ДАЛЕКО — мягко: в глубокой комнате верхняя
        # граница шкалы заставляла диван «отплывать» от стены на метр, что владелец забраковал.
        # Абсолютный потолок — из клампа диагоналей свода (2.5 диагонали ≈ 400 см).
        hard_hi = max(tv[1], float(distances().get("sofa_tv_hard_max", 400)))
        if g < tv[0] or g > hard_hi:
            out.append(_v("SOFA_TV_DIST", f"диван↔ТВ {g:.0f} см вне шкалы", ["диван", "тв-тумба"],
                          round(g), f"{tv[0]:.0f}–{hard_hi:.0f} см"))
        elif g > tv[1]:
            out.append(_v("SOFA_TV_FAR", f"диван↔ТВ {g:.0f} см — дальше комфортной шкалы",
                          ["диван", "тв-тумба"], round(g), f"≤{tv[1]:.0f} см", Severity.SOFT))
    if "диван" in by and "столик" in by:
        g = _zone_gap(by["диван"], by["столик"])
        if not (tbl[0] <= g <= tbl[1]):
            out.append(_v("SOFA_TABLE_DIST", f"диван↔столик {g:.0f} см вне шкалы", ["диван", "столик"],
                          round(g), f"{tbl[0]:.0f}–{tbl[1]:.0f} см"))
    if "диван" in by and "кресло" in by:
        g = footprint(by["диван"]).distance(footprint(by["кресло"]))
        lim = distances().get("seats_group_max", 200)   # единый порог для обоих движков
        if g > lim:
            out.append(_v("SEATS_TOO_FAR", f"диван↔кресло {g:.0f} см — зона разорвана", ["диван", "кресло"],
                          round(g), f"≤{lim:.0f} см"))
    return out


# Мебель хранения/техники живёт ТОЛЬКО у стены (ProcTHOR placement-annotations: onEdge,
# inMiddle=false). Отдельно стоящий шкаф посреди комнаты — вердикт владельца «так нельзя».
WALL_ONLY_ROLES = frozenset({"тв-тумба", "шкаф", "комод", "стенка", "витрина", "стеллаж", "камин"})
WALL_TOUCH_MAX_CM = 20.0


def check_wall_only(room: Room, ps: list[Placement]) -> list[Violation]:
    """Корпусная мебель стоит СПИНКОЙ к стене, а не «касается стены каким-нибудь боком».

    Раньше хватало любой ближайшей стороны — и комод вставал перпендикулярно, торча в комнату
    как перегородка, формально «у стены» (вердикт владельца 2026-08-03).
    """
    out = []
    for p in ps:
        if p.role not in WALL_ONLY_ROLES:
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


def check_facing(ps: list[Placement]) -> list[Violation]:
    """«Диван параллельно телеку» (правило владельца): фронты встречные + боковое перекрытие.

    Соответствует MILP-констрейнту Holodeck «относительные позиции — в локальной системе цели,
    боковой разброс ≤ полуширины цели».
    """
    by = {p.role: p for p in ps}
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
    by = {p.role: p for p in ps}
    sofa = by.get("диван")
    if sofa is None or sofa.item is None:
        return []
    strip = _behind_strip(room, sofa)   # вся ширина комнаты (вердикт 07.08, сет 25)
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
DEAD_BEHIND_ROLES = ("кашпо", "торшер", "столик", "пуф", "кресло",
                     "стол обеденный", "стул", "лампа", "ваза", "камин")


def _behind_strip(room: Room, sofa: Placement):
    """Полоса за спинкой дивана НА ВСЮ ШИРИНУ КОМНАТЫ (вердикты 07.08: торшер за плечом,
    стеллаж в углу за спиной — узкая полоса «в ширину дивана» их пропускала)."""
    from shapely.geometry import box as _box

    fx, fy = facing_vector(sofa.rot)
    x0, y0, x1, y1 = footprint(sofa).bounds
    if abs(fy) > abs(fx):
        return _box(0, 0, room.width_cm, y0) if fy > 0 else _box(0, y1, room.width_cm, room.depth_cm)
    return (_box(0, 0, x0, room.depth_cm) if fx > 0
            else _box(x1, 0, room.width_cm, room.depth_cm))


def check_dead_zone_behind_sofa(room: Room, ps: list[Placement]) -> list[Violation]:
    by = {p.role: p for p in ps}
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

    by = {p.role: p for p in ps}
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
    by = {p.role: p for p in ps}
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


_ROOM_BAND = [None]      # текущий бэнд для проверок зоны (ставится в validate)


def check_zone(ps: list[Placement]) -> list[Violation]:
    """Разговорная зона — не набор «где-то рядом»: столик перед диваном, кресло в зоне.

    Боковой разброс ограничен полушириной якоря (+запас) — правило Holodeck-MILP;
    кресло допускается сбоку-впереди (дуга ADR-0051), но не за спинкой дивана.
    """
    by = {p.role: p for p in ps}
    sofa = by.get("диван")
    if sofa is None or sofa.item is None:
        return []
    half = sofa.item.w_cm / 2
    out = []
    tbl = by.get("столик")
    if tbl is not None:
        fwd, lat = relative_position(sofa, tbl)
        if fwd <= 0:
            out.append(_v("TABLE_BEHIND_SOFA", "столик не перед диваном", ["диван", "столик"],
                          round(fwd), "перед фронтом дивана"))
        elif abs(lat) > half * 0.75:
            out.append(_v("TABLE_OFF_AXIS", f"столик смещён на {abs(lat):.0f} см от оси дивана",
                          ["диван", "столик"], round(abs(lat)), f"≤{half * 0.75:.0f} см"))
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
    arm = by.get("кресло")
    if arm is not None and tbl is not None and _lr("armchair_to_table_same_as_sofa", True):
        from .clearances import band_scale as _bs
        lo_t, hi_t = _bs("sofa_table_cm", _ROOM_BAND[0], distances().get("sofa_coffee_table", [36, 50]))
        g = footprint(arm).distance(footprint(tbl))
        if not (lo_t - 5 <= g <= hi_t + 60):
            out.append(_v("ARMCHAIR_TABLE_DIST", f"кресло в {g:.0f} см от столика — вне зоны",
                          ["кресло", "столик"], round(g),
                          f"{lo_t:.0f}–{hi_t + 60:.0f} см (зона вокруг столика)"))
    if arm is not None and arm.item is not None:
        fwd, lat = relative_position(sofa, arm)
        if fwd < -20:
            out.append(_v("ARMCHAIR_BEHIND_SOFA", "кресло стоит за диваном", ["диван", "кресло"],
                          round(fwd), "в зоне перед диваном"))
        elif abs(lat) > half + arm.item.w_cm + 60:
            out.append(_v("ARMCHAIR_OUT_OF_ZONE", f"кресло в {abs(lat):.0f} см вбок от зоны",
                          ["диван", "кресло"], round(abs(lat)),
                          f"≤{half + arm.item.w_cm + 60:.0f} см"))
    return out


def check_sightline(ps: list[Placement]) -> list[Violation]:
    """Линия взгляда диван→ТВ не должна быть перекрыта (Infinigen: «экран не загорожен»)."""
    by = {p.role: p for p in ps}
    sofa, tv = by.get("диван"), by.get("тв-тумба")
    if sofa is None or tv is None or sofa.item is None or tv.item is None:
        return []
    corridor = footprint(sofa).union(footprint(tv)).convex_hull.buffer(-5)
    out = []
    for p in ps:
        if p.role in ("диван", "тв-тумба", "ковёр", "столик"):
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
    by = {p.role: p for p in ps}
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
    if tv is not None:
        tvw = wall_of(tv)
        hmin = float(_lr("tall_storage_not_on_tv_wall_h_cm", 110))
        for p in ps:
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
        corridor = footprint(sofa).union(footprint(tv)).convex_hull.buffer(-30)
        if footprint(by["пуф"]).intersection(corridor).area > 900:
            out.append(_v("POUF_IN_VIEW_AXIS", "пуф стоит на оси просмотра диван↔ТВ", ["пуф"],
                          None, "сбоку от оси"))
    if sofa is not None and sofa.item is not None and sofa.item.corner \
            and _lr("corner_sofa_must_be_in_corner", True):
        x0, y0, x1, y1 = footprint(sofa).bounds
        # жёстко — хотя бы одна секция у стены; «оба плеча в углу» поощряется скорингом
        # (в глубокой комнате Г обязан отплывать к ТВ, иначе не выполняется шкала — ADR-0050)
        near_x = min(x0, room.width_cm - x1) <= 25
        near_y = min(y0, room.depth_cm - y1) <= 25
        if not (near_x or near_y):
            # мягко: в комнате 50+ Г-диван ОБЯЗАН отплыть от стены, иначе не выполнить шкалу диван↔ТВ
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
    buf = float(_lr("zone_buffer_cm", 65))
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
        return [_v("FLOOR_OVERFILL", f"мебель занимает {used:.0f}% пола", [], round(used, 1),
                   f"≤{cap[1]:.0f}%")]
    return []


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
    vs += check_chairs_at_table(room, placements)
    vs += check_functional_zones(room, placements)
    vs += check_layout_rules(room, placements)
    vs += check_floor_cap(room, placements)
    from .geometry import floor_used_pct

    return Layout(room=room, placements=placements, violations=vs,
                  floor_used_pct=round(floor_used_pct(room, placements), 1))
