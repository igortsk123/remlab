"""T-182/Ш6 диагноз: почему зад гладкий при уже имеющемся quilt. По товару и части: известное, чем дана фактура (quilt/patch/none), пул чистых блоков, размер блока,
частота «пикселей на см» поверхности, разброс высоких частот L: фото-часть | зад после заливки (в памяти) | зад в готовом GLB (после сжатия)."""
import os
import sys
import json

W = os.path.expanduser('~/remlab-logs/t182-1121/tools/scout/salad/trellis')
for q in (W, W + '/..', W + '/../..', W + '/../../stablegen'):
    sys.path.insert(0, q)
import numpy as np
import tex_fill as TF
import tex_coverage as TC

H = os.path.expanduser('~/remlab-logs')
OUT = sys.argv[1]
ARGS = sys.argv[2:]          # корень:метка ...
HP = 6.0                     # σ размытия, пиксели: всё выше — «фактура»


def hp_std(L, mask):
    """разброс высокочастотной части L в маске (размытие с нормировкой по маске)."""
    if mask.sum() < 50:
        return None
    bl, _ = TF._blur_norm(np.repeat(L[..., None], 3, axis=2), mask, HP)
    d = (L - bl[..., 0])[mask]
    return float(d.std())


def dims_diag_cm(prod):
    pr = prod.get('params') or {}
    if isinstance(pr, str):
        import ast
        pr = ast.literal_eval(pr)
    import re
    v = []
    for key in ('Длина', 'Ширина', 'Высота'):
        val = 0.0
        for k, x in pr.items():
            if key in k and ('габарит' in k or k == key):               # «Размеры: Длина габаритная»: '373см' или просто 'Длина': '62'
                m = re.search(r'[\d]+(?:[.,]\d+)?', str(x))
                if m:
                    val = float(m.group(0).replace(',', '.'))
                    break
        v.append(val)
    return float(np.sqrt(sum(x * x for x in v)))


res = {}
for a in ARGS:
    root, sku = a.split(':')
    R = f'{H}/{root}/{sku}'
    prod = json.load(open(R + '/work/product.json'))
    diag = dims_diag_cm(prod)
    r = TF.run_stage(OUT + '/' + sku, sku, R + '/06-visible/visible.glb',
                     known=[np.asarray(__import__('PIL.Image', fromlist=['x']).open(R + '/06-visible/known.png').convert('L')) > 127],
                     cfg={'erode_known': 0}, prev_dir=R + '/06-visible', parts_npz=R + '/03-parts/parts.npz')
    rep = r['report']
    geoms, after, before = r['geoms'], r['tex_after'], r['tex_before']
    gl = TC.load_geoms(R + '/07-fill/filled.glb') if os.path.exists(R + '/07-fill/filled.glb') else None
    g = geoms[0]
    tx = TF.Tex(g, np.asarray(g['V'], float), TF._grid(g), r['parts'][0])
    T = tx.T
    kn = r['known'][0]
    kk = kn.reshape(-1)[tx.ti]
    sp = TF.texel_spacing(tx) * diag                   # см на тексель
    Lb = TF.rgb2lab(np.asarray(before[0]).reshape(-1, 3))[:, 0].reshape(T, T)
    La = TF.rgb2lab(np.asarray(after[0]).reshape(-1, 3))[:, 0].reshape(T, T)
    Lg = TF.rgb2lab(np.asarray(gl[0]['tex'])[..., :3].reshape(-1, 3))[:, 0].reshape(T, T) if gl is not None and np.asarray(gl[0]['tex']).shape[:2] == (T, T) else None
    sgn = np.where((tx.Q * tx.N).sum(1) >= 0, 1.0, -1.0)
    Nout = tx.N * sgn[:, None]
    qi = rep.get('quilt_info', {})
    nf_ = Nout[kk].mean(axis=0)
    nf_ /= max(np.linalg.norm(nf_), 1e-9)
    ts = rep.get('texture_src', {})
    print(f'== {sku} · {prod.get("name")} · диагональ {diag:.0f} см · карта {T}×{T} · no_patch {rep["no_patch"]} · quilt {rep.get("quilt")} · зеркало {rep["mirrored_pct"]} %')
    up = Nout[:, 1]
    print('  часть | тексели | известных % | верх (up>0,7) % текс. | известно на верхе % | назад (n·ось<-0,3) % | фактура | пул | блок | пикс/см | HP(L) фото | HP зад в памяти | HP зад в GLB | зад/фото')
    for p in sorted(rep['parts'], key=int):
        sel = tx.part == int(p)
        if sel.sum() < 200:
            continue
        mk = np.zeros(T * T, bool); mk[tx.ti[sel & kk]] = True
        mu = np.zeros(T * T, bool); mu[tx.ti[sel & ~kk]] = True
        mk, mu = mk.reshape(T, T), mu.reshape(T, T)
        h_ph = hp_std(Lb, mk)
        h_af = hp_std(La, mu)
        h_gl = hp_std(Lg, mu) if Lg is not None else None
        ppc = 1.0 / max(float(np.median(sp[sel])), 1e-9)
        info = qi.get(str(p)) or qi.get(int(p)) or {}
        f = lambda v: '—' if v is None else f'{v:.2f}'
        top = sel & (up > 0.7)
        topk = f'{100 * (top & kk).sum() / max(top.sum(), 1):.0f}' if top.sum() else '—'
        ratio = '—' if (h_ph in (None, 0) or h_af is None) else f'{100 * h_af / h_ph:.0f} %'
        print(f'  {p} | {int(sel.sum())} | {100 * (sel & kk).sum() / sel.sum():.0f} | {100 * top.sum() / sel.sum():.0f} | {topk} | {100 * (sel & (Nout @ nf_ < -0.3)).sum() / sel.sum():.0f} | {ts.get(int(p), ts.get(p, "?"))} | {info.get("pool", "—")} | {info.get("block", "—")} | {ppc:.1f} | {f(h_ph)} | {f(h_af)} | {f(h_gl)} | {ratio}')
    res[sku] = {'no_patch': rep['no_patch'], 'texture_src': ts, 'quilt_info': qi}
json.dump(res, open(OUT + '/diag182.json', 'w'), ensure_ascii=False, indent=1)
