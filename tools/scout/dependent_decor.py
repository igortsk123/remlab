"""ЗАВИСИМЫЙ ДЕКОР ПАСПОРТА — ОБЩИЙ КОНТРАКТ ДЛЯ /demo И ТУРОВ (T-20261112-101; Codex 12.11 — `_intake/codex/2026-11-12-t101-lamp-contract-answer.md`).

Декор, у которого место задаёт паспорт комнаты (`services/planner-solver/rules/room-templates/living.json`), идёт в данные варианта
строкой `decor` `{role, strategy, place, sku}`; место считает ОДИН решатель зависимых мест `planner/dependents.py:resolve` на носителях
этого варианта. Общее здесь — носители из предметов варианта (`variant_carriers`), кандидаты товара того же стиля (`candidates`) и
строка места (`place_of`). Политики товара — свои: люстра (`chandelier.py`) висит в присланной точке, высота по мешу; лампа (этот
модуль, `lamp_*`) СТОИТ НА НОСИТЕЛЕ: место в данных — исходный снимок, сцена пересчитывает его от текущего комода
(`lib/configurator/carrier-decor.ts`) по `local` и `fit` — передвинули, повернули или заменили комод, лампа идёт за ним; нет комода
или не влезает — в сцене нет, в цене есть.

ЛАМПА — ТОЛЬКО С МОДЕЛЬЮ (Codex 12.11, как люстра — «ничего в цене без 3D»): лампа набора без годной модели или не влезающая на комод
по норме поверхности (`distances_cm.dependents.surface_decor`: отступ от края, ≤ 20 % столешницы) — следующая лампа того же стиля;
ни одной — строки нет, громко (WARN).
"""
import os
import re
import sys
from types import SimpleNamespace

_SOLVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'services', 'planner-solver')
if _SOLVER not in sys.path:
    sys.path.insert(0, _SOLVER)
from planner import dependents as DEP  # noqa: E402
from planner import room_templates as RT  # noqa: E402
from planner.models import Item, Placement, Room  # noqa: E402

FIT_FAIL = 'FIT_FAIL'               # отказ решателя по товару — пробуем следующий; прочие — по комнате (носителя нет и т.п.)
DEFAULT_CEILING_CM = 270.0          # как `contracts/apartment.ts:DEFAULT_CEILING_CM`


def base_role(role: str | None) -> str:
    """Роль без номера экземпляра: «диван 2» → «диван», «стол обеденный» — целиком."""
    return re.sub(r'\s+\d+$', '', str(role or '').strip())


def carrier_objs(objs: list, mapping: dict) -> list:
    """Предметы варианта, годные в носители: [(«<место паспорта>#n», предмет)], n — порядок предметов места в варианте."""
    out, seen = [], {}
    for o in objs or []:
        role = str(o.get('role') or '').strip()
        pid = mapping.get(role) or mapping.get(base_role(role))
        if not pid or not o.get('w') or not o.get('d'):
            continue
        n = seen.get(pid, 0)
        seen[pid] = n + 1
        out.append((f'{pid}#{n}', o))
    return out


def variant_carriers(objs: list, mapping: dict) -> list:
    """Предметы варианта витрины (`role, x, y, rot, w, d, h`, см, центр, оси комнаты; `sku.name` — для «подвесной») → носители для
    решателя: `Placement` с `slot_instance_id` «<место паспорта>#n» (`carrier_objs`). Роли вне `mapping` не берём."""
    out = []
    for sid, o in carrier_objs(objs, mapping):
        b = base_role(o['role'])
        out.append(Placement(role=b, x=float(o['x']), y=float(o['y']), rot=float(o.get('rot') or 0),
                             item=Item(role=b, w_cm=float(o['w']), d_cm=float(o['d']),
                                       h_cm=float(o['h']) if o.get('h') else None, name=(o.get('sku') or {}).get('name')),
                             slot_instance_id=sid))
    return out


def candidates(sets: list, idx: int, is_role) -> list:
    """Товар роли из набора `idx`, затем из других наборов ТОГО ЖЕ СТИЛЯ по порядку банка (после набора, по кругу); артикулы — без
    повторов. → [(номер набора, роль, товар)]."""
    style = (sets[idx] or {}).get('style')
    order = [idx] + [(idx + k) % len(sets) for k in range(1, len(sets))]
    out, seen = [], set()
    for j in order:
        s = sets[j] or {}
        if j != idx and s.get('style') != style:
            continue
        for role, it in (s.get('items') or {}).items():
            if not is_role(role) or not it or not it.get('mid') or not it.get('eid'):
                continue
            sid = f"{it['mid']}_{it['eid']}"
            if sid not in seen:
                seen.add(sid)
                out.append((j, role, it))
    return out


def place_of(pl: Placement, bottom_cm: float | None = None) -> dict:
    """Место решателя → `place` строки декора: точка и низ (оси комнаты, см), экземпляр места и — у зависимого от носителя — носитель,
    точка крепления и поза в осях носителя (штатный IR `planner/models.py:Placement`)."""
    out = {'x': pl.x, 'y': pl.y, 'bottom_cm': pl.elev_cm if bottom_cm is None else bottom_cm, 'slot_instance_id': pl.slot_instance_id}
    if pl.parent_slot_instance_id:
        out['parent_slot_instance_id'] = pl.parent_slot_instance_id
    if pl.anchor is not None:
        out['anchor'] = {k: v for k, v in pl.anchor.model_dump().items() if v is not None and v is not False}
    if pl.local is not None:
        out['local'] = {'dx': pl.local.dx or 0.0, 'dy': pl.local.dy or 0.0}
    return out


# ───────────────────────── лампа на комоде ─────────────────────────

LAMP_ROLE = 'лампа'
LAMP_STRATEGY = 'carrier_surface'
LAMP_PLACE = ('light', 'dresser_lamp')          # группа и вариант паспорта гостиной: комод + лампа на нём
LAMP_CARRIERS = {'комод': 'light.dresser'}      # роль предмета варианта → место-носитель паспорта
LAMP_DEP = 'light.lamp'                         # зависимое место лампы
FIT_REF = 'distances_cm.dependents.surface_decor'


def is_lamp(role: str | None) -> bool:
    return base_role(role) == LAMP_ROLE


def surface_fit() -> dict:
    """Норма поверхности (`occupancy.json`) — числа, по которым сцена заново проверяет лампу на текущем комоде."""
    v = RT.rule_value(FIT_REF)
    if v is RT._MISSING:
        raise KeyError(f'нет нормы {FIT_REF} в occupancy.json')
    return {k: v[k] for k in ('edge_inset_min_cm', 'edge_inset_over_half_base_cm', 'max_share_of_top')}


def lamp_solve(objs: list, room_wd: tuple, item: Item | None):
    """Место лампы решателем паспорта на комоде варианта → `dependents.Result` (место `light.lamp#0` на `light.dresser#0`)."""
    places = RT._variant_places(RT.load('living'), *LAMP_PLACE)
    room = Room(width_cm=float(room_wd[0]), depth_cm=float(room_wd[1]), ceiling_cm=DEFAULT_CEILING_CM)
    return DEP.resolve(places, variant_carriers(objs, LAMP_CARRIERS), room, items={LAMP_DEP: item} if item else {})


def carrier_lift_cm(objs: list, parent: str) -> float:
    """Подъём подвесного носителя над полом (`draft_render.hung_lift_cm` ↔ `scene-extras.ts:hungLiftCm`): верх комода — низ + корпус."""
    import draft_render as DR
    o = dict(carrier_objs(objs, LAMP_CARRIERS)).get(parent)
    if o is None or o.get('elev'):
        return float((o or {}).get('elev') or 0)
    sku = o.get('sku') or {}
    item = SimpleNamespace(name=sku.get('name'), h_cm=o.get('h'))
    return float(DR.hung_lift_cm(SimpleNamespace(role=base_role(o['role']), hung=sku.get('hung'), item=item)))


def mesh_dims(ext, plan_cm: float) -> dict | None:
    """Габарит в сцене по мешу (Ш, В, Г в единицах меша): один масштаб, наибольшая сторона плана = `plan_cm` (у люстры — диаметр,
    у лампы — бо́льшая из ширины и глубины карточки)."""
    if not ext or not isinstance(ext, (list, tuple)) or not plan_cm or min(ext) <= 1e-6:
        return None
    ex, ey, ez = ext
    k = plan_cm / max(ex, ez)
    return {'w': round(ex * k, 1), 'd': round(ez * k, 1), 'h': round(ey * k, 1)}


def lamp_pick(sets: list, idx: int, objs: list, room_wd: tuple, model) -> tuple:
    """→ (товар банка, место решателя `Placement`, журнал отказов). `model(it)` → (габариты меша или иное «да», или None; причина отказа).
    Лампа набора, затем лампы того же стиля: без ширины и глубины, без модели или не влезает на комод (`FIT_FAIL`) — следующая; отказ
    по комнате (комода нет) — (None, None, журнал). Высоты нет в карточке (у трети ламп банка) — по мешу тем же масштабом, что у люстры
    (`mesh_dims`); тогда товар — копия с этой высотой."""
    why = []
    for _j, role, it in candidates(sets, idx, is_lamp):
        name = it.get('name') or role
        if not (it.get('w') and it.get('d')):
            why.append(f'{name}: размер не указан')
            continue
        ext, bad = model(it)
        if bad:
            why.append(f'{name}: {bad}')
            continue
        if not it.get('h'):
            h = (mesh_dims(ext, max(float(it['w']), float(it['d']))) or {}).get('h')
            if not h:
                why.append(f'{name}: высоты нет ни в карточке, ни у модели')
                continue
            it = {**it, 'h': h}
        res = lamp_solve(objs, room_wd, Item(role=LAMP_ROLE, w_cm=float(it['w']), d_cm=float(it['d']), h_cm=float(it['h'])))
        if not res.ok:
            why.append(f"{name}: решатель {res.reject['code']} — {res.reject['message']}")
            if res.reject['code'] == FIT_FAIL:
                continue
            return None, None, why
        (pl,) = [p for p in res.placements if p.slot_instance_id.startswith(f'{LAMP_DEP}#')]
        return it, pl, why
    return None, None, why


def lamp_row(pl: Placement, objs: list, sku: dict) -> dict:
    """Строка декора лампы: место решателя + носитель (роль и номер среди предметов роли), норма поверхности для пересчёта сценой;
    низ — верх комода с подъёмом подвесного (`carrier_lift_cm`)."""
    parent = pl.parent_slot_instance_id
    place = place_of(pl, round(pl.elev_cm + carrier_lift_cm(objs, parent), 2))
    place['carrier'] = {'role': 'комод', 'ordinal': int(parent.split('#')[1])}
    place['fit'] = surface_fit()
    return {'role': LAMP_ROLE, 'strategy': LAMP_STRATEGY, 'place': place, 'sku': sku}
