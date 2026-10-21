#!/usr/bin/env python3
"""Ворота фото и меша первичной сборки `compose2` — fail-closed (план conv-13 п.2).

ЗАЧЕМ. Сборщик проверял фото (`img_alive`, `slot_contract.photo_ok`) и меш (`slot_contract.mesh_ok`) внутри
`try/except: pass`: упала проверка — товар проходил. Ночной валидатор `sets_incremental --contracts` при сбое того же
предиката товар НЕ пускает, поэтому свежая сборка уходила в банк с позициями, которые валидатор потом массово менял.
Теперь сбой проверки = товар не берём, а сколько раз и какая проверка падала — строка в журнале сборки (`summary`).

ЖИВОСТЬ ФОТО — ТОТ ЖЕ ПРЕДИКАТ, ЧТО У КОНТРАКТА (`sets_incremental._slot_ok` → `img_alive.alive_now`; T-20261021-09).
Сборка спрашивала мягкий `alive`: непроверенное фото — «живое». Пересборка 21.10 взяла комод с мёртвым фото (в кэше
записи не было) в 7 сетов, а сухой контракт тут же его снимал. Теперь непроверенное проверяется сразу и ложится в кэш.

  python3 compose_gates.py --selftest
"""
import collections
import sys

FAILS: collections.Counter = collections.Counter()   # {«какая проверка: класс ошибки»: сколько раз}


def admit(sku: str, img: str | None) -> str | None:
    """None — товар годен по фото и мешу; иначе причина отказа. Сбой проверки — отказ и счёт в `FAILS`."""
    if not img:
        return 'нет фото'
    try:
        from img_alive import alive_now
        if not alive_now(img):
            return 'фото мёртвое'
    except Exception as e:  # noqa: BLE001 — fail-closed, считаем
        FAILS[f'живость фото: {type(e).__name__}'] += 1
        return 'сбой проверки фото'
    try:
        from slot_contract import photo_ok
        if not photo_ok(sku, context='new'):
            return 'фото негодное'
    except Exception as e:  # noqa: BLE001
        FAILS[f'пригодность фото: {type(e).__name__}'] += 1
        return 'сбой проверки фото'
    try:
        # Готовность представления (Codex P0-4): без неё MESH_GATE_PHASE=hard_new не действовал в ПЕРВИЧНОЙ сборке
        from slot_contract import mesh_ok
        if not mesh_ok(sku):
            return 'нет меша'
    except Exception as e:  # noqa: BLE001
        FAILS[f'меш: {type(e).__name__}'] += 1
        return 'сбой проверки меша'
    return None


def summary() -> str:
    n = sum(FAILS.values())
    if not n:
        return 'ворота фото/меша: сбоев проверки 0'
    return (f'WARN:compose_gate_fail: сбоев проверки {n} — эти товары НЕ взяты: '
            + ', '.join(f'{k} ×{v}' for k, v in FAILS.most_common()))


def _selftest() -> int:
    import types
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name)
        bad += 0 if cond else 1

    def boom(*a, **k):
        raise RuntimeError('нет базы')

    saved = {m: sys.modules.get(m) for m in ('img_alive', 'slot_contract')}

    def fake(alive=lambda u: True, photo=lambda s, context=None: True, mesh=lambda s: True):
        sys.modules['img_alive'] = types.SimpleNamespace(alive_now=alive, alive=lambda u, unknown=True: True)
        sys.modules['slot_contract'] = types.SimpleNamespace(photo_ok=photo, mesh_ok=mesh)
        FAILS.clear()

    try:
        fake()
        ok('всё годно — товар берём', admit('1:a', '//img') is None and summary().endswith('0'))
        ok('нет фото — отказ', admit('1:a', None) == 'нет фото')
        fake(alive=lambda u: False)
        ok('мёртвое фото по строгой проверке (как у контракта `_slot_ok`) — отказ, даже если мягкий `alive` «жив»',
           admit('1:a', '//img') == 'фото мёртвое' and not FAILS)
        fake(alive=boom)
        ok('сбой проверки живости — отказ и счёт', admit('1:a', '//img') == 'сбой проверки фото'
           and FAILS['живость фото: RuntimeError'] == 1)
        fake(photo=boom)
        ok('сбой photo_ok — отказ и счёт', admit('1:a', '//img') == 'сбой проверки фото' and sum(FAILS.values()) == 1)
        fake(mesh=boom)
        r = admit('1:a', '//img'), admit('1:b', '//img')
        ok('сбой mesh_ok — отказ, счёт по каждому товару, громкая строка журнала',
           r == ('сбой проверки меша',) * 2 and FAILS['меш: RuntimeError'] == 2 and summary().startswith('WARN:'))
        fake(mesh=lambda s: False)
        ok('нет меша — отказ без счёта сбоя', admit('1:a', '//img') == 'нет меша' and not FAILS)
        sys.modules['slot_contract'] = types.SimpleNamespace()     # модуль без функций — ImportError
        FAILS.clear()
        ok('нет функции проверки — отказ (а не пропуск)', admit('1:a', '//img') == 'сбой проверки фото')
    finally:
        for m, v in saved.items():
            if v is None:
                sys.modules.pop(m, None)
            else:
                sys.modules[m] = v
        FAILS.clear()
    print(f'compose_gates selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else 0)
