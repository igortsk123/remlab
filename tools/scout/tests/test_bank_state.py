#!/usr/bin/env python3
"""Проверка состояния живого банка комнаты — ворота публикации демо ночью (room-bank-01 этап Д, T-20261107-04).

ЗАЧЕМ. «Неопределённое состояние → демо не публиковать»: витрина читает живой банк спальни независимо от флагов банка, и если
запись оборвалась (намерение осталось), журнал или файл повреждены или файл менял кто-то мимо писателя — ночь не должна
публиковать демо по такому банку. `bank_refresh.state` — только чтение; здесь — все виды журнала и каждый способ «не определено».

Всё в песочнице (временная папка); CLI — с `BANK_BEDROOM_GENERATIONS` во временную папку (живой банк рядом с кодом не трогается).

  python3 tests/test_bank_state.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_bank_state')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)

SCOUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCOUT)

import bank_refresh as RF  # noqa: E402

bad = 0


def ok(name, cond, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


def sandbox(d: str) -> dict:
    g = os.path.join(d, 'gen')
    os.makedirs(g, exist_ok=True)
    return {'live': os.path.join(d, 'sets-bedroom.json'), 'gen': g, 'journal': os.path.join(g, 'journal.jsonl'),
            'intent': os.path.join(g, 'intent.json'), 'hold': os.path.join(g, 'hold.json'), 'room': 'bedroom'}


def put(path: str, data: bytes) -> str:
    with open(path, 'wb') as f:
        f.write(data)
    return RF.sha(data)


def rec(P: dict, r: dict) -> None:
    RF._journal_add(P, r)


def main() -> int:
    A, B = b'[{"set_id": "a"}]', b'[{"set_id": "b"}]'
    with tempfile.TemporaryDirectory(prefix='bank-state-') as d:
        P = sandbox(d)
        good, msg = RF.state(P)
        ok('журнала нет, живого нет — определено («писатель не работал»)', good and 'журнала нет' in msg, msg)
        sa = put(P['live'], A)
        good, msg = RF.state(P)
        ok('журнала нет, живой есть — определено', good and 'живой банк есть' in msg, msg)
        rec(P, {'gen': 'g0', 'kind': 'bootstrap', 'live_sha_before': None, 'live_sha_after': sa})
        good, msg = RF.state(P)
        ok('bootstrap, живой = sha журнала — определено', good and 'bootstrap g0' in msg, msg)
        put(P['live'], B)
        good, msg = RF.state(P)
        ok('живой менял кто-то мимо писателя (sha ≠ журнал) — НЕ определено', not good and 'не равен журналу' in msg, msg)
        sb = RF.sha(B)
        rec(P, {'gen': 'g1', 'kind': 'write', 'live_sha_before': sa, 'live_sha_after': sb})
        good, msg = RF.state(P)
        ok('запись write довела живой до своего «после» — определено', good and 'write g1' in msg, msg)
        rec(P, {'gen': 'g2-recover', 'kind': 'recover', 'action': 'abort', 'of': 'g2', 'live_sha': sb})
        rec(P, {'gen': 'g3-recover', 'kind': 'recover', 'action': 'restore', 'of': 'g3', 'live_sha': 'чужой'})
        good, msg = RF.state(P)
        ok('восстановление abort/restore — живой прежний (sha предыдущей записи), определено', good and 'write g1' in msg, msg)
        RF._intent_save(P, {'gen': 'g4', 'record': {'kind': 'write'}, 'live_sha_before': sb, 'live_sha_after': sa})
        good, msg = RF.state(P)
        ok('незавершённая запись (намерение лежит) — НЕ определено, разбор через recover', not good and 'g4' in msg
           and 'recover' in msg, msg)
        os.replace(P['intent'], P['intent'] + '.done')
        put(P['live'], b'[{"set_id": ')
        good, msg = RF.state(P)
        ok('живой не читается как JSON — НЕ определено', not good and 'JSON' in msg, msg)
        sc = put(P['live'], b'[{"set_id": "c"}]')
        rec(P, {'gen': 'g5-recover', 'kind': 'recover', 'action': 'abandon', 'of': 'g5', 'live_sha': sc})
        good, msg = RF.state(P)
        ok('recover --abandon (живой оставлен как был руками) — живой = sha той записи, определено',
           good and 'abandon' in msg, msg)
        rec(P, {'gen': 'g6', 'kind': 'unbootstrap', 'live_sha_before': sc, 'live_sha_after': None})
        good, msg = RF.state(P)
        ok('unbootstrap, а живой файл остался — НЕ определено', not good and 'unbootstrap g6' in msg, msg)
        os.replace(P['live'], os.path.join(P['gen'], 'aside.json'))
        good, msg = RF.state(P)
        ok('unbootstrap и живого нет — определено', good and 'нет файла' in msg, msg)
        with open(P['journal'], 'a', encoding='utf-8') as f:
            f.write('{оборвано\n')
        good, msg = RF.state(P)
        ok('журнал не читается — НЕ определено', not good and 'журнал' in msg, msg)
        # CLI ночи: `--room bedroom state` у каркаса комнаты (гейт каркаса не мешает чтению), код 3 и строка DIGEST
        g2 = os.path.join(d, 'cli-gen')
        os.makedirs(g2)
        env = {**os.environ, 'BANK_BEDROOM_GENERATIONS': g2}
        live_here = os.path.join(SCOUT, 'sets-bedroom.json')
        py = [sys.executable, os.path.join(SCOUT, 'bank_refresh.py'), '--room', 'bedroom', 'state']
        if not os.path.exists(live_here):         # в копии без живого банка: пусто → определено; намерение → 3
            p = subprocess.run(py, env=env, capture_output=True, text=True, timeout=60)
            ok('CLI: --room bedroom state, журнала нет — код 0, строка «ок»', p.returncode == 0 and 'bank_state: bedroom: ок' in p.stdout,
               (p.returncode, p.stdout[-200:], p.stderr[-200:]))
        with open(os.path.join(g2, 'intent.json'), 'w', encoding='utf-8') as f:
            json.dump({'gen': 'gx', 'record': {'kind': 'write'}}, f)
        p = subprocess.run(py, env=env, capture_output=True, text=True, timeout=60)
        ok('CLI: незавершённая запись — код 3, ERROR и DIGEST «демо в эту ночь не публикуется»',
           p.returncode == 3 and 'ERROR:bank_state: bedroom' in p.stdout and 'DIGEST:банк bedroom: состояние не определено' in p.stdout
           and 'не публикуется' in p.stdout, (p.returncode, p.stdout[-300:], p.stderr[-300:]))
    print(f'test_bank_state: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
