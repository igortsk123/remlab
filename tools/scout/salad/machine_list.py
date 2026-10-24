#!/usr/bin/env python3
"""Список физических машин Salad (`machine_id`) с TTL: какая молчит по SSH и сколько раз её быстро пересадили
(план mesh-17 п.А/п.6, T-20261024-01).

Почему отдельно от `node_health`: тот считает ИНСТАНСЫ, а инстанс живёт одну выдачу — после вытеснения или пересадки
Salad заводит новый `instance_id`. Молчание же — свойство машины: ночь 23→24.10 из 50 машин с ≥ 2 прогретыми
инстансами 43 вели себя каждый раз одинаково, 44 машины не ответили ни разу (до 6 выдач подряд). Узнать «эта машина
уже молчала» можно только по `machine_id`.

Состояние — `~/scout-scenes/mesh-machines.json` (`MESH_MACHINES`) под flock, как у `node_health`:
  {machine_id: {silent_at, answered_at, fast: [время быстрой пересадки, …], gpu, last_instance}}
Запись старше `MESH_MACHINE_TTL_H` (24 ч) забывается: машина могла смениться хозяином или починиться.
"""
from __future__ import annotations

import fcntl
import json
import os
import time

STATE = os.path.expanduser(os.environ.get('MESH_MACHINES', '~/scout-scenes/mesh-machines.json'))
TTL_S = float(os.environ.get('MESH_MACHINE_TTL_H', '24')) * 3600
# Быстрых пересадок одной машины (мимо общего лимита 6/ч) — не больше стольких за TTL, затем пауза: дальше машина
# идёт обычным путём (порог молчания + общий бюджет). Защита от бесконечной чехарды, если Salad отдаёт её снова и снова.
FAST_MAX = int(os.environ.get('MESH_FAST_REALLOC_MAX', '2'))


class _State:
    def __enter__(self) -> dict:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        self.fh = open(STATE + '.lock', 'a+')
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        try:
            with open(STATE, encoding='utf-8') as f:
                self.st = json.load(f)
        except Exception:  # noqa: BLE001 — нет файла или битый: начинаем с чистого, список — подсказка, не истина
            self.st = {}
        return self.st

    def __exit__(self, *exc) -> None:
        try:
            now = time.time()
            keep = {}
            for k, v in self.st.items():
                v['fast'] = [t for t in v.get('fast') or [] if now - t < TTL_S]
                if max([v.get('silent_at') or 0, v.get('answered_at') or 0, *v['fast']]) > now - TTL_S:
                    keep[k] = v
            tmp = f'{STATE}.{os.getpid()}.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(keep, f, ensure_ascii=False)
            os.replace(tmp, STATE)
        except Exception as e:  # noqa: BLE001 — учёт машин не должен ронять прогон
            print(f'  список машин: не сохранил ({type(e).__name__}: {str(e)[:60]})', flush=True)
        finally:
            fcntl.flock(self.fh, fcntl.LOCK_UN)
            self.fh.close()


def mark_silent(machine: str | None, instance: str = '', gpu: str | None = None) -> None:
    """Машина прогрелась (или должна была), а SSH-проба молчит дольше порога, при том что другие машины в том же круге
    отвечали — значит дело в машине, а не в нас."""
    if not machine:
        return
    with _State() as st:
        m = st.setdefault(machine, {})
        m['silent_at'] = time.time()
        m['last_instance'] = instance
        m['gpu'] = gpu or m.get('gpu')


def mark_answered(machine: str | None) -> None:
    """Ответила — признак «молчит» снимается: на этой выдаче шлюз до неё достаёт."""
    if not machine:
        return
    with _State() as st:
        m = st.setdefault(machine, {})
        m['answered_at'] = time.time()
        m.pop('silent_at', None)


def is_silent(machine: str | None) -> bool:
    if not machine:
        return False
    with _State() as st:
        return bool((st.get(machine) or {}).get('silent_at'))


def take_fast(machine: str | None) -> bool:
    """Разрешить быструю пересадку уже молчавшей машины (мимо общего лимита) и учесть её. False — лимит этой машины
    исчерпан (пауза до TTL) или машина не молчала."""
    if not machine:
        return False
    now = time.time()
    with _State() as st:
        m = st.get(machine) or {}
        fast = [t for t in m.get('fast') or [] if now - t < TTL_S]
        if not m.get('silent_at') or len(fast) >= FAST_MAX:
            return False
        m['fast'] = fast + [now]
        st[machine] = m
        return True


def silent_list() -> list[dict]:
    """Молчащие машины для отчёта: machine_id, класс карты, сколько раз быстро пересажены."""
    with _State() as st:
        return [{'machine': k, 'gpu': v.get('gpu'), 'fast': len(v.get('fast') or []),
                 'silent_at': round(v['silent_at'])} for k, v in st.items() if v.get('silent_at')]


if __name__ == '__main__':
    print(json.dumps(silent_list(), ensure_ascii=False, indent=1))
