"""Инварианты шаблонов — машинная проверка правил схемы (ADR template-integrity, 12.08).

Зачем: правила шаблонов жили в комментариях, и солвер систематически их нарушал —
ковёр без кресел, пуф на столике, три предмета хранения в ряд, ужатые «под место»
габариты. Комментарий проверить нельзя; эти функции — можно.

Проверки идут ДО поиска места в комнате (на инстансе схемы) и ПОСЛЕ расстановки
(на итоговом наборе). Схема, не прошедшая свои инварианты, недействительна —
каскад берёт СЛЕДУЮЩИЙ шаблон, а не ломает текущий.

Паспорта и обоснования: `rules/templates.json`.
"""
from __future__ import annotations

import json
import os

from .geometry import footprint
from .models import Item, Placement

_RULES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'rules', 'templates.json')
with open(_RULES_PATH, encoding='utf-8') as _f:
    TEMPLATES = json.load(_f)

RUG_ROLE = 'ковёр'
SEAT_ROLES = ('диван', 'кресло')
_TUCK_MIN_SHARE = 0.02          # ≥2% футпринта посадочного на ковре = ножки заходят
def _table_min_cm() -> float:
    """Нижний порог «диван↔столик» — ИЗ ОДНОГО ИСТОЧНИКА с движком (occupancy,
    самый мягкий band). Своё число 38 конфликтовало с hard-вилкой 30-45 и роняло
    схемы, которые движок считает законными (set6-long, 12.08)."""
    try:
        from .rules import distances
        vals = [v[0] for v in distances().get('sofa_table_cm', {}).values()
                if isinstance(v, list) and v]
        return float(min(vals)) if vals else 30.0
    except Exception:
        return 30.0


_TABLE_MIN_CM = _table_min_cm()   # hard-порог столика (паспорт: table_reach_all_seats)


def _base(role: str) -> str:
    return role.split(' ')[0]


def _tucked_pair(r1: str, r2: str) -> bool:
    """Задвинутый стул у обеденного стола — норма, а не пересечение."""
    return {_base(r1), _base(r2)} == {'стол обеденный', 'стул'}


def self_overlap(ps: list[Placement]) -> tuple[str, str] | None:
    """no_self_overlap: предметы схемы не налезают друг на друга."""
    real = [p for p in ps if _base(p.role) != RUG_ROLE]
    fps = [footprint(p) for p in real]
    for i, fa in enumerate(fps):
        for j in range(i + 1, len(fps)):
            if _tucked_pair(real[i].role, real[j].role):
                continue
            if fa.intersection(fps[j]).area > 1.0:
                return (real[i].role, real[j].role)
    return None


def seats_off_rug(ps: list[Placement]) -> list[str]:
    """seats_front_legs_on_rug: посадочные, не достающие до ковра (канон front-legs)."""
    rugs = [p for p in ps if _base(p.role) == RUG_ROLE]
    if not rugs:
        return []
    rf = footprint(rugs[0])
    out = []
    for p in ps:
        if _base(p.role) not in SEAT_ROLES:
            continue
        f = footprint(p)
        if f.intersection(rf).area < _TUCK_MIN_SHARE * f.area:
            out.append(p.role)
    return out


def seats_out_of_table_reach(ps: list[Placement]) -> list[str]:
    """table_reach_all_seats: посадочный ближе hard-порога к столику (колени).

    Г-диван исключён: столик у секционного дивана стоит ВНУТРИ буквы Г, и канон мерит
    зазор от фронта прямой секции, а не от угла-шезлонга — тот законно ближе. Проверка
    по всему полигону роняла схему у каждого Г-дивана (set7-bay, 12.08).
    """
    tables = [p for p in ps if _base(p.role) == 'столик']
    if not tables:
        return []
    tf = footprint(tables[0])
    return [p.role for p in ps
            if _base(p.role) in SEAT_ROLES
            and not (p.item is not None and getattr(p.item, 'corner', False))
            and footprint(p).distance(tf) < _TABLE_MIN_CM]


def too_few_items(ps: list[Placement], minimum: int = 2) -> bool:
    """min_composition: зона из одного предмета — не шаблон."""
    return len(ps) < minimum


def phantom_dimensions(ps: list[Placement], source: dict[str, Item]) -> list[str]:
    """sku_dimensions_intact: габарит поставленного == габарит SKU из сета.

    Поворот допустим (ковёр кладут вдоль другой оси), поэтому сравниваем
    неупорядоченную пару (ширина, глубина) с точностью до 1 см.
    """
    bad = []
    for p in ps:
        src = source.get(p.role) or source.get(_base(p.role))
        if src is None or p.item is None:
            continue
        got = sorted((round(p.item.w_cm), round(p.item.d_cm)))
        want = sorted((round(src.w_cm), round(src.d_cm)))
        if got != want:
            bad.append(f'{p.role}: {got[1]}x{got[0]} вместо {want[1]}x{want[0]}')
    return bad


def storage_zones_ok(ps: list[Placement], max_items: int = 2) -> bool:
    """Правило владельца: не более двух предметов хранения в одной зоне."""
    roles = tuple(TEMPLATES['zones']['storage']['required'][0].split('|'))
    return sum(1 for p in ps if _base(p.role) in roles) <= max_items


def check_block(ps: list[Placement], zone: str = 'seating') -> str | None:
    """Все инварианты паспорта зоны на ИНСТАНСЕ схемы. Возвращает причину отказа."""
    inv = set(TEMPLATES['zones'].get(zone, {}).get('invariants') or ())
    if 'no_self_overlap' in inv:
        ov = self_overlap(ps)
        if ov:
            return f'самопересечение «{ov[0]}» × «{ov[1]}»'
    if 'min_composition' in inv and too_few_items(ps):
        return 'в зоне меньше двух предметов'
    if 'seats_front_legs_on_rug' in inv:
        off = seats_off_rug(ps)
        if off:
            return f'мимо ковра: {", ".join(off)}'
    if 'table_reach_all_seats' in inv:
        near = seats_out_of_table_reach(ps)
        if near:
            return f'ближе {_TABLE_MIN_CM:.0f} см к столику: {", ".join(near)}'
    return None
