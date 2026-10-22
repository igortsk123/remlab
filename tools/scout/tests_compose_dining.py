#!/usr/bin/env python3
"""СТОЛОВАЯ В МАЛЫХ ПОЛОСАХ — одно правило ёмкости для окна стула и обрезки (T-20261022-21/1).

ЗАЧЕМ. 22.10 в кандидате банка не стало столовой ни в одной из 18 ячеек 14-16: окно подбора стула считалось на 4 стула
(`QTY['стул']`), а в комнате < 22 м² ставится 2 (ёмкость столовой). Из каталога ушли маленькие стулья (≤0,188 м²) — окно
опустело, правило R3 «стол ⇔ стулья» молча сняло стол. `compose2` импортировать нельзя (импорт = полная сборка), поэтому
проверяем исходник: правило ёмкости — одна функция, ею пользуются окно стула и обрезка, снятый R3 стол пишется в gaps.

  python3 tests_compose_dining.py --selftest
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, 'compose2.py'), encoding='utf-8').read()


def _func(name: str):
    tree = ast.parse(SRC)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            ns: dict = {}
            exec(compile(ast.Module(body=[node], type_ignores=[]), 'compose2.py', 'exec'), ns)  # noqa: S102 — своя функция
            return ns[name]
    raise KeyError(name)


def _const(name: str):
    for node in ast.parse(SRC).body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


def chair_window(m2: float, share: tuple, qty: int) -> tuple:
    """Окно площади одного стула — та же арифметика, что `pick2` (`zone_m2·доля/100/qty`, допуск ×0.75…×1.25)."""
    z = min(m2, 30.0)
    return z * share[0] / 100 / qty * 0.75, z * share[1] / 100 / qty * 1.25


def _selftest() -> int:
    bad = 0

    def ok(name, cond, extra=''):
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
        bad += 0 if cond else 1
    cap = _func('dining_capacity')
    ok('ёмкость столовой по площади: 2 / 4 / 6', (cap(15), cap(18.5), cap(23), cap(44), cap(45), cap(57)) == (2, 2, 4, 4, 6, 6))
    qty = _const('QTY')
    ok('окно стула — на стулья, которые встанут: min(QTY, ёмкость)',
       "q=min(QTY['стул'],dining_capacity(m2))" in SRC.replace(' ', ''), 'нет min(QTY, dining_capacity) у роли «стул»')
    ok('обрезка состава — то же правило', '_seats_cap = dining_capacity(m2)' in SRC)
    ok('ёмкость больше нигде не считается своими числами', SRC.count('2 if m2 < 22 else') == 1)
    lo, hi = chair_window(15, (1.5, 4), min(qty['стул'], cap(15)))
    ok('14-16: обычный стул 45×50 (0,225 м²) входит в окно', lo <= 0.225 <= hi, (lo, hi))
    lo4, hi4 = chair_window(15, (1.5, 4), qty['стул'])
    ok('прежнее окно «на 4 стула» отсекало его — регресс-причина 22.10', not (lo4 <= 0.225 <= hi4), (lo4, hi4))
    ok('снятый R3 стол пишется в gaps (пробел виден)', "coverage_gap: стол обеденный" in SRC and '_r3_table_gap=True' in SRC)
    print(f'tests_compose_dining selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest())
