#!/usr/bin/env python3
"""МЕРКА ПЯТЕН ПОКРАСКИ, НЕЗАВИСИМАЯ ОТ ПРАВКИ (T-20261125-92; совет Fable 25.11 16:05: мерку и правку делают разные исполнители). ОТЧЁТНАЯ (report_only): товар не меняет, ничего не чистит.

Три состояния (урок 969, ADR-0479 п.2): «чисто» / «брак» / «не наблюдаемо». Кадр камеры 04 делится на НАДЁЖНОЕ (фото честно отвечает: cos ≥ cos_min, не у края силуэта, не у перекрытия) и НЕНАДЁЖНОЕ.
Доля ненадёжного — первая строка отчёта: что вне проверки по фото, «чисто» там не значит.

Класс 1 «пятно против фото» (надёжное). Альбедо 08 (плоское, без света) кладётся в кадр камеры (растр «грань+UV на пиксель», `tex_visible.frame_from_tex`), фото — в тот же кадр (`photo_to_frame`). Контраст места = ΔE(Lab)
между цветом в точке (мелкое размытие) и окружением (шире) внутри своей группы (часть × цвет фото, k-means k=2). Избыток = контраст альбедо − макс. контраст фото в окрестности `tolerance_px`. Балл = избыток / разброс фото
группы (1,4826·MAD, пол `sigma_floor`): порог `k` — в единицах разброса фото, не в L и не в ΔE.
Класс 3 «граница групп» — места класса 1, где альбедо ближе к цвету ДРУГОЙ группы части, чем фото (белая подкладка столешницы на фото — дерево в альбедо): рассовмещение/граница, не пятно; считается отдельно и в «брак» не входит.
Класс 2 «деталь на ненадёжном». Там фото не судья, но по правилу тон группы должен быть РОВНЫМ. Контраст места к окружению в одном альбедо (без фото) — против разброса альбедо ТОЙ ЖЕ группы на надёжных текселях
(группа ненадёжного пикселя — часть × ближайший по альбедо цвет групп части). Избыток ≥ k и ≥ min_area_px → «деталь на ненадёжном».
Вердикт: «брак» — есть место класса 1 или 2 с баллом ≥ k и площадью ≥ min_area_px; «на грани» — лучшее в пределах `edge_frac` (20 %) от порога снизу; иначе «чисто» (для надёжного).
Выход: `spots.json` (доли, распределения, по 5 мест каждого класса), `worst-N.png` (класс 1), `unrel-N.png` (класс 2), `bound-N.png` (класс 3) — «фото | альбедо», `overview.png`, `overlay.png` (классы цветом).
Пороги — `rules/paint-spots.json`. ID товаров в код не попадают.

  python paint_spots.py <material.glb> <photo.rgba.png> <pose_run> <out_dir> [parts08.npz]
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [_HERE]
NOGRP = -(1 << 20)


def _rules() -> dict:
    for p in (os.path.join(_HERE, '..', '..', 'rules', 'paint-spots.json'), os.path.join(_HERE, 'paint-spots.json')):
        if os.path.exists(p):
            return json.load(open(p, encoding='utf-8'))
    raise FileNotFoundError('rules/paint-spots.json не найден')


R = _rules()


def _lab(rgb8: np.ndarray) -> np.ndarray:
    import cv2
    return cv2.cvtColor(rgb8.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)


def _blur_norm(x: np.ndarray, w: np.ndarray, sigma: float) -> np.ndarray:
    """Нормированная свёртка: среднее x по пикселям с весом w (0/1) в гауссовом окне — только по «своим» пикселям."""
    import cv2
    num = cv2.GaussianBlur((x * w[..., None]).astype(np.float32), (0, 0), sigma)
    den = cv2.GaussianBlur(w.astype(np.float32), (0, 0), sigma)
    return num / np.maximum(den[..., None], 1e-4)


def contrast_map(lab: np.ndarray, grp: np.ndarray, valid: np.ndarray, c_sigma: float, s_sigma: float) -> np.ndarray:
    """Контраст места к окружению: ΔE(Lab) между мелким и широким размытием внутри своей группы. Вне valid — 0."""
    out = np.zeros(valid.shape, np.float32)
    for g in np.unique(grp[valid]):
        w = (valid & (grp == g)).astype(np.float32)
        c = _blur_norm(lab, w, c_sigma)
        s = _blur_norm(lab, w, s_sigma)
        d = np.sqrt(((c - s) ** 2).sum(-1))
        out = np.where(w > 0, d, out)
    return out


def split_by_color_ex(lp: np.ndarray, grp: np.ndarray, valid: np.ndarray, c: dict) -> tuple[np.ndarray, dict]:
    """Делит часть на два цвета по ФОТО (k-means, k=2, фиксированное зерно), если центры разнесены больше `split_de` (ΔE) и в каждом ≥ `min_part_px` пикселей. Номер группы = часть·4 + цвет (0/1).
    Возвращает (группы; вне valid — NOGRP) и центры {часть: (центр0, центр1)} разделённых частей (в Lab фото)."""
    import cv2
    out = np.full(grp.shape, NOGRP, np.int32)
    ctrs = {}
    for g in np.unique(grp[valid]):
        m = valid & (grp == g)
        out[m] = int(g) * 4
        X = lp[m].astype(np.float32)
        if len(X) < 2 * int(c['min_part_px']):
            continue
        cv2.setRNGSeed(0)
        sub = np.ascontiguousarray(X[::7])
        _, _, ctr = cv2.kmeans(sub, 2, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5), 3, cv2.KMEANS_PP_CENTERS)
        if float(np.sqrt(((ctr[0] - ctr[1]) ** 2).sum())) < float(c['split_de']):
            continue
        lab = (((X - ctr[1]) ** 2).sum(1) < ((X - ctr[0]) ** 2).sum(1)).astype(np.int32)       # 1 — ближе ко второму центру
        if min(int(lab.sum()), int(len(lab) - lab.sum())) < int(c['min_part_px']):
            continue
        out[m] = int(g) * 4 + lab
        ctrs[int(g)] = (ctr[0].copy(), ctr[1].copy())
    return out, ctrs


def split_by_color(lp: np.ndarray, grp: np.ndarray, valid: np.ndarray, c: dict) -> np.ndarray:
    return split_by_color_ex(lp, grp, valid, c)[0]


def group_name(gid: int) -> str:
    return f'{gid // 4}.{gid % 4}'


def _dilate_max(x: np.ndarray, r: int) -> np.ndarray:
    import cv2
    if r <= 0:
        return x
    return cv2.dilate(x, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))


def robust_sigma(x: np.ndarray, floor: float) -> tuple[float, float]:
    med = float(np.median(x))
    return med, max(1.4826 * float(np.median(np.abs(x - med))), floor)


def _blobs(zs: np.ndarray, thr: float, min_px: int, G: np.ndarray, ca: np.ndarray, cp: np.ndarray | None, mism: np.ndarray | None) -> list:
    """Связные места, где сглаженный балл ≥ thr и площадь ≥ min_px; по убыванию пика."""
    from scipy import ndimage as ndi
    lab, n = ndi.label(zs >= thr)
    out = []
    for i in range(1, n + 1):
        m = lab == i
        area = int(m.sum())
        if area < min_px:
            continue
        ys, xs = np.nonzero(m)
        gv, gn = np.unique(G[m], return_counts=True)
        s = {'peak_z': round(float(zs[m].max()), 2), 'area_px': area, 'part': group_name(int(gv[gn.argmax()])), 'bbox': [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
             'albedo_dE': round(float(ca[m].max()), 2)}
        if cp is not None:
            s['photo_dE'] = round(float(cp[m].mean()), 2)
        if mism is not None:
            core = m & (zs >= 0.5 * s['peak_z'])                 # ядро места (halo размытия вокруг пятна не считаем): доля пикселей, где альбедо ближе к другой группе, чем фото
            s['group_mismatch_share'] = round(float(mism[core].mean()), 3)
        out.append(s)
    out.sort(key=lambda s: -s['peak_z'])
    return out


def _verdict(spots: list, k: float, c: dict) -> tuple[list, list]:
    bad = [s for s in spots if s['peak_z'] >= k and s['area_px'] >= c['min_area_px']]
    lo = k * (1 - float(c['edge_frac']))
    edge = [s for s in spots if s not in bad and (s['peak_z'] >= lo or (s['peak_z'] >= k and s['area_px'] < c['min_area_px']))]
    return bad, edge


def measure(A: np.ndarray, Pf: np.ndarray, valid: np.ndarray, grp: np.ndarray, cfg: dict | None = None, vis: np.ndarray | None = None) -> dict:
    """Ядро мерки на кадрах одного размера: A — альбедо в кадре камеры, Pf — фото в том же кадре, valid — НАДЁЖНО (фото честно), vis — всё, что видит камера (vis ⊇ valid; None — класса 2 нет), grp — метка части на пиксель
    (для vis). Чистая функция (тесты на заглушках)."""
    import cv2
    c = dict(R)
    c.update(cfg or {})
    k = float(c['k'])
    la, lp = _lab(A), _lab(Pf)
    G, ctrs = split_by_color_ex(lp, grp, valid, c)      # группа = часть × цвет ФОТО: метка части может смешивать белую столешницу и дерево — один разброс на двоих завышает порог
    ca = contrast_map(la, G, valid, c['center_sigma'], c['surround_sigma'])
    cp = contrast_map(lp, G, valid, c['center_sigma'], c['surround_sigma'])
    cp_loc = _dilate_max(cp, int(c['tolerance_px']))
    exc = np.where(valid, ca - cp_loc, 0.0).astype(np.float32)
    z = np.zeros(valid.shape, np.float32)
    parts = {}
    for g in np.unique(G[valid]):
        m = valid & (G == g)
        if m.sum() < c['min_part_px']:
            continue
        med, sg = robust_sigma(cp[m], c['sigma_floor'])
        z[m] = exc[m] / sg
        zz = z[m]
        parts[group_name(int(g))] = {'px': int(m.sum()), 'sigma_photo': round(sg, 3), 'median_photo_contrast': round(med, 3),
                                     'z_q50': round(float(np.quantile(zz, 0.5)), 3), 'z_q90': round(float(np.quantile(zz, 0.9)), 3),
                                     'z_q99': round(float(np.quantile(zz, 0.99)), 3), 'z_max': round(float(zz.max()), 3)}
    zs = cv2.GaussianBlur(z, (0, 0), float(c['peak_sigma']))        # пик балла — по сглаженному (одиночный пиксель — не пятно)
    # альбедо ближе к цвету другой группы части, чем фото → «граница групп»
    mism = np.zeros(valid.shape, bool)
    for p, (c0, c1) in ctrs.items():
        m = valid & (grp == p)
        d0 = ((la[m] - c0) ** 2).sum(1)
        d1 = ((la[m] - c1) ** 2).sum(1)
        mism[m] = (d1 < d0).astype(np.int32) != (G[m] - p * 4)
    allspots = _blobs(zs, float(c['list_frac']) * k, int(c['list_min_px']), G, ca, cp_loc, mism)
    bshare = float(c['boundary_share'])
    spots = [s for s in allspots if s['group_mismatch_share'] < bshare]
    bound = [s for s in allspots if s['group_mismatch_share'] >= bshare]
    bad1, edge1 = _verdict(spots, k, c)
    nj = int(c['json_top'])
    res = {'k': k, 'parts': parts, 'spots': spots[:nj], 'spots_boundary': bound[:nj], 'n_bad': len(bad1), 'n_edge': len(edge1), 'n_boundary': len([s for s in bound if s['peak_z'] >= k]),
           'valid_px': int(valid.sum()), 'worst_z': spots[0]['peak_z'] if spots else 0.0}
    maps = {'z': zs, 'ca': ca, 'cp': cp, 'mism': mism}
    # класс 2: деталь на ненадёжном (альбедо против альбедо своей группы на надёжных текселях, без фото)
    bad2, edge2, spots2 = [], [], []
    res['vis_px'] = int((vis if vis is not None else valid).sum())
    if vis is not None:
        from scipy.ndimage import binary_erosion as _be
        vis_in = _be(vis, iterations=int(c['unrel_edge_px']))   # у самого края силуэта окружение (нормированная свёртка) считается по малому числу соседей и шумит — хвост шума давал бы ложную «деталь»
        unrel = vis_in & ~valid
        res['unreliable_px'] = int((vis & ~valid).sum())
        res['unreliable_measured_px'] = int(unrel.sum())
        G2 = G.copy()
        mu = {int(g): la[valid & (G == g)].mean(0) for g in np.unique(G[valid])}
        for p in np.unique(grp[unrel]):
            m = unrel & (grp == p)
            cand = [g for g in mu if g // 4 == int(p)]
            if not cand:
                continue
            if len(cand) == 1:
                G2[m] = cand[0]
            else:
                d = np.stack([((la[m] - mu[g]) ** 2).sum(1) for g in cand], 1)
                G2[m] = np.asarray(cand)[d.argmin(1)]
        vis2 = valid | (unrel & (G2 != NOGRP))
        caU = contrast_map(la, G2, vis2, c['center_sigma'], c['surround_sigma'])
        zu = np.zeros(valid.shape, np.float32)
        stats2 = {}
        for g in np.unique(G2[vis2]):
            rel = valid & (G2 == g)
            un = unrel & vis2 & (G2 == g)
            if rel.sum() < c['min_part_px'] or not un.any():
                continue
            med, sg = robust_sigma(caU[rel], float(c['sigma_floor_albedo']))
            zc = (caU[un] - med) / sg                      # (а) контраст места к окружению: границы пятна, полосы
            # (б) отклонение ТОНА места от типичного тона группы на надёжном: крупное ровное пятно другого тона (контрастом видна лишь его кромка)
            # только если надёжная выборка группы представительна (доля ≥ tone_min_share): у столешницы надёжны лишь кромки, её верх — другая поверхность, эталона тона нет → «не наблюдаемо», а не «чисто»
            rshare = float(rel.sum()) / float(rel.sum() + un.sum())
            tone_ok = rshare >= float(c['tone_min_share'])
            zu[un] = zc
            if tone_ok:
                w = (vis2 & (G2 == g)).astype(np.float32)
                ls = _blur_norm(la, w, float(c['tone_sigma']))
                tone = np.median(la[rel], axis=0)
                dev = np.sqrt(((ls - tone) ** 2).sum(-1))
                dmed, dsg = robust_sigma(dev[rel], float(c['sigma_floor_tone']))
                zu[un] = np.maximum(zc, (dev[un] - dmed) / dsg)
            stats2[group_name(int(g))] = {'px_reliable': int(rel.sum()), 'px_unreliable': int(un.sum()), 'sigma_albedo': round(sg, 3), 'median_albedo_contrast': round(med, 3),
                                          'reliable_share': round(rshare, 3), 'tone_checked': bool(tone_ok),
                                          **({'sigma_tone': round(dsg, 3), 'median_tone_dev': round(dmed, 3)} if tone_ok else {}),
                                          'z_q99': round(float(np.quantile(zu[un], 0.99)), 3), 'z_max': round(float(zu[un].max()), 3)}
        zus = cv2.GaussianBlur(zu, (0, 0), float(c['peak_sigma']))
        zus = np.where(unrel, zus, 0).astype(np.float32)
        # стык частей: место класса 2 у границы двух частей (белый низ столешницы / дерево) — рассовмещение, а не деталь: уходит в «граница групп»
        pe = np.zeros(valid.shape, np.uint8)
        for dy, dx in ((0, 1), (1, 0)):
            a_, b_ = G2[:G2.shape[0] - dy, :G2.shape[1] - dx], G2[dy:, dx:]
            d_ = (a_ != b_) & vis2[:G2.shape[0] - dy, :G2.shape[1] - dx] & vis2[dy:, dx:]
            pe[:G2.shape[0] - dy, :G2.shape[1] - dx] |= d_
            pe[dy:, dx:] |= d_
        near = cv2.dilate(pe, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * int(c['part_join_px']) + 1,) * 2)) > 0
        all2 = _blobs(zus, float(c['list_frac']) * k, int(c['list_min_px']), G2, caU, None, near)
        spots2 = [s for s in all2 if s['group_mismatch_share'] < bshare]
        bound2 = [s for s in all2 if s['group_mismatch_share'] >= bshare]
        for s in bound2:
            s['where'] = 'стык частей (класс 2)'
        bound = sorted(bound + bound2, key=lambda s: -s['peak_z'])
        res['spots_boundary'] = bound[:nj]
        res['n_boundary'] = len([s for s in bound if s['peak_z'] >= k])
        bad2, edge2 = _verdict(spots2, k, c)
        res.update({'spots_unreliable': spots2[:nj], 'n_bad_unreliable': len(bad2), 'n_edge_unreliable': len(edge2), 'unreliable_groups': stats2,
                    'worst_z_unreliable': spots2[0]['peak_z'] if spots2 else 0.0})
        maps['zu'] = zus
        maps['unrel'] = unrel
    res['verdict'] = 'брак' if (bad1 or bad2) else ('на грани' if (edge1 or edge2) else 'чисто')
    res['maps'] = maps
    return res


def _depth_band(st: dict, rel: float, px: int) -> np.ndarray:
    """Полоса у перекрытия: скачок глубины между соседними пикселями силуэта больше `rel` размаха глубины, расширенный на `px`."""
    import cv2
    d = np.asarray(st['depth'], np.float32)
    m = st['mask']
    if not m.any():
        return np.zeros(m.shape, bool)
    span = float(d[m].max() - d[m].min())
    jump = np.zeros(m.shape, bool)
    for dy, dx in ((0, 1), (1, 0)):
        a, b = d[:d.shape[0] - dy, :d.shape[1] - dx], d[dy:, dx:]
        ma, mb = m[:d.shape[0] - dy, :d.shape[1] - dx], m[dy:, dx:]
        j = ma & mb & (np.abs(a - b) > rel * max(span, 1e-9))
        jump[:d.shape[0] - dy, :d.shape[1] - dx] |= j
        jump[dy:, dx:] |= j
    return cv2.dilate(jump.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * px + 1, 2 * px + 1))) > 0


def _crop_row(Pf, A, bbox, pad, scale, text, mark=(255, 0, 0)):
    import cv2
    x0, y0, x1, y1 = bbox
    a, b, cc, d = max(x0 - pad, 0), max(y0 - pad, 0), min(x1 + pad + 1, A.shape[1]), min(y1 + pad + 1, A.shape[0])
    tile = []
    for im in (Pf, A):
        t = im[b:d, a:cc].copy()
        cv2.rectangle(t, (x0 - a, y0 - b), (x1 - a, y1 - b), mark, 1)
        tile.append(t)
    row = np.concatenate([tile[0], np.full((tile[0].shape[0], 4, 3), 255, np.uint8), tile[1]], axis=1)
    row = cv2.resize(row, (row.shape[1] * scale, row.shape[0] * scale), interpolation=cv2.INTER_NEAREST)
    cv2.putText(row, text, (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    return row


def run(glb: str, photo_png: str, pose_run: str, out_dir: str, parts_npz: str | None = None, cfg: dict | None = None) -> dict:
    import cv2
    import tex_visible as TV
    from scipy.ndimage import binary_erosion
    os.makedirs(out_dir, exist_ok=True)
    c = dict(R)
    c.update(cfg or {})
    geoms = TV.load_shape(glb)
    st = TV.load_stage(pose_run)
    photo = np.asarray(Image.open(photo_png).convert('RGBA'), np.uint8)
    Pf, pm = TV.photo_to_frame(photo, st['P'], st['px'])
    A = TV.frame_from_tex(st, geoms, [g['tex'] for g in geoms])
    vis = st['mask'].copy()
    band = TV.depth_band(st)             # полоса у разрыва глубины/перекрытия — тем же правилом, что в этапе 6 (глубина шумная: шаг по пикселю считается с поправкой на наклон)
    valid = binary_erosion(vis & pm, iterations=int(c['erode_px'])) & (st['cos'] >= float(c['cos_min'])) & ~band
    ids = st['ids']
    if parts_npz and os.path.exists(parts_npz):
        part_f = np.load(parts_npz)['part'].astype(np.int32)
        grp = np.where(ids >= 0, part_f[np.clip(ids, 0, len(part_f) - 1)], -1).astype(np.int32)
    else:
        grp = np.zeros(ids.shape, np.int32)
    res = measure(A, Pf, valid, grp, cfg, vis=vis)
    maps = res.pop('maps')
    n_vis = max(int(vis.sum()), 1)
    res['coverage'] = {'frame_px': int(vis.sum()), 'valid_share': round(float(valid.sum()) / n_vis, 4), 'unreliable_share': round(float((vis & ~valid).sum()) / n_vis, 4),
                       'note': 'надёжное = камера фото видит честно (cos ≥ cos_min, не у края силуэта, не у перекрытия). Ненадёжное по фото НЕ проверяется («не наблюдаемо» ≠ «чисто»): там — класс 2 (деталь на ненадёжном, без фото); '
                               'невидимое камерой (зад, боковые грани) мерка не видит вовсе'}
    res['inputs'] = {'glb': glb, 'photo': photo_png, 'pose_run': pose_run, 'parts': parts_npz}
    if c.get('dump_npz'):                    # маленькая фикстура для тестов: A — на всём видимом, Pf — только на надёжном
        np.savez_compressed(c['dump_npz'], A=np.where(vis[..., None], A, 0).astype(np.uint8), Pf=np.where(valid[..., None], Pf, 0).astype(np.uint8), valid=valid, vis=vis,
                            grp=np.where(vis, grp, -1).astype(np.int16))
    np.save(os.path.join(out_dir, 'z.npy'), maps['z'].astype(np.float16))
    pad, sc = int(c['crop_pad_px']), max(1, int(c['crop_scale']))
    for key, pref, col, lab in (('spots', 'worst', (255, 0, 0), 'пятно против фото'), ('spots_unreliable', 'unrel', (255, 0, 255), 'деталь на ненадёжном'), ('spots_boundary', 'bound', (0, 160, 255), 'граница групп')):
        for i, s in enumerate(res.get(key, [])[:int(c['crops_top'])], 1):
            row = _crop_row(Pf, A, s['bbox'], pad, sc, f"{lab} #{i} гр {s['part']} z={s['peak_z']} площадь={s['area_px']}  фото | альбедо", col)
            Image.fromarray(row).save(os.path.join(out_dir, f'{pref}-{i}.png'))
    zi = np.clip(maps['z'] / max(float(c['k']) * 2, 1e-6), 0, 1)
    heat = cv2.applyColorMap((zi * 255).astype(np.uint8), cv2.COLORMAP_INFERNO)[..., ::-1]
    heat = np.where(valid[..., None], heat, 255).astype(np.uint8)
    Image.fromarray(np.concatenate([Pf, A, heat], axis=1)).save(os.path.join(out_dir, 'overview.png'))
    ov = np.where(vis[..., None], (A.astype(np.float32) * 0.55 + 255 * 0.45), 255).astype(np.uint8)          # классы цветом поверх бледного альбедо: серая вуаль — ненадёжное, красное — пятно, пурпур — деталь на ненадёжном, голубое — граница групп
    ov[vis & ~valid] = (ov[vis & ~valid] * 0.6 + 120 * 0.4).astype(np.uint8)
    k = float(c['k'])
    ov[maps['z'] >= k] = (255, 0, 0)
    if 'zu' in maps:
        ov[maps['zu'] >= k] = (255, 0, 255)
    ov[(maps['mism']) & (maps['z'] >= k)] = (0, 160, 255)
    Image.fromarray(ov).save(os.path.join(out_dir, 'overlay.png'))
    json.dump(res, open(os.path.join(out_dir, 'spots.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return res


if __name__ == '__main__':
    if len(sys.argv) < 5:
        print(__doc__)
        sys.exit(2)
    r = run(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else None)
    print(f"надёжное {r['coverage']['valid_share']:.0%} / ненадёжное {r['coverage']['unreliable_share']:.0%} кадра")
    print(json.dumps({k: r.get(k) for k in ('verdict', 'k', 'worst_z', 'n_bad', 'n_edge', 'n_boundary', 'worst_z_unreliable', 'n_bad_unreliable', 'spots', 'spots_unreliable', 'spots_boundary')}, ensure_ascii=False))
