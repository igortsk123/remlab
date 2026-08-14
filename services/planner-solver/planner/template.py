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
from .geometry import footprint, room_polygon
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

    def add(self, item: Item, x: float, y: float, rot: float) -> None:
        self.rel.append((item, x, y, rot % 360))

    def to_world(self, ax: float, ay: float, arot: float) -> list[Placement]:
        out = []
        for it, rx, ry, rrot in self.rel:
            wx, wy = _rt(rx, ry, arot)
            out.append(Placement(role=it.role, x=ax + wx, y=ay + wy,
                                 rot=(rrot + arot) % 360, item=it,
                                 tpl_id=self.tpl_id, tpl_version=self.tpl_version))
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


def _valid(b: Block | None, zone: str = 'seating') -> Block | None:
    """Схема действительна, только если прошла ИНВАРИАНТЫ своего паспорта
    (`rules/templates.json`): нет самопересечений, ножки посадочных на ковре,
    столик в досягаемости, в зоне ≥2 предмета. Не прошла — недействительна,
    каскад возьмёт следующий шаблон (правило владельца «берём другой шаблон»)."""
    if b is None:
        return None
    from .invariants import TEMPLATES as _TPL
    b.tpl_id = zone
    b.tpl_version = str((_TPL['zones'].get(zone) or {}).get('version') or '')
    why = check_block(b.to_world(0.0, 0.0, 0.0), zone)
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
        sc = seat.corner_section_cm
        edge = seat.w_cm / 2 - sc            # ближний к плечу край свободной части
        if seat.corner_left:
            fx = max(sc / 2, -edge + 32 + tw / 2)
        else:
            fx = min(-sc / 2, edge - 32 - tw / 2)
    ty = _front(seat) + gap + tt.d_cm / 2
    b.add(tt, fx, ty, 0.0)
    return ty + tt.d_cm / 2, fx, ty


RUG_TUCK = float(_g('rug_tuck_cm', 15.0))        # заход ковра под ножки посадки


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


def _add_L(b: Block, sofa: Item, other: Item) -> None:
    """Г/П-стык (правка владельца 11.08): второй диван перпендикулярно слева,
    спинкой наружу; его ближний торец — на уровне ФРОНТА первого (не спинки:
    хвост до линии спинки читался как «перекрытие зоны» на чертеже)."""
    ox = -(sofa.w_cm / 2 + L_GAP + other.d_cm / 2)
    oy = _front(sofa) + 5.0 + other.w_cm / 2
    b.add(other, ox, oy, 90.0)


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
        far, _fx, tcy = _add_coffee(b, arm1, table or by_role.get('приставной'),
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
            a3, a4 = by_role.get('кресло 3'), by_role.get('кресло 4')
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
        elif variant == 'bridge':
            # B1 (v2, веб-свод): диван смотрит на ТВ, одно кресло развёрнуто ПОД
            # УГЛОМ (45°) — мостик между медиа-зоной и камином
            # ПАРА ПОД ЗЕРКАЛЬНЫМИ УГЛАМИ (замечание владельца 11.08 + веб-свод:
            # «identical seating on each side», пара кресел — симметрия). Одно
            # кресло под углом, другое прямо — визуально неряшливо.
            _fx1 = _add_flank(b, sofa, arm1, +1, table_cy,
                              table_half_w=(max(table.w_cm, table.d_cm) / 2
                                            if table else None))
            b.rel[-1] = (arm1, b.rel[-1][1], b.rel[-1][2], 225.0)
            _add_flank(b, sofa, arm2, -1, table_cy,
                       table_half_w=(max(table.w_cm, table.d_cm) / 2 if table else None))
            b.rel[-1] = (arm2, b.rel[-1][1], b.rel[-1][2], 135.0)   # зеркально
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
        for _sx, _sy, _srt in _spots:
            if _on_axis(_sx, _sy):
                continue
            b.add(_pouf, _sx, _sy, _srt)
            if block_self_overlap(b) is None:
                break
            b.rel.pop()                      # не встал — пробуем другую позицию
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
            out.append(Candidate(placement=p, kind='middle',
                                 note=f'пара WallScore {pr.score}',
                                 topology='tv_range'))
        return out
    except Exception:
        return []


def _tv_range_candidates(room: Room, item: Item, free: Polygon) -> list:
    """Позиции дивана НА ТВ-ВИЛКЕ от стены будущего носителя (глубокие комнаты).

    Владелец 13.08: в глубокой комнате коммуникативная зона придвигается к медиа
    (дистанция просмотра в вилке диагонали), а за спинкой остаётся столовая. Даём
    позиции «спинкой в комнату» на расстоянии середины вилки от каждой из 4 стен.
    """
    from .candidates import Candidate
    from .tv import distance_range
    lo, hi, _ = distance_range(120.0)
    W, D = room.width_cm, room.depth_cm
    spots = []
    # ступени дистанции: середина вилки и верх (13.08: блок с ковром и пуфом ГЛУБЖЕ
    # одного дивана — от середины вилки фронту блока не хватало места до стены,
    # и стенка не вставала; от верха вилки — помещается блок целиком)
    for base_d in ((lo + hi) / 2, hi * 0.92):
        d_mid = base_d + item.d_cm / 2 + 40.0
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
                require_bearer: Item | None = None) -> list[Placement] | None:
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
        scored.append((score, ps, getattr(c, 'topology', '')))
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
    for _, ps, _topo in _pool:
        lay = validate(room, base + ps)
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
                lay2 = validate(room, base + ps + [bc.placement])
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
                nb_variants.append((lexo_key(0, 0, terms_nb), ps))
                if first_hard is None:
                    first_hard = [('NO_ROOM_FOR_BEARER', [require_bearer.role], None)]
                continue
        if not hards:
            terms = score_layout(room, base + ps).terms
            ok_variants.append((lexo_key(0, 0, terms), ps))
            continue
        if first_hard is None:
            first_hard = [(v.code, v.roles, v.value) for v in hards[:3]]
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


def place_template(room: Room, group_id: str, items: list[Item], free: Polygon,
                   fixed: list[Placement] | None = None) -> list[Placement] | None:
    """Разговорная зона блоком: лучший hard-чистый вариант или None (фолбэк beam)."""
    if os.environ.get('LAYOUT_TEMPLATES', '1') == '0':
        return None
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
        for g in (36.0, 32.0, 48.0):
            tries.append((by_role, g, 0.0))
        # (габариты столика НЕ подгоняем — см. правило выше про конверт слота)
        for sh in (_sh, -_sh):
            tries.append((by_role, COFFEE_GAP, sh))
        # СХЕМ БЕЗ СТОЛИКА В КАСКАДЕ НЕТ (владелец 13.08: «куда делся столик?»).
        # Столик — клей зоны (glue_rule паспорта); каскад жертвует пуфом, торшером,
        # креслом — но столик и ковёр неприкосновенны. Нет места столику — берётся
        # меньший состав ВОКРУГ него, а не зона без поверхности.
    variants = tries
    # ЭФФЕКТИВНАЯ группа (11.08): выбранная группа может требовать роль, которой в
    # сете нет (sofa_armchair без кресла) — тогда блок не собирался и сцена уходила
    # в поштучный фолбэк. Понижаем группу до реально доступного состава.
    _av = set(by_role)
    if group_id in ('sofa_2armchairs', 'sofa_4armchairs') and 'кресло 2' not in _av:
        group_id = 'sofa_armchair'
    if group_id in ('sofa_armchair', 'sectional_armchair') and 'кресло' not in _av \
            and 'пуф' not in _av:
        group_id = 'compact_sectional'
    if group_id in ('sofa_facing_sofa', 'sofa_loveseat', 'sofa_loveseat_2armchairs',
                    'two_sofas_2armchairs') and 'диван 2' not in _av:
        group_id = 'sofa_2armchairs' if 'кресло 2' in _av else (
            'sofa_armchair' if 'кресло' in _av else 'compact_sectional')
    shapes = {'sofa_4armchairs': ['default', 'u', 'pouf_table'],
              'sofa_pouf': ['default'],
              'sofa_lamp': ['default'],
              'sofa_solo': ['default'],
              'compact_sectional': ['default', 'pouf_table'],
              'sofa_2armchairs': ['default', 'bulky', 'pouf_table', 'facing',
                                  'bridge', 'tandem_r', 'tandem_l'],
              'sofa_armchair': ['default', 'pouf_table', 'facing'],
              'two_sofas_2armchairs': ['default', 'square'],
              'sofa_loveseat': ['default', 'square'],
              'sofa_loveseat_2armchairs': ['default', 'square'],
              }.get(group_id, ['default'])
    # C1 (M-C, свод №5): квадратная комната — симметричные ЦЕНТРАЛЬНЫЕ схемы первыми
    # (список приоритета — паспорт contour_features, выбор схемы = первая вставшая)
    from .invariants import TEMPLATES as _CT
    from .room_map import contour_features as _cf
    if _cf(room)[2]:
        _prio = _CT.get('contour_features', {}).get('square_scheme_priority', [])
        shapes = [s for s in _prio if s in shapes] + [s for s in shapes if s not in _prio]
    # ФОКУС-СТЕНА ОБЯЗАТЕЛЬНА (свод владельца 12.08: «стена напротив дивана не должна
    # быть пустой»). КРУГ 1 — принимаем только те позиции посадки, при которых носителю
    # ТВ остаётся чистое место. КРУГ 2 (если ни одна схема не ужилась) — ставим посадку
    # без этого требования: лучше зона, чем пустая сцена, и носитель честно уходит в
    # «не использовано».
    # ВНУТРИ каждого круга — прежние два прохода: сперва схемы с НАСТОЯЩИМ столиком,
    # затем «пуф вместо столика» (104 сцены оставались без столика, 12.08).
    global _FOCUS_LEVEL
    _rounds = (2, 1, 0) if (bearer is not None
                            and os.environ.get('LAYOUT_FOCUS_MANDATORY', '1') != '0') \
        else (0,)
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
              if room.width_cm * room.depth_cm > 40 * 10_000 or _deep:
                  cands += list(middle_candidates(room, b.anchor, free,
                                                  limit=10 if _deep else 6))
              if _deep:
                  # П1 (MASTER-tv-sofa-pair): кандидаты дивана — из генератора ПАР
                  # «медиа-блок × блок посадки» (WallScore, свод владельца §3–7).
                  # Прежние tv_range-кандидаты остаются фолбэком.
                  cands += _pair_sofa_candidates(room, b.anchor, free, tv)
                  cands += _tv_range_candidates(room, b.anchor, free)
              ps = _best_block(room, b, free, cands, tv=tv, fixed=fixed,
                               second_focus=second, require_bearer=bearer)
              if ps is not None:
                  if os.environ.get('ZONES_DEBUG'):
                      import sys as _s
                      print(f'ZDBG посадка принята: круг фокуса={_lvl} схема={shape} '
                            f'состав={sorted(br)}', file=_s.stderr, flush=True)
                  return ps
      finally:
        _FOCUS_LEVEL = 0
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
    # число стульев = сколько ЕСТЬ в сете (до предела band): лишние стулья иначе
    # оставались без зоны (экзамен 11.08: «стул 4» пропущен в 125 сценах)
    have_chairs = sum(1 for it in items if it.role == 'стул' or it.role.startswith('стул '))
    cap = 2 if usable_m2 <= 18 else (4 if usable_m2 <= 30 else 6)
    max_chairs = max(2, min(have_chairs, cap))
    # S4 (small-свод §14): каскад масштаба — если полный состав не встал, пробуем
    # столовую на 2 места, прежде чем отказаться (living не ломаем ради стола)
    _chair_steps = [max_chairs] + ([2] if max_chairs > 2 else [])
    # П5 (MASTER-tv-sofa-pair, свод §10): проверяется ЭКСПЛУАТАЦИОННАЯ зона стола —
    # прямоугольник «стол + 90 см со стороны посадок» (R&B), а не голый габарит.
    # Реализация — расширенный футпринт стола в блоке: build_dining уже ставит стулья,
    # а validate меряет отодвигание; здесь фильтр очевидно-тесных мест до перебора.
    # схемы паспорта: остров → у стены; каскад масштаба стульев (S4)
    for _nch in _chair_steps:
        b_all = build_dining(by_role, _nch, sides='all')
        if b_all is None or len(b_all.rel) < 2:
            continue
        ps = _best_block(room, b_all, free,
                         list(middle_candidates(room, b_all.anchor, free, limit=8)),
                         tv=None, fixed=fixed)
        if ps is not None:
            return ps
        b_front = build_dining(by_role, _nch, sides='front')
        if b_front is not None:
            ps = _best_block(room, b_front, free,
                             list(wall_candidates(room, b_front.anchor, free)),
                             tv=None, fixed=fixed)
            if ps is not None:
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
    for br in tries:
        b = build_storage(br, max_items=len(br), ceiling_cm=room.ceiling_cm)
        if b is None:
            continue
        for _avoid in ((True, False) if _busy else (False,)):
            cands = wall_candidates(room, b.anchor, free)
            if _avoid:                    # сперва ищем СВОБОДНУЮ стену
                cands = [c for c in cands if _wall_of(room, c.placement) not in _busy]
            ps = _best_block(room, b, free, cands, tv=None, fixed=fixed)
            if ps is not None:
                return ps
    return None


def build_reading(by_role: dict[str, Item]) -> Block | None:
    """v2.6: уголок чтения — кресло + торшер за плечом (30–40 от спинки, сбоку)
    + приставной у другого подлокотника (≤15)."""
    arm = by_role.get('кресло 3') or by_role.get('кресло')
    lamp, side = by_role.get('торшер'), by_role.get('приставной')
    ott = by_role.get('пуф')
    # E3 (свод №4, residual 130-180 → nook): аксессуаром нука может быть и пуф-
    # оттоманка перед креслом — торшер в вытянутых малых часто занят посадкой
    # (sofa_lamp), и нук не собирался при живом кресле+пуфе в банке
    if arm is None or (lamp is None and side is None and ott is None):
        return None
    b = Block(arm)
    if lamp is None and side is None and ott is not None:
        b.add(ott, 0.0, arm.d_cm / 2 + ott.d_cm / 2 + 10, 0.0)
    if lamp is not None:
        # сбоку и чуть сзади — свет через плечо (веб-свод 11.08 подтвердил)
        b.add(lamp, arm.w_cm / 2 + lamp.w_cm / 2 + 12, -arm.d_cm / 2 + 8, 0.0)
    if side is not None:
        b.add(side, -(arm.w_cm / 2 + side.w_cm / 2 + 8), 5.0, 0.0)
    return _valid(b, 'reading')


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


def build_media_fireplace(by_role: dict[str, Item]) -> Block | None:
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
    # он «отходит» от неё на разницу глубин и ловит NOT_AT_WALL
    b.add(fp, bearer.w_cm / 2 + 40 + fp.w_cm / 2, -(bearer.d_cm - fp.d_cm) / 2, 0.0)
    return _valid(b, 'fireplace')


def place_media_fireplace(room: Room, items: list[Item], free: Polygon,
                          fixed: list[Placement] | None = None) -> list[Placement] | None:
    """Ставится ДО отдельных медиа/каминной зон: когда в комплекте есть и носитель,
    и камин, они должны делить одну фасадную стену, а не конкурировать за стены."""
    if os.environ.get('LAYOUT_TEMPLATES', '1') == '0':
        return None
    by_role: dict[str, Item] = {}
    for it in items:
        by_role.setdefault(it.role, it)
    seat = next((p for p in (fixed or []) if p.role == 'диван'), None)
    b = build_media_fireplace(by_role)
    if b is None:
        return None
    return _best_block(room, b, free, wall_candidates(room, b.anchor, free),
                       tv=None, fixed=fixed, axis_seat=seat)


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
        _inview = _view_filter(_cands, seat, max_deg=float(_g('fireplace_view_max_deg', 60.0)),
                               min_dist_cm=float(_g('fireplace_min_dist_cm', 90.0)))
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


def _corner_candidates(room: Room, item: Item, free: Polygon) -> list:
    """Кандидаты «по диагонали в углу» (заявка владельца 12.08 + веб-свод: угловое
    диагональное размещение — рабочий приём, когда прямых стен не осталось).
    Предмет ставится под 45° спинкой в угол."""
    from .candidates import Candidate
    out = []
    w, d = item.w_cm, item.d_cm
    diag = (w / 2) * math.sin(math.radians(45)) + (d / 2) * math.cos(math.radians(45))
    for cx, cy, rot in ((0, 0, 45), (room.width_cm, 0, 315),
                        (0, room.depth_cm, 135), (room.width_cm, room.depth_cm, 225)):
        r = math.radians(rot)
        x = cx + math.sin(r) * (diag + 6)
        y = cy + math.cos(r) * (diag + 6)
        p = Placement(role=item.role, x=x, y=y, rot=float(rot), item=item)
        fp = footprint(p)
        if free.intersection(fp).area >= fp.area * 0.97:
            out.append(Candidate(p, 'corner', 'диагональ в углу'))
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
    by_role: dict[str, Item] = {}
    for it in items:
        by_role.setdefault(it.role, it)
    seat = next((p for p in (fixed or []) if p.role == 'диван'), None) or         next((p for p in (fixed or []) if p.role == 'кресло'), None)
    # ЛЕСТНИЦА НОСИТЕЛЕЙ (владелец 13.08: «шаблон со стенкой не лезет — автоматом
    # выбирать с тумбой»): при обоих носителях в банке сперва вся попытка со СТЕНКОЙ,
    # не встала ни в одном круге — повтор с ТУМБОЙ (стенка исключается из вида).
    if 'стенка' in by_role and 'тв-тумба' in by_role:
        ps = place_media(room, [it for it in items if it.role != 'тв-тумба'],
                         free, fixed=fixed, top=top, relaxed=relaxed)
        if ps is not None:
            return ps
        return place_media(room, [it for it in items if it.role != 'стенка'],
                           free, fixed=fixed, top=top, relaxed=relaxed)
    global _MEDIA_TOE_RELAXED
    # Ступени: обычный заход ковра под носитель (15 см) → без флангов → КРАЙНИЙ
    # СЛУЧАЙ: ковёр уходит под медиа-зону глубже (решение владельца 12.08).
    for relaxed in (False, True):
        _MEDIA_TOE_RELAXED = relaxed
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
                    # ЦЕНТР — ПОРОГ, А НЕ БОНУС (свод владельца 12.08): сперва только
                    # позиции в оси взгляда (смещение ≤ FOCUS_OFFSET_MAX_CM); если таких
                    # нет вовсе — весь список. Раньше центровка была слагаемым скора и
                    # проигрывала прочим штрафам: 163 сцены со смещением >40 см.
                    # ПОСЛЕДНЯЯ ПОПЫТКА (правило владельца 12.08: «тумба или стенка
                    # должна быть везде»): в relaxed-режиме центровка не требуется —
                    # лучше носитель сбоку, чем сцена вообще без ТВ.
                    _strict = [] if relaxed else _axis_filter(_cands, seat)
                    ps = _best_block(room, b, free, _strict or _cands, top=top,
                                     tv=None, fixed=fixed, axis_seat=seat)
                    if ps is None and _strict:
                        ps = _best_block(room, b, free, _cands, top=top,
                                         tv=None, fixed=fixed, axis_seat=seat)
                    if ps is None:
                        continue
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


def build_quiet(by_role: dict[str, Item]) -> Block | None:
    """B2 (v2, веб-свод «watch zone + quiet zone»): вторая подзона просторных
    гостиных — пара кресел визави + приставной между ними; ставится у камина
    или свободного угла ПОСЛЕ главной зоны."""
    a1 = by_role.get('кресло 3')
    a2 = by_role.get('кресло 4')
    if not (a1 and a2):
        return None
    b = Block(a1)
    side = by_role.get('приставной') or by_role.get('столик')
    gap = (side.d_cm if side else 60.0)
    b.add(a2, 0.0, a1.d_cm / 2 + gap + 40 + a2.d_cm / 2, 180.0)
    if side is not None:
        b.add(side, 0.0, a1.d_cm / 2 + (gap + 40) / 2, 0.0)
    return _valid(b, 'quiet')


def place_quiet(room: Room, items: list[Item], free: Polygon,
                fixed: list[Placement] | None = None) -> list[Placement] | None:
    """Тихая зона — только в просторных комнатах (45+ м²) и только если главная
    зона уже стоит: иначе кресла нужнее в основной группе."""
    if os.environ.get('LAYOUT_TEMPLATES', '1') == '0':
        return None
    if room.width_cm * room.depth_cm < 45 * 10_000:
        return None
    by_role: dict[str, Item] = {}
    for it in items:
        by_role.setdefault(it.role, it)
    b = build_quiet(by_role)
    if b is None:
        return None
    return _best_block(room, b, free, wall_candidates(room, b.anchor, free),
                       tv=None, fixed=fixed)


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
            _bx, _by = _bg.centroid.x, _bg.centroid.y
            _bay_cands.append(Placement(role=pl.role, x=_bx, y=_by,
                                        rot=0 if _by > room.depth_cm / 2 else 180,
                                        item=pl))
        for c in list(wall_candidates(room, pl, free)) + _bay_cands:
            _in_bay = isinstance(c, Placement)
            if not _in_bay and c.kind != 'corner':
                continue                      # только углы (свод: зелень в угол)
            p = c if _in_bay else c.placement
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
            if d + _light_bonus + _bb > best_d:
                best, best_d = p, d + _light_bonus + _bb
        if best is not None:
            # прослеживаемость: декор — тоже шаблон (паспорт decor)
            out.append(best.model_copy(update={'tpl_id': 'decor', 'tpl_version': '1.0'}))
    return out or None

# ЗОНА ПУФА УДАЛЕНА 12.08 (владелец: «зачем шаблон из одного пуфа?»). Одиночный
# предмет — не шаблон: он читался как случайный (пуф в линию с креслом, мимо ковра).
# Пуф ставится ТОЛЬКО внутри схемы посадки, где его координаты задаёт схема
# (две канонные позиции: подставка для ног перед креслом либо свободный фланг столика).
