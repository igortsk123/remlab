#!/usr/bin/env python3
"""ТЕНЬ ГОСТИНОЙ на настоящих комнатах /demo и туров (T-20261112-69, план living-full-01 П1.6; Codex 12.11
`_intake/codex/2026-11-12-living-passport-carriers-answer.md` § 7 «Этап 3 — shadow living engine»). Только чтение живого.

ЗАЧЕМ. Паспорт гостиной (`rules/room-templates/living.json`) и решатель зависимых мест (`planner/dependents.py`) проверены только на
синтетике. Здесь — что они дали бы на тех же данных, что видит покупатель: уровень, места подушек/пледа/вазы/картин/штор/люстры,
отказы с причиной, и сколько ₽ «в цене без 3D» (отчёт T-64, `priced_vs_3d.py`) осталось бы. Живое /demo не меняется: старый
решатель главный, тень пишет только отчёт и свои сцены.

КАК. Носители — предметы варианта демо как есть (координаты старого решателя, не двигаем). Уровень — ПО НАБОРУ
(`room_templates.levels_by_set`, T-20261112-71): уровень годен, если на каждое его ОБЯЗАТЕЛЬНОЕ место-слот есть предмет той же роли
(угловое место — угловой диван); места «по желанию» без предмета — пусты; годные — по числу пустых мест, затем порядок паспорта.
Годный уровень → `dependents.resolve` с товарами декора варианта (мест подушек и картин — не больше товаров); отказ → следующий
(как `on_failure: reject_composition`; картины — `leave_empty`: не встали — пусто с причиной); первый без отказа — выбран. Предметы, которых нет в уровне (пуф, стеллаж, лишние стулья) — остаются
на полу как в живой сцене, с пометкой «вне паспорта уровня». Потолок: `rooms_geo.height_cm`, иначе 270 — как живое 3D
(`contracts/apartment.ts:DEFAULT_CEILING_CM`, `lib/configurator/fromDemo.ts`).

  ~/venvs/scout/bin/python living_shadow.py OUTDIR [--demo demo-data.json] [--tours DIR] [--draw N]
Итог: OUTDIR/report.md, report.json, scenes/<где>__<вариант>.json, schemes/*.png.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, 'services', 'planner-solver'))
sys.path.insert(0, HERE)

from planner import dependents as DEP  # noqa: E402
from planner import room_templates as RT  # noqa: E402
from planner.geometry import base_role, footprint  # noqa: E402
from planner.models import Item, Opening, Placement, Room  # noqa: E402

import priced_vs_3d as PV  # noqa: E402

TOURS = os.path.expanduser('~/remlab-logs/t64-1112/tours')
WALL_ART = os.path.join(REPO, 'data', 'flat3d', 'wall-art.json')
DEFAULT_CEILING_CM = 270          # contracts/apartment.ts:DEFAULT_CEILING_CM — то же, что берёт живое 3D
OPEN_KEYS = set(Opening.model_fields)
ART_REF = 'distances_cm.mounting.wall_art'
CURTAINS, SCREEN = 'шторы', 'экран'
DOC = RT.load('living')


def is_living(room_id: str) -> bool:
    return not str(room_id or 'living').startswith('bed')


# ───────────────────────── комната ─────────────────────────

def to_room(geo: dict) -> tuple[Room, list[str], dict]:
    """Комната решателя из `rooms_geo` демо → (Room, пометки, факты для `when`)."""
    notes = []
    ops = [Opening(**{k: v for k, v in o.items() if k in OPEN_KEYS}) for o in geo.get('openings') or []]
    ceil = geo.get('height_cm')
    if not ceil:
        ceil = DEFAULT_CEILING_CM
        notes.append(f'потолок не задан — {DEFAULT_CEILING_CM}, как живое 3D')
    room = Room(width_cm=geo['w'], depth_cm=geo['d'], ceiling_cm=ceil, openings=ops)
    # площадь для выбора уровня — весь контур помещения: основной прямоугольник + пристройки (T-71 п.5); хвост коридора (`stub`)
    # и балкон/лоджия (`outdoor`) — не часть комнаты. Решатель зависимых по-прежнему видит только основной прямоугольник.
    part = [a for a in geo.get('annexes') or [] if not a.get('stub') and not a.get('outdoor')]
    extra_m2 = sum(float(a.get('w') or 0) * float(a.get('d') or 0) for a in part) / 10_000
    if geo.get('annexes'):
        notes.append(f"НЕ прямоугольник: пристроек {len(part)} из {len(geo['annexes'])} (+{extra_m2:.1f} м² к площади для выбора "
                     'уровня; хвост коридора и балкон не в счёт) — решатель зависимых видит только основной прямоугольник')
    if geo.get('contour'):
        notes.append('НЕ прямоугольник: контур — решатель видит bbox')
    if geo.get('approx'):
        notes.append('размеры приблизительные (approx)')
    title = str(geo.get('title') or geo.get('title_ru') or '').lower()
    facts = {**DEP.room_facts(room), 'aspect': max(room.width_cm, room.depth_cm) / min(room.width_cm, room.depth_cm),
             'area_m2': room.area_m2 + extra_m2,
             'kitchen': 'кухн' in title or geo.get('kind') == 'kitchen_living', 'annex': bool(part)}
    return room, notes, facts


# ───────────────────────── носители и товары ─────────────────────────

def _slot_shape(p: dict) -> str | None:
    """`shape` места-слота из паспорта (компилятор его не переносит): угловое место — только угловой диван."""
    g, sid = p['id'].split('.', 1)
    var = ((DOC.get('groups') or {}).get(g, {}).get('variants') or {}).get(p.get('variant')) or {}
    return next((s.get('shape') for s in var.get('slots') or [] if s.get('id') == sid), None)


def carrier(it: dict, sid: str) -> Placement:
    sku = it.get('sku') or {}
    item = Item(role=it['role'], w_cm=it['w'], d_cm=it['d'], h_cm=it.get('h'), name=sku.get('name'), item_id=sku.get('sid'),
                corner=bool(it.get('corner')), corner_left=bool(it.get('corner_left')), corner_section_cm=it.get('section') or 95)
    return Placement(role=it['role'], x=it['x'], y=it['y'], rot=it.get('rot') or 0, item=item, slot_instance_id=sid)


def match(places: list[dict], items: list[dict]) -> tuple[list[Placement], list[str], list[Placement], dict, set]:
    """Предметы варианта → места-слоты уровня. → (носители уровня, недостающие «роль×n», вне уровня, {индекс предмета: sid},
    id мест-слотов без носителя)."""
    pool = [i for i, it in enumerate(items) if it.get('w') and it.get('d')]
    used, cars, missing, sid_of, miss_ids = set(), [], [], {}, set()
    for p in (q for q in places if q['kind'] == 'slot'):
        n, want = p.get('count', 1), p['role']
        corner = _slot_shape(p) == 'corner'
        ok = lambda it: bool(it.get('corner')) == corner if base_role(want) == 'диван' else True  # noqa: E731
        cand = [i for i in pool if i not in used and items[i]['role'] == want and ok(items[i])]
        cand += [i for i in pool if i not in used and i not in cand and base_role(items[i]['role']) == base_role(want)
                 and ok(items[i])]
        for k, i in enumerate(cand[:n]):
            used.add(i)
            sid_of[i] = f"{p['id']}#{k}"
            cars.append(carrier(items[i], sid_of[i]))
        if len(cand) < n:
            missing.append(f"{want}{'(угловой)' if corner else ''}×{n - len(cand)}")
            miss_ids.add(p['id'])
    extra, seen = [], {}
    for i in pool:
        if i in used:
            continue
        b = base_role(items[i]['role'])
        sid_of[i] = f"extra.{b}#{seen.get(b, 0)}"
        seen[b] = seen.get(b, 0) + 1
        extra.append(carrier(items[i], sid_of[i]))
    return cars, missing, extra, sid_of, miss_ids


def carriers_from_variant(v: dict, places: list[dict]) -> tuple[list[Placement], list[str]]:
    """ПЕРЕХОДНИК «вариант гостиной → носители» (одна точка входа для живого экспорта, T-66/T-69): предметы варианта демо
    (`items` с x/y/rot и габаритами) + места компилированного уровня (`room_templates.compile_level`) → Placement с
    `slot_instance_id` «группа.место#n» для `dependents.resolve`; предметы вне уровня — «extra.<роль>#n» (на полу, занимают стену).
    Второе — недостающие носители «роль×n» (пусто — уровень покрыт)."""
    items = [it for it in v.get('items') or [] if it.get('w') and it.get('d')]
    cars, missing, extra, _, _ = match(places, items)
    return cars + extra, missing


def partial_places(places: list[dict], miss_ids: set) -> tuple[list[dict], list[str]]:
    """ЧАСТИЧНАЯ проверка (только для отчёта, не решение движка): места-слоты без носителя убираются; зависимое на убранном
    месте — тоже (у `one_of` остаются кандидаты, что есть в уровне). Остальное (подушки на диване, картина, шторы) — проверяется.
    → (места, убранные места). То же правило, что у выбора уровня по набору для пустых мест «по желанию» (`RT.drop_places`)."""
    return RT.drop_places(places, set(miss_ids)), sorted(miss_ids)


def found_of(places: list[dict], items: list[dict]) -> dict:
    """Сколько предметов набора нашлось на каждое место-слот уровня (для `RT.levels_by_set`)."""
    out = {}
    for sid in match(places, items)[3].values():
        if not sid.startswith('extra.'):
            k = sid.split('#')[0]
            out[k] = out.get(k, 0) + 1
    return out


def dep_items(places: list[dict], decor: list[dict]) -> dict:
    """Товар декора на зависимое место: та же базовая роль; несколько товаров одной роли — самый широкий (строже по клетке)."""
    out = {}
    for p in (q for q in places if q['kind'] == 'dependent'):
        cands = [d['sku'] for d in decor if base_role(d.get('role') or '') == base_role(p['role'])
                 and (d.get('sku') or {}).get('w')]
        if cands:
            s = max(cands, key=lambda s: s['w'])
            out[p['id']] = Item(role=p['role'], w_cm=s['w'], d_cm=s.get('d') or s['w'], h_cm=s.get('h'), name=s.get('name'),
                                item_id=s.get('sid'))
    return out


def dep_counts(places: list[dict], decor: list[dict]) -> dict:
    """Сколько товаров набора на зависимое место (та же базовая роль, штуки по qty): подушек 2 — мест 2, не 3 по ширине.
    Декора нет (туры) — пусто: мест по норме, они ждут подбора товара."""
    out = {}
    for p in (q for q in places if q['kind'] == 'dependent'):
        n = sum(int(d.get('qty') or 1) for d in decor if base_role(d.get('role') or '') == base_role(p['role']))
        if n:
            out[p['id']] = n
    return out


# ───────────────────────── уровни ─────────────────────────

SLOT_ROLE = {k: v[2]['role'] for k, v in RT._slot_index(DOC).items()}


def _role_n(ids: list[str]) -> list[str]:
    """«группа.место×n» → «роль×n» для отчёта."""
    return [f"{SLOT_ROLE.get(x.rsplit('×', 1)[0], x)}×{x.rsplit('×', 1)[1]}" for x in ids]


LIGHT_GROUP = 'light'   # группа света паспорта `living.json`: торшер ИЛИ комод с лампой — обязательна (T-20261112-71/2)


def light_label(missing: list[str]) -> list[str]:
    """«комод×1» / «торшер×1» ближайшего уровня → одна метка «свет (торшер или комод + лампа)»: недостаёт группы, а не комода."""
    roles = {SLOT_ROLE[k] for k in SLOT_ROLE if k.split('.')[0] == LIGHT_GROUP}
    out = [m for m in missing if m.rsplit('×', 1)[0] not in roles]
    return out + ['свет (торшер или комод + лампа)'] if len(out) < len(missing) else out


def only_light(bad: list[dict]) -> bool:
    """Уровня нет, но хоть одному уровню не хватает ТОЛЬКО света (все недостающие места — группы света): дыра набора,
    которую закрывает сборка наборов, а не паспорт."""
    return any(b.get('missing') and all(x.split('.')[0] == LIGHT_GROUP for x in b['missing']) for b in bad)


def try_levels(room: Room, facts: dict, items: list[dict], decor: list[dict]) -> dict:
    """Выбор уровня ПО НАБОРУ — общее правило `RT.levels_by_set` (обязательное есть — уровень годен, места «по желанию» без
    предмета пусты; годные — по числу пустых мест, затем порядок паспорта). Годные по очереди → `dependents.resolve`; первый
    без отказа — выбран. Нет такого: `rejected` — первый годный (с отказом), иначе `closest` — негодный уровень, где недостаёт
    меньше всего обязательного (частичная проверка — только для отчёта)."""
    good, bad = RT.levels_by_set(DOC, facts, lambda places: found_of(places, items))
    tried, rejected = [], None
    for b in bad:
        if 'error' in b:
            tried.append({'tpl': b['tpl'], 'level': b['level'], 'status': 'LEVEL_INVALID', 'why': b['error']})
        else:
            tried.append({'tpl': b['tpl'], 'level': b['level'], 'status': 'нет носителя', 'why': ', '.join(_role_n(b['missing']))})
    for c in good:
        places = c['places']
        cars, _, extra, sid_of, _ = match(places, items)
        res = DEP.resolve(places, cars + extra, room, dep_items(places, decor), facts, dep_counts(places, decor))
        tried.append({'tpl': c['tpl'], 'level': c['level'], 'status': 'OK' if res.ok else res.reject['code'],
                      'why': '' if res.ok else f"{res.reject['place']}: {res.reject['message']}", 'empty': c['empty']})
        pick = {'tpl': c['tpl'], 'level': c['level'], 'places': places, 'cars': cars, 'extra': extra, 'sid_of': sid_of,
                'res': res, 'empty': c['empty']}
        if res.ok:
            return {'tried': tried, 'chosen': pick, 'rejected': rejected}
        rejected = rejected or pick
    miss_n = lambda b: sum(int(x.rsplit('×', 1)[1]) for x in b['missing'])  # noqa: E731
    cands = [b for b in bad if 'missing' in b]
    if rejected is None and cands:   # ни один уровень не годен: ближайший — чтобы показать, чего не хватает
        b = min(cands, key=miss_n)
        tpl = RT.template_by_id('living', b['tpl'])
        places, _ = RT.compile_level(DOC, tpl, b['level'])
        found = found_of(places, items)
        gone = {p['id'] for p in places if p['kind'] == 'slot' and not found.get(p['id'])}
        part, dropped = partial_places(places, gone)
        cars, _, extra, sid_of, _ = match(part, items)
        res = DEP.resolve(part, cars + extra, room, dep_items(part, decor), facts, dep_counts(part, decor))
        return {'tried': tried, 'chosen': None, 'rejected': None, 'only_light': only_light(bad),
                'closest': {'tpl': b['tpl'], 'level': b['level'], 'missing': _role_n(b['missing']), 'dropped': dropped,
                            'places': part, 'cars': cars, 'extra': extra, 'sid_of': sid_of, 'res': res, 'empty': []}}
    return {'tried': tried, 'chosen': None, 'rejected': rejected}


# ───────────────────────── строки «в цене» ─────────────────────────

def _places_by_role(pick: dict | None) -> dict:
    """Базовая роль зависимого места → сколько мест поставила тень (только у выбранного уровня без отказа)."""
    out = {}
    if not pick or not pick['res'].ok:
        return out
    for p in pick['res'].placements:
        out[base_role(p.role)] = out.get(base_role(p.role), 0) + 1
    return out


def judge_rows(rows: list[dict], pick: dict | None, why_none: str) -> list[dict]:
    """Строки «в цене» варианта (факты T-64) → место в тени: носители — как в живой сцене (координаты те же), декор — по
    местам решателя по порядку строк одной роли. Шторы — место есть, товар отдельно; виртуальный экран не в цене."""
    have = _places_by_role(pick)
    roles_in_level = {base_role(p['role']) for p in (pick or {}).get('places', []) if p['kind'] == 'dependent'}
    taken, out = {}, []
    for r in rows:
        b = PV.base_role(r.get('role'))
        live_ok = r.get('shown', 0) >= r.get('slots', 1)
        if r.get('src') == 'item':
            shadow, why = live_ok, ('' if live_ok else 'как живое: ' + (PV.reason(r) or ''))
        elif not pick or not pick['res'].ok:
            shadow, why = False, why_none
        elif b not in roles_in_level:
            shadow, why = False, 'в уровне нет места этой роли'
        else:
            k = taken.get(b, 0)
            taken[b] = k + 1
            shadow = k < have.get(b, 0)
            why = '' if shadow else f'лишняя: мест {have.get(b, 0)}'
        kind = ('место есть, товар отдельно' if b == CURTAINS and shadow else
                'оба' if live_ok and shadow else 'тень добавила' if shadow else 'тень потеряла' if live_ok else 'нигде')
        out.append({**{k: r.get(k) for k in ('src', 'role', 'name', 'price', 'qty', 'qty_shown')},
                    'rub': PV.missing_rub(r) if not live_ok else 0.0, 'rub_all': float(r.get('price') or 0) * int(r.get('qty') or 1),
                    'live': live_ok, 'shadow': shadow, 'kind': kind, 'why': why})
    return out


# ───────────────────────── проверки ─────────────────────────

def drift(items: list[dict], sid_of: dict, placements: list[Placement]) -> float:
    """Сдвиг крупной геометрии: носители тени против предметов варианта (должен быть 0 — тень носители не двигает)."""
    by = {p.slot_instance_id: p for p in placements}
    worst = 0.0
    for i, sid in sid_of.items():
        p, it = by.get(sid), items[i]
        if p is None:
            continue
        worst = max(worst, abs(p.x - it['x']), abs(p.y - it['y']), abs(((p.rot - (it.get('rot') or 0)) + 180) % 360 - 180))
    return round(worst, 3)


def hard_checks(room: Room, deps: list[Placement]) -> list[str]:
    """Жёсткое у зависимых мест: точка вне комнаты, ниже пола, выше потолка (низ + высота товара)."""
    bad = []
    for p in deps:
        if not (-1 <= p.x <= room.width_cm + 1 and -1 <= p.y <= room.depth_cm + 1):
            bad.append(f'{p.slot_instance_id}: точка ({p.x:g}, {p.y:g}) вне комнаты')
        top = p.elev_cm + (p.item.h_cm if p.item is not None and p.item.h_cm and p.mount == 'wall' else 0)
        if p.elev_cm < 0 or (room.ceiling_cm and top > room.ceiling_cm + 0.5):
            bad.append(f'{p.slot_instance_id}: высота {p.elev_cm:g}–{top:g} вне 0–{room.ceiling_cm:g}')
    return bad


@contextlib.contextmanager
def live_art_numbers():
    """Картины по числам ЖИВОЙ сцены (`data/flat3d/wall-art.json` above_cm по опоре, pair_gap_cm) вместо паспорта — только
    для сравнения «сколько картин встало бы иначе»; файлы не меняются (подмена правила в памяти на время прогона)."""
    wa = json.load(open(WALL_ART, encoding='utf-8'))
    orig_rule, orig_on = DEP._rule, DEP._art_on
    state = {'role': '*'}

    def rule(ref, place):
        v = orig_rule(ref, place)
        if ref == ART_REF:
            v = copy.deepcopy(v)
            above = wa['above_cm'].get(state['role'], wa['above_cm']['*'])
            v['bottom_above_carrier'], v['gap_between_frames'] = above, wa['pair_gap_cm']
        return v

    def art_on(p, car, *a):
        state['role'] = base_role(car.role)
        return orig_on(p, car, *a)

    DEP._rule, DEP._art_on = rule, art_on
    try:
        yield
    finally:
        DEP._rule, DEP._art_on = orig_rule, orig_on


def art_compare(pick: dict | None, room: Room, facts: dict, decor: list[dict]) -> dict | None:
    """Картины тени по паспорту vs по числам живой сцены: число, опора, низ."""
    if not pick or not any(p['id'] == 'art.art' for p in pick['places']):
        return None
    with live_art_numbers():
        res2 = DEP.resolve(pick['places'], pick['cars'] + pick['extra'], room, dep_items(pick['places'], decor), facts,
                           dep_counts(pick['places'], decor))
    a = [p for p in pick['res'].placements if p.slot_instance_id.startswith('art.art#')]
    b = [p for p in res2.placements if p.slot_instance_id.startswith('art.art#')] if res2.ok else []
    sig = lambda xs: (len(xs), sorted({p.parent_slot_instance_id for p in xs}))  # noqa: E731
    return {'passport': {'n': len(a), 'parent': sig(a)[1], 'bottom': [p.elev_cm for p in a]},
            'live_numbers': {'ok': res2.ok, 'reject': res2.reject, 'n': len(b), 'parent': sig(b)[1], 'bottom': [p.elev_cm for p in b]},
            'differs': sig(a) != sig(b), 'shift_cm': round((b[0].elev_cm - a[0].elev_cm), 1) if a and b else None}


# ───────────────────────── вариант целиком ─────────────────────────

def shadow_variant(geo: dict, v: dict, rows: list[dict] | None = None) -> dict:
    """Тень одного варианта гостиной: комната → уровни → зависимые → строки в цене, проверки. Без node и файлов."""
    room, notes, facts = to_room(geo)
    items = [it for it in v.get('items') or [] if it.get('w') and it.get('d')]
    decor = [d for d in v.get('decor') or [] if (d.get('sku') or {}).get('name')]
    lv = try_levels(room, facts, items, decor)
    pick = lv.get('chosen') or lv.get('rejected') or lv.get('closest')
    first_cov = next((t for t in lv['tried'] if t['status'] not in ('нет носителя', 'LEVEL_INVALID')), None)
    down = None
    if lv.get('chosen'):
        status, why_none = 'OK', ''
        if first_cov and first_cov['level'] != pick['level']:
            down = f"{first_cov['tpl']}.{first_cov['level']} {first_cov['status']}"
    elif lv.get('rejected'):
        rj = lv['rejected']['res'].reject
        status = f"отказ: {rj['code']} ({lv['rejected']['level']})"
        why_none = 'все покрытые уровни — отказ: ' + '; '.join(
            f"{t['level']} {t['status']}" for t in lv['tried'] if t['status'] not in ('нет носителя', 'OK'))
    elif lv.get('closest'):
        c = lv['closest']
        part = 'OK' if c['res'].ok else f"{c['res'].reject['code']} {c['res'].reject['place']}"
        need = ', '.join(light_label(c['missing']))
        status = f"нет уровня: не хватает {need}; частично без {'/'.join(c['dropped'])}: {part}"
        why_none = f"нет покрытого уровня (не хватает {need})"
    else:
        status, why_none = 'нет уровней для комнаты', 'нет уровней для комнаты'
    deps = pick['res'].placements if pick and pick['res'].ok else []
    no_item = no_item_places(deps)
    floor = (pick['cars'] + pick['extra']) if pick else [carrier(it, f'extra.{base_role(it["role"])}#{i}') for i, it in enumerate(items)]
    judged = judge_rows(rows or [], pick if lv.get('chosen') else None, why_none)
    return {
        'variant': v.get('id'), 'style': v.get('style'), 'room_id': v.get('room_id') or 'living',
        'room': {'w': room.width_cm, 'd': room.depth_cm, 'area_m2': round(room.area_m2, 2), 'aspect': round(facts['aspect'], 2),
                 'ceiling': room.ceiling_cm, 'kitchen': facts['kitchen'], 'annex': facts['annex'], 'notes': notes},
        'status': status, 'down_from': down, 'tpl': pick and pick['tpl'], 'level': pick and pick['level'], 'tried': lv['tried'],
        'first_covered': first_cov, 'outside_level': sorted({base_role(p.role) for p in (pick['extra'] if pick else [])}),
        'reject': None if not pick or pick['res'].ok else pick['res'].reject,
        'skipped': pick['res'].skipped if pick else [], 'limits': pick['res'].limits if pick else {},
        'missing': lv['closest']['missing'] if lv.get('closest') else [],  # обязательное, чего нет (ближайший уровень)
        'empty_slots': _role_n(pick['empty']) if pick else [],            # места «по желанию», которых нет в наборе
        'empty_deps': (pick['res'].empty if pick else []) + no_item,      # картины не встали; места без товара набора (NO_ITEM)
        'only_light': bool(lv.get('only_light')),                         # уровня нет только из-за света (торшер / комод+лампа)
        'deps': deps, 'floor': floor, 'rows': judged,
        'drift_cm': drift(items, pick['sid_of'], floor) if pick else 0.0,
        'hard': hard_checks(room, deps), 'art': art_compare(pick if lv.get('chosen') else None, room, facts, decor),
        '_room': room,
    }


NO_ITEM = 'NO_ITEM'


def no_item_places(deps: list[Placement]) -> list[dict]:
    """Зависимые места, на которые в наборе нет товара (туры: декора в данных нет) — место есть, но ПУСТО; виртуальное
    (`priced` False, экран ТВ) не в счёт. Число мест по норме остаётся (их и закроет подбор товара)."""
    out = {}
    for p in deps:
        if p.item is None and p.priced is not False:
            pid = p.slot_instance_id.split('#')[0]
            out.setdefault(pid, {'code': NO_ITEM, 'place': pid, 'message': f'пусто: нет в наборе ({base_role(p.role)})', 'n': 0})
            out[pid]['n'] += 1
    return list(out.values())


def is_no_item(p: Placement) -> bool:
    return p.item is None and p.priced is not False


def scene_json(src: str, sv: dict) -> dict:
    dump = lambda p: p.model_dump(exclude_none=True, exclude_defaults=True)  # noqa: E731
    return {'src': src, 'variant': sv['variant'], 'style': sv['style'], 'room': sv['room'], 'template': sv['tpl'],
            'level': sv['level'], 'status': sv['status'], 'tried': sv['tried'], 'floor': [dump(p) for p in sv['floor']],
            'dependents': [dump(p) for p in sv['deps']], 'limits': sv['limits'], 'skipped': sv['skipped'],
            'empty_slots': sv['empty_slots'], 'empty_deps': sv['empty_deps']}


# ───────────────────────── прогон по файлам ─────────────────────────

def run_file(path: str, src: str, facts_file: dict) -> list[dict]:
    """Все варианты гостиных файла данных (те же, что берёт страница: до `MAXV` на комнату — по фактам T-64)."""
    D = json.load(open(path, encoding='utf-8'))
    rows_by = {v['id']: v for v in facts_file.get('variants') or []}
    out = []
    for v in D.get('variants') or []:
        rid = v.get('room_id') or 'living'
        f = rows_by.get(v.get('id'))
        if not is_living(rid) or f is None:
            continue
        geo = (D.get('rooms_geo') or {}).get(rid) or D.get('room')
        if f.get('refused') or not v.get('items'):
            out.append({'src': src, 'variant': v.get('id'), 'room_id': rid, 'status': 'комната отказана страницей', 'skip': True})
            continue
        sv = shadow_variant(geo, v, f.get('rows') or [])
        sv['src'] = src
        out.append(sv)
    return out


def totals(svs: list[dict]) -> dict:
    t = {'variants': 0, 'ok': 0, 'priced_rows': 0, 'priced_rub': 0.0, 'live_missing_n': 0, 'live_missing_rub': 0.0,
         'shadow_missing_n': 0, 'shadow_missing_rub': 0.0, 'curtains_rub': 0.0, 'kinds': {}, 'why': {}}
    for sv in svs:
        if sv.get('skip'):
            continue
        t['variants'] += 1
        t['ok'] += sv['status'] == 'OK'
        for r in sv['rows']:
            t['priced_rows'] += 1
            t['priced_rub'] += r['rub_all']
            if not r['live']:
                t['live_missing_n'] += 1
                t['live_missing_rub'] += r['rub']
            k = t['kinds'].setdefault(r['kind'], {'n': 0, 'rub': 0.0})
            k['n'] += 1
            k['rub'] += r['rub_all']
            if r['kind'] == 'место есть, товар отдельно':
                t['curtains_rub'] += r['rub_all']
            if not r['shadow']:
                rub = r['rub'] if not r['live'] else r['rub_all']
                t['shadow_missing_n'] += 1
                t['shadow_missing_rub'] += rub
                w = t['why'].setdefault(f"{PV.base_role(r['role'])}: {r['why']}", {'n': 0, 'rub': 0.0})
                w['n'] += 1
                w['rub'] += rub
    t['why'] = dict(sorted(t['why'].items(), key=lambda kv: -kv[1]['rub']))
    return t


def _rub(x: float) -> str:
    return f'{round(x):,}'.replace(',', ' ')


def _arts(sv: dict) -> list[dict]:
    return [e for e in sv['empty_deps'] if e['code'] != NO_ITEM]


def _no_items(sv: dict) -> list[dict]:
    return [e for e in sv['empty_deps'] if e['code'] == NO_ITEM]


def sets_light(path: str) -> dict:
    """Банк наборов гостиной (`sets3.json`, его берут туры — `trial_demo.sets_path`): по стилю — наборов всего, с торшером,
    с комодом. Файла нет — пусто (отчёт так и скажет)."""
    import ast
    try:
        sets = json.load(open(path, encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    out = {}
    for st in sets:
        items = st.get('items') or {}
        items = ast.literal_eval(items) if isinstance(items, str) else items
        c = out.setdefault(st.get('style') or '?', {'n': 0, 'торшер': 0, 'комод': 0})
        c['n'] += 1
        for r in ('торшер', 'комод'):
            c[r] += any(base_role(k) == r for k in items)
    return out


CATALOG_SQL = ("select coalesce(s.top_style, '-'), count(*) from lr_roles l left join product_style_scores s using (shop_mid, external_id) "
               "where l.role = 'торшер' and l.price_rub is not null and l.in_stock group by 1")


def catalog_floor_lamps() -> dict | None:
    """Торшеры каталога в наличии по стилю (`product_style_scores.top_style`) — локальная база DEV, как `compose.py` (без ключей).
    База недоступна — None."""
    psql = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab', '-q', '-t', '-A', '-F', '|']
    try:
        r = subprocess.run(psql, input=CATALOG_SQL, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode:
        return None
    return {k: int(n) for k, n in (ln.split('|') for ln in r.stdout.split() if '|' in ln)}


def light_summary(tours: list[dict], light: dict | None) -> list[str]:
    """Строка-итог «не хватает ТОЛЬКО света» и вход задачи сборки наборов: по стилям этих туров — сколько наборов банка с
    торшером/комодом и сколько торшеров в каталоге."""
    only = [sv for sv in tours if not sv.get('skip') and sv['status'] != 'OK' and sv.get('only_light')]
    L = [f"**Не хватает ТОЛЬКО света (торшер или комод + лампа): {len(only)} туров** — свет обязателен (таблица Codex); это "
         'дыра набора, её закрывает сборка наборов, паспорт её не прячет.']
    if not only:
        return L
    light = light or {}
    sets, cat = light.get('sets') or {}, light.get('catalog')
    by = {}
    for sv in only:
        by[sv['style']] = by.get(sv['style'], 0) + 1
    L += ['', '| стиль | туров «только свет» | наборов банка (`sets3.json`) | с торшером | с комодом | торшеров в каталоге (в наличии) |',
          '|---|---|---|---|---|---|']
    for st, n in sorted(by.items(), key=lambda kv: -kv[1]):
        c = sets.get(st, {})
        L.append(f"| {st} | {n} | {c.get('n', '—')} | {c.get('торшер', '—')} | {c.get('комод', '—')} | "
                 f"{'не опрошен' if cat is None else cat.get(st, 0)} |")
    no_cat = sorted(st for st in by if cat is not None and not cat.get(st))
    in_cat = sorted(st for st in by if cat is not None and cat.get(st))
    if cat is None:
        L.append('Каталог не опрошен (локальная база недоступна) — по стилям смотреть только банк.')
    else:
        L.append('Из них стилей без торшера в каталоге: ' + (', '.join(no_cat) or 'нет') + '.')
        if in_cat:
            live = [sv for sv in tours if not sv.get('skip')]
            has = lambda r: sum(any(base_role(p.role) == r for p in sv['floor']) for sv in live)  # noqa: E731
            L.append('Торшеры в каталоге по стилям ' + ', '.join(in_cat) + ' ЕСТЬ, а в наборы этих туров не попали (столбец '
                     f"«с торшером» — доля наборов банка). Во всех турах вариантов с торшером {has('торшер')}, с комодом "
                     f"{has('комод')} из {len(live)} — где теряется комод банка, разбирает сборка наборов (вход задачи).")
    return L


def empty_summary(demo: list[dict], tours: list[dict], light: dict | None = None) -> list[str]:
    """Выбор уровня по набору (T-71): сколько получили уровень, какие места пусты (нет в наборе), где картины не встали,
    чего из обязательного нет у отказанных; сверху — «не хватает только света» (T-71/2)."""
    live = lambda xs: [x for x in xs if not x.get('skip')]  # noqa: E731
    ok = lambda xs: [x for x in live(xs) if x['status'] == 'OK']  # noqa: E731

    def count(xs, key):
        c = {}
        for sv in xs:
            for k in key(sv):
                c[k] = c.get(k, 0) + 1
        return sorted(c.items(), key=lambda kv: -kv[1])

    L = ['', '## Выбор уровня по набору (T-20261112-71)',
         f"Туры: уровень получили **{len(ok(tours))} из {len(live(tours))}** гостиных (T-69: 0); /demo — {len(ok(demo))} из "
         f"{len(live(demo))}. Правило — `room_templates.levels_by_set`: обязательное место нет в наборе → уровень не годен целиком "
         '(следующий); место «по желанию» (`required` в паспорте) нет → пусто, уровень остаётся; годные — по числу пустых мест '
         '(с мелочами, что ушли вместе с носителем), затем порядок паспорта; годных нет — честный отказ с причиной.', '']
    L += light_summary(tours, light)
    L += ['', '### Пустые места выбранных уровней (нет в наборе — место ждёт товар, уровень не теряется)',
         '| место | туров | /demo |', '|---|---|---|']
    d_e = dict(count(ok(demo), lambda sv: sv['empty_slots']))
    L += [f"| {k} | {n} | {d_e.get(k, 0)} |" for k, n in count(ok(tours), lambda sv: sv['empty_slots'])] or ['| — | 0 | 0 |']
    art = lambda sv: [f"{e['code']}: {e['message'].split(':')[0]}" for e in _arts(sv)]  # noqa: E731
    L += ['', '### Картины не встали — место пусто (условно обязательны «при глухой стене», `on_failure: leave_empty`)',
          '| причина | туров | /demo |', '|---|---|---|']
    d_a = dict(count(ok(demo), art))
    L += [f"| {k} | {n} | {d_a.get(k, 0)} |" for k, n in count(ok(tours), art)] or ['| — | 0 | 0 |']
    noi = lambda sv: [f"{e['place']} ({e['message'].split('(')[-1].rstrip(')')})" for e in _no_items(sv)]  # noqa: E731
    L += ['', '### Места мелочей без товара в наборе — пусто: нет в наборе (на схеме — пустой кружок)',
          '| место | туров | /demo |', '|---|---|---|']
    with_deps = [sv for sv in live(tours) if sv['deps']]                  # и частичная проверка: места те же, товара нет
    t_n, d_n = dict(count(with_deps, noi)), dict(count(ok(demo), noi))
    L += [f"| {k} | {t_n.get(k, 0)} | {d_n.get(k, 0)} |" for k in sorted(set(t_n) | set(d_n), key=lambda k: -t_n.get(k, 0))] \
        or ['| — | 0 | 0 |']
    L.append(f"(туры — {len(with_deps)} с местами мелочей, включая частичную проверку уровня без носителя)")
    bad = [sv for sv in live(tours) if sv['status'] != 'OK']
    L += ['', f"### Отказы туров ({len(bad)}) — чего из обязательного нет в наборе (ближайший уровень)",
          '| не хватает | туров | ближайший уровень |', '|---|---|---|']
    by = {}
    for sv in bad:
        k = ', '.join(light_label(sv['missing'])) or sv['status']
        by.setdefault(k, []).append(f"{sv['tpl']}.{sv['level']}")
    L += [f"| {k} | {len(v)} | {', '.join(sorted(set(v)))} |" for k, v in sorted(by.items(), key=lambda kv: -len(kv[1]))]
    return L


def render_md(meta: dict, demo: list[dict], tours: list[dict], t64: dict, light: dict | None = None) -> str:
    td, tt = totals(demo), totals(tours)
    L = [f"# Тень гостиной на живых данных — {meta['at']}", '',
         f"Источник: /demo `{meta['demo']}`, туры `{meta['tours']}` ({meta['tours_n']} файлов). Цена и «в 3D» — тем же кодом, что T-64 "
         '(`priced_vs_3d_scene.ts`); тень — `tools/scout/living_shadow.py` (паспорт `living.json` → `dependents.resolve`). Живое не менялось.', '',
         '## Итог /demo (гостиные)',
         f"Вариантов {td['variants']}, уровень без отказа найден у {td['ok']}. Строк в цене {td['priced_rows']} на {_rub(td['priced_rub'])} ₽.",
         f"- **Сейчас (живое, как T-64): в цене без 3D — {td['live_missing_n']} строк на {_rub(td['live_missing_rub'])} ₽** "
         f"(весь /demo по T-64 сейчас: {t64.get('missing_n', '?')} строк на {_rub(t64.get('missing_rub', 0))} ₽, из них спальни "
         f"{_rub(t64.get('missing_rub', 0) - td['live_missing_rub'])} ₽ — тень спален не считает).",
         f"- **При тени: без места — {td['shadow_missing_n']} строк на {_rub(td['shadow_missing_rub'])} ₽**; шторы — место есть, "
         f"3D-товара нет: {_rub(td['curtains_rub'])} ₽ (не дефект по брифу).", '',
         '| что со строкой | строк | ₽ (вся цена строки) |', '|---|---|---|']
    L += [f"| {k} | {a['n']} | {_rub(a['rub'])} |" for k, a in sorted(td['kinds'].items())]
    if td['why']:
        L += ['', '### Почему у тени нет места (топ)', '| причина | строк | ₽ |', '|---|---|---|']
        L += [f"| {k} | {a['n']} | {_rub(a['rub'])} |" for k, a in td['why'].items()]
    L += empty_summary(demo, tours, light)
    L += ['', '## Комнаты /demo', '| вариант | стиль | комната | шаблон.уровень | итог | ушёл с | вне уровня | дрейф см | жёсткое |',
          '|---|---|---|---|---|---|---|---|---|']
    for sv in demo:
        if sv.get('skip'):
            L.append(f"| {sv['variant']} | | | | {sv['status']} | | | | |")
            continue
        r = sv['room']
        L.append(f"| {sv['variant']} | {sv['style']} | {r['w']:g}×{r['d']:g} ({r['area_m2']} м², {r['aspect']}) | {sv['tpl']}.{sv['level']} | "
                 f"{sv['status']} | {sv['down_from'] or ''} | {', '.join(sv['outside_level'])} | {sv['drift_cm']} | {len(sv['hard'])} |")
    for sv in (x for x in demo if not x.get('skip')):
        L += ['', f"### {sv['variant']} ({sv['style']}) — {sv['tpl']}.{sv['level']}: {sv['status']}",
              'Перебор уровней: ' + ' → '.join(f"{t['level']} {t['status']}" + (f" ({t['why']})" if t['why'] and t['status'] != 'OK' else '')
                                             for t in sv['tried']), '']
        if sv['room']['notes']:
            L.append('Комната: ' + '; '.join(sv['room']['notes']))
        deps = sv['deps']
        L.append('Места тени: ' + (', '.join(f"{p.slot_instance_id}→{p.parent_slot_instance_id} ({p.mount}, {p.elev_cm:g} см)"
                                              for p in deps) or '—'))
        if sv['skipped']:
            L.append('Не нужны по условию: ' + ', '.join(sv['skipped']))
        if sv['empty_slots'] or sv['empty_deps']:
            L.append('Пусто: ' + ', '.join(sv['empty_slots'] + [f"{e['place']} ({e['code']})" for e in sv['empty_deps']]))
        L += ['', '| роль | товар | ₽ | живое 3D | тень | итог | почему |', '|---|---|---|---|---|---|---|']
        L += [f"| {x['role']} | {x['name']} | {_rub(x['rub_all'])} | {'да' if x['live'] else 'нет'} | {'да' if x['shadow'] else 'нет'} | "
              f"{x['kind']} | {x['why']} |" for x in sv['rows']]
        if sv['hard']:
            L += ['', 'Жёсткие нарушения: ' + '; '.join(sv['hard'])]
    arts = [sv for sv in demo if not sv.get('skip') and sv['art']]
    L += ['', '## Картины: паспорт (10–20 над опорой, зазор 5–8) против чисел живой сцены (wall-art.json 22/25, зазор 10)',
          'Числа не меняли — второй прогон решателя с числами живой сцены в памяти.', '',
          '| вариант | паспорт: шт, опора, низ | живые числа: шт, опора, низ | иначе? | сдвиг низа см |', '|---|---|---|---|---|']
    for sv in arts:
        a, b = sv['art']['passport'], sv['art']['live_numbers']
        L.append(f"| {sv['variant']} | {a['n']}, {', '.join(a['parent'])}, {a['bottom']} | "
                 f"{b['n'] if b['ok'] else 'отказ ' + b['reject']['code']}, {', '.join(b['parent'])}, {b['bottom']} | "
                 f"{'да' if sv['art']['differs'] else 'нет'} | {sv['art']['shift_cm']} |")
    n_art = sum(sv['art']['passport']['n'] for sv in arts)
    n_diff = sum(sv['art']['passport']['n'] for sv in arts if sv['art']['differs'])
    L += ['', f"Итог: картин в тени {n_art}; иначе по числу/опоре встали бы {n_diff}; по высоте — все на сдвиг из таблицы.", '']
    L += ['## Туры /try (гостиные; декора в данных туров нет — места без товара)',
          f"Вариантов {tt['variants']}, уровень без отказа — у {tt['ok']}.", '',
          '| тур | вариант | комната | шаблон.уровень | итог | пусто | ушёл с | вне уровня | дрейф | жёсткое | комната: пометки |',
          '|---|---|---|---|---|---|---|---|---|---|---|']
    for sv in tours:
        if sv.get('skip'):
            L.append(f"| {sv['src']} | {sv['variant']} | {sv['room_id']} | | {sv['status']} | | | | | | |")
            continue
        r = sv['room']
        empty = ', '.join(sv['empty_slots'] + [f"картины: {e['code']}" for e in _arts(sv)]
                          + [f"{e['place']} ×{e['n']}: нет в наборе" for e in _no_items(sv)]) if sv['status'] == 'OK' else ''
        L.append(f"| {sv['src']} | {sv['variant']} | {sv['room_id']} {r['w']:g}×{r['d']:g} ({r['area_m2']} м²) | {sv['tpl']}.{sv['level']} | "
                 f"{sv['status']} | {empty} | {sv['down_from'] or ''} | {', '.join(sv['outside_level'])} | {sv['drift_cm']} | "
                 f"{len(sv['hard'])} | {'; '.join(n for n in r['notes'] if not n.startswith('потолок'))} |")
    st = {}
    for sv in tours:
        if not sv.get('skip'):
            k = sv['status'] if sv['status'] == 'OK' else sv['status'].split(' (')[0].split('; частично')[0]
            st[k] = st.get(k, 0) + 1
    L += ['', 'Итоги туров: ' + '; '.join(f'{k} — {n}' for k, n in sorted(st.items(), key=lambda kv: -kv[1])), '']
    pt = {}
    for sv in tours:
        if not sv.get('skip') and '; частично' in sv['status']:
            k = sv['status'].split(': ')[-1].split(' ')[0]
            pt[k] = pt.get(k, 0) + 1
    if pt:
        L += ['Частичная проверка (группы без носителя убраны, только для отчёта — движок такой уровень не взял бы): '
              + '; '.join(f'{k} — {n}' for k, n in sorted(pt.items(), key=lambda kv: -kv[1])), '']
    return '\n'.join(L) + '\n'


# ───────────────────────── схема сверху ─────────────────────────

COLORS = {'подушка': (214, 96, 77), 'плед': (232, 160, 60), 'ваза': (70, 150, 90), 'лампа': (240, 200, 40), 'картина': (120, 80, 170),
          'шторы': (60, 120, 200), 'люстра': (230, 60, 160), 'экран': (40, 40, 40), 'кашпо': (40, 140, 60)}


RUG_ROLES = ('ковёр', 'ковер')


def floor_draw_order(floor: list[Placement]) -> list[Placement]:
    """Ковёр — первым (под мебелью): иначе его след закрывает журнальный столик, и ваза «висит» на ковре."""
    return sorted(floor, key=lambda p: base_role(p.role) not in RUG_ROLES)


def draw(sv: dict, path: str, s: float = 1.6) -> None:
    """Схема сверху: стены и проёмы, носители (след), зависимые — точки с подписью и родителем. Юг — снизу."""
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 12)   # как bedroom_schemes.FONT
    except OSError:
        font = ImageFont.load_default()
    room = sv['_room']
    m = 40
    W, H = max(900, int(room.width_cm * s + 2 * m)), int(room.depth_cm * s + 2 * m + 76)    # шапка — не уже 900 px
    im = Image.new('RGB', (W, H), 'white')
    g = ImageDraw.Draw(im)
    g.font = font
    P = lambda x, y: (m + x * s, m + 76 + (room.depth_cm - y) * s)  # noqa: E731
    g.text((8, 6), f"{sv.get('src', '')} {sv['variant']} · {sv['style']} · {sv['tpl']}.{sv['level']} · {sv['status']}", fill='black')
    empty = sv.get('empty_slots', []) + [f"картины ({e['code']})" for e in sv.get('empty_deps', []) if e['code'] != NO_ITEM]
    g.text((8, 24), f"{room.width_cm:g}×{room.depth_cm:g} см, потолок {room.ceiling_cm:g} · юг снизу · окно синим, дверь красным"
                    f"{' · пусто: ' + ', '.join(empty) if empty else ''}\n"
                    'точка — место тени (число — низ, см); пустой кружок — товара нет в наборе или непродаваемое;\n'
                    'ковёр — под мебелью; розовый след — вне паспорта уровня', fill='black')
    g.rectangle([P(0, room.depth_cm), P(room.width_cm, 0)], outline='black', width=3)
    for op in room.openings:
        a, b = op.offset_cm, op.offset_cm + op.width_cm
        seg = {'south': (P(a, 0), P(b, 0)), 'north': (P(a, room.depth_cm), P(b, room.depth_cm)),
               'west': (P(0, a), P(0, b)), 'east': (P(room.width_cm, a), P(room.width_cm, b))}[op.wall]
        g.line(seg, fill=(80, 160, 230) if op.kind == 'window' else (200, 60, 60), width=7)
    for p in floor_draw_order(sv['floor']):
        poly = [P(x, y) for x, y in footprint(p).exterior.coords]
        extra = p.slot_instance_id.startswith('extra.')
        g.polygon(poly, fill=(235, 235, 235) if not extra else (250, 230, 230), outline=(110, 110, 110))
        cx, cy = footprint(p).centroid.coords[0]
        g.text(P(cx - 15, cy + 4), base_role(p.role)[:9], fill=(60, 60, 60))
    n_of = {e['place']: e['n'] for e in sv.get('empty_deps', []) if e['code'] == NO_ITEM}
    said = set()
    for p in sv['deps']:
        b = base_role(p.role)
        pid = p.slot_instance_id.split('#')[0]
        c = COLORS.get(b, (0, 0, 0))
        x, y = P(p.x, p.y)
        r = 5 if p.mount in ('surface', 'wall', 'rod') else 8
        hollow = p.priced is False or is_no_item(p)
        g.ellipse([x - r, y - r, x + r, y + r], fill=None if hollow else c, outline=c, width=2)
        if is_no_item(p) and pid in said:
            continue                                         # подпись пустого места — одна на место (три подушки не наезжают)
        said.add(pid)
        n = n_of.get(pid, 1) if is_no_item(p) else 1
        g.text((x + 6, y - 12), f"{b}{f' ×{n}' if n > 1 else ''}{' ' + str(int(p.elev_cm)) if p.mount != 'surface' else ''}"
                                f"{' · пусто: нет в наборе' if is_no_item(p) else ''}", fill=c)
    im.save(path)


def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--demo', default=PV.DEMO)
    ap.add_argument('--tours', default=TOURS)
    ap.add_argument('--draw', type=int, default=3, help='сколько схем /demo нарисовать')
    ap.add_argument('--sets', default=os.path.join(HERE, 'sets3.json'), help='банк наборов гостиной (вход «только свет»)')
    ap.add_argument('--no-catalog', action='store_true', help='не опрашивать торшеры в локальной базе')
    a = ap.parse_args(argv[1:])
    os.makedirs(os.path.join(a.out, 'scenes'), exist_ok=True)
    os.makedirs(os.path.join(a.out, 'schemes'), exist_ok=True)
    tours = sorted(glob.glob(os.path.join(a.tours, '*.json'))) if a.tours and os.path.isdir(a.tours) else []
    facts = PV.scene_facts([a.demo] + tours, a.out)
    t64 = PV.summarize({a.demo: facts[a.demo]}, 'demo')
    demo = run_file(a.demo, 'demo', facts[a.demo])
    tour = [sv for f in tours for sv in run_file(f, os.path.basename(f)[:-5], facts[f])]
    for sv in demo + tour:
        if not sv.get('skip'):
            json.dump(scene_json(sv['src'], sv), open(os.path.join(a.out, 'scenes', f"{sv['src']}__{sv['variant']}.json"), 'w',
                                                        encoding='utf-8'), ensure_ascii=False, indent=1)
    # схемы: /demo (полный уровень) + разные комнаты туров с местами частичной проверки — по одной на размер комнаты
    drawn, sizes = [sv for sv in demo if not sv.get('skip')][:max(1, a.draw - 2)], set()
    for sv in sorted(tour, key=lambda x: x.get('status') != 'OK'):          # сперва туры с выбранным уровнем
        key = None if sv.get('skip') or not sv['deps'] else (sv['room']['w'], sv['room']['d'])
        if key and key not in sizes and len(drawn) < a.draw:
            sizes.add(key)
            drawn.append(sv)
    for sv in drawn:
        draw(sv, os.path.join(a.out, 'schemes', f"{sv['src']}__{sv['variant']}.png"))
    meta = {'at': subprocess.run(['date', '-u', '+%Y-%m-%d %H:%M UTC'], capture_output=True, text=True).stdout.strip(),
            'demo': a.demo, 'tours': a.tours, 'tours_n': len(tours)}
    light = {'sets': sets_light(a.sets), 'catalog': None if a.no_catalog else catalog_floor_lamps()}
    strip = lambda sv: {k: v for k, v in sv.items() if k not in ('_room', 'deps', 'floor')}  # noqa: E731
    json.dump({'meta': meta, 'totals': {'demo': totals(demo), 'tours': totals(tour)}, 'light': light,
               't64_demo': {k: t64[k] for k in ('missing_n', 'missing_rub', 'priced_rub')},
               'demo': [strip(sv) for sv in demo], 'tours': [strip(sv) for sv in tour]},
              open(os.path.join(a.out, 'report.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    with open(os.path.join(a.out, 'report.md'), 'w', encoding='utf-8') as fh:
        fh.write(render_md(meta, demo, tour, t64, light))
    td, tt = totals(demo), totals(tour)
    print(f"/demo гостиные: {td['variants']} вар., OK {td['ok']}; в цене без 3D сейчас {td['live_missing_n']} строк "
          f"{round(td['live_missing_rub'])} ₽ → при тени {td['shadow_missing_n']} строк {round(td['shadow_missing_rub'])} ₽ "
          f"(шторы: место есть, {round(td['curtains_rub'])} ₽); туры: {tt['variants']} вар., OK {tt['ok']}")
    print('отчёт', os.path.join(a.out, 'report.md'))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
