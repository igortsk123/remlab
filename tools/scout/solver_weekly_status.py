#!/usr/bin/env python3
"""Итог недельной проверки расстановки `solver_full` для сводки дня (T-20261112-56/3, план refresh-split-01, вариант А).

`solver_full` больше не шаг дневной сборки: его запускает `solver_weekly.sh` ночью в понедельник и пишет статус
`~/.cache/remlab-refresh/solver-weekly-status.json`. Шаг `solver_weekly_last` дневной сборки (понедельник) зовёт этот файл с `--digest`:
  • строка `DIGEST:…` — итог последней проверки (когда, сколько минут, сколько сетов влезает) — идёт в сводку дня как раньше шаг `solver_full`;
  • строка `WARN:solver_weekly: …` — проверки не было больше недели / упала / пропущена / не закончилась: шаг warn, сводка покажет.
    Сама проверка при падении или пропуске ещё и шлёт тревогу владельцу (`solver_weekly.sh`), так что сводка — вторая линия.

  ~/venvs/scout/bin/python solver_weekly_status.py --digest [--status файл] [--max-age-days 8]
  python3 solver_weekly_status.py --selftest
"""
import datetime
import json
import os
import sys

DEFAULT = os.path.expanduser('~/.cache/remlab-refresh/solver-weekly-status.json')


def _parse_utc(s: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return None


def digest(path: str, now: datetime.datetime | None = None, max_age_days: float = 8) -> list[str]:
    """Строки для вывода шага: `DIGEST:…` и/или `WARN:solver_weekly: …`. Статуса нет или он битый — предупреждение."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        s = json.load(open(path, encoding='utf-8'))
    except FileNotFoundError:
        return ['WARN:solver_weekly: недельной проверки расстановки (solver_full) ещё не было — нет статуса solver-weekly-status.json; '
                'проверьте строку крона `30 5 * * 1 …/solver_weekly.sh`']
    except (OSError, ValueError):
        return ['WARN:solver_weekly: статус недельной проверки расстановки не читается (битый файл)']
    state = s.get('state', '?')
    started = _parse_utc(s.get('started_at', ''))
    fin = _parse_utc(s.get('finished_at', ''))
    when = (s.get('finished') or s.get('started') or '?')[:16]
    mins = round(float(s.get('sec') or 0) / 60)
    if state == 'running':
        if started and (now - started).total_seconds() > 6 * 3600:
            return [f'WARN:solver_weekly: недельная проверка расстановки начата {when} и не закончилась (упала посреди? смотри solver-weekly.log)']
        return [f'DIGEST:недельная проверка расстановки (solver_full) идёт — начата {when}']
    if state == 'ok':
        age = (now - fin).total_seconds() / 86400 if fin else None
        line = (f'DIGEST:недельная проверка расстановки (solver_full): {when}, {mins} мин, '
                f'влезают {s.get("fit", "?")}/{s.get("total", "?")}, проблемных {s.get("bad", "?")}')
        if age is None or age > max_age_days:
            return [line, f'WARN:solver_weekly: последняя недельная проверка расстановки — {when} '
                          f'({"давно" if age is None else f"{age:.0f} дн. назад"}); понедельничного запуска не было']
        return [line]
    why = s.get('reason') or f'код {s.get("rc", "?")}'
    what = 'упала' if state == 'FAIL' else 'пропущена' if state == 'skipped' else f'в состоянии «{state}»'
    return [f'WARN:solver_weekly: последняя недельная проверка расстановки {what} ({when}): {why}']


def _selftest() -> int:
    import tempfile
    bad = 0

    def ok(name, cond, extra=''):
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
        bad += 0 if cond else 1
    now = datetime.datetime(2026, 11, 23, 12, 0, tzinfo=datetime.timezone.utc)
    with tempfile.TemporaryDirectory(prefix='sw-status-') as td:
        p = os.path.join(td, 's.json')

        def put(d):
            json.dump(d, open(p, 'w', encoding='utf-8'))
        r = digest(os.path.join(td, 'нет.json'), now)
        ok('нет статуса — одно предупреждение', len(r) == 1 and r[0].startswith('WARN:solver_weekly:') and 'ещё не было' in r[0])
        open(p, 'w').write('{битый')
        ok('битый файл — предупреждение, без падения', digest(p, now)[0].startswith('WARN:solver_weekly:'))
        put({'state': 'ok', 'finished_at': '2026-11-23T06:31:00Z', 'finished': '2026-11-23 06:31:00', 'sec': 3450, 'total': 272, 'fit': 266, 'bad': 6})
        r = digest(p, now)
        ok('ok свежий — только DIGEST с числами', r == ['DIGEST:недельная проверка расстановки (solver_full): 2026-11-23 06:31, 58 мин, влезают 266/272, проблемных 6'], r)
        put({'state': 'ok', 'finished_at': '2026-11-10T06:31:00Z', 'finished': '2026-11-10 06:31:00', 'sec': 3450, 'total': 272, 'fit': 266, 'bad': 6})
        r = digest(p, now)
        ok('ok старше 8 дней — DIGEST и WARN', len(r) == 2 and r[1].startswith('WARN:solver_weekly:') and '13 дн.' in r[1], r)
        put({'state': 'FAIL', 'rc': 124, 'finished': '2026-11-23 08:00:00', 'finished_at': '2026-11-23T08:00:00Z', 'reason': 'не уложился в срок'})
        r = digest(p, now)
        ok('FAIL — предупреждение с причиной', len(r) == 1 and 'упала' in r[0] and 'не уложился в срок' in r[0], r)
        put({'state': 'skipped', 'reason': 'дневная сборка держит замок', 'finished': '2026-11-23 06:00:00', 'finished_at': '2026-11-23T06:00:00Z'})
        ok('skipped — предупреждение «пропущена»', 'пропущена' in digest(p, now)[0])
        put({'state': 'running', 'started_at': '2026-11-23T09:30:00Z', 'started': '2026-11-23 09:30:00'})
        ok('running недавно — просто «идёт», не WARN', digest(p, now)[0].startswith('DIGEST:') and 'идёт' in digest(p, now)[0])
        put({'state': 'running', 'started_at': '2026-11-22T05:30:00Z', 'started': '2026-11-22 05:30:00'})
        ok('running больше 6 часов — предупреждение', digest(p, now)[0].startswith('WARN:solver_weekly:'))
    return 1 if bad else 0


def main() -> int:
    if '--selftest' in sys.argv:
        return _selftest()
    if '--digest' not in sys.argv:
        print(__doc__)
        return 2

    def arg(name, default):
        return sys.argv[sys.argv.index(name) + 1] if name in sys.argv and sys.argv.index(name) + 1 < len(sys.argv) else default
    for line in digest(arg('--status', os.environ.get('SW_STATUS') or DEFAULT), max_age_days=float(arg('--max-age-days', 8))):
        print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
