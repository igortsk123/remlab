#!/usr/bin/env python3
"""T-20261119-112/2: проверка этапа 04-камера (план `paint-photo-fill-01`, «Проверка на каждом этапе», владелец TG 187).

Вход — папка прогона `pose_fit.py` (`pose.json`, `stage_loss.json`, `stages/render_view0/mask.png`) и фото. Пишет в `<out>/`:
  check.json — общий формат `tools/scout/paint_stage.py` (version 1, писатель — он один): stage `04-camera`; passed = IoU И miss И extra (всего кадра и нижней полосы):
               iou_silhouette (главная), miss («фото не закрыто формой»: доля силуэта фото вне формы), extra («форма вне фото»: доля силуэта формы вне фото), те же две — по нижней
               полосе (15 % высоты силуэта от низа: плита-подложка, ножки); пороги — `tools/scout/rules/camera-check.json`; edge_agree — справочно (пометка edge_below_ref);
               если в `<корень>/<sku>/02-prep/check.json` plate_found=true, а среза нет — камера unreliable (passed=false, причина в extra.unreliable_reason);
               в extra — camera, yaw, pairs, photo (не прошёл — товар идёт нынешним путём, fail-closed);
  frame.png  — «фото поверх рендера»: фото 50 % + рендер формы с камеры 50 %; красный контур — силуэт рендера, зелёный — силуэт фото.
  camera_check.py --run <out-run = <корень прогона>/<sku>> --photo <фото .rgba.png> [--view0 <рендер с камеры .png>] [--yaw N]
Папка этапа — `<корень>/<sku>/04-camera/` (sku = имя папки out-run, корень = её родитель), как у остальных этапов пути покраски.
Рендер: `--view0` (цепочка: `chain/s1-mv12/view0.png`); нет — силуэт формы заливается полупрозрачным красным.
`pairs` — число пар точек: у подбора по силуэту+кромкам их нет (null); поле для RoMa/PoseLib (следующий шаг плана).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
import stage_loss as SL  # noqa: E402
import paint_stage as PS  # noqa: E402

RULES_PATH = os.path.join(HERE, '..', '..', 'rules', 'camera-check.json')


def load_rules(path: str = RULES_PATH) -> dict:
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def silhouette_shares(S: np.ndarray, A: np.ndarray, strip_frac: float) -> dict:
    """Две доли несовпадения силуэтов (маски bool одной формы, S — форма с камеры, A — фото в кадре камеры).
    miss  — доля силуэта ФОТО, не закрытая формой (|A∖S| / |A|); extra — доля силуэта ФОРМЫ вне фото (|S∖A| / |S|).
    Отдельно по нижней полосе: строки от низа объединения S∪A, высота strip_frac × высота объединения. Пустое с одной стороны — 1,0 (не прятать: фото есть, формы нет — miss 1),
    пусто с обеих — 0."""
    S = np.asarray(S, bool)
    A = np.asarray(A, bool)
    if S.shape != A.shape:
        raise ValueError('маски разной формы')

    def sh(num_mask: np.ndarray, den_mask: np.ndarray, other: np.ndarray) -> float:
        den = int(den_mask.sum())
        if den == 0:
            return 1.0 if other.any() else 0.0
        return float(num_mask.sum()) / den

    U = S | A
    rows = np.flatnonzero(U.any(axis=1))
    if rows.size == 0:
        return {'miss': 0.0, 'extra': 0.0, 'miss_bottom': 0.0, 'extra_bottom': 0.0, 'strip_rows': None}
    y1 = int(rows[-1])
    h = y1 - int(rows[0]) + 1
    y0 = max(y1 - max(1, int(round(strip_frac * h))) + 1, 0)
    Sb, Ab = S[y0:y1 + 1], A[y0:y1 + 1]
    St, At = S[:y0], A[:y0]                                              # верх: всё выше нижней полосы (корпус)
    un = float((St | At).sum())
    iou_top = float((St & At).sum()) / un if un else None
    return {'miss': sh(A & ~S, A, S), 'extra': sh(S & ~A, S, A),
            'miss_bottom': sh(Ab & ~Sb, Ab, Sb), 'extra_bottom': sh(Sb & ~Ab, Sb, Ab), 'iou_top': iou_top, 'strip_rows': [y0, y1]}


def bottom_shape_mismatch(shares: dict, coarse: bool, rules: dict) -> bool:
    """Форма низа не совпадает с фото (ножки: кресло 1167 — на фото два полоза, у формы четыре ножки), а корпус лёг: доли внизу (extra или miss) выше порога, маска фото внизу НЕ грубая,
    IoU верхней части (выше полосы) ≥ bottom_top_iou_min. Это отдельная причина в check.json (extra.bottom_shape_mismatch): этапы 05/07 не переносят фото на ножки такой формы."""
    if coarse or shares.get('iou_top') is None:
        return False
    low = shares['extra_bottom'] > rules['extra_bottom_max'] or shares['miss_bottom'] > rules['miss_bottom_max']
    return bool(low and shares['iou_top'] >= rules.get('bottom_top_iou_min', rules['iou_min']))


def bottom_mask_quality(rgb: np.ndarray, A: np.ndarray, strip_rows) -> dict:
    """Насколько можно верить нижней полосе фото-маски (комод 13224: ножки бледные, маска грубая блоками — extra/miss внизу шумят и НЕ повод двигать порог).
    thin_share — доля пикселей маски в полосе от (высота полосы × ширина силуэта фото); contrast — |яркость маски − яркость фона| в полосе (0…1; фон — не-маска той же полосы в ширине силуэта).
    Нет полосы/маски → None."""
    if not strip_rows:
        return {'thin_share': None, 'contrast': None}
    y0, y1 = strip_rows
    A = np.asarray(A, bool)
    cols = np.flatnonzero(A.any(axis=0))
    if cols.size == 0:
        return {'thin_share': None, 'contrast': None}
    x0, x1 = int(cols[0]), int(cols[-1]) + 1
    sub = A[y0:y1 + 1, x0:x1]
    col = np.asarray(rgb)[y0:y1 + 1, x0:x1].astype(np.float32)
    lum = 0.299 * col[..., 0] + 0.587 * col[..., 1] + 0.114 * col[..., 2]
    area = sub.size
    if area == 0 or not sub.any():
        return {'thin_share': 0.0, 'contrast': None}
    fg = float(lum[sub].mean())
    bg = float(lum[~sub].mean()) if (~sub).any() else fg
    return {'thin_share': round(float(sub.sum()) / area, 4), 'contrast': round(abs(fg - bg) / 255.0, 4)}


def prep_plate_unreliable(root: str, sku: str) -> tuple[bool, str]:
    """02-prep: plate_found=true без среза (нет выходного файла и report.written ложно) → камера по такой форме ненадёжна (форма с плитой; IoU по силуэту плиту не видит).
    Нет check.json этапа 02-prep — не знаем, не флажим (False, '')."""
    c = PS.read_check(os.path.join(root, PS.safe_name(sku), '02-prep'))
    if not c:
        return False, ''
    pf = ((c.get('metrics') or {}).get('plate_found') or {}).get('value')
    if pf is None:
        pf = (c.get('extra') or {}).get('plate_found')
    if not pf:
        return False, ''
    rep = (c.get('extra') or {}).get('report') or {}
    cut = bool(c.get('outputs')) or bool(rep.get('written'))
    if cut:
        return False, ''
    return True, '02-prep: plate_found=true, среза нет — форма с плитой-подложкой, камера по ней ненадёжна'


def verdict(iou: float, shares: dict, edge: float, rules: dict, unreliable: str = '') -> tuple[bool, str]:
    """→ (ok, причина). Порядок причин: unreliable, IoU, miss/extra кадра, miss/extra нижней полосы. Кромки — только справочная пометка."""
    bad: list[str] = []
    if unreliable:
        bad.append(unreliable)
    if iou < rules['iou_min']:
        bad.append(f"IoU силуэта {iou:.3f} < {rules['iou_min']}")
    for k, lim, what in (('miss', 'miss_max', 'фото не закрыто формой'), ('extra', 'extra_max', 'форма вне фото'),
                         ('miss_bottom', 'miss_bottom_max', 'фото не закрыто формой внизу'), ('extra_bottom', 'extra_bottom_max', 'форма вне фото внизу')):
        if shares[k] > rules[lim]:
            bad.append(f"{what}: {k} {shares[k]:.3f} > {rules[lim]}")
    if bad:
        return False, '; '.join(bad) + ' — товар идёт нынешним путём'
    return True, 'камера легла' + (f" (внутренние кромки {edge:.3f} < {rules['edge_ref']}: справочно, проверить глазами)" if edge < rules['edge_ref'] else '')


def main() -> int:
    import cv2
    from PIL import Image
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run', required=True)
    ap.add_argument('--photo', required=True)
    ap.add_argument('--view0', default=None)
    ap.add_argument('--yaw', type=float, default=None)
    a = ap.parse_args()
    import time
    t0 = time.time()
    run = a.run.rstrip('/')
    out = PS.stage_dir(os.path.dirname(run), os.path.basename(run), '04-camera')
    pose = json.load(open(os.path.join(a.run, 'pose.json'), encoding='utf-8'))
    sl = json.load(open(os.path.join(a.run, 'stage_loss.json'), encoding='utf-8'))
    reg = sl['registration']
    iou = float(reg['iou'])
    edge = float(pose['picked']['edge']['agree'])
    rules = load_rules()
    root, sku = os.path.dirname(run), os.path.basename(run)
    unrel, unrel_why = prep_plate_unreliable(root, sku) if rules.get('plate_check', True) else (False, '')

    S = np.asarray(Image.open(os.path.join(a.run, 'stages', 'render_view0', 'mask.png')).convert('L')) > 127
    h, w = S.shape
    photo = SL.read_rgba(a.photo)
    P = np.array(reg['P'], np.float64).reshape(3, 3)
    ph = SL.warp_inv(photo[..., :3], P, (w, h))
    pa = SL.warp_inv((photo[..., 3] > 127).astype(np.uint8) * 255, P, (w, h), interp=cv2.INTER_NEAREST) > 127
    shares = silhouette_shares(S, pa, rules['strip_frac'])
    ok, reason = verdict(iou, shares, edge, rules, unrel_why)
    bq = bottom_mask_quality(ph, pa, shares['strip_rows'])
    coarse = bool(bq['thin_share'] is not None and bq['contrast'] is not None
                  and bq['thin_share'] < rules.get('coarse_thin_max', 0.3) and bq['contrast'] < rules.get('coarse_contrast_max', 0.35))
    coarse_note = 'низ: маска фото грубая (мало пикселей маски в нижней полосе, низкий контраст) — доли внизу шумят, порог под такие не подгонять' if coarse else ''
    if coarse_note:
        reason = reason + '; ' + coarse_note if not ok else reason + ' (' + coarse_note + ')'
    bsm = bottom_shape_mismatch(shares, coarse, rules)
    if bsm:
        reason = 'bottom_shape_mismatch: форма низа не совпадает с фото (ножки), корпус лёг (IoU верха %.3f) — фото на ножки не переносить; ' % shares['iou_top'] + reason
        ok = False
    if a.view0 and os.path.exists(a.view0):
        rend = np.asarray(Image.open(a.view0).convert('RGB'))
        if rend.shape[:2] != (h, w):
            rend = cv2.resize(rend, (w, h), interpolation=cv2.INTER_AREA)
    else:
        rend = np.zeros((h, w, 3), np.uint8)
        rend[S] = (255, 0, 0)
    gray = np.full((h, w, 3), 235, np.uint8)
    ph_bg = np.where(pa[..., None], ph, gray)                       # фон фото — светло-серый, не чёрный
    rend_bg = np.where(S[..., None], rend, gray)
    blend = (0.5 * ph_bg.astype(np.float32) + 0.5 * rend_bg.astype(np.float32)).astype(np.uint8)
    for m, col in ((S, (255, 0, 0)), (pa, (0, 200, 0))):
        cs, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(blend, cs, -1, col, 2)
    Image.fromarray(blend).save(os.path.join(out, 'frame.png'))

    def lim(name: str, key: str) -> dict:
        return {'value': round(shares[name], 4), 'threshold': rules[key], 'op': '<='}
    res = PS.write_check(out, '04-camera', os.path.basename(run), passed=ok,
                         metric={'name': 'iou_silhouette', 'value': round(iou, 4), 'threshold': rules['iou_min'], 'op': '>='},
                         metrics={'miss': lim('miss', 'miss_max'), 'extra': lim('extra', 'extra_max'),
                                  'miss_bottom': lim('miss_bottom', 'miss_bottom_max'), 'extra_bottom': lim('extra_bottom', 'extra_bottom_max'),
                                  'edge_agree': {'value': round(edge, 4)}},
                         reason=reason if not ok else '', seconds=round(time.time() - t0, 1), outputs=['frame.png'], frame='frame.png',
                         edge_ref_min=rules['edge_ref'], edge_below_ref=bool(edge < rules['edge_ref']), note=reason if ok else '', strip_rows=shares['strip_rows'], strip_frac=rules['strip_frac'],
                         bottom_mask_coarse=coarse, bottom_mask=bq, bottom_shape_mismatch=bsm, iou_top=None if shares['iou_top'] is None else round(shares['iou_top'], 4),
                         bottom_top_iou_min=rules.get('bottom_top_iou_min', rules['iou_min']), unreliable=bool(unrel), unreliable_reason=unrel_why, rules_file='tools/scout/rules/camera-check.json',
                         camera=pose['camera'], yaw=a.yaw if a.yaw is not None else pose.get('yaw'), pairs=None, photo=a.photo, method=reg.get('method'),
                         textured=pose.get('textured'), frame_note='фото 50 % + рендер 50 %; красный контур — рендер формы, зелёный — фото')
    print(f"{'OK ' if res['passed'] else 'НЕТ'} IoU {iou:.3f} miss {shares['miss']:.3f}/{shares['miss_bottom']:.3f} extra {shares['extra']:.3f}/{shares['extra_bottom']:.3f} (всё/низ) кромки {edge:.3f} — {reason}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
