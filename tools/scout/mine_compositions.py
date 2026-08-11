#!/usr/bin/env python3
"""Майнинг композиций гостиных из ProcTHOR-10k (Apache 2.0) — ОПОРА для
проектирования НАШИХ шаблонов (решение владельца 11.08): считаем частоты
схем посадки по диапазонам площадей и сверяем с библиотекой planner/template.py.
Данные датасета в прод НЕ переносятся — только агрегаты в отчёт.

  ~/venvs/scout/bin/python mine_compositions.py   # → composition-mining.json + чат-таблица
"""
import gzip
import json
import math
import os
from collections import Counter, defaultdict

from shapely.geometry import Point, Polygon

SRC = os.path.expanduser('~/datasets/procthor-10k/train.jsonl.gz')

ROLE_SUBSTR = [
    ('sofa', 'диван'), ('armchair', 'кресло'), ('arm_chair', 'кресло'),
    ('coffeetable', 'столик'), ('coffee_table', 'столик'),
    ('diningtable', 'стол обеденный'), ('dining_table', 'стол обеденный'),
    ('sidetable', 'приставной'), ('side_table', 'приставной'),
    ('tvstand', 'тв-тумба'), ('tv_stand', 'тв-тумба'),
    ('shelving', 'стеллаж'), ('dresser', 'комод'), ('ottoman', 'пуф'),
    ('chair', 'стул'),   # после armchair! обеденные/прочие стулья
]


def role_of(asset_id: str) -> str | None:
    a = asset_id.lower()
    for sub, role in ROLE_SUBSTR:
        if sub in a:
            return role
    return None


def ang_norm(a: float) -> float:
    return a % 360.0


def rel_bucket(sofa, other) -> str:
    """Отношение предмета к дивану: фланг/визави/линия — по углу направления
    на предмет относительно взгляда дивана (THOR: rot.y компасный, как у нас)."""
    r = math.radians(sofa['rot'])
    fx, fz = math.sin(r), math.cos(r)
    dx, dz = other['x'] - sofa['x'], other['z'] - sofa['z']
    n = math.hypot(dx, dz) or 1.0
    cosang = (fx * dx + fz * dz) / n
    ang = math.degrees(math.acos(max(-1.0, min(1.0, cosang))))
    if ang <= 45:
        return 'front'      # перед диваном (визави-позиция)
    if ang >= 135:
        return 'behind'
    return 'flank'          # сбоку


def sofa_pair_bucket(s1, s2) -> str:
    d = abs(ang_norm(s1['rot']) - ang_norm(s2['rot']))
    d = min(d, 360 - d)
    if d >= 135:
        return '2sofas_facing'
    if 45 <= d < 135:
        return '2sofas_L'
    return '2sofas_parallel'


def band_of(m2: float) -> str:
    for hi, name in ((11, '<11'), (15, '11-15'), (22, '15-22'),
                     (32, '22-32'), (45, '32-45')):
        if m2 <= hi:
            return name
    return '45+'


def main() -> None:
    sig_by_band: dict[str, Counter] = defaultdict(Counter)
    comp_counter = Counter()
    n_lr = 0
    with gzip.open(SRC, 'rt') as f:
        for line in f:
            h = json.loads(line)
            lrs = [r for r in h.get('rooms', []) if r.get('roomType') == 'LivingRoom']
            if not lrs:
                continue
            objs = h.get('objects', [])
            for lr in lrs:
                poly = Polygon([(p['x'], p['z']) for p in lr['floorPolygon']])
                n_lr += 1
                items = []
                for o in objs:
                    pos = o.get('position') or {}
                    pt = Point(pos.get('x', 1e9), pos.get('z', 1e9))
                    if not poly.contains(pt):
                        continue
                    role = role_of(o.get('assetId', ''))
                    if role:
                        items.append({'role': role, 'x': pos['x'], 'z': pos['z'],
                                      'rot': (o.get('rotation') or {}).get('y', 0.0)})
                sofas = [i for i in items if i['role'] == 'диван']
                arms = [i for i in items if i['role'] == 'кресло']
                if not sofas and not arms:
                    continue
                m2 = poly.area
                # сигнатура: состав + геометрия отношений
                if len(sofas) >= 2:
                    scheme = sofa_pair_bucket(sofas[0], sofas[1])
                elif len(sofas) == 1 and arms:
                    rels = Counter(rel_bucket(sofas[0], a) for a in arms)
                    parts = []
                    if rels.get('flank'):
                        parts.append(f"{rels['flank']}fl")
                    if rels.get('front'):
                        parts.append(f"{rels['front']}fr")
                    if rels.get('behind'):
                        parts.append(f"{rels['behind']}bh")
                    scheme = 'sofa+' + '+'.join(parts) if parts else 'sofa_solo'
                elif len(sofas) == 1:
                    scheme = 'sofa_solo'
                else:
                    scheme = f'{len(arms)}arm_only'
                has_ct = any(i['role'] == 'столик' for i in items)
                has_din = any(i['role'] == 'стол обеденный' for i in items)
                sig = scheme + ('+ct' if has_ct else '') + ('+din' if has_din else '')
                sig_by_band[band_of(m2)][sig] += 1
                comp_counter[sig] += 1
    out = {'living_rooms': n_lr,
           'top_signatures': comp_counter.most_common(40),
           'by_band': {b: c.most_common(12) for b, c in sig_by_band.items()}}
    dst = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'composition-mining.json')
    json.dump(out, open(dst, 'w'), ensure_ascii=False, indent=1)
    print('гостиных с посадкой:', n_lr)
    print('\nТОП-20 сигнатур (все площади):')
    for sig, n in comp_counter.most_common(20):
        print(f'  {n:5d}  {sig}')
    print('\nПо диапазонам (топ-5):')
    for b in ('<11', '11-15', '15-22', '22-32', '32-45', '45+'):
        top = sig_by_band[b].most_common(5)
        tot = sum(sig_by_band[b].values())
        print(f'  {b} ({tot}): ' + '; '.join(f'{s}×{n}' for s, n in top))


if __name__ == '__main__':
    main()
