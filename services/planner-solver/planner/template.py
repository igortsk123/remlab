"""T3 (solver-speed): зонные ШАБЛОНЫ — разговорная и обеденная зоны как атомарные блоки.

Идея владельца (10.08): перебираем не предметы, а ШАБЛОНЫ с запечённой внутренней
геометрией — столик/кресла/ковёр/стулья жёстко привязаны к якорю и «уехать» не могут;
вариантов на порядок меньше, клиренсы выверены книгой заранее (KB: круг беседы
366–396 см, столик 40–45 от фронта, Г-стык торец-к-торцу, визави ≤305 фронт-фронт,
стулья у стола с местом отодвигания — проверяет validate на итоговом наборе).

Механика: позиции якоря — существующий wall_candidates (диван; стол — ещё и middle);
блок инстанцируется в локальном фрейме якоря (rot 0 → смотрит +y; конвенция rot
компасная, по часовой — см. `geometry.footprint`: rotate(−rot)) от ФАКТИЧЕСКИХ
габаритов SKU. Г-диван — фронт и центр «свободной» части считаются от его прямой
секции (`geometry._corner_polygon`). Дешёвые пробы (все члены в free, ТВ-проба по
лучу взгляда) отбраковывают мёртвые позиции ДО валидации (ранняя отбраковка);
топ по эвристике проходит полный validate (hard); первый чистый блок побеждает.
Нет чистого блока → None, прежний путь beam (фолбэк — страховка «0 хуже»).

Выключатель для A/B и бисекта: LAYOUT_TEMPLATES=0.
"""
from __future__ import annotations

import math
import os

from shapely.geometry import Point, Polygon

from .candidates import middle_candidates, wall_candidates
from .geometry import footprint, room_polygon
from .models import Item, Placement, Room, Severity
from .validate import validate

# --- параметры внутренней геометрии (см); пруфы — KB/occupancy ---
COFFEE_GAP = 42.5                # столик от фронта дивана (preferred 40–45, KB 5.2)
FLANK_GAP = 32.0                 # кресло от торца дивана (25–40)
VIS_FACE = (183.0, 305.0)        # фронт-фронт визави (TYPICAL face-to-face, KB)
L_GAP = 20.0                     # Г-стык торец-к-торцу (10–30)
CIRCLE_D = 396.0                 # круг беседы, верх PREFERRED (KB)
CHAIR_GAP = 2.0                  # стул вплотную к кромке (заезд под столешницу =
                                 # COLLISION в движке — урок 205, стык без пересечения)
TOP_FULL_VALIDATE = 6            # лучших блоков на полный validate


def _rt(x: float, y: float, deg: float) -> tuple[float, float]:
    """Локаль → мир при компасном rot движка (0=север/+y, 90=восток/+x, по часовой):
    forward=(sin r, cos r), right=(cos r, −sin r); x — вправо, y — вперёд."""
    r = math.radians(deg)
    return (x * math.cos(r) + y * math.sin(r), -x * math.sin(r) + y * math.cos(r))


class Block:
    """Блок в локальном фрейме якоря: якорь в (0,0), rot 0 → смотрит +y (север)."""

    def __init__(self, anchor: Item):
        self.anchor = anchor
        self.rel: list[tuple[Item, float, float, float]] = [(anchor, 0.0, 0.0, 0.0)]

    def add(self, item: Item, x: float, y: float, rot: float) -> None:
        self.rel.append((item, x, y, rot % 360))

    def to_world(self, ax: float, ay: float, arot: float) -> list[Placement]:
        out = []
        for it, rx, ry, rrot in self.rel:
            wx, wy = _rt(rx, ry, arot)
            out.append(Placement(role=it.role, x=ax + wx, y=ay + wy,
                                 rot=(rrot + arot) % 360, item=it))
        return out


def _front(seat: Item) -> float:
    """Линия фронта посадки. Прямой предмет — d/2; Г-диван — фронт ПРЯМОЙ секции
    (её глубина = corner_section_cm, геометрия `geometry._corner_polygon`)."""
    if seat.corner:
        d = max(seat.d_cm, seat.corner_section_cm + 1)
        return -d / 2 + seat.corner_section_cm
    return seat.d_cm / 2


def _free_x(seat: Item) -> tuple[float, int]:
    """Центр свободной (неплечевой) части фронта Г-дивана и сторона, свободная от
    плеча (+1 = плечо слева, свободен правый фланг). Прямой диван: (0, +1)."""
    if not seat.corner:
        return 0.0, +1
    s = seat.corner_section_cm
    # плечо слева (corner_left) → свободная часть и фланг СПРАВА; плечо справа → слева
    return (s / 2, +1) if seat.corner_left else (-s / 2, -1)


def _add_coffee(b: Block, seat: Item, table: Item | None) -> tuple[float, float, float]:
    """Столик по центру свободного фронта якоря; у Г-дивана дополнительно отжат от
    плеча на hard-минимум 32 (SOFA_TABLE_DIST мерит мин-гэп футпринтов, плечо рядом).
    Возвращает (y дальней кромки, фактический x столика, y ЦЕНТРА столика)."""
    fx, _ = _free_x(seat)
    if table is None:
        return _front(seat) + COFFEE_GAP, fx, _front(seat) + COFFEE_GAP
    # столик длинной стороной ВДОЛЬ дивана (TABLE_ORIENTATION): нормализуем габариты
    tw, td = max(table.w_cm, table.d_cm), min(table.w_cm, table.d_cm)
    tt = table if table.w_cm >= table.d_cm else Item(
        role=table.role, w_cm=tw, d_cm=td, h_cm=table.h_cm, name=table.name,
        item_id=table.item_id)
    if seat.corner:
        sc = seat.corner_section_cm
        edge = seat.w_cm / 2 - sc            # ближний к плечу край свободной части
        if seat.corner_left:
            fx = max(sc / 2, -edge + 32 + tw / 2)
        else:
            fx = min(-sc / 2, edge - 32 - tw / 2)
    ty = _front(seat) + COFFEE_GAP + tt.d_cm / 2
    b.add(tt, fx, ty, 0.0)
    return ty + tt.d_cm / 2, fx, ty


def _add_rug(b: Block, seat: Item, rug: Item | None, far_y: float,
             min_left: float | None = None) -> None:
    """Ковёр — производная блока: по оси свободной части якоря, длинной стороной
    вдоль дивана. Габарит SKU фиксирован: крупный накрывает передние ножки,
    малый честно ложится под столик (легальный паттерн). min_left — левая граница
    (Г-стык: ковёр не заезжает под торец второго дивана — на чертеже сливалось
    в «перекрытие», замечание владельца 10.08)."""
    if rug is None:
        return
    fx, _ = _free_x(seat)
    w, d = max(rug.w_cm, rug.d_cm), min(rug.w_cm, rug.d_cm)
    if min_left is not None:
        fx = max(fx, min_left + w / 2)
    ry = max(_front(seat) - 15.0 + d / 2,
             min(_front(seat) + 5.0 + d / 2, (far_y + _front(seat)) / 2))
    b.add(Item(role=rug.role, w_cm=w, d_cm=d, h_cm=rug.h_cm, name=rug.name,
               item_id=rug.item_id), fx, ry, 0.0)


def _add_flank(b: Block, seat: Item, arm: Item, side: int, at_y: float,
               table_half_w: float | None = None) -> None:
    """Кресло флангом сбоку зоны на уровне столика, лицом к центру (компасный rot:
    справа → смотрит запад 270); не разлетаться шире круга беседы. У ШИРОКОГО
    дивана (set50: 285 см) якорь от торца уводит кресло от столика (ARMCHAIR_
    TABLE_DIST 109) — тогда якоримся к столику (min из двух)."""
    ax_sofa = seat.w_cm / 2 + FLANK_GAP + arm.d_cm / 2
    ax = ax_sofa
    if table_half_w is not None:
        ax = min(ax_sofa, table_half_w + FLANK_GAP + arm.d_cm / 2 + 20)
    ax = side * min(ax, CIRCLE_D / 2 - 10)
    b.add(arm, ax, at_y, 270.0 if side > 0 else 90.0)


def _add_facing(b: Block, seat: Item, other: Item, far_y: float) -> None:
    """Визави: второй посадочный напротив через столик, СИММЕТРИЧНО — равный
    зазор от столика с обеих сторон (замечание владельца 11.08: «один дальше
    другого»; книжный face-to-face получается из симметрии сам)."""
    fx, _ = _free_x(seat)
    b.add(other, fx, far_y + COFFEE_GAP + other.d_cm / 2, 180.0)


def _add_L(b: Block, sofa: Item, other: Item) -> None:
    """Г/П-стык (правка владельца 11.08): второй диван перпендикулярно слева,
    спинкой наружу; его ближний торец — на уровне ФРОНТА первого (не спинки:
    хвост до линии спинки читался как «перекрытие зоны» на чертеже)."""
    ox = -(sofa.w_cm / 2 + L_GAP + other.d_cm / 2)
    oy = _front(sofa) + 5.0 + other.w_cm / 2
    b.add(other, ox, oy, 90.0)


def build_block(group_id: str, by_role: dict[str, Item],
                variant: str = 'default') -> Block | None:
    """Инстанс шаблона разговорной группы от фактических SKU. v1: канонический
    вариант на группу (вариативность даёт позиция/поворот блока); диван соло без
    спутников блоком не считаем (нечего запекать)."""
    sofa = by_role.get('диван')
    arm1, arm2 = by_role.get('кресло'), by_role.get('кресло 2')
    sofa2 = by_role.get('диван 2')
    table, rug = by_role.get('столик'), by_role.get('ковёр')

    if group_id == 'armchair_pair':
        if not (arm1 and arm2):
            return None
        # СИММЕТРИЯ (замечание владельца 11.08): оба кресла на РАВНОМ зазоре от
        # столика (книжный face-to-face 183 давал разные плечи при мелком столике)
        b = Block(arm1)
        far, _fx, tcy = _add_coffee(b, arm1, table or by_role.get('приставной'))
        b.add(arm2, 0.0, far + COFFEE_GAP + arm2.d_cm / 2, 180.0)
        if rug is not None:
            # ковёр по ЦЕНТРУ СТОЛИКА (замечание владельца 11.08): зона пары
            # симметрична — оба кресла заходят на ковёр одинаково
            rw, rd = max(rug.w_cm, rug.d_cm), min(rug.w_cm, rug.d_cm)
            b.add(Item(role=rug.role, w_cm=rw, d_cm=rd, h_cm=rug.h_cm,
                       name=rug.name, item_id=rug.item_id), 0.0, tcy, 0.0)
        return b

    if sofa is None:
        return None
    b = Block(sofa)
    far, table_x, table_cy = _add_coffee(b, sofa, table)
    _, free_side = _free_x(sofa)
    rug_min_left = None

    if group_id == 'sofa_facing_sofa':
        # v2.2: два дивана визави — чистая беседа/камин. С носителем ТВ в составе
        # честное face-to-face несовместимо с прицелом ≤30° (никто не смотрит на
        # экран) — фолбэк beam найдёт компромиссную не-визави постановку.
        if not sofa2 or sofa.corner or sofa2.corner:
            return None
        if by_role.get('стенка') is not None or by_role.get('тв-тумба') is not None:
            return None
        _add_facing(b, sofa, sofa2, far)
        if rug is not None:
            # симметричная схема: ковёр по ЦЕНТРУ столика (владелец 11.08)
            rw, rd = max(rug.w_cm, rug.d_cm), min(rug.w_cm, rug.d_cm)
            b.add(Item(role=rug.role, w_cm=rw, d_cm=rd, h_cm=rug.h_cm,
                       name=rug.name, item_id=rug.item_id), table_x, table_cy, 0.0)
        return b
    elif group_id in ('sofa_loveseat', 'sofa_loveseat_2armchairs',
                      'two_sofas_2armchairs'):
        # v2.1: Г-стык торец-к-торцу; столик остаётся по центру ГЛАВНОГО дивана
        # (SOFA_TABLE_DIST в validate привязан только к главному — проверено)
        if not sofa2 or sofa.corner or sofa2.corner:
            return None
        _add_L(b, sofa, sofa2)
        rug_min_left = -(sofa.w_cm / 2 + L_GAP) + 6.0   # правый край дивана 2 + зазор
        if variant == 'square':
            # фолбэк для тесных канонических комнат: кресла столбиком сбоку столика
            tw_half = (max(table.w_cm, table.d_cm) / 2) if table else 40.0
            ax = table_x + tw_half + FLANK_GAP + (arm1.d_cm / 2 if arm1 else 0)
            if arm1:
                b.add(arm1, ax, table_cy, 270.0)
                if arm2 and group_id != 'sofa_loveseat':
                    b.add(arm2, ax,
                          table_cy + arm1.w_cm / 2 + arm2.w_cm / 2 + 12, 270.0)
        elif arm1:
            # П-композиция (владелец 11.08): кресла — на ДЛИННОЙ стороне столика
            # НАПРОТИВ главного дивана, лицом к нему; открытая сторона П — к экрану
            ay = far + COFFEE_GAP + arm1.d_cm / 2
            if arm2 and group_id != 'sofa_loveseat':
                b.add(arm1, table_x - (arm1.w_cm / 2 + 8), ay, 180.0)
                b.add(arm2, table_x + (arm2.w_cm / 2 + 8), ay, 180.0)
            else:
                b.add(arm1, table_x, ay, 180.0)
    elif group_id in ('sofa_2armchairs', 'sofa_4armchairs'):
        if not (arm1 and arm2):
            return None
        if variant == 'u':
            tw_half = (max(table.w_cm, table.d_cm) / 2) if table else 40.0
            a3, a4 = by_role.get('кресло 3'), by_role.get('кресло 4')
            for side, near, far_arm in ((-1, arm1, a3), (+1, arm2, a4)):
                ax = side * (abs(table_x) * 0 + tw_half + FLANK_GAP + near.d_cm / 2) + table_x
                rot = 90.0 if side < 0 else 270.0
                b.add(near, ax, table_cy, rot)
                if far_arm is not None:
                    b.add(far_arm, ax,
                          table_cy + near.w_cm / 2 + far_arm.w_cm / 2 + 12, rot)
            _add_rug(b, sofa, rug, far, min_left=rug_min_left)
            return b
        if sofa.corner:
            # Г-диван: кресла ПАРОЙ визави напротив свободной секции (сбоку от оси
            # экрана); со столиком у Г-компакта пара «столик×плечо» часто нерешаема
            # (ось ≤15% против зазора ≥32) — каскад демоций уронит столик,
            # и P0.4-лимит «не дальше столика+60» уйдёт вместе с ним
            face = 160.0 if table is None else min(
                183.0, far - _front(sofa) + 60.0 - arm1.d_cm / 2)
            ay = _front(sofa) + max(120.0, face) + arm1.d_cm / 2
            fx0, _ = _free_x(sofa)
            b.add(arm1, fx0 - (arm1.w_cm / 2 + 8), ay, 180.0)
            b.add(arm2, fx0 + (arm2.w_cm / 2 + 8), ay, 180.0)
        elif variant in ('tandem_r', 'tandem_l'):
            # узкая комната (set37): фланги с двух сторон не влезают по ширине —
            # кресла СТОЛБИКОМ с одного бока, лицом к центру зоны
            side = +1 if variant == 'tandem_r' else -1
            ax = side * (sofa.w_cm / 2 + FLANK_GAP + arm1.d_cm / 2)
            rot = 270.0 if side > 0 else 90.0
            ay1 = _front(sofa) + arm1.w_cm / 2 + 10
            b.add(arm1, ax, ay1, rot)
            b.add(arm2, ax, ay1 + arm1.w_cm / 2 + arm2.w_cm / 2 + 12, rot)
        else:
            thw = max(table.w_cm, table.d_cm) / 2 if table else None
            _add_flank(b, sofa, arm1, -1, table_cy, table_half_w=thw)
            _add_flank(b, sofa, arm2, +1, table_cy, table_half_w=thw)
        a3, a4 = by_role.get('кресло 3'), by_role.get('кресло 4')
        if group_id == 'sofa_4armchairs' and a3 and a4:
            if variant == 'u':
                # v2.12 (правка владельца 11.08): столбики ПО БОКАМ СТОЛИКА —
                # якорь к столику (не к дивану), ближние центрированы по нему,
                # вторые кресла строго за ближними тем же x
                pass
            else:
                off = sofa.w_cm / 4
                b.add(a3, -off, far + 45 + a3.d_cm / 2, 180.0)
                b.add(a4, +off, far + 45 + a4.d_cm / 2, 180.0)
    elif group_id in ('sofa_armchair', 'sectional_armchair'):
        if not arm1:
            return None
        if sofa.corner:
            tw_half = (max(table.w_cm, table.d_cm) / 2) if table else 40.0
            ax = table_x + free_side * (tw_half + FLANK_GAP + arm1.d_cm / 2)
            b.add(arm1, ax, far, 270.0 if free_side > 0 else 90.0)
        else:
            _add_flank(b, sofa, arm1, free_side, table_cy,
                       table_half_w=(max(table.w_cm, table.d_cm) / 2 if table else None))
    else:
        # v1.1 (аудит полноты): диван соло + столик + ковёр — блоком тоже (самый
        # частый состав малых комнат; привязка ковра/столика нужна и без кресел).
        # Совсем нечего запекать (ни столика, ни ковра) — блока нет.
        if table is None and rug is None:
            return None
    _add_rug(b, sofa, rug, far, min_left=rug_min_left)
    return b


def build_dining(by_role: dict[str, Item], max_chairs: int,
                 sides: str = 'all') -> Block | None:
    """Шаблон столовой зоны (владелец 10.08: «зону столовую тоже шаблон»): стол-якорь
    + стулья, задвинутые к кромке (CHAIR_TUCK — задвинутый стул НОРМА; место для
    отодвигания проверит validate/проходы). Пары — по длинным сторонам (rot 0 якоря:
    длинная ось вдоль x), торцы — последними. sides='front' — пристенная постановка:
    стулья только со стороны комнаты (+y) и с торцов (задняя сторона у стены)."""
    tbl = by_role.get('стол обеденный')
    if tbl is None:
        return None
    chairs = [by_role[r] for r in sorted(by_role)
              if r == 'стул' or r.startswith('стул ')][:max_chairs]
    if not chairs:
        return None
    b = Block(tbl)
    w, d = tbl.w_cm, tbl.d_cm
    chair_w = max(c.w_cm for c in chairs)
    # v2.3: круглый/квадратный стол (w==d) — по одному стулу с каждой стороны
    # (через 90°). Прямоугольный — пары по длинным сторонам, но ТОЛЬКО если пара
    # физически помещается с зазором ≥8 (set37: узкий стол бил стул о стул)
    pair_ok = w >= 2 * chair_w + 24
    xs = [0.0] if (abs(w - d) < 2 or not pair_ok) else [-w / 4, w / 4]
    spots: list[tuple[float, float, float]] = []
    for x in sorted(xs, key=abs):
        spots.append((x, d / 2, 180.0))            # сторона комнаты, стул лицом к столу
        if sides == 'all':
            spots.append((x, -d / 2, 0.0))         # дальняя сторона
    spots += [(w / 2, 0.0, 270.0), (-w / 2, 0.0, 90.0)]   # торцы
    for ch, (sx, sy, srot) in zip(chairs, spots):
        off = ch.d_cm / 2 + CHAIR_GAP
        dx, dy = _rt(0.0, off, srot)               # сдвиг наружу вдоль взгляда стула
        b.add(ch, sx - dx, sy - dy, srot)
    return b


def _tv_probe(room: Room, sofa_p: Placement, free: Polygon, need_w: float) -> float:
    """Дешёвая ТВ-проба до валидации (ранняя отбраковка): луч взгляда якоря до
    стены; счёт 0..1 — дистанция в разумной вилке и свободное пятно под носитель."""
    r = math.radians(sofa_p.rot)
    dx, dy = math.sin(r), math.cos(r)
    poly = room_polygon(room)
    d = None
    t = 60.0
    while t <= 900.0:
        if not poly.contains(Point(sofa_p.x + dx * t, sofa_p.y + dy * t)):
            d = t
            break
        t += 30.0
    if d is None:
        return 0.3
    if d < 170:
        return 0.0
    spot = Point(sofa_p.x + dx * (d - 45), sofa_p.y + dy * (d - 45)) \
        .buffer(max(need_w / 2, 40.0), resolution=4)
    frac = free.intersection(spot).area / max(spot.area, 1e-6)
    # реальная ТВ-вилка от ширины носителя (planner.tv, диагональ-метод): дистанция
    # диван→носитель ≈ (до стены − глубина носителя); вне вилки — сильный штраф,
    # чтобы в больших комнатах выигрывали «плавающие» позиции (v2.10)
    from .tv import distance_range
    lo, hi, soft_hi = distance_range(need_w)
    dd = d - 40.0
    band = 1.0 if lo <= dd <= hi else (0.5 if dd <= soft_hi else 0.15)
    return band * (0.4 + 0.6 * frac)


def _best_block(room: Room, b: Block, free: Polygon, cands, *, tv: Item | None,
                fixed: list[Placement] | None,
                axis_seat: Placement | None = None) -> list[Placement] | None:
    """Общий отборщик: fits-проба всех членов → ТВ-проба → эвристический ранг →
    полный validate (hard) топ-N; первый чистый побеждает."""
    room_poly = room_polygon(room)
    scored: list[tuple[float, list[Placement]]] = []
    for c in cands:
        ps = b.to_world(c.placement.x, c.placement.y, c.placement.rot)
        ok = True
        for p in ps:
            fp = footprint(p)
            if p.role == 'ковёр':
                # подложка: free её не ограничивает (ADR-0083), но из комнаты не торчит
                if room_poly.intersection(fp).area < fp.area * 0.995:
                    ok = False
                    break
                continue
            if free.intersection(fp).area < fp.area * 0.97:
                ok = False
                break
        if not ok:
            continue
        score = 1.0 if c.kind == 'wall' else 0.8
        if 'отплыв' in (c.note or ''):
            score -= 0.15                   # прижатый канон приоритетнее отплыва
        # v2.11 (интернет-свод): вытянутая комната → посадка ПОПЕРЁК длинной оси
        # (якорь на длинной стене «раздвигает стены»)
        rw, rd = room.width_cm, room.depth_cm
        if max(rw, rd) / max(min(rw, rd), 1) >= 1.6:
            along_long = (int(c.placement.rot) % 180 == 90) if rd > rw else                 (int(c.placement.rot) % 180 == 0)
            if along_long:
                score += 0.3
        if tv is not None or b.anchor.role == 'диван':
            probe = _tv_probe(room, ps[0], free, tv.w_cm if tv else 120.0)
            if tv is not None and probe <= 0.0:
                continue                    # ТВ ставить некуда — мёртвая ветка
            score += probe * 2.0
        if axis_seat is not None:
            # медиа-блок: приоритет соосности с главным посадочным (межзонная связь)
            r = math.radians(axis_seat.rot)
            vx, vy = ps[0].x - axis_seat.x, ps[0].y - axis_seat.y
            n = math.hypot(vx, vy) or 1.0
            cosang = (math.sin(r) * vx + math.cos(r) * vy) / n
            ang = math.degrees(math.acos(max(-1.0, min(1.0, cosang))))
            score += max(0.0, 1.5 - ang / 30.0)
        scored.append((score, ps))
    scored.sort(key=lambda t: -t[0])
    base = list(fixed or [])
    first_hard = None
    for _, ps in scored[:TOP_FULL_VALIDATE]:
        lay = validate(room, base + ps)
        hards = [v for v in lay.violations if v.severity is Severity.HARD]
        if not hards:
            return ps
        if first_hard is None:
            first_hard = [(v.code, v.roles, v.value) for v in hards[:3]]
    if os.environ.get('ZONES_DEBUG'):
        import sys
        print(f"ZDBG block[{b.anchor.role}+{len(b.rel)-1}] REJECT: "
              f"fits={len(scored)} top_hard={first_hard}", file=sys.stderr, flush=True)
    return None


def place_template(room: Room, group_id: str, items: list[Item], free: Polygon,
                   fixed: list[Placement] | None = None) -> list[Placement] | None:
    """Разговорная зона блоком: лучший hard-чистый вариант или None (фолбэк beam)."""
    if os.environ.get('LAYOUT_TEMPLATES', '1') == '0':
        return None
    by_role: dict[str, Item] = {}
    for it in items:
        by_role.setdefault(it.role, it)
    # фокус зоны: медиа-носитель, а без него — камин (v2.5: камин-фокус легален)
    tv = by_role.get('стенка') or by_role.get('тв-тумба') or by_role.get('камин')
    # каскад демоций: полный блок → без столика (бывают невозможные пары «длинный
    # столик × Г-диван», beam их тоже терял в missing) → без столика и ковра
    variants = [by_role]
    if 'столик' in by_role:
        variants.append({k: v for k, v in by_role.items() if k != 'столик'})
        if 'ковёр' in by_role:
            variants.append({k: v for k, v in by_role.items()
                             if k not in ('столик', 'ковёр')})
    shapes = {'sofa_4armchairs': ['default', 'u'],
              'sofa_2armchairs': ['default', 'tandem_r', 'tandem_l'],
              'two_sofas_2armchairs': ['default', 'square'],
              'sofa_loveseat': ['default', 'square'],
              'sofa_loveseat_2armchairs': ['default', 'square'],
              }.get(group_id, ['default'])
    for br in variants:
      for shape in shapes:
        b = build_block(group_id, br, variant=shape)
        if b is None or len(b.rel) < 2:
            continue
        cands = list(wall_candidates(room, b.anchor, free))
        # v2.10: в просторных комнатах посадка может «плавать» (зонирование
        # спинкой); тыл за спинкой проверят passage/sliver-чеки validate
        if room.width_cm * room.depth_cm > 40 * 10_000:
            cands += list(middle_candidates(room, b.anchor, free, limit=6))
        ps = _best_block(room, b, free, cands, tv=tv, fixed=fixed)
        if ps is not None:
            return ps
    return None


def place_dining(room: Room, items: list[Item], free: Polygon, usable_m2: float,
                 fixed: list[Placement] | None = None) -> list[Placement] | None:
    """Столовая зона блоком: стол + стулья по band (малые комнаты 2, средние 4,
    просторные 6 — «заранее продумать» владельца). Кандидаты позиции — у стены и
    свободные (остров); проходы/отодвигание проверит validate на объединении."""
    if os.environ.get('LAYOUT_TEMPLATES', '1') == '0':
        return None
    by_role: dict[str, Item] = {}
    for it in items:
        by_role.setdefault(it.role, it)
    max_chairs = 2 if usable_m2 <= 18 else (4 if usable_m2 <= 30 else 6)
    # остров (стулья вокруг) — на свободных позициях; не встал — пристенный вариант
    # (стулья со стороны комнаты и с торцов) на стенных позициях
    b_all = build_dining(by_role, max_chairs, sides='all')
    if b_all is None or len(b_all.rel) < 2:
        return None
    ps = _best_block(room, b_all, free,
                     list(middle_candidates(room, b_all.anchor, free, limit=8)),
                     tv=None, fixed=fixed)
    if ps is not None:
        return ps
    b_front = build_dining(by_role, max_chairs, sides='front')
    return _best_block(room, b_front, free,
                       list(wall_candidates(room, b_front.anchor, free)),
                       tv=None, fixed=fixed)


STORAGE_ROLES = ('стеллаж', 'стеллаж 2', 'шкаф', 'комод')


def build_storage(by_role: dict[str, Item]) -> Block | None:
    """v2.4: стеллаж-стена — ряд хранения вдоль одной стены, фасады в линию,
    зазор 8 см; якорь — самый широкий предмет, остальные вправо от него."""
    items = [by_role[r] for r in STORAGE_ROLES if r in by_role]
    if len(items) < 2:
        return None
    items.sort(key=lambda i: -i.w_cm)
    anchor = items[0]
    b = Block(anchor)
    x = anchor.w_cm / 2
    for it in items[1:]:
        # глубины разные — фасады в линию: сдвиг по y на полуразность глубин
        b.add(it, x + 8 + it.w_cm / 2, (anchor.d_cm - it.d_cm) / 2, 0.0)
        x += 8 + it.w_cm
    plant = by_role.get('кашпо')
    if plant is not None:
        # живой акцент у торца ряда (веб-свод 11.08: растение у стеллажа/полок)
        b.add(plant, x + 15 + plant.w_cm / 2, (anchor.d_cm - plant.d_cm) / 2, 0.0)
    return b


def place_storage(room: Room, items: list[Item], free: Polygon,
                  fixed: list[Placement] | None = None) -> list[Placement] | None:
    if os.environ.get('LAYOUT_TEMPLATES', '1') == '0':
        return None
    by_role: dict[str, Item] = {}
    for it in items:
        by_role.setdefault(it.role, it)
    b = build_storage(by_role)
    if b is None:
        return None
    return _best_block(room, b, free, wall_candidates(room, b.anchor, free),
                       tv=None, fixed=fixed)


def build_reading(by_role: dict[str, Item]) -> Block | None:
    """v2.6: уголок чтения — кресло + торшер за плечом (30–40 от спинки, сбоку)
    + приставной у другого подлокотника (≤15)."""
    arm = by_role.get('кресло 3') or by_role.get('кресло')
    lamp, side = by_role.get('торшер'), by_role.get('приставной')
    if arm is None or (lamp is None and side is None):
        return None
    b = Block(arm)
    if lamp is not None:
        # сбоку и чуть сзади — свет через плечо (веб-свод 11.08 подтвердил)
        b.add(lamp, arm.w_cm / 2 + lamp.w_cm / 2 + 12, -arm.d_cm / 2 + 8, 0.0)
    if side is not None:
        b.add(side, -(arm.w_cm / 2 + side.w_cm / 2 + 8), 5.0, 0.0)
    return b


def place_reading(room: Room, items: list[Item], free: Polygon,
                  fixed: list[Placement] | None = None) -> list[Placement] | None:
    if os.environ.get('LAYOUT_TEMPLATES', '1') == '0':
        return None
    by_role: dict[str, Item] = {}
    for it in items:
        by_role.setdefault(it.role, it)
    b = build_reading(by_role)
    if b is None:
        return None
    return _best_block(room, b, free, wall_candidates(room, b.anchor, free),
                       tv=None, fixed=fixed)


def build_media(by_role: dict[str, Item], with_flanks: bool = True) -> Block | None:
    """v2.7/v2.8: медиа-зона — носитель ТВ (стенка ИЛИ тумба, ADR-0081) + при
    наличии свободного декора симметричные фланги (кашпо/торшер, 25 см от торцов)."""
    bearer = by_role.get('стенка') or by_role.get('тв-тумба')
    if bearer is None:
        return None
    b = Block(bearer)
    if with_flanks:
        # только растения/декор (веб-свод 11.08: торшер — у ПОСАДКИ, не у тумбы;
        # мелкая лампа — НА поверхности, её ставит рендер-механика hosts)
        deco = [by_role[r] for r in ('кашпо', 'кашпо 2') if r in by_role][:2]
        for i, d in enumerate(deco):
            side = -1 if i == 0 else 1
            b.add(d, side * (bearer.w_cm / 2 + 25 + d.w_cm / 2), 0.0, 0.0)
    return b


def place_media(room: Room, items: list[Item], free: Polygon,
                fixed: list[Placement] | None = None) -> list[Placement] | None:
    """Медиа-зона блоком; позиция — по межзонной связи (соосность с главным
    посадочным из fixed, дистанция/прицел проверит validate)."""
    if os.environ.get('LAYOUT_TEMPLATES', '1') == '0':
        return None
    by_role: dict[str, Item] = {}
    for it in items:
        by_role.setdefault(it.role, it)
    seat = next((p for p in (fixed or []) if p.role == 'диван'), None) or         next((p for p in (fixed or []) if p.role == 'кресло'), None)
    for flanks in (True, False):
        b = build_media(by_role, with_flanks=flanks)
        if b is None:
            return None
        ps = _best_block(room, b, free, wall_candidates(room, b.anchor, free),
                         tv=None, fixed=fixed, axis_seat=seat)
        if ps is not None:
            return ps
    return None
