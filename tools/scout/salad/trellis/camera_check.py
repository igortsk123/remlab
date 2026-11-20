#!/usr/bin/env python3
"""T-20261119-112/2: проверка этапа 04-камера (план `paint-photo-fill-01`, «Проверка на каждом этапе», владелец TG 187).

Вход — папка прогона `pose_fit.py` (`pose.json`, `stage_loss.json`, `stages/render_view0/mask.png`) и фото. Пишет в `<out>/`:
  check.json — общий формат `tools/scout/paint_stage.py` (version 1, писатель — он один): stage `04-camera`, главная мерка iou_silhouette ≥ 0,85, edge_agree — справочно (порога нет, пометка edge_below_ref при <0,5); в extra — camera, yaw, pairs, photo
               (не прошёл — товар идёт нынешним путём, fail-closed);
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

IOU_MIN = 0.85    # порог плана paint-photo-fill-01, шаг 1: IoU силуэта фото на кадр камеры
EDGE_REF = 0.5    # согласие внутренних кромок: СПРАВОЧНАЯ мерка (гейт плана — только IoU силуэта); ниже 0,5 — пометка edge_below_ref, на passed не влияет


def verdict(iou: float, edge: float) -> tuple[bool, str]:
    if iou < IOU_MIN:
        return False, f'IoU силуэта {iou:.3f} < {IOU_MIN} — товар идёт нынешним путём'
    return True, 'камера легла' + (f' (внутренние кромки {edge:.3f} < {EDGE_REF}: справочно, проверить глазами)' if edge < EDGE_REF else '')


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
    ok, reason = verdict(iou, edge)

    S = np.asarray(Image.open(os.path.join(a.run, 'stages', 'render_view0', 'mask.png')).convert('L')) > 127
    h, w = S.shape
    photo = SL.read_rgba(a.photo)
    P = np.array(reg['P'], np.float64).reshape(3, 3)
    ph = SL.warp_inv(photo[..., :3], P, (w, h))
    pa = SL.warp_inv((photo[..., 3] > 127).astype(np.uint8) * 255, P, (w, h), interp=cv2.INTER_NEAREST) > 127
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

    res = PS.write_check(out, '04-camera', os.path.basename(run),
                         metric={'name': 'iou_silhouette', 'value': round(iou, 4), 'threshold': IOU_MIN, 'op': '>='},
                         metrics={'edge_agree': {'value': round(edge, 4)}},
                         reason=reason if not ok else '', seconds=round(time.time() - t0, 1), outputs=['frame.png'], frame='frame.png',
                         edge_ref_min=EDGE_REF, edge_below_ref=bool(edge < EDGE_REF), note=reason if ok else '', camera=pose['camera'], yaw=a.yaw if a.yaw is not None else pose.get('yaw'), pairs=None, photo=a.photo, method=reg.get('method'),
                         textured=pose.get('textured'), frame_note='фото 50 % + рендер 50 %; красный контур — рендер формы, зелёный — фото')
    print(f"{'OK ' if res['passed'] else 'НЕТ'} IoU {iou:.3f} кромки {edge:.3f} — {reason}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
