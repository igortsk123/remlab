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
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import node_health as NH  # noqa: E402
import ssh_run as S  # noqa: E402
import wave_cap as WC  # noqa: E402


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
    # `.done` снимка (план mesh-13) — тоже во временную папку: иначе стенд писал бы рядом с боевым снимком
    S.DONE_SET = os.path.join(tmp, 'snap.json.done')
    S._done_keys = None
    S.cull_slow = lambda: None
    NH.STATE = os.path.join(tmp, 'health.json')
    # Список физических машин (mesh-17) — тоже во временную папку: живой файл держит карантин молчащих машин на сутки
    S.ML.STATE = os.path.join(tmp, 'machines.json')
    # Карантин входа (T-20261022-10 Г) — тоже во временную папку: каждый прогон читает его и выпускает истёкшее,
    # на боевом файле стенд пометил бы живые записи «отданными на проверку», и проверка бы не случилась.
    S.IQ.STATE = os.path.join(tmp, 'input-quarantine.json')
    S.IQ._rules = {'forbidden_marks': ['http error 403'], 'after_n': 2, 'recheck_h': 24, 'node_after_n': 3}   # правило, не живой файл
    # ФАЙЛ ЗАМКА НЕ УДАЛЯЕМ: от прошлого случая могли остаться демон-потоки, и подмена
    # inode'а замка снимает взаимное исключение — два потока писали состояние одновременно.
    for p in (NH.STATE, NH.STATE + '.tmp', S.RETRY_SPOOL, S.DONE_SET, S.IQ.STATE, S.ML.STATE):
        if os.path.exists(p):
            os.remove(p)
    NH.reallocate = lambda group, iid, why: culled.append(iid) or True   # noqa: B010 — стенд
    culled.clear()
    # Ручная волна и стоп-файл (T-20261027-02): `finale()` закрывает ручную волну и снимает свой запрет — на боевых
    # файлах стенд закрыл бы идущую волну и снял настоящий стоп потолка
    WC.PATH = os.path.join(tmp, 'wave-manual.json')
    import batch_show as B  # noqa: PLC0415
    B.HALT = os.path.join(tmp, 'halt.json')


culled: list = []               # кого стенд «пересадил» вместо реального вызова Salad
ORIG_JOBS_FROM_FILE = S.jobs_from_file   # `patch()` его подменяет — держим настоящий
ORIG_RUN_JOB = S.run_job                 # то же: случаю про двойной /generate нужен настоящий
ORIG_SSH_TEXT = S.ssh_text              # то же для ssh_text: случай про адрес шлюза смотрит, куда уходит ssh
ORIG_INSTANCES = S.instances           # `patch()` подменяет список инстансов — случаю про адрес шлюза нужен настоящий
ORIG_REALLOCATE = NH.reallocate          # `setup()` подменяет на запись в `culled` — случаю про 404 нужен настоящий
ORIG_STOP_GROUP = S.stop_group           # `patch()` гасит его заглушкой — случаю про проверку остановки нужен настоящий


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
        # ДОКАЧАВШУЮ НЕ СНИМАЕМ НИКОГДА (05.09). У готовой машины прогресс стоит по
        # определению, поэтому на неё срабатывали ОБА признака — и «нет движения», и «темп
        # ниже нормы»: в логе `100%, темп 0.9%/мин → ещё 0 мин — ПЕРЕСАЖИВАЮ`. Мы выбрасывали
        # машину, только что бесплатно скачавшую 26 ГБ, и платили за прогрев замены.
        ((30 * M, 1.0, 60, 0.009), False, '100%: качать больше нечего, темп не в счёт'),
        ((30 * M, 1.0, 60, 0.0), False, '100% и темп ноль — это готовность, а не смерть'),
        ((90 * M, 1.0, 30 * M, 0.0), False, '100% и час без движения — всё равно не снимать'),
        ((30 * M, 0.998, 60, 0.0), True, '99.8% — ещё качает и стоит: снимать можно'),
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

    НА ВРЕМЕННОМ ПУТИ, А НЕ НА БОЕВОМ (04.09). Случай ходил в живой
    `~/scout-scenes/mesh-group-halt.json`: писал туда фальшивый запрет и удалял его в `finally`.
    Две беды разом. Во-первых, пока фальшивка лежит, её читает РАБОТАЮЩИЙ конвейер и отказывается
    поднимать группы — прогон стенда вмешивался в прод. Во-вторых, при настоящей остановке пула
    стенд краснел на первой же строке (поймано 04.09, когда сторож денег погасил группы), то есть
    ломался ровно тогда, когда за ним и надо было следить.
    """
    import batch_show as B  # noqa: PLC0415
    keep = B.HALT
    B.HALT = os.path.join(tempfile.gettempdir(), 'tests_pool-halt.json')
    try:
        os.path.exists(B.HALT) and os.remove(B.HALT)
        assert B.halt_reason() == '', 'без файла запрета быть не должно'
        with open(B.HALT, 'w', encoding='utf-8') as f:
            json.dump({'why': '125 нодо-минут без единого меша'}, f, ensure_ascii=False)
        assert B.halt_reason() == '125 нодо-минут без единого меша', B.halt_reason()
        assert B.ensure_group_started() is False, 'при запрете группа стартовать НЕ должна'
        os.remove(B.HALT)
        assert B.halt_reason() == '', 'удаление файла снимает запрет'
    finally:
        os.path.exists(B.HALT) and os.remove(B.HALT)
        B.HALT = keep
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
    assert r['status'] == 'transport_failed' and r['error'].startswith('ssh/node_taken'), r
    calls.clear()
    S.subprocess.run = lambda *a, **k: (calls.append(1), R(''))[1]
    try:
        r = ORIG_RUN_JOB(1, {'sku': 's', 'role': 'r'})
    finally:
        S.subprocess.run = real
    assert len(calls) == 2 and r['error'].startswith('ssh/empty'), (len(calls), r)
    print('  ✓ обрыв после посланной команды → 1 попытка (ssh/node_taken); пустой вывод → 2 (ssh/empty)')


def case_transport_class() -> None:
    """Подклассы обрыва SSH по образцам из журнала."""
    assert NH.transport_class('', '', 255) == 'empty'
    assert NH.transport_class('Connecting to container abc\nfailed to lookup container ID', '', 1) == 'container_id'
    assert NH.transport_class('failed to set user in spec: snapshot x' + ' ' * 40, '', 1) == 'set_user'
    assert NH.transport_class('# python - <<RLPY\nimport urllib\n' + 'x' * 60 + 'RLPY\nexit', '', 1) == 'node_taken'
    assert NH.error_class({'error': 'ssh/container_id rc=1: …'}) == 'ssh/container_id'
    assert NH.classify({'status': 'failed', 'error': 'HTTP Error 507: nope'}, sink_ok=False) == NH.FAULT_INFRA
    assert NH.classify({'status': 'failed', 'error': 'HTTP Error 507: nope'}, sink_ok=True) == NH.FAULT_UNKNOWN
    assert NH.classify({'status': 'input_failed', 'error': 'EOF occurred in violation of protocol'}, sink_ok=False) != NH.FAULT_INFRA
    # «машину забрали» (T-20261024-01): не вина ноды — серия не растёт, в сетевые события не попадает
    taken = {'status': 'transport_failed', 'error': 'ssh/node_taken rc=1: RemoteDisconnected'}
    assert NH.classify(taken) == NH.FAULT_UNKNOWN
    assert NH.classify({'status': 'transport_failed', 'error': 'ssh/empty rc=255: '}) == NH.FAULT_NODE
    print('  ✓ классы транспорта и инфры: 10 проверок')


def case_sink_relief_before_red() -> None:
    """Уборка транзита запускается на ЖЁЛТОМ пороге, до остановки пула.

    05.09: за час одна пауза в 17.6 мин — все воркеры разом встали на красном приёмнике
    (`while not _SINK['ok']`) и разом пошли, когда уборка по таймеру освободила место.
    18 минут простоя при ~20 оплаченных машинах = ~7 нодо-часов из 16. Защита сработала верно,
    но уборка была реактивной. Здесь проверяем, что она стала упреждающей — и что дроссель
    не плодит параллельные заходы, пока предыдущий разбор ещё идёт.
    """
    import ssh_run as SR  # noqa: PLC0415
    import sink_health as SH  # noqa: PLC0415
    # ЦЕПОЧКА ОБЯЗАНА УМЕТЬ ОСВОБОЖДАТЬ МЕСТО. `receiver_purge` удаляет комплект, только если он
    # записан в реестр (`ingest_registry`; до 20.10 — метка `mesh_status='ready'` от `mesh_bind`).
    # Уборка «стащить + почистить» печатала «ok» и удаляла НОЛЬ (05.09: 459 комплектов, 7.3 ГБ,
    # «оставляю: нет в базе 459»), пока пул стоял оплаченным на красном приёмнике.
    chain = [c for _, c in SR.SINK_RELIEF_CHAIN]
    order = [i for i, c in enumerate(chain)
             for m in ('drain.sh', 'ingest_registry', 'mesh_bind', 'receiver_purge') if m in c]
    assert len(order) == 4, f'в цепочке уборки не хватает шага: {chain}'
    assert order == sorted(order), f'чистка раньше пометки в базе — удалит ноль: {chain}'
    started = []
    real_thread = SR.threading.Thread
    SR.threading.Thread = lambda target, daemon=None: type(  # noqa: ARG005 — стенд не запускает уборку
        'T', (), {'start': lambda _self: started.append(1)})()
    SR._RELIEF.update(busy=False, at=0.0)
    t = 1_000_000.0

    def at(d: float) -> dict:   # ответ `check()` при каталоге d ГБ и просторном диске
        m = {'free_gb': 30.0, 'dir_gb': d, 'max_dir_gb': 8.0, 'refuses': ''}
        return {**SH.verdict(m), 'tight': SH.tight(m)}
    yellow = SH.tight_dir_gb(8.0)
    try:
        # ниже жёлтого порога — не трогаем: кэш «уже сделано» экономит GPU на повторах
        assert SR.sink_relief(at(yellow - 0.1), t) is False, 'убрал раньше времени'
        assert not started
        # выше жёлтого — запускаем, ДО красной черты (красная = max_dir - 1)
        assert at(yellow + 0.1)['ok'], 'жёлтый порог не раньше ворот'
        assert SR.sink_relief(at(yellow + 0.1), t) is True, 'не убрал на жёлтом'
        assert len(started) == 1
        # пока предыдущая уборка идёт — второй заход не плодим
        assert SR.sink_relief(at(99.0), t + 1) is False, 'запустил вторую уборку поверх идущей'
        SR._RELIEF['busy'] = False
        # дроссель: сразу после уборки не повторяем
        assert SR.sink_relief(at(99.0), t + 1) is False, 'проигнорировал дроссель'
        assert SR.sink_relief(at(99.0), t + SR.SINK_RELIEF_COOLDOWN_S) is True, 'не убрал после дросселя'
        assert len(started) == 2
    finally:
        SR.threading.Thread = real_thread
        SR._RELIEF.update(busy=False, at=0.0)
    print('  ✓ уборка транзита идёт на жёлтом пороге, с дросселем и без наложений')


def case_silent_node_is_zombie() -> None:
    """Молчащая нода становится зомби — но не сразу, и с ОДИНАКОВОЙ причиной для группировки.

    04.09: два детектора зомби расходились. `batch_show.cull_dead_warmups` считал пустой
    `/health` смертью, супервизор `ssh_run` — нет (`warmup_fault({})` пустой). А супервизор
    крутится всё время, пока идёт пачка, тогда как `batch_show` — только между пачками. Итог:
    молчащие ноды часами тарифицировались как `running`, и не снимал их никто.
    """
    import ssh_run as SR  # noqa: PLC0415
    SR._SILENT.clear()
    t0 = 1_000_000.0
    # ответила — приговора нет и таймер молчания сброшен
    assert SR.silent_fault('n1', {'warm': True}, t0) == ''
    # молчит, но недолго — ждём, пересадка стёрла бы скачанный образ (урок 402)
    assert SR.silent_fault('n1', {}, t0) == ''
    assert SR.silent_fault('n1', {}, t0 + SR.SILENT_ZOMBIE_S - 1) == ''
    # молчит дольше порога — приговор
    why = SR.silent_fault('n1', {}, t0 + SR.SILENT_ZOMBIE_S)
    assert why == 'нет ответа по SSH', why
    # причина БЕЗ секунд: иначе одинаковые случаи не схлопнутся и предохранитель
    # «общая беда — не повод менять машины» перестанет срабатывать
    assert SR.silent_fault('n2', {}, t0) == ''
    assert SR.silent_fault('n2', {}, t0 + SR.SILENT_ZOMBIE_S) == why
    # ожила — таймер сбрасывается, повторное молчание считается заново
    assert SR.silent_fault('n1', {'warm': False}, t0 + SR.SILENT_ZOMBIE_S + 1) == ''
    assert SR.silent_fault('n1', {}, t0 + SR.SILENT_ZOMBIE_S + 2) == ''
    # не меньше SILENT_MIN_PROBES проб подряд (mesh-17): одна поздняя проба после порога — ещё не приговор
    keep = SR.SILENT_MIN_PROBES
    SR.SILENT_MIN_PROBES = 3
    try:
        assert SR.silent_fault('n4', {}, t0) == '' and SR.silent_fault('n4', {}, t0 + SR.SILENT_ZOMBIE_S) == ''
        assert SR.silent_fault('n4', {}, t0 + SR.SILENT_ZOMBIE_S + 1) == why
    finally:
        SR.SILENT_MIN_PROBES = keep
    SR._SILENT.clear()
    print('  ✓ молчащая нода — зомби после порога и N проб подряд, причина пригодна для группировки')


def case_window_gate() -> None:
    """Окно тарифа — одно правило: batch можно только в 09–15 UTC, low — всегда.

    НА ФИКСТУРЕ, А НЕ НА ЖИВОМ ФАЙЛЕ (04.09). Раньше тест читал боевой
    `rules/salad-groups.json` и развалился, когда состав пула сменился на `mesh-low-4/5` +
    `mesh-batch-3`: падал не код, а устаревшее имя группы в самом тесте. Стенд обязан
    проверять ПРАВИЛО, а не сегодняшний состав, иначе каждая миграция групп красит его
    в красный и приучает не верить стенду.
    """
    import salad_groups as SG  # noqa: PLC0415
    fixture = {'prices_usd_h': {'batch': 0.09, 'low': 0.143},
               'prices_by_class_usd_h': {'_source': 'стенд', 'RTX X (16 GB)': {'low': 0.10}},
               'usd_rub': 86.89,
               'groups': {'g-batch': {'tier': 'batch', 'window_utc': [9, 15]},
                          'g-cls': {'tier': 'low', 'price_class': 'RTX X (16 GB)'},
                          'g-cls-batch': {'tier': 'batch', 'price_class': 'RTX X (16 GB)'},
                          'g-cls-lost': {'tier': 'low', 'price_class': 'нет в прайсе'},
                          'g-batch-closed': {'tier': 'batch', 'window_utc': [0, 0]},
                          'g-low': {'tier': 'low'}}}
    path = os.path.join(tempfile.gettempdir(), 'tests_pool-salad-groups.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(fixture, f)
    keep_rules, keep_cache = SG.RULES, SG._CACHE
    SG.RULES, SG._CACHE = path, None
    try:
        hour = lambda h: time.mktime(time.strptime(f'2026-09-04 {h:02d}:30', '%Y-%m-%d %H:%M')) - time.timezone  # noqa: E731
        assert SG.allowed_now('g-batch', hour(10)) and not SG.allowed_now('g-batch', hour(16))
        assert not SG.allowed_now('g-batch-closed', hour(8)) and SG.allowed_now('g-low', hour(3))
        assert SG.tier('g-low') == 'low' and SG.price('g-batch') == 0.09 and SG.tier('нет-такой') == '?'
        # цена по классу карты (T-20261024-01); у класса нет тарифа или класса нет в прайсе — цена по тарифу
        assert SG.price('g-cls') == 0.10 and SG.price('g-cls-batch') == 0.09 and SG.price('g-cls-lost') == 0.143
    finally:
        SG.RULES, SG._CACHE = keep_rules, keep_cache
        os.path.exists(path) and os.remove(path)
    # живые правила: класс каждой группы есть в прайсе и с её тарифом — иначе цена молча уедет на запасную
    live = json.load(open(SG.RULES, encoding='utf-8'))
    for g, gi in (live.get('groups') or {}).items():
        if gi.get('price_class'):
            assert gi['tier'] in (live['prices_by_class_usd_h'].get(gi['price_class']) or {}), (g, gi['price_class'])
    print('  ✓ окно тарифа — правило на фикстуре, не на живом составе групп')


def case_group_status_mixed() -> None:
    """Смешанное состояние групп — это состояние ЖИВОЙ части, а не первой в списке."""
    import batch_show as B  # noqa: PLC0415
    real = B.subprocess.run

    class R:
        def __init__(self, s):
            self.stdout = json.dumps({'current_state': {'status': s}})
            self.returncode, self.stderr = 0, ''   # curl теперь проверяется по коду возврата
    seq = iter(['stopped', 'running'])
    B.subprocess.run = lambda *a, **k: R(next(seq))
    keep_grp = os.environ.get('SALAD_GROUP')   # тест не должен менять состав пула соседям
    os.environ['SALAD_GROUP'] = 'mesh-batch-1,mesh-low-2'
    # Ключ читается ИЗ ОКРУЖЕНИЯ до вызова subprocess, поэтому мока мало: без него KeyError
    # ловится внутри `group_status`, статус выходит None, и тест падал только на машине без
    # боевого ключа (04.09). Стенд не должен зависеть от того, что лежит в окружении.
    keep_key = os.environ.get('SALAD_API_KEY')
    os.environ['SALAD_API_KEY'] = 'ключ-для-стенда-запросы-замоканы'
    try:
        assert B.group_status() == 'running', 'stopped первой группы выдали за состояние пула'
        seq = iter(['stopped', 'stopped'])
        assert B.group_status() == 'stopped'
    finally:
        B.subprocess.run = real
        for k, v in (('SALAD_API_KEY', keep_key), ('SALAD_GROUP', keep_grp)):
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    print('  ✓ group_status: stopped только если ВСЕ, иначе живая часть')


def case_step_timeout_kills_children() -> None:
    """Таймаут шага снимает ВСЮ группу процессов, а не только `/bin/sh`-обёртку.

    05.09: шаг топ-вью падал по таймауту, `subprocess.run` убивал обёртку
    `/bin/sh -c 'while ...; do python topview_render.py; done'`, а python оставался жить с
    `ppid=1`. Пост-разбор идёт каждые MESH_POST_EVERY_S, поэтому сироты копились: к 10:00 их
    было 20, старейшая работала 21 ч 44 мин. Цена — съеденная память дев-машины (trimesh её не
    отдаёт, урок 391) и блокировка перезапуска: новый конвейер честно ждёт сирот, а ноды всё
    это время оплачиваются.
    """
    import batch_show as B  # noqa: PLC0415

    def _alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True       # процесс есть, просто чужой — «нет прав» это НЕ «умер»
        return True

    def _run_case(child: str, note: str) -> None:
        fd, pidfile = tempfile.mkstemp(prefix='tests_pool-child-', suffix='.pid')
        os.close(fd)
        t0 = time.time()
        rc, out = B.sh(f'{child} & echo $! > {pidfile}; sleep 120', timeout=2)
        assert rc == 124, f'{note}: ожидали таймаут 124, получили {rc}: {out[:150]}'
        assert time.time() - t0 < 40, f'{note}: sh() завис вместо того, чтобы добить шаг'
        pid = int(open(pidfile, encoding='utf-8').read().strip())
        os.remove(pidfile)
        for _ in range(150):      # даём ядру дожать сигнал и init — прибрать зомби
            if not _alive(pid):
                return
            time.sleep(0.1)
        os.kill(pid, 9)           # не оставляем сироту после самого теста
        raise AssertionError(f'{note}: потомок {pid} пережил таймаут — это и есть утечка сирот')

    _run_case('sleep 120', 'послушный потомок')
    # УПРЯМЫЙ ПОТОМОК — иначе ветка SIGKILL не проверена вообще. Первая версия правки
    # эскалировала по смерти ОБОЛОЧКИ: shell честно умирал от SIGTERM, код выходил довольным,
    # а игнорирующий TERM внук жил дальше — утечка воспроизводилась в самом лекарстве.
    _run_case("/bin/sh -c \"trap '' TERM; sleep 120\"", 'потомок игнорирует SIGTERM')
    # СОСЕД НЕ ПОСТРАДАЛ: killpg обязан бить только группу шага
    neighbour = subprocess.Popen(['sleep', '30'])
    try:
        _run_case('sleep 120', 'при живом соседе')
        assert neighbour.poll() is None, 'killpg задел посторонний процесс — это авария изоляции'
    finally:
        neighbour.kill()
        neighbour.wait()
    print('  ✓ таймаут шага убивает всю группу (и упрямого потомка), соседей не трогает')


def case_no_restart_of_running_group() -> None:
    """Уже поднятую группу повторно не стартуем.

    05.09: `/start` живой группы Salad отбивает как `400 replicas_quota_exceeded` (квота реплик
    уже разобрана ею же). Работе не мешает, но в логе неотличим от настоящей беды — тем же
    кодом 400 приходит `no_credits_available` (урок 404). Лишний шум прячет реальный отказ.
    """
    import urllib.request  # noqa: PLC0415

    import batch_show as B  # noqa: PLC0415
    started, keep_states, keep_open = [], B.group_states, urllib.request.urlopen
    keep_grp, keep_key, keep_halt = (os.environ.get('SALAD_GROUP'),
                                     os.environ.get('SALAD_API_KEY'), B.HALT)
    os.environ['SALAD_GROUP'] = 'g-run,g-down'
    os.environ['SALAD_API_KEY'] = 'ключ-для-стенда-запросы-замоканы'
    # HALT ПОДМЕНЯЕМ, А НЕ УДАЛЯЕМ. Первая версия теста делала `os.remove(B.HALT)` по боевому
    # пути: прогон стенда рядом с работающим конвейером снял бы запрет сторожа и вернул платные
    # ноды — ровно та беда, от которой этот запрет и стоит (находка Codex 05.09).
    B.HALT = os.path.join(tempfile.gettempdir(), 'tests_pool-halt-start.json')
    os.path.exists(B.HALT) and os.remove(B.HALT)

    class _Resp:
        def read(self):
            return b''

    def _fake_open(req, timeout=0):
        started.append(req.full_url.rsplit('/containers/', 1)[-1])
        return _Resp()

    urllib.request.urlopen = _fake_open
    try:
        B.group_states = lambda: {'g-run': 'running', 'g-down': 'stopped'}
        assert B.ensure_group_started() is True, 'живой пул должен считаться поднятым'
        assert started == ['g-down/start'], f'тронули лишнее: {started}'
        # НЕЗНАКОМОЕ И НЕЧИТАЕМОЕ СОСТОЯНИЕ — ПОВОД ПОПРОБОВАТЬ, а не записать в живые: иначе
        # при сбое API или новом статусе Salad группу не поднимет никто и пул встанет молча.
        started.clear()
        B.group_states = lambda: {'g-run': 'чего-то-новое', 'g-down': None}
        B.ensure_group_started()
        assert sorted(started) == ['g-down/start', 'g-run/start'], f'не пробовали поднять: {started}'
        # и НИ ОДНОГО повторного /start той группе, которую только что стартовали (гонка с
        # согласованием состояния на стороне Salad)
        started.clear()
        B.group_states = lambda: {'g-run': 'stopped', 'g-down': 'stopped'}
        B.ensure_group_started()
        assert started == ['g-run/start', 'g-down/start'], f'повторный старт: {started}'
    finally:
        B.group_states, urllib.request.urlopen, B.HALT = keep_states, keep_open, keep_halt
        for k, v in (('SALAD_GROUP', keep_grp), ('SALAD_API_KEY', keep_key)):
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    print('  ✓ /start шлём лежащим и непонятным, живым — нет, повторно — нет')


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


def case_alarm_before_halt() -> None:
    """Ранняя тревога обязана срабатывать РАНЬШЕ гашения, иначе она бесполезна.

    05.09 (цель владельца «меш не дороже 1.5 ₽»): цену портит не тариф, а остановки — платим за
    `running` всегда, мешей в это время нет. Порог гашения (120 нодо-минут + 40 мин) — защита от
    разорения, а не инструмент цены: пока он ждёт, простой уже сделан. Тревога должна кричать
    втрое раньше; если пороги когда-нибудь сравняются, она просто не успеет.
    """
    import money_guard as G  # noqa: PLC0415
    assert G.ALARM_NODE_MIN < G.BUDGET_NODE_MIN, 'тревога не раньше гашения по нодо-минутам'
    assert G.ALARM_WALL_MIN < G.MIN_WALL_MIN, 'тревога не раньше гашения по времени тишины'
    assert G.ALARM_WALL_MIN >= 5, 'слишком рано: прогрев ноды укладывается в 5–8 минут'
    # состав шагов лечения у сторожа — тот же, что у конвейера (одна цепочка на всех)
    assert G.SR.SINK_RELIEF_CHAIN and any('mesh_bind' in c for _, c in G.SR.SINK_RELIEF_CHAIN)
    print('  ✓ тревога сторожа срабатывает раньше гашения и лечит той же цепочкой')


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


def case_hot_restart() -> None:
    """Горячий перезапуск: флаг draining → finale не гасит группы и снимает флаг; второй
    экземпляр не получает замок и НЕ гасит группы работающего; курсор пишется атомарно."""
    import batch_show as B  # noqa: PLC0415
    stopped = []
    B.sh = lambda cmd, timeout=3600: (stopped.append(cmd), (0, ''))[1]
    B.wait_post = lambda: None
    tmp = tempfile.mkdtemp()
    B.DRAINING, B.LOCK, B.DONE = (os.path.join(tmp, 'draining'), os.path.join(tmp, 'lock'),
                                  os.path.join(tmp, 'progress.json'))
    # 1) не стартовал — не гасит
    B._STARTED = False
    B.finale()
    assert not stopped, 'finale без замка погасил группы'
    # 2) замок + draining → группы целы, флаг снят
    B.acquire_singleton()
    open(B.DRAINING, 'w').close()
    B.finale()
    assert not stopped and not os.path.exists(B.DRAINING), (stopped, os.path.exists(B.DRAINING))
    # 3) второй экземпляр — SystemExit, замок не отдан
    import subprocess as sp
    r = sp.run([sys.executable, '-c',
                f"import sys, os; sys.path.insert(0, {os.path.dirname(os.path.abspath(__file__))!r}); "
                f"os.environ['SALAD_GROUP']='g'; os.environ['SALAD_API_KEY']='x'; import batch_show as B; "
                f"B.LOCK={B.LOCK!r}; B.acquire_singleton()"], capture_output=True, text=True)
    assert r.returncode != 0 and 'уже работает' in (r.stderr + r.stdout), (r.returncode, r.stderr[-200:])
    # 4) обычный финал гасит ровно один раз
    B.finale()
    assert len(stopped) == 2 and 'stop_group' in stopped[0], stopped
    # 5) курсор атомарно
    B.save_cursor(42)
    assert json.load(open(B.DONE))['done'] == 42 and not os.path.exists(B.DONE + '.tmp')
    print('  ✓ горячий перезапуск: draining не гасит, второй экземпляр не проходит, курсор атомарен')


def case_stop_verified() -> None:
    """conv-11: «/stop принят» ≠ «остановлено». Группа, не дошедшая до stopped, — провал (деньги идут);
    дошедшая — успех; отказ /stop — провал без ожидания."""
    import io
    import urllib.error
    keep_open, keep_groups, keep_key = urllib.request.urlopen, S.GROUPS, S.key
    states = {'g1': ['stopping', 'stopped'], 'g2': ['running', 'running', 'running']}
    posted = []

    def fake_open(req, timeout=0):
        url = req.full_url
        if url.endswith('/stop'):
            g = url.split('/')[-2]
            if g == 'g3':
                raise urllib.error.HTTPError(url, 500, 'x', {}, io.BytesIO(b'boom'))
            posted.append(g)
            return io.BytesIO(b'{}')
        g = url.rsplit('/', 1)[-1]
        seq = states[g]
        st = seq.pop(0) if len(seq) > 1 else seq[0]
        return io.BytesIO(json.dumps({'current_state': {'status': st}}).encode())

    try:
        urllib.request.urlopen, S.key = fake_open, (lambda: 'k')
        S.GROUPS = ['g1']
        assert ORIG_STOP_GROUP(wait_s=5, poll_s=0.01) is True, 'дошла до stopped — успех'
        S.GROUPS = ['g1', 'g2']
        states['g1'] = ['stopped']
        assert ORIG_STOP_GROUP(wait_s=0.2, poll_s=0.01) is False, 'running после ожидания — провал'
        S.GROUPS = ['g3']
        assert ORIG_STOP_GROUP(wait_s=5, poll_s=0.01) is False, 'отказ /stop — провал'
        assert posted.count('g1') == 2 and 'g3' not in posted, posted
    finally:
        urllib.request.urlopen, S.GROUPS, S.key = keep_open, keep_groups, keep_key
    print('  ✓ остановка групп проверяется: stopped — успех, running/отказ — провал')


def case_cursor_on_stall() -> None:
    """Пачка кончилась пропажей машин (75), но итог в ней есть: курсор обязан сдвинуться на `terminal_prefix`,
    а следующая пачка — начаться с него (план mesh-13). Раньше 75 уводил в ожидание до чтения итога, и ночь
    20→21.10 пять вызовов подряд шли с `--skip 0`."""
    import types
    import batch_show as B  # noqa: PLC0415
    calls = []
    outs = [(75, 'RUN_SUMMARY {"requested": 2000, "terminal": 15, "terminal_prefix": 14, "unresolved": 1986}\n'
                 '!! нет живых нод 30 мин — закрываю остаток'),
            (75, 'нет прогретых нод'),
            (0, 'RUN_SUMMARY {"requested": 2000, "terminal": 5, "terminal_prefix": 5, "unresolved": 0}')]
    keep = {k: getattr(B, k) for k in ('sh', 'DONE', 'group_status', 'cull_slow_pulls', 'cull_dead_warmups',
                                       'drain_retry_spool', 'start_post', 'time')}
    tmp = tempfile.mkdtemp()
    try:
        B.sh = lambda cmd, timeout=3600: (calls.append(cmd), outs[len(calls) - 1])[1]
        B.DONE = os.path.join(tmp, 'snap.json.progress.json')
        B.group_status = lambda states=None: 'running'
        B.cull_slow_pulls = B.cull_dead_warmups = B.drain_retry_spool = lambda: None
        B.start_post = lambda tag: None
        B.time = types.SimpleNamespace(sleep=lambda s: None, time=time.time)
        done, nxt = B.run_batch(0, 2000, 2592)
        assert (done, nxt) == (14, 'wait'), (done, nxt)
        assert json.load(open(B.DONE))['done'] == 14, 'курсор не сохранён после 75'
        done, nxt = B.run_batch(done, 2000, 2592)       # нод нет, итога нет — курсор стоит
        assert (done, nxt) == (14, 'wait'), (done, nxt)
        done, nxt = B.run_batch(done, 2000, 2592)
        assert '--skip 14 ' in calls[1] and '--skip 14 ' in calls[2], calls
        assert (done, nxt) == (19, 'next') and json.load(open(B.DONE))['done'] == 19, (done, nxt)
    finally:
        for k, v in keep.items():
            setattr(B, k, v)
    print('  ✓ 75 с итогом: курсор 14 сохранён, следующие пачки идут с --skip 14')


def case_wave_tail_order() -> None:
    """Конец волны (план mesh-18 этап 4, T-20261027-02): GPU-перегон → гашение групп → фоновый разбор. Проба 27.10: группа
    ждала разбор 29 мин после последнего меша (≈ 40 % денег). Перегон — по снимку файла, битый файл (его пишет приёмка
    разбора) перегон не теряет: файл цел и уйдёт следующей волной, а группы гаснут всё равно."""
    import batch_show as B  # noqa: PLC0415
    ev = []
    keep = {k: getattr(B, k) for k in ('sh', 'RESEED', 'wait_post', 'post_steps', 'ensure_group_started',
                                       'cull_slow_pulls')}
    tmp = tempfile.mkdtemp()
    pause = os.path.join(tmp, 'PAUSE')

    def fake_sh(cmd, timeout=3600):
        ev.append('heal:' + cmd.split('--jobs-file ')[1].split()[0] if '--jobs-file' in cmd
                  else 'stop' if 'stop_group' in cmd else 'post:' + cmd)
        return 0, 'RUN_SUMMARY {"requested": 1, "terminal": 1, "terminal_prefix": 1, "unresolved": 0}'

    try:
        B.sh, B.RESEED = fake_sh, os.path.join(tmp, 'mesh-reseed.json')
        B.wait_post = lambda: ev.append('wait_post')
        B.post_steps = lambda: (('шаг', 'p'),)
        B.ensure_group_started = B.cull_slow_pulls = lambda: None
        # 1) перегон есть → он ДО гашения, разбор — после, без машин
        json.dump([{'sku': 'a', 'seed': 1}], open(B.RESEED, 'w'))
        with contextlib.redirect_stdout(io.StringIO()):
            B.wave_tail(pause, guard_done=True)
        assert ev == ['heal:' + B.RESEED + '.heal', 'stop', 'wait_post', 'post:p'], ev
        assert json.load(open(B.RESEED + '.heal')) == [{'sku': 'a', 'seed': 1}], 'перегону отдан не снимок'
        # 2) перегона нет → гашение раньше ожидания разбора, лишнего разбора нет
        ev.clear()
        json.dump([], open(B.RESEED, 'w'))
        with contextlib.redirect_stdout(io.StringIO()):
            B.wave_tail(pause, guard_done=True)
        assert ev == ['stop', 'wait_post'], ev
        # 3) файл перегона недописан приёмкой → не падаем, группы гасим, файл не тронут (уйдёт следующей волной)
        ev.clear()
        open(B.RESEED, 'w').write('[{"sku": "a", "se')
        with contextlib.redirect_stdout(io.StringIO()):
            B.wave_tail(pause, guard_done=True)
        assert ev == ['stop', 'wait_post'] and open(B.RESEED).read() == '[{"sku": "a", "se', ev
        # 4) пауза владельца → перегона нет, гашение есть
        ev.clear()
        json.dump([{'sku': 'a', 'seed': 1}], open(B.RESEED, 'w'))
        open(pause, 'w').close()
        with contextlib.redirect_stdout(io.StringIO()):
            B.wave_tail(pause, guard_done=True)
        assert ev == ['stop', 'wait_post'], ev
    finally:
        for k, v in keep.items():
            setattr(B, k, v)
    print('  ✓ конец волны: перегон до гашения, гашение до разбора; битый файл перегона не теряется')


def case_budget_halt_ends_wave() -> None:
    """Сторож денег погасил пул по потолку волны (стоп-файл kind=budget) → конвейер выходит, а не ждёт тёплых нод под
    запретом вечно; другой запрет (тишина) — по-прежнему ждём (T-20261027-02)."""
    import types
    import batch_show as B  # noqa: PLC0415
    keep = {k: getattr(B, k) for k in ('sh', 'HALT', 'group_status', 'ensure_group_started', 'cull_slow_pulls',
                                       'cull_dead_warmups', 'time')}
    tmp = tempfile.mkdtemp()
    try:
        B.sh = lambda cmd, timeout=3600: (75, 'нет прогретых нод')
        B.HALT = os.path.join(tmp, 'halt.json')
        B.group_status = lambda states=None: 'stopped'
        B.ensure_group_started = lambda: False
        B.cull_slow_pulls = B.cull_dead_warmups = lambda: None
        B.time = types.SimpleNamespace(sleep=lambda s: None, time=time.time)
        json.dump({'why': 'ПОТОЛОК', 'kind': 'budget', 'source': 'manual'}, open(B.HALT, 'w'))
        with contextlib.redirect_stdout(io.StringIO()):
            assert B.run_batch(5, 10, 20) == (5, 'exit'), 'потолок выбран — конвейер обязан выйти'
        json.dump({'why': 'тишина', 'kind': 'silence'}, open(B.HALT, 'w'))
        with contextlib.redirect_stdout(io.StringIO()):
            assert B.run_batch(5, 10, 20) == (5, 'wait'), 'запрет тишины — ждём, как раньше'
    finally:
        for k, v in keep.items():
            setattr(B, k, v)
    print('  ✓ потолок денег волны выбран → конвейер выходит; запрет тишины — ждёт')


def case_manual_cap() -> None:
    """Ручной старт без потолка ₽ — отказ ДО любых шагов; finale закрывает ручную волну и снимает только СВОЙ стоп-файл
    потолка (T-20261027-02)."""
    import batch_show as B  # noqa: PLC0415
    import wave_cap as WC  # noqa: PLC0415
    import money_guard as MG  # noqa: PLC0415
    tmp = tempfile.mkdtemp()
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'mesh_wave_start.sh')
    env = {k: v for k, v in os.environ.items() if k not in ('MESH_RUB_CAP', 'MESH_WAVE_LEASE')}
    env['HOME'] = tmp                        # ни боевого замка, ни salad.env: отказ обязан случиться раньше них
    for args in (['--launch'], ['--launch', '--rub-cap', '0'], ['--launch', '--rub-cap', 'abc'], ['--launch', '--rub-cap']):
        r = subprocess.run(['bash', script, *args], env=env, capture_output=True, text=True, timeout=30)
        assert r.returncode == 64 and 'без потолка' in r.stdout, (args, r.returncode, r.stdout[-200:], r.stderr[-200:])
    assert not os.path.exists(os.path.join(tmp, 'scout-scenes')), 'отказ тронул ~/scout-scenes'
    keep = (WC.PATH, B.HALT, MG.load, B.SG.usd_rub)
    try:
        WC.PATH, B.HALT = os.path.join(tmp, 'manual.json'), os.path.join(tmp, 'halt.json')
        MG.load = lambda: {'paid_node_min': {'g': 600}}
        B.SG.usd_rub = lambda: 87.0
        WC.open_wave(174, 87.0, 0.0, 's.json')
        json.dump({'kind': 'budget', 'source': 'manual'}, open(B.HALT, 'w'))
        with contextlib.redirect_stdout(io.StringIO()):
            B.close_manual_cap()
        w = WC.read()['waves'][-1]
        assert w.get('closed') and w['why'] == 'конвейер завершился' and 'spent_rub' in w, w
        assert not os.path.exists(B.HALT), 'свой стоп-файл потолка не снят'
        json.dump({'kind': 'budget'}, open(B.HALT, 'w'))          # потолок разрешения владельца — не наш
        with contextlib.redirect_stdout(io.StringIO()):
            B.close_manual_cap()
        assert os.path.exists(B.HALT), 'снят чужой стоп-файл'
    finally:
        WC.PATH, B.HALT, MG.load, B.SG.usd_rub = keep
    print('  ✓ ручной старт без потолка — отказ до шагов; finale закрывает ручную волну и снимает только свой запрет')


def case_done_set() -> None:
    """Идемпотентность по снимку (план mesh-13): сделанное ok/cached ложится в `<снимок>.done` атомарно и
    переживает перезапуск; срез с уже сделанным не раздаёт его нодам, но курсор проходит его целиком."""
    S.mark_done('sku0', 0)
    S.mark_done('sku0', 0)
    S.mark_done('sku1', None)
    S._done_keys = None                                    # новый процесс ssh_run
    assert S.done_keys() == {('sku0', 0), ('sku1', 0)}, S.done_keys()
    assert not os.path.exists(S.DONE_SET + '.tmp'), 'tmp не переименован'
    nodes = [{'id': 'A' * 8, 'port': 1, 'group': 'g', 'state': 'running'}]
    sent = []

    def job_fn(port, job):
        sent.append(job['sku'])
        return {'sku': job['sku'], 'status': 'ok', 'timings_s': {'total': 1}}

    keep = S.jobs_from_sample
    try:
        patch.jobs = []
        patch(nodes, job_fn)
        S.jobs_from_sample = lambda limit: jobs(4)
        code = S.run(4, True, skip=0)
        st = json.load(open(S.RESULTS, encoding='utf-8'))['summary']
        assert code == 0 and sorted(sent) == ['sku2', 'sku3'], (code, sent)
        assert st['terminal_prefix'] == 4, st
        assert ('sku3', 0) in S.done_keys(), 'новый ok не записан в .done'
        # весь срез сделан — ни одной ноды не спрашиваем, курсор проходит срез
        S.instances = lambda: (_ for _ in ()).throw(AssertionError('спросил ноды при сделанном срезе'))
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            code = S.run(4, True, skip=0)
        assert code == 0 and '"terminal_prefix": 4' in buf.getvalue(), (code, buf.getvalue()[-200:])
        assert NH.classify({'status': 'done_before'}) == NH.FAULT_NONE
    finally:
        S.jobs_from_sample = keep
    print('  ✓ .done: атомарно, переживает перезапуск, сделанное не раздаётся, курсор проходит срез')


def case_taken_no_streak() -> None:
    """«Машину забрали» (ssh/node_taken) не пишет машине серию: три таких обрыва подряд — серия 0, не снята."""
    key = 'g/TAKEN000'
    for _ in range(NH.FAIL_STREAK):
        n = NH.record(key, NH.classify({'status': 'transport_failed', 'error': 'ssh/node_taken rc=1: x'}), 'ssh/node_taken')
    assert n == 0 and not NH.is_retired(key), n
    assert not NH.fleet_wide('ssh/node_taken'), 'забранные машины посчитаны общей бедой сети'
    print(f'  ✓ «машину забрали» {NH.FAIL_STREAK} раза подряд — серия 0, машина не снята')


def case_realloc_404_returns_slot() -> None:
    """Пересадка, на которую Salad ответил 404 (инстанса уже нет), слот бюджета не тратит; другая ошибка — тратит."""
    import urllib.error  # noqa: PLC0415
    keep_open, keep_key = NH.urllib.request.urlopen, os.environ.get('SALAD_API_KEY')
    os.environ['SALAD_API_KEY'] = 'x'
    culls = lambda: len(NH.snapshot()['culls'])   # noqa: E731

    def fail(code):
        def _open(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, code, 'x', {}, None)
        return _open
    try:
        assert NH.take_cull_slot() == 1 and culls() == 1
        NH.urllib.request.urlopen = fail(404)
        assert ORIG_REALLOCATE('g', 'gone0000', 'тест') is False
        assert culls() == 0, 'слот за 404 сгорел'
        assert NH.take_cull_slot() == 1
        NH.urllib.request.urlopen = fail(500)
        assert ORIG_REALLOCATE('g', 'err00000', 'тест') is False
        assert culls() == 1, 'слот за настоящую ошибку вернулся — лимит перестал бы защищать'
    finally:
        NH.urllib.request.urlopen = keep_open
        os.environ.pop('SALAD_API_KEY', None) if keep_key is None else os.environ.__setitem__('SALAD_API_KEY', keep_key)
    print('  ✓ пересадка: 404 — слот вернулся, 500 — слот потрачен')


def case_ssh_addr() -> None:
    """Адрес шлюза SSH — из того же ответа API, что и порт (T-20261024-01): пара сохраняется, уходит в ssh, разные
    `ssh_ip` с одним портом — разные адреса; без `ssh_ip` — запасной адрес и WARN; в журнал — ip, порт, машина."""
    keep_api, keep_groups, keep_run = S.api, S.GROUPS, S.subprocess.run
    S.GROUPS = ['g']
    S.api = lambda path: {'instances': [
        {'id': 'I1' + 'a' * 6, 'started': True, 'state': 'running', 'ssh_port': 20001, 'ssh_ip': '10.0.0.1', 'machine_id': 'M1'},
        {'id': 'I2' + 'b' * 6, 'started': True, 'state': 'running', 'ssh_port': 20001, 'ssh_ip': '10.0.0.2', 'machine_id': 'M2'},
        {'id': 'I3' + 'c' * 6, 'started': True, 'state': 'running', 'ssh_port': 20003, 'machine_id': 'M3'}]}
    argv = []

    class R:
        stdout, stderr, returncode = 'ok', '', 0
    S.subprocess.run = lambda a, **k: (argv.append(a), R())[1]
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            ins = ORIG_INSTANCES()
        p1, p2, p3 = (i['port'] for i in ins)
        assert p1 == 20001 and p1.ip == '10.0.0.1' and p2.ip == '10.0.0.2', ins
        assert p1 != p2 and len({p1, p2}) == 2, 'один порт на двух шлюзах слился в один адрес'
        assert p1 == S.Addr(20001, '10.0.0.1') and str(p1) == '20001' and f'{p1}' == '20001'
        S.ssh_slot = lambda: None
        ORIG_SSH_TEXT(p1, 'true')
        ORIG_SSH_TEXT(p2, 'true')
        ORIG_SSH_TEXT(p3, 'true')
        ORIG_SSH_TEXT(7, 'true')                                  # голое число — старые вызовы и стенд
        hosts = [a[-1] for a in argv]
        assert hosts == ['root@10.0.0.1', 'root@10.0.0.2', S.SSH_HOST, S.SSH_HOST], hosts
        assert all(a[a.index('-p') + 1] in ('20001', '20003', '7') for a in argv), argv
        assert 'WARN' in out.getvalue() and 'I3cccccc'[:8] in out.getvalue(), out.getvalue()
        f = S.addr_fields('I2' + 'b' * 6, p2)
        assert f == {'ssh_ip': '10.0.0.2', 'ssh_port': 20001, 'machine': 'M2'}, f
    finally:
        S.api, S.GROUPS, S.subprocess.run = keep_api, keep_groups, keep_run
    print('  ✓ адрес шлюза из API: пара в ssh, разные шлюзы — разные адреса, без ssh_ip — запасной и WARN, поля журнала')


def case_silent_machines() -> None:
    """Молчащие по SSH — своим правилом (mesh-17, T-20261024-01). Одна машина работает, две молчат: та, чей machine_id
    уже молчал, пересажена СРАЗУ; новая — после порога, по своему бюджету, и её machine_id попал в список; общий лимит
    пересадок не тронут, повторов нет. Молчат все и никто не работает — машины не трогаем (это шлюз или сеть)."""
    keep = (S.SILENT_ZOMBIE_S, S.ML.FAST_MAX)
    S.SILENT_ZOMBIE_S = 0.5
    S._SILENT.clear()
    nodes = [{'id': 'W' * 8, 'port': 1, 'group': 'g', 'state': 'running', 'machine': 'MW'},
             {'id': 'S' * 8, 'port': 2, 'group': 'g', 'state': 'running', 'machine': 'MS1'},
             {'id': 'N' * 8, 'port': 3, 'group': 'g', 'state': 'running', 'machine': 'MS2'}]

    def job_fn(port, job):
        time.sleep(0.4)
        return {'sku': job['sku'], 'status': 'ok', 'timings_s': {'total': 1}}
    patch.jobs = jobs(8)
    patch(nodes, job_fn)
    S.probe_warm = lambda port: port == 1
    S.probe_health = lambda port: {'ok': True, 'warm': True, 'done': 0} if port == 1 else {}
    S.ML.mark_silent('MS1', 'old-instance')               # молчала в прошлой выдаче
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            code = S.run(None, True, jobs_file='x')
    finally:
        S.SILENT_ZOMBIE_S = keep[0]
    log = out.getvalue()
    assert code == 0, (code, log[-600:])
    assert culled.count('S' * 8) == 1 and culled.count('N' * 8) == 1 and 'W' * 8 not in culled, culled
    assert culled.index('S' * 8) < culled.index('N' * 8), f'знакомую молчащую не пересадили первой: {culled}'
    assert 'уже молчала по SSH — ПЕРЕСАЖИВАЮ сразу' in log and 'в список молчащих' in log, log[-800:]
    assert S.ML.is_silent('MS2') and not S.ML.is_silent('MW'), 'список машин не обновлён'
    st = NH.snapshot()
    assert st['culls'] == [] and len(st['silent_culls']) == 1, st
    # все молчат, работающих нет — разбор круга: шлюз недостижим, на пересадку никого (это шлюз или сеть)
    S._SILENT.clear()
    S.SILENT_ZOMBIE_S = 0.5
    q = [{'id': 'Q' * 8, 'port': 4, 'group': 'g', 'machine': 'MS2'}, {'id': 'R' * 8, 'port': 5, 'group': 'g', 'machine': 'MR'}]
    t = time.time()
    S.sort_probes(q, [{}, {}], False, {}, t)
    reach, z, sil, fast = S.sort_probes(q, [{}, {}], False, {}, t + 1)
    assert not reach and not fast and len(sil) == 2 and not z, (reach, sil, fast)
    # тот же круг, но один воркер работает — знакомая молчащая MS2 идёт на пересадку сразу
    reach, z, sil, fast = S.sort_probes(q, [{}, {}], True, {}, t + 2)
    assert reach and [i['id'] for i in fast] == ['Q' * 8], (reach, fast)
    S.SILENT_ZOMBIE_S = keep[0]
    S._SILENT.clear()
    # не больше FAST_MAX быстрых пересадок одной машины за сутки — затем пауза (обычный путь)
    S.ML.mark_silent('MF')
    got = [S.ML.take_fast('MF') for _ in range(S.ML.FAST_MAX + 1)]
    assert got == [True] * S.ML.FAST_MAX + [False] and not S.ML.take_fast('MW'), got
    print('  ✓ молчащие: знакомая машина — сразу, новая — после порога своим бюджетом, в список; шлюз недостижим — не трогаем')


def case_batch_show_silent() -> None:
    """Пересадка зомби между пачками (`batch_show.cull_dead_warmups`) — то же правило молчащих (mesh-17): одна нода
    отвечает — молчащая пересажена своим бюджетом, её машина в списке; молчат все — «наша беда», никого не трогаем."""
    import urllib.request as U  # noqa: PLC0415
    import batch_show as B  # noqa: PLC0415
    old = time.strftime('%Y-%m-%dT%H:%M:%S.1234567+00:00', time.gmtime(time.time() - 1200))   # 20 мин — не молодая
    ins = [{'id': 'A' * 8, 'state': 'running', 'ssh_port': 1, 'ssh_ip': '10.0.0.1', 'machine_id': 'MA', 'update_time': old},
           {'id': 'B' * 8, 'state': 'running', 'ssh_port': 2, 'ssh_ip': '10.0.0.2', 'machine_id': 'MB', 'update_time': old}]

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    keep = (U.urlopen, B.SG.groups_from_env, S.probe_health, os.environ.get('SALAD_API_KEY'))
    U.urlopen = lambda req, timeout=0: Resp(json.dumps({'instances': ins}).encode())
    B.SG.groups_from_env = lambda: ['g']
    os.environ['SALAD_API_KEY'] = 'x'
    out = io.StringIO()
    try:
        S.probe_health = lambda port: {'ok': True, 'warm': True} if port == 1 and port.ip == '10.0.0.1' else {}
        with contextlib.redirect_stdout(out):
            B.cull_dead_warmups()
        assert culled == ['B' * 8] and S.ML.is_silent('MB') and not S.ML.is_silent('MA'), (culled, out.getvalue())
        assert len(NH.snapshot()['silent_culls']) == 1 and NH.snapshot()['culls'] == []
        culled.clear()
        S.probe_health = lambda port: {}
        with contextlib.redirect_stdout(out):
            B.cull_dead_warmups()
        assert culled == [] and 'это наша беда' in out.getvalue(), (culled, out.getvalue())
    finally:
        U.urlopen, B.SG.groups_from_env, S.probe_health = keep[:3]
        os.environ.pop('SALAD_API_KEY', None) if keep[3] is None else os.environ.__setitem__('SALAD_API_KEY', keep[3])
    print('  ✓ batch_show: молчащая при живых соседях — пересажена своим бюджетом; молчат все — не трогаем')


def case_low_ram_node() -> None:
    """Машина с ОЗУ ниже порога уходит ДО первого задания (T-20261022-10 Б): ни одного задания не взяла, снята и
    пересажена, в журнале — служебная строка `node_reject`, которую сторож денег не считает ни попыткой, ни сбоем.
    Нет слота пересадок — ждёт его и пересаживается, когда слот появится; машину, не ответившую про ОЗУ, не наказываем."""
    import money_guard as G  # noqa: PLC0415
    kb = {1: 16 * 1024 ** 2, 2: 64 * 1024 ** 2}    # 16 и 64 ГиБ в kB, как пишет /proc/meminfo
    nodes = [{'id': 'LOW' + 'a' * 5, 'port': 1, 'group': 'g', 'state': 'running'},
             {'id': 'BIG' + 'b' * 5, 'port': 2, 'group': 'g', 'state': 'running'},
             {'id': 'MUT' + 'c' * 5, 'port': 3, 'group': 'g', 'state': 'running'}]
    used = []

    def job_fn(port, job):
        used.append(port)
        time.sleep(0.5)      # очередь длиннее стартового обхода (по 2 с на ноду): супервизор успевает покрутиться
        return {'sku': job['sku'], 'status': 'ok', 'timings_s': {'total': 1}}

    slots = iter([0, 0])     # первые два запроса слота — отказ: бюджет пересадок кончился
    keep_min, keep_slot = S.SG.node_min_ram_gb, NH.take_cull_slot
    patch.jobs = jobs(16)
    patch(nodes, job_fn)
    # порт 3 — машина, не ответившая про ОЗУ: работает как обычно
    S.ssh_text = lambda port, cmd, timeout=60: ('' if port == 3 else
                                                f'NVIDIA GeForce RTX 4080\nMemTotal:       {kb[port]} kB\n')
    S.SG.node_min_ram_gb = lambda: 32.0
    NH.take_cull_slot = lambda: next(slots, 1)
    try:
        code = S.run(None, True, jobs_file='x')
    finally:
        S.SG.node_min_ram_gb, NH.take_cull_slot = keep_min, keep_slot
    rows = json.load(open(S.RESULTS, encoding='utf-8'))['results']
    assert code == 0 and all(r['status'] == 'ok' for r in rows), (code, [r['status'] for r in rows])
    assert 1 not in used, f'машина с 16 ГБ взяла заданий: {used.count(1)}'
    assert 2 in used and 3 in used, f'здоровые машины простаивали: {used}'
    assert culled == [nodes[0]['id']], f'пересадка: {culled} — ждали ровно одну, малой ОЗУ, после ожидания слота'
    assert NH.is_retired(f'g/{nodes[0]["id"]}'), 'машина с малой ОЗУ не помечена снятой — супервизор вернёт её'
    rej = [x for x in map(json.loads, open(S.PROGRESS, encoding='utf-8')) if x.get('kind') == 'node_reject']
    assert len(rej) == 1, rej
    r = rej[0]
    assert r['instance'] == nodes[0]['id'] and r['min_gb'] == 32.0 and 17.0 <= r['mem_total_gb'] <= 17.5, r
    keep_j = G.JOURNAL
    G.JOURNAL = S.PROGRESS
    try:
        assert G.failure_burst() == ('', 0), 'уход машины с малой ОЗУ посчитан сбоем'
    finally:
        G.JOURNAL = keep_j
    print('  ✓ малая ОЗУ: ни одного задания, строка node_reject, пересадка — и после ожидания слота')


def case_input_quarantine() -> None:
    """Фото, которое магазин не отдаёт (403), не гоняем по машинам (T-20261022-10 Г): два ответа 403 подряд → карантин,
    задание закрыто без спула и без вины машины; следующий прогон его не раздаёт; по сроку — один раз на проверку."""
    IQ = S.IQ
    nodes = [{'id': 'A' * 8, 'port': 1, 'group': 'g', 'state': 'running'},
             {'id': 'B' * 8, 'port': 2, 'group': 'g', 'state': 'running'}]
    S.NODE_COOLDOWN_S = 0.1
    sent = []
    forbid = {'on': True}

    def job_fn(port, job):
        sent.append(job['sku'])
        if job['sku'] == 'sku0' and forbid['on']:
            return {'sku': job['sku'], 'status': 'input_failed', 'error': 'HTTP Error 403: Forbidden'}
        time.sleep(0.1)
        return {'sku': job['sku'], 'status': 'ok', 'timings_s': {'total': 1}}

    # мелкие правила: прочие исходы серию не растят
    assert IQ.note({'sku': 'z'}, {'status': 'transport_failed', 'error': 'HTTP Error 403'}) == 0
    assert IQ.note({'sku': 'z'}, {'status': 'input_failed', 'error': 'HTTP Error 404: Not Found'}) == 0
    assert 'z' not in IQ._load(), 'не-403 завёл запись карантина'

    # 1) два 403 → карантин
    patch.jobs = jobs(3)
    patch(nodes, job_fn)
    code = S.run(None, True, jobs_file='x')
    res = json.load(open(S.RESULTS, encoding='utf-8'))
    st, rows = res['summary'], {r['sku']: r for r in res['results']}
    assert sent.count('sku0') == 2, f'sku0 отправлен {sent.count("sku0")} раз — ждали 2 (на втором 403 — карантин)'
    assert rows['sku0']['status'] == IQ.STATUS, rows['sku0']
    assert code == 0 and st['unresolved'] == 0 and st['terminal_prefix'] == 3, (code, st)
    assert not os.path.exists(S.RETRY_SPOOL), 'карантинное задание ушло в спул повторов'
    assert not culled, f'машину пересадили за запрет магазина: {culled}'
    assert IQ.active() == {'sku0'}, IQ.active()
    q = [x for x in map(json.loads, open(S.PROGRESS, encoding='utf-8')) if x.get('quarantine_until')]
    assert len(q) == 1 and q[0]['sku'] == 'sku0', q

    # 2) второй прогон того же среза — карантинное ноде не раздаётся, курсор проходит его
    sent.clear()
    code = S.run(None, True, jobs_file='x')
    st = json.load(open(S.RESULTS, encoding='utf-8'))['summary']
    assert 'sku0' not in sent, f'карантинное задание раздано: {sent}'
    assert code == 0 and st['terminal_prefix'] == 3 and st['unresolved'] == 0, (code, st)

    # 3) срок вышел → прогон среза отдаёт его ОДИН раз в спул на проверку (товар не в срезе)
    d = json.load(open(IQ.STATE, encoding='utf-8'))
    d['sku0']['until'] = round(time.time()) - 1
    json.dump(d, open(IQ.STATE, 'w', encoding='utf-8'))
    keep = S.jobs_from_sample
    try:
        S.jobs_from_sample = lambda limit: jobs(3)[1:]
        S.run(2, True, skip=0)
    finally:
        S.jobs_from_sample = keep
    spool = [json.loads(x) for x in open(S.RETRY_SPOOL, encoding='utf-8') if x.strip()]
    assert [(r['sku'], r['status']) for r in spool] == [('sku0', 'input_recheck')], spool
    back = ORIG_JOBS_FROM_FILE(S.RETRY_SPOOL)
    assert [j['sku'] for j in back] == ['sku0'], back
    assert IQ.release_due() == [], 'истёкший карантин отдан на проверку второй раз'

    # 4) проверка из спула: снова 403 → карантин с первого же ответа (серия набрана); готовый меш снимает запись
    sent.clear()
    patch.jobs = back
    S.run(None, True, jobs_file='x')
    assert sent == ['sku0'], f'повторный 403 после проверки: {sent} — ждали ровно одну отправку'
    assert IQ.active() == {'sku0'}
    assert IQ.note({'sku': 'sku0'}, {'status': 'ok'}) == 0 and 'sku0' not in IQ._load(), 'готовый меш не снял запись'

    # 5) истёкший товар, который и так идёт в текущем срезе, в спул не дублируется
    IQ.note({'sku': 'sku5'}, {'status': 'input_failed', 'error': 'HTTP Error 403'}, now=0)
    IQ.note({'sku': 'sku5'}, {'status': 'input_failed', 'error': 'HTTP Error 403'}, now=0)
    assert IQ.release_due(skip={'sku5'}) == [] and IQ.release_due() == [], 'товар из среза отдан ещё и в спул'
    print('  ✓ 403 дважды → карантин без спула и без вины машины; второй прогон не раздаёт; по сроку — одна проверка')


def case_forbidden_node() -> None:
    """403 бывает виной машины (T-20261022-13): 65141c32 22.10 — 5 разных товаров подряд, другая машина их сделала.
    3 разных товара с 403 подряд на одной машине → машина уходит (`node_reject`, reason forbidden), товары не в карантине
    и уходят другой машине, попытка на заблокированной не в счёт. Серия рвётся скачанным фото."""
    IQ = S.IQ
    S.NODE_COOLDOWN_S = 0.1
    nodes = [{'id': 'A' * 8, 'port': 1, 'group': 'g', 'state': 'running'},
             {'id': 'B' * 8, 'port': 2, 'group': 'g', 'state': 'running'}]
    on_a = []

    def job_fn(port, job):
        if port == 1:
            on_a.append(job['sku'])
            return {'sku': job['sku'], 'status': 'input_failed', 'error': 'HTTP Error 403: Forbidden'}
        time.sleep(1.0)          # B медленная: A успевает вернуться из паузы и набрать серию
        return {'sku': job['sku'], 'status': 'ok', 'timings_s': {'total': 1}}

    # 1) машина A не пускается магазином — уходит на третьем разном товаре
    patch.jobs = jobs(6)
    patch(nodes, job_fn)
    made, keep, out = [], S.Jobs, io.StringIO()
    n_before = sum(1 for _ in open(S.PROGRESS, encoding='utf-8')) if os.path.exists(S.PROGRESS) else 0   # журнал общий для стенда

    class Seen(keep):                       # очередь прогона — чтобы проверить её счётчики после итога
        def __init__(self, js):
            super().__init__(js)
            made.append(self)
    S.Jobs = Seen
    try:
        with contextlib.redirect_stdout(out):
            code = S.run(None, True, jobs_file='x')
            n_rows = sum(1 for _ in open(S.PROGRESS, encoding='utf-8'))
            time.sleep(1.5)                 # дольше одного задания B: лишний повтор после итога успел бы напечататься
    finally:
        S.Jobs = keep
    log = out.getvalue()
    tail = log[log.index('RUN_SUMMARY'):].splitlines()[1:]
    assert not [x for x in tail if x.lstrip().startswith('[')], f'задание после итога прогона: {tail}'
    assert sum(1 for _ in open(S.PROGRESS, encoding='utf-8')) == n_rows, 'строка журнала после итога прогона'
    q = made[0]
    assert q.inflight == 0 and not any(it['busy'] for it in q.items), (q.inflight, [it['busy'] for it in q.items])
    oks = [x['sku'] for x in map(json.loads, open(S.PROGRESS, encoding='utf-8').readlines()[n_before:])
           if x.get('status') == 'ok' and x.get('node') == 'B' * 8]
    assert sorted(oks) == sorted(f'sku{i}' for i in range(6)), f'B сделала {sorted(oks)} — каждый товар ровно один раз'
    res = json.load(open(S.RESULTS, encoding='utf-8'))
    st, rows = res['summary'], {r['sku']: r for r in res['results']}
    assert code == 0 and st['unresolved'] == 0, (code, st)
    assert all(r['status'] == 'ok' for r in rows.values()), {k: r['status'] for k, r in rows.items()}
    assert len(on_a) == 3 and len(set(on_a)) == 3, f'A получила {on_a} — ждали 3 разных товара и уход'
    assert culled == ['A' * 8], f'пересажены {culled}'
    rej = [x for x in map(json.loads, open(S.PROGRESS, encoding='utf-8')) if x.get('reason') == 'forbidden']
    assert len(rej) == 1 and rej[0]['reason'] == 'forbidden' and sorted(rej[0]['skus']) == sorted(on_a), rej
    assert IQ._load() == {}, f'товары машины A попали в карантин: {IQ._load()}'
    # попытка на заблокированной машине не в счёт; закрытое запретом (карантин, исчерпанные попытки) — снова в очередь
    q = S.Jobs(jobs(3))
    for it in q.items:
        it['attempts'] = S.MAX_ATTEMPTS
    q.items[0]['result'] = {'sku': 'sku0', 'status': IQ.STATUS}
    q.items[1]['result'] = {'sku': 'sku1', 'status': 'input_failed', 'error': 'HTTP Error 403: Forbidden'}
    q.items[2]['result'] = {'sku': 'sku2', 'status': 'ok'}
    assert q.reopen({'sku0', 'sku1', 'sku2'}) == 2
    assert [(it['result'], it['attempts']) for it in q.items[:2]] == [(None, S.MAX_ATTEMPTS - 1)] * 2
    assert q.items[2]['result']['status'] == 'ok' and q.items[2]['attempts'] == S.MAX_ATTEMPTS, 'сделанное тронуто'

    # 2) серия рвётся скачанным фото: 403, 403, ok, 403, 403 — машина остаётся (магазин отдаёт ей фото через раз)
    culled.clear()
    first = set()
    solo = [{'id': 'C' * 8, 'port': 3, 'group': 'g', 'state': 'running'}]

    def flaky(port, job):
        if job['sku'] in ('sku0', 'sku1', 'sku3', 'sku4') and job['sku'] not in first:
            first.add(job['sku'])
            return {'sku': job['sku'], 'status': 'input_failed', 'error': 'HTTP Error 403: Forbidden'}
        return {'sku': job['sku'], 'status': 'ok', 'timings_s': {'total': 1}}

    patch.jobs = jobs(6)
    patch(solo, flaky)
    code = S.run(None, True, jobs_file='x')
    st = json.load(open(S.RESULTS, encoding='utf-8'))['summary']
    rej = [x for x in map(json.loads, open(S.PROGRESS, encoding='utf-8')) if x.get('reason') == 'forbidden']
    assert code == 0 and st['unresolved'] == 0, (code, st)
    assert not culled and len(rej) == 1, f'машину сняли, хотя серию рвало скачанное фото: {culled}, {rej}'
    assert IQ._load() == {}, IQ._load()

    # 3) правила: один 403 у товара на двух машинах — по-прежнему карантин товара (машины не виноваты, серия у каждой 1)
    assert IQ.note({'sku': 'q'}, {'status': 'input_failed', 'error': 'HTTP Error 403'}) == 0       # машина X
    assert IQ.note({'sku': 'q'}, {'status': 'input_failed', 'error': 'HTTP Error 403'}) > 0        # машина Y
    assert IQ.active() == {'q'}
    assert IQ.forgive('q') and IQ.active() == set(), 'снятие запрета не вывело товар из карантина'
    assert not IQ.forgive('нет такого')
    print('  ✓ 403 на 3 разных товарах у одной машины → машина уходит, товары не в карантине и сделаны другой; '
          'серию рвёт скачанное фото')


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        setup(tmp)
        pure = (case_checkpoint, case_cull_rule, case_fault_classes, case_halt_blocks_start,
                case_silent_node_is_zombie, case_sink_relief_before_red,
                case_transport_class, case_window_gate, case_group_status_mixed,
                case_step_timeout_kills_children, case_no_restart_of_running_group,
                case_burst_counts_cached, case_alarm_before_halt, case_notify_reports, case_hot_restart,
                case_stop_verified)
        for fn in (case_late_node, case_bad_node, case_unresolved, case_prefix, case_cursor_on_stall, case_done_set,
                   case_stall_is_capacity, case_no_capacity, case_cull_rule, case_checkpoint,
                   case_fault_classes, case_streak_rules, case_streak_survives_restart,
                   case_retire_is_temporary, case_fleet_wide_guard, case_cull_budget_shared, case_node_breaker_run,
                   case_dead_photo_keeps_node, case_spool_keeps_reason,
                   case_post_background, case_flat_plan, case_halt_blocks_start,
                   case_preflight_sink_full, case_infra_closes_rest, case_no_double_generate,
                   case_transport_class, case_window_gate, case_group_status_mixed,
                   case_step_timeout_kills_children, case_no_restart_of_running_group,
                   case_silent_node_is_zombie, case_sink_relief_before_red,
                   case_burst_counts_cached, case_alarm_before_halt, case_notify_reports, case_hot_restart,
                   case_stop_verified, case_low_ram_node, case_input_quarantine, case_forbidden_node,
                   case_taken_no_streak, case_realloc_404_returns_slot, case_ssh_addr, case_silent_machines,
                   case_batch_show_silent, case_wave_tail_order, case_budget_halt_ends_wave, case_manual_cap):
            if fn not in pure:
                setup(tmp)
            fn()
    print('стенд пула: ВСЁ ЗЕЛЁНОЕ')


if __name__ == '__main__':
    main()
