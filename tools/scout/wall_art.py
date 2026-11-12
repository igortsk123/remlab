"""КАРТИНЫ НАД МЕБЕЛЬЮ В НАБОРАХ ВИТРИНЫ (план viz-decor-01 шаг 3, T-20261112-26; владелец TG 1645/1656: «картины — только товары
каталога»). Сборка витрины (`flat215_demo.main`) добавляет в декор гостиной и спальни 1–2 картины стиля варианта — строкой
списка с ценой (сумма страницы считает декор сама) и предметом 3D: место над опорой считает расчёт сцены от ТЕКУЩЕЙ расстановки
(`lib/configurator/wall-art.ts:placeWallArt`), здесь — только какой товар и сколько.

- Числа — одно место с 3D: `data/flat3d/wall-art.json` (опоры, доля ширины, подъём над опорой, зазор до потолка, толщина).
- Товар — каталог (`demo_swap_pool.soft_pool('картина')`: в продаже, живое фото, балл стиля ≥ порога ленты); габарит Ш×В из
  карточки, глубины у картин нет — толщина подрамника из правил.
- Выбор: одна картина или пара похожего размера, ширина (пары — с зазором) ближе всего к доле `share` ширины опоры, внутри
  коридора `share_range`; по высоте влезает между верхом опоры (+ подъём) и потолком (− зазор). Нет такой — картины нет (честно).
- Белое поле фото товара срезаем (`crop_white`): полотно в 3D — фото без поля (`sku.img_art`).
- Выключатель: `enabled: false` в правилах или `DEMO_WALL_ART=0` — сборка картин не добавляет.
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.normpath(os.path.join(HERE, '..', '..', 'data', 'flat3d', 'wall-art.json'))
CEILING_CM = 270.0
SKU_KEYS = ('name', 'price', 'price_at', 'img', 'url', 'shop', 'basis', 'sid', 'name_en', 'colour_en')
# пара — «комплект»: обе стороны отличаются не больше чем на 15 %
PAIR_SIMILAR = 0.15
# штраф пары против одной картины, пары из разных серий («Монстера» + «Абстракция») и повтора товара, уже взятого другим
# вариантом (разнообразие витрины) — в долях отклонения от `share`
PAIR_PENALTY, SERIES_PENALTY, USED_PENALTY = 0.05, 0.05, 0.06


def rules(path: str = RULES_PATH) -> dict:
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def enabled(r: dict) -> bool:
    return bool(r.get('enabled')) and os.environ.get('DEMO_WALL_ART', '1') != '0'


def base_role(role: str | None) -> str:
    return re.sub(r'\s+\d+$', '', role or '').strip()


def is_art(d: dict, r: dict) -> bool:
    """Картина декора: стратегия плоскости или роль из правил (тот же признак, что `fromDemo.ts:isWallArtDecor`)."""
    return d.get('strategy') == 'procedural_plane' or base_role(d.get('role')) == r['role']


def support(items: list, r: dict) -> dict | None:
    """Опора картины в наборе — первая по порядку правил (кровать → диван → комод), с шириной и высотой."""
    for role in r['supports']:
        for it in items:
            if base_role(it.get('role')) == role and it.get('w') and it.get('h'):
                return it
    return None


def headroom(sup: dict, ceiling: float, r: dict) -> float:
    """Высота стены под картину над опорой, см: потолок − зазор − (верх опоры + подъём)."""
    a = r['above_cm']
    top = float(sup.get('elev') or 0) + float(sup['h']) + float(a.get(base_role(sup.get('role')), a.get('*', 22)))
    return ceiling - float(r['ceiling_gap_cm']) - top


def series(name: str | None) -> str:
    """Серия картины — первое слово названия после «Картина» и магазина («Картина divan.ru Рельеф-2 Арки Белый» → «рельеф»)."""
    words = [w for w in re.split(r'\s+', (name or '').lower()) if w and w != 'картина' and '.' not in w]
    return re.sub(r'-\d+$', '', words[0]) if words else ''


def _similar(p: dict, q: dict) -> bool:
    return all(abs(float(p[k]) - float(q[k])) <= PAIR_SIMILAR * max(float(p[k]), float(q[k])) for k in ('w', 'h'))


def pick(cands: list, sup: dict, ceiling: float, r: dict, used: set | None = None) -> list:
    """1–2 картины к опоре: ширина группы / ширина опоры ближе всего к `share` внутри `share_range`; высота влезает. → [] — нет."""
    used = used or set()
    lo, hi = r['share_range']
    room = headroom(sup, ceiling, r)
    ok = [p for p in cands if p.get('w') and p.get('h') and float(p['h']) <= room]
    best = None
    groups = [[p] for p in ok]
    if int(r.get('max_count') or 1) >= 2:
        groups += [[p, q] for i, p in enumerate(ok) for q in ok[i + 1:] if _similar(p, q)]
    for g in groups:
        ratio = (sum(float(p['w']) for p in g) + float(r['pair_gap_cm']) * (len(g) - 1)) / float(sup['w'])
        if not lo <= ratio <= hi:
            continue
        score = (abs(ratio - float(r['share'])) + PAIR_PENALTY * (len(g) - 1) + USED_PENALTY * sum(p.get('sid') in used for p in g)
                 + SERIES_PENALTY * (len({series(p.get('name')) for p in g}) - 1))
        if best is None or score < best[0]:
            best = (score, g)
    return best[1] if best else []


def room_kind(data: dict, v: dict) -> str:
    rid = v.get('room_id') or 'living'
    for x in data.get('apartment_rooms') or []:
        if x.get('id') == rid and x.get('kind'):
            return x['kind']
    return 'living' if rid == 'living' else rid.split('-')[0]


def ceiling_of(data: dict, v: dict, default: float | None) -> float:
    geo = (data.get('rooms_geo') or {}).get(v.get('room_id') or 'living') or data.get('room') or {}
    return float(geo.get('height_cm') or default or CEILING_CM)


def decor_row(p: dict, role: str, r: dict) -> dict:
    sku = {k: p.get(k) for k in SKU_KEYS if p.get(k) is not None}
    sku.update({'msid': None, 'pack': 1, 'w': float(p['w']), 'd': float(r['depth_cm']), 'h': float(p['h'])})
    return {'role': role, 'strategy': 'procedural_plane', 'sku': sku}


def feed_rows(pool: list, r: dict) -> list:
    """Лента замен картины: строки пула с толщиной подрамника (примерка страницы требует Ш и Г) и без пометки мягкого."""
    return [{**{k: v for k, v in p.items() if k != 'soft'}, 'd': float(r['depth_cm']), 'strategy': 'procedural_plane'}
            for p in pool if p.get('w') and p.get('h')]


def annotate(data: dict, pool: list, r: dict | None = None, ceiling: float | None = None,
             kinds: tuple = ('living', 'bedroom')) -> list:
    """Картины в декор вариантов гостиной и спальни + ленты замен (`картина`, `bedroom:картина`). → [(вариант, опора, имена)]."""
    r = r or rules()
    if not enabled(r):
        return []
    out, used, feeds_for = [], set(), set()
    for v in data.get('variants') or []:
        kind = room_kind(data, v)
        if kind not in kinds or any(is_art(d, r) for d in v.get('decor') or []):
            continue
        sup = support(v.get('items') or [], r)
        if not sup:
            continue
        st = v.get('style')
        cands = [p for p in pool if p.get('style') == st or st in (p.get('styles') or [])]
        got = pick(cands, sup, ceiling_of(data, v, ceiling), r, used)
        if not got:
            out.append((v.get('id'), base_role(sup.get('role')), []))
            continue
        v.setdefault('decor', []).extend(decor_row(p, r['role'] + (f' {k + 1}' if k else ''), r) for k, p in enumerate(got))
        used.update(p.get('sid') for p in got)
        feeds_for.add(kind)
        out.append((v.get('id'), base_role(sup.get('role')), [p.get('name') for p in got]))
    rows = feed_rows(pool, r)
    for kind in feeds_for:
        data.setdefault('feeds', {})[r['role'] if kind == 'living' else f"{kind}:{r['role']}"] = [dict(p) for p in rows]
    return out


def crop_white(src: str, dst: str, r: dict | None = None, max_px: int = 900, aspect: float | None = None) -> bool:
    """Срезать белое поле фото товара: строки и столбцы, где «не белых» (любой канал < thr) пикселей меньше 0,5 %, — поле.
    Поле меньше `min_margin_pct` стороны со всех сторон — не трогаем (→ False). Итог — JPEG до `max_px` по длинной стороне.
    `aspect` — Ш/В товара: срез вышел шире или выше больше чем на 12 % (светло-серый фон снимка у белой картины) — лишнее
    по длинной стороне снимаем поровну с краёв, полотно не растягивается."""
    import numpy as np
    from PIL import Image
    wc = (r or rules())['white_crop']
    im = Image.open(src).convert('RGB')
    a = np.asarray(im)
    ink = (a < int(wc['thr'])).any(axis=2)
    rows = np.where(ink.mean(axis=1) > 0.005)[0]
    cols = np.where(ink.mean(axis=0) > 0.005)[0]
    if not len(rows) or not len(cols):
        return False
    h, w = ink.shape
    box = (int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1)
    m = float(wc['min_margin_pct']) / 100
    if box[0] < w * m and box[1] < h * m and w - box[2] < w * m and h - box[3] < h * m:
        return False
    bw, bh = box[2] - box[0], box[3] - box[1]
    if aspect and abs(bw / bh / aspect - 1) > 0.12:
        if bw / bh > aspect:
            cut = (bw - round(bh * aspect)) // 2
            box = (box[0] + cut, box[1], box[2] - cut, box[3])
        else:
            cut = (bh - round(bw / aspect)) // 2
            box = (box[0], box[1] + cut, box[2], box[3] - cut)
    out = im.crop(box)
    out.thumbnail((max_px, max_px))
    out.save(dst, 'JPEG', quality=88)
    return True


def annotate_crop(data: dict, out_dir: str, r: dict | None = None) -> tuple[int, int]:
    """Фото картин (декор вариантов и ленты) без белого поля → `sku.img_art` / `img_art` строки ленты (`img/<имя>-art.jpg`).
    Источник — крупная копия `-l.jpg`, нет — плитка. → (срезано, всего)."""
    r = r or rules()
    done, seen = 0, {}

    def one(p: dict) -> None:
        nonlocal done
        img = p.get('img') or ''
        if not img.startswith('img/'):
            return
        if img not in seen:
            src = os.path.join(out_dir, img)
            big = src[:-4] + '-l.jpg'
            name = 'img/' + os.path.basename(img)[:-4] + '-art.jpg'
            asp = float(p['w']) / float(p['h']) if p.get('w') and p.get('h') else None
            try:
                seen[img] = name if crop_white(big if os.path.exists(big) else src, os.path.join(out_dir, name), r, aspect=asp) else None
            except (OSError, ValueError):
                seen[img] = None
        if seen[img]:
            p['img_art'] = seen[img]
            done += 1
    targets = [d.get('sku') or {} for v in data.get('variants') or [] for d in v.get('decor') or [] if is_art(d, r)]
    targets += [p for k, lst in (data.get('feeds') or {}).items() if base_role(k.split(':')[-1]) == r['role'] for p in lst]
    for p in targets:
        one(p)
    return done, len(targets)
