"""СПАЛЬНИ ВИТРИНЫ ДЕМО (план onb-07 Т2, T-20261105-32; контракты ADR-0330). Чистые функции: банк спальни → варианты витрины
`demo-data.json` с комнатой, назначением и своей геометрией (`rooms_geo[room_id]`), ленты замен по ролям спальни.

Почему отдельным модулем: `flat215_demo.py` тяжёлый (база, сеть, меши), а здесь — правила, которые проверяются без них
(`tools/scout/tests/test_demo_bedroom.py`); товар, габариты и модель берутся функциями сборки, переданными параметрами.

- Комната включается флагом реестра (`apartments[].rooms[].enabled`, `flat215_demo.room_flags`); выключено — ни одной строки
  спальни в данных, гостиная байт в байт прежняя.
- Банк — живой `sets-bedroom.json` (правки Codex 05.11 к onb-07: демо не читает `*.next`); проверочная сборка — `BEDROOM_SETS`.
  Запись = формат `sets3` + `room_id`, `room_type`, `purpose` (onb-06 п.5). Файл — список записей или `{"sets": [...]}`.
- Геометрия — комната готовой расстановки банка (`layout._room`, `bank_room`), нет её — `flat215-bedrooms.json`, первая запись
  комнаты (основной вариант чертежа; `registry-*`/`small-*` — проверочные).
- Расстановка: готовая в записи (`layout` — `{роль: {x, z, rot}}`, как `v3set{n}-layout.json`), иначе солвер спальни
  (`services/planner-solver/planner/bedroom.py:solve_bedroom`) по габаритам товаров. Солвер не расставил кровать — вариант
  не публикуется (строка в `incomplete_styles` с комнатой).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GEO_FILE = os.path.join(HERE, 'flat215-bedrooms.json')
BANK_LIVE = os.path.join(HERE, 'sets-bedroom.json')
# ЯДРО СПАЛЬНИ: без кровати и хотя бы одной тумбы вариант не показываем (критерий onb-07: «в кадре видны кровать и ≥ 1 тумба»)
CORE = ('кровать', 'тумба прикроватная')
# роли спальни, которые ставит солвер (`planner/bedroom.py:ORDER`); остальное из набора — в списке, если это декор/мягкое
SOLVER_ROLES = ('кровать', 'тумба прикроватная', 'шкаф', 'комод', 'туалетный столик', 'стол рабочий', 'стул рабочий')
# в сцену и план идут ещё ковёр (место — из готовой расстановки записи, солвер ковёр не ставит; рисуется как у гостиной)
PLACE_ROLES = SOLVER_ROLES + ('ковёр',)
# в списке набора, но не в 3D: настольная лампа на тумбе (`layout.лампа.on`) — строкой списка и в запрос «Улучшить фото», как декор
LIST_ROLES = ('лампа',)
# ЯЧЕЙКА НА КОМНАТУ И СТИЛЬ (onb-06: 3 ступени цены × назначение): витрина показывает одну — средняя ступень, назначение по
# порядку; нет такой — следующая по порядку
TIER_ORDER = ('комфорт', 'mid', 'эконом', 'премиум')
PURPOSE_ORDER = ('couple', 'guest', 'single', 'office')
# ПОЛОСА «ПОДХОДЯЩИХ ПО РАЗМЕРУ» ленты замен спальни (то же правило страницы `inBand`, ключ — роль): кровать — по ширине рамы
# под назначение (вдвоём — спальное место 160–180, рама до ~205; один — 120–140), тумбы — по ширине; шкаф и комод полосой не режем
# (встаёт ли на место — решает `fitBadge` страницы по месту в комнате)
BAND_CM = {'couple': {'кровать': {'lo': 160, 'hi': 205}}, 'single': {'кровать': {'lo': 120, 'hi': 165}},
           'guest': {'кровать': {'lo': 140, 'hi': 205}}, '*': {'тумба прикроватная': {'lo': 30, 'hi': 65}}}


def base_role(role: str) -> str:
    return re.sub(r'\s+\d+$', '', role or '')


def load_bank(path: str) -> list:
    """Записи банка спальни; нет файла — пусто (комната остаётся «скоро»), битый файл — громко."""
    if not path or not os.path.exists(path):
        return []
    doc = json.load(open(path, encoding='utf-8'))
    rows = doc.get('sets') if isinstance(doc, dict) else doc
    return [r for r in rows or [] if isinstance(r, dict) and r.get('room_id') and isinstance(r.get('items'), dict)]


def bank_room(bank: list, room_id: str) -> dict | None:
    """Комната, в которой сборщик наборов расставил мебель (`layout._room` записи: w, d, проёмы, радиаторы) — первая запись
    комнаты. Готовая расстановка годна только в своей геометрии: витрина берёт её, а не чертёж (onb-06 → onb-07)."""
    for r in bank:
        rm = (r.get('layout') or {}).get('_room') if r.get('room_id') == room_id else None
        if isinstance(rm, dict) and rm.get('w') and rm.get('d'):
            return rm
    return None


def room_geo(room_id: str, reg: dict | None = None, extra: dict | None = None, path: str = GEO_FILE,
             layout_room: dict | None = None) -> dict | None:
    """Геометрия комнаты витрины в форме `data['room']` гостиной: w, d, title, проёмы, радиаторы (служебные `_why` сняты) и `kind`
    — тип зоны кадра (`CAM_ZONES` страницы). Подпись — имя и площадь реестра (как у гостиной «Гостиная 14.4 м²»).
    `extra` — общее с гостиной (вид из окна, потолок). `layout_room` — комната готовой расстановки банка (`bank_room`): есть —
    она вместо записи чертежа."""
    rec = layout_room or next((r for r in json.load(open(path, encoding='utf-8')).get('rooms') or []
                               if r.get('id') == room_id), None)
    if not rec or not rec.get('w') or not rec.get('d'):
        return None
    clean = lambda xs: [{k: v for k, v in x.items() if not k.startswith('_')} for x in xs or []]   # noqa: E731
    reg = reg or {}
    title = f"{reg.get('titleRu') or room_id} {reg['areaM2']} м²" if reg.get('areaM2') else (reg.get('titleRu') or room_id)
    return {'w': rec['w'], 'd': rec['d'], 'title': title, 'kind': reg.get('kind') or 'bedroom',
            'openings': clean(rec.get('openings')), 'radiators': clean(rec.get('radiators')), **(extra or {})}


def solve(geo: dict, dims: list, purpose: str | None) -> dict:
    """Расстановка солвером спальни → `{роль: {x, z, rot}, '_fill_pct', '_reason'}` (форма файла раскладки гостиной).
    `dims` — `[(роль, w, d, h)]` только с известным габаритом (Р1: размер не придумываем)."""
    sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))
    from planner.bedroom import solve_bedroom
    from planner.models import Item, Opening, Radiator, Room
    room = Room(width_cm=geo['w'], depth_cm=geo['d'], openings=[Opening(**o) for o in geo.get('openings') or []],
                radiators=[Radiator(**r) for r in geo.get('radiators') or []], room_type='bedroom', purpose=purpose)
    lay = solve_bedroom(room, [Item(role=r, w_cm=w, d_cm=d, h_cm=h) for r, w, d, h in dims], purpose)
    out = {p.role: {'x': p.x, 'z': p.y, 'rot': p.rot} for p in lay.placements}
    out['_fill_pct'] = lay.floor_used_pct
    if not lay.ok:
        out['_reason'] = list(lay.meta.get('reason') or []) or [v.code for v in lay.violations if v.severity.value == 'hard']
    return out


def variant_id(room_id: str, style_id: str) -> str:
    """Номер варианта спальни — `<комната>-<стиль>` (решение ведущего, onb-07 лог T-08): один на квартиру, ссылка `#v=` без комнаты."""
    return f'{room_id}-{style_id}'


def build_variant(rec: dict, geo: dict, sku, dims_of, style_id, hung=lambda n: False, decor_role=lambda r: False,
                  layout=None) -> tuple[dict | None, dict | None]:
    """Запись банка → (вариант витрины, None) или (None, строка `incomplete_styles`). `sku(items, role)` и `dims_of(v, sku, role)`
    — функции сборки (`flat215_demo._sku`, `_dims_of`): товар и габарит из каталога, как у гостиной."""
    items = rec.get('items') or {}
    style = rec.get('style') or ''
    sid = style_id(style)
    miss = {'style': style, 'room_id': rec.get('room_id')}
    if not sid:
        return None, {**miss, 'missing': ['стиль вне витрины']}
    skus, dims, unknown = {}, [], []
    art = layout if layout is not None else rec.get('layout')
    # экземпляры ролей: товары записи и пронумерованные места готовой расстановки («тумба прикроватная 2» — товар базовой роли)
    roles = list(items) + [r for r in (art or {}) if not r.startswith('_') and r not in items and base_role(r) in items]
    for role in roles:
        if base_role(role) not in PLACE_ROLES:
            continue
        s = sku(items, role)
        if not s:
            continue
        dm = dims_of({}, s, role)
        if dm.get('dims_unknown'):
            unknown.append({'role': role, 'name': s.get('name')})
            continue
        skus[role] = (s, dm)
        if base_role(role) in SOLVER_ROLES:
            dims.append((role, dm['w'], dm['d'], dm['h']))
    art = art or solve(geo, dims, rec.get('purpose'))
    objs = []
    for role, p in art.items():
        if role.startswith('_') or not isinstance(p, dict) or 'x' not in p or role not in skus:
            continue
        s, dm = skus[role]
        if hung(s.get('name')):
            s = dict(s, hung=True)
        objs.append({'role': role, 'x': round(p['x'], 1), 'y': round(p['z'], 1), 'rot': int(p.get('rot') or 0),
                     'w': dm['w'], 'd': dm['d'], 'h': dm['h'], 'dims_src': dm.get('dims_src'), 'sku': s,
                     'corner': False, 'corner_left': False, 'section': None})
    have = {base_role(o['role']) for o in objs}
    lost = [c for c in CORE if c not in have]
    if lost:
        return None, {**miss, 'missing': lost + list(art.get('_reason') or [])}
    decor = []
    lst = lambda r: decor_role(r) or base_role(r) in LIST_ROLES   # noqa: E731
    for role in list(items) + [r for r in art if not r.startswith('_') and r not in items and lst(base_role(r))]:
        if lst(role) or lst(base_role(role)):
            s = sku(items, role)
            if s:
                decor.append({'role': role, 'sku': s})
    return ({'id': variant_id(rec['room_id'], sid), 'title': (style or sid).capitalize(), 'style': style, 'style_id': sid,
             'room_id': rec['room_id'], 'purpose': rec.get('purpose'), 'fill_pct': art.get('_fill_pct'), 'items': objs,
             'decor': decor, 'dims_unknown': unknown, 'missing_item': [], 'fill': []}, None)


def pick_records(bank: list, rooms: list, styles: list) -> list:
    """Одна запись на (комнату, стиль): только включённые комнаты, стили — опубликованные гостиной (ключ стиля — витрина, ADR-0330
    п.3), порядок — как у гостиной. Несколько записей одной ячейки — первая (банк упорядочивает сборщик)."""
    rank = lambda xs, x: xs.index(x) if x in xs else len(xs)   # noqa: E731
    out, seen = [], set()
    for st in styles:
        cand = [r for r in bank if r.get('room_id') in rooms and (r.get('style') or '') == st]
        # ячейка витрины: назначение и ступень цены по порядку (`PURPOSE_ORDER`, `TIER_ORDER`), при равных — порядок банка
        cand.sort(key=lambda r: (rank(PURPOSE_ORDER, r.get('purpose')), rank(TIER_ORDER, r.get('tier'))))
        for r in cand:
            key = (r.get('room_id'), st)
            if key not in seen:
                seen.add(key)
                out.append(r)
    return sorted(out, key=lambda r: rooms.index(r['room_id']))


def feed_row(role: str, it: dict, style: str | None, msid, mesh_ok, alive=lambda u: True) -> dict | None:
    """Товар спальни → строка ленты замен (поля как у ленты гостиной). Только с фото, тремя габаритами и моделью на сервере
    (правило владельца 01.09: в замену — то, что видно в 3D); `mesh_ok` — проверка индекса мешей прода."""
    if not it or not it.get('img') or not (it.get('w') and it.get('d') and it.get('h')):
        return None
    sid = f"{it.get('mid')}_{it.get('eid')}" if it.get('mid') and it.get('eid') else it.get('sid')
    m = msid(sid)
    if not sid or not mesh_ok(m) or not alive(it.get('img')):
        return None
    return {'name': it.get('name'), 'w': it.get('w'), 'd': it.get('d'), 'h': it.get('h'), 'price': it.get('price'),
            'img': it.get('img'), 'url': it.get('url'), 'shop': it.get('shop'), 'style': style or '',
            'styles': [style] if style else [], 'sid': sid, 'msid': m, 'src': 'set'}


def feeds(bank: list, catalog: dict, msid, mesh_ok, alive=lambda u: True) -> dict:
    """Ленты замен ролей спальни: товары записей банка (со стилем записи) и их `alternates`, затем фото-каталог спальни
    (`flat215_demo.bedroom_catalog`, без стиля — виден при снятом чипе «Только стиль»). Один товар — одна строка, стили копятся."""
    out: dict = {}
    have: dict = {}

    def put(role, it, style):
        b = base_role(role)
        if b not in PLACE_ROLES:
            return
        row = feed_row(b, it, style, msid, mesh_ok, alive)
        if not row:
            return
        old = have.get((b, row['sid']))
        if old:
            if style and style not in old['styles']:
                old['styles'].append(style)
            return
        have[(b, row['sid'])] = row
        out.setdefault(b, []).append(row)
    for r in bank:
        for role, it in (r.get('items') or {}).items():
            put(role, it, r.get('style'))
        for role, alts in (r.get('alternates') or {}).items():
            for it in alts or []:
                put(role, it, r.get('style'))
    for role, rows in ((catalog or {}).get('roles') or {}).items():
        for p in rows:
            mid, _, eid = str(p.get('sid') or '').partition(':')
            put(role, {**p, 'mid': mid, 'eid': eid, 'src': 'catalog'}, None)
    for lst in out.values():
        lst.sort(key=lambda x: x['price'] or 0)
    return out


def bands(purposes: list) -> dict:
    """Полосы размера ролей спальни для `rules.slot_band_cm` (ключ — роль): по назначению первой включённой спальни."""
    out = dict(BAND_CM['*'])
    for p in purposes:
        for k, v in (BAND_CM.get(p) or {}).items():
            out.setdefault(k, v)
    return out
