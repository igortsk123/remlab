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
  * ДО ТРЁХ СЛОТОВ (T-57/3 → T-74; HEAVY_SLOT_SLOTS, по умолчанию 3; `1` — один слот, как до T-57/3): первый слот
    (`slot.lock`, `holder` — общие со старой версией) берёт первый в очереди и ждёт в нём память. Слоты 2…N (`slot<k>.lock`,
    `holder<k>`) — только пока занят другой слот и только если память есть ПО ФАКТУ сейчас: стартует сразу, ждать память в
    дополнительном слоте нельзя. Не хватает — строго по одному, как прежде.
  * ДОПУСК ПО ПАМЯТИ (T-74, один для всех слотов, без двойного счёта):
        MemAvailable ≥ Σ по другим держателям max(порог_h − память_h, 0) + свой порог + запас
    память_h — PSS всего дерева процессов держателя сейчас (она уже вычтена из MemAvailable, поэтому из порога держателя
    вычитается — до T-74 порог держателя вычитался целиком второй раз); запас — HEAVY_SLOT_RESERVE_GB (1 ГБ), но не меньше
    10 % MemTotal (earlyoom `-m 10,5` на 10 % шлёт SIGTERM, render первым). СТОРОЖ: MemAvailable < запаса — новых не пускать,
    идущих не трогать (earlyoom остаётся). Держатель первого слота, пока ждёт память, считается целиком (дерево ещё пустое).
  * ЗАМЕР (T-74): пока держит — раз в HEAVY_SLOT_SAMPLE с (5) замер памяти дерева процессов держателя (PSS — доля общих
    страниц: хром из 10 процессов по сумме RSS вышел бы в 2–3 раза больше; RSS пишется рядом); при отпускании — пик и время
    держания в журнал и в `<HEAVY_SLOT_DIR>/peaks.tsv`; сводка — `--stats` (по типу задачи: build, live, cutout, exam,
    parity, иначе метка без номера задачи). Держание дольше HEAVY_SLOT_LONG_S (2700 с = 45 мин) — WARN в журнал.
    Чего замер НЕ видит: память чужих процессов, которые команда только просит (docker exec → postgres в контейнере).
  * ПОРОГ ПО ЗАМЕРУ (T-74): при ≥ 3 засчитанных замерах типа (держание ≥ HEAVY_SLOT_MEASURE_MIN_S, 30 с; последние 10)
    эффективный порог = min(объявленный, max(1,5 × наибольший пик, HEAVY_SLOT_EFF_FLOOR_GB 0,5)); замеров меньше —
    объявленный. Им же считается и своё ожидание, и доля держателя у следующих (`eff_gb` в записи держателя).
Переменные (для самопроверки и особых случаев): HEAVY_SLOT_DIR (замок и состояние, по умолчанию ~/.cache/remlab-heavy-slot —
одинаково в кроне и в сессии, не в репо), HEAVY_SLOT_LOG, HEAVY_SLOT_MEMINFO (подмена /proc/meminfo), HEAVY_SLOT_POLL (с, 30),
HEAVY_SLOT_REPORT (строка «ждёт» в журнал раз в N с, 300), HEAVY_SLOT_YIELD, HEAVY_SLOT_MAX_YIELDS, HEAVY_SLOT_SLOTS,
HEAVY_SLOT_RESERVE_GB, HEAVY_SLOT_HEAD_POLL, HEAVY_SLOT_SAMPLE, HEAVY_SLOT_LONG_S, HEAVY_SLOT_MEASURE_MIN_S,
HEAVY_SLOT_EFF_FLOOR_GB, HEAVY_SLOT_MEM_STUB (файл «метка ГБ» — подмена замера памяти дерева для самопроверки).
"""
from __future__ import annotations

import contextlib
import fcntl
import os
import re
import signal
import subprocess
import sys
import threading
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
    """Число слотов (HEAVY_SLOT_SLOTS, по умолчанию 3; меньше 1 — 1)."""
    return max(1, int(_env_f('HEAVY_SLOT_SLOTS', 3)))


def reserve_gb() -> float:
    """Запас при любом допуске: HEAVY_SLOT_RESERVE_GB (1 ГБ), но не меньше 10 % памяти (порог SIGTERM earlyoom)."""
    try:
        floor = 0.10 * _meminfo('MemTotal')
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


def _fits_now(d: str, ticket_pid: int, free: float, others: float = 0.0) -> dict | None:
    """Ожидающий (не я), которому памяти хватает уже сейчас (его порог + доля других держателей + запас ≤ свободно; я —
    держатель слота 1 — уступаю и не считаюсь), — ради него держатель уступает."""
    room = free - others - reserve_gb()
    for _, _, kv in _tickets(d):
        try:
            if int(kv['pid']) != ticket_pid and float(kv.get('eff_gb') or kv.get('min_gb', 1e9)) <= room:
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


# ---------------------------------------------------------------- замер памяти дерева процессов и порог по замеру (T-74)

_PAGE = os.sysconf('SC_PAGE_SIZE')
_TYPES = ('build', 'live', 'cutout', 'exam', 'parity')      # порядок важен: «parity-hall-exam» — экзамен


def task_type(label: str) -> str:
    """Тип задачи по метке: build / live / cutout / exam / parity; иначе метка без номера задачи (`t51-look` → `look`)."""
    s = label.lower()
    for t in _TYPES:
        if t in s:
            return t
    s2 = re.sub(r'[-_]?\d+$', '', re.sub(r'^t\d+(-\d+)?[-_]', '', s))
    return s2 or s


def _mem_stub(label: str) -> float | None:
    """Самопроверка: HEAVY_SLOT_MEM_STUB — файл строк «метка ГБ» (последняя строка метки побеждает)."""
    p = os.environ.get('HEAVY_SLOT_MEM_STUB')
    if not p:
        return None
    v = None
    with contextlib.suppress(OSError):
        for ln in open(p, encoding='utf-8'):
            a = ln.split()
            if len(a) == 2 and a[0] == label:
                with contextlib.suppress(ValueError):
                    v = float(a[1])
    return v


def _proc_mem(pid: int) -> tuple[int, int]:
    """(PSS, RSS) процесса в байтах; PSS не прочитать — RSS за обе; процесса нет — (0, 0)."""
    try:
        with open(f'/proc/{pid}/statm', encoding='ascii') as f:
            rss = int(f.read().split()[1]) * _PAGE
    except (OSError, IndexError, ValueError):
        return 0, 0
    try:
        with open(f'/proc/{pid}/smaps_rollup', encoding='ascii') as f:
            for ln in f:
                if ln.startswith('Pss:'):
                    return int(ln.split()[1]) * 1024, rss
    except (OSError, IndexError, ValueError):
        pass
    return rss, rss


def tree_mem(pid: int, label: str = '') -> tuple[float, float]:
    """Память всего дерева процессов pid сейчас → (PSS ГБ, RSS ГБ). Процесса нет — (0, 0)."""
    stub = _mem_stub(label)
    if stub is not None:
        return stub, stub
    if not pid or not _alive(pid):
        return 0.0, 0.0
    kids: dict = {}
    for p in os.listdir('/proc'):
        if p.isdigit():
            kids.setdefault(_ppid(int(p)), []).append(int(p))
    todo, seen, pss, rss = [pid], set(), 0, 0
    while todo:
        p = todo.pop()
        if p in seen:
            continue
        seen.add(p)
        a, b = _proc_mem(p)
        pss, rss = pss + a, rss + b
        todo.extend(kids.get(p, ()))
    return pss / 2**30, rss / 2**30


def _peaks_path(d: str) -> str:
    return os.path.join(d, 'peaks.tsv')


_PEAK_COLS = ('ts', 'type', 'label', 'peak_gb', 'peak_rss_gb', 'hold_s', 'min_gb', 'eff_gb')


def _peaks(d: str) -> list:
    """Замеры из `peaks.tsv` → [{ts, type, label, peak_gb, peak_rss_gb, hold_s, min_gb, eff_gb}] (числа — float)."""
    out = []
    with contextlib.suppress(OSError):
        for ln in open(_peaks_path(d), encoding='utf-8'):
            a = ln.rstrip('\n').split('\t')
            if len(a) != len(_PEAK_COLS) or a[0] == 'ts':
                continue
            r = dict(zip(_PEAK_COLS, a))
            try:
                for k in _PEAK_COLS[3:]:
                    r[k] = float(r[k])
            except ValueError:
                continue
            out.append(r)
    return out


def _counted(rows: list, typ: str) -> list:
    """Засчитанные замеры типа: держание ≥ HEAVY_SLOT_MEASURE_MIN_S (упавший за секунды прогон пика не показал), последние 10."""
    min_s = _env_f('HEAVY_SLOT_MEASURE_MIN_S', 30)
    return [r for r in rows if r['type'] == typ and r['hold_s'] >= min_s][-10:]


def eff_threshold(d: str, typ: str, declared: float, rows: list | None = None) -> tuple[float, str]:
    """Эффективный порог: ≥ 3 засчитанных замеров типа → min(объявленный, max(1,5 × наибольший пик, пол)); иначе
    объявленный. → (ГБ, пояснение — пусто, если порог не изменился)."""
    c = _counted(_peaks(d) if rows is None else rows, typ)
    if len(c) < 3:
        return declared, ''
    peak = max(r['peak_gb'] for r in c)
    eff = min(declared, max(1.5 * peak, _env_f('HEAVY_SLOT_EFF_FLOOR_GB', 0.5)))
    if eff >= declared:
        return declared, ''
    return eff, f'порог по замеру: объявлен {declared:g}, тип {typ}, замеров {len(c)}, наибольший пик {peak:.2f} ГБ → {eff:.2f}'


def _record(d: str, typ: str, label: str, peak: float, peak_rss: float, hold: float, declared: float, eff: float) -> None:
    p = _peaks_path(d)
    try:
        new = not os.path.exists(p)
        with open(p, 'a', encoding='utf-8') as f:
            if new:
                f.write('\t'.join(_PEAK_COLS) + '\n')
            f.write('\t'.join([time.strftime('%Y-%m-%d %H:%M:%S'), typ, label, f'{peak:.3f}', f'{peak_rss:.3f}',
                               f'{hold:.1f}', f'{declared:g}', f'{eff:.3f}']) + '\n')
    except OSError as e:
        sys.stderr.write(f'heavy-slot: замер не записан ({e.__class__.__name__})\n')


class _Meter(threading.Thread):
    """Замер памяти дерева держателя раз в `every` с; WARN в журнал при держании дольше `long_s`."""

    def __init__(self, label: str, pid: int, every: float, long_s: float):
        super().__init__(daemon=True)
        self.label, self.pid, self.every, self.long_s = label, pid, every, long_s
        self.peak, self.peak_rss, self.t0, self.warned = 0.0, 0.0, time.time(), False
        self._stop_ev = threading.Event()

    def sample(self) -> None:
        with contextlib.suppress(Exception):          # замер не должен ронять прогон
            a, b = tree_mem(self.pid, self.label)
            self.peak, self.peak_rss = max(self.peak, a), max(self.peak_rss, b)

    def run(self) -> None:
        while True:
            self.sample()
            held = time.time() - self.t0
            if not self.warned and held > self.long_s:
                self.warned = True
                log(self.label, f'WARN: держит слот дольше {self.long_s / 60:g} мин ({_sec(held)} с), '
                                f'пик памяти дерева пока {self.peak:.2f} ГБ')
            if self._stop_ev.wait(self.every):
                return

    def stop(self) -> tuple[float, float]:
        self._stop_ev.set()
        self.join(timeout=5)
        self.sample()
        return self.peak, self.peak_rss


# ---------------------------------------------------------------- допуск по памяти (T-74: без двойного счёта)

def _holders_need(d: str, k: int, n: int) -> tuple[float, str, bool]:
    """Сколько ещё памяти могут взять ДРУГИЕ держатели (кроме слота k): Σ max(порог_h − память_h, 0) → (ГБ, пояснение,
    есть ли держатели). Порог — эффективный (`eff_gb`, у старой версии — `min_gb`); память — PSS дерева держателя сейчас:
    она уже вычтена из MemAvailable, второй раз не считается. Порог не прочитан — бесконечность (ждать тот слот)."""
    total, parts = 0.0, []
    for j in range(1, n + 1):
        if j == k or not is_held(j):
            continue
        h = _read_kv(_holder_file(d, j)) or {}
        try:
            th = float(h.get('eff_gb') or h['min_gb'])
        except (KeyError, ValueError):
            return float('inf'), f'порог держателя слота {j} не прочитан', True
        try:
            pid = int(h.get('pid', 0))
        except ValueError:
            pid = 0
        used = tree_mem(pid, h.get('label', ''))[0] if h.get('stage') == 'работает' else 0.0
        part = max(th - used, 0.0)
        total += part
        parts.append(f"{h.get('label', '?')} {th:g}−{used:.1f}={part:.1f}")
    return total, ('держатели ' + ' + '.join(parts)) if parts else '', bool(parts)


def _need(d: str, k: int, own: float, n: int) -> tuple[bool, str, float]:
    """Допуск держателя слота k: MemAvailable ≥ Σ по другим max(порог_h − память_h, 0) + свой порог + запас.
    Сторож: MemAvailable < запаса — нет при любом пороге (идущих не трогаем). → (да/нет, пояснение, свободно ГБ)."""
    free, res = mem_available_gb(), reserve_gb()
    if free < res:
        return False, f'сторож: свободно {free:.1f} ГБ < запаса {res:.1f} — новых не пускаю', free
    others, why, _ = _holders_need(d, k, n)
    ok = free >= others + own + res
    return ok, (f"свободно {free:.1f} ГБ {'≥' if ok else '<'} свой {own:g}" + (f' + {why}' if why else '')
                + f' + запас {res:.1f}'), free


def _admit(d: str, k: int, own: float, n: int) -> tuple[bool, str, float]:
    """Можно ли занять только что взятый слот k ≥ 2: только при занятом другом слоте и по допуску `_need` ПО ФАКТУ сейчас
    (ждать память в дополнительном слоте нельзя — стартует сразу)."""
    if not any(is_held(j) for j in range(1, n + 1) if j != k):
        return False, 'другие слоты свободны', 0.0
    return _need(d, k, own, n)


@contextlib.contextmanager
def heavy_slot(label: str, min_gb: float = 6.0, timeout: float | None = None, no_slot: bool = False,
               poll: float | None = None, report: float | None = None, say=None, cmd: str = '',
               yield_after: float | None = None, max_yields: int | None = None):
    """Взять общую очередь, дождаться памяти по допуску (`_need`: свой порог + доля других держателей + запас), выполнить
    тело, отпустить (пик памяти дерева и время — в журнал и `peaks.tsv`). → info: waited_s, free_gb, fd, eff_gb.
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
    typ = task_type(label)
    own, eff_why = eff_threshold(d, typ, min_gb)
    if eff_why:
        note(eff_why)
    me = {'label': label, 'pid': os.getpid(), 'since': int(t0), 'min_gb': min_gb, 'eff_gb': round(own, 3), 'type': typ,
          'cmd': cmd[:300]}
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
            ok, why, free_k = _admit(d, k, own, n)
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
            last, yielded = -1e9, False
            ok, why, free = _need(d, 1, own, n)
            while not ok:
                if time.time() - last >= report:
                    note(f'держит очередь, ждёт память: {why} (опрос раз в {poll:g} с; живое демо важнее)')
                    last = time.time()
                if timeout is not None and time.time() - t0 >= timeout:
                    note(f'не дождался памяти за {round(time.time() - t0)} с (--timeout {timeout:g}) — не запускаю')
                    raise SlotTimeout(label)
                if time.time() - t_mem >= yield_s:
                    w = _fits_now(d, os.getpid(), free, _holders_need(d, 1, n)[0]) if yields < max_y else None
                    if w:
                        yields += 1
                        note(f"уступил очередь: ждал память {_sec(time.time() - t_mem)} с, {why}; "
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
                ok, why, free = _need(d, 1, own, n)
            if not yielded:
                break
        waited = time.time() - t0
        if slot == 1:
            _write_kv(holder_p, dict(me, since=int(time.time()), stage='работает', free_gb=round(free, 1), yields=yields))
        note(f'взял: ждал {_sec(waited)} с (очередь {_sec(t_lock)}, память {_sec(waited - t_lock)}), свободно {free:.1f} ГБ'
             + (f', уступок {yields}' if yields else '') + (f'; слот {slot}: {extra_why}' if slot > 1 else ''))
        info.update(waited_s=round(waited, 1), free_gb=free, fd=fd, yields=yields, eff_gb=own)
        old = os.environ.get('HEAVY_SLOT_HELD')
        os.environ['HEAVY_SLOT_HELD'] = str(os.getpid())
        long_s = _env_f('HEAVY_SLOT_LONG_S', 2700)
        meter = _Meter(label, os.getpid(), max(0.05, _env_f('HEAVY_SLOT_SAMPLE', 5)), long_s)
        meter.start()
        t_run = time.time()
        try:
            yield info
        finally:
            if old is None:
                os.environ.pop('HEAVY_SLOT_HELD', None)
            else:
                os.environ['HEAVY_SLOT_HELD'] = old
            peak, peak_rss = meter.stop()
            hold = time.time() - t_run
            log(label, f'отпустил: держал {_sec(hold)} с; пик памяти дерева {peak:.2f} ГБ (RSS {peak_rss:.2f}), тип {typ}, '
                       f'порог {min_gb:g}' + (f' (по замеру {own:.2f})' if own < min_gb else '')
                + (f'; WARN: держание дольше {long_s / 60:g} мин' if hold > long_s else ''))
            _record(d, typ, label, peak, peak_rss, hold, min_gb, own)
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
            eff = h.get('eff_gb')
            eff_s = f" (по замеру {float(eff):.2f})" if eff and float(eff) < float(h.get('min_gb') or 0) else ''
            pr(f"ДЕРЖИТ: {h['label']} · pid {h['pid']} · {h.get('stage', '?')} {_ago(h.get('since'))} · порог {h.get('min_gb')} ГБ"
               + eff_s + (f" · уступок {h['yields']}" if h.get('yields') not in (None, '0') else '') + tag)
            a, b = tree_mem(int(h['pid']), h['label'])
            pr(f"  процесс: {_proc(int(h['pid']))}")
            pr(f"  память дерева сейчас: {a:.2f} ГБ (RSS {b:.2f})")
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
        res = reserve_gb()
        line = (f'СЛОТОВ: {n} (дополнительный — только пока занят другой и свободно ≥ Σ держателей max(порог − память, 0)'
                f' + свой + запас {res:.1f} ГБ; иначе по одному)')
        with contextlib.suppress(OSError, RuntimeError):
            others = _holders_need(d, 0, n)[0]
            if any_held and others != float('inf'):
                line += f'\n  сейчас: держатели могут взять ещё {others:.1f} ГБ → войдёт задача с порогом до ' \
                        f'{max(mem_available_gb() - others - res, 0):.1f} ГБ'
        pr(line)
    pr(f'журнал: {log_path()} · замеры: {_peaks_path(d)} (сводка — --stats)')
    return 0


def stats(out=sys.stdout) -> int:
    """Сводка замеров по типу задачи: сколько, пик памяти дерева, держание, объявленный и эффективный порог."""
    d = os.path.dirname(_lock_file())
    rows = _peaks(d)
    pr = lambda s: print(s, file=out)  # noqa: E731
    if not rows:
        pr(f'замеров нет: {_peaks_path(d)} (пишутся при отпускании слота)')
        return 0
    long_s = _env_f('HEAVY_SLOT_LONG_S', 2700)
    pr(f'ЗАМЕРЫ: {len(rows)} ({rows[0]["ts"]} … {rows[-1]["ts"]}) · {_peaks_path(d)}')
    pr('тип        замеров(засч.)  пик ГБ  RSS ГБ  держание сред/макс, мин  порог объявл. → эфф.  метки')
    for typ in sorted({r['type'] for r in rows}):
        rs = [r for r in rows if r['type'] == typ]
        c = _counted(rows, typ)
        holds = sorted(r['hold_s'] for r in rs)
        decl = rs[-1]['min_gb']
        eff, _ = eff_threshold(d, typ, decl, rows)
        labels = sorted({r['label'] for r in rs})
        pr(f"{typ:<10} {len(rs):>4} ({len(c):>2})     {max(r['peak_gb'] for r in rs):>6.2f}  "
           f"{max(r['peak_rss_gb'] for r in rs):>6.2f}  {holds[len(holds) // 2] / 60:>8.1f} / {holds[-1] / 60:<6.1f}"
           f"        {decl:>5g} → {eff:<5.2f}{'' if len(c) >= 3 else ' (мало замеров)'}  "
           f"{', '.join(labels[:4])}{' …' if len(labels) > 4 else ''}")
    lg = [r for r in rows if r['hold_s'] > long_s]
    if lg:
        pr(f'ДОЛГИЕ (> {long_s / 60:g} мин): ' + '; '.join(f"{r['label']} {r['hold_s'] / 60:.0f} мин ({r['ts']})" for r in lg[-10:]))
    return 0


def run(argv: list) -> int:
    """`<метка> [--min-gb N] [--timeout S] [--no-slot] -- <команда…>` → rc команды (124 — не дождался)."""
    if '--' not in argv or argv.index('--') < 1 or argv.index('--') == len(argv) - 1:
        print('heavy-slot: <метка> [--min-gb N] [--timeout S] [--no-slot] -- <команда…> | --status | --stats', file=sys.stderr)
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
    if argv[:1] == ['--stats']:
        return stats()
    return run(argv)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
