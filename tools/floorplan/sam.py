#!/usr/bin/env python3
"""MobileSAM-путь стенда планировок (T-20261109-02/2): точка-подсказка = центр подписи комнаты из эталона →
маска комнаты → те же мерки (комнаты, слияния, LOO размеров по подписям). CPU, веса Apache-2.0
(github.com/ChaoningZhang/MobileSAM, `~/models/mobilesam/mobile_sam.pt`; пакет — `~/venvs/floorplan/lib`).

  python tools/floorplan/sam.py <A|B|C> <out-папка>
"""
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, os.path.expanduser('~/venvs/floorplan/lib'))
INPUTS = Path('/home/pakar/remlab-logs/floorplan-bench/inputs')
WEIGHTS = Path(os.path.expanduser('~/models/mobilesam/mobile_sam.pt'))


def main(plan, out):
    import torch
    from mobile_sam import SamPredictor, sam_model_registry
    import fpcore as fc
    torch.set_num_threads(4)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    gold = json.loads((HERE / 'gold' / f'{plan}.json').read_text())
    img = cv2.imread(str(INPUTS / gold['image']), cv2.IMREAD_COLOR)
    t0 = time.time()
    sam = sam_model_registry['vit_t'](checkpoint=str(WEIGHTS)).eval()
    pred = SamPredictor(sam)
    pred.set_image(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    t_enc = time.time() - t0
    rooms = [g for g in gold['rooms']]
    masks = []
    for g in rooms:
        ms, sc, _ = pred.predict(point_coords=np.array([g['pt']], float), point_labels=np.array([1]), multimask_output=True)
        # из трёх масок SAM берём самую уверенную, но не «весь лист» (≥ 25 % картинки — это фон/вытекание)
        # точка стоит на подписи → самая уверенная маска часто = буквы подписи; правило (env FP_SAM_PICK=largest):
        # самая большая из трёх, не касающаяся края листа и < 25 % картинки
        order = np.argsort(-sc)
        if os.environ.get('FP_SAM_PICK') == 'largest':
            ok = [i for i in range(len(ms)) if ms[i].mean() < 0.25 and not (ms[i][0].any() or ms[i][-1].any()
                  or ms[i][:, 0].any() or ms[i][:, -1].any())]
            k = max(ok, key=lambda i: ms[i].sum()) if ok else order[0]
        else:
            k = next((i for i in order if ms[i].mean() < 0.25), order[0])
        masks.append(ms[k].astype(np.uint8))
    t_all = time.time() - t0
    # слияния: две эталонные точки попали в одну маску (IoU > 0,5)
    req = [i for i, g in enumerate(rooms) if not g.get('optional')]
    merged = []
    for a_i, a in enumerate(req):
        for b in req[a_i + 1:]:
            inter = (masks[a] & masks[b]).sum()
            uni = (masks[a] | masks[b]).sum()
            if uni and inter / uni > 0.5:
                merged.append([rooms[a]['name'], rooms[b]['name']])
    fams = [0.0, 90.0]
    obs = []
    for i in req:
        g = rooms[i]
        if 'dims_m' not in g or masks[i].sum() < 50:
            continue
        if any(rooms[i]['name'] in m for m in merged):
            continue
        obs.append({'id': g['name'], 'dims': tuple(g['dims_m']), 'ext': fc.room_extents(masks[i], 0.0, True), 'angle': 0.0})
    fit = fc.fit_scale(obs) if obs else None
    ppm = 1 / fit['s'] if fit else None
    loo = fc.leave_one_out(obs) if len(obs) >= 3 else []
    # «вытекло»: маска касается края листа или больше подписанной площади вдвое
    leaks = []
    for i in req:
        g, m = rooms[i], masks[i]
        border = m[0].any() or m[-1].any() or m[:, 0].any() or m[:, -1].any()
        big = ppm and 'dims_m' in g and m.sum() / ppm / ppm > 2 * g['dims_m'][0] * g['dims_m'][1]
        if border or big:
            leaks.append(g['name'])
    ov = (img.astype(float) * 0.35 + 255 * 0.65).astype(np.uint8)
    rng = np.random.default_rng(7)
    for i, m in enumerate(masks):
        ov[m > 0] = (ov[m > 0] * 0.4 + rng.integers(100, 240, 3) * 0.6).astype(np.uint8)
        cv2.circle(ov, tuple(map(int, rooms[i]['pt'])), 5, (0, 0, 255), -1)
    cv2.imwrite(str(out / f'sam-{plan}.png'), ov)
    rep = {'plan': plan, 'rooms_gold': len(req), 'merged': merged, 'leaks': leaks,
           'found': len(req) - len({n for m in merged for n in m}) - len(leaks),
           'ppm': ppm and round(ppm, 2), 'loo': fc.loo_summary(loo) if loo else None,
           'loo_near': fc.loo_summary(loo, 'near') if loo else None,
           'loo_clean': fc.loo_summary(loo, 'near_clean') if loo else None,
           'sec_encode': round(t_enc, 1), 'sec_total': round(t_all, 1)}
    (out / f'sam-{plan}.json').write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=float))
    print(json.dumps(rep, ensure_ascii=False, default=float))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
