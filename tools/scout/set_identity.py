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
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SETS = os.path.join(HERE, 'sets3.json')

# Поля замысла: они задают, ЧТО это за комплект, и не меняются при подмене товара в слоте.
IDENTITY_FIELDS = ('band', 'm2', 'tier', 'style', 'capsule', 'group')


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


if __name__ == '__main__':
    raise SystemExit(main())
