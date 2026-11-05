#!/usr/bin/env python3
"""ОБЩАЯ ОЧЕРЕДЬ ТЯЖЁЛЫХ ПРОГОНОВ DEV (T-20261105-57): одно тяжёлое за раз на машину + порог свободной памяти.

ЗАЧЕМ. Ночью 05.11 тяжёлые прогоны (VLM T-36, обход моделей T-51, паритет T-53/T-54, compose2) ждали памяти каждый своим
циклом с разными порогами (6 и 7 ГБ): при 5,5 ГБ стояли все, а освободилось — стартовали вдвоём, и earlyoom снимал
`remlab-render` (живое демо). Здесь — одна очередь: замок `flock` (держит процесс; умер — ядро отпускает само), взявший
очередь ждёт порога памяти и только потом стартует; кто держит и кто ждёт — `--status`, журнал — `~/remlab-logs/heavy-slot.log`.

  tools/ops/heavy-slot.sh <метка> [--min-gb N] [--timeout S] [--no-slot] -- <команда…>   # обёртка: rc команды наружу
  tools/ops/heavy-slot.sh --status                                                       # кто держит, кто ждёт, память
  from heavy_slot import heavy_slot                                                       # из питона — на ОДИН шаг:
  with heavy_slot('t51-look', min_gb=6):                                                  #   длинный цикл берёт слот на
      обработать_одну_модель()                                                            #   шаг, другие встают между

Правила очереди:
  * одна реализация (этот файл); `heavy-slot.sh` — обёртка над ним, замок и файлы состояния общие;
  * команда обёртки наследует открытый замок: обёртку убили, а команда работает — очередь занята, пока жива команда;
  * вложенный вызов (команда под слотом сама зовёт слот) не ждёт сам себя: `HEAVY_SLOT_HELD` = pid держателя, и он — предок;
  * обойти очередь — только явный `--no-slot` / `no_slot=True` (для отладки; строка в журнал);
  * ожидание сверх `--timeout` — код 124 (как у `timeout`), команда не запускается.
Переменные (для самопроверки и особых случаев): HEAVY_SLOT_DIR (замок и состояние, по умолчанию ~/.cache/remlab-heavy-slot —
одинаково в кроне и в сессии, не в репо), HEAVY_SLOT_LOG, HEAVY_SLOT_MEMINFO (подмена /proc/meminfo), HEAVY_SLOT_POLL (с, 30),
HEAVY_SLOT_REPORT (строка «ждёт» в журнал раз в N с, 300).
"""
from __future__ import annotations

import contextlib
import fcntl
import os
import signal
import subprocess
import sys
import time

TIMEOUT_RC = 124


class SlotTimeout(Exception):
    pass


def slot_dir() -> str:
    return os.path.expanduser(os.environ.get('HEAVY_SLOT_DIR') or '~/.cache/remlab-heavy-slot')


def log_path() -> str:
    return os.path.expanduser(os.environ.get('HEAVY_SLOT_LOG') or '~/remlab-logs/heavy-slot.log')


def _env_f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def mem_available_gb() -> float:
    with open(os.environ.get('HEAVY_SLOT_MEMINFO') or '/proc/meminfo', encoding='ascii') as f:
        for ln in f:
            if ln.startswith('MemAvailable:'):
                return int(ln.split()[1]) / 1048576
    raise RuntimeError('нет MemAvailable')


def log(label: str, msg: str) -> None:
    p = log_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'a', encoding='utf-8') as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {label} pid={os.getpid()} {msg}\n")


def _write_kv(path: str, d: dict) -> None:
    tmp = f'{path}.tmp-{os.getpid()}'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(''.join(f'{k}={str(v).replace(chr(10), " ")}\n' for k, v in d.items()))
    os.replace(tmp, path)


def _read_kv(path: str) -> dict | None:
    try:
        with open(path, encoding='utf-8') as f:
            return dict(ln.rstrip('\n').split('=', 1) for ln in f if '=' in ln)
    except OSError:
        return None


def _sec(x: float) -> str:
    return f'{x:.1f}' if x < 10 else str(round(x))


def _unlink(path: str) -> None:
    with contextlib.suppress(OSError):
        os.unlink(path)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _ppid(pid: int) -> int:
    try:
        with open(f'/proc/{pid}/stat', encoding='utf-8', errors='replace') as f:
            return int(f.read().rsplit(')', 1)[1].split()[1])      # имя процесса может быть с пробелами и скобками
    except (OSError, IndexError, ValueError):
        return 0


def _ancestors(pid: int | None = None) -> list:
    out, p = [], pid or os.getpid()
    while p > 1 and p not in out:
        out.append(p)
        p = _ppid(p)
    return out


def _lock_file() -> str:
    d = slot_dir()
    os.makedirs(os.path.join(d, 'wait'), exist_ok=True)
    return os.path.join(d, 'slot.lock')


def is_held() -> bool:
    """Занят ли замок сейчас (пробная попытка взять и сразу отпустить)."""
    fd = os.open(_lock_file(), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


def _nested() -> int | None:
    """Слот уже у предка (команда под слотом сама зовёт слот) — не ждать самого себя."""
    try:
        pid = int(os.environ.get('HEAVY_SLOT_HELD', ''))
    except ValueError:
        return None
    return pid if pid in _ancestors() and is_held() else None


@contextlib.contextmanager
def heavy_slot(label: str, min_gb: float = 6.0, timeout: float | None = None, no_slot: bool = False,
               poll: float | None = None, report: float | None = None, say=None, cmd: str = ''):
    """Взять общую очередь, дождаться MemAvailable ≥ min_gb, выполнить тело, отпустить. → info: waited_s, free_gb, fd.
    Таймаут (очередь + память) — SlotTimeout. `say(msg)` — дублировать строки ожидания в свой журнал."""
    poll = _env_f('HEAVY_SLOT_POLL', 30) if poll is None else poll
    report = _env_f('HEAVY_SLOT_REPORT', 300) if report is None else report

    def note(msg):
        log(label, msg)
        if say:
            say(msg)
    info = {'label': label, 'waited_s': 0.0, 'free_gb': None, 'fd': None, 'nested': None, 'no_slot': no_slot}
    if no_slot:
        note('БЕЗ ОЧЕРЕДИ (--no-slot): слот не берётся, порог памяти не ждётся')
        yield info
        return
    parent = _nested()
    if parent:
        info['nested'] = parent
        log(label, f'вложенный вызов: слот уже у предка pid={parent} — не ждём')
        yield info
        return
    lock = _lock_file()
    d = os.path.dirname(lock)
    holder_p, wait_p = os.path.join(d, 'holder'), os.path.join(d, 'wait', str(os.getpid()))
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o644)
    t0 = time.time()
    me = {'label': label, 'pid': os.getpid(), 'since': int(t0), 'min_gb': min_gb, 'cmd': cmd[:300]}
    got = False
    try:
        _write_kv(wait_p, dict(me, stage='очередь'))
        said = False
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if not said:
                    h = _read_kv(holder_p) or {}
                    note(f"ждёт очередь: держит {h.get('label', '?')} pid={h.get('pid', '?')}")
                    said = True
                if timeout is not None and time.time() - t0 >= timeout:
                    note(f'не дождался очереди за {round(time.time() - t0)} с (--timeout {timeout:g}) — не запускаю')
                    raise SlotTimeout(label) from None
                time.sleep(min(1.0, poll) if poll > 0 else 0.05)
        got = True
        t_lock = time.time() - t0
        _unlink(wait_p)
        _write_kv(holder_p, dict(me, since=int(time.time()), stage='память'))
        free, last = mem_available_gb(), -1e9
        while free < min_gb:
            if time.time() - last >= report:
                note(f'держит очередь, ждёт память: свободно {free:.1f} ГБ < {min_gb:g} (опрос раз в {poll:g} с; живое демо важнее)')
                last = time.time()
            if timeout is not None and time.time() - t0 >= timeout:
                note(f'не дождался памяти за {round(time.time() - t0)} с (--timeout {timeout:g}) — не запускаю')
                raise SlotTimeout(label)
            time.sleep(poll)
            free = mem_available_gb()
        waited = time.time() - t0
        _write_kv(holder_p, dict(me, since=int(time.time()), stage='работает', free_gb=round(free, 1)))
        note(f'взял: ждал {_sec(waited)} с (очередь {_sec(t_lock)}, память {_sec(waited - t_lock)}), свободно {free:.1f} ГБ')
        info.update(waited_s=round(waited, 1), free_gb=free, fd=fd)
        old = os.environ.get('HEAVY_SLOT_HELD')
        os.environ['HEAVY_SLOT_HELD'] = str(os.getpid())
        t_run = time.time()
        try:
            yield info
        finally:
            if old is None:
                os.environ.pop('HEAVY_SLOT_HELD', None)
            else:
                os.environ['HEAVY_SLOT_HELD'] = old
            log(label, f'отпустил: держал {_sec(time.time() - t_run)} с')
    finally:
        _unlink(wait_p)
        if got:
            h = _read_kv(holder_p) or {}
            if h.get('pid') == str(os.getpid()):
                _unlink(holder_p)                 # под замком: новый держатель свой файл ещё не пишет
        os.close(fd)                              # закрытие отпускает замок (если команда-потомок не держит копию)


# ---------------------------------------------------------------- обёртка и статус

def _lock_fd_pids(lock: str) -> list:
    """Процессы (свои), у которых открыт файл замка: держатель и его потомки с унаследованным замком, ожидающие."""
    st = os.stat(lock)
    out = []
    for p in os.listdir('/proc'):
        if not p.isdigit():
            continue
        fdd = f'/proc/{p}/fd'
        try:
            for f in os.listdir(fdd):
                try:
                    s = os.stat(os.path.join(fdd, f))
                except OSError:
                    continue
                if (s.st_dev, s.st_ino) == (st.st_dev, st.st_ino):
                    out.append(int(p))
                    break
        except OSError:
            continue
    return out


def _proc(pid: int) -> str:
    try:
        cmd = open(f'/proc/{pid}/cmdline', 'rb').read().replace(b'\0', b' ').decode(errors='replace').strip()
        state = open(f'/proc/{pid}/stat', encoding='utf-8', errors='replace').read().rsplit(')', 1)[1].split()[0]
    except OSError:
        return 'нет процесса'
    return f'состояние {state} · {cmd[:120]}'


def _ago(since: str | None) -> str:
    try:
        s = int(time.time() - int(since or 0))
    except ValueError:
        return '?'
    return f"с {time.strftime('%H:%M:%S', time.localtime(int(since)))} ({s // 60} мин {s % 60} с)"


def status(out=sys.stdout) -> int:
    lock = _lock_file()
    d = os.path.dirname(lock)
    held = is_held()
    h = _read_kv(os.path.join(d, 'holder'))
    waiters, dead = [], 0
    for f in sorted(os.listdir(os.path.join(d, 'wait'))):
        w = _read_kv(os.path.join(d, 'wait', f))
        if w and w.get('pid', '').isdigit() and _alive(int(w['pid'])):
            waiters.append(w)
        elif w is not None:
            dead += 1
    pr = lambda s: print(s, file=out)  # noqa: E731
    if held and h and _alive(int(h.get('pid', 0) or 0)):
        pr(f"ДЕРЖИТ: {h['label']} · pid {h['pid']} · {h.get('stage', '?')} {_ago(h.get('since'))} · порог {h.get('min_gb')} ГБ")
        pr(f"  процесс: {_proc(int(h['pid']))}")
        if h.get('cmd'):
            pr(f"  команда: {h['cmd']}")
    elif held:
        wp = {int(w['pid']) for w in waiters}
        owners = [p for p in _lock_fd_pids(lock) if p not in wp]
        who = f"{h['label']} pid {h['pid']} — процесса уже нет" if h else 'файла держателя нет'
        pr(f'ДЕРЖИТ: замок занят, держатель по записи: {who}; замок держат (унаследовали): '
           + ('; '.join(f'pid {p} {_proc(p)}' for p in owners) or 'не видно (чужой пользователь?)'))
    else:
        pr('СВОБОДНО: очередь никто не держит' + (' (запись держателя устарела — процесс умер)' if h else ''))
    pr(f'ЖДУТ: {len(waiters)}' + ''.join(f"\n  {w['label']} · pid {w['pid']} · {w.get('stage')} {_ago(w.get('since'))}"
                                           f" · порог {w.get('min_gb')} ГБ" for w in waiters)
       + (f'\n  (записей умерших ожидающих: {dead} — не считаются)' if dead else ''))
    try:
        pr(f'ПАМЯТЬ: свободно {mem_available_gb():.1f} ГБ')
    except (OSError, RuntimeError) as e:
        pr(f'ПАМЯТЬ: не прочитать ({e})')
    pr(f'журнал: {log_path()}')
    return 0


def run(argv: list) -> int:
    """`<метка> [--min-gb N] [--timeout S] [--no-slot] -- <команда…>` → rc команды (124 — не дождался)."""
    if '--' not in argv or argv.index('--') < 1 or argv.index('--') == len(argv) - 1:
        print('heavy-slot: <метка> [--min-gb N] [--timeout S] [--no-slot] -- <команда…> | --status', file=sys.stderr)
        return 2
    i = argv.index('--')
    opts, cmd = argv[:i], argv[i + 1:]
    label, opts = opts[0], opts[1:]
    min_gb, timeout, no_slot = 6.0, None, False
    k = 0
    while k < len(opts):
        o = opts[k]
        if o in ('--min-gb', '--timeout') and k + 1 < len(opts):
            try:
                v = float(opts[k + 1])
            except ValueError:
                print(f'heavy-slot: {o} {opts[k + 1]!r} — нужно число', file=sys.stderr)
                return 2
            min_gb, timeout = (v, timeout) if o == '--min-gb' else (min_gb, v)
            k += 2
        elif o == '--no-slot':
            no_slot, k = True, k + 1
        else:
            print(f'heavy-slot: неизвестный ключ {o}', file=sys.stderr)
            return 2

    def _term(sig, _frm):
        raise SystemExit(128 + sig)               # чтобы finally убрал записи держателя/ожидающего
    for s in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, _term)
    try:
        with heavy_slot(label, min_gb=min_gb, timeout=timeout, no_slot=no_slot, cmd=' '.join(cmd)) as info:
            p = subprocess.Popen(cmd, pass_fds=(info['fd'],) if info['fd'] is not None else ())

            def _fwd(sig, _frm):
                p.send_signal(sig)
            for s in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
                signal.signal(s, _fwd)
            rc = p.wait()
            log(label, f'команда завершилась rc={rc}')
            return 128 - rc if rc < 0 else rc
    except SlotTimeout:
        print(f'heavy-slot: {label} не дождался очереди/памяти (--timeout) — команда не запущена', file=sys.stderr)
        return TIMEOUT_RC
    except FileNotFoundError as e:
        print(f'heavy-slot: команда не найдена: {e}', file=sys.stderr)
        return 127


def main(argv: list) -> int:
    if argv[:1] == ['--status']:
        return status()
    return run(argv)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
