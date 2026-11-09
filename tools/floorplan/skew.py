#!/usr/bin/env python3
"""Метрика косых граней по прогону (T-20261109-04): по каждой панели — полы и стены, до (прежнее выпрямление) и после.
  python tools/floorplan/skew.py <run-папка> [планы...] → печать и <run>/skew.txt
Косая грань — ребро ≥ 0,3 м, чей угол дальше 3° от любого семейства углов панели; «косой пол» — пол с такой гранью."""
import json
import sys
from pathlib import Path


def main():
    run = Path(sys.argv[1])
    plans = sys.argv[2:] or ['A', 'B', 'C']
    out = ['план | панель | семейства | полы: косых до → после (доля длины) | стены: доля косой длины до → после']
    tot = {'fb': 0, 'fa': 0, 'fn': 0}
    for plan in plans:
        mp = run / plan / f'metrics-{plan}.json'
        if not mp.exists():
            out.append(f'{plan}: нет metrics')
            continue
        for p in json.loads(mp.read_text())['panels']:
            s = p.get('skew')
            if not s:
                continue
            fb, fa, wb, wa = s['floors_before'], s['floors_after'], s['walls_before'], s['walls_after']
            tot['fb'] += fb['skew_polys']; tot['fa'] += fa['skew_polys']; tot['fn'] += fa['polys']
            out.append(f'{plan} | {p["panel"]:<12} | {s["fams_panel"]} | {fb["skew_polys"]}/{fb["polys"]} '
                       f'({fb["off_share"]:.1%}) → {fa["skew_polys"]}/{fa["polys"]} ({fa["off_share"]:.1%}) | '
                       f'{wb["off_share"]:.1%} → {wa["off_share"]:.1%} (худший {wa["worst_deg"]}°) · откатов {s.get("straight")}')
    out.append(f'ИТОГО косых полов: до {tot["fb"]}, после {tot["fa"]} из {tot["fn"]}')
    text = '\n'.join(out)
    (run / 'skew.txt').write_text(text + '\n')
    print(text)


if __name__ == '__main__':
    main()
