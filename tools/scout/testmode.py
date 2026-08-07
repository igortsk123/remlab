"""ТЕСТОВЫЙ РЕЖИМ конвейера сетов — один источник правды (владелец 2026-08-07).

Боевой режим (по умолчанию, ничего не задано): все 126 сетов — крон работает только так.
Тестовый: `SCOUT_TEST=1` — конвейер работает на референсной десятке (та, что на странице
/test/layout10/): пересборка/судья/перегон/страница за минуты вместо часов, БЕЗ платы за
остальные 116. Свой набор: `SETS_ONLY="1,5,9"` (работает и без SCOUT_TEST).

Правила: непересобираемые сеты копируются из прежнего sets3.json и УЧАСТВУЮТ в реестре
разнообразия; судья НЕ зовёт модель для прочих сетов (деньги); лечение выбывших (`--heal`)
тест-режим игнорирует — наличие чинится всегда и везде.

Одна команда на итерацию: `bash test_pipeline.sh` (compose → judge → check → страница).
"""
import os

REFERENCE_TEN = (3, 17, 25, 33, 47, 62, 76, 91, 104, 121)


def is_test() -> bool:
    return os.environ.get('SCOUT_TEST') == '1'


def only() -> set[int] | None:
    """Номера сетов для обработки; None = все (боевой режим)."""
    raw = os.environ.get('SETS_ONLY', '')
    if raw.strip():
        return {int(x) for x in raw.replace(' ', '').split(',') if x}
    if is_test():
        return set(REFERENCE_TEN)
    return None


def skip(set_no: int) -> bool:
    o = only()
    return o is not None and set_no not in o
