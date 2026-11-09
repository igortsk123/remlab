#!/usr/bin/env python3
"""Кадры «исходник | 3D» (T-20261109-02): кусок листа по bbox панели рядом с серым 3D (сверху и под углом).
  python tools/floorplan/stitch.py <run-папка с A/B/C и 3d/> <out-папка>"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

INPUTS = Path('/home/pakar/remlab-logs/floorplan-bench/inputs')


def fit_h(img, h):
    return cv2.resize(img, (max(1, round(img.shape[1] * h / img.shape[0])), h), interpolation=cv2.INTER_AREA)


def label(img, text):
    out = cv2.copyMakeBorder(img, 34, 0, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    cv2.putText(out, text, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (40, 40, 40), 2, cv2.LINE_AA)
    return out


def main(run, out):
    run, out = Path(run), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for mp in sorted(run.glob('*/model-*.json')):
        m = json.loads(mp.read_text())
        plan, idx = m['plan'], mp.stem.split('-')[-1]
        if m.get('image'):                             # T-04: путь к исходнику — в модели (слепые планы без золота)
            src = cv2.imread(m['image'], cv2.IMREAD_COLOR)
        else:
            gold = json.loads((Path(__file__).resolve().parent / 'gold' / f'{plan}.json').read_text())
            src = cv2.imread(str(INPUTS / gold['image']), cv2.IMREAD_COLOR)
        x0, y0, x1, y1 = m['bbox_px']
        crop = src[max(0, y0):y1, max(0, x0):x1]
        H = 700
        tiles = [label(fit_h(crop, H), f'{plan} {m["panel"]}: source')]   # OpenCV-шрифт без кириллицы
        for v in ('top', 'oblique'):
            p = run / '3d' / f'3d-{plan}-{idx}-{v}.png'
            if p.exists():
                im = cv2.imread(str(p))
                ys, xs = np.nonzero((im < 250).any(axis=2))
                if len(ys):
                    pad = 10
                    im = im[max(0, ys.min() - pad):ys.max() + pad, max(0, xs.min() - pad):xs.max() + pad]
                tiles.append(label(fit_h(im, H), f'3D {v}'))
        gap = np.full((H + 34, 16, 3), 255, np.uint8)
        row = tiles[0]
        for t in tiles[1:]:
            row = np.hstack([row, gap, t])
        cv2.imwrite(str(out / f'side-{plan}-{idx}-{m["panel"]}.png'), row)
        print(out / f'side-{plan}-{idx}-{m["panel"]}.png', row.shape[1], 'x', row.shape[0])


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
