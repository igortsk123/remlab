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
import os

from shapely.geometry import Point, Polygon

from .candidates import middle_candidates, wall_candidates
from .geometry import footprint, room_polygon, opening_polygon, radiator_polygon
from .models import Item, Placement, Room, Severity
from .invariants import check_block
from .validate import validate

# --- параметры внутренней геометрии (см); пруфы — KB/occupancy ---
# ЧИСЛА ГЕОМЕТРИИ СХЕМ — ИЗ ПАСПОРТА (`rules/templates.json` → geometry), не из кода:
# правило владельца 12.08 «шаблон задаёт размер, нерушимый, везде». Здесь только чтение
# с дефолтами на случай отсутствия ключа.
def _g(name: str, default):
    from .invariants import TEMPLATES as _T
    v = ((_T.get('geometry') or {}).get(name) or {}).get('v')
    return default if v is None else v


def _dining_rules() -> dict:
    """Паспорт столовой (`rules/templates.json → zones.dining.rules`) — source of truth
    по эргономике: seats_by_area, edge_per_diner_cm, operational_envelope_cm (свод №8 v2 §4:
    параллельную clearance-модель не заводить; физический минимум отодвигания 55 см
    остаётся в occupancy.json `dining_chair_pullout` — это разные уровни: hard-минимум
    vs полноценный island-класс)."""
    from .invariants import TEMPLATES as _T
    return ((_T.get('zones') or {}).get('dining') or {}).get('rules') or {}


def dining_seats_cap(usable_m2: float) -> int:
    """Мест по площади — из паспорта (`seats_by_area`: "<=18"→2, "<=30"→4, ">30"→6)."""
    sba = _dining_rules().get('seats_by_area') or {}
    le = sorted(((float(k[2:]), int(v)) for k, v in sba.items() if k.startswith('<=')))
    for thr, seats in le:
        if usable_m2 <= thr:
            return seats
    gt = [int(v) for k, v in sba.items() if k.startswith('>')]
    return gt[0] if gt else 6


def dining_envelope_cm() -> float:
    """Эксплуатационная зона полноценного острова (паспорт; пруфы R&B 36″/Moschino 90-100)."""
    return float(_dining_rules().get('operational_envelope_cm', 90) or 90)


# Пакет B свода №8: диагностика выбора dining (mode/island_feasible/fallback_reason).
# Канал: place_dining заполняет модульный слот, zones.py кладёт его в Layout.meta,
# solver_run экспортирует как `_dining`. Сбрасывается в начале place_dining.
LAST_DINING_DIAG: dict | None = None


def dining_island_feasible(table: Item, free: Polygon) -> bool:
    """Независимая грубая проба (свод №8 v2 §5): существует ли ГДЕ-ТО в свободном
    полигоне позиция полного острова (стол + envelope со всех сторон) — отдельно от
    генератора кандидатов, чтобы отличать «остров невозможен геометрически» от
    «кандидаты его не нашли» (баг генерации). Сетка 25 см, обе ориентации."""
    from shapely.geometry import box as _box
    from shapely.prepared import prep as _prep
    env = dining_envelope_cm()
    if free.is_empty:
        return False
    pf = _prep(free)
    minx, miny, maxx, maxy = free.bounds
    for w, d in ((table.w_cm, table.d_cm), (table.d_cm, table.w_cm)):
        W, D = w + 2 * env, d + 2 * env
        x = minx + W / 2
        while x <= maxx - W / 2 + 1e-6:
            y = miny + D / 2
            while y <= maxy - D / 2 + 1e-6:
                if pf.contains(_box(x - W / 2, y - D / 2, x + W / 2, y + D / 2)):
                    return True
                y += 25.0
            x += 25.0
    return False


def _island_probe_candidates(table: Item, free: Polygon, limit: int = 6) -> list:
    """Пакет C свода №8: кандидаты полного острова ИЗ ПРОБЫ. Генератор
    middle_candidates даёт центры крупнейших прямоугольников — их может не хватить,
    и тогда «остров возможен, но кандидаты не нашли» = тихий edge из-за генерации
    (v2 §12). Здесь позиции берутся прямо из сетки пробы envelope (шаг 25 см,
    прореживание 50 см), класс кандидата — middle."""
    from shapely.geometry import box as _box
    from shapely.prepared import prep as _prep
    from .candidates import Candidate
    env = dining_envelope_cm()
    if free.is_empty:
        return []
    pf = _prep(free)
    minx, miny, maxx, maxy = free.bounds
    out: list = []
    for rot, (w, d) in ((0.0, (table.w_cm, table.d_cm)),
                        (90.0, (table.d_cm, table.w_cm))):
        W, D = w + 2 * env, d + 2 * env
        hits: list[tuple[float, float]] = []
        x = minx + W / 2
        while x <= maxx - W / 2 + 1e-6:
            y = miny + D / 2
            while y <= maxy - D / 2 + 1e-6:
                if pf.contains(_box(x - W / 2, y - D / 2, x + W / 2, y + D / 2)) \
                        and all(abs(x - hx) + abs(y - hy) >= 50 for hx, hy in hits):
                    hits.append((x, y))
                    out.append(Candidate(
                        Placement(role=table.role, x=x, y=y, rot=rot, item=table),
                        'middle', 'island-probe'))
                    if len(hits) >= limit:
                        break
                y += 25.0
            if len(hits) >= limit:
                break
            x += 25.0
    return out


def dining_mode_topology(table: Placement, free: Polygon) -> str:
    """V3-E свода №9 (PACKAGE E): режим — по фактической ТОПОЛОГИИ постановки, не по
    пути кандидата. Числа СУЩЕСТВУЮЩИЕ: сторона, у которой полоса отодвигания стула
    (dining_chair_pullout 55, occupancy.json) упирается в стену/мебель → wall-attached
    → 'edge'; все четыре стороны свободны ≥ паспортного envelope (90) → 'full_island';
    иначе 'compact_island' (freestanding, 55…89 — fallback-класс; 55 НЕ трактуется
    как «нормальный проход» — поправка рефери, это минимум отодвигания)."""
    from .clearances import distances as _dist
    _pv = _dist().get('dining_chair_pullout', 55)
    pull = float(_pv[0] if isinstance(_pv, list) else _pv)
    it = table.item
    for side_rot, grow in ((0.0, it.d_cm), (180.0, it.d_cm),
                           (90.0, it.w_cm), (270.0, it.w_cm)):
        # полоса pull-глубины сразу за соответствующей стороной стола
        w_ = it.w_cm if side_rot in (0.0, 180.0) else it.d_cm
        strip = Item(role=it.role, w_cm=w_, d_cm=pull, h_cm=it.h_cm)
        off = grow / 2 + pull / 2
        dx, dy = _rt(0.0, off, table.rot + side_rot)
        probe = Placement(role=it.role, x=table.x + dx, y=table.y + dy,
                          rot=table.rot + side_rot, item=strip)
        if not free.contains(footprint(probe)):
            return 'edge'
    return 'full_island' if dining_envelope_ok(table, free, 'all') else 'compact_island'


def dining_envelope_ok(table: Placement, free: Polygon, sides: str = 'all') -> bool:
    """FULL_ISLAND-валидность: паспортный envelope свободен вокруг рабочих сторон стола.
    sides='all' — все четыре стороны (остров); 'front' — пристенная сторона (локальный −y)
    envelope не требует (edge-режим асимметричен, свод №8 v2 §4). Проверка на free ДО
    постановки стульев: стулья — часть зоны, их споты входят в её же envelope."""
    env = dining_envelope_cm()
    it = table.item
    grow_back = env if sides == 'all' else 0.0
    box = Item(role=it.role, w_cm=it.w_cm + 2 * env,
               d_cm=it.d_cm + env + grow_back, h_cm=it.h_cm, name=it.name)
    off = 0.0 if sides == 'all' else (env - grow_back) / 2
    dx, dy = _rt(0.0, off, table.rot)
    probe = Placement(role=it.role, x=table.x + dx, y=table.y + dy,
                      rot=table.rot, item=box)
    return free.contains(footprint(probe))


COFFEE_GAP = float(_g('coffee_gap_cm', 42.5))    # столик от фронта дивана
FLANK_GAP = float(_g('flank_gap_cm', 32.0))      # кресло от торца дивана
VIS_FACE = tuple(_g('visavi_face_cm', [183.0, 305.0]))   # фронт-фронт визави
L_GAP = float(_g('l_joint_gap_cm', 20.0))        # Г-стык торец-к-торцу
CIRCLE_D = float(_g('circle_d_cm', 396.0))       # круг беседы
CHAIR_GAP = float(_g('chair_tuck_cm', 2.0))      # задвинутый стул
TOP_FULL_VALIDATE = 24           # позиций блока на полный разбор: из hard-чистых
                                 # выбирается лучшая по лексикографическому скору


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
        self.tpl_id = ''          # паспорт схемы (rules/templates.json) — ставит _valid
        self.tpl_version = ''
        self.tpl_variant = ''     # форма схемы: должна попадать в Placement УЖЕ В ПОИСКЕ, иначе
                                  # контракты формы (уголок/консоль) не проверяются в _best_block
                                  # и брак всплывает только на финальном плане (18.08, NOOK_PULLOUT)

    def add(self, item: Item, x: float, y: float, rot: float) -> None:
        self.rel.append((item, x, y, rot % 360))

    def to_world(self, ax: float, ay: float, arot: float) -> list[Placement]:
        out = []
        for it, rx, ry, rrot in self.rel:
            wx, wy = _rt(rx, ry, arot)
            out.append(Placement(role=it.role, x=ax + wx, y=ay + wy,
                                 rot=(rrot + arot) % 360, item=it,
                                 tpl_id=self.tpl_id, tpl_version=self.tpl_version,
                                 tpl_variant=self.tpl_variant))
        return out


def block_self_overlap(b: Block) -> tuple[str, str] | None:
    """Самопроверка схемы: предметы ВНУТРИ шаблона не должны налезать друг на друга.

    Причина (12.08): подставка для ног перед креслом попадала на журнальный столик
    (COLLISION «столик»×«пуф» до 0.13 м²), и весь блок отбраковывался на любой
    позиции в комнате — сцена уходила в отказ. Ловим это на СБОРКЕ: схема с
    самопересечением недействительна → каскад берёт следующую (меньшую) схему.
    Ковёр — подложка (мебель стоит НА нём), он из проверки исключён.
    """
    ps = [p for p in b.to_world(0.0, 0.0, 0.0) if p.role.split(' ')[0] != 'ковёр']
    def _tucked(r1: str, r2: str) -> bool:      # задвинутый стул — норма (CHAIR_TUCK)
        a, bb = r1.split(' ')[0], r2.split(' ')[0]
        return {a, bb} == {'стол обеденный', 'стул'}
    fps = [footprint(p) for p in ps]
    for i, fa in enumerate(fps):
        for j in range(i + 1, len(fps)):
            if _tucked(ps[i].role, ps[j].role):
                continue
            if fa.intersection(fps[j]).area > 1.0:      # >1 см² — не численный шум
                return (ps[i].role, ps[j].role)
    return None


def _valid(b: Block | None, zone: str = 'seating', variant: str | None = None) -> Block | None:
    """Схема действительна, только если прошла ИНВАРИАНТЫ своего паспорта
    (`rules/templates.json`): нет самопересечений, ножки посадочных на ковре,
    столик в досягаемости, в зоне ≥2 предмета. Не прошла — недействительна,
    каскад возьмёт следующий шаблон (правило владельца «берём другой шаблон»)."""
    if b is None:
        return None
    from .invariants import TEMPLATES as _TPL
    b.tpl_id = zone
    b.tpl_version = str((_TPL['zones'].get(zone) or {}).get('version') or '')
    if variant:
        b.tpl_variant = variant
    why = check_block(b.to_world(0.0, 0.0, 0.0), zone, variant=variant)
    if why is not None:
        if os.environ.get('ZONES_DEBUG'):
            import sys
            print(f"ZDBG схема отброшена на сборке [{zone}]: {why}",
                  file=sys.stderr, flush=True)
        return None
    return b


def _place_zone_rug(b: Block, rug: Item, tuck: float = None) -> None:
    """Ковёр по внутреннему контуру зоны: центр — центр контура, размер подобран
    так, чтобы ножки посадочных заходили на ковёр (канон front-legs)."""
    t = RUG_TUCK if tuck is None else tuck
    ix0, iy0, ix1, iy1 = _inner_zone(b)
    rw, rd = max(rug.w_cm, rug.d_cm), min(rug.w_cm, rug.d_cm)
    need_x, need_y = (ix1 - ix0) + 2 * t, (iy1 - iy0) + 2 * t
    if rw >= need_x and rd >= need_y:
        w_, d_ = rw, rd
    elif rd >= need_x and rw >= need_y:
        w_, d_ = rd, rw
    else:
        w_, d_ = ((rw, rd) if (ix1 - ix0) >= (iy1 - iy0) else (rd, rw))
    b.add(Item(role=rug.role, w_cm=w_, d_cm=d_, h_cm=rug.h_cm, name=rug.name,
               item_id=rug.item_id), (ix0 + ix1) / 2, (iy0 + iy1) / 2, 0.0)


def _pull_seats_onto_rug(b: Block, tuck: float = None) -> None:
    """Посадочные ДОЛЖНЫ стоять на ковре передними ножками (канон front-legs;
    замечание владельца 12.08 по set6-base: «кресло на ковёр ножками не заходит»).
    Ковёр мельче зоны — не оставляем кресло в стороне, а подтягиваем его к ковру.
    Якорь блока (индекс 0) не двигаем — он задаёт систему координат схемы."""
    t = RUG_TUCK if tuck is None else tuck
    rug = next((r for r in b.rel if r[0].role.split(' ')[0] == 'ковёр'), None)
    if rug is None:
        return
    ri, rx, ry, _ = rug
    rx0, rx1, ry0, ry1 = rx - ri.w_cm / 2, rx + ri.w_cm / 2, ry - ri.d_cm / 2, ry + ri.d_cm / 2
    for i, (it, x, y, rot) in enumerate(b.rel):
        if i == 0 or it.role.split(' ')[0] not in ('кресло', 'диван'):
            continue
        w, d = (it.d_cm, it.w_cm) if int(rot) % 180 == 90 else (it.w_cm, it.d_cm)
        x0, x1, y0, y1 = x - w / 2, x + w / 2, y - d / 2, y + d / 2
        dx = dy = 0.0
        if x1 < rx0 + t:
            dx = rx0 + t - x1
        elif x0 > rx1 - t:
            dx = rx1 - t - x0
        if y1 < ry0 + t:
            dy = ry0 + t - y1
        elif y0 > ry1 - t:
            dy = ry1 - t - y0
        if not (dx or dy):
            continue
        # подтяжка не должна нарушить канон «колени до столика 40-45 см»
        _tbl = next((r for r in b.rel if r[0].role.split(' ')[0] == 'столик'), None)
        for _k in (1.0, 0.6, 0.3):
            b.rel[i] = (it, x + dx * _k, y + dy * _k, rot)
            _ok = block_self_overlap(b) is None
            if _ok and _tbl is not None:
                _p = b.to_world(0.0, 0.0, 0.0)
                _fi = footprint(_p[i])
                _ft = footprint(_p[b.rel.index(_tbl)])
                _ok = _fi.distance(_ft) >= 38.0     # hard-вилка столика (32-50)
            if _ok:
                break
        else:
            b.rel[i] = (it, x, y, rot)              # подтянуть нельзя — оставляем


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


def _add_coffee(b: Block, seat: Item, table: Item | None, gap: float = COFFEE_GAP,
                shift: float = 0.0) -> tuple[float, float, float]:
    """Столик по центру свободного фронта якоря; у Г-дивана дополнительно отжат от
    плеча на hard-минимум 32 (SOFA_TABLE_DIST мерит мин-гэп футпринтов, плечо рядом).
    Возвращает (y дальней кромки, фактический x столика, y ЦЕНТРА столика)."""
    fx, _ = _free_x(seat)
    fx += shift
    if table is None:
        return _front(seat) + gap, fx, _front(seat) + gap
    # столик длинной стороной ВДОЛЬ дивана (TABLE_ORIENTATION): нормализуем габариты
    tw, td = max(table.w_cm, table.d_cm), min(table.w_cm, table.d_cm)
    tt = table if table.w_cm >= table.d_cm else Item(
        role=table.role, w_cm=tw, d_cm=td, h_cm=table.h_cm, name=table.name,
        item_id=table.item_id)
    if seat.corner:
        # 18.08 (после снятия допусков): столик Г-дивана канонически центрируется на АКТИВНОМ
        # центре посадки (та же величина, которой TABLE_OFF_AXIS мерит ось — geometry.corner_active_lat),
        # с обязательным зазором 32 см от плеча. Раньше центр брался от свободной части, ось уезжала
        # на ~28 см, и это лечил сдвиг-допуск; допусков больше нет — канон обязан попадать сам.
        from .geometry import corner_active_lat as _cal
        sc = seat.corner_section_cm
        edge = seat.w_cm / 2 - sc            # ближний к плечу край свободной части
        _target = _cal(seat)
        if seat.corner_left:
            fx = max(_target, -edge + 32 + tw / 2)
        else:
            fx = min(_target, edge - 32 - tw / 2)
    ty = _front(seat) + gap + tt.d_cm / 2
    b.add(tt, fx, ty, 0.0)
    return ty + tt.d_cm / 2, fx, ty


def _oc(path: str, default):
    """Значение из occupancy.json по пути 'a/b/c' — ЕДИНЫЙ источник истины для чисел, которые
    раньше дублировались в двух файлах (ковёр, радиатор): дубль всегда расходится (Codex 19.08)."""
    try:
        from .clearances import rules as _rules
        _O = _rules()
    except Exception:
        return default
    cur = _O
    for k in path.split('/'):
        cur = (cur or {}).get(k) if isinstance(cur, dict) else None
    return default if cur is None else cur


# ЗАХОД КОВРА под передние ножки: источник истины — occupancy.rug_rules.front_legs_on_rug_cm
# (в templates.geometry лежал ВТОРОЙ, разошедшийся экземпляр числа: 15 против 25)
RUG_TUCK = float(_oc('dynamic/rug_rules/front_legs_on_rug_cm', _g('rug_tuck_cm', 15.0)))
# зазор торшера от подлокотника — из правил (dynamic.extras.floor_lamp.from_armrest_cm),
# в коде стояло «+12», вне вилки 15–30
LAMP_GAP = float((_oc('dynamic/extras/floor_lamp/from_armrest_cm', [15, 30]) or [15, 30])[0])


def _add_rug(b: Block, seat: Item, rug: Item | None, far_y: float,
             min_left: float | None = None, others: list[Item] | None = None,
             others_y: float | None = None, others_x: float | None = None) -> None:
    """Ковёр — производная блока: по оси свободной части якоря, длинной стороной
    вдоль дивана.

    КОНСИСТЕНТНОСТЬ ЗАХОДА (замечание владельца 11.08, веб-канон «be consistent
    with how you handle the legs»): ковёр должен заходить под передние ножки ВСЕХ
    посадочных ОДИНАКОВО (~15 см), а не глубоко под диван и краем под кресло.
    Если спутники (кресла/второй диван) стоят дальше — ковёр смещается вперёд,
    чтобы захватить и их фронт; при малом ковре он честно ложится под столик.
    min_left — левая граница (Г-стык: не заезжать под торец второго дивана)."""
    if rug is None:
        return
    fx, _ = _free_x(seat)
    w, d = max(rug.w_cm, rug.d_cm), min(rug.w_cm, rug.d_cm)
    if min_left is not None:
        fx = max(fx, min_left + w / 2)
    near = _front(seat) - RUG_TUCK               # ближняя кромка ковра = под ножки дивана
    ry = near + d / 2
    if others and others_y is not None:
        # достаёт ли ковёр до спутников? фланги стоят СБОКУ (по x), визави — дальше (по y)
        reach_x = others_x
        want_far = others_y + max(o.d_cm for o in others) / 2 - RUG_TUCK
        far_ok = (near + d) >= want_far + RUG_TUCK - 1
        # заход должен быть ЗНАЧИМЫМ (те же ~15 см), а не касанием кромки
        side_ok = reach_x is None or (w / 2) >= reach_x + RUG_TUCK
        if not far_ok and (near + d) < want_far:
            ry = min(want_far - d / 2, (near + want_far) / 2 + d / 4)
            far_ok = True
        if not (far_ok and side_ok):
            # ковёр мал — НЕ подсовываем его частично под диван (веб-канон: либо
            # ножки всех посадочных на ковре, либо ничьи): центрируем под столик
            ry = others_y
    b.add(Item(role=rug.role, w_cm=w, d_cm=d, h_cm=rug.h_cm, name=rug.name,
               item_id=rug.item_id), fx, ry, 0.0)


def _add_flank(b: Block, seat: Item, arm: Item, side: int, at_y: float,
               table_half_w: float | None = None) -> float:
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
    return abs(ax) - arm.d_cm / 2              # внутренняя кромка кресла — для ковра


def _add_lamp(b: Block, seat: Item, lamp: Item | None, side: int = -1) -> None:
    """Торшер У ПОСАДКИ (заявка владельца 11.08; веб-свод: «a pair of matching lamps
    look great flanking a sofa», свет от 60–90 см сбоку, абажур над плечом сидящего).
    Ставим ОДИН у торца дивана — данные майнинга говорят, что напольных предметов
    в комнате около одного; пара — только если в сете два торшера."""
    if lamp is None:
        return
    b.add(lamp, side * (seat.w_cm / 2 + 12 + lamp.w_cm / 2),
          -seat.d_cm / 2 + lamp.d_cm / 2 + 6, 0.0)


def _add_facing(b: Block, seat: Item, other: Item, far_y: float) -> None:
    """Визави: второй посадочный напротив через столик, СИММЕТРИЧНО — равный
    зазор от столика с обеих сторон (замечание владельца 11.08: «один дальше
    другого»; книжный face-to-face получается из симметрии сам)."""
    fx, _ = _free_x(seat)
    b.add(other, fx, far_y + COFFEE_GAP + other.d_cm / 2, 180.0)


def _add_L(b: Block, sofa: Item, other: Item, side: int = -1) -> None:
    """Г/П-стык (правка владельца 11.08): второй диван перпендикулярно сбоку,
    спинкой наружу; его ближний торец — на уровне ФРОНТА первого (не спинки:
    хвост до линии спинки читался как «перекрытие зоны» на чертеже).
    Q5 (Codex 16.08): side=-1 слева (прежнее), +1 — зеркально справа (форма L_right):
    раньше второй диван ставился ТОЛЬКО слева — дыра поиска two_sofa."""
    ox = side * (sofa.w_cm / 2 + L_GAP + other.d_cm / 2)
    oy = _front(sofa) + 5.0 + other.w_cm / 2
    b.add(other, ox, oy, 90.0 if side < 0 else 270.0)


def _seating_bbox(b: Block) -> tuple[tuple[float, float], tuple[float, float]]:
    """Центр и размах посадочного контура блока в ЛОКАЛЬНЫХ координатах (повороты
    осевые). Нужен ковру многосторонних композиций: класть его по центру контура,
    а не по оси одного дивана."""
    xs, ys = [], []
    for it, x, y, rot in b.rel:
        if not it.role.startswith(('диван', 'кресло')):
            continue
        w, d = (it.d_cm, it.w_cm) if int(rot) % 180 == 90 else (it.w_cm, it.d_cm)
        xs += [x - w / 2, x + w / 2]
        ys += [y - d / 2, y + d / 2]
    if not xs:
        return (0.0, 0.0), (0.0, 0.0)
    return (((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2),
            (max(xs) - min(xs), max(ys) - min(ys)))


def _inner_zone(b: Block) -> tuple[float, float, float, float]:
    """Внутренний контур зоны — прямоугольник между ФРОНТАМИ посадочных (то, что
    ковёр обязан накрыть, чтобы ножки всех сторон стояли на нём одинаково)."""
    x0, y0, x1, y1 = -1e9, -1e9, 1e9, 1e9
    for it, x, y, rot in b.rel:
        if not it.role.startswith(('диван', 'кресло')):
            continue
        w, d = (it.d_cm, it.w_cm) if int(rot) % 180 == 90 else (it.w_cm, it.d_cm)
        r = int(rot) % 360
        if r == 0:      # смотрит +y → фронт снизу зоны
            y0 = max(y0, y + d / 2)
        elif r == 180:
            y1 = min(y1, y - d / 2)
        elif r == 90:   # смотрит +x
            x0 = max(x0, x + w / 2)
        else:           # 270, смотрит -x
            x1 = min(x1, x - w / 2)
    # открытая сторона (там никто не сидит) — берём край посадочного контура
    (_, _), _sp = _seating_bbox(b), None
    (cx, cy), (sx, sy) = _seating_bbox(b)
    if x0 < -1e8:
        x0 = cx - sx / 2
    if y0 < -1e8:
        y0 = cy - sy / 2
    if x1 > 1e8:
        x1 = cx + sx / 2
    if y1 > 1e8:
        y1 = cy + sy / 2
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


# ФОКУС-СТЕНА ОБЯЗАТЕЛЬНА (свод владельца 12.08): позиция посадки, не оставляющая
# чистого места носителю ТВ, отвергается. Снимается только на последнем круге каскада,
# когда НИ ОДНА схема не смогла ужиться с фокусом — тогда честнее поставить посадку,
# чем оставить сцену пустой.
# 2 — носителю нужно место В ОСИ взгляда; 1 — любое чистое место; 0 — требования нет
_FOCUS_LEVEL = 2


POUF_AS_TABLE_MIN_W = float(_g('pouf_as_table_min_w_cm', 70.0))


def build_block(group_id: str, by_role: dict[str, Item],
                variant: str = 'default', table_gap: float = COFFEE_GAP,
                table_shift: float = 0.0) -> Block | None:
    """Инстанс шаблона разговорной группы от фактических SKU. v1: канонический
    вариант на группу (вариативность даёт позиция/поворот блока); диван соло без
    спутников блоком не считаем (нечего запекать)."""
    sofa = by_role.get('диван')
    # СЕКЦИОНАЛ ТОЛЬКО УГЛОВОЙ (Codex 21.08, аудит Юли №14): паспорт compact_sectional
    # объявляет sofa_subtype «углов», фактический признак — `Item.corner`. Прямой диван
    # в этой группе — честный sofa_solo (геометрия та же, ярлык перестаёт врать).
    if group_id == 'compact_sectional' and sofa is not None and not sofa.corner:
        group_id = 'sofa_solo'
    arm1, arm2 = by_role.get('кресло'), by_role.get('кресло 2')
    sofa2 = by_role.get('диван 2')
    table, rug = by_role.get('столик'), by_role.get('ковёр')
    # ПУФ ВМЕСТО СТОЛИКА (веб-свод 12.08: «use a compact round table or an ottoman
    # instead of a large rectangular table»): крупный пуф (от 70 см) — мягкий столик
    # по центру зоны, а не подставка для ног сбоку.
    # КАНОН (перепроверено вебом 12.08 по замечанию владельца): пуф работает
    # столиком, только если он ~2/3 длины дивана (HORNE, Decorating Den) — иначе это
    # подставка для ног, а не поверхность. Прежний порог «от 70 см» был липовый:
    # пуфы каталога 75-80 см против диванов 200-230 дают 0.33-0.38 длины.
    _big_pouf = by_role.get('пуф')
    _pouf_ratio = 0.6
    _seat_w = (sofa or arm1).w_cm if (sofa or arm1) else 0.0
    if variant == 'pouf_table' and _big_pouf is not None \
            and _big_pouf.w_cm >= POUF_AS_TABLE_MIN_W \
            and _seat_w and _big_pouf.w_cm >= _pouf_ratio * _seat_w:
        table = _big_pouf
        by_role = {k: v for k, v in by_role.items() if k != 'пуф'}

    if group_id == 'armchair_pair':
        if not (arm1 and arm2):
            return None
        # СИММЕТРИЯ (замечание владельца 11.08): оба кресла на РАВНОМ зазоре от
        # столика (книжный face-to-face 183 давал разные плечи при мелком столике)
        b = Block(arm1)
        # ПАСПОРТ ПЕРВЫМ (аудит Юли №13 + решение владельца 21.08): armchair_pair по
        # zones.json требует «приставной» — крупный журнальный стол между креслами
        # превращал схему в «через стол» и читался как ошибка. Общий столик — фолбэк,
        # когда паспортной поверхности в сете нет.
        far, _fx, tcy = _add_coffee(b, arm1, by_role.get('приставной')
                                    or by_role.get('столик 2') or table,
                                    table_gap, table_shift)
        b.add(arm2, 0.0, far + COFFEE_GAP + arm2.d_cm / 2, 180.0)
        if rug is not None:
            # ковёр по ВНУТРЕННЕМУ КОНТУРУ зоны (замечание владельца 12.08 «оба
            # кресла не на ковре»): центр столика не гарантировал заход ножек —
            # при глубоких креслах ковёр оказывался только под столиком
            _place_zone_rug(b, rug)
        _pull_seats_onto_rug(b)
        return _valid(b)

    if sofa is None:
        return None
    # СВЯЗКА ЗОНЫ (замечание владельца 12.08, set1-bay): разговорная зона из
    # НЕСКОЛЬКИХ посадочных обязана иметь «клей» — столик ИЛИ ковёр. Без них кресло
    # читается как оторванное, даже стоя на канонической фланговой дистанции.
    # Нет клея → эта схема недействительна, каскад возьмёт меньшую (диван соло),
    # а кресло уйдёт в свою зону (уголок чтения).
    _companions = any(k.startswith(('кресло', 'диван 2', 'пуф')) for k in by_role)
    if _companions and table is None and rug is None:
        return None
    b = Block(sofa)
    # Г-КОМПОЗИЦИЯ: столик канонически сдвигается К ВНУТРЕННЕМУ УГЛУ (R1, разбор Codex 19.08).
    # Столик по центру ГЛАВНОГО дивана оставлял второму 75 см до столика при hard-пределе 50 —
    # с него до столика просто не дотянуться, а валидатор мерил только главный диван.
    # Сдвиг ровно такой, чтобы второй диван получил тот же канонический зазор 42.5.
    if group_id in ('sofa_loveseat', 'sofa_loveseat_2armchairs', 'two_sofas_2armchairs') \
            and sofa2 is not None and table is not None and not table_shift:
        _side_L = +1 if variant in ('L_right', 'square_r') else -1
        _tl = max(table.w_cm, table.d_cm)
        table_shift = _side_L * max(0.0, sofa.w_cm / 2 + L_GAP - _tl / 2 - COFFEE_GAP)
    far, table_x, table_cy = _add_coffee(b, sofa, table, table_gap, table_shift)
    _, free_side = _free_x(sofa)
    rug_min_left = None
    rug_others: list[Item] | None = None
    rug_others_y: float | None = None
    rug_others_x: float | None = None

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
        return _valid(b)
    elif group_id in ('sofa_loveseat', 'sofa_loveseat_2armchairs',
                      'two_sofas_2armchairs'):
        # v2.1: Г-стык торец-к-торцу; столик остаётся по центру ГЛАВНОГО дивана
        # (SOFA_TABLE_DIST в validate привязан только к главному — проверено)
        if not sofa2 or sofa.corner or sofa2.corner:
            return None
        # 19.08 (Codex): у `square` не было ЗЕРКАЛА — второй диван всегда слева, кресла всегда
        # справа. Поворот блока зеркало не заменяет: композиция трёхсторонняя, и сторона входа
        # в группу задаётся именно отражением. Вводим `square_r`.
        _Lside = +1 if variant in ('L_right', 'square_r') else -1
        _add_L(b, sofa, sofa2, side=_Lside)
        rug_min_left = -(sofa.w_cm / 2 + L_GAP) + 6.0   # правый край дивана 2 + зазор
        if variant in ('square', 'square_r'):
            # ТРЁХСТОРОННЯЯ группа (H&G): два дивана по двум сторонам, ПАРА кресел на третьей,
            # четвёртая открыта под вход. Кресла — на стороне, ПРОТИВОПОЛОЖНОЙ второму дивану.
            tw_half = (max(table.w_cm, table.d_cm) / 2) if table else 40.0
            _cs = -_Lside                      # сторона кресел
            _rot_c = 270.0 if _cs > 0 else 90.0
            if arm1:
                # 19.08: центр каждого кресла считаем по ЕГО глубине (раньше оба брали глубину
                # первого — при разных креслах зазоры фактически расходились)
                b.add(arm1, table_x + _cs * (tw_half + FLANK_GAP + arm1.d_cm / 2),
                      table_cy, _rot_c)
                if arm2 and group_id != 'sofa_loveseat':
                    b.add(arm2, table_x + _cs * (tw_half + FLANK_GAP + arm2.d_cm / 2),
                          table_cy + arm1.w_cm / 2 + arm2.w_cm / 2 + 12, _rot_c)
        elif arm1:
            # П-композиция (владелец 11.08): кресла — на ДЛИННОЙ стороне столика
            # НАПРОТИВ главного дивана, лицом к нему; открытая сторона П — к экрану.
            # Q5 (Codex): ay — ПО КАЖДОМУ креслу (передние кромки выровнены), а не по d
            # первого: иначе клон с меньшей глубиной падал в ARMCHAIR_OUT_OF_ZONE
            ay1 = far + COFFEE_GAP + arm1.d_cm / 2
            if arm2 and group_id != 'sofa_loveseat':
                ay2 = far + COFFEE_GAP + arm2.d_cm / 2
                b.add(arm1, table_x - (arm1.w_cm / 2 + 8), ay1, 180.0)
                b.add(arm2, table_x + (arm2.w_cm / 2 + 8), ay2, 180.0)
            else:
                b.add(arm1, table_x, ay1, 180.0)
        if rug is not None:
            # П-композиция (замечание владельца 11.08 «неравномерно заходят»):
            # ковёр кладём по центру ВНУТРЕННЕГО контура зоны и только если он
            # достаёт до фронтов ВСЕХ сторон с одинаковым заходом; иначе —
            # честный малый паттерн «под столик» (канон: либо ножки всех, либо ничьи)
            (cx, cy), _ = _seating_bbox(b)
            (ix0, iy0, ix1, iy1) = _inner_zone(b)
            need_x = (ix1 - ix0) + 2 * RUG_TUCK
            need_y = (iy1 - iy0) + 2 * RUG_TUCK
            rw, rd = max(rug.w_cm, rug.d_cm), min(rug.w_cm, rug.d_cm)
            fits_wide = rw >= need_x and rd >= need_y
            fits_tall = rd >= need_x and rw >= need_y
            if fits_wide or fits_tall:
                w_, d_ = (rw, rd) if fits_wide else (rd, rw)
                b.add(Item(role=rug.role, w_cm=w_, d_cm=d_, h_cm=rug.h_cm,
                           name=rug.name, item_id=rug.item_id),
                      (ix0 + ix1) / 2, (iy0 + iy1) / 2, 0.0)
            else:
                # мал для «ножек всех» — кладём по центру ВНУТРЕННЕГО контура:
                # так перекос захода минимален (под столик ушёл бы к одной стороне)
                w_, d_ = ((rw, rd) if (ix1 - ix0) >= (iy1 - iy0) else (rd, rw))
                b.add(Item(role=rug.role, w_cm=w_, d_cm=d_, h_cm=rug.h_cm,
                           name=rug.name, item_id=rug.item_id),
                      (ix0 + ix1) / 2, (iy0 + iy1) / 2, 0.0)
            _ = cx, cy
        return _valid(b)
    elif group_id in ('sofa_2armchairs', 'sofa_4armchairs'):
        if not (arm1 and arm2):
            return None
        if variant == 'bulky' or (variant == 'default' and arm1.d_cm >= 100):
            # КРУПНЫЕ КРЕСЛА (новая схема 11.08, сет 112: кресла-кровати 118×119 —
            # по глубине почти диван). Флангом у столика они не встают физически
            # (круг беседы против дистанции до столика). Схема: кресла ВТОРЫМ РЯДОМ
            # напротив дивана, развёрнуты к зоне; столик остаётся у дивана.
            ay = far + COFFEE_GAP + arm1.d_cm / 2
            b.add(arm1, table_x - (arm1.w_cm / 2 + 10), ay, 180.0)
            b.add(arm2, table_x + (arm2.w_cm / 2 + 10), ay, 180.0)
            _add_lamp(b, sofa, by_role.get('торшер'))
            if rug is not None:
                # ковёр по ЦЕНТРУ ВНУТРЕННЕГО КОНТУРА (замечание владельца 11.08:
                # столик был не по центру ковра, кресла на ковре, диван мимо).
                # Правило то же, что в П-композиции: либо ножки всех, либо ничьи.
                (ix0, iy0, ix1, iy1) = _inner_zone(b)
                rw, rd = max(rug.w_cm, rug.d_cm), min(rug.w_cm, rug.d_cm)
                need_x, need_y = (ix1 - ix0) + 2 * RUG_TUCK, (iy1 - iy0) + 2 * RUG_TUCK
                if rw >= need_x and rd >= need_y:
                    w_, d_ = rw, rd
                elif rd >= need_x and rw >= need_y:
                    w_, d_ = rd, rw
                else:
                    w_, d_ = ((rw, rd) if (ix1 - ix0) >= (iy1 - iy0) else (rd, rw))
                b.add(Item(role=rug.role, w_cm=w_, d_cm=d_, h_cm=rug.h_cm,
                           name=rug.name, item_id=rug.item_id),
                      (ix0 + ix1) / 2, (iy0 + iy1) / 2, 0.0)
            return _valid(b)
        if variant == 'u':
            tw_half = (max(table.w_cm, table.d_cm) / 2) if table else 40.0
            # Q5 свода №13 (реплей set92): кресла 3/4 — SECONDARY (второй pod, Q1/Q3: sofa_4armchairs
            # — shadow-контрфактуал); форма «u» главной sofa_2armchairs их НЕ забирает — иначе
            # pod-комплект (пара + столик 2) обезглавлен, а главная группа перегружена (№174)
            a3, a4 = ((by_role.get('кресло 3'), by_role.get('кресло 4'))
                      if group_id == 'sofa_4armchairs' else (None, None))
            for side, near, far_arm in ((-1, arm1, a3), (+1, arm2, a4)):
                ax = side * (tw_half + FLANK_GAP + near.d_cm / 2) + table_x
                rot = 90.0 if side < 0 else 270.0
                b.add(near, ax, table_cy, rot)
                if far_arm is not None:
                    b.add(far_arm, ax,
                          table_cy + near.w_cm / 2 + far_arm.w_cm / 2 + 12, rot)
            side_t = by_role.get('приставной')
            if table is not None and side_t is not None:
                # U обслуживает 3 стороны — пары столиков валидны (веб-свод 11.08:
                # «paired coffee tables»); приставной в линию к столику по оси
                b.add(side_t, table_x, table_cy + max(table.w_cm, table.d_cm) / 2 * 0
                      + min(table.w_cm, table.d_cm) / 2 + 8 + side_t.d_cm / 2, 0.0)
            if rug is not None:
                rw, rd = max(rug.w_cm, rug.d_cm), min(rug.w_cm, rug.d_cm)
                b.add(Item(role=rug.role, w_cm=rw, d_cm=rd, h_cm=rug.h_cm,
                           name=rug.name, item_id=rug.item_id), table_x, table_cy, 0.0)
            return _valid(b)
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
        elif variant == 'media_bridge':
            # Q3 свода №13 (blind: владелец хочет кресла параллельно дивану или ПОЛУОБОРОТОМ
            # к ТВ, не «к дивану»; Wayfair: акцентное кресло рядом с диваном под углом к ТВ):
            # пара флангами у столика, повёрнута к экрану на 45° (справа 315°, слева 45° —
            # взгляд ВНУТРЬ-ВПЕРЁД, на экран; до 19.08 стороны были перепутаны, и кресла
            # смотрели в наружные углы мимо ТВ) — зеркально «bridge», который смотрит
            # НАЗАД (135/225). Медиапригодность
            # проверяется на готовом плане (view_metrics.armchair_tv_angles ≤ 45°).
            _thw = (max(table.w_cm, table.d_cm) / 2 if table else None)
            # 19.08: диагональные кресла сдвигаем на 12 см ЗА линию столика — иначе взгляд под 45°
            # проходит ровно по кромке (валидатор честно ловит ARMCHAIR_NOT_FACING_GROUP), а
            # композиция читается как «кресла сами по себе»
            _fx1 = _add_flank(b, sofa, arm1, +1, table_cy, table_half_w=_thw)
            b.rel[-1] = (arm1, b.rel[-1][1], b.rel[-1][2] + 12.0, 315.0)
            _fx2 = _add_flank(b, sofa, arm2, -1, table_cy, table_half_w=_thw)
            b.rel[-1] = (arm2, b.rel[-1][1], b.rel[-1][2] + 12.0, 45.0)
            rug_others, rug_others_y, rug_others_x = [arm1, arm2], table_cy, max(_fx1, _fx2)
        elif variant == 'bridge':
            # B1 (v2, веб-свод): диван смотрит на ТВ, одно кресло развёрнуто ПОД
            # УГЛОМ (45°) — мостик между медиа-зоной и камином
            # ПАРА ПОД ЗЕРКАЛЬНЫМИ УГЛАМИ (замечание владельца 11.08 + веб-свод:
            # «identical seating on each side», пара кресел — симметрия). Одно
            # кресло под углом, другое прямо — визуально неряшливо.
            _fx1 = _add_flank(b, sofa, arm1, +1, table_cy,
                              table_half_w=(max(table.w_cm, table.d_cm) / 2
                                            if table else None))
            b.rel[-1] = (arm1, b.rel[-1][1], b.rel[-1][2] + 12.0, 225.0)
            _add_flank(b, sofa, arm2, -1, table_cy,
                       table_half_w=(max(table.w_cm, table.d_cm) / 2 if table else None))
            b.rel[-1] = (arm2, b.rel[-1][1], b.rel[-1][2] + 12.0, 135.0)   # зеркально
            rug_others, rug_others_y, rug_others_x = [arm1, arm2], table_cy, _fx1
        elif variant == 'facing':
            # кресла ВИЗАВИ прямого дивана (майнинг ProcTHOR 11.08: схема так же
            # часта, как фланг — 612 vs 626 из 9013 гостиных; легальна, когда
            # кресло не на пути диван→экран — ослабленный P0.4)
            ay = far + COFFEE_GAP + arm1.d_cm / 2
            b.add(arm1, table_x - (arm1.w_cm / 2 + 8), ay, 180.0)
            b.add(arm2, table_x + (arm2.w_cm / 2 + 8), ay, 180.0)
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
            _fx1 = _add_flank(b, sofa, arm1, -1, table_cy, table_half_w=thw)
            _fx2 = _add_flank(b, sofa, arm2, +1, table_cy, table_half_w=thw)
            rug_others, rug_others_y = [arm1, arm2], table_cy
            rug_others_x = max(_fx1, _fx2)
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
            # C1 (v2, перепроверено вебом 11.08): пуфы вместо кресла в тесных.
            # СИММЕТРИЯ (замечание владельца): пара одинаковых пуфов по бокам
            # столика; одиночный — только если второго в сете нет.
            pouf, pouf2 = by_role.get('пуф'), by_role.get('пуф 2')
            if pouf is None:
                return None
            off = (max(table.w_cm, table.d_cm) / 2 if table else 40) + 20
            if pouf2 is not None:
                b.add(pouf, table_x - off - pouf.w_cm / 2, table_cy, 90.0)
                b.add(pouf2, table_x + off + pouf2.w_cm / 2, table_cy, 270.0)
            else:
                b.add(pouf, table_x + off + pouf.w_cm / 2, table_cy, 270.0)
            _add_lamp(b, sofa, by_role.get('торшер'))
            _add_rug(b, sofa, rug, far, min_left=rug_min_left)
            return _valid(b)
        if variant == 'facing' and not sofa.corner:
            b.add(arm1, table_x, far + COFFEE_GAP + arm1.d_cm / 2, 180.0)
            _add_rug(b, sofa, rug, far, min_left=rug_min_left)
            return _valid(b)
        if sofa.corner:
            tw_half = (max(table.w_cm, table.d_cm) / 2) if table else 40.0
            ax = table_x + free_side * (tw_half + FLANK_GAP + arm1.d_cm / 2)
            b.add(arm1, ax, far, 270.0 if free_side > 0 else 90.0)
        elif variant in ('media_parallel', 'media_half'):
            # Q3 свода №13: одиночное кресло флангом у столика ПАРАЛЛЕЛЬНО дивану — лицом
            # к ТВ (media_parallel: 0°) или полуоборотом к экрану (media_half: 45°/315°
            # в сторону центра). Владелец (blind pair09): «кресла должны быть обращены
            # параллельно дивану — к столику/ТВ, либо полуоборотом к телевизору».
            _fx1 = _add_flank(b, sofa, arm1, free_side, table_cy,
                              table_half_w=(max(table.w_cm, table.d_cm) / 2
                                            if table else None))
            _rot = 0.0 if variant == 'media_parallel' else (315.0 if free_side > 0 else 45.0)
            b.rel[-1] = (arm1, b.rel[-1][1], b.rel[-1][2], _rot)
            rug_others, rug_others_y, rug_others_x = [arm1], table_cy, _fx1
        else:
            _fx1 = _add_flank(b, sofa, arm1, free_side, table_cy,
                              table_half_w=(max(table.w_cm, table.d_cm) / 2
                                            if table else None))
            rug_others, rug_others_y, rug_others_x = [arm1], table_cy, _fx1
    else:
        # v1.1 (аудит полноты): диван соло + столик + ковёр — блоком тоже (самый
        # частый состав малых комнат; привязка ковра/столика нужна и без кресел).
        # Совсем нечего запекать (ни столика, ни ковра) — блока нет.
        if table is None and rug is None:
            return None
    # ПУФ-КОМПАНЬОН (экзамен 11.08: пуф избыточен в 124 сценах — отдельная зона
    # ловит место редко). Ставим его в САМ шаблон посадки: у свободного фланга,
    # на линии столика (веб-свод: «next to or in front of the sofa»).
    # ПУФ-КОМПАНЬОН (веб-свод 12.08: «narrow ottoman that tucks neatly in front»):
    # при наличии кресла пуф — ПОДСТАВКА ДЛЯ НОГ перед ним (20–30 см), а не предмет
    # сбоку от столика (там он бился о кресло: COLLISION 22 см, POUF_OUT_OF_ZONE).
    _pouf = by_role.get('пуф')
    _has_bearer = any(r in by_role for r in ('тв-тумба', 'стенка'))
    if _pouf is not None:
        # ДВЕ КАНОННЫЕ ПОЗИЦИИ, а не одна (12.08): подставка для ног перед креслом
        # часто попадает на журнальный столик — тогда пуф уходит на свободный фланг
        # столика. Раньше схема из-за этого браковалась целиком, и зона теряла столик.
        # ПУФ И КРЕСЛО — ПО РАЗНЫЕ СТОРОНЫ (владелец 13.08, планы №1/№2: «пуф рядом
        # с креслом нелогично — либо разнесены, либо одного из них нет»). Подставка
        # для ног строго ПЕРЕД креслом (25 см по его оси); фланговая позиция пуфа —
        # только НА ПРОТИВОПОЛОЖНОМ от кресла фланге столика. Обе не встали — пуф
        # выбывает из схемы (каскад и так пробует состав без пуфа первым делом).
        _spots = []
        _arm_p = next((t for t in b.rel if t[0].role.startswith('кресло')), None)
        if _arm_p is not None:
            _ai, _ax, _ay, _arot = _arm_p
            _dist = _ai.d_cm / 2 + 25 + _pouf.d_cm / 2
            _dx, _dy = _rt(0.0, _dist, _arot)
            _spots.append((_ax + _dx, _ay + _dy, _arot))
            # фланг: строго противоположный креслу (кресло слева → пуф справа)
            _pouf_side = -1 if _ax * free_side > 0 else free_side
        else:
            _pouf_side = free_side
        _px = (table_x + _pouf_side * ((max(table.w_cm, table.d_cm) / 2 if table else 40)
                                       + 25 + _pouf.w_cm / 2))
        _spots.append((_px, table_cy, 270.0 if _pouf_side > 0 else 90.0))
        # ПУФ НЕ НА ОСИ ВЗГЛЯДА (владелец 13.08, «чини»: 22 из 23 пустых фокус-стен —
        # пуф схемы попадал в коридор диван↔ТВ при развороте к окну, и медиа гибла).
        # Ось известна уже на СБОРКЕ: фронт дивана в локальном фрейме = полоса x∈[-60,60]
        # перед фронтом. Пуф в этой полосе недопустим, если в банке есть носитель ТВ.
        def _on_axis(px: float, py: float) -> bool:
            if not _has_bearer:
                return False
            half = _pouf.w_cm / 2 + 8
            return (abs(px) - half) < 60.0 and py > 0
        _pouf_in = False
        for _sx, _sy, _srt in _spots:
            if _on_axis(_sx, _sy):
                continue
            b.add(_pouf, _sx, _sy, _srt)
            if block_self_overlap(b) is None:
                _pouf_in = True
                break
            b.rel.pop()                      # не встал — пробуем другую позицию
        # C-5 свода №11 (Кодекс §7, атомарность): пуф — REQUIRED-роль своей группы
        # (sofa_pouf) — не выпадает ТИХО: обе позиции конфликтуют → схема этой
        # ступени НЕ собирается, лестница честно спустится (прежде блок возвращался
        # без пуфа, и _actual_step маскировал разбор переименованием)
        _grp_req = {r.split(' ')[0]
                    for g in _zone_rules().get('seating_groups', [])
                    if g['id'] == group_id
                    for r in g['roles']['required']}
        if not _pouf_in and 'пуф' in _grp_req:
            return None
    _add_lamp(b, sofa, by_role.get('торшер'))
    if by_role.get('торшер 2') is not None:
        _add_lamp(b, sofa, by_role.get('торшер 2'), side=+1)   # пара — симметрично
    # ЕДИНОЕ ПРАВИЛО КОВРА (ревизия 11.08 по замечанию владельца): если в зоне есть
    # спутники — ковёр центрируется по ВНУТРЕННЕМУ КОНТУРУ зоны (тогда и столик по
    # центру ковра, и заход под ножки у всех одинаковый); мал — ложится под столик
    # (канон «либо ножки всех, либо ничьи»). Диван соло — привязка к его ножкам.
    if rug is not None and rug_others:
        (ix0, iy0, ix1, iy1) = _inner_zone(b)
        rw, rd = max(rug.w_cm, rug.d_cm), min(rug.w_cm, rug.d_cm)
        need_x, need_y = (ix1 - ix0) + 2 * RUG_TUCK, (iy1 - iy0) + 2 * RUG_TUCK
        if rw >= need_x and rd >= need_y:
            w_, d_ = rw, rd
        elif rd >= need_x and rw >= need_y:
            w_, d_ = rd, rw
        else:
            w_, d_ = ((rw, rd) if (ix1 - ix0) >= (iy1 - iy0) else (rd, rw))
        b.add(Item(role=rug.role, w_cm=w_, d_cm=d_, h_cm=rug.h_cm, name=rug.name,
                   item_id=rug.item_id), (ix0 + ix1) / 2, (iy0 + iy1) / 2, 0.0)
    else:
        _add_rug(b, sofa, rug, far, min_left=rug_min_left,
                 others=rug_others, others_y=rug_others_y, others_x=rug_others_x)
    _pull_seats_onto_rug(b)
    return _valid(b)


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
    # V4-A свода №10 (аудит №5): «стол + ≥2 стульев или ничего» (ADR-0077,
    # атомарность обеденной группы) — гарантируется ДВИЖКОМ, не только композитором
    if len(chairs) < 2:
        return None
    b = Block(tbl)
    w, d = tbl.w_cm, tbl.d_cm
    chair_w = max(c.w_cm for c in chairs)
    # v2.3: круглый/квадратный стол (w==d) — по одному стулу с каждой стороны
    # (через 90°). Прямоугольный — пары по длинным сторонам, но ТОЛЬКО если пара
    # физически помещается с зазором ≥8 (set37: узкий стол бил стул о стул)
    # + паспортная ёмкость кромки: ≥ edge_per_diner_cm на едока (свод №8 пакет A)
    _edge_min = 2 * float(_dining_rules().get('edge_per_diner_cm', 61) or 61)
    pair_ok = w >= max(2 * chair_w + 24, _edge_min)
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
    return _valid(b, 'dining')


def _pair_sofa_candidates(room: Room, sofa_item: Item, free: Polygon,
                          media: Item | None) -> list:
    """Якоря дивана из топ-пар генератора П1 (`planner/tv_sofa.py`)."""
    if media is None:
        return []
    try:
        from .candidates import Candidate
        from .room_map import build_room_map
        from .tv_sofa import generate_pairs
        rmap = build_room_map(room)
        out = []
        for pr in generate_pairs(room, rmap, media, sofa_item, top_k=6):
            p = Placement(role=sofa_item.role, x=pr.sofa_x, y=pr.sofa_y,
                          rot=pr.sofa_rot, item=sofa_item)
            fp = footprint(p)
            if free.intersection(fp).area < fp.area * 0.97:
                continue
            _cand_pair = Candidate(placement=p, kind='middle',
                                 note=f'пара WallScore {pr.score}',
                                 topology='tv_range')
            # C-3 свода №11 (Кодекс §3): координаты НОСИТЕЛЯ пары сохраняются —
            # проба места под медиа проверит ИМЕННО эту позицию первой (прежде
            # media_x/y выбрасывались, и «пара» была лишь диванным кандидатом)
            _cand_pair.pair_media = (pr.media_x, pr.media_y, pr.media_rot)
            out.append(_cand_pair)
        return out
    except Exception:
        return []


def _tv_range_candidates(room: Room, item: Item, free: Polygon,
                         tv: Item | None = None) -> list:
    """Позиции дивана НА ТВ-ВИЛКЕ от стены будущего носителя (глубокие комнаты).

    Владелец 13.08: в глубокой комнате коммуникативная зона придвигается к медиа
    (дистанция просмотра в вилке диагонали), а за спинкой остаётся столовая. Даём
    позиции «спинкой в комнату» на расстоянии середины вилки от каждой из 4 стен.
    """
    from .candidates import Candidate
    from .tv import distance_range, rules as _tvrules
    # C-2 свода №11 (Кодекс): вилка — от ФАКТИЧЕСКОГО носителя сцены (ширина и
    # глубина), а не условных 120/40; доля верха вилки — из данных
    from .geometry import base_role as _brr
    if tv is not None and _brr(tv.role) in ('тв-тумба', 'стенка'):
        lo, hi, _ = distance_range(tv.w_cm, bearer=_brr(tv.role))
        _tv_depth = tv.d_cm or 40.0
    else:
        lo, hi, _ = distance_range(120.0)
        _tv_depth = 40.0
    _hi_share = float((_tvrules().get('layout_rules') or {}).get('tv_range_hi_share', 0.92))
    W, D = room.width_cm, room.depth_cm
    spots = []
    # ступени дистанции: середина вилки и верх (13.08: блок с ковром и пуфом ГЛУБЖЕ
    # одного дивана — от середины вилки фронту блока не хватало места до стены,
    # и стенка не вставала; от верха вилки — помещается блок целиком)
    for base_d in ((lo + hi) / 2, hi * _hi_share):
        d_mid = base_d + item.d_cm / 2 + _tv_depth
        spots += [(W / 2, d_mid, 180.0), (W / 2, D - d_mid, 0.0),
                  (d_mid, D / 2, 270.0), (W - d_mid, D / 2, 90.0)]
    out = []
    for x, y, rot in spots:
        p = Placement(role=item.role, x=x, y=y, rot=rot, item=item)
        fp = footprint(p)
        if free.intersection(fp).area >= fp.area * 0.97:
            out.append(Candidate(placement=p, kind='middle', note='на ТВ-вилке',
                                 topology='tv_range'))
    return out


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


def _side_probe(room: Room, seat_p: Placement, free: Polygon, need_w: float) -> float:
    """v2.5b (двойной фокус): есть ли место под ВТОРОЙ фокус (камин) на СМЕЖНОЙ
    стене — луч под ±60° от взгляда посадки. Возвращает 0..1 (лучшая из сторон)."""
    best = 0.0
    for off in (-60.0, 60.0):
        r = math.radians(seat_p.rot + off)
        dx, dy = math.sin(r), math.cos(r)
        poly = room_polygon(room)
        d, t = None, 60.0
        while t <= 900.0:
            if not poly.contains(Point(seat_p.x + dx * t, seat_p.y + dy * t)):
                d = t
                break
            t += 30.0
        if d is None or d < 150:
            continue
        spot = Point(seat_p.x + dx * (d - 40), seat_p.y + dy * (d - 40)) \
            .buffer(max(need_w / 2, 40.0), resolution=4)
        best = max(best, free.intersection(spot).area / max(spot.area, 1e-6))
    return best


_RUG_FORBID = ('комод', 'стеллаж', 'витрина', 'шкаф', 'камин', 'кашпо',
               'стол обеденный', 'стул')
_MEDIA_TOE_CM = float(_g('media_toe_cm', 15.0))
# КРАЙНИЙ СЛУЧАЙ (решение владельца 12.08): «ковёр может заходить под медиа-зону».
# Сначала ищем место при обычном заходе 15 см; если медиа-зоны иначе не будет вовсе —
# разрешаем ковру уйти под носитель глубже (до глубины тумбы). Лучше зона с заходом
# ковра, чем сцена без ТВ.
_MEDIA_TOE_MAX_CM = float(_g('media_toe_max_cm', 45.0))
_MEDIA_TOE_RELAXED = False
_DECOR_GAP_CM = float(_g('decor_gap_cm', 30.0))


def _inter_zone_ok(room: Room, ps: list[Placement],
                   fixed: list[Placement] | None) -> bool:
    """МЕЖЗОННЫЕ ПРАВИЛА (замечания владельца 12.08, `zones.json` →
    inter_zone_rules): 1) ковёр — подложка ПОСАДОЧНОЙ зоны, поздние зоны на него
    не заходят (носителю ТВ можно кромкой ≤15 см); 2) напольному декору нужен
    просвет ≥30 см от корпусной мебели, иначе он выглядит зажатым."""
    base = list(fixed or [])
    rug = next((p for p in base if p.role == 'ковёр'), None)
    if rug is not None:
        rug_fp = footprint(rug)
        for p in ps:
            b_ = _base_role(p.role)
            if b_ in _RUG_FORBID:
                if rug_fp.intersection(footprint(p)).area > 100:      # >0.01 м²
                    return False
            elif b_ in ('тв-тумба', 'стенка'):
                inter = rug_fp.intersection(footprint(p))
                if not inter.is_empty:
                    ix0, iy0, ix1, iy1 = inter.bounds
                    _toe = _MEDIA_TOE_MAX_CM if _MEDIA_TOE_RELAXED else _MEDIA_TOE_CM
                    if min(ix1 - ix0, iy1 - iy0) > _toe:
                        return False
    case_fp = [footprint(p) for p in base
               if _base_role(p.role) in ('комод', 'стеллаж', 'витрина', 'шкаф',
                                         'стенка', 'тв-тумба', 'камин')]
    for p in ps:
        if _base_role(p.role) in ('кашпо', 'торшер') and case_fp:
            if min(footprint(p).distance(c) for c in case_fp) < _DECOR_GAP_CM:
                return False
    # СИММЕТРИЧНО (баг 12.08, set4-base: кашпо стояло раньше, стеллаж пришёл в 3 см):
    # новая корпусная мебель тоже обязана держать просвет к уже стоящему декору
    decor_fp = [footprint(p) for p in base
                if _base_role(p.role) in ('кашпо', 'торшер')]
    if decor_fp:
        for p in ps:
            if _base_role(p.role) in ('комод', 'стеллаж', 'витрина', 'шкаф',
                                      'стенка', 'тв-тумба', 'камин'):
                if min(footprint(p).distance(dfp) for dfp in decor_fp) < _DECOR_GAP_CM:
                    return False
    return True


_OPPOSITE = {'north': 'south', 'south': 'north', 'west': 'east', 'east': 'west'}


def _wall_of(room: Room, p: Placement) -> str:
    """К какой стене прижат предмет (по минимальному расстоянию до её линии)."""
    d = {'south': p.y, 'north': room.depth_cm - p.y,
         'west': p.x, 'east': room.width_cm - p.x}
    return min(d, key=d.get)


def _base_role(role: str) -> str:
    return role.split(' ')[0] if role.split(' ')[-1].isdigit() else role


def _window_block_score(room: Room, p: Placement) -> float:
    """D3 (M-D, свод №5): штраф за перекрытие окна = k × доля перекрытия проёма ×
    фактор высоты (предмет ниже подоконника свет не крадёт). Числа —
    `rules/zones.json → wall_preferences.window_blocking`."""
    from .zones import zone_rules as _zr
    cfg = _zr().get('wall_preferences', {}).get('window_blocking', {})
    sill = float(cfg.get('sill_cm', 90))
    k = float(cfg.get('k', 0.9))
    h = float(p.item.h_cm or 0.0 if p.item else 0.0)
    if h <= sill:
        return 0.0
    hf = min(1.0, (h - sill) / 100.0)
    total = 0.0
    from .geometry import opening_polygon
    fp = footprint(p).buffer(8.0)
    for op in room.openings:
        if op.kind != 'window':
            continue
        w_poly = opening_polygon(room, op)
        inter = fp.intersection(w_poly.buffer(12.0))
        if inter.is_empty:
            continue
        share = min(1.0, inter.area / max(w_poly.area, 1.0))
        total += k * share * hf
    return total


def _best_block(room: Room, b: Block, free: Polygon, cands, *, tv: Item | None,
                fixed: list[Placement] | None, top: int = 1,
                axis_seat: Placement | None = None,
                second_focus: Item | None = None,
                require_bearer: Item | None = None,
                stats: dict | None = None) -> list[Placement] | None:
    """Общий отборщик: fits-проба всех членов → ТВ-проба → эвристический ранг →
    полный validate (hard) топ-N; первый чистый побеждает."""
    cands = list(cands)               # V3-B: счётчики + защита от генераторов
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
        if not _inter_zone_ok(room, ps, fixed):
            continue                       # межзонные правила (ковёр/декор)
        score = 1.0 if c.kind == 'wall' else 0.8
        # БЛИКИ (заявка владельца 12.08, веб-свод: «не ставить ТВ напротив окна;
        # лучше стена ПЕРПЕНДИКУЛЯРНО окнам»): носитель на оконной стене или
        # прямо напротив окна получает сильный штраф — уходит вниз рейтинга,
        # но остаётся возможным, если других стен нет
        if _base_role(ps[0].role) in ('тв-тумба', 'стенка'):
            for op in room.openings:
                if op.kind != 'window':
                    continue
                same = _wall_of(room, ps[0]) == op.wall
                opposite = _wall_of(room, ps[0]) == _OPPOSITE.get(op.wall)
                if same or opposite:
                    score -= 1.2 if opposite else 0.8
        # D3 (M-D, свод №5 window-heavy): перекрытие окна × высота — мягкий скор
        # для ЛЮБОЙ пристенной мебели (числа — zones.json wall_preferences)
        for p in ps:
            if p.role == 'ковёр' or not p.item or not p.item.h_cm:
                continue
            score -= _window_block_score(room, p)
        if c.kind == 'corner' and getattr(b.anchor, 'corner', False):
            score += 0.5          # D2 (v2): Г-диван в угол — освобождает пол
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
            if second_focus is not None:
                # v2.5b: камин + ТВ на СМЕЖНЫХ стенах — посадка по диагонали к
                # обоим (данные-правило tv_wall_offset уже в zones.json)
                score += _side_probe(room, ps[0], free, second_focus.w_cm) * 1.2
        if axis_seat is not None:
            # медиа-блок: приоритет соосности с главным посадочным (межзонная связь)
            r = math.radians(axis_seat.rot)
            vx, vy = ps[0].x - axis_seat.x, ps[0].y - axis_seat.y
            n = math.hypot(vx, vy) or 1.0
            cosang = (math.sin(r) * vx + math.cos(r) * vy) / n
            ang = math.degrees(math.acos(max(-1.0, min(1.0, cosang))))
            score += max(0.0, 1.5 - ang / 30.0)
            # ПО ЦЕНТРУ НАПРОТИВ ДИВАНА (замечание владельца 12.08, set6-long: «есть
            # ровная свободная стена, а тумба встала с краю»). Поперечное смещение от
            # оси взгляда — вес сильнее углового: 0 см = +3, 120 см = 0.
            off = abs(math.cos(r) * vx - math.sin(r) * vy)
            score += max(0.0, 3.0 - off / 40.0)
            # П3 (MASTER-tv-sofa-pair): дистанция к ЦЕЛИ RTINGS 1.6×D — слагаемое
            # скоринга позиции носителя (не hard: вилку держит validate)
            _bp = next((p0 for p0 in ps
                        if p0.role.split(' ')[0] in ('тв-тумба', 'стенка')), None)
            # П3 отложен целиком в large-room-mode L2: и слагаемое, и расширение пула
            # сдвигали выбор позиций, set101-trapezoid терял носителя. Функция цели
            # RTINGS живёт в planner/tv.py (distance_target) и ждёт L2.
        scored.append((score, ps, getattr(c, 'topology', ''), c))
    scored.sort(key=lambda t: -t[0])
    base = list(fixed or [])
    first_hard = None
    # КАЧЕСТВО ВЫБОРА ПОЗИЦИИ (A/B 11.08: эвристика давала soft 30.8 против 1.2 у
    # поштучного перебора): среди hard-чистых позиций блока выбираем ЛУЧШУЮ по той же
    # лексикографической мере, что и весь движок, а не первую попавшуюся.
    from .score import score_layout
    from .zones import lexo_key
    ok_variants: list[tuple[tuple, list[Placement]]] = []
    nb_variants: list[tuple[tuple, list[Placement]]] = []   # без места под носитель
    # КВОТА ВИЛОЧНЫХ (13.08): топ-24 по эвристике — сплошь пристенные, и позиции
    # «на ТВ-вилке» (деление глубокой комнаты на 2 зоны) не доходили до полного
    # разбора вовсе. Вилочные разбираются ВСЕ, сверх топ-N.
    _pool = scored[:TOP_FULL_VALIDATE] + [t for t in scored[TOP_FULL_VALIDATE:]
                                          if t[2] == 'tv_range']
    for _, ps, _topo, _cand0 in _pool:
        lay = validate(room, base + ps, fast_hard=True)   # поиск: стоп на первом hard (профиль 17.08)
        hards = [v for v in lay.violations if v.severity is Severity.HARD]
        # СНЯТО 13.08: эвристика «кресло впереди дивана = занимает стену ТВ» рубила
        # ЗАКОННЫЕ схемы визави (кресло напротив через столик — канон face-to-face),
        # и сцены проваливались в круг без требования фокуса: медиа-зона упала с 223
        # до 118 сцен. Занятость стены носителем проверяет РЕАЛЬНАЯ проба ниже
        # (validate ловит ARMCHAIR_AT_TV_WALL), эвристика тут не нужна.
        # ПРОБА МЕСТА ПОД НОСИТЕЛЬ РАБОТАЕТ НА ВСЕХ КРУГАХ (регресс 13.08: с условием
        # `_FOCUS_LEVEL >= 1` на последнем круге проба не запускалась вовсе, и позиция
        # дивана выбиралась без оглядки на ТВ — медиа-зона упала с 223 до 118 сцен).
        # Круги отличаются ТОЛЬКО тем, можно ли принять позицию БЕЗ места носителю:
        # 2 — нужно место в оси, 1 — любое чистое, 0 — можно без него (но позиции с
        # местом всё равно предпочтительнее).
        if not hards and require_bearer is not None:
            # РЕЗЕРВ МЕСТА ПОД МЕДИА (регресс 11.08: блок занимал стену, и носитель
            # ТВ потом не вставал — 40 сцен): позиция блока принимается, только если
            # существует hard-чистая постановка носителя при ней
            from shapely.ops import unary_union as _uu
            occ = _uu([footprint(p) for p in ps if p.role != 'ковёр'])
            free2 = free.difference(occ)
            # ищем место носителю И у стен, И по диагонали в углу: с 10 позиций
            # «по прицелу» проба ошибалась и объявляла место занятым (set3-pylons,
            # владелец 12.08: «тут тоже влезла бы спокойно»)
            bcs = list(wall_candidates(room, require_bearer, free2)) \
                + list(_corner_candidates(room, require_bearer, free2))
            if require_bearer.role == 'тв-тумба':
                bcs += _window_candidates(room, require_bearer, free2)
                bcs += _between_windows_candidates(room, require_bearer, free2)
            # C-3 свода №11: у парного кандидата — СНАЧАЛА позиция носителя из Pair
            _pm_xy = getattr(_cand0, 'pair_media', None)
            if _pm_xy is not None:
                from .candidates import Candidate as _CandJ
                bcs.insert(0, _CandJ(placement=Placement(
                    role=require_bearer.role, x=_pm_xy[0], y=_pm_xy[1],
                    rot=_pm_xy[2], item=require_bearer), kind='wall',
                    note='joint-пара'))
            seat = ps[0]
            def _aim(c):
                r = math.radians(seat.rot)
                vx, vy = c.placement.x - seat.x, c.placement.y - seat.y
                n = math.hypot(vx, vy) or 1.0
                return -((math.sin(r) * vx + math.cos(r) * vy) / n)
            # ЦЕНТР ПРОВЕРЯЕМ ЗАРАНЕЕ (свод владельца 12.08): в круге «фокус обязателен»
            # позиция посадки принимается, только если носителю есть место В ОСИ взгляда.
            # Иначе ось упирается в дверь, и тумба уезжает на 90-150 см вбок.
            if _FOCUS_LEVEL >= 2:
                # круг «центр обязателен»: нет места В ОСИ — позиция посадки не годится
                bcs = _axis_filter(bcs, seat)
                if not bcs:
                    if first_hard is None:
                        first_hard = [('NO_CENTERED_BEARER', [require_bearer.role], None)]
                    continue
            ok_combo = False
            for bc in sorted(bcs, key=_aim)[:24]:
                lay2 = validate(room, base + ps + [bc.placement], fast_hard=True)
                if not any(v.severity is Severity.HARD for v in lay2.violations):
                    ok_combo = True
                    break
            if not ok_combo:
                # РЕЗЕРВ МЕСТА — ПРЕДПОЧТЕНИЕ, НЕ ЗАПРЕТ (11.08): раньше блок
                # отвергался целиком, и сцена оставалась без схемы (сет 112 и др.).
                # Теперь позиция уходит в резервный список: если ни одна не оставляет
                # места носителю, ставим лучшую из них, а медиа-зона честно
                # пропускается («не влезло — значит места нет»).
                terms_nb = score_layout(room, base + ps).terms
                for _pv in ps:
                    _pv.cand_topology = _topo    # Q12-3 v2: топология и на no-bearer ветке
                nb_variants.append((lexo_key(0, 0, terms_nb), ps))
                if first_hard is None:
                    first_hard = [('NO_ROOM_FOR_BEARER', [require_bearer.role], None)]
                continue
        if not hards:
            terms = score_layout(room, base + ps).terms
            for _pv in ps:
                # Q12-3 v2: топология выигравшего кандидата — на предметах, гейт
                # семантики якоря судит по ней (between_windows, door_jamb, …)
                _pv.cand_topology = _topo
            ok_variants.append((lexo_key(0, 0, terms), ps))
            continue
        if first_hard is None:
            first_hard = [(v.code, v.roles, v.value) for v in hards[:3]]
    # V3-B свода №9: счётчики поиска для объяснимости (runtime, не правила):
    # generated → fits-проба → полный validate → hard-чистых; топ-причина отказа
    if stats is not None:
        ok_variants.sort(key=lambda t: t[0])
        stats['generated'] = stats.get('generated', 0) + len(cands)
        stats['fits'] = stats.get('fits', 0) + len(scored)
        stats['validated'] = stats.get('validated', 0) + len(_pool)
        stats['hard_valid'] = stats.get('hard_valid', 0) + len(ok_variants)
        if first_hard and not stats.get('top_reject'):
            stats['top_reject'] = [[c, list(r), v] for c, r, v in first_hard]
        if ok_variants and stats.get('best_key') is None:
            stats['best_key'] = list(ok_variants[0][0])
    if ok_variants:
        ok_variants.sort(key=lambda t: t[0])
        if top > 1:
            return [v[1] for v in ok_variants[:top]]
        return ok_variants[0][1]
    if nb_variants and _FOCUS_LEVEL == 0:
        nb_variants.sort(key=lambda t: t[0])
        if top > 1:
            return [v[1] for v in nb_variants[:top]]
        return nb_variants[0][1]
    if os.environ.get('ZONES_DEBUG'):
        import sys
        print(f"ZDBG block[{b.anchor.role}+{len(b.rel)-1}] REJECT: "
              f"fits={len(scored)} top_hard={first_hard}", file=sys.stderr, flush=True)
    return None


def _zone_rules() -> dict:
    import json as _j
    _p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'rules', 'zones.json')
    global _ZR_CACHE
    try:
        return _ZR_CACHE
    except NameError:
        _ZR_CACHE = _j.load(open(_p, encoding='utf-8'))
        return _ZR_CACHE


def _window_back_candidates(room: Room, sofa_item: Item, free: Polygon) -> list:
    """П4 (MASTER-tv-sofa-pair, схема window_back): диван СПИНКОЙ К ОКНУ.

    Свод §17: не запрещать автоматически — allowed with checks. Чек-лист исполняют
    существующие правила validate: SOFA_BACK_ABOVE_SILL (спинка vs подоконник),
    RADIATOR (зазор конвекции — позицию отступаем на глубину радиатора), доступ.
    Здесь только генерация позиций: центр окна, спинка к нему, отступ от радиатора.
    """
    from .candidates import Candidate
    out = []
    rad_depth = max((r.depth_cm for r in room.radiators), default=0.0)
    setback = (rad_depth + 17.0) if rad_depth else 5.0
    for op in room.openings:
        if op.kind != 'window':
            continue
        # диван перекрывает ≤50% окна → окно шире половины дивана не обязательно,
        # но диван не шире окна вдвое (свод §17)
        rot = {'south': 0.0, 'north': 180.0, 'west': 90.0, 'east': 270.0}.get(op.wall)
        if rot is None:
            continue
        mid = op.offset_cm + op.width_cm / 2
        d_off = setback + sofa_item.d_cm / 2
        if op.wall == 'south':
            x, y = mid, d_off
        elif op.wall == 'north':
            x, y = mid, room.depth_cm - d_off
        elif op.wall == 'west':
            x, y = d_off, mid
        else:
            x, y = room.width_cm - d_off, mid
        p = Placement(role=sofa_item.role, x=x, y=y, rot=rot, item=sofa_item)
        fp = footprint(p)
        if free.intersection(fp).area < fp.area * 0.97:
            continue
        out.append(Candidate(placement=p, kind='wall', note='спинкой к окну',
                             topology='window_back'))
    return out


# V3-H свода №9: счётчики зеркал Г-дивана последнего вызова (debug/export)
LAST_MIRROR_STATS: dict | None = None
# V4-B2 свода №10: трейс лестницы посадки последнего прогона (пишет zones.py)
LAST_SEATING_SEARCH: dict | None = None
# V4-D свода №10: контракт осей — диагнозы столика и медиа последнего прогона
LAST_AXIS_DIAG: dict | None = None
LAST_MEDIA_AXIS: dict | None = None
MEDIA_MODE = ['single']     # P3 свода №12: 'single' | 'installation' — режим медиа гипотезы beam


def place_template(room: Room, group_id: str, items: list[Item], free: Polygon,
                   fixed: list[Placement] | None = None,
                   wall_only: bool = False,
                   enumerate_k: int | None = None,
                   shape_filter: tuple | None = None):
    """Разговорная зона блоком: лучший hard-чистый вариант или None (фолбэк beam).

    P2 свода №12: enumerate_k=K → вместо первого успешного варианта каскада вернуть
    СПИСОК до K hard-чистых вариантов блока (разные схемы/ранги позиций), в порядке
    каскада; пустой список = None. Гипотезы посадки для beam-драйвера
    (zones.solve_zoned_beam). enumerate_k=None — прежнее поведение 1-в-1."""
    if os.environ.get('LAYOUT_TEMPLATES', '1') == '0':
        return None
    _enum: list[list[Placement]] | None = [] if enumerate_k else None
    _enum_topo: list = []
    _shape_filter = tuple(shape_filter) if shape_filter else None   # Q3: семейство beam
    def _uniq_key(ps):
        return tuple(sorted((q.role, round(q.x), round(q.y), int(q.rot) % 360) for q in ps))
    # V3-H свода №9 (поправка рефери: зеркала НЕ first-clean): для Г-дивана ОБЕ
    # стороны решаются полностью, при обоюдной валидности выбор — существующим
    # лексикографическим ключом движка (score_layout → lexo_key), нового скора нет.
    _sofa_m = next((i for i in items if i.role == 'диван'), None)
    if _sofa_m is not None and getattr(_sofa_m, 'corner', False) \
            and not getattr(_sofa_m, 'corner_side_fixed', False):
        global LAST_MIRROR_STATS
        from .score import score_layout as _slm
        from .zones import lexo_key as _lkm
        _stats = {'left': {'generated': 0, 'hard_valid': 0},
                  'right': {'generated': 0, 'hard_valid': 0}, 'winner': None}
        _outs = []
        for _cl in (False, True):
            _side = 'left' if _cl else 'right'
            _stats[_side]['generated'] = 1
            _it2 = [i if i.role != 'диван' else _sofa_m.model_copy(
                update={'corner_left': _cl, 'corner_side_fixed': True})
                for i in items]
            _ps = place_template(room, group_id, _it2, free, fixed=fixed,
                                 wall_only=wall_only, enumerate_k=enumerate_k,
                                 shape_filter=shape_filter)
            if _ps:
                _stats[_side]['hard_valid'] = 1
                if enumerate_k:
                    for _one in _ps:          # P2: варианты обеих сторон — в общий пул
                        _key = _lkm(0, 0, _slm(room, list(fixed or []) + _one).terms)
                        _outs.append((_key, _side, _one))
                    continue
                _key = _lkm(0, 0, _slm(room, list(fixed or []) + _ps).terms)
                _outs.append((_key, _side, _ps))
        LAST_MIRROR_STATS = _stats
        if not _outs:
            return None
        _outs.sort(key=lambda t: t[0])
        _stats['winner'] = _outs[0][1]
        if enumerate_k:
            return [o[2] for o in _outs[:enumerate_k]]
        return _outs[0][2]
    by_role: dict[str, Item] = {}
    for it in items:
        by_role.setdefault(it.role, it)
    # СОСТАВ СТУПЕНИ — ИЗ ПАСПОРТА (план seating-template-ladder): в блок посадки идут
    # только required+optional роли группы (плюс клей: столик и ковёр всегда допустимы).
    # Раньше в схему затекали ВСЕ роли сета, и «лишние» лечились каскадом дропов.
    _grp_cfg = next((g for g in _zone_rules().get('seating_groups', [])
                     if g['id'] == group_id), None)
    if _grp_cfg is not None:
        _allowed = {r for r in _grp_cfg['roles'].get('required', [])} \
            | {r for r in _grp_cfg['roles'].get('optional', [])} \
            | {'столик', 'ковёр', 'приставной'} \
            | {'тв-тумба', 'стенка', 'камин'}   # ФОКУС: не член схемы, но проба места
                                                # под носитель обязана его видеть
        _allowed |= {r + ' 2' for r in list(_allowed)}
        by_role = {k: v for k, v in by_role.items()
                   if k in _allowed or k.split(' ')[0] in _allowed}
    # фокус зоны: медиа-носитель, а без него — камин (v2.5: камин-фокус легален)
    bearer = by_role.get('стенка') or by_role.get('тв-тумба')
    fireplace = by_role.get('камин')
    tv = bearer or fireplace
    # v2.5b: оба фокуса в составе → второй уходит на смежную стену (диагональ)
    second = fireplace if (bearer is not None and fireplace is not None) else None
    # каскад демоций: полный блок → без столика (бывают невозможные пары «длинный
    # столик × Г-диван», beam их тоже терял в missing) → без столика и ковра
    # СНАЧАЛА пробуем сохранить столик: зазор в hard-вилке 32–50 и боковой сдвиг
    # ≤15% ширины дивана (регресс 11.08: демоция роняла столик, и он оставался
    # без места — 25 сцен «столик не размещён»)
    sofa_w = (by_role.get('диван') or by_role.get('кресло'))
    _sh = (sofa_w.w_cm * 0.12) if sofa_w else 20.0
    # КАСКАД СХЕМ (правило атомарности: не выкидываем предмет «на ходу», а берём
    # ДРУГУЮ схему из библиотеки). Порядок отказов — от наименее ценного:
    # компаньоны (пуф → торшер → ковёр) → сдвиги/зазоры столика → без столика.
    tries = [(by_role, COFFEE_GAP, 0.0)]
    # КОВЁР НЕ ОТБРАСЫВАЕТСЯ (правило владельца, повторено 12.08: «диван без
    # коврика» — недопустимо, если ковёр есть в банке). Каскад жертвует только
    # пуфом и торшером; не влезло — берётся МЕНЬШИЙ шаблон, тоже с ковром.
    # ПОРЯДОК ДИЗАЙНЕРА (свод владельца 12.08): консоль ТВ важнее дополнительного
    # кресла. Если кресло занимает стену под носитель (ARMCHAIR_AT_TV_WALL), берём
    # МЕНЬШУЮ схему — без кресла; само кресло уйдёт в свою зону (чтение/тихая).
    # КАСКАД ДРОПОВ УДАЛЁН (план seating-template-ladder, владелец 13.08: «кресло —
    # только если есть в шаблоне; правильный шаблон подбирать, а не выкидывать
    # предметы»). Состав ступени фиксирован паспортом (`zones.json → seating_groups`);
    # не встал — solve_zoned спускается на СЛЕДУЮЩУЮ ступень лестницы. Здесь остаются
    # только законные ДОПУСКИ СХЕМЫ: зазор/сдвиг столика и поворот ковра.
    if 'ковёр' in by_role:
        _rg = by_role['ковёр']
        _rot_rug = Item(role=_rg.role, w_cm=_rg.d_cm, d_cm=_rg.w_cm, h_cm=_rg.h_cm,
                        name=_rg.name, item_id=_rg.item_id)
        tries.append(({**by_role, 'ковёр': _rot_rug}, COFFEE_GAP, 0.0))
        # НИКАКОГО «ужать предмет на 10-20%» (владелец 12.08): конверт −20/+10 —
        # это допуск ШАБЛОНА под реальный SKU, а не право менять габарит товара.
        # Придуманный размер = мебель, которой нет в каталоге, и неверная смета.
        # Не влезло — берём ДРУГОЙ шаблон (каскад ниже).
    if 'столик' in by_role:
        # ВЛАДЕЛЕЦ 17.08 (№31): «никаких допусков — не влез канон, берём другой канон». Каскад
        # оставляет ТОЛЬКО канонические зазоры внутри нормы distances.sofa_coffee_table [36,46]:
        # номинал COFFEE_GAP и «компактный» 36 (второй канон, паспорт gap_compact). Зазоры 32/48
        # (вне нормы) и сдвиг столика вдоль дивана (table_axis_shifted) из перебора УДАЛЕНЫ:
        # не встало — другая позиция/ступень лестницы, не деградированная схема.
        _gap_lo = float(_g('coffee_gap_compact_cm', 36.0))
        if abs(_gap_lo - COFFEE_GAP) > 0.5:
            tries.append((by_role, _gap_lo, 0.0))
        # (габариты столика НЕ подгоняем — см. правило выше про конверт слота)
        # СХЕМ БЕЗ СТОЛИКА В КАСКАДЕ НЕТ (владелец 13.08: «куда делся столик?»).
        # Столик — клей зоны (glue_rule паспорта); каскад жертвует пуфом, торшером,
        # креслом — но столик и ковёр неприкосновенны. Нет места столику — берётся
        # меньший состав ВОКРУГ него, а не зона без поверхности.
    variants = tries
    _enum_degraded: set = set()

    def _tol_tag(gap: float, shift: float) -> str:
        """Пометка допуска схемы (Codex 17.08): сдвиг столика вдоль дивана → +table_axis_shifted;
        нестандартный зазор → +gapNN. Канон (COFFEE_GAP, без сдвига) — без пометки; поворот ковра
        деградацией не считается (правило «длинной стороной вдоль дивана»)."""
        t = ''
        if shift:
            t += '+table_axis_shifted'
        if abs(gap - COFFEE_GAP) > 0.5:
            t += f'+gap{int(round(gap))}'
        return t
    # ЭФФЕКТИВНАЯ группа (11.08): выбранная группа может требовать роль, которой в
    # сете нет (sofa_armchair без кресла) — тогда блок не собирался и сцена уходила
    # в поштучный фолбэк. Понижаем группу до реально доступного состава.
    _av = set(by_role)
    if group_id in ('sofa_2armchairs', 'sofa_4armchairs') and 'кресло 2' not in _av:
        group_id = 'sofa_armchair'
    if group_id in ('sofa_armchair', 'sectional_armchair') and 'кресло' not in _av \
            and 'пуф' not in _av:
        # Codex 21.08 (аудит Юли №14–16): прямой диван без компаньонов — это
        # sofa_solo, а НЕ compact_sectional: sectional по паспорту «углов», и
        # понижение сюда рисовало «секционал» прямым диваном
        group_id = 'sofa_solo'
    if group_id in ('sofa_facing_sofa', 'sofa_loveseat', 'sofa_loveseat_2armchairs',
                    'two_sofas_2armchairs') and 'диван 2' not in _av:
        group_id = 'sofa_2armchairs' if 'кресло 2' in _av else (
            'sofa_armchair' if 'кресло' in _av else 'sofa_solo')
    # P3 свода №12: формы посадки — ИЗ ПАСПОРТА (rules/zones.json seating_groups[].shapes),
    # словарь в коде был второй истиной («паспорта богаче runtime», Кодекс §2 п.3)
    shapes = {g['id']: list(g.get('shapes') or ['default'])
              for g in _zone_rules().get('seating_groups', [])}.get(group_id, ['default'])
    # C1 (M-C, свод №5): квадратная комната — симметричные ЦЕНТРАЛЬНЫЕ схемы первыми
    # (список приоритета — паспорт contour_features, выбор схемы = первая вставшая)
    from .invariants import TEMPLATES as _CT
    from .room_map import contour_features as _cf
    if _cf(room)[2]:
        _prio = _CT.get('contour_features', {}).get('square_scheme_priority', [])
        shapes = [s for s in _prio if s in shapes] + [s for s in shapes if s not in _prio]
    if _shape_filter is not None:
        shapes = [sh for sh in shapes if sh in _shape_filter]
        if not shapes:
            return None
    # ФОКУС-СТЕНА ОБЯЗАТЕЛЬНА (свод владельца 12.08: «стена напротив дивана не должна
    # быть пустой»). КРУГ 1 — принимаем только те позиции посадки, при которых носителю
    # ТВ остаётся чистое место. КРУГ 2 (если ни одна схема не ужилась) — ставим посадку
    # без этого требования: лучше зона, чем пустая сцена, и носитель честно уходит в
    # «не использовано».
    # ВНУТРИ каждого круга — прежние два прохода: сперва схемы с НАСТОЯЩИМ столиком,
    # затем «пуф вместо столика» (104 сцены оставались без столика, 12.08).
    global _FOCUS_LEVEL
    _centered_fails = 0            # V4-D1: счётчик отказов центрированных вариантов
    _rounds = (2, 1, 0) if (bearer is not None
                            and os.environ.get('LAYOUT_FOCUS_MANDATORY', '1') != '0') \
        else (0,)
    class _EnumFull(Exception):
        pass
    try:
     for _lvl in _rounds:
      _FOCUS_LEVEL = _lvl
      try:
        for _pass in (0, 1):
          _shapes = [sh for sh in shapes if (sh == 'pouf_table') == bool(_pass)]
          if not _shapes:
              continue
          for br, _gap, _shift in variants:
            for shape in _shapes:
              b = build_block(group_id, br, variant=shape, table_gap=_gap,
                              table_shift=_shift)
              if b is None or len(b.rel) < 2:
                  continue
              cands = list(wall_candidates(room, b.anchor, free))
              cands += _window_back_candidates(room, b.anchor, free)   # П4: спинкой к окну
              # v2.10: в просторных комнатах посадка может «плавать» (зонирование
              # спинкой); тыл за спинкой проверят passage/sliver-чеки validate
              # «плавающие» позиции: в просторных комнатах — всегда; в ГЛУБОКИХ
              # (глубина по оси взгляда больше верха ТВ-вилки) — тоже: диван у стены
              # даёт SOFA_TV_DIST на всей противоположной стене, и медиа-зона гибла
              # (13.08, 10 сцен long: комната 475 при вилке до ~370). Отход дивана
              # от стены + столовая за спинкой — канонное решение для глубоких комнат.
              # L1 (large-room-mode): единый источник режима — room_map.room_mode;
              # прежний двойник max(сторона)>430 удалён (сверка конфликтов)
              from .room_map import room_mode as _rm
              _deep = _rm(room) == 'large'
              if (room.width_cm * room.depth_cm > 40 * 10_000 or _deep) \
                      and not wall_only:
                  cands += list(middle_candidates(room, b.anchor, free,
                                                  limit=10 if _deep else 6))
              if _deep and not wall_only:
                  # П1 (MASTER-tv-sofa-pair): кандидаты дивана — из генератора ПАР
                  # «медиа-блок × блок посадки» (WallScore, свод владельца §3–7).
                  # Прежние tv_range-кандидаты остаются фолбэком.
                  cands += _pair_sofa_candidates(room, b.anchor, free, tv)
                  cands += _tv_range_candidates(room, b.anchor, free, tv=tv)
              if _enum is not None:
                  # P2 свода №12: перечисление — top-K позиций этой схемы, каскад
                  # продолжается, пока не наберём enumerate_k уникальных вариантов
                  _pss = _best_block(room, b, free, cands, tv=tv, fixed=fixed,
                                     second_focus=second, require_bearer=bearer,
                                     top=max(2, int(enumerate_k)))
                  for _one in (_pss or []):
                      _kk = _uniq_key(_one)
                      if _kk in {_uniq_key(e) for e in _enum}:
                          continue
                      # КВОТА РАЗНООБРАЗИЯ (Кодекс §3 п.3): по одному варианту на
                      # топологию (схема × стена/rot дивана) — иначе K соседних
                      # позиций одной формы, а гипотезы «другая стена / другая
                      # схема / другой состав» не попадают в beam (владелец №16)
                      _sofa1 = next((q for q in _one if q.role.split(' ')[0] == 'диван'),
                                    _one[0])
                      _topo = (shape, int(_sofa1.rot) % 360, round(_sofa1.x / 120),
                               round(_sofa1.y / 120))
                      if _topo in {e[0] for e in _enum_topo}:
                          continue
                      _enum_topo.append((_topo,))
                      _variant0 = shape + _tol_tag(_gap, _shift)
                      # Codex 17.08 (владелец №31): деградированных вариантов (сдвиг/нестандартный
                      # зазор) — не более ОДНОГО на форму в перечислении; канон — все топологии
                      if _tol_tag(_gap, _shift):
                          if shape in _enum_degraded:
                              continue
                          _enum_degraded.add(shape)
                      for _pv in _one:
                          _pv.tpl_variant = _variant0
                      _enum.append(_one)
                      if len(_enum) >= enumerate_k:
                          raise _EnumFull      # базовый набор полон — к хвосту (media-квота), не return
                  continue
              ps = _best_block(room, b, free, cands, tv=tv, fixed=fixed,
                               second_focus=second, require_bearer=bearer)
              if ps is None and not _shift:
                  _centered_fails += 1      # V4-D1: centered-провалы — в трейс
              if ps is not None:
                  # V4-D1 (свод №10): сдвиг столика — ЯВНЫЙ вариант, не тихий default.
                  # Сдвиговые варианты идут в каскаде ПОСЛЕ центрированных, поэтому
                  # успех со сдвигом = «centered hard-invalid» по построению.
                  global LAST_AXIS_DIAG
                  _variant = shape + _tol_tag(_gap, _shift)
                  LAST_AXIS_DIAG = {'table': {
                      'shift_cm': round(_shift, 1), 'variant': _variant,
                      'centered_rejects': _centered_fails,
                      'reason': ('centered_hard_invalid' if _shift else None)}}
                  for _pv in ps:            # V3-H: identity схемы в экспорт
                      _pv.tpl_variant = _variant
                  if os.environ.get('ZONES_DEBUG'):
                      import sys as _s
                      print(f'ZDBG посадка принята: круг фокуса={_lvl} схема={shape} '
                            f'состав={sorted(br)}', file=_s.stderr, flush=True)
                  return ps
      finally:
        _FOCUS_LEVEL = 0
    except _EnumFull:
        _FOCUS_LEVEL = 0
    if _enum:
        # Q3 свода №13: КВОТА media-aware формы — гипотеза с креслом «к ТВ» обязана
        # попасть в beam, даже если каскад набрал enumerate_k раньше (иначе media-формы
        # в конце каскада никогда не перебираются). Помечено tpl_variant.
        _MEDIA_SHAPES = ('media_parallel', 'media_half', 'media_bridge')
        if not any(getattr(e[0], 'tpl_variant', '').split('+')[0] in _MEDIA_SHAPES for e in _enum)                 and any(sh in _MEDIA_SHAPES for sh in shapes):
            _saved = list(_enum)
            _enum.clear()
            _extra_k = 1
            try:
                for _lvl2 in _rounds:
                    _FOCUS_LEVEL = _lvl2
                    for br, _gap, _shift in variants:
                        for shape in [sh for sh in shapes if sh in _MEDIA_SHAPES]:
                            b = build_block(group_id, br, variant=shape, table_gap=_gap,
                                            table_shift=_shift)
                            if b is None or len(b.rel) < 2:
                                continue
                            cands = list(wall_candidates(room, b.anchor, free))
                            cands += _window_back_candidates(room, b.anchor, free)
                            _pss = _best_block(room, b, free, cands, tv=tv, fixed=fixed,
                                               second_focus=second, require_bearer=bearer, top=1)
                            if _pss:
                                _one = _pss if isinstance(_pss[0], Placement) else _pss[0]
                                for _pv in _one:
                                    _pv.tpl_variant = shape + _tol_tag(_gap, _shift)
                                _saved.append(_one)
                                raise StopIteration
            except StopIteration:
                pass
            finally:
                _FOCUS_LEVEL = 0
            _enum.extend(_saved)
        return _enum
    return None


def place_dining(room: Room, items: list[Item], free: Polygon, usable_m2: float,
                 fixed: list[Placement] | None = None,
                 classes: tuple = ('island', 'edge')) -> list[Placement] | None:
    """Столовая зона блоком: стол + стулья по band (малые комнаты 2, средние 4,
    просторные 6 — «заранее продумать» владельца). Кандидаты позиции — у стены и
    свободные (остров); проходы/отодвигание проверит validate на объединении."""
    if os.environ.get('LAYOUT_TEMPLATES', '1') == '0':
        return None
    by_role: dict[str, Item] = {}
    for it in items:
        by_role.setdefault(it.role, it)
    # число стульев = сколько ЕСТЬ в сете (до предела band): лишние стулья иначе
    # оставались без зоны (экзамен 11.08: «стул 4» пропущен в 125 сценах)
    have_chairs = sum(1 for it in items if it.role == 'стул' or it.role.startswith('стул '))
    # мест по площади — из паспорта (пакет A свода №8: паспорт = source of truth)
    cap = dining_seats_cap(usable_m2)
    max_chairs = max(2, min(have_chairs, cap))
    # S4 (small-свод §14): каскад масштаба — если полный состав не встал, пробуем
    # столовую на 2 места, прежде чем отказаться (living не ломаем ради стола)
    _chair_steps = [max_chairs] + ([2] if max_chairs > 2 else [])
    # П5 (MASTER-tv-sofa-pair, свод §10): проверяется ЭКСПЛУАТАЦИОННАЯ зона стола —
    # прямоугольник «стол + 90 см со стороны посадок» (R&B), а не голый габарит.
    # Реализация — расширенный футпринт стола в блоке: build_dining уже ставит стулья,
    # а validate меряет отодвигание; здесь фильтр очевидно-тесных мест до перебора.
    # Свод №7 S3 (веб-канон, вердикт владельца): обеденная группа НЕ заходит на
    # ковёр посадки — у столовой свой пол/ковёр; фильтр на уровне свободного
    # полигона (кандидаты на ковре не предлагаются, атомарность не страдает)
    _rug_fx = next((p for p in (fixed or []) if p.role == 'ковёр'), None)
    if _rug_fx is not None:
        free = free.difference(footprint(_rug_fx))
    # пакет B свода №8: объяснимость выбора — заполняем диагноз по ходу каскада
    global LAST_DINING_DIAG
    _tbl_it = by_role.get('стол обеденный')
    diag = {'mode': None, 'island_feasible': (
                dining_island_feasible(_tbl_it, free) if _tbl_it is not None else False),
            'island_reject': None, 'fallback_reason': None,
            'envelope_cm': dining_envelope_cm(),
            # V3-B свода №9: счётчики поиска по классам (runtime, не правила)
            'search': {'full_island': {}, 'compact_island': {}, 'edge': {}}}
    LAST_DINING_DIAG = diag
    # Пакет C свода №8 (v2 §3/§6.2): КАСКАД КЛАССОВ как приоритет кандидатов ПОСЛЕ
    # hard, не вес: FULL_ISLAND (паспортный envelope со всех сторон; кандидаты — и от
    # генератора, и из пробы) → COMPACT_ISLAND (остров без полного envelope) → EDGE.
    for _nch in _chair_steps:
        b_all = build_dining(by_role, _nch, sides='all') if 'island' in classes else None
        if 'island' in classes and (b_all is None or len(b_all.rel) < 2):
            diag['island_reject'] = diag['island_reject'] or 'no_island_block'
        if b_all is not None and len(b_all.rel) >= 2:
            _mids = list(middle_candidates(room, b_all.anchor, free, limit=8))
            _mids += _island_probe_candidates(b_all.anchor, free)
            _full = [c for c in _mids if dining_envelope_ok(c.placement, free, 'all')]
            ps = None
            for _cands, _klass in ((_full, 'full_island'), (_mids, 'compact_island')):
                if not _cands:
                    continue
                ps = _best_block(room, b_all, free, _cands, tv=None, fixed=fixed,
                                 stats=diag['search'][_klass])
                if ps is not None:
                    _tbl_p = next((p for p in ps if p.role == 'стол обеденный'), None)
                    diag['mode_path'] = ('full_island' if _tbl_p is not None and
                                         dining_envelope_ok(_tbl_p, free, 'all')
                                         else 'compact_island')
                    # V3-E: экспортный mode — фактическая топология постановки
                    diag['mode'] = (dining_mode_topology(_tbl_p, free)
                                    if _tbl_p is not None else diag['mode_path'])
                    return ps
            diag['island_reject'] = 'island_candidates_failed'
        if 'edge' not in classes:
            continue
        # Q6c свода №13: КАСКАД — island → (round_compact, Q6d) → EDGE_NOOK → голый edge.
        # Уголок пробуется ДО пристенного стола: банкетка к стене даёт посадку с двух сторон,
        # а «стол у стены» — вынужденная деградация (владелец: «стол придвинут к стене?»).
        # Требует комплекта (банкетка с caps ≥2 мест + dining_seat_capable) — иначе пропуск.
        if by_role.get('банкетка') is not None:
            _nook = place_edge_nook(room, items, free, fixed=fixed)
            if _nook is not None:
                diag['mode_path'] = 'edge_nook'
                diag['mode'] = 'edge_nook'
                diag['nook'] = dict(NOOK_DIAG)
                diag['fallback_reason'] = ('island_infeasible' if not diag['island_feasible']
                                           else diag['island_reject'] or 'island_place_failed')
                return _nook
            diag['nook'] = dict(NOOK_DIAG)      # причина отказа уголка — в сертификат столовой
        b_front = build_dining(by_role, _nch, sides='front')
        if b_front is not None:
            ps = _best_block(room, b_front, free,
                             list(wall_candidates(room, b_front.anchor, free)),
                             tv=None, fixed=fixed, stats=diag['search']['edge'])
            if ps is not None:
                diag['mode_path'] = 'edge'
                _tbl_pe = next((p for p in ps if p.role == 'стол обеденный'), None)
                diag['mode'] = (dining_mode_topology(_tbl_pe, free)
                                if _tbl_pe is not None else 'edge')
                diag['fallback_reason'] = (
                    'island_infeasible' if not diag['island_feasible']
                    else diag['island_reject'] or 'island_place_failed')
                return ps
    return None


STORAGE_ROLES = ('шкаф', 'стеллаж', 'стеллаж 2', 'витрина', 'комод')


def build_storage(by_role: dict[str, Item], max_items: int = 3,
                  ceiling_cm: float | None = None) -> Block | None:
    """ЗОНА ХРАНЕНИЯ (v3, правило владельца 11.08 «зона может быть из одного
    предмета»): ряд вдоль стены из 1–3 предметов, фасады в линию, зазор 8 см.
    Веб-свод: открытые полки дают вертикаль, комод — вес у пола; пара ламп по
    бокам комода задаёт симметрию (лампы ставит рендер на поверхность)."""
    items = [by_role[r] for r in STORAGE_ROLES if r in by_role][:max_items]
    if not items:
        return None
    items.sort(key=lambda i: -i.w_cm)
    # D5 (M-D, свод №5): высокий потолок — вертикальный масштаб: высокий корпус
    # якорем ряда (числа — zones.json wall_preferences.high_ceiling; сцены без
    # ceiling_cm правило не трогает)
    if ceiling_cm is not None:
        from .zones import zone_rules as _zr5
        _cfg_hc = _zr5().get('wall_preferences', {}).get('high_ceiling', {})
        if ceiling_cm >= float(_cfg_hc.get('min_ceiling_cm', 300)):
            _tall = float(_cfg_hc.get('tall_h_cm', 190))
            items.sort(key=lambda i: (-(i.h_cm >= _tall), -i.w_cm))
    anchor = items[0]
    b = Block(anchor)
    x = anchor.w_cm / 2
    for it in items[1:]:
        # глубины разные — фасады в линию: сдвиг по y на полуразность глубин
        b.add(it, x + 8 + it.w_cm / 2, (anchor.d_cm - it.d_cm) / 2, 0.0)
        x += 8 + it.w_cm
    plant = by_role.get('кашпо')
    if plant is not None:
        # живой акцент у торца ряда (веб-свод 11.08: растение у стеллажа/полок).
        # ПРОСВЕТ 30 см (замечание владельца 12.08: кашпо в 3 см читалось как
        # «загорожено стеллажом») — то же число, что в межзонном правиле декора.
        b.add(plant, x + _DECOR_GAP_CM + plant.w_cm / 2,
              (anchor.d_cm - plant.d_cm) / 2, 0.0)
    return _valid(b, 'storage')


def place_storage(room: Room, items: list[Item], free: Polygon,
                  fixed: list[Placement] | None = None) -> list[Placement] | None:
    """ЗОНА ХРАНЕНИЯ — правила владельца (12.08, замечание по set4-base):
    НЕ БОЛЕЕ ДВУХ предметов в зоне и НЕ БОЛЕЕ ДВУХ зон хранения на гостиную;
    вторая зона — на ДРУГОЙ стене (стеллаж+витрина+комод в один ряд по одной стене
    читаются как склад). Каскад длины ряда: 2 предмета → каждый по одному."""
    if os.environ.get('LAYOUT_TEMPLATES', '1') == '0':
        return None
    by_role: dict[str, Item] = {}
    for it in items:
        by_role.setdefault(it.role, it)
    have = [r for r in STORAGE_ROLES if r in by_role]
    if not have:
        return None
    # стены, уже занятые хранением: вторую зону туда не ставим
    _busy = {_wall_of(room, p) for p in (fixed or [])
             if _base_role(p.role) in STORAGE_ROLES}
    tries: list[dict[str, Item]] = []
    if len(have) >= 2:
        for i in range(len(have) - 1):
            tries.append({r: by_role[r] for r in have[i:i + 2]})
    tries += [{r: by_role[r]} for r in have]         # одиночные — последним шансом
    # L5 (large-room): узкая полоса за спинкой (машина R: passage_plus_shallow_storage)
    # предпочитает НЕГЛУБОКОЕ хранение — глубже 40 см туда не ставим
    _seat_fx = next((p for p in (fixed or []) if p.role.split(' ')[0] == 'диван'), None)
    if _seat_fx is not None:
        from .zones import _behind_decision
        if _behind_decision(room, _seat_fx) == 'passage_plus_shallow_storage':
            _shallow = [t for t in tries if all(v.d_cm <= 40 for v in t.values())]
            tries = _shallow + [t for t in tries if t not in _shallow]
    # Q6e свода №13: КОНСОЛЬ ЗА ДИВАНОМ — приоритетная постановка неглубокого хранения, когда
    # диван «плавает» и за спинкой остаётся полоса (машина R: passage_plus_shallow_storage).
    # Правила — данные `zones.json → subtypes.console` (H&G/BHG: высота ≤ спинки+5, длина 0.5–0.75
    # дивана, глубина ≤40, после консоли остаётся маршрут). Не встало — обычный путь ниже.
    _cons = place_console_behind_sofa(room, items, free, fixed=fixed)
    if _cons is not None:
        return _cons
    for br in tries:
        b = build_storage(br, max_items=len(br), ceiling_cm=room.ceiling_cm)
        if b is None:
            continue
        # Q12-4: УГЛОВАЯ БАШНЯ (`storage.corner_tower`) — узкий высокий корпус ВПЛОТНУЮ К ОДНОЙ
        # ИЗ СТЕН угла (не по диагонали: так требует паспорт и практика — фасад остаётся
        # доступен). Пробуем первой для одиночного узкого корпуса: угол — «мёртвая» площадь,
        # которую периметр обычно не берёт.
        if len(br) == 1:
            _tw = next(iter(br.values()))
            _ct = _corner_tower_candidates(room, b.anchor, free)
            if _ct:
                ps = _best_block(room, b, free, _ct, tv=None, fixed=fixed)
                if ps is not None:
                    for _p in ps:
                        _p.tpl_variant = 'corner_tower'
                        if (_p.item.h_cm or 0) >= float(_TALL_ANCHOR_H_CM):
                            # высокая мебель у стены — требование монтажа, а не геометрии
                            _p.installation_requirement = 'wall_anchor'
                    return ps
        for _avoid in ((True, False) if _busy else (False,)):
            cands = wall_candidates(room, b.anchor, free)
            if _avoid:                    # сперва ищем СВОБОДНУЮ стену
                cands = [c for c in cands if _wall_of(room, c.placement) not in _busy]
            ps = _best_block(room, b, free, cands, tv=None, fixed=fixed)
            if ps is not None:
                return ps
    return None


_TALL_ANCHOR_H_CM = 150.0   # выше — крепление к стене обязательно (CPSC Anchor It: опрокидывание)


def _corner_tower_candidates(room: Room, item: Item, free: Polygon) -> list:
    """Кандидаты «угловая башня» (Q12-4, паспорт storage.corner_tower): корпус СТОИТ ВДОЛЬ одной
    из стен угла, прижатый к смежной — не по диагонали. Фасад смотрит в комнату, доступ спереди
    проверит `_best_block`/validate. Диагональную постановку сюда не берём: паспорт и практика
    требуют корпус вдоль стены (Codex 19.08)."""
    from .candidates import Candidate
    out = []
    W, D = room.width_cm, room.depth_cm
    w, d = item.w_cm, item.d_cm
    pad = 5.0
    for cx, cy in ((0, 0), (W, 0), (0, D), (W, D)):
        for wall, rot in ((('south', 0.0) if cy == 0 else ('north', 180.0)),
                          (('west', 90.0) if cx == 0 else ('east', 270.0))):
            if wall in ('south', 'north'):          # корпус вдоль горизонтальной стены угла
                x = (pad + w / 2) if cx == 0 else (W - pad - w / 2)
                y = (pad + d / 2) if cy == 0 else (D - pad - d / 2)
            else:                                    # вдоль вертикальной стены угла
                x = (pad + d / 2) if cx == 0 else (W - pad - d / 2)
                y = (pad + w / 2) if cy == 0 else (D - pad - w / 2)
            p = Placement(role=item.role, x=x, y=y, rot=rot, item=item)
            fp = footprint(p)
            if free.intersection(fp).area >= fp.area * 0.97:
                out.append(Candidate(p, 'corner', 'угловая башня'))
    return out


CONSOLE_DIAG: dict = {}   # Q6e: почему консоль за диваном (не) встала


def _zone_rules_zn() -> dict:
    from .zones import zone_rules as _zr
    return _zr()


def place_console_behind_sofa(room: Room, items: list[Item], free: Polygon,
                              fixed: list[Placement] | None = None) -> list[Placement] | None:
    """Q6e свода №13: низкая консоль ЗА СПИНКОЙ floating-дивана (H&G/BHG «sofa table»):
    высота ≤ спинки дивана +5, глубина ≤ max_d_cm, длина 0.5–0.75 длины дивана; ставится
    вплотную к спинке по центру, маршрут за ней проверяет validate (проходы).
    Кандидат — из имеющегося хранения (комод/тумба/стеллаж): отдельной роли «консоль»
    в каталоге нет, это СПОСОБНОСТЬ узкого низкого корпуса (Q6a shallow_storage_capable)."""
    CONSOLE_DIAG.clear()
    if os.environ.get('LAYOUT_TEMPLATES', '1') == '0':
        return None
    sofa = next((p for p in (fixed or []) if p.role.split(' ')[0] == 'диван'), None)
    if sofa is None or sofa.item is None:
        CONSOLE_DIAG['reject'] = 'no_sofa'
        return None
    from .zones import _behind_decision
    if _behind_decision(room, sofa) != 'passage_plus_shallow_storage':
        CONSOLE_DIAG['reject'] = 'behind_strip_not_for_storage'
        return None
    cfg = (_zone_rules_zn().get('group_scheme') or {}).get('console') or {}
    max_d = float(cfg.get('max_d_cm', 40))
    lo, hi = (cfg.get('length_vs_sofa_soft') or [0.5, 0.75])
    back_h = float(sofa.item.h_cm or 85) + 5.0
    # ТОЛЬКО НАСТОЯЩИЙ СТОЛ-КОНСОЛЬ (решение владельца 21.08, аудит Юли №46 раунд 2):
    # корпус с ящиками/створками (комод/тумба/стеллаж) за диваном отклонён — «это не
    # консоль». Признак — способность `sofa_console_capable` (тегинг каталога);
    # предметов с ней в фиде пока нет → схема спит (паспорт storage.console_behind_sofa)
    # и оживёт сама с появлением товара.
    cands_it = [it for it in items
                if bool((it.caps or {}).get('sofa_console_capable'))
                and it.d_cm <= max_d and (it.h_cm or 999) <= back_h
                and lo * sofa.item.w_cm <= it.w_cm <= hi * sofa.item.w_cm * 1.34]   # верх — до 1.0 дивана
    if not cands_it:
        CONSOLE_DIAG['reject'] = 'no_console_capable_sku'
        CONSOLE_DIAG['limits'] = {'max_d_cm': max_d, 'max_h_cm': back_h,
                                  'w_range': [round(lo * sofa.item.w_cm), round(sofa.item.w_cm)]}
        return None
    cands_it.sort(key=lambda it: -it.w_cm)          # длиннее — ближе к канону «≈2/3 дивана»
    r = math.radians(sofa.rot)
    for it in cands_it[:3]:
        # позиция: вплотную за спинкой, по центру дивана (спинка — противоположно фасаду)
        off = sofa.item.d_cm / 2 + it.d_cm / 2 + 2.0
        cx = sofa.x - math.sin(r) * off
        cy = sofa.y - math.cos(r) * off
        p = Placement(role=it.role, x=cx, y=cy, rot=(sofa.rot + 180) % 360, item=it)
        p.tpl_id = 'storage'
        # ПРОПОРЦИЯ (Codex 21.08, аудит Юли №46): канон — консоль ≥2/3 длины дивана (H&G);
        # 0.5–0.67 остаётся ЯВНО деградированным вариантом (+short), не тихой нормой
        _pref = float(cfg.get('length_vs_sofa_preferred_min', 2 / 3))
        p.tpl_variant = 'console_behind_sofa' + \
            ('' if it.w_cm >= _pref * sofa.item.w_cm else '+short')
        if free.intersection(footprint(p)).area < footprint(p).area * 0.97:
            CONSOLE_DIAG['reject'] = 'no_space_behind'
            continue
        # R8 (19.08, Codex): паспорт обещает МАРШРУТ за консолью — значит он обязан остаться.
        # Прежде консоль принималась в полосе от 91 см, и за ней оставалось ~49 см.
        if bool(cfg.get('route_after_console_required', True)):
            from .back_gap import strip_behind_depth
            _left = strip_behind_depth(room, sofa, extra=[p])
            _rmin = float(((_zone_rules_zn().get('routes') or {}).get('route_min_cm')) or 91)
            if _left is not None and _left + 0.5 < _rmin:
                CONSOLE_DIAG['reject'] = 'no_route_after_console'
                CONSOLE_DIAG['route_left_cm'] = _left
                continue
        if not _inter_zone_ok(room, [p], list(fixed or [])):
            CONSOLE_DIAG['reject'] = 'inter_zone'
            continue
        lay = validate(room, list(fixed or []) + [p])
        if any(v.severity is Severity.HARD for v in lay.violations):
            CONSOLE_DIAG['reject'] = 'hard'
            CONSOLE_DIAG['hard'] = [v.code for v in lay.violations if v.severity is Severity.HARD][:3]
            continue
        CONSOLE_DIAG.update({'placed': it.role, 'w': it.w_cm, 'd': it.d_cm, 'h': it.h_cm,
                             'sofa_w': sofa.item.w_cm, 'share': round(it.w_cm / sofa.item.w_cm, 2)})
        return [p]
    return None


def build_reading_pair(by_role: dict[str, Item]) -> Block | None:
    """Q12 (аудит канонов 19.08): ПАРА кресел у архитектурного якоря (окно/эркер) с общей
    поверхностью между ними. Практика («кресло ИЛИ ПАРА кресел у окна» — 28%) знает обе формы,
    у нас была только одиночная. Кресла — рядом, лицом в комнату; поверхность между ними
    в пределах вытянутой руки (иначе SERVICE_SURFACE у обоих)."""
    a1 = by_role.get('кресло') or by_role.get('кресло 3')
    a2 = by_role.get('кресло 2') or by_role.get('кресло 4')
    if a1 is None or a2 is None:
        return None
    surf = by_role.get('приставной') or by_role.get('столик 2')
    b = Block(a1)
    gap = (surf.w_cm + 2 * 10.0) if surf is not None else 24.0
    dx = a1.w_cm / 2 + gap + a2.w_cm / 2
    b.add(a2, dx, 0.0, 0.0)
    if surf is not None:
        b.add(surf, dx / 2, 0.0, 0.0)
    return _valid(b, 'reading', variant='pair_anchor')


def build_reading(by_role: dict[str, Item], allow_solo: bool = False,
                  corner: bool = False, lamp_side: int = +1,
                  lamp_forward: bool = False) -> Block | None:
    """v2.6: уголок чтения — кресло + торшер за плечом (30–40 от спинки, сбоку)
    + приставной у другого подлокотника (≤15).

    Q10b (19.08): `allow_solo` — У ОКНА кресло самодостаточно («кресло у окна» — узнаваемая
    композиция практики, 28% проектов); у произвольной стены соло-кресло по-прежнему запрещено
    (читается как забытый предмет)."""
    arm = by_role.get('кресло 3') or by_role.get('кресло')
    lamp, side = by_role.get('торшер'), by_role.get('приставной')
    ott = by_role.get('пуф')
    # E3 (свод №4, residual 130-180 → nook): аксессуаром нука может быть и пуф-
    # оттоманка перед креслом — торшер в вытянутых малых часто занят посадкой
    # (sofa_lamp), и нук не собирался при живом кресле+пуфе в банке
    if arm is None or (not allow_solo and lamp is None and side is None and ott is None):
        return None
    b = Block(arm)
    if lamp is None and side is None and ott is not None:
        b.add(ott, 0.0, arm.d_cm / 2 + ott.d_cm / 2 + 10, 0.0)
    _ls = +1 if lamp_side >= 0 else -1
    if lamp is not None:
        # свет ЗА ПЛЕЧОМ, а не за спинкой — ВЕЗДЕ, включая угол (нормы 20.08 BenQ/Homebaa
        # + аудит Юли №27/№31 и LRC RPI: источник сбоку-чуть-сзади, свет через плечо на
        # страницу; 46–90 см от центра посадки). Прежняя угловая раскладка нарочно ставила
        # торшер В ВЕРШИНУ строго за спинкой — читалось «торшер за креслом» и не светило.
        # `lamp_side` — у какого плеча (зеркала перебирает плейсер), `lamp_forward` —
        # эркер: свет уходит к УСТЬЮ ниши (сбоку-впереди), иначе упирается в окно
        # наружной кромки (WINDOW_BLOCKED — разбор 21.08).
        _ly = (arm.d_cm / 4) if lamp_forward else (-arm.d_cm / 4)
        b.add(lamp, _ls * (arm.w_cm / 2 + lamp.w_cm / 2 + LAMP_GAP), _ly, 0.0)
    if side is not None:
        # приставной — у ПЕРЕДНЕЙ половины подлокотника (туда ложится рука), зазор 5–10 см;
        # раньше столик стоял по центру кресла и читался как «поставить некуда» (владелец 20.08).
        # Сторона — противоположная торшеру (оба у одного подлокотника пересекаются).
        _sg = float((_oc('dynamic/extras/side_table/gap_from_chair_cm', [5, 10]) or [5, 10])[1])
        b.add(side, -_ls * (arm.w_cm / 2 + side.w_cm / 2 + _sg),
              arm.d_cm / 2 - side.d_cm / 2 - 4.0, 0.0)
    return _valid(b, 'reading', variant='window_anchor' if allow_solo and len(b.rel) == 1 else None)


def build_fireplace_anchor(by_role: dict[str, Item], fireplace: Item,
                           side: int = -1) -> Block | None:
    """Схема `reading.fireplace_anchor` (владелец 19.08: канон «ОДНО кресло + камин» существует
    наравне с парой): кресло сбоку от очага, развёрнуто к огню на угол `fireplace.rules
    .chair_angle_deg`, вне зоны безопасности портала. Свет/поверхность — опциональны.
    Пара кресел по сторонам — это `quiet.fireplace_flank`, другая схема."""
    arm = by_role.get('кресло 3') or by_role.get('кресло')
    if arm is None:
        return None
    b = Block(fireplace)
    _rules = (_zone_rules_tpl().get('zones', {}).get('fireplace', {}).get('rules') or {})
    ang = float(_rules.get('chair_angle_deg', 45))
    off = fireplace.w_cm / 2 + 45 + arm.w_cm / 2
    fwd = float((_rules.get('safety_zone_cm') or [61, 91])[0]) + arm.d_cm / 2 + 20
    b.add(arm, side * off, fwd, 180.0 - side * -ang if side < 0 else 180.0 + ang)
    side_t = by_role.get('приставной') or by_role.get('столик 2')
    if side_t is not None:
        # поверхность — у ВНЕШНЕГО подлокотника, в пределах вытянутой руки
        _ca, _sa = abs(math.cos(math.radians(ang))), abs(math.sin(math.radians(ang)))
        _e = (arm.w_cm * _ca + arm.d_cm * _sa) / 2
        b.add(side_t, side * (off + _e + 6 + side_t.w_cm / 2), fwd, 0.0)
    return _valid(b, 'reading', variant='fireplace_anchor')


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
    # ЯКОРЬ «КАМИН» (владелец 19.08: «либо 2 кресла + камин, либо 1 кресло + камин»): если очаг
    # уже стоит, одиночное кресло принадлежит ему — это `reading.fireplace_anchor`. Пара кресел
    # у очага — схема quiet.fireplace_flank, она разбирается в place_quiet.
    _fp = next((p for p in (fixed or []) if p.role.split(' ')[0] == 'камин' and p.item is not None), None)
    if _fp is not None:
        from .candidates import Candidate as _CF
        for _sd in (-1, +1):
            _fb = build_fireplace_anchor(by_role, _fp.item, side=_sd)
            if _fb is None:
                continue
            _cf = _CF(placement=Placement(role=_fp.role, x=_fp.x, y=_fp.y, rot=_fp.rot, item=_fp.item),
                      kind='anchor', note='fireplace_anchor')
            _ps = _best_block(room, _fb, free.union(footprint(_fp)), [_cf], tv=None,
                              fixed=[p for p in (fixed or []) if p is not _fp])
            if _ps:
                for _p in _ps:
                    _p.tpl_variant = 'fireplace_anchor'
                return [_p for _p in _ps if _p.role != _fp.role]   # камин уже стоит

    # ПОРЯДОК ЯКОРЕЙ (модель «функция × якорь × форма», Q11): архитектурный якорь сильнее
    # обычного угла — эркер пробуем ДО углового канона (владелец 19.08: в эркерной комнате
    # уголок уезжал к произвольному углу).
    # ЭРКЕР — отдельный поиск: раньше на нишу приходился ОДИН кандидат (её центроид), поэтому
    # схема почти всегда проигрывала обычной стене. Общий генератор `_bay_candidates`: позиции
    # вдоль пролёта, спинка КРЕСЛА-ЯКОРЯ (не всего габарита) к наружной кромке; в эркере, как
    # и у окна, кресло самодостаточно — архитектурный якорь заменяет комплект (паспорт reading).
    _bay = _bay_candidates(room, b.anchor, free)
    if _bay:
        # ПАРА кресел в эркере (Q12): ниша достаточной ширины держит две посадки — практика
        # знает и одиночное кресло, и пару; пробуем пару первой, она богаче по местам
        _pb = build_reading_pair(by_role)
        if _pb is not None:
            _bay_pair = _bay_candidates(room, _pb.anchor, free, block_ref=_pb)
            _ps = _best_block(room, _pb, free, _bay_pair or _bay, tv=None, fixed=fixed)
            if _ps:
                for _p in _ps:
                    _p.tpl_variant = 'bay_pair'
                return _ps
        # КАСКАД СОСТАВА в нише: полный комплект (свет к УСТЬЮ) → полный (свет назад) →
        # кресло+поверхность → соло. Свет-вперёд первым (аудит Юли №28, разбор 21.08):
        # торшер «за плечом» в мелкой нише упирается в окно наружной кромки
        # (WINDOW_BLOCKED в 6 см от проёма) и весь комплект молча худел до кресла.
        _kits = [(dict(by_role), True), (dict(by_role), False),
                 ({k: v for k, v in by_role.items() if k not in ('торшер', 'лампа')}, False),
                 ({k: v for k, v in by_role.items() if k in ('кресло', 'кресло 3')}, False)]
        for _kit, _fwd in _kits:
            for _ls in (+1, -1):
                _bb = build_reading(_kit, allow_solo=True, lamp_side=_ls, lamp_forward=_fwd)
                if _bb is None:
                    break                       # состав не собрался — зеркало не поможет
                _bb.tpl_variant = 'bay_anchor'
                _ps = _best_block(room, _bb, free, _bay, tv=None, fixed=fixed)
                if _ps:
                    for _p in _ps:
                        _p.tpl_variant = 'bay_anchor'
                    return _ps
    # УГЛОВОЙ канон `corner_vignette` — кресло + СВЕТ + ПОВЕРХНОСТЬ (H&G chair-table-lamp).
    # В обычном углу архитектурного якоря нет, поэтому комплект обязателен: одинокое кресло
    # в углу читается как забытый предмет.
    _strict = (by_role.get('торшер') is not None or by_role.get('лампа') is not None) and \
        (by_role.get('приставной') is not None or by_role.get('столик 2') is not None)
    if _strict:
      # зеркала света (аудит Юли №27): торшер за ЛЮБЫМ из плеч — какой стороной блок
      # встанет в угол, решает перебор; строго за спинкой не ставим никогда
      for _ls in (+1, -1):
        _cb = build_reading(by_role, corner=True, lamp_side=_ls)
        if _cb is not None:
            _cb.tpl_variant = 'corner_vignette'
            # ЯКОРНЫЙ КОНТРАКТ КРЕСЛА (владелец 19.08 «кресло надо в угол загонять сильнее»,
            # Codex): сначала в вершину загоняем САМО КРЕСЛО — спутники (свет, поверхность)
            # законно расходятся к стенам и могут стоять ближе к устью угла; полный габарит
            # проверит `_best_block`. Не вышло — падаем на прежний якорь «по габариту блока»
            # (композиция целиком внутри, но кресло в середине ширины).
            _cc = [type(_c)(placement=_c.placement, kind='corner', note='угол (кресло в вершину)')
                   for _c in _corner_candidates(room, _cb.anchor, free)]
            _ps = _best_block(room, _cb, free, _cc, tv=None, fixed=fixed)
            if not _ps:
                _bw, _bd, _cxb, _cyb = block_bbox(_cb, 0.0)
                _virt = Item(role=_cb.anchor.role, w_cm=_bw, d_cm=_bd, h_cm=_cb.anchor.h_cm)
                _cc2 = []
                for _c in _corner_candidates(room, _virt, free):
                    # якорь = центр bbox − R(rot)·(смещение bbox в локальных координатах блока)
                    _wx, _wy = _rt(_cxb, _cyb, _c.placement.rot)
                    _cc2.append(type(_c)(placement=Placement(role=_cb.anchor.role,
                                                             x=_c.placement.x - _wx,
                                                             y=_c.placement.y - _wy,
                                                             rot=_c.placement.rot, item=_cb.anchor),
                                         kind='corner', note='угол (по габариту блока)'))
                _ps = _best_block(room, _cb, free, _cc2, tv=None, fixed=fixed)
            if _ps:
                return _ps
    cands = list(wall_candidates(room, b.anchor, free))
    return _best_block(room, b, free, cands, tv=None, fixed=fixed)


WINDOW_SEAT_DIAG: dict = {}   # Q12-4: почему скамья у окна (не) встала


def _ws_rules() -> dict:
    return (_zone_rules_tpl().get('zones', {}).get('window_seat', {}).get('rules') or {})


def place_window_seat(room: Room, items: list[Item], free: Polygon,
                      fixed: list[Placement] | None = None) -> list[Placement] | None:
    """Q12-4 (ADR-0112): СКАМЬЯ У ОКНА — `window_seat.bench_under_window` и `bay_bench`.

    FAIL-CLOSED (паспорт `zones.window_seat.rules.radiator_policy` + разбор Codex 19.08):
    - радиатор в проекции окна → НЕ ставим (у нас нет высоты/типа батареи и capability
      `radiator_compatible`, а закрывать прибор произвольной лавкой нельзя);
    - неизвестна высота подоконника (`sill_cm` = 0) → НЕ ставим: правило «не выше подоконника
      +10» проверить нечем;
    - скамья обязана иметь способность сиденья у стены (`caps.wall_seat_capable`), глубину в
      вилке паспорта и свободный фронт `front_access_cm`.
    Эркер: прямая скамья ЦЕЛИКОМ внутри ниши, лицом в комнату (встроенная по контуру — столярка,
    это отдельная спящая схема)."""
    WINDOW_SEAT_DIAG.clear()
    if os.environ.get('LAYOUT_TEMPLATES', '1') == '0':
        return None
    rules = _ws_rules()
    front = float(rules.get('front_access_cm', 60))
    dmin, dmax = (rules.get('depth_cm') or [38, 60])
    bench = next((it for it in items
                  if it.role.split(' ')[0] in ('банкетка', 'скамья')
                  and bool((it.caps or {}).get('wall_seat_capable'))
                  and float(dmin) <= it.d_cm <= float(dmax)), None)
    if bench is None:
        WINDOW_SEAT_DIAG['reject'] = 'no_window_seat_capable_bench'
        return None
    from .room_map import contour_features
    bays = contour_features(room)[0]
    wins = [o for o in room.openings if o.kind == 'window']
    if not wins:
        WINDOW_SEAT_DIAG['reject'] = 'no_window'
        return None
    for op in sorted(wins, key=lambda o: (o.wall, o.offset_cm)):
        sill = float(getattr(op, 'sill_cm', 0) or 0)
        if sill <= 0:
            WINDOW_SEAT_DIAG['reject'] = 'sill_unknown'
            continue
        if (bench.h_cm or 0) > sill + 10:
            WINDOW_SEAT_DIAG['reject'] = 'bench_above_sill'
            continue
        if any(r.wall == op.wall and r.offset_cm < op.offset_cm + op.width_cm
               and op.offset_cm < r.offset_cm + r.width_cm for r in (room.radiators or [])):
            WINDOW_SEAT_DIAG['reject'] = 'radiator_under_window'
            continue
        # позиция: по центру проёма, спинкой к оконной стене
        cx, cy, rot = _wall_seat_pose(room, op, bench)
        variant = 'bench_under_window'
        for bay in bays:                       # окно в эркере → скамья внутрь ниши
            if bay.buffer(1.0).contains(_opening_point(room, op)):
                variant = 'bay_bench'
                break
        p = Placement(role=bench.role, x=cx, y=cy, rot=rot, item=bench)
        p.tpl_id = 'window_seat'
        p.tpl_variant = variant
        fp = footprint(p)
        if free.intersection(fp).area < fp.area * 0.97:
            WINDOW_SEAT_DIAG['reject'] = 'no_space'
            continue
        # свободный фронт: перед сиденьем обязан быть проход front_access_cm
        from shapely.affinity import translate as _tr
        fx, fy = math.sin(math.radians(rot)), math.cos(math.radians(rot))
        probe = _tr(fp, xoff=fx * front, yoff=fy * front)
        if free.intersection(probe).area < probe.area * 0.9:
            WINDOW_SEAT_DIAG['reject'] = 'no_front_access'
            continue
        WINDOW_SEAT_DIAG['placed'] = variant
        return [p]
    return None


def _opening_point(room: Room, op):
    from shapely.geometry import Point
    g = opening_polygon(room, op)
    return Point(g.centroid.x, g.centroid.y)


def _wall_seat_pose(room: Room, op, bench: Item) -> tuple[float, float, float]:
    """Центр и поворот скамьи: спинкой к оконной стене, по центру проёма, фронт в комнату."""
    g = opening_polygon(room, op)
    cx, cy = g.centroid.x, g.centroid.y
    half = bench.d_cm / 2 + 5.0
    if op.wall == 'south':
        return cx, half, 0.0
    if op.wall == 'north':
        return cx, room.depth_cm - half, 180.0
    if op.wall == 'west':
        return half, cy, 90.0
    return room.width_cm - half, cy, 270.0


WINDOW_DIAG: dict = {}   # Q10b: почему оконный уголок (не) встал — в артефакт `_opportunities`


def place_window_reading(room: Room, items: list[Item], free: Polygon,
                         fixed: list[Placement] | None = None) -> list[Placement] | None:
    """Q10b свода №13 (Codex 19.08, «самый быстрый путь к практике»): уголок чтения С ЯКОРЕМ НА ОКНО —
    кресло (+торшер/приставной/пуф) в полосе у окна, ЛИЦОМ В КОМНАТУ (к центру главной группы, не в
    стену). Это не новый шаблон, а схема `reading` с `tpl_variant=window_anchor`: тот же атом и тот же
    контракт, другой генератор позиций. Практика: кресло у окна — самый частый исход (28%), у нас было
    16% и, главное, «не пробовали» в половине сцен (Q10-0).

    Радиатор: позиция отступает от ЛИЦЕВОЙ грани (общий RADIATOR-чек), подоконник — SOFA_BACK_ABOVE_SILL
    не применяется (кресло ниже спинки дивана), перекрытие окна проверяет window-скоринг блока.
    """
    WINDOW_DIAG.clear()
    if os.environ.get('LAYOUT_TEMPLATES', '1') == '0':
        return None
    wins = [op for op in room.openings if op.kind == 'window']
    if not wins:
        WINDOW_DIAG['reject'] = 'no_window'
        return None
    by_role: dict[str, Item] = {}
    for it in items:
        by_role.setdefault(it.role, it)
    # Q12 (аудит канонов): у окна практика знает ДВЕ формы — одиночное кресло и ПАРУ кресел
    # с общей поверхностью. Пара богаче по местам, поэтому пробуется первой; не собралась
    # (нет второго кресла) — обычный одиночный канон, у окна кресло самодостаточно (Q10b).
    _pair = build_reading_pair(by_role)
    b = _pair or build_reading(by_role, allow_solo=True)
    if b is None:
        WINDOW_DIAG['reject'] = 'no_armchair'
        WINDOW_DIAG['bank_roles'] = sorted(by_role)
        return None
    _wr_variant = 'window_pair' if _pair is not None else 'window_anchor'
    from .candidates import Candidate as _Cnd
    from .geometry import opening_polygon as _opg
    from .models import Placement as _Pl
    _fx = list(fixed or [])
    _seat = next((p for p in _fx if p.role.split(' ')[0] == 'диван'), None)
    rad_depth = 0.0
    cands = []
    for op in wins:
        # отступ от стены: глубина радиатора на ТОЙ ЖЕ стене (+ зазор конвекции) либо минимум
        rd = max((r.depth_cm for r in (room.radiators or []) if r.wall == op.wall), default=0.0)
        rad_depth = max(rad_depth, rd)
        # отступ считаем от ЗАДНЕЙ КРОМКИ ВСЕГО БЛОКА, а не только кресла: торшер/приставной
        # стоят чуть позади кресла и первыми попадали в зону конвекции радиатора (19.08)
        _back = max((it.d_cm / 2 - ry) for it, rx, ry, rr in b.rel)
        # зазор конвекции — ИЗ ПРАВИЛ (clearances.distances.sofa_to_radiator_wall), а не «12 на глаз»
        from .clearances import distances as _dz
        _rad_clear = float((_dz().get('sofa_to_radiator_wall') or [15, 20])[0])
        # без радиатора отступ = НИЖНЯЯ ГРАНИЦА «воздуха» из нашей же политики полосы
        # (occupancy.window_sofa.back_gap_policy: 15–30 см). 8 см читались как «вплотную»
        # и не оставляли места шторе (замечание владельца 20.08)
        _air = float(((_zone_rules_zn().get('window_sofa') or {}).get('back_gap_policy') or {})
                     .get('air_cm', [15, 30])[0] if isinstance(
                         ((_zone_rules_zn().get('window_sofa') or {}).get('back_gap_policy') or {})
                         .get('air_cm'), list) else 15.0)
        setback = (rd + _rad_clear + 3.0 if rd else _air) + _back
        g = _opg(room, op)
        mid_x, mid_y = g.centroid.x, g.centroid.y
        # три позиции вдоль окна: центр и трети — кресло не обязано стоять ровно по центру проёма
        # позиции: центр проёма, трети — и ПО БОКАМ окна (кресло у окна не обязано стоять
        # ровно перед стеклом; практика: кресло рядом с окном, лицом в комнату)
        _side_off = (op.width_cm / 2 + b.anchor.w_cm / 2 + 10) / max(op.width_cm, 1.0)
        for t in (0.5, 0.3, 0.7, -_side_off, 1 + _side_off):
            x0, y0, x1, y1 = g.bounds
            px = x0 + (x1 - x0) * t if op.wall in ('south', 'north') else mid_x
            py = y0 + (y1 - y0) * t if op.wall in ('west', 'east') else mid_y
            if op.wall == 'south':
                x, y = px, setback
            elif op.wall == 'north':
                x, y = px, room.depth_cm - setback
            elif op.wall == 'west':
                x, y = setback, py
            else:
                x, y = room.width_cm - setback, py
            # лицо — в комнату; если есть главная посадка, доворачиваем к её центру
            rot = {'south': 0.0, 'north': 180.0, 'west': 90.0, 'east': 270.0}[op.wall]
            if _seat is not None:
                import math as _m
                _ang = (_m.degrees(_m.atan2(_seat.x - x, _seat.y - y)) + 360) % 360
                if abs(((_ang - rot + 180) % 360) - 180) <= 60:      # цель в разумном секторе
                    rot = round(_ang / 15) * 15                       # квант 15° (контракт позы)
            # ЦЕНТРИРУЕМ БЛОК, А НЕ ЯКОРЬ: у пары кресел якорь — левое кресло, и позиция
            # «по центру проёма» уводила композицию вбок (замечание владельца 20.08)
            _bw0, _bd0, _cx0b, _cy0b = block_bbox(b, 0.0)
            _wx0, _wy0 = _rt(_cx0b, _cy0b, rot)      # смещение центра bbox В МИРОВЫХ осях
            if op.wall in ('south', 'north'):
                x -= _wx0
            else:
                y -= _wy0
            cands.append(_Cnd(placement=_Pl(role=b.anchor.role, x=x, y=y, rot=rot, item=b.anchor),
                              kind='wall', note=f'окно {op.wall}', topology='window'))
    if not cands:
        WINDOW_DIAG['reject'] = 'no_candidates'
        return None
    b.tpl_variant = _wr_variant
    ps = _best_block(room, b, free, cands, tv=None, fixed=_fx)
    if ps:
        for _p in ps:
            _p.tpl_variant = _wr_variant
        WINDOW_DIAG.update({'placed': _wr_variant, 'candidates': len(cands),
                            'radiator_depth_cm': rad_depth})
        return ps
    if _pair is not None:
        # пара не влезла у окна — честно откатываемся на одиночный канон
        _solo = build_reading(by_role, allow_solo=True)
        if _solo is not None:
            _solo.tpl_variant = 'window_anchor'
            ps = _best_block(room, _solo, free, cands, tv=None, fixed=_fx)
            if ps:
                for _p in ps:
                    _p.tpl_variant = 'window_anchor'
                WINDOW_DIAG.update({'placed': 'window_anchor', 'pair_rejected': True,
                                    'candidates': len(cands), 'radiator_depth_cm': rad_depth})
                return ps
    WINDOW_DIAG.update({'reject': 'no_valid_position', 'candidates': len(cands)})
    return None


def place_bay_armchair(room: Room, items: list[Item], free: Polygon,
                       fixed: list[Placement] | None = None) -> list[Placement] | None:
    """Шаблон bay_armchair 1.0 (одобрение владельца 14.08): кресло в эркере —
    ниша сама задаёт рамку зоны. Кандидаты ТОЛЬКО в эркерах (room_map.bays);
    торшер за плечом — если свободен. Вне эркера шаблон не ставится."""
    if os.environ.get('LAYOUT_TEMPLATES', '1') == '0':
        return None
    from .room_map import contour_features as _cfb
    bays = _cfb(room)[0]
    if os.environ.get('ZONES_DEBUG'):
        import sys as _sb
        print(f'ZDBG bay_armchair: эркеров={len(bays)}', file=_sb.stderr, flush=True)
    if not bays:
        return None
    by_role: dict[str, Item] = {}
    for it in items:
        by_role.setdefault(it.role, it)
    arm = by_role.get('кресло') or by_role.get('кресло 2')
    if arm is None:
        return None
    b = Block(arm)
    lamp = by_role.get('торшер')
    if lamp is not None:
        b.add(lamp, arm.w_cm / 2 + lamp.w_cm / 2 + LAMP_GAP, -arm.d_cm / 2 + 8, 0.0)
    b = _valid(b, 'bay_armchair')
    if b is None:
        return None
    from .candidates import Candidate as _Cnd
    cands = []
    for _bg in bays:
      x1, y1, x2, y2 = _bg.bounds
      # три позиции вдоль пролёта ниши (25/50/75%): часть ниши может быть занята
      # клиренсами соседей — кресло сдвигается, а не отказывается
      for _t in (0.5, 0.25, 0.75):
        _bx = x1 + (x2 - x1) * _t
        _by = y1 + (y2 - y1) * _t
        pad = 3.0
        # спинка ПРИЖАТА к наружной кромке ниши (глубокое кресло выступает в комнату —
        # эркер часть помещения); ориентация — фронтом вглубь комнаты
        if y2 - y1 <= x2 - x1:          # ниша за север/юг
            if _bg.centroid.y > room.depth_cm / 2:   # север: фронт на юг
                _rot, _cy = 180, y2 - arm.d_cm / 2 - pad
            else:                          # юг: фронт на север
                _rot, _cy = 0, y1 + arm.d_cm / 2 + pad
            _cx = _bx
        else:                            # ниша за запад/восток
            if _bg.centroid.x > room.width_cm / 2:   # восток: фронт на запад
                _rot, _cx = 270, x2 - arm.d_cm / 2 - pad
            else:                          # запад: фронт на восток
                _rot, _cx = 90, x1 + arm.d_cm / 2 + pad
            _cy = _by
        cands.append(_Cnd(placement=Placement(role=arm.role, x=_cx, y=_cy, rot=_rot,
                                              item=arm),
                          kind='wall', note='эркер', topology='bay'))
    if os.environ.get('ZONES_DEBUG'):
        import sys as _sb2
        from .geometry import footprint as _fpb
        for c in cands:
            _fp = _fpb(c.placement)
            cov = free.intersection(_fp).area / max(_fp.area, 1.0)
            print(f'ZDBG bay-канд: ({c.placement.x:.0f},{c.placement.y:.0f}) rot={c.placement.rot} покрытие={cov:.2f}', file=_sb2.stderr, flush=True)
    return _best_block(room, b, free, cands, tv=None, fixed=fixed)


def build_fireplace(by_role: dict[str, Item]) -> Block | None:
    """v2.5 КАМИННАЯ ЗОНА блоком (заявка владельца 11.08; веб-свод: симметричные
    built-ins по бокам камина — канон): камин-якорь + пара симметричных флангов.
    Приоритет флангов: стеллаж×2 (классика) → стеллаж+комод → кашпо×2 (зелень).
    Фасады в линию с камином, зазор 20 см от его торцов."""
    fp = by_role.get('камин')
    if fp is None:
        return None
    pairs = [('стеллаж', 'стеллаж 2'), ('стеллаж', 'комод'),
             ('кресло 3', 'кресло 4'), ('кашпо', 'кашпо 2')]
    left = right = None
    for a, bb in pairs:
        if a in by_role and bb in by_role:
            left, right = by_role[a], by_role[bb]
            break
    if left is None:
        single = by_role.get('стеллаж') or by_role.get('кашпо')
        if single is None:
            return None                      # камин без оформления — блок не нужен
        left = single
    b = Block(fp)
    chairs = left is not None and left.role.startswith('кресло')
    for side, it in ((-1, left), (+1, right)):
        if it is None:
            continue
        if chairs:
            # A2 (v2, веб-канон «identical seating on each side»): кресла лицом
            # друг к другу, зона безопасности от очага 61–91 см
            # 45° К ОЧАГУ, зеркально (замечание владельца 11.08 и 12.08): кресла
            # развёрнуты и к камину, и друг к другу — «лицом друг к другу» под 90°
            # оставляло камин сбоку от взгляда
            b.add(it, side * (fp.w_cm / 2 + 15 + it.d_cm / 2), 75.0 + it.w_cm / 2,
                  225.0 if side > 0 else 135.0)
        else:
            b.add(it, side * (fp.w_cm / 2 + 20 + it.w_cm / 2),
                  (fp.d_cm - it.d_cm) / 2, 0.0)   # фасады в линию с камином
    return _valid(b, 'fireplace')


def build_media_fireplace(by_role: dict[str, Item], mirror: bool = False) -> Block | None:
    """ЗОНА «МЕДИА + КАМИН НА ОДНОЙ СТЕНЕ» (заявка владельца 11.08, веб-свод
    подтвердил: side-by-side на широкой стене — рабочая схема, «TV ниже, камин
    остаётся виден на той же фасадной стене»). Носитель по центру взгляда, камин
    сбоку на той же стене с зазором 40 см — оба в поле зрения, кресло можно
    развернуть к огню."""
    bearer = by_role.get('стенка') or by_role.get('тв-тумба')
    fp = by_role.get('камин')
    if bearer is None or fp is None:
        return None
    b = Block(bearer)
    # ВЫРАВНИВАНИЕ ПО СПИНКЕ (обе вещи пристенные): камин у той же стены, иначе
    # он «отходит» от неё на разницу глубин и ловит NOT_AT_WALL.
    # `mirror` — камин слева от носителя (оба зеркала пробует place_media_fireplace)
    _sgn = -1.0 if mirror else 1.0
    b.add(fp, _sgn * (bearer.w_cm / 2 + 40 + fp.w_cm / 2), -(bearer.d_cm - fp.d_cm) / 2, 0.0)
    return _valid(b, 'fireplace')


def build_media_installation(by_role: dict[str, Item], wall_len_cm: float,
                             params: dict) -> Block | None:
    """P3 свода №12: ИНСТАЛЛЯЦИЯ на длинной стене — носитель ТВ + компаньоны хранения
    симметрично по бокам (витрина/стеллаж/комод), одним атомарным блоком (владелец
    №172; паспорт templates.json → zones.media.schemes.media_installation)."""
    bearer = by_role.get('стенка') or by_role.get('тв-тумба')
    if bearer is None:
        return None
    gap = float(params.get('gap_cm', 40))
    roles = list(params.get('companion_roles', ['витрина', 'стеллаж', 'комод']))
    comps = [by_role[r] for r in roles if r in by_role][: int(params.get('max_companions', 2))]
    if not comps:
        return None
    need = bearer.w_cm + sum(c.w_cm for c in comps) + gap * len(comps) + 80
    if wall_len_cm < max(float(params.get('wall_min_cm', 520)), need):
        return None
    b = Block(bearer)
    for i, c in enumerate(comps):
        side = -1 if i == 0 else +1
        # выравнивание по спинке (пристенные): сдвиг на разницу глубин
        b.add(c, side * (bearer.w_cm / 2 + gap + c.w_cm / 2), -(bearer.d_cm - c.d_cm) / 2, 0.0)
    return _valid(b, 'media')


def place_media_installation(room: Room, items: list[Item], free: Polygon,
                             fixed: list[Placement] | None = None) -> list[Placement] | None:
    """Ставится ДО обычной медиа-зоны в large-комнатах: длинная стена оформляется
    инсталляцией; не встала — обычный place_media (ничего не теряем)."""
    if os.environ.get('LAYOUT_TEMPLATES', '1') == '0':
        return None
    from .invariants import TEMPLATES as _T
    from .room_map import room_mode as _rm
    sch = next((x for x in _T.get('zones', {}).get('media', {}).get('schemes', [])
                if x.get('id') == 'media_installation'), None)
    if not sch or _rm(room) != 'large':
        return None
    params = sch.get('params', {})
    by_role: dict[str, Item] = {}
    for it in items:
        by_role.setdefault(it.role, it)
    seat = next((p for p in (fixed or []) if p.role == 'диван'), None)
    wall_len = max(room.width_cm, room.depth_cm)
    b = build_media_installation(by_role, wall_len, params)
    if b is None:
        return None
    ps = _best_block(room, b, free, wall_candidates(room, b.anchor, free),
                     tv=None, fixed=fixed, axis_seat=seat)
    if ps:
        for q in ps:
            q.tpl_variant = 'installation'      # маркер в экспорте (галерея/ИИ-экспорт)
    return ps


def place_media_fireplace(room: Room, items: list[Item], free: Polygon,
                          fixed: list[Placement] | None = None) -> list[Placement] | None:
    """Совместная постановка «носитель ТВ + камин» — ставится ДО отдельных медиа/каминной зон.

    КАСКАД СХЕМ (21.08, аудит Юли №35 + решение владельца; Houzz «7 ways TV+fireplace»,
    Homes&Gardens): side-by-side — рабочая схема, но НЕ обязаловка «должны делить стену»:
      1. `fireplace_side_by_side` — одна фасадная стена (единый фокус, огонь не в отражении);
         оба зеркала (камин справа/слева от носителя);
      2. `fireplace_tv_adjacent_walls` — СМЕЖНЫЕ (перпендикулярные) стены: оба фокуса в
         угле обзора посадки, огонь по-прежнему не отражается в экране;
      3. `tv_over_fireplace` — стенам тесно: ЭКРАН НАД КАМИНОМ, отдельный носитель не
         ставится (в этой схеме тумба не нужна — решение владельца 21.08); экран —
         служебная часть шаблона (свод №8 v2 §14), место под мебель не занимает.
    «Камин НАПРОТИВ ТВ» сознательно не предлагаем: пламя отражается в экране
    (FIRE_REFLECTION_ON_TV) и фокусы конкурируют."""
    if os.environ.get('LAYOUT_TEMPLATES', '1') == '0':
        return None
    by_role: dict[str, Item] = {}
    for it in items:
        by_role.setdefault(it.role, it)
    seat = next((p for p in (fixed or []) if p.role == 'диван'), None)
    bearer = by_role.get('стенка') or by_role.get('тв-тумба')
    fp = by_role.get('камин')
    if bearer is None or fp is None:
        return None
    # 1) одна стена: оба зеркала СРАВНИВАЮТСЯ по (ось носителя, lexo-термы), а не
    #    first-valid (Codex 21.08); тумбе доступны и аналитические позиции «ровно на ось»
    #    (_axis_candidates) — иначе joint систематически проигрывал одиночной медиа по оси
    _best1 = None
    for _mir in (False, True):
        b = build_media_fireplace(by_role, mirror=_mir)
        if b is None:
            break
        _cands1 = list(wall_candidates(room, b.anchor, free))
        if os.environ.get('LAYOUT_AXIS_CANDS', '1') != '0':
            _cands1 += _axis_candidates(room, b.anchor, free, seat, _cands1)
        ps = _best_block(room, b, free, _cands1, tv=None, fixed=fixed, axis_seat=seat)
        if not ps:
            continue
        from .score import score_layout as _slj
        _key1 = (_axis_off(list(ps), seat),
                 tuple(_slj(room, list(fixed or []) + list(ps)).terms))
        if _best1 is None or _key1 < _best1[0]:
            _best1 = (_key1, ps)
    if _best1:
        for p in _best1[1]:
            p.tpl_variant = 'fireplace_side_by_side'
        return _best1[1]
    # 2) смежные стены: носитель — ПОЛНОЙ медиа-логикой (дистанция/прицел/ось, как у
    #    отдельной зоны), камин — на перпендикулярной стене в угле обзора посадки.
    #    Камин не встал перпендикулярно → возвращаем None: раздельные зоны разберутся
    #    сами (прежнее поведение), а найденную медиа-позицию не навязываем.
    mps = place_media(room, [it for it in items if it.role.split(' ')[0] != 'камин'],
                      free, fixed=fixed)
    if mps:
        from shapely.ops import unary_union as _uu_mf
        _r0 = int(next((p.rot for p in mps
                        if p.role.split(' ')[0] in ('тв-тумба', 'стенка')), 0))
        _free2 = free.difference(_uu_mf([footprint(p) for p in mps
                                         if p.role.split(' ')[0] != 'ковёр']))
        fb = _valid(Block(fp), 'fireplace_solo')
        _cands = [c for c in wall_candidates(room, fb.anchor, _free2)
                  if int(c.placement.rot - _r0) % 180 == 90]      # только смежные стены
        _inview = _fireplace_dist_filter(_view_filter(
            _cands, seat, max_deg=_fireplace_sector_deg(seat),
            min_dist_cm=float(_g('fireplace_min_dist_cm', 90.0))), seat)
        # только сектор+вилка: нефильтрованный фолбэк плодил кандидатов-зомби
        fps = _best_block(room, fb, _free2, _inview or [], tv=None,
                          fixed=list(fixed or []) + mps)
        if fps:
            for p in list(mps) + list(fps):
                p.tpl_variant = 'fireplace_tv_adjacent_walls'
            return list(mps) + list(fps)
    # side-by-side и смежные не сложились — раздельные зоны в общем порядке; вариант
    # «экран над камином» (tv_over_fireplace) включается ПОСЛЕДНИМ резервом в place_media
    return None


def _fireplace_dist_range() -> tuple[float, float]:
    """Вилка «камин↔посадка» — единый источник zones.json (Codex 21.08: генератор фильтровал
    только ≥90 см по центрам, validate требует 200–450 по футпринтам — кандидаты-зомби)."""
    try:
        from .zones import zone_rules
        lo, hi = zone_rules()['zones']['seating_media']['fireplace']['distance_to_seating_cm']
        return float(lo), float(hi)
    except Exception:
        return 200.0, 450.0


def _fireplace_dist_filter(cands, seat):
    """Кандидаты камина в вилке дистанции ДО посадки (по футпринтам, допуск ±10 см)."""
    if seat is None:
        return list(cands)
    lo, hi = _fireplace_dist_range()
    _sf = footprint(seat)
    out = []
    for c in cands:
        d = footprint(c.placement).distance(_sf)
        if lo - 10.0 <= d <= hi + 10.0:
            out.append(c)
    return out


def _fireplace_sector_deg(seat: Placement | None) -> float:
    """Канон угла «камин↔посадка» — ЕДИНЫЙ источник `zones.json seating_media.fireplace
    .primary_sector_deg` (диван 35°, прочая посадка 45°): его читает validate
    (FIREPLACE_FAR_FROM_SEATING). Разбор Codex 21.08 (проверка «каноны учитываются в планах»):
    генератор пускал кандидатов до 60° (`fireplace_view_max_deg` — теперь deprecated-фолбэк),
    validate резал по 35°/45° — в узких сценах ВСЕ кандидаты камина были «зомби»
    (candidate_generated>0, hard_valid=0) и камин молча выпадал."""
    try:
        from .zones import zone_rules
        sec = (zone_rules()['zones']['seating_media']['fireplace']
               .get('primary_sector_deg') or {})
        if seat is not None and seat.role.split(' ')[0] == 'диван':
            return float(sec.get('диван', 35))
        return float(sec.get('прочая_посадка', 45))
    except Exception:
        return float(_g('fireplace_view_max_deg', 60.0))


def _view_filter(cands, seat: Placement | None, max_deg: float = 60.0,
                 min_dist_cm: float = 90.0):
    """Кандидаты, попадающие в УГОЛ ОБЗОРА с посадки и не ближе безопасной дистанции."""
    if seat is None:
        return list(cands)
    r = math.radians(seat.rot)
    fx, fy = math.sin(r), math.cos(r)
    out = []
    for c in cands:
        vx, vy = c.placement.x - seat.x, c.placement.y - seat.y
        d = math.hypot(vx, vy)
        if d < min_dist_cm:
            continue
        cosang = (fx * vx + fy * vy) / (d or 1.0)
        if math.degrees(math.acos(max(-1.0, min(1.0, cosang)))) <= max_deg:
            out.append(c)
    return out


def place_fireplace(room: Room, items: list[Item], free: Polygon,
                    fixed: list[Placement] | None = None) -> list[Placement] | None:
    """Каминная зона блоком; ставится ПОСЛЕ посадки — камин должен смотреть в зону
    (межзонная связь), поэтому позиции ранжируются соосностью с главным диваном."""
    if os.environ.get('LAYOUT_TEMPLATES', '1') == '0':
        return None
    by_role: dict[str, Item] = {}
    for it in items:
        by_role.setdefault(it.role, it)
    seat = next((p for p in (fixed or []) if p.role == 'диван'), None) or \
        next((p for p in (fixed or []) if p.role == 'кресло'), None)
    # КАМИН ОБЯЗАН БЫТЬ В УГЛУ ОБЗОРА (правило владельца 12.08 + веб-канон: камин и ТВ
    # на смежных стенах, посадка развёрнута к углу между ними — «clear view without
    # twisting», intdesigners.com, homesandgardens.com). Держим ≤60° от оси взгляда:
    # дальше человеку приходится выворачивать корпус, и зона перестаёт читаться.
    # Плюс безопасная дистанция 90 см от посадки до очага (веб-канон 90-120 см).
    # КАСКАД (экзамен 11.08: камин избыточен в 88 сценах — «камин+фланг» не влезал,
    # fits=0): фланги → один фланг → КАМИН СОЛО (зона из одного предмета легальна)
    fp = by_role.get('камин')
    if fp is None:
        return None
    tries = [by_role,
             {k: v for k, v in by_role.items()
              if k in ('камин', 'стеллаж', 'кресло 3', 'кашпо')},
             {'камин': fp}]
    for br in tries:
        b = build_fireplace(br) if len(br) > 1 else _valid(Block(fp), 'fireplace_solo')
        if b is None:
            continue
        _cands = list(wall_candidates(room, b.anchor, free)) \
            + list(_corner_candidates(room, b.anchor, free))
        _inview = _fireplace_dist_filter(_view_filter(
            _cands, seat, max_deg=_fireplace_sector_deg(seat),
            min_dist_cm=float(_g('fireplace_min_dist_cm', 90.0))), seat)
        ps = _best_block(room, b, free, _inview or [],
                         tv=None, fixed=fixed, axis_seat=seat)
        if ps is not None:
            return ps
    return None


def build_media(by_role: dict[str, Item], with_flanks: bool = True,
                max_flanks: int = 1, mirror: bool = False) -> Block | None:
    """v2.7/v2.8: медиа-зона — носитель ТВ (стенка ИЛИ тумба, ADR-0081) + напольный
    акцент сбоку.

    ВАЖНО (майнинг ProcTHOR 11.08, 9013 гостиных): напольного декора в комнате
    в среднем 0.7–1.0 предмета, и он РЕДКО стоит вплотную к носителю (в 60–120 см
    от якоря — единицы процентов). Поэтому по умолчанию ставим ОДИН акцент,
    пару — только в просторных комнатах (max_flanks=2). «Красота» медиа-зоны
    в реальных сценах живёт НА поверхности (тумба несёт 2.8 предмета) — это
    делает рендер-механика hosts, не блок."""
    bearer = by_role.get('стенка') or by_role.get('тв-тумба')
    if bearer is None:
        return None
    b = Block(bearer)
    # МЕДИА-СТЕНКА — свой паспорт (владелец 12.08: «стенка = медиазона»). По канону
    # она занимает 2.5-4 м стены и уже несёт хранение, поэтому флангов ей не даём:
    # кашпо у корпуса 2.6 м читается как случайный предмет (barkerandcobespoke.co.uk).
    if bearer.role == 'стенка':
        return _valid(b, 'media_wall')
    if with_flanks and max_flanks > 0:
        # только растения (веб-свод 11.08: торшер — у ПОСАДКИ, не у тумбы)
        deco = [by_role[r] for r in ('кашпо', 'кашпо 2') if r in by_role][:max_flanks]
        for i, d in enumerate(deco):
            # ЗЕРКАЛЬНЫЙ ВАРИАНТ (заявка владельца 12.08, set1-base): акцент бывает и
            # слева, и справа от носителя — схемы две, побеждает та, где носитель
            # встал ровнее к дивану
            side = (1 if mirror else -1) if i == 0 else (-1 if mirror else 1)
            # просвет декора — единое число межзонного правила (было 25 см, кашпо
            # читалось зажатым: замечание владельца 12.08)
            b.add(d, side * (bearer.w_cm / 2 + _DECOR_GAP_CM + d.w_cm / 2), 0.0, 0.0)
    return _valid(b, 'media')


def block_bbox(block, rot: float = 0.0) -> tuple[float, float, float, float]:
    """Габарит блока в МИРОВЫХ осях при повороте rot + смещение центра bbox от якоря.
    Общий helper: им пользуются и генераторы кандидатов, и витрина канонов
    (`tools/scout/canon_gallery.py`) — иначе галерея считает по-своему и маскирует
    дефекты боевого поиска (вывод Codex 19.08)."""
    xs, ys = [], []
    for it, rx, ry, rr in block.rel:
        w, d = (it.d_cm, it.w_cm) if int(rr) % 180 == 90 else (it.w_cm, it.d_cm)
        for cx, cy in ((rx - w / 2, ry - d / 2), (rx + w / 2, ry - d / 2),
                       (rx + w / 2, ry + d / 2), (rx - w / 2, ry + d / 2)):
            wx, wy = _rt(cx, cy, rot)
            xs.append(wx); ys.append(wy)
    return (max(xs) - min(xs), max(ys) - min(ys),
            (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2)


def _corner_candidates(room: Room, item: Item, free: Polygon) -> list:
    """Кандидаты «по диагонали в углу» (заявка владельца 12.08 + веб-свод: угловое
    диагональное размещение — рабочий приём, когда прямых стен не осталось).
    Предмет ставится под 45° спинкой в угол.

    Отступ считается от ПОЛУГАБАРИТА ПОВЁРНУТОГО предмета по каждой оси
    (ex = |cos|·w/2 + |sin|·d/2, ey = |sin|·w/2 + |cos|·d/2), а не от радиуса до угла:
    прежняя формула смешивала `hypot(w,d)/2` с проекцией и повторно множила на sin/cos —
    вытянутый блок 180×92 заходил в стены на ~15 см и угловые кандидаты молча вымирали
    (замечание владельца «уголок не в углу», разбор Codex 19.08)."""
    from .candidates import Candidate
    w, d = item.w_cm, item.d_cm
    m = float(_g('corner_margin_cm', 14.0))
    out = []
    for cx, cy, rot in ((0, 0, 45), (room.width_cm, 0, 315),
                        (0, room.depth_cm, 135), (room.width_cm, room.depth_cm, 225)):
        r = math.radians(rot)
        ex = abs(math.cos(r)) * w / 2 + abs(math.sin(r)) * d / 2
        ey = abs(math.sin(r)) * w / 2 + abs(math.cos(r)) * d / 2
        x = cx + math.copysign(1.0, math.sin(r)) * (ex + m)
        y = cy + math.copysign(1.0, math.cos(r)) * (ey + m)
        p = Placement(role=item.role, x=x, y=y, rot=float(rot), item=item)
        fp = footprint(p)
        if free.intersection(fp).area >= fp.area * 0.97:
            out.append(Candidate(p, 'corner', 'диагональ в углу'))
    return out


def _bay_candidates(room: Room, item: Item, free: Polygon, back_d_cm: float | None = None,
                    block_ref=None) -> list:
    """ОБЩИЙ генератор позиций в эркере (Codex 19.08: у reading был ОДИН кандидат — центроид
    ниши, из-за чего «кресло в эркере» уезжало к обычной стене). Позиции вдоль пролёта
    (`geometry.bay_positions_pct`), спинка ЯКОРЯ прижата к наружной кромке
    (`geometry.bay_back_pad_cm`), фронт — вглубь комнаты.

    `back_d_cm` — глубина того, что прижимается спинкой (у блока это глубина кресла-якоря,
    а не всего габарита: торшер и столик законно стоят ближе к устью ниши)."""
    from .candidates import Candidate
    from .room_map import contour_features
    out = []
    pcts = list(_g('bay_positions_pct', [50, 25, 75]))
    pad = float(_g('bay_back_pad_cm', 3.0))
    for bay in contour_features(room)[0]:
        x0, y0, x1, y1 = bay.bounds
        horiz = (x1 - x0) >= (y1 - y0)          # пролёт вдоль X (эркер на север/юг)
        far = (y1 if (y0 + y1) / 2 > room.depth_cm / 2 else y0) if horiz else               (x1 if (x0 + x1) / 2 > room.width_cm / 2 else x0)
        if horiz:
            rot = 180.0 if far == y1 else 0.0
        else:
            rot = 270.0 if far == x1 else 90.0
        half = (back_d_cm if back_d_cm is not None else item.d_cm) / 2
        sgn = -1.0 if far in (y1, x1) else 1.0
        for pct in pcts:
            if horiz:
                x = x0 + (x1 - x0) * pct / 100.0
                y = far + sgn * (pad + half)
            else:
                y = y0 + (y1 - y0) * pct / 100.0
                x = far + sgn * (pad + half)
            p = Placement(role=item.role, x=x, y=y, rot=rot, item=item)
            if free.intersection(footprint(p)).area >= footprint(p).area * 0.97:
                out.append(Candidate(p, 'wall', 'эркер', topology='bay'))
    if block_ref is not None and out:
        # ЦЕНТРИРОВКА БЛОКА в нише (пара кресел): позиции считаются для якоря, а композиция
        # шире его — иначе вторая посадка уезжает к краю эркера (владелец 20.08)
        _bw, _bd, _cxb, _cyb = block_bbox(block_ref, 0.0)
        for c in out:
            _wx, _wy = _rt(_cxb, _cyb, c.placement.rot)
            if int(c.placement.rot) % 180 == 0:
                c.placement.x -= _wx
            else:
                c.placement.y -= _wy
    return out



def _axis_off(ps: list[Placement], seat: Placement | None) -> float:
    """Насколько носитель ТВ смещён с оси взгляда дивана (см). Меньше — лучше."""
    if seat is None or not ps:
        return 0.0
    bearer = next((p for p in ps if _base_role(p.role) in ('тв-тумба', 'стенка')), ps[0])
    r = math.radians(seat.rot)
    vx, vy = bearer.x - seat.x, bearer.y - seat.y
    return abs(math.cos(r) * vx - math.sin(r) * vy)      # поперечное смещение от оси


def _jamb_candidates(room: Room, item: Item, free: Polygon) -> list:
    """Схема «носитель вплотную к косяку» (владелец 12.08): позиции у КРАЯ дверного
    проёма, где предмет прижат к косяку торцом. Канон разрешает мебель у косяка,
    если сохранён проход 76-91 см перед дверью и предмет вне дуги (weekand.com,
    auramodernhome.com) — оба условия проверит validate (DOOR_PASSAGE, DOOR_SWING).
    """
    from .candidates import WALL_FACING_ROT, Candidate
    out = []
    for op in room.openings:
        if op.kind != 'door':
            continue
        rot = WALL_FACING_ROT.get(op.wall)
        if rot is None:
            continue
        w, d = item.w_cm, item.d_cm
        if int(rot) % 180 == 90:
            w, d = d, w
        for side in (-1, +1):          # к левому и к правому косяку
            edge = op.offset_cm if side < 0 else op.offset_cm + op.width_cm
            along = edge - w / 2 if side < 0 else edge + w / 2
            if op.wall in ('south', 'north'):
                x, y = along, (d / 2 if op.wall == 'south' else room.depth_cm - d / 2)
            else:
                x, y = (d / 2 if op.wall == 'west' else room.width_cm - d / 2), along
            p = Placement(role=item.role, x=x, y=y, rot=float(rot), item=item)
            if free.intersection(footprint(p)).area < footprint(p).area * 0.97:
                continue
            out.append(Candidate(placement=p, kind='wall', note='у косяка двери',
                                 topology='door_jamb'))
    return out


def _window_candidates(room: Room, item: Item, free: Polygon) -> list:
    """Носитель ТВ ПЕРЕД ОКНОМ (разрешение владельца 13.08: «ТВ можно, если нет других
    вариантов, перед окном ставить; тумба низкая — окно полностью не перекроет»).

    Под окном обычно радиатор — тумба отступает от стены на его глубину + зазор
    конвекции, стоит по центру окна. WINDOW_BLOCKED не сработает (высота тумбы ниже
    подоконника), RADIATOR не сработает (отступили), TV_ON_WINDOW_WALL остаётся
    мягким штрафом — потому эти кандидаты только в relaxed-круге.
    """
    from .candidates import WALL_FACING_ROT, Candidate
    out = []
    rad_depth = max((r.depth_cm for r in room.radiators), default=15.0)
    setback = rad_depth + 17.0            # зазор конвекции к радиатору
    for op in room.openings:
        if op.kind != 'window':
            continue
        rot = WALL_FACING_ROT.get(op.wall)
        if rot is None:
            continue
        w, d = item.w_cm, item.d_cm
        mid = op.offset_cm + op.width_cm / 2
        if op.wall in ('south', 'north'):
            x = mid
            y = setback + d / 2 if op.wall == 'south' else room.depth_cm - setback - d / 2
        else:
            y = mid
            x = setback + d / 2 if op.wall == 'west' else room.width_cm - setback - d / 2
        p = Placement(role=item.role, x=x, y=y, rot=float(rot), item=item)
        fp = footprint(p)
        if free.intersection(fp).area < fp.area * 0.97:
            continue
        out.append(Candidate(placement=p, kind='wall', note='перед окном',
                             topology='window_front'))
    return out


def _between_windows_candidates(room: Room, item: Item, free: Polygon) -> list:
    """Схема `media_between_windows` (паспорт: «на стене два окна с простенком ≥ W_media»).

    ПРОД-ДЫРА до 21.08 (аудит Юли №41 → разбор Codex): паспорт объявлял
    `implemented_as: _window_candidates`, но тот центрирует носитель ПО ОКНУ (схема
    «перед окном»), а не по ПРОСТЕНКУ между двумя проёмами — «между окон» не имела
    реализации вовсе. Здесь носитель встаёт спинкой к стене, ЦЕНТР — на оси простенка
    между соседними окнами одной стены; допуск TV_ON_WINDOW_WALL объявлен в паспорте."""
    from .candidates import WALL_FACING_ROT, Candidate
    out = []
    by_wall: dict[str, list] = {}
    for op in room.openings:
        if op.kind == 'window':
            by_wall.setdefault(op.wall, []).append(op)
    for wall, wins in by_wall.items():
        if len(wins) < 2:
            continue
        rot = WALL_FACING_ROT.get(wall)
        if rot is None:
            continue
        w, d = item.w_cm, item.d_cm
        wins = sorted(wins, key=lambda o: o.offset_cm)
        for a, bnext in zip(wins, wins[1:]):
            lo, hi = a.offset_cm + a.width_cm, bnext.offset_cm
            if hi - lo < w:              # простенок уже носителя — схема не для этой стены
                continue
            mid = (lo + hi) / 2
            if wall in ('south', 'north'):
                x, y = mid, (d / 2 if wall == 'south' else room.depth_cm - d / 2)
            else:
                y, x = mid, (d / 2 if wall == 'west' else room.width_cm - d / 2)
            p = Placement(role=item.role, x=x, y=y, rot=float(rot), item=item)
            fp = footprint(p)
            if free.intersection(fp).area < fp.area * 0.97:
                continue
            out.append(Candidate(placement=p, kind='wall', note='простенок между окон',
                                 topology='between_windows'))
    return out


def _axis_candidates(room, item, free, seat, cands):
    """P1 свода №12: клоны пристенных кандидатов, сдвинутые ВДОЛЬ СТЕНЫ так, чтобы центр
    носителя лёг точно на ось взгляда посадки. Только там, где клон целиком в free
    (проверка footprint), иначе кандидат не добавляется. Не более одного клона на
    (стена, rot). Ничего не заменяет — расширяет пул; hard-правила решают дальше."""
    if seat is None:
        return []
    from .geometry import seat_axis_origin, footprint as _fpA
    from shapely.prepared import prep as _prep
    sx, sy = seat_axis_origin(seat)
    r = math.radians(seat.rot)
    # направление оси взгляда (единичный) и поперечный вектор
    ax, ay = math.sin(r), math.cos(r)
    out, seen = [], set()
    _free = _prep(free.buffer(1))
    for c in cands:
        if getattr(c, 'kind', '') != 'wall':
            continue
        p = c.placement
        rot = int(round(p.rot)) % 360
        # стена горизонтальная (rot 0/180) → скользим по x; вертикальная → по y
        if rot in (0, 180):
            # проекция оси дивана на эту стену: точка оси при y = p.y
            if abs(ay) < 1e-6:
                continue
            t = (p.y - sy) / ay
            nx, ny = sx + ax * t, p.y
        else:
            if abs(ax) < 1e-6:
                continue
            t = (p.x - sx) / ax
            nx, ny = p.x, sy + ay * t
        key = (rot, round(p.y if rot in (0, 180) else p.x))
        if key in seen:
            continue
        q = p.model_copy(update={'x': float(nx), 'y': float(ny)})
        if not _free.contains(_fpA(q)):
            continue
        seen.add(key)
        out.append(type(c)(placement=q, kind='wall', note='ось посадки (P1)',
                           topology=getattr(c, 'topology', '')))
    return out


def _axis_filter(cands, seat: Placement | None):
    """Кандидаты, стоящие В ОСИ ВЗГЛЯДА посадки (поперечное смещение ≤ порога)."""
    if seat is None:
        return []
    from .quality import FOCUS_OFFSET_MAX_CM
    r = math.radians(seat.rot)
    out = []
    for c in cands:
        vx, vy = c.placement.x - seat.x, c.placement.y - seat.y
        if abs(math.cos(r) * vx - math.sin(r) * vy) <= FOCUS_OFFSET_MAX_CM:
            out.append(c)
    return out


def place_media(room: Room, items: list[Item], free: Polygon,
                fixed: list[Placement] | None = None,
                top: int = 1, relaxed: bool = False) -> list[Placement] | None:
    """Медиа-зона блоком; позиция — по межзонной связи (соосность с главным
    посадочным из fixed, дистанция/прицел проверит validate)."""
    if os.environ.get('LAYOUT_TEMPLATES', '1') == '0':
        return None
    # ЭКРАН УЖЕ НАД КАМИНОМ (схема tv_over_fireplace, 21.08): медиа-функцию несёт
    # камин — отдельный носитель НЕ ставим, тумба честно уходит в «не использовано»
    if any(getattr(p, 'tpl_variant', '') == 'tv_over_fireplace'
           and p.role.split(' ')[0] == 'камин' for p in (fixed or [])):
        return None
    by_role: dict[str, Item] = {}
    for it in items:
        by_role.setdefault(it.role, it)
    seat = next((p for p in (fixed or []) if p.role == 'диван'), None) or         next((p for p in (fixed or []) if p.role == 'кресло'), None)
    # P3 свода №12: ИНСТАЛЛЯЦИЯ на длинной стене (large) — альтернатива одиночного
    # носителя, сравнивается ЛЕКСО-КЛЮЧОМ (как стенка/тумба, C-3): носитель +
    # компаньоны хранения атомарно; не встала/проиграла — обычная медиа.
    # P3 свода №12: инсталляция (носитель + компаньоны хранения) — РЕЖИМ медиа,
    # запрашиваемый beam-драйвером как отдельная ГИПОТЕЗА (MEDIA_MODE), не локальный
    # лексо-выбор: у инсталляции больше предметов → больше штрафов circulation/zone,
    # а её функция (хранение размещено сразу) видна только на ГОТОВОМ плане (plan_key).
    if MEDIA_MODE[0] == 'installation' and not relaxed:
        _inst = place_media_installation(room, items, free, fixed=fixed)
        if _inst:
            return [_inst] if top > 1 else _inst
        # инсталляция не встала — честный фолбэк на одиночный носитель
    return _place_media_core(room, items, free, fixed=fixed, top=top, relaxed=relaxed)


def _place_media_core(room: Room, items: list[Item], free: Polygon,
                      fixed: list[Placement] | None = None,
                      top: int = 1, relaxed: bool = False) -> list[Placement] | None:
    by_role: dict[str, Item] = {}
    for it in items:
        by_role.setdefault(it.role, it)
    seat = next((p for p in (fixed or []) if p.role == 'диван'), None) or         next((p for p in (fixed or []) if p.role == 'кресло'), None)
    # ЛЕСТНИЦА НОСИТЕЛЕЙ (владелец 13.08: «шаблон со стенкой не лезет — автоматом
    # выбирать с тумбой»): при обоих носителях в банке сперва вся попытка со СТЕНКОЙ,
    # не встала ни в одном круге — повтор с ТУМБОЙ (стенка исключается из вида).
    if 'стенка' in by_role and 'тв-тумба' in by_role:
        # C-3 свода №11 (Кодекс §Q-C.4): обе альтернативы носителя решаются и
        # сравниваются ЛЕКСО-КЛЮЧОМ движка (прежний first-feasible «стенка → тумба»
        # позволял широкой стенке предопределить FAR, хотя тумба давала пару)
        from .score import score_layout as _slm2
        from .zones import lexo_key as _lkm2
        _outs2 = []
        for _excl in ('тв-тумба', 'стенка'):
            _ps2 = _place_media_core(room, [it for it in items if it.role != _excl],
                                     free, fixed=fixed, top=top, relaxed=relaxed)
            if _ps2 is not None:
                # top>1 → список ВАРИАНТОВ (P1 lookahead): ключ по лучшему (первому)
                _first2 = _ps2[0] if (_ps2 and isinstance(_ps2[0], list)) else _ps2
                _key2 = _lkm2(0, 0, _slm2(
                    room, list(fixed or []) + _first2).terms)
                _outs2.append((_key2, _ps2))
        if not _outs2:
            return None
        _outs2.sort(key=lambda t: t[0])
        return _outs2[0][1]
    global _MEDIA_TOE_RELAXED
    # Ступени: обычный заход ковра под носитель (15 см) → без флангов → КРАЙНИЙ
    # СЛУЧАЙ: ковёр уходит под медиа-зону глубже (решение владельца 12.08).
    for relaxed_toe in (False, True):
        _MEDIA_TOE_RELAXED = relaxed_toe
        try:
            # СНАЧАЛА ГОЛЫЙ НОСИТЕЛЬ, потом с акцентами (13.08): проба места при выборе
            # позиции дивана проверяет именно голый носитель. Обратный порядок давал
            # рассогласование «проба нашла место, зона не встала» — кашпо у тумбы
            # ломало зону, ради которой освобождалась стена.
            for flanks in (False, True):
                # обе зеркальные схемы разом: _best_block сам выберет позицию с лучшей
                # соосностью носителя и дивана, а мы берём лучший из двух вариантов
                best = None
                for mirror in (False, True):
                    b = build_media(by_role, with_flanks=flanks, mirror=mirror)
                    if b is None:
                        break
                    _cands = list(wall_candidates(room, b.anchor, free)) \
                        + _jamb_candidates(room, b.anchor, free) \
                        + list(_corner_candidates(room, b.anchor, free))
                    if b.anchor.role == 'тв-тумба':
                        # НИЗКОЙ ТУМБЕ МОЖНО К ОКНУ, ЕСЛИ ТЕСНО (владелец 13.08,
                        # повторено): кандидаты у окна есть всегда, но несут soft-штраф
                        # TV_ON_WINDOW_WALL — выигрывают только когда больше некуда.
                        # Стенке к окну нельзя (перекроет свет).
                        _cands += _window_candidates(room, b.anchor, free)
                        # ПРОСТЕНОК между двух окон — своя схема media_between_windows
                        # (реализация 21.08, аудит Юли №41): центр — на оси простенка
                        _cands += _between_windows_candidates(room, b.anchor, free)
                    # P1 свода №12 (владелец №1/№2): АНАЛИТИЧЕСКИЕ кандидаты «ровно на
                    # оси дивана» — решётка ~25 см точки на оси не гарантирует, и лучший
                    # достижимый offset оставался 13–16 см при свободной стене. Для каждой
                    # пристенной позиции добавляем клона со сдвигом вдоль стены на ось
                    # (seat_axis_origin: у Г-дивана — центр главной секции).
                    if os.environ.get('LAYOUT_AXIS_CANDS', '1') != '0':
                        _cands += _axis_candidates(room, b.anchor, free, seat, _cands)
                    # ЦЕНТР — ПОРОГ, А НЕ БОНУС (свод владельца 12.08): сперва только
                    # позиции в оси взгляда (смещение ≤ FOCUS_OFFSET_MAX_CM); если таких
                    # нет вовсе — весь список. Раньше центровка была слагаемым скора и
                    # проигрывала прочим штрафам: 163 сцены со смещением >40 см.
                    # ПОСЛЕДНЯЯ ПОПЫТКА (правило владельца 12.08: «тумба или стенка
                    # должна быть везде»): в relaxed-режиме центровка не требуется —
                    # лучше носитель сбоку, чем сцена вообще без ТВ.
                    _strict = [] if relaxed else _axis_filter(_cands, seat)
                    # V4-D2 (свод №10): классы кандидатов ЛЕКСИКОГРАФИЧЕСКИ —
                    # CENTERED (ось ≤ существующего порога фокуса) → OFFSET (пристенные
                    # вне оси) → CORNER/JAMB/WINDOW. Прежде фолбэк мешал всё в один
                    # список, и №8 получал offset 83 при доступных ближних позициях.
                    global LAST_MEDIA_AXIS
                    _mdiag = {'centered_generated': len(_strict),
                              'centered_hard_valid': 0, 'class': None}
                    LAST_MEDIA_AXIS = _mdiag
                    ps = _best_block(room, b, free, _strict or _cands, top=top,
                                     tv=None, fixed=fixed, axis_seat=seat)
                    if ps is not None and _strict:
                        _mdiag['centered_hard_valid'] = 1
                        _mdiag['class'] = 'centered'
                    elif ps is not None:
                        _mdiag['class'] = 'relaxed'
                    if ps is None and _strict:
                        _off_c = [c for c in _cands if getattr(c, 'kind', '') == 'wall']
                        _rest_c = [c for c in _cands if getattr(c, 'kind', '') != 'wall']
                        for _klass, _sub in (('offset', _off_c),
                                             ('corner_jamb_window', _rest_c)):
                            if not _sub:
                                continue
                            ps = _best_block(room, b, free, _sub, top=top,
                                             tv=None, fixed=fixed, axis_seat=seat)
                            if ps is not None:
                                _mdiag['class'] = _klass
                                break
                    if ps is None:
                        continue
                    try:
                        _mdiag['offset_cm'] = round(_axis_off(ps, seat), 1)
                    except Exception:
                        pass
                    # V4-E свода №10: заход носителя на ковёр — ДОКАЗУЕМЫЙ fallback:
                    # ступень toe=relaxed достигается только после провала чистой
                    # (clean_nonoverlap_failed=True по построению цикла)
                    try:
                        _rugp = next((q for q in (fixed or [])
                                      if q.role.split(' ')[0] == 'ковёр'), None)
                        _car = next((q for q in ps if q.role.split(' ')[0]
                                     in ('тв-тумба', 'стенка')), None)
                        if _rugp is not None and _car is not None:
                            _ov = footprint(_car).intersection(
                                footprint(_rugp)).area
                            _mdiag['rug_overlap_cm2'] = round(_ov, 0)
                            if _ov > 0:
                                _mdiag['degraded_reason'] = (
                                    'rug_toe_relaxed' if _MEDIA_TOE_RELAXED
                                    else 'toe_within_norm')
                                _mdiag['clean_nonoverlap_failed'] = bool(
                                    _MEDIA_TOE_RELAXED)
                    except Exception:
                        pass
                    if top > 1:
                        best = (best or []) + ps
                    elif best is None or _axis_off(ps, seat) < _axis_off(best, seat):
                        best = ps
                    if not flanks:
                        break            # без акцентов зеркалить нечего
                if best is not None:
                    return best
        finally:
            _MEDIA_TOE_RELAXED = False
    return None


QUIET_DIAG: dict = {}   # Q5: почему второй pod (не) встал — читает solve_zoned → артефакт `_quiet_diag`


def build_quiet(by_role: dict[str, Item], variant: str = 'quiet_chat',
                fireplace: Item | None = None) -> Block | None:
    """Второй pod (Q5 свода №13, Codex по замечаниям владельца №181/№183):
    quiet_chat — пара кресел 3/4 + ОБЯЗАТЕЛЬНАЯ малая поверхность (приставной|столик 2|столик)
    между ними, кресла повёрнуты 30–45° к общему центру (не «интервью» 0/180);
    fireplace_flank — пара по сторонам камина под 45° к очагу (fireplace.rules), камин — часть блока.
    Без поверхности и без камина — блока НЕТ (пара визави «ни о чём» — владелец)."""
    a1 = by_role.get('кресло 3')
    a2 = by_role.get('кресло 4')
    if not (a1 and a2):
        return None
    if variant == 'fireplace_flank' and fireplace is not None:
        b = Block(fireplace)
        _rules = (_zone_rules_tpl().get('zones', {}).get('fireplace', {}).get('rules') or {})
        _ang = float(_rules.get('chair_angle_deg', 45))
        _off = fireplace.w_cm / 2 + 45 + a1.w_cm / 2
        _fwd = float((_rules.get('safety_zone_cm') or [61, 91])[0]) + a1.d_cm / 2 + 20
        b.add(a1, -_off, _fwd, 180.0 - _ang)      # слева, к очагу под углом
        b.add(a2, +_off, _fwd, 180.0 + _ang)      # справа, зеркально
        # СОСТАВ СХЕМЫ НЕ ЗАВИСИТ ОТ БАНКА (владелец 19.08 + Codex): `fireplace_flank` — это
        # РОВНО два кресла + камин. Поверхности сюда не добавляем: раньше наличие двух столиков
        # в банке молча превращало базовый канон в другую композицию. Одно кресло + камин —
        # отдельная схема `reading.fireplace_anchor`; кресло+поверхность+свет без камина —
        # `reading.corner_vignette`. Нехватка поверхности у пары — задокументированное
        # отклонение схемы (якорь здесь очаг), см. templates.json quiet.fireplace_flank.
        return _valid(b, 'quiet')
    side = by_role.get('приставной') or by_role.get('столик 2') or by_role.get('столик')
    if side is None:
        return None                               # quiet_chat без поверхности не собирается
    # Геометрия (правка 16.08 после реплея: якорь-кресло под 35° у стены торчал углом В СТЕНУ →
    # ни одной валидной позиции): якорь — ПОВЕРХНОСТЬ (rot 0, спиной к стене), кресла по обе
    # стороны ВДОЛЬ стены, развёрнуты на 35° к общему центру; сдвинуты вперёд на «вылет»
    # повёрнутого прямоугольника, чтобы задний угол не пересекал стену
    b = Block(side)
    ang = 35.0
    r = math.radians(ang)
    def _fwd(a: Item) -> float:                   # задняя кромка повёрнутого кресла = задняя кромка столика
        back = a.w_cm / 2 * math.sin(r) + a.d_cm / 2 * math.cos(r)
        return back - side.d_cm / 2
    off1 = side.w_cm / 2 + 20 + a1.w_cm / 2       # 20 см — зазор кромок (H&G: reach ≤ ~45 см до поверхности)
    off2 = side.w_cm / 2 + 20 + a2.w_cm / 2
    b.add(a1, -off1, _fwd(a1), ang)               # слева, повёрнуто к центру (+x)
    b.add(a2, +off2, _fwd(a2), 360.0 - ang)       # справа, зеркально
    return _valid(b, 'quiet')


def _zone_rules_tpl():
    from .invariants import TEMPLATES as _T
    return _T


def place_quiet(room: Room, items: list[Item], free: Polygon,
                fixed: list[Placement] | None = None) -> list[Placement] | None:
    """Тихая зона (пара кресло 3/4 визави). C-4 свода №11 (Кодекс Q-B):
    (1) гейт — режим комнаты из ДАННЫХ (room_mode == large), не отдельные 45 м²;
    (2) кандидаты — стены + СРЕДИННЫЕ регионы (крупнейший незакреплённый регион
    часто в центре/за диваном, где wall-якоря нет); главная посадка обязана уже
    стоять (fixed) — иначе кресла нужнее в основной группе."""
    if os.environ.get('LAYOUT_TEMPLATES', '1') == '0':
        return None
    QUIET_DIAG.clear()
    from .room_map import room_mode as _rmq
    if _rmq(room) != 'large':
        QUIET_DIAG['skip'] = 'room_mode_not_large'
        return None
    if not any(p.role.split(' ')[0] == 'диван' for p in (fixed or [])):
        QUIET_DIAG['skip'] = 'no_main_sofa'
        return None
    by_role: dict[str, Item] = {}
    for it in items:
        by_role.setdefault(it.role, it)
    if not (by_role.get('кресло 3') and by_role.get('кресло 4')):
        QUIET_DIAG['skip'] = 'no_pair_3_4'
        return None
    # Q5 (Codex): pod не ставится при богатой primary (≥2 кресла в главной группе или два
    # дивана) и при уже существующем reading/bay pod — вторая зона должна быть осмысленной
    _fx = list(fixed or [])
    _main_arm = sum(1 for p in _fx if p.role.split(' ')[0] == 'кресло' and getattr(p, 'tpl_id', '') == 'seating')
    _sofas = sum(1 for p in _fx if p.role.split(' ')[0] == 'диван')
    if _main_arm >= 2 or _sofas >= 2:
        QUIET_DIAG['skip'] = 'primary_rich'
        return None
    if any(getattr(p, 'tpl_id', '') in ('reading', 'bay_armchair') for p in _fx):
        QUIET_DIAG['skip'] = 'existing_pod'
        return None
    # порядок: fireplace_flank (камин уже стоит и достижим) → quiet_chat у окна/в углу
    _fp = next((p for p in _fx if p.role.split(' ')[0] == 'камин'), None)
    outs = []
    if _fp is not None and _fp.item is not None:
        bf = build_quiet(by_role, variant='fireplace_flank', fireplace=_fp.item)
        if bf is not None:
            # блок якорится на камине: единственный кандидат — фактическая поза камина
            from .candidates import Candidate as _CQ
            _cq = _CQ(placement=Placement(role=_fp.role, x=_fp.x, y=_fp.y, rot=_fp.rot, item=_fp.item),
                      kind='anchor', note='fireplace_flank')
            _fx_wo = [p for p in _fx if p is not _fp]
            ps = _best_block(room, bf, free.union(footprint(_fp)), [_cq], tv=None, fixed=_fx_wo)
            if ps:
                for q in ps:
                    q.tpl_variant = 'fireplace_flank'
                QUIET_DIAG['placed'] = 'fireplace_flank'
                return [q for q in ps if q.role != _fp.role]   # камин уже стоит — не дублируем
            QUIET_DIAG['fireplace_flank'] = 'no_valid_position'
        else:
            QUIET_DIAG['fireplace_flank'] = 'block_none'
    else:
        QUIET_DIAG['fireplace_flank'] = 'no_fireplace_placed'
    b = build_quiet(by_role, variant='quiet_chat')
    if b is None:
        QUIET_DIAG['quiet_chat'] = 'no_surface'   # нет приставной|столик 2|столик в остатке банка
        return None
    _cands = list(wall_candidates(room, b.anchor, free)) \
        + list(middle_candidates(room, b.anchor, free, limit=8))
    ps = _best_block(room, b, free, _cands, tv=None, fixed=fixed)
    if ps:
        for q in ps:
            q.tpl_variant = 'quiet_chat'
        QUIET_DIAG['placed'] = 'quiet_chat'
    else:
        QUIET_DIAG['quiet_chat'] = 'no_valid_position'
    return ps


NOOK_DIAG: dict = {}   # Q6b: почему уголок (не) собрался/встал — читает solve_zoned → `_dining`


def _nook_rules() -> dict:
    return (_zone_rules_tpl().get('zones', {}).get('dining', {}).get('rules') or {})


def bench_seats(bench: Item) -> int | None:
    """Мест на банкетке — ТОЛЬКО из capability-проекции каталога (`caps.guaranteed_seats`, длина/60).
    Нет caps → None (unknown): считать места из ширины запрещено (Codex Q6a/Q6b — пуф подходящей
    ширины не обязан быть пригоден для еды)."""
    v = (getattr(bench, 'caps', None) or {}).get('guaranteed_seats')
    try:
        return int(v) if v is not None else None
    except Exception:
        return None


def build_edge_nook(by_role: dict[str, Item], variant: str = 'edge_nook_4') -> Block | None:
    """Q6b свода №13: banquette-уголок — банкетка спинкой к ПРЯМОЙ стене + стол кромкой вровень
    (зазор 0–3 см, `geometry.nook_table_bench_gap_cm`: 2D-модель не знает столешницу/царгу, поэтому
    вместо нахлёста — минимальный зазор) + стулья со свободной стороны. Минимум 4 места:
    `caps.guaranteed_seats` ≥2 И ≥2 стула (Codex 17.08). Формы edge_nook_4/5/6 атомарные —
    торцевые стулья не «молчаливый добор». Локальный фрейм: банкетка (0,0) rot 0 — фасад +y
    (в комнату), спинка к стене (-y)."""
    NOOK_DIAG.clear()
    bench = by_role.get('банкетка')
    tbl = by_role.get('стол обеденный')
    chairs = [by_role[r] for r in sorted(by_role) if r == 'стул' or r.startswith('стул ')]
    if bench is None:
        NOOK_DIAG['reject'] = 'no_bench'
        return None
    seats_b = bench_seats(bench)
    if seats_b is None:
        NOOK_DIAG['reject'] = 'bench_capability_unknown'
        return None
    if not (getattr(bench, 'caps', None) or {}).get('dining_seat_capable'):
        NOOK_DIAG['reject'] = 'bench_not_dining_capable'   # высота сиденья не подтверждена как обеденная
        return None
    if seats_b < int(_nook_rules().get('nook_bench_min_seats', 2)):
        NOOK_DIAG['reject'] = 'bench_capacity_lt2'
        return None
    if tbl is None:
        NOOK_DIAG['reject'] = 'no_table'
        return None
    need_chairs = {'edge_nook_4': 2, 'edge_nook_5': 3, 'edge_nook_6': 4}.get(variant, 2)
    if len(chairs) < need_chairs:
        NOOK_DIAG['reject'] = 'chairs_lt2' if need_chairs == 2 else f'chairs_lt{need_chairs}'
        return None
    chairs = chairs[:need_chairs]
    if not (0.5 * bench.w_cm <= tbl.w_cm <= 1.2 * bench.w_cm):
        NOOK_DIAG.update({'reject': 'table_bench_mismatch', 'bench_w': bench.w_cm, 'table_w': tbl.w_cm})
        return None
    gap = float(_g('nook_table_bench_gap_cm', 2.0))
    b = Block(bench)
    ty = bench.d_cm / 2 + gap + tbl.d_cm / 2
    b.add(tbl, 0.0, ty, 0.0)
    far = ty + tbl.d_cm / 2                                  # свободная кромка стола
    cw = max(c.w_cm for c in chairs)
    _edge = float(_nook_rules().get('edge_per_diner_cm', 61) or 61)
    pair_ok = tbl.w_cm >= max(2 * cw + 24, 2 * _edge)
    xs = [-tbl.w_cm / 4, tbl.w_cm / 4] if pair_ok else [0.0]
    spots = [(x, far, 180.0) for x in xs][:2]
    if len(spots) < 2:                                        # узкий стол — второй стул на торец
        spots.append((tbl.w_cm / 2, ty, 270.0))
    if variant in ('edge_nook_5', 'edge_nook_6'):
        spots.append((tbl.w_cm / 2, ty, 270.0))
    if variant == 'edge_nook_6':
        spots.append((-tbl.w_cm / 2, ty, 90.0))
    for ch, (sx, sy, srot) in zip(chairs, spots):
        off = ch.d_cm / 2 + CHAIR_GAP
        dx, dy = _rt(0.0, off, srot)
        b.add(ch, sx - dx, sy - dy, srot)
    b.tpl_variant = variant          # метка формы — до поиска позиции (контракт в validate)
    NOOK_DIAG.update({'variant': variant, 'bench_seats': seats_b, 'chairs': len(chairs),
                      'total_seats': seats_b + len(chairs), 'gap_cm': gap})
    if seats_b + len(chairs) < int(_nook_rules().get('nook_min_total_seats', 4)):
        NOOK_DIAG['reject'] = 'seats_lt4'
        return None
    return _valid(b, 'dining')


def _at_window_wall(room: Room, p: Placement) -> bool:
    """Позиция спинкой к оконной стене (Q6b: запрещено — банкетке нужна глухая опора; окно — Q8)."""
    from .geometry import opening_polygon
    fp = footprint(p)
    for op in room.openings:
        if op.kind != 'window':
            continue
        if fp.distance(opening_polygon(room, op)) < 40:
            return True
    return False


def place_edge_nook(room: Room, items: list[Item], free: Polygon,
                    fixed: list[Placement] | None = None) -> list[Placement] | None:
    """Q6b: постановка уголка — банкетка спиной к ПРЯМОЙ стене (окно исключено: `allow_window_back=false`).
    Формы от большей к меньшей; валидность (проходы, дуга двери, отодвигание стульев, торец) —
    validate + `check_edge_nook_contract`."""
    if os.environ.get('LAYOUT_TEMPLATES', '1') == '0':
        return None
    by_role: dict[str, Item] = {}
    for it in items:
        by_role.setdefault(it.role, it)
    _fx = list(fixed or [])
    for variant in ('edge_nook_6', 'edge_nook_5', 'edge_nook_4'):
        b = build_edge_nook(by_role, variant=variant)
        if b is None:
            continue
        cands = [c for c in wall_candidates(room, b.anchor, free)
                 if not _at_window_wall(room, c.placement)]
        if not cands:
            NOOK_DIAG['reject'] = 'no_wall_segment'
            continue
        _st: dict = {}
        ps = _best_block(room, b, free, cands, tv=None, fixed=_fx, stats=_st)
        if ps:
            for q in ps:
                q.tpl_variant = variant
            NOOK_DIAG['placed'] = variant
            return ps
        NOOK_DIAG['reject'] = 'no_valid_position'
        NOOK_DIAG['search'] = {'cands': len(cands), 'fits': _st.get('fits'),
                               'top_hard': _st.get('first_hard')}   # объяснимость отказа
    return None


def place_decor(room: Room, items: list[Item], free: Polygon,
                fixed: list[Placement] | None = None) -> list[Placement] | None:
    """ЗОНА ДЕКОРА (последняя по приоритету, правило владельца 11.08): напольная
    зелень ставится в СВОБОДНЫЙ УГОЛ, а не вплотную к мебели — по майнингу 9013
    гостиных декор в 60–120 см от мебели встречается единицами, основная масса
    дальше 250 см. Кашпо — один предмет (в просторных до двух)."""
    if os.environ.get('LAYOUT_TEMPLATES', '1') == '0':
        return None
    plants = [it for it in items if it.role.startswith('кашпо')]
    if not plants:
        return None
    cap = 2 if room.width_cm * room.depth_cm > 32 * 10_000 else 1
    plants = plants[:cap]
    base = list(fixed or [])
    occ = [footprint(p) for p in base if p.role != 'ковёр']
    out: list[Placement] = []
    # C5 (M-C, свод №5): эркер — приоритетное место для растения. Кандидаты в
    # центре каждого эркера (спиной к наружной кромке), поверх угловых.
    from .room_map import contour_features as _cf5
    _bays = _cf5(room)[0]
    from .invariants import TEMPLATES as _CT5
    _bay_bonus = float(_CT5.get('contour_features', {}).get('bay_bonus', 25))
    for pl in plants:
        best, best_d = None, -1.0
        _bay_cands = []
        for _bg in _bays:
            bx1, by1, bx2, by2 = _bg.bounds
            for _t in (0.5, 0.2, 0.8):   # вдоль пролёта: часть ниши может быть занята
                _bx = bx1 + (bx2 - bx1) * _t
                _by = by1 + (by2 - by1) * _t
                if bx2 - bx1 >= by2 - by1:
                    _by = _bg.centroid.y
                else:
                    _bx = _bg.centroid.x
                _bay_cands.append(Placement(role=pl.role, x=_bx, y=_by,
                                            rot=180 if _by > room.depth_cm / 2 else 0,
                                            item=pl))
        # Q12 (аудит канонов): РАСТЕНИЕ У ОКНА — самостоятельный канон (17% практики по частотам
        # владельца). Кандидаты СБОКУ от проёма (не перед створкой), мимо радиатора: у угла бонус
        # света уже был, но самой позиции «у окна вне угла» не существовало.
        _win_cands = []
        for _op in [o for o in room.openings if o.kind == 'window']:
            _g = opening_polygon(room, _op)
            _wx0, _wy0, _wx1, _wy1 = _g.bounds
            _horiz = _op.wall in ('north', 'south')
            _off = (pl.w_cm / 2 + 12.0)
            _depth = pl.d_cm / 2 + 8.0
            for _sgn in (-1, +1):
                if _horiz:
                    _px = (_wx0 - _off) if _sgn < 0 else (_wx1 + _off)
                    _py = (room.depth_cm - _depth) if _op.wall == 'north' else _depth
                else:
                    _py = (_wy0 - _off) if _sgn < 0 else (_wy1 + _off)
                    _px = (room.width_cm - _depth) if _op.wall == 'east' else _depth
                _pp = Placement(role=pl.role, x=_px, y=_py,
                                rot=(180.0 if _op.wall == 'north' else 0.0) if _horiz
                                    else (270.0 if _op.wall == 'east' else 90.0), item=pl)
                if any(radiator_polygon(room, _r).intersects(footprint(_pp))
                       for _r in (room.radiators or [])):
                    continue                       # прибор не загораживаем
                _win_cands.append(_pp)
        for c in list(wall_candidates(room, pl, free)) + _bay_cands + _win_cands:
            _in_bay = isinstance(c, Placement) and c not in _win_cands
            _at_win = c in _win_cands
            if not _in_bay and not _at_win and c.kind != 'corner':
                continue                      # иначе — только углы (свод: зелень в угол)
            p = c if (_in_bay or _at_win) else c.placement
            if _at_win and not free.contains(footprint(p)):
                continue
            if _in_bay and not (free.contains(footprint(p)) or
                                any(_bg.buffer(1.0).contains(footprint(p))
                                    for _bg in _bays)):
                continue
            d = min((footprint(p).distance(o) for o in occ), default=999.0)
            if d < 60:
                continue                      # вплотную к мебели не ставим
            # МЕЖЗОННЫЕ ПРАВИЛА и здесь (баг 12.08: зона декора шла своим путём,
            # мимо общей проверки — кашпо вставало в 3 см от стеллажа)
            if not _inter_zone_ok(room, [p], base + out):
                continue
            lay = validate(room, base + out + [p])
            if any(v.severity is Severity.HARD for v in lay.violations):
                continue
            # П7 (свод §16, RHS): растению нужен свет — позиции ближе к окну лучше.
            # Дистанция до ближайшей стены с окном входит в выбор (не hard: тене-
            # выносливые существуют, жёсткость появится с light_need из обогащения).
            _light_bonus = 0.0
            _wins = [o for o in room.openings if o.kind == 'window']
            if _wins:
                from .geometry import opening_polygon as _opw
                _dw = min(footprint(p).distance(_opw(room, o)) for o in _wins)
                _light_bonus = max(0.0, 150.0 - _dw)      # ≤1.5 м от окна — бонус
            _bb = _bay_bonus if _in_bay else 0.0   # C5: растение в эркере
            _var = 'bay_plant' if _in_bay else ('window_plant' if _at_win else 'corner_plant')
            if d + _light_bonus + _bb > best_d:
                best, best_d, _best_var = p, d + _light_bonus + _bb, _var
        if best is not None:
            # прослеживаемость: декор — тоже шаблон (паспорт decor), с формой канона
            out.append(best.model_copy(update={'tpl_id': 'decor', 'tpl_version': '1.0',
                                               'tpl_variant': _best_var}))
    return out or None

# ЗОНА ПУФА УДАЛЕНА 12.08 (владелец: «зачем шаблон из одного пуфа?»). Одиночный
# предмет — не шаблон: он читался как случайный (пуф в линию с креслом, мимо ковра).
# Пуф ставится ТОЛЬКО внутри схемы посадки, где его координаты задаёт схема
# (две канонные позиции: подставка для ног перед креслом либо свободный фланг столика).
