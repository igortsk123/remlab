#!/usr/bin/env python3
"""РАЗОВОЕ РАЗРЕШЕНИЕ НА ОБХОД КОНВЕЙЕРА (T-20261112-121 шаг 4; план conveyor-guards-01; инцидент 12.11 — спальня продвинута
`--force` при promote_enabled=false). Обходы перечислены в реестре `tools/ops/conveyor-manifest.yml` § force_guard; хук
`tools/hooks/guard_conveyor.py` пускает такой запуск агента, только если есть разрешение на ЭТОТ инструмент и флаги.

Разрешение выпускает директор ТОЛЬКО по слову владельца в Telegram — номер сообщения обязателен:
    python3 tools/ops/conveyor_permit.py issue --tid T-20261113-05 --tg 1402 --target "bank_promote.py --force" \\
        [--match "--room bedroom"] [--hours 2]
    python3 tools/ops/conveyor_permit.py list          # действующие + хвост журнала
    python3 tools/ops/conveyor_permit.py revoke <id>
    python3 tools/ops/conveyor_permit.py --selftest
Одно разрешение = один запуск: хук тратит его в момент вызова (команда упала — нужно новое). Срок — не больше 24 ч.
`--match` — ещё одна строка, которая обязана быть в команде (комната, стиль): разрешение не уйдёт на соседний запуск.

Хранилище — вне git, на машине запуска: `~/.local/state/remlab/conveyor-permits.json` (действующие) и журнал
`conveyor-permits.log` (JSON-строки, только дописываем: issue / use / revoke / deny). Руками их не правят — хук отказывает
в записи в эти файлы (как в собранные). Подписи нет (владелец код не пишет): защита — номер TG в записи и журнал."""
import datetime as dt
import json
import os
import re
import secrets
import shlex
import socket
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.environ.get('CONVEYOR_PERMIT_DIR') or os.path.expanduser('~/.local/state/remlab')
MAX_HOURS = 24
TID = re.compile(r'^T-\d{8}-\d{2,3}(/\d+)?$')


def paths(state=None):
    d = state or STATE
    return os.path.join(d, 'conveyor-permits.json'), os.path.join(d, 'conveyor-permits.log')


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _load(state=None):
    p, _ = paths(state)
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _save(items, state=None):
    p, _ = paths(state)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def journal(event, rec, state=None, **extra):
    _, log = paths(state)
    os.makedirs(os.path.dirname(log), exist_ok=True)
    row = dict(ts=_now().isoformat(timespec='seconds'), event=event, host=socket.gethostname(), **rec, **extra)
    with open(log, 'a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def _guards(root=None):
    import yaml
    with open(os.path.join(root or os.path.join(HERE, '..', '..'), 'tools', 'ops', 'conveyor-manifest.yml'), encoding='utf-8') as f:
        return (yaml.safe_load(f) or {}).get('force_guard') or []


def parse_target(target, guards):
    """«bank_promote.py --force --no-exam» → ('bank_promote.py', {'--force', '--no-exam'}); флаги — только из реестра."""
    parts = target.split()
    if not parts:
        raise ValueError('пустая цель')
    tool = os.path.basename(parts[0])
    g = next((g for g in guards if os.path.basename(g.get('path', '')) == tool), None)
    if not g:
        raise ValueError(f'{tool} нет в force_guard реестра — разрешение на него не нужно или реестр устарел')
    flags = set(parts[1:])
    bad = flags - set(g.get('flags') or [])
    if not flags or bad:
        raise ValueError(f'флаги {sorted(bad) or "(нет)"} не из force_guard для {tool}: {g.get("flags")}')
    return tool, flags


def issue(tid, tg, target, hours=2.0, match='', state=None, guards=None):
    if not TID.match(tid or ''):
        raise ValueError('T-ID вида T-20261113-05')
    if not str(tg).isdigit():
        raise ValueError('номер сообщения владельца в Telegram — число (слово владельца обязательно)')
    if not 0 < float(hours) <= MAX_HOURS:
        raise ValueError(f'срок 0–{MAX_HOURS} ч')
    tool, flags = parse_target(target, guards if guards is not None else _guards())
    rec = dict(id=secrets.token_hex(3), tid=tid, tg=int(tg), tool=tool, flags=sorted(flags), match=match,
               issued=_now().isoformat(timespec='seconds'),
               expires=(_now() + dt.timedelta(hours=float(hours))).isoformat(timespec='seconds'),
               by=os.environ.get('USER', '?'))
    items = [x for x in _load(state) if _alive(x)] + [rec]
    _save(items, state)
    journal('issue', rec, state)
    return rec


def _alive(x):
    try:
        return dt.datetime.fromisoformat(x['expires']) > _now()
    except (KeyError, ValueError):
        return False


def take(tool, flags, cmd, state=None, dry=False):
    """Потратить разрешение на запуск `tool` с `flags` (команда целиком — для --match и журнала). Нашли — запись, иначе None.
    dry — только проверить (без траты и без журнала): хук сперва проверяет все инструменты команды, потом тратит."""
    items = _load(state)
    for x in items:
        if _alive(x) and x.get('tool') == tool and set(flags) <= set(x.get('flags') or []) \
                and (not x.get('match') or x['match'] in cmd):
            if not dry:
                _save([y for y in items if y is not x and _alive(y)], state)
                journal('use', x, state, cmd=cmd[:500])
            return x
    if not dry:
        journal('deny', dict(tool=tool, flags=sorted(flags)), state, cmd=cmd[:500])
    return None


def revoke(pid, state=None):
    items = _load(state)
    hit = [x for x in items if x.get('id') == pid]
    _save([x for x in items if x.get('id') != pid], state)
    for x in hit:
        journal('revoke', x, state)
    return bool(hit)


def _arg(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else default


def _selftest():
    import tempfile
    bad = 0

    def ok(cond, name, info=''):
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name + ('' if cond else f' — {info}'))
        bad += 0 if cond else 1

    G = [{'path': 'tools/scout/bank_promote.py', 'flags': ['--force', '--force-ready', '--no-exam'], 'why': 'x'}]
    with tempfile.TemporaryDirectory() as d:
        for kw, why in ((dict(tid='T-1', tg=5, target='bank_promote.py --force'), 'T-ID'),
                        (dict(tid='T-20261113-05', tg='', target='bank_promote.py --force'), 'без номера TG'),
                        (dict(tid='T-20261113-05', tg=5, target='bank_promote.py --force', hours=48), 'срок > 24 ч'),
                        (dict(tid='T-20261113-05', tg=5, target='bank_promote.py --dry'), 'флаг не из реестра'),
                        (dict(tid='T-20261113-05', tg=5, target='other.py --force'), 'инструмент не из реестра')):
            try:
                issue(state=d, guards=G, **kw)
                ok(False, f'отказ выпуска: {why}')
            except ValueError:
                ok(True, f'отказ выпуска: {why}')
        r = issue('T-20261113-05', 1402, 'bank_promote.py --force --no-exam', hours=1, match='--room bedroom', state=d, guards=G)
        ok(r['tg'] == 1402 and r['flags'] == ['--force', '--no-exam'], 'выпуск: номер TG, флаги', r)
        ok(take('bank_promote.py', {'--force'}, 'python3 bank_promote.py --force --room hall', state=d) is None,
           '--match: другая комната — не тратится')
        ok(take('bank_promote.py', {'--force-ready'}, 'python3 bank_promote.py --force-ready 1 --room bedroom', state=d) is None,
           'флаг вне разрешения — не тратится')
        ok(take('bank_promote.py', {'--force'}, 'python3 bank_promote.py --force --room bedroom', state=d, dry=True) is not None
           and take('bank_promote.py', {'--force'}, 'python3 bank_promote.py --force --room bedroom', state=d, dry=True) is not None,
           'проверка (dry) — не тратит')
        ok(take('bank_promote.py', {'--force', '--no-exam'}, 'python3 bank_promote.py --force --no-exam --room bedroom', state=d) is not None,
           'совпало — тратится')
        ok(take('bank_promote.py', {'--force'}, 'python3 bank_promote.py --force --room bedroom', state=d) is None, 'второй раз — нет (разовое)')
        r2 = issue('T-20261113-05', 1402, 'bank_promote.py --force', hours=1, state=d, guards=G)
        ok(revoke(r2['id'], state=d) and take('bank_promote.py', {'--force'}, 'x', state=d) is None, 'отозванное — не тратится')
        items = _load(d) + [dict(id='old', tool='bank_promote.py', flags=['--force'], expires='2000-01-01T00:00:00+00:00')]
        _save(items, d)
        ok(take('bank_promote.py', {'--force'}, 'x', state=d) is None, 'просроченное — не тратится')
        ev = [json.loads(x)['event'] for x in open(paths(d)[1], encoding='utf-8')]
        ok(ev.count('issue') == 2 and ev.count('use') == 1 and ev.count('revoke') == 1 and ev.count('deny') >= 4,
           'журнал: выпуск, трата, отзыв, отказы', ev)
    print(f'conveyor_permit selftest: ошибок {bad}')
    return 1 if bad else 0


def main(argv):
    if '--selftest' in argv:
        return _selftest()
    cmd = argv[0] if argv else 'list'
    if cmd == 'issue':
        try:
            r = issue(_arg(argv, '--tid'), _arg(argv, '--tg', ''), _arg(argv, '--target', ''), float(_arg(argv, '--hours', 2)),
                      _arg(argv, '--match', ''))
        except ValueError as e:
            print(f'НЕ ВЫПУЩЕНО: {e}', file=sys.stderr)
            return 2
        print(f"разрешение {r['id']}: {r['tool']} {' '.join(r['flags'])}" + (f" (+ «{r['match']}»)" if r['match'] else '') +
              f" — один запуск до {r['expires']}; {r['tid']}, TG {r['tg']}")
        return 0
    if cmd == 'revoke' and len(argv) > 1:
        return 0 if revoke(argv[1]) else 1
    if cmd == 'list':
        for x in _load():
            if _alive(x):
                print(f"{x['id']}  {x['tool']} {' '.join(x['flags'])}  {x.get('match', '')}  до {x['expires']}  {x['tid']} TG {x['tg']}")
        _, log = paths()
        if os.path.exists(log):
            print('журнал (хвост):')
            for ln in open(log, encoding='utf-8').read().splitlines()[-10:]:
                print('  ' + ln)
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
