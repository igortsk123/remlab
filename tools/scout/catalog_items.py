"""Адаптер каталога комнат (room-pipeline-01 Б-1, T-20261105-39): `items(room_type, roles=None) -> list[CatalogItem]`.

Единственное место, где сборщики комнат читают `products` (каталог гостиной и декор) и `room_catalog` (мебель прочих комнат,
ADR-0330). Только SELECT: представления БД нет (миграция — слово владельца), поэтому два запроса живут здесь, в коде.
Потребители сейчас: `compose_bedroom.py` (спальня) и тень гостиной `catalog_items_shadow.py --room living` — сверка с тем, что
читает `compose2.py` (сама гостиная на адаптер НЕ переведена до доказанного паритета, план room-pipeline-01). Перевод обрезки,
спроса и привязки мешей — волна В.

Тип комнаты — данные: `_sources(room_type)` говорит, из каких таблиц и какие роли берёт комната; роли — из профиля
комнаты (`room_profile.load`, поле `source` у роли; T-20261105-43), своего списка у адаптера нет. Неизвестный тип (кухня,
прихожая — пока нет профиля) и неизвестная роль закрытого списка — ошибка ValueError, а не «гостиная по умолчанию».
Товар в двух ролях — один `CatalogItem` с `roles` в порядке появления (поля — первой строки).

    python catalog_items.py --selftest          # без базы
    python catalog_items.py --room bedroom      # счёт по ролям и источникам (база DEV)
"""
from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = os.path.join(HERE, 'rules', 'catalog-item.schema.json')
STYLE_SCORES = {'bedroom': ('BEDROOM_STYLE_SCORES', os.path.join(HERE, 'style-scores-bedroom.json'))}
ROOM_TYPES = ('living', 'bedroom')   # профиль есть только у этих; kitchen/hall — после RoomProfile (волна Б)
ORIGINS = ('products', 'room_catalog')
PARAM_KEYS = ('Материал', 'Назначение', 'Тип', 'Регулируемая высота')   # то, что подбор гостиной берёт из params
FS, RS, NUL = '\x1f', '\x1e', '\x1d'   # поле, запись, NULL: перевод строки в названии не рвёт запись


@dataclasses.dataclass(frozen=True)
class CatalogItem:
    offer_id: str          # «магазин:артикул» (shop_mid:external_id) — тот же ключ, что sku в asset_revisions
    origin: str            # products | room_catalog
    room_type: str
    roles: tuple
    mid: int
    eid: str
    name: str | None
    shop: str | None
    brand: str | None
    price: float | None    # руб.
    in_stock: bool | None  # room_catalog: None (наличие — «оффер в свежем фиде», missing_runs)
    url: str | None        # ссылка фида как есть
    url_direct: str | None  # products: прямая ссылка магазина (direct_url или goto= из партнёрской) — её берёт гостиная
    dims: dict             # w,d,h,len,dia,sleep_w,sleep_l (см|None), source, footprint_ok, note, h_evidence{source,cm,drop_min}
    photo: dict            # url, url_hd, best (hd, иначе обычное), alive, revision (None — волна В, photo_hash)
    style: dict | None     # баллы стилей: products — product_style_scores; room_catalog — style-scores-<room>.json по семейству
    asset: dict            # mesh_status, mesh_url (products), revision ready|generated|None, defect (with_assets; иначе None)
    params: dict           # PARAM_KEYS
    flags: dict            # признаки по описанию товара (desc_flags), сам текст не тянем
    family: str | None     # «магазин|модель без размера и цвета» (room_catalog.family) — ключ оценки стиля семейства

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d['roles'] = list(self.roles)
        return d


# ---------------------------------------------------------------- профиль комнаты (источники)
# Отбор и порядок источника по комнате (preset `products_sql` / `room_catalog_sql`); РОЛИ — только из профиля комнаты.
PRESETS = {'living': (('products', 'living'),),
           'bedroom': (('room_catalog', 'bedroom'), ('products', 'decor'))}   # декор спальни — каталог гостиной (onb-06 п.1)


def check_room(room_type: str) -> None:
    if room_type not in ROOM_TYPES:
        raise ValueError(f'catalog_items: неизвестный тип комнаты {room_type!r}; профиль есть у {", ".join(ROOM_TYPES)}')


def profile_roles(room_type: str, profile: dict | None = None) -> dict:
    """{источник: [роли]} из `roles` профиля комнаты (`room_profile.load`, поле `source`), порядок профиля (T-20261105-43:
    единственный список ролей комнаты — профиль; адаптер своего не держит)."""
    if profile is None:
        import room_profile as RP
        profile = RP.load(room_type)
    out: dict = {}
    for r, v in profile['roles'].items():
        out.setdefault(v['source'], []).append(r)
    return out


def _sources(room_type: str, profile: dict | None = None) -> list:
    """[(origin, preset, roles)] — порядок источников = порядок выдачи; роли из профиля (`profile_roles`). Источник роли
    профиля, которого у комнаты нет в PRESETS, — ошибка (иначе роль молча пропала бы из выдачи)."""
    check_room(room_type)
    by = profile_roles(room_type, profile)
    have = [o for o, _ in PRESETS[room_type]]
    if set(by) - set(have):
        raise ValueError(f'catalog_items: у комнаты {room_type!r} роли из источника {sorted(set(by) - set(have))}, '
                         f'а читаются только {have}')
    return [(o, preset, by.get(o, [])) for o, preset in PRESETS[room_type]]


# ---------------------------------------------------------------- база
def _psql() -> list:
    return ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', os.environ.get('REMLAB_DEVDB_NAME', 'remlab'),
            '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', FS, '-R', RS, '-P', 'null=' + NUL]


def parse(out: str) -> list:
    """Вывод psql (-R RS, null=NUL) → строки; NULL → None. Перевод строки внутри значения сохраняется."""
    if out.endswith('\n'):
        out = out[:-1]
    if not out:
        return []
    return [[None if v == NUL else v for v in rec.split(FS)] for rec in out.split(RS)]


def fetch(sql: str) -> list:
    r = subprocess.run(_psql(), input=sql, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'catalog_items: SQL упал: {r.stderr[:400]}')
    return parse(r.stdout)


def _width(r: list, n: int) -> list:
    if len(r) != n:
        raise RuntimeError(f'catalog_items: строка из {len(r)} полей, ждали {n}: {r[:3]}')
    return r


def _lit(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def _f(v):
    return None if v is None or v == '' else float(v)


def _b(v):
    return None if v is None else v == 't'


PRODUCT_COLS = (
    "p.cat_role, p.shop_mid, p.external_id, p.name, p.shop, p.brand, p.price_rub, p.in_stock, "
    "p.w_cm, p.d_cm, p.h_cm, p.len_cm, p.dia_cm, p.dims_source, "
    "p.dims_evidence->'h'->>'source', p.dims_evidence->'h'->>'cm', p.dims_evidence->'h'->>'drop_min', "
    "p.image_url, p.image_url_hd, p.photo_alive, p.url, "
    "coalesce(p.direct_url, replace(replace(replace(substring(p.url from 'goto=([^&]+)'),'%3A',':'),'%2F','/'),'%3F','?')), "
    + ', '.join(f"p.params->>{_lit(k)}" for k in PARAM_KEYS)
    + ", p.mesh_status, p.mesh_uri, ps.scores::text")
N_PRODUCT = 29   # столбцов PRODUCT_COLS; дальше — признаки desc_flags


def products_sql(preset: str, roles: list | None, flags: dict) -> str:
    """Один SELECT по products на все комнаты; preset — отбор и порядок источника:
    living — то, что берёт подбор гостиной (`compose2.py`: роль фида, цена, фото, в наличии, не категория без размеров;
    порядок цена → магазин → артикул); decor — декор в чужой комнате (как прежний `compose_bedroom.load_decor`: ещё фото
    живо и есть оценка стиля; порядок магазин → артикул)."""
    fl = ''.join(f", (coalesce(p.description,'') ~* {_lit(v)})" if v else ', false' for v in flags.values())
    where = ["p.cat_role is not null", "p.price_rub is not null", "p.image_url is not null", "p.in_stock"]
    if preset == 'living':
        import dimless
        where.append(dimless.exclude_sql('p'))
        order = 'p.price_rub, p.shop_mid, p.external_id'
    elif preset == 'decor':
        where += ["coalesce(p.photo_alive, true)", "ps.shop_mid is not null"]
        order = 'p.shop_mid, p.external_id'
    else:
        raise ValueError(f'catalog_items: неизвестный отбор products {preset!r}')
    if roles is not None:
        where.append('p.cat_role in (' + ','.join(_lit(r) for r in roles) + ')')
    return (f"select {PRODUCT_COLS}{fl} from products p left join product_style_scores ps using (shop_mid, external_id) "
            f"where {' and '.join(where)} order by {order}")


def product_item(r: list, room_type: str, flag_names: list) -> CatalogItem:
    return CatalogItem(
        offer_id=f'{r[1]}:{r[2]}', origin='products', room_type=room_type, roles=(r[0],), mid=int(r[1]), eid=r[2],
        name=r[3], shop=r[4], brand=r[5], price=_f(r[6]), in_stock=_b(r[7]), url=r[20], url_direct=r[21],
        dims={'w': _f(r[8]), 'd': _f(r[9]), 'h': _f(r[10]), 'len': _f(r[11]), 'dia': _f(r[12]), 'sleep_w': None,
              'sleep_l': None, 'source': r[13], 'footprint_ok': None, 'note': None,
              'h_evidence': {'source': r[14], 'cm': r[15], 'drop_min': r[16]}},
        photo={'url': r[17], 'url_hd': r[18], 'best': r[18] if r[18] is not None else r[17], 'alive': _b(r[19]),
               'revision': None},
        style=json.loads(r[28]) if r[28] is not None else None,
        asset={'mesh_status': r[26], 'mesh_url': r[27], 'revision': None, 'defect': None},
        params={k: r[22 + i] for i, k in enumerate(PARAM_KEYS)},
        flags={k: r[N_PRODUCT + i] == 't' for i, k in enumerate(flag_names)}, family=None)


ROOM_CATALOG_COLS = ("role, shop_mid, external_id, name, shop, brand, price_rub, w_cm, d_cm, h_cm, sleep_w_cm, sleep_l_cm, "
                     "footprint_ok, dims_note, image_url, image_url_hd, coalesce(image_url_hd, image_url), url")
N_ROOM = 18


def room_catalog_sql(room_type: str, roles: list) -> str:
    """Мебель комнаты: показ (`room_catalog.shown_where`: цена, фото, оффер в свежем фиде) + роли профиля + не детское
    (когда есть столбец kids). Порядок — магазин → артикул (как прежний `compose_bedroom.load_catalog`)."""
    import room_catalog as RC
    if room_type != RC.ROOM:
        raise ValueError(f'catalog_items: room_catalog знает только {RC.ROOM!r}, не {room_type!r}')
    R = RC.rules()
    return (f"select {ROOM_CATALOG_COLS} from room_catalog where {RC.shown_where(R)} and role in ("
            + ','.join(_lit(r) for r in roles) + f"){RC.kids_where(R)} order by shop_mid, external_id")


def room_catalog_items(rows: list, room_type: str) -> list:
    """Строки room_catalog → CatalogItem. Детское в общей роли (`kids_shared`) — вне показа взрослой спальни, как прежде;
    детская (child:*) — PURPOSE_PENDING, её отбор появится с её профилем. Стиль — оценка семейства у любого его члена."""
    import room_catalog as RC
    if not rows:
        return []
    R = RC.rules()
    env, default = STYLE_SCORES[room_type]
    path = os.environ.get(env) or default
    if not os.path.exists(path):
        raise SystemExit(f'нет {path} — стиль спальни (style_score.py --source room_catalog); в worktree задать {env}')
    ss = json.load(open(path, encoding='utf-8'))
    out, fams = [], {}
    for r in rows:
        if RC.child_only(_width(r, N_ROOM)[0], r[3] or '', R):
            continue
        fam = f'{r[4] or ""}|{RC.family(r[3] or "")}'
        it = dict(
            offer_id=f'{r[1]}:{r[2]}', origin='room_catalog', room_type=room_type, roles=(r[0],), mid=int(r[1]), eid=r[2],
            name=r[3], shop=r[4], brand=r[5], price=_f(r[6]), in_stock=None, url=r[17], url_direct=None,
            dims={'w': _f(r[7]), 'd': _f(r[8]), 'h': _f(r[9]), 'len': None, 'dia': None, 'sleep_w': _f(r[10]),
                  'sleep_l': _f(r[11]), 'source': None, 'footprint_ok': _b(r[12]), 'note': r[13],
                  'h_evidence': {'source': None, 'cm': None, 'drop_min': None}},
            photo={'url': r[14], 'url_hd': r[15], 'best': r[16], 'alive': None, 'revision': None},
            style=None, asset={'mesh_status': None, 'mesh_url': None, 'revision': None, 'defect': None},
            params={}, flags={}, family=fam)
        fams.setdefault(fam, []).append(it)
        out.append(it)
    for members in fams.values():
        sc = next((ss[_skey(m['mid'], m['eid'])] for m in members if _skey(m['mid'], m['eid']) in ss), None)
        for m in members:
            m['style'] = sc
    return [CatalogItem(**it) for it in out]


def _skey(mid, eid) -> str:
    """Ключ кэша оценок стиля (`style_score.py`; прежний `compose_bedroom._key`)."""
    import re
    return f"{mid}-{re.sub(r'[^A-Za-z0-9]', '_', str(eid))[:40]}"


# ---------------------------------------------------------------- меши
def mesh_state() -> tuple:
    """(готовые, сгенерированные, брак) — множества sku: готов — `mesh_ready.mesh_ready_raw` (принят + ориентация решена);
    сгенерирован — ревизия меша есть (accepted|generated, не legacy-local); брак — ревизия owner_reject."""
    from mesh_queue import db
    from mesh_ready import mesh_ready_raw
    ready = mesh_ready_raw()
    gen = {r[0] for r in db("select distinct sku from asset_revisions where status in ('accepted','generated') "
                            "and origin <> 'legacy-local'") if r and r[0]}
    rejected = {r[0] for r in db("select distinct sku from asset_revisions where status = 'owner_reject'") if r and r[0]}
    return ready, gen, rejected


def with_mesh(items: list, state: tuple) -> list:
    ready, gen, rejected = state
    return [dataclasses.replace(c, asset=dict(c.asset, revision='ready' if c.offer_id in ready else
                                              ('generated' if c.offer_id in gen else None),
                                              defect=c.offer_id in rejected)) for c in items]


# ---------------------------------------------------------------- адаптер
def merge(items: list) -> list:
    """Один товар — один CatalogItem: повтор offer_id добавляет роль (порядок появления), поля — первой строки."""
    out, at = [], {}
    for c in items:
        i = at.get(c.offer_id)
        if i is None:
            at[c.offer_id] = len(out)
            out.append(c)
        elif not set(c.roles) <= set(out[i].roles):
            out[i] = dataclasses.replace(out[i], roles=out[i].roles + tuple(r for r in c.roles if r not in out[i].roles))
    return out


BINDING_ORIGINS = ('room_catalog',)   # чьим товарам меш даёт привязка offer_asset_binding (T-20261105-45); products — свои поля
BINDING_KEYS = ('ready', 'asset_id', 'mesh_id', 'representative_offer_id', 'via_family', 'generation_key', 'revision_key',
                'source_sha', 'glb_sha', 'orientation', 'passport_status', 'gate_status', 'published', 'capabilities', 'reasons',
                'warnings', 'binding_snapshot')


def bound_asset(asset: dict, row: dict | None, why: str) -> dict:
    """Наложение привязки на asset товара. row — строка offer_asset_binding (room_bindings.load_db) или None:
    why пусто — товара в привязке нет (меша нет ни своего, ни семьи) → mesh_status none; иначе таблица не читается → unbound."""
    if row is None:
        st = 'unbound' if why else 'none'
        return dict(asset, mesh_status=st, mesh_url=None, ready=False, asset_id=None, mesh_id=None, representative_offer_id=None,
                    via_family=False, generation_key=None, revision_key=None, source_sha=None, glb_sha=None, orientation=None,
                    passport_status=None, gate_status=None, published=False, capabilities=None,
                    reasons=[why] if why else ['no_asset'], warnings=[], binding_snapshot=None)
    ready = row['status'] == 'ready'
    aid = row['asset_id']
    return dict(asset, mesh_status=row['status'], mesh_url=('file://' + row['local_path']) if ready and row['local_path'] else None,
                ready=ready, asset_id=aid, mesh_id=row['mesh_id'], representative_offer_id=row['representative_offer_id'],
                via_family=row['via_family'], generation_key=row['generation_key'], revision_key=row['revision_key'],
                source_sha=row['source_sha'], glb_sha=aid.split(':', 1)[1] if aid else None, orientation=row['orientation'],
                passport_status=(row['passport'] or {}).get('status'), gate_status='pass' if row['local_3d'] else 'fail',
                published=row['published_3d'],
                capabilities={k: row[k] for k in ('solver', 'local_3d', 'appearance', 'published_3d')},
                reasons=list(row['reasons'] or []), warnings=list(row['warnings'] or []), binding_snapshot=row['snapshot_id'][:16])


def with_binding(items: list, room_type: str, get=None) -> list:
    """Меши товаров room_catalog — из таблицы привязки ОДНИМ запросом на вызов. Гостиная и товары products — как были
    (их меш — поля products, Codex: «living/product rows retain their current DB fields»). Нет таблицы / пусто / чужая
    политика — каждому товару room_catalog mesh_status unbound с причиной, без исключения."""
    if room_type == 'living' or not any(c.origin in BINDING_ORIGINS for c in items):
        return items
    import room_bindings as RB
    rows, why = RB.load_db(get or fetch)
    return [dataclasses.replace(c, asset=bound_asset(c.asset, (rows or {}).get(c.offer_id), why))
            if c.origin in BINDING_ORIGINS else c for c in items]


def items(room_type: str, roles=None, *, desc_flags: dict | None = None, with_assets: bool = False,
          _fetch=None, _mesh=None, _bindings=None) -> list:
    """Товары комнаты. roles: None — все роли профиля; [] — пусто без запроса; роль вне закрытого списка профиля — ValueError.
    desc_flags {имя: регекс} — признаки по products.description (регекс пустой — False). with_assets — состояние меша."""
    srcs = _sources(room_type)
    if roles is not None:
        roles = list(roles)
        if not roles:
            return []
        known = {r for _, _, rs in srcs for r in rs}
        bad = [r for r in roles if r not in known]
        if bad:
            raise ValueError(f'catalog_items: у комнаты {room_type!r} нет ролей {bad}; есть {sorted(known)}')
    flags = dict(desc_flags or {})
    get = _fetch or fetch
    out = []
    for origin, preset, rs in srcs:
        want = rs if roles is None else [r for r in roles if r in rs]
        if not want:
            continue
        if origin == 'room_catalog':
            out += room_catalog_items(get(room_catalog_sql(preset, want)), room_type)
        else:
            names = list(flags)
            out += [product_item(_width(r, N_PRODUCT + len(names)), room_type, names)
                    for r in get(products_sql(preset, want, flags))]
    out = merge(out)
    if not with_assets:
        return out
    return with_binding(with_mesh(out, _mesh or mesh_state()), room_type, _bindings)


# ---------------------------------------------------------------- схема (без jsonschema: типы верхнего уровня и ключи)
def schema_errors(d: dict, schema: dict | None = None) -> list:
    S = schema or json.load(open(SCHEMA, encoding='utf-8'))
    T = {'string': str, 'integer': int, 'number': (int, float), 'boolean': bool, 'object': dict, 'array': list,
         'null': type(None)}
    errs = [f'нет поля {k}' for k in S['required'] if k not in d]
    errs += [f'лишнее поле {k}' for k in d if k not in S['properties']]
    for k, p in S['properties'].items():
        if k not in d:
            continue
        ts = p['type'] if isinstance(p['type'], list) else [p['type']]
        v = d[k]
        if not any(isinstance(v, T[t]) and not (t in ('integer', 'number') and isinstance(v, bool)) for t in ts):
            errs.append(f'{k}: {type(v).__name__} не {ts}')
        if 'enum' in p and v not in p['enum']:
            errs.append(f'{k}: {v!r} не из {p["enum"]}')
        for sub in p.get('required', []):
            if isinstance(v, dict) and sub not in v:
                errs.append(f'{k}.{sub}: нет')
        for sub, q in (p.get('properties') or {}).items():      # вложенные поля (asset привязки) — тип и enum
            if not isinstance(v, dict) or sub not in v:
                continue
            qs = q['type'] if isinstance(q.get('type'), list) else [q.get('type', 'null')]
            w = v[sub]
            if q.get('type') and not any(isinstance(w, T[t]) and not (t in ('integer', 'number') and isinstance(w, bool)) for t in qs):
                errs.append(f'{k}.{sub}: {type(w).__name__} не {qs}')
            if 'enum' in q and w not in q['enum']:
                errs.append(f'{k}.{sub}: {w!r} не из {q["enum"]}')
    return errs


# ---------------------------------------------------------------- селфтест (без базы)
def _selftest() -> int:
    bad = 0

    def ok(name, cond):
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += not cond

    for rt in ('kitchen', 'hall', 'garage', '', None):
        try:
            items(rt, _fetch=lambda s: [])
            ok(f'тип комнаты {rt!r} — ошибка', False)
        except ValueError:
            ok(f'тип комнаты {rt!r} — ошибка (не гостиная по умолчанию)', True)
    calls = []
    ok('пустой список ролей — пусто, без запроса', items('living', [], _fetch=lambda s: calls.append(s) or []) == [] and not calls)
    try:
        items('bedroom', ['кровать', 'диван'], _fetch=lambda s: [])
        ok('роль вне профиля спальни — ошибка', False)
    except ValueError as e:
        ok('роль вне профиля спальни — ошибка', 'диван' in str(e))
    ok('роль профиля без товаров — пусто, не ошибка', items('bedroom', ['кровать'], _fetch=lambda s: []) == [])
    try:
        items('living', ['шкаф'], _fetch=lambda s: [])
        ok('гостиная — закрытый список профиля: шкаф (есть в фиде, нет в профиле) — ошибка', False)
    except ValueError:
        ok('гостиная — закрытый список профиля: шкаф (есть в фиде, нет в профиле) — ошибка', True)
    import room_profile as RP
    Pb = RP.load('bedroom')
    ok('роли адаптера = роли профиля (источник один)',
       all({r for _, _, rs in _sources(t) for r in rs} == set(RP.load(t)['roles']) for t in ROOM_TYPES))
    Pb['roles']['пуф'] = {'source': 'room_catalog'}
    ok('правка профиля меняет выдачу адаптера', 'пуф' in dict((o, rs) for o, _, rs in _sources('bedroom', Pb))['room_catalog'])
    sqls = []
    items('living', _fetch=lambda s: sqls.append(s) or [])
    ok('гостиная: запрос с ролями профиля (не весь фид)', len(sqls) == 1 and "p.cat_role in ('диван'" in sqls[0]
       and "'шкаф'" not in sqls[0])
    Pb['roles']['кухня'] = {'source': 'kitchen_catalog'}
    try:
        _sources('bedroom', Pb)
        ok('источник роли, которого комната не читает, — ошибка', False)
    except ValueError as e:
        ok('источник роли, которого комната не читает, — ошибка', 'kitchen_catalog' in str(e))

    def prow(role, mid, eid, name='Лампа', desc=('f',)):
        r = [role, str(mid), eid, name, 'Магазин', None, '4990', 't', '20', '20', '45', None, None, 'feed', None, None, None,
             'http://i/1.jpg', None, 't', 'http://u', 'http://d', 'хлопок', None, None, None, None, None, '{"сканди": 7.5}']
        assert len(r) == N_PRODUCT, len(r)
        return r + list(desc)
    rows = [prow('лампа', 1, 'a'), prow('торшер', 1, 'a'), prow('лампа', 2, 'b', name='Лампа\nдва'), prow('лампа', 1, 'a')]
    got = items('living', ['лампа', 'торшер'], desc_flags={'task': 'офис'}, _fetch=lambda s: rows)
    ok('товар в двух ролях — один, роли по порядку', [(c.offer_id, c.roles) for c in got]
       == [('1:a', ('лампа', 'торшер')), ('2:b', ('лампа',))])
    ok('перевод строки в названии не рвёт товар', got[1].name == 'Лампа\nдва')
    ok('NULL — None; числа — float; признак описания', got[0].brand is None and got[0].price == 4990.0
       and got[0].dims['h'] == 45.0 and got[0].flags == {'task': False} and got[0].params['Материал'] == 'хлопок')
    ok('psql: запись, поле, NULL', parse(f'1{FS}{NUL}{FS}a\nb{RS}2{FS}x{FS}y\n') == [['1', None, 'a\nb'], ['2', 'x', 'y']]
       and parse('') == [] and parse('\n') == [])
    sql = products_sql('decor', ['лампа'], {'task': 'офисн', 'bed': ''})
    ok('декор: фото живо, есть стиль, порядок магазин → артикул; пустой регекс — false',
       'coalesce(p.photo_alive, true)' in sql and 'ps.shop_mid is not null' in sql
       and sql.endswith('order by p.shop_mid, p.external_id') and ", false from" in sql and "~* 'офисн'" in sql)
    try:
        products_sql('kitchen', None, {})
        ok('неизвестный отбор products — ошибка', False)
    except ValueError:
        ok('неизвестный отбор products — ошибка', True)
    errs = [schema_errors(c.to_dict()) for c in got]
    ok('CatalogItem соответствует схеме', all(not e for e in errs) or print(errs))
    ok('схема ловит лишнее и тип', schema_errors(dict(got[0].to_dict(), mid='1', x=1)) == ['лишнее поле x', "mid: str не ['integer']"])
    m = with_mesh(got, ({'1:a'}, {'2:b'}, {'2:b'}))
    ok('меш: готов / сгенерирован, брак по ревизии', [(c.asset['revision'], c.asset['defect']) for c in m]
       == [('ready', False), ('generated', True)])
    # привязка мешей комнат (T-20261105-45): тесты Codex «Adapter tests»
    import room_bindings as RB
    calls = []

    def tab(rows_, err=None):
        def get(q):
            calls.append(q)
            if err:
                raise RuntimeError(err)
            return rows_
        return get
    lv = items('living', ['лампа', 'торшер'], desc_flags={'task': 'офис'}, _fetch=lambda s: rows, with_assets=True,
               _mesh=({'1:a'}, {'2:b'}, {'2:b'}), _bindings=tab([]))
    ok('гостиная с with_assets — как была, к привязке не ходит', [c.to_dict() for c in lv] == [c.to_dict() for c in m] and not calls)
    rc = [dataclasses.replace(c, origin='room_catalog', room_type='bedroom', asset=dict(c.asset)) for c in m]
    rc.append(dataclasses.replace(got[0], offer_id='3:c', mid=3, eid='c', room_type='bedroom'))   # товар products — свои поля
    snap_id = 'f' * 64
    row = lambda oid, st, rep=None, why=(): [oid, rep, st, 'sha256:' + 'a' * 64, (rep or oid).replace(':', '_'),  # noqa: E731
                                             '/g/x', 'G', 'R', 'ph', 't' if rep else 'f', 'mesh-family:v1:x' if rep else None,
                                             json.dumps(list(why)), '[]', 't', 't' if st == 'ready' else 'f', 't', 'f',
                                             '{"status": "ok"}', '{"status": "auto_resolved", "yaw_deg": 90}',
                                             RB.policy()['policy_version'], snap_id]
    calls.clear()
    b = with_binding(rc, 'bedroom', tab([row('1:a', 'ready'), row('2:b', 'blocked', '5:r', ['rep:orientation_review_pending'])]))
    a0, a1 = b[0].asset, b[1].asset
    ok('спальня: asset_id, mesh_id, ориентация, представитель, причины; один запрос на вызов',
       len(calls) == 1 and a0['mesh_status'] == 'ready' and a0['ready'] and a0['asset_id'] == 'sha256:' + 'a' * 64
       and a0['mesh_url'] == 'file:///g/x' and a0['orientation']['yaw_deg'] == 90 and a0['revision'] == 'ready'
       and a1['mesh_status'] == 'blocked' and a1['mesh_url'] is None and a1['representative_offer_id'] == '5:r'
       and a1['via_family'] and a1['reasons'] == ['rep:orientation_review_pending'] and a1['gate_status'] == 'fail'
       and b[2].asset == rc[2].asset)
    ok('товара нет в привязке — none (меша нет)', with_binding(rc[:1], 'bedroom', tab([row('9:z', 'ready')]))[0].asset['mesh_status'] == 'none')
    bad_rows = [row('1:a', 'ready')]
    bad_rows[0][-2] = 'v0'
    mixed = [row('1:a', 'ready'), row('2:b', 'ready')]
    mixed[1][-1] = 'e' * 64
    want = {'binding_missing': tab([], 'relation "offer_asset_binding" does not exist'), 'binding_empty': tab([]),
            'binding_version': tab(bad_rows), 'binding_corrupt': tab(mixed)}
    res = {k: with_binding(rc, 'bedroom', g) for k, g in want.items()}
    ok('нет таблицы / пусто / чужая политика / смесь снимков — unbound с причиной, без исключения',
       all(c.asset['mesh_status'] == 'unbound' and c.asset['reasons'] == [k] for k, cs in res.items() for c in cs[:2])
       and all(cs[2].asset == rc[2].asset for cs in res.values()))
    errs = [schema_errors(c.to_dict()) for c in b + res['binding_missing']]
    ok('расширенная схема принимает объект привязки', all(not e for e in errs) or print(errs))
    ok('схема ловит неверный тип в asset', schema_errors(dict(b[0].to_dict(), asset=dict(a0, ready='да'))) == ["asset.ready: str не ['boolean']"])
    print('selftest:', 'OK' if not bad else f'{bad} FAIL')
    return 1 if bad else 0


def main(argv: list) -> int:
    if '--selftest' in argv:
        return _selftest()
    room = argv[argv.index('--room') + 1] if '--room' in argv else 'bedroom'
    got = items(room, with_assets='--assets' in argv)
    by: dict = {}
    for c in got:
        for r in c.roles:
            by[(c.origin, r)] = by.get((c.origin, r), 0) + 1
    print(f'{room}: товаров {len(got)}')
    for (o, r), n in sorted(by.items(), key=lambda kv: (kv[0][0], -kv[1])):
        print(f'  {o:13} {r:22} {n}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
