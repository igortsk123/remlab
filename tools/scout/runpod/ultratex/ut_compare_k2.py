#!/usr/bin/env python3
"""T-178/1: сравнение двух результатов UltraTex на ТОМ ЖЕ входе (эталон k2 — Qwen на карте; новый образ — пустой текст из файла): ΔE и SSIM кадров, допуск, вердикт.
Бесплатно: рендер GLB на CPU (mesh_render) и счёт — запускать под heavy-slot --prio 1.

  python ut_compare_k2.py --ref ref.glb --new new.glb --out папка [--ref-metrics a.json --new-metrics b.json]
  python ut_compare_k2.py --selftest

Кадры — те же 4 ракурса и подписи по камере, что в render_k2.py (фасад yaw 335; одна геометрия prep.glb → один и тот же вид у обоих). Маска — пиксели не фона у ОБОИХ.
Мерки: ΔE76 (Lab, OpenCV) среднее и 95-й процентиль; SSIM по яркости (окно Гаусса 11, σ 1,5); доля несовпадения масок.
ДОПУСК (предложение, подтверждает директор): среднее ΔE ≤ 2,0 (порог заметной разницы), p95 ≤ 6,0, SSIM ≥ 0,98, маски совпали ≥ 99,5 % — по КАЖДОМУ из 4 кадров.
Вердикт: SAME (всё в допуске) | DIFFER (что-то вне — вывести кадры разности) | число граней и покрытие видов из metrics сверяются отдельно (должны совпасть точно: геометрия общая)."""
import argparse
import json
import os
import sys

import numpy as np

VIEWS = (('facade_yaw335', 335.0), ('rear_yaw155', 155.0), ('rear_right34_yaw205', 205.0), ('side_yaw105', 105.0))
TOL = {'mean_de': 2.0, 'p95_de': 6.0, 'ssim': 0.98, 'mask_match': 0.995}


def _gauss_filter(a, k=11, sigma=1.5):
    import cv2
    return cv2.GaussianBlur(a, (k, k), sigma, borderType=cv2.BORDER_REFLECT)


def ssim_gray(a: np.ndarray, b: np.ndarray, mask: np.ndarray | None = None) -> float:
    """Средний SSIM по яркости (0..255) на пикселях маски (без неё — по всему кадру)."""
    a, b = a.astype(np.float64), b.astype(np.float64)
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mu_a, mu_b = _gauss_filter(a), _gauss_filter(b)
    saa = _gauss_filter(a * a) - mu_a ** 2
    sbb = _gauss_filter(b * b) - mu_b ** 2
    sab = _gauss_filter(a * b) - mu_a * mu_b
    m = ((2 * mu_a * mu_b + c1) * (2 * sab + c2)) / ((mu_a ** 2 + mu_b ** 2 + c1) * (saa + sbb + c2))
    return float(m[mask].mean()) if mask is not None and mask.any() else float(m.mean())


def delta_e76(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """ΔE76 по пикселям для двух RGB uint8 кадров."""
    import cv2
    la = cv2.cvtColor(a, cv2.COLOR_RGB2LAB).astype(np.float64)
    lb = cv2.cvtColor(b, cv2.COLOR_RGB2LAB).astype(np.float64)
    la[..., 0] *= 100 / 255
    lb[..., 0] *= 100 / 255
    la[..., 1:] -= 128
    lb[..., 1:] -= 128
    return np.sqrt(((la - lb) ** 2).sum(axis=-1))


def fg_mask(img: np.ndarray, bg_tol: int = 6) -> np.ndarray:
    bg = img[0, 0].astype(int)
    return (np.abs(img.astype(int) - bg).max(axis=-1) > bg_tol)


def compare_frames(a: np.ndarray, b: np.ndarray) -> dict:
    ma, mb = fg_mask(a), fg_mask(b)
    both = ma & mb
    union = ma | mb
    match = float(both.sum() / union.sum()) if union.any() else 1.0
    if not both.any():
        return {'mean_de': None, 'p95_de': None, 'ssim': None, 'mask_match': match}
    de = delta_e76(a, b)[both]
    ga = np.asarray(__import__('PIL.Image', fromlist=['Image']).fromarray(a).convert('L'))
    gb = np.asarray(__import__('PIL.Image', fromlist=['Image']).fromarray(b).convert('L'))
    return {'mean_de': round(float(de.mean()), 3), 'p95_de': round(float(np.percentile(de, 95)), 3), 'ssim': round(ssim_gray(ga, gb, both), 4), 'mask_match': round(match, 4)}


def verdict_of(rows: dict, tol: dict = TOL) -> tuple[str, list]:
    bad = []
    for name, r in rows.items():
        if r['mean_de'] is None:
            bad.append(f'{name}: нет общих пикселей')
            continue
        if r['mean_de'] > tol['mean_de']:
            bad.append(f'{name}: средний ΔE {r["mean_de"]} > {tol["mean_de"]}')
        if r['p95_de'] > tol['p95_de']:
            bad.append(f'{name}: p95 ΔE {r["p95_de"]} > {tol["p95_de"]}')
        if r['ssim'] < tol['ssim']:
            bad.append(f'{name}: SSIM {r["ssim"]} < {tol["ssim"]}')
        if r['mask_match'] < tol['mask_match']:
            bad.append(f'{name}: маски {r["mask_match"]} < {tol["mask_match"]}')
    return ('SAME' if not bad else 'DIFFER'), bad


def render_set(glb: str, out_dir: str, tag: str) -> dict:
    sys.path.insert(0, os.environ.get('SCOUT_DIR', '/home/pakar/igor/remlab/tools/scout'))
    import mesh_render as MR
    parts = MR.load_parts(glb)
    os.makedirs(out_dir, exist_ok=True)
    frames = {}
    for name, yaw in VIEWS:
        im = MR.render(parts, yaw, 18.0)
        im.save(os.path.join(out_dir, f'{name}.{tag}.png'))
        frames[name] = np.asarray(im.convert('RGB'))
    return frames


def metrics_check(ref_m: dict, new_m: dict) -> list:
    """Геометрия общая: число граней и покрытие видов должны совпасть точно."""
    bad = []
    for k in ('faces', 'faces_out', 'view_coverage_pct', 'texel_seen_pct'):
        if ref_m.get(k) != new_m.get(k):
            bad.append(f'{k}: {ref_m.get(k)} ≠ {new_m.get(k)}')
    return bad


def selftest() -> int:
    from PIL import Image, ImageDraw
    rng = np.random.default_rng(0)
    base = np.full((120, 160, 3), 255, np.uint8)
    im = Image.fromarray(base)
    d = ImageDraw.Draw(im)
    d.rectangle([30, 20, 130, 100], fill=(150, 90, 40))
    a = np.asarray(im)
    ok = []
    r0 = compare_frames(a, a)
    ok.append(('одинаковые кадры: ΔE 0, SSIM 1, маски 1', r0['mean_de'] == 0 and r0['ssim'] == 1.0 and r0['mask_match'] == 1.0))
    noise = np.clip(a.astype(int) + rng.integers(-1, 2, a.shape), 0, 255).astype(np.uint8)
    r1 = compare_frames(a, noise)
    ok.append(('шум ±1: в допуске', verdict_of({'v': r1})[0] == 'SAME'))
    shifted = a.copy().astype(int)
    shifted[25:95, 35:125] = shifted[25:95, 35:125] + np.array([30, -20, 10])
    r2 = compare_frames(a, np.clip(shifted, 0, 255).astype(np.uint8))
    ok.append(('сдвиг цвета на ~35 ΔE: DIFFER с причиной ΔE', verdict_of({'v': r2})[0] == 'DIFFER' and any('ΔE' in x for x in verdict_of({'v': r2})[1])))
    im3 = Image.fromarray(base)
    ImageDraw.Draw(im3).rectangle([60, 20, 160, 100], fill=(150, 90, 40))
    r3 = compare_frames(a, np.asarray(im3))
    ok.append(('другая форма (сдвиг маски): DIFFER, маски < допуска', verdict_of({'v': r3})[0] == 'DIFFER' and r3['mask_match'] < TOL['mask_match']))
    ok.append(('метрики: равные — чисто, разные грани — замечание', not metrics_check({'faces': 1, 'faces_out': 1}, {'faces': 1, 'faces_out': 1}) and metrics_check({'faces': 1}, {'faces': 2})))
    for name, cond in ok:
        print(('ok   ' if cond else 'FAIL ') + name)
    print('ИТОГ:', 'ВСЁ ЗЕЛЁНОЕ' if all(c for _, c in ok) else 'ЕСТЬ ПРОВАЛЫ')
    return 0 if all(c for _, c in ok) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--ref')
    ap.add_argument('--new')
    ap.add_argument('--out')
    ap.add_argument('--ref-metrics')
    ap.add_argument('--new-metrics')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    fr = render_set(a.ref, a.out, 'ref')
    fn = render_set(a.new, a.out, 'new')
    rows = {n: compare_frames(fr[n], fn[n]) for n, _ in VIEWS}
    v, bad = verdict_of(rows)
    mbad = metrics_check(json.load(open(a.ref_metrics)), json.load(open(a.new_metrics))) if a.ref_metrics and a.new_metrics else ['metrics не переданы']
    res = {'verdict': v, 'tolerance': TOL, 'views': rows, 'problems': bad, 'metrics_problems': mbad}
    json.dump(res, open(os.path.join(a.out, 'compare.json'), 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False))
    return 0 if v == 'SAME' and not mbad else 1


if __name__ == '__main__':
    sys.exit(main())
