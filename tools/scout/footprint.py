#!/usr/bin/env python3
"""ОДНО ПРАВИЛО «РАЗМЕР ИЗВЕСТЕН» для сборки, лечения, экспорта, сцены и демо (план stock-and-dims-honesty, Р1).

Правило владельца (03.09): размер НИКОГДА не придумывается. Если у напольного предмета нет ширины и
глубины (или диаметра) из каталога — предмет не расставляется, а витрина честно пишет «размеры не
указаны магазином». Достраивать можно только по мешу с калибровкой (`mesh_dims.py`) и с пометкой.

До этого размеры выдумывали пять мест независимо: compose2 (диван 100 см, 0,16 м² торшеру/кашпо/камину),
solver_run (типовые 190×95, угловой 150), scene_build (100), export_plans_ai (40), flat215_demo (меш без
калибровки, «квадратное основание» d=w, старая раскладка). Теперь все спрашивают здесь.

  footprint.py --selftest
"""
import sys

# Напольные роли: их место на полу решает footprint, без него предмет расставить нельзя.
FLOOR_ROLES = frozenset({'диван', 'кресло', 'пуф', 'столик', 'тв-тумба', 'комод', 'стеллаж', 'витрина',
                         'стенка', 'стол обеденный', 'стол', 'стул', 'камин', 'кашпо', 'торшер', 'шкаф',
                         'банкетка', 'растение'})
# Роли, которым footprint не положен по природе (висят/лежат/на поверхности) — их не гейтим.
NON_FLOOR_ROLES = frozenset({'ковёр', 'лампа', 'люстра', 'ваза', 'статуэтка', 'плед', 'подушка', 'зеркало',
                             'полка', 'часы', 'шторы', 'бра', 'картина'})


def base_role(role: str) -> str:
    """«кресло 2» → «кресло»."""
    return (role or '').rsplit(' ', 1)[0] if (role or '').rsplit(' ', 1)[-1].isdigit() else (role or '')


def is_floor(role: str) -> bool:
    return base_role(role) in FLOOR_ROLES


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def footprint_known(item: dict | None) -> bool:
    """Ширина И глубина известны, либо диаметр. Ключи: w/d/dia или w_cm/d_cm/dia_cm."""
    if not item:
        return False
    w = _num(item.get('w', item.get('w_cm')))
    d = _num(item.get('d', item.get('d_cm')))
    dia = _num(item.get('dia', item.get('dia_cm')))
    return bool((w and d) or dia)


def footprint_m2(item: dict | None):
    """Площадь на полу, м² — только из известных осей; None, если размер неизвестен."""
    if not footprint_known(item):
        return None
    w = _num(item.get('w', item.get('w_cm')))
    d = _num(item.get('d', item.get('d_cm')))
    dia = _num(item.get('dia', item.get('dia_cm')))
    if w and d:
        return w * d / 10000.0
    import math
    return math.pi * (dia / 200.0) ** 2


def wd(item: dict | None) -> tuple[float, float] | None:
    """(Ш, Г) в см для расстановки; круглый предмет — (dia, dia). None — размер неизвестен."""
    if not footprint_known(item):
        return None
    w = _num(item.get('w', item.get('w_cm')))
    d = _num(item.get('d', item.get('d_cm')))
    dia = _num(item.get('dia', item.get('dia_cm')))
    if w and d:
        return w, d
    return dia, dia


class DimsUnknown(ValueError):
    """Контракт: напольный предмет без footprint не должен доходить до солвера/сцены/экспорта."""


def require(item: dict | None, role: str) -> tuple[float, float]:
    """(Ш, Г) или DimsUnknown — вместо молчаливого дефолта."""
    r = wd(item)
    if r is None:
        raise DimsUnknown(f'{role}: размер не указан магазином (w={(item or {}).get("w")}, '
                          f'd={(item or {}).get("d")}, dia={(item or {}).get("dia")}) — предмет не расставляется')
    return r


def _selftest() -> int:
    bad = 0
    cases = [
        ({'w': 200, 'd': 90}, True), ({'w': 200}, False), ({'dia': 60}, True), ({'w': 200, 'd': 0}, False),
        ({'w_cm': 120, 'd_cm': 60}, True), ({}, False), (None, False), ({'w': '200', 'd': '95.5'}, True),
    ]
    for it, want in cases:
        if footprint_known(it) != want:
            bad += 1; print(f'  FAIL footprint_known {it}: ожидалось {want}')
    if wd({'dia': 60}) != (60.0, 60.0) or wd({'w': 200, 'd': 90}) != (200.0, 90.0) or wd({'w': 200}) is not None:
        bad += 1; print('  FAIL wd')
    if abs((footprint_m2({'w': 200, 'd': 100}) or 0) - 2.0) > 1e-9 or footprint_m2({'w': 200}) is not None:
        bad += 1; print('  FAIL footprint_m2')
    try:
        require({'w': 200}, 'диван'); bad += 1; print('  FAIL require не поднял DimsUnknown')
    except DimsUnknown:
        pass
    if not is_floor('кресло 2') or is_floor('люстра') or base_role('стул 3') != 'стул':
        bad += 1; print('  FAIL роли')
    print(f'footprint selftest: случаев {len(cases) + 4}, ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else (print(__doc__) or 0))
