#!/usr/bin/env python3
"""Стенд динамического пула нод — БЕЗ Salad, сети и GPU.

Проверяет ровно то, ради чего пул переделан (план mesh-dynamic-node-pool):
  1) нода, прогревшаяся ПОСЛЕ старта, подключается к идущему прогону;
  2) транспортный сбой возвращает задание в очередь и выводит ноду из пула;
  3) исчерпанные попытки честно попадают в `unresolved`, курсор дальше дырки не едет;
  4) «нет тёплых нод» — это код 75, а не падение;
  5) чекпойнт пишется после каждого задания.

Запуск: ~/venvs/scout/bin/python tests_pool.py
"""
import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import node_health as NH  # noqa: E402
import ssh_run as S  # noqa: E402


def setup(tmp: str) -> None:
    """Быстрые таймеры и временные файлы: боевые mesh-pilot-results.json, журнал прогона и
    состояние здоровья нод трогать нельзя — рядом идёт живой конвейер."""
    S.POLL_S, S.CULL_S, S.STALL_S = 0.3, 10_000, 6.0
    S.RETRY_GRACE_S, S.MAX_ATTEMPTS, S.NODE_COOLDOWN_S = 0.2, 3, 30.0
    S.SSH_STAGGER_S = 0.0
    S.WARMUP_GRACE_S = 0.0                 # стенду ждать прогрев замены незачем
    S.RESULTS = os.path.join(tmp, 'results.json')
    S.PROGRESS = os.path.join(tmp, 'progress.jsonl')
    S.RETRY_SPOOL = os.path.join(tmp, 'retry.jsonl')
    S.cull_slow = lambda: None
    NH.STATE = os.path.join(tmp, 'health.json')
    # ФАЙЛ ЗАМКА НЕ УДАЛЯЕМ: от прошлого случая могли остаться демон-потоки, и подмена
    # inode'а замка снимает взаимное исключение — два потока писали состояние одновременно.
    for p in (NH.STATE, NH.STATE + '.tmp', S.RETRY_SPOOL):
        if os.path.exists(p):
            os.remove(p)
    NH.reallocate = lambda group, iid, why: culled.append(iid) or True   # noqa: B010 — стенд
    culled.clear()


culled: list = []               # кого стенд «пересадил» вместо реального вызова Salad
ORIG_JOBS_FROM_FILE = S.jobs_from_file   # `patch()` его подменяет — держим настоящий
ORIG_RUN_JOB = S.run_job                 # то же: случаю про двойной /generate нужен настоящий


def jobs(n: int) -> list[dict]:
    return [{'sku': f'sku{i}', 'role': 'кресло', 'image_url': 'x', 'dims_cm': {},
             'seed': 0, 'params': {}} for i in range(n)]


def patch(nodes: list[dict], job_fn) -> None:
    S.instances = lambda: list(nodes)
    S.ssh_text = lambda port, cmd, timeout=60: 'NVIDIA GeForce RTX 3090'   # фоновый опрос карты
    S.probe_warm = lambda port: True
    # Супервизор с 03.09 спрашивает у ноды ВЕСЬ `/health`, а не только «тёплая ли»: по тому же
    # ответу он снимает зомби с мёртвым прогревом. Стенд подменяет транспорт, поэтому здесь
    # отдаём здоровый ответ — без `warmup_error`, иначе нода уедет в пересадку.
    S.probe_health = lambda port: {'ok': True, 'warm': True, 'done': 0, 'gpu_seconds': 0.0}
    # Приёмник (04.09): стенд без сети — считаем его зелёным, отдельные случаи красят сами
    S.sink_preflight = lambda: True
    S.sink_poll = lambda force=False: True
    S._SINK.update(ok=True, why='', at=0.0)
    S.run_job = job_fn
    S.jobs_from_file = lambda path: patch.jobs           # noqa: B010 — стенд
    S.stop_group = lambda: None


def case_late_node() -> None:
    """Нода появилась через секунду после старта — прогон обязан её подхватить."""
    nodes = [{'id': 'A' * 8, 'port': 1, 'group': 'g', 'state': 'running'}]
    used = []

    def job_fn(port, job):
        used.append(port)
        time.sleep(0.25)
        return {'sku': job['sku'], 'status': 'ok', 'timings_s': {'total': 1}}

    patch.jobs = jobs(8)
    patch(nodes, job_fn)
    threading.Timer(0.7, lambda: nodes.append(
        {'id': 'B' * 8, 'port': 2, 'group': 'g', 'state': 'running'})).start()

    code = S.run(None, True, jobs_file='x')
    assert code == 0, code
    assert 2 in used, f'поздняя нода не подключилась: {used}'
    st = json.load(open(S.RESULTS, encoding='utf-8'))['summary']
    assert st == {'requested': 8, 'terminal': 8, 'terminal_prefix': 8, 'unresolved': 0}, st
    print('  ✓ поздняя нода подключилась к идущему прогону')


def case_bad_node() -> None:
    """Мёртвая нода не должна съесть очередь: задание возвращается, нода выбывает."""
    nodes = [{'id': 'A' * 8, 'port': 1, 'group': 'g', 'state': 'running'},
             {'id': 'B' * 8, 'port': 2, 'group': 'g', 'state': 'running'}]
    hits = {1: 0, 2: 0}

    def job_fn(port, job):
        hits[port] += 1
        if port == 1:
            return {'sku': job['sku'], 'status': 'transport_failed', 'error': 'нет маркера'}
        time.sleep(0.1)
        return {'sku': job['sku'], 'status': 'ok', 'timings_s': {'total': 1}}

    patch.jobs = jobs(4)
    patch(nodes, job_fn)
    code = S.run(None, True, jobs_file='x')
    assert code == 0, code
    rows = json.load(open(S.RESULTS, encoding='utf-8'))['results']
    assert all(r['status'] == 'ok' for r in rows), rows
    assert hits[1] == 1, f'битая нода взяла {hits[1]} заданий — должна была выбыть после первого'
    print('  ✓ транспортный сбой вернул задание, битая нода выведена из пула')


def case_unresolved() -> None:
    """Все ноды мертвы: попытки исчерпаны, это честный код 1 и нулевой курсор."""
    nodes = [{'id': 'A' * 8, 'port': 1, 'group': 'g', 'state': 'running'}]
    S.NODE_COOLDOWN_S = 0.2      # нода возвращается, чтобы исчерпать попытки быстро

    def job_fn(port, job):
        return {'sku': job['sku'], 'status': 'transport_failed', 'error': 'ssh timeout'}

    patch.jobs = jobs(2)
    patch(nodes, job_fn)
    code = S.run(None, True, jobs_file='x')
    st = json.load(open(S.RESULTS, encoding='utf-8'))['summary']
    assert code == 1, code
    assert st['unresolved'] == 2 and st['terminal_prefix'] == 0, st
    # В спул они попасть НЕ должны: курсор их не пропустил, следующая пачка запросит их
    # сама. Иначе одно и то же задание уходило бы на GPU дважды.
    assert not os.path.exists(S.RETRY_SPOOL), 'задание задублировано в спул повторов'
    print('  ✓ исчерпанные попытки → unresolved, курсор не двигается, дубля в спуле нет')


def case_prefix() -> None:
    """Дырка в середине: курсор двигается только до неё, хвост перегонится следующей пачкой."""
    nodes = [{'id': 'A' * 8, 'port': 1, 'group': 'g', 'state': 'running'}]
    S.NODE_COOLDOWN_S = 0.2

    def job_fn(port, job):
        if job['sku'] == 'sku1':
            return {'sku': job['sku'], 'status': 'transport_failed', 'error': 'обрыв'}
        return {'sku': job['sku'], 'status': 'ok', 'timings_s': {'total': 1}}

    patch.jobs = jobs(4)
    patch(nodes, job_fn)
    S.run(None, True, jobs_file='x')
    st = json.load(open(S.RESULTS, encoding='utf-8'))['summary']
    assert st['terminal_prefix'] == 1 and st['unresolved'] == 1, st
    print('  ✓ курсор двигается только до первой дырки')


def case_stall_is_capacity() -> None:
    """Ноды кончились посреди прогона — это ожидание ёмкости (75), а не провал волны:
    иначе конвейер бросает недоделанную волну и уходит в основную очередь."""
    nodes = [{'id': 'A' * 8, 'port': 1, 'group': 'g', 'state': 'running'}]
    S.STALL_S, S.NODE_COOLDOWN_S = 1.5, 10_000     # нода выбывает и не возвращается

    def job_fn(port, job):
        return {'sku': job['sku'], 'status': 'transport_failed', 'error': 'нода исчезла'}

    patch.jobs = jobs(3)
    patch(nodes, job_fn)
    code = S.run(None, True, jobs_file='x')
    st = json.load(open(S.RESULTS, encoding='utf-8'))['summary']
    assert code == S.EXIT_NO_CAPACITY, code
    assert st['unresolved'] == 3, st
    print('  ✓ прогон без нод → код 75 (ждём ёмкость), а не «волна провалена»')


def case_no_capacity() -> None:
    """Нет прогретых нод — это ожидание (75), а не авария."""
    S.instances = lambda: []
    S.probe_warm = lambda port: False
    assert S.run(None, True, jobs_file='x') == S.EXIT_NO_CAPACITY
    print('  ✓ нет тёплых нод → код 75')


def case_cull_rule() -> None:
    """Правило снятия медленных нод: возраст и остаток, а не «скорость за окно».
    Прошлая формула снимала ноды на 83–90% — замена начинала с нуля."""
    import batch_show as B  # noqa: PLC0415 — стенду нужен только чистый вердикт
    M = 60.0
    # Ступени и порог простоя смягчены 02.09 под образ в 26 ГБ: прежние (5/10/20 мин и
    # 5 минут без движения) снимали живые ноды — одну с формулировкой «4% к 20-й минуте
    # (норма 5%)», то есть за отставание на процент. Замена начинала закачку с нуля, и пул
    # не наполнялся. Стенд закрепляет ИМЕННО терпеливое поведение, чтобы его не «оптимизировали»
    # обратно: ступени 20 мин→5%, 40 мин→25%, 80 мин→60%, простой — 15 минут.
    cases = [
        # (возраст, скачано, без движения, темп/мин) → ждём снятия?
        ((5 * M, 0.0177, 60, 0.004), False, 'на 5-й минуте рано при любом проценте'),
        ((11 * M, 0.20, 60, 0.02), False, '20% к 11-й минуте — рано судить'),
        ((21 * M, 0.02, 60, 0.004), True, 'мертвяк: <5% к 20-й минуте'),
        ((21 * M, 0.10, 60, 0.02), False, '10% к 20-й — в норме'),
        ((41 * M, 0.20, 60, 0.005), True, '<25% к 40-й минуте'),
        ((41 * M, 0.40, 60, 0.02), False, '40% к 40-й — в норме'),
        ((81 * M, 0.50, 60, 0.006), True, '<60% к 80-й минуте'),
        ((30 * M, 0.90, 60, 0.03), False, 'финиш, темп нормальный'),
        ((30 * M, 0.90, 60, 0.004), True, 'финиш, но ползёт: ещё 25 мин'),
        ((30 * M, 0.95, 60, 0.012), True, '95%, темп ниже половины нормы'),
        ((30 * M, 0.95, 60, None), False, 'мало наблюдений — не судим'),
        ((25 * M, 0.70, 6 * M), False, 'встала на 6 минут — для 26 ГБ это не поломка'),
        ((25 * M, 0.70, 16 * M), True, 'встала на 16 минут — вот это уже мертвяк'),
    ]
    for args, want, note in cases:
        got = B.cull_verdict(*args) is not None
        assert got == want, f'{note}: {args} → {got}'
    print(f'  ✓ правило снятия нод: {len(cases)} случаев (пороги вдвое; финиш — по остатку)')


def case_fault_classes() -> None:
    """Кто виноват — нода или товар. Разбор по ТЕКСТУ ошибки, а не по статусу: 01.09 один и
    тот же `input_failed` приносил и мёртвую сеть ноды (21 раз), и мёртвую ссылку (7 раз)."""
    cases = [
        ({'status': 'ok'}, NH.FAULT_NONE, 'успех'),
        ({'status': 'cached'}, NH.FAULT_NONE, 'уже сделано'),
        ({'status': 'input_failed', 'error': '<urlopen error [Errno 101] Network is unreachable>'},
         NH.FAULT_NODE, 'у ноды нет сети'),
        ({'status': 'input_failed', 'error': '<urlopen error [Errno -3] Temporary failure in name resolution>'},
         NH.FAULT_NODE, 'у ноды не работает DNS'),
        ({'status': 'input_failed', 'error': 'HTTP Error 404: Not Found'},
         NH.FAULT_JOB, '404 = сервер ответил, значит сеть у ноды жива'),
        ({'status': 'input_failed', 'error': '<urlopen error timed out>'},
         NH.FAULT_UNKNOWN, 'таймаут: может быть и хостинг фото'),
        ({'status': 'input_failed', 'error': '<urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING]>'},
         NH.FAULT_UNKNOWN, 'обрыв SSL: ноду не обвиняем'),
        ({'status': 'transport_failed', 'error': 'ssh timeout'}, NH.FAULT_NODE, 'ssh не дошёл'),
        ({'status': 'flat_shape', 'error': 'плоская форма'}, NH.FAULT_JOB, 'вердикт по товару'),
        ({'status': 'bad_cutout', 'error': 'вырезка'}, NH.FAULT_JOB, 'вердикт по товару'),
        ({'status': 'failed', 'error': 'ValueError: пустой файл'}, NH.FAULT_UNKNOWN,
         'дефект кода, а не вина ноды'),
    ]
    for res, want, note in cases:
        got = NH.classify(res)
        assert got == want, f'{note}: {res} → {got}, ждали {want}'
    print(f'  ✓ классификация вины: {len(cases)} случаев (сеть ноды ≠ мёртвая ссылка)')


def case_streak_rules() -> None:
    """Счётчик серии: растёт только на вине ноды, рвётся успехом И вердиктом по товару."""
    net = {'status': 'input_failed', 'error': '[Errno 101] Network is unreachable'}
    dead = {'status': 'input_failed', 'error': 'HTTP Error 404: Not Found'}
    key = 'g/nodeX'
    assert NH.record(key, NH.classify(net), NH.error_class(net)) == 1
    assert NH.record(key, NH.classify(net), NH.error_class(net)) == 2
    assert not NH.is_retired(key), 'сняли раньше порога'
    # 404 доказывает, что сеть у ноды работает — серия обязана обнулиться
    assert NH.record(key, NH.classify(dead), NH.error_class(dead)) == 0
    assert NH.record(key, NH.classify(net), NH.error_class(net)) == 1, 'серия не обнулилась'
    ok = {'status': 'ok'}
    NH.record(key, NH.classify(ok), '')
    assert NH.record(key, NH.classify(net), NH.error_class(net)) == 1, 'успех не обнулил серию'
    print('  ✓ серия растёт только на вине ноды; успех и 404 её рвут')


def case_streak_survives_restart() -> None:
    """Счётчик обязан пережить перезапуск процесса: каждая пачка — НОВЫЙ `ssh_run`, и в
    памяти серия 2+2+2 никогда не дошла бы до порога (главная поправка Codex 01.09)."""
    import importlib  # noqa: PLC0415
    net = {'status': 'input_failed', 'error': '[Errno 101] Network is unreachable'}
    key = 'g/nodeR'
    NH.record(key, NH.FAULT_NODE, NH.error_class(net))
    NH.record(key, NH.FAULT_NODE, NH.error_class(net))
    state_path = NH.STATE
    fresh = importlib.reload(NH)          # «новый процесс» — состояние только из файла
    fresh.STATE = state_path
    assert fresh.record(key, fresh.FAULT_NODE, 'errno 101') == 3, 'серия не пережила перезапуск'
    print('  ✓ серия сбоев переживает перезапуск процесса между пачками')


def case_retire_is_temporary() -> None:
    """Снятие — НЕ навсегда. Болезнь ноды бывает плавающей: 01.09 `35b10e39` весь день валила
    задания по сети, а потом отработала одно за 272с (наблюдение соседней сессии). Значит
    запись о снятии обязана истекать, иначе исправившаяся машина навсегда выпадает из пула."""
    key = 'g/nodeT'
    NH.retire(key)
    assert NH.is_retired(key), 'снятие не записалось'
    # «прошло больше RETIRED_TTL_S»: сдвигаем отметку в прошлое, как это увидит следующий запуск
    with NH._State() as st:
        st['nodes'][key]['retired_at'] -= NH.RETIRED_TTL_S + 60
    assert not NH.is_retired(key), 'снятая нода не вернулась в пул после истечения срока'
    print(f'  ✓ снятие истекает за {NH.RETIRED_TTL_S / 3600:.0f}ч — нода не выбывает навсегда')


def case_fleet_wide_guard() -> None:
    """Одна и та же болезнь у многих нод — это общая сеть: пул выкашивать нельзя."""
    for i in range(NH.FLEET_MIN_NODES):
        NH.record(f'g/fleet{i}', NH.FAULT_NODE, 'errno 101')
    assert NH.fleet_wide('errno 101'), 'не распознали общую сеть'
    assert not NH.fleet_wide('ssh timeout'), 'чужой класс ошибки посчитан общим'
    print('  ✓ одинаковый отказ на нескольких нодах распознан как общая сеть')


def case_cull_budget_shared() -> None:
    """Бюджет пересадок ОДИН на всех: два процесса не должны выкосить пул вдвоём."""
    got = sum(NH.take_cull_slot() for _ in range(NH.MAX_CULL_PER_HOUR + 5))
    assert got == NH.MAX_CULL_PER_HOUR, f'выдано {got}, потолок {NH.MAX_CULL_PER_HOUR}'
    assert NH.take_cull_slot() == 0, 'бюджет не кончился'
    print(f'  ✓ общий бюджет пересадок: не больше {NH.MAX_CULL_PER_HOUR} в час на всех')


def case_node_breaker_run() -> None:
    """Живой прогон: нода без сети сдаёт три задания подряд — её снимают и пересаживают,
    а сами задания уходят на здоровые ноды и доделываются."""
    nodes = [{'id': 'BAD' + 'b' * 5, 'port': 1, 'group': 'g', 'state': 'running'},
             {'id': 'OK1' + 'c' * 5, 'port': 2, 'group': 'g', 'state': 'running'},
             {'id': 'OK2' + 'd' * 5, 'port': 3, 'group': 'g', 'state': 'running'}]
    S.NODE_COOLDOWN_S, S.POLL_S = 0.1, 0.1
    hits = {1: 0, 2: 0, 3: 0}

    def job_fn(port, job):
        hits[port] += 1
        if port == 1:
            return {'sku': job['sku'], 'status': 'input_failed',
                    'error': '<urlopen error [Errno 101] Network is unreachable>'}
        # здоровые ноды работают заметно дольше битой — иначе прогон кончится раньше, чем
        # та успеет набрать серию, и стенд проверял бы не то
        time.sleep(1.0)
        return {'sku': job['sku'], 'status': 'ok', 'timings_s': {'total': 1}}

    patch.jobs = jobs(14)
    patch(nodes, job_fn)
    code = S.run(None, True, jobs_file='x')
    rows = json.load(open(S.RESULTS, encoding='utf-8'))['results']
    assert code == 0, code
    assert all(r['status'] == 'ok' for r in rows), [r['status'] for r in rows]
    assert nodes[0]['id'] in culled, f'битую ноду не пересадили: {culled}'
    assert NH.is_retired(f'g/{nodes[0]["id"]}'), 'битая нода не помечена снятой'
    assert hits[1] == S.NH.FAIL_STREAK, f'битая нода взяла {hits[1]} заданий вместо порога'
    print(f'  ✓ нода без сети снята и пересажена после {NH.FAIL_STREAK} сбоев подряд')


def case_dead_photo_keeps_node() -> None:
    """Три мёртвые ссылки подряд НЕ повод снимать ноду: виноват товар, а не машина.
    Именно на этом ловил мой первый план — порог «3 подряд input_failed» убил бы здоровую."""
    nodes = [{'id': 'N' * 8, 'port': 1, 'group': 'g', 'state': 'running'},
             {'id': 'M' * 8, 'port': 2, 'group': 'g', 'state': 'running'}]

    def job_fn(port, job):
        return {'sku': job['sku'], 'status': 'input_failed',
                'error': 'HTTP Error 404: Not Found'}

    patch.jobs = jobs(4)
    patch(nodes, job_fn)
    code = S.run(None, True, jobs_file='x')
    st = json.load(open(S.RESULTS, encoding='utf-8'))['summary']
    assert not culled, f'здоровую ноду пересадили из-за мёртвых ссылок: {culled}'
    assert st['unresolved'] == 0 and st['terminal_prefix'] == 4, st
    assert code == 0, code
    print('  ✓ мёртвые ссылки закрывают задание, но ноду не снимают')


def case_spool_keeps_reason() -> None:
    """Задание, пропущенное курсором не по своей вине, обязано лечь в спул — с причиной.
    Раньше такой товар исчезал молча: приёмка его не видит (манифеста ещё нет)."""
    nodes = [{'id': 'A' * 8, 'port': 1, 'group': 'g', 'state': 'running'},
             {'id': 'B' * 8, 'port': 2, 'group': 'g', 'state': 'running'}]
    S.NODE_COOLDOWN_S = 0.1

    def job_fn(port, job):
        return {'sku': job['sku'], 'status': 'input_failed',
                'error': '<urlopen error timed out>'}

    patch.jobs = jobs(2)
    patch(nodes, job_fn)
    S.run(None, True, jobs_file='x')
    recs = [json.loads(x) for x in open(S.RETRY_SPOOL, encoding='utf-8') if x.strip()]
    assert len(recs) == 2, recs
    for r in recs:
        assert r['fault'] == NH.FAULT_UNKNOWN and 'timed out' in r['error'], r
        assert r['retries'] == 1 and r['job']['_retries'] == 1, r
    # счётчик попыток едет внутри задания: спул можно скормить обратно, но не бесконечно
    back = [dict(r['job']) for r in recs]
    open(S.RETRY_SPOOL, 'w', encoding='utf-8').write(
        '\n'.join(json.dumps({'job': j}) for j in back))
    assert len(ORIG_JOBS_FROM_FILE(S.RETRY_SPOOL)) == 2, 'спул не читается обратно'
    for j in back:
        j['_retries'] = S.MAX_SPOOL_RETRIES
    open(S.RETRY_SPOOL, 'w', encoding='utf-8').write(
        '\n'.join(json.dumps({'job': j}) for j in back))
    assert ORIG_JOBS_FROM_FILE(S.RETRY_SPOOL) == [], 'исчерпавшие попытки снова пошли на GPU'
    print('  ✓ пропущенное курсором ложится в спул с причиной и не гоняется вечно')


def case_post_background() -> None:
    """Разбор пачки идёт ФОНОМ и не задерживает следующую генерацию; одновременно — не
    больше одного разбора; конвейер не выходит, пока разбор не доделан."""
    import batch_show as B  # noqa: PLC0415
    started, finished = [], []
    orig = B.post_steps

    def slow_steps():
        def mark(tag):
            started.append(tag)
            time.sleep(0.6)
            finished.append(tag)
            return 0, ''
        return (('стенд', mark),)

    orig_sh = B.sh
    B.post_steps = slow_steps
    B.sh = lambda cmd, timeout=3600: cmd(len(started))    # noqa: B010 — стенд
    B._post['thread'] = None
    try:
        t0 = time.time()
        B.start_post(1)
        # возврат должен быть мгновенным: генерация следующей пачки не ждёт разбора
        assert time.time() - t0 < 0.3, 'start_post заблокировал цикл генерации'
        B.start_post(2)                       # первый ещё идёт — второй ставиться не должен
        assert len(started) == 1, f'запущено два разбора разом: {started}'
        B.wait_post()
        assert finished == [0], f'разбор не доделан к выходу: {finished}'
        B.start_post(3)                       # предыдущий закончился — этот обязан пойти
        B.wait_post()
        assert len(finished) == 2, finished

        # «Занято» (код 75, DRAIN_BUSY у drain.sh) — это НЕ сбой и НЕ успех: шаг не начался.
        # Он не должен останавливать остальные, работу подберёт следующий заход.
        seen = []
        B.post_steps = lambda: (('занятый', 'a'), ('обычный', 'b'))
        B.sh = lambda cmd, timeout=3600: (seen.append(cmd),
                                          (B.BUSY, 'DRAIN_BUSY') if cmd == 'a' else (0, ''))[1]
        B._post['thread'] = None
        B.start_post(4)
        B.wait_post()
        assert seen == ['a', 'b'], f'занятый шаг оборвал разбор: {seen}'
    finally:
        B.post_steps = orig
        B.sh = orig_sh
    print('  ✓ разбор идёт фоном, не дублируется и доделывается перед выходом')


def case_flat_plan() -> None:
    """`total` супервизора и список прогона — из ОДНОГО источника. Расхождение 1465 против
    1503 оставляло 38 последних заданий незапрошенными (нашёл Codex 01.09)."""
    import batch_show as B  # noqa: PLC0415
    if not os.path.exists(S.SAMPLE):
        print('  ~ пропуск: нет mesh-pilot-sample.json')
        return
    raw = len(json.load(open(S.SAMPLE, encoding='utf-8'))['jobs'])
    flat = len(S.plan_jobs())
    assert B.SR is S, 'супервизор считает план не тем же модулем'
    assert flat >= raw, f'плоский список меньше сырого: {flat} < {raw}'
    print(f'  ✓ план из одного источника: {raw} SKU → {flat} заданий (seeds развёрнуты)')


def case_checkpoint() -> None:
    """Падение процесса не должно стирать знание о сделанном."""
    lines = [json.loads(x) for x in open(S.PROGRESS, encoding='utf-8').read().splitlines() if x]
    assert lines and all('sku' in x and 'status' in x for x in lines), lines[:2]
    print(f'  ✓ чекпойнт: {len(lines)} строк, все разбираются')


def case_halt_blocks_start() -> None:
    """Намеренная остановка сильнее автостарта.

    Ночь на 03.09: сторож денег погасил группу на 125 нодо-минутах молчания, а конвейер через
    минуту поднял её обратно — «остановлена» он читал как «надо стартовать». Семь часов ноды
    крутились без единого меша. Стоп-файл делает решение сторожа старше решения конвейера.
    """
    import batch_show as B  # noqa: PLC0415
    assert B.halt_reason() == '', 'без файла запрета быть не должно'
    try:
        with open(B.HALT, 'w', encoding='utf-8') as f:
            json.dump({'why': '125 нодо-минут без единого меша'}, f, ensure_ascii=False)
        assert B.halt_reason() == '125 нодо-минут без единого меша', B.halt_reason()
        assert B.ensure_group_started() is False, 'при запрете группа стартовать НЕ должна'
    finally:
        os.path.exists(B.HALT) and os.remove(B.HALT)
    assert B.halt_reason() == '', 'удаление файла снимает запрет'
    print('  ✓ стоп-файл блокирует подъём группы, снимается только удалением')


def case_preflight_sink_full() -> None:
    """Приёмник не принимает → задания НЕ раздаются, код 75 (нет ёмкости), ни одного /generate."""
    nodes = [{'id': 'A' * 8, 'port': 1, 'group': 'g', 'state': 'running'}]
    calls = []

    def job_fn(port, job):
        calls.append(port)
        return {'sku': job['sku'], 'status': 'ok', 'timings_s': {'total': 1}}

    patch.jobs = jobs(3)
    patch(nodes, job_fn)
    S.sink_preflight = lambda: False          # 507 / канарейка не прошла
    assert S.run(None, True, jobs_file='x') == S.EXIT_NO_CAPACITY
    assert not calls, f'при красном приёмнике ушло заданий: {len(calls)}'
    print('  ✓ красный приёмник → код 75, GPU не тронут')


def case_infra_closes_rest() -> None:
    """Публикация упала (EOF) и приёмник подтвердил беду → остаток закрыт как инфра, нода не виновата."""
    nodes = [{'id': 'A' * 8, 'port': 1, 'group': 'g', 'state': 'running'}]
    hits = []

    def job_fn(port, job):
        hits.append(job['sku'])
        return {'sku': job['sku'], 'status': 'failed',
                'error': 'URLError: <urlopen error EOF occurred in violation of protocol (_ssl.c:2437)>'}

    patch.jobs = jobs(5)
    patch(nodes, job_fn)
    S.sink_poll = lambda force=False: False    # приёмник красный
    code = S.run(None, True, jobs_file='x')
    st = json.load(open(S.RESULTS, encoding='utf-8'))['summary']
    rows = json.load(open(S.RESULTS, encoding='utf-8'))['results']
    assert code == S.EXIT_NO_CAPACITY, code
    assert len(hits) == 1, f'после первого инфра-сбоя ноде дали ещё заданий: {hits}'
    assert st['terminal_prefix'] == 0 and st['unresolved'] == 5, st
    assert sum(1 for r in rows if str(r.get('error', '')).startswith('infra/sink')) == 4, rows
    assert any(r.get('status') == 'failed' for r in rows), 'собственный отказ задания в работе потерян'
    assert not culled, 'ноду пересадили за чужую беду'
    print('  ✓ приёмник красный посреди пачки → остаток закрыт как инфра, курсор на месте, нода цела')


def case_no_double_generate() -> None:
    """Обрыв ПОСРЕДИ генерации (эхо скрипта без маркера) → одна попытка, не две."""
    calls = []

    class R:
        def __init__(self, out):
            self.stdout, self.stderr, self.returncode = out, '', 255
    long_out = 'python - <<RLPY\nimport urllib.request\n' + 'x' * 100 + '\nRLPY\nexit\n> # Traceback'
    real = S.subprocess.run
    S.subprocess.run = lambda *a, **k: (calls.append(1), R(long_out))[1]
    try:
        S.ssh_slot = lambda: None
        r = ORIG_RUN_JOB(1, {'sku': 's', 'role': 'r'})
    finally:
        S.subprocess.run = real
    assert len(calls) == 1, f'вызовов ssh: {len(calls)} — вторая попытка = второй /generate'
    assert r['status'] == 'transport_failed' and r['error'].startswith('ssh/mid_generation'), r
    calls.clear()
    S.subprocess.run = lambda *a, **k: (calls.append(1), R(''))[1]
    try:
        r = ORIG_RUN_JOB(1, {'sku': 's', 'role': 'r'})
    finally:
        S.subprocess.run = real
    assert len(calls) == 2 and r['error'].startswith('ssh/empty'), (len(calls), r)
    print('  ✓ обрыв посреди генерации → 1 попытка (ssh/mid_generation); пустой вывод → 2 (ssh/empty)')


def case_transport_class() -> None:
    """Подклассы обрыва SSH по образцам из журнала."""
    assert NH.transport_class('', '', 255) == 'empty'
    assert NH.transport_class('Connecting to container abc\nfailed to lookup container ID', '', 1) == 'container_id'
    assert NH.transport_class('failed to set user in spec: snapshot x' + ' ' * 40, '', 1) == 'set_user'
    assert NH.transport_class('# python - <<RLPY\nimport urllib\n' + 'x' * 60 + 'RLPY\nexit', '', 1) == 'mid_generation'
    assert NH.error_class({'error': 'ssh/container_id rc=1: …'}) == 'ssh/container_id'
    assert NH.classify({'status': 'failed', 'error': 'HTTP Error 507: nope'}, sink_ok=False) == NH.FAULT_INFRA
    assert NH.classify({'status': 'failed', 'error': 'HTTP Error 507: nope'}, sink_ok=True) == NH.FAULT_UNKNOWN
    assert NH.classify({'status': 'input_failed', 'error': 'EOF occurred in violation of protocol'}, sink_ok=False) != NH.FAULT_INFRA
    print('  ✓ классы транспорта и инфры: 8 проверок')


def case_window_gate() -> None:
    """Окно тарифа — одно правило: batch можно только в 09–15 UTC, low — всегда."""
    import salad_groups as SG  # noqa: PLC0415
    hour = lambda h: time.mktime(time.strptime(f'2026-09-04 {h:02d}:30', '%Y-%m-%d %H:%M')) - time.timezone  # noqa: E731
    assert SG.allowed_now('mesh-batch-1', hour(10)) and not SG.allowed_now('mesh-batch-1', hour(16))
    assert not SG.allowed_now('mesh-batch-2', hour(8)) and SG.allowed_now('mesh-low-2', hour(3))
    assert SG.tier('mesh-low-3') == 'low' and SG.price('mesh-batch-1') == 0.09 and SG.tier('нет-такой') == '?'
    print('  ✓ окно тарифа из rules/salad-groups.json')


def case_group_status_mixed() -> None:
    """Смешанное состояние групп — это состояние ЖИВОЙ части, а не первой в списке."""
    import batch_show as B  # noqa: PLC0415
    real = B.subprocess.run

    class R:
        def __init__(self, s):
            self.stdout = json.dumps({'current_state': {'status': s}})
    seq = iter(['stopped', 'running'])
    B.subprocess.run = lambda *a, **k: R(next(seq))
    os.environ['SALAD_GROUP'] = 'mesh-batch-1,mesh-low-2'
    try:
        assert B.group_status() == 'running', 'stopped первой группы выдали за состояние пула'
        seq = iter(['stopped', 'stopped'])
        assert B.group_status() == 'stopped'
    finally:
        B.subprocess.run = real
    print('  ✓ group_status: stopped только если ВСЕ, иначе живая часть')


def case_burst_counts_cached() -> None:
    """Обвал не объявляется, если рядом живые cached; последний НОВЫЙ меш — только по ok."""
    import money_guard as G  # noqa: PLC0415
    jf = os.path.join(os.path.dirname(S.PROGRESS), 'guard-journal.jsonl')
    now = time.time()
    rows = [{'at': now - 60, 'status': 'failed', 'error': 'URLError: EOF occurred in violation of protocol'}] * 30
    with open(jf, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')
        for _ in range(5):
            f.write(json.dumps({'at': now - 30, 'status': 'cached', 'sku': 'x'}) + '\n')
        f.write(json.dumps({'at': now - 9999, 'status': 'ok', 'sku': 'old'}) + '\n')
    real = G.JOURNAL
    G.JOURNAL = jf
    try:
        assert G.failure_burst() == ('', 0), 'обвал при живых cached — ложная тревога'
        assert abs(G.last_mesh_at() - (now - 9999)) < 1, 'cached посчитан новым мешем'
        with open(jf, 'a', encoding='utf-8') as f:
            pass
        os.replace(jf, jf)     # без cached — обвал
        with open(jf, 'w', encoding='utf-8') as f:
            for r in rows:
                f.write(json.dumps(r) + '\n')
        err, n = G.failure_burst()
        assert n == 30 and 'EOF' in err, (err, n)
    finally:
        G.JOURNAL = real
    print('  ✓ сторож: cached — живой транспорт (обвала нет), но не новый меш')


def case_notify_reports() -> None:
    """notify() честно говорит, доставлено ли, и не роняет сторожа при сбое."""
    import money_guard as G  # noqa: PLC0415
    real = G.subprocess.run

    class R:
        def __init__(self, rc):
            self.returncode = rc
    for rc, want in ((0, True), (1, False), (2, False)):
        G.subprocess.run = lambda *a, rc=rc, **k: R(rc)
        assert G.notify('тест') is want, rc
    G.subprocess.run = real
    print('  ✓ notify(): 0 → доставлено, 1/2 → нет')


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        setup(tmp)
        pure = (case_checkpoint, case_cull_rule, case_fault_classes, case_halt_blocks_start,
                case_transport_class, case_window_gate, case_group_status_mixed,
                case_burst_counts_cached, case_notify_reports)
        for fn in (case_late_node, case_bad_node, case_unresolved, case_prefix,
                   case_stall_is_capacity, case_no_capacity, case_cull_rule, case_checkpoint,
                   case_fault_classes, case_streak_rules, case_streak_survives_restart,
                   case_retire_is_temporary, case_fleet_wide_guard, case_cull_budget_shared, case_node_breaker_run,
                   case_dead_photo_keeps_node, case_spool_keeps_reason,
                   case_post_background, case_flat_plan, case_halt_blocks_start,
                   case_preflight_sink_full, case_infra_closes_rest, case_no_double_generate,
                   case_transport_class, case_window_gate, case_group_status_mixed,
                   case_burst_counts_cached, case_notify_reports):
            if fn not in pure:
                setup(tmp)
            fn()
    print('стенд пула: ВСЁ ЗЕЛЁНОЕ')


if __name__ == '__main__':
    main()
