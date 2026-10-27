#!/usr/bin/env python3
"""Стенд сторожа денег — смена групп посреди цикла и слепота (T-20261020-24). БЕЗ Salad, сети и телеграма.

20.10 группы пересоздали и сменили `SALAD_GROUP` в salad.env, а вечный цикл сторожа держал старый список: опрашивал
удалённые группы (HTTPError), писал «работающих нод нет — не платим» и новую группу с живой нодой не видел. Тогда же
«вероятнее всего кончились кредиты» ввело в заблуждение — кредиты были. Стенд гоняет НАСТОЯЩИЙ `main()` с подменённым
API, сном и путями и проверяет:
  1) все опросы падают → «не платим» не пишется; на BLIND_N-м тике подряд — одна тревога «сторож слеп»;
  2) SALAD_GROUP сменился в salad.env посреди цикла → строка в журнал, дальше опрашиваются ТОЛЬКО новые группы,
     книга расходов не обнулена;
  3) все группы остановлены без маркера no_credits → «причина неизвестна» + факт из журнала сторожа простоя, о кредитах
     ни слова; с маркером — про кредиты;
  4) разбор salad.env: последняя строка, `export`, кавычки; нет строки — None (старый список остаётся);
  5) повторы (план mesh-13): ok того же job_id второй раз считается, cached и разные job_id — нет;
  6) потолок цены меша (план mesh-15): дорогая группа гаснет одна и под запретом подъёма; дешёвая — нет; мало данных —
     не судит; повторы не считаются мешами; история до запуска правила не судится; правило — из файла.
Запуск: ~/venvs/scout/bin/python tests_money_guard.py
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import money_guard as G  # noqa: E402
import mesh_price as MP  # noqa: E402
import salad_groups as SG  # noqa: E402

bad = 0


def ok(name: str, cond: bool) -> None:
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name)
    bad += 0 if cond else 1


class _Stop(Exception):
    pass


def case_env_parse(tmp: str) -> None:
    p = os.path.join(tmp, 'parse.env')
    open(p, 'w').write('SALAD_API_KEY=x\nSALAD_GROUP=a,b\n# SALAD_GROUP=old\nexport SALAD_GROUP="c, d"\n')
    ok('salad.env: последняя строка, export и кавычки', G.env_groups(p) == ['c', 'd'])
    open(p, 'w').write('SALAD_API_KEY=x\n')
    ok('salad.env без SALAD_GROUP — None (сторожим прежние)', G.env_groups(p) is None)
    ok('нет файла — None', G.env_groups(os.path.join(tmp, 'нет.env')) is None)


def case_loop(tmp: str) -> None:
    env = os.path.join(tmp, 'salad.env')
    open(env, 'w').write('SALAD_API_KEY=x\nSALAD_GROUP=g-old\n')
    open(G.IDLE_LOG, 'w').write(time.strftime('%Y-%m-%d %H:%M') + ' конвейера нет два захода подряд, машин в работе: 3'
                                ' — ГАШУ ГРУППЫ\n')
    G.SALAD_ENV = env
    calls, sent, ticks = [], [], [0]

    def fake_api(path: str, method: str = 'GET') -> dict:
        calls.append((ticks[0], path))
        if path.split('/')[0] == 'g-old':
            raise OSError('HTTP Error 404: Not Found')      # группа удалена
        if path.endswith('/instances'):
            return {'instances': []}
        return {'current_state': {'status': 'stopped'}}

    def fake_sleep(_s: float) -> None:
        ticks[0] += 1
        if ticks[0] == G.BLIND_N:                             # после слепых тиков — смена состава в salad.env
            open(env, 'w').write('SALAD_API_KEY=x\nSALAD_GROUP=g-new\n')
        if ticks[0] > G.BLIND_N + 1:
            raise _Stop

    keep = (G._api, G.notify, G.heartbeat, G.conveyor_alive, G.SH.check, time.sleep, os.environ.get('SALAD_GROUP'))
    G._api, G.notify, G.heartbeat = fake_api, (lambda t: sent.append(t) or True), (lambda *a, **k: None)
    G.conveyor_alive, G.SH.check = (lambda: False), (lambda: {'ok': True, 'why': '', 'free_gb': 10.0})
    time.sleep = fake_sleep
    os.environ['SALAD_GROUP'], os.environ['SALAD_API_KEY'] = 'g-old', 'x'
    json.dump({'group': 'g-old', 'idle_node_min': 0.0, 'silent_since': 0.0, 'last_seen_mesh': 0.0,
               'paid_node_min': {'g-old': 42.0}}, open(G.STATE, 'w'))
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            try:
                G.main()
            except _Stop:
                pass
    finally:
        G._api, G.notify, G.heartbeat, G.conveyor_alive, G.SH.check, time.sleep = keep[:6]
        os.environ.pop('SALAD_GROUP', None) if keep[6] is None else os.environ.__setitem__('SALAD_GROUP', keep[6])
    log = out.getvalue()
    blind_part, _, after_part = log.partition('состав групп сменился')
    ok('слепые тики: «не платим» не пишется', 'не платим' not in blind_part)
    ok(f'слепые тики считаются ({G.BLIND_N} из {G.BLIND_N})', f'слепой тик {G.BLIND_N} из {G.BLIND_N}' in blind_part)
    blind_alerts = [t for t in sent if 'СЛЕП' in t]
    ok('тревога «сторож слеп» — ровно одна', len(blind_alerts) == 1 and 'g-old' in blind_alerts[0])
    ok('смена состава — строка в журнал', 'состав групп сменился: g-old → g-new' in log)
    after = [p for t, p in calls if t >= G.BLIND_N]
    ok('после смены опрашиваются только новые группы', after and all(p.startswith('g-new') for p in after))
    ok('после смены — «не платим» по ответившей группе', 'не платим' in after_part)
    st = json.load(open(G.STATE))
    ok('книга расходов пережила смену состава', st.get('paid_node_min', {}).get('g-old') == 42.0
       and st.get('group') == 'g-new')
    down = [t for t in sent if 'остановлены' in t]
    ok('все стоят: «причина неизвестна», о кредитах ни слова',
       len(down) == 1 and 'Причина неизвестна' in down[0] and 'кредит' not in down[0].lower())
    ok('все стоят: приложен факт из журнала сторожа простоя', down and 'сторож простоя' in down[0]
       and 'конвейер не запущен' in down[0])


def case_credits_only_by_marker(tmp: str) -> None:
    keep = G.conveyor_alive
    G.conveyor_alive = lambda: True
    try:
        if os.path.exists(G.NO_CREDITS):
            os.remove(G.NO_CREDITS)
        os.remove(G.IDLE_LOG)
        credits, clues = G.stop_clues()
        ok('без маркера и журналов — кредиты не упоминаются, фактов нет', credits is False and clues == [])
        json.dump({'at': time.time() - 600, 'why': 'no_credits_available'}, open(G.NO_CREDITS, 'w'))
        credits, clues = G.stop_clues()
        ok('маркер no_credits свежий — про кредиты', credits and 'no_credits_available' in clues[0])
        json.dump({'at': time.time() - (G.CLUE_H + 1) * 3600, 'why': 'no_credits_available'}, open(G.NO_CREDITS, 'w'))
        ok('маркер старше CLUE_H — не довод', G.stop_clues()[0] is False)
        open(G.WINDOW_LOG, 'w').write(time.strftime('%d.%m %H:%M') + ' стоп mesh-batch-5: HTTP 202\n')
        ok('стоп по окну batch — в фактах', any('окно batch' in c for c in G.stop_clues()[1]))
    finally:
        G.conveyor_alive = keep


def case_repeats(tmp: str) -> None:
    """Повторы (план mesh-13): ok того же job_id второй раз — счёт после `since`, разные job_id и cached — не повтор."""
    keep = G.JOURNAL
    G.JOURNAL = os.path.join(tmp, 'rep.jsonl')
    try:
        rows = [{'status': 'ok', 'prefix': 'meshes/v2/1_a/J1', 'at': 100},
                {'status': 'ok', 'prefix': 'meshes/v2/1_b/J2', 'at': 200},
                {'status': 'cached', 'prefix': 'meshes/v2/1_a/J1', 'at': 250},
                {'status': 'ok', 'prefix': 'meshes/v2/1_a/J1', 'at': 300},
                {'status': 'ok', 'prefix': 'meshes/v2/1_c/J3', 'at': 400}]
        with open(G.JOURNAL, 'w', encoding='utf-8') as f:
            f.write('\n'.join(json.dumps(r) for r in rows) + '\n')
        ok('повтор J1 после 150 — один, пример J1', G.repeats(150) == (1, 'J1'))
        ok('после последнего повтора — ноль', G.repeats(300) == (0, ''))
        ok('история: первый ok не повтор', G.repeats(0)[0] == 1)
    finally:
        G.JOURNAL = keep


def case_price(tmp: str) -> None:
    """Потолок цены (план mesh-15; порог суда — 4 рабочих нодо-часа, владелец 21.10). Курс 86.89 ₽/$.
    g-cheap и g-dear — low ($0.143/ч), 24 тика × 5 мин × 2 ноды = 4 нодо-часа ≈ 49.7 ₽: g-cheap — 38 новых мешей
    + 30 повторов (≈1.31 ₽, дёшево); g-dear — 27 новых + 20 повторов мешей, готовых 30 ч назад (по новым ≈1.84 ₽ —
    дорого; посчитай повторы мешами — было бы ≈1.06 ₽ и группа уцелела бы). g-few — тир tiny ($0.0587/ч ≈ 5.1 ₽/ч),
    12 тиков × 1 нода = 1 нодо-час, 3 меша по ≈1.70 ₽ — выше потолка, но это шум: мало данных."""
    rules = os.path.join(tmp, 'salad-groups.json')
    rule = {'prices_usd_h': {'low': 0.143, 'tiny': 0.0587}, 'usd_rub': 86.89,
            'groups': {'g-cheap': {'tier': 'low'}, 'g-dear': {'tier': 'low'}, 'g-few': {'tier': 'tiny'}},
            'price_ceiling': {'rub_per_mesh': 1.5, 'window_h': 24, 'judge_after_node_h': 4}}
    json.dump(rule, open(rules, 'w'))
    keep = (SG.RULES, SG._CACHE, SG.PRICE_HALT, G.CENSUS, G.JOURNAL, G._api, G.notify)
    SG.RULES, SG._CACHE, SG.PRICE_HALT = rules, None, os.path.join(tmp, 'price-halt.json')
    G.CENSUS, G.JOURNAL = os.path.join(tmp, 'price-census.jsonl'), os.path.join(tmp, 'price-progress.jsonl')
    now = time.time()
    with open(G.CENSUS, 'w') as f:
        for k in range(1, 25):
            for g, run in (('g-cheap', 2), ('g-dear', 2)) + ((('g-few', 1),) if k <= 12 else ()):
                f.write(json.dumps({'at': now - k * 300, 'group': g, 'total': run, 'running': run}) + '\n')
    rows = [{'status': 'ok', 'group': 'g-cheap', 'prefix': f'm/C{i}', 'at': now - 3000 + i} for i in range(38)]
    rows += [{'status': 'ok', 'group': 'g-cheap', 'prefix': f'm/C{i}', 'at': now - 1000 + i} for i in range(30)]
    rows += [{'status': 'ok', 'group': 'g-dear', 'prefix': f'm/D{i}', 'at': now - 30 * 3600 + i} for i in range(20)]
    rows += [{'status': 'ok', 'group': 'g-dear', 'prefix': f'm/D{i}', 'at': now - 2000 + i} for i in range(20)]
    rows += [{'status': 'ok', 'group': 'g-dear', 'prefix': f'm/N{i}', 'at': now - 1500 + i} for i in range(27)]
    rows += [{'status': 'ok', 'group': 'g-few', 'prefix': f'm/F{i}', 'at': now - 1200 + i} for i in range(3)]
    rows += [{'status': 'cached', 'group': 'g-dear', 'prefix': f'm/X{i}', 'at': now - 900} for i in range(9)]
    open(G.JOURNAL, 'w').write(''.join(json.dumps(r) + '\n' for r in rows))
    calls, sent = [], []
    G._api = lambda path, method='GET': calls.append((path, method)) or {'instances': []}
    G.notify = lambda t: sent.append(t) or True
    gs = ['g-cheap', 'g-dear', 'g-few']
    try:
        st = {'price_floor': {g: now - 3 * 3600 for g in gs}}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            stopped = G.price_tick(st, gs, now)
        res = st['price']['groups']
        ok('дорогая группа гаснет одна (stop, не delete)', stopped == ['g-dear']
           and [c for c in calls if c[1] == 'POST'] == [('g-dear/stop', 'POST')])
        ok('повторы не меши: g-dear 27 новых из 47 ok, g-cheap 38 из 68',
           res['g-dear']['meshes'] == 27 and res['g-cheap']['meshes'] == 38)
        ok(f'средняя за 4+ нодо-часа: {res["g-cheap"]["per_mesh"]} ₽ — дёшево, {res["g-dear"]["per_mesh"]} ₽ — дорого',
           res['g-cheap']['state'] == 'дёшево' and 1.25 < res['g-cheap']['per_mesh'] < 1.35
           and res['g-dear']['state'] == 'дорого' and 1.8 < res['g-dear']['per_mesh'] < 1.9
           and res['g-cheap']['node_min'] == 240.0)
        ok(f'3 меша по {res["g-few"]["per_mesh"]} ₽ за 1 нодо-час — мало данных, не гаснет',
           res['g-few']['state'] == 'мало данных' and 1.65 < res['g-few']['per_mesh'] < 1.75
           and res['g-few']['node_min'] == 60.0)
        pc = rule['price_ceiling']
        ok('0 мешей за 4 нодо-часа — дорого; за 3.9 — ещё мало данных',
           MP.verdict(240, 0.143, 86.89, 0, pc)['state'] == 'дорого'
           and MP.verdict(234, 0.143, 86.89, 0, pc)['state'] == 'мало данных')
        ok('запрет подъёма до остановки: g-dear запрещена, g-cheap нет',
           SG.price_halted('g-dear') and not SG.allowed_now('g-dear') and SG.allowed_now('g-cheap'))
        ok('сообщение владельцу — одно, про g-dear', len(sent) == 1 and 'g-dear' in sent[0] and 'ОСТАНОВЛЕНА' in sent[0])
        ok('строка в журнал: «ДОРОГАЯ ГРУППА» и сводка ₽ за меш', 'ДОРОГАЯ ГРУППА g-dear' in out.getvalue()
           and '₽ за меш по группам' in out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            again = G.price_tick(st, gs, now + 300)
        ok('под запретом — второй раз не гасит и не пишет', again == [] and len(sent) == 1)
        env = dict(os.environ, MESH_GROUPS_RULES=rules, MESH_PRICE_HALT=SG.PRICE_HALT)
        sg = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'salad_groups.py')
        r1 = subprocess.run([sys.executable, sg, '--can-start', 'g-dear'], env=env, capture_output=True, text=True)
        r0 = subprocess.run([sys.executable, sg, '--can-start', 'g-cheap'], env=env, capture_output=True, text=True)
        ok('batch_window: --can-start — запрещённой 1 с причиной, остальным 0',
           r1.returncode == 1 and 'запрет цены' in r1.stdout and r0.returncode == 0)
        st2: dict = {}
        with contextlib.redirect_stdout(io.StringIO()):
            G.price_tick(st2, ['g-cheap'], now)
        ok('история до запуска правила не судится (окно — с первого тика)',
           st2['price']['groups']['g-cheap']['state'] == 'мало данных' and st2['price_floor']['g-cheap'] == now)
        json.dump(dict(rule, price_ceiling=dict(rule['price_ceiling'], rub_per_mesh=0.5)), open(rules, 'w'))
        SG._CACHE = None
        ok('правило из файла: потолок 0.5 ₽ — g-cheap уже дорого',
           MP.by_group(['g-cheap'], now, census=G.CENSUS, journal=G.JOURNAL)['g-cheap']['state'] == 'дорого')
        # СУД ПО ПОЛНЫМ 8 ЧАСАМ (T-20261022-10/4): окно 3 ч → дорогая g-dear не судится; запрет сняли — суд заново с той минуты
        json.dump(dict(rule, price_ceiling=dict(rule['price_ceiling'], judge_after_h=8)), open(rules, 'w'))
        SG._CACHE = None
        r8 = MP.by_group(['g-dear'], now, {'g-dear': now - 3 * 3600}, G.CENSUS, G.JOURNAL)['g-dear']
        r9 = MP.by_group(['g-dear'], now, {'g-dear': now - 9 * 3600}, G.CENSUS, G.JOURNAL)['g-dear']
        ok(f'judge_after_h=8: окно 3 ч — мало данных (ещё {r8.get("judge_in_h")} ч), окно 9 ч — дорого',
           r8['state'] == 'мало данных' and r8.get('judge_in_h') == 5.0 and r9['state'] == 'дорого')
        st3 = {'price_floor': {'g-dear': now - 20 * 3600}}
        with contextlib.redirect_stdout(io.StringIO()):
            G.price_tick(st3, ['g-dear'], now)                 # под запретом (поставлен выше) — запомнили
        held = list(st3['price_held'])
        d = json.load(open(SG.PRICE_HALT)); d.pop('g-dear'); json.dump(d, open(SG.PRICE_HALT, 'w'))
        n0 = len(calls)
        out3 = io.StringIO()
        with contextlib.redirect_stdout(out3):
            again = G.price_tick(st3, ['g-dear'], now + 60)
        ok('запрет снят — окно с этой минуты, не гасит сразу; строка в журнал',
           held == ['g-dear'] and st3['price_floor']['g-dear'] == now + 60 and again == [] and len(calls) == n0
           and st3['price']['groups']['g-dear']['state'] == 'мало данных' and 'снят' in out3.getvalue())
    finally:
        SG.RULES, SG._CACHE, SG.PRICE_HALT, G.CENSUS, G.JOURNAL, G._api, G.notify = keep


def case_planned_stop(tmp: str) -> None:
    """Все группы стоят ПО ПЛАНУ (T-20261024-01, 24.10 00:47): одна — запрет по цене, другая — вне окна batch. Тревоги
    «причина неизвестна» нет, в журнале — строка «пул стоит по плану». Одна по плану, другая без причины — тревога есть,
    и в ней названа известная часть."""
    json.dump({'g-dear': {'why': 'меш 6.76 ₽ при потолке 1.5 ₽'}}, open(SG.PRICE_HALT, 'w'))
    night = time.mktime(time.strptime('2026-10-24 00:47', '%Y-%m-%d %H:%M')) - time.timezone
    keep_info = SG.info
    SG.info = lambda g: {'window_utc': [9, 15]} if g == 'g-batch' else {}
    try:
        got = G.known_stops(['g-dear', 'g-batch', 'g-lost'], night)
        ok('известные остановки: цена и окно, третья — нет',
           set(got) == {'g-dear', 'g-batch'} and 'по цене' in got['g-dear'] and '09–15 UTC' in got['g-batch'])
        h = time.gmtime().tm_hour       # цикл сторожа смотрит на часы сейчас: окно batch — заведомо не сейчас
        SG.info = lambda g: {'window_utc': [(h + 1) % 24, (h + 2) % 24]} if g == 'g-batch' else {}
        for groups, want_alert in (('g-dear,g-batch', False), ('g-dear,g-lost', True)):
            sent, ticks = [], [0]

            def fake_sleep(_s: float) -> None:
                ticks[0] += 1
                if ticks[0] > 1:
                    raise _Stop
            keep = (G._api, G.notify, G.heartbeat, G.conveyor_alive, G.SH.check, time.sleep, os.environ.get('SALAD_GROUP'))
            G._api = lambda path, method='GET': {'instances': []} if path.endswith('/instances') else \
                {'current_state': {'status': 'stopped'}}
            G.notify, G.heartbeat = (lambda t: sent.append(t) or True), (lambda *a, **k: None)
            G.conveyor_alive, G.SH.check = (lambda: True), (lambda: {'ok': True, 'why': '', 'free_gb': 10.0})
            time.sleep = fake_sleep
            os.environ['SALAD_GROUP'], os.environ['SALAD_API_KEY'] = groups, 'x'
            env = os.path.join(tmp, 'salad-planned.env')
            open(env, 'w').write(f'SALAD_API_KEY=x\nSALAD_GROUP={groups}\n')
            G.SALAD_ENV = env
            json.dump({'group': groups, 'idle_node_min': 0.0, 'silent_since': 0.0, 'last_seen_mesh': 0.0}, open(G.STATE, 'w'))
            out = io.StringIO()
            try:
                with contextlib.redirect_stdout(out):
                    try:
                        G.main()
                    except _Stop:
                        pass
            finally:
                G._api, G.notify, G.heartbeat, G.conveyor_alive, G.SH.check, time.sleep = keep[:6]
                os.environ.pop('SALAD_GROUP', None) if keep[6] is None else os.environ.__setitem__('SALAD_GROUP', keep[6])
            down = [t for t in sent if 'остановлены' in t]
            if want_alert:
                ok('одна без причины — тревога есть, известная часть в ней названа',
                   len(down) == 1 and 'Причина неизвестна' in down[0] and 'g-dear — запрет по цене' in down[0])
            else:
                ok('все по плану — тревоги нет, строка «по плану» в журнале',
                   not down and 'пул стоит по плану' in out.getvalue() and 'g-batch — вне окна' in out.getvalue())
    finally:
        SG.info = keep_info
        os.remove(SG.PRICE_HALT)


def case_manual_cap(tmp: str) -> None:
    """Потолок ручной волны (T-20261027-02): судится тем же правилом, что волна автозапуска, но из своего файла;
    выбран — причина непустая и помечена «manual»; закрытая волна и нет файла — молчим."""
    import wave_cap as WC  # noqa: PLC0415
    keep = WC.PATH
    try:
        WC.PATH = os.path.join(tmp, 'wave-manual.json')
        st = {'paid_node_min': {'g': 600}}               # 10 ч × тариф g
        keep_price = SG.price
        SG.price = lambda g: 0.1                         # $1.00 оплачено
        ok('нет ручной волны — потолка нет', G.breach_of(st, None, WC.read()) == ('', ''))
        WC.open_wave(87.0, 87.0, 0.5, 's.json')          # потолок $1.00, отметка $0.50 → потрачено $0.50
        ok('ручной потолок не выбран — молчим', G.breach_of(st, None, WC.read()) == ('', ''))
        WC.open_wave(43.5, 87.0, 0.5, 's.json')          # потолок $0.50 — выбран
        why, src = G.breach_of(st, None, WC.read())
        ok('ручной потолок выбран — гасим, источник manual', src == 'manual' and why.startswith('ПОТОЛОК РУЧНОЙ ВОЛНЫ'))
        ok('прежняя открытая ручная волна закрыта как брошенная', WC.read()['waves'][-2].get('closed') is not None)
        lease = {'waves': [{'usd_cap': 0.1, 'usd_mark': 0}]}
        ok('волна разрешения судится первой', G.breach_of(st, lease, WC.read())[1] == 'lease')
        w = WC.close('стенд', G.paid_usd(st), 87.0)
        ok('закрытие пишет факт денег', w and abs(w['spent_usd'] - 0.5) < 1e-6 and w['spent_rub'] == 43.5)
        ok('закрытая ручная волна не ограничивает', G.breach_of(st, None, WC.read()) == ('', ''))
        SG.price = keep_price
    finally:
        WC.PATH = keep


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        G.STATE, G.HALT = os.path.join(tmp, 'guard.json'), os.path.join(tmp, 'halt.json')
        G.CENSUS, G.SNAPSHOT = os.path.join(tmp, 'census.jsonl'), os.path.join(tmp, 'snapshot.json')
        G.JOURNAL, G.LEASE = os.path.join(tmp, 'progress.jsonl'), os.path.join(tmp, 'lease.json')
        G.NO_CREDITS, G.IDLE_LOG = os.path.join(tmp, 'no-credits.json'), os.path.join(tmp, 'idle.log')
        G.WINDOW_LOG = os.path.join(tmp, 'window.log')
        G.WC.PATH = os.path.join(tmp, 'wave-manual-loop.json')    # живую ручную волну стенд не читает
        SG.PRICE_HALT = os.path.join(tmp, 'price-halt-loop.json')   # живой запрет цены стенд не читает и не пишет
        open(G.JOURNAL, 'w').close()
        case_env_parse(tmp)
        case_loop(tmp)
        case_credits_only_by_marker(tmp)
        case_repeats(tmp)
        case_price(tmp)
        case_planned_stop(tmp)
        case_manual_cap(tmp)
    print('сторож денег: ' + ('ВСЁ ЗЕЛЁНОЕ' if not bad else f'ПРОВАЛОВ {bad}'))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
