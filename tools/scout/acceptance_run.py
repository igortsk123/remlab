#!/usr/bin/env python3
"""Z5: прогон зафиксированного приёмочного набора (acceptance-scenes.json) одним или двумя
движками (A/B: beam vs zoned). Для каждой сцены — solver_run --v3 с геометрией сцены; итог —
acceptance-report-<engine>.json + сводка: чистых / hard-провалов / неразмещённых / медиана soft.

Запуск: ~/venvs/scout/bin/python acceptance_run.py [beam|zoned|ab] [N_from N_to]
По умолчанию ab (оба движка). Сцены режутся диапазоном НОМЕРОВ СЕТОВ (не сцен).
"""
import json
import os
import re
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.expanduser('~/venvs/scout/bin/python')
SCENES = json.load(open(os.path.join(HERE, 'acceptance-scenes.json')))
mode = sys.argv[1] if len(sys.argv) > 1 else 'ab'
nums = [a for a in sys.argv[2:] if a.isdigit()]
if len(nums) >= 2:
    a, b = int(nums[0]), int(nums[1])
    SCENES = [sc for sc in SCENES if a <= sc['set'] <= b]


def run_engine(engine):
    report = []
    for sc in SCENES:
        env = dict(os.environ, LAYOUT_ENGINE=engine, LAYOUT_SUFFIX=f'-acc-{engine}')
        args = [PY, os.path.join(HERE, 'solver_run.py'), str(sc['set']), '--v3']
        if sc['kind'] == 'contour':
            xs = [p[0] for p in sc['contour']]; ys = [p[1] for p in sc['contour']]
            env['SCENE_CONTOUR'] = json.dumps(sc['contour'])
            args += [str(max(xs)), str(max(ys))]
        elif 'w' in sc:
            args += [str(sc['w']), str(sc['d'])]
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=300, env=env)
        except subprocess.TimeoutExpired:
            report.append(dict(scene=sc['id'], set=sc['set'], ok=False,
                               fails=['TIMEOUT'], missing=[], soft_score=None))
            print(f"{sc['id']} [{engine}]: TIMEOUT", flush=True)
            continue
        out = r.stdout
        fails = [l.strip() for l in out.splitlines() if l.startswith('FAIL')]
        m = re.search(r'НЕ размещены: (\[.*\])', out)
        missing = eval(m.group(1)) if m else []
        msoft = re.search(r'^SOFT (\{.*\})$', out, re.M)
        soft = json.loads(msoft.group(1)) if msoft else {}
        dumb = round(sum(soft.get('terms', {}).values()), 1)
        ok = not fails and not missing and r.returncode == 0
        report.append(dict(scene=sc['id'], set=sc['set'], ok=ok, fails=fails,
                           missing=missing, soft_score=dumb,
                           group=(re.search(r'зонная группа: (\S+)', out) or [None, None])[1]))
        print(f"{sc['id']} [{engine}]: " + ('OK' if ok else f'FAIL {fails} miss={missing}')
              + f' soft={dumb}', flush=True)
    json.dump(report, open(os.path.join(HERE, f'acceptance-report-{engine}.json'), 'w'),
              ensure_ascii=False, indent=1)
    return report


def summary(engine, rep):
    okc = sum(1 for r in rep if r['ok'])
    softs = [r['soft_score'] for r in rep if r['ok'] and r['soft_score'] is not None]
    med = statistics.median(softs) if softs else 0
    dumb = sum(1 for x in softs if x > float(os.environ.get('DUMB_T', '12')))
    print(f'\n[{engine}] чистых {okc}/{len(rep)}; медиана soft {med}; «глупых» {dumb}')
    return okc, med, dumb


engines = ['beam', 'zoned'] if mode == 'ab' else [mode]
results = {e: run_engine(e) for e in engines}
for e in engines:
    summary(e, results[e])
if len(engines) == 2:
    flips = [(r1['scene'], r1['ok'], r2['ok'])
             for r1, r2 in zip(results['beam'], results['zoned']) if r1['ok'] != r2['ok']]
    print(f'разошлись по чистоте: {len(flips)}')
    for sc, b1, b2 in flips[:20]:
        print(f'  {sc}: beam={"OK" if b1 else "fail"} zoned={"OK" if b2 else "fail"}')
