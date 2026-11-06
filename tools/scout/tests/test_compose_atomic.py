#!/usr/bin/env python3
"""Сборщики комнат пишут кандидата атомарно и после проверки (room-bank-nightly-04 шаг 1, T-20261106-89; Codex к К4).

ЗАЧЕМ. Ночью `compose_bedroom --nightly` и `compose_hall` подменяют `sets-<комната>.next.json`, который читают `room_bootstrap check`,
спрос мешей и публикация комнат. Раньше файл писался ДО проверки, а спальня выходила 0 даже при жёстких нарушениях — вчерашний
годный кандидат затирался молча. Здесь `main` обоих сборщиков гоняется без базы (каталог и сборка — подставные), на песочнице:
  • жёсткое нарушение → код 1, строка `ERROR:compose_<комната>:`, прежний кандидат и его отчёт байт в байт, отказ — рядом;
  • годный → код 0, кандидат и отчёт подменены, временных файлов нет;
  • «пропали ячейки» (включена не вся комната / ячейка пуста по каталогу) — предупреждение, не отказ;
  • прихожая: id набора — от ячейки, происхождение в записи, матрица — стили × ступени (`room_identity.expected('hall')`);
  • спальня, правило ядра (T-20261106-89/2): стиль без ядра в каталоге пропускается — WARN + строка сводки, матрица без него,
    суд поколения 0 знает о пропуске из отчёта; стиль ЖИВОГО банка так исключиться не может — код 1, кандидат не тронут.

  python3 tests/test_compose_atomic.py
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile

SCOUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCOUT)

import compose_bedroom as CB  # noqa: E402
import compose_hall as CH  # noqa: E402
import room_bootstrap as RBo  # noqa: E402
import room_candidate as RC  # noqa: E402
import room_coverage as RCov  # noqa: E402
import room_identity as RI  # noqa: E402

bad = 0


def ok(name, cond, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


def _bank_for(room: str, R: dict, cells: list, broken: bool) -> list:
    prov = RI.provenance(room)
    out = []
    for c in cells:
        s = dict(zip(RI.CELL, c), room_type=room, items={}, provenance=dict(prov), set_id=RI.set_id_of(room, c))
        out.append(s)
    if broken:
        out[0]['set_id'] = out[0]['set_id'] + 'x'      # id не от своей ячейки — отказ идентичности
    return out


SEEN: dict = {}


def _run(mod, room: str, td: str, bank: list, problems: list, argv: list, gaps: dict | None = None,
         live: set | None = None) -> tuple[int, str]:
    """`main` сборщика без базы: каталог пустой, сборка и проверка состава — подставные; кандидат — в песочницу.
    `gaps` — что «нашёл» счёт ядра спальни (по умолчанию ядро есть у всех стилей), `live` — стили живого банка."""
    saved = {k: getattr(mod, k) for k in ('compose', 'check_bank')}
    cov = {k: getattr(RCov, k) for k in ('bedroom_core_counts', 'core_gaps', 'live_styles')}
    RCov.bedroom_core_counts = lambda *a, **k: {}
    RCov.core_gaps = lambda *a, **k: dict(gaps or {})
    RCov.live_styles = lambda *a, **k: live
    SEEN.clear()
    extra = {'load_items': lambda *a, **k: ([], []) if mod is CB else []}
    saved.update({k: getattr(mod, k) for k in extra})
    out = os.path.join(td, f'sets-{room}.next.json')
    os.environ['ROOM_SETS_OUTPUT'] = out
    rep = {'cells': [], 'shortage': {}, 'by_role': {}}
    def compose(rooms, C, *a, **k):
        SEEN['styles'] = list(C.R['styles']) if hasattr(C, 'R') else None
        return json.loads(json.dumps(bank)), dict(rep)
    mod.compose = compose
    mod.check_bank = lambda *a, **k: list(problems)
    for k, v in extra.items():
        setattr(mod, k, v)
    import catalog_items as CI
    ms = CI.mesh_state
    CI.mesh_state = lambda *a, **k: (set(), set(), set())
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = mod.main(argv)
    finally:
        for k, v in saved.items():
            setattr(mod, k, v)
        for k, v in cov.items():
            setattr(RCov, k, v)
        CI.mesh_state = ms
        os.environ.pop('ROOM_SETS_OUTPUT', None)
    return rc, buf.getvalue()


def case(mod, room: str, R: dict, want: list, argv: list) -> None:
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, f'sets-{room}.next.json')
        old, old_rep = b'[{"old": 1}]', b'{"old": true}'
        open(out, 'wb').write(old)
        open(RC.report_path(out), 'wb').write(old_rep)
        rc, txt = _run(mod, room, td, _bank_for(room, R, want, broken=False), ['x: нет layout'], argv)
        ok(f'{room}: нарушение состава — код 1, ERROR, прежний кандидат и отчёт байт в байт, отказ рядом',
           rc == 1 and f'ERROR:compose_{room}:' in txt and open(out, 'rb').read() == old
           and open(RC.report_path(out), 'rb').read() == old_rep and os.path.exists(RC.rejected_path(out)), (rc, txt[-400:]))
        rc, txt = _run(mod, room, td, _bank_for(room, R, want, broken=True), [], argv)
        ok(f'{room}: id не от ячейки — код 1, прежний кандидат цел', rc == 1 and open(out, 'rb').read() == old, (rc, txt[-400:]))
        good = _bank_for(room, R, want, broken=False)
        rc, txt = _run(mod, room, td, good, ['~ x: декор'], argv)
        rep = json.load(open(RC.report_path(out)))
        ok(f'{room}: годный — код 0, кандидат подменён, отчёт с check и candidate_written, временных нет',
           rc == 0 and json.load(open(out)) == good and rep['candidate_written'] is True and rep['check']['warn'] == ['x: декор']
           and not [f for f in os.listdir(td) if '.tmp-' in f], (rc, txt[-400:]))
        rc, txt = _run(mod, room, td, good[1:], [], argv)
        ok(f'{room}: пропала ячейка — предупреждение, не отказ (полноту судит банк)',
           rc == 0 and json.load(open(out)) == good[1:]
           and any(w.startswith(RC.LOST) for w in json.load(open(RC.report_path(out)))['check']['warn']), (rc, txt[-400:]))


def core_case(R: dict) -> None:
    """Правило ядра спальни: пропуск нового стиля — WARN; исключение стиля живого банка — FAIL; суд знает о пропуске."""
    old5 = [s for s in R['styles'] if s != 'неоклассика']
    R5 = dict(R, styles=old5)
    miss = ['шкафа/комода', 'тумбы']
    ok('спальня: правило ядра включено в составе (style_requires_core)', R.get('style_requires_core') is True)
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, 'sets-bedroom.next.json')
        bank5 = _bank_for('bedroom', R5, CB.cells(R5), broken=False)
        rc, txt = _run(CB, 'bedroom', td, bank5, [], [], gaps={'неоклассика': miss}, live=set(old5))
        rep = json.load(open(RC.report_path(out)))
        line = RCov.skip_text('неоклассика', miss)
        ok('спальня: неоклассика без ядра — пропущена: код 0, кандидат из 5 стилей записан, сборщик её не собирал, '
           'WARN и строка сводки «спальня: неоклассика пропущена — нет шкафа/комода/тумбы в стиле», «пропали ячейки» нет',
           rc == 0 and json.load(open(out)) == bank5 and SEEN.get('styles') == old5
           and f'WARN:compose_bedroom: {line}' in txt and f'DIGEST:{line}' in txt
           and line == 'спальня: неоклассика пропущена — нет шкафа/комода/тумбы в стиле'
           and rep.get('skipped_styles') == {'неоклассика': miss} and not any(w.startswith(RC.LOST) for w in rep['check']['warn']),
           (rc, SEEN, txt[-500:]))
        chk = CB.check_bank
        CB.check_bank = lambda *a, **k: []
        lv = RCov.live_styles
        RCov.live_styles = lambda *a, **k: set(old5)
        try:
            sk = RBo.skipped_of(out)
            ok('суд поколения 0: пропуск читает из отчёта кандидата, матрица без неоклассики — отказов 0',
               sk == {'неоклассика': miss} and RBo.verdict('bedroom', bank5, skipped=sk) == [], RBo.verdict('bedroom', bank5, skipped=sk)[:2])
            ok('суд поколения 0: без отчёта о пропуске те же 5 стилей — «пропали ячейки» (полная матрица)',
               any(x.startswith(RC.LOST) for x in RBo.verdict('bedroom', bank5)))
            v = RBo.verdict('bedroom', bank5, skipped={'сканди': miss})
            ok('суд поколения 0: в отчёте пропущен стиль живого банка — отказ', len(v) == 1 and 'сканди' in v[0], v)
        finally:
            CB.check_bank, RCov.live_styles = chk, lv
        old = open(out, 'rb').read()
        rc, txt = _run(CB, 'bedroom', td, bank5, [], [], gaps={'сканди': ['шкафа/комода'], 'неоклассика': miss}, live=set(old5))
        ok('спальня: стиль живого банка (сканди) остался без ядра — код 1 (сводка FAIL), ERROR, сборки не было, кандидат цел',
           rc == 1 and 'ERROR:compose_bedroom: стиль живого банка без ядра — сканди' in txt and 'WARN:' not in txt
           and 'styles' not in SEEN and open(out, 'rb').read() == old, (rc, txt[-400:]))
        rc, txt = _run(CB, 'bedroom', td, bank5, [], [], gaps={s: miss for s in R['styles']}, live=None)
        ok('спальня: живого банка нет, ядра нет ни у одного стиля — код 1, собирать нечего', rc == 1
           and 'ни у одного стиля нет ядра' in txt and open(out, 'rb').read() == old, (rc, txt[-300:]))


def main() -> int:
    Rb = CB.rules()
    case(CB, 'bedroom', Rb, CB.cells(Rb), [])
    core_case(Rb)
    Rh = CH.rules()
    want = RI.expected('hall')
    ok('прихожая: матрица room_identity = compose_hall.cells (стили × ступени), без повторов',
       want == CH.cells(Rh) and len(want) == len(Rh['styles']) * len(Rh['tiers']) == len(set(want)), want[:2])
    case(CH, 'hall', Rh, want, [])
    print(f'compose_atomic: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
