"""ВИТРИНА КОМНАТЫ ДЕМО — ОБЩЕЕ ЯДРО (hall-demo-01 этап 3, T-20261106-98; до того — `demo_bedroom.py`, onb-07 Т2, ADR-0330).
Чистые функции: банк комнаты → варианты витрины `demo-data.json` с комнатой, назначением и своей геометрией (`rooms_geo[room_id]`),
ленты замен по ролям комнаты. Что у комнаты своё (роли солвера и сцены, «только в списке», полосы размера, порядок ячейки,
солвер, пути банка и чертежа) — в `Showcase` адаптера (`demo_bedroom.SPEC`); ведущие роли — профиль комнаты
(`rules/profiles/<тип>.json`, `lead: true`). Гостиная — прежний путь `flat215_demo.py` (strangler: ядро её не трогает).

Почему отдельным модулем: `flat215_demo.py` тяжёлый (база, сеть, меши), а здесь — правила, которые проверяются без них
(`tests/test_demo_bedroom.py`, побайтный эталон до переноса — `tests/test_demo_room_golden.py`); товар, габариты и модель берутся
функциями сборки, переданными параметрами.

- Банк — живой `sets-<тип>.json` (демо не читает `*.next`); запись = формат `sets3` + `room_id`, `room_type`, `purpose` (onb-06 п.5).
- Геометрия — комната готовой расстановки банка (`layout._room`, `bank_room`), нет её — файл чертежа адаптера, первая запись
  комнаты (основной вариант чертежа).
- Расстановка: готовая в записи (`layout` — `{роль: {x, z, rot}}`), иначе солвер адаптера по габаритам товаров. Солвер не
  расставил ведущих — вариант не публикуется (строка в `incomplete_styles` с комнатой).
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Callable

HERE = os.path.dirname(os.path.abspath(__file__))
PLANNER = os.path.join(HERE, '..', '..', 'services', 'planner-solver')
STYLE_AXES = os.path.join(HERE, 'rules', 'style-axes.json')


@dataclass(frozen=True)
class Showcase:
    """Что у витрины комнаты своё. Роли — базовые имена (без номера экземпляра «… 2»).
    solver_roles — ставит солвер (и проверяет сторож модели, запас — `role_spares`); place_roles — в сцену и план (солвер + место
    из готовой расстановки записи, напр. ковёр); list_roles — в списке набора, не в 3D (`list_only`); нужна ли роли модель — не
    список, а стратегия ассета (`needs_mesh`); one_free_roles — «одна расстановка»: по центру места опорной; band_cm — полоса «подходящих по размеру»
    ленты: {назначение | '*': {роль: {lo, hi}}}; tier_order/purpose_order — ячейка витрины на комнату и стиль;
    solve(geo, dims, purpose) — солвер комнаты → `{роль: {x, z, rot}, '_fill_pct'[, '_reason']}`."""
    room_type: str
    solver_roles: tuple
    place_roles: tuple
    solve: Callable
    list_roles: tuple = ()
    one_free_roles: tuple = ()
    tier_order: tuple = ()
    purpose_order: tuple = ()
    band_cm: dict = field(default_factory=lambda: {'*': {}})
    # назначения, которые знает модель комнаты солвера (`planner.models.Room.purpose`); None — все назначения записи как есть
    # (спальня), () — ни одного (у прихожей назначение записи «hall» — не назначение солвера, проверка без него)
    solver_purposes: tuple | None = None


def lead_roles(room_type: str) -> tuple:
    import room_profile as RP
    return RP.lead(RP.load(room_type))


def profile_rules(room_type: str) -> tuple[tuple, bool, tuple]:
    """Правила витрины из профиля комнаты (данные, не код; hall-demo-01 этап 3): (ведущие роли, «достаточно любой ведущей» —
    `lead_rule: any`, у спальни `all` — нужны все; парные роли — `pair: true`: пронумерованное место расстановки «… 2» берёт товар
    своей роли, у спальни тумба и лампа)."""
    import room_profile as RP
    P = RP.load(room_type)
    return RP.lead(P), RP.lead_rule(P) == 'any', RP.pairs(P)


def needs_mesh(role: str) -> bool:
    """Нужна ли роли модель — по канону стратегий ассета (`rules/asset-strategies.json`): `hunyuan3d` — да; ковёр и зеркало
    (`procedural_plane`) рисуются плоскостью из фото — сторож модели и лента их не держат (Codex 06.11: от стратегии, не от списка)."""
    import asset_strategy as AS
    return AS.strategy(role) == 'hunyuan3d'


def neighbour_styles(style: str, path: str = STYLE_AXES) -> list:
    """Соседние стили — пары «легко спутать» паспорта осей стиля (`style-axes.json:confusable_pairs`, с источниками): запас
    предмета, когда в своём стиле товара с моделью нет. Порядок — порядок пар в файле."""
    doc = json.load(open(path, encoding='utf-8'))
    out = []
    for p in doc.get('confusable_pairs') or []:
        pair = p.get('pair') or []
        if style in pair:
            out += [x for x in pair if x != style and x not in out]
    return out


def base_role(role: str) -> str:
    return re.sub(r'\s+\d+$', '', role or '')


def _key(it) -> str | None:
    """Товар записи банка: `mid:eid` (как `sid` сборщика), иначе `sid`."""
    if not isinstance(it, dict):
        return None
    return f"{it['mid']}:{it['eid']}" if it.get('mid') and it.get('eid') else it.get('sid')


def role_spares(spec: Showcase, bank: list, rec: dict, roles=None, neighbours=neighbour_styles) -> dict:
    """Запас ролей солвера (None — все `solver_roles`; одно правило для всех ролей, T-20261106-77/4) сверх `alternates` своей
    записи: товары роли (состав и `alternates`) других записей банка — сперва своего стиля, потом соседних (`neighbour_styles`);
    внутри стиля — сначала та же комната и назначение, дальше порядок банка.
    → {роль: [(стиль, товар), …]} без повторов sid. Подходит ли товар (модель, размер, место) — решает `gate_items`."""
    style = rec.get('style') or ''
    order = [style] + [s for s in neighbours(style) if s != style]
    out = {}
    for role in spec.solver_roles if roles is None else roles:
        seen, rows = set(), []
        for st in order:
            cand = [r for r in bank if r is not rec and (r.get('style') or '') == st]
            cand.sort(key=lambda r: (r.get('room_id') != rec.get('room_id'), r.get('purpose') != rec.get('purpose')))
            for r in cand:
                for it in [v for k, v in (r.get('items') or {}).items() if base_role(k) == role] + list((r.get('alternates') or {}).get(role) or []):
                    sid = _key(it)
                    if sid and sid not in seen:
                        seen.add(sid)
                        rows.append((st, it))
        out[role] = rows
    return out


def load_bank(path: str) -> list:
    """Записи банка комнаты; нет файла — пусто (комната остаётся «скоро»), битый файл — громко."""
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


def _clean(xs) -> list:
    return [{k: v for k, v in x.items() if not k.startswith('_')} for x in xs or []]


def room_geo(spec: Showcase, room_id: str, path: str, reg: dict | None = None, extra: dict | None = None,
             layout_room: dict | None = None) -> dict | None:
    """Геометрия комнаты витрины в форме `data['room']` гостиной: w, d, title, проёмы, радиаторы (служебные `_why` сняты) и `kind`
    — тип зоны кадра (`CAM_ZONES` страницы; нет в реестре — тип комнаты). Подпись — имя и площадь реестра («Гостиная 14.4 м²»).
    `path` — файл чертежа адаптера, `extra` — общее с гостиной (вид из окна, потолок). `layout_room` — комната готовой расстановки
    банка (`bank_room`): есть — она вместо записи чертежа."""
    rec = layout_room or next((r for r in json.load(open(path, encoding='utf-8')).get('rooms') or []
                               if r.get('id') == room_id), None)
    if not rec or not rec.get('w') or not rec.get('d'):
        return None
    reg = reg or {}
    title = f"{reg.get('titleRu') or room_id} {reg['areaM2']} м²" if reg.get('areaM2') else (reg.get('titleRu') or room_id)
    # КОНТУР (hall-demo-01 этап 3): не прямоугольная комната (Г-образная прихожая) — вершины, см; без него витрина рисовала бы
    # прямоугольник w×d. Нет контура — поля нет (спальни побайтно прежние)
    return {'w': rec['w'], 'd': rec['d'], 'title': title, 'kind': reg.get('kind') or spec.room_type,
            'openings': _clean(rec.get('openings')), 'radiators': _clean(rec.get('radiators')),
            **({'contour': rec['contour']} if rec.get('contour') else {}), **(extra or {})}


# ОДНА РАССТАНОВКА НА ВСЕ СТИЛИ (T-20261105-32/4, решение ведущего «А»; как у гостиной demo-31 `demo_one_layout.py`):
# при переключении стиля та же комната, меняются товары. Место роли — её ЗОНА тем же расчётом, что подпись гостиной
# (`planner/zones.py:signature_xy`): ближайшая к центру стена + четверть комнаты. Опорный стиль — тот, с чьими зонами согласно
# больше всего ролей других стилей, при равенстве — первый по порядку витрины. Роль другого стиля в чужой зоне встаёт на место
# опорной (та же стена вплотную, тот же центр вдоль стены, поворот опорной; `one_free_roles` — по центру), если `planner.validate`
# комнаты не даёт НОВЫХ жёстких нарушений; не встала — своя позиция банка и строка в журнал. Роль в своей зоне не трогаем. Банк не
# переписывается. Правило — `rules/demo-layout.json` → <тип комнаты>; выключатель общий с гостиной (`DEMO_ONE_LAYOUT=0`).
def one_rule(spec: Showcase) -> dict:
    sys.path.insert(0, HERE)
    import demo_one_layout as _ONE
    return (_ONE.rules().get(spec.room_type) or {}) if _ONE.enabled() else {}


def _placed(spec: Showcase, art: dict) -> dict:
    return {k: v for k, v in (art or {}).items() if not k.startswith('_') and isinstance(v, dict) and v.get('x') is not None
            and v.get('w') and v.get('d') and base_role(k) in spec.place_roles}


def zone(W: float, D: float, x: float, z: float) -> str:
    """Зона центра: ближайшая стена (N: z=0, S: z=D, W: x=0, E: x=W) и четверть комнаты — как `signature_xy`."""
    d = {'N': z, 'S': D - z, 'W': x, 'E': W - x}
    return f"{min(d, key=d.get)}:{'N' if z < D / 2 else 'S'}{'W' if x < W / 2 else 'E'}"


def zones(spec: Showcase, art: dict) -> dict:
    W, D = art['_room']['w'], art['_room']['d']
    return {k: zone(W, D, v['x'], v['z']) for k, v in _placed(spec, art).items()}


def reference(spec: Showcase, arts: dict, order: list) -> str:
    """Опорный стиль: больше всех совпадений зон своих ролей с ролями других стилей; равенство — порядок витрины."""
    zs = {s: zones(spec, a) for s, a in arts.items()}
    score = {s: sum(zs[s][r] == zs[t].get(r) for t in zs if t != s for r in zs[s]) for s in zs}
    return max(order, key=lambda s: (score.get(s, -1), -order.index(s)))


def _ext(v: dict, rot: int) -> tuple[float, float]:
    """Размах по x и z при повороте (0/180 — ширина по x)."""
    return (v['w'], v['d']) if int(rot or 0) % 180 == 0 else (v['d'], v['w'])


def on_ref_place(own: dict, ref: dict, W: float, D: float, free: bool) -> dict:
    """Роль `own` на месте опорной `ref`: тот же поворот и центр вдоль стены, зазор до стены — как у опорной (свой габарит)."""
    rot = int(ref.get('rot') or 0)
    out = dict(own, rot=rot, x=ref['x'], z=ref['z'])
    if free:
        return out
    wall = zone(W, D, ref['x'], ref['z']).split(':')[0]
    (rx, rz), (ox, oz) = _ext(ref, rot), _ext(own, rot)
    if wall == 'N':
        out['z'] = round(ref['z'] - rz / 2 + oz / 2, 1)
    elif wall == 'S':
        out['z'] = round(ref['z'] + rz / 2 - oz / 2, 1)
    elif wall == 'W':
        out['x'] = round(ref['x'] - rx / 2 + ox / 2, 1)
    else:
        out['x'] = round(ref['x'] + rx / 2 - ox / 2, 1)
    return out


def hard_codes(spec: Showcase, art: dict, purpose: str | None) -> set:
    """Жёсткие нарушения расстановки комнаты по `planner.validate` (код|роли) — до и после переноса роли."""
    sys.path.insert(0, PLANNER)
    from planner.models import Item, Opening, Placement, Radiator, Room
    from planner.validate import validate
    r = art['_room']
    if spec.solver_purposes is not None and purpose not in spec.solver_purposes:
        purpose = None
    room = Room(width_cm=r['w'], depth_cm=r['d'], openings=[Opening(**o) for o in _clean(r.get('openings'))],
                radiators=[Radiator(**o) for o in _clean(r.get('radiators'))], room_type=spec.room_type, purpose=purpose,
                contour=r.get('contour'))
    ps = [Placement(role=k, x=v['x'], y=v['z'], rot=int(v.get('rot') or 0), elev_cm=v.get('elev') or 0,
                    item=Item(role=k, w_cm=v['w'], d_cm=v['d'], h_cm=v.get('h') or 60)) for k, v in _placed(spec, art).items()]
    return {f"{v.code}|{','.join(sorted(v.roles))}" for v in validate(room, ps).violations if v.severity.name == 'HARD'}


def one_layout(spec: Showcase, arts: dict, order: list, purposes: dict | None = None, free=None) -> tuple[dict, dict]:
    """`arts` — {стиль: готовая расстановка банка с `_room`} одной комнаты → (расстановки, отчёт `{ref, moved, kept}`).
    `moved` — [{style, role, from, to}], `kept` — [{style, role, why}] (роль не встала на место опорной). Комнаты разные
    (`_room` не совпал) — стиль не трогаем (`kept`, why «другая комната»). `free` — None: `spec.one_free_roles`."""
    free = spec.one_free_roles if free is None else free
    purposes = purposes or {}
    order = [s for s in order if s in arts]
    if len(order) < 2:
        return arts, {'ref': order[0] if order else None, 'moved': [], 'kept': []}
    ref = reference(spec, arts, order)
    ra = arts[ref]
    W, D = ra['_room']['w'], ra['_room']['d']
    rz = zones(spec, ra)
    out, moved, kept = dict(arts), [], []
    for s in order:
        if s == ref:
            continue
        a = arts[s]
        if (a['_room'].get('w'), a['_room'].get('d')) != (W, D):
            kept.append({'style': s, 'role': '*', 'why': 'другая комната'})
            continue
        cur = dict(a)
        base = hard_codes(spec, cur, purposes.get(s))
        for role, z in zones(spec, a).items():
            if role not in rz or rz[role] == z:
                continue
            cand = dict(cur, **{role: on_ref_place(cur[role], ra[role], W, D, base_role(role) in free)})
            new = hard_codes(spec, cand, purposes.get(s)) - base
            if new:
                kept.append({'style': s, 'role': role, 'why': sorted(new)})
                continue
            p, q = cur[role], cand[role]
            moved.append({'style': s, 'role': role, 'from': [p['x'], p['z'], int(p.get('rot') or 0), z],
                          'to': [q['x'], q['z'], int(q.get('rot') or 0), rz[role]]})
            cur = cand
        out[s] = cur
    return out, {'ref': ref, 'moved': moved, 'kept': kept}


def variant_id(room_id: str, style_id: str) -> str:
    """Номер варианта — `<комната>-<стиль>` (решение ведущего, onb-07 лог T-08): один на квартиру, ссылка `#v=` без комнаты."""
    return f'{room_id}-{style_id}'


# СТОРОЖ МОДЕЛИ ПРЕДМЕТА (T-20261105-51/2): в вариант идёт только товар, чья модель готова и выложена — иначе сцена рисует серую
# «коробку» (404 → заглушка `lib/viewer3d/viewer.ts`) или чужой меш. Проверку даёт сборка (`mesh_ok(sku) → ''` или причина);
# роли без модели по стратегии ассета (`needs_mesh`: ковёр, зеркало — плоскость по фото) сторож не трогает.
def _instances(role: str, art: dict | None) -> list:
    """Места роли в расстановке: сама роль и пронумерованные экземпляры («тумба прикроватная 2»)."""
    return [r for r in (art or {}) if not r.startswith('_') and isinstance(art[r], dict) and base_role(r) == role]


def _fits(spec: Showcase, art: dict, role: str, dm: dict, purpose: str | None) -> tuple[dict | None, list]:
    """Замена на месте прежнего товара: те же поворот, стена и центр вдоль стены, свой габарит (`on_ref_place`) → (новая
    расстановка, []) или (None, новые жёсткие нарушения). Без комнаты в расстановке — расстановку не трогаем."""
    if not isinstance((art or {}).get('_room'), dict):
        return art, []
    W, D = art['_room']['w'], art['_room']['d']
    out = dict(art)
    for r in _instances(role, art):
        p = art[r]
        if p.get('x') is None or not (p.get('w') and p.get('d')):
            continue
        out[r] = on_ref_place(dict(p, w=dm['w'], d=dm['d'], h=dm.get('h')), p, W, D, False)
    new = hard_codes(spec, out, purpose) - hard_codes(spec, art, purpose)
    return (None, sorted(new)) if new else (out, [])


def _in_band(spec: Showcase, role: str, dm: dict, purpose: str | None) -> bool:
    b = (spec.band_cm.get(purpose) or {}).get(role) or spec.band_cm['*'].get(role)
    return not b or b['lo'] <= (dm.get('w') or 0) <= b['hi']


def gate_items(spec: Showcase, rec: dict, art: dict | None, sku, dims_of, mesh_ok, spares: dict | None = None
               ) -> tuple[dict, dict | None, list, list, list]:
    """Товары записи через сторож модели → (товары, расстановка, замены, пустые роли, пропущенные с нерешённым разворотом).
    Роль без годной модели — следующий кандидат той же роли из `alternates` банка (по порядку банка), который встаёт на её
    место без новых жёстких нарушений; дальше — запас `spares` (`role_spares`, любая роль солвера: свой стиль, потом соседний;
    чужой товар ещё и в полосе размера назначения `band_cm`); нет такого — роль пустая с причиной. Замены — `{role, was, now,
    why[, style]}` (style — у товара соседнего стиля), пустые — `{role, why}`, нерешённые — `{role, msid, why}` (у сторожа есть
    `mesh_ok.note(sku)` → причина или ''; в журнал сборки)."""
    items = dict(rec.get('items') or {})
    swaps, empty, orient = [], [], []
    alts = rec.get('alternates') or {}
    own = rec.get('style') or ''
    note = getattr(mesh_ok, 'note', None)

    def noted(role, x):
        n = note(x) if note and x else ''
        if n:
            orient.append({'role': role, 'msid': x.get('msid'), 'why': n})
    for role in [r for r in list(items) if base_role(r) == r and r in spec.solver_roles and needs_mesh(r)]:
        s = sku(items, role)
        why = mesh_ok(s) if s else 'нет товара'
        if not why:
            noted(role, s)
            continue
        tried = []
        own_sids = {_key(a) for a in alts.get(role) or []} | {_key(items.get(role))}
        pool = [(own, a, False) for a in alts.get(role) or []] + [
            (st, a, True) for st, a in (spares or {}).get(role) or [] if _key(a) not in own_sids]
        for st, alt, far in pool:
            t = sku({role: alt}, role)
            w = mesh_ok(t) if t else 'нет товара'
            if not w:
                dm = dims_of({}, t, role)
                if dm.get('dims_unknown'):
                    w = 'размер не указан'
                elif far and not _in_band(spec, role, dm, rec.get('purpose')):
                    w = 'вне полосы размера'
                else:
                    a2, bad = _fits(spec, art, role, dm, rec.get('purpose'))
                    w = ('не встаёт: ' + ', '.join(bad)) if bad else ''
            if not w:
                swaps.append({'role': role, 'was': [s and s.get('sid'), s and s.get('name')], 'now': [t.get('sid'), t.get('name')],
                              'why': why, **({'style': st} if st != own else {})})
                art = a2
                noted(role, t)
                for k in [k for k in items if base_role(k) == role]:   # и пронумерованные строки банка («… 2») — тот же товар
                    items[k] = alt
                break
            tried.append(w)
        else:
            empty.append({'role': role, 'why': f'модель не готова ({why}); кандидатов {len(tried)}'
                                              + (f": {'; '.join(dict.fromkeys(tried))}" if tried else '')})
            for k in [k for k in items if base_role(k) == role]:
                items.pop(k)
    return items, art, swaps, empty, orient


def build_variant(spec: Showcase, rec: dict, geo: dict, sku, dims_of, style_id, hung=lambda n: False, decor_role=lambda r: False,
                  layout=None, mesh_ok=None, spares: dict | None = None, lead=None, lead_any: bool | None = None,
                  pairs=None) -> tuple[dict | None, dict | None]:
    """Запись банка → (вариант витрины, None) или (None, строка `incomplete_styles`). `sku(items, role)` и `dims_of(v, sku, role)`
    — функции сборки (`flat215_demo._sku`, `_dims_of`): товар и габарит из каталога, как у гостиной. `mesh_ok(sku)` — сторож
    модели (`gate_items`; None — без проверки): замены — в `mesh_swaps` варианта, пустые роли — в `missing_item` с причиной,
    пропущенные с нерешённым разворотом — в `orient_unresolved` (сборка снимает поле в журнал). `spares` — запас ролей солвера
    (`role_spares`), `lead` — ведущие роли, `lead_any` — достаточно любой из них, `pairs` — парные роли (None — из профиля,
    `profile_rules`): правило ALL — нет хотя бы одной ведущей, ANY — нет ни одной → вариант не публикуется. Предмет с подъёмом над
    полом (зеркало солвера прихожей, `elev`, см) несёт его в вариант — сцена вешает на стену (`fromDemo.ts`), не ставит на пол."""
    if lead is None or lead_any is None or pairs is None:
        p_lead, p_any, p_pairs = profile_rules(rec.get('room_type') or spec.room_type)
        lead = p_lead if lead is None else lead
        lead_any = p_any if lead_any is None else lead_any
        pairs = p_pairs if pairs is None else pairs
    lead, pairs = tuple(lead), tuple(pairs)
    items = rec.get('items') or {}
    style = rec.get('style') or ''
    sid = style_id(style)
    miss = {'style': style, 'room_id': rec.get('room_id')}
    if not sid:
        return None, {**miss, 'missing': ['стиль вне витрины']}
    skus, dims, unknown = {}, [], []
    art = layout if layout is not None else rec.get('layout')
    swaps, empty, orient = [], [], []
    if mesh_ok is not None:
        items, art, swaps, empty, orient = gate_items(spec, rec, art, sku, dims_of, mesh_ok, spares)
    # экземпляры ролей: товары записи и пронумерованные места готовой расстановки парной роли («тумба прикроватная 2» — товар базовой)
    roles = list(items) + [r for r in (art or {}) if not r.startswith('_') and r not in items and base_role(r) in items
                           and base_role(r) in pairs]
    for role in roles:
        if base_role(role) not in spec.place_roles:
            continue
        s = sku(items, role)
        if not s:
            continue
        dm = dims_of({}, s, role)
        if dm.get('dims_unknown'):
            unknown.append({'role': role, 'name': s.get('name')})
            continue
        skus[role] = (s, dm)
        if base_role(role) in spec.solver_roles:
            dims.append((role, dm['w'], dm['d'], dm['h']))
    art = art or spec.solve(geo, dims, rec.get('purpose'))
    objs = []
    for role, p in art.items():
        if role.startswith('_') or not isinstance(p, dict) or 'x' not in p or role not in skus:
            continue
        s, dm = skus[role]
        if hung(s.get('name')):
            s = dict(s, hung=True)
        objs.append({'role': role, 'x': round(p['x'], 1), 'y': round(p['z'], 1), 'rot': int(p.get('rot') or 0),
                     'w': dm['w'], 'd': dm['d'], 'h': dm['h'], 'dims_src': dm.get('dims_src'), 'sku': s,
                     'corner': False, 'corner_left': False, 'section': None, **({'elev': p['elev']} if p.get('elev') else {})})
    have = {base_role(o['role']) for o in objs}
    lost = [c for c in lead if c not in have]
    if lead_any and len(lost) < len(lead):   # ANY (прихожая — «любое хранение», `hall-composition.json:storage`)
        lost = []
    if lost:
        return None, {**miss, 'missing': lost + list(art.get('_reason') or []),
                      **({'mesh': [e for e in empty if e['role'] in lost]} if empty else {}),
                      **({'orient_unresolved': len(orient)} if orient else {})}
    decor = []
    lst = lambda r: decor_role(r) or base_role(r) in spec.list_roles   # noqa: E731
    for role in list(items) + [r for r in art if not r.startswith('_') and r not in items and lst(base_role(r))
                               and (base_role(r) == r or base_role(r) in pairs)]:
        if lst(role) or lst(base_role(role)):
            s = sku(items, role)
            if s:
                # ТОЛЬКО В СПИСКЕ (T-20261106-77/2): лампа на тумбе — строка списка и запрос фото, в 3D её нет (модели у ламп нет —
                # окно ставило бы её на тумбу пустым местом, ворота копий моделей `demo_rt` ждали её копию и стопорили публикацию)
                decor.append({'role': role, 'sku': s, **({'list_only': True} if base_role(role) in spec.list_roles else {})})
    return ({'id': variant_id(rec['room_id'], sid), 'title': (style or sid).capitalize(), 'style': style, 'style_id': sid,
             'room_id': rec['room_id'], 'purpose': rec.get('purpose'), 'fill_pct': art.get('_fill_pct'), 'items': objs,
             'decor': decor, 'dims_unknown': unknown, 'missing_item': empty, 'fill': [],
             **({'mesh_swaps': swaps} if swaps else {}), **({'orient_unresolved': orient} if orient else {})}, None)


def pick_records(spec: Showcase, bank: list, rooms: list, styles: list) -> list:
    """Одна запись на (комнату, стиль): только включённые комнаты, стили — опубликованные гостиной (ключ стиля — витрина, ADR-0330
    п.3), порядок — как у гостиной. Несколько записей одной ячейки — первая (банк упорядочивает сборщик)."""
    rank = lambda xs, x: xs.index(x) if x in xs else len(xs)   # noqa: E731
    out, seen = [], set()
    for st in styles:
        cand = [r for r in bank if r.get('room_id') in rooms and (r.get('style') or '') == st]
        # ячейка витрины: назначение и ступень цены по порядку (`purpose_order`, `tier_order`), при равных — порядок банка
        cand.sort(key=lambda r: (rank(spec.purpose_order, r.get('purpose')), rank(spec.tier_order, r.get('tier'))))
        for r in cand:
            key = (r.get('room_id'), st)
            if key not in seen:
                seen.add(key)
                out.append(r)
    return sorted(out, key=lambda r: rooms.index(r['room_id']))


def feed_row(role: str, it: dict, style: str | None, msid, mesh_ok, alive=lambda u: True) -> dict | None:
    """Товар комнаты → строка ленты замен (поля как у ленты гостиной). Только с фото, габаритами и годной моделью (правило
    владельца 01.09: в замену — то, что видно в 3D). `mesh_ok(sku) → ''` (годен) или причина — ТОТ ЖЕ сторож, что у предметов
    варианта (`flat215_demo.bedroom_mesh_gate` → `room_bindings.usable`, T-20261106-77 Д1). Роли, которым модель по канону не
    нужна (`needs_mesh`: ковёр, зеркало — плоскость из фото), сторожа не проходят и высоты не требуют."""
    needs = needs_mesh(role)
    if not it or not it.get('img') or not (it.get('w') and it.get('d') and (it.get('h') or not needs)):
        return None
    sid = f"{it.get('mid')}_{it.get('eid')}" if it.get('mid') and it.get('eid') else it.get('sid')
    m = msid(sid)
    if not sid or (needs and mesh_ok({'sid': sid, 'msid': m})) or not alive(it.get('img')):
        return None
    return {'name': it.get('name'), 'w': it.get('w'), 'd': it.get('d'), 'h': it.get('h'), 'price': it.get('price'),
            'img': it.get('img'), 'url': it.get('url'), 'shop': it.get('shop'), 'style': style or '',
            'styles': [style] if style else [], 'sid': sid, 'msid': m, 'src': 'set'}


def feeds(spec: Showcase, bank: list, catalog: dict, msid, mesh_ok, alive=lambda u: True) -> dict:
    """Ленты замен ролей комнаты: товары записей банка (со стилем записи) и их `alternates`, затем фото-каталог комнаты
    (`flat215_demo.bedroom_catalog`, без стиля — виден при снятом чипе «Только стиль»). Один товар — одна строка, стили копятся."""
    out: dict = {}
    have: dict = {}

    def put(role, it, style):
        b = base_role(role)
        if b not in spec.place_roles:
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


def bands(spec: Showcase, purposes: list) -> dict:
    """Полосы размера ролей комнаты для `rules.slot_band_cm` (ключ — роль): общие и по назначению первой включённой комнаты."""
    out = dict(spec.band_cm['*'])
    for p in purposes:
        for k, v in (spec.band_cm.get(p) or {}).items():
            out.setdefault(k, v)
    return out


# КЛЮЧ ЛЕНТЫ И ПОЛОСЫ — КОМНАТА + РОЛЬ (T-20261106-77, Codex): ленты и полосы были общими на роль, и роль, что есть в двух комнатах
# (ковёр), брала строки гостиной. Гостиная остаётся под голой ролью (данные побайтно прежние); другие комнаты — «<тип>:<роль>» для
# ленты и «<комната>:<роль>» для полосы. Страница ищет так же: `index.html:roomKeysOf` (блок ROOMKEY), /flat —
# `lib/configurator/demo-feeds.ts:roomFeedKey`
def room_key(room: str, role: str) -> str:
    return role if not room or room == 'living' else f'{room}:{role}'


def merge_room_feeds(feeds: dict, room_type: str, room_feeds: dict) -> dict:
    """Ленты комнаты — в общий словарь под её ключами; строки гостиной (голые роли) не трогаются. → `feeds`."""
    for role, rows in room_feeds.items():
        feeds[room_key(room_type, role)] = rows
    return feeds


def room_bands(spec: Showcase, bank: list, rooms) -> dict:
    """Полосы размера по комнатам: «<комната>:<роль>» → полоса, по назначению своей комнаты — тому, что берёт витрина
    (`pick_records`: первое по `purpose_order` среди записей комнаты)."""
    rank = lambda x: spec.purpose_order.index(x) if x in spec.purpose_order else len(spec.purpose_order)   # noqa: E731
    out: dict = {}
    for rid in rooms:
        purpose = min((r.get('purpose') for r in bank if r.get('room_id') == rid and r.get('purpose')), key=rank, default=None)
        out.update({room_key(rid, k): v for k, v in bands(spec, [purpose] if purpose else []).items()})
    return out
