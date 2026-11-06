"""СПАЛЬНИ ВИТРИНЫ ДЕМО (план onb-07 Т2, T-20261105-32; контракты ADR-0330) — АДАПТЕР общего ядра `demo_room.py`
(hall-demo-01 этап 3, T-20261106-98: ядро переехало побайтно, эталон — `tests/test_demo_room_golden.py`). Здесь — только своё
спальни: роли, полосы размера, порядок ячейки, солвер, пути банка и чертежа; имена и подписи прежние (сборка
`flat215_demo.py:bedroom_*`, сторожа `room_guards.py`, `room_ready.py`, тесты).

- Комната включается флагом реестра (`apartments[].rooms[].enabled`, `flat215_demo.room_flags`); выключено — ни одной строки
  спальни в данных, гостиная байт в байт прежняя.
- Банк — живой `sets-bedroom.json` (правки Codex 05.11 к onb-07: демо не читает `*.next`); проверочная сборка — `BEDROOM_SETS`.
  Файл — список записей или `{"sets": [...]}`.
- Геометрия — комната готовой расстановки банка, нет её — `flat215-bedrooms.json`, первая запись комнаты (основной вариант
  чертежа; `registry-*`/`small-*` — проверочные).
- Расстановка: готовая в записи (`layout`, как `v3set{n}-layout.json`), иначе солвер спальни
  (`services/planner-solver/planner/bedroom.py:solve_bedroom`). Солвер не расставил кровать — вариант не публикуется.
"""
import os
import sys

import demo_room as R
from demo_room import (STYLE_AXES, _ext, _instances, _key, base_role, bank_room, feed_row, load_bank, neighbour_styles,
                       on_ref_place, room_key, merge_room_feeds, variant_id, zone)

# прежний открытый набор имён модуля (сборка, сторожа и тесты зовут их как `demo_bedroom.<имя>`)
__all__ = ['HERE', 'GEO_FILE', 'BANK_LIVE', 'STYLE_AXES', 'SOLVER_ROLES', 'PLACE_ROLES', 'LIST_ROLES', 'TIER_ORDER', 'PURPOSE_ORDER',
           'BAND_CM', 'ONE_FREE_ROLES', 'MESH_FREE_ROLES', 'SPEC', 'lead_roles', 'neighbour_styles', '_key', 'role_spares',
           'base_role', 'load_bank', 'bank_room', 'room_geo', 'solve', 'one_rule', '_placed', 'zone', 'zones', 'reference', '_ext',
           'on_ref_place', 'hard_codes', 'one_layout', 'variant_id', '_instances', '_fits', '_in_band', 'gate_items',
           'build_variant', 'pick_records', 'feed_row', 'feeds', 'bands', 'room_key', 'merge_room_feeds', 'room_bands']

HERE = os.path.dirname(os.path.abspath(__file__))
GEO_FILE = os.path.join(HERE, 'flat215-bedrooms.json')
BANK_LIVE = os.path.join(HERE, 'sets-bedroom.json')
# ВЕДУЩИЕ ПРЕДМЕТЫ — данные профиля комнаты (`rules/profiles/bedroom.json`, роль `lead: true`; T-20261106-77, ведущий 06.11 — было
# списком CORE здесь): без ведущего с годной моделью вариант не публикуется (критерий onb-07: «в кадре кровать и ≥ 1 тумба»)

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
# одна расстановка на все стили: ковёр встаёт по центру места опорной (`demo_room.one_layout`)
ONE_FREE_ROLES = ('ковёр',)
# у ковра модели нет — его рисует своя отрисовка по фото; ядро решает по стратегии ассета (`demo_room.needs_mesh`), имя — справка
MESH_FREE_ROLES = ('ковёр',)


def solve(geo: dict, dims: list, purpose: str | None) -> dict:
    """Расстановка солвером спальни → `{роль: {x, z, rot}, '_fill_pct', '_reason'}` (форма файла раскладки гостиной).
    `dims` — `[(роль, w, d, h)]` только с известным габаритом (Р1: размер не придумываем)."""
    sys.path.insert(0, R.PLANNER)
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


SPEC = R.Showcase(room_type='bedroom', solver_roles=SOLVER_ROLES, place_roles=PLACE_ROLES, solve=solve, list_roles=LIST_ROLES,
                  one_free_roles=ONE_FREE_ROLES, tier_order=TIER_ORDER, purpose_order=PURPOSE_ORDER, band_cm=BAND_CM)


# --- прежние имена спальни поверх ядра (подписи и значения по умолчанию — как до переноса) ---
def lead_roles(room_type: str = 'bedroom') -> tuple:
    return R.lead_roles(room_type)


def role_spares(bank: list, rec: dict, roles=None, neighbours=neighbour_styles) -> dict:
    return R.role_spares(SPEC, bank, rec, roles, neighbours)


def room_geo(room_id: str, reg: dict | None = None, extra: dict | None = None, path: str = GEO_FILE,
             layout_room: dict | None = None) -> dict | None:
    return R.room_geo(SPEC, room_id, path, reg, extra, layout_room)


def one_rule() -> dict:
    return R.one_rule(SPEC)


def _placed(art: dict) -> dict:
    return R._placed(SPEC, art)


def zones(art: dict) -> dict:
    return R.zones(SPEC, art)


def reference(arts: dict, order: list) -> str:
    return R.reference(SPEC, arts, order)


def hard_codes(art: dict, purpose: str | None) -> set:
    return R.hard_codes(SPEC, art, purpose)


def one_layout(arts: dict, order: list, purposes: dict | None = None, free=ONE_FREE_ROLES) -> tuple[dict, dict]:
    return R.one_layout(SPEC, arts, order, purposes, free)


def _fits(art: dict, role: str, dm: dict, purpose: str | None) -> tuple[dict | None, list]:
    return R._fits(SPEC, art, role, dm, purpose)


def _in_band(role: str, dm: dict, purpose: str | None) -> bool:
    return R._in_band(SPEC, role, dm, purpose)


def gate_items(rec: dict, art: dict | None, sku, dims_of, mesh_ok, spares: dict | None = None
               ) -> tuple[dict, dict | None, list, list, list]:
    return R.gate_items(SPEC, rec, art, sku, dims_of, mesh_ok, spares)


def build_variant(rec: dict, geo: dict, sku, dims_of, style_id, hung=lambda n: False, decor_role=lambda r: False,
                  layout=None, mesh_ok=None, spares: dict | None = None, lead=None, lead_any: bool | None = None,
                  pairs=None) -> tuple[dict | None, dict | None]:
    return R.build_variant(SPEC, rec, geo, sku, dims_of, style_id, hung, decor_role, layout, mesh_ok, spares, lead, lead_any, pairs)


def pick_records(bank: list, rooms: list, styles: list) -> list:
    return R.pick_records(SPEC, bank, rooms, styles)


def feeds(bank: list, catalog: dict, msid, mesh_ok, alive=lambda u: True) -> dict:
    return R.feeds(SPEC, bank, catalog, msid, mesh_ok, alive)


def bands(purposes: list) -> dict:
    return R.bands(SPEC, purposes)


def room_bands(bank: list, rooms) -> dict:
    return R.room_bands(SPEC, bank, rooms)
