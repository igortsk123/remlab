"""Зависимые спальни (T-20261113-22, владелец TG 1619/1623 «всё видно: предметы мешами»): лампа на КАЖДОЙ прикроватной тумбе
(пара — по одной на экземпляр носителя, не больше товаров), плед-дорожка поперёк изножья кровати по норме `bed_throw`.
Носители — `bedroom-catalog.json` (`light.bedside`, `textile.bed`); решатель — `planner/dependents.py`."""
from __future__ import annotations

from planner import dependents as D
from planner import room_templates as RT
from planner.models import Item, Placement, Room

DOC = RT.load("bedroom-catalog")
THROW = RT.rule_value("distances_cm.dependents.bed_throw")
BED_TOP = RT.norm_value("heights_cm.bed_top")


def _pl(sid, role, x, y, rot, w, d, h, **kw) -> Placement:
    return Placement(role=role, x=x, y=y, rot=rot, item=Item(role=role, w_cm=w, d_cm=d, h_cm=h, **kw), slot_instance_id=sid)


def _room() -> Room:
    return Room(width_cm=360, depth_cm=400, ceiling_cm=270, openings=[])


def _bedroom(ns=2, bed_h=100, caps=None):
    """Кровать 180×210 изголовьем к северной стене (rot 180 — лицом на юг), тумбы 45×40×55 по бокам."""
    bed = _pl("sleep.bed#0", "кровать", 180, 400 - 105, 180, 180, 210, bed_h, caps=caps or {})
    tabs = [_pl(f"sleep.ns#{i}", "тумба прикроватная", 180 + s * (90 + 25), 400 - 20, 180, 45, 40, 55)
            for i, s in enumerate((-1, 1)[:ns])]
    return [bed, *tabs]


def _places(group, variant, pid):
    return [p for p in RT._variant_places(DOC, group, variant) if p["id"] == pid]


LAMP = Item(role="лампа", w_cm=20, d_cm=20, h_cm=40)


def test_lamp_on_every_bedside_table():
    places = _places("light", "bedside", "light.lamp")
    res = D.resolve(places, _bedroom(), _room(), items={"light.lamp": LAMP}, counts={"light.lamp": 2})
    assert res.ok, res.reject
    got = sorted(p.parent_slot_instance_id for p in res.placements)
    assert got == ["sleep.ns#0", "sleep.ns#1"]
    for p in res.placements:
        assert p.anchor.kind == "item_surface" and p.elev_cm == 55   # на верху тумбы, не в воздухе


def test_lamps_not_more_than_goods():
    places = _places("light", "bedside", "light.lamp")
    res = D.resolve(places, _bedroom(), _room(), items={"light.lamp": LAMP}, counts={"light.lamp": 1})
    assert res.ok, res.reject
    assert [p.parent_slot_instance_id for p in res.placements] == ["sleep.ns#0"]


def test_lamp_too_big_for_bedside_table_rejects():
    places = _places("light", "bedside", "light.lamp")
    huge = Item(role="лампа", w_cm=60, d_cm=60, h_cm=70)
    res = D.resolve(places, _bedroom(), _room(), items={"light.lamp": huge}, counts={"light.lamp": 2})
    assert not res.ok and res.reject["code"] == "FIT_FAIL"


def test_throw_across_bed_foot_by_rule():
    places = _places("textile", "bed", "textile.throw")
    assert places and places[0]["anchor"] == {"kind": "item_edge", "surface": "foot"}
    res = D.resolve(places, _bedroom(), _room())
    assert res.ok, res.reject
    (p,) = res.placements
    depth = sum(THROW["folded_depth_cm"]) / 2
    inset = sum(THROW["side_inset_cm"]) / 2
    assert p.parent_slot_instance_id == "sleep.bed#0" and p.anchor.surface == "foot"
    assert p.local.dy == round(210 / 2 - depth / 2, 2)               # у изножья, не посередине кровати
    assert res.limits["textile.throw#0"] == {"w": round(180 - 2 * inset, 1), "d": round(depth, 1)}
    assert p.elev_cm == sum(BED_TOP) / 2                             # кровать выше нормы (h 100 — с изголовьем) → норма верха
    # мир: кровать лицом на юг (rot 180) — изножье ближе к южной стене, чем центр кровати
    assert p.y < 400 - 105


def test_throw_height_from_mesh_and_low_bed():
    places = _places("textile", "bed", "textile.throw")
    res = D.resolve(places, _bedroom(caps={"foot_h_cm": 48.5}), _room())
    assert res.ok and res.placements[0].elev_cm == 48.5              # верх матраса у изножья по модели кровати
    low = D.resolve(places, _bedroom(bed_h=36), _room())
    assert low.ok and low.placements[0].elev_cm == 36                # низкая кровать-подиум — не выше её самой


def test_throw_on_too_short_bed_left_out_not_whole_room():
    """Кромка — необязательное место: не влез плед — его нет (в пустых с причиной), остальная комната не отклоняется."""
    places = _places("textile", "bed", "textile.throw")
    bed = [_pl("sleep.bed#0", "кровать", 180, 300, 180, 90, 40, 40)]
    res = D.resolve(places, bed, _room())
    assert res.ok and not res.placements
    assert [e["code"] for e in res.empty] == ["FIT_FAIL"]
