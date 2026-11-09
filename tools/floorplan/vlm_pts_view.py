#!/usr/bin/env python3
"""Точки VLM (сетка 0–1000) поверх листа — проверить глазами (T-20261109-03).
  python tools/floorplan/vlm_pts_view.py <план> <raw-ответ.txt> <выход.png> [ключ списка=spaces]"""
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vlm  # noqa: E402

plan, raw, out = sys.argv[1:4]
key = sys.argv[4] if len(sys.argv) > 4 else 'spaces'
gold = json.loads((vlm.HERE / 'gold' / f'{plan}.json').read_text())
im = cv2.imread(str(vlm.INPUTS / gold['image']))
H, W = im.shape[:2]
d = vlm.parse(Path(raw).read_text()) or {}
for s in d.get(key, []):
    x, y = s['pt'][0] * W / 1000, s['pt'][1] * H / 1000
    cv2.circle(im, (int(x), int(y)), 6, (0, 0, 255), -1)
    cv2.putText(im, s['name'][:12], (int(x) + 7, int(y) + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 200), 1, cv2.LINE_AA)
for g in gold['rooms']:
    cv2.circle(im, tuple(int(v) for v in g['pt']), 5, (0, 160, 0), -1)
cv2.imwrite(out, im)
