#!/usr/bin/env python3
"""Поколение 0 банка спальни: bootstrap, повтор, откат, сбой в каждом окне; готовность спальни в `bank_pending`
(room-bank-01 этап В, T-20261106-70; обязательные тесты разбора Codex `_intake/codex/room-bank-2026-11-06-answer.md`:
«bootstrap и повторный bootstrap», «identity спальни», «профиль/composer SHA mismatch»).

Всё — в песочнице (временная папка), живые банки и правила не трогаются; CLI — только пути отказа (ничего не пишут).

  python3 tests/test_room_bootstrap.py
"""
from __future__ import annotations

import contextlib
import gzip
import io
import json
import os
import subprocess
import sys
import tempfile

SCOUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCOUT)

import bank_pending as BP  # noqa: E402
import compose_bedroom as CB  # noqa: E402
import bank_refresh as RF  # noqa: E402
import room_bank_spec as RBS  # noqa: E402
import room_bootstrap as RBO  # noqa: E402
import room_identity as RI  # noqa: E402
import room_ready as RR  # noqa: E402

bad = 0


def ok(name, cond, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


def quiet(f, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = f(*a, **k)
    return rc, buf.getvalue()


WANT = RI.expected('bedroom')
PROV = RI.provenance('bedroom')


def candidate(**over) -> list:
    out = []
    for c in WANT:
        s = dict(zip(RI.CELL, c), room_type='bedroom', items={'кровать': {'mid': 1, 'eid': 'a', 'sid': '1_a'}},
                 alternates={'кровать': ['x', 'y', 'z']}, set_id=RI.set_id_of('bedroom', c), provenance=dict(PROV))
        out.append(s)
    return out


def ident(room, c):
    return RI.check(c, WANT, PROV, room)


def sandbox(td: str, tag: str) -> tuple[dict, str]:
    d = os.path.join(td, tag)
    os.makedirs(d)
    P = {'live': os.path.join(d, 'sets-bedroom.json'), 'lock': os.path.join(d, 'exam.lock'),
         'manifest': os.path.join(d, 'prom.json'), 'gen': os.path.join(d, 'gens'),
         'journal': os.path.join(d, 'gens', 'journal.jsonl'), 'hold': os.path.join(d, 'gens', 'hold.json'),
         'intent': os.path.join(d, 'gens', 'intent.json'), 'room': 'bedroom', 'snap': 'sets-bedroom'}
    cp = os.path.join(d, 'sets-bedroom.next.json')
    json.dump(candidate(), open(cp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return P, cp


def main() -> int:
    ON = {'write_enabled': True}
    with tempfile.TemporaryDirectory() as td:
        P, cp = sandbox(td, 'a')
        run = lambda R=ON, confirm=True, **k: quiet(RBO.run, P, R, 'bedroom', cp, confirm=confirm,  # noqa: E731
                                                     verdict_fn=k.get('v', ident))
        rc, out = run(confirm=False)
        ok('без --confirm-lead — код 2, живого нет', rc == 2 and 'confirm-lead' in out and not os.path.exists(P['live']), out)
        rc, out = run(R={'write_enabled': False})
        ok('флаг rooms.bedroom.write_enabled=false — код 2 «выключено», живого нет',
           rc == 2 and 'rooms.bedroom.write_enabled=false' in out and not os.path.exists(P['live']), out)
        rc, out = quiet(RBO.run, P, ON, 'living', cp, confirm=True)
        ok('гостиная — отказ (у неё живой банк есть)', rc == 2, out)
        open(P['lock'], 'w').close()
        rc, out = run()
        os.replace(P['lock'], P['lock'] + '.off')
        ok('exam.lock — отказ, живого нет', rc == 1 and not os.path.exists(P['live']), out)
        for name, mut, want in (
                ('пропала ячейка', lambda c: c[:-1], 'пропали ячейки'),
                ('дубль ячейки', lambda c: c + [c[0]], 'дубль ячейки'),
                ('id от состава', lambda c: [dict(c[0], set_id='bed-12345678')] + c[1:], 'set_id не от своей ячейки'),
                ('профиль правлен без версии', lambda c: [dict(x, provenance=dict(PROV, content_sha='0' * 12)) for x in c],
                 'происхождение content_sha'),
                ('сборщик другой', lambda c: [dict(x, provenance=dict(PROV, composer_sha='0' * 12)) for x in c],
                 'происхождение composer_sha')):
            Pm, cpm = sandbox(td, 'm-' + str(abs(hash(name)) % 10 ** 6))
            json.dump(mut(candidate()), open(cpm, 'w', encoding='utf-8'), ensure_ascii=False)
            rc, out = quiet(RBO.run, Pm, ON, 'bedroom', cpm, confirm=True, verdict_fn=ident)
            ok(f'кандидат: {name} — отказ «{want}», живого нет', rc == 1 and want in out and not os.path.exists(Pm['live']), out)
        rc, out = run(v=lambda r, c: ['раскладка: жёсткие нарушения'])
        ok('строгая проверка состава не прошла — отказ', rc == 1 and 'жёсткие' in out and not os.path.exists(P['live']), out)

        rc, out = run()
        raw = open(cp, 'rb').read()
        J = RF.journal(P)
        ok('bootstrap: живой = кандидат байт в байт, журнал «bootstrap, поколение 0», намерения нет',
           rc == 0 and open(P['live'], 'rb').read() == raw and [r['kind'] for r in J] == ['bootstrap']
           and J[0]['generation'] == 0 and J[0]['live_sha_before'] is None and J[0]['cells'] == len(WANT)
           and not os.path.exists(P['intent']), out)
        ok('снимок поколения 0 — сам кандидат (sets-bedroom-….json.gz), происхождение в журнале',
           gzip.decompress(open(J[0]['snapshot'], 'rb').read()) == raw
           and os.path.basename(J[0]['snapshot']).startswith('sets-bedroom-') and J[0]['provenance'] == PROV)
        rc, out = run()
        ok('повторный bootstrap при живом — отказ, живой не тронут', rc == 1 and 'уже есть' in out
           and open(P['live'], 'rb').read() == raw and len(RF.journal(P)) == 1, out)
        rc, out = quiet(RF.list_gens, P)
        ok('`bank_refresh list` комнаты показывает поколение 0', 'bootstrap' in out and f'ячеек {len(WANT)}' in out, out)

        rc, out = quiet(RBO.rollback, P, 'bedroom', confirm=False)
        ok('откат без --confirm-lead — код 2', rc == 2 and os.path.exists(P['live']), out)
        rc, out = quiet(RBO.rollback, P, 'bedroom', confirm=True)
        aside = RF.journal(P)[-1]['snapshot']
        ok('откат поколения 0: живого нет, файл переименован в папку поколений (не удалён), журнал unbootstrap',
           rc == 0 and not os.path.exists(P['live']) and open(aside, 'rb').read() == raw
           and RF.journal(P)[-1]['kind'] == 'unbootstrap', out)
        rc, out = quiet(RBO.rollback, P, 'bedroom', confirm=True)
        ok('второй откат — отказ (последнее в журнале не bootstrap)', rc == 1, out)
        rc, out = run()
        ok('повторный bootstrap после отката — можно, помечен repeat', rc == 0 and RF.journal(P)[-1]['repeat'] is True
           and open(P['live'], 'rb').read() == raw, out)
        open(P['live'], 'ab').write(b' ')
        rc, out = quiet(RBO.rollback, P, 'bedroom', confirm=True)
        ok('живой менялся после bootstrap — откат отказ, не тронут', rc == 1 and 'менялся' in out and os.path.exists(P['live']),
           out)
        J2 = RF.journal(P)
        J2.append({'gen': 'w1', 'kind': 'write'})
        with open(P['journal'], 'a', encoding='utf-8') as f:
            f.write(json.dumps({'gen': 'w1', 'kind': 'write', 'at': 'x', 'snapshot': 'x'}) + '\n')
        rc, out = quiet(RBO.rollback, P, 'bedroom', confirm=True)
        ok('после bootstrap была запись писателя — откат поколения 0 отказ (сперва откат писателя)', rc == 1
           and 'не bootstrap' in out, out)

        # сбои в каждом окне
        P2, cp2 = sandbox(td, 'crash')
        keep = RF._atomic
        RF._atomic = lambda path, data: (_ for _ in ()).throw(OSError('диск')) if path == P2['live'] else keep(path, data)
        try:
            rc, out = quiet(RBO.run, P2, ON, 'bedroom', cp2, confirm=True, verdict_fn=ident)
        finally:
            RF._atomic = keep
        ok('сбой записи до rename — живого нет, намерение снято', rc == 1 and not os.path.exists(P2['live'])
           and not os.path.exists(P2['intent']), out)
        keepj = RF._journal_add
        RF._journal_add = lambda P_, rec: (_ for _ in ()).throw(OSError('сбой')) if rec.get('kind') == 'bootstrap' else keepj(P_, rec)
        try:
            quiet(RBO.run, P2, ON, 'bedroom', cp2, confirm=True, verdict_fn=ident)
        except OSError:
            pass
        finally:
            RF._journal_add = keepj
        ok('сбой после rename до журнала — живой новый, намерение осталось', os.path.exists(P2['live'])
           and os.path.exists(P2['intent']) and not RF.journal(P2))
        rc, out = quiet(RF.recover, P2)
        J = RF.journal(P2)
        ok('`bank_refresh.recover` доводит bootstrap: журнал с recovered, намерение снято', rc == 0 and len(J) == 1
           and J[0]['kind'] == 'bootstrap' and J[0].get('recovered') and not os.path.exists(P2['intent']), out)
        P3, cp3 = sandbox(td, 'abort')
        RF._intent_save(P3, {'gen': 'g9', 'snapshot': 'x', 'live_sha_before': None, 'live_sha_after': 'f' * 64, 'hold': None,
                             'record': {'gen': 'g9', 'kind': 'bootstrap'}})
        rc, out = quiet(RBO.run, P3, ON, 'bedroom', cp3, confirm=True, verdict_fn=ident)
        J = RF.journal(P3)
        ok('намерение прошлого bootstrap, живого нет — abort в журнал, затем новый bootstrap', rc == 0
           and [(r['kind'], r.get('action')) for r in J] == [('recover', 'abort'), ('bootstrap', None)], out)
        P4, cp4 = sandbox(td, 'foreign')
        open(P4['live'], 'w').write('[]')
        RF._intent_save(P4, {'gen': 'g8', 'snapshot': 'x', 'live_sha_before': None, 'live_sha_after': 'f' * 64, 'hold': None,
                             'record': {'gen': 'g8', 'kind': 'bootstrap'}})
        rc, out = quiet(RBO.recover, P4)
        ok('намерение есть, живой ни «до», ни «после» — отказ, не трогаем', rc == 1 and open(P4['live']).read() == '[]', out)
        rc, out = quiet(RBO.recover, P4, True)
        ok('`recover --abandon` — намерение снято, живой как есть', rc == 0 and not os.path.exists(P4['intent'])
           and open(P4['live']).read() == '[]', out)

        # запас замен: у поколения 0 — предупреждение в журнал (ячейка, роль, сколько), у ночной замены (этап Г) — отказ (T-70/2)
        rec0 = dict(candidate()[0], items={'кровать': {}, 'шкаф': {}, 'лампа': {}, 'тумба прикроватная': {}},
                    alternates={'кровать': ['x'], 'шкаф': ['x', 'y', 'z'], 'лампа': [], 'тумба прикроватная': ['x', 'y']})
        ok('spare_short: роли с заменами < 3 по порядку предметов, мебель помечена',
           CB.spare_short(rec0) == [('кровать', 1, True), ('лампа', 0, False), ('тумба прикроватная', 2, True)],
           CB.spare_short(rec0))
        try:
            CB.check_bank([], {}, (), spare='мягко')
            ok('check_bank: неизвестный режим запаса — отказ', False)
        except ValueError:
            ok('check_bank: неизвестный режим запаса — отказ (не молча жёсткий)', True)
        ok('по умолчанию у check_bank запас жёсткий (ночная замена), у bootstrap — предупреждение',
           CB.check_bank.__defaults__ == ('hard',) and RBO.SPARE == 'warn')
        seen = []
        keep_cb = CB.check_bank

        def fake_cb(bank, R, tol, spare='hard'):
            seen.append(spare)
            return [('' if spare == 'hard' else '~ ') + f"{b['set_id']}: {r} — альтернатив {n} < 3"
                    for b in bank for r, n, major in CB.spare_short(b) if major]
        CB.check_bank = fake_cb
        try:
            c5 = candidate()
            c5[3] = dict(c5[3], items={'кровать': {}, 'шкаф': {}}, alternates={'кровать': ['x'], 'шкаф': []})
            c5[7] = dict(c5[7], items={'кровать': {}, 'лампа': {}}, alternates={'кровать': ['x', 'y', 'z'], 'лампа': []})
            ok('суд: spare=hard — нехватка замен мебели — отказ', len(RBO.verdict('bedroom', c5, spare='hard')) == 2)
            ok('суд: по умолчанию (поколение 0) — не отказ', RBO.verdict('bedroom', c5) == [] and seen[-1] == 'warn')
            P5, cp5 = sandbox(td, 'spare')
            json.dump(c5, open(cp5, 'w', encoding='utf-8'), ensure_ascii=False)
            rc, out = quiet(RBO.run, P5, ON, 'bedroom', cp5, confirm=True)
            W = (RF.journal(P5) or [{}])[-1].get('warnings')
            ok('bootstrap с нехваткой замен мебели: код 0, в журнале поколения 2 предупреждения (ячейка, роль, замен), WARN в выводе',
               rc == 0 and W == [{'set_id': c5[3]['set_id'], 'cell': '|'.join(RI.cell(c5[3])), 'role': 'кровать', 'alternates': 1,
                                  'min': 3},
                                 {'set_id': c5[3]['set_id'], 'cell': '|'.join(RI.cell(c5[3])), 'role': 'шкаф', 'alternates': 0,
                                  'min': 3}]
               and out.count('WARN:room_bootstrap:') == 2 and 'предупреждений 2' in out, (rc, W, out))
            P6, cp6 = sandbox(td, 'spare0')
            rc, out = quiet(RBO.run, P6, ON, 'bedroom', cp6, confirm=True)
            ok('без нехватки — warnings пуст', rc == 0 and RF.journal(P6)[-1]['warnings'] == [], out)
        finally:
            CB.check_bank = keep_cb

        # готовность спальни в bank_pending: ключ ячейки и привязка
        saved = {k: getattr(BP, k) for k in ('SPEC', 'RULES_PATH', 'STATE', 'CANDIDATE', 'LIVE', 'DEMO_DATA', 'PREPARE_REPORT')}
        RBS.bind(BP, RBS.for_room('bedroom'))
        try:
            rec = dict(candidate()[0], items={'кровать': {'mid': 1, 'eid': 'a'}, 'лампа': {'mid': 2, 'eid': 'b'},
                                               'шкаф': {'mid': 3, 'eid': 'c'}})
            F = RR.Facts({'1:a': {**_row('ready', '1_a'), 'published_3d': True},
                          '3:c': _row('blocked', '3_c', ['orientation_review_pending'])}, '', {'1_a', '3_c'}, {})
            st, _ = BP.update({}, [rec], F, now=1)
            c = st['cells'][BP.key(rec)]
            ok('bank_pending спальни: ключ room_id|purpose|band|style|tier, кровать и шкаф (разворот) готовы, лампа готова',
               BP.key(rec) == '|'.join(map(str, RI.cell(rec))) and c['status'] == 'ready' and c['missing'] == {}, c)
            F2 = RR.Facts({}, '', set(), {})
            st, _ = BP.update({}, [rec], F2, now=1)
            c = st['cells'][BP.key(rec)]
            ok('без привязки — ячейка ждёт меш (wait_asset, в спрос мешей 2 предмета)', c['status'] == 'wait_asset'
               and c['mesh_missing'] == 2, c)
        finally:
            for k, v in saved.items():
                setattr(BP, k, v)
        ok('после возврата — у bank_pending снова гостиная', BP.SPEC.room == 'living')

        # CLI: только пути отказа, ничего не пишут
        home = os.path.join(td, 'home')
        os.makedirs(home)
        env = {**os.environ, 'HOME': home}
        before = set(os.listdir(SCOUT))
        for argv, want_rc, want in ((['--room', 'bedroom', 'run'], 2, 'confirm-lead'),
                                    (['--room', 'bedroom', 'run', '--confirm-lead'], 2, 'rooms.bedroom.write_enabled=false'),
                                    (['--room', 'bedroom', 'rollback'], 2, 'confirm-lead'),
                                    (['run', '--confirm-lead'], 2, 'у гостиной'),
                                    (['--room', 'kitchen', 'run'], 1, 'банка такой комнаты нет')):
            p = subprocess.run([sys.executable, os.path.join(SCOUT, 'room_bootstrap.py'), *argv], cwd=SCOUT, env=env,
                               capture_output=True, text=True, timeout=120)
            txt = p.stdout + p.stderr
            ok(f'`room_bootstrap.py {" ".join(argv)}` — код {want_rc}, «{want}»', p.returncode == want_rc and want in txt,
               (p.returncode, txt[-300:]))
        made = set(os.listdir(SCOUT)) - before
        ok('CLI отказов не создал файлов рядом и в HOME', not made and not os.listdir(home), (made, os.listdir(home)))
    print(f'room_bootstrap: ошибок {bad}')
    return 1 if bad else 0


def _row(status, mesh_id, reasons=()):
    return {'status': status, 'asset_id': 'a:' + 'f' * 64, 'mesh_id': mesh_id, 'local_path': '/x.glb',
            'representative_offer_id': None, 'via_family': False, 'generation_key': 'g', 'revision_key': 'r', 'source_sha': 's',
            'orientation': None, 'passport': None, 'local_3d': True, 'solver': True, 'appearance': True, 'published_3d': False,
            'reasons': list(reasons), 'warnings': [], 'snapshot_id': 'snap' * 4}


if __name__ == '__main__':
    sys.exit(main())
