#!/usr/bin/env python3
"""T-20261119-83/2 (план `mesh-photo-projection-01`, шаги «итог 4096» и А1): два бесплатных (CPU) шага над готовой краской MV-Adapter, форма и развёртка НЕ меняются.

  k4096  итог без уменьшения до 2048: в GLB кладётся карта 4096 из 6 видов (`maps/tex4096_lossless.png` из `stages/`, без JPEG апстрима) вместо `tex2048`.
  a1     поверх k4096 — кривая только по L* (светлота), цвет a*b* не трогаем. Сама кривая — по КАЖДОМУ материалу (кластер по a*b* видимых пикселей фасада рендера вида 0):
         квантили L* рендера → квантили L* фото (та же регистрация, что в `stage_loss.py`: берётся из его `stage_loss.json`, одна на товар), затем кривая делается монотонной,
         наклон каждого куска зажат в [0,8; 1,3], медиана кластера садится в медиану фото, за краями квантилей наклон 1. Тексель получает L* как смесь кривых по мягким весам кластеров
         (расстояние по a*b* до центров кластеров). Без локальных μ/σ — они дают ореолы (план А1).
Guard: геометрия, развёртка (UV), индексы и всё JSON, кроме картинки, сравниваются с исходным GLB (макс. |разность| ≤ 1e-6, `--guard`); цвет a*b* — измеряется на рендере и в тексте.
Метрики стадий — те же функции `stage_loss.stage_metrics` (hf, σL, ΔE00 низких частот, ncc с `register=None`) на рендере вида 0: «рендер» здесь — выборка карты по `render_view0/uv.npz`
(CPU, без видеокарты; сверка с запечённым `r4096_lossless.png` — в выводе: MAE по маске фасада).

  a1_tone.py --glb <исходный .glb> --stages <папка stages/ товара> --photo <фото .rgba.png> --out-dir <папка> --stem <имя>
  → <out-dir>/<stem>-k4096.glb, <stem>-a1.glb, <out-dir>/<stem>.a1.json (кривые, метрики), <out-dir>/<stem>.view0_{2048,k4096,a1}.png
"""
from __future__ import annotations

import argparse
import io
import json
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, SCOUT)
import pattern_metric as PM  # noqa: E402
import stage_loss as SL  # noqa: E402

SLOPE_MIN, SLOPE_MAX = 0.8, 1.3        # наклон куска кривой (план А1)
KNOT_PCT = (2, 10, 20, 35, 50, 65, 80, 90, 98)      # перцентили узлов кривой; 50 — якорь (медиана)
CHROMA_MERGE = 6.0                     # центры кластеров ближе этого по a*b* — один материал
MIN_SHARE = 0.03                       # кластер меньше этой доли пикселей маски — сливаем с ближайшим
MIN_PIX = 400                          # пикселей фото/рендера в кластере, меньше — кластер без своей кривой (общая кривая)
SOFT_TAU = 6.0                         # ширина мягкого веса кластера по a*b* (exp(−(d/τ)²))
GUARD = 1e-6
CHUNK = 512


# ——— GLB без внешних библиотек ———
def read_glb(path: str) -> tuple[dict, bytes]:
    b = open(path, 'rb').read()
    magic, _ver, _total = struct.unpack('<4sII', b[:12])
    if magic != b'glTF':
        raise ValueError(f'не GLB: {path}')
    off, j, binc = 12, None, b''
    while off < len(b):
        ln, tp = struct.unpack('<II', b[off:off + 8])
        data = b[off + 8:off + 8 + ln]
        off += 8 + ln
        if tp == 0x4E4F534A:
            j = json.loads(data.decode('utf-8'))
        elif tp == 0x004E4942:
            binc = bytes(data)
    if j is None:
        raise ValueError('в GLB нет JSON-куска')
    return j, binc


def write_glb(path: str, j: dict, binc: bytes) -> None:
    js = json.dumps(j, separators=(',', ':')).encode('utf-8')
    js += b' ' * ((4 - len(js) % 4) % 4)
    bn = binc + b'\0' * ((4 - len(binc) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(bn)
    with open(path, 'wb') as f:
        f.write(struct.pack('<4sII', b'glTF', 2, total))
        f.write(struct.pack('<II', len(js), 0x4E4F534A) + js)
        f.write(struct.pack('<II', len(bn), 0x004E4942) + bn)


def view_bytes(j: dict, binc: bytes, vi: int) -> bytes:
    v = j['bufferViews'][vi]
    o = v.get('byteOffset', 0)
    return binc[o:o + v['byteLength']]


def swap_texture(j: dict, binc: bytes, png: bytes) -> tuple[dict, bytes]:
    """Новая пара (JSON, BIN): картинка единственной текстуры заменена на `png`, остальные куски буфера — те же байты. Одна картинка — иначе отказ (чужие случаи не угадываем)."""
    imgs = j.get('images') or []
    if len(imgs) != 1 or 'bufferView' not in imgs[0]:
        raise ValueError(f'ожидалась одна картинка во вложенном буфере, их {len(imgs)}')
    iv = imgs[0]['bufferView']
    out = bytearray()
    views = []
    for i, v in enumerate(j['bufferViews']):
        data = png if i == iv else view_bytes(j, binc, i)
        out += b'\0' * ((4 - len(out) % 4) % 4)
        nv = dict(v)
        nv['byteOffset'] = len(out)
        nv['byteLength'] = len(data)
        out += data
        views.append(nv)
    nj = json.loads(json.dumps(j))
    nj['bufferViews'] = views
    nj['buffers'] = [dict(j['buffers'][0], byteLength=len(out))]
    nj['images'][0]['mimeType'] = 'image/png'
    return nj, bytes(out)


_CT = {5120: 'i1', 5121: 'u1', 5122: 'i2', 5123: 'u2', 5125: 'u4', 5126: 'f4'}
_NC = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT2': 4, 'MAT3': 9, 'MAT4': 16}


def accessor_array(j: dict, binc: bytes, ai: int) -> np.ndarray:
    a = j['accessors'][ai]
    v = j['bufferViews'][a['bufferView']]
    dt = np.dtype(_CT[a['componentType']]).newbyteorder('<')
    n = _NC[a['type']]
    stride = v.get('byteStride') or dt.itemsize * n
    base = v.get('byteOffset', 0) + a.get('byteOffset', 0)
    raw = np.frombuffer(binc, np.uint8)
    idx = base + np.arange(a['count'])[:, None] * stride + np.arange(dt.itemsize * n)[None, :]
    return np.ascontiguousarray(raw[idx]).view(dt).reshape(a['count'], n)


def geometry_guard(ja: dict, ba: bytes, jb: dict, bb: bytes) -> dict:
    """Guard «форма и развёртка не изменились»: все атрибуты/индексы примитивов — максимум |разности|; остальной JSON (кроме картинки и раскладки буфера) — равенство."""
    strip = lambda j: {k: v for k, v in j.items() if k not in ('bufferViews', 'buffers', 'images')}  # noqa: E731
    same_json = json.dumps(strip(ja), sort_keys=True) == json.dumps(strip(jb), sort_keys=True)
    worst, n_acc = 0.0, 0
    for mesh in ja.get('meshes', []):
        for pr in mesh.get('primitives', []):
            ids = list(pr.get('attributes', {}).values()) + ([pr['indices']] if 'indices' in pr else [])
            for ai in ids:
                x, y = accessor_array(ja, ba, ai).astype(np.float64), accessor_array(jb, bb, ai).astype(np.float64)
                worst = float('inf') if x.shape != y.shape else max(worst, float(np.abs(x - y).max()) if x.size else 0.0)
                n_acc += 1
    return {'max_abs_diff': worst, 'accessors': n_acc, 'json_same': same_json, 'ok': bool(same_json and worst <= GUARD and n_acc > 0)}


# ——— цвет ———
_M = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]], np.float64)
_MI = np.linalg.inv(_M).astype(np.float32)
_WHITE = np.array([0.95047, 1.0, 1.08883], np.float32)


def lab_to_rgb(lab: np.ndarray) -> tuple[np.ndarray, float]:
    """Lab D65 → sRGB 0–255 (float32, обрезано) и доля пикселей, вышедших из гаммы (обрезаны). Обратная к `pattern_metric.rgb_to_lab`."""
    fy = (lab[..., 0] + 16) / 116
    fx, fz = fy + lab[..., 1] / 500, fy - lab[..., 2] / 200
    finv = lambda t: np.where(t ** 3 > 216 / 24389, t ** 3, (116 * t - 16) / (24389 / 27))  # noqa: E731
    xyz = np.stack([finv(fx), finv(fy), finv(fz)], -1) * _WHITE
    lin = xyz @ _MI.T
    out_of = ((lin < -1e-4) | (lin > 1 + 1e-4)).any(-1)
    lin = np.clip(lin, 0, 1)
    c = np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * lin ** (1 / 2.4) - 0.055)
    return (np.clip(c, 0, 1) * 255).astype(np.float32), float(out_of.mean())


# ——— кластеры материалов и кривые ———
def find_clusters(ab: np.ndarray, seed: int = 1, k: int = 4) -> np.ndarray:
    """Центры материалов по a*b* (N×2) — k-средних, затем слияние близких (< CHROMA_MERGE) и мелких (< MIN_SHARE). Детерминированно (seed). Возвращает (K, 2), K ≥ 1."""
    from scipy.cluster.vq import kmeans2
    rng = np.random.default_rng(seed)
    pts = ab.astype(np.float64)
    if len(pts) > 200000:
        pts = pts[rng.choice(len(pts), 200000, replace=False)]
    if len(pts) < 8:
        return pts.mean(0, keepdims=True) if len(pts) else np.zeros((1, 2))
    k = min(k, len(pts))
    cent, lab = kmeans2(pts, k, minit='++', seed=int(seed), missing='warn')
    cnt = np.bincount(lab, minlength=len(cent)).astype(np.float64)
    keep = cnt > 0
    cent, cnt = cent[keep], cnt[keep]
    while len(cent) > 1:
        share = cnt / cnt.sum()
        d = np.hypot(*(cent[:, None, :] - cent[None, :, :]).transpose(2, 0, 1))
        np.fill_diagonal(d, np.inf)
        i, j = np.unravel_index(np.argmin(d), d.shape)
        small = int(np.argmin(share))
        if share[small] < MIN_SHARE:
            j = int(np.argmin(d[small]))
            i = small
        elif d[i, j] >= CHROMA_MERGE:
            break
        w = cnt[i] + cnt[j]
        c = (cent[i] * cnt[i] + cent[j] * cnt[j]) / w
        keepi = [x for x in range(len(cent)) if x not in (i, j)]
        cent = np.vstack([cent[keepi], c[None]]) if keepi else c[None]
        cnt = np.append(cnt[keepi], w) if keepi else np.array([w])
    return cent[np.argsort(-cnt)]


def assign(ab: np.ndarray, cent: np.ndarray) -> np.ndarray:
    return np.argmin(((ab[:, None, :] - cent[None, :, :]) ** 2).sum(-1), -1)


def monotone_curve(Lr: np.ndarray, Lp: np.ndarray) -> dict:
    """Кривая L*(рендер) → L*(фото) по квантилям: кусочно-линейная, монотонная, наклон каждого куска в [SLOPE_MIN, SLOPE_MAX], медиана рендера → медиана фото, вне крайних узлов наклон 1.
    Возвращает {'x': [...], 'y': [...], 'slopes': [...]} (узлы с продолжением до ±100)."""
    r = np.percentile(Lr, KNOT_PCT).astype(np.float64)
    p = np.percentile(Lp, KNOT_PCT).astype(np.float64)
    for i in range(1, len(r)):                                  # узлы по x строго возрастают (плоский кластер)
        r[i] = max(r[i], r[i - 1] + 0.05)
    s = np.clip(np.diff(p) / np.diff(r), SLOPE_MIN, SLOPE_MAX)
    i0 = KNOT_PCT.index(50)
    y = np.empty_like(r)
    y[i0] = p[i0]
    for i in range(i0, len(r) - 1):
        y[i + 1] = y[i] + s[i] * (r[i + 1] - r[i])
    for i in range(i0, 0, -1):
        y[i - 1] = y[i] - s[i - 1] * (r[i] - r[i - 1])
    x = np.concatenate([[r[0] - 100.0], r, [r[-1] + 100.0]])
    yy = np.concatenate([[y[0] - 100.0], y, [y[-1] + 100.0]])
    return {'x': [round(float(v), 4) for v in x], 'y': [round(float(v), 4) for v in yy], 'slopes': [round(float(v), 4) for v in s]}


def eval_curve(c: dict, L: np.ndarray) -> np.ndarray:
    return np.interp(L, c['x'], c['y']).astype(np.float32)


def apply_curves(tex: np.ndarray, cent: np.ndarray, curves: list[dict]) -> tuple[np.ndarray, dict]:
    """Карта uint8 H×W×3 → новая: L* = смесь кривых по мягким весам кластеров (по a*b* текселя), a*b* прежние. Кусками по строкам (память)."""
    H, W = tex.shape[:2]
    out = np.empty_like(tex)
    clipped, dab_max = 0.0, 0.0
    for y0 in range(0, H, CHUNK):
        lab = PM.rgb_to_lab(tex[y0:y0 + CHUNK]).astype(np.float32)
        ab = lab[..., 1:]
        d2 = ((ab[..., None, :] - cent[None, None, :, :].astype(np.float32)) ** 2).sum(-1)
        w = np.exp(-d2 / (SOFT_TAU ** 2))
        s = w.sum(-1, keepdims=True)
        one = np.eye(len(cent), dtype=np.float32)[np.argmin(d2, -1)]
        w = np.where(s < 1e-6, one, w / np.maximum(s, 1e-12))
        L = lab[..., 0]
        lab[..., 0] = sum(w[..., k] * eval_curve(curves[k], L) for k in range(len(curves)))
        rgb, frac = lab_to_rgb(lab)
        clipped += frac * (lab.shape[0] / H)
        out[y0:y0 + CHUNK] = np.round(rgb).astype(np.uint8)
    return out, {'gamut_clipped_share': round(clipped, 5)}


# ——— рендер вида 0 по карте (CPU) ———
def render_view0(tex: np.ndarray, uvd) -> np.ndarray:
    import cv2
    uv, vm = uvd['uv'].astype(np.float32), uvd['mask'].astype(bool)
    size = tex.shape[0]
    img = cv2.remap(tex, uv[..., 0] * size - 0.5, uv[..., 1] * size - 0.5, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    img[~vm] = 0
    return img


def png_bytes(arr: np.ndarray) -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.fromarray(arr).save(b, format='PNG', compress_level=3)
    return b.getvalue()


def run(glb: str, stages: str, photo_path: str, out_dir: str, stem: str) -> dict:
    import cv2
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    man = json.load(open(os.path.join(stages, 'manifest.json'), encoding='utf-8'))
    sl_json = os.path.join(os.path.dirname(stages.rstrip('/')), 'stage_loss.json')
    sl = json.load(open(sl_json, encoding='utf-8'))
    P = np.array(sl['registration']['P'], np.float64).reshape(3, 3)          # ОДНА регистрация на товар — из stage_loss.json
    rd = os.path.join(stages, 'render_view0')
    S = np.asarray(Image.open(os.path.join(rd, 'mask.png')).convert('L')) > 127
    aoi = np.asarray(Image.open(os.path.join(rd, 'aoi_cos16.png'))).astype(np.float32) / 65535.0
    uvd = np.load(os.path.join(rd, 'uv.npz'))
    photo = SL.read_rgba(photo_path)
    fh, fw = S.shape
    A_fr = SL.warp_inv((photo[..., 3] > 127).astype(np.float32), P, (fw, fh)) > 0.5
    cm, width = SL.common_mask(S, A_fr, aoi)
    ph = np.clip(SL.warp_inv(photo[..., :3], P, (fw, fh), cv2.INTER_LINEAR), 0, 255).astype(np.uint8)
    tex2048 = SL.read_rgb(os.path.join(stages, 'maps', 'tex2048.png'))
    tex4096 = SL.read_rgb(os.path.join(stages, 'maps', 'tex4096_lossless.png'))
    r2048, r4096 = render_view0(tex2048, uvd), render_view0(tex4096, uvd)
    chk = SL.read_rgb(os.path.join(rd, 'r4096_lossless.png'))
    mae = float(np.abs(chk.astype(np.float32) - r4096.astype(np.float32))[cm].mean())     # сверка нашего «рендера» с запечённым r4096_lossless.png (супер-сэмплинг ×2 у воркера)

    # кривые: статистика — видимый фасад рендера k4096 и фото в одной маске
    lab_r, lab_p = PM.rgb_to_lab(r4096), PM.rgb_to_lab(ph)
    ys, xs = np.nonzero(cm)
    ab_r, ab_p = lab_r[ys, xs, 1:], lab_p[ys, xs, 1:]
    Lr, Lp = lab_r[ys, xs, 0], lab_p[ys, xs, 0]
    cent = find_clusters(ab_r)
    lr_c, lp_c = assign(ab_r, cent), assign(ab_p, cent)
    glob = monotone_curve(Lr, Lp)
    curves, info = [], []
    for k in range(len(cent)):
        a, b = Lr[lr_c == k], Lp[lp_c == k]
        own = len(a) >= MIN_PIX and len(b) >= MIN_PIX
        curves.append(monotone_curve(a, b) if own else glob)
        info.append({'center_ab': [round(float(v), 2) for v in cent[k]], 'px_render': int(len(a)), 'px_photo': int(len(b)), 'own_curve': bool(own),
                     'L_median_render': round(float(np.median(a)), 2) if len(a) else None, 'L_median_photo': round(float(np.median(b)), 2) if len(b) else None,
                     'slopes': curves[-1]['slopes']})
    new, apinfo = apply_curves(tex4096, cent, curves)
    ra1 = render_view0(new, uvd)

    # GLB: k4096 и a1; guard
    j0, b0 = read_glb(glb)
    jk, bk = swap_texture(j0, b0, png_bytes(tex4096))
    ja, ba = swap_texture(j0, b0, png_bytes(new))
    pk, pa = os.path.join(out_dir, f'{stem}-k4096.glb'), os.path.join(out_dir, f'{stem}-a1.glb')
    write_glb(pk, jk, bk)
    write_glb(pa, ja, ba)
    g_k = geometry_guard(*read_glb(glb), *read_glb(pk))
    g_a = geometry_guard(*read_glb(glb), *read_glb(pa))

    # метрики (одна регистрация, одна маска, фото в кадре 1536)
    met = {}
    for name, img in (('mv_2048', r2048), ('k4096', r4096), ('a1', ra1)):
        met[name] = SL.stage_metrics(img, ph, cm, width, ncc=True)
        Image.fromarray(img).save(os.path.join(out_dir, f'{stem}.view0_{name}.png'))
    lab_a = PM.rgb_to_lab(ra1)
    dab = np.abs(lab_a[ys, xs, 1:] - lab_r[ys, xs, 1:])
    pick = lambda m: {'hf_1%': m['hf']['1%']['ratio'], 'hf_0.5%': m['hf']['0.5%']['ratio'], 'hf_2%': m['hf']['2%']['ratio'], 'sigmaL': m['sigmaL']['ratio'],  # noqa: E731
                      'dE00_lf': m['dE00_lf_median'], 'ncc': (m.get('ncc') or {}).get('median'), 'ncc_p10': (m.get('ncc') or {}).get('p10')}
    table = {k: pick(v) for k, v in met.items()}
    gate_dE = round(table['a1']['dE00_lf'] - table['k4096']['dE00_lf'], 3)
    res = {'glb': glb, 'stem': stem, 'tex': {'k4096': 'maps/tex4096_lossless.png', 'base': 'maps/tex2048.png'}, 'render_check_mae_vs_stored_r4096_lossless': round(mae, 3),
           'clusters': info, 'global_curve': {'slopes': glob['slopes']}, 'apply': apinfo, 'a_b_change_render': {'mean_abs_da': round(float(dab[:, 0].mean()), 3), 'mean_abs_db': round(float(dab[:, 1].mean()), 3)},
           'table': table, 'gate': {'dE00_lf_a1_minus_k4096': gate_dE, 'dE00_lf_ok': gate_dE <= 1.0, 'limit': 1.0},
           'guard': {'k4096': g_k, 'a1': g_a}, 'files': {'k4096': pk, 'a1': pa, 'k4096_mb': round(os.path.getsize(pk) / 2 ** 20, 2), 'a1_mb': round(os.path.getsize(pa) / 2 ** 20, 2),
                                                          'orig_mb': round(os.path.getsize(glb) / 2 ** 20, 2)},
           'registration': sl['registration'], 'mask_px': int(cm.sum()), 'curves': curves}
    json.dump(res, open(os.path.join(out_dir, f'{stem}.a1.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
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
    print(json.dumps({k: r[k] for k in ('stem', 'render_check_mae_vs_stored_r4096_lossless', 'table', 'gate', 'a_b_change_render', 'apply')}, ensure_ascii=False, indent=1))
    print('guard k4096:', r['guard']['k4096'], '\nguard a1:', r['guard']['a1'])
    for c in r['clusters']:
        print('кластер', c)
    return 0 if r['guard']['k4096']['ok'] and r['guard']['a1']['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
