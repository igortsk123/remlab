"""Тесты заготовки кадров (T-20261118-07): `render_jobs` (заготовка `warm`) + `render_prewarm.Prewarmer`. Без сети и без платного: исполнитель и машина — подмены.

Запуск: ~/venvs/scout/bin/python tools/scout/render_gpu/tests_render_prewarm.py   (код 0 — чисто)"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.abspath(os.path.join(HERE, '..'))
TMP = tempfile.mkdtemp(prefix='pw-test-')
os.environ.update(RENDER_MACHINE_DIR=os.path.join(TMP, 'rm'), RENDER_PREWARM_STATUS=os.path.join(TMP, 'pw-status.json'))
sys.path[:0] = [SCOUT, HERE]
import render_exec as RX  # noqa: E402
import render_jobs as RJ  # noqa: E402
import render_machine as RM  # noqa: E402
import render_prewarm as PW  # noqa: E402

BAD = []


def ok(cond, name):
    print(('OK   ' if cond else 'FAIL ') + name)
    if not cond:
        BAD.append(name)


class FakeEx:
    """Машина рендера: `up` — прогрета; `render` кладёт два кадра. `primary` нет — очередь берёт сам объект."""
    name = 'salad-gpu'

    def __init__(self, store, delay=0.0):
        self.store, self.delay, self.up, self.calls, self.fail_keys = store, delay, False, [], set()

    def warm_ok(self):
        return self.up

    def available(self):
        return self.up

    def render(self, snap, out_dir, progress):
        self.calls.append(snap['scene_hash'])
        progress('C1')
        time.sleep(self.delay)
        if snap['scene_hash'] in self.fail_keys:
            raise RX.RenderError('render_failed', 'ру', 'en')
        os.makedirs(out_dir, exist_ok=True)
        for c in RJ.CAMS:
            open(os.path.join(out_dir, f'{c}.jpg'), 'wb').write(b'\xff\xd8x')
        json.dump({'scene_hash': snap['scene_hash'], 'size': [10, 8], 'versions': {}, 'sha': {'C1': 'a' * 64, 'C2': 'b' * 64}}, open(os.path.join(out_dir, 'meta.json'), 'w'))
        return {'timing': {}, 'executor': 'salad-gpu'}


class FakeMachine:
    def __init__(self, ex, spent=0.0, cap=2.0, share=0.6, batch=2, off_idle_s=120):
        self.ex, self.spent, self.cap, self.share, self.batch, self.off_idle_s = ex, spent, cap, share, batch, off_idle_s
        self.notes, self.on_calls, self.off_calls, self.desired, self.by = [], 0, 0, 'off', None

    def rules(self):
        return {'day_cap_usd': self.cap, 'price_class': 'RTX 4090 (24 GB)', 'tier': 'medium', 'warmup_max_min': 1,
                'prewarm': {'day_share': self.share, 'batch': self.batch, 'interval_s': 1, 'start_delay_s': 0, 'tours_max': 0, 'fail_max': 2, 'off_idle_s': self.off_idle_s}}

    def state(self):
        return {'spent_usd': self.spent, 'spent_date': RM.london_date(time.time()), 'desired': self.desired, 'by': self.by}

    def turn_on(self, by):
        self.on_calls += 1
        self.desired, self.by = 'on', by
        self.ex.up = True
        return 'ok'

    def turn_off(self, by):
        self.off_calls += 1
        self.desired = 'off'
        self.ex.up = False
        return 'off ok'

    def set_note(self, t):
        self.notes.append(t)


def snap(h):
    return {'scene_hash': h, 'variant': {'id': h}}


def build(delay=0.0, **mk):
    d = tempfile.mkdtemp(dir=TMP)
    st = RJ.RenderStore(os.path.join(d, 'jobs.json'), os.path.join(d, 'res'))
    ex = FakeEx(st, delay)
    q = RJ.RenderQueue(st, ex)
    q.max_queue, q.ip_max, q.tour_max, q.hour_cap = 1, 1, 1, 1
    q.start()
    m = FakeMachine(ex, **mk)
    return st, ex, q, m


def prewarmer(q, ex, m, scenes, versions=None):
    return PW.Prewarmer(q, ex, versions or {'preset': 3}, m, lambda s: {'room': {'w': 1}}, scenes_fn=lambda pw: scenes, sleep=lambda s: time.sleep(min(s, 0.01)), log=lambda *a: None)


def wait_for(cond, t=5.0):
    t0 = time.time()
    while time.time() - t0 < t:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


try:
    # ——— очередь: заготовка не занимает процессор DEV и не мешает людям
    st, ex, q, m = build()
    w = [q.submit(snap(f'w{i}'), f'kw{i}', tour=f'demo:w{i}', warm=True) for i in range(5)]
    ok(all(x['status'] == 'queued' for x in w), 'заготовки мимо пределов покупателя (очередь 1, час 1 — пять заготовок приняты)')
    ok(q.waiting_n() == 0 and q.warm_counts() == {'queued': 5, 'running': 0}, 'заготовки не считаются в очереди покупателей')
    time.sleep(0.3)
    ok(ex.calls == [], 'машина не прогрета — заготовки ждут, исполнитель не вызван (процессор DEV не занят)')
    h = q.submit(snap('human'), 'kh', ip='1.2.3.4')
    ok(wait_for(lambda: (q.view(h['job']) or {}).get('status') == 'done') and ex.calls == ['human'], 'заказ человека идёт при непрогретой машине и без ожидания заготовок')
    ex.up = True
    ok(wait_for(lambda: all((st.cached(f'kw{i}') is not None) for i in range(5)), 8), 'машина прогрелась — заготовки посчитаны')
    ok(q.stats()['warm']['queued'] == 0, 'статистика: заготовок в очереди нет')
    q.close()

    # человек обгоняет ждущие заготовки, когда машина прогрета
    st, ex, q, m = build(delay=0.15)
    ex.up = True
    for i in range(4):
        q.submit(snap(f'a{i}'), f'ka{i}', tour=f'demo:a{i}', warm=True)
    time.sleep(0.05)
    hh = q.submit(snap('hh'), 'khh', ip='5.5.5.5')
    wait_for(lambda: len(ex.calls) >= 3, 5)
    ok('hh' in ex.calls[:2], f'заказ человека — вторым после уже идущей заготовки, не в хвосте: {ex.calls[:4]}')
    q.close()

    # машину погасили посреди заготовки: не ошибка, ждёт
    st, ex, q, m = build()
    ex.up = True

    class Lose(FakeEx):
        pass
    orig = ex.render

    def lose(snp, out_dir, progress):
        ex.up = False
        raise RX.ExecutorUnavailable('gpu_off', 'ру', 'en')
    ex.render = lose
    q.submit(snap('lost'), 'klost', tour='demo:lost', warm=True)
    time.sleep(0.4)
    jb = [j for j in st.jobs.values() if j.get('warm')]
    ok(jb and jb[0]['status'] == 'queued', 'машину вытеснили посреди заготовки — заготовка снова в очереди, не ошибка')
    ex.render = orig
    ex.up = True
    ok(wait_for(lambda: st.cached('klost') is not None, 5), 'машина вернулась — заготовка досчитана')
    q.close()

    # ——— проход заготовки
    scenes = [(f'demo:s{i}', snap(f's{i}')) for i in range(4)]
    st, ex, q, m = build(batch=2)
    p = prewarmer(q, ex, m, scenes)
    r = p.once()
    keys = [RX.cache_key(s['scene_hash'], {'preset': 3}) for _, s in scenes]
    ok(m.on_calls == 1 and r['state'] == 'done' and all(st.cached(k) for k in keys), f"машина выключена — включена один раз, все 4 комнаты в кэше ({r['state']})")
    ok(m.off_calls == 1 and m.desired == 'off' and 'выключена сразу' in r['note'], 'включила заготовка, людей не было — выключена сразу после прохода (не ждём автостоп)')
    ok(any('Заготовка кадров' in n for n in m.notes), 'строка статуса машины записана')
    ok(all(os.path.isfile(os.path.join(st.result_dir(k), 'order.json')) for k in keys), 'рядом с кадрами order.json — «Улучшить» из рендера работает с заготовкой')
    calls = len(ex.calls)
    r2 = p.once()
    ok(r2['state'] == 'idle' and len(ex.calls) == calls and m.on_calls == 1 and m.off_calls == 1, 'второй проход: всё в кэше — ничего не считается, машину не включает и второй раз не выключает')
    ok(q.submit(snap('s1'), keys[1], ip='9.9.9.9')['cached'] is True, 'заказ покупателя после заготовки — мгновенно из кэша')
    # сменился ключ (новая версия рендера) — все комнаты считаются заново
    p2 = prewarmer(q, ex, m, scenes, versions={'preset': 4})
    r3 = p2.once()
    ok(r3['state'] == 'done' and len(ex.calls) == calls + 4, 'версия рендера сменилась — заготовка пересчитала все комнаты под новый ключ')
    q.close()

    # ——— выключение сразу: оба случая + границы
    def human(q, ex, tag):
        ex.up = True
        h = q.submit(snap(tag), 'k' + tag, ip='8.8.8.' + str(len(tag)))
        wait_for(lambda: (q.view(h['job']) or {}).get('status') == 'done', 5)

    st, ex, q, m = build(delay=0.3, batch=2)
    p = prewarmer(q, ex, m, scenes[:2])
    orig_on = m.turn_on

    def on_then_human(by):                       # пока шла заготовка, пришёл заказ человека (его считает машина)
        r_ = orig_on(by)
        threading.Thread(target=lambda: (time.sleep(0.05), human(q, ex, 'hum1')), daemon=True).start()
        return r_
    m.turn_on = on_then_human
    r = p.once()
    time.sleep(0.3)
    ok(r['state'] == 'done' and m.off_calls == 0 and m.desired == 'on' and 'выключена сразу' not in r['note'], 'за время прохода был заказ людей — не выключаем, остаётся обычный автостоп 20 мин')
    q.close()

    st, ex, q, m = build()
    human(q, ex, 'old')
    for j in st.jobs.values():
        j['ts'] -= 600                           # заказ людей был 10 минут назад — окно 2 мин он не держит
    ex.up, m.desired, m.by = True, 'on', 'prewarm'
    p = prewarmer(q, ex, m, scenes[:1])
    r = p.once()
    ok(m.off_calls == 1, 'заказ людей был давно (вне окна) — выключаем сразу')
    q.close()

    st, ex, q, m = build()
    p = prewarmer(q, ex, m, scenes[:2])
    p.once()
    k0 = RX.cache_key('s0', {'preset': 3})
    h2 = q.submit(snap('s0'), k0, ip='7.7.7.7')            # человек заказал уже готовое — из кэша, машине не нужен
    ex.up, m.desired, m.by = True, 'on', 'prewarm'
    r = p.once()
    ok(h2['cached'] and m.off_calls == 2, 'заказ из кэша машине не нужен — не мешает выключению')
    q.close()

    st, ex, q, m = build()
    ex.up, m.desired, m.by = True, 'on', 'cli'             # машину включил человек (кнопка бота), не заготовка
    p = prewarmer(q, ex, m, scenes[:2])
    r = p.once()
    ok(r['state'] == 'done' and m.off_calls == 0 and m.on_calls == 0, 'машину включил не заготовка — заготовка её не выключает')
    q.close()

    st, ex, q, m = build(off_idle_s=0)
    p = prewarmer(q, ex, m, scenes[:2])
    p.once()
    ok(m.off_calls == 0 and m.desired == 'on', 'off_idle_s = 0 — только автостоп, как раньше')
    q.close()

    st, ex, q, m = build()
    p = prewarmer(q, ex, m, scenes[:2])
    p.once()
    m.desired, m.by, ex.up = 'on', 'prewarm', True          # сервис перезапустился, машина включена нами, всё уже в кэше
    r = p.once()
    ok(r['state'] == 'idle' and m.off_calls == 2, 'после перезапуска: всё в кэше, машина наша и простаивает — выключаем')
    q.close()

    # ——— деньги
    st, ex, q, m = build(spent=1.19)            # потолок заготовки 0,6 × 2 = 1,2 — осталось $0,01
    p = prewarmer(q, ex, m, scenes)
    r = p.once()
    ok(r['state'] == 'cap' and m.on_calls == 0 and ex.calls == [] and any('лимит' in n for n in m.notes), 'потолок дня исчерпан — машину не включает, строка в статусе')
    q.close()
    st, ex, q, m = build(spent=1.2 - 0.0035 * 2 - 0.0213)      # прогрев ≈ $0,023 + две комнаты по ≈ $0,0035 (замер 40 с × $0,273/ч ≈ $0,003)
    ex.up = True
    p = prewarmer(q, ex, m, scenes)
    per = p.per_room_usd(m.rules())
    m.spent = 1.2 - per * 2.5
    r = p.once()
    ok(r['state'] == 'partial' and len(ex.calls) == 2, f"денег хватает на 2 комнаты из 4 — считает две и говорит остаток ({r['state']}, {len(ex.calls)})")
    q.close()

    # ——— сбойная комната не крутится вечно
    st, ex, q, m = build()
    ex.fail_keys = {'s0'}
    p = prewarmer(q, ex, m, scenes[:2])
    p.once()
    p.once()
    n0 = ex.calls.count('s0')
    p.once()
    ok(n0 == 2 and ex.calls.count('s0') == 2, f'комната, не давшая кадров fail_max раз подряд, больше не берётся (попыток {ex.calls.count("s0")})')
    ok(st.cached(RX.cache_key('s1', {'preset': 3})) is not None, 'остальные комнаты посчитаны')
    q.close()

    # ——— исполнитель без машины
    class NoGpu:
        name = 'local-cpu'
    st, ex, q, m = build()
    p = PW.Prewarmer(q, NoGpu(), {}, m, lambda s: {}, scenes_fn=lambda pw: scenes, log=lambda *a: None)
    ok(p.once()['state'] == 'no_gpu', 'исполнитель только на процессоре — заготовка не запускается')
    q.close()

    # ——— контроллер: строка статуса и правила по умолчанию
    RM.set_note('Заготовка кадров: проба')
    ok(json.load(open(os.path.join(RM.STATE_DIR, 'state.json')))['note'] == 'Заготовка кадров: проба', 'render_machine.set_note пишет строку в состояние')
    ok(RM.load_rules()['prewarm']['day_share'] == 0.6 and RM.load_rules()['prewarm']['tours_max'] == 0, 'правила: доля дня 0,6, туры 0 — по умолчанию')
    # ГОРЯЧИЙ СПИСОК (T-20261118-09/8): обновляется при смене версий/данных, один раз на ключ, сбой не закрепляется
    st, ex, q, m = build()
    p = prewarmer(q, ex, m, scenes[:1], versions={'preset': 3})
    calls = []
    p.hot_fn = lambda e: calls.append(1) or 0
    pwr = p.rules()['pw']
    ok(p.refresh_hot(pwr) == 'ok' and len(calls) == 1, 'горячий список: первый раз — записан')
    ok(p.refresh_hot(pwr) == '' and len(calls) == 1, 'тот же ключ (версии и данные) — второй раз не пишем')
    p.versions = {'preset': 4}
    ok(p.refresh_hot(pwr) == 'ok' and len(calls) == 2, 'версии рендера сменились — список переписан')
    p.versions = {'preset': 5}
    p.hot_fn = lambda e: 2
    ok(p.refresh_hot(pwr) == 'fail' and p.hot_key != json.dumps({'preset': 5}, sort_keys=True) + '|0', 'сбой (код 2) — ключ не закреплён, повтор на следующем проходе')
    p.hot_fn = lambda e: (_ for _ in ()).throw(RuntimeError('нет приёмника'))
    ok(p.refresh_hot(pwr) == 'fail', 'исключение не пробрасывается')
    p.hot_fn = lambda e: calls.append(1) or 0
    ok(p.refresh_hot(dict(pwr, hot_refresh=0)) == 'skip', 'prewarm.hot_refresh = 0 — не трогаем')
    q.close()
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print('\n' + ('ВСЁ ЧИСТО' if not BAD else f'ПРОВАЛЕНО: {len(BAD)} — ' + '; '.join(BAD)))
sys.exit(1 if BAD else 0)
