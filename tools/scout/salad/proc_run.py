#!/usr/bin/env python3
"""Запуск шага-подпроцесса, который по таймауту НЕ оставляет сирот.

ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ. Дефект 05.09: шаги конвейера запускались через
`subprocess.run(shell=True, timeout=...)`. По таймауту Python убивает только прямого потомка —
оболочку `/bin/sh -c '...'`. Настоящая работа (`python topview_render.py` внутри shell-цикла)
оставалась жить с `ppid=1` навсегда. Пост-разбор идёт каждые `MESH_POST_EVERY_S`, поэтому сироты
копились: к 10:00 05.09 их было 20 штук, старейшая работала 21 ч 44 мин. Цена — съеденная память
дев-машины (trimesh её не отдаёт, урок 391) и блокировка перезапуска: новый конвейер честно ждёт
сирот (`batch_show.wait_orphans`), а арендованные ноды всё это время оплачиваются.

Тот же дефект был в `ssh_run.sink_relief` — поэтому запуск живёт ОДНИМ местом на оба вызова.

УСТРОЙСТВО.
- `start_new_session=True` кладёт шаг в СВОЮ сессию и группу процессов (pgid == pid потомка):
  сигнал группе не может задеть ни конвейер, ни харнесс агента.
- Эскалация считается по ЖИЗНИ ГРУППЫ, а не по смерти оболочки. Первый вариант правки проверял
  `p.wait()` — оболочка честно умирала от SIGTERM, код выходил довольным, а упрямый внук жил
  дальше, то есть утечка воспроизводилась ровно в том месте, которое её чинило (находка Codex).
- Вывод пишется во ВРЕМЕННЫЙ ФАЙЛ, а не в трубы: труба, которую держит недобитый внук, повесила
  бы добор вывода, а `communicate()` по второму таймауту выбросил бы уже накопленное. Плюс не
  держим в памяти вывод сорокаминутного шага на машине с 11 ГБ.

Что этим НЕ ловится: потомок, сделавший СОБСТВЕННЫЙ `setsid()` — он уходит из группы. Для
абсолютной гарантии нужен cgroup/systemd scope; среди наших шагов таких потомков нет
(python/rsync/ssh сами не демонизируются), проверять — при добавлении новых шагов.
"""
import os
import signal
import subprocess
import tempfile
import time

TAIL = 1500          # сколько символов вывода отдаём наверх (в лог идёт хвост)
GRACE_S = 10.0       # сколько ждём после SIGTERM, прежде чем бить SIGKILL


def group_alive(pgid: int) -> bool:
    """Жива ли ГРУППА процессов (а не конкретный процесс)."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True      # группа существует, просто не наша — считать мёртвой нельзя
    return True


def kill_group(p: subprocess.Popen, grace: float = GRACE_S, step: float = 0.2) -> str:
    """Снять всю группу процессов шага. Возвращает, чем именно снялось (для лога)."""
    try:
        pgid = os.getpgid(p.pid)
    except (ProcessLookupError, PermissionError):
        pgid = -1
    if pgid <= 0 or pgid == os.getpgid(0):
        # изоляция не сработала (шаг остался в нашей группе) — бить группу НЕЛЬЗЯ, заденем
        # сам конвейер; бьём только процесс и честно говорим, что сироты возможны
        try:
            p.kill()
            p.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return 'без группы — возможны сироты'
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return 'ушёл сам'
    deadline = time.time() + grace
    while time.time() < deadline:
        if p.returncode is None:
            try:
                p.wait(timeout=step)   # снимаем зомби оболочки: иначе группа «жива» из-за него
            except subprocess.TimeoutExpired:
                pass
        else:
            time.sleep(step)
        if p.returncode is not None and not group_alive(pgid):
            return 'SIGTERM'
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    return 'SIGKILL' if not group_alive(pgid) else 'SIGKILL, группа не сдалась'


def run_step(cmd: str, timeout: float = 3600, tail: int = TAIL,
             grace: float = GRACE_S) -> tuple[int, str]:
    """Выполнить команду оболочки. → (код возврата, хвост вывода). Таймаут = код 124.

    Исключение НЕ поднимается: у вызывающего (`batch_show`) на исходе шага висит `finale()`,
    который гасит группы Salad. Упасть здесь значит оставить ноды тарифицироваться.
    """
    with tempfile.TemporaryFile('w+', encoding='utf-8', errors='replace') as f:
        p = subprocess.Popen(cmd, shell=True, stdout=f, stderr=subprocess.STDOUT,
                             start_new_session=True)
        note = ''
        try:
            p.wait(timeout=timeout)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            how = kill_group(p, grace)
            rc, note = 124, f'ТАЙМАУТ {timeout:.0f}с ({how}): {cmd[:120]}\n'
        try:
            f.seek(0)
            out = f.read()[-tail:]
        except (OSError, ValueError):
            out = ''
    return rc, note + out
