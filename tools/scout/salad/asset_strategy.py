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
    (`draft_render.decor_layout` их не ставит) и «Улучшить фото» (`improve_mode.soft_items` — в запрос словами и фото).
    `soft_until_models` канона — роли, которым меш уже генерируется (hunyuan3d), а показ /demo ещё мягкий, пока его не
    переведут на модели (подушка, ADR-0402, T-20261113-03): генерация и показ переключаются раздельно."""
    return (roles_with('cutout') | set(_load().get('soft_until_models') or ())) - _TABLETOP_CUTOUT


def non_mesh_roles() -> set:
    """Роли, которым меш НЕ нужен (вклейка плоскостью и вырезка по контуру).

    Заменяет разошедшийся с каноном локальный список `MESH_EXCLUDE`: он жил в
    `mesh_queue.py`, был удалён как третья истина, и три модуля (`mesh_ready`,
    `pipeline_funnel`, `mesh_scheduler`) с тех пор падали на импорте — ночной конвейер
    молча не строил очередь (найдено разбором Codex 01.09).
    """
    return {r for r, s in _load()['roles'].items() if s != 'hunyuan3d'}


# ---------------------------------------------------------------- перед меша (T-20261106-78)
FRONT_KINDS = ('directed', 'by_back', 'none')


def front(role: str | None) -> str:
    """Есть ли у меша роли перед: `directed` | `by_back` (только со спинкой) | `none`. Канон — `front` в
    `rules/asset-strategies.json`. Роли без меша (плоскость, вырезка) — `none`; роль с мешем без записи — `directed`
    (безопаснее проверить ориентацию, чем поставить предмет задом: прихожая до T-78)."""
    r = base_role(role)
    if strategy(r) != 'hunyuan3d':
        return 'none'
    k = (_load().get('front') or {}).get(r, 'directed')
    if k not in FRONT_KINDS:
        raise ValueError(f'asset-strategies.json front[{r!r}] = {k!r}: допустимо {FRONT_KINDS}')
    return k


def is_directed(role: str | None, name: str = '', subtype: str = '') -> bool:
    """Направлен ли этот предмет: по роли, а у `by_back` — по признаку спинки в названии/подтипе (q25)."""
    k = front(role)
    if k == 'by_back':
        return 'спинк' in f'{name} {subtype or ""}'.lower()
    return k == 'directed'


def directed_roles(roles=()) -> set:
    """Направленные роли из карты `front` и переданных ролей (роли комнат — из профилей, их собирает вызывающий:
    нода Salad профилей не видит)."""
    known = set(_load().get('front') or {}) | {base_role(r) for r in roles if r}
    return {r for r in known if not r.startswith('_') and front(r) == 'directed'}


def front_hint(role: str | None) -> str:
    """Признаки сторон для VLM-свидетеля; нет подсказки — имя роли."""
    return (_load().get('front_hints') or {}).get(base_role(role), role or '')


def reserve_roles() -> set:
    """Роли резерва спроса на меши (деньги — отдельное решение от переда; каждая обязана быть directed)."""
    return set(_load().get('reserve_roles') or ())
