#!/usr/bin/env python3
"""ОБЩАЯ ОЧЕРЕДЬ ТЯЖЁЛЫХ ПРОГОНОВ DEV (T-20261105-57): одно тяжёлое за раз на машину + порог свободной памяти.

ЗАЧЕМ. Ночью 05.11 тяжёлые прогоны (VLM T-36, обход моделей T-51, паритет T-53/T-54, compose2) ждали памяти каждый своим
циклом с разными порогами (6 и 7 ГБ): при 5,5 ГБ стояли все, а освободилось — стартовали вдвоём, и earlyoom снимал
`remlab-render` (живое демо). Здесь — одна очередь: замок `flock` (держит процесс; умер — ядро отпускает само), взявший
очередь ждёт порога памяти и только потом стартует; кто держит и кто ждёт — `--status`, журнал — `~/remlab-logs/heavy-slot.log`.

  tools/ops/heavy-slot.sh <метка> [--min-gb N] [--cores N] [--long|--short] [--timeout S] [--prio 0|1|2] [--no-slot] \
      -- <команда…>                                                                       # rc команды наружу
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
  * ДО ПЯТИ СЛОТОВ (T-57/3 → T-74 → T-20261111-07, владелец 11.11: 5 вместо 3; HEAVY_SLOT_SLOTS, по умолчанию 5; `1` — один
    слот, как до T-57/3; допуск по памяти тот же, меняется только потолок числа держателей): первый слот
    (`slot.lock`, `holder` — общие со старой версией) берёт первый в очереди и ждёт в нём память. Слоты 2…N (`slot<k>.lock`,
    `holder<k>`) — только пока занят другой слот и только если память есть ПО ФАКТУ сейчас: стартует сразу, ждать память в
    дополнительном слоте нельзя. Не хватает — строго по одному, как прежде.
  * ДОПУСК ПО ПАМЯТИ (T-74, без двойного счёта); параллельно с другими держателями:
        MemAvailable ≥ Σ по другим держателям max(порог_h − память_h, 0) + свой порог + запас
    одиночный (других нет) — как до T-74: MemAvailable ≥ свой порог, без запаса (ведущий 06.11);
    память_h — PSS всего дерева процессов держателя сейчас (она уже вычтена из MemAvailable, поэтому из порога держателя
    вычитается — до T-74 порог держателя вычитался целиком второй раз); запас — HEAVY_SLOT_RESERVE_GB (1 ГБ), но не меньше
    10 % MemTotal (earlyoom `-m 10,5` на 10 % шлёт SIGTERM, render первым). СТОРОЖ: MemAvailable < запаса — новых не пускать,
    идущих не трогать (earlyoom остаётся). Держатель первого слота, пока ждёт память, считается целиком (дерево ещё пустое).
  * ЗАМЕР (T-74): пока держит — раз в HEAVY_SLOT_SAMPLE с (5) замер памяти дерева процессов держателя (PSS — доля общих
    страниц: хром из 10 процессов по сумме RSS вышел бы в 2–3 раза больше; RSS пишется рядом); при отпускании — пик и время
    держания в журнал и в `<HEAVY_SLOT_DIR>/peaks.tsv`; сводка — `--stats` (по типу задачи: build, live, cutout, exam,
    parity, иначе метка без номера задачи). Держание дольше HEAVY_SLOT_LONG_S (2700 с = 45 мин) — WARN в журнал.
    Чего замер НЕ видит: память чужих процессов, которые команда только просит (docker exec → postgres в контейнере).
  * ПОРОГ ПО ЗАМЕРУ (T-74; с 1 замера — T-91): есть хоть один засчитанный замер типа (держание ≥ HEAVY_SLOT_MEASURE_MIN_S,
    30 с; последние 10) — эффективный порог = min(объявленный, max(k × наибольший пик, HEAVY_SLOT_EFF_FLOOR_GB 0,5)),
    k = 2,0 при 1–2 замерах (запас на разброс: следующий прогон типа доходил до 1,8× первого пика), 1,5 при 3+; замеров
    нет — объявленный. Им же считается и своё ожидание, и доля держателя у следующих (`eff_gb` в записи держателя).
    ПРЕВЫШЕНИЕ (T-91): держатель в этом прогоне превысил свой порог (замер пишет `peak_gb` в запись держателя) — его доля
    у следующих = max(объявленный, пик прогона) − память сейчас: оценка не сработала, не верим ей до конца прогона.
  * ОБГОН (backfill, T-79): голова очереди не проходит по памяти в свободный дополнительный слот — его берёт СЛЕДУЮЩИЙ ПО
    ПОРЯДКУ, кто проходит сейчас (тот же допуск, что у дополнительного слота: по факту, стартует сразу). Только слоты 2…N и
    только пока слот 1 занят: свободный слот 1 берёт голова, как прежде (у старых версий общий только слот 1 — их не задевает).
    Впереди проходящий (голова любой версии или ожидающий этой версии, `bf=1`) — его очередь, не моя; ожидающий старой версии не
    в голове сам не обгоняет — его не ждём. ЗАЩИТА ГОЛОВЫ: обгон закрыт, пока голова ждёт дольше HEAVY_SLOT_BACKFILL_MIN (мин,
    20; 0 — обгона нет): новые не стартуют, слоты стекают к ней. Ожидание головы — с момента, как она стала первой (метка
    `head` под `queue.lock`; считать от прихода нельзя — задача, простоявшая в хвосте, закрывала бы обгон сразу, ровно в
    заторе 06.11), а у держателя слота 1, ждущего память, — с начала ожидания памяти. Голова ждёт не дольше
    HEAVY_SLOT_BACKFILL_MIN + оставшееся держание тех, кто уже идёт.
  * ПРИОРИТЕТ ИНТЕРАКТИВНЫХ (T-20261109-31): у билета класс `prio` — `--prio N` / `heavy_slot(prio=N)` / переменная
    HEAVY_SLOT_PRIO (её ставит воркер пробы стадиям): 0 — обычный (тесты, меши, сборки), 1 — загрузка тура (человек ждёт
    страницу), 2 — «Обустроить» (агент нажал и смотрит на «подбираем…»). Порядок выдачи — по классу, внутри класса — по
    номеру билета (приходу): голова, обгон, уступка — всё по этому порядку. ПРИОРИТЕТ ОБХОДИТ ТОЛЬКО ОЧЕРЕДЬ: порог памяти,
    допуск в дополнительный слот и сторож — те же; идущих не снимает. Держатель слота 1, который ещё ЖДЁТ ПАМЯТЬ (не
    стартовал), отдаёт слот пришедшему старшего класса сразу (опрос раз в ≤ 1 с) и встаёт в очередь со своим прежним билетом —
    место среди равных за ним; старший ждёт память в слоте так же. ЗАЩИТА ОТ ГОЛОДАНИЯ: билет, ждущий дольше
    HEAVY_SLOT_PRIO_AGE_MIN (мин, 30; 0 — без старения), считается старшим классом — дальше идёт по приходу; поток
    приоритетных не держит обычную задачу больше этого срока (плюс текущие держания). Ожидающий старой версии (без билета)
    и заместитель — класс 0; процесс старой версии классов не знает и сверяет порог только по номерам — до своего
    перезапуска может взять слот раньше приоритетного (переходный период).
  * РЕЗЕРВ ПРОБЫ (T-20261110-29): приоритет обходит только очередь, а 10.11 все три слота по 10 мин держали наши прогоны
    (VLM-тесты T-27/T-26, пик 0,5 ГБ каждый, свободно 15–16 ГБ) — проба агента (11 с, пик 0,15 ГБ) 8 мин падала по таймауту 60 с.
    Поэтому сверх HEAVY_SLOT_SLOTS есть HEAVY_SLOT_PRIO_SLOTS (1) слот(ов) `slot<k>.lock`, которые берут ТОЛЬКО билеты класса ≥ 1;
    допуск — как в дополнительный слот (по памяти по факту, с долями всех держателей и запасом), долю держателя резерва считают все.
    Свободен только резерв — обычные впереди не мешают обгону (он не их), защита головы его не закрывает.
  * ЯДРА (T-20261111-17, владелец TG 1488: 11.11 в 13:55 нагрузка 24 на 15 ядрах — 3D в Playwright ~7 ядер, три регресса
    по -j 3 и ещё два прогона; память была, процессора нет). `--cores N` / `heavy_slot(cores=N)` — сколько ядер займёт задача,
    без ключа CORES_DEFAULT = 2 (старые вызовы: 5 слотов + резерв × 2 = 12 ≤ 15 — пускаются, как раньше). Бюджет —
    HEAVY_SLOT_CORES_BUDGET, иначе `nproc`. Допуск — ДОПОЛНИТЕЛЬНОЕ условие к памяти, везде, где проверяется память (слот 1,
    дополнительный слот, обгон, уступка): Σ ядер других держателей + свои ≤ бюджета. Держатель слота 1, ждущий память/ядра,
    считается целиком — его ядра забронированы, обгоняющие их не займут. ШИРЕ БЮДЖЕТА (N > бюджета) — только одна: в
    дополнительный слот не идёт никогда, ждёт слот 1 и в нём — ухода всех держателей; бронь шире бюджета закрывает старт новым,
    слоты стекают — не ждёт вечно. Класс ≥ 1 (проба агента) бюджет ядер не ждёт (как резерв обходит потолок слотов), его ядра
    другие считают. ОБГОН с ядрами: голова может не проходить по ядрам (7 при занятых 10 из 15) — следующий, кто проходит и по
    памяти, и по ядрам, берёт дополнительный слот; впереди проходящий (по обоим) — его очередь. Голова НЕ держатель слота 1
    ядра не бронирует — мелкие могут обгонять её, пока работает защита 20 мин (как с памятью); стала держателем слота 1 —
    бронь, и обгон уже не отнимает её ядра. `--status` — ядра у каждого держателя и ожидающего, строка ЯДРА (сумма из бюджета,
    нагрузка за 1 мин). Подсказки (`cores_hint`; без --cores обёртка пишет «подсказка: … укажи --cores K»):
        регресс разбора `regress.py run … -j K` → K (без -j — 4, умолчание regress.py);
        pnpm test / vitest / pytest → 3 (замер 11.11: 2,6 ядра в среднем, vitest пускает до nproc − 1 процессов);
        pnpm typecheck → 2 (замер 1,75);
        Playwright с 3D (страница демо/тура, без видеокарты рисует процессор) → 6–7; без 3D — 2.
  * ДОЛГИЕ (T-20261111-17, владелец TG 1490/1491: «работай с тем, что дали, оптимизируй»): `--long` — обёртка после
    взятия слота ставит себе nice +HEAVY_SLOT_LONG_NICE (10), команда наследует: вливания и короткие тесты получают
    процессор первыми. Без ключа долгая — по признаку в команде (`long_auto`): `regress.py`, `playwright`, `pnpm e2e`, скрипт
    js/cjs/mjs/ts/py из команды, который подключает playwright; `--short` — признак не брать. Очередь и допуск долгая не меняет.
    В питоне (`heavy_slot(long=True)`) — только метка: свой процесс обратно не повысить. `--status`: «· долгая, nice 10» —
    nice фактический, из /proc держателя.
Переменные (для самопроверки и особых случаев): HEAVY_SLOT_DIR (замок и состояние, по умолчанию ~/.cache/remlab-heavy-slot —
одинаково в кроне и в сессии, не в репо), HEAVY_SLOT_LOG, HEAVY_SLOT_MEMINFO (подмена /proc/meminfo), HEAVY_SLOT_POLL (с, 30),
HEAVY_SLOT_REPORT (строка «ждёт» в журнал раз в N с, 300), HEAVY_SLOT_YIELD, HEAVY_SLOT_MAX_YIELDS, HEAVY_SLOT_SLOTS,
HEAVY_SLOT_RESERVE_GB, HEAVY_SLOT_HEAD_POLL, HEAVY_SLOT_SAMPLE, HEAVY_SLOT_LONG_S, HEAVY_SLOT_MEASURE_MIN_S,
HEAVY_SLOT_EFF_FLOOR_GB, HEAVY_SLOT_MEM_STUB (файл «метка ГБ» — подмена замера памяти дерева для самопроверки),
HEAVY_SLOT_BACKFILL_MIN, HEAVY_SLOT_PRIO, HEAVY_SLOT_PRIO_AGE_MIN, HEAVY_SLOT_PRIO_SLOTS, HEAVY_SLOT_CORES_BUDGET,
HEAVY_SLOT_LONG_NICE.
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
    """Число слотов (HEAVY_SLOT_SLOTS, по умолчанию 5 — владелец 11.11, T-20261111-07; меньше 1 — 1)."""
    return max(1, int(_env_f('HEAVY_SLOT_SLOTS', 5)))


def prio_slots() -> int:
    """РЕЗЕРВ ПРОБЫ (T-20261110-29): сколько слотов сверх `slots()` берут только билеты класса ≥ 1 (загрузка тура, «Обустроить») —
    HEAVY_SLOT_PRIO_SLOTS, по умолчанию 1; 0 — резерва нет. Допуск в резерв — как в дополнительный слот (по памяти по факту)."""
    return max(0, int(_env_f('HEAVY_SLOT_PRIO_SLOTS', 1)))


def all_slots() -> int:
    """Все слоты: обычные + резерв пробы (его держателей считают все — их доля памяти)."""
    return slots() + prio_slots()


CORES_DEFAULT = 2.0                              # T-20261111-17: столько ядер считает задача без --cores (старые вызовы)


def cores_budget() -> float:
    """Бюджет ядер (T-20261111-17): HEAVY_SLOT_CORES_BUDGET, иначе ядер, доступных процессу (= `nproc`)."""
    v = os.environ.get('HEAVY_SLOT_CORES_BUDGET')
    if v:
        with contextlib.suppress(ValueError):
            return max(float(v), 0.0)
    try:
        return float(len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return float(os.cpu_count() or 1)


def cores_of(kv: dict) -> float:
    """Ядра из записи держателя/билета; нет поля (процесс старой версии) или мусор — CORES_DEFAULT."""
    try:
        return max(float(kv.get('cores') or CORES_DEFAULT), 0.0)
    except (TypeError, ValueError):
        return CORES_DEFAULT


def long_nice() -> int:
    """На сколько понижать приоритет долгой задачи (HEAVY_SLOT_LONG_NICE, 10)."""
    return int(_env_f('HEAVY_SLOT_LONG_NICE', 10))


def _nice_of(pid: int) -> int | None:
    """Фактический nice процесса (поле 19 /proc/pid/stat); нет процесса — None."""
    try:
        with open(f'/proc/{pid}/stat', encoding='utf-8', errors='replace') as f:
            return int(f.read().rsplit(')', 1)[1].split()[16])
    except (OSError, IndexError, ValueError):
        return None


_LONG_RE = re.compile(r'regress\.py|playwright|pnpm\s+(?:run\s+)?e2e')
_SCRIPT_EXT = ('.js', '.cjs', '.mjs', '.ts', '.py')


def _uses_playwright(cmd: list) -> str:
    """Скрипт из команды (первые 8 аргументов с расширением js/cjs/mjs/ts/py) подключает playwright → его имя, иначе ''."""
    for a in cmd[:8]:
        if a.endswith(_SCRIPT_EXT) and os.path.isfile(a):
            with contextlib.suppress(OSError):
                with open(a, encoding='utf-8', errors='replace') as f:
                    if 'playwright' in f.read(262144):
                        return a
    return ''


def long_auto(cmd: list) -> str:
    """Признак долгой задачи по команде (T-20261111-17) → пояснение или '': регресс разбора (`regress.py`), Playwright
    (`playwright`, `pnpm e2e`, скрипт, который подключает playwright)."""
    m = _LONG_RE.search(' '.join(cmd))
    if m:
        return f'в команде «{m.group(0)}»'
    s = _uses_playwright(cmd)
    return f'скрипт {os.path.basename(s)} подключает playwright' if s else ''


def cores_hint(cmd: list) -> tuple[float, str]:
    """Сколько ядер обычно берёт такая команда (подсказка, если --cores не указан) → (ядер, почему); не знаю — (0, '')."""
    s = ' '.join(cmd)
    if 'regress.py' in s:
        m = re.search(r'(?:^|\s)(?:-j\s*|--jobs[\s=])(\d+)', s)
        k = int(m.group(1)) if m else 4
        return float(k), f'регресс разбора -j {k}' + ('' if m else ' (по умолчанию в regress.py)')
    if re.search(r'playwright|pnpm\s+(?:run\s+)?e2e', s) or _uses_playwright(cmd):
        return 6.0, 'Playwright: 3D без видеокарты рисует процессор, 6–7 ядер на страницу'
    if re.search(r'pnpm\s+(?:run\s+)?test\b|vitest|pytest', s):
        # замер 11.11 (нагрузка 10–15): pnpm test — 638 с процессора за 245 с = 2,6 ядра в среднем, но vitest 2 пускает
        # до nproc − 1 = 14 процессов сразу (пик в начале); typecheck — 1,75 ядра (по умолчанию 2 хватает)
        return 3.0, 'pnpm test / vitest / pytest — по замеру 2,6 ядра в среднем, всплеск до 14 процессов'
    return 0.0, ''


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


def _num(x) -> str:
    """Число из записи «как есть» без лишних нулей (6.0 → 6); не число — как есть."""
    try:
        return f'{float(x):g}'
    except (TypeError, ValueError):
        return str(x)


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


def _take_ticket(d: str, me: dict, keep: int | None = None) -> str:
    """Билет в конец очереди: следующий номер из `seq`, файл `wait/<номер>-<pid>`. `keep` — вернуться со СВОИМ прежним номером
    (держатель отдал слот старшему классу, не дождавшись памяти: место среди равных за ним)."""
    with _qlock(d):
        _tickets(d, clean=True)                   # пришедшие раньше без билета — получают его до меня
        n = keep if keep else _next_seq(d)
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


PRIO_MAX = 2                                     # 0 обычный · 1 загрузка тура · 2 «Обустроить» (T-20261109-31)


def prio_clamp(x) -> int:
    """Класс приоритета в границах 0…PRIO_MAX; не число — 0 (обычный)."""
    try:
        return min(max(int(x), 0), PRIO_MAX)
    except (TypeError, ValueError):
        return 0


def prio_env() -> int:
    """Класс по умолчанию — из HEAVY_SLOT_PRIO (ставит воркер пробы своим стадиям); нет — 0."""
    return prio_clamp(os.environ.get('HEAVY_SLOT_PRIO') or 0)


def prio_age_s() -> float:
    """Старение (защита от голодания): ждущий дольше HEAVY_SLOT_PRIO_AGE_MIN (мин, 30) — старший класс; ≤ 0 — без старения."""
    return _env_f('HEAVY_SLOT_PRIO_AGE_MIN', 30) * 60


def _cls(kv: dict, now: float, age: float) -> int:
    """Действующий класс записи: `prio`; ждёт дольше `age` — старший (по `since` — начало ожидания всего вызова: уступка
    и новый билет срок не обнуляют)."""
    p = prio_clamp(kv.get('prio') or 0)
    if age > 0 and p < PRIO_MAX:
        with contextlib.suppress(TypeError, ValueError):
            if now - float(kv.get('since') or now) >= age:
                p = PRIO_MAX
    return p


def _rank(kv: dict, n: int, now: float, age: float) -> tuple:
    """Ключ порядка выдачи: (−класс, номер билета)."""
    return -_cls(kv, now, age), n


def _outranked(d: str, me: dict) -> dict | None:
    """Ожидающий СТАРШЕГО класса, чем мой (держатель слота 1, ещё ждущий память), — ему слот отдаётся сразу (T-20261109-31)."""
    now, age = time.time(), prio_age_s()
    mine = _cls(me, now, age)
    if mine >= PRIO_MAX:
        return None
    for _, _, kv in _tickets(d):
        if str(kv.get('pid')) != str(me.get('pid')) and _cls(kv, now, age) > mine:
            return kv
    return None


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
    now, age = time.time(), prio_age_s()
    out.sort(key=lambda x: _rank(x[2], x[0], now, age))   # порядок выдачи: класс, потом приход (T-20261109-31)
    if clean:
        _mark_head(d, out)
    return out


def _head_path(d: str) -> str:
    return os.path.join(d, 'head')


def _mark_head(d: str, live: list) -> None:
    """Метка «кто первый и с какого момента» (T-79; вызывать под `_qlock`): сменился первый билет — новое время."""
    hp = _head_path(d)
    first = os.path.basename(live[0][1]) if live else ''
    cur = _read_kv(hp) or {}
    if cur.get('ticket') == first:
        return
    if first:
        _write_kv(hp, {'ticket': first, 'since': f'{time.time():.3f}', 'label': live[0][2].get('label', '?')})
    else:
        _unlink(hp)


def backfill_s() -> float:
    """Сколько голова может ждать, пока её обгоняют (HEAVY_SLOT_BACKFILL_MIN, мин, 20) → с; ≤ 0 — обгона нет."""
    return _env_f('HEAVY_SLOT_BACKFILL_MIN', 20) * 60


def _head_wait(d: str, live: list, now: float | None = None) -> tuple[str, float]:
    """Голова и сколько она ждёт головой → (метка, с); головы нет — ('', 0). Голова — первый живой билет (с момента, как
    стал первым: метка `head`) и держатель слота 1, ждущий память (с начала ожидания памяти); из двух — кто ждёт дольше."""
    now = time.time() if now is None else now
    best = ('', 0.0)
    h = _read_kv(_holder_file(d, 1)) or {}
    if h.get('stage') == 'память' and is_held(1):
        with contextlib.suppress(KeyError, ValueError):
            best = (h.get('label', '?'), now - float(h['since']))
    if live:
        m = _read_kv(_head_path(d)) or {}
        t = 0.0
        if m.get('ticket') == os.path.basename(live[0][1]):
            with contextlib.suppress(KeyError, ValueError):
                t = max(now - float(m['since']), 0.0)
        if not best[0] or t > best[1]:
            best = (live[0][2].get('label', '?'), t)
    return best


def _my_turn(d: str, ticket: str) -> bool:
    with _qlock(d):
        live = _tickets(d, clean=True)
    return bool(live) and live[0][1] == ticket


def _fits_now(d: str, ticket_pid: int, room: float, croom: float = float('inf')) -> dict | None:
    """Ожидающий (не я), которому памяти хватает уже сейчас (его порог ≤ room — свободно минус доля других держателей и
    запас, без других — просто свободно; я — держатель слота 1 — уступаю и не считаюсь), — ради него держатель уступает.
    Ядра (T-20261111-17): его ядра ≤ croom (бюджет минус ядра других держателей), класс ≥ 1 бюджет ядер не ждёт."""
    for _, _, kv in _tickets(d):
        try:
            if (int(kv['pid']) != ticket_pid and float(kv.get('eff_gb') or kv.get('min_gb', 1e9)) <= room
                    and (cores_of(kv) <= croom or prio_clamp(kv.get('prio') or 0) >= 1)):
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
    return pid if pid in _ancestors() and any(is_held(k) for k in range(1, all_slots() + 1)) else None


def _noslot_parent() -> int | None:
    """Предок пущен с `--no-slot` (исключение по слову ведущего, T-20261106-97) — вложенные шаги его команды тоже без очереди.
    Признак — `HEAVY_SLOT_NOSLOT` = pid обхода; чужой процесс с тем же env, но не потомок, — ждёт как обычно."""
    try:
        pid = int(os.environ.get('HEAVY_SLOT_NOSLOT', ''))
    except ValueError:
        return None
    return pid if pid in _ancestors() else None


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


def eff_mult(n: int) -> float:
    """Множитель к наибольшему пику по числу засчитанных замеров (T-91): 0 — нет замера; 1–2 — 2,0 (запас на разброс:
    по peaks.tsv 06.11 следующий прогон типа доходил до 1,80× первого пика — gates, 1,53× — build); 3+ — 1,5."""
    return 0.0 if n < 1 else (2.0 if n < 3 else 1.5)


def eff_threshold(d: str, typ: str, declared: float, rows: list | None = None) -> tuple[float, str]:
    """Эффективный порог (T-91: с 1 засчитанного замера типа): min(объявленный, max(k × наибольший пик, пол)), k — `eff_mult`
    (1–2 замера — 2,0; 3+ — 1,5); замеров нет — объявленный. → (ГБ, пояснение — пусто, если порог не изменился)."""
    c = _counted(_peaks(d) if rows is None else rows, typ)
    k = eff_mult(len(c))
    if not k:
        return declared, ''
    peak = max(r['peak_gb'] for r in c)
    eff = min(declared, max(k * peak, _env_f('HEAVY_SLOT_EFF_FLOOR_GB', 0.5)))
    if eff >= declared:
        return declared, ''
    return eff, (f'порог по замеру: объявлен {declared:g}, тип {typ}, замеров {len(c)}, наибольший пик {peak:.2f} ГБ × {k:g} '
                 f'→ {eff:.2f}')


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

    def __init__(self, label: str, pid: int, every: float, long_s: float, holder: str = '', eff: float = 0.0):
        super().__init__(daemon=True)
        self.label, self.pid, self.every, self.long_s = label, pid, every, long_s
        self.peak, self.peak_rss, self.t0, self.warned = 0.0, 0.0, time.time(), False
        self.holder, self.eff, self.told = holder, eff, 0.0
        self._stop_ev = threading.Event()

    def sample(self) -> None:
        with contextlib.suppress(Exception):          # замер не должен ронять прогон
            a, b = tree_mem(self.pid, self.label)
            self.peak, self.peak_rss = max(self.peak, a), max(self.peak_rss, b)
            self.tell()

    def tell(self) -> None:
        """ПРЕВЫШЕНИЕ (T-91): пик прогона выше своего порога — пишу его в запись держателя (`peak_gb`), чтобы другие считали
        мою долю по факту (`_holders_need`). Пишу только при превышении и росте на ≥ 0,05 ГБ — запись редкая."""
        if not self.holder or not self.eff or self.peak <= self.eff or self.peak < self.told + 0.05:
            return
        h = _read_kv(self.holder) or {}
        if h.get('pid') != str(os.getpid()):
            return
        h['peak_gb'] = f'{self.peak:.3f}'
        _write_kv(self.holder, h)
        if not self.told:
            log(self.label, f'WARN: превысил свой порог {self.eff:.2f} ГБ (пик {self.peak:.2f}) — другие считают мою долю '
                            f'по факту, не ниже объявленного')
        self.told = self.peak

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
    она уже вычтена из MemAvailable, второй раз не считается. Порог не прочитан — бесконечность (ждать тот слот).
    ПРЕВЫШЕНИЕ (T-91): пик держателя в этом прогоне (`peak_gb` из записи — пишет его замер, — или память сейчас) выше его
    порога — оценка по замерам для него не сработала: доля считается по факту, не ниже объявленного —
    max(объявленный, пик прогона) − память сейчас (пик выше сейчас — значит, память у него скачет и может вернуться)."""
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
        try:
            peak = max(float(h.get('peak_gb') or 0), used)
        except ValueError:
            peak = used
        over = ''
        if peak > th:
            try:
                decl = float(h.get('min_gb') or th)
            except ValueError:
                decl = th
            th, over = max(decl, peak), f'(превысил: пик {peak:.1f})'
        part = max(th - used, 0.0)
        total += part
        parts.append(f"{h.get('label', '?')}{over} {th:g}−{used:.1f}={part:.1f}")
    return total, ('держатели ' + ' + '.join(parts)) if parts else '', bool(parts)


def _holders_cores(d: str, k: int, n: int, strict: bool = True) -> tuple[float, bool]:
    """Ядра ДРУГИХ держателей (кроме слота k) → (сумма, есть ли держатели). Запись без `cores` (старая версия) —
    CORES_DEFAULT. Замок без записи — чужая ПРОБА слота (ожидающий взял замок на время допуска и отпустит) или новый держатель
    до записи: для допуска (strict) — CORES_DEFAULT, осторожно, как память считает его бесконечным (иначе двое,
    проверяющие одновременно, не видят друг друга); для `--status` (strict=False) — не считается: проба мгновенная, сумма
    показывает только держателей. Держатель слота 1, ещё ждущий память/ядра, считается целиком: его ядра забронированы,
    обгоняющие их не займут (T-20261111-17)."""
    total, any_h = 0.0, False
    for j in range(1, n + 1):
        if j == k or not is_held(j):
            continue
        h = _read_kv(_holder_file(d, j))
        if h is None and not strict:
            continue
        total += cores_of(h or {})
        any_h = True
    return total, any_h


def _cores_ok(d: str, k: int, n: int, cores: float, prio: int) -> tuple[bool, str]:
    """Допуск по ядрам (T-20261111-17), дополнительное условие к памяти: Σ ядер других держателей + свои ≤ бюджета.
    Шире бюджета (свои > бюджета) — только одна: других держателей нет. Класс ≥ 1 (проба агента: секунды, человек ждёт)
    бюджет не ждёт — как резерв пробы обходит потолок слотов; его ядра другие считают. → (да/нет, пояснение)."""
    budget = cores_budget()
    used, any_h = _holders_cores(d, k, n)
    if prio >= 1:
        return True, f'ядра {used:g} + свои {cores:g} из {budget:g} (приоритет {prio} — бюджет ядер не ждёт)'
    if cores > budget:
        return (not any_h), (f'ядра: свои {cores:g} > бюджета {budget:g} — только одна, '
                             + ('других нет' if not any_h else f'жду, пока уйдут держатели (у них {used:g})'))
    ok = used + cores <= budget
    return ok, f"ядра {used:g} + свои {cores:g} {'≤' if ok else '>'} {budget:g}"


def _need(d: str, k: int, own: float, n: int, cores: float = CORES_DEFAULT, prio: int = 0) -> tuple[bool, str, float, str]:
    """Допуск держателя слота k. Параллельно с другими: MemAvailable ≥ Σ по другим max(порог_h − память_h, 0) + свой порог
    + запас. Одиночный (других держателей нет) — как до T-74: MemAvailable ≥ свой порог, без запаса (ведущий 06.11: иначе
    порог 7 при свободных 8 встаёт навсегда). Сторож для всех: MemAvailable < запаса — нового нет при любом пороге
    (идущих не трогаем). И ядра (`_cores_ok`, T-20261111-17). → (да/нет, пояснение, свободно ГБ, чего ждёт: память|ядра)."""
    free, res = mem_available_gb(), reserve_gb()
    if free < res:
        return False, f'сторож: свободно {free:.1f} ГБ < запаса {res:.1f} — новых не пускаю', free, 'память'
    others, why, any_h = _holders_need(d, k, n)
    mok = free >= (others + own + res if any_h else own)
    cok, cwhy = _cores_ok(d, k, n, cores, prio)
    return mok and cok, (f"свободно {free:.1f} ГБ {'≥' if mok else '<'} свой {own:g}"
                         + (f' + {why} + запас {res:.1f}' if any_h else ' (одиночный — без запаса)')
                         + f'; {cwhy}'), free, ('память' if not mok else 'ядра')


def _admit(d: str, k: int, own: float, n: int, cores: float = CORES_DEFAULT, prio: int = 0) -> tuple[bool, str, float]:
    """Можно ли занять только что взятый слот k ≥ 2: только при занятом другом слоте и по допуску `_need` ПО ФАКТУ сейчас
    (ждать память и ядра в дополнительном слоте нельзя — стартует сразу)."""
    if not any(is_held(j) for j in range(1, n + 1) if j != k):
        return False, 'другие слоты свободны', 0.0
    return _need(d, k, own, n, cores, prio)[:3]


@contextlib.contextmanager
def heavy_slot(label: str, min_gb: float = 6.0, timeout: float | None = None, no_slot: bool = False,
               poll: float | None = None, report: float | None = None, say=None, cmd: str = '',
               yield_after: float | None = None, max_yields: int | None = None, prio: int | None = None,
               cores: float | None = None, long: bool = False):
    """Взять общую очередь, дождаться памяти по допуску (`_need`: свой порог + доля других держателей + запас) и ядер
    (`_cores_ok`: Σ ядер держателей + свои ≤ бюджета), выполнить тело, отпустить (пик памяти дерева и время — в журнал и
    `peaks.tsv`). → info: waited_s, free_gb, fd, eff_gb, prio, cores, long. Таймаут (очередь + память) — SlotTimeout.
    `say(msg)` — дублировать строки ожидания в свой журнал. `prio` — класс приоритета 0…2 (None — из HEAVY_SLOT_PRIO):
    меняет только место в очереди, не порог памяти. `cores` — сколько ядер займёт тело (None — CORES_DEFAULT, 2).
    `long` — метка «долгая» в записи держателя; nice ставит только обёртка (`run`): в питоне понизить свой процесс
    обратно нельзя, поэтому `with` приоритет не трогает."""
    poll = _env_f('HEAVY_SLOT_POLL', 30) if poll is None else poll
    report = _env_f('HEAVY_SLOT_REPORT', 300) if report is None else report

    def note(msg):
        log(label, msg)
        if say:
            say(msg)
    pr = prio_env() if prio is None else prio_clamp(prio)
    cores = CORES_DEFAULT if cores is None else max(float(cores), 0.0)
    info = {'label': label, 'waited_s': 0.0, 'free_gb': None, 'fd': None, 'nested': None, 'no_slot': no_slot, 'yields': 0,
            'prio': pr, 'cores': cores, 'long': bool(long)}
    said_starve = False
    free_by = None if no_slot else _noslot_parent()
    if no_slot or free_by:
        if no_slot:
            note('БЕЗ ОЧЕРЕДИ (--no-slot): слот не берётся, порог памяти не ждётся')
        else:
            info['no_slot_parent'] = free_by
            note(f'без очереди по предку pid={free_by} (--no-slot)')
        # признак потомкам: их вложенные вызовы слота тоже идут мимо очереди (иначе шаги команды под --no-slot встают в очередь)
        old = os.environ.get('HEAVY_SLOT_NOSLOT')
        os.environ['HEAVY_SLOT_NOSLOT'] = str(free_by or os.getpid())
        try:
            yield info
        finally:
            if old is None:
                os.environ.pop('HEAVY_SLOT_NOSLOT', None)
            else:
                os.environ['HEAVY_SLOT_NOSLOT'] = old
        return
    parent = _nested()
    if parent:
        info['nested'] = parent
        log(label, f'вложенный вызов: слот уже у предка pid={parent} — не ждём')
        yield info
        return
    # n — все слоты (обычные + резерв пробы): доли памяти держателей и «занят ли другой слот» — по всем; top — до какого слота
    # могу брать я: класс ≥ 1 — и резерв (T-20261110-29), обычный — только `slots()`
    n = all_slots()
    top = n if pr >= 1 else slots()
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
          'bf': 1, 'cmd': cmd[:300], 'prio': pr, 'cores': f'{cores:g}', 'long': int(bool(long))}
    got, ticket, yields, t_lock, extra_why, said_closed = False, None, 0, 0.0, '', False
    keep = None                                       # номер билета, с которым вернуться после уступки старшему классу

    def grab(try_extra: bool) -> int:
        """Первый в очереди: занять слот 1, иначе (раз в step) — второй по памяти. → номер слота, 0 — нет, −1 — я уже не первый.
        «Первый» сверяется раз в step, а старший класс встаёт впереди в любой момент (T-20261109-31): взяв замок, сверяю
        ещё раз под `queue.lock` — не первый → замок назад."""
        nonlocal extra_why
        for k in range(1, top + 1):
            if k > 1 and not try_extra:
                break
            try:
                fcntl.flock(fds[k], fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                continue
            if not _my_turn(d, ticket):
                fcntl.flock(fds[k], fcntl.LOCK_UN)
                return -1
            if k == 1:
                return 1
            ok, why, free_k = _admit(d, k, own, n, cores, pr)
            if ok:
                extra_why = why
                _write_kv(_holder_file(d, k), dict(me, since=int(time.time()), stage='работает', free_gb=round(free_k, 1),
                                                   yields=yields, slot=k))
                return k
            fcntl.flock(fds[k], fcntl.LOCK_UN)
        return 0

    def backfill(tk: str) -> int:
        """ОБГОН (T-79): я не первый; все впереди, кто может взять дополнительный слот, не проходят по памяти, я — проходит:
        беру свободный слот 2…N сразу (как `grab`, ждать память в нём нельзя). Закрыт, пока голова ждёт дольше
        HEAVY_SLOT_BACKFILL_MIN, и пока свободен слот 1 (его берёт голова). РЕЗЕРВ ПРОБЫ (T-20261110-29): свободен только резерв —
        он не слот впереди стоящих обычных (их не ждём, защита головы его не закрывает); ждём только впереди стоящих класса ≥ 1.
        → номер слота или 0."""
        nonlocal extra_why, said_closed
        lim = backfill_s()
        if not is_held(1):
            return 0
        free_k = [k for k in range(2, top + 1) if not is_held(k)]
        res_only = bool(free_k) and all(k > slots() for k in free_k)
        if lim <= 0 and not res_only:
            return 0
        res = reserve_gb()
        if not free_k or mem_available_gb() - res < own:      # дешёвые отсечки до разбора держателей
            return 0
        with _qlock(d):                               # решение и запись держателя — одним шагом против других обгоняющих
            live = _tickets(d)
            pos = next((i for i, x in enumerate(live) if x[1] == tk), -1)
            if pos <= 0:
                return 0
            who, waited = _head_wait(d, live)
            if waited >= lim and not res_only:
                if not said_closed:
                    note(f'обгон закрыт: голова {who} ждёт {waited / 60:.0f} мин (≥ {lim / 60:g}) — новые не стартуют, '
                         f'слоты стекают к ней; жду по очереди')
                    said_closed = True
                return 0
            others = _holders_need(d, 0, n)[0]
            room = mem_available_gb() - others - res
            if own > room:
                return 0
            # ядра (T-20261111-17): обгоняет только тот, кто проходит и по ядрам; впереди проходящий — и по памяти, и по
            # ядрам (класс ≥ 1 бюджет ядер не ждёт; шире бюджета при держателях не проходит никогда — ждёт слот 1)
            croom = cores_budget() - _holders_cores(d, 0, n)[0]
            if pr < 1 and cores > croom:
                return 0
            for i, (_, _, kv) in enumerate(live[:pos]):
                if kv.get('proxy') == '1' or (i > 0 and kv.get('bf') != '1'):
                    continue                          # старая версия не в голове сама не обгоняет — её не ждём
                if res_only and prio_clamp(kv.get('prio') or 0) < 1:
                    continue                          # резерв пробы обычному не достанется — его не ждём
                try:
                    th = float(kv.get('eff_gb') or kv['min_gb'])
                except (KeyError, ValueError):
                    continue
                if th <= room and (cores_of(kv) <= croom or prio_clamp(kv.get('prio') or 0) >= 1):
                    return 0                          # впереди тот, кто проходит, — его очередь
            hd = live[0][2]
            for k in free_k:
                try:
                    fcntl.flock(fds[k], fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                ok, why, free_k_gb = _admit(d, k, own, n, cores, pr)
                if ok:
                    h_th = _num(hd.get('eff_gb') or hd.get('min_gb'))
                    try:
                        h_mem = float(hd.get('eff_gb') or hd.get('min_gb')) <= room
                    except (TypeError, ValueError):
                        h_mem = False
                    blk = (f'ядер {cores_of(hd):g} не проходит: свободно ядер {croom:g} из {cores_budget():g}, '
                           f'место {room:.1f} ГБ' if h_mem else f'порог {h_th} не проходит: место {room:.1f} ГБ')
                    extra_why = (f"обогнал голову {hd.get('label', '?')} ({blk}; "
                                 f"голова ждёт {waited / 60:.0f} мин из {lim / 60:g}); {why}")
                    _write_kv(_holder_file(d, k), dict(me, since=int(time.time()), stage='работает',
                                                       free_gb=round(free_k_gb, 1), yields=yields, slot=k, backfill=1,
                                                       over=hd.get('label', '?')))
                    return k
                fcntl.flock(fds[k], fcntl.LOCK_UN)
        return 0
    try:
        while True:                                   # круг: билет → очередь → слот → память (или уступка → новый билет)
            ticket = _take_ticket(d, dict(me, yields=yields), keep)
            my_n, keep = int(os.path.basename(ticket)[:8]), None
            said, head, t_chk, t_extra, t_bf = False, False, -1e9, -1e9, -1e9
            while True:
                now = time.time()
                if now - t_chk >= step:               # первого не сдвинуть (новые — в конец): сверка раз в step
                    head, t_chk = _my_turn(d, ticket), now
                k = 0
                if head:
                    k = grab(top > 1 and now - t_extra >= step)
                    if top > 1 and now - t_extra >= step:
                        t_extra = now
                    if k < 0:                         # впереди встал старший класс — я больше не первый
                        head, k = False, 0
                elif top > 1 and now - t_bf >= step:  # не первый — обгон в свободный дополнительный слот (T-79)
                    t_bf = now
                    k = backfill(ticket)
                if k:
                    break
                if not said:
                    h = _read_kv(holder_p) or {}
                    note(f"ждёт очередь: держит {h.get('label', '?')} pid={h.get('pid', '?')}, билет {os.path.basename(ticket)}"
                         + (f', приоритет {pr}' if pr else ''))
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
            last, yielded, what0 = -1e9, False, ''
            ok, why, free, what = _need(d, 1, own, n, cores, pr)
            while not ok:
                if time.time() - last >= report or what != what0:
                    note(f'держит очередь, ждёт {what}: {why} (опрос раз в {poll:g} с; '
                         + ('живое демо важнее)' if what == 'память' else 'без толкучки на процессоре)'))
                    last, what0 = time.time(), what
                if timeout is not None and time.time() - t0 >= timeout:
                    note(f'не дождался памяти за {round(time.time() - t0)} с (--timeout {timeout:g}) — не запускаю')
                    raise SlotTimeout(label)
                if time.time() - t_mem >= yield_s:
                    oth, _, any_h = _holders_need(d, 1, n)
                    croom = cores_budget() - _holders_cores(d, 1, n)[0]
                    w = (_fits_now(d, os.getpid(), free - oth - reserve_gb() if any_h else free, croom)
                         if yields < max_y else None)
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
                # пока жду память — слот не мой по праву: пришёл ожидающий старшего класса — отдаю сразу, встаю на своё место
                # (опрос раз в step, память — раз в poll; порог памяти он ждёт так же — обходится только очередь; T-20261109-31)
                t_end, w = time.time() + poll, None
                while True:
                    w = _outranked(d, me)
                    if w or time.time() >= t_end:
                        break
                    time.sleep(min(step, max(t_end - time.time(), 0.0)))
                if w:
                    note(f"отдал слот старшему классу: {w.get('label')} pid={w.get('pid')} (приоритет "
                         f"{_cls(w, time.time(), prio_age_s())}) — сам ждал память {_sec(time.time() - t_mem)} с, {why}; "
                         f"встаю в очередь со своим билетом {my_n}")
                    h = _read_kv(holder_p) or {}
                    if h.get('pid') == str(os.getpid()):
                        _unlink(holder_p)
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    got, yielded, keep = False, True, my_n
                    break
                ok, why, free, what = _need(d, 1, own, n, cores, pr)
            if not yielded:
                break
        waited = time.time() - t0
        if slot == 1:
            _write_kv(holder_p, dict(me, since=int(time.time()), stage='работает', free_gb=round(free, 1), yields=yields))
        note(f'взял: ждал {_sec(waited)} с (очередь {_sec(t_lock)}, память {_sec(waited - t_lock)}), свободно {free:.1f} ГБ'
             + (f', уступок {yields}' if yields else '') + f', ядер {cores:g}' + (', долгая' if long else '')
             + (f', приоритет {pr}' if pr else '')
             + (f'; слот {slot}: {extra_why}' if slot > 1 else ''))
        info.update(waited_s=round(waited, 1), free_gb=free, fd=fd, yields=yields, eff_gb=own, slot=slot)
        old = os.environ.get('HEAVY_SLOT_HELD')
        os.environ['HEAVY_SLOT_HELD'] = str(os.getpid())
        long_s = _env_f('HEAVY_SLOT_LONG_S', 2700)
        meter = _Meter(label, os.getpid(), max(0.05, _env_f('HEAVY_SLOT_SAMPLE', 5)), long_s, holder_p, own)
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


def waiting(min_prio: int = 0) -> int:
    """Сколько живых билетов ждут с объявленным классом ≥ min_prio (T-20261110-29: предохранитель воркера пробы считает только
    свой класс — обычные его не задерживают, задание идёт впереди них и в резерв). min_prio 0 — все, со старой версией без билета."""
    d = os.path.dirname(_lock_file())
    live = _tickets(d)
    if min_prio <= 0:
        proxied = {kv.get('pid') for _, _, kv in live if kv.get('proxy') == '1'}
        w = os.path.join(d, 'wait')
        old = sum(1 for f in os.listdir(w) if f.isdigit() and str(f) not in proxied and _alive(int(f)))
        return len(live) + old
    return sum(1 for _, _, kv in live if kv.get('proxy') != '1' and prio_clamp(kv.get('prio') or 0) >= min_prio)


def status(out=sys.stdout) -> int:
    n = all_slots()
    d = os.path.dirname(_lock_file())
    live = _tickets(d)
    waiters = [dict(kv, ticket=f"{kv.get('ticket')} (за старую версию без билета)") if kv.get('proxy') == '1' else kv
               for _, _, kv in live]                               # по порядку билетов: первый — следующий
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
        tag = (f' · слот {k}' if k > 1 else '') + (' (резерв пробы)' if k > slots() else '')
        if held and h and _alive(int(h.get('pid', 0) or 0)):
            eff = h.get('eff_gb')
            eff_s = f" (по замеру {float(eff):.2f})" if eff and float(eff) < float(h.get('min_gb') or 0) else ''
            if h.get('peak_gb'):
                with contextlib.suppress(ValueError):
                    eff_s += f" · превысил порог: пик {float(h['peak_gb']):.2f} ГБ — доля по факту"
            cpu_s = (f" · ядер {cores_of(h):g}" + (' (старая версия — по умолчанию)' if 'cores' not in h else '')
                     + (f" · долгая, nice {_nice_of(int(h['pid']))}" if h.get('long') == '1' else ''))
            pr(f"ДЕРЖИТ: {h['label']} · pid {h['pid']} · {h.get('stage', '?')} {_ago(h.get('since'))} · порог {h.get('min_gb')} ГБ"
               + eff_s + cpu_s + (f" · уступок {h['yields']}" if h.get('yields') not in (None, '0') else '')
               + (f" · обогнал голову {h.get('over', '?')}" if h.get('backfill') == '1' else '') + tag)
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
    anyp = any(prio_clamp(w.get('prio') or 0) for w in waiters)
    pr(f'ЖДУТ: {len(waiters)}' + ((' (по порядку выдачи: приоритет, потом приход)' if anyp else ' (по порядку прихода)')
                                  if waiters else '')
       + ''.join(f"\n  {k}. {w['label']} · pid {w['pid']} · {w.get('stage')} {_ago(w.get('since'))}"
                 f" · порог {w.get('min_gb')} ГБ · ядер {cores_of(w):g}" + (' · долгая' if w.get('long') == '1' else '')
                 + f" · билет {w.get('ticket')}"
                 + (f" · приоритет {w['prio']}" if prio_clamp(w.get('prio') or 0) else '')
                 + (f" · уступок {w['yields']}" if w.get('yields') not in (None, '0') else '')
                 for k, w in enumerate(waiters, 1))
       + (f'\n  (записей умерших ожидающих: {dead} — не считаются)' if dead else ''))
    if slots() > 1:
        lim, (who, w) = backfill_s(), _head_wait(d, live)
        if lim <= 0:
            pr('ОБГОН: выключен (HEAVY_SLOT_BACKFILL_MIN ≤ 0) — строго по порядку прихода')
        elif who and w >= lim:
            pr(f'ОБГОН: обгон закрыт: голова {who} ждёт {w / 60:.0f} мин (≥ {lim / 60:g}) — новые не стартуют, слоты стекают к ней')
        elif who:
            pr(f'ОБГОН: открыт — голова {who} ждёт {w / 60:.0f} мин из {lim / 60:g}; не проходит по памяти или ядрам — свободный '
               'дополнительный слот берёт следующий, кто проходит')
    try:
        pr(f'ПАМЯТЬ: свободно {mem_available_gb():.1f} ГБ')
    except (OSError, RuntimeError) as e:
        pr(f'ПАМЯТЬ: не прочитать ({e})')
    used, _ = _holders_cores(d, 0, n, strict=False)
    budget = cores_budget()
    try:
        with open('/proc/loadavg', encoding='ascii') as f:
            la = f.read().split()[0]
    except (OSError, IndexError):
        la = '?'
    src = 'HEAVY_SLOT_CORES_BUDGET' if os.environ.get('HEAVY_SLOT_CORES_BUDGET') else 'nproc'
    pr(f'ЯДРА: держатели {used:g} из {budget:g} ({src}; новый ждёт, если держатели + свои > {budget:g}; долгие — nice '
       f'{long_nice()}) · нагрузка за 1 мин {la}')
    if slots() > 1:
        res = reserve_gb()
        line = (f'СЛОТОВ: {slots()} (дополнительный — только пока занят другой и свободно ≥ Σ держателей max(порог − память, 0)'
                f' + свой + запас {res:.1f} ГБ; иначе по одному)'
                + (f' + резерв пробы {prio_slots()} (только приоритет ≥ 1, допуск тот же)' if prio_slots() else ''))
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
    pr('тип        замеров(засч.)  пик ГБ  RSS ГБ  держание сред/макс, мин  порог объявл. → эфф. (множитель)  метки')
    for typ in sorted({r['type'] for r in rows}):
        rs = [r for r in rows if r['type'] == typ]
        c = _counted(rows, typ)
        holds = sorted(r['hold_s'] for r in rs)
        decl = rs[-1]['min_gb']
        eff, _ = eff_threshold(d, typ, decl, rows)
        k = eff_mult(len(c))
        how = ('нет засчитанных' if not k else f'× {k:g}' + (' — 1–2 замера' if k == 2.0 else '')
               + (' ≥ объявл.' if eff >= decl else ''))
        labels = sorted({r['label'] for r in rs})
        pr(f"{typ:<10} {len(rs):>4} ({len(c):>2})     {max(r['peak_gb'] for r in rs):>6.2f}  "
           f"{max(r['peak_rss_gb'] for r in rs):>6.2f}  {holds[len(holds) // 2] / 60:>8.1f} / {holds[-1] / 60:<6.1f}"
           f"        {decl:>5g} → {eff:<5.2f} ({how})  "
           f"{', '.join(labels[:4])}{' …' if len(labels) > 4 else ''}")
    lg = [r for r in rows if r['hold_s'] > long_s]
    if lg:
        pr(f'ДОЛГИЕ (> {long_s / 60:g} мин): ' + '; '.join(f"{r['label']} {r['hold_s'] / 60:.0f} мин ({r['ts']})" for r in lg[-10:]))
    return 0


def child_env() -> dict:
    """Окружение команды: TMPDIR — временная папка на диске, если не задан (T-20261107-13). Тяжёлое (тесты, Playwright/Chromium,
    сборки) писало временное в /tmp — tmpfs с квотой, общий с соседями, и падало EDQUOT. Правило одно —
    `tools/scout/remlab_tmp.py` (REMLAB_TMP → ~/remlab-scratch/tmp → в CI системная); нет помощника — окружение как есть."""
    scout = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scout')
    if scout not in sys.path:
        sys.path.append(scout)                 # в конец: свои модули heavy_slot не подменяются
    try:
        import remlab_tmp
    except ImportError:
        return dict(os.environ)
    return remlab_tmp.child_env()


def run(argv: list) -> int:
    """`<метка> [--min-gb N] [--cores N] [--long|--short] [--timeout S] [--prio 0|1|2] [--no-slot] -- <команда…>` → rc
    команды (124 — не дождался). Долгая (`--long` или по признаку в команде — `long_auto`; `--short` — признак не брать)
    запускается с nice +HEAVY_SLOT_LONG_NICE (10): обёртка понижает себя после взятия слота, команда наследует."""
    use = ('<метка> [--min-gb N] [--cores N] [--long|--short] [--timeout S] [--prio 0|1|2] [--no-slot] -- <команда…> '
           '| --status | --stats')
    if '--' not in argv or argv.index('--') < 1 or argv.index('--') == len(argv) - 1:
        print(f'heavy-slot: {use}', file=sys.stderr)
        return 2
    i = argv.index('--')
    opts, cmd = argv[:i], argv[i + 1:]
    label, opts = opts[0], opts[1:]
    min_gb, timeout, no_slot, prio, cores, long_flag = 6.0, None, False, None, None, None
    k = 0
    while k < len(opts):
        o = opts[k]
        if o == '--prio' and k + 1 < len(opts):
            if opts[k + 1] not in [str(x) for x in range(PRIO_MAX + 1)]:
                print(f'heavy-slot: --prio {opts[k + 1]!r} — нужно 0…{PRIO_MAX}', file=sys.stderr)
                return 2
            prio, k = int(opts[k + 1]), k + 2
        elif o in ('--min-gb', '--timeout', '--cores') and k + 1 < len(opts):
            try:
                v = float(opts[k + 1])
                if o == '--cores' and not 0 <= v < 1e6:
                    raise ValueError
            except ValueError:
                print(f'heavy-slot: {o} {opts[k + 1]!r} — нужно число' + (' ≥ 0' if o == '--cores' else ''), file=sys.stderr)
                return 2
            if o == '--min-gb':
                min_gb = v
            elif o == '--timeout':
                timeout = v
            else:
                cores = v
            k += 2
        elif o in ('--long', '--short'):
            long_flag, k = o == '--long', k + 1
        elif o == '--no-slot':
            no_slot, k = True, k + 1
        else:
            print(f'heavy-slot: неизвестный ключ {o}', file=sys.stderr)
            return 2
    auto = long_auto(cmd) if long_flag is None else ''
    is_long = bool(auto) if long_flag is None else long_flag
    if auto:
        log(label, f'долгая по признаку ({auto}) — пойдёт с nice {long_nice()}; не так — ключ --short')
    if cores is None:
        hk, hwhy = cores_hint(cmd)
        if hk > CORES_DEFAULT:
            msg = f'подсказка: {hwhy} — укажи --cores {hk:g} (без ключа считаю {CORES_DEFAULT:g})'
            log(label, msg)
            print(f'heavy-slot: {label}: {msg}', file=sys.stderr)

    def _term(sig, _frm):
        raise SystemExit(128 + sig)               # чтобы finally убрал записи держателя/ожидающего
    for s in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, _term)
    try:
        with heavy_slot(label, min_gb=min_gb, timeout=timeout, no_slot=no_slot, cmd=' '.join(cmd), prio=prio,
                        cores=cores, long=is_long) as info:
            if is_long and long_nice() > 0:
                try:                              # себя (команда унаследует при запуске): вливания и короткие тесты — первыми
                    os.nice(long_nice())
                except OSError as e:
                    log(label, f'nice не поставился ({e.__class__.__name__}) — иду с обычным приоритетом')
            p = subprocess.Popen(cmd, pass_fds=(info['fd'],) if info['fd'] is not None else (), env=child_env())

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
