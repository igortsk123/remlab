#!/usr/bin/env python3
"""V4-K свода №10: камин-регресс — ТОЛЬКО отчёт, правил не меняем.

По всем сценам с камином: видимость от посадки (focus_visible-угол), дистанция
до посадки, есть ли посадка вокруг фокала в большой комнате. Существующие пороги
(distance 200-450, сектора 35°/45°) — из паспорта fireplace; здесь только замер.
"""
import glob
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    out = []
    for f in sorted(glob.glob(os.path.join(HERE, 'v3set*-layout-acc-zoned-*.json'))):
        a = json.load(open(f))
        fp = a.get('камин')
        sofa = a.get('диван')
        if not isinstance(fp, dict) or not isinstance(sofa, dict):
            continue
        sid = os.path.basename(f).split('-acc-zoned-')[-1][:-5]
        rm = a.get('_room') or {}
        m2 = round((rm.get('w', 0) * rm.get('d', 0)) / 10_000, 1)
        dist = math.hypot(fp['x'] - sofa['x'], fp['z'] - sofa['z'])
        r = math.radians(sofa.get('rot') or 0)
        dx, dy = fp['x'] - sofa['x'], fp['z'] - sofa['z']
        fwd = math.sin(r) * dx + math.cos(r) * dy
        lat = math.cos(r) * dx - math.sin(r) * dy
        ang = abs(math.degrees(math.atan2(lat, fwd))) if fwd > 0 else 180.0
        out.append({'scene': sid, 'm2': m2, 'dist_cm': round(dist),
                    'angle_from_sofa_deg': round(ang),
                    'in_primary_sector_35': ang <= 35,
                    'in_distance_band_200_450': 200 <= dist <= 450})
    outp = os.path.join(HERE, 'fireplace-regression-report.json')
    json.dump(out, open(outp, 'w'), ensure_ascii=False, indent=1)
    n = len(out)
    sec = sum(1 for r in out if r['in_primary_sector_35'])
    band = sum(1 for r in out if r['in_distance_band_200_450'])
    print(f'OK → {outp}: камин-сцен {n}; в секторе 35°: {sec}; '
          f'в вилке 200-450: {band}; вне обоих: '
          f'{[r["scene"] for r in out if not r["in_primary_sector_35"] and not r["in_distance_band_200_450"]][:8]}')


if __name__ == '__main__':
    main()
