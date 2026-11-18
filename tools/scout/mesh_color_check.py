#!/usr/bin/env python3
"""Сторож «меш не того цвета» (T-20261107-14): цвет модели против цвета товара — для всех комнат. Шаг 1 — ПЕРЕПИСЬ.

ЗАЧЕМ. В гостиной неоклассики диван «Сорен Велюр Коричневый» в 3D белый (находка Работника 1, 07.11). Прежние сторожа судят
не по модели: `mesh_dark` — только «модель темнее светлого названия», `family_colour_mismatch` и привязка (`appearance`) —
по группам цвета обогащения у представителя семьи. Модель, которую покраска увела в другую светлоту или оттенок, и вариант
семьи «того же» цвета по группе, но другого на деле, проходят. Здесь — замер самой модели:
  • цвет модели — поверхность (цвет текстуры в центре грани, вес — площадь), медиана по каналам Lab;
  • цвет товара — его фото карточки (фон — по краю кадра; вырезка — по альфе), медиана Lab; цвет входа модели — фото, с
    которого её красили (`cutout.png` рядом с GLB), — чтобы различать «семья другого цвета» и «покраска ушла».
Разница — ΔL (светлота Lab), Δab (оттенок и насыщенность без светлоты), ступени светлоты log2(Y модели / Y фото).

ПЕРЕПИСЬ (только чтение, ничего не помечает): пары «товар → модель, которую грузит сцена» из опубликованного демо (варианты и
ленты гостиной и спальни, `demo-data.json`) и из готовых привязок спальни и прихожей (`catalog-assets/v1/current.json`).
Пороги — из распределения переписи 07.11 (`rules/mesh-color-guard.json`: p99 ошибки покраски своих мешей, версия и провенанс).

СТОРОЖ (шаг 2, T-20261107-14/2; ночью — шаг `mesh_color_guard` в `refresh_daily.sh` ПЕРЕД `room_bindings --build`): каждой
привязке с ассетом — видимый цвет (цвет её модели × подкраска, которую поставит сцена, `tint_of` = правило
`flat215_demo.annotate_tint`) против цвета текущего фото товара (`product_photo_current` → малая копия `thumbs/`). Итог —
таблица `~/scout-scenes/catalog-assets/mesh-color/current.json` {товар: asset_id, модель, tint, разница, вердикт}; её читает
`room_bindings` (вариант семьи с вердиктом mismatch — blocked `mesh_color_mismatch:…`, свой меш — только предупреждение).
Вердикт привязан к ассету: модель сменилась — старый вердикт не действует. Таблицы нет — привязка без отметок (WARN, fail-open).
Замеры моделей — кэш по пути и mtime файла (рядом с таблицей), повтор ночи считает только новые модели.
Строка в сводку: `DIGEST:сторож цвета мешей: отмечено N, из них в ленте было M; свои меши с расхождением: K` — свои меши
только числом, без WARN (К8 отложен, T-14/3); их список — `own-mismatch.tsv` рядом с таблицей. warn/FAIL шага — только сбой.

  ~/venvs/scout/bin/python mesh_color_check.py census <папка> [--rooms living,bedroom,hall] [--workers 3]
  ~/venvs/scout/bin/python mesh_color_check.py guard [--out ДИР] [--bindings СНИМОК] [--workers 3] [--seed-cache ФАЙЛ]
  ~/venvs/scout/bin/python mesh_color_check.py --selftest
Env: `MESH_COLOR_DIR` — папка таблицы (тесты, сухой прогон).
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
DEMO = os.path.expanduser(os.environ.get('FLAT215_DEMO_OUT') or '~/scout-scenes/flat215-demo')
GALLERY = os.path.expanduser('~/scout-scenes/mesh-pilot-gallery')
BINDINGS = os.path.join(os.path.expanduser(os.environ.get('CATALOG_ASSETS_DIR') or '~/scout-scenes/catalog-assets/v1'),
                        'current.json')
RULES = os.path.join(HERE, 'rules', 'mesh-color-guard.json')
TABLE_DIR = os.path.expanduser(os.environ.get('MESH_COLOR_DIR') or '~/scout-scenes/catalog-assets/mesh-color')
TABLE = 'current.json'
OWN_TSV = 'own-mismatch.tsv'
GREY_TSV = 'grey-top.tsv'
REASON = 'mesh_color_mismatch'
BG_DE = 12.0        # пиксель фото карточки — товар, если дальше от цвета фона (медиана рамки) больше чем на ΔE
MIN_PX = 80         # меньше пикселей товара — цвета фото нет


def rules(path: str = RULES) -> dict:
    return json.load(open(path, encoding='utf-8'))


# ---------- цвет: sRGB ↔ Lab (D65) ----------
def _lin(c):
    c = np.asarray(c, np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lab(rgb) -> np.ndarray:
    """sRGB 0–255 (N×3) → Lab D65 (N×3)."""
    li = _lin(np.atleast_2d(rgb))
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = li @ M.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], axis=1)


def luminance(rgb) -> np.ndarray:
    return _lin(np.atleast_2d(rgb)) @ np.array([0.2126, 0.7152, 0.0722])


def wmedian(v: np.ndarray, w: np.ndarray) -> float:
    o = np.argsort(v)
    cw = np.cumsum(w[o])
    return float(v[o][min(np.searchsorted(cw, cw[-1] / 2), len(v) - 1)])


def summary(rgb: np.ndarray, w: np.ndarray | None = None) -> dict:
    """Цвет набора точек: медиана по каналам Lab (вес — площадь), медиана RGB для листа, относительная светлота Y."""
    rgb = np.asarray(rgb, np.float64)
    w = np.ones(len(rgb)) if w is None else np.asarray(w, np.float64)
    L = lab(rgb)
    m = [round(wmedian(L[:, k], w), 2) for k in range(3)]
    return {'lab': m, 'rgb': [round(wmedian(rgb[:, k], w)) for k in range(3)],
            'y': round(wmedian(luminance(rgb), w), 5), 'n': int(len(rgb))}


def _to_srgb(lin: np.ndarray) -> np.ndarray:
    """Линейный свет 0…1 → sRGB 0…255 (обратное `_lin`)."""
    li = np.clip(np.asarray(lin, np.float64), 0, 1)
    return np.where(li <= 0.0031308, li * 12.92, 1.055 * li ** (1 / 2.4) - 0.055) * 255


def is_wood(rgb, P: dict) -> bool:
    """Цвет похож на дерево: оттенок Lab в `wood_hue`, насыщенность не ниже `wood_chroma`, светлота в `wood_L`. Серое/латте/белое — нет."""
    L, a, b = lab(rgb)[0]
    h = math.degrees(math.atan2(b, a)) % 360
    return P['wood_hue'][0] <= h <= P['wood_hue'][1] and math.hypot(a, b) >= P['wood_chroma'] and P['wood_L'][0] <= L <= P['wood_L'][1]


def part_colours(C: np.ndarray, W: np.ndarray, R: dict | None = None) -> list:
    """ЧАСТИ МОДЕЛИ (mcg-v3): цветовые кластеры текстуры (k-means в линейном свете, вес — площадь грани, фиксированное зерно →
    повтор даёт то же). → [{'share', 'rgb', 'wood'}] по убыванию доли. Одна медиана (`summary`) на модели из дерева и фасадов
    показывает дерево и «не видит» фасады — отсюда подкраска, ломавшая фасады."""
    P = (R or rules())['tint']['parts']
    lin = _lin(C)
    w = np.asarray(W, np.float64)
    rng = np.random.default_rng(1)
    if len(lin) > 20000:                                   # выборка: хватает для долей и цветов, k-means на 40 тыс. граней лишний
        ix = rng.choice(len(lin), 20000, replace=False)
        lin, w = lin[ix], w[ix]
    k = min(P['k'], len(lin))
    cent = lin[rng.choice(len(lin), k, replace=False)]
    lab_ = np.zeros(len(lin), int)
    for _ in range(40):
        lab_ = np.argmin(((lin[:, None, :] - cent[None]) ** 2).sum(2), 1)
        for j in range(k):
            m = lab_ == j
            if m.any():
                cent[j] = np.average(lin[m], 0, w[m])
    tot = max(float(w.sum()), 1e-9)
    out = []
    for j in range(k):
        m = lab_ == j
        if m.any():
            rgb = [int(round(v)) for v in _to_srgb(cent[j])]
            out.append({'share': round(float(w[m].sum()) / tot, 3), 'rgb': rgb, 'wood': bool(is_wood(rgb, P))})
    return sorted(out, key=lambda x: -x['share'])


def _de(a, b) -> float:
    la, lb = lab(a)[0], lab(b)[0]
    return float(np.sqrt(((la - lb) ** 2).sum()))


def merge_parts(parts: list | None, R: dict | None = None) -> list:
    """Слить части одного цвета (ΔE ≤ `merge_dE`, одинаковая «деревянность»): k-средние дробят один сплошной цвет на несколько
    кластеров (тёмные фасады 31 % + 20 % + 2 %), и «самой крупной» становилась меньшая, но цельная светлая часть (кадр 18.11).
    Идемпотентна — кэш замеров со старыми `parts` сливается при чтении."""
    P = (R or rules())['tint']['parts']
    out = []
    for p in sorted(parts or [], key=lambda p: -p['share']):
        for q in out:
            if bool(q.get('wood')) == bool(p.get('wood')) and _de(q['rgb'], p['rgb']) <= P['merge_dE']:
                w = q['share'] + p['share']
                q['rgb'] = [int(round((a * q['share'] + b * p['share']) / w)) for a, b in zip(q['rgb'], p['rgb'])]
                q['share'] = round(w, 3)
                break
        else:
            out.append(dict(p))
    return sorted(out, key=lambda p: -p['share'])


def anchor_part(photo_rgb, parts: list | None, R: dict | None = None):
    """ОПОРНАЯ ЧАСТЬ (mcg-v3): самая крупная из НЕ-деревянных частей модели, если она не меньше `min_share` площади и уже в
    пределах `match_dE` от цвета варианта и проходит порог семьи (ΔL/Δab) — тогда модель этого цвета «верная» там, где глаз её видит (фасады). Снимает ли это
    подкраску — решает `judge` (только если подкраска уводит эту часть на ΔE ≥ `broken_dE` или негодна). → часть | None (подкраска как раньше: нет частей/фото, мелкая или не самая крупная часть,
    дерево совпало с цветом варианта)."""
    if not photo_rgb or not parts:
        return None
    P = (R or rules())['tint']['parts']
    pool = [p for p in merge_parts(parts, R) if not p.get('wood')]
    if not pool:
        return None
    pool.sort(key=lambda p: -p['share'])
    big = pool[0]
    if big['share'] < P['min_share'] or _de(big['rgb'], photo_rgb) > P['match_dE']:
        return None
    # заметно крупнее остальных не-деревянных: иначе другая почти такая же часть (тёмные фасады при светлой внутренней полке) решит,
    # что модель «не того цвета», а подкраска её не лечит — оставляем подкраску как была (по умолчанию, ❶ директора)
    if len(pool) > 1 and big['share'] < P['lead_ratio'] * pool[1]['share']:
        return None
    # и проходит строгий порог варианта семьи (ΔL/Δab): иначе снятие подкраски выбросило бы вариант из ленты (mismatch)
    d = diff(summary(np.array([big['rgb']])), summary(np.array([photo_rgb])))
    return big if verdict(d, R or rules(), True) == 'ok' else None


def tint_shift(part_rgb, tint, photo_rgb) -> float:
    """ΔE цвета части модели ПОСЛЕ подкраски (линейный цвет × tint) от цвета варианта."""
    after = [int(round(v)) for v in _to_srgb(np.clip(_lin(part_rgb) * np.asarray(tint, np.float64), 0, 1))]
    return _de(after, photo_rgb)


def tint_hurts(photo_rgb, parts: list | None, tint, R: dict | None = None):
    """СЛЕПОТА «медиана × tint = фото»: часть модели заметной площади (`watch_share`), что ДО подкраски совпадала с цветом
    варианта (ΔE ≤ `match_dE`), а ПОСЛЕ ушла на ΔE ≥ `broken_dE`. → худшая часть {'share', 'before', 'after', 'dE'} | None.
    Правило опорной части такие случаи снимает; здесь остаются те, где подкраску оставили из осторожности (мелкая часть)."""
    if not photo_rgb or not parts or not tint:
        return None
    P = (R or rules())['tint']['parts']
    worst = None
    for p in merge_parts(parts, R):
        if p['share'] < P['watch_share']:
            continue
        after = [int(round(v)) for v in _to_srgb(np.clip(_lin(p['rgb']) * np.asarray(tint, np.float64), 0, 1))]
        d0, d1 = _de(p['rgb'], photo_rgb), tint_shift(p['rgb'], tint, photo_rgb)
        if d0 <= P['match_dE'] and d1 >= P['broken_dE'] and (worst is None or d1 > worst['dE']):
            worst = {'share': p['share'], 'before': p['rgb'], 'after': after, 'dE': round(d1, 1)}
    return worst


def tinted(mesh: dict | None, tint) -> dict | None:
    """Цвет, который видит покупатель, когда сцена подкрашивает модель семьи (`sku.tint` демо — множитель цвета материала
    THREE, `flat215_demo.annotate_tint`): линейный цвет модели × tint. Без подкраски — цвет модели."""
    if not mesh or not tint:
        return mesh
    li = _lin(mesh['rgb']) * np.asarray(tint, np.float64)
    li = np.clip(li, 0, 1)
    srgb = np.where(li <= 0.0031308, li * 12.92, 1.055 * li ** (1 / 2.4) - 0.055) * 255
    return summary(np.array([srgb]))


def diff(x: dict | None, y: dict | None) -> dict | None:
    """x против y: ΔL (x − y), Δab, ступени светлоты log2(Yx / Yy)."""
    if not x or not y:
        return None
    (L1, a1, b1), (L2, a2, b2) = x['lab'], y['lab']
    return {'dL': round(L1 - L2, 1), 'dab': round(math.hypot(a1 - a2, b1 - b2), 1),
            'stops': round(math.log2(max(x['y'], 1e-4) / max(y['y'], 1e-4)), 2)}


def verdict(d: dict | None, R: dict, via: bool = False) -> str:
    """ok | mismatch | unknown: |ΔL| или Δab выше порога правил — mismatch; нет замера — unknown (не судим). Вариант семьи на
    чужой модели (`via`) — строгий порог `family_thresholds` (T-20261112-89: «Латте» ΔL −24,5 / Δab 15,4 проходила порог своих
    мешей и в туре была зелёной); свой меш — прежний `thresholds`."""
    if not d:
        return 'unknown'
    T = (R.get('family_thresholds') or R['thresholds']) if via else R['thresholds']
    return 'mismatch' if abs(d['dL']) > T['dL'] or d['dab'] > T['dab'] else 'ok'


# ---------- подкраска: одно правило со сценой демо ----------
def tone(path: str | None):
    """Средний цвет товара по фото без белого фона, доли 0..1 — правило подкраски демо (`flat215_demo._tone`, перенесено сюда,
    чтобы сторож и сцена считали одно и то же)."""
    if not path:
        return None
    try:
        from PIL import Image
        a = np.asarray(Image.open(path).convert('RGB').resize((64, 64)), np.float32)
        m = a.sum(axis=2) < 720
        if m.sum() < 40:
            return None
        return [float(a[..., i][m].mean()) / 255.0 for i in range(3)]
    except Exception:  # noqa: BLE001 — нет фото: подкраски нет, модель остаётся своего цвета
        return None


def tint_of(a, b, R: dict | None = None):
    """Подкраска модели семьи под вариант: тон фото варианта / тон фото представителя по каналу, в границах правил; разница
    меньше min_change по всем каналам или нет тона — None (сцена не подкрашивает)."""
    if not a or not b:
        return None
    t = (R or rules())['tint']
    out = [round(min(t['hi'], max(t['lo'], x / max(y, 0.02))), 3) for x, y in zip(a, b)]
    return out if max(abs(x - 1) for x in out) >= t['min_change'] else None


SPREAD = 'spread'


def tint_from_mesh(photo_rgb, mesh_rgb, R: dict | None = None):
    """ПОДКРАСКА ОТ МОДЕЛИ (T-20261112-89): лин(цвет фото варианта) / лин(цвет текстуры модели представителя) по каналу, в
    границах lo…hi_mesh — сцена умножает на неё линейный цвет материала, значит видимый цвет ≈ фото. Прежняя `tint_of` делила
    тоны двух ФОТО, а текстура модели темнее и зеленее фото представителя: оливковая «Имин» под «Латте» выходила хаки.
    → список | None (разница < min_change, нет замера) | SPREAD (каналы разошлись больше max_spread — перекраска меняет
    оттенок через упор, вариант на этой модели не годен; Codex 12.11)."""
    if not photo_rgb or not mesh_rgb:
        return None
    t = (R or rules())['tint']
    raw = _lin(photo_rgb) / np.maximum(_lin(mesh_rgb), 1e-4)
    out = [round(float(min(t.get('hi_mesh', t['hi']), max(t['lo'], x))), 3) for x in raw]
    if max(out) / max(min(out), 1e-4) > t.get('max_spread', float('inf')):
        return SPREAD
    return out if max(abs(x - 1) for x in out) >= t['min_change'] else None


def photo_urls(skus) -> dict:
    """Текущее фото товара (`product_photo_current`, артикул через «:») — один SELECT, только чтение."""
    import room_bindings as RB
    skus = sorted(set(skus))
    if not skus:
        return {}
    lit = ','.join("'" + s.replace("'", "''") + "'" for s in skus)
    return {r[0]: r[1] for r in RB._rows(f'select sku, image_url from product_photo_current where sku = any(array[{lit}])')
            if len(r) == 2 and r[1]}


def thumbs_of(urls: dict, workers: int = 8) -> dict:
    """Артикул «mid:eid» → путь малой копии фото (`compose_common.get_thumb`: есть на диске — без сети)."""
    import concurrent.futures as cf
    import compose_common as CC

    def one(kv):
        sku, url = kv
        mid, eid = sku.split(':', 1)
        return sku, CC.get_thumb(url, mid, eid)
    with cf.ThreadPoolExecutor(workers) as ex:
        return {k: p for k, p in ex.map(one, sorted(urls.items())) if p}


# ---------- замеры ----------
def photo_colour(path: str) -> dict | None:
    """Цвет товара на фото: вырезка — пиксели с альфой > 50 %; фото карточки — пиксели дальше BG_DE от цвета фона (медиана
    рамки 3 % кадра). Меньше MIN_PX — None."""
    from PIL import Image
    if not path or not os.path.exists(path):
        return None
    im = Image.open(path)
    if im.mode in ('RGBA', 'LA', 'P'):
        a = np.asarray(im.convert('RGBA'), np.float64)
        if (a[..., 3] < 128).mean() > 0.02:
            px = a[..., :3][a[..., 3] > 128]
            return summary(px) if len(px) >= MIN_PX else None
    a = np.asarray(im.convert('RGB'), np.float64)
    h, w = a.shape[:2]
    k = max(1, int(min(h, w) * 0.03))
    border = np.concatenate([a[:k].reshape(-1, 3), a[-k:].reshape(-1, 3), a[:, :k].reshape(-1, 3), a[:, -k:].reshape(-1, 3)])
    bg = lab(np.median(border, axis=0))[0]
    flat = a.reshape(-1, 3)
    de = np.linalg.norm(lab(flat) - bg, axis=1)
    px = flat[de > BG_DE]
    return summary(px) if len(px) >= MIN_PX else None


def surface_colour(glb: str) -> dict | None:
    """Цвет поверхности модели: цвет текстуры в центре каждой грани (как `mesh_dark.surface_luma`), вес — площадь грани;
    без текстуры — цвет вершин/материала (`mesh_render.flat_colors`). Текстура уменьшается до 512 точек (память DEV)."""
    import gc
    import trimesh
    import mesh_render as MR
    sc = trimesh.load(glb, force='scene')
    cols, ws, tex_area = [], [], 0.0
    for m in sc.geometry.values():
        area = np.asarray(m.area_faces, np.float64)
        if not len(area):
            continue
        vis = getattr(m, 'visual', None)
        uv = getattr(vis, 'uv', None)
        mat = getattr(vis, 'material', None)
        img = (getattr(mat, 'baseColorTexture', None) or getattr(mat, 'image', None)) if mat is not None else None
        if img is not None and uv is not None:
            t = img.convert('RGB')
            t.thumbnail((512, 512))
            tex = np.asarray(t)
            c = np.asarray(uv, np.float32)[np.asarray(m.faces)].mean(axis=1)
            th, tw = tex.shape[:2]
            tx = np.clip((c[:, 0] % 1.0) * (tw - 1), 0, tw - 1).astype(int)
            ty = np.clip((1.0 - (c[:, 1] % 1.0)) * (th - 1), 0, th - 1).astype(int)
            col = tex[ty, tx]
            tex_area += float(area.sum())
        else:
            col = MR.flat_colors(m)
        cols.append(np.asarray(col, np.float64)[:, :3])
        ws.append(area)
    del sc
    gc.collect()
    if not cols:
        return None
    C, W = np.concatenate(cols), np.concatenate(ws)
    out = summary(C, W)
    out['textured'] = round(tex_area / max(float(W.sum()), 1e-9), 3)
    out['parts'] = part_colours(C, W)               # mcg-v3: из каких цветов состоит модель, не одна медиана
    return out


# ---------- перепись: пары ----------
def _sid(s: str) -> str:
    return s.replace(':', '_', 1)


def demo_pairs(rooms: set) -> list:
    """Пары из опубликованного демо: (комната, место, sid, msid, название, фото товара)."""
    d = json.load(open(os.path.join(DEMO, 'demo-data.json'), encoding='utf-8'))
    room_of = {v['id']: v.get('room_id') or 'living' for v in d.get('variants') or []}
    out = []

    def walk(x, path):
        if isinstance(x, dict):
            if 'sid' in x and 'name' in x and x.get('msid'):
                p0 = path[0] if path else ''
                if p0 == 'variants':
                    room = room_of.get(path[1], 'living')
                    place = f'вариант {path[1]}'
                elif p0 == 'feeds':
                    room = path[1].split(':')[0] if ':' in path[1] else 'living'
                    place = f'лента {path[1]}'
                elif p0 == 'sofa_feed':
                    room, place = 'living', 'лента диван'
                else:
                    room, place = ('bedroom' if 'bedroom' in p0 else 'living'), p0
                room = 'bedroom' if room.startswith('bedroom') else room
                if room in rooms:
                    img = x.get('img') or ''
                    out.append({'room': room, 'place': place, 'sid': _sid(x['sid']), 'msid': _sid(x['msid']), 'name': x['name'],
                                'tint': x.get('tint'),
                                'photo': os.path.join(DEMO, img) if img and not img.startswith('http') else None,
                                'photo_url': img if img.startswith('http') else None,
                                'glb': os.path.join(GALLERY, _sid(x['msid']), 'model.glb')})
            for v in x.values():
                walk(v, path)
        elif isinstance(x, list):
            for v in x:
                walk(v, path)
    for k, v in d.items():
        if k == 'variants':
            for var in v:
                walk(var, ('variants', var['id']))
        elif isinstance(v, dict) and k == 'feeds':
            for role, rows in v.items():
                walk(rows, ('feeds', role))
        else:
            walk(v, (k,))
    return out


def binding_pairs(rooms: set) -> list:
    """Готовые привязки комнат (то, что пойдёт в варианты и ленты банка): товар → модель сцены (`scene_msid`) и её файл."""
    import room_bindings as RB
    d = json.load(open(BINDINGS, encoding='utf-8'))
    offers, assets = d['offers'], d['assets']
    rep = {}
    for oid, o in offers.items():
        if o.get('representative_offer_id'):
            rep[_sid(oid)] = _sid(o['representative_offer_id'])
    out = []
    for oid, o in offers.items():
        rs = {s[0] for s in o.get('seen_in') or []} & rooms
        if not rs or o.get('status') != 'ready':
            continue
        row = {'mesh_id': o.get('mesh_id'), 'local_3d': (o.get('capabilities') or {}).get('local_3d')}
        sid = _sid(oid)
        msid = RB.scene_msid(row, sid, rep)
        aid = o.get('asset_id')
        if msid != sid and msid.replace('_', ':', 1) in offers:
            aid = offers[msid.replace('_', ':', 1)].get('asset_id') or aid
        glb = (assets.get(aid) or {}).get('local_path') if aid else None
        glb = glb or os.path.join(GALLERY, msid, 'model.glb')
        for r in sorted(rs):
            out.append({'room': r, 'place': 'привязка ready', 'sid': sid, 'msid': msid, 'name': None, 'tint': None, 'photo': None,
                        'photo_url': None, 'glb': glb})
    return out


def fill_photos(pairs: list) -> None:
    """Название и фото карточки товаров привязок — из каталога сборщиков (только чтение БД); фото — малая копия thumbs/."""
    need = {p['sid'] for p in pairs if not p['photo'] and not p['photo_url']}
    if not need:
        return
    import catalog_items as CI
    import compose_common as CC
    info = {}
    for rt in ('bedroom', 'hall', 'living'):
        try:
            for it in CI.items(rt):
                k = f'{it.mid}_{it.eid}'
                if k in need and k not in info:
                    info[k] = {'mid': it.mid, 'eid': it.eid, 'name': it.name,
                               'img': (it.photo or {}).get('url') or (it.photo or {}).get('best')}
        except Exception as e:  # noqa: BLE001 — комнаты нет в каталоге: громко, остальные считаем
            print(f'WARN: каталог {rt}: {repr(e)[:120]}', flush=True)
    for p in pairs:
        it = info.get(p['sid'])
        if it and not p['photo'] and not p['photo_url']:
            p['name'] = p['name'] or it.get('name')
            if it.get('img'):
                p['photo'] = CC.get_thumb(it['img'], it['mid'], it['eid'])


def _measure_glb(glb: str):
    try:
        return glb, surface_colour(glb), None
    except Exception as e:  # noqa: BLE001 — модель не открылась: в перепись причиной, не падаем
        return glb, None, repr(e)[:160]


def glb_from_bindings(pairs: list) -> None:
    """Модели нет в галерее (`mesh-pilot-gallery`) — файл ассета привязки этой модели (`assets.local_path`)."""
    d = json.load(open(BINDINGS, encoding='utf-8'))
    path_of = {}
    for oid, o in d['offers'].items():
        lp = (d['assets'].get(o.get('asset_id')) or {}).get('local_path')
        if lp and os.path.exists(lp):
            path_of[_sid(o.get('mesh_id') or oid)] = lp
    for p in pairs:
        if not os.path.exists(p['glb']) and p['msid'] in path_of:
            p['glb'] = path_of[p['msid']]


def census(out_dir: str, rooms: set, workers: int = 3) -> list:
    os.makedirs(out_dir, exist_ok=True)
    pairs = demo_pairs(rooms) + binding_pairs(rooms & {'bedroom', 'hall'})
    glb_from_bindings(pairs)
    fill_photos(pairs)
    cache_p = os.path.join(out_dir, 'cache.json')
    try:
        cache = json.load(open(cache_p))
    except (OSError, ValueError):
        cache = {}
    key = _gkey
    print(f'пар {len(pairs)}', flush=True)
    measure_glbs([p['glb'] for p in pairs], cache, workers, save=lambda: _atomic_json(cache_p, cache))
    photo_cache: dict = {}

    def ph(path):
        if path not in photo_cache:
            photo_cache[path] = photo_colour(path) if path else None
        return photo_cache[path]
    rows = []
    for p in pairs:
        m = cache.get(key(p['glb']) or '', None)
        mesh = m if m and 'lab' in m else None
        sku = ph(p['photo'])
        inp = ph(os.path.join(os.path.dirname(p['glb']), 'cutout.png'))
        seen = tinted(mesh, p.get('tint'))
        rows.append({**p, 'family': p['msid'] != p['sid'], 'mesh': mesh, 'seen': seen, 'sku_photo': sku, 'input_photo': inp,
                     'seen_vs_sku': diff(seen, sku),
                     'mesh_error': (m or {}).get('error') if not mesh else None,
                     'mesh_vs_sku': diff(mesh, sku), 'mesh_vs_input': diff(mesh, inp), 'sku_vs_input': diff(sku, inp)})
    with open(os.path.join(out_dir, 'census.jsonl'), 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(f'записано {len(rows)} строк → {out_dir}/census.jsonl', flush=True)
    return rows


# ---------- сторож: таблица вердиктов для привязки ----------
def measure_glbs(glbs, cache: dict, workers: int = 3, save=None) -> None:
    """Цвет поверхности моделей, которых нет в кэше (ключ «путь:mtime»); ошибка открытия — {'error': …} в кэш."""
    import concurrent.futures as cf
    # замер старого кэша (mcg-v2) без `parts` — перемеряем один раз; запись-ошибка остаётся (не повторяем каждую ночь)
    todo = sorted({g for g in glbs if _gkey(g) and (_gkey(g) not in cache
                                                    or ('lab' in cache[_gkey(g)] and 'parts' not in cache[_gkey(g)]))})
    if not todo:
        return
    print(f'моделей к замеру {len(todo)}', flush=True)
    with cf.ProcessPoolExecutor(workers) as ex:
        for i, (g, res, err) in enumerate(ex.map(_measure_glb, todo, chunksize=4), 1):
            cache[_gkey(g)] = res if res else {'error': err}
            if save and i % 100 == 0:
                save()
                print(f'  моделей {i}/{len(todo)}', flush=True)
    if save:
        save()


def _gkey(p: str | None) -> str | None:
    return f'{p}:{int(os.path.getmtime(p))}' if p and os.path.exists(p) else None


def pairs_of(snap: dict) -> list:
    """Привязки с файлом модели: {sku, asset_id, owner, via, glb}. owner — чей меш (представитель у варианта семьи)."""
    out = []
    assets = snap.get('assets') or {}
    for oid, o in (snap.get('offers') or {}).items():
        aid = o.get('asset_id')
        glb = (assets.get(aid) or {}).get('local_path') if aid else None
        if not glb:
            continue
        via = bool(o.get('via_family'))
        owner = (o.get('representative_offer_id') or oid) if via else oid
        out.append({'sku': oid, 'asset_id': aid, 'owner': owner, 'via': via, 'glb': glb})
    return out


def judge(pairs: list, mesh_of, photo_of, R: dict) -> dict:
    """Вердикт каждой пары: видимый цвет (модель × подкраска сцены) против фото товара. mesh_of(glb) → замер | None,
    photo_of(sku) → путь фото | None. Чистая функция над замерами — её и проверяет самопроверка."""
    rows, tones, cols = {}, {}, {}

    def tn(sku):
        if sku not in tones:
            tones[sku] = tone(photo_of(sku))
        return tones[sku]

    def pc(sku):
        if sku not in cols:
            p = photo_of(sku)
            cols[sku] = photo_colour(p) if p else None
        return cols[sku]
    for p in pairs:
        mesh = mesh_of(p['glb'])
        photo = (pc(p['sku']) or {}).get('rgb')
        anchor0 = None
        if p['via']:
            # mcg-v3 (T-20261118-03/10): опорная часть модели уже цвета варианта (фасады), а множитель, подобранный под медиану,
            # уводит её на ΔE ≥ broken_dE (или негоден — каналы разошлись): подкраски нет, глаз видит опорную часть
            cand = tint_from_mesh(photo, (mesh or {}).get('rgb'), R)
            anchor0 = anchor_part(photo, (mesh or {}).get('parts'), R)
            if anchor0 and not (cand == SPREAD or (cand and tint_shift(anchor0['rgb'], cand, photo) >= R['tint']['parts']['broken_dE'])):
                anchor0 = None
        for use_anchor in ((True, False) if anchor0 else (False,)):
            t, spread, anchor = None, False, (anchor0 if use_anchor else None)
            if p['via'] and not anchor:
                # подкраска от МОДЕЛИ (T-20261112-89); нет замера модели или цвета фото — прежняя, от фото представителя
                t = tint_from_mesh(photo, (mesh or {}).get('rgb'), R)
                spread = t == SPREAD
                if spread:
                    t = None
                elif t is None and not (mesh and pc(p['sku'])):
                    t = tint_of(tn(p['sku']), tn(p['owner']), R)
            seen = summary(np.array([anchor['rgb']])) if anchor else tinted(mesh, t)
            d = diff(seen, pc(p['sku']))
            v = 'mismatch' if spread and d else verdict(d, R, p['via'])
            if not anchor or v == 'ok':       # снятие подкраски не должно выбросить вариант из ленты — иначе прежнее поведение
                break
        hurt = tint_hurts(photo, (mesh or {}).get('parts'), t, R) if p['via'] else None
        rows[p['sku']] = {'asset_id': p['asset_id'], 'owner': p['owner'], 'via_family': p['via'], 'tint': t,
                          'mesh_rgb': (mesh or {}).get('rgb'), 'seen_rgb': (seen or {}).get('rgb'),
                          'photo_rgb': photo, 'seen_vs_sku': d, 'verdict': v,
                          **({'tint_spread': True} if spread else {}),
                          **({'tint_anchor': {'share': anchor['share'], 'rgb': anchor['rgb']}} if anchor else {}),
                          **({'tint_hurts_part': hurt} if hurt else {})}
    return rows


def flagged(rows: dict, via: bool) -> list:
    return sorted(k for k, r in rows.items() if r['verdict'] == 'mismatch' and bool(r['via_family']) == via)


def demo_sids() -> set:
    """Товары опубликованного демо в лентах и вариантах (артикул через «:») — для строки «из них в ленте было M»."""
    try:
        return {p['sid'].replace('_', ':', 1) for p in demo_pairs({'living', 'bedroom', 'hall'})
                if p['place'].startswith(('лента', 'вариант'))}
    except (OSError, ValueError, KeyError):
        return set()


def load_table(path: str | None = None, R: dict | None = None) -> tuple:
    """(строки {sku: вердикт} | None, причина). Нет файла — mesh_colour_missing; чужая версия правил — mesh_colour_version.
    Исключений наружу нет: привязка без таблицы идёт без отметок (fail-open, WARN у читателя)."""
    path = path or os.path.join(TABLE_DIR, TABLE)
    try:
        if not os.path.exists(path):
            return None, 'mesh_colour_missing'
        t = json.load(open(path, encoding='utf-8'))
        if t.get('version') != (R or rules())['version']:
            return None, 'mesh_colour_version'
        return t.get('rows') or {}, ''
    except Exception:  # noqa: BLE001
        return None, 'mesh_colour_corrupt'


def _atomic_json(path: str, obj) -> None:
    tmp = f'{path}.tmp{os.getpid()}'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, path)


def guard(out_dir: str = TABLE_DIR, snap_path: str = BINDINGS, workers: int = 3, seed: str | None = None) -> dict:
    import datetime
    R = rules()
    os.makedirs(out_dir, exist_ok=True)
    snap = json.load(open(snap_path, encoding='utf-8'))
    pairs = pairs_of(snap)
    cache_p = os.path.join(out_dir, 'glb-colour-cache.json')
    try:
        cache = json.load(open(cache_p, encoding='utf-8'))
    except (OSError, ValueError):
        cache = {}
    if seed and os.path.exists(seed):          # замеры переписи (тот же ключ «путь:mtime») — первая ночь не меряет заново
        for k, v in json.load(open(seed, encoding='utf-8')).items():
            cache.setdefault(k, v)
    measure_glbs([p['glb'] for p in pairs], cache, workers, save=lambda: _atomic_json(cache_p, cache))
    skus = {p['sku'] for p in pairs} | {p['owner'] for p in pairs if p['via']}
    thumbs = thumbs_of(photo_urls(skus))

    def mesh_of(g):
        m = cache.get(_gkey(g) or '')
        return m if m and 'lab' in m else None
    rows = judge(pairs, mesh_of, thumbs.get, R)
    fam, own = flagged(rows, True), flagged(rows, False)
    shown = demo_sids()
    grey = grey_top_pass(rows, pairs, out_dir, workers, shown)        # серая крышка (T-20261118-04/12): ОТДЕЛЬНОЕ поле строки, вердикт цвета выше не трогает
    counts = {'pairs': len(rows), 'unknown': sum(1 for r in rows.values() if r['verdict'] == 'unknown'),
              'family_mismatch': len(fam), 'own_mismatch': len(own), 'family_mismatch_shown': len(set(fam) & shown),
              'tint_anchor': sum(1 for r in rows.values() if r.get('tint_anchor')),
              'tint_hurts_part': sum(1 for r in rows.values() if r.get('tint_hurts_part')), **grey}
    table = {'version': R['version'], 'thresholds': {k: R['thresholds'][k] for k in ('dL', 'dab')},
             'family_thresholds': {k: (R.get('family_thresholds') or R['thresholds'])[k] for k in ('dL', 'dab')},
             'bindings_sha': snap.get('content_sha'), 'built_at': datetime.datetime.now().isoformat(timespec='seconds'),
             'counts': counts, 'rows': rows}
    _atomic_json(os.path.join(out_dir, TABLE), table)
    print(f'сторож цвета мешей ({R["version"]}): пар {counts["pairs"]}, без замера {counts["unknown"]}, '
          f'вариантов семьи с расхождением {len(fam)}, своих мешей {len(own)} → {out_dir}/{TABLE}', flush=True)
    write_own(os.path.join(out_dir, OWN_TSV), rows, own)
    print(digest_line(counts), flush=True)
    return table


def grey_top_pass(rows: dict, pairs: list, out_dir: str, workers: int, shown: set) -> dict:
    """«Серая крышка»: вердикт `mesh_grey_top` по моделям пар → поле `grey_top` в строке таблицы (только `candidate`/`reject`) и `grey-top.tsv` рядом.
    Кэш вердиктов — свой (`grey-top-cache.json`, ключ «путь:mtime:версия правил»), замер цвета не пересчитывается. Сбой не роняет сторож цвета (fail-open)."""
    import mesh_grey_top as GT
    cache_p = os.path.join(out_dir, 'grey-top-cache.json')
    try:
        cache = json.load(open(cache_p, encoding='utf-8'))
    except (OSError, ValueError):
        cache = {}
    try:
        GT.measure_glbs([p['glb'] for p in pairs], cache, workers, save=lambda: _atomic_json(cache_p, cache))
    except Exception as e:  # noqa: BLE001
        print(f'WARN:серая крышка: замер не вышел ({type(e).__name__}: {str(e)[:100]}) — поле grey_top не обновлено', flush=True)
        return {}
    lines, n = [], {'reject': 0, 'candidate': 0}
    for p in pairs:
        r = cache.get(GT._gkey(p['glb']) or '') or {}
        v = GT.effective(r, (rows.get(p['sku']) or {}).get('photo_rgb'))      # серый верх у товара, который и на фото серый, — не дефект
        if v in GT.BAD and p['sku'] in rows:
            rows[p['sku']]['grey_top'] = {k: r.get(k) for k in ('verdict', 'grey_share', 'std', 'area_px', 'mr_share', 'edge_contrast')}
            n[v] += 1
            lines.append(f"{p['sku']}\t{r['verdict']}\t{r.get('grey_share')}\t{r.get('edge_contrast')}\t{'лента/набор' if p['sku'] in shown else ''}")
    tmp = os.path.join(out_dir, GREY_TSV + f'.tmp{os.getpid()}')
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write('sku\tverdict\tgrey_share\tedge_contrast\tshown\n' + '\n'.join(sorted(lines)) + ('\n' if lines else ''))
    os.replace(tmp, os.path.join(out_dir, GREY_TSV))
    return {'grey_top_reject': n['reject'], 'grey_top_candidate': n['candidate'],
            'grey_top_shown': sum(1 for p in pairs if p['sku'] in shown and (rows.get(p['sku']) or {}).get('grey_top'))}


def write_own(path: str, rows: dict, own: list) -> None:
    """Свои меши с расхождением — список для К8 (цвет мешей, отложен владельцем): TSV рядом с таблицей, сильные сверху."""
    def sev(k):
        d = rows[k].get('seen_vs_sku') or {}
        return -(abs(d.get('dL', 0)) + d.get('dab', 0))
    tmp = f'{path}.tmp{os.getpid()}'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write('sku\tasset_id\tdL\tdab\n')
        for k in sorted(own, key=sev):
            d = rows[k].get('seen_vs_sku') or {}
            f.write(f"{k}\t{rows[k].get('asset_id')}\t{d.get('dL')}\t{d.get('dab')}\n")
    os.replace(tmp, path)


def digest_line(counts: dict) -> str:
    """Одна строка в утреннюю сводку. Свои меши — только число, не WARN (ведущий 07.11, T-14/3): это К8, отложен; вечный warn
    шага — шум, за ним не видно настоящего сбоя. warn/FAIL шага — только сбой самого сторожа (rc) или нет таблицы (room_bindings)."""
    return (f'DIGEST:сторож цвета мешей: отмечено {counts["family_mismatch"]}, из них в ленте было '
            f'{counts["family_mismatch_shown"]}; свои меши с расхождением: {counts["own_mismatch"]} (список — {OWN_TSV}); '
            f'подкраска снята по опорной части: {counts.get("tint_anchor", 0)}, подкраска портит часть модели: '
            f'{counts.get("tint_hurts_part", 0)} (поле tint_hurts_part в таблице)'
            + ('; ' + _gt_digest(counts) if 'grey_top_reject' in counts else ''))


def _gt_digest(counts: dict) -> str:
    import mesh_grey_top as GT
    return GT.digest_part(counts) + f' (список — {GREY_TSV})'


# ---------- самопроверка ----------
def _selftest() -> int:
    import tempfile
    import remlab_tmp  # временное селфтеста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)
    remlab_tmp.use('mesh_color_check-selftest')
    from PIL import Image
    bad = 0

    def ok(name, cond):
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += not cond
    ok('Lab: белый — L 100, чёрный — L 0, серый нейтрален', abs(lab([255, 255, 255])[0][0] - 100) < 0.1
       and abs(lab([0, 0, 0])[0][0]) < 0.1 and abs(lab([128, 128, 128])[0][1]) < 0.5)
    brown, white = summary(np.array([[85, 76, 71]] * 10)), summary(np.array([[146, 131, 124]] * 10))
    d = diff(white, brown)
    ok('«Сорен»: модель (146,131,124) против фото (85,76,71) — светлее на ~22 L и ~1,6 ступени, оттенок почти тот же',
       20 < d['dL'] < 26 and 1.3 < d['stops'] < 1.9 and d['dab'] < 3)
    ok('взвешенная медиана: тяжёлая грань перевешивает', wmedian(np.array([1.0, 5.0, 9.0]), np.array([1.0, 10.0, 1.0])) == 5.0)
    with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as td:
        a = np.full((100, 100, 3), 250, np.uint8)
        a[30:70, 20:80] = [120, 60, 40]
        Image.fromarray(a).save(os.path.join(td, 'card.jpg'), quality=95)
        pc = photo_colour(os.path.join(td, 'card.jpg'))
        ok('фото карточки: белый фон отброшен, цвет — у товара', pc and abs(pc['rgb'][0] - 120) <= 4 and abs(pc['rgb'][2] - 40) <= 4)
        b = np.zeros((100, 100, 4), np.uint8)
        b[10:90, 10:90] = [30, 90, 200, 255]
        Image.fromarray(b, 'RGBA').save(os.path.join(td, 'cut.png'))
        pc = photo_colour(os.path.join(td, 'cut.png'))
        ok('вырезка: только непрозрачное', pc and pc['rgb'] == [30, 90, 200] and pc['n'] == 6400)
        Image.fromarray(np.full((20, 20, 3), 250, np.uint8)).save(os.path.join(td, 'empty.jpg'))
        ok('пустое фото — цвета нет', photo_colour(os.path.join(td, 'empty.jpg')) is None)
    ok('нет замера — разницы нет', diff(None, brown) is None)
    ok('подкраска: без tint — цвет модели; ×2 по красному — краснее, синий тот же',
       tinted(brown, None) is brown and tinted(brown, [2, 1, 1])['rgb'][0] > 85 and tinted(brown, [2, 1, 1])['rgb'][2] == 71)
    # ---- сторож (T-20261107-14/2)
    R = rules()
    T = R['thresholds']
    ok('правила: версия и провенанс порога есть, порог — p99 переписи 07.11 (ΔL 44, Δab 31,6)',
       R['version'] and T['provenance'].get('census') and T['dL'] == 44.0 and T['dab'] == 31.6)
    ok('вердикт: ΔL −45 — mismatch, Δab 32 — mismatch, ΔL 43/Δab 31 — ok, нет замера — unknown',
       verdict({'dL': -45, 'dab': 1}, R) == 'mismatch' and verdict({'dL': 0, 'dab': 32}, R) == 'mismatch'
       and verdict({'dL': 43, 'dab': 31}, R) == 'ok' and verdict(None, R) == 'unknown')
    ok('подкраска как у сцены: разница < 6 % — нет, граница 2,5, нет тона — нет',
       tint_of([0.5] * 3, [0.52] * 3, R) is None and tint_of([0.9] * 3, [0.1] * 3, R) == [2.5] * 3
       and tint_of(None, [0.5] * 3, R) is None and tint_of([0.6, 0.3, 0.3], [0.3, 0.3, 0.3], R) == [2.0, 1.0, 1.0])
    snap = {'assets': {'A': {'local_path': '/m/rep.glb'}, 'B': {'local_path': '/m/own.glb'}, 'C': {}},
            'offers': {'1:v': {'asset_id': 'A', 'via_family': True, 'representative_offer_id': '1:r'},
                       '1:r': {'asset_id': 'A', 'via_family': False}, '1:o': {'asset_id': 'B', 'via_family': False},
                       '1:x': {'asset_id': 'C'}, '1:n': {'asset_id': None}}}
    pp = {p['sku']: p for p in pairs_of(snap)}
    ok('пары: вариант семьи — меш представителя, без файла модели — не судим',
       set(pp) == {'1:v', '1:r', '1:o'} and pp['1:v']['owner'] == '1:r' and pp['1:v']['via'] and pp['1:o']['owner'] == '1:o')
    with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as td:
        def card(name, rgb):
            a = np.full((80, 110, 3), 255, np.uint8)
            a[15:65, 20:90] = rgb
            p = os.path.join(td, name + '.png')
            Image.fromarray(a).save(p)
            return p
        ph = {'1:grey': card('grey', [150, 150, 150]), '1:orange': card('orange', [200, 80, 10]),
              '1:dark': card('dark', [60, 60, 60]), '1:black': card('black', [20, 20, 20]), '1:white': card('white', [215, 215, 212])}
        meshes = {'/m/orange.glb': summary(np.array([[190, 70, 5]] * 4)), '/m/grey.glb': summary(np.array([[150, 150, 150]] * 4)),
                  '/m/black.glb': summary(np.array([[2, 2, 2]] * 4))}
        P = [{'sku': '1:grey', 'owner': '1:orange', 'via': True, 'glb': '/m/orange.glb', 'asset_id': 'A'},   # Аронт: оранжевая основа
             {'sku': '1:dark', 'owner': '1:grey', 'via': True, 'glb': '/m/grey.glb', 'asset_id': 'B'},       # серая основа → тёмный вариант
             {'sku': '1:white', 'owner': '1:black', 'via': True, 'glb': '/m/black.glb', 'asset_id': 'C'},    # Риан: чёрная основа
             {'sku': '1:orange', 'owner': '1:orange', 'via': False, 'glb': '/m/grey.glb', 'asset_id': 'D'},  # свой меш другого цвета
             {'sku': '1:none', 'owner': '1:grey', 'via': True, 'glb': '/m/grey.glb', 'asset_id': 'E'}]       # нет фото товара
        rows = judge(P, meshes.get, ph.get, R)
        ok('оранжевая основа, серый товар — каналы множителя разошлись > max_spread: mismatch без подкраски (T-20261112-89)',
           rows['1:grey']['verdict'] == 'mismatch' and rows['1:grey']['tint'] is None and rows['1:grey'].get('tint_spread'))
        # «Имин Латте» (T-20261112-89, владелец TG 859): оливковая модель 99,102,68, фото 190,180,170
        lat = judge([{'sku': '9:latte', 'owner': '9:olive', 'via': True, 'glb': '/m/olive.glb', 'asset_id': 'L'}],
                    {'/m/olive.glb': summary(np.array([[99, 102, 68]] * 4))}.get,
                    {'9:latte': card('latte', [190, 180, 170])}.get, R)['9:latte']
        ok('«Латте» на оливковой модели: подкраска от модели (×5 по синему), оттенок всё равно мимо (Δab > 6) — mismatch',
           lat['verdict'] == 'mismatch' and lat['tint'] and max(lat['tint']) == R['tint']['hi_mesh']
           and lat['seen_vs_sku']['dab'] > R['family_thresholds']['dab']) or print(lat)
        bei = judge([{'sku': '9:beige', 'owner': '9:grey', 'via': True, 'glb': '/m/grey.glb', 'asset_id': 'G'}],
                    meshes.get, {'9:beige': card('beige', [200, 190, 175])}.get, R)['9:beige']
        ok('серая модель → бежевый вариант: подкраска от модели сводит к фото (|ΔL| ≤ 15, Δab ≤ 6) — ok',
           bei['verdict'] == 'ok' and bei['tint']) or print(bei)
        ok('вердикт: вариант семьи — строгий порог (ΔL 20 — mismatch), свой меш с тем же — ok',
           verdict({'dL': 20, 'dab': 1}, R, True) == 'mismatch' and verdict({'dL': 20, 'dab': 1}, R, False) == 'ok'
           and verdict({'dL': 0, 'dab': 7}, R, True) == 'mismatch')
        ok('серая основа, тёмный вариант — подкраска сводит: ok', rows['1:dark']['verdict'] == 'ok' and rows['1:dark']['tint'])
        ok('чёрная основа, белый товар — ×2,5 не поднимает чёрное: mismatch', rows['1:white']['verdict'] == 'mismatch')
        ok('свой меш другого цвета — mismatch без подкраски, в список «свои»',
           rows['1:orange']['verdict'] == 'mismatch' and rows['1:orange']['tint'] is None
           and flagged(rows, False) == ['1:orange'] and flagged(rows, True) == ['1:grey', '1:white'])
        ok('нет фото товара — unknown, не отметка', rows['1:none']['verdict'] == 'unknown')
        tp = os.path.join(td, 't.json')
        _atomic_json(tp, {'version': R['version'], 'rows': rows})
        got, why = load_table(tp, R)
        _atomic_json(tp, {'version': 'old', 'rows': rows})
        old, why2 = load_table(tp, R)
        ok('таблица: своя версия читается, чужая — нет (mesh_colour_version), нет файла — mesh_colour_missing',
           got == rows and not why and old is None and why2 == 'mesh_colour_version'
           and load_table(os.path.join(td, 'нет.json'), R) == (None, 'mesh_colour_missing'))
        own_p = os.path.join(td, OWN_TSV)
        write_own(own_p, rows, flagged(rows, False))
        lines = open(own_p, encoding='utf-8').read().splitlines()
        line = digest_line({'family_mismatch': 2, 'family_mismatch_shown': 1, 'own_mismatch': 1})
        ok('свои меши — TSV рядом с таблицей и число в DIGEST, без WARN (статус шага ok)',
           len(lines) == 2 and lines[1].startswith('1:orange\tD\t') and line.startswith('DIGEST:')
           and 'отмечено 2, из них в ленте было 1; свои меши с расхождением: 1' in line and 'WARN' not in line)
    # ---- части модели (mcg-v3, T-20261118-03/10: фасады «Теджонс Ромб Латте» голубые)
    Pp = R['tint']['parts']
    wood, latte, wood2 = [195, 154, 112], [181, 167, 156], [179, 130, 86]
    ok('правила mcg-v3: версия, доли 15 %/8 %, ΔE 12/20',
       R['version'] == 'mcg-v3' and Pp['min_share'] == 0.15 and Pp['watch_share'] == 0.08 and Pp['match_dE'] == 12.0 and Pp['broken_dE'] == 20.0)
    ok('дерево по цвету: тёплое коричневое — да; латте, серый, белый, тёмный графит — нет',
       is_wood(wood, Pp) and is_wood(wood2, Pp) and not is_wood(latte, Pp) and not is_wood([150, 150, 150], Pp)
       and not is_wood([240, 240, 236], Pp) and not is_wood([60, 60, 62], Pp))
    C = np.array([wood] * 63 + [latte] * 19 + [wood2] * 18, np.float64)
    cp = part_colours(C, np.ones(len(C)), R)
    ok('части: 3 цвета, доли 63/19/18 %, у латте wood=False, повтор даёт то же',
       [round(x['share'], 2) for x in cp] == [0.63, 0.19, 0.18] and [x['wood'] for x in cp] == [True, False, True]
       and abs(cp[1]['rgb'][0] - 181) <= 1 and cp == part_colours(C, np.ones(len(C)), R))
    tej = [{'share': .63, 'rgb': wood, 'wood': True}, {'share': .19, 'rgb': latte, 'wood': False}, {'share': .17, 'rgb': wood2, 'wood': True}]
    photo = [181, 169, 159]
    ok('опорная часть: «Теджонс» — латте-фасады (19 %, ΔE ~0) — да', (anchor_part(photo, tej, R) or {}).get('rgb') == latte)
    ok('опорной нет: совпала мелкая часть (12 %, < 15 %)',
       anchor_part(photo, [tej[0], {'share': .12, 'rgb': latte, 'wood': False}, {'share': .25, 'rgb': [20, 20, 20], 'wood': False}], R) is None)
    ok('опорной нет: совпавшая — не самая крупная из не-деревянных (графит 30 % крупнее)',
       anchor_part(photo, tej + [{'share': .30, 'rgb': [60, 60, 62], 'wood': False}], R) is None)
    ok('опорной нет: цвет варианта далеко от фасадов; частей нет; фото нет; совпало дерево (не опора)',
       anchor_part([60, 60, 200], tej, R) is None and anchor_part(photo, None, R) is None and anchor_part(None, tej, R) is None
       and anchor_part(wood, tej[:1] + tej[2:], R) is None)
    th = tint_hurts(photo, tej, [0.866, 1.228, 2.1], R)
    ok('слепота «медиана × tint»: подкраска Теджонса ломает фасады (ΔE после ≥ 20), без подкраски и на мелкой части — нет',
       th and th['dE'] >= Pp['broken_dE'] and th['before'] == latte and tint_hurts(photo, tej, None, R) is None
       and tint_hurts(photo, [{'share': .05, 'rgb': latte, 'wood': False}], [0.866, 1.228, 2.1], R) is None)
    mesh_t = summary(np.array([wood] * 63 + [latte] * 19 + [wood2] * 18, np.float64))
    mesh_t['parts'] = tej
    with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as td2:
        a = np.full((80, 110, 3), 255, np.uint8)
        a[15:65, 20:90] = photo
        pth = os.path.join(td2, 'romb.png')
        Image.fromarray(a).save(pth)
        PJ = [{'sku': '9:romb', 'owner': '9:deco', 'via': True, 'glb': '/m/t.glb', 'asset_id': 'T'}]
        new = judge(PJ, {'/m/t.glb': mesh_t}.get, {'9:romb': pth}.get, R)['9:romb']
        old = judge(PJ, {'/m/t.glb': {k: v for k, v in mesh_t.items() if k != 'parts'}}.get, {'9:romb': pth}.get, R)['9:romb']
        ok('сторож на «Теджонсе»: с частями — подкраски нет, видна опорная часть, вердикт ok; без частей (старый замер) — прежняя подкраска',
           new['tint'] is None and new['tint_anchor']['rgb'] == latte and new['verdict'] == 'ok' and 'tint_hurts_part' not in new
           and old['tint'] and 'tint_anchor' not in old) or print(new, old)
        # мелкая совпавшая часть (12 %): подкраска остаётся, но сторож её видит (поле tint_hurts_part) — список для разбора
        small = dict(mesh_t, parts=[tej[0], {'share': .12, 'rgb': latte, 'wood': False}, {'share': .25, 'rgb': [20, 20, 20], 'wood': False}])
        sm = judge(PJ, {'/m/t.glb': small}.get, {'9:romb': pth}.get, R)['9:romb']
        ok('мелкая совпавшая часть (12 %): подкраска остаётся (осторожно), сторож метит tint_hurts_part',
           sm['tint'] and 'tint_anchor' not in sm and sm.get('tint_hurts_part', {}).get('dE', 0) >= Pp['broken_dE']) or print(sm)
        # дробление одного цвета k-средними: тёмные фасады 31+20+2 % и светлая цельная столешница 39 % — опорной не должно стать столешницей
        frag = [{'share': .39, 'rgb': [96, 98, 100], 'wood': False}, {'share': .31, 'rgb': [19, 19, 18], 'wood': False},
                {'share': .20, 'rgb': [22, 22, 21], 'wood': False}, {'share': .02, 'rgb': [13, 12, 13], 'wood': False}]
        mg = merge_parts(frag, R)
        ok('слияние кластеров одного цвета: тёмные 53 % крупнее светлых 39 %; повторное слияние не меняет',
           len(mg) == 2 and mg[0]['rgb'][0] < 25 and abs(mg[0]['share'] - .53) < .01 and merge_parts(mg, R) == mg) or print(mg)
        ok('опорной части нет, когда цельная светлая часть меньше слитых тёмных',
           anchor_part([83, 82, 80], frag, R) is None)
        # тёмно-зелёные фасады 18 % и светлая полка 19 % (кадр 18.11): опорная не «заметно крупнее» остальных — подкраска остаётся
        close = [{'share': .193, 'rgb': [185, 186, 180], 'wood': False}, {'share': .182, 'rgb': [25, 35, 20], 'wood': False}]
        ok('опорной части нет, если вторая не-деревянная часть почти такого же размера (лидерство < 1,5×)',
           anchor_part([193, 192, 188], close, R) is None
           and anchor_part([193, 192, 188], [close[0], dict(close[1], share=.08)], R) is not None)
        # подкраска слабая (опорная часть уходит на ΔE < 20) — остаётся как раньше: правило не трогает то, что почти верно
        mild = dict(summary(np.array([[165, 152, 142]] * 100, np.float64)),
                    parts=[{'share': .7, 'rgb': [165, 152, 142], 'wood': False}, {'share': .3, 'rgb': wood, 'wood': True}])
        mrow = judge(PJ, {'/m/t.glb': mild}.get, {'9:romb': pth}.get, R)['9:romb']
        ok('слабая подкраска (часть уходит на ΔE < 20): остаётся, опорной нет',
           mrow['tint'] and 'tint_anchor' not in mrow) or print(mrow)
    line2 = digest_line({'family_mismatch': 2, 'family_mismatch_shown': 1, 'own_mismatch': 1, 'tint_anchor': 22, 'tint_hurts_part': 3})
    ok('DIGEST: добавлены числа «снята по опорной части» и «портит часть», без WARN',
       'подкраска снята по опорной части: 22' in line2 and 'портит часть модели: 3' in line2 and 'WARN' not in line2)
    # СЕРАЯ КРЫШКА (T-20261118-04/12): отдельное поле строки, вердикт цвета не меняется; кэш и список рядом; сбой замера — fail-open
    import mesh_grey_top as GT
    with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as gd:
        glbs = {k: os.path.join(gd, f'{k}.glb') for k in ('grey', 'fine', 'bad')}
        for g in glbs.values():
            open(g, 'wb').write(b'x')
        gcache = {GT._gkey(glbs['grey']): {'verdict': 'reject', 'grey_share': 0.97, 'edge_contrast': 60.0, 'median_rgb': [130, 130, 130]},
                  GT._gkey(glbs['fine']): {'verdict': 'ok'}}
        json.dump(gcache, open(os.path.join(gd, 'grey-top-cache.json'), 'w'))
        # glb 'bad' не в кэше → замер зовёт настоящий детектор; подмена: пустой файл не GLB → запись об ошибке, но не падение
        grows = {'1:grey': {'verdict': 'ok'}, '2:fine': {'verdict': 'mismatch'}, '3:bad': {'verdict': 'ok'}}
        gpairs = [{'sku': '1:grey', 'glb': glbs['grey']}, {'sku': '2:fine', 'glb': glbs['fine']}, {'sku': '3:bad', 'glb': glbs['bad']}]
        c = grey_top_pass(grows, gpairs, gd, 1, {'1:grey'})
        ok('серая крышка: поле только у reject/candidate, вердикт цвета не тронут',
           grows['1:grey']['grey_top']['verdict'] == 'reject' and 'grey_top' not in grows['2:fine'] and grows['2:fine']['verdict'] == 'mismatch'
           and grows['1:grey']['verdict'] == 'ok')
        ok('серая крышка: числа и «в ленте» в счётчиках, битый GLB не роняет', c == {'grey_top_reject': 1, 'grey_top_candidate': 0, 'grey_top_shown': 1})
        tl = open(os.path.join(gd, GREY_TSV), encoding='utf-8').read().splitlines()
        ok('серая крышка: список grey-top.tsv — шапка и одна строка с пометкой «лента/набор»', len(tl) == 2 and tl[1].startswith('1:grey\treject\t0.97\t60.0\tлента'))
    ok('DIGEST: серая крышка отдельной частью, без WARN', 'серая крышка' in digest_line({'family_mismatch': 0, 'family_mismatch_shown': 0, 'own_mismatch': 0, 'grey_top_reject': 3,
                                                                                     'grey_top_candidate': 4, 'grey_top_shown': 2}) and 'отказ 3' in digest_line(
        {'family_mismatch': 0, 'family_mismatch_shown': 0, 'own_mismatch': 0, 'grey_top_reject': 3, 'grey_top_candidate': 4, 'grey_top_shown': 2}))
    print(f'mesh_color_check: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    if len(sys.argv) >= 3 and sys.argv[1] == 'census':
        rooms = {'living', 'bedroom', 'hall'}
        workers = 3
        if '--rooms' in sys.argv:
            rooms = set(sys.argv[sys.argv.index('--rooms') + 1].split(','))
        if '--workers' in sys.argv:
            workers = int(sys.argv[sys.argv.index('--workers') + 1])
        census(sys.argv[2], rooms, workers)
        sys.exit(0)
    if len(sys.argv) >= 2 and sys.argv[1] == 'guard':
        a = sys.argv
        arg = lambda k, d=None: a[a.index(k) + 1] if k in a else d  # noqa: E731
        guard(arg('--out', TABLE_DIR), arg('--bindings', BINDINGS), int(arg('--workers', 3)), arg('--seed-cache'))
        sys.exit(0)
    print(__doc__)
    sys.exit(2)
