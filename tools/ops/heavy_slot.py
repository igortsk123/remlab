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
  * ожидание сверх `--timeout` — код 124 (как у `timeout`), команда не запускается;
  * СТРОГИЙ ПОРЯДОК ПРИХОДА (T-57/2): каждый ожидающий берёт билет (номер под отдельным замком `queue.lock`), слот берёт
    только первый ЖИВОЙ билет; умерший ожидающий выбывает сам (pid + время старта процесса); отпустивший и тут же
    вернувшийся (длинный цикл по шагам) получает новый билет в конец — ждущих не обгоняет;
  * УСТУПКА ПО ПАМЯТИ: держатель, ждущий память дольше HEAVY_SLOT_YIELD (с, 600), отпускает слот и встаёт в конец, если в
    очереди есть тот, кому памяти хватает уже сейчас (меньший порог); не больше HEAVY_SLOT_MAX_YIELDS (3) раз — дальше ждёт
    память, держа очередь (защита большой задачи от голодания: её обгоняют не больше K раз);
  * ОЖИДАЮЩИЙ БЕЗ БИЛЕТА (T-57/3; процесс старой версии, `wait/<pid>`, билетов не знает и ловит замок опросом раз в 1 с):
    при первом же разборе очереди новым ожидающим получает билет-заместитель в КОНЕЦ очереди (`proxy=1`); пока он не первый,
    новые его не пропускают — первый живой билет опрашивает замки часто (HEAVY_SLOT_HEAD_POLL, 0,02 с) и забирает
    освободившийся слот раньше секундного опроса старого; дошла очередь до заместителя — новые ждут, старый берёт сам;
    взял / ушёл / вернулся заново — заместитель снимается (вернувшийся — снова в конец). Голодания нет: билет у него есть;
  * ДВА СЛОТА (T-57/3, HEAVY_SLOT_SLOTS, по умолчанию 2; `1` — один слот, как до T-57/3): первый слот (`slot.lock`, `holder` —
    общие со старой версией) берёт первый в очереди и, как прежде, ждёт в нём свой порог памяти. Второй (`slot2.lock`,
    `holder2`) — только пока первый занят и только если свободно ПО ФАКТУ (MemAvailable сейчас) ≥ порог держателя + свой
    порог + запас (HEAVY_SLOT_RESERVE_GB, 1 ГБ, но не меньше 5 % MemTotal — earlyoom `-m 10,5` на 5 % убивает, render
    первым): второй стартует сразу, ждать память во втором слоте нельзя. Не хватает — строго по одному, как прежде;
    держатель первого слота, пока ждёт память, второго не пускает (свободно меньше его же порога).
Переменные (для самопроверки и особых случаев): HEAVY_SLOT_DIR (замок и состояние, по умолчанию ~/.cache/remlab-heavy-slot —
одинаково в кроне и в сессии, не в репо), HEAVY_SLOT_LOG, HEAVY_SLOT_MEMINFO (подмена /proc/meminfo), HEAVY_SLOT_POLL (с, 30),
HEAVY_SLOT_REPORT (строка «ждёт» в журнал раз в N с, 300), HEAVY_SLOT_YIELD, HEAVY_SLOT_MAX_YIELDS, HEAVY_SLOT_SLOTS,
HEAVY_SLOT_RESERVE_GB, HEAVY_SLOT_HEAD_POLL.
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


def _meminfo(key: str) -> float:
    with open(os.environ.get('HEAVY_SLOT_MEMINFO') or '/proc/meminfo', encoding='ascii') as f:
        for ln in f:
            if ln.startswith(key + ':'):
                return int(ln.split()[1]) / 1048576
    raise RuntimeError(f'нет {key}')


def mem_available_gb() -> float:
    return _meminfo('MemAvailable')


def slots() -> int:
    """Число слотов (HEAVY_SLOT_SLOTS, по умолчанию 2; меньше 1 — 1)."""
    return max(1, int(_env_f('HEAVY_SLOT_SLOTS', 2)))


def reserve_gb() -> float:
    """Запас для второго держателя: HEAVY_SLOT_RESERVE_GB (1 ГБ), но не меньше 5 % памяти (порог SIGKILL earlyoom)."""
    try:
        floor = 0.05 * _meminfo('MemTotal')
    except (OSError, RuntimeError):
        floor = 0.0
    return max(_env_f('HEAVY_SLOT_RESERVE_GB', 1.0), floor)


def log(label: str, msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {label} pid={os.getpid()} {msg}\n"
    try:                                          # журнал не должен ронять прогон (стенд паритета запрещает запись вне себя)
        p = log_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'a', encoding='utf-8') as f:
            f.write(line)
    except OSError as e:
        sys.stderr.write(f'heavy-slot: журнал недоступен ({e.__class__.__name__}): {line}')


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


def _starttime(pid: int) -> str:
    """Время старта процесса (поле 22 /proc/pid/stat) — чтобы чужой процесс с тем же pid не «оживил» умерший билет."""
    try:
        with open(f'/proc/{pid}/stat', encoding='utf-8', errors='replace') as f:
            return f.read().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return ''


@contextlib.contextmanager
def _qlock(d: str):
    """Отдельный короткий замок на выдачу и разбор билетов (слот — `slot.lock`, его держат долго)."""
    fd = os.open(os.path.join(d, 'queue.lock'), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _next_seq(d: str) -> int:
    """Следующий номер билета (вызывать под `_qlock`)."""
    try:
        with open(os.path.join(d, 'seq'), encoding='ascii') as f:
            n = int(f.read().strip() or 0) + 1
    except (OSError, ValueError):
        n = 1
    with open(os.path.join(d, 'seq.tmp'), 'w', encoding='ascii') as f:
        f.write(str(n))
    os.replace(os.path.join(d, 'seq.tmp'), os.path.join(d, 'seq'))
    return n


def _take_ticket(d: str, me: dict) -> str:
    """Билет в конец очереди: следующий номер из `seq`, файл `wait/<номер>-<pid>`."""
    with _qlock(d):
        _tickets(d, clean=True)                   # пришедшие раньше без билета — получают его до меня
        n = _next_seq(d)
        p = os.path.join(d, 'wait', f'{n:08d}-{os.getpid()}')
        _write_kv(p, dict(me, ticket=n, start=_starttime(os.getpid()), stage='очередь'))
    return p


def _old_waiters(w: str, files: list) -> dict:
    """Живые ожидающие старой версии (`wait/<pid>` без номера): {pid: запись}."""
    out = {}
    for f in files:
        if not f.isdigit():
            continue
        kv = _read_kv(os.path.join(w, f))
        if kv and _alive(int(f)):
            out[int(f)] = kv
    return out


def _is_ticket(f: str) -> bool:
    """Имя билета: `<номер>-<pid>`, заместитель — `<номер>_<pid>` (версия T-57/2 имена без «-» пропускает, поэтому
    заместитель её ожидающих не держит: снять устаревший заместитель она не умеет)."""
    return '.tmp' not in f and f[:8].isdigit() and f[8:9] in ('-', '_')


def _tickets(d: str, clean: bool = False) -> list:
    """Живые билеты по порядку: [(номер, путь, запись)]. clean (вызывать под `_qlock`) — убрать билеты умерших и выдать
    билет-заместитель в конец ожидающим без билета (старая версия, `wait/<pid>`). Заместитель жив, пока лежит тот же
    `wait/<pid>` (то же `since`): старый взял слот / ушёл / вернулся заново — заместитель снимается."""
    out = []
    w = os.path.join(d, 'wait')
    files = sorted(os.listdir(w))
    old = _old_waiters(w, files)
    covered = set()
    for f in files:
        if not _is_ticket(f):
            continue
        p = os.path.join(w, f)
        kv = _read_kv(p)
        try:
            pid = int((kv or {}).get('pid', ''))
        except ValueError:
            pid = 0
        alive = bool(kv and pid and _alive(pid) and kv.get('start', '') == _starttime(pid))
        if alive and kv.get('proxy') == '1':
            alive = pid in old and old[pid].get('since') == kv.get('since_old') and pid not in covered
        if alive:
            out.append((int(f[:8]), p, kv))
            if kv.get('proxy') == '1':
                covered.add(pid)
        elif clean and kv is not None:
            _unlink(p)
    if clean:
        for pid, kv in sorted(old.items(), key=lambda x: x[1].get('since', '')):
            st = _starttime(pid)
            if pid in covered or not st:
                continue
            n = _next_seq(d)
            p = os.path.join(w, f'{n:08d}_{pid}')
            rec = {k: str(v) for k, v in dict(kv, ticket=n, start=st, proxy=1, since_old=kv.get('since', ''),
                                             stage='очередь').items()}
            _write_kv(p, rec)
            out.append((n, p, rec))
    return out


def _my_turn(d: str, ticket: str) -> bool:
    with _qlock(d):
        live = _tickets(d, clean=True)
    return bool(live) and live[0][1] == ticket


def _fits_now(d: str, ticket_pid: int, free: float) -> dict | None:
    """Ожидающий (не я), которому свободной памяти хватает уже сейчас, — ради него держатель уступает."""
    for _, _, kv in _tickets(d):
        try:
            if int(kv['pid']) != ticket_pid and float(kv.get('min_gb', 1e9)) <= free:
                return kv
        except (KeyError, ValueError):
            continue
    return None


def _lock_file(k: int = 1) -> str:
    """Замок слота k: первый — `slot.lock` (общий со старой версией), дальше `slot<k>.lock`."""
    d = slot_dir()
    os.makedirs(os.path.join(d, 'wait'), exist_ok=True)
    return os.path.join(d, 'slot.lock' if k == 1 else f'slot{k}.lock')


def _holder_file(d: str, k: int) -> str:
    return os.path.join(d, 'holder' if k == 1 else f'holder{k}')


def is_held(k: int = 1) -> bool:
    """Занят ли замок слота k сейчас (пробная попытка взять и сразу отпустить)."""
    fd = os.open(_lock_file(k), os.O_RDWR | os.O_CREAT, 0o644)
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
    return pid if pid in _ancestors() and any(is_held(k) for k in range(1, slots() + 1)) else None


def _co_need(d: str, k: int, n: int) -> tuple[float, str]:
    """Сколько памяти нужно держателю слота k ВДОБАВОК к своему порогу из-за других занятых слотов: их пороги + запас
    (никого — 0). Порог держателя не прочитан — бесконечность (ждать, пока тот слот освободится). → (ГБ, пояснение)."""
    ths = []
    for j in range(1, n + 1):
        if j == k or not is_held(j):
            continue
        h = _read_kv(_holder_file(d, j)) or {}
        try:
            ths.append(float(h['min_gb']))
        except (KeyError, ValueError):
            return float('inf'), f'порог держателя слота {j} не прочитан'
    if not ths:
        return 0.0, ''
    res = reserve_gb()
    return sum(ths) + res, f"порог держателя {' + '.join(f'{t:g}' for t in ths)} + запас {res:.1f}"


def _admit(d: str, k: int, min_gb: float, n: int) -> tuple[bool, str, float]:
    """Можно ли занять только что взятый слот k ≥ 2 → (да/нет, пояснение, свободно ГБ): только при занятом другом слоте и
    если свободно ПО ФАКТУ ≥ пороги держателей + свой + запас (ждать память во втором слоте нельзя — стартует сразу)."""
    extra, why = _co_need(d, k, n)
    if not why:
        return False, 'другие слоты свободны', 0.0
    free = mem_available_gb()
    need = extra + min_gb
    return free >= need, f"свободно {free:.1f} ГБ {'≥' if free >= need else '<'} {why} + свой {min_gb:g}", free


@contextlib.contextmanager
def heavy_slot(label: str, min_gb: float = 6.0, timeout: float | None = None, no_slot: bool = False,
               poll: float | None = None, report: float | None = None, say=None, cmd: str = '',
               yield_after: float | None = None, max_yields: int | None = None):
    """Взять общую очередь, дождаться MemAvailable ≥ min_gb, выполнить тело, отпустить. → info: waited_s, free_gb, fd.
    Таймаут (очередь + память) — SlotTimeout. `say(msg)` — дублировать строки ожидания в свой журнал."""
    poll = _env_f('HEAVY_SLOT_POLL', 30) if poll is None else poll
    report = _env_f('HEAVY_SLOT_REPORT', 300) if report is None else report

    def note(msg):
        log(label, msg)
        if say:
            say(msg)
    info = {'label': label, 'waited_s': 0.0, 'free_gb': None, 'fd': None, 'nested': None, 'no_slot': no_slot, 'yields': 0}
    said_starve = False
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
    n = slots()
    d = os.path.dirname(_lock_file())
    holder_p = os.path.join(d, 'holder')
    yield_s = _env_f('HEAVY_SLOT_YIELD', 600) if yield_after is None else yield_after
    max_y = int(_env_f('HEAVY_SLOT_MAX_YIELDS', 3)) if max_yields is None else max_yields
    step = min(1.0, poll) if poll > 0 else 0.05
    head_step = min(step, _env_f('HEAVY_SLOT_HEAD_POLL', 0.02))
    fds = {k: os.open(_lock_file(k), os.O_RDWR | os.O_CREAT, 0o644) for k in range(1, n + 1)}
    fd, slot = fds[1], 1
    t0 = time.time()
    me = {'label': label, 'pid': os.getpid(), 'since': int(t0), 'min_gb': min_gb, 'cmd': cmd[:300]}
    got, ticket, yields, t_lock, extra_why = False, None, 0, 0.0, ''

    def grab(try_extra: bool) -> int:
        """Первый в очереди: занять слот 1, иначе (раз в step) — второй по памяти. → номер слота или 0."""
        nonlocal extra_why
        for k in range(1, n + 1):
            if k > 1 and not try_extra:
                break
            try:
                fcntl.flock(fds[k], fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                continue
            if k == 1:
                return 1
            ok, why, free_k = _admit(d, k, min_gb, n)
            if ok:
                extra_why = why
                _write_kv(_holder_file(d, k), dict(me, since=int(time.time()), stage='работает', free_gb=round(free_k, 1),
                                                   yields=yields, slot=k))
                return k
            fcntl.flock(fds[k], fcntl.LOCK_UN)
        return 0
    try:
        while True:                                   # круг: билет → очередь → слот → память (или уступка → новый билет)
            ticket = _take_ticket(d, dict(me, yields=yields))
            said, head, t_chk, t_extra = False, False, -1e9, -1e9
            while True:
                now = time.time()
                if now - t_chk >= step:               # первого не сдвинуть (новые — в конец): сверка раз в step
                    head, t_chk = _my_turn(d, ticket), now
                if head:
                    k = grab(n > 1 and now - t_extra >= step)
                    if n > 1 and now - t_extra >= step:
                        t_extra = now
                    if k:
                        break
                if not said:
                    h = _read_kv(holder_p) or {}
                    note(f"ждёт очередь: держит {h.get('label', '?')} pid={h.get('pid', '?')}, билет {os.path.basename(ticket)}")
                    said = True
                if timeout is not None and time.time() - t0 >= timeout:
                    note(f'не дождался очереди за {round(time.time() - t0)} с (--timeout {timeout:g}) — не запускаю')
                    raise SlotTimeout(label) from None
                time.sleep(head_step if head else step)  # первый опрашивает часто — старый (раз в 1 с) не обгонит
            got, slot, fd = True, k, fds[k]
            t_lock = time.time() - t0
            if slot > 1:                              # второй слот: память проверена при допуске, стартует сразу
                _unlink(ticket)
                ticket = None
                free = mem_available_gb()
                holder_p = _holder_file(d, slot)
                break
            t_mem = time.time()
            _write_kv(holder_p, dict(me, since=int(t_mem), stage='память', yields=yields))
            _unlink(ticket)                           # после записи держателя: следующий первый уже видит мой порог
            ticket = None
            free, last, yielded = mem_available_gb(), -1e9, False
            co, co_why = _co_need(d, 1, n) if n > 1 else (0.0, '')
            while free < min_gb + co:
                if time.time() - last >= report:
                    note(f'держит очередь, ждёт память: свободно {free:.1f} ГБ < {min_gb:g}'
                         + (f' + {co_why} (идёт второй слот)' if co_why else '')
                         + f' (опрос раз в {poll:g} с; живое демо важнее)')
                    last = time.time()
                if timeout is not None and time.time() - t0 >= timeout:
                    note(f'не дождался памяти за {round(time.time() - t0)} с (--timeout {timeout:g}) — не запускаю')
                    raise SlotTimeout(label)
                if time.time() - t_mem >= yield_s:
                    w = _fits_now(d, os.getpid(), free) if yields < max_y else None
                    if w:
                        yields += 1
                        note(f"уступил очередь: ждал память {_sec(time.time() - t_mem)} с, свободно {free:.1f} ГБ < {min_gb:g}; "
                             f"{w.get('label')} pid={w.get('pid')} (порог {w.get('min_gb')}) проходит — встаю в конец "
                             f"(уступка {yields} из {max_y})")
                        h = _read_kv(holder_p) or {}
                        if h.get('pid') == str(os.getpid()):
                            _unlink(holder_p)
                        fcntl.flock(fd, fcntl.LOCK_UN)
                        got, yielded = False, True
                        break
                    if yields >= max_y and yields > 0 and not said_starve:
                        note(f'уступок {yields} из {max_y} — дальше жду память, держа очередь (защита от голодания)')
                        said_starve = True
                time.sleep(poll)
                free = mem_available_gb()
                co, co_why = _co_need(d, 1, n) if n > 1 else (0.0, '')
            if not yielded:
                break
        waited = time.time() - t0
        if slot == 1:
            _write_kv(holder_p, dict(me, since=int(time.time()), stage='работает', free_gb=round(free, 1), yields=yields))
        note(f'взял: ждал {_sec(waited)} с (очередь {_sec(t_lock)}, память {_sec(waited - t_lock)}), свободно {free:.1f} ГБ'
             + (f', уступок {yields}' if yields else '') + (f'; второй слот {slot}: {extra_why}' if slot > 1 else ''))
        info.update(waited_s=round(waited, 1), free_gb=free, fd=fd, yields=yields)
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
        if ticket:
            _unlink(ticket)
        if got:
            h = _read_kv(holder_p) or {}
            if h.get('pid') == str(os.getpid()):
                _unlink(holder_p)                 # под замком: новый держатель свой файл ещё не пишет
        for f in fds.values():
            os.close(f)                           # закрытие отпускает замок (если команда-потомок не держит копию)


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
    n = slots()
    d = os.path.dirname(_lock_file())
    waiters = [dict(kv, ticket=f"{kv.get('ticket')} (за старую версию без билета)") if kv.get('proxy') == '1' else kv
               for _, _, kv in _tickets(d)]                        # по порядку билетов: первый — следующий
    proxied = {w['pid'] for w in waiters if w.get('proxy') == '1'}
    names = [f for f in os.listdir(os.path.join(d, 'wait')) if '.tmp' not in f]
    dead = sum(1 for f in names if _is_ticket(f)) - len(waiters)
    for f in sorted(f for f in names if f.isdigit()):             # старая версия, заместителя ещё не выдали
        w = _read_kv(os.path.join(d, 'wait', f))
        if w and w.get('pid', '').isdigit() and _alive(int(w['pid'])) and w['pid'] not in proxied:
            waiters.append(dict(w, ticket='без билета'))
    pr = lambda s: print(s, file=out)  # noqa: E731
    any_held, stale = False, False
    for k in range(1, n + 1):
        lock = _lock_file(k)
        held = is_held(k)
        h = _read_kv(_holder_file(d, k))
        tag = f' · слот {k}' if k > 1 else ''
        if held and h and _alive(int(h.get('pid', 0) or 0)):
            pr(f"ДЕРЖИТ: {h['label']} · pid {h['pid']} · {h.get('stage', '?')} {_ago(h.get('since'))} · порог {h.get('min_gb')} ГБ"
               + (f" · уступок {h['yields']}" if h.get('yields') not in (None, '0') else '') + tag)
            pr(f"  процесс: {_proc(int(h['pid']))}")
            if h.get('cmd'):
                pr(f"  команда: {h['cmd']}")
        elif held:
            wp = {int(w['pid']) for w in waiters}
            owners = [p for p in _lock_fd_pids(lock) if p not in wp]
            who = f"{h['label']} pid {h['pid']} — процесса уже нет" if h else 'файла держателя нет'
            pr(f'ДЕРЖИТ{f" (слот {k})" if k > 1 else ""}: замок занят, держатель по записи: {who}; '
               'замок держат (унаследовали): '
               + ('; '.join(f'pid {p} {_proc(p)}' for p in owners) or 'не видно (чужой пользователь?)'))
        any_held = any_held or held
        stale = stale or bool(h and not held)
    if not any_held:
        pr('СВОБОДНО: очередь никто не держит' + (' (запись держателя устарела — процесс умер)' if stale else ''))
    pr(f'ЖДУТ: {len(waiters)}' + (' (по порядку прихода)' if waiters else '')
       + ''.join(f"\n  {k}. {w['label']} · pid {w['pid']} · {w.get('stage')} {_ago(w.get('since'))}"
                 f" · порог {w.get('min_gb')} ГБ · билет {w.get('ticket')}"
                 + (f" · уступок {w['yields']}" if w.get('yields') not in (None, '0') else '')
                 for k, w in enumerate(waiters, 1))
       + (f'\n  (записей умерших ожидающих: {dead} — не считаются)' if dead else ''))
    try:
        pr(f'ПАМЯТЬ: свободно {mem_available_gb():.1f} ГБ')
    except (OSError, RuntimeError) as e:
        pr(f'ПАМЯТЬ: не прочитать ({e})')
    if n > 1:
        pr(f'СЛОТОВ: {n} (второй — только пока первый занят и свободно ≥ порог держателя + свой + запас {reserve_gb():.1f} ГБ;'
           ' иначе по одному)')
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
