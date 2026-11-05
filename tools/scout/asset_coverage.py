"""Аудит покрытия ассетов комнат (room-pipeline-01 Б-4, T-20261105-42): у каких товаров комнаты есть меш и где он.

Только чтение. Товары — адаптер `catalog_items.items(room, with_assets=True)`; роли, стили, порог «в стиле», корзины размеров,
правила состава — профиль `room_profile.load(room)`; нужен ли меш — канон `asset_strategy.strategy` (hunyuan3d — нужен; ковёр
плоскостью, шторы/плед вырезкой — нет). Файлы мешей — `mesh_generations.path` на диске pakardev; прод — индекс
`/test/mesh-pilot10/mesh-index.json` (ключ «mid_eid»); банки наборов — по комнате (`--bank room=путь`).

Статус товара (один, по порядку):
  брак              — ревизия owner_reject (asset_revisions) или модель из `mesh_defect.names` правил состава комнаты;
  привязан          — у товара есть меш в карточке (`products.mesh_uri`, `mesh_bind`) и он годен (mesh_status ready);
  привязан_не_годен — меш в карточке есть, но mesh_status stale|rejected|quarantine;
  сирота            — glb на диске есть, а привязки нет (`mesh_bind` читает только products: меши комнат из `room_catalog` —
                      все такие, `room_mesh_jobs.py` их делает, карточка не видит); цветовой вариант без своего файла
                      берёт файл представителя семьи (`products.mesh_family_rep`, как `mesh_ready`) — отметка via_family;
  ревизия_без_файла — ревизия меша есть, файла model.glb нет;
  нет               — меша нет.
Ячейка — роль × стиль × корзина: стиль — каждый стиль профиля с баллом ≥ порога (товар бывает в нескольких; без оценки — «—»);
корзина — гостиная: полосы ширины по метражу (`size_buckets` профиля, товар бывает в нескольких); спальня (корзин в профиле нет) —
назначения, в слот которых товар годен (`compose_bedroom.gate` по полосе слота, как в подборе).

    python asset_coverage.py [--rooms living,bedroom] [--bank bedroom=ПУТЬ] [--prod URL|ФАЙЛ] [--out ПАПКА]
    python asset_coverage.py --selftest      # без базы, диска мешей и сети
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
STATUSES = ('привязан', 'привязан_не_годен', 'сирота', 'ревизия_без_файла', 'брак', 'нет')
PROD_IDX = 'https://remont-lab.online/test/mesh-pilot10/mesh-index.json'   # как mesh_publish.PROD_IDX (ADR-0243)
NO_STYLE, NO_BUCKET = '—', 'вне корзин'


# ---------------------------------------------------------------- чистые правила (селфтест)
def status(c, glb: dict, defect_rx=None) -> str:
    """c — CatalogItem с with_assets; glb — {sku: путь model.glb | None (ревизия есть, файла нет)}."""
    a = c.asset
    if a.get('defect') or (defect_rx and defect_rx.search(c.name or '')):
        return 'брак'
    if a.get('mesh_url'):
        return 'привязан' if a.get('mesh_status') == 'ready' else 'привязан_не_годен'
    if glb.get(c.offer_id):
        return 'сирота'
    if c.offer_id in glb or a.get('revision'):
        return 'ревизия_без_файла'
    return 'нет'


def styles_of(c, ids: list, thr: float) -> list:
    sc = c.style or {}
    got = [s for s in ids if isinstance(sc.get(s), (int, float)) and sc[s] >= thr]
    return got or [NO_STYLE]


def buckets_living(size_buckets: dict, role: str, w) -> list:
    """Полосы ширины роли по метражу (size-bands.json); [0,0] — у роли в этом метраже полосы нет."""
    if not w:
        return ['нет ширины']
    got = [b for b, roles in size_buckets.items() if isinstance(roles, dict)
           and (rng := roles.get(role)) and rng != [0, 0] and rng[0] <= w <= rng[1]]
    return got or [NO_BUCKET]


def buckets_slots(rules: dict, tol: tuple, role: str, it: dict, CB) -> list:
    """Назначения, в слот (или декор) которых товар годен — тем же `compose_bedroom.gate`, что подбор."""
    got = []
    for purpose, p in rules['purposes'].items():
        specs = [s for s in p.get('slots', []) if s.get('role') == role]
        d = (p.get('decor') or {}).get(role)
        if isinstance(d, dict) and d.get('band'):
            specs.append(dict(d, role=role))
        if any(CB.gate(it, s, CB.band_of(s, tol)) is None for s in specs if s.get('band')):
            got.append(purpose)
    return got or [NO_BUCKET]


def prod_key(sku: str) -> str:
    return sku.replace(':', '_')


def bank_skus(bank: list) -> dict:
    """{sku: 'items'|'alternates'} — позиция набора важнее альтернативы."""
    out: dict = {}

    def sku(v):
        if not isinstance(v, dict):
            return None
        if v.get('sid'):
            return v['sid']
        return f"{v['mid']}:{v['eid']}" if v.get('mid') is not None and v.get('eid') is not None else None
    for s in bank:
        for v in (s.get('items') or {}).values():
            k = sku(v)
            if k:
                out[k] = 'items'
        for vs in (s.get('alternates') or {}).values():
            for v in vs or []:
                k = sku(v)
                if k and k not in out:
                    out[k] = 'alternates'
    return out


def tally(rows: list) -> dict:
    """rows — [{status, cells[], in_prod, bank}] → сводки."""
    by = {s: 0 for s in STATUSES}
    cells: dict = {}
    prod = {s: 0 for s in STATUSES}
    bank = {'items': {s: 0 for s in STATUSES}, 'alternates': {s: 0 for s in STATUSES}}
    for r in rows:
        by[r['status']] += 1
        prod[r['status']] += bool(r['in_prod'])
        if r['bank']:
            bank[r['bank']][r['status']] += 1
        for cell in r['cells']:
            cells.setdefault(cell, {s: 0 for s in STATUSES})[r['status']] += 1
    return {'by_status': by, 'on_prod': prod, 'in_bank': bank, 'cells': dict(sorted(cells.items()))}


# ---------------------------------------------------------------- данные
def mesh_files() -> tuple:
    """(glb, семья): glb — {sku: путь model.glb, если файл есть; None — поколение/ревизия есть, файла нет} по
    `mesh_generations` и ревизиям; семья — {вариант: представитель} из `products.mesh_family_rep` (один меш на модель,
    05.09: готовность варианта `mesh_ready` берёт у представителя, своего файла у варианта нет)."""
    from mesh_queue import db
    out: dict = {}
    for r in db("select sku, path from mesh_generations order by created"):
        if len(r) == 2 and r[0]:
            p = os.path.join(r[1] or '', 'model.glb')
            out[r[0]] = p if os.path.isfile(p) else out.get(r[0])
    for r in db("select distinct sku from asset_revisions where status in ('accepted','generated')"):
        if r and r[0]:
            out.setdefault(r[0], None)
    fam = {r[0]: r[1] for r in db("select shop_mid||':'||external_id, mesh_family_rep from products "
                                  "where mesh_family_rep is not null and mesh_family_rep <> shop_mid||':'||external_id")
           if len(r) == 2}
    return out, fam


def with_family(glb: dict, fam: dict) -> tuple:
    """Варианту без своего файла — файл представителя. → (glb с вариантами, множество sku «через семью»)."""
    eff, via = dict(glb), set()
    for v, rep in fam.items():
        if not glb.get(v) and glb.get(rep):
            eff[v] = glb[rep]
            via.add(v)
    return eff, via


def prod_index(src: str) -> tuple:
    """(множество ключей «mid_eid» | None, откуда/почему нет)."""
    try:
        if re.match(r'https?://', src):
            with urllib.request.urlopen(src, timeout=60) as r:
                d = json.load(r)
        else:
            d = json.load(open(src, encoding='utf-8'))
        return set(d), src
    except Exception as e:  # noqa: BLE001 — нет прода: отчёт без столбца, с причиной
        return None, f'{src}: {str(e)[:200]}'


def default_bank(room: str) -> str:
    import bank_paths as BP
    return BP.LIVE if room == 'living' else os.path.join(HERE, BP.ROOM_BANKS.get(room, f'sets-{room}') + '.json')


def audit_room(room: str, glb: dict, prod: set | None, bank_path: str | None, via: set = frozenset()) -> dict:
    import asset_strategy as AS
    import catalog_items as CI
    import room_profile as RP
    P = RP.load(room)
    thr = float(P['style']['in_style_min'])   # обязателен по схеме профиля (T-20261105-43)
    ids = list(P['style']['ids'])
    rules = (P['composer'] or {}).get('rules')
    drx = (rules or {}).get('mesh_defect', {}).get('names')
    drx = re.compile(drx, re.I) if drx else None
    tol = tuple(P['tolerance'])
    bank = None
    if bank_path and os.path.exists(bank_path):
        bank = bank_skus(json.load(open(bank_path, encoding='utf-8')))
    got = CI.items(room, with_assets=True)
    CB = None
    dicts = {}
    if not P.get('size_buckets') and rules:
        import compose_bedroom as CB
        cat, decor = CB.to_dicts(got)
        dicts = {(f"{d['mid']}:{d['eid']}", d['role']): d for d in cat + decor}
    rows, skipped, orphans = [], {}, []
    for c in got:
        for role in c.roles:
            if AS.strategy(role) != 'hunyuan3d':
                skipped[role] = skipped.get(role, 0) + 1
                continue
            st = status(c, glb, drx)
            if CB is not None:
                bk = buckets_slots(rules, tol, role, dicts.get((c.offer_id, role)) or {}, CB)
            else:
                bk = buckets_living(P.get('size_buckets') or {}, role, c.dims.get('w'))
            cells = [f'{role}|{s}|{b}' for s in styles_of(c, ids, thr) for b in bk]
            inp = None if prod is None else prod_key(c.offer_id) in prod
            inb = (bank or {}).get(c.offer_id)
            rows.append({'status': st, 'cells': cells, 'in_prod': inp, 'bank': inb})
            if st == 'сирота':
                orphans.append({'sku': c.offer_id, 'role': role, 'name': c.name, 'origin': c.origin, 'glb': glb[c.offer_id],
                                'via_family': c.offer_id in via, 'ready': c.asset.get('revision') == 'ready',
                                'on_prod': inp, 'bank': inb})
    t = tally(rows)
    seen = {c.offer_id for c in got}
    gone = sorted(k for k in (bank or {}) if k not in seen)
    by_origin: dict = {}
    for o in orphans:
        by_origin[o['origin']] = by_origin.get(o['origin'], 0) + 1
    return dict(room=room, profile_version=RP.raw(room)['profile_version'], items=len(got), mesh_roles_rows=len(rows),
                no_mesh_by_strategy=skipped, in_style_min=thr, styles=ids,
                buckets='size_buckets профиля' if CB is None else 'назначения: годен в слот (compose_bedroom.gate)',
                bank={'path': bank_path, 'found': bank is not None, 'skus': len(bank or {}), 'not_in_catalog': len(gone),
                      'not_in_catalog_items': sum(bank[k] == 'items' for k in gone), 'not_in_catalog_sample': gone[:20],
                      '_why': 'sku банка, которых нет в выдаче адаптера сейчас (нет в наличии, снят, вне ролей) — статус не считается'},
                prod_checked=prod is not None, orphans_n=len(orphans), orphans_by_origin=by_origin,
                orphans_via_family=sum(o['via_family'] for o in orphans), **t,
                orphans=sorted(orphans, key=lambda o: (o['bank'] is None, o['role'], o['sku'])))


def outside(glb: dict, rooms: list, skus_seen: set) -> dict:
    """Файлы мешей у товаров, которых нет ни в одной комнате адаптера (снят с показа, не в наличии, вне ролей)."""
    lost = sorted(s for s, p in glb.items() if p and s not in skus_seen)
    return {'n': len(lost), 'sample': lost[:30], '_why': f'sku с model.glb, которых нет в выдаче адаптера комнат {rooms}'}


def md(rep: dict) -> str:
    L = [f"# Покрытие ассетов комнат — {rep['at']}", '',
         f"Прод: {'индекс прочитан' if rep['prod_ok'] else 'НЕ прочитан'} ({rep['prod_src']}); файлов мешей на диске: {rep['glb_files']}.", '',
         '| комната | товаров (мешевые роли) | привязан | не годен | **сирота** | без файла | брак | нет | на проде |',
         '|---|---|---|---|---|---|---|---|---|']
    for r in rep['rooms']:
        b = r['by_status']
        L.append(f"| {r['room']} | {r['mesh_roles_rows']} | {b['привязан']} | {b['привязан_не_годен']} | **{b['сирота']}** | "
                 f"{b['ревизия_без_файла']} | {b['брак']} | {b['нет']} | {sum(r['on_prod'].values()) if r['prod_checked'] else '—'} |")
    L += ['', 'Банки наборов (позиции / альтернативы), сирот:']
    for r in rep['rooms']:
        bk = r['bank']
        L.append(f"- {r['room']}: " + (f"{bk['path']} — сирот в позициях {r['in_bank']['items']['сирота']}, в альтернативах "
                                        f"{r['in_bank']['alternates']['сирота']}, «нет меша» в позициях {r['in_bank']['items']['нет']}; "
                                        f"товаров банка нет в каталоге сейчас {bk['not_in_catalog']} из {bk['skus']} "
                                        f"(в позициях {bk['not_in_catalog_items']})"
                                        if bk['found'] else f"банка нет ({bk['path']})"))
    L += ['', f"Сироты вне комнат (glb есть, товара нет в выдаче адаптера): {rep['outside_rooms']['n']}.", '',
          'Сироты по ролям (в скобках — из них вариант семьи: файл у представителя, `products.mesh_family_rep`):']
    for r in rep['rooms']:
        roles: dict = {}
        for o in r['orphans']:
            roles[o['role']] = roles.get(o['role'], 0) + 1
        L.append(f"- {r['room']}: " + (', '.join(f'{k} {v}' for k, v in sorted(roles.items(), key=lambda kv: -kv[1])) or 'нет')
                 + f" (семья {r['orphans_via_family']})")
    L += ['', 'Ячейки «роль × стиль × корзина» и списки сирот — в JSON рядом.']
    return '\n'.join(L) + '\n'


def run(rooms: list, banks: dict, prod_src: str, out: str) -> dict:
    t = time.time()
    glb, fam = mesh_files()
    eff, via = with_family(glb, fam)
    prod, why = prod_index(prod_src)
    reps = [audit_room(r, eff, prod, banks.get(r, default_bank(r)), via) for r in rooms]
    import catalog_items as CI
    seen = {c.offer_id for r in rooms for c in CI.items(r)}
    rep = {'at': time.strftime('%Y-%m-%d %H:%M'), 'seconds': None, 'prod_ok': prod is not None, 'prod_src': why,
           'prod_keys': len(prod or ()), 'glb_files': sum(1 for p in glb.values() if p), 'rooms': reps,
           'outside_rooms': outside(glb, rooms, seen)}
    rep['seconds'] = round(time.time() - t, 1)
    os.makedirs(out, exist_ok=True)
    json.dump(rep, open(os.path.join(out, 'asset-coverage.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    open(os.path.join(out, 'asset-coverage.md'), 'w', encoding='utf-8').write(md(rep))
    return rep


# ---------------------------------------------------------------- селфтест
def _selftest() -> int:
    bad = 0

    def ok(name, cond):
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += not cond
    from types import SimpleNamespace as NS

    def it(sku, name='Кровать Нордик', **asset):
        a = {'mesh_status': None, 'mesh_url': None, 'revision': None, 'defect': False}
        a.update(asset)
        return NS(offer_id=sku, name=name, asset=a, style={'сканди': 8, 'лофт': 5}, dims={'w': 200})
    glb = {'1:a': '/m/1_a/model.glb', '1:b': None}
    rx = re.compile('Стелла', re.I)
    ok('привязан и годен', status(it('9:x', mesh_url='file://m', mesh_status='ready'), glb) == 'привязан')
    ok('привязан, но stale — не годен', status(it('9:x', mesh_url='file://m', mesh_status='stale'), glb) == 'привязан_не_годен')
    ok('glb есть, привязки нет — сирота', status(it('1:a'), glb) == 'сирота')
    ok('ревизия без файла', status(it('1:b'), glb) == 'ревизия_без_файла' and status(it('5:q', revision='generated'), {}) == 'ревизия_без_файла')
    ok('брак: owner_reject и модель из списка — раньше привязки', status(it('1:a', defect=True), glb) == 'брак'
       and status(it('9:x', name='Кровать Стелла 160', mesh_url='u', mesh_status='ready'), glb, rx) == 'брак')
    ok('нет меша', status(it('7:z'), glb) == 'нет')
    ok('стиль: все стили ≥ порога; без оценки — «—»', styles_of(it('1:a'), ['сканди', 'лофт'], 6.6) == ['сканди']
       and styles_of(NS(style=None), ['сканди'], 6.6) == [NO_STYLE])
    sb = {'14-16': {'диван': [160, 230], 'стенка': [0, 0]}, '17-20': {'диван': [180, 250]}}
    ok('корзины гостиной: ширина в нескольких полосах; [0,0] — нет полосы',
       buckets_living(sb, 'диван', 200) == ['14-16', '17-20'] and buckets_living(sb, 'стенка', 220) == [NO_BUCKET]
       and buckets_living(sb, 'диван', None) == ['нет ширины'])
    eff, via = with_family({'1:a': '/m/1_a/model.glb', '4:r': None}, {'1:v': '1:a', '4:v': '4:r', '1:a': '1:a'})
    ok('семья: вариант берёт файл представителя; у представителя без файла — нет',
       eff.get('1:v') == '/m/1_a/model.glb' and via == {'1:v'} and status(it('1:v'), eff) == 'сирота' and '4:v' not in eff)
    ok('ключ прода', prod_key('112923:15') == '112923_15')
    bank = [{'items': {'кровать': {'sid': '1:a'}, 'диван': {'mid': 2, 'eid': 'b'}},
             'alternates': {'кровать': [{'sid': '1:a'}, {'sid': '3:c'}]}}]
    ok('банк: позиция важнее альтернативы', bank_skus(bank) == {'1:a': 'items', '2:b': 'items', '3:c': 'alternates'})
    T = tally([{'status': 'сирота', 'cells': ['кровать|сканди|couple', 'кровать|сканди|guest'], 'in_prod': False, 'bank': 'items'},
               {'status': 'нет', 'cells': ['кровать|сканди|couple'], 'in_prod': None, 'bank': None}])
    ok('сводка: статусы, ячейки, прод, банк', T['by_status']['сирота'] == 1 and T['cells']['кровать|сканди|couple']['нет'] == 1
       and T['cells']['кровать|сканди|guest']['сирота'] == 1 and T['on_prod']['сирота'] == 0 and T['in_bank']['items']['сирота'] == 1)
    import compose_bedroom as CB
    import room_profile as RP
    R = RP.load('bedroom')['composer']['rules']
    bed = {'role': 'кровать', 'w': 176, 'd': 214, 'h': 100, 'footprint_ok': True, 'sleep_w': 160}
    ok('корзины спальни: кровать 160 — пара, не одиночная', buckets_slots(R, (0.8, 1.1), 'кровать', bed, CB) == ['couple'])
    ok('корзины спальни: без размеров — вне корзин', buckets_slots(R, (0.8, 1.1), 'шкаф', {'role': 'шкаф'}, CB) == [NO_BUCKET])
    ok('прод: нет индекса — None с причиной', prod_index('/nonexistent/x.json')[0] is None)
    print('selftest:', 'OK' if not bad else f'{bad} FAIL')
    return 1 if bad else 0


def main(argv: list) -> int:
    if '--selftest' in argv:
        return _selftest()
    import catalog_items as CI
    rooms = argv[argv.index('--rooms') + 1].split(',') if '--rooms' in argv else list(CI.ROOM_TYPES)
    for r in rooms:
        CI.check_room(r)
    banks = dict(a.split('=', 1) for i, a in enumerate(argv) if i and argv[i - 1] == '--bank')
    prod = argv[argv.index('--prod') + 1] if '--prod' in argv else PROD_IDX
    out = argv[argv.index('--out') + 1] if '--out' in argv else os.path.expanduser(f'~/remlab-logs/asset-coverage-{time.strftime("%m%d-%H%M")}')
    rep = run(rooms, banks, prod, out)
    print(md(rep))
    print(f'JSON и md: {out}  ({rep["seconds"]} с)')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
