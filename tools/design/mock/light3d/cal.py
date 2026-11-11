"""T-20261111-22/2 правки (владелец TG 1666): числа яркости «эталон / было / стало».
   python .t22-cal.py <эталон.png> <папка кадров> [маска имён, по умолчанию -v6-1280-c1-]
Области — прямоугольники на кадре (x0, y0, x1, y1): камера вида фиксирована, меняется только свет.
- стена: чистая белая стена крупным куском; окно-стена / дальний угол: одна стена, перпендикулярная окну, у окна и у дальнего угла;
- пол; потолок (на эталоне не виден); пересвет: доля пикселей с каждым каналом >= 250 по кадру без окна (вида наружу) и кнопок;
- перепад: яркость Y «стена у окна» / «стена у дальнего угла»; тон — L* (0..100), теплота — b* (плюс — желтее)."""
import glob
import json
import os
import sys

import numpy as np
from PIL import Image

REF_REG = {
    "wall": [(1000, 100, 1300, 380)],
    "near": [(1800, 320, 1920, 480)],
    "far": [(890, 380, 990, 690)],
    "floor": [(960, 820, 1120, 1000)],
    "ceil": [],
    "skip": [(1000, 25, 1540, 90), (1150, 1060, 1390, 1125), (2255, 900, 2515, 1125), (595, 245, 665, 315), (1820, 0, 1920, 65),
             (20, 1070, 135, 1120), (2280, 0, 2546, 900)],
}
OUR_REG = {   # спальня v6, вид «Другой ракурс» (c1), холст 831×736: окно слева, стена со шкафом — перпендикулярно окну
    "wall": [(450, 60, 800, 240), (640, 240, 800, 360)],
    "near": [(95, 70, 150, 230)],
    "far": [(335, 70, 385, 280)],
    "floor": [(600, 600, 800, 720)],
    "ceil": [(150, 2, 350, 25)],
    "furn": [(300, 380, 560, 470)],   # серая ткань кровати — проверка «мебель не в черноте»
    "skip": [(0, 30, 100, 340)],
}


def lab(rgb):
    c = rgb / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = lin @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1), xyz[..., 1]


def pix(a, boxes):
    return np.concatenate([a[y0:y1, x0:x1].reshape(-1, 3) for x0, y0, x1, y1 in boxes]) if boxes else None


def measure(path, reg, scale=1.0):
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64)
    s = lambda bs: [tuple(int(v * scale) for v in b) for b in bs]
    out = {}
    for k in ("wall", "near", "far", "floor", "ceil", "furn"):
        p = pix(a, s(reg.get(k, [])))
        if p is None:
            out[k] = None
            continue
        L, Y = lab(p)
        out[k] = {"L": float(L[:, 0].mean()), "b": float(L[:, 2].mean()), "Y": float(Y.mean())}
    keep = np.ones(a.shape[:2], bool)
    for x0, y0, x1, y1 in s(reg["skip"]):
        keep[y0:y1, x0:x1] = False
    px = a[keep]
    out["over"] = float((px.min(1) >= 250).mean() * 100)
    out["Lall"] = float(lab(px)[0][:, 0].mean())
    out["ratio"] = out["near"]["Y"] / max(1e-6, out["far"]["Y"])
    return out


def row(name, m, ref=None):
    def f(v, r, fmt="{:.1f}"):
        if v is None:
            return "—"
        t = fmt.format(v)
        if r is not None and r != 0:
            t += f" ({(v - r) / abs(r) * 100:+.0f} %)"
        return t
    g = lambda m, k, q: m[k][q] if m and m.get(k) else None
    cells = [name,
             f(g(m, "wall", "L"), g(ref, "wall", "L")), f(g(m, "wall", "b"), None),
             f(g(m, "floor", "L"), g(ref, "floor", "L")), f(g(m, "ceil", "L"), None),
             f(m["over"], ref and ref["over"], "{:.2f}"), f(m["ratio"], ref and ref["ratio"], "{:.2f}"), f(m["Lall"], ref and ref["Lall"]),
             f(g(m, "furn", "L"), None)]
    return "| " + " | ".join(cells) + " |"


def err(m, ref):
    """Сумма отклонений от эталона (доли): стена, пол, перепад, весь кадр + теплота стены (b* выше 3 — штраф)."""
    e = [abs(m["wall"]["L"] - ref["wall"]["L"]) / ref["wall"]["L"], abs(m["floor"]["L"] - ref["floor"]["L"]) / ref["floor"]["L"],
         abs(m["ratio"] - ref["ratio"]) / ref["ratio"], abs(m["Lall"] - ref["Lall"]) / ref["Lall"]]
    return sum(e) + max(0.0, m["wall"]["b"] - 3) * 0.02


def overlay(path, reg, out):
    from PIL import ImageDraw
    im = Image.open(path).convert("RGB")
    d = ImageDraw.Draw(im)
    col = {"wall": "blue", "near": "orange", "far": "purple", "floor": "green", "ceil": "cyan", "skip": "red"}
    for k, bs in reg.items():
        for b in bs:
            d.rectangle(b, outline=col[k], width=4)
    im.save(out)


def main():
    ref_path, d = sys.argv[1], sys.argv[2]
    mask = sys.argv[3] if len(sys.argv) > 3 else "-v6-1280-c1-"
    ref = measure(ref_path, REF_REG)
    if os.environ.get("OVERLAY"):
        overlay(ref_path, REF_REG, os.path.join(d, "boxes-ref.png"))
        first = sorted(glob.glob(os.path.join(d, f"*{mask}*.png")))[0]
        overlay(first, OUR_REG, os.path.join(d, "boxes" + mask.strip("-") + ".png"))
    print("| кадр | стена L* (откл.) | стена b* | пол L* | потолок L* | пересвет % | перепад окно/угол | весь кадр L* | ткань кровати L* | ошибка |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    print(row("эталон", ref)[:-2] + " | — | — |")
    res = {"ref": ref}
    for p in sorted(glob.glob(os.path.join(d, f"*{mask}*.png"))):
        m = measure(p, OUR_REG)
        m["err"] = err(m, ref)
        res[os.path.basename(p)] = m
        print(row(os.path.basename(p).replace(".png", ""), m, ref)[:-2] + f" | {m['err']:.3f} |")
    with open(os.path.join(d, "cal" + mask.strip("-") + ".json"), "w") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
