#!/usr/bin/env python3
"""Пробная сборка кандидатов в растения-декор (T-20261117-21): лёгкие копии по правилам `plant_from_scan.build_one` (≤ 60 тыс. треугольников,
≤ 1 МБ, стоит вертикально, низ в нуле), но в ПРОБНУЮ папку — в `public/` и `manifest.json` ничего не попадает.

  ~/venvs/scout/bin/python tools/assets/plant_candidates.py [--out ~/remlab-logs/t21-1117/glb] [--id c-shrub4]

Список — `data/flat3d/plant-candidates.json`; источники — `plant_from_scan.py fetch` (кэш `~/scout-scenes/plants-src`).
Пишет `<out>/<id>.glb` и `<out>/candidates.json` (размеры, треугольники, байты, использование)."""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import plant_from_scan as PS  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.expanduser('~/remlab-logs/t21-1117/glb'))
    ap.add_argument('--id')
    ap.add_argument('--existing', action='store_true', help='вместо кандидатов — нынешние растения `plants.json` (для сравнения на кадрах), без букетов')
    a = ap.parse_args()
    with open(os.path.join(ROOT, 'data', 'flat3d', 'plant-candidates.json'), encoding='utf-8') as f:
        cfg = json.load(f)
    if a.existing:
        cfg = {'limits': cfg['limits'], 'candidates': [{**q, 'id': 'cur-' + q['id']} for q in PS.load_config()['plants'] if not q.get('builder')]}
    os.makedirs(a.out, exist_ok=True)
    PS.OUT = a.out                                   # пробная папка вместо public/flat3d/plants
    rows = []
    for p in cfg['candidates']:
        if a.id and p['id'] != a.id:
            continue
        try:
            r = PS.build_one(p, cfg['limits'])
            raw = os.path.join(a.out, 'raw')          # без сжатия meshopt — для Blender (импорт не знает EXT_meshopt_compression)
            os.makedirs(raw, exist_ok=True)
            PS.OUT = raw
            real = PS.subprocess.run
            PS.subprocess.run = lambda cmd, **kw: real([c for c in cmd if c != '-cc'], **kw)
            try:
                PS.build_one(p, {**cfg['limits'], 'maxBytes': 10 ** 9})
            finally:
                PS.subprocess.run = real
                PS.OUT = a.out
        except SystemExit as e:
            r = {'id': p['id'], 'asset': p['asset'], 'error': str(e)}
        r['use'] = p.get('use')
        rows.append(r)
        print(r)
    path = os.path.join(a.out, 'candidates.json')
    have = {}
    if a.id and os.path.isfile(path):
        with open(path, encoding='utf-8') as f:
            have = {x['id']: x for x in json.load(f)}
    have.update({r['id']: r for r in rows})
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(list(have.values()), f, ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
