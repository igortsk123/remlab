#!/usr/bin/env python3
"""Флаги писателя гостиной и спальни — раздельно; каркас (прихожая) ничего не пишет (room-bank-01 этап Б, T-20261106-67; этап Ж — спальня настоящая).

ЗАЧЕМ. С этапа Б у банка спальни свои флаги шагов (`rules/bank-candidate.json:rooms.bedroom.*`), а гостиная читает прежние
ключи верхнего уровня. Разбор Codex (`_intake/codex/room-bank-2026-11-06-answer.md`): включение писателя спальни не должно
менять ночной `BANK_WRITE`, не должно выключать прежних писателей гостиной и вызывать её `bank_refresh`; писатель не берёт
manifest чужой комнаты. Таблица — все 4 сочетания `write_enabled` (гостиная × спальня).

  python3 tests/test_room_bank_flags.py
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import tempfile

SCOUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCOUT)

import bank_pending as BP  # noqa: E402
import bank_refresh as RF  # noqa: E402
import room_bank_spec as RBS  # noqa: E402

bad = 0


def ok(name, cond, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


def rules_with(td: str, living: bool, bedroom: bool) -> str:
    R = json.load(open(RBS.RULES_PATH, encoding='utf-8'))
    R['write_enabled'] = living
    R.setdefault('rooms', {}).setdefault('bedroom', {})['write_enabled'] = bedroom
    p = os.path.join(td, f'rules-{int(living)}{int(bedroom)}.json')
    json.dump(R, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    return p


def call_main(argv: list, rules: str, home: str) -> tuple[int, str, list]:
    """`bank_refresh.main` в процессе: правила — временные; запись/откат подменены (что вызвано — список)."""
    saved = (RBS.RULES_PATH, RF.SPEC, RF.RULES_PATH, RF.write, RF.rollback, RF.release, RF.recover, sys.argv, os.environ.get('HOME'))
    calls = []
    try:
        RBS.RULES_PATH = rules
        RF.SPEC, RF.RULES_PATH = RBS.for_room(None), rules
        RF.write = lambda P, R, **k: calls.append(('write', P['live'], P.get('room'))) or 0
        RF.rollback = lambda P, *a, **k: calls.append(('rollback', P['live'])) or 0
        RF.release = lambda P, *a, **k: calls.append(('release', P['live'])) or 0
        RF.recover = lambda P, *a, **k: calls.append(('recover', P['live'])) or 0
        sys.argv = ['bank_refresh.py'] + argv
        os.environ['HOME'] = home
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = RF.main()
        return rc, buf.getvalue(), calls
    finally:
        (RBS.RULES_PATH, RF.SPEC, RF.RULES_PATH, RF.write, RF.rollback, RF.release, RF.recover, sys.argv, h) = saved
        if h is not None:
            os.environ['HOME'] = h


def run_cli(argv: list, rules: str, home: str) -> tuple[int, str]:
    """Скрипт шага как `python X.py …`, но в процессе (`runpy`): правила — временный файл (`room_bank_spec.RULES_PATH`), HOME —
    временная папка; модули, которые шаг меняет через `bind`, возвращаются. → (код, вывод целиком; при исключении — traceback)."""
    import runpy
    import traceback
    names = ('bank_pending', 'bank_promote', 'bank_prepare', 'bank_refresh')
    saved_mods = {n: dict(vars(sys.modules[n])) for n in names if n in sys.modules}
    saved = (RBS.RULES_PATH, sys.argv, os.environ.get('HOME'))
    buf = io.StringIO()
    rc = None
    try:
        RBS.RULES_PATH = rules
        sys.argv = [os.path.join(SCOUT, argv[0]), *argv[1:]]
        os.environ['HOME'] = home
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            try:
                runpy.run_path(sys.argv[0], run_name='__main__')
                rc = 0
            except SystemExit as e:
                rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
                if not isinstance(e.code, (int, type(None))):
                    print(e.code)
            except BaseException:  # noqa: BLE001 — тест печатает исключение целиком
                traceback.print_exc()
                rc = 'исключение'
    finally:
        RBS.RULES_PATH, sys.argv, h = saved
        if h is not None:
            os.environ['HOME'] = h
        for n, d in saved_mods.items():
            vars(sys.modules[n]).update(d)
    return rc, buf.getvalue()


def main() -> int:
    B = RBS.for_room('bedroom')
    L = RBS.for_room(None)
    with tempfile.TemporaryDirectory() as td:
        home = os.path.join(td, 'home')
        os.makedirs(home)
        print('таблица флагов write_enabled (гостиная × спальня):')
        for lw in (False, True):
            for bw in (False, True):
                rp = rules_with(td, lw, bw)
                tag = f'гостиная={str(lw).lower()}, спальня={str(bw).lower()}'
                rc, out, _ = call_main(['--enabled'], rp, home)
                ok(f'[{tag}] `bank_refresh --enabled` (ночной BANK_WRITE) = флаг гостиной', out.strip() == str(int(lw)), out)
                rc, out, _ = call_main(['--room', 'bedroom', '--enabled'], rp, home)
                ok(f'[{tag}] `--room bedroom --enabled` = флаг спальни', out.strip() == str(int(bw)), out)
                rc, out, calls = call_main(['--run-id', 'N1'], rp, home)
                ok(f'[{tag}] писатель гостиной без --room: идёт к записи своего sets3.json, флаг спальни не влияет',
                   rc == 0 and calls == [('write', L.live, None)], (rc, calls))
                # этап Ж (T-20261107-04/3): писатель спальни настоящий — идёт к записи СВОЕГО банка (флаг решает `write` сам)
                rc, out, calls = call_main(['--room', 'bedroom', '--run-id', 'N1'], rp, home)
                ok(f'[{tag}] писатель спальни: к записи sets-bedroom.json со своей комнатой; писателя гостиной нет',
                   rc == 0 and calls == [('write', B.live, 'bedroom')], (rc, out, calls))
                for sub in (['rollback', 'last'], ['release'], ['recover']):
                    rc, out, calls = call_main(['--room', 'bedroom', *sub], rp, home)
                    ok(f'[{tag}] спальня `{sub[0]}` — свой банк', rc == 0 and calls == [(sub[0], B.live)], (rc, calls))
                # прихожая — по-прежнему каркас: флаг в файле выключен — «выключено», ничего не зовёт
                rc, out, calls = call_main(['--room', 'hall', '--run-id', 'N1'], rp, home)
                ok(f'[{tag}] писатель прихожей (каркас): «выключено», ни записи, ни писателя гостиной',
                   rc == 0 and 'rooms.hall.write_enabled=false' in out and calls == [], (rc, out, calls))
                for sub in (['rollback', 'last'], ['release'], ['recover']):
                    rc, out, calls = call_main(['--room', 'hall', *sub], rp, home)
                    ok(f'[{tag}] прихожая `{sub[0]}` — каркас, ничего не трогает', rc in (0, 2) and calls == [], (rc, calls))
                with open(rp, encoding='utf-8') as f:
                    R = json.load(f)
                RL = L.view(R)
                RB = B.view(R)
                ok(f'[{tag}] правила гостиной — прежний ключ верхнего уровня; спальни — rooms.bedroom',
                   RL['write_enabled'] is lw and RB['write_enabled'] is bw and RB['prepare_enabled'] is False)

        sh = open(os.path.join(SCOUT, 'refresh_daily.sh'), encoding='utf-8').read()
        bw_line = [ln for ln in sh.splitlines() if re.match(r'\s*BANK_WRITE=', ln)]
        # шаги комнат в ночи с `--room X` (T-20261106-89) — свои строки; гостиную они не трогают: ни BANK_WRITE, ни её bank_refresh
        room_refresh = [ln for ln in sh.splitlines() if re.search(r'bank_refresh\.py\b', ln) and not ln.lstrip().startswith('#')]
        ok('refresh_daily.sh: BANK_WRITE — `bank_refresh.py --enabled` без --room (флаг спальни ночь не меняет); '
           'писатель гостиной — без --room',
           len(bw_line) == 1 and 'bank_refresh.py --enabled' in bw_line[0] and not re.search(r'--room\b', bw_line[0])
           and any(not re.search(r'--room\b', ln) and '--run-id' in ln for ln in room_refresh), (bw_line, room_refresh))

        # писатель: manifest чужой комнаты — отказ
        P = {k: os.path.join(td, 'w', v) for k, v in (('live', 'sets3.json'), ('lock', 'exam.lock'), ('manifest', 'prom.json'),
                                                      ('gen', 'gens'), ('journal', 'gens/journal.jsonl'),
                                                      ('hold', 'gens/hold.json'), ('intent', 'gens/intent.json'))}
        os.makedirs(os.path.join(td, 'w', 'gens'))
        open(P['live'], 'w').write('[]')
        R = {'write_enabled': True}
        for man, PP, want in (({'run_id': 'N1', 'room': 'bedroom'}, P, 'manifest комнаты bedroom, а писатель — living'),
                              ({'run_id': 'N1'}, {**P, 'room': 'bedroom', 'snap': 'sets-bedroom'},
                               'manifest комнаты living, а писатель — bedroom')):
            json.dump(man, open(P['manifest'], 'w'))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = RF.write(PP, R, run_id='N1')
            ok(f'писатель {PP.get("room", "living")}: manifest чужой комнаты — отказ, банк не тронут',
               rc == 1 and want in buf.getvalue() and open(P['live']).read() == '[]', buf.getvalue())
        gen, spath = RF.snapshot({**P, 'snap': 'sets-bedroom'}, b'[]')
        gen2, spath2 = RF.snapshot(P, b'[]')
        ok('снимок поколения: префикс комнаты (sets-bedroom-…); у гостиной — прежний sets3-…',
           os.path.basename(spath).startswith('sets-bedroom-') and os.path.basename(spath2).startswith('sets3-'), (spath, spath2))

        # ключ ячейки и пути через bind
        s = {'room_id': 'r1', 'purpose': 'double', 'band': 'S', 'style': 'сканди', 'tier': 'эконом', 'items': {}}
        saved = {k: getattr(BP, k) for k in ('SPEC', 'RULES_PATH', 'STATE', 'CANDIDATE', 'LIVE', 'DEMO_DATA', 'PREPARE_REPORT')}
        k_living = BP.key(s)
        RBS.bind(BP, B)
        k_bed, st_bed = BP.key(s), BP.STATE
        for k, v in saved.items():
            setattr(BP, k, v)
        ok('bank_pending.key: гостиная band|style|tier; после bind спальни — room_id|purpose|band|style|tier, своё состояние',
           k_living == 'S|сканди|эконом' and k_bed == 'r1|double|S|сканди|эконом' and st_bed == B.pending_state
           and BP.key(s) == k_living)

        # CLI шагов с --room в процессе, правила — ВРЕМЕННЫЕ (флаги в файле репо ведущий включает — тест от них не зависит,
        # урок CI T-04/2): спальня — настоящие шаги, флаги выключены — «выключено», 0 (prepare кладёт отчёт {disabled} — по нему
        # подмена этой ночи знает, что судить нечего); прихожая — каркас: флаг выключен — 0, --force — отказ 2. Рядом ничего.
        R = json.load(open(RBS.RULES_PATH, encoding='utf-8'))
        for room in ('bedroom', 'hall'):
            R.setdefault('rooms', {}).setdefault(room, {}).update(prepare_enabled=False, promote_enabled=False,
                                                                  write_enabled=False)
        off = os.path.join(td, 'rules-off.json')
        json.dump(R, open(off, 'w', encoding='utf-8'), ensure_ascii=False)
        home2 = os.path.join(td, 'home2')
        os.makedirs(home2)
        before = set(os.listdir(SCOUT))
        for argv, want_rc, want in ((['bank_prepare.py', '--room', 'bedroom', '--run-id', 'N1'], 0,
                                     'rooms.bedroom.prepare_enabled=false'),
                                    (['bank_pending.py', '--room', 'bedroom', '--night', '--run-id', 'N1'], 0,
                                     'rooms.bedroom.prepare_enabled=false'),
                                    (['bank_pending.py', '--room', 'bedroom', '--update'], 0, 'rooms.bedroom.prepare_enabled=false'),
                                    (['bank_promote.py', '--room', 'bedroom', '--run-id', 'N1'], 0,
                                     'rooms.bedroom.promote_enabled=false'),
                                    (['bank_refresh.py', '--room', 'bedroom', '--run-id', 'N1'], 0,
                                     'rooms.bedroom.write_enabled=false'),
                                    (['bank_prepare.py', '--room', 'hall'], 0, 'rooms.hall.prepare_enabled=false'),
                                    (['bank_prepare.py', '--room', 'hall', '--force'], 2, 'адаптер каркас'),
                                    (['bank_promote.py', '--room', 'hall', '--force'], 2, 'адаптер каркас'),
                                    (['bank_pending.py', '--room', 'hall', '--update'], 0, 'rooms.hall.prepare_enabled=false'),
                                    (['bank_prepare.py', '--room', 'kitchen'], 1, 'банка такой комнаты нет')):
            rc, txt = run_cli(argv, off, home2)
            ok(f'`{" ".join(argv)}` — код {want_rc}' + (f', «{want}»' if want else ''), rc == want_rc and want in txt,
               (rc, txt[-600:]))
        made = set(os.listdir(SCOUT)) - before
        rep = os.path.join(home2, 'scout-scenes', 'bank-bedroom-prepare.json')
        got = sorted(os.path.relpath(os.path.join(d, f), home2) for d, _, fs in os.walk(home2) for f in fs)
        ok('шаги комнат не создали файлов рядом (sets-*, bank-generations-*); в HOME — только отчёт prepare спальни {disabled}',
           not made and got == ['scout-scenes/bank-bedroom-prepare.json'] and json.load(open(rep)).get('disabled') is True,
           (made, got))
    print(f'room_bank_flags: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
