#!/usr/bin/env python3
"""Стабильный идентификатор комплекта.

ЗАЧЕМ. Сегодня сет опознаётся НОМЕРОМ в массиве `sets3.json`: сцены приёмки называются
`set72-base`, отчёты хранят `"set": 72`. Пока порядок массива не меняется, это работает; стоит
вставить, удалить или переупорядочить комплект — и все ссылки молча уезжают на соседние сеты.
Для журнала замен и для точечной пересборки («какие сцены пересчитать после подмены товара»)
такая идентичность не годится: мы будем пересчитывать не то, что поменялось.

ЧТО ИМЕННО ОПОЗНАЁМ. Идентичность комплекта — это его ЗАМЫСЕЛ (площадь, ярус, стиль, капсула),
а не текущий состав: при замене товара сет остаётся тем же самым сетом. Поэтому id считается по
неизменным при подборе полям и присваивается ОДИН РАЗ; дальше он только переносится.

Идентификатор детерминирован (одна и та же выборка даёт те же id при пересборке с нуля), но
однажды записанный НЕ пересчитывается — даже если поля замысла кто-то поправит.

ЯЧЕЙКА И ФАТАЛЬНОСТЬ (conv-14 шаг 1). При пересборке id и номер массива переносятся по постоянной ячейке
`(band, style, tier)` (`assign_ids`); потеря, дубль или дрейф id — `IdentityError`, и `write_bank` банк не пишет:
раньше сборщик ловил ошибку идентичности и писал банк всё равно.
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SETS = os.path.join(HERE, 'sets3.json')

# Поля замысла: они задают, ЧТО это за комплект, и не меняются при подмене товара в слоте.
IDENTITY_FIELDS = ('band', 'm2', 'tier', 'style', 'capsule', 'group')
# ЯЧЕЙКА БАНКА (conv-14 шаг 1, разбор Codex 22.10): постоянная идентичность комплекта — `(band, style, tier)`. В банке
# 7 полос × 6 стилей × 3 яруса = 126 ячеек, каждая ровно одна. Прежний ключ переноса (band, m2, tier, style, group)
# с порядковым номером зависел от `group`, а группу сборка ротирует — id мог уехать на соседний сет молча.
CELL_FIELDS = ('band', 'style', 'tier')


class IdentityError(Exception):
    """Потеря, дубль или дрейф set_id / ячейки: банк с такой ошибкой не пишется (сцены, отчёты и демо живут на номерах)."""


def cell(s: dict) -> tuple:
    return tuple(s.get(f) for f in CELL_FIELDS)


def _fingerprint(s: dict) -> str:
    payload = json.dumps({f: s.get(f) for f in IDENTITY_FIELDS},
                         ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:8]


def ensure_ids(sets: list[dict]) -> int:
    """Проставить `set_id` там, где его нет. Идемпотентно; возвращает число новых.

    Коллизии замысла (два комплекта с одинаковыми площадью/ярусом/стилем) реальны и законны —
    развязываем порядковым суффиксом в порядке первой встречи, чтобы id остались различимыми.
    """
    seen: dict[str, int] = {}
    taken = {s['set_id'] for s in sets if s.get('set_id')}
    added = 0
    for s in sets:
        if s.get('set_id'):
            continue
        fp = _fingerprint(s)
        n = seen.get(fp, 0)
        seen[fp] = n + 1
        sid = f'set-{fp}' if n == 0 else f'set-{fp}-{n}'
        while sid in taken:                      # столкнулись с уже занятым — сдвигаем суффикс
            n += 1
            seen[fp] = n + 1
            sid = f'set-{fp}-{n}'
        s['set_id'] = sid
        taken.add(sid)
        added += 1
    return added


def assign_ids(sets: list[dict], prev: list[dict] | None) -> list[dict]:
    """Идентичность пересобранного банка относительно прежнего: id и ПОРЯДОК — по ячейке `(band, style, tier)`.

    Возвращает новый список: сеты в порядке прежнего банка, у каждого id его ячейки. Без прежнего (первая сборка) —
    отпечаток `ensure_ids`. Любое нарушение — `IdentityError`, ничего не возвращаем: дубль ячейки, пропавшая или лишняя
    ячейка, у сета уже записан ДРУГОЙ id, в прежнем банке нет id или он повторяется. Номер массива — тоже идентичность
    (сцены `setN-*`, демо публикует `setN`): поэтому порядок задаёт прежний банк, а не порядок сборки."""
    dup = [c for c, n in _count(cell(s) for s in sets).items() if n > 1]
    if dup:
        raise IdentityError(f'дубль ячейки в новом банке: {dup[:3]}')
    if prev is None:
        ensure_ids(sets)
        return list(sets)
    pdup = [c for c, n in _count(cell(s) for s in prev).items() if n > 1]
    if pdup:
        raise IdentityError(f'дубль ячейки в прежнем банке: {pdup[:3]}')
    noid = [n for n, s in enumerate(prev, 1) if not s.get('set_id')]
    if noid:
        raise IdentityError(f'в прежнем банке сеты без set_id: номера {noid[:5]}')
    piddup = [i for i, n in _count(s['set_id'] for s in prev).items() if n > 1]
    if piddup:
        raise IdentityError(f'в прежнем банке повторяется set_id: {piddup[:3]}')
    by_cell = {cell(s): s for s in sets}
    lost = [cell(p) for p in prev if cell(p) not in by_cell]
    extra = [c for c in by_cell if c not in {cell(p) for p in prev}]
    if lost or extra:
        raise IdentityError(f'ячейки не совпали с прежним банком: пропали {len(lost)} {lost[:3]}, лишние {len(extra)} {extra[:3]}')
    out = []
    for p in prev:
        s = by_cell[cell(p)]
        if s.get('set_id') and s['set_id'] != p['set_id']:
            raise IdentityError(f'дрейф set_id ячейки {cell(p)}: записан {s["set_id"]}, в прежнем банке {p["set_id"]}')
        s['set_id'] = p['set_id']
        out.append(s)
    problems = verify(out, prev, cells=None)     # число ячеек задаёт прежний банк (живой — 126)
    if problems:
        raise IdentityError('; '.join(problems))
    return out


def verify(sets: list[dict], prev: list[dict] | None = None, cells: int | None = 126) -> list[str]:
    """Структура банка: `cells` уникальных ячеек (None — не проверять число), у каждого сета set_id, id не повторяются;
    с `prev` — карта «номер массива → (ячейка, set_id)» та же. Пусто — всё цело."""
    out = []
    cs = [cell(s) for s in sets]
    if cells is not None and len(sets) != cells:
        out.append(f'сетов {len(sets)}, ждали {cells}')
    if len(set(cs)) != len(cs):
        out.append(f'ячейки повторяются: {[c for c, n in _count(cs).items() if n > 1][:3]}')
    noid = [n for n, s in enumerate(sets, 1) if not s.get('set_id')]
    if noid:
        out.append(f'без set_id: номера {noid[:5]}')
    iddup = [i for i, n in _count(s.get('set_id') for s in sets if s.get('set_id')).items() if n > 1]
    if iddup:
        out.append(f'повторяется set_id: {iddup[:3]}')
    if prev is not None:
        moved = [n for n, (a, b) in enumerate(zip(prev, sets), 1)
                 if (cell(a), a.get('set_id')) != (cell(b), b.get('set_id'))]
        if moved or len(prev) != len(sets):
            out.append(f'карта «номер → set_id» не та: сдвинуты номера {moved[:5]}' + ('…' if len(moved) > 5 else '')
                       + (f', сетов {len(sets)} против {len(prev)}' if len(prev) != len(sets) else ''))
    return out


def _count(xs) -> dict:
    out: dict = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return out


def write_bank(sets: list[dict], out_path: str, prev_path: str | None) -> list[dict]:
    """Записать собранный банк: идентичность по прежнему (`assign_ids`), затем АТОМАРНО (временный файл + rename; инцидент
    08.08 — падение посреди json.dump оставило 18/126). Нарушение идентичности — `IdentityError` ДО записи: файл не тронут.
    Возвращает сеты в записанном порядке."""
    prev = json.load(open(prev_path, encoding='utf-8')) if prev_path and os.path.exists(prev_path) else None
    out = assign_ids(sets, prev)
    tmp = out_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out_path)
    return out


def index_map(sets: list[dict]) -> dict[int, str]:
    """Номер сета (1-based, как в именах сцен `setN-*`) → стабильный id."""
    return {n: s.get('set_id') for n, s in enumerate(sets, 1) if s.get('set_id')}


def check(sets: list[dict], snapshot_path: str | None = None) -> list[str]:
    """Проверка целостности: не уехали ли номера относительно прошлого снимка.

    Пока сцены и отчёты живут на номерах, единственная защита — заметить сдвиг и сказать вслух.
    """
    problems = []
    missing = [n for n, s in enumerate(sets, 1) if not s.get('set_id')]
    if missing:
        problems.append(f'без set_id: {len(missing)} комплектов (номера {missing[:5]}…)')
    ids = [s.get('set_id') for s in sets if s.get('set_id')]
    if len(ids) != len(set(ids)):
        problems.append('есть повторяющиеся set_id — идентичность нарушена')
    snapshot_path = snapshot_path or os.path.join(HERE, 'sets-id-map.json')
    now = index_map(sets)
    if os.path.exists(snapshot_path):
        was = {int(k): v for k, v in json.load(open(snapshot_path)).items()}
        moved = [n for n, sid in was.items() if n in now and now[n] != sid]
        if moved:
            problems.append(
                f'номера сдвинулись у {len(moved)} комплектов (например {moved[:5]}) — '
                f'сцены и отчёты с именами setN-* теперь указывают не на те сеты')
    return problems


def save_map(sets: list[dict], snapshot_path: str | None = None) -> None:
    snapshot_path = snapshot_path or os.path.join(HERE, 'sets-id-map.json')
    json.dump({str(k): v for k, v in index_map(sets).items()},
              open(snapshot_path, 'w'), ensure_ascii=False, indent=1)


def main() -> int:
    sets = json.load(open(SETS))
    added = ensure_ids(sets)
    problems = check(sets)
    if '--apply' in sys.argv:
        if added:
            json.dump(sets, open(SETS, 'w'), ensure_ascii=False)
        save_map(sets)
        print(f'set_id проставлен новым: {added}; карта номеров сохранена')
    else:
        print(f'без --apply: новых set_id было бы {added}')
    for p in problems:
        print('  ⚠', p)
    return 1 if problems else 0


def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name)
        bad += 0 if cond else 1

    def mk(band, style, tier, sid=None, group='g'):
        return {'band': band, 'm2': 15, 'tier': tier, 'style': style, 'group': group, 'capsule': 'c',
                **({'set_id': sid} if sid else {})}
    prev = [mk('14-16', 'сканди', 'эконом', 'set-1'), mk('14-16', 'лофт', 'эконом', 'set-2'),
            mk('17-20', 'сканди', 'премиум', 'set-3')]
    # пересборка в другом порядке, с другой группой и капсулой — id и номер по ячейке
    new = [mk('17-20', 'сканди', 'премиум', group='x'), mk('14-16', 'сканди', 'эконом'), mk('14-16', 'лофт', 'эконом')]
    out = assign_ids(new, prev)
    ok('id и порядок — по ячейке (band, style, tier), не по порядку сборки и не по группе',
       [s['set_id'] for s in out] == ['set-1', 'set-2', 'set-3'] and out[2]['group'] == 'x')
    ok('карта номеров та же — verify пуст', verify(out, prev, cells=3) == [])

    def fails(xs, why):
        try:
            assign_ids(xs, prev)
        except IdentityError as e:
            return why in str(e)
        return False
    ok('дубль ячейки — ошибка', fails([mk('14-16', 'сканди', 'эконом'), mk('14-16', 'сканди', 'эконом'),
                                       mk('17-20', 'сканди', 'премиум')], 'дубль ячейки'))
    ok('пропавшая ячейка — ошибка', fails([mk('14-16', 'сканди', 'эконом'), mk('14-16', 'лофт', 'эконом')], 'пропали 1'))
    ok('лишняя ячейка — ошибка', fails([mk('14-16', 'сканди', 'эконом'), mk('14-16', 'лофт', 'эконом'),
                                        mk('17-20', 'сканди', 'премиум'), mk('50+', 'лофт', 'эконом')], 'лишние 1'))
    ok('у сета записан другой id — дрейф, ошибка', fails([mk('14-16', 'сканди', 'эконом', 'set-9'), mk('14-16', 'лофт', 'эконом'),
                                                       mk('17-20', 'сканди', 'премиум')], 'дрейф'))
    bad_prev = [dict(p, set_id='set-1') for p in prev]
    try:
        assign_ids([mk('14-16', 'сканди', 'эконом'), mk('14-16', 'лофт', 'эконом'), mk('17-20', 'сканди', 'премиум')], bad_prev)
        ok('повтор id в прежнем банке — ошибка', False)
    except IdentityError as e:
        ok('повтор id в прежнем банке — ошибка', 'повторяется' in str(e))
    swapped = [out[1], out[0], out[2]]
    ok('сдвиг порядка — verify ловит', any('карта' in p for p in verify(swapped, prev, cells=3)))
    ok('verify: число ячеек и повтор id', len(verify([dict(out[0]), dict(out[0])], None, cells=3)) == 3)
    first = [mk('14-16', 'сканди', 'эконом'), mk('14-16', 'лофт', 'эконом')]
    ok('первая сборка без прежнего — отпечаток всем', all(s.get('set_id') for s in assign_ids(first, None)))
    # ЗАПИСЬ: нарушение идентичности — банк не записан, файл как был; порядок сборки — не порядок файла
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        live, out_p = os.path.join(tmp, 'sets3.json'), os.path.join(tmp, 'sets3.next.json')
        json.dump(prev, open(live, 'w', encoding='utf-8'), ensure_ascii=False)
        open(out_p, 'w').write('ПРЕЖНИЙ')

        def kept(xs):
            try:
                write_bank(xs, out_p, live)
            except IdentityError:
                return open(out_p).read() == 'ПРЕЖНИЙ' and not os.path.exists(out_p + '.tmp')
            return False
        ok('дубль ячейки — банк не записан', kept([mk('14-16', 'сканди', 'эконом'), mk('14-16', 'сканди', 'эконом'),
                                                    mk('17-20', 'сканди', 'премиум')]))
        ok('пропажа ячейки — банк не записан', kept([mk('14-16', 'сканди', 'эконом'), mk('14-16', 'лофт', 'эконом')]))
        ok('id сдвинуты на соседние ячейки — банк не записан',
           kept([mk('14-16', 'сканди', 'эконом', 'set-2'), mk('14-16', 'лофт', 'эконом', 'set-1'), mk('17-20', 'сканди', 'премиум', 'set-3')]))
        got = write_bank([mk('17-20', 'сканди', 'премиум'), mk('14-16', 'лофт', 'эконом'), mk('14-16', 'сканди', 'эконом')], out_p, live)
        disk = json.load(open(out_p, encoding='utf-8'))
        ok('порядок сборки другой — записан в порядке живого, карта номеров та же',
           [x['set_id'] for x in disk] == ['set-1', 'set-2', 'set-3'] == [x['set_id'] for x in got] and verify(disk, prev, cells=3) == [])
    print(f'set_identity selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(_selftest() if '--selftest' in sys.argv else main())
