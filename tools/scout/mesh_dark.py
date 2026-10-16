#!/usr/bin/env python3
"""МОДЕЛЬ ТЕМНЕЕ ТОВАРА (план demo-05 п.1б/п.3, 15.10): признак карантина «dark».

Журнальный стол «Ньюман-2 Бежевый» во всех местах рисовался чёрным: текстура у модели есть, но генерация дала её почти
чёрной (средняя яркость поверхности 17 из 255). Настоящие чёрные товары (стеклянный столик лофта) — не брак, поэтому
признак — расхождение: поверхность модели тёмная, а в названии товара светлый цвет.

Яркость считается ПО ПОВЕРХНОСТИ (цвет текстуры в центре каждой грани, взвешенный площадью), а не по всей картинке-текстуре:
в атласе бывают тёмные пустые поля. Чистые функции — для селфтеста и для `mesh_quarantine.apply`.

  ~/venvs/scout/bin/python mesh_dark.py <model.glb> «название товара»
  python3 mesh_dark.py --selftest
"""
from __future__ import annotations

import re
import sys

import numpy as np

# светлый цвет в названии: бежевый, белый, светлый, кремовый, молочный, слоновая кость, песочный, натуральный, дуб, ясень, бук…
LIGHT_RE = re.compile(r'беж|бел(ый|ая|ое|ые|ого|ой)\b|светл|крем|молоч|слонов|песоч|натурал|ваниль|айвори|ivory|beige|white|'
                      r'cream|\bдуб|ясен|\bбук\b|сосн|берез|клён|клен|капучино|латте|сливоч', re.I)
DARK_RE = re.compile(r'чёрн|черн|графит|венге|тёмн|темн|антрацит|black|graphite|anthracite|шоколад|эбен', re.I)
_RULES = __file__.rsplit('/', 1)[0] + '/rules/mesh-quarantine.json'


# ГРУППЫ ЦВЕТА ОБОГАЩЕНИЯ (`enrich_bridge`: colour) для «модель семейства другого цвета» (demo-05 п.2b, разбор Codex 16.10):
# близкие оттенки — одна группа, «не_определён» — не судим
COLOUR_GROUPS = {'белый': 'светлый', 'бежевый': 'светлый', 'серый': 'светлый', 'коричневый': 'коричневый', 'чёрный': 'чёрный',
                 'зелёный': 'зелёный', 'синий': 'синий', 'жёлтый': 'тёплый', 'оранжевый': 'тёплый', 'красный': 'красный',
                 'розовый': 'красный', 'фиолетовый': 'фиолетовый', 'разноцветный': 'разноцветный'}


def family_colour_mismatch(sid: str | None, msid: str | None, colour_of=None) -> str | None:
    """Модель представителя семейства (msid ≠ sid, ADR-0196) другого цвета, чем товар → причина `family_colour_mismatch:A→B`,
    иначе None. Цвета — из обогащения каталога; нет данных у одного из двух — не судим (fail-open). `colour_of(sid)` — для тестов."""
    if not sid or not msid or sid == msid:
        return None
    if colour_of is None:
        import enrich_bridge as EB

        def colour_of(x):
            m, e = x.split('_', 1)
            return (EB.get(m, e) or {}).get('colour')
    try:
        a, b = COLOUR_GROUPS.get(colour_of(sid)), COLOUR_GROUPS.get(colour_of(msid))
    except Exception:  # noqa: BLE001 — обогащение недоступно: не судим
        return None
    return f'family_colour_mismatch:{a}→{b}' if a and b and a != b else None


def cfg() -> dict:
    import json
    return {'photo_ratio': 0.35, 'photo_min_gap': 40.0, 'name_dark_y': 45.0, **(json.load(open(_RULES, encoding='utf-8')).get('dark') or {})}


def main_color(name: str) -> str:
    """Основной цвет товара — до «/»: у «Алекс Букле Светло-серый/Черный» чёрные только ножки (15.10: модель 11/255 при фото 57
    прошла как «чёрный товар», и в минимализме стоял чёрный стул вместо светло-серого)."""
    return (name or '').split('/')[0]


def is_light_name(name: str) -> bool:
    return bool(LIGHT_RE.search(main_color(name)))


def surface_luma(parts) -> float | None:
    """Средняя яркость поверхности модели (Y, 0–255), взвешенная площадью граней; нет граней — None."""
    import mesh_render as MR
    tot, acc = 0.0, 0.0
    for m in parts:
        area = np.asarray(m.area_faces, np.float64)
        if not len(area):
            continue
        # текстура уменьшается до 512 точек: для средней яркости хватает, а 2048² ×3 канала в float на DEV съедали память
        vis = getattr(m, 'visual', None)
        uv = getattr(vis, 'uv', None)
        mat = getattr(vis, 'material', None)
        img = (getattr(mat, 'baseColorTexture', None) or getattr(mat, 'image', None)) if mat is not None else None
        tex = None
        if img is not None and uv is not None:
            small = img.convert('RGB')
            small.thumbnail((512, 512))
            tex, uv = np.asarray(small), np.asarray(uv, np.float32)
        if tex is not None and uv is not None:
            c = uv[np.asarray(m.faces)].mean(axis=1)
            h, w = tex.shape[:2]
            tx = np.clip((c[:, 0] % 1.0) * (w - 1), 0, w - 1).astype(int)
            ty = np.clip((1.0 - (c[:, 1] % 1.0)) * (h - 1), 0, h - 1).astype(int)
            col = tex[ty, tx].astype(np.float64)
        else:
            col = MR.flat_colors(m).astype(np.float64)
        y = col @ np.array([0.2126, 0.7152, 0.0722])
        acc += float((y * area).sum())
        tot += float(area.sum())
    return acc / tot if tot > 0 else None


def photo_luma(cutout_png: str) -> float | None:
    """Средняя яркость товара на фото карточки (вырезка с прозрачным фоном, пиксели с альфой > 50 %)."""
    import os
    from PIL import Image
    if not os.path.exists(cutout_png):
        return None
    a = np.asarray(Image.open(cutout_png).convert('RGBA'), np.float64)
    m = a[..., 3] > 128
    if m.sum() < 100:
        return None
    return float((a[..., :3][m] @ np.array([0.2126, 0.7152, 0.0722])).mean())


def dark_flag(luma: float | None, name: str, photo: float | None = None, c: dict | None = None) -> float | None:
    """Признак «модель темнее товара»: яркость модели, если она намного темнее фото товара (или, без фото, тёмная при
    светлом названии), а в названии нет тёмного цвета; иначе None. Пороги — `rules/mesh-quarantine.json → dark`. Чистая функция."""
    c = c or cfg()
    if luma is None or DARK_RE.search(main_color(name)):
        return None
    if photo is not None:
        if luma < photo * c['photo_ratio'] and photo - luma >= c['photo_min_gap']:
            return round(luma, 1)
        # светлое название и почти чёрная модель — брак, даже если фото карточки само тёмное (у «Ньюман-2 Бежевый»
        # фото 40/255, модель 4/255: абсолютная разница мала, а покупатель видит чёрный стол вместо бежевого)
        if is_light_name(name) and luma < c['name_dark_y'] and luma < photo * c['photo_ratio']:
            return round(luma, 1)
        return None
    if luma < c['name_dark_y'] and is_light_name(name):
        return round(luma, 1)
    return None


def measure(glb: str, name: str) -> float | None:
    import gc
    import os
    import trimesh
    sc = trimesh.load(glb, force='scene')
    luma = surface_luma(list(sc.geometry.values()))
    del sc
    gc.collect()
    return dark_flag(luma, name, photo_luma(os.path.join(os.path.dirname(glb), 'cutout.png')))


def _selftest() -> int:
    fails = 0

    def ok(c, n):
        nonlocal fails
        print(('ok   ' if c else 'FAIL ') + n)
        fails += 0 if c else 1

    c = {'photo_ratio': 0.35, 'photo_min_gap': 40.0, 'name_dark_y': 45.0}
    ok(dark_flag(16.6, 'Журнальный столик Ньюман-2 Бежевый', None, c) == 16.6, 'без фото: тёмная модель бежевого товара — брак')
    ok(dark_flag(11.0, 'Стул Алекс Замша Бежевый', 57.0, c) == 11.0, 'модель в 5 раз темнее фото — брак')
    ok(dark_flag(7.0, 'Журнальный стол Ориндж Черный', 109.0, c) is None, 'чёрный товар — не брак, даже если фото светлее')
    ok(dark_flag(38.0, 'Журнальный стол Лейтон Орех', 58.0, c) is None, 'орех темнее фото на треть — не брак')
    ok(dark_flag(3.9, 'Журнальный стол Ньюман-2 Бежевый', 40.0, c) == 3.9, 'светлое название, тёмное фото, чёрная модель — брак')
    ok(dark_flag(120.0, 'Диван Белый', None, c) is None, 'светлая модель светлого товара — не брак')
    ok(dark_flag(None, 'Белый', 200.0, c) is None, 'нет замера — нет признака')
    ok(is_light_name('стол дуб натуральный') and not is_light_name('Графит'), 'светлые слова находятся, тёмные — нет')
    ok(dark_flag(10.8, 'Стул Алекс Букле Светло-серый/Черный', 56.7, c) == 10.8, 'двухцветный: чёрные ножки не делают товар чёрным')
    ok(dark_flag(7.0, 'Стул Лофт Черный/Дуб', 109.0, c) is None, 'основной цвет чёрный — не брак')
    tab = {'s1': 'серый', 'r1': 'разноцветный', 's2': 'белый', 'r2': 'серый', 's3': 'синий', 'r3': 'не_определён', 's4': 'зелёный'}
    ok(family_colour_mismatch('s1', 'r1', tab.get) == 'family_colour_mismatch:светлый→разноцветный', 'Брера: серый товар, разноцветная модель — брак')
    ok(family_colour_mismatch('s2', 'r2', tab.get) is None, 'белый и серый — одна группа')
    ok(family_colour_mismatch('s3', 'r3', tab.get) is None, 'нет цвета у модели — не судим')
    ok(family_colour_mismatch('s4', 's4', tab.get) is None, 'своя модель — не семейство')
    print('итог:', 'чисто' if not fails else f'{fails} провал(ов)')
    return 1 if fails else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    sys.path.insert(0, __file__.rsplit('/', 1)[0])
    print(measure(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ''))
