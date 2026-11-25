#!/usr/bin/env python3
"""МЕРКА ПЯТЕН ПОКРАСКИ, НЕЗАВИСИМАЯ ОТ ПРАВКИ (T-20261125-92; совет Fable 25.11 16:05: мерку и правку делают разные исполнители). ОТЧЁТНАЯ (report_only): товар не меняет, ничего не чистит.

Идея. Пятно покраски — место, где в ПЛОСКОЙ текстуре (альбедо этапа 08, без света) цвет резко отличается от своего окружения, а в ТОЙ ЖЕ точке фото такого контраста нет. Точку к точке даёт камера этапа 4:
растр `render_view0` (грань + UV на каждый пиксель кадра) → цвет альбедо в этом пикселе, фото — в тот же кадр по матрице P (`tex_visible.photo_to_frame`). Свет не участвует ни там, ни там: у альбедо его нет, а
контраст фото берётся ТОЛЬКО как ориентир «сколько неровности честно бывает у этой части на фото».
Контраст места = ΔE(Lab) между цветом в точке (мелкое размытие) и цветом окружения (то же, шире) — окружение считается только внутри своей части (метки `parts08.npz`) и только по видимым пикселям.
Избыток = контраст альбедо − (макс. по малой окрестности) контраст фото (окрестность гасит сдвиг на пиксель-два между камерой и фото). Балл места = избыток в единицах РАЗБРОСА ФОТО ЭТОЙ ЧАСТИ
(1,4826·MAD контраста фото по её видимым пикселям, не меньше `sigma_floor`): порог `k` — в этих единицах, не в L и не в ΔE. Подогнать его под один стол нельзя: у «гладкой» части (белая столешница) разброс мал,
порог в ΔE мал; у «узорной» (дерево) — велик.
Вердикт: «брак» — есть место с баллом ≥ k и площадью ≥ min_area_px; «на грани» — лучшее место в пределах `edge_frac` (20 %) от порога снизу, или площадь чуть ниже; иначе «чисто». Не видит камера фото — не видим (доля — в json).
Выход: `spots.json` (распределение баллов по частям, 5 худших мест на часть и всего, вердикт), `worst-N.png` («фото | рендер альбедо», рамка места), `overview.png` (фото | альбедо | карта балла).
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
    """Нормированная свёртка: среднее x по взвешенным пикселям w (0/1) в гауссовом окне — только по «своим» пикселям."""
    import cv2
    num = cv2.GaussianBlur((x * w[..., None]).astype(np.float32), (0, 0), sigma)
    den = cv2.GaussianBlur(w.astype(np.float32), (0, 0), sigma)
    return num / np.maximum(den[..., None], 1e-4)


def contrast_map(lab: np.ndarray, grp: np.ndarray, valid: np.ndarray, c_sigma: float, s_sigma: float) -> np.ndarray:
    """Контраст места к окружению: ΔE(Lab) между мелким и широким размытием внутри своей части. Вне valid — 0."""
    out = np.zeros(valid.shape, np.float32)
    for g in np.unique(grp[valid]):
        w = (valid & (grp == g)).astype(np.float32)
        c = _blur_norm(lab, w, c_sigma)
        s = _blur_norm(lab, w, s_sigma)
        d = np.sqrt(((c - s) ** 2).sum(-1))
        out = np.where(w > 0, d, out)
    return out


def split_by_color(lp: np.ndarray, grp: np.ndarray, valid: np.ndarray, c: dict) -> np.ndarray:
    """Разбивает часть на два цвета по ФОТО (k-means, k=2, фиксированное зерно), если центры разнесены больше `split_de` (ΔE) и в каждом ≥ `min_part_px` пикселей. Номер группы = часть·4 + цвет (0/1)."""
    import cv2
    out = np.full(grp.shape, -(1 << 20), np.int32)
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
    return out


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


def measure(A: np.ndarray, Pf: np.ndarray, valid: np.ndarray, grp: np.ndarray, cfg: dict | None = None) -> dict:
    """Ядро мерки на двух кадрах одного размера: A — альбедо в кадре камеры, Pf — фото в том же кадре, valid — где обе картинки честны, grp — метка части на пиксель. Чистая функция (тесты на заглушках)."""
    import cv2
    from scipy import ndimage as ndi
    c = dict(R)
    c.update(cfg or {})
    la, lp = _lab(A), _lab(Pf)
    grp = split_by_color(lp, grp, valid, c)          # группа = часть × цвет ФОТО: метка части может смешивать белую столешницу и дерево — один разброс на двоих завышает порог
    ca = contrast_map(la, grp, valid, c['center_sigma'], c['surround_sigma'])
    cp = contrast_map(lp, grp, valid, c['center_sigma'], c['surround_sigma'])
    cp_loc = _dilate_max(cp, int(c['tolerance_px']))
    exc = np.where(valid, ca - cp_loc, 0.0).astype(np.float32)
    z = np.zeros(valid.shape, np.float32)
    parts = {}
    for g in np.unique(grp[valid]):
        m = valid & (grp == g)
        if m.sum() < c['min_part_px']:
            continue
        med, sg = robust_sigma(cp[m], c['sigma_floor'])
        z[m] = exc[m] / sg
        zz = z[m]
        parts[group_name(int(g))] = {'px': int(m.sum()), 'sigma_photo': round(sg, 3), 'median_photo_contrast': round(med, 3),
                         'z_q50': round(float(np.quantile(zz, 0.5)), 3), 'z_q90': round(float(np.quantile(zz, 0.9)), 3),
                         'z_q99': round(float(np.quantile(zz, 0.99)), 3), 'z_max': round(float(zz.max()), 3)}
    zs = cv2.GaussianBlur(z, (0, 0), float(c['peak_sigma']))        # пик балла — по сглаженному (одиночный пиксель — не пятно)
    k = float(c['k'])
    lab_map, n = ndi.label(zs >= float(c['list_frac']) * k)
    spots = []
    for i in range(1, n + 1):
        m = lab_map == i
        area = int(m.sum())
        if area < c['list_min_px']:
            continue
        ys, xs = np.nonzero(m)
        peak = float(zs[m].max())
        gv, gn = np.unique(grp[m], return_counts=True)
        g = group_name(int(gv[gn.argmax()]))
        spots.append({'peak_z': round(peak, 2), 'area_px': area, 'part': g, 'bbox': [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
                      'albedo_dE': round(float(ca[m].max()), 2), 'photo_dE': round(float(cp_loc[m].mean()), 2)})
    spots.sort(key=lambda s: -s['peak_z'])
    bad = [s for s in spots if s['peak_z'] >= k and s['area_px'] >= c['min_area_px']]
    edge_lo = k * (1 - float(c['edge_frac']))
    edge = [s for s in spots if s not in bad and (s['peak_z'] >= edge_lo or (s['peak_z'] >= k and s['area_px'] < c['min_area_px']))]
    verdict = 'брак' if bad else ('на грани' if edge else 'чисто')
    return {'verdict': verdict, 'k': k, 'parts': parts, 'spots': spots[:5], 'n_bad': len(bad), 'n_edge': len(edge), 'valid_px': int(valid.sum()),
            'worst_z': spots[0]['peak_z'] if spots else 0.0, 'maps': {'z': zs, 'ca': ca, 'cp': cp}}


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
    valid = binary_erosion(st['mask'] & pm, iterations=int(c['erode_px'])) & (st['cos'] >= float(c['cos_min']))
    ids = st['ids']
    if parts_npz and os.path.exists(parts_npz):
        part_f = np.load(parts_npz)['part'].astype(np.int32)
        grp = np.where(ids >= 0, part_f[np.clip(ids, 0, len(part_f) - 1)], -1).astype(np.int32)
    else:
        grp = np.zeros(ids.shape, np.int32)
    res = measure(A, Pf, valid, grp, cfg)
    maps = res.pop('maps')
    if c.get('dump_npz'):                    # маленькая фикстура для тестов: вне valid кадры обнулены (сжимается в сотни КБ), мерка вне valid ничего не читает
        v3 = valid[..., None]
        np.savez_compressed(c['dump_npz'], A=np.where(v3, A, 0).astype(np.uint8), Pf=np.where(v3, Pf, 0).astype(np.uint8), valid=valid, grp=np.where(valid, grp, -1).astype(np.int8))
    np.save(os.path.join(out_dir, 'z.npy'), maps['z'].astype(np.float16))
    res['coverage'] = {'frame_px': int(st['mask'].sum()), 'valid_share': round(float(valid.sum()) / max(int(st['mask'].sum()), 1), 4),
                       'note': 'мерка видит только то, что видит камера фото; невидимое (зад, бок) — не наблюдаемо, но не «чисто»'}
    res['inputs'] = {'glb': glb, 'photo': photo_png, 'pose_run': pose_run, 'parts': parts_npz}
    pad = int(c['crop_pad_px'])
    for i, s in enumerate(res['spots'], 1):
        x0, y0, x1, y1 = s['bbox']
        a, b, cc, d = max(x0 - pad, 0), max(y0 - pad, 0), min(x1 + pad + 1, A.shape[1]), min(y1 + pad + 1, A.shape[0])
        tile = []
        for im in (Pf, A):
            t = im[b:d, a:cc].copy()
            cv2.rectangle(t, (x0 - a, y0 - b), (x1 - a, y1 - b), (255, 0, 0), 1)
            tile.append(t)
        row = np.concatenate([tile[0], np.full((tile[0].shape[0], 4, 3), 255, np.uint8), tile[1]], axis=1)
        sc = max(1, int(c['crop_scale']))
        row = cv2.resize(row, (row.shape[1] * sc, row.shape[0] * sc), interpolation=cv2.INTER_NEAREST)
        cv2.putText(row, f"#{i} part {s['part']} z={s['peak_z']} area={s['area_px']}  foto | albedo", (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
        Image.fromarray(row).save(os.path.join(out_dir, f'worst-{i}.png'))
    zi = np.clip(maps['z'] / max(float(c['k']) * 2, 1e-6), 0, 1)
    heat = cv2.applyColorMap((zi * 255).astype(np.uint8), cv2.COLORMAP_INFERNO)[..., ::-1]
    heat = np.where(valid[..., None], heat, 255).astype(np.uint8)
    Image.fromarray(np.concatenate([Pf, A, heat], axis=1)).save(os.path.join(out_dir, 'overview.png'))
    json.dump(res, open(os.path.join(out_dir, 'spots.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return res


if __name__ == '__main__':
    if len(sys.argv) < 5:
        print(__doc__)
        sys.exit(2)
    r = run(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else None)
    print(json.dumps({k: r[k] for k in ('verdict', 'k', 'worst_z', 'n_bad', 'n_edge', 'parts', 'spots')}, ensure_ascii=False))
