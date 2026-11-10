#!/usr/bin/env python3
"""ЛЕНТЫ ЗАМЕН /demo ДЛЯ ДРУГИХ КОМНАТ (T-20261110-37, план `tour-as-demo-01`, владелец 10.11 TG 869/872).

Тур пробы по наполнению — как `/demo`: на каждую позицию до 20+ товаров, которые влезают по размеру, подходят по стилю и все с 3D-моделью
из общей библиотеки мешей. Источник — ленты, которые уже собрала сборка витрины (`flat215_demo.build`, ночь): товары всех наборов
банка (`set_feed_row`) и пул каталога (`demo_swap_pool.pool` / `rug_pool`), с теми же проверками — модель есть на сервере и подходит
по цвету, живое фото, `unfit`, конверт роли. ПРОВЕРКИ НЕ ПОВТОРЯЕМ: тот же пул, пересчитанный на каждую пробу, стоит ~3,5 мин (замер
10.11: `pick+swap_ok` 207 с, весь пул 250 с — бюджет сборки тура +30 с), а ночная сборка витрины считает его тем же кодом раз в сутки.
Своё у тура — только КОНВЕРТ: товар подходит позиции, если влезает в СЛОТ этого предмета в комнате тура (`fits`: ширина и глубина
не больше места, которое решатель отдал предмету этого стиля), а не в комнату flat215.

Ключи лент витрины: у гостиной — голая роль, у спальни — `bedroom:<роль>`; вид комнаты тура → ключ — `kind_rows`.
Нет файла витрины (тест, чистая машина) — пусто: тур собирается прежним путём (товары своих вариантов), сборщик пишет `feeds_short`."""
from __future__ import annotations

import json
import os
import re

MIN_FEED = 20            # «стандарт — 20 на каждый вариант» (владелец 10.11 TG 869/872): меньше — счётчик `feeds_short`
FIT_TOL_CM = 1.0         # округление каталога: 99,6 см «влезает» в слот 99
# роли без модели — плита с фото (ковёр) и мягкое: годность — фото, а не меш (`flat215_demo.NOMESH_ROLES`)
NOMESH = {'ковёр', 'ковер', 'картина', 'зеркало', 'плед', 'покрывало', 'шторы', 'подушка'}
KIND_PREFIX = {'bedroom': 'bedroom:'}

_CACHE: dict = {}


def default_path() -> str:
    """`demo-data.json` сборки витрины (`flat215_demo.OUT`, env `FLAT215_DEMO_OUT`)."""
    import flat215_demo as FD
    return os.path.join(FD.OUT, 'demo-data.json')


def load(path: str | None = None) -> dict:
    """Ленты витрины → {вид комнаты: {роль: [строки]}} (`living` — голые ключи, `bedroom` — `bedroom:<роль>`). Кэш — по времени
    файла. Нет файла / битый — {}."""
    path = path or default_path()
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return {}
    hit = _CACHE.get(path)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        with open(path, encoding='utf-8') as f:
            feeds = (json.load(f) or {}).get('feeds') or {}
    except (OSError, ValueError):
        return {}
    out: dict = {}
    for k, rows in feeds.items():
        kind, role = k.split(':', 1) if ':' in k else ('living', k)
        out.setdefault(kind, {})[role] = [r for r in rows or [] if isinstance(r, dict)]
    _CACHE[path] = (mt, out)
    return out


def room_kind(room_id: str) -> str:
    """Вид комнаты тура по id (`living`, `living-2` → гостиная; `bedroom-1` → спальня)."""
    return re.sub(r'-\d+$', '', room_id or '') or 'living'


def kind_rows(data: dict, kind: str, role: str) -> list:
    if kind.startswith('_'):                 # служебные ключи кэша (`_tiles`)
        return []
    return ((data or {}).get(kind) or {}).get(role) or []


def styles_of(row: dict) -> list:
    st = row.get('styles') or ([row['style']] if row.get('style') else [])
    return [s for s in st if s]


def model_ok(role: str, row: dict) -> bool:
    """Товар покажется в кадре: у роли с моделью — модель (`msid`, проверена сборкой витрины), у плиты с фото — фото."""
    return bool(row.get('img')) if role in NOMESH else bool(row.get('msid'))


def fits(role: str, row: dict, slot: tuple) -> bool:
    """Товар влезает в слот (ширина, глубина места предмета в комнате тура). Ковёр — длинная к длинной, короткая к короткой."""
    w, d = row.get('w') or 0, row.get('d') or 0
    sw, sd = slot
    if not (w and d and sw and sd):
        return False
    if role in ('ковёр', 'ковер'):
        return max(w, d) <= max(sw, sd) + FIT_TOL_CM and min(w, d) <= min(sw, sd) + FIT_TOL_CM
    return w <= sw + FIT_TOL_CM and d <= sd + FIT_TOL_CM


def slot_pick(data: dict, kind: str, role: str, style: str, slot: tuple, ok=None, exclude=()) -> dict | None:
    """Лучший товар ленты витрины на слот: своего стиля, с моделью, влезает; из таких — самый крупный (меньше пустоты на месте
    геометрии), при равенстве — по названию. `ok(row)` — доп. проверка вызывающего (правило модели пробы, форма дивана)."""
    best = None
    for r in kind_rows(data, kind, role):
        if style not in styles_of(r) or not model_ok(role, r) or not fits(role, r, slot) or r.get('sid') in exclude:
            continue
        if ok is not None and not ok(r):
            continue
        key = (-(r.get('w') or 0) * (r.get('d') or 0), r.get('name') or '')
        if best is None or key < best[0]:
            best = (key, r)
    return best[1] if best else None


def tile_of(sid: str | None, path: str | None = None) -> str | None:
    """Плитка фото товара витрины (`img/<md5>.jpg`) по ключу товара — у товара пула, которого нет в банках пробы (подставлен по слоту)."""
    if not sid:
        return None
    data = load(path)
    idx = data.get('_tiles')
    if idx is None:
        idx = {r['sid']: r['img'] for rows in (v for k, v in data.items() if not k.startswith('_')) for lst in rows.values()
               for r in lst if r.get('sid') and r.get('img')}
        data['_tiles'] = idx
    return idx.get(sid)


def _key(r: dict) -> tuple:
    return (r.get('msid') or r.get('name'), r.get('w'), r.get('d'), r.get('sleep_w'))


# ТОВАР В ЛЕНТЕ — С ФОТО И МАГАЗИНОМ (T-20261110-40, владелец TG 917): строка без них — белая карточка «Диван · 210×90» без картинки
GOODS_FIELDS = ('name', 'name_en', 'colour_en', 'colour_ru', 'price', 'img', 'url', 'shop')
BAND_LO = 0.8            # нижняя граница «подходящего по размеру» — доля места (полоса владельца 22.10, demo-20 А4: 0,8–1,1 идеала)


def has_goods(r: dict) -> bool:
    """Строка — товар: фото, ссылка в магазин, цена."""
    p = r.get('price')
    return bool(r.get('img')) and bool(r.get('url')) and isinstance(p, (int, float)) and not isinstance(p, bool) and p > 0


def side(role: str, r: dict) -> float:
    """Мерило размера роли: у ковра — длинная сторона (в фидах `w` — короткая), у прочих — ширина (как `slot_rules.in_band`)."""
    w, d = r.get('w') or 0, r.get('d') or 0
    return max(w, d) if role in ('ковёр', 'ковер') else w


def same_goods(data: dict, kind: str, role: str, sku: dict) -> dict | None:
    """Товар витрины для предмета без товара (сборка до T-25, перенесённая перевыпуском): та же модель (`msid`) того же размера, с
    фото и магазином. Из цветов модели — неперекрашенный (`tint` нет: фото = цвет модели в кадре), сперва тот, с которого модель
    снята (`sid` = `msid`). Нет такого — None (покрашенный цвет дал бы фото не того цвета, что в 3D)."""
    m = sku.get('msid')
    if not m:
        return None
    best = None
    for r in kind_rows(data, kind, role):
        if r.get('msid') != m or r.get('tint') or not has_goods(r):
            continue
        if abs((r.get('w') or 0) - (sku.get('w') or 0)) > FIT_TOL_CM or abs((r.get('d') or 0) - (sku.get('d') or 0)) > FIT_TOL_CM:
            continue
        key = (r.get('sid') != m, r.get('name') or '')
        if best is None or key < best[0]:
            best = (key, r)
    return best[1] if best else None


def room_feed(data: dict, kind: str, role: str, slots: dict, own: list | None = None, lo: dict | None = None) -> tuple[list, dict]:
    """Лента позиции комнаты тура → (строки, {стиль: сколько}). `slots` — {стиль: [(ширина, глубина) мест этой роли в варианте
    стиля]}; `own` — строки товаров самих вариантов (идут первыми, как «изначальный набор» /demo). Товар витрины берётся, если у него
    модель и он влезает в место хотя бы одного своего стиля; `styles` строки — только те стили, в чьё место он влезает (страница режет
    ленту стилем варианта — `index.html:feedFor`). `lo` — {стиль: наименьший размер (`side`)}: мельче — «не по размеру» (страница —
    та же полоса, `rules.slot_band_cm`). Своя строка без товара и строка витрины того же товара — одна строка С ТОВАРОМ витрины;
    строки без фото и магазина в ленту не идут (T-40)."""
    out = [dict(r) for r in own or []]
    have = {_key(r): r for r in out}             # свой товар варианта = тот же товар витрины (модель и размер) — одна строка
    seen = set()                                 # строки витрины — по ключу товара: цвета одной модели — разные строки, как в /demo
    lo = lo or {}
    for r in kind_rows(data, kind, role):
        if not model_ok(role, r) or not has_goods(r) or (r.get('sid') and r['sid'] in seen):
            continue
        st = [s for s in styles_of(r) if any(fits(role, r, sl) for sl in slots.get(s) or []) and side(role, r) >= (lo.get(s) or 0)]
        if not st:
            continue
        seen.add(r.get('sid'))
        old = have.get(_key(r))
        if old is not None:
            old['styles'] = list(dict.fromkeys(styles_of(old) + st))
            if not has_goods(old) and not r.get('tint'):           # своя строка без товара — товар витрины (фото, магазин, цена)
                old.update({k: r[k] for k in GOODS_FIELDS if r.get(k) not in (None, '')})
            continue
        out.append(dict(r, style=st[0], styles=st))
    if any(has_goods(r) for r in out):          # тур без товаров вовсе (каталог лёг, витрины нет) — прежняя лента своих строк
        out = [r for r in out if has_goods(r)]
    count = {s: sum(1 for r in out if s in styles_of(r)) for s in slots}
    return out, count
