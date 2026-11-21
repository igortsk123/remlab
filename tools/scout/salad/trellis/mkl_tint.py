#!/usr/bin/env python3
"""T-20261119-88 (доработка директора, TG 1882): вариант шага 3 цепочки «вариант 9» — перенос цвета по MKL (Monge–Kantorovich, Pitié, Kokaram, Dahyot 2007), своя реализация на numpy.

ЗАЧЕМ. Сравнить «наш шаг» (`ab_tint.py`: сдвиг медиан a*b* с ограничителями, L* не трогается) с классическим линейным переносом цвета, который меняет и яркость, и разброс, и корреляции каналов.
Пакет `color-matcher` (GPL-3.0, без маски, статистики по всем пикселям с фоном) не используем; здесь — формула из статьи, статистики ТОЛЬКО по маске видимого фасада (общая маска А0, регистрация А0).

ФОРМУЛА. Источник — рендер карты в кадре вида 0, цель — фото (в том же кадре), оба в Lab D65 (L*, a*, b*), по маске `cm`. Средние μs, μr и ковариации Σs, Σr (3×3, + `EPS` на диагонали);
  T = Σs^(−1/2) · (Σs^(1/2) · Σr · Σs^(1/2))^(1/2) · Σs^(−1/2),   x' = T·(x − μs) + μr   (T симметрична, T·Σs·Tᵀ = Σr — ковариация источника становится ковариацией цели).
Режимы:
  all      — одно преобразование на всю карту (весь объект);
  clusters — как `ab_tint`: кластеры материалов по a*b* рендера (`a1_tone.find_clusters`), у каждого своё преобразование (пиксели рендера кластера → пиксели фото, попавшие в тот же кластер по a*b*;
             мало пикселей — общее), тексель карты получает смесь преобразований по мягким весам a*b* (`SOFT_TAU`).
ЧЕСТНО. MKL меняет L* (в отличие от `ab_tint`): в json — сдвиг L* (медиана и p99 |ΔL|) и доля текселей, вышедших из гаммы sRGB (обрезаны); L* после преобразования обрезается в [0, 100].
Форма и развёртка не меняются (guard 1e-6, `a1_tone.geometry_guard`).

  mkl_tint.py --glb <GLB с картой> --stages <stages/> --photo <фото .rgba.png> --out-dir <папка> --stem <имя> [--mode all|clusters]
  → <out-dir>/<stem>-mkl.glb, <stem>.mkl.json, <stem>.view0_{in,mkl}.png
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
import a1_tone as A  # noqa: E402
import ab_tint as T  # noqa: E402
import pattern_metric as PM  # noqa: E402
import stage_loss as SL  # noqa: E402

EPS = 1e-3          # добавка к диагонали ковариаций (устойчивость при почти вырожденных цветах)


def _sym_pow(M: np.ndarray, p: float) -> np.ndarray:
    w, V = np.linalg.eigh((M + M.T) / 2)
    w = np.maximum(w, 1e-12)
    return (V * w ** p) @ V.T


def mkl_transform(src: np.ndarray, ref: np.ndarray, eps: float = EPS) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Точки источника (N×3) и цели (M×3) → (T 3×3, μ_источника, μ_цели): x' = T(x − μs) + μr; T·Σs·Tᵀ = Σr."""
    src, ref = np.asarray(src, np.float64), np.asarray(ref, np.float64)
    ms, mr = src.mean(0), ref.mean(0)
    Ss = np.cov(src.T) + eps * np.eye(3)
    Sr = np.cov(ref.T) + eps * np.eye(3)
    s_h, s_ih = _sym_pow(Ss, 0.5), _sym_pow(Ss, -0.5)
    Tm = s_ih @ _sym_pow(s_h @ Sr @ s_h, 0.5) @ s_ih
    return Tm, ms, mr


def apply_mkl(tex: np.ndarray, transforms: list, cent: np.ndarray | None = None) -> tuple[np.ndarray, dict]:
    """Карта uint8 → новая: Lab текселя преобразуется (один T или смесь по мягким весам кластеров), L* в [0, 100], Lab → sRGB с обрезкой по гамме."""
    H = tex.shape[0]
    out = np.empty_like(tex)
    clipped = 0.0
    dls = []
    cf = None if cent is None else cent.astype(np.float32)
    for y0 in range(0, H, T.CHUNK):
        lab = PM.rgb_to_lab(tex[y0:y0 + T.CHUNK]).astype(np.float32)
        new = np.zeros_like(lab)
        if cf is None or len(transforms) == 1:
            Tm, ms, mr = transforms[0]
            new = ((lab - ms.astype(np.float32)) @ Tm.T.astype(np.float32)) + mr.astype(np.float32)
        else:
            d2 = ((lab[..., None, 1:] - cf[None, None, :, :]) ** 2).sum(-1)
            w = np.exp(-d2 / (A.SOFT_TAU ** 2))
            s = w.sum(-1, keepdims=True)
            one = np.eye(len(cf), dtype=np.float32)[np.argmin(d2, -1)]
            w = np.where(s < 1e-6, one, w / np.maximum(s, 1e-12))
            for k, (Tm, ms, mr) in enumerate(transforms):
                cand = ((lab - ms.astype(np.float32)) @ Tm.T.astype(np.float32)) + mr.astype(np.float32)
                new += w[..., k:k + 1] * cand
        new[..., 0] = np.clip(new[..., 0], 0, 100)
        dls.append((new[..., 0] - lab[..., 0]).ravel()[::7])
        rgb, frac = A.lab_to_rgb(new)
        clipped += frac * (lab.shape[0] / H)
        out[y0:y0 + T.CHUNK] = np.round(rgb).astype(np.uint8)
    dl = np.concatenate(dls)
    return out, {'gamut_clipped_share': round(clipped, 5), 'dL_texels': {'median': round(float(np.median(dl)), 3), 'p99_abs': round(float(np.percentile(np.abs(dl), 99)), 3)}}


def run(glb: str, stages: str, photo_path: str, out_dir: str, stem: str, mode: str = 'all') -> dict:
    import cv2
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    sl = json.load(open(os.path.join(os.path.dirname(stages.rstrip('/')), 'stage_loss.json'), encoding='utf-8'))
    P = np.array(sl['registration']['P'], np.float64).reshape(3, 3)
    rd = os.path.join(stages, 'render_view0')
    S = np.asarray(Image.open(os.path.join(rd, 'mask.png')).convert('L')) > 127
    aoi = np.asarray(Image.open(os.path.join(rd, 'aoi_cos16.png'))).astype(np.float32) / 65535.0
    uvd = np.load(os.path.join(rd, 'uv.npz'))
    photo = SL.read_rgba(photo_path)
    fh, fw = S.shape
    A_fr = SL.warp_inv((photo[..., 3] > 127).astype(np.float32), P, (fw, fh)) > 0.5
    cm, width = SL.common_mask(S, A_fr, aoi)
    ph = np.clip(SL.warp_inv(photo[..., :3], P, (fw, fh), cv2.INTER_LINEAR), 0, 255).astype(np.uint8)
    j0, b0 = A.read_glb(glb)
    tex = T.read_texture(j0, b0)
    r_in = A.render_view0(tex, uvd)
    lab_r, lab_p = PM.rgb_to_lab(r_in), PM.rgb_to_lab(ph)
    ys, xs = np.nonzero(cm)
    pr, pp = lab_r[ys, xs].astype(np.float64), lab_p[ys, xs].astype(np.float64)
    g_tr = mkl_transform(pr, pp)
    cent, info = None, []
    if mode == 'clusters':
        cent = A.find_clusters(pr[:, 1:])
        lr_c, lp_c = A.assign(pr[:, 1:], cent), A.assign(pp[:, 1:], cent)
        trs = []
        for k in range(len(cent)):
            a, b = pr[lr_c == k], pp[lp_c == k]
            own = len(a) >= A.MIN_PIX and len(b) >= A.MIN_PIX
            trs.append(mkl_transform(a, b) if own else g_tr)
            info.append({'center_ab': [round(float(v), 2) for v in cent[k]], 'px_render': int(len(a)), 'px_photo': int(len(b)), 'own_transform': bool(own)})
    else:
        trs = [g_tr]
    new, apinfo = apply_mkl(tex, trs, cent)
    r_out = A.render_view0(new, uvd)
    jn, bn = A.swap_texture(j0, b0, A.png_bytes(new))
    p_out = os.path.join(out_dir, f'{stem}-mkl.glb')
    A.write_glb(p_out, jn, bn)
    g = A.geometry_guard(*A.read_glb(glb), *A.read_glb(p_out))
    met = {}
    for name, img in (('in', r_in), ('mkl', r_out)):
        met[name] = SL.stage_metrics(img, ph, cm, width, ncc=True)
        Image.fromarray(img).save(os.path.join(out_dir, f'{stem}.view0_{name}.png'))
    pick = lambda m: {'hf_1%': m['hf']['1%']['ratio'], 'sigmaL': m['sigmaL']['ratio'], 'dE00_lf': m['dE00_lf_median'], 'ncc': (m.get('ncc') or {}).get('median')}  # noqa: E731
    lab_o = PM.rgb_to_lab(r_out)
    res = {'glb_in': glb, 'stem': stem, 'mode': mode, 'tex_size': list(tex.shape[:2]), 'clusters': info, 'apply': apinfo, 'table': {k: pick(v) for k, v in met.items()},
           'view0_mean_lab': {'render_before': [round(float(v), 2) for v in pr.mean(0)], 'render_after': [round(float(v), 2) for v in lab_o[ys, xs].mean(0)], 'photo': [round(float(v), 2) for v in pp.mean(0)]},
           'guard': g, 'files': {'mkl': p_out}, 'mask_px': int(cm.sum())}
    json.dump(res, open(os.path.join(out_dir, f'{stem}.mkl.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--glb')
    ap.add_argument('--stages')
    ap.add_argument('--photo')
    ap.add_argument('--out-dir')
    ap.add_argument('--stem')
    ap.add_argument('--mode', choices=('all', 'clusters'), default='all')
    a = ap.parse_args()
    if not all([a.glb, a.stages, a.photo, a.out_dir, a.stem]):
        ap.error('нужны --glb --stages --photo --out-dir --stem')
    r = run(a.glb, a.stages, a.photo, a.out_dir, a.stem, a.mode)
    print(json.dumps({k: r[k] for k in ('stem', 'mode', 'table', 'apply', 'view0_mean_lab', 'guard')}, ensure_ascii=False, indent=1))
    return 0 if r['guard']['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
