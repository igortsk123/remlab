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
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__))))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_refresh_order')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, 'refresh_daily.sh')
START = 'step sets_index '
HEAD = 'step load3 '        # вся ночь от загрузки фидов: каталоги комнат стоят в голове (T-20261106-84)

PRELUDE = r'''set -u
cd "$TD"
LOG="$TD/log"; STAMP="$TD/stamp"; today=x; PY="$TD/py"
declare -A RES; RES[candidates]=ok; RES[sets_index]=ok
step() { local n="$1"; shift; local c="$*"; local id="${BANK_RUN_ID:-}"; c="${c//$PY/\$PY}"; [ -n "$id" ] && c="${c//$id/\$BANK_RUN_ID}"
  echo "$n :: $c" >> "$TD/steps"; if [ "$n" = "${FAIL_STEP:-}" ]; then RES[$n]=FAIL; return 1; fi
  if [ "$n" = "${WARN_STEP:-}" ]; then RES[$n]=warn; return 0; fi; RES[$n]=ok; return 0; }
paid_step() { step "$@"; }
date() { case "${1:-}" in +%u) echo "$WEEKDAY" ;; +%s) echo 0 ;; *) command date "$@" ;; esac; }   # +%s — метка в адресе, шаги сравнимы
'''
# заглушка $PY: флаг писателя гостиной; флаги банков комнат (`room_bank_spec.py --room X --flag F` → 1, если «X:F» в ROOMFLAGS_STUB)
# и значение ROOM_PUBLISH (`room_bank_spec.py --publish`) — T-20261106-89
PY_STUB = ('#!/bin/bash\n'
           'if [ "${1:-}" = bank_refresh.py ] && [ "${2:-}" = --enabled ]; then echo "$BANK_WRITE_STUB"; fi\n'
           'if [ "${1:-}" = room_bank_spec.py ] && [ "${4:-}" = --flag ]; then\n'
           '  case " ${ROOMFLAGS_STUB:-} " in *" $3:$5 "*) echo 1 ;; *) echo 0 ;; esac; fi\n'
           'if [ "${1:-}" = room_bank_spec.py ] && [ "${2:-}" = --publish ]; then echo "${ROOM_PUBLISH_STUB:-}"; fi\n'
           'exit 0\n')


def tail(text: str, start: str = START) -> str:
    i = text.index('\n' + start) + 1
    return text[i:]


def night(text: str, write: int, weekday: int = 3, lock: bool = False, fail: str = '', start: str = START) -> list[str]:
    """Шаги хвоста ночи (или всей ночи от `start`) по порядку: «имя :: команда»."""
    return night_log(text, write, weekday, lock, fail, start)[0]


def night_log(text: str, write: int, weekday: int = 3, lock: bool = False, fail: str = '',
              start: str = START, flags: str = '', publish: str = '', warn: str = '') -> tuple[list[str], str]:
    """(шаги, лог ночи): `fail` — шаг, который заглушка роняет (код 1); `warn` — шаг с WARN (код 0, статус warn);
    `start` — с какого шага (HEAD — вся ночь)."""
    with tempfile.TemporaryDirectory(prefix='night-order-') as td:
        open(os.path.join(td, 'py'), 'w').write(PY_STUB)
        os.chmod(os.path.join(td, 'py'), 0o755)
        if lock:
            open(os.path.join(td, 'exam.lock'), 'w').close()
        sh = os.path.join(td, 'run.sh')
        open(sh, 'w', encoding='utf-8').write(PRELUDE + tail(text, start))
        p = subprocess.run(['bash', sh], env={**os.environ, 'TD': td, 'WEEKDAY': str(weekday), 'BANK_WRITE_STUB': str(write),
                                              'FAIL_STEP': fail, 'WARN_STEP': warn, 'ROOMFLAGS_STUB': flags, 'ROOM_PUBLISH_STUB': publish},
                           capture_output=True, text=True, timeout=60)
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
# БАНКИ КОМНАТ НОЧЬЮ (room-bank-nightly-04 = К4, T-20261106-89; порядок — room-bank-01 этап Д, T-20261107-04): привязка → сборщик →
# сухой суд → цепочка банка комнаты (prepare → меши кандидата → привязка → pending [за prepare_enabled] → promote [promote_enabled]
# → refresh [write_enabled]) → проверка состояния (всегда) — после писателя гостиной, до demo_band
ROOMS = ('bedroom', 'hall')
CHAIN = ('bank_prepare', 'mesh_cand', 'room_bindings', 'bank_pending', 'bank_promote', 'bank_refresh')
# сторож цвета мешей (T-20261107-14/2) — сразу перед первой привязкой комнат: его таблицу читает room_bindings --build
ROOM_BANK = ('mesh_color_guard', 'room_bindings', *(f'{s}_{r}' for r in ROOMS for s in ('compose', 'room_check', *CHAIN,
                                                                                         'bank_rehearse', 'bank_state')))
DEMO = ('flat215_demo', 'demo_rt', 'flat215_publish')


def chain_of(room: str) -> list[str]:
    return [f'{s}_{room}' for s in CHAIN]
ROOM_ALL = ('room_catalog', *ROOM_STEPS, *ROOM_BANK)
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
        tl = [n for n in tn if n not in ROOM_BANK]          # шаги комнат (проверка состояния идёт всегда) — отдельно, ниже
        k = tl.index('bank_promote') + 1
        ok(f'[{tag}] true: писатель сразу за bank_promote, за ним индекс, set_id, пересчёт сцен, страницы, затем (после комнат) demo_band',
           tl[k:k + len(IDX) + 2] == ['bank_refresh', *IDX, 'demo_band'] and tn.index('layout_page') < tn.index('bank_state_bedroom'),
           tl[k:k + len(IDX) + 2])
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
    ok('комнаты: команды — каталоги --run; фото --rooms; стиль с --limit 200, прихожая в базу; вырезка --rooms-only, по умолчанию 300 за ночь',
       cmd.get('room_catalog') == '$PY room_catalog.py --run' and cmd.get('hall_catalog') == '$PY hall_catalog.py --run'
       and cmd.get('rooms_alive', '').startswith('$PY img_alive.py --rooms --minutes ')
       and cmd.get('style_bedroom') == '$PY style_score.py --source room_catalog --limit 200'
       and cmd.get('style_hall') == '$PY style_score.py --source hall --db --limit 200'
       and cmd.get('rooms_cutout') == 'env PHOTO_ROOMS_LIMIT=500 CUTOUT_ROOMS_MAX=300 $PY cutout_sync.py --rooms-only',
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
    _rooms_bank(text, ok)          # ошибки считает сам `ok` (nonlocal bad) — не `bad += …`: та сумма затёрла бы их
    ok('флаг не прочитан (заглушка молчит) — ночь как при false', names(night(text, 0)) == names(night(text.replace(
        'BANK_WRITE=$("$PY" bank_refresh.py --enabled 2>/dev/null || echo 0)', 'BANK_WRITE=""'), 1)))
    print(f'tests_refresh_order selftest: ошибок {bad}')
    return 1 if bad else 0


def _rooms_bank(text: str, ok) -> int:
    """Банки комнат ночью (T-20261106-89; порядок, флаги и сбои — room-bank-01 этап Д, T-20261107-04): флаги, порядок, команды,
    сбой на каждом шаге комнаты, «состояние не определено → демо не публикуется», ROOM_PUBLISH. Ошибки считает `ok` вызывающего."""
    def run(write=0, flags='', fail='', warn=''):
        full, log = night_log(text, write, start=HEAD, flags=flags, fail=fail, warn=warn)
        import collections                  # нет шага — пустая команда (проверка «✗», а не KeyError)
        return names(full), collections.defaultdict(str, (x.split(' :: ', 1) for x in full)), log

    def dig(log, room):
        return next((ln for ln in log.splitlines() if ln.startswith(f'DIGEST:{room} (банк): ')), '')
    base, cmd, log = run()
    living = names(night(text, 0, start=HEAD))
    ok('банки комнат: флаги выключены — из шагов комнат только проверка состояния (спальня, прихожая; витрина читает живой банк '
       'и при выключенных флагах), сразу за банком гостиной и до demo_band; остальная ночь та же',
       [n for n in base if n in ROOM_BANK] == ['bank_state_bedroom', 'bank_state_hall']
       and base.index('bank_promote') < base.index('bank_state_bedroom') < base.index('bank_state_hall') < base.index('demo_band')
       and [n for n in base if n not in ROOM_BANK] == [n for n in living if n not in ROOM_BANK],
       [n for n in base if n in ROOM_BANK])
    ok('банки комнат: проверка состояния — `bank_refresh.py --room X state` (только чтение)',
       cmd.get('bank_state_bedroom') == '$PY bank_refresh.py --room bedroom state'
       and cmd.get('bank_state_hall') == '$PY bank_refresh.py --room hall state', cmd.get('bank_state_bedroom'))
    ok('банки комнат: выключено — строка дайджеста «сборка выключено … состояние ok»',
       'сборка выключено' in dig(log, 'спальня') and 'состояние ok' in dig(log, 'спальня'), dig(log, 'спальня'))
    on = 'bedroom:enabled hall:enabled'
    for write in (0, 1):
        fn, cmd, log = run(write, on)
        want = ['room_bindings', 'compose_bedroom', 'room_check_bedroom', 'bank_state_bedroom', 'compose_hall', 'room_check_hall',
                'bank_state_hall']
        last_living = 'bank_refresh' if write else 'bank_promote'
        i = fn.index('room_bindings')
        ok(f'[write={write}] банки комнат: привязка → сборка → суд → состояние спальни → то же прихожей подряд, сразу после банка '
           f'гостиной ({last_living}{" + индекс" if write else ""}) и до demo_band; цепочки комнат нет (prepare выключен)',
           fn[i:i + len(want)] == want and fn[i + len(want)] == 'demo_band' and fn.index(last_living) < i
           and not any(n in fn for r in ROOMS for n in chain_of(r)), fn[i - 2:i + 8])
        ok(f'[write={write}] банки комнат: остальная ночь — та же и тем же порядком',
           [n for n in fn if n not in ROOM_BANK] == [n for n in names(night(text, write, start=HEAD)) if n not in ROOM_BANK])
        ok(f'[write={write}] банки комнат: команды — привязка --build, сборщики без --nightly (флаг показа не решает), суд --night',
           cmd['room_bindings'] == '$PY room_bindings.py --build' and cmd['compose_bedroom'] == '$PY compose_bedroom.py'
           and cmd['compose_hall'] == '$PY compose_hall.py'
           and cmd['room_check_hall'] == '$PY room_bootstrap.py --room hall check --night', cmd.get('room_check_hall'))
    blk = text[text.index('# БАНКИ КОМНАТ НОЧЬЮ'):text.index('step demo_band ')]
    ok('банки комнат: флаги банка — только `room_bank_spec.py --flag` (rules/bank-candidate.json:rooms.*), флаг показа витрины '
       '(apartments[].rooms[].enabled, `--nightly`, room_flags) блок не читает',
       'room_bank_spec.py --room "$1" --flag' in blk and not any(w in blk.split('room_flag()', 1)[1]
                                                                  for w in ('--nightly', 'room_flags', 'apartments')))
    fn, _, _ = run(0, 'hall:enabled')
    ok('банки комнат: включена только прихожая — сборки спальни нет, привязка одна, состояние — у обеих',
       'compose_bedroom' not in fn and fn.count('room_bindings') == 1 and 'room_check_hall' in fn
       and 'bank_state_bedroom' in fn and 'bank_state_hall' in fn, fn)
    # полная цепочка спальни: все флаги банка спальни включены (prepare, promote, write); у прихожей — только сборка
    full = 'bedroom:enabled hall:enabled bedroom:prepare_enabled bedroom:promote_enabled bedroom:write_enabled'
    fn, cmd, log = run(0, full)
    bch = chain_of('bedroom')
    j = fn.index('room_check_bedroom') + 1
    ok('банки комнат: полная цепочка спальни — prepare → меши кандидата → привязка → pending → promote → refresh → проверка '
       'состояния, сразу за судом; у прихожей цепочки нет',
       fn[j:j + len(bch) + 2] == [*bch, 'bank_state_bedroom', 'compose_hall']
       and not any(n in fn for n in chain_of('hall')), fn[j - 1:j + 9])
    ok('банки комнат: номер ночи спальни свой ($BANK_RUN_ID-bedroom) у prepare/pending/promote/refresh; меши кандидата — '
       '`ROOM_PUBLISH=bedroom=next mesh_publish --rooms-only`; вторая привязка — --build',
       all(cmd[f'{s}_bedroom'].endswith('--room bedroom --run-id $BANK_RUN_ID-bedroom') for s in ('bank_prepare', 'bank_promote',
                                                                                                   'bank_refresh'))
       and cmd['bank_pending_bedroom'] == '$PY bank_pending.py --room bedroom --night --run-id $BANK_RUN_ID-bedroom'
       and cmd['mesh_cand_bedroom'] == 'env ROOM_PUBLISH=bedroom=next $PY mesh_publish.py --rooms-only'
       and cmd['room_bindings_bedroom'] == '$PY room_bindings.py --build', [cmd.get(n) for n in bch])
    ok('банки комнат: порядок ночи плана — room_catalog → привязка → подготовка спальни → … → состояние → demo_band → публикация '
       'мешей → витрина → публикация витрины; цепочка ok в дайджесте',
       fn.index('room_catalog') < fn.index('room_bindings') < fn.index('compose_bedroom') < fn.index('bank_prepare_bedroom')
       < fn.index('bank_refresh_bedroom') < fn.index('bank_state_bedroom') < fn.index('demo_band') < fn.index('mesh_publish')
       < fn.index('flat215_demo') < fn.index('flat215_publish') and 'цепочка ok' in dig(log, 'спальня'), dig(log, 'спальня'))
    ok('банки комнат: при полной цепочке остальная ночь — та же и тем же порядком',
       [n for n in fn if n not in ROOM_BANK] == [n for n in living if n not in ROOM_BANK])
    # флаги по одному: prepare без promote — до pending; promote без write — до promote; write без promote — refresh не идёт
    for flags, stop, why in (('bedroom:enabled bedroom:prepare_enabled', 'bank_pending_bedroom', 'promote выключен'),
                             ('bedroom:enabled bedroom:prepare_enabled bedroom:promote_enabled', 'bank_promote_bedroom',
                              'write выключен'),
                             ('bedroom:enabled bedroom:prepare_enabled bedroom:write_enabled', 'bank_pending_bedroom',
                              'promote выключен — писать нечего')):
        fn, _, log = run(0, flags)
        k = bch.index(stop) + 1
        ok(f'банки комнат: {flags.replace("bedroom:", "")} — цепочка до {stop} ({why}), дальше её шагов нет, состояние проверено, '
           'цепочка ok', all(n in fn for n in bch[:k]) and not any(n in fn for n in bch[k:]) and 'bank_state_bedroom' in fn
           and 'цепочка ok' in dig(log, 'спальня'), (fn, dig(log, 'спальня')))
    ok('банки комнат: write_enabled без prepare_enabled — цепочки нет вовсе (флаг записи один ничего не запускает)',
       not any(n in run(0, 'bedroom:enabled bedroom:write_enabled')[0] for n in bch))
    # ВНЕДРЕНИЕ СБОЯ НА КАЖДОМ ШАГЕ КОМНАТЫ: дальше по спальне не идёт, проверка состояния и прихожая — идут, витрина и
    # публикация — идут (живой банк спальни — последний годный), в дайджесте спальни FAIL / «суд не прошёл»
    fn, _, _ = run(0, full)
    steps = ['room_bindings', 'compose_bedroom', 'room_check_bedroom', *bch]
    for failed in steps:
        if failed == 'room_bindings':
            gone = []
        elif failed == 'compose_bedroom':
            gone = ['room_check_bedroom', *bch]
        elif failed == 'room_check_bedroom':
            gone = bch
        else:
            gone = bch[bch.index(failed) + 1:]
        gn, _, flog = run(0, full, fail=failed)
        d = dig(flog, 'спальня')
        ok(f'сбой {failed}: дальше по спальне не идёт ({", ".join(gone) or "—"}); состояние, прихожая, витрина и публикация — '
           f'идут, остальная ночь та же; дайджест спальни с FAIL',
           gn == [n for n in fn if n not in gone] and all(n in gn for n in ('bank_state_bedroom', 'compose_hall', *DEMO))
           and 'FAIL' in d and (failed != 'room_check_bedroom' or 'цепочка суд не прошёл' in d), (gn[-10:], d))
    for warned in ('compose_bedroom', 'room_check_bedroom', 'mesh_cand_bedroom'):
        gn, _, wlog = run(0, full, warn=warned)
        ok(f'WARN на {warned} (сборка: стиль пропущен по правилу ядра; суд: «не годен»; меши: прод не ответил) — цепочка идёт до '
           'конца, ночь та же', gn == fn and 'цепочка ok' in dig(wlog, 'спальня'), (gn[-10:], dig(wlog, 'спальня')))
    # НЕОПРЕДЕЛЁННОЕ СОСТОЯНИЕ → ДЕМО НЕ ПУБЛИКОВАТЬ (и не собирать: на проде остаётся вчерашнее)
    for flags, room in ((full, 'bedroom'), ('', 'bedroom'), (on, 'hall')):
        ref, _, _ = run(0, flags)
        gn, _, ulog = run(0, flags, fail=f'bank_state_{room}')
        ok(f'состояние {room} не определено ({"флаги выключены" if not flags else "флаги включены"}) — витрина не собирается и не '
           'публикуется, платной досъёмки нет (идёт сухая проверка), строка в дайджест; остальная ночь та же',
           not any(n in gn for n in DEMO) and 'demo_real' not in gn and 'demo_real_check' in gn
           and gn == [n for n in ref if n not in (*DEMO, 'demo_real')]
           and 'DIGEST:!демо не собрано и не опубликовано: состояние банка комнат не определено' in ulog
           and 'состояние FAIL' in dig(ulog, 'спальня' if room == 'bedroom' else 'прихожая'), (gn[-12:], ulog[-400:]))
    fn, cmd, _ = run(0, full)
    # ФОТО ДО ПУБЛИКАЦИИ (photo-before-publish-01, T-20261107-34): сборка → ворота → платная досъёмка на ЛОКАЛЬНОЙ сборке → публикация
    # (с отметкой «фото сняты», обёртка не повторяет) → прогрев кадров → бесплатная проверка по опубликованному — каждую ночь
    ok('состояние определено — сборка → ворота → досъёмка фото на новой сборке (DEMO_LOCAL) → публикация (PUB_PHOTOS_DONE=1) → '
       'прогрев → сухая проверка по опубликованному',
       fn.index('flat215_demo') < fn.index('demo_rt') < fn.index('demo_real') < fn.index('flat215_publish') < fn.index('demo_warm')
       < fn.index('demo_real_check') and fn.count('demo_real_check') == 1
       and cmd['demo_real'].startswith('env DEMO_LOCAL=') and cmd['demo_real'].endswith('/scout-scenes/flat215-demo bash ../ops/demo-real.sh')
       and cmd['flat215_publish'] == 'env PUB_PHOTOS_DONE=1 bash publish_demo.sh'
       and cmd['demo_real_check'] == 'bash ../ops/demo-real.sh --dry', {n: cmd.get(n) for n in ('demo_real', 'flat215_publish', 'demo_real_check')})
    gn, _, glog = run(0, full, fail='demo_rt')
    ok('ворота demo_rt не прошли — ни досъёмки, ни публикации; сухая проверка идёт; строка «фото: пропущено» в дайджест',
       'demo_real' not in gn and 'flat215_publish' not in gn and 'demo_real_check' in gn
       and 'DIGEST:фото нейросети: пропущено — демо не опубликовано (ворота demo_rt)' in glog, (gn[-8:], glog[-300:]))
    for bad in ('demo_real', 'flat215_publish'):
        gn, _, _ = run(0, full, fail=bad)
        ok(f'сбой {bad} — ночь та же: публикация не зависит от фото (TG 378), проверка по опубликованному идёт', gn == fn, gn[-8:])
    # ТЕНЬ (этап Е): репетиция записи в копию — за rehearse_enabled, после цепочки (или суда), до проверки состояния; сбой — WARN
    # в смысле ночи: остальное идёт, витрина и публикация — идут
    reh = 'bedroom:rehearse_enabled'
    for flags, after in ((f'{full} {reh}', 'bank_refresh_bedroom'), (f'{on} {reh}', 'room_check_bedroom')):
        fn, cmd, log = run(0, flags)
        ref, _, _ = run(0, flags.replace(f' {reh}', ''))
        ok(f'репетиция ({"полная цепочка" if after.startswith("bank_refresh") else "prepare выключен"}): сразу за {after}, до проверки '
           'состояния; команда `bank_rehearsal.py --room bedroom`; у прихожей нет; остальная ночь та же; в дайджесте «репетиция ok»',
           fn.index(after) + 1 == fn.index('bank_rehearse_bedroom') == fn.index('bank_state_bedroom') - 1
           and cmd['bank_rehearse_bedroom'] == '$PY bank_rehearsal.py --room bedroom' and 'bank_rehearse_hall' not in fn
           and [n for n in fn if n != 'bank_rehearse_bedroom'] == ref and 'репетиция ok' in dig(log, 'спальня'),
           (fn[fn.index(after) - 1:fn.index(after) + 4], dig(log, 'спальня')))
    fn, _, log = run(0, full)
    ok('репетиция: флаг выключен — шага нет, в дайджесте «репетиция выключено»',
       'bank_rehearse_bedroom' not in fn and 'репетиция выключено' in dig(log, 'спальня'), dig(log, 'спальня'))
    fr = f'{full} {reh}'
    fn, _, _ = run(0, fr)
    for failed in ('bank_rehearse_bedroom', 'bank_pending_bedroom', 'room_check_bedroom'):
        gn, _, flog = run(0, fr, fail=failed)
        gone = [] if failed == 'bank_rehearse_bedroom' else bch[bch.index(failed) + 1:] if failed in bch else bch
        ok(f'репетиция: сбой {failed} — {"ночь та же" if not gone else "цепочка встала, репетиция всё равно идёт (кандидат есть)"}; '
           'состояние, прихожая, витрина, публикация — идут',
           gn == [n for n in fn if n not in gone] and 'bank_rehearse_bedroom' in gn
           and all(n in gn for n in ('bank_state_bedroom', 'compose_hall', *DEMO, 'demo_real')), (gn[-12:], dig(flog, 'спальня')))
    gn, _, flog = run(0, fr, fail='compose_bedroom')
    ok('репетиция: сборка упала (кандидата нет) — репетиции нет, в дайджесте «репетиция нет кандидата»; витрина идёт',
       'bank_rehearse_bedroom' not in gn and 'репетиция нет кандидата' in dig(flog, 'спальня') and all(n in gn for n in DEMO),
       dig(flog, 'спальня'))
    gn, _, wlog = run(0, fr, warn='compose_bedroom')
    ok('репетиция: сборка с WARN — репетиция идёт', 'bank_rehearse_bedroom' in gn, gn[-12:])
    gn, _, wlog = run(0, fr, warn='bank_rehearse_bedroom')
    ok('репетиция: WARN репетиции — ночь та же, «репетиция warn» в дайджесте',
       gn == fn and 'репетиция warn' in dig(wlog, 'спальня'), dig(wlog, 'спальня'))
    full, _ = night_log(text, 0, start=HEAD, publish='bedroom,hall=next')
    cmd = {x.split(' :: ', 1)[0]: x.split(' :: ', 1)[1] for x in full}
    plain = {x.split(' :: ', 1)[0]: x.split(' :: ', 1)[1] for x in night(text, 0, start=HEAD)}
    ok('публикация комнат: rooms.*.publish → mesh_publish с ROOM_PUBLISH; пусто — команда прежняя',
       cmd['mesh_publish'] == 'env ROOM_PUBLISH=bedroom,hall=next $PY mesh_publish.py'
       and plain['mesh_publish'] == '$PY mesh_publish.py', (cmd['mesh_publish'], plain['mesh_publish']))
    return 0


if __name__ == '__main__':
    if '--against' in sys.argv:
        sys.exit(against(sys.argv[sys.argv.index('--against') + 1]))
    sys.exit(_selftest())
