#!/usr/bin/env python3
"""АТОМАРНАЯ ЗАПИСЬ КАНДИДАТА БАНКА КОМНАТЫ (room-bank-nightly-04 шаг 1, T-20261106-89; Codex к К4: «сборщик пишет кандидата ДО
проверки и выходит 0 при жёстких ошибках»).

ЗАЧЕМ. Ночью сборщик комнаты (`compose_bedroom --nightly`, `compose_hall`) даёт кандидата `sets-<комната>.next.json`; его читают
`room_bootstrap check`, спрос мешей (`room_mesh_demand --hall-bank`) и публикация (`ROOM_PUBLISH=<комната>=next`). Раньше файл
писался `json.dump(open(out, 'w'))` ДО проверки: падение посреди записи оставляло обрезанный JSON, а набор с жёсткими нарушениями
затирал вчерашний годный — и шаг выходил 0, ночь не замечала. Теперь:
  • проверка — ДО записи (по банку в памяти); жёсткое нарушение → кандидат и его отчёт НЕ трогаются, отказ пишется рядом
    (`<банк>.rejected.json` + `.rejected.report.json` — для разбора), строка `ERROR:<шаг>: …` и код 1;
  • годный → временный файл в той же папке + fsync + `os.replace` (подмена целиком или никак), затем отчёт тем же способом;
  • «пропали ячейки» (комната не включена, ячейка пуста по каталогу) — НЕ отказ сборщика, а предупреждение: полноту матрицы судит
    банк (`room_bootstrap.verdict`), а свежий частичный кандидат нужен спросу мешей. Отказ — дубль/лишняя ячейка, id не от ячейки,
    происхождение, нарушения раскладки и состава.

  python3 room_candidate.py --selftest
"""
from __future__ import annotations

import json
import os
import sys

LOST = 'пропали ячейки'      # префикс строки `room_identity.check` — предупреждение сборщика, не отказ (см. выше)


def split(problems: list[str], ident: list[str]) -> tuple[list[str], list[str]]:
    """(жёсткие, предупреждения): «~ …» проверки состава и «пропали ячейки» идентичности — предупреждения, остальное — отказ."""
    hard = [p for p in problems if not p.startswith('~')] + [x for x in ident if not x.startswith(LOST)]
    warn = [p[2:] for p in problems if p.startswith('~')] + [x for x in ident if x.startswith(LOST)]
    return hard, warn


def write_json(path: str, obj) -> None:
    """Атомарно: временный файл рядом (та же ФС) → fsync → os.replace. Сбой до replace — прежний файл цел, временный убран."""
    d = os.path.dirname(os.path.abspath(path))
    tmp = os.path.join(d, f'.{os.path.basename(path)}.tmp-{os.getpid()}')
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=1)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def report_path(out: str, rejected: bool = False) -> str:
    base = os.path.splitext(out)[0]
    return f'{base}.rejected.report.json' if rejected else f'{base}.report.json'


def rejected_path(out: str) -> str:
    return os.path.splitext(out)[0] + '.rejected.json'


def commit(step: str, out: str, bank: list, report: dict, hard: list[str], warn: list[str]) -> int:
    """Записать кандидата, только если жёстких нет. Код: 0 — записан; 1 — отказ (прежний кандидат и отчёт не тронуты)."""
    report = dict(report, check={'hard': hard, 'warn': warn}, candidate_written=not hard)
    if hard:
        write_json(rejected_path(out), bank)
        write_json(report_path(out, True), report)
        print(f'ERROR:{step}: кандидат НЕ записан — нарушений {len(hard)} (первое: {hard[0]}); прежний {out} не тронут; '
              f'отказ для разбора — {rejected_path(out)}', flush=True)
        return 1
    write_json(out, bank)
    write_json(report_path(out), report)
    return 0


# ---------------------------------------------------------------- селфтест
def _selftest() -> int:
    import remlab_tmp  # временное селфтеста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)
    remlab_tmp.use('room_candidate-selftest')
    import contextlib
    import io
    import tempfile
    bad = 0

    def ok(name, cond, extra=''):
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
        bad += 0 if cond else 1
    h, w = split(['a: нет layout', '~ b: декор'], ['пропали ячейки: 3 из 60', 'set_id не от своей ячейки: 1'])
    ok('жёсткие: нарушение состава и id; предупреждения: «~» и пропавшие ячейки',
       h == ['a: нет layout', 'set_id не от своей ячейки: 1'] and w == ['b: декор', 'пропали ячейки: 3 из 60'], (h, w))
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, 'sets-x.next.json')
        write_json(out, [{'old': 1}])
        write_json(report_path(out), {'old': True})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = commit('compose_x', out, [{'new': 1}], {'r': 1}, ['a: нет layout'], [])
        ok('отказ: код 1, строка ERROR, прежний кандидат и отчёт целы, отказ рядом',
           rc == 1 and 'ERROR:compose_x:' in buf.getvalue() and json.load(open(out)) == [{'old': 1}]
           and json.load(open(report_path(out))) == {'old': True} and json.load(open(rejected_path(out))) == [{'new': 1}]
           and json.load(open(report_path(out, True)))['candidate_written'] is False, buf.getvalue())
        rc = commit('compose_x', out, [{'new': 2}], {'r': 2}, [], ['декор'])
        rep = json.load(open(report_path(out)))
        ok('годный: код 0, кандидат и отчёт подменены, предупреждения в отчёте',
           rc == 0 and json.load(open(out)) == [{'new': 2}] and rep['check'] == {'hard': [], 'warn': ['декор']}
           and rep['candidate_written'] is True, rep)

        class Boom:
            pass
        try:
            write_json(out, [Boom()])
        except TypeError:
            pass
        ok('сбой посреди записи: прежний файл цел, временных нет',
           json.load(open(out)) == [{'new': 2}] and not [f for f in os.listdir(td) if '.tmp-' in f], os.listdir(td))
    print(f'room_candidate selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
