"""Ш6 (просьба директора 21.11): (1) кадр, где видна разница вар.1 — крупно, в физическом масштабе, True colour и «рельеф из яркости» (условно), рядом ткань-эталон из фото той же роли;
(2) шов на границе заёма — ступень тона/рисунка по поверхности (грани через общее ребро: часть p ↔ сосед), к фону — такие же пары граней внутри p.
Выход: <выход>/seam/<метка>-p<часть>-zoom.png и печать метрик. Подписи на кадрах латиницей (PIL рисует кириллицу квадратами)."""
import os
import sys

W = os.path.expanduser('~/remlab-logs/t182-1121/tools/scout/salad/trellis')
for q in (W, W + '/..', W + '/../..', W + '/../../stablegen'):
    sys.path.insert(0, q)
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import gaussian_filter
import tex_fill as TF

H = os.path.expanduser('~/remlab-logs')
OUT = sys.argv[1]
RES = 3072
# (корень, sku, часть, подпись): Денди ч.1 — главный (71 %), Брера ч.6 (33 %), шкаф ч.4 (7 %)
ITEMS = [('e2eHD-1121', '114082_10587794773481498560', 1), ('e2eHD-1121', '112923_16411672175141188566', 6), ('e2eHD-batch-1121', '112923_10551627698909366429', 4)]


def indicator(geoms, tx, part_ids, az, el=0.0):
    """маска видимости частей part_ids в кадре az: тексели части = 0, прочие = 128, фон 245."""
    T = tx.T
    a = np.full(T * T, 128, np.uint8)
    for p in part_ids:
        a[tx.ti[tx.part == p]] = 0
    tex = np.repeat(a.reshape(T, T, 1), 3, axis=2)
    img = TF.render_ortho(geoms, [tex], az, res=RES, elevation=el)
    return img[..., 0] < 40


def window(mask, size_list=(900, 800, 700, 600, 500, 400, 300), cover=0.97):
    """квадрат на кадре, ≥cover заполненный маской; ближайший к центроиду; (y, x, s) или None."""
    ys, xs = np.nonzero(mask)
    if len(ys) < 5000:
        return None
    cy, cx = int(ys.mean()), int(xs.mean())
    ii = np.pad(mask.astype(np.int64).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    for s in size_list:
        best = None
        for y in range(0, RES - s, 20):
            for x in range(0, RES - s, 20):
                tot = ii[y + s, x + s] - ii[y, x + s] - ii[y + s, x] + ii[y, x]
                if tot >= cover * s * s:
                    d = (y + s // 2 - cy) ** 2 + (x + s // 2 - cx) ** 2
                    if best is None or d < best[0]:
                        best = (d, y, x)
        if best:
            return best[1], best[2], s
    return None


def emboss(img, k):
    """«рельеф из яркости» (условно!): L → высота, свет скользящий слева; одинаковый множитель k на всех панелях."""
    L = img.astype(np.float64).mean(axis=2)
    h = gaussian_filter(L, 0.8)
    dx = np.gradient(h, axis=1)
    return np.clip(140 + k * dx, 0, 255).astype(np.uint8)


def label(im, text):
    im = Image.fromarray(im).convert('RGB')
    d = ImageDraw.Draw(im)
    d.rectangle((6, 6, 330, 30), fill=(255, 255, 255))
    d.text((12, 12), text, fill=(0, 0, 0))
    return im


os.makedirs(OUT + '/seam', exist_ok=True)
for root, sku, p in ITEMS:
    R = f'{H}/{root}/{sku}'
    known = [np.asarray(Image.open(R + '/06-visible/known.png').convert('L')) > 127]
    runs = {}
    for nm, cfg in (('now', {'erode_known': 0}), ('v1', {'erode_known': 0, 'borrow_texture': True})):
        runs[nm] = TF.run_stage(OUT + '/' + sku + '-' + nm, sku, R + '/06-visible/visible.glb', known=known, cfg=cfg, prev_dir=R + '/06-visible', parts_npz=R + '/03-parts/parts.npz')
    g = runs['now']['geoms'][0]
    tx = TF.Tex(g, np.asarray(g['V'], float), TF._grid(g), runs['now']['parts'][0])
    T = tx.T
    rep1 = runs['v1']['report']
    bi = (rep1.get('borrowed_info') or {}).get(p) or (rep1.get('borrowed_info') or {}).get(str(p))
    print(f'== {sku} ч.{p}: заём {bi}', flush=True)
    if not bi:
        print('  заёма нет — пропуск', flush=True)
        continue
    don = int(bi['donor'])
    kk = runs['now']['known'][0].reshape(-1)[tx.ti]
    # --- (2) шов по поверхности ------------------------------------------------------------------------
    Fw, pf = np.asarray(tx.FW), np.asarray(tx.part_f)
    nF = len(pf)
    cnt = np.bincount(tx.f, minlength=nF).astype(np.float64)
    e = np.concatenate([Fw[:, [0, 1]], Fw[:, [1, 2]], Fw[:, [2, 0]]])
    fi = np.tile(np.arange(nF), 3)
    e.sort(axis=1)
    key = e[:, 0].astype(np.int64) * (int(Fw.max()) + 1) + e[:, 1]
    order = np.argsort(key, kind='stable')
    ks, fs = key[order], fi[order]
    same = ks[1:] == ks[:-1]
    fa, fb = fs[:-1][same], fs[1:][same]
    ok = (cnt[fa] >= 2) & (cnt[fb] >= 2)
    fa, fb = fa[ok], fb[ok]
    for nm, r in runs.items():
        lab = TF.rgb2lab(np.asarray(r['tex_after'][0]).reshape(-1, 3))[tx.ti]
        mean = np.zeros((nF, 3))
        for c in range(3):
            mean[:, c] = np.bincount(tx.f, weights=lab[:, c], minlength=nF) / np.maximum(cnt, 1)
        frac_k = np.bincount(tx.f, weights=kk.astype(float), minlength=nF) / np.maximum(cnt, 1)
        res = {}
        for tag, sel in (('внутри ч.%d (грани рядом)' % p, (pf[fa] == p) & (pf[fb] == p)),
                         ('шов ч.%d ↔ донор ч.%d' % (p, don), ((pf[fa] == p) & (pf[fb] == don)) | ((pf[fa] == don) & (pf[fb] == p))),
                         ('шов ч.%d ↔ прочие' % p, (((pf[fa] == p) & (pf[fb] != p) & (pf[fb] != don)) | ((pf[fb] == p) & (pf[fa] != p) & (pf[fa] != don))))):
            if sel.sum() < 20:
                res[tag] = None
                continue
            d = mean[fa[sel]] - mean[fb[sel]]
            res[tag] = (int(sel.sum()), float(np.abs(d[:, 0]).mean()), float(np.abs(d[:, 1:]).mean()), float(np.linalg.norm(d, axis=1).mean()))
        print(f'  {nm}: ' + ' | '.join(f'{k}: ' + ('мало пар' if v is None else f'n={v[0]} |ΔL|={v[1]:.2f} |Δab|={v[2]:.2f} ΔE={v[3]:.2f}') for k, v in res.items()), flush=True)
    # --- (1) кадр ---------------------------------------------------------------------------------------
    ref = don if (kk & (tx.part == don)).sum() > 3000 else None
    if ref is None:
        cand = [q for q in range(40) if (tx.part == q).any() and (kk & (tx.part == q)).sum() > 3000]
        ref = max(cand, key=lambda q: (kk & (tx.part == q)).sum()) if cand else None
    best = None
    for az in (180.0, 0.0, 90.0, 270.0):
        m = indicator(runs['now']['geoms'], tx, [p], az)
        w = window(m)
        if w and (best is None or w[2] > best[2][2]):
            best = (az, m, w)
    if best is None:
        print('  окно для ч.%d не найдено' % p, flush=True)
        continue
    az_p, _, wp = best
    refbest = None
    if ref is not None:
        for az in (0.0, 180.0, 90.0, 270.0, 45.0, 315.0):
            m = indicator(runs['now']['geoms'], tx, [ref], az)
            w = window(m, size_list=(wp[2], 600, 500, 400, 300))
            if w and (refbest is None or w[2] > refbest[2][2]):
                refbest = (az, m, w)
    panels = []
    if refbest:
        az_r, _, wr = refbest
        img = TF.render_ortho(runs['now']['geoms'], runs['now']['tex_after'], az_r, res=RES)
        panels.append(('photo ref part %d (az %d)' % (ref, az_r), img[wr[0]:wr[0] + wr[2], wr[1]:wr[1] + wr[2]]))
    s = wp[2]
    for nm in ('now', 'v1'):
        img = TF.render_ortho(runs[nm]['geoms'], runs[nm]['tex_after'], az_p, res=RES)
        panels.append(('%s part %d (az %d)' % (nm, p, az_p), img[wp[0]:wp[0] + s, wp[1]:wp[1] + s]))
    sz = min(c.shape[0] for _, c in panels)
    panels = [(t, c[:sz, :sz]) for t, c in panels]
    k = 25.0 / max(float(np.gradient(gaussian_filter(panels[0][1].astype(float).mean(axis=2), 0.8), axis=1).std()), 1e-6)    # эталон → ±25 уровней
    row1 = np.concatenate([np.asarray(label(c, t)) for t, c in panels], axis=1)
    row2 = np.concatenate([np.asarray(label(np.repeat(emboss(c, k)[..., None], 3, axis=2), 'emboss L (conditional) ' + t.split(' (')[0])) for t, c in panels], axis=1)
    Image.fromarray(np.concatenate([row1, row2], axis=0)).save(f'{OUT}/seam/{sku[-12:]}-p{p}-zoom.png')
    print(f'  кадр: {OUT}/seam/{sku[-12:]}-p{p}-zoom.png ({row1.shape[1]}×{row1.shape[0] * 2}), окно {sz} px, эталон ч.{ref}', flush=True)
