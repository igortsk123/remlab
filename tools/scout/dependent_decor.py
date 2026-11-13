"""ЗАВИСИМЫЙ ДЕКОР ПАСПОРТА — ОБЩИЙ КОНТРАКТ ДЛЯ /demo И ТУРОВ (T-20261112-101; Codex 12.11 — `_intake/codex/2026-11-12-t101-lamp-contract-answer.md`).

Декор, у которого место задаёт паспорт комнаты (`services/planner-solver/rules/room-templates/living.json`), идёт в данные варианта
строкой `decor` `{role, strategy, place, sku}`; место считает ОДИН решатель зависимых мест `planner/dependents.py:resolve` на носителях
этого варианта. Общее здесь — носители из предметов варианта (`variant_carriers`), кандидаты товара того же стиля (`candidates`) и
строка места (`place_of`). Политики товара — свои: люстра (`chandelier.py`) висит в присланной точке, высота по мешу; лампа (этот
модуль, `lamp_*`) СТОИТ НА НОСИТЕЛЕ: место в данных — исходный снимок, сцена пересчитывает его от текущего комода
(`lib/configurator/carrier-decor.ts`) по `local` и `fit` — передвинули, повернули или заменили комод, лампа идёт за ним; нет комода
или не влезает — в сцене нет, в цене есть.

ЛАМПА — ТОЛЬКО С МОДЕЛЬЮ (Codex 12.11, как люстра — «ничего в цене без 3D»): лампа набора без годной модели или не влезающая на комод
— следующая лампа того же стиля; ни одной — строки нет, громко (WARN).
ЛАМПА ПО РАЗМЕРУ КОМОДА (T-20261113-12, владелец TG 1406): норма `distances_cm.dependents.table_lamp_on_surface` — на столешнице
целиком ОСНОВАНИЕ (нижний срез модели, `mesh_base_units`; нет — весь габарит), абажур не свисает в проход; из всех годных ламп
стиля берём лучшую по пропорции к ЭТОМУ комоду (`lamp_score`), при равенстве — свою лампу набора, затем по артикулу.
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


def variant_carriers(objs: list, mapping: dict, caps=None) -> list:
    """Предметы варианта витрины (`role, x, y, rot, w, d, h`, см, центр, оси комнаты; `sku.name` — для «подвесной») → носители для
    решателя: `Placement` с `slot_instance_id` «<место паспорта>#n» (`carrier_objs`). Роли вне `mapping` не берём.
    `caps(o)` → замеры поверхностей предмета (`{'foot_h_cm': …}` — верх матраса у изножья по мешу) или None."""
    out = []
    for sid, o in carrier_objs(objs, mapping):
        b = base_role(o['role'])
        out.append(Placement(role=b, x=float(o['x']), y=float(o['y']), rot=float(o.get('rot') or 0),
                             item=Item(role=b, w_cm=float(o['w']), d_cm=float(o['d']),
                                       h_cm=float(o['h']) if o.get('h') else None, name=(o.get('sku') or {}).get('name'),
                                       caps=(caps(o) if caps else None) or {}),
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
# ЗАВИСИМЫЙ ДЕКОР ПО ТИПУ КОМНАТЫ (T-20261113-22, владелец TG 1623 «всё видно»): паспорт, носители (роль предмета варианта → место
# паспорта), место лампы (группа, вариант, id) и роль её носителя. Спальня — каталог шаблонов `bedroom-catalog.json`: лампа на КАЖДОЙ
# тумбе (`light.bedside`, symmetry pair — не больше ламп набора), покрывало в ногах кровати и шторы (`textile_abstract.ROOM_ROLES`)
ROOM_DEPS = {
    'living': {'doc': 'living', 'carriers': LAMP_CARRIERS, 'lamp': LAMP_PLACE + (LAMP_DEP,), 'lamp_carrier': 'комод'},
    'bedroom': {'doc': 'bedroom-catalog', 'carriers': {'тумба прикроватная': 'sleep.ns', 'кровать': 'sleep.bed'},
                'lamp': ('light', 'bedside', 'light.lamp'), 'lamp_carrier': 'тумба прикроватная'},
}
FRONT_BAND = (0.08, 0.30)       # верх у изножья: полоса глубины от лица кровати внутрь (мимо спинки-изножья и изголовья)
FRONT_WIDTH = (0.20, 0.80)      # и полоса ширины по центру — мимо боковых спинок и царг (кровать-софа «Кейси» — спинки вдоль всей длины)
FRONT_TOP_PCT = 100             # верх матраса — плоскость из немногих вершин: перцентиль ниже 100 её недобирает (замер 13.11:
                                # «Силини» матрас 0,54 высоты, p95 — 0,39 → покрывало уходило в матрас); выбросы снимает полоса
FIT_REF = 'distances_cm.dependents.table_lamp_on_surface'
BASE_SLICE = 0.03                               # основание лампы — нижние 3 % высоты модели (замер банка 13.11: 10–34 см, сотни вершин)
BASE_MIN_VERTS = 50                             # меньше вершин в срезе — основанию не верим, опора = весь габарит


def is_lamp(role: str | None) -> bool:
    return base_role(role) == LAMP_ROLE


def lamp_rule() -> dict:
    v = RT.rule_value(FIT_REF)
    if v is RT._MISSING:
        raise KeyError(f'нет нормы {FIT_REF} в occupancy.json')
    return v


def surface_fit(item: Item | None) -> dict:
    """Норма лампы (`occupancy.json`) и её опора — числа, по которым сцена заново проверяет лампу на текущем комоде
    (`carrier-decor.ts:onCarrier`, формула — `dependents.lamp_on_top`)."""
    v = lamp_rule()
    bw, bd = DEP.lamp_base(item) if item is not None else (None, None)
    return {'edge_clear_cm': v['edge_clear_cm'], 'shade_overhang_front_cm': v['shade_overhang_front_cm'],
            **({'base_w_cm': round(bw, 1), 'base_d_cm': round(bd, 1)} if bw else {})}


def mesh_base_units(verts) -> tuple | None:
    """Основание по модели: размах нижнего среза (`BASE_SLICE` высоты) по Ш и Г в единицах меша — вершины в канонической
    ориентации (x — ширина, y — высота, z — глубина, как `flat215_demo._mesh_extents`). Мало вершин в срезе — None."""
    import numpy as np
    v = np.asarray(verts, dtype=float)
    if v.ndim != 2 or len(v) < BASE_MIN_VERTS:
        return None
    lo, hi = v[:, 1].min(), v[:, 1].max()
    sl = v[v[:, 1] <= lo + BASE_SLICE * (hi - lo)]
    if len(sl) < BASE_MIN_VERTS:
        return None
    return float(np.ptp(sl[:, 0])), float(np.ptp(sl[:, 2]))


def mesh_front_top(verts) -> float | None:
    """Верх предмета у ЛИЦА (кровать — матрас у изножья) долей высоты модели: вершины в канонической ориентации (x — ширина, y — высота,
    z — глубина, лицо +Z, `scene_mesh.py`); полоса `FRONT_BAND` глубины от лица внутрь × `FRONT_WIDTH` ширины по центру, перцентиль
    `FRONT_TOP_PCT`. Мало вершин — None."""
    import numpy as np
    v = np.asarray(verts, dtype=float)
    if v.ndim != 2 or len(v) < BASE_MIN_VERTS:
        return None
    zlo, zhi = v[:, 2].min(), v[:, 2].max()
    ylo, yhi = v[:, 1].min(), v[:, 1].max()
    if zhi - zlo <= 1e-6 or yhi - ylo <= 1e-6:
        return None
    xlo, xhi = v[:, 0].min(), v[:, 0].max()
    a, b = zhi - FRONT_BAND[1] * (zhi - zlo), zhi - FRONT_BAND[0] * (zhi - zlo)
    l, r = xlo + FRONT_WIDTH[0] * (xhi - xlo), xlo + FRONT_WIDTH[1] * (xhi - xlo)
    band = v[(v[:, 2] >= a) & (v[:, 2] <= b) & (v[:, 0] >= l) & (v[:, 0] <= r)]
    if len(band) < BASE_MIN_VERTS:
        return None
    return float((np.percentile(band[:, 1], FRONT_TOP_PCT) - ylo) / (yhi - ylo))


def base_cm(it: dict, ext, units) -> tuple:
    """Основание в см тем же масштабом, что габарит лампы по мешу (`mesh_dims`): бо́льшая сторона плана меша = max(Ш, Г) карточки;
    не больше габарита карточки. Нет меша или среза — (None, None): опора = весь габарит."""
    if not units or not isinstance(ext, (list, tuple)) or min(ext) <= 1e-6 or min(units) <= 1e-6:
        return None, None
    w, d = float(it['w']), float(it['d'])
    k = max(w, d) / max(ext[0], ext[2])
    return round(min(units[0] * k, w), 1), round(min(units[1] * k, d), 1)


def lamp_score(item: Item, car: dict | None) -> float:
    """Мягкий штраф пропорции лампы к комоду (меньше — лучше; норма `table_lamp_on_surface`, гипотеза): доля основания от верха
    сверх `base_share_of_top_soft`, ширина абажура вне 0,25–⅔ ширины комода, высота вне 0,55–0,90 высоты комода (долями)."""
    if not car:
        return 0.0
    v = lamp_rule()
    W, D, H = float(car.get('w') or 0), float(car.get('d') or 0), float(car.get('h') or 0)

    def out(x, lo_hi):
        lo, hi = lo_hi
        return (lo - x) if x < lo else (x - hi) if x > hi else 0.0
    bw, bd = DEP.lamp_base(item)
    pen = max(0.0, bw * bd / (W * D) - v['base_share_of_top_soft']) if W and D else 0.0
    pen += out(item.w_cm / W, v['shade_w_to_top_w']) if W else 0.0
    pen += out(float(item.h_cm or 0) / H, v['h_to_carrier_h']) if H and item.h_cm else 0.0
    return round(pen, 4)


def lamp_solve(objs: list, room_wd: tuple, item: Item | None, room_type: str = 'living', n: int = 1):
    """Место лампы решателем паспорта на носителях варианта → `dependents.Result`: гостиная — `light.lamp#0` на `light.dresser#0`,
    спальня — по лампе на каждую тумбу (`light.lamp#k` на `sleep.ns#k`), не больше `n` ламп набора."""
    cfg = ROOM_DEPS[room_type]
    g, v, pid = cfg['lamp']
    places = [p for p in RT._variant_places(RT.load(cfg['doc']), g, v) if p['kind'] != 'dependent' or p['id'] == pid]
    room = Room(width_cm=float(room_wd[0]), depth_cm=float(room_wd[1]), ceiling_cm=DEFAULT_CEILING_CM)
    return DEP.resolve(places, variant_carriers(objs, cfg['carriers']), room, items={pid: item} if item else {}, counts={pid: n})


def carrier_lift_cm(objs: list, parent: str, room_type: str = 'living') -> float:
    """Подъём подвесного носителя над полом (`draft_render.hung_lift_cm` ↔ `scene-extras.ts:hungLiftCm`): верх комода — низ + корпус."""
    import draft_render as DR
    o = dict(carrier_objs(objs, ROOM_DEPS[room_type]['carriers'])).get(parent)
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


def lamp_pick(sets: list, idx: int, objs: list, room_wd: tuple, model, base=None) -> tuple:
    """Лампа на комоде гостиной → (товар, место, журнал) — `lamp_pick_all` с одним местом."""
    it, pls, why = lamp_pick_all(sets, idx, objs, room_wd, model, base)
    return it, (pls[0] if pls else None), why


def lamp_pick_all(sets: list, idx: int, objs: list, room_wd: tuple, model, base=None, room_type: str = 'living',
                  n: int = 1) -> tuple:
    """→ (товар банка, место решателя `Placement`, журнал отказов). `model(it)` → (габариты меша или иное «да», или None; причина отказа);
    `base(it)` → основание по модели в единицах меша (`mesh_base_units`) или None. ВСЕ лампы стиля (набор, затем банк того же стиля):
    без ширины и глубины, без модели или не влезает на комод (`FIT_FAIL`) — мимо; из годных — лучшая по пропорции к комоду
    (`lamp_score`), при равенстве — своя лампа набора, затем по артикулу. Отказ по комнате (комода нет) — (None, None, журнал).
    Высоты нет в карточке (у трети ламп банка) — по мешу тем же масштабом, что у люстры (`mesh_dims`); тогда товар — копия с этой высотой."""
    why, ok = [], []
    cfg = ROOM_DEPS[room_type]
    pid = cfg['lamp'][2]
    car = dict(carrier_objs(objs, cfg['carriers'])).get(f"{cfg['carriers'][cfg['lamp_carrier']]}#0")
    for j, role, it in candidates(sets, idx, is_lamp):
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
        bw, bd = base_cm(it, ext, base(it) if base else None)
        item = Item(role=LAMP_ROLE, w_cm=float(it['w']), d_cm=float(it['d']), h_cm=float(it['h']), base_w_cm=bw, base_d_cm=bd)
        res = lamp_solve(objs, room_wd, item, room_type, n)
        if not res.ok:
            why.append(f"{name}: решатель {res.reject['code']} — {res.reject['message']}")
            if res.reject['code'] == FIT_FAIL:
                continue
            return None, None, why
        pls = sorted((p for p in res.placements if p.slot_instance_id.startswith(f'{pid}#')),
                     key=lambda p: int(p.slot_instance_id.split('#')[1]))
        if not pls:
            why.append(f'{name}: решатель не дал места')
            return None, None, why
        ok.append((lamp_score(item, car), j != idx, f"{it['mid']}_{it['eid']}", it, pls))
    if not ok:
        return None, None, why
    best = min(ok, key=lambda t: t[:3])
    return best[3], best[4], why


def lamp_row(pl: Placement, objs: list, sku: dict, room_type: str = 'living', role: str = LAMP_ROLE) -> dict:
    """Строка декора лампы: место решателя + носитель (роль и номер среди предметов роли), норма лампы и её опора для пересчёта сценой;
    низ — верх носителя с подъёмом подвесного (`carrier_lift_cm`). `role` — роль строки набора («лампа 2» — вторая тумба)."""
    parent = pl.parent_slot_instance_id
    place = place_of(pl, round(pl.elev_cm + carrier_lift_cm(objs, parent, room_type), 2))
    place['carrier'] = {'role': ROOM_DEPS[room_type]['lamp_carrier'], 'ordinal': int(parent.split('#')[1])}
    place['fit'] = surface_fit(pl.item)
    return {'role': role, 'strategy': LAMP_STRATEGY, 'place': place, 'sku': sku}
