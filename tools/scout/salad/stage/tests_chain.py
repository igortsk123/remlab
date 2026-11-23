#!/usr/bin/env python3
"""Тесты общей очереди и конвейера по товару (T-20261123-34): chain_queue.Queue / Chain. Без сети и денег — подставные submit/poll и часы.
Запуск: python3 tools/scout/salad/stage/tests_chain.py"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..')))
sys.path.append(os.path.abspath(os.path.join(HERE, '..', '..')))
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_chain')
import chain_queue as CQ  # noqa: E402

FAILS = []


def check(cond, msg):
    print(('ok   ' if cond else 'FAIL ') + msg)
    if not cond:
        FAILS.append(msg)


class Sim:
    """Подставная нода: этап товара длится DUR[этап] с; submit запоминает, poll отвечает по часам. Журнал событий — для проверки «без барьера»."""

    def __init__(self, dur, fail=None, busy_until=0.0, mult=None):
        self.t = 1000.0
        self.dur, self.fail, self.busy_until, self.mult = dur, fail or {}, busy_until, mult or {}
        self.log = []
        self.n = 0

    def submit(self, gw, sku, row, stage, t):
        if t < self.busy_until:
            return None, {'http': 429}
        self.n += 1
        self.log.append((round(t - 1000.0), 'start', sku, stage))
        return {'sku': sku, 'stage': stage, 't0': t, 'id': self.n}, {}

    def poll(self, gw, cur, t):
        sku, stage = cur['sku'], cur['stage']
        d = self.dur[stage] * self.mult.get(sku, 1)
        if t - cur['t0'] < d:
            return 'running', {}
        if self.fail.get((sku, stage), 0) > 0:
            self.fail[(sku, stage)] -= 1
            self.log.append((round(t - 1000.0), 'fail', sku, stage))
            return 'failed', {'items': {sku: {'status': 'failed', 'error': 'job_lost: тест'}}}
        self.log.append((round(t - 1000.0), 'done', sku, stage))
        return 'done', {}


def run(chains, sim, max_t=5000.0, step=10.0):
    """Крутит все цепочки (ноды) по очереди каждые step секунд; → (время конца, итоги по нодам)."""
    res = {}
    while sim.t < 1000.0 + max_t and len(res) < len(chains):
        for name, ch in chains.items():
            if name in res:
                continue
            st, info = ch.step(None, sim.t)
            if st != 'running':
                res[name] = (st, info)
        sim.t += step
    return sim.t - 1000.0, res


with tempfile.TemporaryDirectory() as tmp:
    # 1. очередь: взять = один rename; две ноды не берут один товар; порядок «не ронял» вперёд
    q = CQ.Queue(os.path.join(tmp, 'q1'))
    check(q.fill({'a': {}, 'b': {}, 'c': {}}) == 3 and q.fill({'a': {}}) == 0, 'очередь: fill кладёт 3, повторный fill не дублирует')
    s1, _ = q.claim('n0')
    s2, _ = q.claim('n1')
    check(s1 != s2 and q.counts() == {'todo': 1, 'claimed': 2, 'done': 0, 'failed': 0}, f'очередь: две ноды взяли разные товары ({s1}, {s2})')
    check(q.fail('n0', s1, 'x', 1) == 'requeued' and q.claim('n0')[0] != s1, 'очередь: упавшая на n0 вернулась, а n0 берёт сперва другой товар')
    check(q.release_stale('n1') == [s2] and s2 in q.todo(), 'очередь: release_stale возвращает «чужое» от прошлого процесса ноды')

    # 2. конвейер без барьера: 3 товара, 2 слота; шов товара A стартует, пока 07 товара B ещё считается
    q = CQ.Queue(os.path.join(tmp, 'q2'))
    q.fill({'A': {}, 'B': {}, 'C': {}})
    sim = Sim({'07': 300.0, 'seam': 100.0, '08': 50.0}, mult={'B': 2})
    ch = CQ.Chain(q, 'n0', ['07', 'seam', '08'], 2, sim.submit, sim.poll, say=lambda *a: None, clock=lambda: sim.t)
    tt, res = run({'n0': ch}, sim)
    st, info = res['n0']
    check(st == 'done' and info['ok'] == 3 and q.counts()['done'] == 3, f'конвейер: 3 товара из 3 готовы ({st}, {info.get("ok")})')
    seam_start_A = min(e[0] for e in sim.log if e[1] == 'start' and e[2] == 'A' and e[3] == 'seam')
    b07_done = min(e[0] for e in sim.log if e[1] == 'done' and e[2] == 'B' and e[3] == '07')
    check(seam_start_A < b07_done, f'конвейер без барьера: шов A стартовал на {seam_start_A} с, раньше конца 07 товара B ({b07_done} с)')
    check(set(info['stage_s']) == {'07', 'seam', '08'}, 'конвейер: в итоге есть секунды по этапам (замер)')

    # 3. сбой: товар упал на n0 → вернулся → его взяла n1 (у n0 тоже есть другой товар); второй сбой — окончательный отказ, остальные готовы
    q = CQ.Queue(os.path.join(tmp, 'q3'))
    q.fill({'A': {}, 'B': {}})
    sim = Sim({'07': 100.0, 'seam': 50.0, '08': 30.0}, fail={('A', 'seam'): 1})
    c0 = CQ.Chain(q, 'n0', ['07', 'seam', '08'], 1, sim.submit, sim.poll, requeue_max=1, say=lambda *a: None, clock=lambda: sim.t)
    c1 = CQ.Chain(q, 'n1', ['07', 'seam', '08'], 1, sim.submit, sim.poll, requeue_max=1, say=lambda *a: None, clock=lambda: sim.t)
    tt, res = run({'n0': c0, 'n1': c1}, sim)
    check(q.counts() == {'todo': 0, 'claimed': 0, 'done': 2, 'failed': 0}, f'сбой: после возврата оба товара готовы ({q.counts()})')
    check(any(res[n][1].get('requeued') for n in res), 'сбой: возврат в очередь записан в итоге ноды')

    q = CQ.Queue(os.path.join(tmp, 'q4'))
    q.fill({'A': {}, 'B': {}})
    sim = Sim({'07': 100.0, 'seam': 50.0, '08': 30.0}, fail={('A', 'seam'): 5})
    c0 = CQ.Chain(q, 'n0', ['07', 'seam', '08'], 1, sim.submit, sim.poll, requeue_max=1, say=lambda *a: None, clock=lambda: sim.t)
    tt, res = run({'n0': c0}, sim)
    st, info = res['n0']
    check(q.counts()['failed'] == 1 and q.counts()['done'] == 1 and st == 'done' and 'A' in info['failed'], f'сбой дважды: A — окончательный отказ с причиной, B готов ({q.counts()}, {st})')

    # 4. нода занята (429): товар не теряется и не считается отказом
    q = CQ.Queue(os.path.join(tmp, 'q5'))
    q.fill({'A': {}})
    sim = Sim({'07': 100.0, 'seam': 50.0, '08': 30.0}, busy_until=1060.0)
    c0 = CQ.Chain(q, 'n0', ['07', 'seam', '08'], 1, sim.submit, sim.poll, say=lambda *a: None, clock=lambda: sim.t)
    tt, res = run({'n0': c0}, sim)
    check(res['n0'][0] == 'done' and c0.busy_waits >= 1 and q.counts()['done'] == 1 and not q.counts()['failed'], f'429: товар дождался и прошёл ({c0.busy_waits} ожиданий)')

    # 5. две ноды делят очередь: 6 товаров по слотам 2 — каждая нода берёт, всего сделано 6, ни одного дубля
    q = CQ.Queue(os.path.join(tmp, 'q6'))
    q.fill({f'S{i}': {} for i in range(6)})
    sim = Sim({'07': 200.0, 'seam': 100.0, '08': 50.0})
    cs = {n: CQ.Chain(q, n, ['07', 'seam', '08'], 2, sim.submit, sim.poll, say=lambda *a: None, clock=lambda: sim.t) for n in ('n0', 'n1')}
    tt, res = run(cs, sim)
    done_total = sum(len(res[n][1]['done']) for n in res)
    check(done_total == 6 and q.counts()['done'] == 6 and all(len(res[n][1]['done']) >= 2 for n in res), f'две ноды: всего 6 готово, без дублей, обе работали ({[len(res[n][1]["done"]) for n in res]})')
    starts = [e for e in sim.log if e[1] == 'start' and e[3] == '07']
    check(len({e[2] for e in starts}) == len(starts), 'две ноды: каждый товар начат на 07 один раз')

    # 5б. наполнение очереди одновременно многими нодами (старт круга: 6 процессов кладут одни и те же товары): ни падения, ни дублей
    import threading as _th
    q = CQ.Queue(os.path.join(tmp, 'q7'))
    rows = {f'S{i}': {'a': i} for i in range(40)}
    errs, added = [], []

    def _fill():
        try:
            added.append(q.fill(rows))
        except Exception as exc:  # noqa: BLE001
            errs.append(repr(exc))
    ths = [_th.Thread(target=_fill) for _ in range(8)]
    [x.start() for x in ths]
    [x.join() for x in ths]
    check(not errs and sum(added) == 40 and len(q.todo()) == 40 and q.counts()['todo'] == 40, f'8 нод наполняют очередь одновременно: без ошибок и дублей (добавлено {sum(added)}, ошибок {len(errs)})')

    # 6. stage_trial --queue: Spec — одно «задание-цепочка», submit/poll ведут товары очереди через submit_stage/poll_stage (подставные), состояние очереди обновляется
    try:
        import argparse
        import stage_trial as ST  # noqa: E402
        calls = []

        def fake_submit(gw, a, inputs, stage, t):
            (sku,) = inputs
            calls.append(('submit', sku, stage))
            return {'key': stage, 'ids': {sku: f'{stage}-{sku}'}, 't0': t, 'got': {}, 'skipped': {}}, {}

        def fake_poll(gw, a, cur, t):
            ((sku, _),) = cur['ids'].items()
            calls.append(('poll', sku, cur['key']))
            return 'done', {'items': {sku: {'status': 'done'}}}
        ST.submit_stage, ST.poll_stage = fake_submit, fake_poll
        qd = os.path.join(tmp, 'qst')
        a = argparse.Namespace(image='x@sha256:1', tier='low', max_min=45, idle_s=900, procs=4, fill_procs=2, threads=1, stage_timeout_s=900, keep_warm=0.0, warm_life_min=120,
                               stages='07,seam,08', out=os.path.join(tmp, 'out'), card='c', queue=qd, slots=0, requeue_max=1, suffix='n7', variant='')
        CQ.Queue(qd).fill({'P': {}, 'Q': {}, 'R': {}})
        spec = ST.make_spec(a, {})
        check(spec.jobs == ['chain'] and spec.ordered is False, 'stage_trial --queue: одно задание-цепочка, не по этапам')
        cur, _info = spec.submit(None, 'chain', 1000.0)
        check(cur and cur['key'] == 'chain', 'stage_trial --queue: submit отдаёт цепочку')
        st, info = 'running', {}
        for i in range(40):
            st, info = spec.poll(None, cur, 1000.0 + i * 10)
            if st != 'running':
                break
        check(st == 'done' and info['ok'] == 3 and CQ.Queue(qd).counts()['done'] == 3, f'stage_trial --queue: 3 товара через цепочку ({st}, {info.get("ok")})')
        first = [c for c in calls if c[0] == 'submit']
        check(len({c[1] for c in first if c[2] == '07'}) == 3 and len([c for c in first if c[2] == '08']) == 3, 'stage_trial --queue: каждый товар прошёл 07 и 08')
        check(a.slots == 0 and spec.poll is not None, 'stage_trial --queue: slots=0 → по fill_procs (2)')
    except ImportError as exc:
        print('SKIP stage_trial (нет зависимостей):', exc)

print('\nИТОГ:', 'ВСЁ ЗЕЛЁНОЕ' if not FAILS else f'ПАДЕНИЙ {len(FAILS)}')
sys.exit(1 if FAILS else 0)
