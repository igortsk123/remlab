#!/usr/bin/env python3
"""ПЕРЕНОС РОДНОГО ЦВЕТА TRELLIS.2 НА УПРОЩЁННУЮ ФОРМУ + СТОРОЖ ШАГА 0 (T-20261120-167; план paint-photo-fill-01, шаг 0).

ЗАЧЕМ. `sg_prep_shape.py` режет форму до ≤150 тыс. граней и строит НОВУЮ развёртку — родная текстура TRELLIS.2 (baseColor + металл/шероховатость + альфа) при этом пропадала.
Здесь цвет переносится в новую развёртку по ближайшим точкам поверхности в 3D: у каждого текселя НОВОЙ карты берётся его точка на упрощённой форме, ищется ближайшая точка
родной формы (по тексельным точкам родной карты) и копируется её baseColor / металл-шероховатость / альфа. Только numpy + scipy + trimesh + PIL, видеокарта и Blender не нужны.

  python3 sg_color_transfer.py transfer --native родной.glb --shape упрощённая.glb --out результат.glb [--size 2048] [--max-dist 0.03]
      --shape — GLB с НОВОЙ развёрткой (`BakeUV` из sg_prep_shape.py), без текстуры; --size — сторона новой карты (по умолчанию — как у родной);
      --max-dist — доля диагонали габарита: дальше этого родной точки нет, тексель считается «без цвета» (заполняется ближайшим цветным; в отчёт идёт счётчик).
      Печатает одну строку `перенос: …` с долей текселей с цветом (ЦЕЛЬ ≥ 99 %). Код 0 — доля текселей ≥ `--min-share` (99 %) И граней с цветом верного места ≥ 99 %, 3 — меньше.
  python3 sg_color_transfer.py guard ПУТЬ...          # сторож шага 0: «baseColor пришёл?» и доля альфа<128 по занятым текселям; ПУТЬ — GLB или папка
      Счётчик: `ЦВЕТ: пришёл N из M; не пришёл K [список]; альфа<128 больше 30 %: J` — код 1, если хоть у одного GLB нет baseColor (fail-closed).
      Альфа — только сообщение, не отказ: замер T-166 (17 из 30 GLB с долей 31–94 % даже у велюра) показал, что как маска стекла она пока ненадёжна.
  python3 sg_color_transfer.py --selftest

ПОЧЕМУ БЕЗ НОРМАЛЕЙ. У сеток TRELLIS порядок обхода граней не всегда «наружу» (см. tex_coverage.py), знак нормали дал бы ложные несовпадения; ищем по положению.
Ограничение: у тонких двойных стенок (<~ шага текселя родной карты) ближайшая точка может оказаться на соседней стенке — такой тексель цвета той стенки; на мебели цвета сторон там совпадают.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'salad', 'trellis'))   # tex_coverage.raster — растеризатор граней на numpy

MIN_SHARE = 0.99          # доля текселей нового атласа с цветом, ниже — отказ (T-167)
FACES_TEXEL_MIN = 0.99    # этап 02, главная мерка: доля граней, получивших хотя бы один тексель
CHAMFER_MAX = 0.01        # этап 02: Chamfer родной↔упрощённая, доля диагонали габарита; больше — «форма не от этого черновика»
MAX_DIST = 0.03          # доля диагонали габарита для «родная точка найдена»
ALPHA_SUSPECT = 0.30      # доля альфа<128 по занятым текселям, выше — «подозрительно» (только сообщение)
ALPHA_LT = 128


def glb_has_normal(path: str) -> bool:
    """Есть ли атрибут NORMAL у ВСЕХ примитивов GLB (читаем JSON-заголовок: trimesh сам досчитывает нормали, по нему «был ли NORMAL» не узнать)."""
    import json
    import struct
    with open(path, 'rb') as f:
        head = f.read(20)
        js = json.loads(f.read(struct.unpack('<I', head[12:16])[0]))
    prims = [pr for m in js.get('meshes', []) for pr in m['primitives']]
    return bool(prims) and all('NORMAL' in pr['attributes'] for pr in prims)


def load_glb(path: str):
    """GLB → {'V','F','UV','mesh','base','mr'}: вершины с применёнными трансформами сцены, развёртка (v вверх, как в trimesh), текстуры PIL (или None). Несколько геометрий сливаются."""
    import numpy as np
    import trimesh
    sc = trimesh.load(path, force='scene', process=False)
    parts = []
    for name, g in sc.geometry.items():
        try:
            g.apply_transform(sc.graph.get(name)[0])
        except Exception:  # noqa: BLE001
            pass
        parts.append(g)
    if not parts:
        raise ValueError(f'{os.path.basename(path)}: в файле нет геометрии')
    out = {'V': [], 'F': [], 'UV': [], 'base': None, 'mr': None}
    off = 0
    for g in parts:
        vis = getattr(g, 'visual', None)
        uv = getattr(vis, 'uv', None)
        mat = getattr(vis, 'material', None)
        if out['base'] is None:
            out['base'] = getattr(mat, 'baseColorTexture', None) or getattr(mat, 'image', None)
            out['mr'] = getattr(mat, 'metallicRoughnessTexture', None)
        out['V'].append(np.asarray(g.vertices, np.float64))
        out['F'].append(np.asarray(g.faces, np.int64) + off)
        out['UV'].append(np.asarray(uv, np.float64) if uv is not None else np.zeros((len(g.vertices), 2)))
        try:
            out.setdefault('N', []).append(np.asarray(g.vertex_normals, np.float64))      # нормали файла (если есть NORMAL), иначе пересчитанные trimesh
            out['has_normals'] = glb_has_normal(path)
        except Exception:  # noqa: BLE001
            out['N'] = None
            out['has_normals'] = False
        off += len(g.vertices)
    out['V'], out['F'], out['UV'] = np.concatenate(out['V']), np.concatenate(out['F']), np.concatenate(out['UV'])
    out['N'] = np.concatenate(out['N']) if out.get('N') else None
    return out


NORMAL_RULES_PATH = os.path.join(os.path.dirname(HERE), 'rules', 'sg-prep-normals.json')   # пороги мерки нормалей этапа 02 — в JSON, не в коде


def normal_rules(path: str = NORMAL_RULES_PATH) -> dict:
    """Пороги мерки нормалей: среднее° и хвост p99° разницы нормали затенения упрощённой и сглаженной родной. Нет файла или битое значение → исключение (этап не проходит молча)."""
    import json
    with open(path, encoding='utf-8') as f:
        r = json.load(f)
    for k in ('normal_dev_mean_deg_max', 'normal_dev_p99_deg_max'):
        if not isinstance(r.get(k), (int, float)) or isinstance(r.get(k), bool) or not 0 < r[k] <= 180:
            raise ValueError(f'{path}: {k} должно быть числом в (0, 180], а не {r.get(k)!r}')
    return r


def normals_reason(mean: float, p99: float, has_n: bool, rules: dict) -> str:
    """Причина отказа по нормалям (пусто — прошли): среднее ИЛИ хвост выше порога. Среднее прячет узкие полосы (шкаф: среднее 7,9°, хвост 36°, на кадре полосы), поэтому гейт по обоим."""
    if mean > rules['normal_dev_mean_deg_max']:
        return f'затенение не как у родной: normal_dev_mean_deg {mean:.1f} > {rules["normal_dev_mean_deg_max"]} (NORMAL в файле: {"да" if has_n else "нет"}) — плашки с прямыми краями на гладком боку'
    if p99 > rules['normal_dev_p99_deg_max']:
        return f'затенение не как у родной в узких местах: normal_dev_p99_deg {p99:.1f} > {rules["normal_dev_p99_deg_max"]} — полосы/складки на гладкой поверхности (кадр clay с плоским затенением)'
    return ''
NORMAL_K = 64           # сколько ближайших вершин родной рассматривается для нормали вершины упрощённой (берутся те, что в радиусе масштаба сетки упрощённой)
NORMAL_AGREE = 0.3       # вершина родной участвует, только если её нормаль не смотрит против собственной нормали упрощённой (cos ≥ этого): тонкая стенка/рама иначе тянет нормаль с обратной стороны → чёрные пятна


def prep_sidecar_path(out_glb: str) -> str:
    """`<выход>.prep.json` — какой предобработке подвергнута родная форма перед упрощением (пишет sg_prep_shape.py): эталон мерки и нормали берутся из родной после ТОЙ ЖЕ предобработки."""
    return (out_glb[:-4] if out_glb.endswith('.glb') else out_glb) + '.prep.json'


def read_prep(out_glb: str) -> dict:
    """Предобработка родной из сайдкара: {'weld': bool, 'presmooth': int, 'presmooth_lambda': float}; нет файла — {} (родная как есть, прежнее поведение)."""
    import json
    p = prep_sidecar_path(out_glb)
    if not os.path.exists(p):
        return {}
    with open(p, encoding='utf-8') as f:
        d = json.load(f)
    return {'weld': bool(d.get('weld')), 'presmooth': int(d.get('presmooth') or 0), 'presmooth_lambda': float(d.get('presmooth_lambda') or 0.5)}


LADDER_RULES_PATH = os.path.join(os.path.dirname(HERE), 'rules', 'sg-prep-ladder.json')     # ступени лестницы отказов переноса — в JSON, не в коде


def ladder_rules(path: str = LADDER_RULES_PATH) -> list:
    """Ступени лестницы отказов: [{'size': сторона карты или None (=как у родной), 'angle': угол Smart UV в градусах}, …] по порядку. Нет файла или он негоден — ошибка (тихо одну ступень не берём)."""
    import json
    if not os.path.exists(path):
        raise SystemExit(f'нет файла правил {path}: лестница отказов без него не запускается')
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    steps = d.get('steps')
    if not isinstance(steps, list) or not steps:
        raise SystemExit(f'{path}: нужен непустой список steps')
    out = []
    for s in steps:
        ang = s.get('angle')
        size = s.get('size')
        if not isinstance(ang, (int, float)) or not 1.0 <= float(ang) <= 89.9 or (size is not None and (not isinstance(size, int) or size < 256)):
            raise SystemExit(f'{path}: негодная ступень {s}')
        out.append({'size': size, 'angle': float(ang)})
    return out


def ladder_path(out_glb: str) -> str:
    """`<выход>.ladder.json` — след лестницы отказов (пишет sg_prep_shape.py): какая ступень сработала и мерки каждой попытки."""
    return (out_glb[:-4] if out_glb.endswith('.glb') else out_glb) + '.ladder.json'


def read_ladder(out_glb: str) -> dict:
    import json
    p = ladder_path(out_glb)
    if not os.path.exists(p):
        return {}
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def run_ladder(steps: list, attempt) -> tuple:
    """Пройти ступени по порядку: `attempt(k, step) -> (код, отчёт переноса или {})`. Код 0 — готово, 3 — отказ по мерке (идём на следующую ступень), другой код — сбой (ступенью не лечится, стоп).
    → (номер сработавшей ступени или None, список попыток [{'step','angle','size','rc','faces_with_texel','share'}])."""
    attempts = []
    for k, st in enumerate(steps):
        rc, rep = attempt(k, st)
        attempts.append({'step': k, 'angle': st['angle'], 'size': rep.get('size') or st.get('size'), 'rc': rc, 'faces_with_texel': rep.get('faces_with_texel'), 'share': rep.get('share')})
        if rc == 0:
            return k, attempts
        if rc != 3:
            break
    return None, attempts


def weld_vertices(V, F, tol: float = 1e-7):
    """Склеить вершины с совпадающими координатами (glTF режет вершину по каждому шву UV/нормалей). → (V, F) без неиспользуемых вершин."""
    import numpy as np
    key = np.round(np.asarray(V, np.float64) / tol).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    F2 = inv[np.asarray(F)]
    used = np.unique(F2)
    remap = np.full(len(first), -1, np.int64)
    remap[used] = np.arange(len(used))
    return np.asarray(V, np.float64)[first][used], remap[F2]


def taubin_smooth(V, F, iters: int, lam: float = 0.5):
    """Сглаживание Таубина: Лапласово «сжатие» (+λ) и «растяжение» (μ = −λ/(1−0.1λ)) по очереди, `iters` раз — шум сетки гаснет, форма почти не садится. Одна функция для sg_prep_shape.py (форма для упрощения)
    и для эталона мерки нормалей: эталон сглажен ТАК ЖЕ, иначе мерка сравнивала бы с шумом, который предобработка уже убрала."""
    import numpy as np
    V = np.asarray(V, np.float64)
    F = np.asarray(F, np.int64)
    E = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    E = np.unique(np.sort(E, axis=1), axis=0)
    ea, eb = np.concatenate([E[:, 0], E[:, 1]]), np.concatenate([E[:, 1], E[:, 0]])
    nv = len(V)
    deg = np.bincount(ea, minlength=nv).astype(np.float64)
    mu = -lam / (1.0 - 0.1 * lam)
    Q = V.copy()
    for _ in range(int(iters)):
        for k in (lam, mu):
            S = np.stack([np.bincount(ea, weights=Q[eb, c], minlength=nv) for c in range(3)], 1)
            nb = np.where(deg[:, None] > 0, S / np.maximum(deg, 1.0)[:, None], Q)
            Q = Q + k * (nb - Q)
    return Q


def vertex_normals_area(V, F):
    """Нормали вершин: сумма нормалей граней, взвешенных площадью (длина векторного произведения), нормированная."""
    import numpy as np
    V = np.asarray(V, np.float64)
    F = np.asarray(F, np.int64)
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    N = np.zeros_like(V)
    for c in range(3):
        for k in range(3):
            N[:, c] += np.bincount(F[:, k], weights=fn[:, c], minlength=len(V))
    ln = np.linalg.norm(N, axis=1, keepdims=True)
    return N / np.where(ln < 1e-12, 1.0, ln)


def native_reference(nat_V, nat_F, nat_N, prep: dict):
    """Родная для эталона нормалей и для их переноса: (вершины, нормали). `nat_F` — грани без плиты. Без предобработки — сырые вершины и нормали файла (как прежде); с предобработкой (склейка по швам,
    Таубин) — та же склейка и то же сглаживание, нормали из получившейся геометрии: мерка проверяет только то, что сломало упрощение, а не то, что предобработка убрала сознательно."""
    import numpy as np
    used = np.unique(nat_F)
    if not prep or not (prep.get('weld') or prep.get('presmooth')):
        return nat_V[used], nat_N[used]
    remap = np.full(len(nat_V), -1, np.int64)
    remap[used] = np.arange(len(used))
    V, F = weld_vertices(nat_V[used], remap[nat_F])
    if prep.get('presmooth'):
        V = taubin_smooth(V, F, prep['presmooth'], prep.get('presmooth_lambda') or 0.5)
    return V, vertex_normals_area(V, F)


def transfer_normals(nat_V, nat_N, tgt_V, tgt_F, k: int = NORMAL_K, agree: float = NORMAL_AGREE):
    """Нормали упрощённой формы из родной (T-167: без NORMAL в GLB Blender считает свои по большим граням — плашки с прямыми краями на спинке): среднее нормалей k ближайших вершин родной с весом
    по расстоянию, но только тех, что согласны с собственной нормалью упрощённой (cos ≥ agree; обратные — отбрасываем). Нет согласных — собственная нормаль упрощённой."""
    import numpy as np
    import trimesh
    own = np.asarray(trimesh.Trimesh(vertices=tgt_V, faces=tgt_F, process=False).vertex_normals, np.float64)
    return smooth_native_normals(nat_V, nat_N, tgt_V, own, vertex_spacing(tgt_V, tgt_F), k, agree)


def vertex_spacing(V, F):
    """Средняя длина рёбер, сходящихся в вершине (масштаб сетки упрощённой в этой точке)."""
    import numpy as np
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    lab, lbc, lca = np.linalg.norm(a - b, axis=1), np.linalg.norm(b - c, axis=1), np.linalg.norm(c - a, axis=1)
    s = np.zeros(len(V))
    n = np.zeros(len(V))
    for idx, ln in ((F[:, 0], lab + lca), (F[:, 1], lab + lbc), (F[:, 2], lbc + lca)):
        s += np.bincount(idx, weights=ln, minlength=len(V))
        n += np.bincount(idx, weights=np.full(len(idx), 2.0), minlength=len(V))
    return s / np.maximum(n, 1.0)


def smooth_native_normals(nat_V, nat_N, pts, own, scale, k: int = NORMAL_K, agree: float = NORMAL_AGREE):
    """Сглаженная нормаль родной в точках `pts`: среднее нормалей вершин родной в радиусе `scale` (масштаб сетки упрощённой в точке; ближайшая берётся всегда, до k вершин). Сырая сетка TRELLIS шумит
    на масштабе своей вершины (мелкие борозды), упрощённая грань — крупнее: нормаль вершины должна быть средней по её окрестности, иначе борозды дают тёмные полосы (шкаф, кадры T-167). own — собственные нормали
    точек: согласие с ними отсеивает вершины обратной стороны."""
    import numpy as np
    from scipy.spatial import cKDTree
    d, j = cKDTree(nat_V).query(pts, k=k, workers=-1)
    cand = nat_N[j]                                               # (n, k, 3)
    cosv = np.einsum('nkc,nc->nk', cand, own)
    near = d <= np.asarray(scale)[:, None]
    near[:, 0] = True
    w = ((cosv >= agree) & near).astype(np.float64)
    s = np.einsum('nk,nkc->nc', w, cand)
    ln = np.linalg.norm(s, axis=1, keepdims=True)
    out = np.where(ln > 1e-12, s / np.where(ln < 1e-12, 1.0, ln), own)
    return out


def texel_points(V, F, UV, size: int, conservative: bool = False):
    """Занятые развёрткой тексели карты size×size → (индексы пикселей (y, x), положения в 3D). Тексель — центр пикселя; точка = барицентрика грани."""
    import numpy as np
    from tex_coverage import raster
    xy = np.stack([UV[:, 0] * size, (1.0 - UV[:, 1]) * size], 1)
    ids, _ = raster(xy, F, size)
    pix = np.nonzero(ids >= 0)[0]
    f = ids[pix].astype(np.int64)
    py, px = pix // size, pix % size
    cx, cy = px + 0.5, py + 0.5
    A, B, C = xy[F[f, 0]], xy[F[f, 1]], xy[F[f, 2]]
    ar = (B[:, 0] - A[:, 0]) * (C[:, 1] - A[:, 1]) - (B[:, 1] - A[:, 1]) * (C[:, 0] - A[:, 0])
    ar = np.where(np.abs(ar) < 1e-12, 1e-12, ar)
    wa = ((B[:, 0] - cx) * (C[:, 1] - cy) - (B[:, 1] - cy) * (C[:, 0] - cx)) / ar
    wb = ((C[:, 0] - cx) * (A[:, 1] - cy) - (C[:, 1] - cy) * (A[:, 0] - cx)) / ar
    wc = 1.0 - wa - wb
    P = wa[:, None] * V[F[f, 0]] + wb[:, None] * V[F[f, 1]] + wc[:, None] * V[F[f, 2]]
    if conservative:
        # Мелкие грани (меньше пикселя) без «своего» текселя берут цвет соседнего острова — пятна не того цвета (кадры T-167). Даём такой грани тексель
        # по центру её развёртки, если он свободен; точка — центр грани в 3D.
        flat, fm = _claim_missing(F, xy, ids, size)
        if len(fm):
            Pm = (V[F[fm, 0]] + V[F[fm, 1]] + V[F[fm, 2]]) / 3.0
            py = np.concatenate([py, flat // size])
            px = np.concatenate([px, flat % size])
            P = np.concatenate([P, Pm])
    return py, px, P


def _claim_missing(F, xy, ids, size: int):
    """Грани без своего текселя → (плоские индексы свободных текселей по центру развёртки грани, номера этих граней). Тексель берёт одна грань (первая)."""
    import numpy as np
    own = np.zeros(len(F), bool)
    own[ids[ids >= 0]] = True
    miss = np.nonzero(~own)[0]
    if not len(miss):
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    cuv = (xy[F[miss, 0]] + xy[F[miss, 1]] + xy[F[miss, 2]]) / 3.0
    flat = np.clip(np.floor(cuv[:, 1]).astype(np.int64), 0, size - 1) * size + np.clip(np.floor(cuv[:, 0]).astype(np.int64), 0, size - 1)
    free = ids[flat] < 0
    flat, k = np.unique(flat[free], return_index=True)
    return flat, miss[free][k]


SLIVER_Q = 0.1       # грань — «щепка», если качество q = 4√3·S / (a²+b²+c²) ниже этого (равносторонняя 1, игла → 0)


def sliver_share(V, F, q_max: float = SLIVER_Q) -> float:
    """Доля граней-щепок (длинные узкие треугольники — следы упрощения, которое не смогло схлопнуть рёбра через шов; полосы и трещины на гладкой поверхности). T-167: сперва только отчёт, порога нет."""
    import numpy as np
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    s2 = np.einsum('nc,nc->n', b - a, b - a) + np.einsum('nc,nc->n', c - b, c - b) + np.einsum('nc,nc->n', a - c, a - c)
    q = np.where(s2 > 0, 4.0 * np.sqrt(3.0) * area / np.where(s2 > 0, s2, 1.0), 0.0)
    return float((q < q_max).mean())


def face_coverage(V, F, UV, size: int) -> float:
    """Доля граней, получивших хотя бы один тексель в атласе size×size. Грань без текселя при показе берёт цвет соседнего острова (пятна не того цвета, кадры T-167)."""
    import numpy as np
    from tex_coverage import raster
    xy = np.stack([UV[:, 0] * size, (1.0 - UV[:, 1]) * size], 1)
    ids, _ = raster(xy, F, size)
    ids = np.array(ids).ravel()
    flat, fm = _claim_missing(F, xy, ids, size)
    ids[flat] = fm                                   # свободные тексели по центру развёртки мелких граней — как в переносе
    covered = np.zeros(len(F), bool)
    covered[ids[ids >= 0]] = True
    miss = np.nonzero(~covered)[0]
    if len(miss):
        # у грани нет своего текселя, но тексель в центре её развёртки занят соседом: цвет верный, если сосед в 3D рядом (≤ 1,5 длины её самого длинного ребра)
        cuv = (xy[F[miss, 0]] + xy[F[miss, 1]] + xy[F[miss, 2]]) / 3.0
        fl = np.clip(np.floor(cuv[:, 1]).astype(np.int64), 0, size - 1) * size + np.clip(np.floor(cuv[:, 0]).astype(np.int64), 0, size - 1)
        ow = ids[fl]
        has = ow >= 0
        C = (V[F[:, 0]] + V[F[:, 1]] + V[F[:, 2]]) / 3.0
        e = np.maximum.reduce([np.linalg.norm(V[F[miss, 0]] - V[F[miss, 1]], axis=1), np.linalg.norm(V[F[miss, 1]] - V[F[miss, 2]], axis=1),
                               np.linalg.norm(V[F[miss, 2]] - V[F[miss, 0]], axis=1)])
        near = np.zeros(len(miss), bool)
        near[has] = np.linalg.norm(C[miss[has]] - C[ow[has]], axis=1) <= 1.5 * e[has]
        covered[miss[near]] = True
    return float(covered.mean()) if len(F) else 1.0


def plate_free_faces(V, F, strip_plate: bool = True):
    """Грани родной формы без плиты-подложки TRELLIS (plate_strip.py, правила tools/scout/rules/plate-strip.json) → (F без плиты, отчёт). Упрощённая форма собрана БЕЗ плиты, поэтому
    и перенос цвета, и Chamfer сравнивают её с родной тоже без плиты. Плиты нет / выключено / модуля нет — F как есть."""
    import numpy as np
    if not strip_plate:
        return F, {'plate_found': False, 'refused': '', 'skipped': 'выключено'}
    sys.path.insert(0, os.path.dirname(HERE))           # tools/scout
    try:
        import plate_strip as P
    except ImportError:
        return F, {'plate_found': False, 'refused': '', 'skipped': 'нет plate_strip.py'}
    remove, rep = P.analyze(V, F)
    return (F[~remove] if remove.any() else F), rep


def chamfer_ratio(native_path: str, shape_path: str, n: int = 40000, strip_plate: bool = True) -> tuple[float, float]:
    """Расстояние Chamfer между родной (без плиты-подложки) и упрощённой формой по точкам поверхности, в долях диагонали габарита родной: (среднее, p99). Большое — форма не от этого черновика или другие оси."""
    import numpy as np
    import trimesh
    from scipy.spatial import cKDTree
    a = trimesh.load(native_path, force='mesh', process=False)
    Fk, _ = plate_free_faces(np.asarray(a.vertices), np.asarray(a.faces), strip_plate)
    if len(Fk) != len(a.faces):
        a = trimesh.Trimesh(vertices=np.asarray(a.vertices), faces=Fk, process=False)
        a.remove_unreferenced_vertices()
    b = trimesh.load(shape_path, force='mesh', process=False)
    pa, _ = trimesh.sample.sample_surface(a, n, seed=1)
    pb, _ = trimesh.sample.sample_surface(b, n, seed=1)
    diag = float(np.linalg.norm(a.bounds[1] - a.bounds[0])) or 1.0
    d1 = cKDTree(pb).query(pa)[0]
    d2 = cKDTree(pa).query(pb)[0]
    return float((d1.mean() + d2.mean()) / 2 / diag), float(max(np.percentile(d1, 99), np.percentile(d2, 99)) / diag)


def normal_deviation(native_path: str, shape_path: str, n: int = 40000) -> tuple[float, float, bool]:
    """Разница затенения родной↔упрощённая без съёмки (T-167: «плашка» на гладком боку у модели без NORMAL): на n точках поверхности упрощённой — угол между её НОРМАЛЬЮ ЗАТЕНЕНИЯ
    (нормали вершин из файла по барицентрике; нет NORMAL в файле — плоская нормаль грани, как её рисует просмотрщик) и СГЛАЖЕННОЙ нормалью родной (родная без плиты, сырая сетка TRELLIS шумит
    на масштабе вершины: среднее по ближайшим согласным вершинам). Яркость clay ≈ cos этого угла: p99 угла — геометрический аналог «p99 разницы затенения clay» без съёмки (съёмка родной и упрощённой
    кадрируется по разным габаритам — плита, — поэтому в кадрах поточечно не сравнить). Возврат: (среднее°, p99°, есть ли в файле NORMAL)."""
    import numpy as np
    import trimesh
    na, nb = load_glb(native_path), load_glb(shape_path)
    na['F'], _ = plate_free_faces(na['V'], na['F'])
    ref_V, ref_N = native_reference(na['V'], na['F'], na['N'], read_prep(shape_path))          # эталон — родная после той же предобработки (сайдкар `<выход>.prep.json`)
    b = trimesh.Trimesh(vertices=nb['V'], faces=nb['F'], process=False)
    has_n = bool(nb.get('has_normals')) and nb.get('N') is not None
    pts, fi = trimesh.sample.sample_surface(b, n, seed=1)
    if has_n:
        tri = nb['V'][nb['F'][fi]]
        bc = trimesh.triangles.points_to_barycentric(tri, pts)
        nrm = np.einsum('nk,nkc->nc', bc, nb['N'][nb['F'][fi]])
    else:
        nrm = np.asarray(b.face_normals)[fi]
    nrm = nrm / np.where(np.linalg.norm(nrm, axis=1, keepdims=True) < 1e-12, 1.0, np.linalg.norm(nrm, axis=1, keepdims=True))
    scale = vertex_spacing(nb['V'], nb['F'])[nb['F'][fi]].mean(1)                    # тот же радиус сглаживания, что в переносе нормалей
    ref = smooth_native_normals(ref_V, ref_N, pts, np.asarray(b.face_normals)[fi], scale)
    cos = np.clip(np.einsum('nc,nc->n', nrm, ref), -1.0, 1.0)
    ang = np.degrees(np.arccos(cos))
    return float(ang.mean()), float(np.percentile(ang, 99)), has_n


def _rgba(img, size: int | None = None):
    import numpy as np
    from PIL import Image
    if img is None:
        return None
    im = img.convert('RGBA')
    if size and im.size != (size, size):
        im = im.resize((size, size), Image.BILINEAR)
    return np.asarray(im, np.uint8)


def _fill_empty(arr, filled):
    """Тексели вне островков и «без цвета» берут цвет ближайшего цветного (поля вокруг островков — иначе в швах просвечивает чёрное)."""
    import numpy as np
    from scipy import ndimage
    if filled.all() or not filled.any():
        return arr
    idx = ndimage.distance_transform_edt(~filled, return_distances=False, return_indices=True)
    return arr[idx[0], idx[1]]


PAD_RING = 1.0          # «кольцо границы острова»: занятые тексели не дальше этого (в текселях) от свободного — их цвет берётся с края фигуры и чаще всего «крошка»
PAD_REACH = 3.0         # дальше этого от внутренних текселей перекраска кольца/поля не идёт (узкие острова без «внутри» остаются как есть)


SPECKLE_DE = 60          # «крошка»: тексель отличается от медианы 3×3 хоть по одному каналу больше чем на столько (из 255)


def speckle_share(res, filled) -> float:
    """Доля занятых развёрткой текселей атласа, резко отличных от медианы 3×3 (крошка по кромке, точки по раме). Справочная мерка для check.json этапа 02."""
    import numpy as np
    from scipy import ndimage
    if not filled.any():
        return 0.0
    rgb = np.asarray(res)[..., :3]
    med = np.stack([ndimage.median_filter(rgb[..., c], size=3) for c in range(3)], -1)
    diff = np.abs(rgb.astype(np.int16) - med.astype(np.int16)).max(2)
    return round(float((diff[filled] > SPECKLE_DE).mean()), 5)


def atlas_speckle(g) -> float | None:
    """Крошка атласа готового GLB (по занятым развёрткой текселям)."""
    import numpy as np
    if g['base'] is None:
        return None
    n = g['base'].size[0]
    py, px, _ = texel_points(g['V'], g['F'], g['UV'], n)
    filled = np.zeros((n, n), bool)
    filled[py, px] = True
    return speckle_share(np.asarray(g['base'].convert('RGBA')), filled)


def pad_islands(arr, filled, mode: str = 'nearest', ring: float = PAD_RING, reach: float = PAD_REACH, de: int = 60):
    """Заполнение поля вокруг островков и кольца границы. `nearest` — как было: свободные тексели берут цвет ближайшего занятого. `interior` — стандартная «дилатация изнутри»: кольцо границы (занятые не дальше `ring` от
    свободного) и поле берут цвет ближайшего ВНУТРЕННЕГО тексела (дальше `ring` от границы), край острова не распространяется в поле. `repair` — как interior, но кольцо перекрашивается только там, где тексель резко
    (> de из 255 по каналу) отличается от медианы 3×3, остальное кольцо остаётся родным; поле — от исправленного. Острова без «внутри» (уже `reach`) остаются как в nearest."""
    import numpy as np
    from scipy import ndimage
    base = _fill_empty(arr, filled)
    if mode == 'nearest' or filled.all() or not filled.any():
        return base
    d_in = ndimage.distance_transform_edt(filled)
    core = filled & (d_in > ring)
    if not core.any():
        return base
    d_core, idx = ndimage.distance_transform_edt(~core, return_indices=True)
    near_core = arr[idx[0], idx[1]]
    if mode == 'interior':
        sel = (d_core > 0) & (d_core <= reach)
        out = base.copy()
        out[sel] = near_core[sel]
        return out
    if mode == 'repair':
        med = np.stack([ndimage.median_filter(arr[..., c], size=3) for c in range(arr.shape[2])], -1)
        crumb = filled & (d_in <= ring) & (np.abs(arr.astype(np.int16) - med.astype(np.int16)).max(2) > de) & (d_core <= reach)
        fixed = arr.copy()
        fixed[crumb] = near_core[crumb]
        return _fill_empty(fixed, filled)
    raise ValueError(f'неизвестный режим заполнения поля: {mode}')


def transfer(native_path: str, shape_path: str, out_path: str, size: int | None = None, max_dist: float = MAX_DIST, strip_plate: bool = True, pad: str = 'nearest') -> dict:
    """Главная функция: родной GLB (с цветом) + упрощённая форма с НОВОЙ развёрткой → GLB с перенесёнными baseColor / металл-шероховатость / альфа. Возвращает отчёт."""
    import numpy as np
    import trimesh
    from PIL import Image
    from scipy.spatial import cKDTree
    t0 = time.time()
    nat = load_glb(native_path)
    if nat['base'] is None:
        raise ValueError(f'{os.path.basename(native_path)}: в родном GLB нет baseColor — переносить нечего')
    tgt = load_glb(shape_path)
    nsize = nat['base'].size[0]
    size = int(size or nsize)
    base = _rgba(nat['base'])
    mr = _rgba(nat['mr'], nsize) if nat['mr'] is not None else None
    nat['F'], plate_rep = plate_free_faces(nat['V'], nat['F'], strip_plate)       # родная без плиты: плитные тексели цвет не отдают
    used = np.unique(nat['F'])
    ny, nx, NP = texel_points(nat['V'], nat['F'], nat['UV'], nsize)
    ty, tx, TP = texel_points(tgt['V'], tgt['F'], tgt['UV'], size, conservative=True)
    t_ras = time.time() - t0
    diag = float(np.linalg.norm(nat['V'][used].max(0) - nat['V'][used].min(0))) or 1.0
    tree = cKDTree(NP)
    dist, j = tree.query(TP, k=1, workers=-1)
    ok = dist <= max_dist * diag
    oc_native = base[ny[j], nx[j]]
    oc_mr = mr[ny[j], nx[j]] if mr is not None else None
    res = np.zeros((size, size, 4), np.uint8)
    resmr = np.zeros((size, size, 4), np.uint8) if mr is not None else None
    filled = np.zeros((size, size), bool)
    res[ty[ok], tx[ok]] = oc_native[ok]
    if resmr is not None:
        resmr[ty[ok], tx[ok]] = oc_mr[ok]
    filled[ty[ok], tx[ok]] = True
    res = pad_islands(res, filled, pad)
    if resmr is not None:
        resmr = pad_islands(resmr, filled, pad)
    share = float(ok.mean()) if len(ok) else 0.0
    mat = trimesh.visual.material.PBRMaterial(
        baseColorTexture=Image.fromarray(res, 'RGBA'), baseColorFactor=np.array([255, 255, 255, 255], np.uint8),
        metallicRoughnessTexture=Image.fromarray(resmr[..., :3], 'RGB') if resmr is not None else None,
        metallicFactor=1.0 if resmr is not None else 0.0, roughnessFactor=1.0 if resmr is not None else 0.8, alphaMode='OPAQUE')
    prep = read_prep(out_path)                                    # предобработка родной перед упрощением (сайдкар sg_prep_shape.py): нормали берём из родной после неё же
    ref_V, ref_N = native_reference(nat['V'], nat['F'], nat['N'], prep) if nat.get('N') is not None else (None, None)
    normals = transfer_normals(ref_V, ref_N, tgt['V'], tgt['F']) if nat.get('has_normals') and ref_N is not None else None
    m = trimesh.Trimesh(vertices=tgt['V'], faces=tgt['F'], vertex_normals=normals, process=False)
    m.visual = trimesh.visual.TextureVisuals(uv=tgt['UV'], material=mat)
    tmp = out_path + '.tmp.glb'
    m.export(tmp, file_type='glb')
    os.replace(tmp, out_path)
    rep = {'native': os.path.basename(native_path), 'native_size': nsize, 'size': size, 'native_texels': int(len(ny)), 'target_texels': int(len(ty)), 'with_color': int(ok.sum()),
           'share': round(share, 5), 'faces_with_texel': round(face_coverage(tgt['V'], tgt['F'], tgt['UV'], size), 5), 'max_dist_m': round(max_dist * diag, 5), 'dist_p50': round(float(np.median(dist)), 6) if len(dist) else 0.0,
           'dist_p99': round(float(np.percentile(dist, 99)), 6) if len(dist) else 0.0, 'has_mr': mr is not None, 'normals_from_native': normals is not None, 'native_prep': prep, 'plate_found': bool(plate_rep.get('plate_found')) and not plate_rep.get('refused'), 'sec_raster': round(t_ras, 1), 'sec_total': round(time.time() - t0, 1)}
    return rep


def guard_report(path: str) -> dict:
    """Сторож шага 0 по одному GLB: пришёл ли baseColor и какая доля альфа<128 по ЗАНЯТЫМ текселям развёртки (пустое поле атласа всегда 0 и не считается)."""
    import numpy as np
    r = {'file': os.path.basename(path), 'has_color': False, 'tex_size': None, 'alpha_lt128': None, 'alpha_suspect': False, 'error': None}
    try:
        g = load_glb(path)
    except Exception as e:  # noqa: BLE001
        r['error'] = str(e)[:120]
        return r
    if g['base'] is None:
        return r
    r['has_color'] = True
    n = g['base'].size[0]
    r['tex_size'] = n
    a = _rgba(g['base'])[..., 3]
    if a.min() == a.max() == 255:
        r['alpha_lt128'] = 0.0
        return r
    py, px, _ = texel_points(g['V'], g['F'], g['UV'], n)
    if len(py):
        r['alpha_lt128'] = round(float((a[py, px] < ALPHA_LT).mean()), 4)
        r['alpha_suspect'] = r['alpha_lt128'] > ALPHA_SUSPECT
    return r


def guard(paths: list[str]) -> tuple[int, str, list]:
    """Счётчик по набору: (код, строка итога, отчёты). Код 1 — есть GLB без baseColor или не открылся."""
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(os.path.join(p, x) for x in os.listdir(p) if x.endswith('.glb') and '.raw.' not in x)
        else:
            files.append(p)
    reps = [guard_report(f) for f in files]
    bad = [r for r in reps if not r['has_color']]
    sus = [r for r in reps if r['alpha_suspect']]
    line = (f'ЦВЕТ: пришёл {len(reps) - len(bad)} из {len(reps)}; не пришёл {len(bad)}'
            + (' [' + ', '.join(r['file'] for r in bad[:8]) + ('…' if len(bad) > 8 else '') + ']' if bad else '')
            + f'; альфа<128 больше {int(ALPHA_SUSPECT * 100)} %: {len(sus)}')
    return (1 if bad else 0), line, reps


# ---------------------------------------------------------------- проверка на каждом этапе (T-20261120-167; paint_stage.py — общий писатель check.json, T-164) -----------------------
FACES_MAX = 150000        # этап 02: граней упрощённой формы не больше


def _paint_stage():
    sys.path.insert(0, os.path.dirname(HERE))           # tools/scout
    import paint_stage
    return paint_stage


def _link(src: str, dst: str) -> None:
    import shutil
    if os.path.exists(dst):
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _atlas_frame(img, dst: str, side: int = 768) -> None:
    """Контрольный кадр этапа без Blender: карта цвета (baseColor) в квадрате side×side; альфа<255 показана шахматкой — сразу видно, цвет пришёл и не пустой."""
    import numpy as np
    from PIL import Image
    im = img.convert('RGBA').resize((side, side), Image.BILINEAR)
    a = np.asarray(im).astype(np.float32)
    yy, xx = np.mgrid[0:side, 0:side]
    chk = np.where(((yy // 24) + (xx // 24)) % 2 == 0, 200.0, 120.0)[..., None]
    al = a[..., 3:4] / 255.0
    rgb = a[..., :3] * al + chk * (1 - al)
    Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), 'RGB').save(dst)


def stage01(run: str, sku: str, native_glb: str, frame_src: str | None = None, seconds: float | None = None) -> dict:
    """Этап 01-trellis: родной GLB TRELLIS.2 — есть ли baseColor (главная мерка, порог 1) и доля альфа<128 по занятым текселям (справочная: пока ненадёжна как маска стекла, T-166).
    Папка `<run>/<sku>/01-trellis/`: `model.glb` (ссылка на родной), `frame.png` (кадр из `frame_src` или карта цвета), `check.json`."""
    ps = _paint_stage()
    d = ps.stage_dir(run, sku, '01-trellis')
    rep = guard_report(native_glb)
    if os.path.exists(native_glb):
        _link(native_glb, os.path.join(d, 'model.glb'))
    frame = None
    if frame_src and os.path.exists(frame_src):
        import shutil
        shutil.copy2(frame_src, os.path.join(d, 'frame.png'))
        frame = 'frame.png'
    elif rep['has_color']:
        _atlas_frame(load_glb(native_glb)['base'], os.path.join(d, 'frame.png'))
        frame = 'frame.png'
    return ps.write_check(d, '01-trellis', sku, None,
                          metric={'name': 'has_base_color', 'value': 1 if rep['has_color'] else 0, 'threshold': 1, 'op': '>='},
                          metrics={'alpha_lt128': {'value': rep['alpha_lt128'], 'op': '<=', 'note': 'справочная, без порога: у 17 из 30 GLB 31–94 % даже у велюра (T-166)'}},
                          reason=rep['error'] or ('' if rep['has_color'] else 'в родном GLB нет baseColor — цвет не пришёл'),
                          seconds=seconds, outputs=['model.glb'] if os.path.exists(native_glb) else [], frame=frame,
                          tex_size=rep['tex_size'], alpha_suspect=rep['alpha_suspect'], file=rep['file'])


def stage02(run: str, sku: str, native_glb: str, out_glb: str, rep: dict | None = None, faces_max: int = FACES_MAX, min_share: float = MIN_SHARE,
            frame_src: str | None = None, seconds: float | None = None, strip_plate: bool = True) -> dict:
    """Этап 02-prep: упрощённая форма с НОВОЙ развёрткой и перенесённым цветом — доля текселей с цветом ≥ 99 % (главная мерка) и граней ≤ 150 тыс.
    `rep` — отчёт `transfer()`; нет — считается заново из файлов. Папка `<run>/<sku>/02-prep/`: `shape.glb`, `frame.png`, `check.json`."""
    ps = _paint_stage()
    d = ps.stage_dir(run, sku, '02-prep')
    if not os.path.exists(out_glb):
        return ps.write_check(d, '02-prep', sku, False, metric={'name': 'faces_with_texel', 'value': None, 'threshold': FACES_TEXEL_MIN, 'op': '>='},
                              reason='нет выходного GLB упрощённой формы (перенос не удался или упрощение не прошло)', seconds=seconds)
    g = load_glb(out_glb)
    faces = int(len(g['F']))
    if rep is None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            rep = transfer(native_glb, out_glb, os.path.join(tmp, 'x.glb'), size=g['base'].size[0] if g['base'] is not None else None, strip_plate=strip_plate)
    _link(out_glb, os.path.join(d, 'shape.glb'))
    frame = None
    if frame_src and os.path.exists(frame_src):
        import shutil
        shutil.copy2(frame_src, os.path.join(d, 'frame.png'))
        frame = 'frame.png'
    elif g['base'] is not None:
        _atlas_frame(g['base'], os.path.join(d, 'frame.png'))
        frame = 'frame.png'
    cov = face_coverage(g['V'], g['F'], g['UV'], g['base'].size[0] if g['base'] is not None else rep.get('size') or 1024)
    ch_mean, ch_p99 = chamfer_ratio(native_glb, out_glb, strip_plate=strip_plate)
    metrics = {'faces': {'value': faces, 'threshold': faces_max, 'op': '<='},
               'speckle_share': {'value': atlas_speckle(g), 'op': '<=', 'note': f'справочная, без порога: доля занятых текселей атласа, отличных от медианы 3×3 больше чем на {SPECKLE_DE} из 255 (крошка кромки)'},
               'sliver_share': {'value': round(sliver_share(g['V'], g['F']), 5), 'op': '<=', 'note': f'справочная, без порога (порог — по таблице 30): доля граней-щепок с качеством q < {SLIVER_Q}'},
               'chamfer_diag': {'value': round(ch_mean, 5), 'threshold': CHAMFER_MAX, 'op': '<='},
               'chamfer_p99_diag': {'value': round(ch_p99, 5)},
               'color_texel_share': {'value': rep['share'], 'threshold': min_share, 'op': '>='}}
    nd_mean, nd_p99, has_n = normal_deviation(native_glb, out_glb)
    nr = normal_rules()
    metrics.update({'normal_dev_mean_deg': {'value': round(nd_mean, 2), 'threshold': nr['normal_dev_mean_deg_max'], 'op': '<='},
                    'normal_dev_p99_deg': {'value': round(nd_p99, 1), 'threshold': nr['normal_dev_p99_deg_max'], 'op': '<='},
                    'normals_in_file': {'value': bool(has_n)}})
    plate_json = (out_glb[:-4] if out_glb.endswith('.glb') else out_glb) + '.plate.json'      # отчёт среза плиты, его пишет sg_prep_shape.py (до упрощения)
    if os.path.exists(plate_json):
        import json
        sys.path.insert(0, os.path.dirname(HERE))
        import plate_strip as P
        with open(plate_json, encoding='utf-8') as fp:
            prep_plate = json.load(fp)
        metrics.update({f'plate_{k}': v for k, v in P.plate_metrics(prep_plate).items()})
    return ps.write_check(d, '02-prep', sku, None,
                          metric={'name': 'faces_with_texel', 'value': round(cov, 5), 'threshold': FACES_TEXEL_MIN, 'op': '>='},
                          metrics=metrics,
                          reason=(f'форма не от этого черновика: chamfer_diag {ch_mean:.3f} > {CHAMFER_MAX} (Chamfer родной↔упрощённая, доля диагонали)' if ch_mean > CHAMFER_MAX else
                                  normals_reason(nd_mean, nd_p99, has_n, nr)),
                          seconds=seconds, outputs=['shape.glb'], frame=frame, native_texels=rep.get('native_texels'), target_texels=rep.get('target_texels'),
                          dist_p50=rep.get('dist_p50'), dist_p99=rep.get('dist_p99'), atlas=rep.get('size'), has_mr=rep.get('has_mr'), native_prep=read_prep(out_glb), ladder=read_ladder(out_glb))



def selftest() -> int:
    """Тот же набор проверок, что `tests_color_transfer.py` (отдельный файл запускается в CI)."""
    sys.path.insert(0, HERE)
    import tests_color_transfer as T
    return T.main()


def main() -> int:
    if '--selftest' in sys.argv:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    t = sub.add_parser('transfer')
    t.add_argument('--native', required=True)
    t.add_argument('--shape', required=True)
    t.add_argument('--out', required=True)
    t.add_argument('--size', type=int, default=None)
    t.add_argument('--max-dist', type=float, default=MAX_DIST)
    t.add_argument('--pad', choices=['nearest', 'interior', 'repair'], default='nearest', help='заполнение поля вокруг островков: nearest (как было) | interior (дилатация изнутри) | repair (только крошка кольца границы)')
    t.add_argument('--min-share', type=float, default=MIN_SHARE)
    t.add_argument('--no-plate-strip', action='store_true', help='не вычитать плиту-подложку из родной формы (если sg_prep_shape.py плиту не резал)')
    g = sub.add_parser('guard')
    g.add_argument('paths', nargs='+')
    st = sub.add_parser('stages', help='записать этапы 01-trellis и (если есть --out) 02-prep в <run>/<sku>/NN-этап/ (check.json + кадр)')
    st.add_argument('--run', required=True)
    st.add_argument('--sku', required=True)
    st.add_argument('--native', required=True)
    st.add_argument('--out', default=None, help='упрощённая форма с перенесённым цветом (выход sg_prep_shape.py --color-from)')
    st.add_argument('--frame01', default=None)
    st.add_argument('--frame02', default=None)
    st.add_argument('--no-plate-strip', action='store_true')
    a = ap.parse_args()
    if a.cmd == 'stages':
        c1 = stage01(a.run, a.sku, a.native, a.frame01)
        print('01-trellis:', 'прошёл' if c1['passed'] else 'НЕ прошёл', c1['reason'])
        code = 0 if c1['passed'] else 1
        if a.out:
            c2 = stage02(a.run, a.sku, a.native, a.out, None, frame_src=a.frame02, strip_plate=not a.no_plate_strip)
            print('02-prep:', 'прошёл' if c2['passed'] else 'НЕ прошёл', c2['reason'])
            code = code or (0 if c2['passed'] else 1)
        return code
    if a.cmd == 'guard':
        code, line, reps = guard(a.paths)
        for r in reps:
            if not r['has_color'] or r['alpha_suspect']:
                print('  ', r)
        print(line)
        return code
    rep = transfer(a.native, a.shape, a.out, a.size, a.max_dist, strip_plate=not a.no_plate_strip, pad=a.pad)
    print('перенос:', rep)
    import json
    print('перенос-итог:', json.dumps({'size': rep.get('size'), 'share': rep.get('share'), 'faces_with_texel': rep.get('faces_with_texel')}))   # строка для sg_prep_shape.py (лестница отказов)
    print(f'перенос: с цветом {rep["share"]:.2%} текселей нового атласа (цель ≥ {a.min_share:.0%}), граней с цветом верного места {rep["faces_with_texel"]:.2%} (цель ≥ {FACES_TEXEL_MIN:.0%}), расстояние p50 {rep["dist_p50"]}, p99 {rep["dist_p99"]}, {rep["sec_total"]} с')
    if rep['share'] >= a.min_share and rep['faces_with_texel'] >= FACES_TEXEL_MIN:
        return 0
    rejected = (a.out[:-4] if a.out.endswith('.glb') else a.out) + '.rejected.glb'
    os.replace(a.out, rejected)      # отказ: под рабочим именем файла НЕТ — потребители (out30) не возьмут негодную модель
    print(f'перенос: ОТКАЗ — результат отложен как {rejected}')
    return 3


if __name__ == '__main__':
    sys.exit(main())
