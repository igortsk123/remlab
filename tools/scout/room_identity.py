#!/usr/bin/env python3
"""ИДЕНТИЧНОСТЬ БАНКА КОМНАТЫ (room-bank-01 этап В, T-20261106-70; разбор Codex `_intake/codex/room-bank-2026-11-06-answer.md`
§ 3 п.1–2 «идентичность и полнота», «аттестация профиля и сборщика»).

ЗАЧЕМ. У гостиной ячейка `(band, style, tier)` и id «по замыслу» (`set_identity`). У спальни id набора считался от состава
(SKU кровати, шкафа…) — замена одного предмета давала НОВЫЙ набор вместо нового поколения той же ячейки: писатель и откат
по ячейкам с таким id работать не могут. Здесь:
  • ячейка спальни `(room_id, purpose, band, style, tier)`; `set_id` — только от ячейки (`set_id_of`), состав на него не влияет;
  • ОЖИДАЕМАЯ МАТРИЦА — из профиля комнаты: какие ячейки обязан дать сборщик (`compose_bedroom.cells`: комнаты × непустые
    назначения × стили × тиры, полоса — площадь комнаты по геометрии). Число не зашито: сегодня профиль даёт 60;
  • ПРОИСХОЖДЕНИЕ записи (`provenance`): `room_type`, `profile_id`, `profile_version`, `content_sha` профиля, `composer_plugin`,
    `rules_sha` (дайджест разрешённых правил сборщика — их файл правится без новой версии профиля), `composer_sha` (код
    сборщика). Пишется в КАЖДУЮ запись: после подмены ячеек живой банк смешанный, у каждой ячейки — своё происхождение;
  • `check` — отказ кандидата: дубль ячейки, пропавшая, лишняя, id не от своей ячейки, повтор id, нет происхождения или оно
    не совпало с текущим профилем/правилами/сборщиком. Порядок записей — порядок матрицы (номер массива тоже идентичность).

  python3 room_identity.py --room bedroom matrix            # ожидаемая матрица (число и список)
  python3 room_identity.py --room bedroom check <банк.json>  # отказы кандидата; код 1 — есть
  python3 room_identity.py --room bedroom map <банк.json>    # переход старых set_id в новые (таблица)
  python3 room_identity.py --selftest
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)

import room_profile as RP  # noqa: E402

CELL = ('room_id', 'purpose', 'band', 'style', 'tier')
PREFIX = {'bedroom': 'bed'}          # префикс id набора по типу комнаты (как было у спальни)
PROV_KEYS = ('room_type', 'profile_id', 'profile_version', 'content_sha', 'composer_plugin', 'rules_sha', 'composer_sha')


def cell(s: dict) -> tuple:
    return tuple(s.get(f) for f in CELL)


def set_id_of(room_type: str, c: tuple) -> str:
    """Стабильный id набора — от ячейки, БЕЗ состава: замена предмета — то же set_id (новое поколение ячейки)."""
    return f"{PREFIX.get(room_type, room_type)}-" + hashlib.sha1('|'.join(map(str, c)).encode()).hexdigest()[:8]


def _sha(o) -> str:
    return hashlib.sha256(json.dumps(o, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()[:12]


def provenance(room_type: str, profile: dict | None = None) -> dict:
    """Происхождение кандидата по ТЕКУЩЕМУ профилю (файлы на диске)."""
    raw = RP.raw(room_type)
    p = profile if profile is not None else RP.resolve(raw)
    plugin = raw['composer']['plugin']
    code = os.path.join(ROOT, RP.COMPOSERS[plugin])
    return {'room_type': room_type, 'profile_id': raw['profile_id'], 'profile_version': raw['profile_version'],
            'content_sha': raw['content_sha'], 'composer_plugin': plugin, 'rules_sha': _sha(p['composer']['rules']),
            'composer_sha': hashlib.sha256(open(code, 'rb').read()).hexdigest()[:12]}


def expected(room_type: str, R: dict | None = None) -> list[tuple]:
    """Ожидаемая матрица ячеек из профиля — через сборщик комнаты (он один знает, как профиль разворачивается в ячейки)."""
    if room_type == 'hall':          # прихожая (T-20261106-89 шаг 2): стили × ступени на геометрии варианта из правил
        import compose_hall as CH
        return CH.cells(R if R is not None else CH.rules())
    if room_type != 'bedroom':
        raise ValueError(f'матрица ячеек для {room_type!r} не описана (есть: bedroom, hall)')
    import compose_bedroom as CB
    return CB.cells(R if R is not None else CB.rules())


def check(bank: list, want: list[tuple], prov: dict | None, room_type: str = 'bedroom') -> list[str]:
    """Отказы кандидата (пусто — годен): матрица, id, происхождение. prov=None — происхождение не сверять."""
    bad = []
    cs = [cell(s) for s in bank]
    seen: dict = {}
    for c in cs:
        seen[c] = seen.get(c, 0) + 1
    dup = [c for c, n in seen.items() if n > 1]
    if dup:
        bad.append(f'дубль ячейки: {len(dup)} {["|".join(map(str, c)) for c in dup[:3]]}')
    lost = [c for c in want if c not in seen]
    extra = [c for c in seen if c not in set(want)]
    if lost:
        bad.append(f'пропали ячейки: {len(lost)} из {len(want)} {["|".join(map(str, c)) for c in lost[:3]]}')
    if extra:
        bad.append(f'лишние ячейки: {len(extra)} {["|".join(map(str, c)) for c in extra[:3]]}')
    if not (dup or lost or extra) and cs != list(want):
        bad.append('порядок записей не порядок матрицы профиля')
    wrong = [s.get('set_id') for s in bank if s.get('set_id') != set_id_of(room_type, cell(s))]
    if wrong:
        bad.append(f'set_id не от своей ячейки: {len(wrong)} {wrong[:3]}')
    ids: dict = {}
    for s in bank:
        ids[s.get('set_id')] = ids.get(s.get('set_id'), 0) + 1
    if any(n > 1 for n in ids.values()):
        bad.append(f'повтор set_id: {[i for i, n in ids.items() if n > 1][:3]}')
    if prov is not None:
        nop = sum(1 for s in bank if not isinstance(s.get('provenance'), dict))
        if nop:
            bad.append(f'нет происхождения у {nop} записей')
        diff: dict = {}
        for s in bank:
            for k in PROV_KEYS:
                v = (s.get('provenance') or {}).get(k)
                if isinstance(s.get('provenance'), dict) and v != prov[k]:
                    diff.setdefault(k, set()).add(str(v))
        for k, vs in diff.items():
            bad.append(f'происхождение {k}: в кандидате {sorted(vs)[:3]}, сейчас {prov[k]}')
    return bad


def transition(bank: list, room_type: str = 'bedroom') -> list[dict]:
    """Переход старых id в новые: [{cell, old, new}] по записям банка (старый id — от состава)."""
    return [{'cell': '|'.join(map(str, cell(s))), 'old': s.get('set_id'), 'new': set_id_of(room_type, cell(s))} for s in bank]


# ---------------------------------------------------------------- селфтест
def _rec(c: tuple, room_type='bedroom', prov=None, items=None) -> dict:
    s = dict(zip(CELL, c), room_type=room_type, items=items or {'кровать': {'mid': 1, 'eid': 'a'}})
    s['set_id'] = set_id_of(room_type, c)
    if prov is not None:
        s['provenance'] = dict(prov)
    return s


def _selftest() -> int:
    bad = 0

    def ok(name, cond, extra=''):
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
        bad += 0 if cond else 1
    want = expected('bedroom')
    rooms = {c[0] for c in want}
    ok(f'матрица спальни из профиля: {len(want)} ячеек, без повторов, комнаты {sorted(rooms)}',
       len(want) == len(set(want)) and len(want) > 0)
    import compose_bedroom as CB
    R = CB.rules()
    n = sum(len(R['styles']) * len(R['tiers']) for r, rc in R['rooms'].items() for p in rc['purposes']
            if not R['purposes'][p].get('empty'))
    ok(f'число ячеек = комнаты × непустые назначения × стили × тиры профиля ({n})', len(want) == n)
    R2 = json.loads(json.dumps(R))
    R2['styles'] = R2['styles'][:2]
    ok('стилей в профиле меньше — матрица меньше (число выводится, не зашито)', len(expected('bedroom', R2)) == len(want) * 2 // 5)
    prov = provenance('bedroom')
    ok('происхождение: профиль, версия, content_sha, плагин bedroom, дайджест правил и кода',
       prov['profile_id'] == 'bedroom' and prov['composer_plugin'] == 'bedroom' and len(prov['rules_sha']) == 12
       and set(prov) == set(PROV_KEYS))
    good = [_rec(c, prov=prov) for c in want]
    ok('полный кандидат в порядке матрицы — отказов нет', check(good, want, prov) == [], check(good, want, prov))
    c0 = want[0]
    a = _rec(c0, items={'кровать': {'mid': 1, 'eid': 'a'}})
    b = _rec(c0, items={'кровать': {'mid': 2, 'eid': 'zz'}, 'шкаф': {'mid': 3, 'eid': 'w'}})
    ok('замена SKU — тот же set_id (новое поколение ячейки, не новый набор)', a['set_id'] == b['set_id'])
    ok('разные ячейки — разные set_id', len({set_id_of('bedroom', c) for c in want}) == len(want))
    cases = {
        'перестановка записей': (good[1:2] + good[:1] + good[2:], 'порядок записей'),
        'дубль ячейки': (good + [good[0]], 'дубль ячейки'),
        'пропала ячейка': (good[:-1], 'пропали ячейки: 1'),
        'лишняя ячейка': (good + [_rec(('bedroom-9', 'couple', '9', 'сканди', 'эконом'), prov=prov)], 'лишние ячейки: 1'),
        'id от состава (старый)': ([dict(good[0], set_id='bed-0badc0de')] + good[1:], 'set_id не от своей ячейки'),
        'нет происхождения': ([{k: v for k, v in good[0].items() if k != 'provenance'}] + good[1:], 'нет происхождения'),
        'профиль правлен (content_sha)': ([dict(good[0], provenance=dict(prov, content_sha='000000000000'))] + good[1:],
                                         'происхождение content_sha'),
        'правила сборщика другие (rules_sha)': ([dict(good[0], provenance=dict(prov, rules_sha='x'))] + good[1:],
                                               'происхождение rules_sha'),
        'сборщик другой (composer_sha)': ([dict(good[0], provenance=dict(prov, composer_sha='x'))] + good[1:],
                                         'происхождение composer_sha'),
        'плагин другой': ([dict(good[0], provenance=dict(prov, composer_plugin='living_legacy'))] + good[1:],
                          'происхождение composer_plugin'),
    }
    for name, (bank, want_txt) in cases.items():
        got = check(bank, want, prov)
        ok(f'{name} — отказ «{want_txt}»', any(want_txt in x for x in got), got)
    t = transition([dict(good[0], set_id='bed-old00001')])
    ok('таблица перехода: старый id → новый от ячейки', t[0]['old'] == 'bed-old00001' and t[0]['new'] == good[0]['set_id'])
    print(f'room_identity: ошибок {bad}')
    return bad


def main(argv: list) -> int:
    room = argv[argv.index('--room') + 1] if '--room' in argv else 'bedroom'
    rest = [a for i, a in enumerate(argv) if a != '--room' and (i == 0 or argv[i - 1] != '--room')]
    want = expected(room)
    if rest[:1] == ['matrix']:
        print(f'{room}: ячеек {len(want)}')
        for c in want:
            print('  ' + '|'.join(map(str, c)) + '  ' + set_id_of(room, c))
        return 0
    bank = json.load(open(rest[1], encoding='utf-8'))
    if rest[:1] == ['check']:
        got = check(bank, want, provenance(room), room)
        print(f'{rest[1]}: записей {len(bank)}, матрица {len(want)}, отказов {len(got)}' + ''.join(f'\n  ✗ {x}' for x in got))
        return 1 if got else 0
    if rest[:1] == ['map']:
        for r in transition(bank, room):
            print(f"{r['cell']}\t{r['old']}\t{r['new']}")
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(1 if _selftest() else 0)
    sys.exit(main(sys.argv[1:]))
