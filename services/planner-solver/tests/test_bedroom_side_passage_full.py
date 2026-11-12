"""Проход у бока кровати — на ВСЮ длину (T-20261112-31; разбор T-27: в 6 наборах спальни 1 комод стоял вплотную к тумбе
и закрывал подход к изголовью). У изголовья в полосе можно только тумбе и лампе; выключатель `switches.bed_side_passage_full`."""
from __future__ import annotations

import copy

import pytest

from planner import bedroom_checks as BC
from planner import passage_norms as PN
from planner.bedroom import solve_bedroom
from planner.bedroom_checks import validate_bedroom
from planner.models import Item, Opening, Placement, Room, Severity

W, D = 597.0, 293.0      # спальня 1 квартиры 215 (registry-17.5)
BED = dict(role="кровать", w_cm=165, d_cm=203, h_cm=98)
NS = dict(w_cm=42, d_cm=35, h_cm=52)
DRESSER = dict(role="комод", w_cm=105, d_cm=42, h_cm=80)


def _room() -> Room:
    return Room(width_cm=W, depth_cm=D, room_type="bedroom", purpose="couple",
                openings=[Opening(kind="door", wall="west", offset_cm=180, width_cm=90, swing_cm=90)])


def _layout(dresser_x: float | None) -> list[Placement]:
    ps = [Placement(role="кровать", x=298.5, y=101.5, rot=0, item=Item(**BED)),
          Placement(role="тумба прикроватная", x=194, y=17.5, rot=0, item=Item(role="тумба прикроватная", **NS)),
          Placement(role="тумба прикроватная 2", x=403, y=17.5, rot=0, item=Item(role="тумба прикроватная 2", **NS))]
    if dresser_x is not None:
        ps.append(Placement(role="комод", x=dresser_x, y=21, rot=0, item=Item(**DRESSER)))
    return ps


def _hard(ps) -> set[str]:
    return {v.code for v in validate_bedroom(_room(), ps).violations if v.severity is Severity.HARD}


def test_dresser_next_to_nightstand_blocks_head_of_passage():
    """Комод вплотную к тумбе (тумба до 424, комод от 424) — в полосе у изголовья: прохода к изголовью нет. С T-68 бок пары —
    цель 60 / допуск 50 (`distances_cm.clearances`): вне движка проверка по допуску, в проходе 1 движка — по цели (банк
    T-27: x≈482, зазор 49 — уже цели 60)."""
    assert "BED_SIDE_PASSAGE" in _hard(_layout(424 + 52.5))
    with PN.using("target"):
        assert "BED_SIDE_PASSAGE" in _hard(_layout(482.5))


def test_nightstands_alone_and_dresser_beyond_strip_ok():
    assert "BED_SIDE_PASSAGE" not in _hard(_layout(None))
    # полоса справа по цели кончается на 298.5 + 82.5 + 60 = 441; комод от 442 — уже за ней
    with PN.using("target"):
        assert "BED_SIDE_PASSAGE" not in _hard(_layout(442 + 52.5))


def test_solver_keeps_full_strip():
    """Солвер не ставит комод в полосу у изголовья; тумбы у изголовья остаются."""
    items = [Item(**BED), Item(role="тумба прикроватная", **NS), Item(role="тумба прикроватная 2", **NS), Item(**DRESSER),
             Item(role="шкаф", w_cm=153, d_cm=52, h_cm=240)]
    lay = solve_bedroom(_room(), items, "couple")
    assert not [v for v in lay.violations if v.severity is Severity.HARD], [v.code for v in lay.violations]
    bed = next(p for p in lay.placements if p.role == "кровать")
    z = BC.bed_zones(bed)
    for p in lay.placements:
        if BC.bedroom_role(p.role) in ("комод", "шкаф"):
            for k in ("left", "right", "left_head", "right_head"):
                assert BC.footprint(p).intersection(z[k]).area <= BC.AREA_EPS, (p.role, k)
    assert {"тумба прикроватная", "тумба прикроватная 2"} <= {p.role for p in lay.placements}


@pytest.fixture
def switch_off(monkeypatch):
    rules = copy.deepcopy(BC.bedroom_rules())
    rules["switches"]["bed_side_passage_full"]["on"] = False
    monkeypatch.setattr(BC, "bedroom_rules", lambda: rules)
    yield


def test_switch_off_restores_old_strip(switch_off):
    assert "BED_SIDE_PASSAGE" not in _hard(_layout(424 + 52.5))
    assert "left_head" not in BC.bed_zones(_layout(None)[0])
