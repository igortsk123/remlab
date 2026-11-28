#!/usr/bin/env python3
"""Карточка прогона для запускателей Этажей (П1.161 шаг 5, Fable otvet-52): обёртка над `run_manifest` (его API не меняет) — start в начале, finish в конце, при исключении finish «fail».
Нужна, чтобы у каждого прогона в его выходной папке появлялся RUN.json (замер 28.11: 0 из 92 папок с карточкой — квоте шага 5 нечего считать).

Использование — декоратор на входной функции запускателя (тело функции не меняется, вывод/таблицы/журнал прежние; прибавляется только файл RUN.json в выходной папке):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'ops'))
    from run_card import carded
    @carded(OUT_DIR)                       # путь строкой, либо функция (*args, **kw) → путь
    def main(): ...
Исход: вернулась — finish «ok»; исключение (в т.ч. KeyboardInterrupt и SystemExit с ненулевым кодом) — finish «fail» с причиной в note, исключение летит дальше как было;
SystemExit(0/None) — «ok». Сбой самой карточки (нет прав, схема новее, диск) прогон НЕ валит: строка в stderr, прогон идёт дальше как без карточки.
Проверка «у прогона есть законченная карточка»: `python3 tools/ops/run_card.py check ПАПКА…` (код 1, если у какой-то нет карточки, она битая/новее схемы или не закончена — статус running).
Ничего не удаляет и не переносит. Без внешних зависимостей (python 3.9+)."""
from __future__ import annotations

import functools
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_manifest as rm  # noqa: E402


def _warn(msg: str) -> None:
    print(f"run_card: {msg}", file=sys.stderr)


def _reason(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:200]}"


def carded(run_dir, task: str | None = None, intermediate: list | None = None):
    """Декоратор: карточка RUN.json в папке прогона. run_dir — строка или функция от аргументов запускаемой функции."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            d = None
            try:
                d = os.path.expanduser(str(run_dir(*a, **kw) if callable(run_dir) else run_dir))
                rm.start(d, task=task, inputs=[str(x) for x in sys.argv[1:]], intermediate=intermediate,
                         note=f"{fn.__module__}.{fn.__name__} {' '.join(sys.argv[1:])}"[:300])
            except (rm.ManifestError, OSError) as e:
                _warn(f"карточку не начал ({_reason(e)}) — прогон идёт без неё")
                d = None
            try:
                res = fn(*a, **kw)
            except SystemExit as e:
                ok = e.code in (None, 0)
                _finish(d, "ok" if ok else "fail", None if ok else f"SystemExit({e.code!r})")
                raise
            except BaseException as e:
                _finish(d, "fail", _reason(e))
                raise
            _finish(d, "ok", None)
            return res
        return wrapper
    return deco


def _finish(d: str | None, status: str, note: str | None) -> None:
    if d is None:
        return
    try:
        rm.finish(d, status, note=note)
    except (rm.ManifestError, OSError) as e:
        _warn(f"карточку не закончил ({_reason(e)})")


def check_card(run_dir: str) -> list:
    """Что не так с карточкой прогона: список строк (пусто — всё в порядке). Статус fail — не поломка карточки (это честный исход прогона)."""
    r = rm.read_card(run_dir)
    st = r["state"]
    if st == "нет":
        return [f"{run_dir}: нет RUN.json — прогон без карточки"]
    if st in ("битая", "новее схемы"):
        return [f"{run_dir}: карточка {st}"]
    if st == "running" or (r["card"] or {}).get("finished_utc") is None:
        return [f"{run_dir}: карточка не закончена (running) — прогон упал без finish или идёт"]
    return []


def main(argv: list | None = None) -> int:
    av = list(sys.argv[1:] if argv is None else argv)
    if len(av) < 2 or av[0] != "check":
        print("использование: run_card.py check ПАПКА [ПАПКА…]", file=sys.stderr)
        return 2
    bad = [p for d in av[1:] for p in check_card(d)]
    for p in bad:
        print(p)
    print("карточки в порядке" if not bad else f"проблем: {len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
