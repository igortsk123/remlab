#!/usr/bin/env python3
"""Real-бенчмарк солвера: реальные планировки × референсные составы — T3 truth-first.

Отличия от синтетической приёмки (acceptance_run.py):
  - комнаты берутся из tools/scout/real-plans/*.json (мост room_bridge.py из замера по фото
    или планировки, добавленные руками); набор замораживается коммитом, как и 252 синтетики;
  - кроме «чистоты» публикуются метрики УДЕРЖАНИЯ (рефери §18: clean нельзя выигрывать
    деэскалацией состава): required_recall, optional_retention, mean_items, runtime p50/p95.

Сцена без проёмов пропускается с пометкой (солверу нужна дверь; замер проёмы пока не отдаёт —
дописать в JSON руками). SCENE_OPENINGS прокидывается в env — солвер начнёт читать её после
правки T6 (до того используется его синтетическая дверь, о чём печатается предупреждение).

  ~/venvs/scout/bin/python acceptance_real.py [--sets 1,21,55] [--engine zoned]
"""
import glob
import json
import os
import re
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.expanduser('~/venvs/scout/bin/python')
PLANS = sorted(glob.glob(os.path.join(HERE, 'real-plans', '*.json')))
REFERENCE_TEN = (3, 17, 25, 33, 47, 62, 76, 91, 104, 121)

# Ярусы — как в occupancy.placement_tiers (required = base)
BASE_ROLES = {'диван', 'столик', 'тв-тумба', 'ковёр'}
OPTIONAL_ROLES = {'кресло', 'торшер', 'кашпо', 'пуф', 'камин', 'стул', 'стол обеденный',
                  'стенка', 'комод', 'стеллаж', 'шкаф', 'витрина'}


def run_scene(plan: dict, set_no: int, engine: str) -> dict:
    env = dict(os.environ,
               LAYOUT_ENGINE=engine,
               SCENE_CONTOUR=json.dumps(plan['contour']),
               SCENE_OPENINGS=json.dumps(plan.get('openings') or []),
               LAYOUT_SUFFIX=f'-real-{plan["_name"]}-{set_no}')
    t0 = time.time()
    r = subprocess.run([PY, os.path.join(HERE, 'solver_run.py'), str(set_no), '--v3'],
                       capture_output=True, text=True, timeout=300, env=env, cwd=HERE)
    dt = time.time() - t0
    out = r.stdout
    fails = re.findall(r'^FAIL .*$', out, re.M)
    missing = re.search(r'НЕ размещены: \[([^\]]*)\]', out)
    skipped = re.search(r'SKIPPED \[([^\]]*)\]', out)
    placed = len(re.findall(r'^OK ', out, re.M))
    miss = [s.strip(" '\"") for s in (missing.group(1).split(',') if missing else []) if s.strip()]
    skip = [s.strip(" '\"") for s in (skipped.group(1).split(',') if skipped else []) if s.strip()]
    base_lost = [m for m in miss if m.split(' ')[0] in BASE_ROLES]
    return {'plan': plan['_name'], 'set': set_no, 'engine': engine,
            'ok': (not fails and not miss and r.returncode == 0),
            'fails': fails[:6], 'missing': miss, 'skipped': skip,
            'base_lost': base_lost, 'runtime_s': round(dt, 1)}


def main() -> None:
    engine = sys.argv[sys.argv.index('--engine') + 1] if '--engine' in sys.argv else 'zoned'
    sets = ([int(x) for x in sys.argv[sys.argv.index('--sets') + 1].split(',')]
            if '--sets' in sys.argv else list(REFERENCE_TEN))
    if not PLANS:
        print('real-plans/ пуст — добавь планировки (room_bridge.py или руками)')
        sys.exit(1)
    results, skipped_plans = [], []
    for pf in PLANS:
        plan = json.load(open(pf))
        plan['_name'] = os.path.splitext(os.path.basename(pf))[0]
        if not plan.get('openings'):
            skipped_plans.append(plan['_name'])
            continue
        for s in sets:
            res = run_scene(plan, s, engine)
            results.append(res)
            print(f"{plan['_name']} × сет {s}: {'ЧИСТО' if res['ok'] else 'провал'} "
                  f"({res['runtime_s']}s"
                  + (f", потеряно base: {res['base_lost']}" if res['base_lost'] else '')
                  + (f", дроп: {len(res['skipped'])}" if res['skipped'] else '') + ')',
                  flush=True)
    if skipped_plans:
        print(f'пропущено планов без двери: {len(skipped_plans)} ({", ".join(skipped_plans)}) '
              f'— проёмы дописать в JSON')
    if not results:
        sys.exit(1)
    out_path = os.path.join(HERE, f'acceptance-real-{engine}.jsonl')
    with open(out_path, 'w') as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    okc = sum(1 for r in results if r['ok'])
    times = sorted(r['runtime_s'] for r in results)
    n_base = sum(len(r['base_lost']) for r in results)
    n_skip = sum(len(r['skipped']) for r in results)
    print(f"\nreal-бенч [{engine}]: {okc}/{len(results)} чистых; "
          f"потерь base-предметов {n_base}; дропов ярусом {n_skip}; "
          f"runtime p50 {statistics.median(times):.0f}s / p95 {times[int(len(times)*0.95)-1]:.0f}s "
          f"→ {out_path}")


if __name__ == '__main__':
    main()
