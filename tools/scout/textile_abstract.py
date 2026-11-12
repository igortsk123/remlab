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
ROLES = {'шторы': ('textile', 'curtains', 'textile.curtains'), 'плед': ('soft', 'pillows_throw', 'soft.throw')}
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


def annotate(decor: list, objs: list, geo: dict, tag: str, ceiling_cm: float | None = None) -> int:
    """Строкам штор и пледа декора варианта гостиной — `strategy`, `place`, `look`. Возвращает, скольким дали место."""
    n = 0
    taken: set = set()
    for row in decor:
        role = str(row.get('role') or '').split(' ')[0]
        sk = row.get('sku') or {}
        if role not in ROLES or not sk.get('name') or role in taken:
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
