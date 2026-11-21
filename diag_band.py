"""Ш6: почему при заёме (wholepart) band_ratio ~0,1 при spec_dist ~0,1–0,3? Сравнить энергию полосы (МАД-σ DoG яркости в масштабе поверхности — как в мерке) у НАСТОЯЩЕЙ ткани части-мишени и у настоящей ткани её доноров (известные тексели, окно эрозии 2).
Если полоса донора сама ≈0,1 от мишени — заём работает правильно, а полоса мишени — не ткань (складки/макро тень); если ≈1 — заём теряет амплитуду (баг переноса)."""
import json
import os
import sys

W = os.path.expanduser('~/remlab-logs/t182-1121/tools/scout/salad/trellis')
for q in (W, W + '/..', W + '/../..', W + '/../../stablegen'):
    sys.path.insert(0, q)
import numpy as np
from scipy.ndimage import binary_erosion
import tex_fill as TF
import tex_fill_blind as BL
import tex_fill_hidden_visible as HV

FZ = os.path.expanduser('~/remlab-logs/t182-1121/blind-v3/frozen')
fz = json.load(open(FZ + '/frozen.json'))
Z = np.load(FZ + '/masks.npz')
R = TF.RULES['trellis_relief']
borrowed = {}
for l in open(os.path.expanduser('~/remlab-logs/t182-1121/blind-v3/blind-borrow.jsonl')):
    r = json.loads(l)
    if r.get('mirror') is False or 'sku' not in r:
        continue
    borrowed[r['sku']] = r.get('borrowed_from')
for it in fz['items']:
    md = (it.get('modes') or {}).get('wholepart') or {}
    if 'eval_sha256' not in md:
        print('==', it['sku'], 'wholepart нет:', md.get('skipped'), flush=True)
        continue
    sku, part = it['sku'], it['part']
    vis, npz, geoms, known, parts, txs = BL.load_item(it['root'], sku)
    labs = [TF.rgb2lab(np.asarray(g['tex']).reshape(-1, 3)).reshape(tx.T, tx.T, 3) for g, tx in zip(geoms, txs)]

    def band_of(p, mask_fn, ref_sp):
        vals = []
        for gi, tx in enumerate(txs):
            m = mask_fn(gi, tx)
            if m is None or m.sum() < 500:
                continue
            sp = float(np.median(TF.texel_spacing(tx)[tx.part == p])) if (tx.part == p).any() else ref_sp
            s_lo = float(np.clip(R['band_lo'] / sp, R['sigma_lo_min'], R['sigma_lo_max']))
            s_hi = float(np.clip(R['band_hi'] / sp, 2.0 * s_lo, R['sigma_hi_max']))
            vals.append((TF._mad_sigma(TF._band(labs[gi][..., 0], m, s_lo, s_hi)[0][m]), int(m.sum()), sp, s_lo, s_hi))
        return vals

    def tgt_mask(gi, tx):
        shp = (tx.T, tx.T)
        e_ = np.unpackbits(Z[f'{sku}|wholepart_eval|{gi}'])[:tx.T * tx.T].astype(bool).reshape(shp)
        return binary_erosion(e_, iterations=2)

    def don_mask(p):
        def f(gi, tx):
            pm = np.zeros(tx.T * tx.T, bool)
            pm[tx.ti[tx.part == p]] = True
            return binary_erosion(pm.reshape(tx.T, tx.T) & known[gi], iterations=2)
        return f
    bt = band_of(part, tgt_mask, 1.0)
    print(f'== {sku} · мишень ч.{part} · полоса настоящей ткани {[(round(v[0], 3), v[1], round(v[2], 4)) for v in bt]} (σ, текс., см/текс.)', flush=True)
    for q in it['donors']:
        bd = band_of(q, don_mask(q), 1.0)
        mark = ' ← взят в заём' if borrowed.get(sku) == q else ''
        rat = [round(a[0] / max(b[0], 1e-9), 3) for a, b in zip(bd, bt)] if bd and bt else None
        print(f'   донор ч.{q}: полоса настоящей ткани {[(round(v[0], 3), v[1], round(v[2], 4)) for v in bd]} → к мишени {rat}{mark}', flush=True)
