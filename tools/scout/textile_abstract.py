#!/usr/bin/env python3
"""УСЛОВНЫЕ ШТОРЫ И ПЛЕД ГОСТИНОЙ (T-20261112-74, владелец TG 953; разбор T-73 `~/remlab-logs/t73-1112/1340/report.md`): из фото
магазина ткань не вырезать — у штор годна 1 вырезка из 8, у пледов 0 из 8 (сеть вырезает кресло и кровать с интерьерного фото),
меш строит чужую мебель. Поэтому в 3D — простая форма ЦВЕТОМ ТОВАРА: штора — полотна у окна (та же форма, что
`lib/viewer3d/window-light.ts`), плед — сложенный брусок на подлокотнике дивана. В карточке пометка «вид условный».

Строка декора получает `strategy: textile_abstract`, `place` (решатель паспорта `dependents.resolve`: шторы — место
`textile.curtains` на окне, плед — `soft.throw` на краю дивана; носители — предметы варианта, как у люстры T-66) и `look`
{hex, from, sheer}. Цвет — ПО НАЗВАНИЮ товара (`colour_of_name`); `sku.swatch` — только если в названии цвета нет (на интерьерных фото
он берёт цвет кресла: «Вуаль сливочный экрю» → #6a6156, T-73); нет ни того, ни другого — нейтральный, `from: neutral`, строка WARN.
Тюль и вуаль — полупрозрачные (`sheer`). Решатель отказал — строка остаётся только в списке, как раньше (без места).

ПОДУШКИ (T-20261113-02, директор: «есть годная модель → настоящая; нет → условная в тон товара с ценником, как плед»; ADR-0402):
место — тот же решатель (`soft.pillows` на сиденье дивана, по месту на строку подушки, `annotate_pillows`), `place.kind: pillow`.
Модель проверяет сборка (`flat215_demo.decor_sku_model`: на сервере, цвет как на фото) — годна: `sku.msid` и габарит сцены по мешу,
сцена ставит меш; нет — условная подушка цветом товара (`lib/viewer3d/kits/textile.ts:buildPillow`). Канон стратегий не трогаем
(`подушка: cutout` в `rules/asset-strategies.json` держит ночную очередь мешей).
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))
sys.path.insert(0, HERE)

from planner import dependents as DEP  # noqa: E402
from planner import room_templates as RT  # noqa: E402
from planner.models import Item, Opening, Room  # noqa: E402

STRATEGY = 'textile_abstract'
ROLES = {'шторы': ('textile', 'curtains', 'textile.curtains'), 'плед': ('soft', 'pillows_throw', 'soft.throw'),
         'подушка': ('soft', 'pillows_throw', 'soft.pillows')}
PILLOW = 'подушка'
PILLOW_DEF_CM = (45.0, 45.0, 12.0)      # подушка без размеров в карточке: лицо 45×45, толщина 12 (типовая диванная)
NEUTRAL = '#d8c4a6'                     # прежний общий цвет штор сцены (`window-light.ts`)
DEFAULT_CEILING_CM = 270.0              # как `contracts/apartment.ts:DEFAULT_CEILING_CM`
THROW_CM = {'w': 36.0, 'd': 55.0, 'h': 5.0}   # сложенный плед на подлокотнике: поперёк, вдоль глубины дивана, толщина
OPEN_KEYS = ('kind', 'wall', 'offset_cm', 'width_cm', 'sill_cm', 'height_cm', 'swing_cm')

# ЦВЕТ ПО НАЗВАНИЮ: основа слова → цвет. Берётся слово, стоящее в названии РАНЬШЕ (у «оранжевый/темно-серый» — оранжевый),
# при равном начале — более длинная основа («темно-сер» раньше «сер»). Цвета — спокойные тона ткани, не «чистые» RGB.
COLOURS = [
    ('экрю', '#e6dcc6'), ('сливоч', '#eee4cf'), ('молоч', '#f0e9da'), ('кремов', '#ece0c8'), ('айвори', '#ece4d0'),
    ('слоновой кост', '#ece4d0'), ('белоснеж', '#f3f2ee'), ('бел', '#f1f0ea'), ('льнян', '#d9cdb4'), ('натурал', '#d9cdb4'),
    ('бежев', '#d8c4a6'), ('беж', '#d8c4a6'), ('песоч', '#d6c29d'), ('капучино', '#b39b7f'), ('кофе', '#8c6c52'),
    ('мокко', '#7d6150'), ('тауп', '#9a8a7c'), ('коричнев', '#7b5a43'), ('шоколад', '#5a3f30'), ('терракот', '#b8644a'),
    ('кирпич', '#a24f3a'), ('рыж', '#c8743c'), ('оранжев', '#d9823b'), ('горчич', '#c9a032'), ('жёлт', '#e0c35a'),
    ('желт', '#e0c35a'), ('золот', '#c8a85a'), ('оливк', '#8a8a55'), ('хаки', '#7f7b55'), ('шалфе', '#9aa58a'),
    ('мятн', '#a8cfc0'), ('зелён', '#6f8a63'), ('зелен', '#6f8a63'), ('изумруд', '#2f6f5a'), ('бирюз', '#3fa4a0'),
    ('голуб', '#9bbad6'), ('тёмно-син', '#263b5e'), ('темно-син', '#263b5e'), ('син', '#3d5a8a'), ('индиго', '#3a3f75'),
    ('лаванд', '#b3a6cf'), ('сирен', '#b49ac2'), ('фиолет', '#6a4f8a'), ('пудр', '#dcb8b0'), ('розов', '#d9a9a4'),
    ('бордо', '#6e2a35'), ('винн', '#6e2a35'), ('красн', '#b03a3a'), ('графит', '#4a4c50'), ('антрацит', '#3b3d40'),
    ('тёмно-сер', '#5c5f63'), ('темно-сер', '#5c5f63'), ('светло-сер', '#c9cacb'), ('серебр', '#c0c2c4'), ('сер', '#9a9c9e'),
    ('чёрн', '#2a2a2b'), ('черн', '#2a2a2b'),
]
SHEER = re.compile(r'тюл|вуал|органз|сетк|кисе', re.I)


def colour_of_name(name: str | None) -> tuple[str, str] | None:
    """(hex, слово) — цвет по названию товара; нет цветового слова — None."""
    low = (name or '').lower()
    best = None
    for stem, hexv in COLOURS:
        i = low.find(stem)
        if i < 0 or (i > 0 and low[i - 1].isalpha() and low[i - 1] not in '-'):
            continue                                        # «сер» внутри «серия»? — только начало слова или после дефиса
        if stem == 'сер' and low[i:i + 4] == 'сери':
            continue
        if best is None or i < best[0] or (i == best[0] and len(stem) > len(best[1])):
            best = (i, stem, hexv)
    return (best[2], best[1]) if best else None


def look_of(sk: dict) -> dict:
    """Цвет и прозрачность условной ткани: название → swatch → нейтральный."""
    name = sk.get('name') or ''
    by = colour_of_name(name)
    sw = sk.get('swatch')
    if by:
        hexv, src = by[0], f'name:{by[1]}'
    elif isinstance(sw, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', sw):
        hexv, src = sw.lower(), 'swatch'
    else:
        hexv, src = NEUTRAL, 'neutral'
    # `of` — чей это цвет: замена товара на странице меняет `sku`, а не `look`; у чужого товара сцена штору не рисует (`textile.ts`)
    return {'hex': hexv, 'from': src, 'sheer': bool(SHEER.search(name)), 'of': look_key(sk)}


def look_key(sk: dict) -> str:
    """Ключ товара для `look.of` — артикул, иначе название (то же правило — `lib/configurator/textile.ts:lookKey`)."""
    return str(sk.get('sid') or sk.get('name') or '')


def to_room(geo: dict, ceiling_cm: float | None = None) -> Room:
    ops = [Opening(**{k: v for k, v in o.items() if k in OPEN_KEYS}) for o in geo.get('openings') or []]
    return Room(width_cm=float(geo['w']), depth_cm=float(geo['d']), ceiling_cm=float(ceiling_cm or geo.get('height_cm')
                or DEFAULT_CEILING_CM), openings=ops)


def place_of(role: str, objs: list, geo: dict, sk: dict, ceiling_cm: float | None = None) -> tuple[dict | None, str | None]:
    """Место условной ткани решателем паспорта на носителях варианта → (place, причина отказа)."""
    import chandelier as CH                              # переходник зоны отдыха (диван → `seating.sofa#n`), T-66
    group, variant, pid = ROLES[role]
    places = [p for p in RT._variant_places(RT.load('living'), group, variant)
              if p['kind'] != 'dependent' or p['id'] == pid]
    if role == 'шторы':
        item = Item(role=role, w_cm=float(sk.get('w') or 1), d_cm=float(sk.get('d') or sk.get('w') or 1),
                    h_cm=float(sk['h']) if sk.get('h') else None, name=sk.get('name'))
    else:
        item = Item(role=role, w_cm=THROW_CM['w'], d_cm=THROW_CM['d'], h_cm=THROW_CM['h'], name=sk.get('name'))
    try:
        res = DEP.resolve(places, CH.carriers_from_variant(objs), to_room(geo, ceiling_cm), items={pid: item})
    except Exception as e:  # noqa: BLE001 — отказ решателя не роняет сборку: строка остаётся в списке без места
        return None, f'{type(e).__name__}: {str(e)[:120]}'
    got = [p for p in res.placements if p.slot_instance_id.startswith(pid + '#')]
    if not got:
        bad = [res.reject] if res.reject else [e for e in res.empty if str(e.get('place', '')).startswith(pid)]
        why = '; '.join(f"{e.get('code')}: {e.get('message')}" for e in bad)
        return None, why or ('не нужно: ' + ', '.join(res.skipped) if res.skipped else 'решатель не дал места')
    p = got[0]
    a = p.anchor
    out = {'x': round(p.x, 1), 'y': round(p.y, 1), 'rot': p.rot, 'elev_cm': round(p.elev_cm, 1),
           'slot_instance_id': p.slot_instance_id, 'parent': p.parent_slot_instance_id}
    if role == 'шторы':
        out.update(kind='curtain', opening=a.opening if a else None, wall=a.wall if a else None)
    else:
        out.update(kind='throw', edge=a.edge if a else None, **THROW_CM)
    return out, None


def pillow_size(sk: dict) -> dict:
    """Габарит подушки СТОЯ у спинки (сцена: w — ширина лица, h — высота лица, d — толщина): из трёх размеров карточки самый малый —
    толщина, самый большой — ширина (валик 50×18×18 лежит вдоль сиденья, 45×45×11 стоит лицом вперёд). Нет размеров — типовая."""
    dims = [float(sk[k]) for k in ('w', 'd', 'h') if sk.get(k)]
    a, b, c = sorted(dims) if len(dims) == 3 else sorted(PILLOW_DEF_CM)
    return {'w': c, 'd': a, 'h': b}


def pillow_places(rows: list, objs: list, geo: dict, ceiling_cm: float | None = None) -> tuple[list, str | None]:
    """Места подушек на сиденье дивана решателем паспорта (`soft.pillows`: число по ширине дивана, но не больше товаров набора —
    `counts`): по месту на строку, по порядку экземпляров (`подушка` → `#0`, `подушка 2` → `#1`). Центр подушки — на толщину вперёд
    от начала сиденья (решатель даёт точку у спинки), низ — высота сиденья. → (места по строкам, None для лишних; причина отказа)."""
    import chandelier as CH
    group, variant, pid = ROLES[PILLOW]
    places = [p for p in RT._variant_places(RT.load('living'), group, variant) if p['kind'] != 'dependent' or p['id'] == pid]
    sizes = [r['_size'] for r in rows]
    item = Item(role=PILLOW, w_cm=max(s['w'] for s in sizes), d_cm=max(s['d'] for s in sizes), h_cm=max(s['h'] for s in sizes))
    cars = CH.carriers_from_variant(objs)
    try:
        res = DEP.resolve(places, cars, to_room(geo, ceiling_cm), items={pid: item}, counts={pid: len(rows)})
    except Exception as e:  # noqa: BLE001 — отказ решателя не роняет сборку: строки остаются в списке без места
        return [None] * len(rows), f'{type(e).__name__}: {str(e)[:120]}'
    got = sorted((p for p in res.placements if p.slot_instance_id.startswith(pid + '#')),
                 key=lambda p: int(p.slot_instance_id.split('#')[1]))
    if not got:
        bad = [res.reject] if res.reject else [e for e in res.empty if str(e.get('place', '')).startswith(pid)]
        return [None] * len(rows), '; '.join(f"{e.get('code')}: {e.get('message')}" for e in bad) or 'решатель не дал места'
    by_id = {c.slot_instance_id: c for c in cars}
    out = []
    for i, row in enumerate(rows):
        p = got[i] if i < len(got) else None
        car = by_id.get(p.parent_slot_instance_id) if p else None
        if p is None or car is None or p.local is None:
            out.append(None)
            continue
        s = row['_size']
        x, y = DEP._world(car, p.local.dx or 0.0, (p.local.dy or 0.0) + s['d'] / 2)
        out.append({'x': round(x, 1), 'y': round(y, 1), 'rot': p.rot, 'elev_cm': round(p.elev_cm, 1),
                    'slot_instance_id': p.slot_instance_id, 'parent': p.parent_slot_instance_id, 'kind': 'pillow', **s})
    return out, (None if len(got) >= len(rows) else f'на сиденье мест {len(got)} из {len(rows)}')


def annotate_pillows(decor: list, objs: list, geo: dict, tag: str, ceiling_cm: float | None = None, model=None) -> int:
    """ПОДУШКИ НА ДИВАНЕ (T-20261113-02, ADR-0402 «ничего из сметы без места в 3D»): каждой строке подушки — место на сиденье
    (`pillow_places`) и цвет товара. Годная модель (`model(sku)` → (msid, габарит меша) или (None, причина)) — настоящая подушка:
    `sku.msid` и габарит сцены по мешу (ширина — как у товара); нет модели — условная подушка цветом товара, как плед."""
    import dependent_decor as DD
    rows = [r for r in decor if str(r.get('role') or '').split(' ')[0] == PILLOW and (r.get('sku') or {}).get('name')]
    if not rows:
        return 0
    meshes = []
    for r in rows:
        size = pillow_size(r['sku'])
        msid, ext = model(r['sku']) if model else (None, 'проверки модели нет')
        dims = DD.mesh_dims(ext, size['w']) if msid else None        # меш не тянем до размеров карточки: один масштаб по ширине
        meshes.append((msid, dims) if msid and dims else (None, ext if isinstance(ext, str) else 'меш не читается'))
        r['_size'] = dims if msid and dims else size
    try:
        places, why = pillow_places(rows, objs, geo, ceiling_cm)
    finally:
        for r in rows:
            r.pop('_size')
    n = 0
    for row, place, (msid, note) in zip(rows, places, meshes):
        sk = row['sku']
        sk['msid'] = msid           # модель — только проверенная для ЭТОГО товара; пришедшая с заменой из ленты не остаётся
        if not place:
            print(f'WARN:textile: {tag} «{sk.get("name")}» — подушке нет места в 3D: {why}', flush=True)
            continue
        if msid:
            what = f'модель {msid}'
        else:
            what = f'условная ({note})'
        lk = look_of(sk)
        row.update(strategy=STRATEGY, place=place, look=lk)
        n += 1
        print(f"  подушка {tag}: «{sk.get('name')}» → {place['slot_instance_id']}, {what}, цвет {lk['hex']} ({lk['from']})", flush=True)
    return n


def annotate(decor: list, objs: list, geo: dict, tag: str, ceiling_cm: float | None = None, model=None) -> int:
    """Строкам штор, пледа и подушек декора варианта гостиной — `strategy`, `place`, `look`. Возвращает, скольким дали место.
    `model` — проверка модели подушки (`annotate_pillows`)."""
    n = annotate_pillows(decor, objs, geo, tag, ceiling_cm, model)
    taken: set = set()
    for row in decor:
        role = str(row.get('role') or '').split(' ')[0]
        sk = row.get('sku') or {}
        if role not in ROLES or role == PILLOW or not sk.get('name') or role in taken:
            continue                                       # одно место на роль: второй комплект — только в списке
        place, why = place_of(role, objs, geo, sk, ceiling_cm)
        if not place:
            print(f'WARN:textile: {tag} «{sk.get("name")}» — без места в 3D: {why}', flush=True)
            continue
        if role == 'шторы' and place.get('opening') is None:
            print(f'WARN:textile: {tag} «{sk.get("name")}» — решатель не назвал окно', flush=True)
            continue
        lk = look_of(sk)
        if lk['from'] == 'neutral':
            print(f'WARN:textile: {tag} «{sk.get("name")}» — цвета нет ни в названии, ни в swatch: нейтральный', flush=True)
        row.update(strategy=STRATEGY, place=place, look=lk)
        taken.add(role)
        n += 1
        print(f"  ткань {tag}: {role} «{sk.get('name')}» → {lk['hex']} ({lk['from']}{', тюль' if lk['sheer'] else ''}), "
              f"место {place['slot_instance_id']}", flush=True)
    return n


def feed_base(key: str) -> str:
    """Роль ленты без комнаты и номера: `bedroom:плед` → `плед`, `подушка 2` → `подушка`."""
    return str(key or '').split(':')[-1].split(' ')[0]


def annotate_feeds(feeds: dict, model=None) -> str:
    """ЛЕНТЫ ЗАМЕН ТКАНЕЙ НЕСУТ ЦВЕТ И МОДЕЛЬ (T-20261113-24, владелец TG 1629/1623: «заменяю подушку — исчезает»; что в списке — видно
    в 3D). Замена на странице (`tryOn`, строка декора) меняла только `sku`, а цвет строки (`look.of`) оставался от прежнего товара —
    сцена по правилу «чужой цвет не рисуем» снимала вещь из 3D. Теперь каждый товар ленты штор, пледа и подушек несёт свой `look`
    (тот же `look_of`), подушка — ещё `pillow` {msid, w, d, h}: msid — только проверенная модель (`model`, как у строк вариантов),
    иначе None (условная подушка цветом товара); размер — по мешу или по карточке (`pillow_size`). Страница переносит их в строку
    при замене, место строки остаётся. → строка отчёта."""
    import dependent_decor as DD
    n = {'look': 0, 'pillow': 0, 'model': 0}
    for key, lst in (feeds or {}).items():
        base = feed_base(key)
        if base not in ROLES:
            continue
        for p in lst or []:
            if not isinstance(p, dict) or not p.get('name'):
                continue
            p['look'] = look_of(p)
            n['look'] += 1
            if base != PILLOW:
                continue
            size = pillow_size(p)
            msid, ext = model(p) if model else (None, None)
            dims = DD.mesh_dims(ext, size['w']) if msid else None
            p['pillow'] = {'msid': msid if dims else None, **(dims or size)}
            n['pillow'] += 1
            n['model'] += 1 if msid and dims else 0
    return f"ленты тканей: цвет у {n['look']} товаров, подушек {n['pillow']} (с моделью {n['model']})"


def look_guard(variants: list) -> list:
    """Сторож перед записью данных (T-20261113-02/2): у строки ткани с цветом `look.of` — ключ товара, который в ней стоит
    (`look_key`). Расходится (товар сменил шаг после разметки) — место и цвет снимаем: строка остаётся в списке без 3D, а не
    висит «в 3D» с чужим цветом. → строки журнала WARN (пусто — расхождений нет)."""
    out = []
    for v in variants or []:
        for row in v.get('decor') or []:
            lk = row.get('look')
            if not isinstance(lk, dict) or lk.get('of') == look_key(row.get('sku') or {}):
                continue
            out.append(f"WARN:textile_look: {v.get('id')} {row.get('role')} «{(row.get('sku') or {}).get('name')}» — цвет посчитан "
                       f"для другого товара ({lk.get('of')}): место и цвет сняты, строка только в списке")
            for k in ('strategy', 'place', 'look'):
                row.pop(k, None)
    return out
