"""Ш6 × р.8: слой тона 06 (tone-l0) + 07 с tone_only. Три варианта на каждый товар: base (нынешний 06 + нынешний 07) | tone (06 р.8 + 07 tone_only, свой квилт) | tone_b (то же + заём borrow_texture).
Кадры: сверху-спереди (az 0, el 55) и сбоку-сверху (az 45, el 35): три колонки base|tone|tone_b, два ряда — <выход>/frames/<метка>-top-base_tone_toneb.png (без кириллицы в подписях).
Метрики по частям, где есть тон-только тексели: доля тон-только, дрейф среднего Lab (вход → итог), HP(L) в тон-только тексели (итог) к HP фото-известного той же части (если ≥2 %) — в вариантах tone и tone_b."""
import json
import os
import sys

W = os.path.expanduser('~/remlab-logs/t182-1121/tools/scout/salad/trellis')
for q in (W, W + '/..', W + '/../..', W + '/../../stablegen'):
    sys.path.insert(0, q)
import numpy as np
from PIL import Image
import tex_fill as TF

H = os.path.expanduser('~/remlab-logs')
TOP = H + '/t173-1121/top06/tonel0'
OUT = sys.argv[1]
ITEMS = [('e2eHD-1121', '112923_16411672175141188566'), ('e2eHD-1121', '114082_10587794773481498560'), ('e2eHD-batch-1121', '112923_1040167435642588653'),
         ('e2eHD-batch-1121', '112923_10551627698909366429'), ('e2eHD-1121', '99272_607007941975253599')]
HP = 6.0


def hp_std(L, mask):
    if mask.sum() < 50:
        return None
    bl, _ = TF._blur_norm(np.repeat(L[..., None], 3, axis=2), mask, HP)
    return float((L - bl[..., 0])[mask].std())


def load_known(d):
    return [np.asarray(Image.open(d + '/known.png').convert('L')) > 127]


os.makedirs(OUT + '/frames', exist_ok=True)
for root, sku in ITEMS:
    R = f'{H}/{root}/{sku}'
    V6 = R + '/06-visible'
    T6 = f'{TOP}/{sku}/06-visible'
    if not os.path.exists(T6 + '/visible.glb'):
        print(f'== {sku}: нет {T6}', flush=True)
        continue
    runs = {}
    for nm, vis, cfg in (('base', V6, {'erode_known': 0}), ('tone', T6, {'erode_known': 0}), ('tone_b', T6, {'erode_known': 0, 'borrow_texture': True})):
        runs[nm] = TF.run_stage(OUT + '/' + nm, sku, vis + '/visible.glb', known=load_known(vis), cfg=cfg, prev_dir=vis, parts_npz=R + '/03-parts/parts.npz')
    to = TF.load_tone_only_png(T6)
    print(f'== {sku}: тон-только {int(to[0].sum()) if to else 0} текс.; tone_only в отчёте: {runs["tone"]["report"].get("tone_only_texels")}', flush=True)
    r0 = runs['tone']
    g = r0['geoms'][0]
    tx = TF.Tex(g, np.asarray(g['V'], float), TF._grid(g), r0['parts'][0])
    T = tx.T
    kk = r0['known'][0].reshape(-1)[tx.ti]
    tt = to[0].reshape(-1)[tx.ti] if to else np.zeros(len(tx.ti), bool)
    Lin = TF.rgb2lab(np.asarray(r0['tex_before'][0]).reshape(-1, 3)).reshape(T, T, 3)
    for p in sorted(int(x) for x in r0['report']['parts']):
        sel = tx.part == p
        n_t = int((sel & tt).sum())
        if n_t < 500:
            continue
        mt = np.zeros(T * T, bool); mt[tx.ti[sel & tt]] = True; mt = mt.reshape(T, T)
        mk = np.zeros(T * T, bool); mk[tx.ti[sel & kk]] = True; mk = mk.reshape(T, T)
        hk = hp_std(Lin[..., 0], mk) if mk.sum() >= 0.02 * sel.sum() else None
        row = [f'  ч.{p}: тон-только {n_t} ({100 * n_t / max(sel.sum(), 1):.0f} % части), известно {100 * (sel & kk).sum() / max(sel.sum(), 1):.0f} %, HP фото {None if hk is None else round(hk, 2)}']
        for nm in ('tone', 'tone_b'):
            la = TF.rgb2lab(np.asarray(runs[nm]['tex_after'][0]).reshape(-1, 3)).reshape(T, T, 3)
            drift = np.abs(la[mt].mean(axis=0) - Lin[mt].mean(axis=0)).max()
            h = hp_std(la[..., 0], mt)
            row.append(f'{nm}: дрейф среднего Lab {drift:.2f}, HP тона {None if h is None else round(h, 2)}' + ('' if not (h and hk) else f' ({100 * h / hk:.0f} % от фото)') + (f', заём {runs[nm]["report"].get("borrowed", {}).get(p)}' if nm == 'tone_b' else ''))
        print(' · '.join(row), flush=True)
    rows = []
    for az, el in ((0.0, 55.0), (45.0, 35.0)):
        ims = [Image.fromarray(TF.render_ortho(runs[nm]['geoms'], runs[nm]['tex_after'], az, elevation=el)).convert('RGB') for nm in ('base', 'tone', 'tone_b')]
        rows.append(np.concatenate([np.asarray(i) for i in ims], axis=1))
    Image.fromarray(np.concatenate(rows, axis=0)).save(f'{OUT}/frames/{sku[-12:]}-top-base_tone_toneb.png')
    for nm, r in runs.items():
        m = (r['check'].get('metrics') or {})
        gv = lambda k: (m.get(k) or {}).get('value')
        print(f'  {nm}: passed {r["check"]["passed"]} · ΔE перёд/зад {gv("dE00_front_back")} · ступени {gv("filled_faces_step_pct")} % · empty {gv("empty_pct")} · far_excess {gv("far_excess_pct")}', flush=True)
