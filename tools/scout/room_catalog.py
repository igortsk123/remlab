#!/usr/bin/env python3
"""Каталог СПАЛЬНИ из фидов Гдеслона → таблица `room_catalog` (план b2b-10 этап 2, v1; ADR-0279).

ЗАЧЕМ. Вкладка «Спальня» демо была «скоро»: карта категорий гостиной запрещает кровати, тумбы и спальные шкафы
(`category_map.DENY` «спальня»), в базе их нет. v1 — фото-каталог: кровати, прикроватные тумбы, комоды, шкафы,
туалетные столики с фото, ценой и партнёрской ссылкой; моделей и расстановки пока нет («3D позже»).

ПОЧЕМУ ОТДЕЛЬНАЯ ТАБЛИЦА (разбор Codex 14.10). `products` читают ночные шаги гостиной без фильтра по роли
(обогащение за деньги, проверки страниц, очередь мешей, стыки конвейера) — кровати там дали бы расходы и ложные
тревоги. Разбор фида — тот же, что у загрузчика гостиной (`load3.parse_feed`, `load3.load_fresh`, `load3.dedupe`).

ПРЕДОХРАНИТЕЛИ (как у `load3`): фид в карантине (`feed-freshness.json`: broken/stale/empty) — магазин не трогаем;
«похудевший» магазин (принято < shrink_ratio прошлого успешного) — не трогаем; оффер пропал из свежего фида —
`missing_runs+1` и он не показывается; нет цены — не показывается. Наличие = «есть в свежем фиде и есть цена»
(поле `available` у Гдеслона пустое, ADR-0171), поэтому на странице — «цена по каталогу, уточните у продавца».

  ~/venvs/scout/bin/python room_catalog.py --run       # загрузить
  ~/venvs/scout/bin/python room_catalog.py --report [--by-shop] [--photos N]   # сколько по ролям показывается
  ~/venvs/scout/bin/python room_catalog.py --measure [--photos N]   # замер по фидам без базы: роль × магазин
  python3 room_catalog.py --selftest                   # правила ролей и размеров, без базы
"""
import glob
import json
import os
import re
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
RULES = os.path.join(HERE, 'rules', 'bedroom-roles.json')
ROOM = 'bedroom'


def psql() -> list:
    return ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d',
            os.environ.get('REMLAB_DEVDB_NAME', 'remlab'), '-q', '-v', 'ON_ERROR_STOP=1', '-tA', '-F', '\x1f']


def sql(q: str) -> list:
    r = subprocess.run(psql(), input=q, capture_output=True, text=True, timeout=600)
    if r.returncode:
        raise RuntimeError(r.stderr[:600])
    return [ln.split('\x1f') for ln in r.stdout.split('\n') if ln]


def rules() -> dict:
    return json.load(open(RULES, encoding='utf-8'))


def role_of(mid: int, cid, name: str, R: dict, is_kids) -> str | None:
    """Роль спальни для оффера или None. Чистая функция (селфтест): точная категория → роль; смешанная — по
    названию (новые смешанные ветки — только роли `mixed_roles`); запрет по названию — в любой ветке; кровать обязана
    называться кроватью. ДЕТСКОЕ (название по `is_kids` или детская категория) — ТОЛЬКО в детские роли (`kids_roles`):
    взрослая роль переходит в детскую по `kids_alias` («Кровать детская» в ветке кроватей → «кровать детская»), иначе
    None. Детские шкаф/комод/тумба (`kids_shared`) остаются в своей роли — с назначением только child:* (`child_only`).
    Так детское не протекает в спальню пары и гостевую (onb-04, ADR-0330), а старые роли видят его как раньше."""
    key = f'{mid}:{cid}'
    nm = name or ''
    if re.search(R['name_deny'], nm, re.I):
        return None
    kids = bool(is_kids(nm)) or key in R.get('kids_categories', ())
    role = R['categories'].get(key)
    if role is None and key in R['mixed']:
        for pat, r in R['name_rules']:
            if re.search(pat, nm, re.I):
                role = r
                break
    if role is None:
        return None
    if kids and role not in R.get('kids_roles', ()) and role not in R.get('kids_shared', ()):
        role = R.get('kids_alias', {}).get(role)
        if role is None:
            return None
    allowed = R.get('mixed_roles', {}).get(key)
    if allowed is not None and role not in allowed:
        return None
    must = R.get('role_must_match', {}).get(role)
    if must and not re.search(must, nm, re.I):
        return None
    deny = R.get('role_deny', {}).get(role)
    if deny and re.search(deny, nm, re.I):
        return None
    return role


def enabled(R: dict | None = None) -> list:
    """Роли, которые показ и демо берут сейчас (флаг `roles_enabled`); остальные грузятся, но не видны."""
    R = R or rules()
    return list(R.get('roles_enabled') or [])


def enabled_sql(R: dict | None = None) -> str:
    return 'role in (' + ','.join(_lit(r) for r in enabled(R)) + ')'


def child_only(role: str, name: str, R: dict) -> bool:
    """Детский товар в общей роли (`kids_shared`: «Шкаф детский» в роли «шкаф») — только для детской: назначения
    child:*, в спальню пары/гостевую (`flat215_demo.bedroom_catalog`) не идёт. Детское — тот же `category_map.is_kids`."""
    import category_map
    return role in R.get('kids_shared', ()) and bool(category_map.is_kids(name or ''))


def hidden_purposes(good: dict, R: dict) -> set:
    """Назначения, которые скрыты, пока у роли-опоры нет годных товаров (`purpose_requires`: child:0-3 — нет годной
    кроватки → нет и шкафа «для малыша»). good — {роль: годных (показ + честный габарит)}."""
    return {t for t, q in R.get('purpose_requires', {}).items() if good.get(q['role'], 0) < q.get('min', 1)}


def purposes_of(role: str, d: dict, R: dict, kids: bool = False, hidden=()) -> list:
    """Назначения ADR-0330 для товара роли: couple|single|guest|office|child:<возраст>. Условие правила — диапазоны
    см по sw/sl (спальное место) и h (высота; растущая мебель — h_min..h, совпадение — пересечение). Нужного размера
    нет — назначения нет: не обещаем подростку кровать, у которой спальное место не указано. kids — детский товар общей
    роли (`child_only`): только child:*; hidden — скрытые назначения (`hidden_purposes`). Чистая функция."""
    out = []
    trust = role in R.get('bed_roles', ()) or bool(d.get('ok'))     # неполные/неправдоподобные размеры — неизвестны
    for tag, cond in (R.get('purposes', {}).get(role) or {}).items():
        if tag in hidden or (kids and not tag.startswith('child:')):
            continue
        fit = True
        for k, (lo, hi) in cond.items():
            v = d.get(k) if trust or k in ('sw', 'sl') else None
            v0 = d.get('h_min') if k == 'h' and d.get('h_min') else v
            if v is None or v0 > hi or v < lo:
                fit = False
                break
        if fit:
            out.append(tag)
    return out


_RANGE_H = re.compile(r'(\d{2,3})\s*(?:-|–|/|до)\s*(\d{2,3})')
_GROW = re.compile(r'растущ|регулир\w* по высот|с регулировкой высот', re.I)


def grow_height(name: str, params: dict) -> tuple | None:
    """Растущая парта/стул: диапазон высоты (см) из параметров высоты или названия → (min, max) или None.
    «Парта-мольберт 102х61,5х680/910 см» — мм внутри см-тройки: 680/910 → 68–91."""
    nm = name or ''
    srcs = [v for k, v in (params or {}).items() if re.search(r'высот', k, re.I) and v]
    if _GROW.search(nm) or any(_GROW.search(k + ' ' + v) for k, v in (params or {}).items()):
        srcs.append(nm)
    for s in srcs:
        m = _RANGE_H.search(str(s))
        if m:
            a, b = float(m.group(1)), float(m.group(2))
            if a > 200 and b > 200:
                a, b = a / 10, b / 10
            if 30 <= a < b <= 130:
                return a, b
    return None


def dims_of(o: dict, role: str, R: dict) -> dict:
    if role in R.get('bed_roles', ('кровать',)):
        import bed_dims
        fm = R.get('frame_max', {}).get(role)
        b = bed_dims.parse(o['params'], o['name'], *(fm or ()))
        return {'w': b['w_cm'], 'd': b['d_cm'], 'h': b['h_cm'], 'sw': b['sleep_w_cm'], 'sl': b['sleep_l_cm'],
                'ok': b['footprint_ok'], 'note': b['why']}
    from dim_resolver import resolve
    dims, _ev, src = resolve(o['mid'], o['name'], o['params'], R['dims_as'].get(role, role))
    ok = all(dims.get(k) for k in ('w', 'd', 'h'))
    note = '' if ok else f'размеры не полные ({src or "нет"})'
    sane = R.get('dims_sane', {}).get(role)
    if ok and sane:
        bad = [k for k, (lo, hi) in sane.items() if not lo <= dims[k] <= hi]
        if bad:
            ok, note = False, f'размеры неправдоподобны для роли ({",".join(bad)}; {src}) — оси перепутаны?'
    out = {'w': dims.get('w'), 'd': dims.get('d'), 'h': dims.get('h'), 'sw': None, 'sl': None, 'ok': ok, 'note': note}
    g = grow_height(o['name'], o['params']) if role in ('стол детский', 'стол рабочий', 'стул детский') else None
    if g:          # растущая: в базе h — верх диапазона (столбца под диапазон нет), низ — в заметке и в purposes_of
        out.update({'h_min': g[0], 'h': g[1], 'note': (out['note'] + '; ' if out['note'] else '') + f'растущая: высота {g[0]:.0f}–{g[1]:.0f}'})
    return out


def line_dims(items: list) -> dict:
    """Габарит «линейки», а не кровати: в магазине один и тот же габарит (w×d) стоит у кроватей с ≥3 разными спальными
    местами (Орматек: 200×200 у 80, 140 и 160) — это общие числа серии. → {индекс: причина}. Правило по данным, не по
    названию магазина: новый магазин с той же привычкой поймается сам. Чистая функция (селфтест)."""
    groups: dict = {}
    for i, (mid, role, d) in enumerate(items):
        if role == 'кровать' and d.get('w') and d.get('d') and d.get('sw'):
            groups.setdefault((mid, d['w'], d['d']), []).append(i)
    out = {}
    for (_mid, w, dd), idx in groups.items():
        if len({items[i][2]['sw'] for i in idx}) >= 3:
            for i in idx:
                out[i] = f'габарит {w:.0f}×{dd:.0f} общий для линейки (у кроватей с разными спальными местами) — не этой кровати'
    return out


def _lit(v) -> str:
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        return repr(float(v)) if isinstance(v, float) else str(v)
    return "'" + str(v).replace("'", "''") + "'"


def collect(R: dict) -> tuple:
    """Свежие фиды → офферы спальни с ролью `br_role` (после дедупа) и множество увиденных магазинов. Без базы:
    этим же путём идут и ночная загрузка, и замер `--measure`."""
    import category_map
    import load3 as L
    catrole, known = L.load_roles()
    fresh = L.load_fresh()
    offers, seen_mids = [], set()
    for z in sorted(glob.glob(os.path.join(L.FEEDS, '*.zip'))):
        fh = os.path.basename(z).split('.')[0]
        st = (fresh.get(fh) or {}).get('state')
        if st in ('broken', 'stale', 'empty') or not zipfile.is_zipfile(z):
            print(f'ФИД {fh[:12]} ПРОПУЩЕН: {st or "не zip"} — товары магазина остаются как есть', flush=True)
            continue
        offs, raw = L.parse_feed(z, catrole, known)
        seen_mids |= set(raw)
        for o in offs:
            role = role_of(o['mid'], o['cid'], o['name'], R, category_map.is_kids)
            if role:
                o['br_role'] = role
                offers.append(o)
    offers, _d = L.dedupe(offers)
    return offers, seen_mids


def with_dims(offers: list, R: dict) -> list:
    for o in offers:
        o['_d'] = dims_of(o, o['br_role'], R)
    for i, why in line_dims([(o['mid'], o['br_role'], o['_d']) for o in offers]).items():
        offers[i]['_d'].update({'ok': False, 'note': why})
    return offers


def run() -> int:
    sql(open(os.path.join(HERE, '013-room-catalog.sql'), encoding='utf-8').read())
    R = rules()
    offers, seen_mids = collect(R)
    by_mid: dict = {}
    for o in offers:
        by_mid[o['mid']] = by_mid.get(o['mid'], 0) + 1
    prev = {int(r[0]): int(r[1]) for r in sql(
        f"select distinct on (shop_mid) shop_mid, accepted from room_catalog_runs where room='{ROOM}' and verdict='ok' "
        "order by shop_mid, run_at desc") if len(r) == 2}
    skip = {m for m in seen_mids if prev.get(m) and by_mid.get(m, 0) < R['shrink_ratio'] * prev[m]}
    for m in skip:
        print(f'WARN:room_catalog: магазин {m} похудел ({by_mid.get(m, 0)} < {R["shrink_ratio"]}×{prev[m]}) — не трогаю', flush=True)
    rows = []
    keep = with_dims([o for o in offers if o['mid'] not in skip], R)
    for o in keep:
        d = o['_d']
        rows.append('(' + ','.join(_lit(x) for x in (
            o['mid'], str(o['eid']), ROOM, o['br_role'], o['shop'], o['name'], o['brand'], o['url'], o['pic'], o['pic_hd'],
            o['price'], d['w'], d['d'], d['h'], d['sw'], d['sl'], d['ok'], d['note'])) +
            ',' + _lit(json.dumps(o['params'], ensure_ascii=False)) + '::jsonb, current_date, 0, now())')
    done = [m for m in seen_mids if m not in skip]
    t0 = sql('select now()')[0][0]          # отметка прогона: всё, что не обновлено в этом прогоне, — пропало
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
    if done:   # пропавшие из СВЕЖЕГО фида своего магазина — не показываем, строку не удаляем
        q.append(f"update room_catalog set missing_runs = missing_runs + 1 where room='{ROOM}' and "
                 f"shop_mid in ({','.join(str(m) for m in done)}) and updated_at < '{t0}';")
    for m in seen_mids:
        q.append(f"insert into room_catalog_runs (room, shop_mid, accepted, verdict) values ('{ROOM}', {m}, "
                 f"{by_mid.get(m, 0)}, '{'shrunk' if m in skip else 'ok'}');")
    q.append('commit;')
    sql('\n'.join(q))
    print(f'каталог спальни: принято {len(rows)} офферов, магазинов {len(done)}, пропущено похудевших {len(skip)}', flush=True)
    return report()


def shown_where(R: dict | None = None) -> str:
    """Что показываем: есть цена, есть фото, оффер в последнем свежем фиде (один предикат для отчёта и экспорта)."""
    R = R or rules()
    return (f"room='{ROOM}' and price_rub is not null and coalesce(image_url_hd, image_url) is not null "
            f"and missing_runs < {int(R.get('missing_hide_after', 1))}")


_FAM_STOP = None


def family(name: str) -> str:
    """Модель без размера, цвета и обивки: «Кровать divan.ru Кейси 90 Велюр Оливковый», «Офисное кресло divan.ru Дейзи
    Букле Терракотовый/Черный» → «кровать divan.ru кейси», «офисное кресло divan.ru дейзи» (до первого слова с цифры,
    материала или цвета из `data/names-en-dict.json`; скобки отрезаны). Для счёта «моделей», приблизительно."""
    global _FAM_STOP
    if _FAM_STOP is None:
        try:
            D = json.load(open(os.path.join(HERE, 'data', 'names-en-dict.json'), encoding='utf-8'))
            _FAM_STOP = {w for k in ('materials', 'colours') for w in D.get(k, {}) if ' ' not in w}
        except Exception:  # noqa: BLE001 — без словаря: только цифры
            _FAM_STOP = set()
    out = []
    for t in re.sub(r'\s*\(.*$', '', name or '').split():
        w = t.lower().strip(',')
        if re.match(r'\d', w) or w.split('/')[0] in _FAM_STOP or w in ('с', 'и', 'ткань'):
            break
        out.append(w)
    return ' '.join(out)


def photo_alive(url: str, tries: int = 3):
    """Фото скачивается → True / False / None («не смог проверить» — не приговор). Проверка — проектная
    `img_alive._probe` (HEAD, затем первые 2 КБ и сигнатура; мертво — только 404/410 или не картинка), в её кэш
    не пишем; «не смог» — до трёх попыток (Гдеслон отвечает 403 через раз, урок 468)."""
    import time
    import img_alive
    for k in range(tries):
        r = img_alive._probe(url)
        if r is not None:
            return r
        if k < tries - 1:
            time.sleep(1.5)
    return None


def table(items: list, R: dict, photos: int = 0, seed: int = 5) -> list:
    """Роль × магазин: в продаже (свежий фид + цена) · с фото · с живым фото (выборка `photos` на клетку: живых/проверенных,
    оценка на всю клетку; «не проверено» — CDN не ответил, не приговор)
    · с полными размерами · честный габарит (кровати) · моделей. items — {role, shop, price, img, full, honest, name}.
    → строки таблицы (markdown), первая — шапка."""
    import random
    from concurrent.futures import ThreadPoolExecutor
    on = set(enabled(R))
    cells: dict = {}
    for it in items:
        cells.setdefault((it['role'], it['shop']), []).append(it)
    alive: dict = {}
    if photos:
        rnd = random.Random(seed)
        todo = {}
        for k, lst in cells.items():
            shown = [x for x in lst if x['price'] and x['img']]
            todo[k] = rnd.sample(shown, min(photos, len(shown)))
        urls = sorted({x['img'] for v in todo.values() for x in v})
        with ThreadPoolExecutor(max_workers=8) as ex:
            got = dict(zip(urls, ex.map(photo_alive, urls)))
        for k, v in todo.items():
            known = [got[x['img']] for x in v if got[x['img']] is not None]
            alive[k] = (sum(known), len(known), len(v) - len(known))
    out = ['| роль | магазин | вкл | в продаже | с фото | живое фото | полные размеры | честный габарит | показ с размерами | моделей |',
           '|---|---|---|---|---|---|---|---|---|---|']
    order = sorted(cells, key=lambda k: (k[0] not in on, k[0], -len(cells[k])))
    for k in order:
        lst = cells[k]
        sale = [x for x in lst if x['price']]
        foto = [x for x in sale if x['img']]
        full = [x for x in foto if x['full']]
        bed = k[0] in R.get('bed_roles', ())
        hon = sum(1 for x in foto if x['honest']) if bed else None
        a, n, unk = alive.get(k, (None, 0, 0))
        live = (f'{a}/{n} (≈{round(len(foto) * a / n)})' if n else '—') + (f', не проверено {unk}' if unk else '')
        out.append(f"| {k[0]} | {k[1]} | {'да' if k[0] in on else 'нет'} | {len(sale)} | {len(foto)} | {live} | {len(full)} | "
                   f"{'—' if hon is None else hon} | {hon if bed else len(full)} | {len({family(x['name']) for x in foto})} |")
    return out


def kids_leak(rows, R: dict) -> list:
    """Детские названия вне детских ролей (должно быть 0): rows — (роль, название). Детское в общей роли
    (`kids_shared`) — не протечка: оно помечено `child_only` и идёт только в детскую."""
    import category_map
    kr = set(R.get('kids_roles', ())) | set(R.get('kids_shared', ()))
    return [(r, n) for r, n in rows if r not in kr and category_map.is_kids(n)]


def label(role: str, name: str, R: dict) -> str:
    """Строка отчёта: детское общей роли — отдельной строкой «шкаф · детское» (в демо пары его нет)."""
    return role + ' · детское' if child_only(role, name, R) else role


def requires_lines(good: dict, R: dict) -> list:
    hid = hidden_purposes(good, R)
    return [f"  назначение {t}: {'СКРЫТО' if t in hid else 'показываем'} — годных «{q['role']}» {good.get(q['role'], 0)} "
            f"(нужно ≥ {q.get('min', 1)})" for t, q in R.get('purpose_requires', {}).items()]


def report(photos: int = 0) -> int:
    R = rules()
    beds = ','.join(_lit(r) for r in R.get('bed_roles', ('кровать',)))
    # полные размеры: три оси; у не-кроватей ещё и `footprint_ok` (туда пишется проверка правдоподобия `dims_of`)
    rows = sql(f"select role, shop, price_rub, coalesce(image_url_hd, image_url), (w_cm is not null and d_cm is not null "
               f"and h_cm is not null and (role in ({beds}) or coalesce(footprint_ok, false))), coalesce(footprint_ok, false), "
               f"name from room_catalog where {shown_where(R)}")
    if not rows:
        print('WARN:room_catalog: каталог спальни пуст — вкладка демо покажет «скоро»', flush=True)
        return 0
    on = set(enabled(R))
    by: dict = {}
    for r in rows:
        k = label(r[0], r[6], R)
        by.setdefault(k, [0, 0])
        by[k][0] += 1
        by[k][1] += r[5] == 't'
    for role, (n, h) in sorted(by.items(), key=lambda x: -x[1][0]):
        print(f"  {role}: показываем {n}, с честным габаритом {h}{'' if role in on else ' (в демо пары нет)'}", flush=True)
    for ln in requires_lines({r: h for r, (n, h) in by.items()}, R):
        print(ln, flush=True)
    if '--by-shop' in sys.argv or photos:
        items = [{'role': label(r[0], r[6], R), 'shop': r[1], 'price': r[2], 'img': r[3], 'full': r[4] == 't',
                  'honest': r[5] == 't', 'name': r[6]} for r in rows]
        for ln in table(items, R, photos):
            print(ln, flush=True)
    leak = kids_leak([(r[0], r[6]) for r in rows], R)
    if leak:
        print(f'WARN:room_catalog: детское вне детских ролей — {len(leak)}: ' + '; '.join(f'{r}: {n[:40]}' for r, n in leak[:5]), flush=True)
    return 0


def measure(photos: int = 0) -> int:
    """Замер БЕЗ базы (onb-04 Т1/Т5): те же фиды и правила, что у `--run`, таблица роль × магазин + детское вне детских."""
    R = rules()
    offers, _seen = collect(R)
    with_dims(offers, R)
    items = [{'role': label(o['br_role'], o['name'], R), 'shop': o['shop'], 'price': o['price'], 'img': o.get('pic_hd') or o.get('pic'),
              'full': all(o['_d'].get(k) for k in ('w', 'd', 'h')) and (o['br_role'] in R.get('bed_roles', ()) or bool(o['_d']['ok'])),
              'honest': bool(o['_d'].get('ok')), 'name': o['name']}
             for o in offers]
    for ln in table(items, R, photos):
        print(ln, flush=True)
    good: dict = {}
    for it in items:
        good[it['role']] = good.get(it['role'], 0) + bool(it['price'] and it['img'] and it['honest'])
    for ln in requires_lines(good, R):
        print(ln, flush=True)
    leak = kids_leak([(o['br_role'], o['name']) for o in offers], R)
    print(f'детское вне детских ролей: {len(leak)}' + (' — ' + '; '.join(f'{r}: {n[:40]}' for r, n in leak[:8]) if leak else ''))
    return 0


def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    R = rules()
    kids = re.compile(r'детск|для детей', re.I).search
    rl = lambda mid, cid, nm: role_of(mid, cid, nm, R, lambda n: bool(kids(n)))  # noqa: E731
    ok('кровать divan.ru по категории', rl(112923, '32', 'Кровать divan.ru Кейт 160 Букле Серый') == 'кровать')
    ok('основание в ветке кроватей — не кровать', rl(112923, '32', 'Основание Орматек Панели для царгового пояса') is None)
    ok('детская кровать во взрослой ветке — не «кровать»', rl(112923, '32', 'Кровать детская Соня') == 'кровать детская')
    ok('ветка «Детские кровати» — только детская роль, не «кровать»', rl(112923, '17', 'Кровать Мишка') == 'кровать детская')
    ok('Орматек «Мебель для спальни»: кровать по названию', rl(93965, '615', 'Кровать Орматек Prado') == 'кровать')
    ok('Орматек «Мебель для спальни»: прикроватная тумба по названию', rl(93965, '615', 'Тумба прикроватная Skandy') == 'тумба прикроватная')
    ok('смешанная ветка: стеллаж — не спальня', rl(99272, '6985', 'Стеллаж Лофт') is None)
    ok('диван-кровать в смешанной ветке — не кровать спальни', rl(93965, '615', 'Диван-кровать Ормео') is None)
    ok('комод divan.ru по категории', rl(112923, '15', 'Комод divan.ru Сканди') == 'комод')
    ok('обувница — не спальня', rl(112923, '15', 'Обувница в прихожую Лайт') is None)
    ok('стеллаж в ветке «Шкафы» — не шкаф спальни', rl(114667, '49', 'Стеллаж 220 Орех Селект') is None)
    ok('категория гостиной (диваны) — не спальня', rl(112923, '176', 'Диван модульный') is None)
    d = dims_of({'mid': 112923, 'name': 'Кровать Кейт 140', 'params': {
        'Размеры: Длина габаритная': '230см', 'Размеры: Ширина габаритная': '173см', 'Размеры: Высота габаритная': '93см',
        'Спальное место: Длина спального места': '200см', 'Спальное место: Ширина спального места': '140см'}}, 'кровать', R)
    ok('кровать: габарит и спальное место раздельно', (d['w'], d['d'], d['sw'], d['sl'], d['ok']) == (173, 230, 140, 200, True))
    line = line_dims([(1, 'кровать', {'w': 200, 'd': 200, 'sw': x}) for x in (80, 140, 160)] +
                     [(2, 'кровать', {'w': 173, 'd': 230, 'sw': 140}), (2, 'кровать', {'w': 193, 'd': 230, 'sw': 160})])
    ok('габарит линейки (один на 3 разных спальных места) — не кровати; у разных габаритов — честно', sorted(line) == [0, 1, 2])
    _selftest_onb04(R, ok)     # провалы считает `ok` (nonlocal); «bad += …» затёр бы их старым значением bad
    return 1 if bad else 0


def _selftest_onb04(R: dict, ok) -> int:
    """Новые роли onb-04 на реальных названиях и карточках фидов 05.11 (`tests/fixtures/onb04-*.json`): роли и назначения
    расставлены руками, размеры — снимок, сверенный глазами. Детское — настоящий `category_map.is_kids`."""
    import category_map
    fx = os.path.join(HERE, 'tests', 'fixtures')
    load = lambda n: json.load(open(os.path.join(fx, n), encoding='utf-8'))  # noqa: E731
    rl = lambda mid, cid, nm: role_of(mid, cid, nm, R, category_map.is_kids)  # noqa: E731
    before = 0
    cases = load('onb04-role-cases.json')
    for c in cases:
        got = rl(c['mid'], c['cid'], c['name'])
        if got != c['role']:
            before += 1
            print(f"FAIL роль: {c['name'][:60]} → {got}, ждали {c['role']} ({c['why']})")
    ok(f'роли новых и старых на {len(cases)} реальных названиях', before == 0)
    kids_roles, keys = set(R['kids_roles']), list(R['categories']) + R['mixed']
    leak = [(n, k, r) for n in load('onb04-kids30.json') for k in keys
            for r in [rl(int(k.split(':')[0]), k.split(':')[1], n)] if r and r not in kids_roles and not child_only(r, n, R)]
    ok(f'30 детских названий × {len(keys)} веток — ни одного вне детских ролей (общие шкаф/комод/тумба — только child_only)',
       not leak)
    pa = lambda role, name, hid=(): purposes_of(role, {'ok': True, 'w': 80, 'd': 45, 'h': 190}, R,  # noqa: E731
                                                child_only(role, name, R), hid)
    ok('детский шкаф — в роли «шкаф», назначения только child:*, без пары и гостевой',
       rl(112923, '42', 'Шкаф детский divan.ru Кейла 1-105x190 Белый') == 'шкаф'
       and pa('шкаф', 'Шкаф детский divan.ru Кейла 1-105x190 Белый') == ['child:0-3', 'child:3-7', 'child:7-12', 'child:teen'])
    ok('взрослый шкаф — назначения прежние (пара, один, гостевая, кабинет, дети)',
       pa('шкаф', 'Распашной шкаф divan.ru Шелтон 2-91x212 Белый')[:4] == ['couple', 'single', 'guest', 'office'])
    hid = hidden_purposes({'кроватка': 0}, R)
    ok('нет годной кроватки — child:0-3 скрыто у всех ролей', hid == {'child:0-3'}
       and 'child:0-3' not in pa('шкаф', 'Шкаф детский divan.ru Кейла', hid) and hidden_purposes({'кроватка': 1}, R) == set())
    ok('отчёт: детское общей роли — своей строкой', label('комод', 'Комод детский divan.ru Милна 1-60x49 Белый', R)
       == 'комод · детское' and label('комод', 'Комод divan.ru Дигарс 43x102', R) == 'комод')
    for x in leak[:5]:
        print('     ', x)
    cards = load('onb04-dims-cards.json')
    per = {}
    miss = 0
    for c in cards:
        d = dims_of(c, c['role'], R)
        got = {k: d[k] for k in ('w', 'd', 'h', 'sw', 'sl', 'ok')} | ({'h_min': d['h_min']} if 'h_min' in d else {})
        pu = purposes_of(c['role'], d, R)
        per[c['role']] = per.get(c['role'], 0) + 1
        if got != c['expect'] or pu != c['purposes']:
            miss += 1
            print(f"FAIL размеры: {c['name'][:50]} {got} {pu} ждали {c['expect']} {c['purposes']}")
    ok(f'размеры и назначения на {len(cards)} реальных карточках ({per})', miss == 0)
    kb = [c for c in cards if c['role'] == 'кровать детская']
    ok('детские кровати: рама честная и не больше +40 см к спальному',
       all(c['expect']['ok'] and c['expect']['w'] - c['expect']['sw'] <= 40 and c['expect']['d'] - c['expect']['sl'] <= 40 for c in kb))
    pk = lambda role, **d: purposes_of(role, {'ok': True, **d}, R)  # noqa: E731
    ok('кровать 160×200: пара, гостевая; не подросток', pk('кровать', sw=160, sl=200) == ['couple', 'guest'])
    ok('кровать 90×200: один, гостевая, подросток', pk('кровать', sw=90, sl=200) == ['single', 'guest', 'child:teen'])
    ok('кровать без спального места — назначений нет', pk('кровать') == [])
    ok('детская 80×160: 3–7 и 7–12; 0–3 — только кроватка', pk('кровать детская', sw=80, sl=160) == ['child:3-7', 'child:7-12']
       and pk('кроватка', sw=60, sl=120) == ['child:0-3'])
    ok('растущая парта 52–76: все детские возрасты', pk('стол детский', h=76, h_min=52) == ['child:3-7', 'child:7-12', 'child:teen'])
    ok('стол с неправдоподобными размерами — без возраста', purposes_of('стол детский', {'h': 50, 'ok': False}, R) == [])
    ok('детское в гостевой — нет: у детских ролей только child:*',
       all(t.startswith('child:') for r in kids_roles for t in R['purposes'].get(r, {})))
    ok('растущая высота: «680/910» в мм внутри см → 68–91', grow_height('Парта-мольберт Shandong 102х61,5х680/910 см',
                                                                          {'Высота': '680/910'}) == (68.0, 91.0))
    ok('растущая высота: «Растущая парта, высота 52-76 см»', grow_height('Растущая парта Дэми, высота 52-76 см', {}) == (52.0, 76.0))
    ok('обычный стол — не растущий', grow_height('Письменный стол divan.ru Крейн-3 90x50', {'Размеры: Высота габаритная': '76см'}) is None)
    old5 = ['кровать', 'тумба прикроватная', 'комод', 'шкаф', 'туалетный столик']
    ok('флаг: новые роли выключены (включает ведущий после Т6 — поправить и этот тест)', enabled(R) == old5)
    ok('флаг: каждая роль правил — в purposes', all(r in R['purposes'] for r in set(R['categories'].values()) |
                                                     {r for _p, r in R['name_rules']}))
    ok('диван-кровать в room_catalog не грузится (ADR-0330 п.2)', 'диван-кровать' not in R['purposes'] and
       rl(93965, '615', 'Диван-кровать Ормео') is None)
    return 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    _ph = int(sys.argv[sys.argv.index('--photos') + 1]) if '--photos' in sys.argv else 0
    if '--report' in sys.argv:
        sys.exit(report(_ph))
    if '--measure' in sys.argv:
        sys.exit(measure(_ph))
    if '--run' in sys.argv:
        sys.exit(run())
    print(__doc__)
