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
  ~/venvs/scout/bin/python room_catalog.py --report    # сколько по ролям показывается
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
    названию; запрет по названию и детское — в любой ветке; кровать обязана называться кроватью."""
    key = f'{mid}:{cid}'
    nm = name or ''
    if re.search(R['name_deny'], nm, re.I) or is_kids(nm):
        return None
    role = R['categories'].get(key)
    if role is None and key in R['mixed']:
        for pat, r in R['name_rules']:
            if re.search(pat, nm, re.I):
                role = r
                break
    if role is None:
        return None
    must = R.get('role_must_match', {}).get(role)
    if must and not re.search(must, nm, re.I):
        return None
    return role


def dims_of(o: dict, role: str, R: dict) -> dict:
    if role == 'кровать':
        import bed_dims
        b = bed_dims.parse(o['params'], o['name'])
        return {'w': b['w_cm'], 'd': b['d_cm'], 'h': b['h_cm'], 'sw': b['sleep_w_cm'], 'sl': b['sleep_l_cm'],
                'ok': b['footprint_ok'], 'note': b['why']}
    from dim_resolver import resolve
    dims, _ev, src = resolve(o['mid'], o['name'], o['params'], R['dims_as'].get(role, role))
    ok = all(dims.get(k) for k in ('w', 'd', 'h'))
    return {'w': dims.get('w'), 'd': dims.get('d'), 'h': dims.get('h'), 'sw': None, 'sl': None,
            'ok': ok, 'note': '' if ok else f'размеры не полные ({src or "нет"})'}


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


def run() -> int:
    import category_map
    import load3 as L
    sql(open(os.path.join(HERE, '013-room-catalog.sql'), encoding='utf-8').read())
    R = rules()
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
    keep = [o for o in offers if o['mid'] not in skip]
    for o in keep:
        o['_d'] = dims_of(o, o['br_role'], R)
    for o, why in line_dims([(o['mid'], o['br_role'], o['_d']) for o in keep]).items():
        keep[o]['_d'].update({'ok': False, 'note': why})
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


def report() -> int:
    rows = sql(f"select role, count(*), count(*) filter (where footprint_ok) from room_catalog where {shown_where()} "
               "group by 1 order by 2 desc")
    for r in rows:
        print(f'  {r[0]}: показываем {r[1]}, с честным габаритом {r[2]}', flush=True)
    if not rows:
        print('WARN:room_catalog: каталог спальни пуст — вкладка демо покажет «скоро»', flush=True)
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
    ok('детская кровать — нет', rl(112923, '32', 'Кровать детская Соня') is None)
    ok('ветка «Детские кровати» не в списке — нет', rl(112923, '17', 'Кровать Мишка') is None)
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
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    if '--report' in sys.argv:
        sys.exit(report())
    if '--run' in sys.argv:
        sys.exit(run())
    print(__doc__)
