#!/usr/bin/env python3
"""Стенд «новый банк рядом» (план conv-13): копия банка не пишет живой `sets3.json` и общие файлы прогона.

Быстрая часть (CI): пути и отказы `bank_paths`, fail-closed ворот сборщика `compose_gates`, демо с копией банка —
свой `demo-sets.json`, свои раскладки, `--publish` из чужой папки — отказ; без env всё как раньше.
Живая часть (`--live`, только DEV — нужен `sets3.json` и солвер): одна сцена экзамена на КОПИИ банка со своим
суффиксом; хеши живого банка, `demo-sets.json`, снимка экзамена, `scene-durations.json`, основных отчётов и всех
раскладок до и после должны совпасть. Свои артефакты стенд убирает.

  python3 tests_bank_isolation.py            # CI
  ~/venvs/scout/bin/python tests_bank_isolation.py --live
"""
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FAILS: list[str] = []


def check(cond: bool, name: str) -> None:
    print(('  ✓ ' if cond else '  ✗ ') + name, flush=True)
    if not cond:
        FAILS.append(name)


def run_py(code: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, '-c', code], cwd=HERE, env=dict(os.environ, **env),
                          capture_output=True, text=True, timeout=120)


def case_units() -> None:
    for m in ('bank_paths', 'compose_gates'):
        r = subprocess.run([sys.executable, os.path.join(HERE, f'{m}.py'), '--selftest'], capture_output=True, text=True)
        print(r.stdout.rstrip())
        check(r.returncode == 0, f'{m} --selftest')


def case_demo() -> None:
    probe = ("import flat215_demo as D, json; print(json.dumps({'sets': D.DEMO_SETS, 'lay': D.layout_path(7), "
             "'bank': D.BANK['bank'], 'live': D.BANK['live']}))")
    env0 = {k: '' for k in ('SETS_BANK', 'FLAT215_DEMO_OUT')}
    r = run_py(probe, env0)
    d = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else {}
    check(d.get('sets') == os.path.join(HERE, 'demo-sets.json') and d.get('lay') == os.path.join(HERE, 'v3set7-layout.json')
          and d.get('live') is True, f'демо без env — как раньше ({r.stderr.strip()[-120:]})')
    with tempfile.TemporaryDirectory() as td:
        cp, out = os.path.join(td, 'sets3.next.json'), os.path.join(td, 'demo')
        open(cp, 'w').write('[]')
        r = run_py(probe, {'SETS_BANK': cp, 'FLAT215_DEMO_OUT': out})
        d = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else {}
        check(d.get('sets') == os.path.join(out, 'demo-sets.json') and '-demo-' in os.path.basename(d.get('lay', ''))
              and d.get('bank') == cp and d.get('live') is False, 'демо на копии: свой demo-sets в OUT, свои раскладки')
        r = run_py(probe, {'SETS_BANK': cp, 'FLAT215_DEMO_OUT': ''})
        check(r.returncode != 0 and 'FLAT215_DEMO_OUT' in (r.stdout + r.stderr), 'демо на копии в папку витрины — отказ')
        r = run_py("import sys, flat215_demo as D; sys.argv = ['x', '--publish']; D.build = None; D.main()",
                   {'SETS_BANK': '', 'FLAT215_DEMO_OUT': out})
        check(r.returncode != 0 and 'публикуется только папка витрины' in (r.stdout + r.stderr),
              '--publish со сборкой не в папке витрины — отказ ДО сборки')


def _hashes(paths: list[str]) -> dict:
    return {p: (hashlib.sha256(open(p, 'rb').read()).hexdigest() if os.path.exists(p) else None) for p in paths}


def case_live_acceptance() -> None:
    live = os.path.join(HERE, 'sets3.json')
    if not os.path.exists(live):
        check(False, 'нет sets3.json — живая часть только на DEV')
        return
    shared = [live, os.path.join(HERE, 'demo-sets.json'), os.path.join(HERE, 'sets3.snapshot.json'),
              os.path.join(HERE, 'scene-durations.json')]
    shared += glob.glob(os.path.join(HERE, 'acceptance-report-*.json*'))
    shared += glob.glob(os.path.join(HERE, 'v3set*-layout*.json'))
    sfx = f'-isotest{os.getpid()}'
    scenes = json.load(open(os.path.join(HERE, 'acceptance-scenes.json'), encoding='utf-8'))
    dur = {}
    try:
        dur = json.load(open(os.path.join(HERE, 'scene-durations.json'), encoding='utf-8'))
    except (OSError, ValueError):
        pass
    sc = min((s for s in scenes if s.get('kind') not in ('demo', 'contour')), key=lambda s: float(dur.get(s['id'], 60)))
    # файлы, которые прогон БЕЗ копии написал бы для этой сцены, — даже если их ещё нет (в worktree их нет)
    shared += [os.path.join(HERE, f'acceptance-report-zoned.{x}') for x in ('json', 'jsonl')]
    shared += [os.path.join(HERE, f"v3set{sc['set']}-layout-acc-zoned-{sc['id']}.json")]
    shared = sorted(set(shared))
    before = _hashes(shared)
    files0 = set(os.listdir(HERE))
    td = tempfile.mkdtemp(prefix='bankiso-')
    try:
        cp = os.path.join(td, 'sets3.next.json')
        shutil.copyfile(live, cp)
        env = dict(os.environ, SETS_BANK=cp, ACC_REPORT_SUFFIX=sfx, ACC_SCENES=sc['id'], ACC_WORKERS='1')
        r = subprocess.run([sys.executable, os.path.join(HERE, 'acceptance_run.py'), 'zoned'], cwd=HERE, env=env,
                           capture_output=True, text=True, timeout=1200)
        print('  ' + ' | '.join((r.stdout or '').strip().splitlines()[-3:]))
        check(r.returncode == 0 and f'БАНК: {cp}' in r.stdout, f'экзамен на копии прошёл, сцена {sc["id"]}')
        rep = os.path.join(HERE, f'acceptance-report-zoned{sfx}.json')
        check(os.path.exists(rep) and len(json.load(open(rep))) == 1, 'отчёт копии — свой файл с суффиксом')
        own = glob.glob(os.path.join(HERE, f'v3set*-layout{sfx}-acc-zoned-*.json'))
        check(len(own) == 1, f'раскладка копии — со своим суффиксом ({[os.path.basename(x) for x in own]})')
        after = _hashes(shared)
        changed = [os.path.basename(p) for p in shared if before[p] != after[p]]
        check(not changed, f'живой банк и общие файлы не изменились (хеш до/после, файлов {len(shared)}; изменились: {changed})')
        new = sorted(f for f in set(os.listdir(HERE)) - files0 if sfx not in f and f != '__pycache__')
        check(not new, f'других новых файлов рядом с банком нет ({new})')
        r = subprocess.run([sys.executable, os.path.join(HERE, 'acceptance_run.py'), 'zoned'], cwd=HERE,
                           env=dict(env, ACC_REPORT_SUFFIX=''), capture_output=True, text=True, timeout=60)
        check(r.returncode != 0 and 'ACC_REPORT_SUFFIX' in (r.stdout + r.stderr), 'экзамен на копии без суффикса — отказ')
    finally:
        shutil.rmtree(td, ignore_errors=True)
        for p in glob.glob(os.path.join(HERE, f'acceptance-report-zoned{sfx}.json*')) \
                + glob.glob(os.path.join(HERE, f'v3set*-layout{sfx}-acc-*')):
            os.remove(p)


def main() -> int:
    print('== пути и ворота'); case_units()
    print('== демо'); case_demo()
    if '--live' in sys.argv:
        print('== экзамен на копии банка (живой)'); case_live_acceptance()
    print('стенд «банк рядом»: ' + ('ВСЁ ЗЕЛЁНОЕ' if not FAILS else f'провалов {len(FAILS)}'))
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
