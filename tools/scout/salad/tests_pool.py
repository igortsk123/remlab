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
import ssh_run as S  # noqa: E402


def setup(tmp: str) -> None:
    """Быстрые таймеры и временные файлы: боевые mesh-pilot-results.json и журнал прогона
    трогать нельзя — рядом идёт живой конвейер."""
    S.POLL_S, S.CULL_S, S.STALL_S = 0.3, 10_000, 6.0
    S.RETRY_GRACE_S, S.MAX_ATTEMPTS, S.NODE_COOLDOWN_S = 0.2, 3, 30.0
    S.SSH_STAGGER_S = 0.0
    S.RESULTS = os.path.join(tmp, 'results.json')
    S.PROGRESS = os.path.join(tmp, 'progress.jsonl')
    S.cull_slow = lambda: None


def jobs(n: int) -> list[dict]:
    return [{'sku': f'sku{i}', 'role': 'кресло', 'image_url': 'x', 'dims_cm': {},
             'seed': 0, 'params': {}} for i in range(n)]


def patch(nodes: list[dict], job_fn) -> None:
    S.instances = lambda: list(nodes)
    S.probe_warm = lambda port: True
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
    print('  ✓ исчерпанные попытки → unresolved, курсор не двигается')


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


def case_no_capacity() -> None:
    """Нет прогретых нод — это ожидание (75), а не авария."""
    S.instances = lambda: []
    S.probe_warm = lambda port: False
    assert S.run(None, True, jobs_file='x') == S.EXIT_NO_CAPACITY
    print('  ✓ нет тёплых нод → код 75')


def case_checkpoint() -> None:
    """Падение процесса не должно стирать знание о сделанном."""
    lines = [json.loads(x) for x in open(S.PROGRESS, encoding='utf-8').read().splitlines() if x]
    assert lines and all('sku' in x and 'status' in x for x in lines), lines[:2]
    print(f'  ✓ чекпойнт: {len(lines)} строк, все разбираются')


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        setup(tmp)
        for fn in (case_late_node, case_bad_node, case_unresolved, case_prefix,
                   case_no_capacity, case_checkpoint):
            setup(tmp) if fn is not case_checkpoint else None
            fn()
    print('стенд пула: ВСЁ ЗЕЛЁНОЕ')


if __name__ == '__main__':
    main()
