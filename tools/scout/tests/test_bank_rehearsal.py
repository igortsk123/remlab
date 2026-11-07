#!/usr/bin/env python3
"""Писатель комнаты и репетиция записи в копию с откатом по SHA (room-bank-01 этап Е, T-20261107-04).

ЗАЧЕМ. (1) Писатель банка (`bank_refresh` → `set_identity`) узнавал записи по ячейке гостиной `(band, style, tier)` — у спальни
её 60 записей по этой тройке повторяются, и запись падала бы на «дубль ячейки». Теперь ключ — из `RoomBankSpec`: 60 записей → 60
уникальных id, повторный прогон — те же id; гостиная — прежняя (её golden-тест отдельно). (2) Репетиция: настоящий писатель
пишет в КОПИЮ и откатывает по SHA; живой банк, его поколения и «наружу» (сеть, процессы) не трогаются — проверяем каждый исход.

Всё в песочнице (временные папки); вердикт сторожей — заглушка (их тесты — tests/test_room_guards.py).

  python3 tests/test_bank_rehearsal.py
"""
from __future__ import annotations

import copy
import json
import os
import socket
import subprocess
import sys
import tempfile

SCOUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCOUT)

import bank_refresh as RF  # noqa: E402
import bank_rehearsal as BR  # noqa: E402
import room_bank_spec as RBS  # noqa: E402
import room_guards as RG  # noqa: E402
import room_identity as RI  # noqa: E402
import set_identity as SID  # noqa: E402

bad = 0
SPEC = RBS.for_room('bedroom')


def ok(name, cond, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


def cli(argv: list, flags: dict, report: str, verdict=None) -> tuple[str, int | None]:
    """`bank_rehearsal.main(argv)` в процессе: флаги комнаты — `flags` (не файл правил), отчёт — `report`, сторож — `verdict`
    (None — не подменять). → (весь вывод + текст исключения, код; None — вышел исключением)."""
    import contextlib
    import io
    import traceback
    saved = (RG.verdict, RBS.RoomBankSpec.rules, os.environ.get('BANK_BEDROOM_REHEARSAL'))
    RBS.RoomBankSpec.rules = lambda self: dict(flags)
    os.environ['BANK_BEDROOM_REHEARSAL'] = report
    if verdict is not None:
        RG.verdict = verdict
    buf, rc = io.StringIO(), None
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = BR.main(list(argv))
    except BaseException:                      # noqa: BLE001 — провал теста, не падение: текст исключения — в строку
        buf.write('\n--- исключение ---\n' + traceback.format_exc())
    finally:
        RG.verdict, RBS.RoomBankSpec.rules = saved[0], saved[1]
        if saved[2] is None:
            os.environ.pop('BANK_BEDROOM_REHEARSAL', None)
        else:
            os.environ['BANK_BEDROOM_REHEARSAL'] = saved[2]
    return f'код {rc}\n--- вывод ---\n' + buf.getvalue(), rc


def bank60() -> list:
    """60 записей спальни: 2 комнаты × 2 назначения × 5 стилей × 3 тира; полоса площади одна на комнату — по (band, style,
    tier) гостиной записи повторяются (разные назначения), по ячейке спальни — уникальны."""
    out = []
    for room_id, band in (('bedroom-1', '13.2'), ('bedroom-2', '17.5')):
        for purpose in ('couple', 'single'):
            for style in ('сканди', 'лофт', 'классика', 'минимализм', 'неоклассика'):
                for tier in ('эконом', 'комфорт', 'премиум'):
                    c = (room_id, purpose, band, style, tier)
                    out.append({'room_id': room_id, 'purpose': purpose, 'band': band, 'style': style, 'tier': tier,
                                'set_id': RI.set_id_of('bedroom', c), 'total': 1000,
                                'items': {'кровать': {'mid': '1', 'eid': f'b{len(out)}', 'qty': 1, 'price': 1000}},
                                'alternates': {}, 'layout': {}})
    return out


def other(s: dict, tag: str = 'x') -> dict:
    t = copy.deepcopy(s)
    t['items']['кровать']['eid'] += tag
    t['items']['кровать']['price'] += 1
    return t


def sandbox(d: str, live: list | None) -> tuple[str, str]:
    lp, g = os.path.join(d, 'sets-bedroom.json'), os.path.join(d, 'gen')
    os.makedirs(g)
    if live is not None:
        raw = json.dumps(live, ensure_ascii=False, indent=1).encode()
        open(lp, 'wb').write(raw)
        with open(os.path.join(g, 'journal.jsonl'), 'w', encoding='utf-8') as f:     # не через писателя: его подменяет тест сети
            f.write(json.dumps({'gen': 'g0', 'kind': 'bootstrap', 'live_sha_before': None, 'live_sha_after': RF.sha(raw)}) + '\n')
    return lp, g


def run(d: str, live, cand, take=(), pre=None, want=None) -> tuple[dict, str, str, dict]:
    """Репетиция на стенде. want — ключи матрицы профиля (кому `retired`); None — все ячейки живого и кандидата (снимать нечего;
    настоящая матрица профиля тестом не читается — стенд не зависит от файлов профиля)."""
    lp, g = sandbox(os.path.join(d, 'real'), live)
    if pre:
        pre(lp, g)
    before = (BR._sha_file(lp), BR.listing(g))
    rows = [{'cell': RG.cell_key(s), 'set_id': s.get('set_id'), 'decision': 'promote', 'new': RG.cell_key(s) not in
             {RG.cell_key(x) for x in live or []}} for s in cand if RG.cell_key(s) in take]
    rep = {'take': [r['cell'] for r in rows], 'rows': rows, 'cap': 15,
           'new_cells': [RG.cell_key(s) for s in cand if RG.cell_key(s) not in {RG.cell_key(x) for x in live or []}]}
    sb = os.path.join(d, 'sb')
    os.makedirs(sb)
    w = want if want is not None else {RG.cell_key(s) for s in (live or []) + cand}
    out = BR.rehearse('bedroom', sb, live_path=lp, gen_dir=g, run_id='R1', want_fn=lambda r: set(w),
                      verdict_fn=lambda r: (rep, [], cand, json.load(open(lp)) if os.path.exists(lp) else None))
    untouched = (BR._sha_file(lp), BR.listing(g)) == before
    return out, lp, g, {'untouched': untouched}


def main() -> int:
    key = SPEC.cell
    # ——— (1) писатель комнаты: идентичность по ячейке спальни ———
    B = bank60()
    try:
        SID.assign_ids(copy.deepcopy(B), B)
        living_refused = False
    except SID.IdentityError:
        living_refused = True
    ok('ключ гостиной на банке спальни — отказ «дубль ячейки» (так писатель падал до этапа Е)', living_refused)
    a = SID.assign_ids(copy.deepcopy(B), B, key)
    b = SID.assign_ids(copy.deepcopy(a), a, key)
    ok('ключ спальни: 60 записей → 60 уникальных id, порядок и id прежние; повторный прогон — те же id',
       len(a) == 60 and len({s['set_id'] for s in a}) == 60 and [s['set_id'] for s in a] == [s['set_id'] for s in B]
       and [s['set_id'] for s in b] == [s['set_id'] for s in a] and not SID.verify(b, B, cells=60, key=key))
    shuffled = list(reversed(copy.deepcopy(B)))
    ok('ключ спальни: пересобранный в другом порядке — порядок и id задаёт прежний банк',
       [s['set_id'] for s in SID.assign_ids(shuffled, B, key)] == [s['set_id'] for s in B])
    drift = copy.deepcopy(B)
    drift[3]['set_id'] = 'bed-чужой'
    try:
        SID.assign_ids(drift, B, key)
        ok('ключ спальни: чужой set_id у ячейки — отказ', False)
    except SID.IdentityError as e:
        ok('ключ спальни: чужой set_id у ячейки — отказ', 'дрейф set_id' in str(e), str(e))
    RBS.bind(RF, RBS.for_room(None), 'bank_refresh')
    ok('писатель гостиной: ключ None (set_identity.cell — прежний)', RF._key() is None)
    RBS.bind(RF, SPEC, 'bank_refresh')
    ok('писатель спальни: ключ — ячейка спальни (room_id, purpose, band, style, tier)',
       RF._key() is not None and RF._key()(B[0]) == ('bedroom-1', 'couple', '13.2', 'сканди', 'эконом'))
    RBS.bind(RF, RBS.for_room(None), 'bank_refresh')

    # ——— (2) репетиция ———
    with tempfile.TemporaryDirectory(prefix='rehearsal-') as d:
        cand = copy.deepcopy(B)
        cand[7] = other(cand[7])
        out, lp, g, x = run(os.path.join(d, 'm'), B, cand)
        ok('механика (сторожа подменили 0): 1 ячейка, отличная от живой — запись в копию и откат по SHA, копия = живой «до»',
           out['ok'] and out['mode'] == 'механика' and out['promoted'] == [8] and out['changed'] == [8]
           and out['sha_after_write'] != out['sha_before'] and out['sha_after_rollback'] == out['sha_before']
           and out['write_rc'] == 0 and out['rollback_rc'] == 0, out.get('problems'))
        ok('механика: живой банк и папка его поколений не тронуты, внешних записей 0', x['untouched'] and out['external'] == [])
        ok('строка дайджеста: подменено 1 (механика, не судима), откат по SHA, внешних записей 0',
           'подменено 1 (механика: 1 ячейка, не судима)' in BR.digest(out) and 'откат по SHA' in BR.digest(out)
           and 'внешних записей 0' in BR.digest(out), BR.digest(out))
        sbj = RF.journal(BR.sandbox_paths(os.path.join(d, 'm', 'sb'), SPEC))
        ok('журнал копии: запись write и откат rollback; у живого журнала — только его bootstrap',
           [r['kind'] for r in sbj] == ['bootstrap', 'write', 'rollback']
           and [r['kind'] for r in RF.journal({'journal': os.path.join(g, 'journal.jsonl')})] == ['bootstrap'],
           [r['kind'] for r in sbj])

        cand = copy.deepcopy(B)
        cand[2], cand[40] = other(cand[2]), other(cand[40])
        cand[11] = other(cand[11])                    # отличается, но сторожа её не берут — в копию не идёт
        out, _, _, x = run(os.path.join(d, 'g'), B, cand, take={RG.cell_key(cand[2]), RG.cell_key(cand[40])})
        ok('подмены сторожей: в копию ровно их ячейки (номера 3 и 41), остальные — как в живом; откат = живой',
           out['ok'] and out['mode'] == 'сторожа' and out['promoted'] == [3, 41] and out['changed'] == [3, 41]
           and out['sha_after_rollback'] == out['sha_before'] and x['untouched'], out.get('problems'))

        newc = copy.deepcopy(B[0])
        newc.update(style='джапанди', set_id=RI.set_id_of('bedroom', ('bedroom-1', 'couple', '13.2', 'джапанди', 'эконом')))
        cand = copy.deepcopy(B) + [newc]
        cand[5] = other(cand[5])
        out, _, _, x = run(os.path.join(d, 'n'), B, cand, take={RG.cell_key(newc), RG.cell_key(cand[5])})
        sbj = RF.journal(BR.sandbox_paths(os.path.join(d, 'n', 'sb'), SPEC))
        # этап Ж (вариант А): писатель ДОБАВЛЯЕТ — новая ячейка в хвост (номер 61) со своим id, прежние номера и id не тронуты,
        # журнал `add`; откат по SHA — копия = живой «до»
        ok('новая ячейка (нет в живом): в хвост номером 61, вид журнала add, прежние номера не тронуты, откат = живой',
           out['ok'] and out['new_cells'] == [RG.cell_key(newc)] and out['promoted'] == [6, 61] and out['added'] == [61]
           and out['grown'] == [61] and out['changed'] == [6] and out['sha_after_rollback'] == out['sha_before']
           and [r['kind'] for r in sbj] == ['bootstrap', 'add', 'rollback'] and x['untouched']
           and 'новых ячеек в хвост 1 [61]' in BR.digest(out), (out.get('problems'), [r['kind'] for r in sbj], BR.digest(out)))
        rec = next(r for r in sbj if r['kind'] == 'add')
        ok('журнал add: added_cells — номер, ячейка и id новой (id = set_id_of ячейки)',
           rec.get('added_cells') == [{'n': 61, 'cell': RG.cell_key(newc), 'set_id': newc['set_id']}], rec.get('added_cells'))

        # ячейка живого вне матрицы профиля — НЕ удаляется: пометка retired, номер и id прежние; откат = живой
        cand = [s for s in copy.deepcopy(B) if RG.cell_key(s) != RG.cell_key(B[9])]
        out, _, _, x = run(os.path.join(d, 'r'), B, cand, want={RG.cell_key(s) for s in cand})
        ok('ячейка вне матрицы: retired (номер 10), не удалена, длина 60, откат = живой',
           out['ok'] and out['mode'] == 'сторожа' and out['retired'] == [10] and out['changed'] == [10] and out['grown'] == []
           and out['sha_after_rollback'] == out['sha_before'] and x['untouched']
           and 'снято с витрины (retired) 1' in BR.digest(out), (out.get('problems'), out.get('changed'), BR.digest(out)))

        out, _, _, x = run(os.path.join(d, 'e'), B, copy.deepcopy(B))
        ok('кандидат равен живому — «записывать нечего», ок, ничего не писали', out['ok'] and out['mode'] == 'нечего' and x['untouched'])

        out, _, _, _ = run(os.path.join(d, 'z'), None, copy.deepcopy(B))
        ok('живого банка нет — репетировать нечего (ок)', out['ok'] and out['mode'] == 'нет живого')

        def broken(lp, g):
            open(os.path.join(g, 'intent.json'), 'w').write('{"gen": "gx", "record": {"kind": "write"}}')
        cand = copy.deepcopy(B)
        cand[1] = other(cand[1])
        out, _, _, x = run(os.path.join(d, 'u'), B, cand, pre=broken)
        ok('состояние живого не определено (незавершённая запись) — репетиция не идёт, сбой строкой, живой не тронут',
           not out['ok'] and 'не определено' in out['problems'][0] and x['untouched'], out.get('problems'))

        real_add = RF._journal_add
        RF._journal_add = lambda P, r: (socket.create_connection(('127.0.0.1', 9), timeout=1), real_add(P, r))
        try:
            out, _, _, x = run(os.path.join(d, 'x'), B, cand)
        finally:
            RF._journal_add = real_add
        ok('попытка выйти в сеть во время записи — перехвачена (наружу ничего), репетиция — сбой, живой не тронут',
           not out['ok'] and out['external'] and 'внешняя запись' in out['problems'][0] and x['untouched'], out)
        real_popen = subprocess.Popen.__init__
        try:
            with BR.sealed([]):
                subprocess.run(['true'])
            sealed_proc = False
        except BR.External:
            sealed_proc = True
        ok('процессы на время записи закрыты, после — открыты', sealed_proc and subprocess.Popen.__init__ is real_popen
           and subprocess.run(['true']).returncode == 0)

        cand = copy.deepcopy(B)
        cand[9] = other(cand[9])
        cand[9]['set_id'] = 'bed-чужой'
        out, _, _, x = run(os.path.join(d, 'i'), B, cand)
        ok('писатель отказал (чужой set_id ячейки) — репетиция сбой, копия и живой целы',
           not out['ok'] and out['write_rc'] == 1 and x['untouched'], out.get('problems'))

        # CLI — В ПРОЦЕССЕ (`cli`): флаги комнаты и сторож подменены, вывод и исключение — целиком в строку провала
        # (T-20261107-04/2: в CI 07.11 тест упал без видимой причины — проверка звала настоящих сторожей и флаги из файла правил)
        rp = os.path.join(d, 'rep', 'r')
        txt, rc = cli(['--room', 'hall'], {'rehearse_enabled': False}, rp)
        ok('CLI: комната с rehearse_enabled=false — «выключено», код 0', rc == 0 and 'выключено' in txt, txt)
        os.makedirs(os.path.join(d, 'nolive-gen'))
        txt, rc = cli(['--room', 'bedroom', '--live', os.path.join(d, 'нет.json'), '--generations', os.path.join(d, 'nolive-gen')],
                      {'rehearse_enabled': True}, rp)
        rep = json.load(open(rp + '.json')) if os.path.exists(rp + '.json') else {}
        ok('CLI: спальня без живого — код 0, DIGEST «репетировать нечего», отчёт и строка истории записаны',
           rc == 0 and 'DIGEST:банк спальня (репетиция): живого банка нет' in txt and rep.get('mode') == 'нет живого'
           and os.path.exists(rp + '.jsonl'), txt)
        p = subprocess.run([sys.executable, os.path.join(SCOUT, 'bank_rehearsal.py'), '--room', 'living'],
                           capture_output=True, text=True, timeout=60)
        ok('CLI (процесс): без комнаты / гостиная — отказ, код 2', p.returncode == 2,
           f'код {p.returncode}\n--- stdout ---\n{p.stdout}\n--- stderr ---\n{p.stderr}')
        # сторожа вышли SystemExit (нет style-scores спальни — так было в worktree 07.11): код 0 и WARN, не FAIL шага ночи.
        # Сторож — ПОДМЕНА: настоящий `room_guards.verdict` зовёт сборщик, каталог и базу — в чистом CI первым падает другое
        os.makedirs(os.path.join(d, 'se-gen'))
        lp = os.path.join(d, 'se-live.json')
        json.dump(B, open(lp, 'w', encoding='utf-8'), ensure_ascii=False)
        cp = os.path.join(d, 'se-cand.json')
        json.dump(B, open(cp, 'w', encoding='utf-8'), ensure_ascii=False)

        def exits(*a, **k):
            raise SystemExit('нет style-scores-bedroom.json')
        txt, rc = cli(['--room', 'bedroom', '--live', lp, '--generations', os.path.join(d, 'se-gen'), '--candidate', cp],
                      {'rehearse_enabled': True}, rp, verdict=exits)
        ok('CLI: сторожа вышли SystemExit — код 0, строка WARN:bank_rehearsal и DIGEST, живой цел',
           rc == 0 and 'WARN:bank_rehearsal: bedroom: упала: SystemExit' in txt
           and 'DIGEST:банк спальня (репетиция)' in txt and json.load(open(lp, encoding='utf-8')) == B, txt)
    print(f'test_bank_rehearsal: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
