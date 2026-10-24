#!/usr/bin/env python3
"""ПОВТОРЯЕМОСТЬ СБОРКИ КАНДИДАТА (план conv-14b задача 2, критерий «один снимок, три seed: 126/126 одинаковых selection_hash»).

ЗАЧЕМ. Ночь 23.10: кандидат и проба через 30 минут совпали в 1109 из 2754 позиций. Часть расхождения — неполный ключ ничьей
(`compose2.pick2`: при равных балле и цене решал порядок пула). Тест собирает кандидат несколько раз с разным `PYTHONHASHSEED` на
одном снимке и сравнивает выбор по ячейкам: роли/SKU/кол-во (`bank_keep.selection_hash`) и полный отпечаток (`bank_pending.candidate_hash`).

ТОЛЬКО НА КОПИИ папки сборщика: прогон пишет кэши фото и эмбеддингов рядом со сборщиком, а кроны DEV берут код и кэши из основной
копии. Копия — `rsync` основной `tools/scout` в `<копия>/tools/scout` + ссылки `<копия>/services`, `data`, `docs` на основную.
Ручной тест (нужна база каталога, ~11 мин на прогон), в CI не идёт. Первым идёт прогон-разогрев: кэш фото докачивается сетью,
а сбой загрузки — отдельный, не проверяемый здесь источник расхождения.

  ~/venvs/scout/bin/python tests_compose_seeds.py --copy ~/.cache/bankkept/copy-… [--seeds 0,1,2,3]
  python3 tests_compose_seeds.py --compare a.json b.json [c.json …]      # только сравнение готовых сборок
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def selections(path: str) -> dict:
    import bank_keep as BK
    import bank_pending as BP
    return {BK.key(s): (BK.selection_hash(s), BP.candidate_hash(s)) for s in json.load(open(path, encoding='utf-8'))}


def compare(paths: list) -> int:
    base = selections(paths[0])
    bad = 0
    for p in paths[1:]:
        cur = selections(p)
        sel = sum(1 for k in base if k in cur and cur[k][0] == base[k][0])
        full = sum(1 for k in base if k in cur and cur[k][1] == base[k][1])
        diff = sorted(k for k in base if cur.get(k, (None,))[0] != base[k][0])
        print(f'{os.path.basename(paths[0])} ↔ {os.path.basename(p)}: тот же выбор {sel}/{len(base)}, '
              f'тот же полный отпечаток {full}/{len(base)}' + (f'; разные: {diff[:8]}' if diff else ''))
        bad += sel != len(base) or len(cur) != len(base)
    return 1 if bad else 0


def run(copy: str, seeds: list) -> int:
    scout = os.path.join(os.path.abspath(copy), 'tools', 'scout')
    if os.path.realpath(scout) == os.path.realpath(HERE):
        raise SystemExit('--copy — это сам сборщик; прогоны только на копии (кроны DEV берут код и кэши отсюда)')
    out = os.path.join(os.path.abspath(copy), 'out')
    os.makedirs(out, exist_ok=True)
    paths = []
    for sd in seeds:
        p = os.path.join(out, f'seed{sd}-{time.strftime("%H%M")}.json')
        t0 = time.time()
        env = {**os.environ, 'PYTHONHASHSEED': str(sd), 'SETS_OUTPUT': p}
        env.pop('BANK_KEEP_FROM', None)                     # без удержания: проверяем саму сборку
        with open(p[:-5] + '.log', 'w', encoding='utf-8') as log:
            rc = subprocess.run([sys.executable, 'compose2.py', '--style', '--bands', 'all'], cwd=scout, env=env,
                                stdout=log, stderr=subprocess.STDOUT).returncode
        print(f'seed {sd}: rc={rc} за {time.time() - t0:.0f} с → {p}', flush=True)
        if rc:
            return rc
        paths.append(p)
    return compare(paths[1:] if len(paths) > 2 else paths)   # первый — разогрев кэшей


if __name__ == '__main__':
    a = sys.argv[1:]
    if '--compare' in a:
        sys.exit(compare(a[a.index('--compare') + 1:]))
    if '--copy' in a:
        seeds = [int(x) for x in (a[a.index('--seeds') + 1] if '--seeds' in a else '0,1,2,3').split(',')]
        sys.exit(run(a[a.index('--copy') + 1], seeds))
    print(__doc__)
