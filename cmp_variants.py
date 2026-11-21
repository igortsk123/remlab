"""Ш6: сравнение «сейчас | вариант 1 (borrow_texture) | вариант 2 (trellis_relief: HF черновика TRELLIS) » на частях БЕЗ чистых блоков (none) на 5 формах.
Для каждой none-части: HP(L) зада (неизвестные, не зеркало) и расстояние спектров (окно 16) к «чистой ткани фото» — известным текселям части-эталона (та же роль, ближайший тон, известного ≥2 %, не узорная).
Кадры зада: <выход>/frames/<метка>-zad-now_v1_v2.png (подписи латиницей: PIL рисует кириллицу квадратами)."""
import json
import os
import sys

W = os.path.expanduser('~/remlab-logs/t182-1121/tools/scout/salad/trellis')
for q in (W, W + '/..', W + '/../..', W + '/../../stablegen'):
    sys.path.insert(0, q)
import numpy as np
from PIL import Image, ImageDraw
import tex_fill as TF
import tex_coverage as TC
import tex_fill_hidden_visible as HV

H = os.path.expanduser('~/remlab-logs')
OUT = sys.argv[1]
DR = os.path.expanduser('~/remlab-logs/mesh-models-1118/trellis2')
HP = 6.0
ITEMS = [('e2eHD-1121', '99272_607007941975253599'), ('e2eHD-1121', '114082_10587794773481498560'), ('e2eHD-1121', '112923_16411672175141188566'),
         ('e2eHD-batch-1121', '112923_1040167435642588653'), ('e2eHD-batch-1121', '112923_10551627698909366429')]


def hp_std(L, mask):
    if mask.sum() < 50:
        return None
    bl, _ = TF._blur_norm(np.repeat(L[..., None], 3, axis=2), mask, HP)
    return float((L - bl[..., 0])[mask].std())


os.makedirs(OUT + '/frames', exist_ok=True)
summary = []
for root, sku in ITEMS:
    R = f'{H}/{root}/{sku}'
    known = [np.asarray(Image.open(R + '/06-visible/known.png').convert('L')) > 127]
    runs = {}
    for nm, cfg, dg in (('now', {'erode_known': 0}, None), ('v1', {'erode_known': 0, 'borrow_texture': True}, None),
                        ('v2', {'erode_known': 0, 'source': 'trellis_relief'}, DR + f'/{sku}-1024-42-0.glb')):
        if nm == 'v2' and not os.path.exists(dg):
            continue
        runs[nm] = TF.run_stage(OUT + '/' + sku + '-' + nm, sku, R + '/06-visible/visible.glb', known=known, cfg=cfg, draft_glb=dg, prev_dir=R + '/06-visible', parts_npz=R + '/03-parts/parts.npz')
    r0 = runs['now']
    g = r0['geoms'][0]
    tx = TF.Tex(g, np.asarray(g['V'], float), TF._grid(g), r0['parts'][0])
    T = tx.T
    kk = r0['known'][0].reshape(-1)[tx.ti]
    mir = None
    rep0 = r0['report']
    ts = rep0.get('texture_src', {})
    none_parts = [int(p) for p, v in ts.items() if v == 'none' and (tx.part == int(p)).sum() > 20000]
    roles = (r0['report'].get('part_class') or {})
    Lb = TF.rgb2lab(np.asarray(r0['tex_before'][0]).reshape(-1, 3))[:, 0].reshape(T, T)
    tone = {int(p): np.asarray(v['mean_lab']) for p, v in rep0['parts'].items()}
    cleanref = [int(p) for p in rep0['parts'] if not rep0['parts'][p]['pattern'] and (tx.part == int(p)).sum() and (kk & (tx.part == int(p))).sum() / (tx.part == int(p)).sum() >= 0.02]
    print(f'== {sku}: none-части {none_parts}; эталонов {cleanref}', flush=True)
    rows = {}
    for p in none_parts:
        ref = min(cleanref, key=lambda q: float(np.linalg.norm(tone[p] - tone[q]))) if cleanref else None
        mu = np.zeros(T * T, bool); mu[tx.ti[(tx.part == p) & ~kk]] = True; mu = mu.reshape(T, T)
        mr = None
        if ref is not None:
            mr = np.zeros(T * T, bool); mr[tx.ti[(tx.part == ref) & kk]] = True; mr = mr.reshape(T, T)
        sr = HV.spec_signature(Lb, mr, np.random.RandomState(3), 16, 24) if mr is not None else None
        hr = hp_std(Lb, mr) if mr is not None else None
        for nm, r in runs.items():
            La = TF.rgb2lab(np.asarray(r['tex_after'][0]).reshape(-1, 3))[:, 0].reshape(T, T)
            h = hp_std(La, mu)
            sp = HV.spec_signature(La, mu, np.random.RandomState(3), 16, 24)
            dist = None if sp is None or sr is None else float(np.mean(np.abs(sp - sr)))
            rows[(p, nm)] = (h, hr, dist)
            print(f'  ч.{p} эталон ч.{ref} · {nm}: HP зада {h if h is None else round(h, 2)} · HP чистой ткани фото {hr if hr is None else round(hr, 2)} · отношение {"—" if not h or not hr else str(round(100 * h / hr)) + " %"} · спектр-расстояние {dist if dist is None else round(dist, 3)} · заём {r["report"].get("borrowed", {}).get(p)}', flush=True)
    ims = []
    for nm in ('now', 'v1', 'v2'):
        if nm in runs:
            im = Image.fromarray(TF.render_ortho(runs[nm]['geoms'], runs[nm]['tex_after'], 180.0, elevation=0.0)).convert('RGB')
            d = ImageDraw.Draw(im); d.rectangle((10, 10, 150, 50), fill=(255, 255, 255)); d.text((20, 20), nm, fill=(0, 0, 0))
            ims.append(im)
    if ims:
        sheet = Image.new('RGB', (sum(i.width for i in ims) + 12 * (len(ims) - 1), ims[0].height), (255, 255, 255))
        x = 0
        for i in ims:
            sheet.paste(i, (x, 0)); x += i.width + 12
        sheet.save(f'{OUT}/frames/{sku[-12:]}-zad-now_v1_v2.png')
    for nm, r in runs.items():
        m = (r['check'].get('metrics') or {})
        gv = lambda k: (m.get(k) or {}).get('value')
        print(f'  {nm}: passed {r["check"]["passed"]} · ΔE перёд/зад {gv("dE00_front_back")} · ступени {gv("filled_faces_step_pct")} % · empty {gv("empty_pct")} · far_excess {gv("far_excess_pct")} · {r["check"].get("seconds")} с', flush=True)
