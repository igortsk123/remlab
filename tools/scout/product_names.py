#!/usr/bin/env python3
"""ОДНО НАЗВАНИЕ У ТОВАРА ВЕЗДЕ (T-20261119-97, П1.92, план `product-names-01`): единственное правило «как зовут товар сейчас» — для сборки
`/demo` (`flat215_demo.main`) и для сборки/перевыпуска тура (`trial_bundle.catalog_goods`, `room_goods`). Раньше пути были разные: витрина брала
название из банка (`sets-bedroom.json` и др., обновляется только при обороте банка), тур — из живого `room_catalog`; магазин переименовал
«Далти» → «Далти-П», и в одной квартире у кровати было два имени (live 19.11: /demo «Далти 160», все туры «Далти-П 160»).

ПРАВИЛО (`Names.name`): название товара `sid` («mid_eid») = название в живом каталоге `products` (фид магазина; товар не снят и источник не в карантине —
как `catalog_media.sync_sets`); нет там — название строки `room_catalog` (товар комнатного каталога вне общего); нет нигде — None, и вызывающий оставляет
своё (нейтральное имя предмета без товара, старая сцена). Английское — не здесь: считается по русскому (`names_en`), поэтому у исправленной карточки
`name_en` снимается.

  unify(data)   — финальный проход по собранным данным: каждой карточке с `sid` — каталожное название (ничего не стирает, кроме `name_en` у исправленной);
  mismatches(data) — то же, без правки: счёт расхождений (сторож: сборка /demo и перевыпуск печатают число).
    ~/venvs/scout/bin/python tools/scout/product_names.py --selftest      ·      --cross <demo-data.json> <bundle.json>…   (сухая сверка: чтение)"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SID_RE = re.compile(r'\d+_[0-9A-Za-z]+')


def key(sid) -> str | None:
    """«mid_eid» из `sid` с «:» или «_»; не ключ товара — None."""
    if not isinstance(sid, str):
        return None
    s = sid.replace(':', '_', 1)
    return s if SID_RE.fullmatch(s) else None


def clean(name: str) -> str:
    """ПРОБЕЛЫ НАЗВАНИЯ — ОДНО ПРАВИЛО (T-20261119-97, T-20261119-105/1): любой пробельный символ (табуляция, неразрывный пробел NBSP, тонкие пробелы, перевод строки)
    и любая серия подряд — ОДИН обычный пробел, пробелы по краям — убрать: у «Лео Кровать 160*200<TAB>Вельвет» витрина и тур писали по-разному. Обычное имя не меняется.
    Зовётся и там, где каталожного названия нет (имя из банка/ленты — `clean_card`, `name_of(…, fallback)`): иначе грязное имя уезжало в данные как есть."""
    return ' '.join(str(name).split())


def clean_card(c: dict) -> bool:
    """Название карточки — по `clean` (на месте). True — поменяли; английское (`name_en`) тогда снимается: считается по русскому заново (`names_en.annotate` / `trial_demo._names_en`)."""
    n = c.get('name')
    if not isinstance(n, str) or clean(n) == n:
        return False
    c['name'] = clean(n)
    c.pop('name_en', None)
    return True


def pick_name(media: dict | None, room_name: str | None = None) -> str | None:
    """САМО ПРАВИЛО: строка `products` из `catalog_media` (товар в продаже — `state == 'available'`) → её название; иначе название строки `room_catalog`;
    иначе None (товар снят/источник в карантине и комнатной строки нет — как `catalog_media.sync_sets`, чужое имя не трогаем). Пробелы — `clean`."""
    if media and media.get('state') == 'available' and media.get('name'):
        return clean(media['name'])
    return clean(room_name) if room_name and clean(room_name) else None


class Names:
    """Живые названия: `products` (`{(mid, eid): {'name', 'state'}}` из `catalog_media`) и `room_catalog` (`{'mid_eid': name}`)."""

    def __init__(self, products: dict | None = None, room: dict | None = None):
        self._products, self._room = products, room

    def _load(self) -> None:
        if self._products is None:
            import catalog_media as CM
            self._products = CM._load()
        if self._room is None:
            self._room = _room_names()

    def name(self, sid) -> str | None:
        k = key(sid)
        if not k:
            return None
        self._load()
        mid, eid = k.split('_', 1)
        return pick_name(self._products.get((mid, eid)), self._room.get(k))


    def sid_index(self) -> dict:
        """{pid: sid} по всем товарам обоих каталогов (обратный ход для карточек тура, где виден только `pid`)."""
        from product_pid import pid_of
        self._load()
        keys = {f'{m}_{e}' for (m, e) in self._products} | set(self._room)
        return {pid_of(k): k for k in keys}


def _room_names() -> dict:
    import catalog_media as CM
    import subprocess
    r = subprocess.run(CM.PSQL + ["select shop_mid||'_'||external_id||E'\\x1f'||name from room_catalog where coalesce(name,'')<>''"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'product_names: psql rc={r.returncode}: {r.stderr.strip()[:200]}')
    out: dict = {}
    for line in r.stdout.splitlines():
        a, _, b = line.partition('\x1f')
        if a and b:
            out[a] = b
    return out


_DEFAULT: Names | None = None


def default() -> Names:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Names()
    return _DEFAULT


def name_of(sid, fallback: str | None = None, N: Names | None = None) -> str | None:
    """Название товара по единому правилу; нет в каталогах — `fallback` (свое имя вызывающего)."""
    return (N or default()).name(sid) or (clean(fallback) if isinstance(fallback, str) else fallback)


def cards(data):
    """Карточки товара в данных: словари, где есть и `sid` (ключ товара), и `name`."""
    if isinstance(data, dict):
        if isinstance(data.get('name'), str) and key(data.get('sid')):
            yield data
        for v in data.values():
            yield from cards(v)
    elif isinstance(data, list):
        for v in data:
            yield from cards(v)


def unify(data, N: Names | None = None) -> dict:
    """Каждой карточке с `sid` — каталожное название (правка на месте). → {cards, fixed, sids_fixed, unknown, ws}; `unknown` — карточки без названия в каталогах
    (им только `clean`: `ws` — у скольких поправлены пробелы)."""
    N = N or default()
    rep = {'cards': 0, 'fixed': 0, 'unknown': 0, 'ws': 0}
    fixed: set = set()
    for c in cards(data):
        rep['cards'] += 1
        cat = N.name(c['sid'])
        if not cat:
            rep['unknown'] += 1
            rep['ws'] += clean_card(c)      # каталожного названия нет — хотя бы пробелы по общему правилу (`clean`), а не «как в банке/ленте»
        elif c['name'] != cat:
            c['name'] = cat
            c.pop('name_en', None)          # английское — по русскому (`names_en.annotate` / `trial_demo._names_en`)
            rep['fixed'] += 1
            fixed.add(key(c['sid']))
    rep['sids_fixed'] = len(fixed)
    return rep


def mismatches(data, N: Names | None = None) -> dict:
    """{sid: {название в данных, …}} там, где оно не равно каталожному (без правки)."""
    N = N or default()
    out: dict = {}
    for c in cards(data):
        cat = N.name(c['sid'])
        if cat and c['name'] != cat:
            out.setdefault(key(c['sid']), set()).add(c['name'])
    return out


def report_line(rep: dict, where: str) -> str:
    """Строка в журнал ночи: число расхождений с каталогом (WARN, если нашлись и исправлены — банк/копия отстали от фида)."""
    base = f"названия {where}: карточек {rep['cards']}, по каталогу исправлено {rep['fixed']} (товаров {rep.get('sids_fixed', 0)}), без названия в каталоге {rep['unknown']}"
    return ('WARN:names_catalog: ' if rep['fixed'] else '') + base + (f", пробелов исправлено {rep['ws']}" if rep.get('ws') else '')


def names_by_sid(data) -> dict:
    """{sid: {название, …}} во всех карточках с `sid` (для сверки двух файлов)."""
    out: dict = {}
    for c in cards(data):
        out.setdefault(key(c['sid']), set()).add(c['name'])
    return out


def names_by_pid(data) -> dict:
    """{pid: {название, …}}: карточки тура (`pid` — хеш `sid`, `product_pid.pid_of`) и карточки витрины (`sid` → `pid`) — общий ключ для сверки витрины и туров."""
    from product_pid import pid_of
    out: dict = {}

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get('name'), str):
                p = o.get('pid') if isinstance(o.get('pid'), str) else (pid_of(key(o.get('sid'))) if key(o.get('sid')) else None)
                if p:
                    out.setdefault(p, set()).add(o['name'])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(data)
    return out


def between(demo: dict, tours: list) -> dict:
    """СТОРОЖ «ВИТРИНА = ТУРЫ» по названиям (T-20261119-97): у скольких товаров (общий ключ `pid`) название в данных `/demo` и в данных туров РАЗНОЕ (или разное внутри тура).
    → {pids: сколько товаров есть и там и там, diff: сколько разошлись, sample: до 5 примеров {pid: [названия]}}."""
    d = names_by_pid(demo)
    t: dict = {}
    for tour in tours:
        for p, ns in names_by_pid(tour).items():
            t.setdefault(p, set()).update(ns)
    both = set(d) & set(t)
    diff = {p: sorted(d[p] | t[p]) for p in both if len(d[p] | t[p]) > 1}
    return {'pids': len(both), 'diff': len(diff), 'sample': dict(list(diff.items())[:5])}


def cross(files: list, N: Names | None = None, apply: bool = False) -> dict:
    """Сухая сверка: сколько `sid` носят разные названия МЕЖДУ файлами (витрина и туры) и сколько расходятся с каталогом; apply=True — после `unify` (в памяти).
    → {sids, cross_diff, vs_catalog, sample}."""
    N = N or default()
    from product_pid import pid_of
    per: list = []
    for f in files:
        d = json.load(open(f, encoding='utf-8'))
        if apply:
            unify(d, N)
            unify_pid(d, N)
        per.append(names_by_pid(d))
    allpid = set().union(*[set(p) for p in per]) if per else set()
    diff = {}
    for s in allpid:
        ns = set().union(*[p.get(s, set()) for p in per])
        if len(ns) > 1:
            diff[s] = sorted(ns)
    sid_of = N.sid_index() if allpid else {}
    vs = {p for p in allpid if sid_of.get(p) and N.name(sid_of[p]) and any(n != N.name(sid_of[p]) for q in per for n in q.get(p, ()))}
    return {'товаров (pid)': len(allpid), 'разные названия МЕЖДУ файлами': len(diff), 'не равны каталогу': len(vs), 'пример': dict(list(diff.items())[:5])}


def unify_pid(data, N: Names | None = None) -> int:
    """Только для сухой сверки: карточкам тура (`pid`, без `sid`) — каталожное название через обратный ход `pid` → `sid` (боевой путь тура — `trial_bundle.unify_cards`)."""
    N = N or default()
    sid_of = N.sid_index()
    n = 0

    def walk(o):
        nonlocal n
        if isinstance(o, dict):
            if isinstance(o.get('name'), str) and isinstance(o.get('pid'), str) and not key(o.get('sid')) and o['pid'] in sid_of:
                cat = N.name(sid_of[o['pid']])
                if cat and o['name'] != cat:
                    o['name'] = cat
                    n += 1
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(data)
    return n


def _selftest() -> int:
    bad = 0

    def ok(n, c):
        nonlocal bad
        print(('ok   ' if c else 'FAIL ') + n)
        bad += 0 if c else 1
    N = Names({('1', '10'): {'name': 'Далти-П', 'state': 'available'}, ('1', '11'): {'name': 'Снят', 'state': 'gone'}, ('1', '12'): {'name': 'Карантин', 'state': 'unknown'}},
              {'1_10': 'Комнатное', '2_20': 'Только комнатный', '1_11': 'Комн-снят'})
    ok('ключ: «:» и «_», чужое — None', key('1:10') == '1_10' and key('1_10') == '1_10' and key('abc') is None and key(None) is None)
    ok('products главнее room_catalog', N.name('1_10') == 'Далти-П' and N.name('1:10') == 'Далти-П')
    ok('нет в products — строка room_catalog', N.name('2_20') == 'Только комнатный')
    ok('снят/карантин без строки комнатного каталога — None (имя не трогаем)', N.name('1_12') is None)
    ok('снят, но есть в комнатном каталоге — его название', N.name('1_11') == 'Комн-снят')
    ok('name_of: нет нигде — fallback', name_of('9_9', 'свое', N) == 'свое' and name_of('1_10', 'свое', N) == 'Далти-П')
    d = {'variants': [{'items': [{'role': 'кровать', 'sku': {'sid': '1_10', 'name': 'Далти', 'name_en': 'Dalti'}}]}],
         'feeds': {'bedroom:кровать': [{'sid': '1_10', 'name': 'Далти', 'name_en': 'Dalti'}, {'sid': '1:10', 'name': 'Далти-П'}, {'sid': '5_5', 'name': 'Нет в каталоге'},
                                       {'name': 'Без sid'}]},
         'sets': [{'roles': {'к': {'name': 'без sid'}}}]}
    mm = mismatches(d, N)
    ok('mismatches: расхождение найдено, без правки', list(mm) == ['1_10'] and mm['1_10'] == {'Далти'} and d['feeds']['bedroom:кровать'][0]['name'] == 'Далти')
    rep = unify(d, N)
    ok('unify: исправлены 2 карточки одного товара, неизвестная и без sid не тронуты',
       rep == {'cards': 4, 'fixed': 2, 'unknown': 1, 'ws': 0, 'sids_fixed': 1} and d['feeds']['bedroom:кровать'][2]['name'] == 'Нет в каталоге' and d['feeds']['bedroom:кровать'][3]['name'] == 'Без sid')
    ok('unify: у исправленной name_en снят, у верной остаётся', 'name_en' not in d['variants'][0]['items'][0]['sku'] and 'name_en' not in d['feeds']['bedroom:кровать'][0])
    ok('повтор — ничего не меняет (идемпотентность)', unify(d, N)['fixed'] == 0 and not mismatches(d, N))
    ok('строка журнала: WARN при исправлении, без — нет', report_line(rep, 'витрины').startswith('WARN:names_catalog: ') and not report_line({'cards': 1, 'fixed': 0, 'unknown': 0}, 'x').startswith('WARN'))
    a = {'f': [{'sid': '1_10', 'name': 'Далти'}]}
    from product_pid import pid_of
    b = {'g': [{'pid': pid_of('1_10'), 'name': 'Далти 2'}]}
    import tempfile
    sys.path.append(HERE)
    import remlab_tmp
    remlab_tmp.use('product_names_selftest')
    with tempfile.TemporaryDirectory() as td:
        pa, pb = os.path.join(td, 'a.json'), os.path.join(td, 'b.json')
        json.dump(a, open(pa, 'w')), json.dump(b, open(pb, 'w'))
        before, after = cross([pa, pb], N), cross([pa, pb], N, apply=True)
        ok('сверка двух файлов: было 1 расхождение между файлами и 1 с каталогом, стало 0 и 0',
           (before['разные названия МЕЖДУ файлами'], before['не равны каталогу'], after['разные названия МЕЖДУ файлами'], after['не равны каталогу']) == (1, 1, 0, 0))
    ok('пробелы названия: табуляция и двойной пробел — одним пробелом', clean('Лео 160*200\tВельвет  Корд') == 'Лео 160*200 Вельвет Корд')
    ok('пробелы: NBSP, пробелы по краям, перевод строки; обычное имя не меняется',
       clean('\u00a0Лео\u00a0Кровать\u00a0 160*200 \n') == 'Лео Кровать 160*200' and clean('Босс Лофт Кровать+ПМ 160*200 \tВелюр') == 'Босс Лофт Кровать+ПМ 160*200 Велюр'
       and clean('Обычное имя 160*200, Орех') == 'Обычное имя 160*200, Орех')
    dd = {'feeds': {'k': [{'sid': '5_5', 'name': 'Нет  в\tкаталоге\u00a0', 'name_en': 'x'}, {'sid': '5_6', 'name': 'Чистое имя', 'name_en': 'y'}]}}
    r2 = unify(dd, N)
    ok('unify: карточке без каталожного названия — пробелы по правилу (name_en снят), чистой — ничего',
       r2['ws'] == 1 and dd['feeds']['k'][0]['name'] == 'Нет в каталоге' and 'name_en' not in dd['feeds']['k'][0] and dd['feeds']['k'][1] == {'sid': '5_6', 'name': 'Чистое имя', 'name_en': 'y'})
    ok('name_of: fallback тоже чистится', name_of('9_9', ' Свое\tимя ', N) == 'Свое имя')
    print('итог: ' + ('OK' if not bad else f'FAIL ({bad})'))
    return 1 if bad else 0


def main(argv) -> int:
    if '--selftest' in argv:
        return _selftest()
    if '--cross' in argv:
        files = argv[argv.index('--cross') + 1:]
        print(json.dumps({'до': cross(files), 'после (unify в памяти)': cross(files, apply=True)}, ensure_ascii=False, indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
