"""ПРИХОЖАЯ ВИТРИНЫ ДЕМО (hall-demo-01 этап 4, T-20261107-05) — АДАПТЕР общего ядра `demo_room.py`. Здесь только своё прихожей:
роли (из профиля `rules/profiles/hall.json` ∩ порядок солвера), солвер (`planner/hall.py:solve_hall` — с контуром Г-образной комнаты
и подъёмом зеркала), пути банка и чертежа, подписи сборки. Правила витрины (ведущие ANY — любое хранение, пары, сторож модели по
стратегии ассета) — в ядре и профиле, не здесь.

- Комната включается флагом реестра (`apartments[].rooms[].enabled`); проверочная сборка рядом — `FLAT215_ROOMS_ENABLED=hall`
  с `FLAT215_DEMO_OUT` (у папки витрины отказ, `flat215_demo.rooms_on`). Выключено — ни одной строки прихожей в данных.
- Банк — живой `sets-hall.json` (его пока нет: кандидат `sets-hall.next.json`, подмена — этап 7); у сборки рядом — `HALL_SETS`
  или кандидат `.next` (`flat215_demo.room_bank_path`).
- Геометрия — комната готовой расстановки банка (`layout._room`, `compose_hall` пишет контур), нет её — `flat215-hall.json`.
- Сторож модели — `room_bindings.usable` (`flat215_demo.room_mesh_gate`, `HALL_MESH_GATE`); выключить его можно только у сборки
  рядом (`GATE_OFF_MAIN = False`): предметы без модели тогда остаются в варианте с меткой `no_mesh` (причина), чтобы шаг спроса
  мешей их видел (ведущий 07.11, T-05/1).
"""
import os
import sys

import demo_room as R

HERE = os.path.dirname(os.path.abspath(__file__))
ROOM_TYPE = 'hall'
GEO_FILE = os.path.join(HERE, 'flat215-hall.json')
BANK_LIVE = os.path.join(HERE, 'sets-hall.json')
# подписи строк журнала сборки (`flat215_demo.room_variants`, `room_photo_catalog`): «прихожая: включены …», «каталог прихожей: …»
TITLE, TITLE_OF = 'прихожая', 'прихожей'
# выключатель сторожа (`HALL_MESH_GATE=0`) у папки витрины — отказ: на главной коробок без модели не бывает (ведущий 07.11)
GATE_OFF_MAIN = False
# фото-каталог прихожей — в данных, только когда прихожая включена (выключено — данные витрины прежние)
CATALOG_ALWAYS = False
# сколько товаров роли в фото-каталоге (выборка по цене через равные шаги; роль вне списка — 8)
CATALOG_SHOW = {'шкаф-купе': 12, 'прихожая': 8, 'обувница': 12, 'банкетка': 12, 'консоль': 8, 'вешалка': 8, 'зеркало': 12}


def _roles() -> tuple:
    """Роли прихожей: профиль (`roles`) в порядке солвера (`planner.hall.ORDER`; роли профиля вне солвера — в конце)."""
    import room_profile as RP
    sys.path.insert(0, R.PLANNER)
    from planner.hall import ORDER
    prof = list(RP.load(ROOM_TYPE)['roles'])
    return tuple([r for r in ORDER if r in prof] + [r for r in prof if r not in ORDER])


ROLES = _roles()


def solve(geo: dict, dims: list, purpose: str | None) -> dict:
    """Расстановка солвером прихожей → `{роль: {x, z, rot, w, d, h, elev}, '_fill_pct'[, '_reason']}` (форма `compose_hall`
    `layout`). Контур комнаты — в модель солвера; назначения у прихожей нет (`purpose` солвер не берёт)."""
    sys.path.insert(0, R.PLANNER)
    from planner.hall import solve_hall
    from planner.models import Item, Opening, Radiator, Room
    room = Room(width_cm=geo['w'], depth_cm=geo['d'], contour=geo.get('contour'), room_type='hall',
                openings=[Opening(**o) for o in geo.get('openings') or []], radiators=[Radiator(**r) for r in geo.get('radiators') or []])
    lay = solve_hall(room, [Item(role=r, w_cm=w, d_cm=d, h_cm=h) for r, w, d, h in dims])
    out = {p.role: {'x': p.x, 'z': p.y, 'rot': p.rot, 'w': p.item.w_cm, 'd': p.item.d_cm, 'h': p.item.h_cm, 'elev': p.elev_cm}
           for p in lay.placements}
    out['_fill_pct'] = lay.floor_used_pct
    if not lay.ok:
        out['_reason'] = list(lay.meta.get('reason') or []) or [v.code for v in lay.violations if v.severity.value == 'hard']
    return out


# ячейка: одна ступень цены у сборщика («комфорт», `hall-composition.json`), назначение записи — «hall»; у модели комнаты солвера
# назначений прихожей нет — проверки без него (`solver_purposes=()`)
SPEC = R.Showcase(room_type=ROOM_TYPE, solver_roles=ROLES, place_roles=ROLES, solve=solve, tier_order=('комфорт',),
                  purpose_order=('hall',), solver_purposes=())
