#!/usr/bin/env python3
"""ВОРОТА «БЕЗ РАКУРСОВ НЕ ВЫКЛАДЫВАЕМ» (T-20261113-17/2, П1.59; владелец TG 1545: «/demo тормозит… это критично»).

ПОЧЕМУ. Сборка витрины пишет данные в два шага: сначала варианты, потом `tools/flat3d/demo-cams.mjs` дописывает каждому пару
ракурсов `v.cams` (`flat215_demo.py:demo_cams`). Шаг ракурсов не валит сборку: не уложился в срок (при загруженной DEV — реально) —
WARN:demo_cams, и витрина уезжала БЕЗ ракурсов. Тогда пару считает сам телефон, в главном потоке, при старте и при каждом окне
комнаты (`index.html:defaultCams` → `camPair`): замер 13.11 на данных между двумя шагами — ОДНА задача 56 с при процессоре ×4,
первый экран 61 с вместо 6 (`~/remlab-logs/t17-1113/prof1-0900/B0.prof.json`). Тур собирает ракурсы своим шагом с тем же исходом
(`trial_bundle.py:_cams_run` → WARN:trial_cams «ракурсы считает страница»).

ПРАВИЛО (одно на витрину и туры). Вариант с мебелью — не `pending` и не пустая комната тура (`EMPTY_STATES`: у них ракурсов не
бывает по построению) — обязан нести пару ракурсов: список из двух точек с числовыми `x`, `y`. Нет вариантов вовсе — тоже отказ (такая витрина пуста).
  • витрина: `publish_demo.sh` зовёт `--check <demo-data.json>` до съёмки и упаковки; отказ — код 1, на проде прежняя витрина,
    строки `ОТКАЗ:cams_gate` и `DIGEST:!` (важная строка ночной сводки, `refresh_digest.py`); ночь проверяет то же шагом
    `cams_gate` ДО платной досъёмки фото (`refresh_daily.sh`);
  • туры: перевыпуск (`tools/floorplan/reissue.py:one`) не публикует новую версию, где ракурсы ПОТЕРЯНЫ — вариант был с парой в
    прежней версии и стал без неё (`lost`); тур остаётся на прежней версии, строка refused/no_cams. Варианты, у которых пары не было и
    раньше, тур не держат: прежняя версия не лучше, а перевыпуск несёт другие правки.
Лечится пересборкой (`flat215_demo.py`, шаг demo_cams); обхода нет.

  python3 tools/scout/cams_gate.py --check <demo-data.json>
  python3 tools/scout/cams_gate.py --selftest
"""
from __future__ import annotations

import json
import sys


def _pair_ok(cams) -> bool:
    num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)  # noqa: E731
    return isinstance(cams, list) and len(cams) == 2 and all(isinstance(c, dict) and num(c.get('x')) and num(c.get('y')) for c in cams)


EMPTY_STATES = ('pending', 'refused', 'not_furnished')   # комнаты тура без мебели (`trial_bundle.py:_empty_variant`): `cams: []` по построению


def included(v: dict) -> bool:
    """Вариант с мебелью на показ: не `pending` и не пустая комната тура (подбор идёт, отказ, «без мебели»). У витрины поля
    `furniture_state` нет — включены все, кроме `pending`."""
    return isinstance(v, dict) and not v.get('pending') and v.get('furniture_state') not in EMPTY_STATES


def missing(data: dict) -> list[str]:
    """id включённых вариантов без пары ракурсов."""
    return [str(v.get('id') or f'#{i}') for i, v in enumerate(data.get('variants') or [])
            if included(v) and not _pair_ok(v.get('cams'))]


def lost(new: dict, old: dict) -> list[str]:
    """id вариантов, у которых пара ракурсов БЫЛА в прежней версии и пропала в новой (перевыпуск тура)."""
    had = {str(v.get('id')) for v in (old.get('variants') or []) if isinstance(v, dict) and _pair_ok(v.get('cams'))}
    return [m for m in missing(new) if m in had]


def check(data: dict) -> tuple[bool, list[str]]:
    """→ (можно выкладывать, строки вывода)."""
    vs = data.get('variants') if isinstance(data, dict) else None
    if not isinstance(vs, list) or not vs:
        why = 'в данных нет вариантов'
        return False, [f'ОТКАЗ:cams_gate: {why} — витрина не выложена, на проде прежняя',
                       f'DIGEST:!демо не опубликовано: {why} — на проде прежняя витрина; пересоберите flat215_demo.py']
    m = missing(data)
    if m:
        ids = ', '.join(m[:8]) + (f' и ещё {len(m) - 8}' if len(m) > 8 else '')
        return False, [f'ОТКАЗ:cams_gate: у {len(m)} из {len(vs)} вариантов нет ракурсов ({ids}) — телефон считал бы их сам, '
                       'зависая на десятки секунд; витрина не выложена, на проде прежняя. Лечится пересборкой flat215_demo.py '
                       '(шаг demo_cams: строка WARN:demo_cams в её выводе — причина)',
                       f'DIGEST:!демо не опубликовано: у {len(m)} вариантов нет ракурсов (шаг demo_cams) — на проде прежняя витрина']
    n = sum(1 for v in vs if included(v))
    return True, [f'cams_gate: OK — ракурсы у {n} из {n} включённых вариантов']


def _selftest() -> int:
    bad = []
    pair = [{'x': 10, 'y': 20}, {'x': 300, 'y': 200.5}]

    def ok(c, m):
        print(('ok   ' if c else 'FAIL ') + m)
        if not c:
            bad.append(m)
    good = {'variants': [{'id': 'a', 'cams': pair}, {'id': 'b', 'cams': pair}, {'id': 'p', 'pending': True, 'cams': []},
                         {'id': 'r', 'furniture_state': 'refused', 'cams': []}, {'id': 'n', 'furniture_state': 'not_furnished', 'cams': []}]}
    ok(check(good)[0] and missing(good) == [], 'все с мебелью — с парой; pending / отказ / без мебели без пары — можно')
    ok(missing({'variants': [{'id': 'w', 'furniture_state': 'awaiting_check'}]}) == ['w'], 'ждёт приёмки, но с мебелью — пара нужна')
    for why, v in (('нет поля', {'id': 'b'}), ('пустой список', {'id': 'b', 'cams': []}), ('одна точка', {'id': 'b', 'cams': pair[:1]}),
                   ('точка без чисел', {'id': 'b', 'cams': [pair[0], {'x': '1', 'y': 2}]})):
        d = {'variants': [{'id': 'a', 'cams': pair}, v]}
        c, lines = check(d)
        ok(not c and missing(d) == ['b'] and any(x.startswith('DIGEST:!') for x in lines), f'{why} — отказ, строка в сводку')
    ok(not check({'variants': []})[0] and not check({})[0] and not check([])[0], 'нет вариантов — отказ')
    old = {'variants': [{'id': 'a', 'cams': pair}, {'id': 'b'}]}
    new = {'variants': [{'id': 'a'}, {'id': 'b'}, {'id': 'c', 'cams': pair}]}
    ok(lost(new, old) == ['a'], 'тур: потеряна пара только у «a» (у «b» не было и раньше)')
    ok(lost(old, old) == [], 'тур: прежняя версия против себя — потерь нет')
    ok(lost({'variants': [{'id': 'a', 'furniture_state': 'refused', 'cams': []}]}, old) == [],
       'тур: комната ушла в отказ (мебели нет) — это не потеря ракурсов')
    print('cams_gate selftest:', 'OK' if not bad else f'FAIL ({len(bad)})')
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if argv == ['--selftest']:
        return _selftest()
    if len(argv) == 2 and argv[0] == '--check':
        try:
            with open(argv[1], encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            print(f'ОТКАЗ:cams_gate: данные не читаются ({type(e).__name__}) — витрина не выложена; пересоберите flat215_demo.py')
            return 1
        good, lines = check(data)
        print('\n'.join(lines))
        return 0 if good else 1
    print('ключи: --check <demo-data.json> | --selftest', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
