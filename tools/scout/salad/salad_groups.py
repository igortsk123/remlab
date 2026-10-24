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
# ЗАПРЕТ ЦЕНЫ ПО ГРУППЕ (план mesh-15): сторож денег кладёт сюда группу, у которой меш дороже потолка, ДО её остановки —
# иначе конвейер (`batch_show.ensure_group_started`) или расписание (`batch_window.sh up`) поднимут её обратно. Общий
# стоп-файл `mesh-group-halt.json` гасит весь пул; этот — одну группу. Снимает человек (удалить группу из файла).
PRICE_HALT = os.environ.get('MESH_PRICE_HALT') or os.path.expanduser('~/scout-scenes/mesh-price-halt.json')
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
    """$/ч машины группы. По классу карты (`price_class` → `prices_by_class_usd_h`, прайс Salad — цена класса полная,
    CPU и ОЗУ включены; T-20261024-01), иначе — по тарифу (`prices_usd_h`, цена RTX 3090 на 03.09: для 4060 Ti она
    на 43 % выше прайса, ночь 23→24.10 считалась 716 ₽ вместо ≈ 501 ₽)."""
    cls = info(group).get('price_class')
    by_cls = ((load().get('prices_by_class_usd_h') or {}).get(cls) or {}) if cls else {}
    if tier(group) in by_cls:
        return by_cls[tier(group)]
    return (load().get('prices_usd_h') or {}).get(tier(group))


def usd_rub() -> float:
    return float(load().get('usd_rub') or 0)


def price_ceiling() -> dict:
    """Потолок цены меша и правила суда (`price_ceiling` в rules/salad-groups.json); нет блока — пусто (сторож молчит)."""
    return load().get('price_ceiling') or {}


def node_min_ram_gb() -> float:
    """Сколько ОЗУ должно быть у машины, чтобы брать задания (`node_ram.min_gb`, T-20261022-10); 0 — не проверяем."""
    return float((load().get('node_ram') or {}).get('min_gb') or 0)


def price_halted(group: str) -> str:
    """Причина запрета подъёма группы по цене меша; '' — запрета нет. Битый файл — запрета нет, но громко."""
    try:
        with open(PRICE_HALT, encoding='utf-8') as f:
            d = json.load(f)
    except FileNotFoundError:
        return ''
    except (OSError, ValueError) as e:
        print(f'!! {PRICE_HALT} не читается ({type(e).__name__}) — запрет цены не учтён', flush=True)
        return ''
    return str((d.get(group) or {}).get('why') or '') if isinstance(d, dict) else ''


def allowed_now(group: str, now: float | None = None) -> bool:
    """Можно ли ПОДНИМАТЬ группу сейчас. Нет окна — всегда (low работает круглосуточно). Запрет цены — никогда.

    Окно — [с, до) по часам UTC. Разбор журнала 01–03.09: доля закрытых заданий на `batch`
    09–14ч 51–81%, 15–19ч 0–9% — вечером хозяева забирают домашние компьютеры, задание рвётся.
    """
    if price_halted(group):
        return False
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


def groups_or_empty() -> list[str]:
    """То же, но без отказа: для чтения при импорте модуля (стенд `tests_pool` импортирует
    `ssh_run` без окружения). Проверка на пустоту — в точке входа `main()`."""
    return [g.strip() for g in os.environ.get('SALAD_GROUP', '').split(',') if g.strip()]


def windowed() -> list[str]:
    """Группы с окном (их поднимает и гасит расписание `batch_window.sh`)."""
    return [g for g, i in (load().get('groups') or {}).items() if i.get('window_utc')]


if __name__ == '__main__':
    import sys
    if '--windowed' in sys.argv:
        print(' '.join(windowed()))
    elif '--can-start' in sys.argv:          # batch_window.sh up: 0 — можно поднимать, 1 — запрет цены (окно там своё — cron)
        _why = price_halted(sys.argv[sys.argv.index('--can-start') + 1])
        if _why:
            print(f'запрет цены: {_why}')
        sys.exit(1 if _why else 0)
    else:
        for g, i in (load().get('groups') or {}).items():
            print(f"{g:14s} {i.get('tier'):6s} {price(g)} $/ч  окно {i.get('window_utc') or '—'}  "
                  f"сейчас {'можно' if allowed_now(g) else 'НЕЛЬЗЯ'}")
