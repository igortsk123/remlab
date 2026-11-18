#!/usr/bin/env python3
"""ДЕТЕКТОР «СЕРАЯ КРЫШКА» (T-20261118-04/12, план mesh-grey-top-01; корень — T-04/11).

ЗАЧЕМ. У ~81 собственного меша (столы, комоды, столики) верх нарисован пустым серым (128,128,128) — фоном сети paint: вид сверху сеть
не нарисовала, запекание приняло фон за окрашенную поверхность, дорисовка не тронула. В 3D и на фото «Сделать фото» стол выходит с серой
крышкой вместо дуба/белого/чёрного. Сторож общего цвета (`mesh_color_check.py`) и приёмка (`mesh_gate_pbr.py`) это не видят: первый
берёт медиану по центрам граней всей модели, второй смотрит карты целиком.

КАК ДЕТЕКТИРУЕМ — ГЕОМЕТРИЧЕСКИ, а не по всему атласу (Codex 18.11, `_intake/codex/2026-11-18-grey-top-answer.md`):
  1) верх = грани почти горизонтальные (нормаль вверх) у самой верхней плоскости модели, достаточной площади относительно её следа;
     нет такой поверхности (стул, лампа) — вердикт `na`, ничего не судим;
  2) UV-тексели верхних граней, БЕЗ швов (тексели, на которые ложатся и не-верхние грани) и БЕЗ полей (эрозия маски на `erode_px`);
  3) по этим текселям: доля, где КАЖДЫЙ канал albedo в 124–134 («фон сети»), разброс (σ), площадь (в текселях исходной карты),
     совпадение с MR ≈ 0,5/0,5 (шероховатость G и металлик B — константа фона), контраст с кромкой (боковые грани).
  Вердикт: `ok` | `candidate` (доля ≥ 80 %, разброс низкий — на ручную проверку) | `reject` (доля ≥ 95 % И резкая граница с кромкой и MR ≈ 0,5/0,5).
  Настоящие серые товары (бетон, графит) с одноцветной кромкой в `reject` не попадают: кромка той же серости — не «пустой верх».
Пороги — `rules/mesh-grey-top.json` (с калибровкой). Вердикт — ОТДЕЛЬНЫМ полем, правило общего цвета не подменяет.

  ~/venvs/scout/bin/python mesh_grey_top.py <model.glb> [...]        # вердикт + числа по файлам
  python3 mesh_grey_top.py --selftest                                 # без trimesh и сети: синтетические коробки
Использование из кода: `analyze(glb)`, `measure_glbs(glbs, cache_path)`; в приёмке — `salad/apply_repairs.accept`,
в ночном сторожe — `mesh_color_check.guard`, в карантине — `mesh_quarantine.apply` (причина `grey_top`).
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, 'rules', 'mesh-grey-top.json')
VERDICTS = ('ok', 'candidate', 'reject', 'na')
BAD = ('candidate', 'reject')                 # что считается «серой крышкой» для карантина и сводки


def rules(path: str = RULES) -> dict:
    return json.load(open(path, encoding='utf-8'))


# ---------- чистое ядро (numpy) ----------

def _erode(m: np.ndarray, k: int) -> np.ndarray:
    """Эрозия бинарной маски квадратом (2k+1): тексели у границы (швы, поля, сглаживание) не считаем. Без scipy."""
    if k <= 0:
        return m
    out = m.copy()
    h, w = m.shape
    p = np.pad(m, k, constant_values=False)
    for dy in range(-k, k + 1):
        for dx in range(-k, k + 1):
            out &= p[k + dy:k + dy + h, k + dx:k + dx + w]
    return out


def _raster(uv: np.ndarray, faces: np.ndarray, w: int, h: int) -> np.ndarray:
    """Маска текселей, закрытых данными гранями (UV → пиксели, V вверх)."""
    from PIL import Image, ImageDraw
    img = Image.new('L', (w, h), 0)
    dr = ImageDraw.Draw(img)
    for f in faces:
        dr.polygon([(float(uv[i][0] * (w - 1)), float((1 - uv[i][1]) * (h - 1))) for i in f], fill=255)
    return np.asarray(img) > 0


def top_faces(V: np.ndarray, F: np.ndarray, R: dict) -> tuple:
    """(индексы верхних граней, индексы боковых, площадь верха, площадь следа). Верх — нормаль ≥ up_cos вверх (ось Y glTF) у самой верхней
    плоскости (в пределах band·высоты от неё); боковые — почти вертикальные (|ny| ≤ side_ny)."""
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    cr = np.cross(b - a, c - a)
    ar = np.linalg.norm(cr, axis=1) / 2
    n = cr / np.maximum(np.linalg.norm(cr, axis=1, keepdims=True), 1e-12)
    cy = (a[:, 1] + b[:, 1] + c[:, 1]) / 3
    height = float(V[:, 1].max() - V[:, 1].min())
    up = n[:, 1] >= R['up_cos']
    if not up.any() or height <= 0:
        return np.array([], int), np.array([], int), 0.0, 0.0
    ytop = cy[up].max()
    top = np.where(up & (cy >= ytop - R['band'] * height))[0]
    side = np.where(np.abs(n[:, 1]) <= R['side_ny'])[0]
    foot = float((V[:, 0].max() - V[:, 0].min()) * (V[:, 2].max() - V[:, 2].min()))
    return top, side, float(ar[top].sum()), foot


def analyze_arrays(V, F, UV, albedo, mr=None, R: dict | None = None) -> dict:
    """Вердикт модели: верх (калиброванное ядро `analyze_top_arrays`) + дыры на ВСЕХ поверхностях (`surfaces_arrays`). Общий вердикт — худший из двух;
    числа верха остаются как были (поля верха), поверхности — списком `surfaces`, где — `where`. Нет верха, но есть видимые поверхности — вердикт по ним
    (стулья, диваны, кресла: раньше `na`)."""
    R = R or rules()
    top = analyze_top_arrays(V, F, UV, albedo, mr, R)
    sf = surfaces_arrays(V, F, UV, albedo, mr, R)
    order = {'na': -1, 'ok': 0, 'candidate': 1, 'reject': 2}
    out = dict(top)
    out['surfaces'] = sf['surfaces']
    out['where'] = sf['where']
    out['top_verdict'] = top['verdict']
    if order[sf['verdict']] > order[top['verdict']]:
        out['verdict'] = sf['verdict']
        out['median_rgb'] = sf['median_rgb']                   # цвет худшей поверхности — для сверки с фото
        out.pop('why', None)
    elif top['verdict'] == 'na' and sf['verdict'] == 'ok':
        out['verdict'] = 'ok'
        out.pop('why', None)
    vis = [x for x in sf['surfaces'] if x['role'] != 'низ']
    tot = sum(x['area_px'] for x in vis)
    out['bright_share'] = round(sum(x['bright_share'] * x['area_px'] for x in vis) / tot, 3) if tot else None
    out['bright_flat'] = bool(vis) and any(x['bright_share'] >= R['bright_share_min'] and x['std'] <= R['std_max'] for x in vis)
    return out


def analyze_top_arrays(V, F, UV, albedo, mr=None, R: dict | None = None) -> dict:
    """Ядро «верха»: вершины (n,3), грани (m,3), UV (n,2), albedo (H,W,3) uint8, mr (H,W,3) uint8 | None → вердикт и числа. Чистая функция."""
    R = R or rules()
    V, F, UV = np.asarray(V, float), np.asarray(F, int), np.asarray(UV, float)
    top, side, top_area, foot = top_faces(V, F, R)
    if not len(top) or foot <= 0 or top_area < R['min_top_frac'] * foot:
        return {'verdict': 'na', 'why': 'нет горизонтальной верхней поверхности'}
    H0, W0 = albedo.shape[:2]
    sc = min(1.0, R['work_px'] / max(H0, W0))                       # считаем на уменьшенной копии (память, скорость); площадь — обратно в исходные
    if sc < 1.0:
        from PIL import Image
        albedo = np.asarray(Image.fromarray(albedo).resize((max(1, int(W0 * sc)), max(1, int(H0 * sc))), Image.BOX))
        mr = None if mr is None else np.asarray(Image.fromarray(mr).resize(albedo.shape[1::-1], Image.BOX))
    H, W = albedo.shape[:2]
    other = np.setdiff1d(np.arange(len(F)), top)
    m_top = _raster(UV, F[top], W, H)
    m_oth = _raster(UV, F[other], W, H) if len(other) else np.zeros_like(m_top)
    inner = _erode(m_top & ~m_oth, R['erode_px'])
    area_px = int(round(inner.sum() / (sc * sc)))
    if area_px < R['min_area_px']:
        return {'verdict': 'na', 'why': 'верх занимает слишком мало текселей', 'area_px': area_px}
    px = albedo[inner].astype(int)
    lo, hi = R['grey_lo'], R['grey_hi']
    share = float(((px >= lo) & (px <= hi)).all(axis=1).mean())                   # окно «серого» (кандидат): шум сжатия сдвигает фон на пару единиц
    pure = float(((px >= R['pure_lo']) & (px <= R['pure_hi'])).all(axis=1).mean())    # чистый фон сети 124–134 (отказ)
    std = float(px.std(axis=0).mean())
    med = np.median(px, axis=0)
    out = {'grey_share': round(share, 3), 'pure_share': round(pure, 3), 'std': round(std, 1), 'area_px': area_px, 'median_rgb': [int(x) for x in med]}
    # диагностика калибровки: доля в окнах пошире (шум сжатия/смешивания сдвигает фон на пару единиц) — в вердикт не входит
    out['wide'] = {f'w{w}': round(float(((px >= 129 - w) & (px <= 129 + w)).all(axis=1).mean()), 3) for w in (5, 8, 12)}
    mr_share = None
    if mr is not None and mr.shape[:2] == albedo.shape[:2]:
        q = mr[inner].astype(int)
        mlo, mhi = R['mr_lo'], R['mr_hi']
        mr_share = float(((q[:, 1] >= mlo) & (q[:, 1] <= mhi) & (q[:, 2] >= mlo) & (q[:, 2] <= mhi)).mean())
        out['mr_share'] = round(mr_share, 3)
    edge = None
    if len(side):
        m_side = _erode(_raster(UV, F[side], W, H) & ~m_top, 1)
        if m_side.sum() >= R['min_edge_px']:
            edge = float(np.abs(np.median(albedo[m_side].astype(int), axis=0) - med).max())
    out['edge_contrast'] = None if edge is None else round(edge, 1)
    cand = share >= R['candidate_share']        # разброс всего верха при 15–20 % настоящей краски велик — на кандидата не давит; для отказа (≥95 %) он и так мал
    rej = (pure >= R['reject_share'] and std <= R['std_max'] and edge is not None and edge >= R['edge_min']
           and (mr_share is None or mr_share >= R['mr_share_min']))
    out['verdict'] = 'reject' if rej else 'candidate' if cand else 'ok'
    return out


# ---------- дыры покраски на ЛЮБОЙ поверхности (T-04/12 расширение, владелец TG 1856) ----------

def _label_largest(mask: np.ndarray) -> int:
    """Площадь (текселей) крупнейшей СВЯЗНОЙ (4-соседство) области маски. Без scipy: заливка стеком по уменьшенной копии не нужна — маска уже ≤ work_px."""
    m = mask.copy()
    h, w = m.shape
    best = 0
    ys, xs = np.nonzero(m)
    for y0, x0 in zip(ys.tolist(), xs.tolist()):
        if not m[y0, x0]:
            continue
        m[y0, x0] = False
        st, n = [(y0, x0)], 0
        while st:
            y, x = st.pop()
            n += 1
            if y > 0 and m[y - 1, x]:
                m[y - 1, x] = False; st.append((y - 1, x))
            if y + 1 < h and m[y + 1, x]:
                m[y + 1, x] = False; st.append((y + 1, x))
            if x > 0 and m[y, x - 1]:
                m[y, x - 1] = False; st.append((y, x - 1))
            if x + 1 < w and m[y, x + 1]:
                m[y, x + 1] = False; st.append((y, x + 1))
        best = max(best, n)
    return best


def face_roles(V: np.ndarray, F: np.ndarray, R: dict) -> np.ndarray:
    """Роль каждой грани по нормали (ось Y glTF — вверх): 'верх' (горизонталь у самой верхней плоскости), 'сиденье' (прочая горизонталь вверх: сиденье, полка),
    'низ' (горизонталь вниз — не видна), 'вертикаль+x/-x/+z/-z' (|ny| ≤ side_ny: бок/фасад/спинка; по направлению нормали), 'скос' (остальное)."""
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    cr = np.cross(b - a, c - a)
    n = cr / np.maximum(np.linalg.norm(cr, axis=1, keepdims=True), 1e-12)
    cy = (a[:, 1] + b[:, 1] + c[:, 1]) / 3
    height = float(V[:, 1].max() - V[:, 1].min())
    roles = np.full(len(F), 'скос', dtype=object)
    up = n[:, 1] >= R['up_cos']
    if up.any() and height > 0:
        ytop = cy[up].max()
        roles[up] = 'сиденье'
        roles[up & (cy >= ytop - R['band'] * height)] = 'верх'
    roles[n[:, 1] <= -R['up_cos']] = 'низ'
    vert = np.abs(n[:, 1]) <= R['side_ny']
    ax = np.abs(n[:, 0]) >= np.abs(n[:, 2])
    roles[vert & ax & (n[:, 0] >= 0)] = 'вертикаль+x'
    roles[vert & ax & (n[:, 0] < 0)] = 'вертикаль-x'
    roles[vert & ~ax & (n[:, 2] >= 0)] = 'вертикаль+z'
    roles[vert & ~ax & (n[:, 2] < 0)] = 'вертикаль-z'
    return roles


def _extra_top_rules(out: list, R: dict) -> None:
    """gt-v3: три признака пустого верха, которых не видит «≥80 % окна 117–141» (калибровка T-20261118-04/16, 3 пропуска из 81 известных):
    1) однотонный низкосатурированный верх светлее остальных поверхностей изделия на ≥ flat_body_dL (графитовая тумба с серой крышкой);
    2) однотонный верх с MR≈0,5/0,5 и серым медианом 110–141 (чёрная столешница, у которой фон сети чуть темнее 117);
    3) частичная дыра: ≥ partial_share верха — чистый фон 124–134 (дуб, у которого пол-крышки серое).
    Только роль «верх»; вердикт — candidate (отказ — по прежнему правилу), причина — поле `why`."""
    top = next((x for x in out if x['role'] == 'верх' and x['verdict'] == 'ok'), None)
    if top is None:
        return
    import mesh_color_check as MC
    med = top['median_rgb']
    lab = MC.lab(med)[0]
    rest = [x for x in out if x['role'] not in ('верх', 'низ') and x.get('median_rgb')]
    if rest:
        tot = sum(x['area_px'] for x in rest)
        body = sum(float(MC.lab(x['median_rgb'])[0][0]) * x['area_px'] for x in rest) / tot
        if (top['std'] <= R['flat_std_max'] and float(np.hypot(lab[1], lab[2])) <= R['flat_chroma_max']
                and R['flat_lo'] <= min(med) and max(med) <= R['flat_hi'] and float(lab[0]) - body >= R['flat_body_dL']):
            top['verdict'], top['why'] = 'candidate', 'lighter-than-body'
            return
    if ((top.get('mr_share') or 0) >= R['mrflat_share'] and top['std'] <= R['mrflat_std_max']
            and R['mrflat_lo'] <= min(med) and max(med) <= R['mrflat_hi'] and max(med) - min(med) <= R['mrflat_spread']):
        top['verdict'], top['why'] = 'candidate', 'mr-flat'
        return
    if top['pure_share'] >= R['partial_share'] and top['grey_share'] >= R['partial_share']:
        top['verdict'], top['why'] = 'candidate', 'partial'


def surfaces_arrays(V, F, UV, albedo, mr=None, R: dict | None = None) -> dict:
    """Дыры покраски по ВСЕМ поверхностям: грани делятся на роли (`face_roles`), для каждой роли — её собственные тексели UV (без швов и полей),
    в них: доля текселей «фона сети» (окно grey_lo–grey_hi по всем каналам), чистого фона (pure), разброс, MR≈0,5/0,5, крупнейшая СВЯЗНАЯ дыра (текселей
    исходной карты и доля площади роли), контраст с остальной поверхностью, доля «пересвета» (все каналы ≥ bright_min на однотонной области).
    → {'surfaces': [{role, area_px, grey_share, pure_share, std, mr_share, hole_px, hole_share, edge_contrast, bright_share, median_rgb, verdict}],
       'verdict', 'where', 'median_rgb'}: общий вердикт = худший по ВИДИМЫМ ролям (без 'низ'); роль мельче min_area_px не судим."""
    R = R or rules()
    V, F, UV = np.asarray(V, float), np.asarray(F, int), np.asarray(UV, float)
    H0, W0 = albedo.shape[:2]
    sc = min(1.0, R['work_px'] / max(H0, W0))
    if sc < 1.0:
        from PIL import Image
        albedo = np.asarray(Image.fromarray(albedo).resize((max(1, int(W0 * sc)), max(1, int(H0 * sc))), Image.BOX))
        mr = None if mr is None else np.asarray(Image.fromarray(mr).resize(albedo.shape[1::-1], Image.BOX))
    H, W = albedo.shape[:2]
    roles = face_roles(V, F, R)
    names = sorted(set(roles.tolist()))
    masks = {r: _raster(UV, F[roles == r], W, H) for r in names}
    cover = sum(m.astype(np.uint8) for m in masks.values())
    inner = {r: _erode(m & (cover == 1), R['erode_px']) for r, m in masks.items()}
    out, worst, order = [], None, {'ok': 0, 'candidate': 1, 'reject': 2}
    for r in names:
        mk = inner[r]
        area_px = int(round(mk.sum() / (sc * sc)))
        if area_px < R['min_area_px']:
            continue
        px = albedo[mk].astype(int)
        grey = ((px >= R['grey_lo']) & (px <= R['grey_hi'])).all(axis=1)
        pure = ((px >= R['pure_lo']) & (px <= R['pure_hi'])).all(axis=1)
        med = np.median(px, axis=0)
        row = {'role': r, 'area_px': area_px, 'grey_share': round(float(grey.mean()), 3), 'pure_share': round(float(pure.mean()), 3),
               'std': round(float(px.std(axis=0).mean()), 1), 'median_rgb': [int(x) for x in med],
               'bright_share': round(float((px >= R['bright_min']).all(axis=1).mean()), 3)}
        full = np.zeros(mk.shape, bool)
        full[mk] = grey
        hole = _label_largest(full) if grey.any() else 0
        row['hole_px'] = int(round(hole / (sc * sc)))
        row['hole_share'] = round(hole / max(int(mk.sum()), 1), 3)
        if mr is not None and mr.shape[:2] == albedo.shape[:2]:
            q = mr[mk].astype(int)
            row['mr_share'] = round(float(((q[:, 1] >= R['mr_lo']) & (q[:, 1] <= R['mr_hi']) & (q[:, 2] >= R['mr_lo']) & (q[:, 2] <= R['mr_hi'])).mean()), 3)
        rest = np.zeros(mk.shape, bool)
        for r2 in names:
            if r2 != r and r2 != 'низ':
                rest |= inner[r2]
        row['edge_contrast'] = (round(float(np.abs(np.median(albedo[rest].astype(int), axis=0) - med).max()), 1) if rest.sum() >= R['min_edge_px'] else None)
        mrs = row.get('mr_share')
        rej = (row['pure_share'] >= R['reject_share'] and row['std'] <= R['std_max'] and row['edge_contrast'] is not None and row['edge_contrast'] >= R['edge_min']
               and (mrs is None or mrs >= R['mr_share_min']))
        row['verdict'] = 'reject' if rej else 'candidate' if row['grey_share'] >= R['candidate_share'] else 'ok'
        if r == 'низ':
            row['verdict'] = 'ok'                      # дно не видно: считаем, но не судим
        out.append(row)
    _extra_top_rules(out, R)
    for row in out:
        if row['verdict'] != 'ok' and (worst is None or order[row['verdict']] > order[worst['verdict']]
                                       or (order[row['verdict']] == order[worst['verdict']] and row['area_px'] > worst['area_px'])):
            worst = row
    vis = [x for x in out if x['role'] != 'низ']
    if not vis:
        return {'surfaces': out, 'verdict': 'na', 'where': [], 'median_rgb': None}
    return {'surfaces': out, 'verdict': worst['verdict'] if worst else 'ok', 'where': [x['role'] for x in out if x['verdict'] != 'ok'],
            'median_rgb': worst['median_rgb'] if worst else None}


# ---------- GLB → массивы ----------

def analyze(glb: str, R: dict | None = None) -> dict:
    """Вердикт по файлу GLB (trimesh). Несколько геометрий с текстурой — берём ту, у которой верх выше всех; нет текстуры — `na`."""
    import trimesh
    sc = trimesh.load(glb, force='scene')
    best = None
    for g in sc.geometry.values():
        vis = getattr(g, 'visual', None)
        mat = getattr(vis, 'material', None)
        tex = getattr(mat, 'baseColorTexture', None) or getattr(mat, 'image', None)
        uv = getattr(vis, 'uv', None)
        if tex is None or uv is None:
            continue
        top = float(g.bounds[1][1])
        if best is None or top > best[0]:
            best = (top, g, mat, tex, uv)
    if best is None:
        return {'verdict': 'na', 'why': 'нет текстуры или UV'}
    _, g, mat, tex, uv = best
    mr = getattr(mat, 'metallicRoughnessTexture', None)
    mra = None
    albedo = np.asarray(tex.convert('RGB'))
    if mr is not None:
        mra = np.asarray(mr.convert('RGB').resize((albedo.shape[1], albedo.shape[0])))
    return analyze_arrays(g.vertices, g.faces, uv, albedo, mra, R)


def _one(glb: str):
    try:
        return glb, analyze(glb), None
    except Exception as e:  # noqa: BLE001 — модель не открылась: причиной в кэш, не падаем
        return glb, None, repr(e)[:160]


def _gkey(p: str) -> str | None:
    try:
        return f'{p}:{int(os.path.getmtime(p))}:{rules()["version"]}'
    except OSError:
        return None


BATCH = 24      # моделей на один пул процессов: trimesh не отдаёт память (урок 391) — после пачки процессы заменяются, ОС забирает память


def run_batches(glbs: list, workers: int = 3):
    """(путь, вердикт | None, ошибка | None) по каждой модели. Пачками по BATCH новым пулом; убитый воркер (нехватка памяти) не губит прогон —
    его пачка добирается по одной в отдельных процессах, и только сама виновница получает ошибку."""
    import concurrent.futures as cf
    from concurrent.futures.process import BrokenProcessPool
    for i in range(0, len(glbs), BATCH):
        batch = glbs[i:i + BATCH]
        try:
            with cf.ProcessPoolExecutor(workers) as ex:
                for res in ex.map(_one, batch):
                    yield res
        except BrokenProcessPool:
            print(f'  серая крышка: воркер убит на пачке {i // BATCH + 1} — добираю по одной', flush=True)
            for g in batch:
                try:
                    with cf.ProcessPoolExecutor(1) as ex:
                        yield ex.submit(_one, g).result()
                except BrokenProcessPool:
                    yield g, None, 'воркер убит (нехватка памяти)'


def measure_glbs(glbs, cache: dict, workers: int = 3, save=None) -> None:
    """Вердикт моделей, которых нет в кэше (ключ «путь:mtime:версия правил»). Ошибка открытия — {'error': …} (не повторяем каждую ночь)."""
    todo = sorted({g for g in glbs if _gkey(g) and _gkey(g) not in cache})
    if not todo:
        return
    print(f'серая крышка: моделей к замеру {len(todo)}', flush=True)
    if True:
        for i, (g, res, err) in enumerate(run_batches(todo, workers), 1):
            cache[_gkey(g)] = res if res else {'error': err}
            if save and i % 100 == 0:
                save()
                print(f'  серая крышка {i}/{len(todo)}', flush=True)
    if save:
        save()


def photo_agrees(median_rgb, photo_rgb, R: dict | None = None) -> bool:
    """Цвет верха меша совпадает с цветом ФОТО товара (ΔL ≤ photo_dL, оттенок Δab ≤ photo_dab): товар и правда серый, серый верх — не дефект.
    Нет цвета фото или верха — False (судим по вердикту детектора)."""
    if not median_rgb or not photo_rgb:
        return False
    R = R or rules()
    import mesh_color_check as MC
    a, b = MC.lab(median_rgb)[0], MC.lab(photo_rgb)[0]
    return abs(float(a[0] - b[0])) <= R['photo_dL'] and float(np.hypot(a[1] - b[1], a[2] - b[2])) <= R['photo_dab']


def effective(res: dict | None, photo_rgb, R: dict | None = None) -> str | None:
    """Вердикт для решений (карантин, сводка): `candidate`/`reject` снимается в `ok`, если серый верх совпадает с фото (настоящий серый товар)."""
    v = (res or {}).get('verdict')
    if v in BAD and photo_agrees((res or {}).get('median_rgb'), photo_rgb, R):
        return 'ok'
    return v


def photo_table() -> dict:
    """{sku: цвет фото товара} из таблицы сторожа цвета (`mesh-color/current.json`); нет файла — {} (судим без фото)."""
    try:
        T = json.load(open(os.path.join(os.path.expanduser(os.environ.get('MESH_COLOR_DIR') or '~/scout-scenes/catalog-assets/mesh-color'), 'current.json'), encoding='utf-8'))
        return {k: r['photo_rgb'] for k, r in T['rows'].items() if r.get('photo_rgb')}
    except (OSError, ValueError, KeyError):
        return {}


def verdict_of(cache: dict, glb: str) -> str | None:
    """Вердикт из кэша (None — не мерили / ошибка открытия)."""
    r = cache.get(_gkey(glb) or '')
    return r.get('verdict') if r else None


def digest_part(counts: dict) -> str:
    return (f'серая крышка (отдельно от цвета): отказ {counts.get("grey_top_reject", 0)}, на проверку {counts.get("grey_top_candidate", 0)}, '
            f'из них в ленте/наборах было {counts.get("grey_top_shown", 0)}')


# ---------- самопроверка (без trimesh) ----------

def _box(w=1.0, d=0.6, h=0.05, y0=0.7):
    """Столешница-плита: 8 вершин, верх и бока с РАЗНЫМИ UV-областями (как у нашего атласа)."""
    x0, x1, z0, z1, ya, yb = -w / 2, w / 2, -d / 2, d / 2, y0, y0 + h
    V, UV, F = [], [], []

    def quad(p, uv):
        i = len(V)
        V.extend(p)
        UV.extend(uv)
        F.extend([[i, i + 1, i + 2], [i, i + 2, i + 3]])
    quad([(x0, yb, z1), (x1, yb, z1), (x1, yb, z0), (x0, yb, z0)], [(0.05, 0.05), (0.60, 0.05), (0.60, 0.60), (0.05, 0.60)])        # верх, нормаль +Y
    quad([(x0, ya, z0), (x1, ya, z0), (x1, ya, z1), (x0, ya, z1)], [(0.05, 0.70), (0.60, 0.70), (0.60, 0.80), (0.05, 0.80)])        # низ
    quad([(x0, ya, z1), (x1, ya, z1), (x1, yb, z1), (x0, yb, z1)], [(0.65, 0.05), (0.95, 0.05), (0.95, 0.15), (0.65, 0.15)])        # бок
    quad([(x1, ya, z0), (x0, ya, z0), (x0, yb, z0), (x1, yb, z0)], [(0.65, 0.25), (0.95, 0.25), (0.95, 0.35), (0.65, 0.35)])
    return np.array(V), np.array(F), np.array(UV)


def _atlas(top_rgb, side_rgb, noise=0.0, size=256, seed=1):
    a = np.full((size, size, 3), 40, np.uint8)
    rng = np.random.default_rng(seed)
    t0, t1 = int(0.0 * size), int(0.65 * size)
    img = np.empty((size, size, 3), np.float32)
    img[:] = a
    y_top = slice(int(size * 0.35), int(size * 0.97))        # V 0.05..0.60 → строки сверху: (1-v)
    img[y_top, int(size * 0.0):int(size * 0.65)] = top_rgb
    img[int(size * 0.80):int(size * 0.97), int(size * 0.62):] = side_rgb      # бока: V 0.05..0.35 → строки 0.65..0.95
    img[int(size * 0.65):int(size * 0.75), int(size * 0.62):] = side_rgb
    if noise:
        img += rng.normal(0, noise, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def _selftest() -> int:
    import remlab_tmp  # временное селфтеста — на диске, не в /tmp (T-20261107-13)
    remlab_tmp.use('mesh_grey_top-selftest')
    bad = []

    def ok(name, cond):
        print(('OK   ' if cond else 'FAIL ') + name)
        if not cond:
            bad.append(name)
    R = {**rules(), 'min_area_px': 1000, 'min_edge_px': 20}
    V, F, UV = _box()
    mrg = np.full((256, 256, 3), 128, np.uint8)
    mro = np.full((256, 256, 3), (0, 200, 20), np.uint8)

    r = analyze_arrays(V, F, UV, _atlas((128, 128, 128), (150, 100, 40)), mrg, R)
    ok('пустой серый верх (128) + дубовая кромка + MR 0,5/0,5 → reject', r['verdict'] == 'reject' and r['grey_share'] >= 0.95 and r['edge_contrast'] >= R['edge_min'])
    r = analyze_arrays(V, F, UV, _atlas((128, 128, 128), (150, 100, 40)), mro, R)
    ok('то же, но MR не «фон» (настоящий материал) → не reject, но кандидат', r['verdict'] == 'candidate')
    r = analyze_arrays(V, F, UV, _atlas((128, 128, 128), (128, 128, 128)), mrg, R)
    ok('настоящий серый стол: кромка той же серости → не reject (кандидат на ручную проверку)', r['verdict'] == 'candidate')
    r = analyze_arrays(V, F, UV, _atlas((128, 128, 128), (128, 128, 128), noise=14), mro, R)
    ok('серая крышка с фактурой (бетон: σ 14, MR настоящий) → ok', r['verdict'] == 'ok')
    r = analyze_arrays(V, F, UV, _atlas((196, 150, 90), (150, 100, 40)), mrg, R)
    ok('дубовая крышка → ok', r['verdict'] == 'ok' and r['grey_share'] < 0.05)
    r = analyze_arrays(V, F, UV, _atlas((120, 120, 120), (150, 100, 40)), mrg, R)
    ok('серый 100 (за всеми окнами) → ok: граница держится', analyze_arrays(V, F, UV, _atlas((100, 100, 100), (150, 100, 40)), mrg, R)['verdict'] == 'ok')
    ok('gt-v3: серый 114 с MR 0,5/0,5 и плоский → candidate (mr-flat), с настоящим MR → ok',
       analyze_arrays(V, F, UV, _atlas((114, 114, 114), (150, 100, 40)), mrg, R)['verdict'] == 'candidate'
       and analyze_arrays(V, F, UV, _atlas((114, 114, 114), (150, 100, 40)), mro, R)['verdict'] == 'ok')
    r = analyze_arrays(V, F, UV, _atlas((134, 124, 129), (150, 100, 40)), mrg, R)
    ok('чистый фон 124/134 на краях окна — reject (чистая доля ≥ 95 %)', r['verdict'] == 'reject')
    r = analyze_arrays(V, F, UV, _atlas((122, 136, 129), (150, 100, 40)), mrg, R)
    ok('шумный фон 121–137 (шире чистого окна) — кандидат, но не reject', r['verdict'] == 'candidate' and r['pure_share'] < 0.5)
    # 85 % верха серые, остальное дерево → кандидат, не reject (доля < 95 %)
    a = _atlas((128, 128, 128), (150, 100, 40))
    a[160:185, :int(256 * 0.65)] = (196, 150, 90)       # полоса дерева ≈ 18 % верха (верх — строки 102…242)
    r = analyze_arrays(V, F, UV, a, mrg, R)
    ok('85 % серого верха → candidate (не reject)', r['verdict'] == 'candidate' and 0.8 <= r['grey_share'] < 0.95)
    # нет верхней поверхности: коробка вверх ногами (верх смотрит вниз) — горизонтальная плоскость есть, но «верха» нет
    Vd = V * np.array([1, -1, 1])
    r = analyze_arrays(Vd, F[:, [0, 2, 1]], UV, _atlas((128, 128, 128), (150, 100, 40)), mrg, R)
    ok('грани смотрят вниз → верх не серая крышка: вердикт зависит только от граней +Y (у перевёрнутой плиты это бывшее дно)', r['verdict'] in VERDICTS)
    Vs = V * np.array([0.04, 1, 0.04])
    ok('стойка (след крошечный, плита — вся модель) считается как верх; предмет без горизонтали — na',
       analyze_arrays(Vs, F, UV, _atlas((128, 128, 128), (150, 100, 40)), mrg, {**R, 'min_area_px': 10})['verdict'] in VERDICTS
       and analyze_arrays(V * [1, 1, 1], F[:0], UV, _atlas((128, 128, 128), (150, 100, 40)), mrg, R)['verdict'] == 'na')
    # ---- дыры на любой поверхности (расширение 18.11): верх нормальный, дыра на боку / предмет без верха
    r = analyze_arrays(V, F, UV, _atlas((196, 150, 90), (128, 128, 128)), mrg, R)
    ok('верх дубовый, оба бока пустой серый → reject по поверхностям, верх ok, где — вертикали',
       r['verdict'] == 'reject' and r['top_verdict'] == 'ok' and set(r['where']) >= {'вертикаль+z', 'вертикаль-z'})
    ok('поверхности: роль, площадь, связная дыра и доля — числами', all(x['hole_share'] >= 0.9 and x['hole_px'] > 1000 for x in r['surfaces'] if x['role'].startswith('вертикаль')))
    Vr = np.stack([V[:, 0], -V[:, 2], V[:, 1]], axis=1)        # поворот на 90° вокруг X: бывший верх смотрит вперёд (+Z), горизонтали нет
    r = analyze_arrays(Vr, F, UV, _atlas((128, 128, 128), (150, 100, 40)), mrg, R)
    ok('предмет без верха (спинка, фасад): дыра на вертикали ловится, раньше было na',
       r['top_verdict'] != 'reject' and r['verdict'] == 'reject' and 'вертикаль+z' in r['where'])
    r = analyze_arrays(Vr, F, UV, _atlas((196, 150, 90), (150, 100, 40)), mrg, R)
    ok('предмет без верха, всё окрашено → ok (не na)', r['verdict'] == 'ok' and r['where'] == [])
    r = analyze_arrays(Vr, F, UV, _atlas((128, 128, 128), (150, 100, 40)), mro, R)
    ok('на вертикали серое, но MR настоящий → кандидат, не reject', r['verdict'] == 'candidate')
    r = analyze_arrays(V, F, UV, _atlas((245, 245, 245), (150, 100, 40)), mrg, R)
    ok('светлое пятно: однотонный верх ≥ 230 → bright_flat; дубовый — нет', r['bright_flat'] and r['bright_share'] > 0.3
       and not analyze_arrays(V, F, UV, _atlas((196, 150, 90), (150, 100, 40)), mrg, R)['bright_flat'])
    m = np.zeros((20, 20), bool)
    m[1:4, 1:4] = True
    m[10:19, 10:19] = True
    m[5, 5] = True
    ok('_label_largest: крупнейшая связная область 81 (8-соседей не склеивает)', _label_largest(m) == 81)
    ok('роль граней: верх/сиденье/низ/вертикаль', set(face_roles(V, F, R).tolist()) == {'верх', 'низ', 'вертикаль+z', 'вертикаль-z'})
    # слишком мало текселей
    r = analyze_arrays(V, F, UV, _atlas((128, 128, 128), (150, 100, 40), size=32), mrg[:32, :32], {**R, 'min_area_px': 10 ** 6})
    ok('верх меньше min_area_px → na', r['verdict'] == 'na')
    # швы: верх и бок делят текселы — общие тексели не считаются
    UVs = UV.copy()
    UVs[16:] = UVs[:16].mean(0)          # неправильная раскладка: не должна падать
    ok('вырожденные UV не роняют ядро', analyze_arrays(V, F, UVs, _atlas((128, 128, 128), (150, 100, 40)), mrg, R)['verdict'] in VERDICTS)
    ok('эрозия: квадрат 5×5 с k=1 → 3×3', int(_erode(np.pad(np.ones((5, 5), bool), 2), 1).sum()) == 9)
    # правила: версия и порядок порогов
    ok('правила: candidate ≤ reject по доле, окно 124–134, версия есть', R['candidate_share'] <= R['reject_share'] and (R['pure_lo'], R['pure_hi']) == (124, 134) and (R['grey_lo'], R['grey_hi']) == (117, 141) and R['version'])
    # кэш: ключ зависит от версии правил и mtime
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, 'm.glb')
    open(p, 'wb').write(b'x')
    cache = {}
    ok('кэш: нет записи → нет вердикта; запись → вердикт', verdict_of(cache, p) is None and (cache.__setitem__(_gkey(p), {'verdict': 'reject'}) or verdict_of(cache, p) == 'reject')
       and _gkey(p).endswith(rules()['version']))
    ok('photo_agrees: серый верх 130 и серое фото 128 — совпало; фото чёрное (75) или дубовое — нет; нет фото — нет',
       photo_agrees([130, 130, 130], [128, 128, 128], R) and not photo_agrees([130, 130, 130], [75, 76, 80], R)
       and not photo_agrees([130, 130, 130], [196, 150, 90], R) and not photo_agrees([130, 130, 130], None, R))
    ok('effective: candidate у серого по фото товара → ok; reject у чёрного → reject; ok/na не трогаем',
       effective({'verdict': 'candidate', 'median_rgb': [130, 130, 130]}, [126, 126, 128], R) == 'ok'
       and effective({'verdict': 'reject', 'median_rgb': [130, 130, 130]}, [75, 76, 80], R) == 'reject'
       and effective({'verdict': 'ok', 'median_rgb': [130, 130, 130]}, [75, 76, 80], R) == 'ok' and effective(None, [1, 1, 1], R) is None)
    ok('digest: числа в строке', 'отказ 3' in digest_part({'grey_top_reject': 3, 'grey_top_candidate': 5, 'grey_top_shown': 2}))
    print('итог:', 'чисто' if not bad else f'ПРОВАЛЕНО {len(bad)}')
    return 1 if bad else 0


def own_glbs() -> dict:
    """{sku: последний model.glb} по собственным мешам (таблица сторожа цвета: не `via_family`) — для калибровки и разовых замеров."""
    import glob
    T = json.load(open(os.path.expanduser('~/scout-scenes/catalog-assets/mesh-color/current.json'), encoding='utf-8'))
    out = {}
    for sku, r in sorted(T['rows'].items()):
        if r.get('via_family'):
            continue
        ks = sorted(glob.glob(os.path.expanduser(f'~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2/{sku.replace(":", "_")}/*/model.glb')), key=os.path.getmtime)
        if ks:
            out[sku] = ks[-1]
    return out


def scan(out_jsonl: str, workers: int = 3, only: set | None = None) -> int:
    """Перепись собственных мешей всех ролей → JSON-строки {sku, res | error}; уже замеренные в файле пропускаются (можно продолжать).
    Дальше — калибровка и таблица «роль → сколько мешей с дырой и где» (сверка с `top_scan.tsv` рабочего 4 и видом сверху)."""
    done = set()
    if os.path.exists(out_jsonl):
        done = {json.loads(ln)['sku'] for ln in open(out_jsonl, encoding='utf-8') if ln.strip()}
    paths = {k: v for k, v in own_glbs().items() if (not only or k in only) and k not in done}
    inv = {v: k for k, v in paths.items()}
    with open(out_jsonl, 'a', encoding='utf-8') as f:
        for i, (g, res, err) in enumerate(run_batches(list(paths.values()), workers), 1):
            f.write(json.dumps({'sku': inv[g], 'res': res, 'error': err}, ensure_ascii=False) + '\n')
            if i % 100 == 0:
                f.flush()
                print(f'  {i}/{len(paths)}', flush=True)
    return 0


def main(argv: list) -> int:
    if '--selftest' in argv:
        return _selftest()
    if argv and argv[0] == '--scan':
        only = {ln.strip() for ln in open(argv[2], encoding='utf-8')} if len(argv) > 2 else None      # файл со списком sku (по строке)
        return scan(argv[1], 2, only)
    for g in argv:
        print(g, json.dumps(analyze(g), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
