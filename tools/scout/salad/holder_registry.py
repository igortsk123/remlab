#!/usr/bin/env python3
"""РЕЕСТР ДЕРЖАТЕЛЕЙ ГРУПП SALAD (T-20261124-42/1, урок 929).

ЗАЧЕМ. 24.11 группа Salad жила после конца работы: скрипт, который её поднял («держатель»), умер, а машина продолжала стоить денег.
Обход видел только «ЖИВО машин N» и не знал, чья группа и жив ли её держатель. Теперь тот, кто поднимает группу, записывает себя сюда;
`tools/ops/salad_live.py` сопоставляет группы Salad с этими записями и поднимает ❗ на группу без живого держателя.

ЗАПИСЬ — файл `<папка>/<группа>.json` (папка: `$SALAD_HOLDERS_DIR` или `~/.local/state/remlab/salad-holders`; реестр локален для машины, `host` в записи):
  {group, host, pid, pid_start, task, started_at, heartbeat_at[, warm_until]}
  • `pid_start` — время старта процесса из /proc/<pid>/stat: pid мог достаться другому процессу, запись про мёртвого не должна выглядеть живой.
  • `warm_until` — тёплая нода оставлена намеренно (kit_driver, keep-warm): до этого момента группу держит «тёплая метка», гасит её sweep.
КТО ПИШЕТ: `kit_driver.create_and_start` (после /start), `batch_show.ensure_group_started` (подняли или подхватили поднятую). Пульс — `beat` там, где драйвер уже
пишет строку журнала раз в минуту. Стирает — `clear` после подтверждённого «0 нод».
НИ ОДНА ФУНКЦИЯ НЕ БРОСАЕТ ИСКЛЮЧЕНИЙ: ошибка реестра — строка в журнал и False; платный драйвер из-за неё не падает.
Сети нет вообще. Ключ Salad сюда не попадает.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time

DEFAULT_DIR = '~/.local/state/remlab/salad-holders'


def holders_dir(d: str | None = None) -> str:
    return os.path.expanduser(d or os.environ.get('SALAD_HOLDERS_DIR') or DEFAULT_DIR)


def _test_process(d: str | None) -> bool:
    """Тесты репозитория (скрипт tests_*/test_*) гоняют драйвер на подставных группах — в настоящий реестр машины они писать не должны
    (имя «g» или «trial-x» стояло бы там мусором). Папка задана явно (`d` или SALAD_HOLDERS_DIR) — пишем, это тест самого реестра."""
    if d or os.environ.get('SALAD_HOLDERS_DIR'):
        return False
    base = os.path.basename(sys.argv[0] or '')
    return base.startswith(('tests_', 'test_'))


def _say(msg: str) -> None:
    try:
        print(f'!! реестр держателей: {msg}', flush=True)
    except Exception:  # noqa: BLE001 — даже печать не должна ронять драйвер
        pass


def pid_start(pid: int) -> str | None:
    """Время старта процесса (22-е поле /proc/<pid>/stat, тики с загрузки) как строка; нет процесса/нет /proc → None."""
    try:
        with open(f'/proc/{int(pid)}/stat', encoding='utf-8', errors='replace') as f:
            s = f.read()
        return s[s.rindex(')') + 2:].split()[19]              # после «(comm)»: state — поле 3, starttime — поле 22
    except (OSError, ValueError, IndexError):
        return None


def _path(group: str, d: str | None = None) -> str:
    safe = ''.join(c if (c.isalnum() or c in '-_.') else '_' for c in str(group))
    return os.path.join(holders_dir(d), safe + '.json')


def _atomic_write(path: str, rec: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(rec, f, ensure_ascii=False)
    os.replace(tmp, path)


def default_task() -> str:
    return os.environ.get('REMLAB_TASK') or os.path.basename(sys.argv[0] or '') or 'неизвестно'


def read(group: str, d: str | None = None) -> dict | None:
    try:
        with open(_path(group, d), encoding='utf-8') as f:
            r = json.load(f)
        return r if isinstance(r, dict) else None
    except (OSError, ValueError):
        return None


def read_all(d: str | None = None) -> dict[str, dict]:
    """{группа: запись}; битый или чужой по форме файл пропускаем."""
    out: dict[str, dict] = {}
    try:
        names = sorted(os.listdir(holders_dir(d)))
    except OSError:
        return out
    for fn in names:
        if not fn.endswith('.json'):
            continue
        try:
            with open(os.path.join(holders_dir(d), fn), encoding='utf-8') as f:
                r = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(r, dict) and r.get('group'):
            out[str(r['group'])] = r
    return out


def write(group: str, task: str | None = None, pid: int | None = None, now: float | None = None, d: str | None = None, warm_until: float | None = None) -> bool:
    """Записать себя держателем группы. Не бросает: ошибка — строка в журнал и False."""
    if _test_process(d):
        return False
    try:
        t = time.time() if now is None else now
        p = os.getpid() if pid is None else int(pid)
        rec = {'group': group, 'host': socket.gethostname(), 'pid': p, 'pid_start': pid_start(p), 'task': task or default_task(), 'started_at': t, 'heartbeat_at': t}
        if warm_until is not None:
            rec['warm_until'] = warm_until
        _atomic_write(_path(group, d), rec)
        return True
    except Exception as e:  # noqa: BLE001 — реестр не должен ронять платный драйвер
        _say(f'не записан держатель {group} ({type(e).__name__}: {str(e)[:80]})')
        return False


def adopt(group: str, task: str | None = None, now: float | None = None, d: str | None = None) -> bool:
    """Группа уже поднята кем-то (подхват): запись пишем, только если живого держателя на этой машине нет. Не бросает."""
    if _test_process(d):
        return False
    try:
        r = read(group, d)
        if r and holder_state(r) == 'alive':
            return True
        return write(group, task, now=now, d=d)
    except Exception as e:  # noqa: BLE001
        _say(f'подхват {group} не записан ({type(e).__name__}: {str(e)[:80]})')
        return False


def beat(group: str, now: float | None = None, d: str | None = None, pid: int | None = None) -> bool:
    """Пульс: обновить heartbeat_at, только если запись — наша (тот же pid). Нет записи или чужая → False, ничего не пишем. Не бросает."""
    try:
        r = read(group, d)
        p = os.getpid() if pid is None else int(pid)
        if not r or r.get('pid') != p:
            return False
        r['heartbeat_at'] = time.time() if now is None else now
        r.pop('warm_until', None)
        _atomic_write(_path(group, d), r)
        return True
    except Exception as e:  # noqa: BLE001
        _say(f'пульс {group} не записан ({type(e).__name__}: {str(e)[:80]})')
        return False


def beat_all(now: float | None = None, d: str | None = None, pid: int | None = None) -> int:
    """Пульс всем группам этого процесса (конвейер держит пачку групп). → сколько обновлено. Не бросает."""
    n = 0
    try:
        p = os.getpid() if pid is None else int(pid)
        for g, r in read_all(d).items():
            if r.get('pid') == p and beat(g, now, d, p):
                n += 1
    except Exception as e:  # noqa: BLE001
        _say(f'пульс не записан ({type(e).__name__}: {str(e)[:80]})')
    return n


def mark_warm(group: str, until: float, now: float | None = None, d: str | None = None) -> bool:
    """Тёплая нода оставлена намеренно до `until`: держатель — «тёплая метка», процесс может умереть. Не бросает."""
    if _test_process(d):
        return False
    try:
        r = read(group, d) or {}
        t = time.time() if now is None else now
        r.update({'group': group, 'warm_until': float(until), 'heartbeat_at': t})
        r.setdefault('host', socket.gethostname())
        r.setdefault('pid', os.getpid())
        r.setdefault('pid_start', pid_start(os.getpid()))
        r.setdefault('task', default_task())
        r.setdefault('started_at', t)
        _atomic_write(_path(group, d), r)
        return True
    except Exception as e:  # noqa: BLE001
        _say(f'тёплая метка {group} не записана ({type(e).__name__}: {str(e)[:80]})')
        return False


def clear(group: str, d: str | None = None) -> bool:
    """Стереть запись после подтверждённого «0 нод». Нет записи — тоже True. Не бросает."""
    if _test_process(d):
        return True
    try:
        os.unlink(_path(group, d))
        return True
    except FileNotFoundError:
        return True
    except Exception as e:  # noqa: BLE001
        _say(f'запись {group} не стёрта ({type(e).__name__}: {str(e)[:80]})')
        return False


def holder_state(rec: dict, host: str | None = None, alive_fn=None) -> str:
    """'alive' — процесс на этой машине есть и это тот же процесс; 'dead' — нет / pid переиспользован; 'foreign' — запись другой машины (проверить нельзя).
    `alive_fn(pid) -> pid_start|None` подменяется в тестах."""
    if (rec.get('host') or '') != (host if host is not None else socket.gethostname()):
        return 'foreign'
    start = (alive_fn or pid_start)(rec.get('pid') or -1)
    if start is None:
        return 'dead'
    want = rec.get('pid_start')
    return 'alive' if (want is None or str(want) == str(start)) else 'dead'
