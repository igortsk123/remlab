"""Класс рисунка бинов библиотеки верха (T-173/3 Ш3в): straight (ровное волокно), swirl (завитки/срез), flat (без направления: плита, войлок), blocks (паркет/торец).
По метрике: flat — сила волокна < flat_strength или семейство chipboard; swirl — доля блоков 16 px с градиентом, отклонённым > 25° от поперечного, ≥ swirl_share16; иначе straight.
blocks метрика не ловит (проверено на 28 бинах) — берётся из review.json (разметка глазами по листу, с датой и источником) и поверх метрики.
Использование: python3 lib_pattern.py <library.json> <raw_dir> <rules.json> <review.json> [--montage out.png]"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

LIB, RAW, RULES, REVIEW = sys.argv[1:5]
R = json.load(open(RULES, encoding="utf-8"))["pattern"]["classify"]
review = json.load(open(REVIEW, encoding="utf-8"))["classes"]
lib = json.load(open(LIB, encoding="utf-8"))


def swirl_share(path: str, axis: str, B: int = 16) -> tuple:
    im = np.asarray(Image.open(path).convert("L").resize((512, 512), Image.BILINEAR), np.float64)
    if axis == "v":
        im = im.T
    gy, gx = np.gradient(im)
    dev, n = [], 0
    for by in range(0, 512, B):
        for bx in range(0, 512, B):
            a, b, c = (gx[by:by + B, bx:bx + B] ** 2).sum(), (gy[by:by + B, bx:bx + B] ** 2).sum(), (gx * gy)[by:by + B, bx:bx + B].sum()
            if a + b < 1e-6 or np.sqrt((a - b) ** 2 + 4 * c * c) / (a + b) < R["min_coh"]:
                continue
            dev.append(abs(np.pi / 2 - abs(0.5 * np.arctan2(2 * c, a - b))))
    return (float(np.mean(np.array(dev) > np.deg2rad(25))) if dev else 0.0), len(dev)


tiles = []
for k, v in lib["items"].items():
    sw, n = swirl_share(os.path.join(RAW, k, "diff.jpg"), v.get("grain_axis") or "u")
    if v.get("family") == "chipboard" or v.get("grain_strength", 0.0) < R["flat_strength"]:
        c = "flat"
    elif sw >= R["swirl_share16"]:
        c = "swirl"
    else:
        c = "straight"
    v["pattern_metrics"] = {"swirl_share16": round(sw, 3), "n_blocks": n}
    v["pattern_class_metric"] = c
    if k in review:
        v["pattern_class"], v["pattern_class_source"] = review[k], "review.json (глаз)"
    else:
        v["pattern_class"], v["pattern_class_source"] = c, "метрика"
    tiles.append((k, v["pattern_class"]))
json.dump(lib, open(LIB, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print({c: sum(1 for _, x in tiles if x == c) for c in sorted(set(x for _, x in tiles))})
if "--montage" in sys.argv:
    out = sys.argv[sys.argv.index("--montage") + 1]
    n, c, S = len(tiles), 7, 220
    sheet = Image.new("RGB", (c * S, ((n + c - 1) // c) * (S + 18)), "white")
    dr = ImageDraw.Draw(sheet)
    for i, (k, cl) in enumerate(tiles):
        t = Image.open(os.path.join(RAW, k, "diff.jpg")).convert("RGB").resize((S, S))
        x, y = (i % c) * S, (i // c) * (S + 18)
        sheet.paste(t, (x, y + 18))
        dr.text((x + 3, y + 2), f"{k} {cl}", fill="black")
    sheet.save(out)
