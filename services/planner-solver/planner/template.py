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


def _add_coffee(b: Block, seat: Item, table: Item | None) -> tuple[float, float]:
    """Столик по центру свободного фронта якоря; у Г-дивана дополнительно отжат от
    плеча на hard-минимум 32 (SOFA_TABLE_DIST мерит мин-гэп футпринтов, плечо рядом).
    Возвращает (y дальней кромки, фактический x столика)."""
    fx, _ = _free_x(seat)
    if table is None:
        return _front(seat) + COFFEE_GAP, fx
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
    return ty + tt.d_cm / 2, fx


def _add_rug(b: Block, seat: Item, rug: Item | None, far_y: float) -> None:
    """Ковёр — производная блока: по оси свободной части якоря, длинной стороной
    вдоль дивана. Габарит SKU фиксирован: крупный накрывает передние ножки,
    малый честно ложится под столик (легальный паттерн)."""
    if rug is None:
        return
    fx, _ = _free_x(seat)
    w, d = max(rug.w_cm, rug.d_cm), min(rug.w_cm, rug.d_cm)
    ry = max(_front(seat) - 15.0 + d / 2,
             min(_front(seat) + 5.0 + d / 2, (far_y + _front(seat)) / 2))
    b.add(Item(role=rug.role, w_cm=w, d_cm=d, h_cm=rug.h_cm, name=rug.name,
               item_id=rug.item_id), fx, ry, 0.0)


def _add_flank(b: Block, seat: Item, arm: Item, side: int, at_y: float) -> None:
    """Кресло флангом сбоку зоны на уровне столика, лицом к центру (компасный rot:
    справа → смотрит запад 270); не разлетаться шире круга беседы."""
    ax = side * min(seat.w_cm / 2 + FLANK_GAP + arm.d_cm / 2, CIRCLE_D / 2 - 10)
    b.add(arm, ax, at_y, 270.0 if side > 0 else 90.0)


def _add_facing(b: Block, seat: Item, other: Item, far_y: float) -> None:
    """Визави: второй посадочный напротив через столик, фронт-фронт в вилке."""
    fx, _ = _free_x(seat)
    face = min(VIS_FACE[1], max(VIS_FACE[0], (far_y - _front(seat)) + COFFEE_GAP))
    b.add(other, fx, _front(seat) + face + other.d_cm / 2, 180.0)


def _add_L(b: Block, sofa: Item, other: Item) -> None:
    """Г-стык торец-к-торцу (KB/владелец): второй диван перпендикулярно, спинки
    наружу, его торец у торца первого, общий угол зоны слева."""
    ox = -(sofa.w_cm / 2 + L_GAP + other.d_cm / 2)
    oy = -sofa.d_cm / 2 + other.w_cm / 2
    b.add(other, ox, oy, 90.0)


def build_block(group_id: str, by_role: dict[str, Item]) -> Block | None:
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
        b = Block(arm1)
        far, _fx = _add_coffee(b, arm1, table or by_role.get('приставной'))
        _add_facing(b, arm1, arm2, far)
        _add_rug(b, arm1, rug, far)
        return b

    if sofa is None:
        return None
    b = Block(sofa)
    far, table_x = _add_coffee(b, sofa, table)
    _, free_side = _free_x(sofa)

    if group_id in ('sofa_facing_sofa', 'sofa_loveseat', 'sofa_loveseat_2armchairs',
                    'two_sofas_2armchairs'):
        # v2: двухдиванные блоки (визави конкурирует с ТВ-стеной, Г-стык душит столик
        # по центру — contract-тест поймал) — пока прежний путь beam, он их решает
        return None
    elif group_id in ('sofa_2armchairs', 'sofa_4armchairs'):
        if not (arm1 and arm2):
            return None
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
        else:
            _add_flank(b, sofa, arm1, -1, far)
            _add_flank(b, sofa, arm2, +1, far)
        a3, a4 = by_role.get('кресло 3'), by_role.get('кресло 4')
        if group_id == 'sofa_4armchairs' and a3 and a4:
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
            _add_flank(b, sofa, arm1, free_side, far)
    else:
        # compact_sectional и пр.: диван соло — блок не даёт выигрыша
        return None
    _add_rug(b, sofa, rug, far)
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
    xs = [0.0] if w < 110 else [-w / 4, w / 4]
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
    return (1.0 if 200 <= d <= 480 else 0.6) * (0.4 + 0.6 * frac)


def _best_block(room: Room, b: Block, free: Polygon, cands, *, tv: Item | None,
                fixed: list[Placement] | None) -> list[Placement] | None:
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
        if tv is not None or b.anchor.role == 'диван':
            probe = _tv_probe(room, ps[0], free, tv.w_cm if tv else 120.0)
            if tv is not None and probe <= 0.0:
                continue                    # ТВ ставить некуда — мёртвая ветка
            score += probe * 2.0
        scored.append((score, ps))
    scored.sort(key=lambda t: -t[0])
    base = list(fixed or [])
    for _, ps in scored[:TOP_FULL_VALIDATE]:
        lay = validate(room, base + ps)
        if not any(v.severity is Severity.HARD for v in lay.violations):
            return ps
    return None


def place_template(room: Room, group_id: str, items: list[Item], free: Polygon,
                   fixed: list[Placement] | None = None) -> list[Placement] | None:
    """Разговорная зона блоком: лучший hard-чистый вариант или None (фолбэк beam)."""
    if os.environ.get('LAYOUT_TEMPLATES', '1') == '0':
        return None
    by_role: dict[str, Item] = {}
    for it in items:
        by_role.setdefault(it.role, it)
    tv = by_role.get('стенка') or by_role.get('тв-тумба')
    # каскад демоций: полный блок → без столика (бывают невозможные пары «длинный
    # столик × Г-диван», beam их тоже терял в missing) → без столика и ковра
    variants = [by_role]
    if 'столик' in by_role:
        variants.append({k: v for k, v in by_role.items() if k != 'столик'})
        if 'ковёр' in by_role:
            variants.append({k: v for k, v in by_role.items()
                             if k not in ('столик', 'ковёр')})
    for br in variants:
        b = build_block(group_id, br)
        if b is None or len(b.rel) < 2:
            continue
        ps = _best_block(room, b, free, wall_candidates(room, b.anchor, free),
                         tv=tv, fixed=fixed)
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
