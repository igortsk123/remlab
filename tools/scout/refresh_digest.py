#!/usr/bin/env python3
"""СТАТУС И УТРЕННЯЯ СВОДКА НОЧНОГО ПРОГОНА — вызывает `finish()` в `refresh_daily.sh`.

Пишет `refresh-status.json` (атомарно) и печатает текст сводки — его `finish()` отдаёт `alert.sh`. До 04.11 это была
python-вставка (heredoc) в самом `refresh_daily.sh`; она падала молча: `step()` режет первую строку WARN до 200 БАЙТ
(`cut -c` в C-локали крона), русская буква рвалась пополам, чтение RES_FILE в utf-8 бросало UnicodeDecodeError — stdout
пустой, владельцу уходило «алерт без текста», статус не писался с 17.10 (T-20261104-11: 14.10 и каждую ночь с 18.10;
так никто и не увидел, что enrich падает 11 ночей). Теперь: вход читается с заменой битых байт; любой сбой сборки —
громкий текст «сводка не собралась: <ошибка>» со списком FAIL-шагов и минимальный статус overall=FAIL, traceback — в stderr.

Вход — переменные окружения (контракт прежней вставки): REFRESH_RC, STATUS_FILE, RES_FILE (строки
`шаг\tсостояние\tчисло WARN\tпервая WARN`), TODAY, STARTED, FEEDS_OK, DL_OK, DL_TOTAL, DEAD, PRODUCTS, LOG_FILE;
FRESH_FILE — по умолчанию `feed-freshness.json` в текущей папке.

    REFRESH_RC=0 STATUS_FILE=… RES_FILE=… … ~/venvs/scout/bin/python refresh_digest.py
    python3 tests/test_refresh_digest.py      # самопроверка: фикстура с FAIL, битый UTF-8, сломанный вход
"""
import datetime
import json
import os
import socket
import subprocess
import sys
import traceback


def read_res(path: str) -> dict:
    """Шаги из RES_FILE → {шаг: (состояние, число WARN, первая WARN)}. Байты, порванные обрезкой, — не ошибка."""
    out = {}
    for line in open(path, encoding='utf-8', errors='replace'):
        parts = line.rstrip('\n').split('\t', 3)
        if len(parts) < 2:
            continue
        out[parts[0]] = (parts[1], parts[2] if len(parts) > 2 else '0', (parts[3] if len(parts) > 3 else '').rstrip('�'))
    return out


TOUR_LOG = os.path.expanduser('~/remlab-logs/trial/reissue.log')


def tour_passes(path: str, now: datetime.datetime | None = None, hours: int = 24) -> tuple[list, list]:
    """Проходы автоперевыпуска туров за сутки (T-20261112-92) — из журнала `tools/ops/tour-reissue.sh` (поля через TAB: время,
    ok|warn, итог, первое замечание, папка). Проходы идут фоном (ночью и после дневных выкладок), поэтому итог ночного попадает
    в сводку СЛЕДУЮЩЕЙ ночи. → (строка-сводка, важные строки по проходам с замечаниями). Журнала нет — ничего."""
    try:
        lines = open(path, encoding='utf-8', errors='replace').read().splitlines()
    except OSError:
        return [], []
    since = (now or datetime.datetime.now()) - datetime.timedelta(hours=hours)
    rows = []
    for ln in lines:
        p = ln.split('\t')
        if len(p) < 3:
            continue
        try:
            t = datetime.datetime.strptime(p[0], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue
        if t >= since:
            rows.append(p)
    if not rows:
        return ['туры агентов: за сутки перевыпусков не было'], []
    bad = [p for p in rows if p[1] == 'warn']
    last = rows[-1][2].removeprefix('tour_reissue: ')
    info = [f'туры агентов за сутки: проходов {len(rows)}, с замечаниями {len(bad)}; последний — {last}'[:300]]
    pinned = [f'❗ туры агентов ({p[0][11:16]}): {p[3] if len(p) > 3 and p[3] else p[2]}'[:300] for p in bad[-2:]]
    return info, pinned


def build(env) -> tuple[dict, str]:
    steps, warns = {}, {}
    for name, (state, n, first) in read_res(env['RES_FILE']).items():
        steps[name] = state
        if state == 'warn':
            warns[name] = {'n': int(n or 0), 'first': first[:200]}
    fails = sorted(k for k, v in steps.items() if v == 'FAIL')
    skipped = sorted(k for k, v in steps.items() if v == 'skipped')
    rc = int(env.get('REFRESH_RC') or 0)
    overall = 'FAIL' if fails or rc != 0 else ('warn' if warns else 'ok')
    try:
        sha = subprocess.run(['git', '-C', os.path.dirname(os.path.abspath(env['STATUS_FILE'])), 'rev-parse', '--short', 'HEAD'],
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        sha = ''
    delta = ''
    info = []      # строки шагов `DIGEST:текст` (писатель банка: снято / добавлено / ждёт меш) — в дайджест как есть, статус не меняют
    pinned = []    # `DIGEST:!текст` — важное владельцу («демо не опубликовано», room-bank-01 Д, T-20261107-04/2): всегда, сразу за
    #               шапкой, вне лимита 6 последних — не зависит от порядка шагов ночи
    try:
        seen = False
        for line in open(env['LOG_FILE'], encoding='utf-8', errors='ignore'):
            if line.startswith('=== ' + env['TODAY']): seen = True
            if seen and line.startswith('ДЕЛЬТА'): delta = line[len('ДЕЛЬТА'):].strip()[:200]
            if seen and line.startswith('DIGEST:!'): pinned.append('❗ ' + line[len('DIGEST:!'):].strip()[:300])
            elif seen and line.startswith('DIGEST:'): info.append(line[len('DIGEST:'):].strip()[:300])
    except Exception:
        pass
    tours, tour_bad = tour_passes(env.get('TOUR_REISSUE_LOG') or TOUR_LOG)
    pinned += tour_bad
    fresh = '?'
    try:
        ff = json.load(open(env.get('FRESH_FILE') or 'feed-freshness.json'))
        fresh = f"{sum(1 for v in ff.values() if v.get('state') == 'fresh')}/{len(ff)}"
    except Exception:
        pass
    now = datetime.datetime.now(datetime.timezone.utc)
    status = {'date': env['TODAY'], 'started_at': env['STARTED'], 'finished_at': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
              'finished': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),  # совместимость со старыми читателями
              'overall': overall, 'exit_code': rc, 'host': socket.gethostname(), 'git_sha': sha,
              'feeds_ok': int(env['FEEDS_OK'] or 0), 'feeds_downloaded': int(env['DL_OK'] or 0), 'feeds_total': int(env['DL_TOTAL'] or 0),
              'feeds_dead': env['DEAD'].strip(), 'feeds_fresh': fresh, 'products': int(env['PRODUCTS'] or 0), 'delta': delta,
              'steps': steps, 'warns': warns, 'fails': fails, 'skipped': skipped}
    status.update({k: v for k, v in steps.items() if k not in status})   # плоские ключи шагов — как раньше
    head = {'ok': 'ок', 'warn': 'с предупреждениями', 'FAIL': 'С ОШИБКАМИ'}[overall]
    msg = [f"remlab каталог {env['TODAY']}: прогон {head}, {status['finished_at'][11:16]} UTC",
           f"фиды: скачано {status['feeds_downloaded']}/{status['feeds_total']}, свежих {fresh}; товаров в наличии: {status['products']}",
           f"дельта: {delta or 'нет'}"] + pinned + info[-6:] + tours
    if fails: msg.append('FAIL: ' + ', '.join(fails) + (f' (exit {rc})' if rc else ''))
    for k, w in sorted(warns.items()): msg.append(f"WARN {k}" + (f" ×{w['n']}" if w['n'] > 1 else '') + f": {w['first']}")
    if skipped: msg.append('пропущено (openai.off): ' + ', '.join(skipped))
    return status, '\n'.join(msg)[:3500]


def write_status(path: str, status: dict) -> None:
    tmp = path + '.tmp'
    json.dump(status, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False)
    os.replace(tmp, path)


def fallback(env, err: BaseException) -> tuple[dict, str]:
    """Сборка упала — всё равно громко: первая строка ошибки, FAIL-шаги (если RES_FILE читается) и минимальный статус."""
    try:
        fails = sorted(k for k, (s, _, _) in read_res(env.get('RES_FILE') or '').items() if s == 'FAIL')
        fl = ', '.join(fails) or 'нет'
    except Exception:
        fails, fl = [], 'неизвестно (список шагов не прочитан)'
    first = (f'{type(err).__name__}: {err}'.splitlines() or [''])[0][:300]
    today = env.get('TODAY') or datetime.date.today().isoformat()
    rc = str(env.get('REFRESH_RC') or '0')
    status = {'date': today, 'started_at': env.get('STARTED', ''), 'overall': 'FAIL',
              'exit_code': int(rc) if rc.lstrip('-').isdigit() else -1, 'host': socket.gethostname(),
              'finished_at': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
              'fails': fails, 'digest_error': first}
    return status, (f'remlab каталог {today}: СВОДКА НЕ СОБРАЛАСЬ — {first}\nFAIL шагов: {fl}\n'
                    'подробности — tools/scout/refresh.log на DEV')


def main(env=None) -> int:
    env = os.environ if env is None else env
    try:
        status, text = build(env)
    except Exception as e:
        traceback.print_exc()
        status, text = fallback(env, e)
    try:
        write_status(env['STATUS_FILE'], status)
    except Exception as e:
        traceback.print_exc()
        text += f'\nстатус не записан: {type(e).__name__}: {e}'[:300]
    print(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
