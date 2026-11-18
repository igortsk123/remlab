"""ПРОГРЕВ МЕШЕЙ ГОРЯЧЕГО СПИСКА В ПРОСТОЕ (T-20261118-10/5 ❷): список (`render_hotwarm.hot_sids`) и клиент постоянного процесса (`render_exec.ExportClient._hot_loop`).
Без Blender/Chromium: дочерний процесс-заглушка говорит протоколом `export_server` (export / hot / warm). Проверяется: порядок и ограничения списка, прогрев только в тишине после заказа,
заказ не ждёт больше одного меша и ставит прогрев на паузу, потолок памяти, отказ процесса «потолок», повтор не шлёт то же, выключатель. python tools/scout/tests/test_render_hotwarm.py"""
import json
import os
import sys
import tempfile
import textwrap
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, '..')]
import render_exec as RX  # noqa: E402
import render_hotwarm as HW  # noqa: E402

fails = []


def check(name, cond):
    print(('OK   ' if cond else 'FAIL ') + name)
    if not cond:
        fails.append(name)


# ---------- список ----------
data = {'feeds': {'диван': [{'sid': 'd1', 'msid': 'dm1'}, {'sid': 'd2'}, {'sid': 'd3'}], 'bedroom:кровать': [{'sid': 'b1'}, {'sid': 'b2'}], 'кресло': [{'sid': 'k1'}],
                  'шторы': [{'name': 'без меша'}], 'ковёр': [{'sid': 'r1'}]},
        'variants': [{'items': [{'sku': {'sid': 'v1'}}, {'sku': {'msid': 'vm2', 'sid': 'v2'}}, {'sku': {'sid': 'd2'}}]}]}
have = {'dm1', 'd2', 'd3', 'b1', 'b2', 'k1', 'r1', 'v1', 'vm2'}                # у d1 «меша нет в кэше»: msid dm1 есть, sid d1 не берётся — msid главнее
lst = HW.hot_sids(data, have=lambda s: s in have, max_n=50)
check('msid главнее sid; нет GLB в кэше — не в списке', 'dm1' in lst and 'd1' not in lst)
check('сперва частые роли вглубь (диван, кровать, кресло), затем по кругу по остальным', lst[:6] == ['dm1', 'b1', 'k1', 'd2', 'b2', 'd3'] and lst.index('r1') > lst.index('d3'))
check('предметы вариантов — после корзин, без повторов', lst[-2:] == ['v1', 'vm2'] and len(lst) == len(set(lst)))
check('потолок длины', len(HW.hot_sids(data, have=lambda s: True, max_n=3)) == 3)
check('нет файла данных — пустой список', HW.hot_sids({}, have=lambda s: True) == [])

# ---------- клиент ----------
tmp = tempfile.mkdtemp(prefix='hotwarm-')
log = os.path.join(tmp, 'child.log')
child = os.path.join(tmp, 'child.py')
open(child, 'w').write(textwrap.dedent(f'''
    import json, sys, time
    LOG = {log!r}
    print(json.dumps({{"ready": True}}), flush=True)
    for line in sys.stdin:
        r = json.loads(line)
        t = time.time()
        if r["cmd"] == "hot":
            time.sleep(float(r.get("sleep", 0.3)))
            open(LOG, "a").write(f"hot {{r['sid']}} {{t:.3f}}\\n")
            st = "ceiling" if r["sid"] == "STOP" else "warmed"
            print(json.dumps({{"ok": True, "state": st, "rss_mb": 50}}), flush=True)
        elif r["cmd"] == "export":
            time.sleep(0.2)
            open(LOG, "a").write(f"export {{t:.3f}}\\n")
            print(json.dumps({{"ok": True, "rss_mb": 50}}), flush=True)
        else:
            print(json.dumps({{"ok": True}}), flush=True)
'''))


def rows():
    return [l.split() for l in open(log).read().splitlines()] if os.path.exists(log) else []


def hots():
    return [r[1] for r in rows() if r[0] == 'hot']


def fresh(sids, hot_gb=1.0, name='a'):
    if os.path.exists(log):
        os.remove(log)
    HW.hot_sids = lambda: list(sids)
    RX.ExportClient._inst.clear()
    c = RX.ExportClient.of([sys.executable, child, name], {}, tmp, keep_gb=0.0, hot_gb=hot_gb)
    return c


def order(c):
    return c.call({'cmd': 'export', 'data': 'x', 'idx': 0, 'out': tmp, 'log': log}, 20, 4.0)


RX.HOT_IDLE_S = 0.3
RX.tree_rss_gb = lambda pid: 0.2

c = fresh(['s1', 's2', 's3'])
order(c)
check('сразу после заказа прогрева нет (тишина ещё не прошла)', hots() == [])
time.sleep(1.8)
check('в тишине прогреты все меши списка по порядку, по одному разу', hots() == ['s1', 's2', 's3'])
order(c)
time.sleep(1.0)
check('следующий заказ тот же процесс: уже прогретое не шлётся повторно', hots() == ['s1', 's2', 's3'])
c.kill()

# заказ посреди прогрева: ждёт не дольше одного меша, прогрев встаёт и продолжается после
c = fresh(['p1', 'p2', 'p3', 'p4', 'p5', 'p6'])
order(c)
time.sleep(0.9)                                  # 0,3 тишина + прогрев идёт
n_before = len(hots())
t0 = time.time()
order(c)
waited = time.time() - t0
check('заказ, пришедший в прогрев, ждёт не дольше одного меша (<0,3+0,2+запас)', waited < 0.8)
rows_now = rows()
ex_t = [float(r[1]) for r in rows_now if r[0] == 'export'][-1]
hot_after = [r for r in rows_now if r[0] == 'hot' and float(r[2]) > ex_t]
check('после заказа прогрев не стартует сразу: тишина HOT_IDLE_S', all(float(r[2]) - ex_t >= 0.3 for r in hot_after) or not hot_after)
time.sleep(3.0)
check('после заказа прогрев продолжился и дошёл до конца списка', hots() == ['p1', 'p2', 'p3', 'p4', 'p5', 'p6'])
c.kill()

# потолок памяти: выше — прогрева нет
RX.tree_rss_gb = lambda pid: 2.0
c = fresh(['m1', 'm2'], hot_gb=1.0)
order(c)
time.sleep(1.2)
check('память процесса выше потолка прогрева — ни одного меша', hots() == [])
c.kill()
RX.tree_rss_gb = lambda pid: 0.2

# процесс ответил «потолок» — прогрев останавливается
c = fresh(['q1', 'STOP', 'q3'])
order(c)
time.sleep(1.8)
check('ответ «ceiling» от процесса — дальше не греем', hots() == ['q1', 'STOP'])
c.kill()

# выключатель: hot_gb = 0
c = fresh(['z1'], hot_gb=0.0)
order(c)
time.sleep(1.0)
check('hot_gb=0 — без прогрева', hots() == [])
c.kill()

# процесс перезапущен — список заново
c = fresh(['r1', 'r2'])
order(c)
time.sleep(1.4)
c.kill()
os.remove(log)
order(c)
time.sleep(1.4)
check('новый процесс после kill — прогрев заново (hot_done сброшен)', hots() == ['r1', 'r2'])
c.kill()

print('итог:', 'чисто' if not fails else f'{len(fails)} падений')
sys.exit(1 if fails else 0)
