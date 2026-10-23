#!/usr/bin/env python3
"""Единственный загрузчик канона стратегий ассета (rules/asset-strategies.json).

Дыра 30.08: правило «ковёр без меша» жило в трёх разошедшихся списках, и flat215-источник
его обошёл — ковёр уехал в Hunyuan. Теперь канон один; каждый потребитель импортирует
ЭТОТ модуль, а воркер дополнительно пересчитывает стратегию сам (страховка до траты GPU).
"""
import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
# Канон ищем в двух местах: `rules/` (раскладка внутри образа воркера) и плоским файлом рядом
# с модулем (так он лежит в репозитории). Жёсткий единственный путь ронял ЛЮБОЙ вызов
# strategy() на дев-машине с FileNotFoundError — а это первый шаг каждого прогона (31.08).
_PATHS = [os.path.join(_HERE, 'rules', 'asset-strategies.json'),
          os.path.join(_HERE, 'asset-strategies.json')]
_CACHE = None


def _load() -> dict:
    global _CACHE
    if _CACHE is None:
        for p in _PATHS:
            if os.path.exists(p):
                _CACHE = json.load(open(p, encoding='utf-8'))
                return _CACHE
        raise FileNotFoundError(f'канон стратегий не найден: {_PATHS}')
    return _CACHE


def base_role(role: str | None) -> str:
    """«кресло 3» → «кресло», но «стол обеденный» ОСТАЁТСЯ собой: срезается только
    ЧИСЛОВОЙ суффикс (Codex q27: split-по-пробелу ломал составные роли)."""
    return re.sub(r'\s+\d+$', '', (role or '').strip())


def strategy(role: str | None) -> str:
    r = _load()['roles']
    return r.get(base_role(role), r.get('_default', 'hunyuan3d'))


def policy_version() -> int:
    return int(_load().get('policy_version', 0))


def roles_with(strategy_name: str) -> set:
    """Роли канона с этой стратегией (`cutout` — мягкое и настенное, demo-24 `flat215_demo.soft_roles`)."""
    return {r for r, s in _load()['roles'].items() if s == strategy_name and not r.startswith('_')}


# НАСТОЛЬНЫЙ ДЕКОР СРЕДИ `cutout` (часы стоят на столешнице, как ваза, — `flat215_demo.DECOR_ROLES`): в «без места в 3D» не входит
_TABLETOP_CUTOUT = {'часы'}


def soft_roles() -> set:
    """МЯГКОЕ БЕЗ МЕСТА В 3D (demo-24, владелец 23.10): подушка, шторы, плед, покрывало (и настенная полка) — стратегия `cutout`,
    кроме настольного декора. Одно правило на экспорт (`flat215_demo.soft_roles` → `rules.soft_roles` страницы), сцену сервера
    (`draft_render.decor_layout` их не ставит) и «Улучшить фото» (`improve_mode.soft_items` — в запрос словами и фото)."""
    return roles_with('cutout') - _TABLETOP_CUTOUT


def non_mesh_roles() -> set:
    """Роли, которым меш НЕ нужен (вклейка плоскостью и вырезка по контуру).

    Заменяет разошедшийся с каноном локальный список `MESH_EXCLUDE`: он жил в
    `mesh_queue.py`, был удалён как третья истина, и три модуля (`mesh_ready`,
    `pipeline_funnel`, `mesh_scheduler`) с тех пор падали на импорте — ночной конвейер
    молча не строил очередь (найдено разбором Codex 01.09).
    """
    return {r for r, s in _load()['roles'].items() if s != 'hunyuan3d'}
