#!/usr/bin/env python3
"""СТОРОЖ МЕСТА ПЕРЕД СТАРТОМ ТЯЖЁЛОГО/ПЛАТНОГО (T-20261123-35; владелец TG 2227/2230, P-072 «Диск pakardev»).

ЗАЧЕМ. 23.11 диск pakardev дошёл до 100 % (0 свободно): платный прогон 09 упал на записи `check.json` и `run_summary.tsv` («No space left on
device»), часть результатов потеряна, а заплачено уже было. Теперь свободно на `/` меньше порога — тяжёлое и платное НЕ СТАРТУЕТ.

ГДЕ СТОИТ. Один вход `check()`; зовут: `heavy-slot` (`tools/ops/heavy_slot.py`: и обёртка `heavy-slot.sh`, и `with heavy_slot(...)` — rc 3 / `DiskLow`),
`kit_driver.require_slot` (платная проба Salad/RunPod: stage_trial, loop5, sg_salad, runpod_trial), CLI ниже — для стартовых скриптов.
ПОРОГ — `tools/scout/rules/dev-disk.json` → `start_min_free_gb` (15), путь замера `start_guard_path` (`/`), не чаще одного ❗ в Telegram за
`alert_every_min` (30) минут. Нет файла правил/ключа — запасные те же числа.
ЧТО ПРИ ОТКАЗЕ. Строка ❗ — в журнал (`~/remlab-logs/disk-guard.log`; запись не получилась — молча дальше, диск и есть полон), в stderr стартовавшего и в Telegram
через ТОТ ЖЕ канал, что ❗ красного CI (`tools/scout/alert.sh`, ключи `.env.alert` вне git). Код возврата 3.
ОТКЛЮЧИТЬ можно только осознанно: `DISK_GUARD=0` в окружении команды (уборка диска сама, ночной перенос на HDD) — в журнал пишется строка «сторож выключен».

  python3 tools/ops/disk_guard.py [--label МЕТКА] [--quiet]    # rc 0 — места хватает, 3 — отказ (с ❗)
  python3 tools/ops/disk_guard.py --status                       # свободно, порог, rc 0
Переопределения для проверки: DISK_GUARD_RULES (файл правил), DISK_GUARD_STATE (папка состояния), DISK_GUARD_LOG (файл журнала), DISK_GUARD_ALERT (скрипт оповещения)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
RULES_PATH = os.path.join(ROOT, 'tools', 'scout', 'rules', 'dev-disk.json')
ALERT = os.path.join(ROOT, 'tools', 'scout', 'alert.sh')
DEFAULTS = {'start_min_free_gb': 15.0, 'start_guard_path': '/', 'alert_every_min': 30}
GB = 1024 ** 3


class DiskLow(RuntimeError):
    """Свободного места меньше порога — тяжёлое/платное не стартует."""


def rules() -> dict:
    p = os.environ.get('DISK_GUARD_RULES') or RULES_PATH
    try:
        with open(p, encoding='utf-8') as f:
            r = json.load(f)
    except (OSError, ValueError):
        r = {}
    return {k: r.get(k, v) for k, v in DEFAULTS.items()}


def free_gb(path: str = '/') -> float:
    return shutil.disk_usage(path).free / GB


def _state_dir() -> str:
    return os.environ.get('DISK_GUARD_STATE') or os.path.expanduser('~/.local/state/disk-guard')


def _journal(text: str) -> None:
    p = os.environ.get('DISK_GUARD_LOG') or os.path.expanduser('~/remlab-logs/disk-guard.log')
    try:
        with open(p, 'a', encoding='utf-8') as f:
            f.write(f'{time.strftime("%F %T")} {text}\n')
    except OSError:
        pass                                                     # диск полон — журнал не обязан получиться, отказ всё равно идёт в stderr и TG


def _alert_due(every_min: float, now: float) -> bool:
    """Не чаще одного ❗ за every_min минут (очередь из десятков отказавших стартов не должна спамить Telegram)."""
    p = os.path.join(_state_dir(), 'last-alert')
    try:
        last = float(open(p).read().strip())
    except (OSError, ValueError):
        last = None                                              # ни разу не слали — ❗ положено
    if last is not None and now - last < every_min * 60:
        return False
    try:
        os.makedirs(_state_dir(), exist_ok=True)
        with open(p, 'w') as f:
            f.write(f'{now:.0f}')
    except OSError:
        pass                                                     # состояние не записалось — лучше повторить ❗, чем промолчать
    return True


def _send_tg(text: str) -> bool:
    """Тот же канал, что у ❗ красного CI (`ci_watch.Real.tg`): `tools/scout/alert.sh` — 0 доставлено, 2 не настроен, 1 не ответил."""
    script = os.environ.get('DISK_GUARD_ALERT') or ALERT
    try:
        return subprocess.run(['bash', script, text], capture_output=True, text=True, timeout=240).returncode in (0, 2)
    except (OSError, subprocess.SubprocessError):
        return False


def check(label: str = '', free_fn=None, notify=None, now: float | None = None) -> tuple[bool, str]:
    """(можно ли стартовать, сообщение). Свободно < порога → (False, «❗ …»), строка уже записана в журнал и (с ограничением частоты) ушла в Telegram.
    `free_fn(path)->ГБ` и `notify(text)->bool` подменяются в тестах."""
    if os.environ.get('DISK_GUARD') == '0':
        _journal(f'сторож места выключен (DISK_GUARD=0): {label or "—"}')
        return True, 'сторож места выключен (DISK_GUARD=0)'
    r = rules()
    path, thr = str(r['start_guard_path']), float(r['start_min_free_gb'])
    try:
        free = (free_fn or free_gb)(path)
    except OSError as e:
        msg = f'❗ диск: не удалось узнать свободное место на {path} ({e}) — {label or "старт"} не запускаю'
        _journal(msg)
        return False, msg
    if free >= thr:
        return True, f'диск: свободно {free:.1f} ГБ на {path} (порог {thr:g})'
    host = os.uname().nodename
    msg = (f'❗ диск {host}: свободно {free:.1f} ГБ на {path} — меньше порога {thr:g} ГБ. {label or "Тяжёлое/платное"} НЕ запущено. '
           f'Освободить место (ночной перенос старых папок на HDD: tools/ops/logs_archive.py), потом повторить.')
    _journal(msg)
    t = time.time() if now is None else now
    if _alert_due(float(r['alert_every_min']), t):
        (notify or _send_tg)(msg)
    return False, msg


def require(label: str = '') -> None:
    ok, msg = check(label)
    if not ok:
        raise DiskLow(msg)


def main(argv: list) -> int:
    if '--status' in argv:
        r = rules()
        print(f'свободно {free_gb(str(r["start_guard_path"])):.1f} ГБ на {r["start_guard_path"]}, порог {float(r["start_min_free_gb"]):g} ГБ')
        return 0
    label = ''
    if '--label' in argv and argv.index('--label') + 1 < len(argv):
        label = argv[argv.index('--label') + 1]
    ok, msg = check(label)
    if not ok:
        print(msg, file=sys.stderr)
        return 3
    if '--quiet' not in argv:
        print(msg)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
