#!/usr/bin/env python3
"""ПОРЯДОК ШАГОВ НОЧИ ВОКРУГ БАНКА — при выключенном писателе ровно как прежде (conv-14 шаги 4–5, T-20261022-22/1).

ЗАЧЕМ. Писатель живого банка `bank_refresh` встаёт за флагом `rules/bank-candidate.json:write_enabled`; включённый, он
переставляет `sets_reindex`/`set_ids`/`resolve_affected` за себя и снимает прежние --apply-писатели. Выключенный — ночь обязана
идти ровно как раньше: те же шаги, тем же порядком, с теми же аргументами, без пропусков и двойного запуска. Проверяем не текст,
а исполнение: хвост `refresh_daily.sh` (от `step sets_index` до конца) запускается настоящим bash, где `step` только записывает
имя и команду, `date +%u` подставлен (понедельник/среда), `exam.lock` есть/нет, а флаг отдаёт заглушка `bank_refresh.py --enabled`.
ЦЕПОЧКА БАНКА (room-bank-01 этап А): у prepare → pending → promote → refresh один номер ночи `--run-id`, шаги через `&&` — заглушка
`step` роняет выбранный шаг (`FAIL_STEP`), и проверяем: следующие шаги банка не идут, остальная ночь — та же, строка в дайджест есть.

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
HEAD = 'step load3 '        # вся ночь от загрузки фидов: каталоги комнат стоят в голове (T-20261106-84)

PRELUDE = r'''set -u
cd "$TD"
LOG="$TD/log"; STAMP="$TD/stamp"; today=x; PY="$TD/py"
declare -A RES; RES[candidates]=ok; RES[sets_index]=ok
step() { local n="$1"; shift; local c="$*"; local id="${BANK_RUN_ID:-}"; c="${c//$PY/\$PY}"; [ -n "$id" ] && c="${c//$id/\$BANK_RUN_ID}"
  echo "$n :: $c" >> "$TD/steps"; if [ "$n" = "${FAIL_STEP:-}" ]; then RES[$n]=FAIL; return 1; fi; RES[$n]=ok; return 0; }
paid_step() { step "$@"; }
date() { case "${1:-}" in +%u) echo "$WEEKDAY" ;; +%s) echo 0 ;; *) command date "$@" ;; esac; }   # +%s — метка в адресе, шаги сравнимы
'''
PY_STUB = '#!/bin/bash\nif [ "${1:-}" = bank_refresh.py ] && [ "${2:-}" = --enabled ]; then echo "$BANK_WRITE_STUB"; fi\nexit 0\n'


def tail(text: str, start: str = START) -> str:
    i = text.index('\n' + start) + 1
    return text[i:]


def night(text: str, write: int, weekday: int = 3, lock: bool = False, fail: str = '', start: str = START) -> list[str]:
    """Шаги хвоста ночи (или всей ночи от `start`) по порядку: «имя :: команда»."""
    return night_log(text, write, weekday, lock, fail, start)[0]


def night_log(text: str, write: int, weekday: int = 3, lock: bool = False, fail: str = '',
              start: str = START) -> tuple[list[str], str]:
    """(шаги, лог ночи): `fail` — шаг, который заглушка роняет (код 1); `start` — с какого шага (HEAD — вся ночь)."""
    with tempfile.TemporaryDirectory(prefix='night-order-') as td:
        open(os.path.join(td, 'py'), 'w').write(PY_STUB)
        os.chmod(os.path.join(td, 'py'), 0o755)
        if lock:
            open(os.path.join(td, 'exam.lock'), 'w').close()
        sh = os.path.join(td, 'run.sh')
        open(sh, 'w', encoding='utf-8').write(PRELUDE + tail(text, start))
        p = subprocess.run(['bash', sh], env={**os.environ, 'TD': td, 'WEEKDAY': str(weekday), 'BANK_WRITE_STUB': str(write),
                                              'FAIL_STEP': fail}, capture_output=True, text=True, timeout=60)
        if p.returncode:
            raise RuntimeError(f'bash rc={p.returncode}: {p.stderr[-400:]}')
        log = open(os.path.join(td, 'log'), encoding='utf-8').read() if os.path.exists(os.path.join(td, 'log')) else ''
        try:
            return open(os.path.join(td, 'steps'), encoding='utf-8').read().splitlines(), log
        except FileNotFoundError:
            return [], log


def names(steps: list[str]) -> list[str]:
    return [s.split(' :: ', 1)[0] for s in steps]


COMBOS = [(wd, lock) for wd in (1, 3) for lock in (False, True)]
# ГОЛОВА КОНВЕЙЕРА КОМНАТ (room-conveyor-02 К1, T-20261106-84): каталоги комнат — сразу за load3, шаги комнат — рядом с такими же
# шагами гостиной (`ROOM_AFTER`). В `--against` шаги комнат не считаем разницей — это сравнение остальной ночи с прежней.
ROOM_STEPS = ('hall_catalog', 'rooms_alive', 'style_bedroom', 'style_hall', 'rooms_cutout')
ROOM_ALL = ('room_catalog', *ROOM_STEPS)
ROOM_AFTER = {'load3': ['room_catalog', 'hall_catalog'], 'pool_photos': ['rooms_alive'],
              'style_score': ['style_bedroom', 'style_hall'], 'cutout': ['rooms_cutout']}


def against(ref: str) -> int:
    old = subprocess.run(['git', '-C', HERE, 'show', f'{ref}:tools/scout/refresh_daily.sh'], capture_output=True, text=True)
    if old.returncode:
        print(f'git show {ref}: {old.stderr.strip()}')
        return 2
    new = open(SCRIPT, encoding='utf-8').read()
    bad = 0
    for wd, lock in COMBOS:
        a = [x for x in night(old.stdout, 0, wd, lock, start=HEAD) if x.split(' :: ', 1)[0] not in ROOM_ALL]
        b = [x for x in night(new, 0, wd, lock, start=HEAD) if x.split(' :: ', 1)[0] not in ROOM_ALL]
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
                   'set_ids', 'resolve_affected', 'changes_page', 'reserve_cov', 'layout_page', 'demo_band', 'solver_full', 'sets_reindex_w')))
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
    IDX = ('sets_reindex', 'set_ids', 'resolve_affected', 'changes_page', 'reserve_cov', 'layout_page')
    for wd, lock in COMBOS:
        tag = f"{'пн' if wd == 1 else 'ср'}{', exam.lock' if lock else ''}"
        f, t = night(text, 0, wd, lock), night(text, 1, wd, lock)
        fn, tn = names(f), names(t)
        ok(f'[{tag}] каждый шаг — один раз (false и true)', len(fn) == len(set(fn)) and len(tn) == len(set(tn)),
           [n for n in fn if fn.count(n) > 1] + [n for n in tn if tn.count(n) > 1])
        ok(f'[{tag}] false: писателя нет; индекс, set_id, пересчёт и страницы — на прежнем месте, подряд, до bank_prepare',
           'bank_refresh' not in fn and all(n in fn for n in IDX)
           and fn[fn.index('sets_reindex'):fn.index('sets_reindex') + len(IDX)] == list(IDX)
           and fn.index('layout_page') < fn.index('bank_prepare'))
        ok(f'[{tag}] false: медиа пишет банк (--apply)', all(s.endswith('catalog_media.py --apply') for s in f
                                                              if s.startswith('bank_media')))
        k = tn.index('bank_promote') + 1
        ok(f'[{tag}] true: писатель сразу за bank_promote, за ним индекс, set_id, пересчёт сцен, страницы, затем demo_band',
           tn[k:k + len(IDX) + 2] == ['bank_refresh', *IDX, 'demo_band'], tn[k:k + len(IDX) + 2])
        wn = names(night(text, 0, wd, lock, start=HEAD))
        ok(f'[{tag}] каталог комнат → demo_band → mesh_publish → витрина (T-20261106-82/2: места комнат — из свежего room_catalog)',
           all(n.index('room_catalog') < n.index('demo_band') < n.index('mesh_publish') < n.index('flat215_demo')
               for n in (wn, names(night(text, 1, wd, lock, start=HEAD)))), wn)
        ok(f'[{tag}] true: прежних --apply-писателей нет, медиа — сухим прогоном',
           not any(n in tn for n in OLD_WRITERS) and not any('--apply' in s for s in t if s.startswith('bank_media')))
        want = [n for n in fn if n not in OLD_WRITERS and n not in IDX]
        i = want.index('bank_promote') + 1
        ok(f'[{tag}] true: остальные шаги — те же и в том же порядке', tn == want[:i] + ['bank_refresh', *IDX] + want[i:])
        ok(f'[{tag}] порядок кандидата (T-20261023-08, Codex 23.10; обогащение — выше, вне хвоста): семейства → привязка → bank_prepare → '
           'bank_pending --night → bank_promote (меш, привязанный этой ночью, promote видит в ту же ночь)',
           all(n.index('mesh_family_early') < n.index('mesh_bind_early') < n.index('bank_prepare')
               < n.index('bank_pending') < n.index('bank_promote') for n in (fn, tn))
           and any(x.startswith('bank_pending ::') and x.endswith('bank_pending.py --night --run-id $BANK_RUN_ID') for x in f),
           fn[fn.index('mesh_family_early'):fn.index('bank_promote') + 1])
        if wd == 1 and not lock:
            ok('[пн] false: недельные sets_refresh и sets_pairs_w идут', 'sets_refresh' in fn and 'sets_pairs_w' in fn)
    BANK = ('bank_prepare', 'bank_pending', 'bank_promote', 'bank_refresh')
    for write in (0, 1):
        full, log = night_log(text, write)
        mine = [s for s in full if s.split(' :: ', 1)[0] in BANK]
        ok(f'[write={write}] у шагов цепочки банка один номер ночи --run-id $BANK_RUN_ID; без сбоя — строки остановки нет',
           len(mine) == (4 if write else 3) and all(s.endswith('--run-id $BANK_RUN_ID') or '--run-id $BANK_RUN_ID ' in s
                                                     for s in mine) and 'цепочка ночи' not in log, mine)
        for k, failed in enumerate(BANK[:3]):
            got, log = night_log(text, write, fail=failed)
            gn, want = names(got), [n for n in names(full) if n not in BANK[k + 1:]]
            ok(f'[write={write}] упал {failed} — дальше шаги банка не идут ({", ".join(BANK[k + 1:3 + write]) or "их нет"}), '
               'остальная ночь та же и тем же порядком, строка в дайджест',
               gn == want and all(n not in gn for n in BANK[k + 1:]) and 'DIGEST:банк: цепочка ночи' in log
               and (not write or all(n in gn for n in IDX)), (gn, want, log[-300:]))
    full, log = night_log(text, 0, start=HEAD)
    fn = names(full)
    cmd = {x.split(' :: ', 1)[0]: x.split(' :: ', 1)[1] for x in full}
    ok('комнаты: каждый шаг ночи один раз', all(fn.count(n) == 1 for n in fn), [n for n in fn if fn.count(n) > 1])
    ok('комнаты: каталоги — сразу за load3 (голова ночи), живость/стиль/вырезка — сразу за такими же шагами гостиной',
       all(n in fn and fn[fn.index(n) + 1:fn.index(n) + 1 + len(v)] == v for n, v in ROOM_AFTER.items()),
       {n: fn[fn.index(n):fn.index(n) + 1 + len(v)] for n, v in ROOM_AFTER.items() if n in fn})
    ok('комнаты: каталог раньше всех шагов комнат, все шаги комнат — до demo_band и витрины',
       max(fn.index(n) for n in ROOM_STEPS) < fn.index('demo_band') < fn.index('flat215_demo')
       and all(fn.index('room_catalog') < fn.index(n) for n in ROOM_STEPS))
    ok('комнаты: команды — каталоги --run; фото --rooms; стиль с --limit 200, прихожая в базу; вырезка --rooms-only, по умолчанию 0',
       cmd.get('room_catalog') == '$PY room_catalog.py --run' and cmd.get('hall_catalog') == '$PY hall_catalog.py --run'
       and cmd.get('rooms_alive', '').startswith('$PY img_alive.py --rooms --minutes ')
       and cmd.get('style_bedroom') == '$PY style_score.py --source room_catalog --limit 200'
       and cmd.get('style_hall') == '$PY style_score.py --source hall --db --limit 200'
       and cmd.get('rooms_cutout') == 'env PHOTO_ROOMS_LIMIT=500 CUTOUT_ROOMS_MAX=0 $PY cutout_sync.py --rooms-only',
       {k: cmd.get(k) for k in ROOM_STEPS})
    ok('комнаты: строка дайджеста на каждую комнату',
       'DIGEST:спальня: каталог ok · фото ok · стиль ok · вырезка ok' in log
       and 'DIGEST:прихожая: каталог ok · фото ok · стиль ok · вырезка ok' in log, log[-400:])
    for failed in ('room_catalog', *ROOM_STEPS):
        got, flog = night_log(text, 0, fail=failed, start=HEAD)
        room = 'прихожая' if failed in ('hall_catalog', 'style_hall') else 'спальня'
        ok(f'комнаты: упал {failed} — остальная ночь та же (сборка витрины и всё после идут), в дайджесте {room} с FAIL',
           names(got) == fn and any(ln.startswith(f'DIGEST:{room}: ') and 'FAIL' in ln for ln in flog.splitlines()),
           (names(got)[-5:], flog[-300:]))
    ok('флаг не прочитан (заглушка молчит) — ночь как при false', names(night(text, 0)) == names(night(text.replace(
        'BANK_WRITE=$("$PY" bank_refresh.py --enabled 2>/dev/null || echo 0)', 'BANK_WRITE=""'), 1)))
    print(f'tests_refresh_order selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--against' in sys.argv:
        sys.exit(against(sys.argv[sys.argv.index('--against') + 1]))
    sys.exit(_selftest())
