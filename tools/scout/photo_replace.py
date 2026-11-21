"""ПРЕДМЕТ ВАРИАНТА БЕЗ СКАЧАННОЙ КАРТИНКИ → БЛИЖАЙШИЙ ИЗ ЛЕНТЫ С КАРТИНКОЙ (T-20261119-115/3, живая проверка 2.20: ковёр set10).

Фото магазина отдаёт 403 через раз; после `fetch_images` у предмета варианта `sku.img` остаётся пустым, страница рисует плашку «нет фото».
Замена — по правилу замены окна и /flat (`lib/configurator/demo-feeds.ts`: `candidates`, `sameShape`, `placeOf`), а не по новому: товар ленты
ТОГО ЖЕ СТИЛЯ И РОЛИ ТОЙ ЖЕ КОМНАТЫ, с моделью, картинкой и размерами, той же формы (угловой/прямой диван), не тот же товар; у ковра длинная
сторона не короче дивана расстановки (контракт зонного ковра); габариты в допуске `rules/demo-swap.json → no_photo_replace.max_size_gap_cm`
(сумма расхождений по сторонам, у ковра длинная с длинной, короткая с короткой) — расстановка и 3D не сдвигаются: место и размеры предмета остаются.
Ближайший по размеру, затем дешевле. Не нашёлся — предмет остаётся с плашкой, строка идёт в отчёт сборки. Чистая функция: без сети и базы."""
from __future__ import annotations

import re


def _long_short(w: float, d: float) -> tuple[float, float]:
    return max(w, d), min(w, d)


def size_gap(p: dict, w: float, d: float, rug: bool) -> float:
    """Расхождение размеров товара и места — как `sizeGap` в demo-feeds.ts."""
    pw, pd = p.get('w') or 0, p.get('d') or 0
    if not rug:
        return abs(pw - w) + abs(pd - d)
    a, b = _long_short(pw, pd)
    c, e = _long_short(w, d)
    return abs(a - c) + abs(b - e)


def _in_style(p: dict, style: str | None) -> bool:
    """Товар для стиля варианта — как `feedForStyle`: `styles` с этим стилем, без `styles` — свой стиль или без стиля."""
    if not style:
        return True
    if p.get('styles'):
        return style in p['styles']
    return not p.get('style') or p.get('style') == style


def _same_shape(p: dict, it: dict) -> bool:
    """Форма места из расстановки — как `sameShape`: угловой на угловое; сторона оттоманки — только на ту же."""
    if bool(p.get('corner')) != bool(it.get('corner')):
        return False
    return not it.get('corner') or p.get('corner_left') is None or bool(p['corner_left']) == bool(it.get('corner_left'))


def room_type(room_id: str | None) -> str:
    """`bedroom-2` → `bedroom`; гостиная и пустое — `living`."""
    return re.sub(r'-\d+$', '', room_id or 'living') or 'living'


def pick_replacement(it: dict, variant: dict, feed: list, max_gap: float) -> dict | None:
    """Ближайший годный товар ленты для предмета `it` варианта или None."""
    sk = it.get('sku') or {}
    rug = str(it.get('role') or '').startswith('ковёр')
    w, d = it.get('w') or 0, it.get('d') or 0
    sofa = next((x.get('w') for x in variant.get('items') or [] if x.get('role') == 'диван' and x.get('w')), None)
    used = {(x.get('sku') or {}).get('sid') for x in variant.get('items') or []}
    best = None
    for p in feed:
        if not (p.get('img') and p.get('msid') and p.get('w') and p.get('d')):
            continue
        if p.get('sid') == sk.get('sid') or p.get('sid') in used or not _in_style(p, variant.get('style')) or not _same_shape(p, it):
            continue
        if rug and sofa and max(p['w'], p['d']) < sofa:
            continue
        gap = size_gap(p, w, d, rug)
        if gap > max_gap:
            continue
        key = (gap, p.get('price') or 0)
        if best is None or key < best[0]:
            best = (key, p)
    return best[1] if best else None


def replace_no_photo(variants: list, feeds: dict, key_of, max_gap: float) -> dict:
    """Заменить предметы вариантов без картинки (`sku` есть, `sku.img` пуст) ближайшим из ленты (`feeds[key_of(тип комнаты, роль)]`).
    Меняет `it['sku']` на месте: те же ключи, что были у sku, значения — товара ленты; место и размеры предмета не трогает.
    → {'without': N, 'replaced': M, 'replaced_rows': [...], 'left_rows': [...]} — строки для отчёта сборки (было → стало / остался)."""
    replaced_rows, left_rows = [], []
    for v in variants:
        for it in v.get('items') or []:
            sk = it.get('sku') or {}
            if not sk or sk.get('img'):
                continue
            feed = feeds.get(key_of(room_type(v.get('room_id')), it.get('role'))) or []
            best = pick_replacement(it, v, feed, max_gap)
            label = f"{v.get('id')} {it.get('role')}"
            if best is None:
                left_rows.append(f"{label}: {sk.get('name')} — замены нет, остаётся плашка")
                continue
            old = sk.get('name')
            it['sku'] = {k: best.get(k) for k in set(sk) | {'name', 'price', 'img', 'url', 'sid', 'msid', 'w', 'd', 'h'} if k in best or k in sk}
            replaced_rows.append(f"{label}: {old} → {best.get('name')} (габариты {best.get('w')}×{best.get('d')} вместо {it.get('w')}×{it.get('d')} места)")
    return {'without': len(replaced_rows) + len(left_rows), 'replaced': len(replaced_rows),
            'replaced_rows': replaced_rows, 'left_rows': left_rows}
