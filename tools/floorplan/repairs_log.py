#!/usr/bin/env python3
"""Журнал починок прогона (T-20261109-03): по каждой панели — гипотезы, ΔE, принято/откат/неоднозначно, итог подписей.
  python tools/floorplan/repairs_log.py <run-папка> [A B C] [--full] → печать и <run>/repairs.txt"""
import json
import sys
from pathlib import Path


def main():
    run = Path(sys.argv[1])
    full = '--full' in sys.argv
    plans = [a for a in sys.argv[2:] if not a.startswith('--')] or ['A', 'B', 'C']
    out, tot = [], {'гипотез': 0, 'принято': 0, 'откат': 0, 'неоднозначно': 0}
    for plan in plans:
        mp = run / plan / f'metrics-{plan}.json'
        if not mp.exists():
            continue
        met = json.loads(mp.read_text())
        for p in met['panels']:
            rep = p.get('repairs') or []
            if not rep:
                continue
            hy = [x for x in rep if x.get('kind') in ('remove', 'mincut', 'recompute', 'neck')]
            acc = [x for x in hy if x.get('applied')]
            amb = [x for x in rep if x.get('kind') == 'ambiguous']
            st = next((x for x in rep if x.get('kind') == 'start'), {})
            en = next((x for x in rep if x.get('kind') == 'end'), {})
            sec = next((x.get('sec') for x in rep if x.get('kind') == 'stop'), None)
            nok = sum(1 for x in hy if x.get('ok') and not x.get('applied'))
            tot['гипотез'] += len(hy); tot['принято'] += len(acc); tot['откат'] += len(hy) - len(acc) - nok
            tot['неоднозначно'] += len(amb)
            out.append(f'{plan} {p["panel"]}: гипотез {len(hy)}, принято {len(acc)}, не выбрано {nok}, '
                       f'откат {len(hy) - len(acc) - nok}, '
                       f'неоднозначно {len(amb)}, {sec} с; топология {st.get("topo0")} → '
                       f'{{cost {en.get("topo")}, merged {en.get("merged")}, missing {en.get("missing")}, '
                       f'unexplained {en.get("unexplained")}}}; пиксели {st.get("pix0_m")} → {en.get("pix_m")} м; '
                       f'манера {st.get("conv")}, ppm {st.get("ppm")} (по VLM {st.get("ppm_vlm")})')
            nsel = sum(1 for x in hy if x.get('ok') and not x.get('applied'))
            tot['не выбрано'] = tot.get('не выбрано', 0) + nsel
            for x in hy:
                if full or x.get('applied') or x.get('ambiguous'):
                    keys = {k: v for k, v in x.items() if k not in ('pass',)}
                    tag = ('ПРИНЯТО ' if x.get('applied') else 'неоднозн. ' if x.get('ambiguous') else
                           'не выбрано ' if x.get('ok') else 'откат ')
                    out.append('   ' + tag + json.dumps(keys, ensure_ascii=False))
            for x in amb:
                out.append('   НЕОДНОЗНАЧНО ' + json.dumps(x, ensure_ascii=False))
            for q in p.get('label_report') or []:
                if q.get('level'):
                    out.append(f'   флаг: {q["name"]} {q["dims"]} → {q.get("pred")} ({q["flag"]})')
    out.append('ИТОГО: ' + ', '.join(f'{k} {v}' for k, v in tot.items()))
    text = '\n'.join(out)
    (run / 'repairs.txt').write_text(text + '\n')
    print(text)


if __name__ == '__main__':
    main()
