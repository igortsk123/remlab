#!/usr/bin/env python3
"""Q10-0: отчёт «практика vs движок» по ВОЗМОЖНОСТЯМ (окно / центр / угол / главная стена).

Честность (Codex 19.08): «пусто» разделено на состояния — занято обязательной зоной,
нечего ставить (банк), не пробовали (placer'а ещё нет), намеренно пусто (валидный вариант
проиграл). Доли считаем ТОЛЬКО среди тех возможностей, где вариант был достижим.

  opportunity_report.py [--by-mode]
"""
from __future__ import annotations

import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> None:
    sets = json.load(open(os.path.join(HERE, 'sets3.json'), encoding='utf-8'))
    priors = json.load(open(os.path.join(HERE, 'rules', 'practice_priors.json'), encoding='utf-8'))
    by_mode = '--by-mode' in sys.argv
    st = collections.Counter()
    sel = collections.defaultdict(collections.Counter)
    modes = collections.defaultdict(collections.Counter)
    n = 0
    for f in glob.glob(os.path.join(HERE, 'v3set*-layout-acc-zoned-*.json')):
        a = json.load(open(f, encoding='utf-8'))
        items = (a.get('_opportunities') or {}).get('items') or []
        if not items:
            continue
        n += 1
        m2 = sets[int(os.path.basename(f).split('v3set')[1].split('-')[0]) - 1]['m2']
        mode = 'small' if m2 < 20 else ('trans' if m2 < 25 else ('large' if m2 < 40 else 'xl'))
        for o in items:
            k = o['kind']
            st[f"{k}:{o.get('state')}"] += 1
            if o.get('state') == 'selected':
                sel[k][o['selected_outcome']] += 1
                modes[f'{k}/{mode}'][o['selected_outcome']] += 1
    print(f'сцен с сертификатом: {n}\n')
    for kind in ('window', 'seating_center', 'free_corner', 'primary_wall'):
        states = {s.split(':')[1]: c for s, c in st.items() if s.startswith(kind + ':')}
        total = sum(states.values())
        if not total:
            continue
        print(f'=== {kind}: возможностей {total}')
        for s, c in sorted(states.items(), key=lambda kv: -kv[1]):
            print(f'    {s:28} {c:4}  ({100*c/total:.0f}%)')
        chosen = sel[kind]
        tot_sel = sum(chosen.values())
        if tot_sel:
            pr = {o['id']: o['observed_share_pct']
                  for o in ((priors.get('opportunities') or {}).get(kind) or {}).get('outcomes', [])}
            print(f'    -- среди ВЫБРАННЫХ ({tot_sel}): движок vs практика')
            for o, c in chosen.most_common():
                print(f'       {o:24} {100*c/tot_sel:4.0f}%   практика {pr.get(o, "—")}%')
        if by_mode:
            for mk in sorted(k for k in modes if k.startswith(kind + '/')):
                tot = sum(modes[mk].values())
                if tot:
                    print(f'    [{mk}] ' + ', '.join(f'{o} {100*c/tot:.0f}%' for o, c in modes[mk].most_common(4)))
        print()


if __name__ == '__main__':
    main()
