#!/usr/bin/env python3
"""Каталог ПРИХОЖЕЙ из фидов Гдеслона → таблица `room_catalog`, room='hall' (план onb-13-bath-hall Т3, T-20261105-34).

ЗАЧЕМ ОТДЕЛЬНО. `room_catalog.py` — загрузчик спальни; в эту волну его не делаем общим (разбор Codex 05.11,
`_intake/codex/room-pipeline-2026-11-05-answer.md`: onb-13 не трогает `room_catalog.py`; общий адаптер каталога — волна Б
плана `room-pipeline-01`). Здесь — только то, чем прихожая отличается: правила `rules/hall-roles.json`, разбор размеров
плоских предметов (зеркала), имя комнаты в запросах. Роли, размеры, сторож, дедуп, разбор фидов, таблица отчёта —
чистые функции `room_catalog` с правилами прихожей (R передаётся явно), поэтому спальня не меняется ни на строку.

Предохранители — те же, что у спальни (`room_catalog.run`): фид в карантине — магазин не трогаем; «похудевший» магазин
(< shrink_ratio прошлого успешного прогона прихожей) — не трогаем; пропавший оффер — missing_runs+1, не показывается.

  ~/venvs/scout/bin/python hall_catalog.py --measure [--photos N]   # замер по фидам без базы: роль × магазин
  ~/venvs/scout/bin/python hall_catalog.py --coverage               # покрытие: роль × фото/цена/размеры × меш (чтение products)
  ~/venvs/scout/bin/python hall_catalog.py --run --dry              # сухой прогон: база только читается
  ~/venvs/scout/bin/python hall_catalog.py --run                    # загрузить (ночью — следующая задача, не эта)
  ~/venvs/scout/bin/python hall_catalog.py --report [--photos N]    # что показывается из базы
  python3 hall_catalog.py --selftest                                # правила ролей и размеров, без базы и фидов
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import room_catalog as C  # noqa: E402

RULES = os.path.join(HERE, 'rules', 'hall-roles.json')
ROOM = 'hall'


def rules() -> dict:
    return {**json.load(open(RULES, encoding='utf-8')), '_room': ROOM}


_TRIPLE = re.compile(r'(\d{1,3}(?:[.,]\d)?)\s*[хx×*]\s*(\d{1,3}(?:[.,]\d)?)\s*[хx×*]\s*(\d{1,3}(?:[.,]\d)?)', re.I)
_PAIR = re.compile(r'(\d{2,3}(?:[.,]\d)?)\s*[хx×*]\s*(\d{2,3}(?:[.,]\d)?)(?!\s*[хx×*]?\s*\d)', re.I)


def flat_dims(o: dict, cfg: dict, sane: dict | None, got: dict | None = None) -> dict | None:
    """Плоский предмет (зеркало, `dims_flat` правил): у магазинов размер — «ширина×высота» («Размеры: 50x70»,
    «Зеркало … 40x160») или тройка в названии «88х4х88» (средняя — толщина). Тройка → w×d×h как есть; пара (или w и h,
    разобранные `dim_resolver`, — got) → w×h, а толщина — `wall_d_cm` ТОЛЬКО у настенного (`wall_re` в названии): на плане
    сверху это линия у стены. Напольное по паре — без глубины (опоры в данных нет) → только фото. → поля dims_of или None.
    Чистая функция."""
    nm = o.get('name') or ''
    f = lambda v: float(v.replace(',', '.'))  # noqa: E731
    src = [nm] + [str(v) for k, v in (o.get('params') or {}).items() if re.search(r'размер', k, re.I)]
    d = None
    for t in src:
        m = _TRIPLE.search(t)
        if m and f(m.group(2)) <= cfg.get('max_d_cm', 10):
            d = {'w': f(m.group(1)), 'd': f(m.group(2)), 'h': f(m.group(3)), 'note': 'плоский: тройка w×толщина×h'}
            break
    wall = re.search(cfg.get('wall_re', '$^'), nm, re.I)
    if d is None and wall and got and got.get('w') and got.get('h') and not got.get('d'):
        d = {'w': float(got['w']), 'd': float(cfg['wall_d_cm']), 'h': float(got['h']),
             'note': f"плоский настенный: w×h из параметров, толщина принята {cfg['wall_d_cm']:g} см"}
    if d is None and wall:
        for t in src:
            m = _PAIR.search(t)
            if m:
                d = {'w': f(m.group(1)), 'd': float(cfg['wall_d_cm']), 'h': f(m.group(2)),
                     'note': f"плоский настенный: w×h, толщина принята {cfg['wall_d_cm']:g} см"}
                break
    if d is None:
        return None
    bad = [k for k, (lo, hi) in (sane or {}).items() if not lo <= d[k] <= hi]
    d['ok'] = not bad
    if bad:
        d['note'] += f' — неправдоподобно ({",".join(bad)})'
    return d


def kit_of(o: dict, role: str, R: dict) -> str | None:
    """Комплект из модулей (`kits` правил, T-20261106-71): стенка из нескольких модулей серии — только фото. Признаки
    общие: название (`name_re`: «Модульная прихожая …») ИЛИ параметр-перечень (`param_re`: «Элементы системы») с
    ≥ `min_modules` разными модулями «Серия-N». → причина или None. Чистая функция."""
    K = R.get('kits') or {}
    if role not in K.get('roles', ()):
        return None
    if re.search(K.get('name_re', '$^'), o.get('name') or '', re.I):
        return 'комплект из модулей (название)'
    for k, v in (o.get('params') or {}).items():
        if re.search(K.get('param_re', '$^'), k, re.I):
            mods = {(a.lower(), n) for a, n in re.findall(K.get('module_re', '$^'), str(v))}
            if len(mods) >= int(K.get('min_modules', 2)):
                return f'комплект из модулей ({k}: {len(mods)} модул.)'
    return None


def dims_of(o: dict, role: str, R: dict) -> dict:
    """Размеры прихожей: общий `room_catalog.dims_of` (dim_resolver + правдоподобие `dims_sane`), а плоским предметам,
    у которых он не набрал трёх осей, — `flat_dims`. Комплект из модулей (`kit_of`) — только фото: footprint_ok=false
    даже при найденных размерах (размер модуля — не габарит стенки) → не в расстановку и не в меши (`room_mesh_jobs.job_of`)."""
    out = C.dims_of(o, role, R)
    cfg = R.get('dims_flat', {}).get(role)
    if not out['ok'] and cfg:
        from dim_resolver import resolve
        got, _ev, _src = resolve(o['mid'], o['name'], o['params'], R['dims_as'].get(role, role))
        out.update(flat_dims(o, cfg, R.get('dims_sane', {}).get(role), got) or {})
    kit = kit_of(o, role, R)
    if kit:
        out.update(ok=False, note=f"{kit} — только фото" + (f"; {out['note']}" if out.get('note') else ''))
    return out


def with_dims(offers: list, R: dict) -> list:
    for o in offers:
        o['_d'] = dims_of(o, o['br_role'], R)
    return offers


def shown_where(R: dict | None = None) -> str:
    """Что показываем: есть цена, есть живое фото, оффер в последнем свежем фиде (как `room_catalog.shown_where`, комната — hall)."""
    R = R or rules()
    return (f"room='{ROOM}' and price_rub is not null and coalesce(image_url_hd, image_url) is not null and {C.PHOTO_OK_SQL} "
            f"and missing_runs < {int(R.get('missing_hide_after', 1))}")


def rows_of(offers: list) -> list:
    """Офферы с размерами → строки VALUES для room_catalog (тот же порядок столбцов, что у спальни, без kids)."""
    L = C._lit
    out = []
    for o in offers:
        d = o['_d']
        out.append('(' + ','.join(L(x) for x in (
            o['mid'], str(o['eid']), ROOM, o['br_role'], o['shop'], o['name'], o['brand'], o['url'], o['pic'], o['pic_hd'],
            o['price'], d['w'], d['d'], d['h'], None, None, d['ok'], d['note'])) +
            ',' + L(json.dumps(o['params'], ensure_ascii=False)) + '::jsonb, current_date, 0, now())')
    return out


def run(dry: bool = False) -> int:
    """Загрузка прихожей. dry — сухой прогон: база только читается (прошлые прогоны прихожей), запросы собираются,
    но не выполняются; печатается, сколько было бы принято."""
    if not dry:
        C.sql(open(os.path.join(HERE, '013-room-catalog.sql'), encoding='utf-8').read())
    R = rules()
    offers, seen_mids = C.collect(R)
    by_mid: dict = {}
    for o in offers:
        by_mid[o['mid']] = by_mid.get(o['mid'], 0) + 1
    prev = {int(r[0]): int(r[1]) for r in C.sql(
        f"select distinct on (shop_mid) shop_mid, accepted from room_catalog_runs where room='{ROOM}' and verdict='ok' "
        "order by shop_mid, run_at desc") if len(r) == 2}
    skip = {m for m in seen_mids if prev.get(m) and by_mid.get(m, 0) < R['shrink_ratio'] * prev[m]}
    for m in skip:
        print(f'WARN:hall_catalog: магазин {m} похудел ({by_mid.get(m, 0)} < {R["shrink_ratio"]}×{prev[m]}) — не трогаю', flush=True)
    keep, gone = C.guarded(with_dims([o for o in offers if o['mid'] not in skip], R), R)
    print(C.guard_line(gone), flush=True)
    rows = rows_of(keep)
    done = [m for m in seen_mids if m not in skip]
    t0 = C.sql('select now()')[0][0]
    q = ['begin;']
    for i in range(0, len(rows), 500):
        q.append('insert into room_catalog (shop_mid, external_id, room, role, shop, name, brand, url, image_url, image_url_hd, '
                 'price_rub, w_cm, d_cm, h_cm, sleep_w_cm, sleep_l_cm, footprint_ok, dims_note, params, last_seen, missing_runs, '
                 'updated_at) values ' + ','.join(rows[i:i + 500]) +
                 ' on conflict (shop_mid, external_id, room) do update set role=excluded.role, shop=excluded.shop, '
                 'name=excluded.name, brand=excluded.brand, url=excluded.url, image_url=excluded.image_url, '
                 'image_url_hd=excluded.image_url_hd, price_rub=excluded.price_rub, w_cm=excluded.w_cm, d_cm=excluded.d_cm, '
                 'h_cm=excluded.h_cm, sleep_w_cm=excluded.sleep_w_cm, sleep_l_cm=excluded.sleep_l_cm, '
                 'footprint_ok=excluded.footprint_ok, dims_note=excluded.dims_note, params=excluded.params, '
                 'last_seen=excluded.last_seen, missing_runs=0, updated_at=now();')
    if done:
        q.append(f"update room_catalog set missing_runs = missing_runs + 1 where room='{ROOM}' and "
                 f"shop_mid in ({','.join(str(m) for m in done)}) and updated_at < '{t0}';")
    for m in seen_mids:
        q.append(f"insert into room_catalog_runs (room, shop_mid, accepted, verdict) values ('{ROOM}', {m}, "
                 f"{by_mid.get(m, 0)}, '{'shrunk' if m in skip else 'ok'}');")
    q.append('commit;')
    if dry:
        print(f'СУХОЙ ПРОГОН каталог прихожей: принял бы {len(rows)} офферов, магазинов {len(done)}, пропущено похудевших '
              f'{len(skip)}; запросов {len(q)} — в базу не пишу', flush=True)
        return 0
    C.sql('\n'.join(q))
    print(f'каталог прихожей: принято {len(rows)} офферов, магазинов {len(done)}, пропущено похудевших {len(skip)}', flush=True)
    return report()


def items_of(offers: list) -> list:
    return [{'role': o['br_role'], 'shop': o['shop'], 'price': o['price'], 'img': o.get('pic_hd') or o.get('pic'),
             'full': all(o['_d'].get(k) for k in ('w', 'd', 'h')) and bool(o['_d']['ok']),
             'honest': bool(o['_d'].get('ok')), 'name': o['name']} for o in offers]


def report(photos: int = 0) -> int:
    R = rules()
    rows = C.sql(f"select role, shop, price_rub, coalesce(image_url_hd, image_url), (w_cm is not null and d_cm is not null "
                 f"and h_cm is not null and coalesce(footprint_ok, false)), coalesce(footprint_ok, false), name "
                 f"from room_catalog where {shown_where(R)}")
    if not rows:
        print('WARN:hall_catalog: каталог прихожей пуст — вкладка демо покажет «скоро»', flush=True)
        return 0
    by: dict = {}
    for r in rows:
        by.setdefault(r[0], [0, 0])
        by[r[0]][0] += 1
        by[r[0]][1] += r[5] == 't'
    for role, (n, h) in sorted(by.items(), key=lambda x: -x[1][0]):
        print(f'  {role}: показываем {n}, с размерами для расстановки {h}', flush=True)
    if '--by-shop' in sys.argv or photos:
        items = [{'role': r[0], 'shop': r[1], 'price': r[2], 'img': r[3], 'full': r[4] == 't', 'honest': r[5] == 't',
                  'name': r[6]} for r in rows]
        for ln in C.table(items, R, photos):
            print(ln, flush=True)
    return 0


def measure(photos: int = 0) -> int:
    """Замер БЕЗ базы: те же фиды и правила, что у `--run`, таблица роль × магазин + детское в прихожей (должно быть 0)."""
    R = rules()
    offers, _seen = C.collect(R)
    offers, gone = C.guarded(with_dims(offers, R), R)
    print(C.guard_line(gone), flush=True)
    for ln in C.table(items_of(offers), R, photos):
        print(ln, flush=True)
    leak = C.kids_leak([(o['br_role'], o['name']) for o in offers], R)
    print(f'детское в прихожей: {len(leak)}' + (' — ' + '; '.join(f'{r}: {n[:40]}' for r, n in leak[:8]) if leak else ''))
    return 0


def coverage() -> int:
    """Покрытие ролей (DoD T-34): роль × предложений × с фото / ценой / размерами для расстановки × меш. Фиды — как у
    `--measure`; меши — ЧТЕНИЕ `products` (гостиная): «тот же товар» — тот же магазин и external_id с mesh_uri; «та же
    модель» — `room_catalog.family` названия совпадает с мешем любого товара (меш семейства, ADR-0196, приблизительно)."""
    R = rules()
    offers, _seen = C.collect(R)
    offers, _gone = C.guarded(with_dims(offers, R), R)
    rows = C.sql("select shop_mid, external_id, name from products where mesh_uri is not null")
    same = {(int(r[0]), r[1]) for r in rows if r[0]}
    fams = {C.family(r[2]) for r in rows}
    by: dict = {}
    for o in offers:
        b = by.setdefault(o['br_role'], {'n': 0, 'foto': 0, 'price': 0, 'dims': 0, 'show': 0, 'mesh': 0, 'fam': 0,
                                          'models': set(), 'mmodels': set()})
        foto, price, dims = bool(o.get('pic_hd') or o.get('pic')), bool(o['price']), bool(o['_d']['ok'])
        fam = C.family(o['name'])
        b['n'] += 1
        b['foto'] += foto
        b['price'] += price
        b['dims'] += dims
        b['show'] += foto and price and dims
        b['mesh'] += (o['mid'], str(o['eid'])) in same
        b['fam'] += fam in fams
        b['models'].add(fam)
        if fam in fams:
            b['mmodels'].add(fam)
    print('| роль | предложений | с фото | с ценой | размеры для расстановки | в расстановку (фото+цена+размеры) | моделей '
          '| меш: тот же товар | меш: та же модель (моделей) |')
    print('|---|---|---|---|---|---|---|---|---|')
    tot = {k: 0 for k in ('n', 'foto', 'price', 'dims', 'show', 'mesh', 'fam')}
    for role in R['roles_enabled']:
        b = by.get(role)
        if not b:
            print(f'| {role} | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |')
            continue
        for k in tot:
            tot[k] += b[k]
        print(f"| {role} | {b['n']} | {b['foto']} | {b['price']} | {b['dims']} | {b['show']} | {len(b['models'])} | {b['mesh']} | "
              f"{b['fam']} ({len(b['mmodels'])}) |")
    print(f"| **всего** | {tot['n']} | {tot['foto']} | {tot['price']} | {tot['dims']} | {tot['show']} | — | {tot['mesh']} | {tot['fam']} |")
    return 0


def _selftest() -> int:
    """Роли и размеры на реальных названиях фидов 05.11 (`tests/fixtures/hall-role-cases.json`); детское — настоящий
    `category_map.is_kids`."""
    import category_map
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    R = rules()
    rl = lambda mid, cid, nm: C.role_of(mid, cid, nm, R, category_map.is_kids)  # noqa: E731
    ok('показ: мёртвое фото не показываем — то же поле, что у спальни (T-20261106-84)', C.PHOTO_OK_SQL in shown_where(R))
    cases = json.load(open(os.path.join(HERE, 'tests', 'fixtures', 'hall-role-cases.json'), encoding='utf-8'))
    miss = 0
    for c in cases:
        got = rl(c['mid'], c['cid'], c['name'])
        if got != c['role']:
            miss += 1
            print(f"FAIL роль: {c['name'][:60]} → {got}, ждали {c['role']} ({c.get('why', '')})")
    ok(f'роли прихожей на {len(cases)} реальных названиях', miss == 0)
    ok('каждая роль правил — в словаре солвера (rules/hall.json)', set(R['categories'].values()) | {r for _p, r in R['name_rules']}
       <= set(json.load(open(os.path.join(HERE, '..', '..', 'services', 'planner-solver', 'rules', 'hall.json'),
                             encoding='utf-8'))['roles']))
    ok('детского в прихожей нет: детская обувница → None', rl(112923, '13', 'Обувница детская Мишка') is None)
    ok('спальня не задета: правила спальни без hall-ролей', not ({'обувница', 'банкетка', 'шкаф-купе'}
                                                                  & set(C.rules()['categories'].values())))
    sane, cfg = R['dims_sane']['зеркало'], R['dims_flat']['зеркало']
    fd = lambda nm, params=None, got=None: flat_dims({'name': nm, 'params': params or {}}, cfg, sane, got)  # noqa: E731
    t = fd('Зеркало настенное Glasar 88х4х88 см', {'Ширина': '4', 'Высота': '88'})
    ok('зеркало: тройка 88х4х88 → w 88, толщина 4, h 88', (t['w'], t['d'], t['h'], t['ok']) == (88, 4, 88, True))
    t = fd('Зеркало настенное divan.ru Далия Лиловый 50x70', {'Размеры': '50x70'})
    ok('настенное по паре 50x70 → толщина принята 3', (t['w'], t['d'], t['h'], t['ok']) == (50, 3, 70, True))
    ok('напольное по паре 40x160 — без глубины, только фото', fd('Зеркало напольное divan.ru Зигрид Черный 40x160',
                                                                   {'Размеры': '40x160'}) is None)
    t = fd('Зеркало настенное divan.ru Ири Золотой 71', {}, {'w': 71, 'h': 71})
    ok('круглое настенное: w и h из параметров → толщина 3', (t['w'], t['d'], t['h']) == (71, 3, 71))
    ok('шкаф-купе: глубина 35 — не купе, 60 — купе; размер неизвестен — не отсекаем',
       C.role_guard('шкаф-купе', 'Шкаф-купе Х', {'w': 150, 'd': 35, 'h': 220}, R) == 'габарит: d 35 < 40'
       and C.role_guard('шкаф-купе', 'Шкаф-купе Х', {'w': 150, 'd': 60, 'h': 220}, R) is None
       and C.role_guard('шкаф-купе', 'Шкаф-купе Х', {'w': None, 'd': None, 'h': None}, R) is None)
    cons = C.dims_of({'mid': 112923, 'name': 'Консоль divan.ru Кимбол 80x35 Белый/Черный', 'params': {
        'Размеры: Длина габаритная': '80см', 'Размеры: Ширина габаритная': '35см', 'Размеры: Высота габаритная': '17см'}},
        'консоль', R)
    ok('настенная консоль-полка h 17 — неправдоподобна для консоли прихожей (только фото)', not cons['ok'])
    # T-20261107-10: консоль — напольная; полка и кронштейн Glasar (лист ориентации W1) — не в роль вовсе
    g = lambda nm, w, d, h: C.role_guard('консоль', nm, {'w': w, 'd': d, 'h': h}, R)  # noqa: E731
    ok('консоль: полка Glasar 50×25×25 и кронштейн 20×11×28 — не консоль; подвесная divan.ru 80×35×17 — тоже',
       g('Консоль настенная Glasar 50x25x25', 50, 25, 25) and g('Консоль настенная Glasar серебристая 20х11х28 см', 20, 11, 28)
       and g('Консоль divan.ru Кимбол 80x35 Белый/Черный', 80, 35, 17))
    ok('консоль: напольные проходят — самая низкая Glasar 80×32×69, Волкер 79×50×76; размер неизвестен — не отсекаем',
       g('Консоль Glasar с белым мрамором 80х32х69 см', 80, 32, 69) is None and g('Консоль divan.ru Волкер 79x50', 79, 50, 76) is None
       and g('Консоль Х', None, None, None) is None)
    # T-20261106-90: шкаф Ormatek «Элит» с отделкой «(профиль)» — в роль, но размеры НЕ выдумываем. Единицы противоречат:
    # параметры «1774см» × «2400см» — это мм (24 м высоты не бывает), а в названии «1488x450» — ширина на 286 мм меньше (так у
    # всех трёх Элит: 1188/902, 1774/1488, 2360/2074) → какой габарит настоящий, не доказано → только фото, без расстановки и меша
    elit = C.dims_of({'mid': 93965, 'name': 'Шкаф Орматек Шкаф-купе 3х дв Элит (ЛДСП Белый ЛДСП/Золото (профиль)) 1488x450',
                      'params': {'Ширина': '1774см', 'Высота': '2400см'}}, 'шкаф-купе', R)
    ok('шкаф Элит: единицы противоречат (мм под «см», ширина в названии ≠ в параметрах) — размер не выдуман, только фото',
       not elit['ok'] and elit['w'] is None)
    bad += _selftest_kits(R, ok)
    return 1 if bad else 0


def _selftest_kits(R: dict, ok) -> int:
    """Правило `kits` (T-20261106-71) на 26 реальных товарах роли «прихожая» 06.11 (`tests/fixtures/hall-kits-20261106.json`):
    сколько в 3D и сколько только фото — без правила и с правилом; признаки, а не список SKU; меши (`job_of`) — только 3D."""
    import room_mesh_jobs as RMJ
    fx = json.load(open(os.path.join(HERE, 'tests', 'fixtures', 'hall-kits-20261106.json'), encoding='utf-8'))['items']
    R0 = {k: v for k, v in R.items() if k != 'kits'}
    in3d = lambda RR: [o for o in fx if dims_of(o, 'прихожая', RR)['ok']]  # noqa: E731
    was, now = in3d(R0), in3d(R)
    kits = [o for o in fx if kit_of(o, 'прихожая', R)]
    print(f'     роль «прихожая»: товаров {len(fx)}; без правила kits — в 3D {len(was)}, только фото {len(fx) - len(was)}; '
          f'с правилом — в 3D {len(now)}, только фото {len(fx) - len(now)} (из них комплектов {len(kits)})')
    ok('прихожая: в 3D только «Неста 77×190», 4 цвета', len(now) == 4 and all('Неста' in o['name'] for o in now))
    ok('22 модульные (Сайрис, Кимбол, Авильтон) — комплекты, только фото',
       len(kits) == 22 and {re.search(r'Сайрис|Кимбол|Авильтон', o['name']).group(0) for o in kits} == {'Сайрис', 'Кимбол', 'Авильтон'}
       and all(not dims_of(o, 'прихожая', R)['ok'] and 'только фото' in dims_of(o, 'прихожая', R)['note'] for o in kits))
    k0 = next(o for o in kits if 'Сайрис 2' in o['name'])
    by_param = dict(k0, name='Прихожая divan.ru Сайрис 2 Белый')         # «модульная» из названия убрана — остался перечень модулей
    ok('признак «перечень модулей» в параметрах: комплект и без слова «модульная»',
       (kit_of(by_param, 'прихожая', R) or '').startswith('комплект из модулей (Элементы системы'))
    one = dict(by_param, params={'Элементы системы': 'Сайрис-1 White'})
    ok('один модуль в перечне — не комплект', kit_of(one, 'прихожая', R) is None)
    sized = dict(k0, params={**k0['params'], 'Размеры: Длина габаритная': '200см', 'Размеры: Ширина габаритная': '40см',
                             'Размеры: Высота габаритная': '210см'})
    ok('комплект с найденными размерами — всё равно только фото (размер модуля — не габарит стенки)',
       C.dims_of(sized, 'прихожая', R0)['ok'] and not dims_of(sized, 'прихожая', R)['ok'])
    ok('правило — только для ролей kits.roles: шкаф-купе «модульный» не задет', kit_of(
        {'name': 'Шкаф-купе модульный', 'params': {}}, 'шкаф-купе', R) is None)
    job = lambda o: RMJ.job_of(dict(  # noqa: E731
        shop_mid=o['mid'], external_id=o['eid'], role='прихожая', name=o['name'], image_url='u', shown=True,
        footprint_ok=dims_of(o, 'прихожая', R)['ok'], **{k + '_cm': dims_of(o, 'прихожая', R)[k] or 0 for k in 'wdh'}), 'hall')
    ok('меши: комплект (и с размерами) — job_of отказывает, Неста — задание',
       all(job(o)[0] is None for o in kits + [sized]) and all(job(o)[0] is not None for o in now))
    return 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    _ph = int(sys.argv[sys.argv.index('--photos') + 1]) if '--photos' in sys.argv else 0
    if '--report' in sys.argv:
        sys.exit(report(_ph))
    if '--measure' in sys.argv:
        sys.exit(measure(_ph))
    if '--coverage' in sys.argv:
        sys.exit(coverage())
    if '--run' in sys.argv:
        sys.exit(run(dry='--dry' in sys.argv))
    print(__doc__)
