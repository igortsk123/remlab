"""Общая очередь товаров и конвейер по товару (T-20261123-34, продолжение): ноды Salad берут товары из общей папки, каждый товар идёт 07→шов→08 на той же ноде без барьера этапов.

Зачем (замер a3, 23.11): прежний драйвер шёл ЭТАПАМИ (все товары ноды 07, потом все шов, потом все 08) и делил товары заранее пополам — хвост (тяжёлый товар 770 с на 07)
держал круг, соседняя нода простаивала. Теперь: очередь `todo/` в общей папке, нода забирает товар, как освободился слот; товар сразу идёт по всей цепочке этапов;
упавший товар (нода перезапустилась, этап отказал) возвращается в очередь для другой ноды (≤ requeue_max раз).

Очередь — файловая (процессы stage_trial разных нод — отдельные; общий замок не нужен: «взять» = атомарный os.rename из todo/ в claimed/<нода>/):
  <dir>/todo/<товар>.json            строка входа stage_trial + служебное `_tries` (сколько раз товар возвращали), `_tried` (ноды, где он падал)
  <dir>/claimed/<нода>/<товар>.json  взят нодой
  <dir>/done/<товар>.json            прошёл все этапы
  <dir>/failed/<товар>.json          окончательный отказ (причина в `_error`)
"""
from __future__ import annotations

import fcntl
import json
import os
import threading
import time
from typing import Callable


def _read(p: str) -> dict:
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def _write(p: str, d: dict) -> None:
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f'{p}.{os.getpid()}.{threading.get_ident()}.tmp'                              # свой временный файл: несколько нод пишут одну строку одновременно (23.11: FileNotFoundError на общем .tmp)
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


class Queue:
    def __init__(self, root: str):
        self.root = root

    def p(self, *a: str) -> str:
        return os.path.join(self.root, *a)

    def fill(self, rows: dict[str, dict]) -> int:
        """Положить товары в очередь (уже лежащие в todo/claimed/done/failed — не трогаем). → сколько добавлено."""
        n = 0
        os.makedirs(self.root, exist_ok=True)
        with open(self.p('.fill.lock'), 'a') as lk:                                    # все ноды наполняют одну очередь на старте — по одной, иначе дубль товара (взят, а в todo записан снова)
            fcntl.flock(lk, fcntl.LOCK_EX)
            for sku, row in rows.items():
                if self.state_of(sku) or self.state_of(sku):                          # второй просмотр: товар мог переехать claimed→todo между проверками
                    continue
                _write(self.p('todo', f'{sku}.json'), {**row, '_tries': 0, '_tried': []})
                n += 1
        return n

    def state_of(self, sku: str) -> str:
        for d in ('todo', 'done', 'failed'):
            if os.path.isfile(self.p(d, f'{sku}.json')):
                return d
        cl = self.p('claimed')
        if os.path.isdir(cl):
            for node in os.listdir(cl):
                if os.path.isfile(os.path.join(cl, node, f'{sku}.json')):
                    return f'claimed/{node}'
        return ''

    def todo(self) -> list[str]:
        d = self.p('todo')
        return sorted(f[:-5] for f in os.listdir(d) if f.endswith('.json')) if os.path.isdir(d) else []

    def claimed_by(self, node: str) -> list[str]:
        d = self.p('claimed', node)
        return sorted(f[:-5] for f in os.listdir(d) if f.endswith('.json')) if os.path.isdir(d) else []

    def claim(self, node: str) -> tuple[str, dict] | None:
        """Взять товар: сперва тот, что эта нода ещё не роняла; гонка двух нод — выигрывает один rename (проигравший пробует следующий)."""
        names = self.todo()
        pref = []
        for sku in names:
            try:
                tried = _read(self.p('todo', f'{sku}.json')).get('_tried') or []
            except (OSError, ValueError):
                continue
            pref.append((node in tried, sku))
        for _, sku in sorted(pref):
            dst = self.p('claimed', node, f'{sku}.json')
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                os.rename(self.p('todo', f'{sku}.json'), dst)
            except OSError:
                continue
            return sku, _read(dst)
        return None

    def release_stale(self, node: str) -> list[str]:
        """Старт процесса ноды: товары, оставшиеся за ней от прошлого (убитого) процесса, — обратно в очередь."""
        back = []
        for sku in self.claimed_by(node):
            src = self.p('claimed', node, f'{sku}.json')
            os.replace(src, self.p('todo', f'{sku}.json'))
            back.append(sku)
        return back

    def finish(self, node: str, sku: str, info: dict | None = None) -> None:
        src = self.p('claimed', node, f'{sku}.json')
        row = _read(src) if os.path.isfile(src) else {}
        _write(self.p('done', f'{sku}.json'), {**row, '_info': info or {}})
        if os.path.isfile(src):
            os.remove(src)

    def fail(self, node: str, sku: str, error: str, requeue_max: int) -> str:
        """Товар упал на ноде: возвращаем в очередь (до requeue_max раз; ноду запоминаем) или окончательный отказ. → 'requeued' | 'failed'."""
        src = self.p('claimed', node, f'{sku}.json')
        row = _read(src) if os.path.isfile(src) else {}
        tries = int(row.get('_tries') or 0) + 1
        row['_tries'] = tries
        row['_tried'] = sorted(set((row.get('_tried') or []) + [node]))
        row['_error'] = error
        if tries <= requeue_max:
            _write(self.p('todo', f'{sku}.json'), row)
            res = 'requeued'
        else:
            _write(self.p('failed', f'{sku}.json'), row)
            res = 'failed'
        if os.path.isfile(src):
            os.remove(src)
        return res

    def counts(self) -> dict:
        def n(d):
            p = self.p(d)
            return sum(1 for f in os.listdir(p) if f.endswith('.json')) if os.path.isdir(p) else 0
        cl = self.p('claimed')
        claimed = sum(len([f for f in os.listdir(os.path.join(cl, x)) if f.endswith('.json')]) for x in os.listdir(cl)) if os.path.isdir(cl) else 0
        return {'todo': n('todo'), 'claimed': claimed, 'done': n('done'), 'failed': n('failed')}


class Chain:
    """Цепочка этапов по товарам одной ноды: ≤ slots товаров в работе, у каждого свой этап. Вызывать step() каждые ~10 с (из poll драйвера)."""

    def __init__(self, queue: Queue, node: str, stages: list[str], slots: int,
                 submit: Callable[[object, str, dict, str, float], tuple[dict | None, dict]],
                 poll: Callable[[object, dict, float], tuple[str, dict]],
                 requeue_max: int = 1, say: Callable[..., None] = print, clock: Callable[[], float] = time.time):
        self.q, self.node, self.stages, self.slots = queue, node, stages, max(1, int(slots))
        self.submit, self.poll, self.requeue_max, self.say, self.clock = submit, poll, requeue_max, say, clock
        self.active: dict[str, dict] = {}          # товар → {row, i (индекс этапа), cur, t0, t_stage}
        self.done: dict[str, dict] = {}            # товар → {seconds, stages: {этап: секунды}}
        self.failed: dict[str, str] = {}
        self.requeued: dict[str, str] = {}
        self.stage_s: dict[str, list[float]] = {}  # этап → секунды по товарам (для замера)
        self.busy_waits = 0

    # --- одна фаза товара
    def _start_stage(self, gw, sku: str, st: dict, t: float) -> bool:
        stage = self.stages[st['i']]
        cur, info = self.submit(gw, sku, st['row'], stage, t)
        if cur is None:
            if info.get('http') == 429:                                                  # нода занята — не провал: ждём, товар остаётся за нодой
                self.busy_waits += 1
                return False
            self._lose(sku, f'этап {stage}: не принят: {str(info)[:200]}')
            return False
        st['cur'], st['t_stage'] = cur, t
        return True

    def _lose(self, sku: str, why: str) -> None:
        self.active.pop(sku, None)
        res = self.q.fail(self.node, sku, why, self.requeue_max)
        if res == 'requeued':
            self.requeued[sku] = why
            self.say(f'товар {sku}: {why} — возвращён в очередь (другая нода или эта же заново)')
        else:
            self.failed[sku] = why
            self.say(f'товар {sku}: {why} — ОТКАЗ окончательный (повторов {self.requeue_max} исчерпано)')

    def step(self, gw, t: float | None = None) -> tuple[str, dict]:
        t = self.clock() if t is None else t
        # 1. продвинуть товары в работе
        for sku in list(self.active):
            st = self.active[sku]
            if st['cur'] is None:                                                      # этап ещё не отправлен (нода отвечала «занято») — пробуем снова
                self._start_stage(gw, sku, st, t)
                continue
            status, info = self.poll(gw, st["cur"], t)
            if status == 'running':
                continue
            stage = self.stages[st['i']]
            if status == 'failed':
                err = ((info.get('items') or {}).get(sku) or {}).get('error') or info.get('error') or info.get('status') or 'failed'
                self._lose(sku, f'этап {stage}: {err}')
                continue
            self.stage_s.setdefault(stage, []).append(round(t - st['t_stage'], 1))
            st.setdefault('stage_s', {})[stage] = round(t - st['t_stage'], 1)
            if st['i'] + 1 >= len(self.stages):
                self.q.finish(self.node, sku, {'stage_s': st['stage_s']})
                self.done[sku] = {'seconds': round(t - st['t0'], 1), 'stage_s': st['stage_s']}
                self.active.pop(sku)
                self.say(f'товар {sku}: все этапы готовы за {t - st["t0"]:.0f} с {st["stage_s"]}')
                continue
            st['i'] += 1
            st['cur'] = None
            self._start_stage(gw, sku, st, t)
        # 2. заполнить свободные слоты
        while len(self.active) < self.slots:
            got = self.q.claim(self.node)
            if got is None:
                break
            sku, row = got
            st = {'row': row, 'i': 0, 'cur': None, 't0': t, 't_stage': t}
            self.active[sku] = st
            self.say(f'товар {sku}: взят из очереди нодой {self.node} (в работе {len(self.active)} из {self.slots}; осталось в очереди {len(self.q.todo())})')
            if not self._start_stage(gw, sku, st, t):
                if sku in self.active and st['cur'] is None:                           # 429: вернуть в очередь без попытки, ждать следующего шага
                    self.active.pop(sku)
                    os.replace(self.q.p('claimed', self.node, f'{sku}.json'), self.q.p('todo', f'{sku}.json'))
                break                                                                  # и при отказе товара — слоты на этом шаге больше не добираем (без горячего цикла)
        # 3. конец: ничего в работе и в очереди пусто
        if not self.active and not self.q.todo():
            ok = len(self.done)
            info = {'ok': ok, 'total': ok + len(self.failed), 'done': self.done, 'failed': self.failed, 'requeued': self.requeued, 'stage_s': self.stage_s,
                    'metrics': {'ok': ok, 'total': ok + len(self.failed), 'failed': dict(self.failed)}}
            return ('done' if ok or not self.failed else 'failed'), info
        return 'running', {}
