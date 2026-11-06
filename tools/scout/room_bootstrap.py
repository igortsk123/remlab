#!/usr/bin/env python3
"""BOOTSTRAP «ПОКОЛЕНИЕ 0» БАНКА КОМНАТЫ (room-bank-01 этап В, T-20261106-70; Codex § 5: «первый живой банк неоткуда продвигать:
нужен отдельный bootstrap-протокол — полностью проверенный кандидат, ручное разрешение, generation-0 и явная семантика rollback»).

ЗАЧЕМ. Ночной писатель (`bank_refresh`) и суд (`bank_promote`) работают от СУЩЕСТВУЮЩЕГО живого банка: подменяют готовые ячейки.
У спальни живого `sets-bedroom.json` нет — первый появляется только этой командой, из проверенного кандидата и по слову ведущего.

ПОРЯДОК `run` (всё нарушенное — отказ, живой не тронут):
  1. `--confirm-lead` (слово ведущего) — иначе код 2; флаг `rules/bank-candidate.json:rooms.<комната>.write_enabled` — иначе код 2;
  2. `exam.lock` — отказ; незавершённая запись комнаты (намерение) — сперва восстановление (`bank_refresh.recover`);
  3. живой банк уже есть — отказ (bootstrap только для первого; дальше — ночной писатель); после `rollback` — можно снова;
  4. проверка кандидата (`verdict`): полная матрица профиля и id от ячейки, происхождение = текущие профиль/правила/сборщик
     (`room_identity.check`), раскладка и состав без нарушений (`compose_bedroom.check_bank` с `spare='warn'`: у поколения 0 нехватка
     запаса замен — `~`, как у декора; набор полный, не хватает лишь замен — ведущий T-70/2; у ночной замены этапа Г правило
     жёсткое, `spare='hard'` по умолчанию); нехватка запаса у мебели — строками в журнал поколения (`warnings`: ячейка, роль, замен);
  5. снимок поколения 0 — САМ кандидат байт в байт (`bank-generations-<комната>/<префикс>-<поколение>.json.gz`; «до» нет), затем
     намерение (sha «до» = нет файла, sha «после»), затем атомарная запись живого (временный + fsync + rename), сверка sha, журнал
     (`kind: bootstrap`, `generation: 0`), намерение снимается последним.
`rollback --confirm-lead` — назад к «живого нет»: живой ПЕРЕИМЕНОВЫВАЕТСЯ в папку поколений (`…-unbootstrapped.json`, ничего не
удаляем), только если после bootstrap записей не было и файл тот же (sha). Демо без живого банка спальню не публикует — как до.
Восстановление (`recover`, его зовёт и `bank_refresh.recover` для этих видов): журнал уже есть — снять намерение; файл в состоянии
«до» — запись не случилась (abort); в «после» — довести журнал; иначе — отказ, разбор руками (`--abandon`).

  ~/venvs/scout/bin/python room_bootstrap.py --room bedroom check [--candidate ФАЙЛ]       # только проверка, ничего не пишет
  ~/venvs/scout/bin/python room_bootstrap.py --room bedroom run --confirm-lead [--candidate ФАЙЛ]
  ~/venvs/scout/bin/python room_bootstrap.py --room bedroom rollback --confirm-lead
  ~/venvs/scout/bin/python room_bootstrap.py --room bedroom recover [--abandon]
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import room_bank_spec as RBS  # noqa: E402

KINDS = ('bootstrap', 'unbootstrap')


def _RF():
    import bank_refresh as RF
    return RF


def _sha_file(path: str) -> str | None:
    try:
        return _RF().sha(open(path, 'rb').read())
    except FileNotFoundError:
        return None


SPARE = 'warn'      # суд поколения 0: нехватка запаса замен у мебели — предупреждение в журнал (ведущий T-70/2)


def verdict(room: str, cand: list, spare: str = SPARE) -> list[str]:
    """Отказы кандидата (пусто — годен к поколению 0): идентичность и происхождение, затем раскладка и состав
    (`compose_bedroom.check_bank(spare=…)`; '~' — предупреждения, не отказ)."""
    import room_identity as RI
    bad = RI.check(cand, RI.expected(room), RI.provenance(room), room)
    if bad:
        return bad
    if room == 'bedroom':
        import compose_bedroom as CB
        bad += [p for p in CB.check_bank(cand, CB.rules(), CB.tolerance(), spare=spare) if not p.startswith('~')]
    return bad


def spare_warnings(room: str, cand: list) -> list[dict]:
    """Нехватка запаса замен у мебели (`compose_bedroom.spare_short`) → строки журнала поколения: ячейка, роль, сколько замен."""
    if room != 'bedroom':
        return []
    import compose_bedroom as CB
    import room_identity as RI
    return [{'set_id': s.get('set_id'), 'cell': '|'.join(RI.cell(s)), 'role': r, 'alternates': n, 'min': CB.SPARE_MIN}
            for s in cand if s.get('items') for r, n, major in CB.spare_short(s) if major]


def _say(msg: str) -> None:
    print(msg, flush=True)


def run(P: dict, R: dict, room: str, cand_path: str, *, confirm: bool, verdict_fn=None) -> int:
    RF = _RF()
    if room == RBS.LIVING:
        _say('ERROR:room_bootstrap: у гостиной живой банк есть — bootstrap только для новой комнаты')
        return 2
    if not confirm:
        _say('ERROR:room_bootstrap: нужно слово ведущего — `--confirm-lead`; живой банк не тронут')
        return 2
    if not R.get('write_enabled'):
        _say(f'ERROR:room_bootstrap: выключено (rules/bank-candidate.json:rooms.{room}.write_enabled=false) — живой банк не тронут')
        return 2
    if os.path.exists(P['lock']):
        _say('ERROR:room_bootstrap: exam.lock — идёт экзамен; живой банк не тронут')
        return 1
    if recover(P):
        return 1
    if os.path.exists(P['live']):
        _say(f"ERROR:room_bootstrap: живой банк {P['live']} уже есть — bootstrap только для первого (дальше — ночной писатель); "
             'не тронут')
        return 1
    try:
        raw = open(cand_path, 'rb').read()
        cand = json.loads(raw)
    except (FileNotFoundError, ValueError) as e:
        _say(f'ERROR:room_bootstrap: кандидат {cand_path} не читается ({type(e).__name__}) — живой банк не создан')
        return 1
    bad = (verdict_fn or verdict)(room, cand)
    if bad:
        _say(f'ERROR:room_bootstrap: кандидат не прошёл проверку ({len(bad)}) — живой банк не создан'
             + ''.join(f'\n  ✗ {x}' for x in bad[:20]))
        return 1
    warns = spare_warnings(room, cand)
    after = RF.sha(raw)
    gen, spath = RF.snapshot(P, raw)
    rec = {'gen': gen, 'kind': 'bootstrap', 'generation': 0, 'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'snapshot': spath,
           'snapshot_is': 'после (поколение 0 — сам кандидат; «до» — живого не было)', 'room': room,
           'live_sha_before': None, 'live_sha_after': after, 'candidate': os.path.abspath(cand_path), 'cells': len(cand),
           'provenance': (cand[0].get('provenance') if cand else None), 'by': 'confirm-lead',
           'repeat': any(r.get('kind') == 'bootstrap' for r in RF.journal(P)), 'warnings': warns}
    RF._intent_save(P, {'gen': gen, 'snapshot': spath, 'live_sha_before': None, 'live_sha_after': after, 'hold': None,
                        'record': rec})
    try:
        RF._atomic(P['live'], raw)
    except Exception as e:  # noqa: BLE001 — сбой до rename: живого нет, как было
        RF._intent_clear(P)
        _say(f'ERROR:room_bootstrap: запись не удалась ({type(e).__name__}: {e}) — живого банка нет, как было')
        return 1
    if _sha_file(P['live']) != after:
        os.replace(P['live'], os.path.join(P['gen'], f"{P.get('snap', room)}-{gen}-bad.json"))
        RF._intent_clear(P)
        _say('ERROR:room_bootstrap: после записи sha не тот — файл убран в папку поколений, живого банка нет')
        return 1
    RF._journal_add(P, rec)
    RF._intent_clear(P)
    for w in warns:
        _say(f"WARN:room_bootstrap: {w['set_id']} {w['cell']} {w['role']} — замен {w['alternates']} < {w['min']} (в журнале поколения)")
    _say(f"room_bootstrap: {room} — живой банк создан, поколение 0 ({gen}), ячеек {len(cand)}; снимок {spath}"
         + (' (повторный — после отката)' if rec['repeat'] else '') + (f'; предупреждений {len(warns)}' if warns else ''))
    _say(f'DIGEST:банк {room}: создан из кандидата — поколение 0, ячеек {len(cand)} (слово ведущего)')
    return 0


def rollback(P: dict, room: str, *, confirm: bool) -> int:
    RF = _RF()
    if not confirm:
        _say('ERROR:room_bootstrap: откат поколения 0 — только словом ведущего (`--confirm-lead`)')
        return 2
    if os.path.exists(P['lock']):
        _say('ERROR:room_bootstrap: exam.lock — идёт экзамен; откат отложен')
        return 1
    if recover(P):
        return 1
    J = [r for r in RF.journal(P) if r.get('kind') != 'recover']
    if not J or J[-1].get('kind') != 'bootstrap':
        _say('ERROR:room_bootstrap: последнее в журнале — не bootstrap ' + (f"({J[-1].get('kind')} {J[-1].get('gen')})" if J else
             '(журнал пуст)') + ' — сперва `bank_refresh.py --room … rollback`, живой не тронут')
        return 1
    rec = J[-1]
    cur = _sha_file(P['live'])
    if cur != rec['live_sha_after']:
        _say(f"ERROR:room_bootstrap: живой банк {'отсутствует' if cur is None else 'менялся после bootstrap'} — не трогаю")
        return 1
    aside = os.path.join(P['gen'], f"{P.get('snap', room)}-{rec['gen']}-unbootstrapped.json")
    gen = f"{rec['gen']}-unboot-{time.strftime('%Y%m%d-%H%M%S')}"
    jrec = {'gen': gen, 'kind': 'unbootstrap', 'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'to': 'нет живого (до bootstrap)',
            'undone': [rec['gen']], 'snapshot': aside, 'live_sha_before': cur, 'live_sha_after': None}
    RF._intent_save(P, {'gen': gen, 'snapshot': aside, 'live_sha_before': cur, 'live_sha_after': None, 'hold': None,
                        'record': jrec})
    os.replace(P['live'], aside)
    RF._journal_add(P, jrec)
    RF._intent_clear(P)
    _say(f"room_bootstrap: {room} — поколение 0 ({rec['gen']}) снято: живого банка нет, файл — {aside}")
    _say(f'DIGEST:банк {room}: откат поколения 0 — живого банка нет (как до bootstrap)')
    return 0


def recover(P: dict, abandon: bool = False) -> int:
    """Незавершённый bootstrap/откат поколения 0 → снять, довести или отказ. Чужое намерение (запись/откат писателя) — к
    `bank_refresh.recover`. 0 — можно работать дальше."""
    RF = _RF()
    it = RF._intent_load(P)
    if not it:
        return 0
    rec = it['record']
    if rec['kind'] not in KINDS:
        return RF.recover(P, abandon)
    return recover_intent(P, it, abandon)


def recover_intent(P: dict, it: dict, abandon: bool = False) -> int:
    RF = _RF()
    gen, rec, now = it['gen'], it['record'], time.strftime('%Y-%m-%dT%H:%M:%S')
    if any(r.get('gen') == gen and r.get('kind') == rec['kind'] for r in RF.journal(P)):
        RF._intent_clear(P)
        _say(f'room_bootstrap: намерение {gen} уже в журнале — снято')
        return 0
    cur = _sha_file(P['live'])
    base = {'gen': f'{gen}-recover', 'kind': 'recover', 'at': now, 'of': gen, 'of_kind': rec['kind'], 'live_sha': cur}
    if cur == it['live_sha_before']:
        RF._journal_add(P, {**base, 'action': 'abort'})
        RF._intent_clear(P)
        _say(f"room_bootstrap: прерванный {rec['kind']} {gen} не дошёл до замены — состояние прежнее, намерение снято")
        return 0
    if cur == it['live_sha_after']:
        RF._journal_add(P, {**rec, 'recovered': now})
        RF._intent_clear(P)
        _say(f"room_bootstrap: прерванный {rec['kind']} {gen} доведён — журнал дописан")
        return 0
    if abandon:
        RF._journal_add(P, {**base, 'action': 'abandon'})
        RF._intent_clear(P, os.path.join(P['gen'], f'intent-{gen}-abandoned.json'))
        _say(f'room_bootstrap: намерение {gen} снято вручную (живой оставлен как есть)')
        return 0
    _say(f"ERROR:room_bootstrap: незавершённый {rec['kind']} {gen}: живой банк ни «до», ни «после» — не трогаю; разбор руками, "
         f"затем `room_bootstrap.py --room … recover --abandon` ({P['intent']})")
    return 1


def main(argv: list) -> int:
    room, argv = RBS.room_arg(argv)
    room = room or RBS.LIVING
    spec = RBS.for_room(room)
    P = spec.refresh_paths()
    cand = argv[argv.index('--candidate') + 1] if '--candidate' in argv else spec.candidate
    if room == RBS.LIVING:
        _say('ERROR:room_bootstrap: у гостиной живой банк есть — bootstrap только для новой комнаты (нужен --room)')
        return 2
    if argv[:1] == ['check']:
        try:
            c = json.load(open(cand, encoding='utf-8'))
        except (FileNotFoundError, ValueError) as e:
            _say(f'ERROR:room_bootstrap: кандидат {cand} не читается ({type(e).__name__})')
            return 1
        bad = verdict(room, c)
        warns = [] if bad else spare_warnings(room, c)
        _say(f'room_bootstrap check {room}: кандидат {cand}, записей {len(c)}, отказов {len(bad)}, предупреждений {len(warns)}'
             + ''.join(f"\n  ~ {w['set_id']} {w['role']} — замен {w['alternates']} < {w['min']}" for w in warns[:30])
             + ''.join(f'\n  ✗ {x}' for x in bad[:30]) + ('' if bad else ' — годен к поколению 0 (запись — `run --confirm-lead`)'))
        return 1 if bad else 0
    if argv[:1] == ['run']:
        return run(P, spec.rules(), room, cand, confirm='--confirm-lead' in argv)
    if argv[:1] == ['rollback']:
        return rollback(P, room, confirm='--confirm-lead' in argv)
    if argv[:1] == ['recover']:
        return recover(P, '--abandon' in argv)
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
