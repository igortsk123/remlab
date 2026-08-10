#!/usr/bin/env python3
"""Бисект регрессий приёмки — ШТАТНОЕ звено конвейера (владелец 10.08:
«анализировать должен конвейер», а не ручные разборы).

Вход: базлайн-отчёт, новый отчёт, спецификация правок (deltas.json). Инструмент
сам находит регресс-сцены (OK→FAIL и soft хуже порога), перегоняет каждую с
отключением правок ПО ОДНОЙ и выдаёт таблицу виновников (md+json). После —
восстанавливает occupancy.json (гарантированно, finally).

  ~/venvs/scout/bin/python acceptance_bisect.py \
      --base acceptance-report-zoned-pre-kbmerge.jsonl \
      --new  acceptance-report-zoned.jsonl \
      --deltas bisect-deltas.json [--soft-thr 1.0] [--max-scenes 12]

Формат deltas.json: [{"name": "...", "occupancy": {"param": value, ...},
                      "env": {"VAR": "1", ...}}, ...] — каждая запись описывает
ОТКАТ одной правки (что выключаем, чтобы проверить виновность).
"""
import argparse
import json
import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
OCC = os.path.join(HERE, '..', '..', 'services', 'planner-solver', 'rules',
                   'occupancy.json')
PY = os.path.expanduser('~/venvs/scout/bin/python')


def run_scene(sc, extra_env):
    env = dict(os.environ, LAYOUT_ENGINE='zoned',
               LAYOUT_SUFFIX=f"-bisect-{sc['id']}")
    env.update(extra_env or {})
    args = [PY, os.path.join(HERE, 'solver_run.py'), str(sc['set']), '--v3']
    if sc['kind'] == 'contour':
        xs = [p[0] for p in sc['contour']]; ys = [p[1] for p in sc['contour']]
        env['SCENE_CONTOUR'] = json.dumps(sc['contour'])
        args += [str(max(xs)), str(max(ys))]
    elif 'w' in sc:
        args += [str(sc['w']), str(sc['d'])]
    r = subprocess.run(args, capture_output=True, text=True, timeout=280,
                       env=env, cwd=HERE)
    fails = [l.strip() for l in r.stdout.splitlines() if l.startswith('FAIL')]
    m = re.search(r'^SOFT (\{.*\})$', r.stdout, re.M)
    soft = round(sum(json.loads(m.group(1)).get('terms', {}).values()), 1) \
        if m else None
    return fails, soft


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True)
    ap.add_argument('--new', required=True)
    ap.add_argument('--deltas', required=True)
    ap.add_argument('--soft-thr', type=float, default=1.0)
    ap.add_argument('--max-scenes', type=int, default=12)
    a = ap.parse_args()

    base = {r['scene']: r for r in map(json.loads, open(a.base))}
    new = {r['scene']: r for r in map(json.loads, open(a.new))}
    deltas = json.load(open(a.deltas))
    scenes = {s['id']: s for s in
              json.load(open(os.path.join(HERE, 'acceptance-scenes.json')))}

    regressed = []
    for sid, b in base.items():
        n = new.get(sid)
        if not n:
            continue
        if b.get('ok') and not n.get('ok'):
            regressed.append((sid, 'HARD', n.get('fails')))
        elif b.get('ok') and n.get('ok') and \
                (n.get('soft_score') or 0) - (b.get('soft_score') or 0) > a.soft_thr:
            regressed.append((sid, 'SOFT',
                              [b.get('soft_score'), n.get('soft_score')]))
    regressed.sort(key=lambda r: (r[1] != 'HARD',))
    regressed = regressed[:a.max_scenes]
    print(f'регресс-сцен к бисекту: {len(regressed)}')

    occ0 = open(OCC).read()

    def set_occ(kw):
        o = json.loads(occ0)
        for k, v in (kw or {}).items():
            o['distances_cm'][k] = v
        open(OCC, 'w').write(json.dumps(o, ensure_ascii=False, indent=1))

    results = []
    try:
        for sid, kind, detail in regressed:
            row = {'scene': sid, 'kind': kind, 'detail': detail, 'culprits': []}
            b_soft = base[sid].get('soft_score') or 0
            for d in deltas:
                set_occ(d.get('occupancy'))
                try:
                    fails, soft = run_scene(scenes[sid], d.get('env'))
                except Exception as e:  # noqa: BLE001 — фиксируем, не молчим
                    row['culprits'].append({'delta': d['name'],
                                            'result': f'ERROR {e}'})
                    continue
                fixed = (kind == 'HARD' and not fails) or \
                        (kind == 'SOFT' and soft is not None
                         and soft - b_soft <= a.soft_thr)
                row['culprits'].append({'delta': d['name'], 'fails': len(fails),
                                        'soft': soft, 'fixes': fixed})
                print(f"  {sid} | без «{d['name']}» | fails={len(fails)} "
                      f"soft={soft} {'← ВИНОВНИК' if fixed else ''}",
                      flush=True)
            results.append(row)
    finally:
        open(OCC, 'w').write(occ0)
        print('occupancy восстановлен')

    # свод: какая правка чинит сколько сцен
    tally = {}
    for row in results:
        for c in row['culprits']:
            if c.get('fixes'):
                tally[c['delta']] = tally.get(c['delta'], 0) + 1
    out = {'regressed': len(regressed), 'tally': tally, 'rows': results}
    json.dump(out, open(os.path.join(HERE, 'bisect-report.json'), 'w'),
              ensure_ascii=False, indent=1)
    print('ВИНОВНИКИ (правка → сколько сцен чинит её откат):',
          json.dumps(tally, ensure_ascii=False))


if __name__ == '__main__':
    main()
