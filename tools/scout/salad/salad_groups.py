#!/usr/bin/env python3
"""Что за группа Salad: тариф, цена, окно подъёма — ОДИН источник для всех стартёров и отчётов.

ЗАЧЕМ (04.09). Тариф и окно жили в именах групп и в трёх разных местах кода (`tier_compare.TIER`,
`pool_hours.TIER`, `batch_window.sh`), а `SALAD_GROUP` разбирался в семи местах с разными
умолчаниями (`mesh-run3`, `mesh-run10`). Итог ночи 03.09: конвейер поднял batch-группы, которые
крон погасил в 15:00 UTC, — 57 машин прогрелось, 0 мешей, 134 ₽ впустую. Правило «группу вне окна
не поднимает никто» может работать только там, где окно записано ровно один раз.

    import salad_groups as SG
    SG.allowed_now('mesh-batch-1')      # False вечером — поднимать нельзя
    SG.price('mesh-low-2')              # 0.143 $/ч
    SG.groups_from_env()                # ['mesh-batch-1', ...] из SALAD_GROUP, без умолчания
"""
from __future__ import annotations

import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.environ.get('MESH_GROUPS_RULES') or os.path.join(HERE, '..', 'rules', 'salad-groups.json')
_CACHE: dict | None = None


def load() -> dict:
    global _CACHE
    if _CACHE is None:
        with open(RULES, encoding='utf-8') as f:
            _CACHE = json.load(f)
    return _CACHE


def info(group: str) -> dict:
    return (load().get('groups') or {}).get(group) or {}


def tier(group: str) -> str:
    """Тариф группы или '?' — неизвестную группу не считаем ничьей молча: отчёты печатают '?'."""
    return info(group).get('tier') or '?'


def price(group: str) -> float | None:
    return (load().get('prices_usd_h') or {}).get(tier(group))


def usd_rub() -> float:
    return float(load().get('usd_rub') or 0)


def allowed_now(group: str, now: float | None = None) -> bool:
    """Можно ли ПОДНИМАТЬ группу сейчас. Нет окна — всегда (low работает круглосуточно).

    Окно — [с, до) по часам UTC. Разбор журнала 01–03.09: доля закрытых заданий на `batch`
    09–14ч 51–81%, 15–19ч 0–9% — вечером хозяева забирают домашние компьютеры, задание рвётся.
    """
    win = info(group).get('window_utc')
    if not win:
        return True
    h = time.gmtime(now if now is not None else time.time()).tm_hour
    a, b = int(win[0]), int(win[1])
    return a <= h < b if a <= b else (h >= a or h < b)


def groups_from_env() -> list[str]:
    """Группы из `SALAD_GROUP` (через запятую). БЕЗ УМОЛЧАНИЯ: тихий `mesh-run3` из старого кода
    однажды заставил бы конвейер работать с давно удалённой группой."""
    raw = os.environ.get('SALAD_GROUP', '')
    gs = [g.strip() for g in raw.split(',') if g.strip()]
    if not gs:
        raise SystemExit('нет SALAD_GROUP — задай в ~/scout-scenes/salad.env (через запятую)')
    return gs


def windowed() -> list[str]:
    """Группы с окном (их поднимает и гасит расписание `batch_window.sh`)."""
    return [g for g, i in (load().get('groups') or {}).items() if i.get('window_utc')]


if __name__ == '__main__':
    import sys
    if '--windowed' in sys.argv:
        print(' '.join(windowed()))
    else:
        for g, i in (load().get('groups') or {}).items():
            print(f"{g:14s} {i.get('tier'):6s} {price(g)} $/ч  окно {i.get('window_utc') or '—'}  "
                  f"сейчас {'можно' if allowed_now(g) else 'НЕЛЬЗЯ'}")
