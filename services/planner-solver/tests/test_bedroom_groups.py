"""Движок групп-шаблонов спальни (T-20261112-38/2, план bedroom-groups-01, ADR-0384): переключатель `engine`
(по умолчанию items — ровно прежние раскладки), варианты «сна» pair → one_side → solo, ступень 140 для пары,
пара в малой квадратной — без шкафа, без кровати — «кабинет», строгие правила (ноги в дуге двери, хранение у изголовья,
батарея перед шкафом/комодом)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from planner import bedroom_checks as BC
from planner.bedroom import solve_bedroom
from planner.bedroom_checks import validate_bedroom
from planner.models import Item, Opening, Radiator, Room, Severity

SNAP = Path(__file__).with_name("bedroom_items_snapshot.json")


def _room(spec: dict, purpose: str, child_age: str | None = None) -> Room:
    return Room(width_cm=spec["w"], depth_cm=spec["d"], contour=spec.get("contour"),
                openings=[Opening(**{k: v for k, v in o.items() if not k.startswith("_")}) for o in spec.get("openings", [])],
                radiators=[Radiator(**{k: v for k, v in r.items() if not k.startswith("_")}) for r in spec.get("radiators", [])],
                room_type="bedroom", purpose=purpose, child_age=child_age)


def _items(kit) -> list[Item]:
    return [Item(role=r, w_cm=w, d_cm=d, h_cm=h) for r, w, d, h in kit]


def _case(cid: str) -> dict:
    return next(c for c in json.loads(SNAP.read_text(encoding="utf-8"))["cases"] if c["id"] == cid)


def _hard(lay) -> list[str]:
    return [v.code for v in lay.violations if v.severity is Severity.HARD]


COUPLE = [["кровать", 170, 210, 94], ["тумба прикроватная", 45, 40, 55], ["тумба прикроватная 2", 45, 40, 55],
          ["шкаф", 120, 60, 210], ["комод", 91, 42, 96]]


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    monkeypatch.delenv("BEDROOM_ENGINE", raising=False)


# ── переключатель: items = ровно прежнее ──

@pytest.mark.parametrize("cid", [c["id"] for c in json.loads(SNAP.read_text(encoding="utf-8"))["cases"]])
def test_items_engine_snapshot(cid):
    """engine=items (по умолчанию) даёт ровно раскладки origin/main до групп (снимок 14 сцен экзамена)."""
    c = _case(cid)
    lay = solve_bedroom(_room(c["room"], c["purpose"], c.get("child_age")), _items(c["kit"]))
    assert lay.meta["solver"] == "bedroom-v1"
    assert [[p.role, p.x, p.y, int(p.rot), p.tpl_id] for p in lay.placements] == c["placements"]
    assert lay.meta.get("reason", []) == c["reason"]
    assert lay.skipped_optional == c["skipped_optional"] and lay.unplaced == c["unplaced"]


def test_engine_default_and_env(monkeypatch):
    assert BC.engine() == "items"
    monkeypatch.setenv("BEDROOM_ENGINE", "groups")
    assert BC.engine() == "groups" and BC.engine("items") == "items"
    c = _case("narrow270-couple")
    lay = solve_bedroom(_room(c["room"], c["purpose"]), _items(c["kit"]))
    assert lay.meta["solver"] == "bedroom-groups-v1" and lay.meta["engine"] == "groups"
    monkeypatch.setenv("BEDROOM_ENGINE", "nonsense")
    with pytest.raises(ValueError):                 # опечатка в переключателе — громко, а не тихо прежний движок
        BC.engine()


# ── группа «сон» ──

def test_pair_symmetric_and_deterministic():
    c = _case("narrow270-couple")
    room = _room(c["room"], "couple")
    lay = solve_bedroom(room, _items(c["kit"]), engine="groups")
    assert lay.meta["sleep_variant"] == "pair" and not _hard(lay)
    bed = next(p for p in lay.placements if p.role == "кровать")
    ns = [p for p in lay.placements if p.role.startswith("тумба")]
    assert len(ns) == 2
    if int(bed.rot) in (0, 180):
        assert abs((ns[0].x + ns[1].x) / 2 - bed.x) < 0.5          # тумбы зеркально относительно кровати
    else:
        assert abs((ns[0].y + ns[1].y) / 2 - bed.y) < 0.5
    again = solve_bedroom(room, _items(c["kit"]), engine="groups")
    assert [(p.role, p.x, p.y, p.rot) for p in lay.placements] == [(p.role, p.x, p.y, p.rot) for p in again.placements]


def test_one_side_with_reason():
    c = _case("r12-couple")
    lay = solve_bedroom(_room(c["room"], "couple"), _items(c["kit"]), engine="groups")
    assert lay.meta["sleep_variant"] in ("pair", "one_side")
    if lay.meta["sleep_variant"] == "one_side":
        assert lay.meta["sleep_why"] == "NIGHTSTAND_PAIR_NO_FIT"
        assert lay.meta["variants_tried"][:2] == ["pair", "one_side"]


@pytest.mark.parametrize("n_ns", [1, 0])
def test_free_side_wall_or_passage(n_ns):
    """Бок без тумбы (one_side/solo) — к стене или с полным проходом 75 см, без «мёртвой» полосы (лист UK 325×280)."""
    room = Room(width_cm=325, depth_cm=280, room_type="bedroom", purpose="guest", openings=[
        Opening(kind="door", wall="south", offset_cm=230, width_cm=80, swing_cm=80, hinge="left"),
        Opening(kind="window", wall="north", offset_cm=100, width_cm=120, sill_cm=85, height_cm=150)])
    kit = [["кровать", 150, 200, 94]] + [["тумба прикроватная", 45, 40, 55]] * n_ns + [["комод", 91, 42, 96]]
    lay = solve_bedroom(room, _items(kit), "guest", engine="groups")
    assert lay.meta["sleep_variant"] == ("one_side" if n_ns else "solo") and not _hard(lay)
    bed = next(p for p in lay.placements if p.role == "кровать")
    ns = [p for p in lay.placements if p.role.startswith("тумба")]
    poly, z = BC.room_polygon(room), BC.bed_zones(bed)
    taken = {s for s in ("left", "right") for n in ns if z[f"{s}_wall"].intersects(BC.footprint(n))}
    for s in {"left", "right"} - taken:
        flush = z[f"{s}_wall"].difference(poly).area >= 0.8 * z[f"{s}_wall"].area
        assert flush or z[s].difference(poly).area < 1, s


def test_couple_bed_no_fit_asks_140():
    c = _case("tiny-couple")
    lay = solve_bedroom(_room(c["room"], "couple"), _items(c["kit"]), engine="groups")
    assert "BED_NO_FIT" in lay.meta["reason"] and lay.meta["sleep_next"] == "bed_140"


def test_foot_not_in_door_swing_demo_bedroom2():
    """Спальня 2 демо (чертёж №180): поштучный ставит ноги кровати в дугу двери — строгая проверка это ловит;
    движок групп такой раскладки не даёт."""
    c = _case("flat215-bedroom-2-drawing-180-couple")
    room = _room(c["room"], "couple")
    old = solve_bedroom(room, _items(c["kit"]), engine="items")
    new = solve_bedroom(room, _items(c["kit"]), engine="groups")
    assert not _hard(new)
    assert "BED_FOOT_IN_SWING" not in [v.code for v in validate_bedroom(room, new.placements, strict=True).violations]
    bed = next(p for p in new.placements if p.role == "кровать")
    assert BC.foot_swing_share(room, bed, BC.door_swings(room)) < 0.15
    assert old.placements      # прежний остаётся как был (снимок), строгая проверка — только у групп


# ── хранение ──

def _sq(w=310, d=320):
    return Room(width_cm=w, depth_cm=d, room_type="bedroom", purpose="couple", openings=[
        Opening(kind="door", wall="south", offset_cm=20, width_cm=80, swing_cm=80, hinge="left"),
        Opening(kind="window", wall="north", offset_cm=(w - 140) / 2, width_cm=140, sill_cm=85, height_cm=150)],
        radiators=[Radiator(wall="north", offset_cm=(w - 120) / 2, width_cm=120, depth_cm=12)])


def test_small_square_couple_no_wardrobe():
    kit = [["кровать", 145, 205, 90]] + COUPLE[1:]
    lay = solve_bedroom(_sq(), _items(kit), engine="groups")
    assert lay.meta.get("storage_why") == "WARDROBE_SMALL_SQUARE"
    assert "шкаф" not in {p.role for p in lay.placements} and "шкаф" in lay.skipped_optional
    assert any(p.role == "кровать" for p in lay.placements) and not _hard(lay)


def test_elongated_small_couple_keeps_wardrobe_option():
    kit = [["кровать", 145, 205, 90]] + COUPLE[1:]
    lay = solve_bedroom(_sq(260, 395), _items(kit), engine="groups")
    assert lay.meta.get("storage_why") != "WARDROBE_SMALL_SQUARE"


def test_radiator_not_in_front_of_storage():
    """Батарея перед фасадом шкафа/комода (вылет до storage_open_reach) — жёстко у групп."""
    c = _case("flat215-bedroom-1-registry-17.5-couple")
    room = _room(c["room"], "couple")
    lay = solve_bedroom(room, _items(c["kit"]), engine="groups")
    rads = [BC.radiator_polygon(room, r) for r in room.radiators]
    codes = [v.code for v in validate_bedroom(room, lay.placements, strict=True).violations]
    assert "BR_ACCESS_RADIATOR" not in codes
    for p in lay.placements:
        if p.role in ("шкаф", "комод") and rads:
            assert not any(BC.front_reach(p).intersection(r).area > 1 for r in rads)


def test_storage_not_at_bed_head_side():
    for cid in ("flat215-bedroom-1-drawing-180-couple", "narrow270-couple", "r14-office"):
        c = _case(cid)
        room = _room(c["room"], c["purpose"])
        lay = solve_bedroom(room, _items(c["kit"]), engine="groups")
        assert "BED_SIDE_STORAGE" not in [v.code for v in validate_bedroom(room, lay.placements, strict=True).violations]


# ── кабинет ──

def test_office_without_bed_labelled_office():
    room = Room(width_cm=300, depth_cm=280, room_type="bedroom", purpose="office", openings=[
        Opening(kind="door", wall="south", offset_cm=20, width_cm=80, swing_cm=80, hinge="left"),
        Opening(kind="window", wall="north", offset_cm=80, width_cm=140, sill_cm=85, height_cm=150)])
    kit = [["стол рабочий", 120, 60, 75], ["стул рабочий", 50, 55, 90], ["комод", 91, 42, 96]]
    lay = solve_bedroom(room, _items(kit), engine="groups")
    assert lay.meta.get("room_label") == "office" and lay.meta["sleep_variant"] is None
    assert {"стол рабочий", "стул рабочий"} <= {p.role for p in lay.placements}


# ── общий формат комнатного шаблона (planner/room_templates.py) ──

def test_bedroom_passport_schema_clean():
    from planner import room_templates as RT
    assert RT.check(RT.load("bedroom")) == []
    for p, tid in (("couple", "br.pair_axis"), ("guest", "br.pair_axis"), ("single_narrow", "br.single_corner"),
                   ("office", "br.office_work")):
        assert RT.template_for("bedroom", p)["id"] == tid
    assert RT.template_for("bedroom", "child", "7-12")["id"] == "br.child_7_12_work_window"
    assert RT.group_of("bedroom", "комод") == "storage" and RT.group_of("bedroom", "лампа") is None


def test_passport_check_catches_errors():
    from planner import room_templates as RT
    bad = {"schema_version": "room-composition/1", "groups": {"sleep": {"roles": ["кровать"], "variants": {"pair": {}}}},
           "order": ["sleep"],
           "templates": [{"id": "x", "purpose": ["couple"], "groups": [{"id": "sleep", "variants": ["pair", "nope"], "required": True}],
                          "predicates": [{"kind": "teleport"}], "relations": [{"kind": "storage_front_radiator", "rule_ref": "distances_cm.no_such"}],
                          "levels": [{"id": "A", "use": {}}]}]}
    err = " | ".join(RT.check(bad))
    for frag in ("sleep.nope", "teleport", "no_such", "без обязательной группы"):
        assert frag in err, err


def test_level_of_subset_and_composition_meta():
    from planner import room_templates as RT
    tpl = RT.template_for("bedroom", "couple")
    assert RT.level_of(tpl, {"sleep": "pair", "storage": "each_on_wall", "dressing": "table_seat"}) == (0, "A")
    assert RT.level_of(tpl, {"sleep": "one_side"})[1] == "E"
    c = _case("narrow270-couple")
    lay = solve_bedroom(_room(c["room"], "couple"), _items(c["kit"]), engine="groups")
    assert lay.meta["composition"] == {"template": "br.pair_axis", "level": "A", "degraded_from": []}


def test_group_rules_off_for_items_engine():
    c = _case("flat215-bedroom-2-drawing-180-couple")
    room = _room(c["room"], "couple")
    lay = solve_bedroom(room, _items(c["kit"]))
    codes = [v.code for v in validate_bedroom(room, lay.placements).violations]
    assert not {"BED_FOOT_IN_SWING", "BED_SIDE_STORAGE", "BR_ACCESS_RADIATOR"} & set(codes)
