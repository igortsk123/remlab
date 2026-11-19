#!/usr/bin/env python3
"""ПОКРЫТИЕ ТЕКСТУРЫ MV-Adapter (T-20261119-06/6/1, п.3): какая доля карты краски НЕ нарисована сетью, а заполнена заплатками или осталась фоном.
Бесплатно, на процессоре (pakardev), только numpy + trimesh (+ PIL). Вход — GLB-результат MV-Adapter (`*-mvtex.glb`: форма, развёртка и текстура), выход — числа, картинка-проверка и
решение автоматики `verdict` (keep / repaint / reject).

ЧТО МЕРИМ — по ТЕКСЕЛЯМ карты внутри островков развёртки (и то же по ПЛОЩАДИ поверхности: у текселя вес = площадь грани в 3D / её площадь в карте — густо уложенные островки не врут):
  unseen    — тексель не виден ни с одного из 6 видов MV-Adapter: его краску сеть не видела, апстрим (`inpaint_mode='view'`) дорисовывает такие места заплатками (LaMa).
  grazing   — виден, но только «вскользь»: лучшее |cos| между нормалью и направлением на камеру < 0,35 (картинка сильно растянута).
  unpainted — тексель цвета «фона», почти чёрный или почти белый, то есть краска туда не легла (пороги `UNPAINTED`). Отдельно `unpainted_seen` — только среди видимых (там это настоящий провал краски;
              среди невидимых заплатка тоже может дать белое). У белой мебели честно белый цвет попадает в unpainted — потому решение по нему мягче и смотрит на цифры вместе.

«НАРУЖУ» — ВАЖНО. У сеток TRELLIS внутри много поверхностей (ящики, толщина рельефа; у комода 17,3 площади при 3,5 у выпуклой оболочки), и до 80 % текселей не видны ни с одного вида просто потому,
что спрятаны внутри. Покупатель их не увидит. Поэтому доли считаются два раза: по ВСЕМ текселям и по «наружным» — видимым хотя бы с одного из 26 направлений вокруг предмета (грани, углы и рёбра куба, ортографический
буфер глубины `EXT_RES`²; 6 видов MV-Adapter входят). Решение `verdict` смотрит на наружные доли (`*_outer_*`): «из того, что видно снаружи, столько-то заплатки/вскользь/пустое».

КАК ВИДНО (та же камера, что у апстрима, `worker_trellis.py:MV_AZ/MV_ORTHO`; сверка с апстримом — `~/ext-src/mvadapter-1911/repo/mvadapter/utils/mesh_utils/camera.py` и `pipelines/pipeline_texture.py:199-205`):
  6 видов, ортографическая камера ±0,55 (сторона `MV_ORTHO` = 1,1), азимуты `MV_AZ` (уже минус 90°), подъёмы 0/0/0/0/+89,99/−89,99, мир апстрима Z вверх → наш кадр GLB (Y вверх, лицом +Z) поворотом
  (x, y, z)_мир → (x, z, −y)_наш: вид 0 = «в лоб» (смотрит на сторону +Z, вверх +Y, вправо +X; совпадает с `worker_trellis.mv_ortho_uv`, проверено тестом). Форма — в куб с поворотом `yaw`, как у воркера
  (`worker_trellis.to_cube`): `yaw` берётся из сводки драйвера (`summary-*.json` → задание → `metrics.fit.yaw_deg`) или `--yaw`.
  Тексель виден с вида, если его точка в кадре — ПЕРВАЯ вдоль луча (буфер глубины 768², как у апстрима; допуск глубины 0,002 размера предмета + наклон) и |cos(нормаль, на камеру)| > 0,1.
  Вместо лучей trimesh.ray на rtree здесь свой буфер глубины на numpy: ИТОГ тот же («первая грань вдоль луча»), но в разы быстрее (несколько секунд на 300 тыс. граней); равенство с `trimesh.ray` проверяет
  `tests_tex_coverage.py` на шаре. |cos| (а не знак) — потому что у сеток TRELLIS порядок обхода не всегда «наружу», знак дал бы ложные «не видно».

РЕШЕНИЕ. `verdict(metrics, thresholds=THRESHOLDS)` → `keep` (оставить) / `repaint` (перекрасить другим seed или другой краской) / `reject` (не публиковать, повтор ночью). ВСЕ числа порогов — в словаре `THRESHOLDS`
вверху файла (или `--thresholds файл.json`); сейчас ЧЕРНОВЫЕ — их настраивает ведущий по данным 30 товаров. Метрики в проценты (`*_pct`) и из таблицы пробы (`de00`, `dL`, `pattern_grad_ncc`); нет метрики — порог пропускается.

СРАВНЕНИЕ С ФОТО (главная мера владельца — узор и цвет как на фото) НЕ считается здесь: его уже считает `trial_table.py:measure_pair` (ΔE00 и ΔL медиан Lab по переднему кадру без света против цвета вырезки,
`pattern_grad_ncc` — `pattern_metric.py`, `colour_guard` — `mesh_color_check`), результат лежит в `trial-table.csv` (колонки de00, dL, pattern_grad_ncc, colour_guard). `--table trial-table.csv [--model имя]` подмешивает
эти колонки в нашу таблицу рядом с долями (товар находится по ключу `sku` → `магазин_товар` в начале имени GLB). Точнее по узору есть `score_pixal_tex.py` (камера по силуэту, фасадные участки).

  ~/venvs/scout/bin/python tex_coverage.py [--out ДИР] [--yaw auto|0|90|180|270] [--grid 2048] [--view-res 768] [--table trial-table.csv --model имя] [--thresholds t.json] [--no-glb] ПУТЬ...
      ПУТЬ — GLB или папка (из неё берутся `*-mvtex.glb`, `--pattern` меняет). Результат в `--out` (по умолчанию — рядом с GLB):
      `<имя>.coverage.json` (доли, решение, время) · `<имя>.coverage.glb` (красный — unseen, жёлтый — grazing, синий — unpainted; снять кадр az045 штатным `render_stand.py`) ·
      `coverage-summary.md/.json/.csv` (таблица набора).
  ~/venvs/scout/bin/python tex_coverage.py --selftest      # то же, что `tests_tex_coverage.py`
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# --- камера апстрима (сверка: `pipeline_texture.py:165-166` — подъёмы и азимуты по умолчанию; MV_AZ/MV_ORTHO — у воркера)
MV_ELEV = [0.0, 0.0, 0.0, 0.0, 89.99, -89.99]
COS_SEEN = 0.1               # ниже — вид текселю не помогает (почти ребро)
COS_GRAZE = 0.35             # лучший |cos| ниже — «вскользь»
DEPTH_EPS = 0.002            # допуск глубины «первая грань», доли размера предмета (≈ 1,5 пикселя вида 768²); внутренняя стенка тоньше этого сливается с наружной
EXT_DIRS = 26                # направления «наружу» (куб: 6 граней + 12 рёбер + 8 углов); 0 — не считать наружные доли
EXT_RES = 384                # буфер глубины наружных видов, пикселей (ортограф. сторона 1,8 — диагональ куба 1,73)
EXT_ORTHO = 1.8
EXT_COS = 0.3                 # «снаружи» — видно с |cos| не меньше (под скользящим углом допуск глубины растёт и пропускает стенки изнутри)
UNPAINTED = {'black_max': 12, 'white_min': 245}      # тексель «фон»: все каналы ≤ black_max (чёрный) или ≥ white_min (белый)
# ШВЫ ВИДОВ. «Главный вид» текселя — вид MV-Adapter с наибольшим |cos| среди видящих его. Граница — пара соседних на поверхности текселей (расстояние между точками ≤ `neigh` размеров тексела
# по сетке карты) с РАЗНЫМ главным видом; скачок — ΔE00 между их цветами. Плохой шов: скачок > max(abs_de, ratio × p-й перцентиль скачков у пар ВНУТРИ областей одного главного вида по этому же товару):
# абсолютный пол — чтобы гладкий товар (внутри почти 0) не ловил заметный глазу, но слабый скачок; относительный — чтобы пёстрое дерево, где внутри ΔE и так большой, не было «сплошным швом».
SEAM = {'neigh': 2.5, 'abs_de': 10.0, 'ratio': 1.5, 'inner_pct': 95.0, 'inner_sample': 400000}
# ПОЧЕМУ unseen среди наружных (диагностика, `explain`): мелкие отдельные куски формы («крошки», площадь куска < crumb_area_frac площади всей формы) · узкие места основного тела
# (видны снаружи не более crevice_max_dirs из 26 направлений: щели, зазоры подушек) · остальное `gap` — реально видимые места, до которых 6 видов не дотянулись; из них `gap_edge_on` — не закрыты,
# но смотрят на все 6 видов ребром (|cos| ≤ COS_SEEN: каркас дивана, торцы), `gap_occluded` — закрыты другими частями формы во всех 6 видах (боковины под подлокотником, зазоры под подушками).
EXPLAIN = {'crumb_area_frac': 0.01, 'crevice_max_dirs': 2}

# --- ПОРОГИ РЕШЕНИЯ (ЧЕРНОВЫЕ; единственное место чисел). `max`: метрика БОЛЬШЕ порога → сработало; `min`: метрика МЕНЬШЕ порога → сработало.
# Порядок: сначала `reject`, потом `repaint`; ничего не сработало → `keep`. Метрики — ключи `flat_metrics` (проценты) и колонки таблицы пробы.
THRESHOLDS = {
    'reject': {
        'max': {'unseen_outer_tex_pct': 45.0, 'unpainted_seen_tex_pct': 30.0, 'de00': 40.0, 'seam_tex_pct': 12.0, 'seam_len_pct': 60.0},
        'min': {},
    },
    'repaint': {
        'max': {'unseen_outer_tex_pct': 20.0, 'grazing_outer_tex_pct': 30.0, 'unpainted_outer_tex_pct': 8.0, 'de00': 25.0, 'seam_tex_pct': 4.0, 'seam_len_pct': 30.0},
        'min': {},          # например {'pattern_grad_ncc': 0.05}: слабая справочная мера, пока без порога
    },
}


# ---------------------------------------------------------------- решение ---------------------------------------
def _judge(metrics: dict, thresholds: dict | None = None) -> tuple[str, list]:
    th = THRESHOLDS if thresholds is None else thresholds
    for verdict in ('reject', 'repaint'):
        why = []
        rule = th.get(verdict) or {}
        for name, lim in (rule.get('max') or {}).items():
            v = metrics.get(name)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > lim:
                why.append(f'{name} {v:g} > {lim:g}')
        for name, lim in (rule.get('min') or {}).items():
            v = metrics.get(name)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v < lim:
                why.append(f'{name} {v:g} < {lim:g}')
        if why:
            return verdict, why
    return 'keep', []


def verdict(metrics: dict, thresholds: dict | None = None) -> str:
    """keep | repaint | reject по метрикам (словарь `*_pct` и колонок таблицы) и порогам (по умолчанию `THRESHOLDS`). Нет метрики — её порог пропускается."""
    return _judge(metrics, thresholds)[0]


# ---------------------------------------------------------------- растеризатор (буфер глубины на numpy) -------
def _commit(pix, d, fid, ids, zb):
    """Лучшее (самое близкое, d больше = ближе) по пикселю из пачки кандидатов, и сравнение с уже записанным."""
    import numpy as np
    if len(pix) == 0:
        return
    order = np.lexsort((-d, pix))
    pix, d, fid = pix[order], d[order], fid[order]
    first = np.ones(len(pix), bool)
    first[1:] = pix[1:] != pix[:-1]
    pix, d, fid = pix[first], d[first], fid[first]
    better = d > zb[pix]
    ids[pix[better]] = fid[better]
    zb[pix[better]] = d[better]


def raster(xy, faces, n: int, depth=None, chunk: int = 3_000_000):
    """Треугольники → буфер id граней n×n (плоский, -1 пусто) и буфер глубины. `xy` — вершины в пикселях (x вправо, y вниз; центр пикселя (i+0,5; j+0,5)); `depth` — по вершинам, БОЛЬШЕ = БЛИЖЕ
    (None — все 0: кто первый, тот и занял). Маленькие грани (в сумме — почти все) идут пачками без цикла, большие (>16 px) — по одной."""
    import numpy as np
    xy = np.asarray(xy, np.float64)
    faces = np.asarray(faces, np.int64)
    ids = np.full(n * n, -1, np.int32)
    zb = np.full(n * n, -np.inf, np.float64)
    if len(faces) == 0:
        return ids, zb
    A, B, C = xy[faces[:, 0]], xy[faces[:, 1]], xy[faces[:, 2]]
    D = np.zeros((len(faces), 3)) if depth is None else np.asarray(depth, np.float64)[faces]
    area = (B[:, 0] - A[:, 0]) * (C[:, 1] - A[:, 1]) - (B[:, 1] - A[:, 1]) * (C[:, 0] - A[:, 0])
    mn, mx = np.minimum(np.minimum(A, B), C), np.maximum(np.maximum(A, B), C)
    x0 = np.maximum(np.ceil(mn[:, 0] - 0.5), 0).astype(np.int64)
    x1 = np.minimum(np.floor(mx[:, 0] - 0.5), n - 1).astype(np.int64)
    y0 = np.maximum(np.ceil(mn[:, 1] - 0.5), 0).astype(np.int64)
    y1 = np.minimum(np.floor(mx[:, 1] - 0.5), n - 1).astype(np.int64)
    w, h = x1 - x0 + 1, y1 - y0 + 1
    ok = (np.abs(area) > 1e-12) & (w > 0) & (h > 0)
    size = np.maximum(w, h)

    def inside(f, gx, gy):
        """gx, gy — массивы индексов пикселей той же формы, что `f` (по грани на элемент) → (маска внутри, глубина)."""
        px, py = gx + 0.5, gy + 0.5
        a, b, c, ar = A[f], B[f], C[f], area[f]
        wa = ((b[..., 0] - px) * (c[..., 1] - py) - (b[..., 1] - py) * (c[..., 0] - px)) / ar
        wb = ((c[..., 0] - px) * (a[..., 1] - py) - (c[..., 1] - py) * (a[..., 0] - px)) / ar
        wc = 1.0 - wa - wb
        m = (wa >= -1e-9) & (wb >= -1e-9) & (wc >= -1e-9)
        d = wa * D[f, 0] + wb * D[f, 1] + wc * D[f, 2]
        return m, d

    tiers = (1, 2, 4, 8, 16)
    for K in tiers:
        lo = K // 2 if K > 1 else 0
        sel = np.nonzero(ok & (size > lo) & (size <= K))[0]
        per = max(1, chunk // (K * K))
        ar = np.arange(K)
        for s in range(0, len(sel), per):
            f = sel[s:s + per]
            gx = x0[f][:, None, None] + ar[None, None, :]
            gy = y0[f][:, None, None] + ar[None, :, None]
            valid = (gx <= x1[f][:, None, None]) & (gy <= y1[f][:, None, None])
            gx, gy = np.broadcast_to(gx, valid.shape), np.broadcast_to(gy, valid.shape)
            ff = np.broadcast_to(f[:, None, None], valid.shape)
            m, d = inside(ff, gx, gy)
            m &= valid
            _commit((gy[m] * n + gx[m]).astype(np.int64), d[m], ff[m].astype(np.int32), ids, zb)
    for f in np.nonzero(ok & (size > tiers[-1]))[0]:
        gx, gy = np.meshgrid(np.arange(x0[f], x1[f] + 1), np.arange(y0[f], y1[f] + 1))
        ff = np.full(gx.shape, f)
        m, d = inside(ff, gx, gy)
        _commit((gy[m] * n + gx[m]).astype(np.int64), d[m], ff[m].astype(np.int32), ids, zb)
    return ids, zb


# ---------------------------------------------------------------- камеры MV-Adapter -----------------------------
def mv_views(azimuths=None, elevations=None) -> list:
    """Камеры апстрима в НАШЕМ кадре (Y вверх, лицом +Z): список (на_камеру c, вправо r, вверх u) — единичные векторы. Формулы — `get_c2w` апстрима
    (камера на (cos e cos a, cos e sin a, sin e), взгляд в центр, вверх +Z мира, вправо = взгляд × вверх); мир → наш кадр (x, y, z) → (x, z, −y)."""
    import numpy as np
    if azimuths is None:
        import worker_trellis as W
        azimuths = W.MV_AZ
    elevations = MV_ELEV if elevations is None else elevations
    out = []

    def to_ours(v):
        return np.array([v[0], v[2], -v[1]], np.float64)

    for az, el in zip(azimuths, elevations):
        a, e = np.radians(az), np.radians(el)
        cam = np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)])
        look = -cam
        right = np.cross(look, [0.0, 0.0, 1.0])
        right /= np.linalg.norm(right)
        up = np.cross(right, look)
        up /= np.linalg.norm(up)
        out.append((to_ours(cam), to_ours(right), to_ours(up)))
    return out


def project(P, view, ortho: float = 1.1):
    """Точки куба (N,3) → (x, y) в долях кадра вида [0, 1]² (y вниз, как строка картинки) и глубина (больше = ближе к камере)."""
    c, r, u = view
    return 0.5 + P @ r / ortho, 0.5 - P @ u / ortho, P @ c


# ---------------------------------------------------------------- покрытие ----------------------------------------
def rgb2lab(rgb):
    """sRGB uint8 (N,3) → Lab (N,3), белая точка D65."""
    import numpy as np
    c = np.asarray(rgb, np.float64) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    M = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
    xyz = (c @ M.T) / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], 1)


def de2000_v(l1, l2):
    """CIEDE2000 между двумя массивами Lab (N,3) (Sharma, Wu, Dalal 2005; kL=kC=kH=1) — по строкам."""
    import numpy as np
    L1, a1, b1 = l1[:, 0], l1[:, 1], l1[:, 2]
    L2, a2, b2 = l2[:, 0], l2[:, 1], l2[:, 2]
    C1, C2 = np.hypot(a1, b1), np.hypot(a2, b2)
    Cb = (C1 + C2) / 2
    G = 0.5 * (1 - np.sqrt(Cb ** 7 / (Cb ** 7 + 25.0 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dL, dC = L2 - L1, C2p - C1p
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where((C1p * C2p) == 0, 0.0, dh)
    dH = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dh / 2))
    Lb, Cpb = (L1 + L2) / 2, (C1p + C2p) / 2
    hs = h1p + h2p
    hb = np.where((C1p * C2p) == 0, hs, np.where(np.abs(h1p - h2p) <= 180, hs / 2, np.where(hs < 360, (hs + 360) / 2, (hs - 360) / 2)))
    T = 1 - 0.17 * np.cos(np.radians(hb - 30)) + 0.24 * np.cos(np.radians(2 * hb)) + 0.32 * np.cos(np.radians(3 * hb + 6)) - 0.20 * np.cos(np.radians(4 * hb - 63))
    dth = 30 * np.exp(-(((hb - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(Cpb ** 7 / (Cpb ** 7 + 25.0 ** 7))
    Sl = 1 + 0.015 * (Lb - 50) ** 2 / np.sqrt(20 + (Lb - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cpb, 1 + 0.015 * Cpb * T
    Rt = -np.sin(np.radians(2 * dth)) * Rc
    return np.sqrt((dL / Sl) ** 2 + (dC / Sc) ** 2 + (dH / Sh) ** 2 + Rt * (dC / Sc) * (dH / Sh))


def seam_pairs(T: int, ti, Q, tsize, mvi, seen, rgb, rng):
    """Пары соседних по карте текселей (вправо и вниз), оба видимы и ТОЖЕ соседи на поверхности (расстояние ≤ SEAM['neigh'] размеров тексела: чужие островки рядом на карте отсеиваются).
    Возвращает (ai, bi, de, ln) для границ главных видов — индексы в массивах текселей геометрии, скачок ΔE00, длина (средний размер тексела) — и de_inner: скачки у пар внутри областей (выборка)."""
    import numpy as np
    idx = np.full(T * T, -1, np.int64)
    idx[ti] = np.arange(len(ti))
    idx = idx.reshape(T, T)
    A, B = [], []
    for a, b in ((idx[:, :-1], idx[:, 1:]), (idx[:-1, :], idx[1:, :])):
        m = (a >= 0) & (b >= 0)
        A.append(a[m])
        B.append(b[m])
    A, B = np.concatenate(A), np.concatenate(B)
    m = seen[A] & seen[B]
    A, B = A[m], B[m]
    ts = np.maximum(tsize[A], tsize[B])
    m = np.linalg.norm(Q[A] - Q[B], axis=1) <= SEAM['neigh'] * np.maximum(ts, 1e-12)
    A, B, ts = A[m], B[m], ts[m]
    edge = mvi[A] != mvi[B]
    ai, bi, tb = A[edge], B[edge], ts[edge]
    ia, ib = A[~edge], B[~edge]
    if len(ia) > SEAM['inner_sample']:
        pick = rng.choice(len(ia), SEAM['inner_sample'], replace=False)
        ia, ib = ia[pick], ib[pick]
    de = de2000_v(rgb2lab(rgb[ai]), rgb2lab(rgb[bi])) if len(ai) else np.zeros(0)
    di = de2000_v(rgb2lab(rgb[ia]), rgb2lab(rgb[ib])) if len(ia) else np.zeros(0)
    return ai, bi, de, tb, di


def face_components(P, F, area):
    """Куски формы: связность граней по ПОЛОЖЕНИЮ вершин (в GLB вершины дублируются по швам развёртки). → (метка куска у каждой грани, площадь куска по меткам) или None без scipy."""
    import numpy as np
    try:
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
    except ImportError:
        return None
    _u, inv = np.unique(np.round(np.asarray(P, np.float64) * 1e5).astype(np.int64), axis=0, return_inverse=True)
    inv = np.asarray(inv).reshape(-1)
    n = int(inv.max()) + 1
    rows = np.concatenate([inv[F[:, 0]], inv[F[:, 1]], inv[F[:, 2]]])
    cols = np.concatenate([inv[F[:, 1]], inv[F[:, 2]], inv[F[:, 0]]])
    _k, lab = connected_components(coo_matrix((np.ones(len(rows), np.int8), (rows, cols)), shape=(n, n)), directed=False)
    cf = lab[inv[F[:, 0]]]
    return cf, np.bincount(cf, weights=area, minlength=int(cf.max()) + 1)


def ext_views(n: int = EXT_DIRS) -> list:
    """Направления «наружу»: до 26 (грани, рёбра и углы куба), как камеры (на_камеру, вправо, вверх) в нашем кадре. Вверх — +Y (у вертикальных направлений — +Z)."""
    import itertools
    import numpy as np
    dirs = [np.array(d, np.float64) for d in itertools.product((-1, 0, 1), repeat=3) if any(d)]
    dirs.sort(key=lambda d: (int(np.count_nonzero(d)), tuple(d)))                  # сначала грани (6), потом рёбра (12), углы (8)
    out = []
    for c in dirs[:max(0, n)]:
        c = c / np.linalg.norm(c)
        up0 = np.array([0.0, 1.0, 0.0]) if abs(c[1]) < 0.99 else np.array([0.0, 0.0, 1.0])
        r = np.cross(-c, up0)
        r /= np.linalg.norm(r)
        u = np.cross(r, -c)
        out.append((c, r, u / np.linalg.norm(u)))
    return out


def analyze(geoms: list, yaw: float = 0.0, grid: int = 2048, view_res: int = 768, signed: bool = False, ext_n: int = EXT_DIRS) -> dict:
    """geoms — список {'V' (n,3), 'F' (m,3), 'UV' (n,2) (v вверх, как у trimesh), 'tex' uint8 (H,W,3|4)}; всё вместе — один предмет (загораживают друг друга).
    Возвращает {'tex', 'area' (доли по всем текселям/площади), 'outer_tex', 'outer_area' (доли среди наружных), 'n_island', 'maps': [ {'cls' (T,T) uint8: 0 вне/1 норма/2 unseen наружу/3 grazing/
    4 unpainted/5 unseen внутри, 'base' (T,T,3)} по геометриям], 'time_s'}."""
    import numpy as np
    import worker_trellis as W
    t0 = time.time()
    stage = {}
    Vall = np.concatenate([np.asarray(g['V'], np.float64) for g in geoms])
    offs = np.cumsum([0] + [len(g['V']) for g in geoms])
    Fall = np.concatenate([np.asarray(g['F'], np.int64) + offs[i] for i, g in enumerate(geoms)])
    P, _c, _s, _R = W.to_cube(Vall, yaw)
    views = mv_views(W.MV_AZ)
    # 1) буфер глубины по каждому виду MV-Adapter и по наружным направлениям (вся сцена); (вид, буфер, разрешение, ортографическая сторона)
    cams = []
    for v in views:
        x, y, d = project(P, v, W.MV_ORTHO)
        cams.append((v, raster(np.stack([x * view_res, y * view_res], 1), Fall, view_res, d)[1], view_res, W.MV_ORTHO, True))
    stage['zbuf'] = round(time.time() - t0, 2)
    for v in ext_views(ext_n):
        x, y, d = project(P, v, EXT_ORTHO)
        cams.append((v, raster(np.stack([x * EXT_RES, y * EXT_RES], 1), Fall, EXT_RES, d)[1], EXT_RES, EXT_ORTHO, False))
    stage['zbuf_ext'] = round(time.time() - t0, 2)
    KEYS = ('island', 'unseen', 'grazing', 'unpainted', 'unpainted_seen')
    tot = {sub: {k: 0 for k in KEYS} for sub in ('t', 'a', 'ot', 'oa')}
    for sub in ('a', 'oa'):
        tot[sub] = {k: 0.0 for k in KEYS}
    maps = []
    seam_store = []
    expl = {'unseen_outer': 0, 'crumbs': 0, 'crevice': 0, 'gap': 0, 'gap_edge_on': 0, 'gap_occluded': 0, 'components': 0, 'crumb_components': 0, 'crumb_area': 0.0, 'area': 0.0, 'ok': True}
    rng = np.random.RandomState(7)
    for gi, g in enumerate(geoms):
        T = int(grid)
        F0 = np.asarray(g['F'], np.int64)
        UV = np.asarray(g['UV'], np.float64)
        Pg = P[offs[gi]:offs[gi + 1]]
        xy = np.stack([UV[:, 0] * T, (1.0 - UV[:, 1]) * T], 1)
        ids, _ = raster(xy, F0, T)
        ti = np.nonzero(ids >= 0)[0]
        cls = np.zeros(T * T, np.uint8)
        tex = np.asarray(g['tex'])[..., :3]
        base = np.zeros((T * T, 3), np.uint8)
        if len(ti):
            f = ids[ti].astype(np.int64)
            a_, b_, c_ = F0[f, 0], F0[f, 1], F0[f, 2]
            px, py = (ti % T) + 0.5, (ti // T) + 0.5
            A, B, C = xy[a_], xy[b_], xy[c_]
            ar = (B[:, 0] - A[:, 0]) * (C[:, 1] - A[:, 1]) - (B[:, 1] - A[:, 1]) * (C[:, 0] - A[:, 0])
            wa = ((B[:, 0] - px) * (C[:, 1] - py) - (B[:, 1] - py) * (C[:, 0] - px)) / ar
            wb = ((C[:, 0] - px) * (A[:, 1] - py) - (C[:, 1] - py) * (A[:, 0] - px)) / ar
            wc = 1.0 - wa - wb
            Q = wa[:, None] * Pg[a_] + wb[:, None] * Pg[b_] + wc[:, None] * Pg[c_]
            n3 = np.cross(Pg[F0[:, 1]] - Pg[F0[:, 0]], Pg[F0[:, 2]] - Pg[F0[:, 0]])
            area3 = 0.5 * np.linalg.norm(n3, axis=1)
            nrm = n3 / np.maximum(np.linalg.norm(n3, axis=1), 1e-30)[:, None]
            uvarea = 0.5 * np.abs((xy[F0[:, 1], 0] - xy[F0[:, 0], 0]) * (xy[F0[:, 2], 1] - xy[F0[:, 0], 1])
                                  - (xy[F0[:, 1], 1] - xy[F0[:, 0], 1]) * (xy[F0[:, 2], 0] - xy[F0[:, 0], 0]))
            wface = np.where(uvarea > 1e-12, area3 / np.maximum(uvarea, 1e-12), 0.0)
            wt = wface[f]
            N = nrm[f]
            best = np.zeros(len(ti))
            mvi = np.full(len(ti), -1, np.int8)
            ext_cnt = np.zeros(len(ti), np.int16)
            dep_any = np.zeros(len(ti), bool)             # виден ли тексель хоть с одного вида MV-Adapter по глубине (без порога по углу)
            seen = np.zeros(len(ti), bool)
            outer = np.zeros(len(ti), bool)
            for ci, (v, zb, res, ortho, is_mv) in enumerate(cams):
                x, y, d = project(Q, v, ortho)
                ix = np.clip(np.floor(x * res).astype(np.int64), 0, res - 1)
                iy = np.clip(np.floor(y * res).astype(np.int64), 0, res - 1)
                cs = N @ v[0]
                cs = cs if signed else np.abs(cs)
                cmin = COS_SEEN if is_mv else EXT_COS
                eps = DEPTH_EPS + (ortho / res) * np.sqrt(np.maximum(1.0 - cs * cs, 0.0)) / np.maximum(np.abs(cs), cmin)      # постоянный допуск + рост глубины по пикселю на наклонной
                vis_geo = zb[iy * res + ix] <= d + eps
                vis = vis_geo & (cs > cmin)
                outer |= vis
                if is_mv:
                    dep_any |= vis_geo
                    mvi = np.where(vis & (cs > best), ci, mvi).astype(np.int8)
                    best = np.where(vis, np.maximum(best, cs), best)
                    seen |= vis
                else:
                    ext_cnt += vis
            H, Wd = tex.shape[:2]
            tx = np.clip(np.floor(px / T * Wd).astype(np.int64), 0, Wd - 1)
            ty = np.clip(np.floor(py / T * H).astype(np.int64), 0, H - 1)
            rgb = tex[ty, tx]
            unp = (rgb.max(axis=1) <= UNPAINTED['black_max']) | (rgb.min(axis=1) >= UNPAINTED['white_min'])
            unseen = ~seen
            graz = seen & (best < COS_GRAZE)
            c = np.ones(len(ti), np.uint8)
            c[unp] = 4
            c[graz] = 3
            c[unseen] = np.where(outer[unseen], 2, 5)
            cls[ti] = c
            base[ti] = rgb
            ai, bi, de_b, ln_b, de_in = seam_pairs(T, ti, Q, np.sqrt(wt), mvi, seen, rgb, rng)
            seam_store.append({'gi': gi, 'ti': ti, 'outer': outer, 'ai': ai, 'bi': bi, 'de': de_b, 'ln': ln_b, 'inner': de_in})
            comp = face_components(Pg, F0, area3)
            if comp is None:
                expl['ok'] = False
            else:
                cf, ca = comp
                crumb = (ca < EXPLAIN['crumb_area_frac'] * float(area3.sum()))[cf][f]
                uo = unseen & outer
                expl['unseen_outer'] += int(uo.sum())
                expl['crumbs'] += int((uo & crumb).sum())
                expl['crevice'] += int((uo & ~crumb & (ext_cnt <= EXPLAIN['crevice_max_dirs'])).sum())
                gap = uo & ~crumb & (ext_cnt > EXPLAIN['crevice_max_dirs'])
                expl['gap'] += int(gap.sum())
                expl['gap_edge_on'] += int((gap & dep_any).sum())             # не закрыт ни в одном виде, но смотрит на все 6 видов под |cos| ≤ COS_SEEN (ребром)
                expl['gap_occluded'] += int((gap & ~dep_any).sum())           # закрыт другими частями формы во всех 6 видах
                expl['components'] += len(ca)
                expl['crumb_components'] += int((ca < EXPLAIN['crumb_area_frac'] * float(area3.sum())).sum())
                expl['crumb_area'] += float(ca[ca < EXPLAIN['crumb_area_frac'] * float(area3.sum())].sum())
                expl['area'] += float(area3.sum())
            masks = {'island': np.ones(len(ti), bool), 'unseen': unseen, 'grazing': graz, 'unpainted': unp, 'unpainted_seen': unp & seen}
            for k, m in masks.items():
                tot['t'][k] += int(m.sum())
                tot['a'][k] += float(wt[m].sum())
                tot['ot'][k] += int((m & outer).sum())
                tot['oa'][k] += float(wt[m & outer].sum())
        maps.append({'cls': cls.reshape(T, T), 'base': base.reshape(T, T, 3)})
    stage['texels'] = round(time.time() - t0, 2)
    # швы: порог по товару целиком (скачки внутри областей — по всем геометриям), затем плохие пары → тексели → картинка
    inner_all = np.concatenate([d['inner'] for d in seam_store]) if seam_store else np.zeros(0)
    de_all = np.concatenate([d['de'] for d in seam_store]) if seam_store else np.zeros(0)
    ln_all = np.concatenate([d['ln'] for d in seam_store]) if seam_store else np.zeros(0)
    inner_p = float(np.percentile(inner_all, SEAM['inner_pct'])) if len(inner_all) else 0.0
    thr = max(SEAM['abs_de'], SEAM['ratio'] * inner_p)
    bad_tex = 0
    for d in seam_store:
        bad = d['de'] > thr
        hit = np.zeros(len(d['ti']), bool)
        hit[d['ai'][bad]] = True
        hit[d['bi'][bad]] = True
        mp = maps[d['gi']]
        flat = mp['cls'].reshape(-1)
        flat[d['ti'][hit]] = 6
        bad_tex += int((hit & d['outer']).sum())
    n_out = tot['ot']['island']
    seam = {'seam_tex_pct': round(100.0 * bad_tex / n_out, 2) if n_out else None,
            'seam_len_share': round(float(ln_all[de_all > thr].sum() / ln_all.sum()), 4) if len(ln_all) and ln_all.sum() > 0 else 0.0,
            'seam_de_med': round(float(np.median(de_all)), 2) if len(de_all) else None, 'seam_de_p90': round(float(np.percentile(de_all, 90)), 2) if len(de_all) else None,
            'seam_inner_p95': round(inner_p, 2), 'seam_threshold': round(thr, 2), 'seam_boundary_pairs': int(len(de_all)), 'seam_bad_pairs': int((de_all > thr).sum())}
    explain = None
    if expl['ok'] and expl['unseen_outer']:
        u, o = expl['unseen_outer'], tot['ot']['island']
        explain = {k: {'of_unseen_pct': round(100.0 * expl[k] / u, 1), 'of_outer_pct': round(100.0 * expl[k] / o, 2)} for k in ('crumbs', 'crevice', 'gap', 'gap_edge_on', 'gap_occluded')}
        explain.update(components=expl['components'], crumb_components=expl['crumb_components'], crumb_area_share_pct=round(100.0 * expl['crumb_area'] / expl['area'], 2) if expl['area'] else None)

    def pct(t, den):
        return {f'{k}_pct': (round(100.0 * t[k] / den, 2) if den else None) for k in ('unseen', 'grazing', 'unpainted', 'unpainted_seen')}

    out = {'tex': pct(tot['t'], tot['t']['island']), 'area': pct(tot['a'], tot['a']['island']),
           'outer_tex': pct(tot['ot'], tot['ot']['island']), 'outer_area': pct(tot['oa'], tot['oa']['island']),
           'outer_share_tex_pct': round(100.0 * tot['ot']['island'] / tot['t']['island'], 2) if tot['t']['island'] else None,
           'outer_share_area_pct': round(100.0 * tot['oa']['island'] / tot['a']['island'], 2) if tot['a']['island'] else None,
           'seam': seam, 'unseen_outer_why': explain, 'n_island': tot['t']['island'], 'maps': maps, 'time_s': {**stage, 'total': round(time.time() - t0, 2)}}
    return out


def coverage_image(m: dict):
    """Картинка проверки: исходная краска приглушена; шов видов (скачок цвета на границе главных видов) — пурпурный, unseen, видимый снаружи — красный, unseen внутри (спрятан в предмете) — тёмно-бордовый, grazing — жёлтый, unpainted — синий."""
    import numpy as np
    from PIL import Image
    cls, base = m['cls'], m['base']
    img = (base.astype(np.float64) * 0.55).astype(np.uint8)
    for k, col in ((4, (0, 90, 255)), (3, (255, 220, 0)), (5, (90, 0, 30)), (2, (255, 0, 0)), (6, (200, 0, 255))):
        img[cls == k] = col
    return Image.fromarray(img)


# ---------------------------------------------------------------- GLB -------------------------------------------
def load_geoms(path: str) -> list:
    """GLB → список геометрий {'V','F','UV','tex'} с применёнными трансформами сцены (как `mesh_render.load_parts`; без слияния вершин: развёртка остаётся как есть)."""
    import numpy as np
    import trimesh
    sc = trimesh.load(path, force='scene', process=False)
    out = []
    for name, g in sc.geometry.items():
        try:
            g.apply_transform(sc.graph.get(name)[0])
        except Exception:  # noqa: BLE001 — геометрия без трансформа берётся как есть
            pass
        vis = getattr(g, 'visual', None)
        uv = getattr(vis, 'uv', None)
        mat = getattr(vis, 'material', None)
        im = getattr(mat, 'baseColorTexture', None) or getattr(mat, 'image', None)
        if uv is None or im is None:
            raise ValueError(f'{os.path.basename(path)}: у геометрии «{name}» нет развёртки или текстуры (нужен GLB с краской MV-Adapter)')
        out.append({'name': name, 'V': np.asarray(g.vertices, np.float64), 'F': np.asarray(g.faces, np.int64), 'UV': np.asarray(uv, np.float64),
                    'tex': np.asarray(im.convert('RGB'), np.uint8), 'mesh': g})
    if not out:
        raise ValueError(f'{os.path.basename(path)}: в файле нет геометрии')
    return out


def write_coverage_glb(geoms: list, maps: list, dst: str) -> None:
    """Те же форма и развёртка, текстура — картинка покрытия (красный unseen, жёлтый grazing, синий unpainted)."""
    import numpy as np
    import trimesh
    from trimesh.visual import TextureVisuals
    from trimesh.visual.material import PBRMaterial
    sc = trimesh.Scene()
    for g, m in zip(geoms, maps):
        mesh = trimesh.Trimesh(vertices=g['V'], faces=g['F'], process=False)
        mesh.visual = TextureVisuals(uv=np.asarray(g['UV']), material=PBRMaterial(baseColorTexture=coverage_image(m), metallicFactor=0.0, roughnessFactor=1.0))
        sc.add_geometry(mesh, geom_name=str(g.get('name') or 'mesh'))
    sc.export(dst)


# ---------------------------------------------------------------- таблица пробы, ярлыки ------------------------
def key_of(sku: str) -> str:
    return str(sku).replace(':', '_')


def load_table(path: str, model: str | None = None) -> list:
    rows = list(csv.DictReader(open(path, encoding='utf-8')))
    return [r for r in rows if not model or r.get('model') == model]


def match_row(stem: str, rows: list) -> dict | None:
    """Строка таблицы пробы для товара по имени файла: ключ `магазин_товар` — начало имени (длиннейшее совпадение, дальше разделитель `-` или `.`)."""
    best = None
    for r in rows:
        k = key_of(r.get('sku', ''))
        if k and (stem == k or stem.startswith(k + '-') or stem.startswith(k + '.')) and (best is None or len(k) > len(key_of(best['sku']))):
            best = r
    return best


PHOTO_COLS = ('de00', 'dL', 'pattern_grad_ncc', 'colour_guard')


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def photo_of(row: dict | None) -> dict | None:
    if not row:
        return None
    out = {}
    for c in PHOTO_COLS:
        v = row.get(c)
        out[c] = (_num(v) if c != 'colour_guard' else (v or None)) if v not in (None, '') else None
    return out


def find_yaw(glb: str, forced=None) -> tuple[float, str]:
    """Поворот формы вокруг вертикали, как подобрал воркер: `forced` (число) → оно; иначе — из `summary-*.json` драйвера рядом/на уровень выше (`jobs[].metrics.fit.yaw_deg`, задание по имени файла); иначе 0."""
    if forced not in (None, '', 'auto'):
        return float(forced), '--yaw'
    stem = os.path.basename(glb)[:-4]
    for d in (os.path.dirname(os.path.abspath(glb)), os.path.dirname(os.path.dirname(os.path.abspath(glb)))):
        for sj in sorted(glob.glob(os.path.join(d, 'summary-*.json'))):
            try:
                data = json.load(open(sj, encoding='utf-8'))
            except (OSError, ValueError):
                continue
            for j in data.get('jobs') or []:
                jid = str(j.get('job_id') or '')
                if jid and (stem == jid or stem.startswith(jid)) and ((j.get('metrics') or {}).get('fit') or {}).get('yaw_deg') is not None:
                    return float(j['metrics']['fit']['yaw_deg']), os.path.basename(sj)
    return 0.0, 'не найден (0°)'


def flat_metrics(res: dict) -> dict:
    """Плоский словарь для `verdict`: доли по текселям `*_tex_pct`, по площади `*_area_pct`, и колонки таблицы пробы (de00, dL, pattern_grad_ncc)."""
    m = {}
    for k, v in (res.get('tex') or {}).items():
        m[k.replace('_pct', '_tex_pct')] = v
    for k, v in (res.get('area') or {}).items():
        m[k.replace('_pct', '_area_pct')] = v
    for k, v in (res.get('outer_tex') or {}).items():
        m[k.replace('_pct', '_outer_tex_pct')] = v
    for k, v in (res.get('outer_area') or {}).items():
        m[k.replace('_pct', '_outer_area_pct')] = v
    for k in ('outer_share_tex_pct', 'outer_share_area_pct'):
        m[k] = res.get(k)
    sm = res.get('seam') or {}
    for k in ('seam_tex_pct', 'seam_de_med', 'seam_de_p90'):
        m[k] = sm.get(k)
    if sm.get('seam_len_share') is not None:
        m['seam_len_pct'] = round(100.0 * sm['seam_len_share'], 2)
    for k, v in (res.get('photo') or {}).items():
        if v is not None:
            m[k] = v
    return m


# ---------------------------------------------------------------- прогон ---------------------------------------
def process(glb: str, out_dir: str | None = None, yaw=None, grid: int = 2048, view_res: int = 768, rows: list | None = None,
            thresholds: dict | None = None, write_glb: bool = True, ext_n: int = EXT_DIRS) -> dict:
    t0 = time.time()
    stem = os.path.basename(glb)[:-4]
    out_dir = out_dir or os.path.dirname(os.path.abspath(glb))
    os.makedirs(out_dir, exist_ok=True)
    geoms = load_geoms(glb)
    t_load = round(time.time() - t0, 2)
    yw, ysrc = find_yaw(glb, yaw)
    # сетка карты — по размеру текстуры (не больше `grid`)
    T = min(int(grid), max(max(g['tex'].shape[:2]) for g in geoms))
    r = analyze(geoms, yw, T, view_res, ext_n=ext_n)
    res = {'file': os.path.abspath(glb), 'key': stem, 'faces': int(sum(len(g['F']) for g in geoms)), 'yaw_deg': yw, 'yaw_source': ysrc, 'grid': T, 'view_res': view_res,
           'texels_island': r['n_island'], 'tex': r['tex'], 'area': r['area'], 'outer_tex': r['outer_tex'], 'outer_area': r['outer_area'],
           'outer_share_tex_pct': r['outer_share_tex_pct'], 'outer_share_area_pct': r['outer_share_area_pct'], 'seam': r['seam'], 'unseen_outer_why': r['unseen_outer_why'], 'photo': photo_of(match_row(stem, rows or [])) if rows else None}
    if write_glb:
        dst = os.path.join(out_dir, stem + '.coverage.glb')
        write_coverage_glb(geoms, r['maps'], dst)
        res['coverage_glb'] = dst
    v, why = _judge(flat_metrics(res), thresholds)
    res['verdict'], res['verdict_why'] = v, why
    res['time_s'] = {'load': t_load, **r['time_s'], 'all': round(time.time() - t0, 2)}
    json.dump(res, open(os.path.join(out_dir, stem + '.coverage.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return res


SUM_COLS = ['key', 'faces', 'outer_share_tex', 'unseen_outer_tex', 'grazing_outer_tex', 'unpainted_outer_tex', 'unseen_outer_area', 'grazing_outer_area', 'unpainted_outer_area',
            'seam_tex', 'seam_len', 'seam_de_med', 'seam_de_p90', 'unseen_tex', 'grazing_tex', 'unpainted_tex', 'unpainted_seen_tex', 'unseen_area', 'grazing_area', 'unpainted_area', 'de00', 'dL', 'pattern_grad_ncc',
            'colour_guard', 'verdict', 'why', 'time_s']


def summary_rows(results: list) -> list:
    out = []
    for r in results:
        if 'error' in r:
            out.append({'key': r['key'], 'verdict': 'ошибка', 'why': r['error']})
            continue
        ph = r.get('photo') or {}
        fm = flat_metrics(r)
        out.append({'key': r['key'], 'faces': r['faces'], 'outer_share_tex': r.get('outer_share_tex_pct'), 'seam_tex': fm.get('seam_tex_pct'), 'seam_len': fm.get('seam_len_pct'),
                    'seam_de_med': fm.get('seam_de_med'), 'seam_de_p90': fm.get('seam_de_p90'),
                    **{f'{k[:-4]}_outer_tex': v for k, v in r['outer_tex'].items()}, **{f'{k[:-4]}_outer_area': v for k, v in r['outer_area'].items()},
                    **{f'{k[:-4]}_tex': v for k, v in r['tex'].items()}, **{f'{k[:-4]}_area': v for k, v in r['area'].items()},
                    'de00': ph.get('de00'), 'dL': ph.get('dL'), 'pattern_grad_ncc': ph.get('pattern_grad_ncc'), 'colour_guard': ph.get('colour_guard'),
                    'verdict': r['verdict'], 'why': '; '.join(r['verdict_why']), 'time_s': r['time_s']['all']})
    return out


def write_summary(out_dir: str, results: list, thresholds: dict | None = None) -> tuple:
    os.makedirs(out_dir, exist_ok=True)
    rows = summary_rows(results)
    p_csv, p_json, p_md = (os.path.join(out_dir, f'coverage-summary.{e}') for e in ('csv', 'json', 'md'))
    with open(p_csv, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=SUM_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ('' if r.get(k) is None else r.get(k)) for k in SUM_COLS})
    counts = {}
    for r in rows:
        counts[r['verdict']] = counts.get(r['verdict'], 0) + 1
    json.dump({'thresholds': THRESHOLDS if thresholds is None else thresholds, 'verdicts': counts, 'products': results}, open(p_json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    def f(v):
        return '—' if v is None or v == '' else (f'{v:.1f}' if isinstance(v, float) else str(v))

    L = ['# Покрытие текстуры MV-Adapter', '',
         'Доли — % текселей карты (в скобках — % площади поверхности) СРЕДИ НАРУЖНЫХ, то есть видимых снаружи хотя бы с одного из 26 направлений; «наружных» — % всех текселей (остальное спрятано внутри предмета и покупателю не видно). '
         'unseen — не виден ни с одного из 6 видов MV-Adapter (заплатки), grazing — только вскользь (|cos| < 0,35), unpainted — фоновый чёрный/белый. Решение — `tex_coverage.verdict` по ЧЕРНОВЫМ порогам. '
         'ΔE00/ΔL/pattern — из `trial_table.py` (сравнение с вырезкой). Доли по ВСЕМ текселям — в csv/json.', '',
         '| товар | граней | наружных | unseen | grazing | unpainted | швы, % текселей | швы, % длины | скачок ΔE00 мед/p90 | ΔE00 | ΔL | pattern | цвет | решение | почему | с |',
         '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for r in rows:
        if r['verdict'] == 'ошибка':
            L.append(f"| `{r['key']}` | | | | | | | | | | | | | ошибка | {r['why']} | |")
            continue
        L.append(f"| `{r['key']}` | {r['faces']} | {f(r['outer_share_tex'])} | {f(r['unseen_outer_tex'])} ({f(r['unseen_outer_area'])}) | {f(r['grazing_outer_tex'])} ({f(r['grazing_outer_area'])}) | "
                 f"{f(r['unpainted_outer_tex'])} ({f(r['unpainted_outer_area'])}) | {f(r['seam_tex'])} | {f(r['seam_len'])} | {f(r['seam_de_med'])} / {f(r['seam_de_p90'])} | {f(r['de00'])} | {f(r['dL'])} | {f(r['pattern_grad_ncc'])} | {f(r['colour_guard'])} | **{r['verdict']}** | {r['why']} | {f(r['time_s'])} |")
    L += ['', 'Итого: ' + ', '.join(f'{k} — {v}' for k, v in sorted(counts.items()))]
    open(p_md, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    return p_csv, p_json, p_md


def gather(paths: list, pattern: str = '*-mvtex.glb') -> list:
    out = []
    for p in paths:
        if os.path.isdir(p):
            out += sorted(x for x in glob.glob(os.path.join(p, '**', pattern), recursive=True) if '.coverage.' not in x)
        else:
            out.append(p)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Покрытие текстуры MV-Adapter: unseen / grazing / unpainted, картинка-проверка, решение keep/repaint/reject')
    ap.add_argument('paths', nargs='*')
    ap.add_argument('--out', default='')
    ap.add_argument('--yaw', default='auto')
    ap.add_argument('--grid', type=int, default=2048)
    ap.add_argument('--view-res', type=int, default=768)
    ap.add_argument('--table', default='', help='trial-table.csv из trial_table.py: подмешать de00/dL/pattern_grad_ncc/colour_guard')
    ap.add_argument('--model', default='', help='имя модели в таблице пробы (колонка model)')
    ap.add_argument('--thresholds', default='', help='JSON с порогами вместо THRESHOLDS')
    ap.add_argument('--pattern', default='*-mvtex.glb')
    ap.add_argument('--no-glb', action='store_true')
    ap.add_argument('--ext-dirs', type=int, default=EXT_DIRS, help='сколько направлений «наружу» (0 — не считать наружные доли)')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)
    if a.selftest:
        import runpy
        runpy.run_path(os.path.join(HERE, 'tests_tex_coverage.py'), run_name='__main__')
        return 0
    files = gather(a.paths, a.pattern)
    if not files:
        ap.error('нет GLB: укажи файлы или папку с *-mvtex.glb')
    th = json.load(open(a.thresholds, encoding='utf-8')) if a.thresholds else None
    rows = load_table(os.path.expanduser(a.table), a.model or None) if a.table else None
    results = []
    for g in files:
        try:
            r = process(g, a.out or None, a.yaw, a.grid, a.view_res, rows, th, not a.no_glb, a.ext_dirs)
            print(f"{r['key']}: наружных {r['outer_share_tex_pct']} % · среди них unseen {r['outer_tex']['unseen_pct']} % · grazing {r['outer_tex']['grazing_pct']} % · unpainted {r['outer_tex']['unpainted_pct']} % · {r['verdict']} · {r['time_s']['all']} с", flush=True)
        except Exception as e:  # noqa: BLE001 — счётчик отказов обязателен: ошибка в таблицу, не молчание
            r = {'key': os.path.basename(g)[:-4], 'error': f'{type(e).__name__}: {str(e)[:160]}'}
            print(f"{r['key']}: ОШИБКА {r['error']}", flush=True)
        results.append(r)
    out_dir = a.out or os.path.dirname(os.path.abspath(files[0]))
    print('\n'.join(write_summary(out_dir, results, th)))
    return 1 if any('error' in r for r in results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
