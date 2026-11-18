#!/usr/bin/env python3
"""Тест силуэта ковра (T-20261118-03/3): функция `rug_silhouette` живёт в `render_cycles.py` (там `import bpy`), поэтому достаём её по `ast`.
Запуск: `~/venvs/scout/bin/python tools/scout/cycles_probe/test_rug_silhouette.py`; с аргументом `--table` — таблица по реальным текстурам ковров."""
import ast
import glob
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def load():
    src = open(os.path.join(HERE, "render_cycles.py"), encoding="utf-8").read()
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "rug_silhouette")
    ns = {"np": np}
    exec(compile(ast.Module([fn], []), "render_cycles.py", "exec"), ns)
    return ns["rug_silhouette"]


def erode(m, steps):
    for _ in range(steps):
        t = m.copy()
        t[1:] &= m[:-1]
        t[:-1] &= m[1:]
        t[:, 1:] &= m[:, :-1]
        t[:, :-1] &= m[:, 1:]
        m = t
    return m


def ncomp(m):
    seen = np.zeros_like(m)
    n = 0
    for y, x in zip(*np.where(m)):
        if seen[y, x]:
            continue
        n += 1
        st = [(y, x)]
        seen[y, x] = 1
        while st:
            a, b = st.pop()
            for u, v in ((a + 1, b), (a - 1, b), (a, b + 1), (a, b - 1)):
                if 0 <= u < m.shape[0] and 0 <= v < m.shape[1] and m[u, v] and not seen[u, v]:
                    seen[u, v] = 1
                    st.append((u, v))
    return n


def test_inner_holes_filled_outer_background_kept():
    sil = load()
    m = np.zeros((60, 80), bool)
    m[10:50, 10:70] = True
    m[20:24, 30:34] = False                       # блик внутри ковра
    m[30, 40:60] = False                          # тонкая светлая полоса внутри
    s = sil(m)
    assert s[20:24, 30:34].all() and s[30, 40:60].all()           # дырки внутри — ковёр
    assert not s[:10].any() and not s[50:].any() and not s[:, :10].any() and not s[:, 70:].any()   # фон снаружи — фон
    assert s.sum() == 40 * 60


def test_background_notch_open_to_edge_stays_background():
    sil = load()
    m = np.ones((40, 40), bool)
    m[0:10, 18:22] = False                        # вырез, открытый к краю кадра (бахрома/угол) — фон
    s = sil(m)
    assert not s[0:10, 18:22].any() and s[10:, :].all()


def test_erosion_after_silhouette_does_not_shatter_rug():
    """Эрозия 10 шагов по силуэту: один кусок. По сырой маске с бликами (≈3 % дырок) — десятки клочков (так было)."""
    sil = load()
    rng = np.random.RandomState(1)
    m = np.ones((120, 160), bool)
    for _ in range(40):
        y, x = rng.randint(15, 105), rng.randint(15, 145)
        m[y:y + 2, x:x + 2] = False               # светлые блики внутри
    raw = ncomp(erode(m, 10))
    new = ncomp(erode(sil(m), 10))
    assert new == 1 and raw > 5, (raw, new)


def table():
    from PIL import Image
    sil = load()
    root = os.path.expanduser("~/remlab-logs/t63-1117/export2")
    seen = {}
    for f in sorted(glob.glob(root + "/*/tex/rug*.png")):
        a = np.asarray(Image.open(f).convert("RGB"), np.float32)
        key = hash(a.tobytes())
        seen.setdefault(key, (f, a))
    print("текстура | размер | светлота | маска, комп. после эрозии: было → стало | площадь после эрозии: было → стало")
    for f, a in seen.values():
        h, w, _ = a.shape
        corn = np.concatenate([a[:6, :6].reshape(-1, 3), a[:6, -6:].reshape(-1, 3), a[-6:, :6].reshape(-1, 3), a[-6:, -6:].reshape(-1, 3)])
        d = np.linalg.norm(a - np.median(corn, axis=0), axis=2)
        msk = d > 22
        if msk.mean() < 0.30:
            msk[:] = True
        ys, xs = np.where(msk)
        st = int(round(0.025 * (xs.max() - xs.min() + 1)))
        old, new = erode(msk, st), erode(sil(msk), st)
        name = "/".join(f.split("/")[-3:-2] + f.split("/")[-1:])
        print(f"{name:26s} | {w}x{h} | {a.mean():4.0f} | {ncomp(old):3d} → {ncomp(new):3d} | {old.mean() * 100:5.1f} % → {new.mean() * 100:5.1f} % (силуэт {sil(msk).mean() * 100:.1f} %)")


if __name__ == "__main__":
    if "--table" in sys.argv:
        table()
    else:
        n = 0
        for k, v in sorted(globals().items()):
            if k.startswith("test_") and callable(v):
                v()
                n += 1
        print(f"test_rug_silhouette: ок ({n})")
