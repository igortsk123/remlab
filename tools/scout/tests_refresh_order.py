#!/usr/bin/env python3
"""ПОРЯДОК ШАГОВ НОЧИ ВОКРУГ БАНКА — при выключенном писателе ровно как прежде (conv-14 шаги 4–5, T-20261022-22/1).

ЗАЧЕМ. Писатель живого банка `bank_refresh` встаёт за флагом `rules/bank-candidate.json:write_enabled`; включённый, он
переставляет `sets_reindex`/`set_ids`/`resolve_affected` за себя и снимает прежние --apply-писатели. Выключенный — ночь обязана
идти ровно как раньше: те же шаги, тем же порядком, с теми же аргументами, без пропусков и двойного запуска. Проверяем не текст,
а исполнение: хвост `refresh_daily.sh` (от `step sets_index` до конца) запускается настоящим bash, где `step` только записывает
имя и команду, `date +%u` подставлен (понедельник/среда), `exam.lock` есть/нет, а флаг отдаёт заглушка `bank_refresh.py --enabled`.

  python3 tests_refresh_order.py --selftest                # структура при false и true
  python3 tests_refresh_order.py --against main            # при false — шаг в шаг как в ветке/коммите main (все 4 сочетания)
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, 'refresh_daily.sh')
START = 'step sets_index '

PRELUDE = r'''set -u
cd "$TD"
LOG="$TD/log"; STAMP="$TD/stamp"; today=x; PY="$TD/py"
declare -A RES; RES[candidates]=ok; RES[sets_index]=ok
step() { local n="$1"; shift; local c="$*"; echo "$n :: ${c//$PY/\$PY}" >> "$TD/steps"; RES[$n]=ok; return 0; }
paid_step() { step "$@"; }
date() { if [ "${1:-}" = "+%u" ]; then echo "$WEEKDAY"; else command date "$@"; fi; }
'''
PY_STUB = '#!/bin/bash\nif [ "${1:-}" = bank_refresh.py ] && [ "${2:-}" = --enabled ]; then echo "$BANK_WRITE_STUB"; fi\nexit 0\n'


def tail(text: str) -> str:
    i = text.index('\n' + START) + 1
    return text[i:]


def night(text: str, write: int, weekday: int = 3, lock: bool = False) -> list[str]:
    """Шаги хвоста ночи по порядку: «имя :: команда»."""
    with tempfile.TemporaryDirectory(prefix='night-order-') as td:
        open(os.path.join(td, 'py'), 'w').write(PY_STUB)
        os.chmod(os.path.join(td, 'py'), 0o755)
        if lock:
            open(os.path.join(td, 'exam.lock'), 'w').close()
        sh = os.path.join(td, 'run.sh')
        open(sh, 'w', encoding='utf-8').write(PRELUDE + tail(text))
        p = subprocess.run(['bash', sh], env={**os.environ, 'TD': td, 'WEEKDAY': str(weekday), 'BANK_WRITE_STUB': str(write)},
                           capture_output=True, text=True, timeout=60)
        if p.returncode:
            raise RuntimeError(f'bash rc={p.returncode}: {p.stderr[-400:]}')
        try:
            return open(os.path.join(td, 'steps'), encoding='utf-8').read().splitlines()
        except FileNotFoundError:
            return []


def names(steps: list[str]) -> list[str]:
    return [s.split(' :: ', 1)[0] for s in steps]


COMBOS = [(wd, lock) for wd in (1, 3) for lock in (False, True)]


def against(ref: str) -> int:
    old = subprocess.run(['git', '-C', HERE, 'show', f'{ref}:tools/scout/refresh_daily.sh'], capture_output=True, text=True)
    if old.returncode:
        print(f'git show {ref}: {old.stderr.strip()}')
        return 2
    new = open(SCRIPT, encoding='utf-8').read()
    bad = 0
    for wd, lock in COMBOS:
        a, b = night(old.stdout, 0, wd, lock), night(new, 0, wd, lock)
        same = a == b
        bad += 0 if same else 1
        print(f"  {'✓' if same else '✗'} write_enabled=false, {'понедельник' if wd == 1 else 'среда'}"
              f"{', exam.lock' if lock else ''}: шагов {len(b)} против {len(a)} в {ref}" + ('' if same else ' — РАЗНИЦА'))
        if not same:
            import difflib
            print('\n'.join(difflib.unified_diff(a, b, ref, 'рабочая копия', lineterm='', n=1)))
    a1 = night(new, 1, 1, False)
    print(f'  write_enabled=true, понедельник: шагов {len(a1)}; ' + ' → '.join(n for n in names(a1)
          if n in ('bank_media', 'bank_photos', 'bank_media2', 'bank_prepare', 'bank_promote', 'bank_refresh', 'sets_reindex',
                   'set_ids', 'resolve_affected', 'demo_band', 'solver_full', 'sets_reindex_w')))
    print(f'tests_refresh_order --against {ref}: расхождений {bad}')
    return 1 if bad else 0


def _selftest() -> int:
    bad = 0

    def ok(name, cond, extra=''):
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
        bad += 0 if cond else 1
    text = open(SCRIPT, encoding='utf-8').read()
    OLD_WRITERS = ('sets_heal', 'sets_pairs', 'sets_contracts', 'sets_refresh', 'sets_pairs_w')
    IDX = ('sets_reindex', 'set_ids', 'resolve_affected')
    for wd, lock in COMBOS:
        tag = f"{'пн' if wd == 1 else 'ср'}{', exam.lock' if lock else ''}"
        f, t = night(text, 0, wd, lock), night(text, 1, wd, lock)
        fn, tn = names(f), names(t)
        ok(f'[{tag}] каждый шаг — один раз (false и true)', len(fn) == len(set(fn)) and len(tn) == len(set(tn)),
           [n for n in fn if fn.count(n) > 1] + [n for n in tn if tn.count(n) > 1])
        ok(f'[{tag}] false: писателя нет; индекс, set_id и пересчёт — на прежнем месте (до changes_page и bank_prepare)',
           'bank_refresh' not in fn and all(n in fn for n in IDX)
           and fn.index('set_ids') == fn.index('sets_reindex') + 1 and fn.index('resolve_affected') == fn.index('set_ids') + 1
           and fn.index('changes_page') == fn.index('resolve_affected') + 1 and fn.index('resolve_affected') < fn.index('bank_prepare'))
        ok(f'[{tag}] false: медиа пишет банк (--apply)', all(s.endswith('catalog_media.py --apply') for s in f
                                                              if s.startswith('bank_media')))
        ok(f'[{tag}] true: писатель сразу за bank_promote, за ним индекс, set_id, пересчёт сцен, затем demo_band',
           tn[tn.index('bank_promote') + 1:tn.index('bank_promote') + 6] == ['bank_refresh', *IDX, 'demo_band'],
           tn[tn.index('bank_promote'):tn.index('bank_promote') + 6])
        ok(f'[{tag}] true: прежних --apply-писателей нет, медиа — сухим прогоном',
           not any(n in tn for n in OLD_WRITERS) and not any('--apply' in s for s in t if s.startswith('bank_media')))
        want = [n for n in fn if n not in OLD_WRITERS and n not in IDX]
        i = want.index('bank_promote') + 1
        ok(f'[{tag}] true: остальные шаги — те же и в том же порядке', tn == want[:i] + ['bank_refresh', *IDX] + want[i:])
        if wd == 1 and not lock:
            ok('[пн] false: недельные sets_refresh и sets_pairs_w идут', 'sets_refresh' in fn and 'sets_pairs_w' in fn)
    ok('флаг не прочитан (заглушка молчит) — ночь как при false', names(night(text, 0)) == names(night(text.replace(
        'BANK_WRITE=$("$PY" bank_refresh.py --enabled 2>/dev/null || echo 0)', 'BANK_WRITE=""'), 1)))
    print(f'tests_refresh_order selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--against' in sys.argv:
        sys.exit(against(sys.argv[sys.argv.index('--against') + 1]))
    sys.exit(_selftest())
