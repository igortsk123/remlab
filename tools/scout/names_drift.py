#!/usr/bin/env python3
"""СТОРОЖ НАЗВАНИЙ ТОВАРОВ (T-20261119-07/5 п.5, план `product-names-01`): у одного товара (`sid` = «mid_eid») — одно название во всех копиях.
Ничего не чинит и не пишет в банки — только отчёт: какие `sid` носят разные названия в банках (`sets3`, спальня, прихожая, их кандидаты, `demo-sets`),
в живом каталоге (`products`) и в `room_catalog`; для каждого — габариты, цена и слаг ссылки магазина у каждого названия и вывод:
  rename   — габариты и слаг ссылки совпали: магазин переименовал тот же товар (банк догонит ночной `bank_media`);
  unverified — названия разные, а сравнить нечем (в одной из копий нет ни габаритов, ни ссылки): вывод «не проверить»;
  suspect  — габариты или слаг разошлись: под тем же номером мог оказаться другой товар (сборка тура уберёт его из лент, `trial_bundle.unify_cards`).
Первая строка `WARN:` — для ночной сводки (`refresh_daily.sh`, шаг `names_drift`); подробности — JSON `--out` (по умолчанию ~/scout-scenes/names-drift.json).
    ~/venvs/scout/bin/python tools/scout/names_drift.py [--out FILE] [--banks ПАПКА] [--print]      · самопроверка: --selftest (без базы)"""
import json
import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
BANKS = ('sets3.json', 'sets-bedroom.json', 'sets-bedroom.next.json', 'sets-hall.next.json', 'demo-sets.json')
DIM_TOL_CM = 1.0
OUT_DEFAULT = os.path.expanduser('~/scout-scenes/names-drift.json')


def slug_of(url) -> str:
    """Слаг карточки в магазине из партнёрской или прямой ссылки (`…goto=https://…/product/<слаг>`): у переименованного товара он прежний."""
    if not isinstance(url, str) or not url:
        return ''
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    target = (q.get('goto') or [url])[0]
    return urllib.parse.urlsplit(urllib.parse.unquote(target)).path.rstrip('/').rsplit('/', 1)[-1]


def bank_cards(data) -> dict:
    """{sid: [карточка]} — все товары банка (наборы, `alternates`): словарь с названием и ключом поставщика."""
    out: dict = {}

    def walk(o):
        if isinstance(o, dict):
            s = o.get('sid') if isinstance(o.get('sid'), str) and o.get('sid') else (f"{o['mid']}_{o['eid']}" if o.get('mid') and o.get('eid') else None)
            if s and isinstance(o.get('name'), str):
                out.setdefault(s.replace(':', '_', 1), []).append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(data)
    return out


def dims_of(c: dict) -> tuple:
    return tuple(c.get(k) for k in ('w', 'd', 'h'))


def same_dims(a: tuple, b: tuple) -> bool:
    return all(not (isinstance(x, (int, float)) and isinstance(y, (int, float)) and abs(x - y) > DIM_TOL_CM) for x, y in zip(a, b))


def drift(sources: dict) -> list:
    """sources: {имя источника: {sid: {'name', 'w', 'd', 'h', 'price', 'url'}}} → [{sid, verdict, names: {название: [источники]}, evidence}] по sid с 2+ названиями."""
    names: dict = {}
    for src, cards in sources.items():
        for sid, c in cards.items():
            if c.get('name'):
                names.setdefault(sid, {}).setdefault(c['name'], []).append(src)
    out = []
    for sid, by_name in sorted(names.items()):
        if len(by_name) < 2:
            continue
        ev = {}
        for nm, srcs in by_name.items():
            c = sources[srcs[0]][sid]
            ev[nm] = {'sources': srcs, 'dims': dims_of(c), 'price': c.get('price'), 'slug': slug_of(c.get('url'))}
        first = next(iter(ev.values()))
        rest = list(ev.values())[1:]
        rename = all(same_dims(first['dims'], e['dims']) and (not first['slug'] or not e['slug'] or first['slug'] == e['slug']) for e in rest)
        # «переименование» — только если было что сравнить: две известные оси габаритов или два слага; иначе вывод «не проверить» (в банке габаритов/ссылки нет)
        known = any(sum(1 for x, y in zip(first['dims'], e['dims']) if isinstance(x, (int, float)) and isinstance(y, (int, float))) >= 2
                    or (first['slug'] and e['slug']) for e in rest)
        out.append({'sid': sid, 'verdict': ('rename' if known else 'unverified') if rename else 'suspect', 'names': ev})
    return out


def load_sources(banks: str = HERE) -> dict:
    """Банки (файлы рядом), `products` и `room_catalog` (DEV-база). Нет файла — пропуск; база недоступна — исключение (сторож не молчит)."""
    import catalog_media as CM
    src: dict = {}
    for f in BANKS:
        p = os.path.join(banks, f)
        if os.path.isfile(p):
            src[f] = {s: cs[0] for s, cs in bank_cards(json.load(open(p, encoding='utf-8'))).items()}
    src['products'] = {f'{m}_{e}': v for (m, e), v in CM._load().items()}
    import subprocess
    q = ("select shop_mid||'_'||external_id||'\x1f'||name||'\x1f'||coalesce(price_rub,0)||'\x1f'||coalesce(url,'') from room_catalog")
    r = subprocess.run(CM.PSQL + [q], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'names_drift: psql rc={r.returncode}: {r.stderr.strip()[:200]}')
    rc: dict = {}
    for line in r.stdout.splitlines():
        p = line.split('\x1f')
        if len(p) >= 4 and p[1]:
            rc[p[0]] = {'name': p[1], 'price': p[2], 'url': p[3]}
    src['room_catalog'] = rc
    return src


def _selftest() -> int:
    bad = 0

    def ok(n, c):
        nonlocal bad
        print(('ok   ' if c else 'FAIL ') + n)
        bad += 0 if c else 1
    u = 'https://xf.gdeslon.ru/cm/a/?mid=1&goto=https%3A%2F%2Fwww.divan.ru%2Fproduct%2Fkreslo-olen-mini&erid=Z'
    ok('слаг из партнёрской ссылки', slug_of(u) == 'kreslo-olen-mini' and slug_of('https://s/p/abc/') == 'abc' and slug_of(None) == '')
    src = {'bank': {'1_1': {'name': 'Далти 160', 'w': 176, 'd': 224, 'h': 127, 'url': u}, '2_2': {'name': 'Один', 'w': 1}, '3_3': {'name': 'Кресло Ольен', 'w': 80, 'd': 90, 'h': 80, 'url': u}},
           'products': {'1_1': {'name': 'Далти-П 160', 'w': 176.4, 'd': 224, 'h': 127, 'url': u}, '2_2': {'name': 'Один', 'w': 1}, '3_3': {'name': 'Кресло Этен-2', 'w': 88, 'd': 108, 'h': 87, 'url': u}},
           'room_catalog': {'1_1': {'name': 'Далти-П 160', 'price': '5', 'url': u}}}
    rep = drift(src)
    ok('два названия одного sid найдены, одинаковые и одиночные — нет', [r['sid'] for r in rep] == ['1_1', '3_3'])
    ok('габариты и слаг те же — переименование', rep[0]['verdict'] == 'rename' and set(rep[0]['names']) == {'Далти 160', 'Далти-П 160'})
    ok('габариты разошлись — подозрение на подмену', rep[1]['verdict'] == 'suspect')
    ok('источники у названия перечислены', rep[0]['names']['Далти-П 160']['sources'] == ['products', 'room_catalog'])
    ok('сравнить нечем (в банке нет ни габаритов, ни ссылки) — «не проверить», а не «переименование»',
       drift({'a': {'1_1': {'name': 'X'}}, 'b': {'1_1': {'name': 'Y', 'w': 1, 'd': 2, 'h': 3, 'url': u}}})[0]['verdict'] == 'unverified')
    ok('нет расхождений — пусто', drift({'a': {'1_1': {'name': 'X'}}, 'b': {'1_1': {'name': 'X'}}}) == [])
    d = bank_cards({'sets': [{'items': {'к': {'mid': 5, 'eid': '9', 'name': 'Н'}}, 'alternates': {'к': [{'sid': '5:10', 'name': 'М'}]}}]})
    ok('банк: товары наборов и alternates, sid с «:» нормализован', set(d) == {'5_9', '5_10'})
    print('итог: ' + ('чисто' if not bad else f'FAIL ({bad})'))
    return 1 if bad else 0


def main(argv) -> int:
    if '--selftest' in argv:
        return _selftest()
    out = argv[argv.index('--out') + 1] if '--out' in argv else OUT_DEFAULT
    rep = drift(load_sources(argv[argv.index('--banks') + 1] if '--banks' in argv else HERE))
    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    tmp = out + '.tmp'
    json.dump({'v': 1, 'items': rep}, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.replace(tmp, out)
    n_s = sum(1 for r in rep if r['verdict'] == 'suspect')
    n_u = sum(1 for r in rep if r['verdict'] == 'unverified')
    if rep:
        print(f"WARN:names_drift: {len(rep)} товаров с разными названиями в банках и каталоге (переименований {len(rep) - n_s - n_u}, "
              f"не проверить {n_u}, подозрений на подмену {n_s}); отчёт {out}")
    else:
        print('названия товаров во всех копиях совпадают')
    if '--print' in argv:
        for r in rep:
            print(r['sid'], r['verdict'], json.dumps(r['names'], ensure_ascii=False)[:300])
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
