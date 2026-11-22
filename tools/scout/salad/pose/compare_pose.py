#!/usr/bin/env python3
"""Сверка прогона pose_fit на Salad с НАШИМ прогоном на тех же форме и фото (T-184/1, очередь 2). Пороги — `tools/scout/rules/salad-pose.json` (СТАРТОВЫЕ, не в коде).
Что сравниваем по каждому товару: камера (az, el в градусах, ln d), IoU кадра, вердикт `camera_check` (passed) и НАБОР проваленных метрик (metrics.*.ok == false).
Вердикт обязан совпасть точно; поза и IoU — в пределах порогов. Расхождение на одном товаре = разбор, не «ок».
Использование: compare_pose.py --ours <папка с <sku>/…> --ref <папка с <sku>/…> --skus a,b,c [--out compare.json]. Код выхода: 0 — все совпали, 1 — есть расхождение/нет файла."""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.normpath(os.path.join(HERE, '..', '..', 'rules', 'salad-pose.json'))


def load_rules(path: str = RULES) -> dict:
    return json.load(open(path, encoding='utf-8'))


def read_run(d: str) -> dict:
    """Из папки прогона: камера, IoU кадра, passed, проваленные метрики, причина. Нет файла — KeyError с именем."""
    def load(rel):
        p = os.path.join(d, rel)
        if not os.path.isfile(p):
            raise KeyError(f'нет {p}')
        return json.load(open(p, encoding='utf-8'))
    pose, chk = load('pose.json'), load(os.path.join('04-camera', 'check.json'))
    cam = pose['camera']
    return {'az': float(cam['az']), 'el': float(cam['el']), 'd': float(cam['d']), 'iou': float(pose['iou_frame']), 'passed': bool(chk['passed']),
            'failed': sorted(k for k, v in (chk.get('metrics') or {}).items() if v.get('ok') is False) + ([] if (chk.get('metric') or {}).get('ok') is not False else ['iou_silhouette']),
            'reason': str(chk.get('reason') or '')}


def diff_az(a: float, b: float) -> float:
    """Разница азимутов по кругу (359° и 1° — это 2°)."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def compare(ref: dict, ours: dict, rules: dict) -> dict:
    d = {'d_az': round(diff_az(ref['az'], ours['az']), 4), 'd_el': round(abs(ref['el'] - ours['el']), 4), 'd_lnd': round(abs(math.log(ref['d'] / ours['d'])), 5),
         'd_iou': round(abs(ref['iou'] - ours['iou']), 5), 'passed': (ref['passed'], ours['passed']), 'failed': (ref['failed'], ours['failed'])}
    bad = []
    if d['d_az'] > rules['az_deg']:
        bad.append(f"азимут {d['d_az']}° > {rules['az_deg']}")
    if d['d_el'] > rules['el_deg']:
        bad.append(f"подъём {d['d_el']}° > {rules['el_deg']}")
    if d['d_lnd'] > rules['ln_d']:
        bad.append(f"|Δln d| {d['d_lnd']} > {rules['ln_d']}")
    if d['d_iou'] > rules['iou']:
        bad.append(f"IoU {d['d_iou']} > {rules['iou']}")
    if rules.get('same_passed', True) and ref['passed'] != ours['passed']:
        bad.append(f"ВЕРДИКТ другой: у нас {ref['passed']}, на Salad {ours['passed']}")
    if rules.get('same_failed_metrics', True) and ref['failed'] != ours['failed']:
        bad.append(f"набор проваленных метрик другой: {ref['failed']} ≠ {ours['failed']}")
    return {**d, 'match': not bad, 'why': bad}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--ours', required=True)
    ap.add_argument('--ref', required=True)
    ap.add_argument('--skus', required=True)
    ap.add_argument('--rules', default=RULES)
    ap.add_argument('--out', default='')
    a = ap.parse_args()
    rules = load_rules(a.rules)
    rows, bad = {}, 0
    for sku in [s for s in a.skus.split(',') if s]:
        try:
            rows[sku] = compare(read_run(os.path.join(a.ref, sku)), read_run(os.path.join(a.ours, sku)), rules)
        except KeyError as exc:
            rows[sku] = {'match': False, 'why': [str(exc)]}
        r = rows[sku]
        bad += 0 if r['match'] else 1
        print(sku, 'СОВПАЛО' if r['match'] else 'РАСХОЖДЕНИЕ', {k: r[k] for k in r if k not in ('match', 'why')}, r['why'] or '')
    print(f"итого: совпало {len(rows) - bad} из {len(rows)}; пороги СТАРТОВЫЕ: {rules['az_deg']}°/{rules['el_deg']}°/ln d {rules['ln_d']}/IoU {rules['iou']}, вердикт — точно")
    if a.out:
        json.dump({'rules': rules, 'items': rows, 'matched': len(rows) - bad, 'total': len(rows)}, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
