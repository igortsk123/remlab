#!/usr/bin/env python3
"""T-20261119-87 (план `mesh-photo-projection-01`, шаг «оттенок a*b*» будущей цепочки «вариант 9»: MV-Adapter → пиксели фото → ОТТЕНОК a*b* → заливка дыр → итог 4096).

Самостоятельный шаг над готовой картой краски: форма и развёртка НЕ меняются, светлота L* НЕ трогается (её правит А1, `a1_tone.py`), двигается только цвет a*b*.
Отдельный файл (не режим `a1_tone.py`), потому что шаг встаёт в цепочку в ЛЮБОМ месте после покраски: вход — любой GLB с одной картой (2048 или 4096, в т. ч. выход А1), выход — тот же GLB
с новой картой; общие куски (GLB, кластеры, регистрация, Lab↔sRGB, guard) берутся из `a1_tone.py` без копий.

КАК ЭТО РАБОТАЕТ (на ту же регистрацию фото→кадр вида 0, что в `stage_loss.py`: берётся из `stage_loss.json`, одна на товар):
  1. Кластеры материалов — по a*b* видимого фасада рендера карты (`a1_tone.find_clusters`, те же пороги). Рендер — выборка карты по `render_view0/uv.npz` (CPU).
  2. По каждому кластеру: сдвиг = (медиана a*b* фото по пикселям, попавшим в этот кластер) − (медиана a*b* рендера). Кластер без своих пикселей (< MIN_PIX) берёт общий сдвиг по всему фасаду.
  3. Ограничители на кластер: длина сдвига ≤ MAX_SHIFT (единиц a*b*, при L=const это ΔE76; за шаг не дальше); цветность медианы после сдвига не выше большей из цветностей
     фото и рендера (насыщенность не раздувается выше фото — по сути «не уходить за цель»).
  4. Тексель карты получает сдвиг как смесь сдвигов кластеров по мягким весам a*b* (как у А1, `SOFT_TAU`) — без швов на границах материалов. Ограничитель «без инверсии оттенка»:
     сдвиг каждого текселя масштабируется так, чтобы вектор a*b* не переходил через ноль (серые и светлые текселя не получают чужого оттенка).
  5. L* текселя прежняя; Lab → sRGB с обрезкой по гамме (доля обрезанных — в json). Guard формы 1e-6 — `a1_tone.geometry_guard`.

  ab_tint.py --glb <GLB с картой> --stages <папка stages/ товара> --photo <фото .rgba.png> --out-dir <папка> --stem <имя>
  → <out-dir>/<stem>-ab.glb, <stem>.ab.json (сдвиги по кластерам, метрики до/после, guard), <stem>.view0_{in,ab}.png
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
import a1_tone as A  # noqa: E402
import pattern_metric as PM  # noqa: E402
import stage_loss as SL  # noqa: E402

MAX_SHIFT = 10.0       # предел длины сдвига a*b* кластера за один шаг (единиц a*b*; при L=const = ΔE76)
CHUNK = A.CHUNK


# ——— карта из GLB ———
def read_texture(j: dict, binc: bytes) -> np.ndarray:
    """Единственная карта GLB (PNG/JPEG во вложенном буфере) → uint8 H×W×3."""
    from PIL import Image
    imgs = j.get('images') or []
    if len(imgs) != 1 or 'bufferView' not in imgs[0]:
        raise ValueError(f'ожидалась одна картинка во вложенном буфере, их {len(imgs)}')
    return np.asarray(Image.open(io.BytesIO(A.view_bytes(j, binc, imgs[0]['bufferView']))).convert('RGB'))


# ——— сдвиги ———
def cluster_shift(c_r: np.ndarray, c_p: np.ndarray, max_shift: float = MAX_SHIFT) -> tuple[np.ndarray, dict]:
    """Сдвиг a*b* кластера: от медианы рендера к медиане фото; длина ≤ max_shift; цветность результата не выше max(цветность фото, цветность рендера)."""
    raw = np.asarray(c_p, np.float64) - np.asarray(c_r, np.float64)
    n = float(np.hypot(*raw))
    s = raw * min(1.0, max_shift / n) if n > 1e-9 else raw * 0.0
    limited = n > max_shift
    target = np.asarray(c_r, np.float64) + s
    cap = max(float(np.hypot(*c_p)), float(np.hypot(*c_r)))
    sat = False
    if float(np.hypot(*target)) > cap + 1e-9:
        target = target * (cap / float(np.hypot(*target)))
        s = target - np.asarray(c_r, np.float64)
        sat = True
    return s, {'raw_len': round(n, 3), 'len': round(float(np.hypot(*s)), 3), 'limited_by_max_shift': bool(limited), 'limited_by_chroma_cap': sat}


def apply_shifts(tex: np.ndarray, cent: np.ndarray, shifts: np.ndarray) -> tuple[np.ndarray, dict]:
    """Карта uint8 H×W×3 → новая: a*b* += смесь сдвигов по мягким весам кластеров (по a*b* текселя), L* прежняя. Без инверсии оттенка: сдвиг масштабируется, чтобы вектор a*b* не переходил ноль."""
    H = tex.shape[0]
    out = np.empty_like(tex)
    clipped, inv_scaled, dl_max = 0.0, 0.0, 0.0
    cf = cent.astype(np.float32)
    sh = shifts.astype(np.float32)
    for y0 in range(0, H, CHUNK):
        lab = PM.rgb_to_lab(tex[y0:y0 + CHUNK]).astype(np.float32)
        ab = lab[..., 1:]
        d2 = ((ab[..., None, :] - cf[None, None, :, :]) ** 2).sum(-1)
        w = np.exp(-d2 / (A.SOFT_TAU ** 2))
        s = w.sum(-1, keepdims=True)
        one = np.eye(len(cf), dtype=np.float32)[np.argmin(d2, -1)]
        w = np.where(s < 1e-6, one, w / np.maximum(s, 1e-12))
        d = (w[..., None] * sh[None, None, :, :]).sum(-2)                       # сдвиг текселя
        dot = (d * ab).sum(-1)
        n2 = (ab * ab).sum(-1)
        t = np.where(dot < 0, np.minimum(1.0, n2 / np.maximum(-dot, 1e-9)), 1.0)  # dot(ab + t·d, ab) ≥ 0
        inv_scaled += float((t < 1.0).mean()) * (lab.shape[0] / H)
        lab[..., 1:] = ab + t[..., None] * d
        rgb, frac = A.lab_to_rgb(lab)
        clipped += frac * (lab.shape[0] / H)
        out[y0:y0 + CHUNK] = np.round(rgb).astype(np.uint8)
    return out, {'gamut_clipped_share': round(clipped, 5), 'texels_scaled_by_no_inversion_share': round(inv_scaled, 5)}


def run(glb: str, stages: str, photo_path: str, out_dir: str, stem: str) -> dict:
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
    tex = read_texture(j0, b0)
    r_in = A.render_view0(tex, uvd)
    lab_r, lab_p = PM.rgb_to_lab(r_in), PM.rgb_to_lab(ph)
    ys, xs = np.nonzero(cm)
    ab_r, ab_p = lab_r[ys, xs, 1:], lab_p[ys, xs, 1:]
    cent = A.find_clusters(ab_r)
    lr_c, lp_c = A.assign(ab_r, cent), A.assign(ab_p, cent)
    g_shift, g_info = cluster_shift(np.median(ab_r, 0), np.median(ab_p, 0))
    shifts, info = [], []
    for k in range(len(cent)):
        a, b = ab_r[lr_c == k], ab_p[lp_c == k]
        own = len(a) >= A.MIN_PIX and len(b) >= A.MIN_PIX
        if own:
            s, li = cluster_shift(np.median(a, 0), np.median(b, 0))
        else:
            s, li = g_shift, g_info
        shifts.append(s)
        info.append({'center_ab': [round(float(v), 2) for v in cent[k]], 'px_render': int(len(a)), 'px_photo': int(len(b)), 'own_shift': bool(own),
                     'median_ab_render': [round(float(v), 2) for v in np.median(a, 0)] if len(a) else None,
                     'median_ab_photo': [round(float(v), 2) for v in np.median(b, 0)] if len(b) else None,
                     'shift_ab': [round(float(v), 3) for v in s], **li})
    new, apinfo = apply_shifts(tex, cent, np.array(shifts))
    r_out = A.render_view0(new, uvd)

    ja, ba = A.swap_texture(j0, b0, A.png_bytes(new))
    p_out = os.path.join(out_dir, f'{stem}-ab.glb')
    A.write_glb(p_out, ja, ba)
    g = A.geometry_guard(*A.read_glb(glb), *A.read_glb(p_out))

    met = {}
    for name, img in (('in', r_in), ('ab', r_out)):
        met[name] = SL.stage_metrics(img, ph, cm, width, ncc=True)
        Image.fromarray(img).save(os.path.join(out_dir, f'{stem}.view0_{name}.png'))
    pick = lambda m: {'hf_1%': m['hf']['1%']['ratio'], 'sigmaL': m['sigmaL']['ratio'], 'dE00_lf': m['dE00_lf_median'], 'ncc': (m.get('ncc') or {}).get('median')}  # noqa: E731
    table = {k: pick(v) for k, v in met.items()}
    lab_o = PM.rgb_to_lab(r_out)
    dL = lab_o[ys, xs, 0] - lab_r[ys, xs, 0]
    after = {'median_ab_render_after': [round(float(v), 2) for v in np.median(lab_o[ys, xs, 1:], 0)],
             'median_ab_photo': [round(float(v), 2) for v in np.median(ab_p, 0)], 'median_ab_render_before': [round(float(v), 2) for v in np.median(ab_r, 0)],
             'L_change_render': {'median': round(float(np.median(dL)), 3), 'p99_abs': round(float(np.percentile(np.abs(dL), 99)), 3)}}
    res = {'glb_in': glb, 'stem': stem, 'tex_size': list(tex.shape[:2]), 'max_shift': MAX_SHIFT, 'clusters': info, 'apply': apinfo, 'table': table, 'after': after,
           'guard': g, 'files': {'ab': p_out, 'in_mb': round(os.path.getsize(glb) / 2 ** 20, 2), 'ab_mb': round(os.path.getsize(p_out) / 2 ** 20, 2)}, 'mask_px': int(cm.sum()),
           'registration': sl['registration']}
    json.dump(res, open(os.path.join(out_dir, f'{stem}.ab.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--glb')
    ap.add_argument('--stages')
    ap.add_argument('--photo')
    ap.add_argument('--out-dir')
    ap.add_argument('--stem')
    a = ap.parse_args()
    if not all([a.glb, a.stages, a.photo, a.out_dir, a.stem]):
        ap.error('нужны --glb --stages --photo --out-dir --stem')
    r = run(a.glb, a.stages, a.photo, a.out_dir, a.stem)
    print(json.dumps({k: r[k] for k in ('stem', 'tex_size', 'table', 'after', 'apply', 'guard')}, ensure_ascii=False, indent=1))
    for c in r['clusters']:
        print('кластер', c)
    return 0 if r['guard']['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
