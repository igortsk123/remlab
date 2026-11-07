#!/usr/bin/env python3
"""Настоящие шаги цепочки банка комнаты: подготовка → подмена → писатель «добавить» (room-bank-01 этап Ж, T-20261107-04/3).

ЗАЧЕМ. Спальня получает новые ячейки (шестой стиль: матрица профиля 72, живой 60) штатной ночью. Ведущий 07.11 (вариант А):
писатель умеет «добавить» — новая ячейка в ХВОСТ со своим id, у прежних номер и id не меняются, журнал `add`, откат по SHA как
раньше; ячейку живого, которой нет в матрице профиля, НЕ удаляем — пометка `retired`, в витрину не идёт. Здесь — каждый исход
на стенде во временной папке: файлы правил, профиля и живые банки репо тест не читает (урок CI T-04/2), сторожа — заглушка
(их тесты — tests/test_room_guards.py), база не нужна.

  python3 tests/test_room_bank_chain.py
"""
from __future__ import annotations

import contextlib
import copy
import dataclasses
import io
import json
import os
import sys
import tempfile
import traceback

SCOUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCOUT)

import bank_pending as BP  # noqa: E402
import bank_refresh as RF  # noqa: E402
import bank_run as RUN  # noqa: E402
import demo_room as DR  # noqa: E402
import room_bank_chain as RBC  # noqa: E402
import room_bank_spec as RBS  # noqa: E402
import room_guards as RG  # noqa: E402
import room_identity as RI  # noqa: E402
import room_publish as RP  # noqa: E402

bad = 0


def ok(name, cond, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


def quiet(fn, *a, **k):
    """Вызов шага с выводом в строку; исключение — текст целиком в вывод, код None (провал теста виден в логе)."""
    buf = io.StringIO()
    rc = None
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            rc = fn(*a, **k)
        except BaseException:  # noqa: BLE001
            buf.write('\n--- исключение ---\n' + traceback.format_exc())
    return rc, buf.getvalue()


def cell(room_id, purpose, band, style, tier, n=0) -> dict:
    c = (room_id, purpose, band, style, tier)
    return {'room_id': room_id, 'purpose': purpose, 'band': band, 'style': style, 'tier': tier,
            'set_id': RI.set_id_of('bedroom', c), 'total': 1000 + n,
            'items': {'кровать': {'mid': '1', 'eid': f'b{style}{tier}{n}', 'qty': 1, 'price': 1000 + n}},
            'alternates': {}, 'layout': {}}


TIERS = ('эконом', 'комфорт', 'премиум')


def live_bank() -> list:
    """6 живых ячеек (2 стиля × 3 тира) + 1 ячейка комнаты, которой больше нет в профиле (кандидат за неё — без неё)."""
    out = [cell('bedroom-1', 'couple', '13.2', st, t, i) for i, (st, t) in enumerate((s, t) for s in ('сканди', 'лофт')
                                                                                    for t in TIERS)]
    return out + [cell('bedroom-9', 'couple', '9.0', 'сканди', 'эконом', 99)]


def other(s: dict, tag: str = 'x') -> dict:
    t = copy.deepcopy(s)
    t['items']['кровать']['eid'] += tag
    t['items']['кровать']['price'] += 1
    return t


def spec_in(td: str, flags: dict):
    """Спальня с путями во временной папке и своим файлом правил."""
    rp = os.path.join(td, 'rules.json')
    json.dump({'rooms': {'bedroom': flags}}, open(rp, 'w', encoding='utf-8'))
    j = lambda n: os.path.join(td, n)  # noqa: E731
    return dataclasses.replace(
        RBS.for_room('bedroom', {}), live=j('sets-bedroom.json'), candidate=j('sets-bedroom.next.json'),
        candidate_default=j('sets-bedroom.next.json'), prepare_report=j('prep.json'), pending_state=j('pending.json'),
        demo_data=j('demo-data.json'), promote_manifest=j('promote.json'), promote_work=j('promote'),
        generations=j('gens'), lock=j('exam.lock'), rules_path=rp)


def dump(path: str, obj) -> bytes:
    raw = json.dumps(obj, ensure_ascii=False, indent=1).encode('utf-8')
    open(path, 'wb').write(raw)
    return raw


def main() -> int:
    live = live_bank()
    gone = RG.cell_key(live[6])                                          # ячейка вне матрицы профиля
    new = [cell('bedroom-1', 'couple', '13.2', 'неоклассика', t, 50 + i) for i, t in enumerate(TIERS)]
    cand = [other(live[0])] + copy.deepcopy(live[1:6]) + new             # живые (без снятой) + 3 новые в порядке матрицы
    want = {RG.cell_key(s) for s in cand}

    # ——— (1) build: смешанный банк и manifest — чистая функция ———
    rows = ([{'cell': RG.cell_key(cand[0]), 'set_id': cand[0]['set_id'], 'decision': 'promote', 'new': False}]
            + [{'cell': RG.cell_key(s), 'set_id': s['set_id'], 'decision': 'same', 'new': False} for s in cand[1:6]]
            + [{'cell': RG.cell_key(new[0]), 'set_id': new[0]['set_id'], 'decision': 'promote', 'new': True},
               {'cell': RG.cell_key(new[1]), 'set_id': new[1]['set_id'], 'decision': 'promote', 'new': True},
               {'cell': RG.cell_key(new[2]), 'set_id': new[2]['set_id'], 'decision': 'waiting', 'new': True,
                'reasons': ['кровать 1:x: нет модели']}])
    rep = {'take': [RG.cell_key(cand[0]), RG.cell_key(new[0]), RG.cell_key(new[1])], 'rows': rows, 'cap': 3}
    hyb, f = RBC.build('bedroom', rep, live, cand, want, BP.candidate_hash)
    ok('build: прежние 7 ячеек на своих номерах и с прежними id, 2 принятые новые — в хвост (8, 9) в порядке матрицы',
       [s['set_id'] for s in hyb] == [s['set_id'] for s in live] + [new[0]['set_id'], new[1]['set_id']]
       and hyb[0] == cand[0] and hyb[1:6] == live[1:6], [s['set_id'] for s in hyb])
    ok('build: ячейка вне матрицы — пометка retired (не удалена; всё прочее как в живом)',
       hyb[6] == {**live[6], 'retired': True} and f['retired'] == [7], (f['retired'], hyb[6].get('retired')))
    ok('build: promoted [1, 8, 9], новые [8, 9], ждущая новая — в pending_new (в банк не идёт)',
       f['promoted'] == [1, 8, 9] and f['new_cells'] == [8, 9]
       and [p['cell'] for p in f['pending_new']] == [RG.cell_key(new[2])] and f['pending_new'][0]['decision'] == 'wait',
       (f['promoted'], f['new_cells'], f['pending_new']))
    ok('build: строки manifest — отпечаток кандидата у продвигаемых совпадает с ячейкой смешанного (писатель сверяет)',
       all(c['candidate_hash'] == BP.candidate_hash(hyb[c['n'] - 1]) for c in f['cells'] if c['decision'] == 'promote')
       and {c['n'] for c in f['cells'] if c['decision'] == 'promote'} == {1, 8, 9})
    hyb2, f2 = RBC.build('bedroom', {**rep, 'take': rep['take'] + [gone]}, live, cand, want, BP.candidate_hash)
    ok('build: ячейка, которую подменяют, не получает retired', 7 not in f2['retired'])
    retired_twice = copy.deepcopy(live)
    retired_twice[6]['retired'] = True
    _h, f3 = RBC.build('bedroom', {'take': [], 'rows': [], 'cap': 3}, retired_twice, cand, want, BP.candidate_hash)
    ok('build: уже снятая ячейка второй раз не помечается (retired пусто)', f3['retired'] == [], f3['retired'])

    saved_bp = dict(vars(BP))
    try:
        with tempfile.TemporaryDirectory(prefix='room-chain-') as td:
            # ——— (2) подготовка ———
            os.makedirs(os.path.join(td, 'off'))
            S = spec_in(os.path.join(td, 'off'), {})
            rc, out = quiet(RBC.prepare, S, 'N1')
            ok('prepare: флаг выключен — 0, «выключено», отчёт {disabled} (подмена этой ночи не судит)',
               rc == 0 and 'rooms.bedroom.prepare_enabled=false' in out
               and json.load(open(S.prepare_report)).get('disabled') is True, out)
            d = os.path.join(td, 'p')
            os.makedirs(d)
            S = spec_in(d, {'prepare_enabled': True, 'promote_enabled': True, 'write_enabled': True})
            lraw = dump(S.live, live)
            rc, out = quiet(RBC.prepare, S, 'N1', identity_fn=lambda c: [], content_fn=lambda c: [])
            ok('prepare: кандидата нет — 1, «не читается», отчёт с error', rc == 1 and 'не читается' in out
               and 'error' in json.load(open(S.prepare_report)), out)
            dump(S.candidate, cand)
            rc, out = quiet(RBC.prepare, S, 'N1', identity_fn=lambda c: ['пропали ячейки: 1'], content_fn=lambda c: [])
            ok('prepare: идентичность кандидата нарушена — 1, цепочка дальше не идёт', rc == 1 and 'идентичность' in out, out)
            rc, out = quiet(RBC.prepare, S, 'N1', identity_fn=lambda c: [], content_fn=lambda c: [],
                            now=os.path.getmtime(S.candidate) + 13 * 3600)
            ok('prepare: кандидат старше 12 ч — 1 (не этой ночи)', rc == 1 and 'предел 12' in out, out)
            drift = copy.deepcopy(cand)
            drift[1]['set_id'] = 'bed-чужой'
            dump(S.candidate, drift)
            rc, out = quiet(RBC.prepare, S, 'N1', identity_fn=lambda c: [], content_fn=lambda c: [])
            ok('prepare: id живой ячейки ≠ id той же ячейки кандидата — 1 (писатель упал бы на дрейфе)',
               rc == 1 and 'id живых ячеек' in out, out)
            S2 = dataclasses.replace(S, candidate=S.live)
            rc, out = quiet(RBC.prepare, S2, 'N1', identity_fn=lambda c: [], content_fn=lambda c: [])
            ok('prepare: кандидат — это живой банк — 2', rc == 2, out)
            craw = dump(S.candidate, cand)
            rc, out = quiet(RBC.prepare, S, 'N1', identity_fn=lambda c: [], content_fn=lambda c: ['целое: ~ковёр'])
            prep = json.load(open(S.prepare_report))
            ok('prepare: годен — 0, паспорт ночи (sha байт), pending_due, новых 3; замечания к целому — WARN, не отказ',
               rc == 0 and prep.get('pending_due') is True and prep.get('candidate_sha') == RUN.sha(craw)
               and prep.get('new_cells') == 3 and json.load(open(RUN.passport_path(S.candidate)))['run_id'] == 'N1'
               and 'WARN:bank_prepare' in out and 'DIGEST:кандидат банка bedroom' in out, (rc, prep, out[-400:]))

            # ——— (3) подмена ———
            def verdict(room, cand_path, live_path, cand_raw=None, held_fn=None):
                c = json.loads(cand_raw)
                return rep, ['room_guards bedroom: заглушка'], c, json.load(open(live_path))
            rc, out = quiet(RBC.promote, S, 'N1', verdict_fn=verdict, want=want)
            ok('promote: ожидание (bank_pending) не этой ночи — отказ, manifest не пишет',
               rc == 1 and 'состояние ожидания' in out and not os.path.exists(S.promote_manifest), out)
            json.dump({'run_id': 'N1', 'candidate_sha': RUN.sha(craw), 'cells': {}}, open(S.pending_state, 'w'))
            rc, out = quiet(RBC.promote, S, 'N2', verdict_fn=verdict, want=want)
            ok('promote: чужой номер ночи — отказ', rc == 1 and 'не этой ночи' in out
               and not os.path.exists(S.promote_manifest), out)
            S_off = dataclasses.replace(S, rules_path=os.path.join(td, 'off', 'rules.json'))
            rc, out = quiet(RBC.promote, S_off, 'N1', verdict_fn=verdict, want=want)
            ok('promote: флаг выключен — 0, «выключено», manifest не пишет',
               rc == 0 and 'promote_enabled=false' in out and not os.path.exists(S.promote_manifest), out)

            def fatal(room, cand_path, live_path, cand_raw=None, held_fn=None):
                return ({'fatal': ['пропали ячейки'], 'rows': [], 'take': []}, [], json.loads(cand_raw),
                        json.load(open(live_path)))
            rc, out = quiet(RBC.promote, S, 'N1', verdict_fn=fatal, want=want)
            man = json.load(open(S.promote_manifest))
            ok('promote: кандидат не годен целиком — 1, manifest с fatal и без смешанного (писатель пропустит)',
               rc == 1 and man['fatal'] and man['hybrid'] is None, (rc, man.get('fatal')))
            rc, out = quiet(RBC.promote, S, 'N1', verdict_fn=verdict, want=want)
            man = json.load(open(S.promote_manifest))
            ok('promote: годен — 0, manifest писателя: комната, ночь, sha живого и смешанного, promoted/retired/new_cells',
               rc == 0 and man['room'] == 'bedroom' and man['run_id'] == 'N1' and man['live_sha'] == RUN.sha(lraw)
               and man['hybrid_sha'] == RUN.sha(open(man['hybrid'], 'rb').read()) and man['promoted'] == [1, 8, 9]
               and man['retired'] == [7] and man['new_cells'] == [8, 9] and 'DIGEST:банк bedroom (подмена)' in out,
               (rc, {k: man.get(k) for k in ('promoted', 'retired', 'new_cells', 'fatal')}, out[-300:]))
            ok('promote: живой банк не тронут', open(S.live, 'rb').read() == lraw)

            # ——— (4) писатель «добавить» и откат по SHA ———
            RBS.bind(RF, S, 'bank_refresh')
            P = S.refresh_paths()
            rc, out = quiet(RF.write, P, {'write_enabled': True}, run_id='N1')
            w = json.load(open(S.live))
            J = RF.journal(P)
            ok('писатель: записал — 9 ячеек, прежние 7 номеров и id те же, новые 8 и 9 — со своими id (set_id_of ячейки)',
               rc == 0 and len(w) == 9 and [s['set_id'] for s in w[:7]] == [s['set_id'] for s in live]
               and [s['set_id'] for s in w[7:]] == [new[0]['set_id'], new[1]['set_id']]
               and w[7]['set_id'] == RI.set_id_of('bedroom', RBS.for_room('bedroom', {}).cell(new[0])), out[-600:])
            ok('писатель: журнал — вид add, added_cells (номер, ячейка, id) и retired_cells',
               J[-1]['kind'] == 'add' and [c['n'] for c in J[-1]['added_cells']] == [8, 9]
               and J[-1]['added_cells'][0]['set_id'] == new[0]['set_id'] and [c['n'] for c in J[-1]['retired_cells']] == [7],
               J[-1] if J else None)
            ok('писатель: ячейка вне матрицы НЕ удалена — на своём номере с пометкой retired',
               w[6].get('retired') is True and w[6]['set_id'] == live[6]['set_id'])
            ok('писатель: дайджест — «новых ячеек 2», «снято с витрины (retired) 1»',
               'новых ячеек 2 [8, 9]' in out and 'снято с витрины (retired) 1 [7]' in out, out[-400:])
            shown = DR.load_bank(S.live)
            ok('витрина: снятая ячейка не идёт (demo_room.load_bank), остальные 8 — идут',
               RG.cell_key(w[6]) == gone and len(shown) == 8 and gone not in {RG.cell_key(s) for s in shown})
            ok('публикация: товары снятой ячейки не публикуются (room_publish.bank_offers)',
               '1:' + live[6]['items']['кровать']['eid'] not in RP.bank_offers(w)
               and '1:' + new[0]['items']['кровать']['eid'] in RP.bank_offers(w))
            rc2, out2 = quiet(RF.write, P, {'write_enabled': True}, run_id='N1')
            ok('писатель: тот же manifest второй раз — «уже записан», банк тот же',
               rc2 == 0 and 'уже записан' in out2 and json.load(open(S.live)) == w, out2)
            rc, out = quiet(RF.rollback, P, 'last')
            ok('откат по SHA: живой = байты «до» (новые сняты, пометка снята), журнал rollback',
               rc == 0 and open(S.live, 'rb').read() == lraw and RF.journal(P)[-1]['kind'] == 'rollback', out[-400:])
            hold = RBC._hold(S)
            ok('откат: запрет того же кандидата — у подменённых ячеек, и у новых тоже (hold.json)',
               set(hold) == {RG.cell_key(cand[0]), RG.cell_key(new[0]), RG.cell_key(new[1])}, sorted(hold))
            held = lambda s: hold.get(RG.cell_key(s)) == BP.candidate_hash(s)  # noqa: E731
            pr = RG.plan(live, cand, strict_fn=lambda s: [], ready_fn=lambda s: [], exam_fn=lambda s, o: [],
                         bank_fn=lambda b: [], share=1.0, order=RG.bank_order(live, cand), held_fn=held)
            kinds = {r['cell']: (r['decision'], r.get('kind')) for r in pr['rows']}
            ok('после отката тот же кандидат не идёт: подменённая и новые — rejected:held, ждущая новая — снова в суде',
               kinds[RG.cell_key(cand[0])] == ('rejected', 'held') and kinds[RG.cell_key(new[0])] == ('rejected', 'held')
               and kinds[RG.cell_key(new[2])] == ('promote', None), kinds)
            pr2 = RG.plan(live, cand, strict_fn=lambda s: [], ready_fn=lambda s: [], exam_fn=lambda s, o: [],
                          bank_fn=lambda b: [], share=0.5, order=RG.bank_order(live, cand))
            ok('предел ночи: новые ячейки считаются в долю (floor(0.5 × 7) = 3 подмены, остальное — deferred)',
               len(pr2['take']) == 3 and sum(1 for r in pr2['rows'] if r['decision'] == 'deferred') == 1,
               [(r['cell'][-20:], r['decision']) for r in pr2['rows']])
            ok('порядок смешанного: живые на своих номерах, новые — в хвост в порядке кандидата',
               RG.bank_order(live, cand) == [RG.cell_key(s) for s in live] + [RG.cell_key(s) for s in new])

            # ——— (5) писатель отказывает: новая ячейка без суда, retired с посторонней правкой, новая с чужим id ———
            def refused(tag: str, hybrid: list, promoted: list, retired: list, want_txt: str):
                d5 = os.path.join(td, 'w-' + tag)
                os.makedirs(d5)
                S5 = spec_in(d5, {'write_enabled': True})
                raw5 = dump(S5.live, live)
                hp = os.path.join(d5, 'hybrid.json')
                h5 = dump(hp, hybrid)
                cells = [{'n': n, 'cell': RG.cell_key(hybrid[n - 1]), 'decision': 'promote',
                          'candidate_hash': BP.candidate_hash(hybrid[n - 1])} for n in promoted]
                json.dump({'room': 'bedroom', 'run_id': 'N1', 'at': RBC._now(), 'live_sha': RUN.sha(raw5), 'hybrid': hp,
                           'hybrid_sha': RUN.sha(h5), 'promoted': promoted, 'retired': retired, 'cells': cells},
                          open(S5.promote_manifest, 'w'), ensure_ascii=False)
                RBS.bind(RF, S5, 'bank_refresh')
                rc5, out5 = quiet(RF.write, S5.refresh_paths(), {'write_enabled': True}, run_id='N1')
                ok(f'писатель: {tag} — отказ, живой не тронут', rc5 == 1 and want_txt in out5
                   and open(S5.live, 'rb').read() == raw5, out5[-300:])
            refused('новая ячейка без суда', copy.deepcopy(live) + [new[0]], [], [], 'новые ячейки без суда')
            r_bad = copy.deepcopy(live)
            r_bad[6] = {**other(live[6]), 'retired': True}
            refused('retired с правкой состава', r_bad, [], [7], 'retired')
            n_bad = copy.deepcopy(live) + [{**new[0], 'set_id': live[0]['set_id']}]
            refused('новая ячейка с id прежней', n_bad, [8], [], 'идентичность')
    finally:
        vars(BP).update(saved_bp)
        RBS.bind(RF, RBS.for_room(None), 'bank_refresh')
    print(f'test_room_bank_chain: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
