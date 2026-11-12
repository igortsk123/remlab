"""ЛЮСТРА ГОСТИНОЙ ИЗ НАБОРА (T-20261112-66, план living-full-01 П1.6 «ничего в цене без 3D»).

Люстра есть в каждом наборе гостиной банка, но витрина её не выгружала — ни в цене, ни в 3D (отчёт T-64). Теперь она идёт
строкой декора варианта со стратегией `ceiling_over`, а МЕСТО ей даёт тот же решатель паспорта, что всем зависимым местам
(`services/planner-solver/planner/dependents.py:resolve`, место `ceiling.chandelier` паспорта `rules/room-templates/living.json`,
условие директора 12.11): центр ковра зоны отдыха, нет ковра — рамки зоны; низ — по норме
`distances_cm.mounting.chandelier`. Сцена рисует люстру в присланной точке и своего расчёта не держит.

ВЫСОТА В СЦЕНЕ — ПО МЕШУ, А НЕ ПО КАТАЛОГУ. У подвесных высота карточки — только корпус (Arte Lamp A1623LM: 32 см), а меш снят с
фото вместе со шнуром или цепью. Сцена тянет модель до Ш×Г×В (`meshes.ts:placeMesh`), и каталожная высота сплющила бы люстру
втрое. Поэтому масштаб один на все оси: наибольшая сторона плана меша = диаметр товара (у люстр в каталоге `dia`), высота — из
пропорций меша.

ПОДВЕС УКОРАЧИВАЕТСЯ, КАК В ЖИЗНИ (менеджер common 12.11): шнур и цепь регулируются, поэтому решателю идёт товар с высотой
«как повешен» — меш, но не длиннее потолок − норма низа (`drop_cm`); лишний шнур уходит выше потолка. Следующая люстра того же
стиля — только если не влезает сам КОРПУС (потолок − корпус по каталогу ниже нормы) или решатель отказал местом (`FIT_FAIL`).
Отказ по комнате (низкий потолок, нет носителей зоны) — люстры нет ни в цене, ни в 3D (не «в цене без 3D»).
"""
import os
import sys

_SOLVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'services', 'planner-solver')
if _SOLVER not in sys.path:
    sys.path.insert(0, _SOLVER)
from planner import dependents as DEP  # noqa: E402
from planner import room_templates as RT  # noqa: E402
from planner.models import Item, Room  # noqa: E402

import dependent_decor as DD  # noqa: E402  (общий контракт зависимого декора паспорта, T-20261112-101)

ROLE = 'люстра'
STRATEGY = 'ceiling_over'
DEFAULT_CEILING_CM = 270.0          # как `contracts/apartment.ts:DEFAULT_CEILING_CM` (комната без потолка в реестре)
NORM = 'distances_cm.mounting.chandelier'
PLACE = ('ceiling', 'chandelier_seating')   # группа и вариант паспорта гостиной: люстра над зоной отдыха
# ПЕРЕХОДНИК «ВАРИАНТ ВИТРИНЫ → НОСИТЕЛИ» ДЛЯ ОДНОЙ ЗОНЫ: роль предмета → место паспорта (группа seating `living.json`).
# Полный переходник всех мест — T-20261112-69 (рабочий 4), этот потом им заменим
_SEATING = {'диван': 'seating.sofa', 'диван 2': 'seating.sofa2', 'столик': 'seating.coffee', 'ковёр': 'seating.rug',
            'кресло': 'seating.armchair'}
FIT_FAIL = 'FIT_FAIL'               # отказ решателя по товару (длинная) — пробуем следующую люстру; прочие — по комнате


def base_role(role: str | None) -> str:
    return str(role or '').split(' ')[0]


def is_role(role: str | None) -> bool:
    return base_role(role) == ROLE


def bottom_min_cm() -> float:
    """Наименьшая высота низа люстры над полом, см — норма паспорта; нет в правилах — исключение (своего числа нет)."""
    v = RT.rule_value(NORM + '.bottom_min')
    if v is RT._MISSING:
        raise KeyError(f'нет нормы {NORM}.bottom_min в occupancy.json')
    return float(v)


def diameter(it: dict) -> float | None:
    """Диаметр товара, см: `dia` карточки, иначе бо́льшая из ширины и глубины."""
    d = it.get('dia') or max(it.get('w') or 0, it.get('d') or 0)
    return float(d) if d and d > 0 else None


def hang_dims(ext, dia: float) -> dict | None:
    """Габарит в сцене по мешу (Ш, В, Г в единицах меша): один масштаб, наибольшая сторона плана = диаметр (`DD.mesh_dims`, общее с лампой)."""
    return DD.mesh_dims(ext, dia)


def body_h(it: dict, dims: dict) -> float:
    """Высота корпуса, см: каталожная (у подвесных — без шнура); нет в карточке — весь меш (строже)."""
    return float(it.get('h') or dims['h'])


def fits(body_cm: float, ceiling_cm: float, bottom_min: float) -> bool:
    """Корпус влезает: при самом коротком подвесе низ (потолок − корпус) не ниже нормы."""
    return ceiling_cm - body_cm >= bottom_min


def drop_cm(dims: dict, ceiling_cm: float, bottom_min: float) -> float:
    """Высота «как повешена»: весь меш, но подвес укорочен так, чтобы низ был не ниже нормы."""
    return round(min(dims['h'], ceiling_cm - bottom_min), 1)


def carriers_from_variant(objs: list) -> list:
    """Предметы варианта витрины → носители зоны отдыха для решателя (общий `dependent_decor.variant_carriers`, T-20261112-101)."""
    return DD.variant_carriers(objs, _SEATING)


def solve(objs: list, room_wd: tuple, ceiling_cm: float, item: Item | None):
    """Место люстры решателем паспорта на носителях варианта → `dependents.Result` (одно место `ceiling.chandelier#0`)."""
    places = RT._variant_places(RT.load('living'), *PLACE)   # места варианта группы — как `compile_level` разворачивает
    room = Room(width_cm=float(room_wd[0]), depth_cm=float(room_wd[1]), ceiling_cm=ceiling_cm)
    return DEP.resolve(places, carriers_from_variant(objs), room, items={f'{PLACE[0]}.chandelier': item} if item else {})


def candidates(sets: list, idx: int) -> list:
    """Люстра набора, затем люстры других наборов ТОГО ЖЕ СТИЛЯ по порядку банка (общий `dependent_decor.candidates`)."""
    return DD.candidates(sets, idx, is_role)


def pick(sets: list, idx: int, objs: list, room_wd: tuple, ceiling_cm: float | None, model) -> tuple:
    """→ (товар банка, габарит сцены, место решателя `Placement`, журнал отказов). `model(it)` → (габариты меша или None,
    причина отказа). Ничего не подошло или решатель отказал по комнате — (None, None, None, журнал)."""
    ceil = float(ceiling_cm or DEFAULT_CEILING_CM)
    low = bottom_min_cm()
    why = []
    for j, role, it in candidates(sets, idx):
        name = it.get('name') or role
        dia = diameter(it)
        if not dia:
            why.append(f'{name}: нет диаметра')
            continue
        ext, bad = model(it)
        if bad:
            why.append(f'{name}: {bad}')
            continue
        dims = hang_dims(ext, dia)
        if not dims:
            why.append(f'{name}: меш без габаритов')
            continue
        body = body_h(it, dims)
        if not fits(body, ceil, low):
            why.append(f'{name}: корпус {body:g} см — низ {ceil - body:g} см ниже {low:g} даже без шнура')
            continue
        res = solve(objs, room_wd, ceil, Item(role=ROLE, w_cm=dia, d_cm=dia, h_cm=drop_cm(dims, ceil, low)))
        if not res.ok:
            why.append(f"{name}: решатель {res.reject['code']} — {res.reject['message']}")
            if res.reject['code'] == FIT_FAIL:
                continue
            return None, None, None, why
        (pl,) = [p for p in res.placements if p.slot_instance_id.startswith(f'{PLACE[0]}.chandelier#')]
        return it, dims, pl, why
    return None, None, None, why
