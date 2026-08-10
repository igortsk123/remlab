#!/usr/bin/env python3
"""Z5: прогон зафиксированного приёмочного набора (acceptance-scenes.json) одним или двумя
движками (A/B: beam vs zoned). Для каждой сцены — solver_run --v3 с геометрией сцены; итог —
acceptance-report-<engine>.json + сводка: чистых / hard-провалов / неразмещённых / медиана soft.

Запуск: ~/venvs/scout/bin/python acceptance_run.py [beam|zoned|ab] [N_from N_to]
По умолчанию ab (оба движка). Сцены режутся диапазоном НОМЕРОВ СЕТОВ (не сцен).
"""
import concurrent.futures as cf
import json
import os
import re
import statistics
import subprocess
import sys
import threading

WORKERS = int(os.environ.get('ACC_WORKERS', '4'))   # RAM 4 ГБ: 4 солвера параллельно — безопасно

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.expanduser('~/venvs/scout/bin/python')
SCENES = json.load(open(os.path.join(HERE, 'acceptance-scenes.json')))
mode = sys.argv[1] if len(sys.argv) > 1 else 'ab'
nums = [a for a in sys.argv[2:] if a.isdigit()]
if len(nums) >= 2:
    a, b = int(nums[0]), int(nums[1])
    SCENES = [sc for sc in SCENES if a <= sc['set'] <= b]


def _one(engine, sc):
    """Один прогон сцены; уникальный LAYOUT_SUFFIX на СЦЕНУ — параллельные воркеры не дерутся
    за файлы раскладок (set3-base и set3-pylons писали бы в один v3set3-layout-*.json)."""
    env = dict(os.environ, LAYOUT_ENGINE=engine, LAYOUT_SUFFIX=f"-acc-{engine}-{sc['id']}")
    args = [PY, os.path.join(HERE, 'solver_run.py'), str(sc['set']), '--v3']
    if sc['kind'] == 'contour':
        xs = [p[0] for p in sc['contour']]; ys = [p[1] for p in sc['contour']]
        env['SCENE_CONTOUR'] = json.dumps(sc['contour'])
        args += [str(max(xs)), str(max(ys))]
    elif 'w' in sc:
        args += [str(sc['w']), str(sc['d'])]
    try:
        # W5 (урок 213 + 10.08): при >2 воркерах контеншн замедляет тяжёлые сцены —
        # таймаут 600, чтобы они ДОСЧИТЫВАЛИСЬ, а не падали ложным TIMEOUT
        r = subprocess.run(args, capture_output=True, text=True, timeout=600, env=env)
    except subprocess.TimeoutExpired:
        return dict(scene=sc['id'], set=sc['set'], ok=False,
                    fails=['TIMEOUT'], missing=[], soft_score=None)
    out = r.stdout
    fails = [l.strip() for l in out.splitlines() if l.startswith('FAIL')]
    m = re.search(r'НЕ размещены: (\[.*\])', out)
    missing = eval(m.group(1)) if m else []
    msoft = re.search(r'^SOFT (\{.*\})$', out, re.M)
    soft = json.loads(msoft.group(1)) if msoft else {}
    dumb = round(sum(soft.get('terms', {}).values()), 1)
    mskip = re.search(r'^SKIPPED (\[.*\])$', out, re.M)
    skipped = json.loads(mskip.group(1)) if mskip else []
    ok = not fails and not missing and r.returncode == 0
    rec = dict(scene=sc['id'], set=sc['set'], ok=ok, fails=fails,
               missing=missing, skipped=skipped, soft_score=dumb,
               group=(re.search(r'зонная группа: (\S+)', out) or [None, None])[1],
               topo=(re.search(r'^TOPO (.+)$', out, re.M) or [None, None])[1])
    if r.returncode != 0:   # крэш без FAIL-строк иначе неотличим от «просто не ok»
        rec['rc'] = r.returncode
        rec['err'] = (r.stderr or '').strip()[-400:]
    return rec


def run_engine(engine):
    """Параллельно (ACC_WORKERS), с покадровой записью в jsonl: упавший/убитый прогон
    не теряет готовые сцены — при рестарте они читаются из jsonl и не пересчитываются."""
    jl_path = os.path.join(HERE, f'acceptance-report-{engine}.jsonl')
    done = {}
    if os.path.exists(jl_path):
        for line in open(jl_path):
            try:
                rec = json.loads(line); done[rec['scene']] = rec
            except Exception:
                pass
        if done:
            print(f'[{engine}] из jsonl подхвачено готовых: {len(done)}', flush=True)
    todo = [sc for sc in SCENES if sc['id'] not in done]
    lock = threading.Lock()
    jl = open(jl_path, 'a')
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(_one, engine, sc): sc for sc in todo}
        for fut in cf.as_completed(futs):
            rec = fut.result()
            with lock:
                done[rec['scene']] = rec
                jl.write(json.dumps(rec, ensure_ascii=False) + '\n'); jl.flush()
            print(f"{rec['scene']} [{engine}]: "
                  + ('OK' if rec['ok'] else f"FAIL {rec['fails']} miss={rec['missing']}")
                  + f" soft={rec['soft_score']} [{len(done)}/{len(SCENES)}]", flush=True)
    jl.close()
    report = [done[sc['id']] for sc in SCENES if sc['id'] in done]
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
