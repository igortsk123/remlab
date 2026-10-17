#!/usr/bin/env python3
"""ВЕРНОСТЬ ЦВЕТА ТОВАРА НА ФОТО НЕЙРОСЕТИ (план demo-14, критика Codex 17.10). Для каждого товара варианта: область товара на
фото нейросети — по карте предметов той же позы камеры (`tools/flat3d/cam-masks.mjs`, лучи по коробкам мебели; маска сжата на ~10 %,
чтобы края и соседи не попали), эталон — фото товара из магазина без фона (`fg_mask`). Сравнение — медиана Lab области против
основного тона эталона (самый крупный кластер Lab), ΔE2000; плюс расстояние Хеллингера между гистограммами a*b*.
Гейт на товар (Codex): ΔE00 ≤ 8 — ок, 8–12 — предупреждение, > 12 — брак; лист принят, если ≥ 80 % видимых товаров ок
и ни одного крупного (диван, кресло, ковёр, тумба, столик, стол) с ΔE00 > 12.

Функции — для `tools/ops/bench-refs.py`; сам по себе:
    ~/venvs/scout/bin/python refs_check.py --selftest
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import urllib.request

import cv2
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
OK_DE, WARN_DE = 8.0, 12.0
BIG_ROLES = {'диван', 'кресло', 'ковёр', 'тв-тумба', 'столик', 'стол обеденный', 'комод', 'стеллаж', 'витрина'}
MIN_PX = 600          # видимых пикселей товара в виде (на 2048 px по ширине) — меньше: не меряем
# МЕРЯЕМ ТОЛЬКО СПЛОШНОЕ (замер 17.10): у торшера, стульев и стеллажей коробка карты шире силуэта — в неё попадает стена за ними;
# у столов — только верхние 40 % области (столешница), ножки тонкие
MEASURE_ROLES = {'диван', 'кресло', 'ковёр', 'тв-тумба', 'комод', 'банкетка', 'пуф', 'столик', 'стол обеденный', 'тумба'}
TOP_ONLY = {'столик', 'стол обеденный'}


def base_role(role: str) -> str:
    return ' '.join(w for w in str(role or '').split() if not w.isdigit())


def to_lab(rgb: np.ndarray) -> np.ndarray:
    """RGB uint8 (…×3) → CIE Lab float (L 0…100, a/b ≈ −128…127), через OpenCV (D65, sRGB)."""
    a = np.asarray(rgb, np.float32).reshape(-1, 1, 3) / 255.0
    return cv2.cvtColor(a, cv2.COLOR_RGB2LAB).reshape(-1, 3)


def lab_hex(lab) -> str:
    a = np.array(lab, np.float32).reshape(1, 1, 3)
    r, g, b = (np.clip(cv2.cvtColor(a, cv2.COLOR_LAB2RGB).reshape(3), 0, 1) * 255).round().astype(int)
    return f'#{r:02X}{g:02X}{b:02X}'


def ciede2000(l1, l2) -> float:
    """ΔE2000 (Sharma 2005) двух цветов Lab."""
    L1, a1, b1 = map(float, l1)
    L2, a2, b2 = map(float, l2)
    C1, C2 = np.hypot(a1, b1), np.hypot(a2, b2)
    Cb = (C1 + C2) / 2
    G = 0.5 * (1 - np.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dLp, dCp = L2 - L1, C2p - C1p
    if C1p * C2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    else:
        dhp = h2p - h1p - 360 if h2p > h1p else h2p - h1p + 360
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dhp / 2))
    Lbp, Cbp = (L1 + L2) / 2, (C1p + C2p) / 2
    if C1p * C2p == 0:
        hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbp = (h1p + h2p) / 2
    else:
        hbp = (h1p + h2p + 360) / 2 if h1p + h2p < 360 else (h1p + h2p - 360) / 2
    T = (1 - 0.17 * np.cos(np.radians(hbp - 30)) + 0.24 * np.cos(np.radians(2 * hbp))
         + 0.32 * np.cos(np.radians(3 * hbp + 6)) - 0.20 * np.cos(np.radians(4 * hbp - 63)))
    dth = 30 * np.exp(-((hbp - 275) / 25) ** 2)
    Rc = 2 * np.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7))
    Sl = 1 + 0.015 * (Lbp - 50) ** 2 / np.sqrt(20 + (Lbp - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cbp, 1 + 0.015 * Cbp * T
    Rt = -np.sin(np.radians(2 * dth)) * Rc
    return float(np.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh)))


def fg_mask(img: Image.Image, thr: int = 236) -> np.ndarray:
    """Маска товара на фото магазина: светлый фон, связанный с краями кадра, — прочь (белое ВНУТРИ товара остаётся)."""
    a = np.asarray(img.convert('RGB'))
    light = (a.min(axis=2) >= thr).astype(np.uint8)
    n, lab = cv2.connectedComponents(light, connectivity=4)
    edge = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])).tolist())
    bg = np.isin(lab, [k for k in edge if k != 0 or light[0, 0]]) & (light > 0)
    fg = ~bg
    if fg.sum() < 50:
        fg = np.ones(a.shape[:2], bool)
    return cv2.erode(fg.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)


def ref_colour(img: Image.Image) -> dict:
    """Основной тон товара: самый крупный кластер Lab по маске (тени, ножки и надписи — в других кластерах), доля — уверенность."""
    im = img.convert('RGB')
    im.thumbnail((256, 256))
    m = fg_mask(im)
    lab = to_lab(np.asarray(im)[m])
    if len(lab) < 30:
        return {'lab': None}
    k = 3 if len(lab) > 300 else 1
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    _, labels, centers = cv2.kmeans(lab.astype(np.float32), k, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.ravel(), minlength=k)
    i = int(counts.argmax())
    dom = np.median(lab[labels.ravel() == i], axis=0)
    return {'lab': dom.tolist(), 'hex': lab_hex(dom), 'confidence': round(float(counts[i] / counts.sum()), 2), 'all_lab': lab}


def hellinger(lab1: np.ndarray, lab2: np.ndarray, bins: int = 16) -> float:
    rng = [[-60, 60], [-60, 60]]
    h1, _, _ = np.histogram2d(lab1[:, 1], lab1[:, 2], bins=bins, range=rng)
    h2, _, _ = np.histogram2d(lab2[:, 1], lab2[:, 2], bins=bins, range=rng)
    h1, h2 = h1 / max(h1.sum(), 1), h2 / max(h2.sum(), 1)
    return float(np.sqrt(max(0.0, 1 - np.sum(np.sqrt(h1 * h2)))))


def split_sheet(sheet: Image.Image) -> list:
    """Лист двух видов → [(вид, box)]: альбомный — друг под другом, полоса горизонтальная; вертикальный — бок о бок."""
    a = np.asarray(sheet.convert('RGB')).astype(int)
    mg = (a[..., 0] > 170) & (a[..., 2] > 170) & (a[..., 1] < 110)
    rows, cols = np.where(mg.mean(axis=1) > 0.5)[0], np.where(mg.mean(axis=0) > 0.5)[0]
    if len(rows) >= 8:
        return [(0, (0, 0, sheet.width, int(rows.min()))), (1, (0, int(rows.max()) + 1, sheet.width, sheet.height))]
    if len(cols) >= 8:
        return [(0, (0, 0, int(cols.min()), sheet.height)), (1, (int(cols.max()) + 1, 0, sheet.width, sheet.height))]
    h = sheet.height // 2       # полоса закрашена моделью — режем пополам (так режет и `_split_pair`)
    return [(0, (0, 0, sheet.width, h)), (1, (0, h, sheet.width, sheet.height))]


def item_masks(room: dict, items: list, cams: list, w: int, h: int, no_tv: bool = True) -> np.ndarray:
    """Карта предметов для каждой камеры (cams × h × w, номер в `items` или −1) — `tools/flat3d/cam-masks.mjs`."""
    with tempfile.TemporaryDirectory() as td:
        jp, bp = os.path.join(td, 'job.json'), os.path.join(td, 'mask.bin')
        json.dump({'room': room, 'items': items, 'cams': cams, 'w': w, 'h': h, 'noTv': no_tv}, open(jp, 'w'), ensure_ascii=False)
        r = subprocess.run(['bash', '-c', f'. "{ROOT}/tools/ops/node-env.sh" >/dev/null 2>&1; node "{ROOT}/tools/flat3d/cam-masks.mjs" "{jp}" "{bp}"'],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise RuntimeError(f'карта предметов не построилась: {(r.stderr or r.stdout)[-300:]}')
        m = np.fromfile(bp, dtype='<i2').reshape(len(cams), h, w)
        solo = json.load(open(bp + '.json'))['solo']
        return m, solo


def views_of(out_sheet: Image.Image) -> list:
    return [out_sheet.crop(box).convert('RGB') for _, box in split_sheet(out_sheet)]


VIS_MIN = 0.5        # видно меньше половины предмета (заслонён) — не меряем: в коробках карты ажурные стулья и столы сплошные


def measure(views: list, masks: np.ndarray, items: list, refs: dict, solo: list | None = None) -> list:
    """Виды фото нейросети (лист — через `views_of`, готовые кадры C1/C2 — как есть) → строки по товару и виду: ΔE00 медианы
    области товара против основного тона эталона, Хеллингер, вердикт."""
    rows = []
    for k, view in enumerate(views):
        if k >= len(masks):
            break
        view = view.convert('RGB')
        mk = masks[k]
        mk_r = cv2.resize(mk.astype(np.int16), view.size, interpolation=cv2.INTER_NEAREST)
        va = np.asarray(view)
        for i, it in enumerate(items):
            ref = refs.get(it.get('sku_name') or it.get('name') or it['role'])
            if not ref or ref.get('lab') is None:
                continue
            if base_role(it['role']) not in MEASURE_ROLES:
                continue
            if solo is not None and (mk == i).sum() < VIS_MIN * float((solo[k] or {}).get(str(i), 0) or 0):
                continue
            m = (mk_r == i).astype(np.uint8)
            if m.sum() < MIN_PX:
                continue
            if base_role(it['role']) in TOP_ONLY:
                ys = np.where(m.any(axis=1))[0]
                m[int(ys.min() + 0.4 * (ys.max() - ys.min() + 1)):] = 0
            er = max(2, int(0.05 * np.sqrt(m.sum())))      # сжать ≈ на 10 % по площади: края и соседи не в замер
            m2 = cv2.erode(m, np.ones((er, er), np.uint8)).astype(bool)
            if m2.sum() < MIN_PX // 3:
                continue
            lab = to_lab(va[m2])
            med = np.median(lab, axis=0)
            de = ciede2000(med, ref['lab'])
            rows.append({'view': k + 1, 'n': i + 1, 'role': it['role'], 'name': it.get('sku_name') or '', 'px': int(m2.sum()),
                         'out_hex': lab_hex(med), 'ref_hex': ref['hex'], 'ref_conf': ref['confidence'], 'de': round(de, 1),
                         'hell': round(hellinger(lab, ref['all_lab']), 2),
                         'verdict': 'ok' if de <= OK_DE else 'warn' if de <= WARN_DE else 'fail'})
    return rows


def summary(rows: list) -> dict:
    """Итог листа: доля ок (по товару — лучший из видов), крупные с браком, средний ΔE."""
    best = {}
    for r in rows:
        k = r['n']
        if k not in best or r['de'] < best[k]['de']:
            best[k] = r
    vals = list(best.values())
    ok = sum(1 for r in vals if r['verdict'] == 'ok')
    big_fail = [r['role'] for r in vals if r['verdict'] == 'fail' and base_role(r['role']) in BIG_ROLES]
    return {'items': len(vals), 'ok': ok, 'share_ok': round(ok / len(vals), 2) if vals else 0.0,
            'mean_de': round(float(np.mean([r['de'] for r in vals])), 1) if vals else None, 'big_fail': big_fail,
            'pass': bool(vals) and ok / len(vals) >= 0.8 and not big_fail}


def fetch(url: str) -> Image.Image:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 remlab-refs'})
    with urllib.request.urlopen(req, timeout=40) as r:
        return Image.open(io.BytesIO(r.read())).convert('RGB')


def selftest() -> int:
    fails = 0

    def check(name, cond):
        nonlocal fails
        print(('OK   ' if cond else 'FAIL ') + name)
        fails += 0 if cond else 1
    # эталонные пары Sharma 2005 (табл. 1): ΔE00 = 2.0425, 2.8615, 3.4412
    for l1, l2, want in (((50, 2.6772, -79.7751), (50, 0, -82.7485), 2.0425), ((50, 3.1571, -77.2803), (50, 0, -82.7485), 2.8615),
                         ((50, 2.8361, -74.0200), (50, 0, -82.7485), 3.4412)):
        check(f'ΔE00 по таблице Sharma ≈ {want}', abs(ciede2000(l1, l2) - want) < 1e-3)
    check('ΔE00 одного цвета — 0', ciede2000((60, 10, 10), (60, 10, 10)) < 1e-9)
    im = Image.new('RGB', (100, 100), (255, 255, 255))
    a = np.asarray(im).copy()
    a[30:70, 20:80] = (120, 90, 60)
    a[45:55, 45:55] = (250, 250, 250)                                  # белое ВНУТРИ товара — товар
    m = fg_mask(Image.fromarray(a))
    check('фон карточки — прочь, белое внутри товара — товар', not m[5, 5] and m[40, 30] and m[50, 50])
    rc = ref_colour(Image.fromarray(a))
    check('основной тон — коричневый товара', rc['lab'] is not None and ciede2000(rc['lab'], to_lab(np.array([[120, 90, 60]], np.uint8))[0]) < 3)
    sh = Image.new('RGB', (200, 310), (200, 200, 200))
    s = np.asarray(sh).copy()
    s[150:160] = (255, 0, 255)
    v = split_sheet(Image.fromarray(s))
    check('лист режется по полосе', v[0][1][3] == 150 and v[1][1][1] == 160)
    print('всё зелёное' if not fails else f'красных: {fails}')
    return 1 if fails else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    print(__doc__)
