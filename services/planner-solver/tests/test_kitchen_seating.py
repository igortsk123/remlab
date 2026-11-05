"""Посадка кухни (план onb-09 Т2, ADR-0330): экзамен сцен `kitchen_scenes.json` (кухня flat215 + прямоугольники, узкие,
с дверью в торце, низкий/высокий подоконник, Г), повторная проверка годной посадки независимой геометрией, детерминизм,
нормы — из `rules/kitchen.json` с источником у каждого числа."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from shapely.geometry import box

from planner.geometry import _wall_strip, swing_polygon
from planner.kitchen import RIGHT, ROT, WHY, KitchenKit, Vent, kitchen_rules, rule, seat_kitchen
from planner.models import Opening, Radiator, Room

HERE = Path(__file__).resolve().parent
SCENES = json.loads((HERE / "kitchen_scenes.json").read_text(encoding="utf-8"))
FLAT = json.loads((HERE.parents[2] / "tools" / "scout" / "flat215-kitchen.json").read_text(encoding="utf-8"))["rooms"][0]


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("_")}


def _room(spec: dict) -> Room:
    return Room(width_cm=spec["w"], depth_cm=spec["d"], contour=spec.get("contour"), room_type="kitchen",
                openings=[Opening(**_clean(o)) for o in spec.get("openings", [])],
                radiators=[Radiator(**_clean(r)) for r in spec.get("radiators", [])])


def _kit(k: dict) -> KitchenKit:
    return KitchenKit(length_cm=k["L"], tall_cm=k["tall"], fridge_in_column=k["fridge"], uppers=k["uppers"],
                      shape=k.get("shape", "straight"), leg_cm=k.get("leg"))


def _vent(v) -> Vent | None:
    if v == "flat215":
        return Vent(**_clean(FLAT["vent"]))
    return Vent(wall=v["wall"], offset_cm=v["offset_cm"], assumed=False) if v else None


def _run(scene: dict) -> dict:
    spec = FLAT if scene["room"] == "flat215" else SCENES["rooms"][scene["room"]]
    return seat_kitchen(_room(spec), _kit(SCENES["kits"][scene["kit"]]), _vent(scene.get("vent")), scene.get("cooks", 1))


def test_exam_size():
    ids = [s["id"] for s in SCENES["scenes"]]
    assert len(ids) == len(set(ids))
    assert len(ids) >= 15 and sum(i.startswith("flat215") for i in ids) >= 3
    assert {SCENES["kits"][s["kit"]]["L"] for s in SCENES["scenes"]} >= {240, 300, 304}


@pytest.mark.parametrize("scene", SCENES["scenes"], ids=lambda s: s["id"])
def test_scene(scene):
    r = _run(scene)
    e = scene["expect"]
    assert r["ok"] is e["ok"], (r.get("reason"), r.get("why"))
    if not e["ok"]:
        assert r["reason"] and all(c in WHY or c == "KITCHEN_CONTOUR" for c in r["reason"])
        for code in e.get("reason", []):
            assert code in r["reason"], r["why"]
        return
    if "wall" in e:
        assert r["wall"] in e["wall"]
    assert r["wall"] not in e.get("not_wall", [])
    for k in ("columns_at", "shape", "shape_changed"):
        if k in e:
            assert r[k] == e[k], (k, r[k])
    if "vent_max_cm" in e:
        assert r["vent_distance_cm"] is not None and r["vent_distance_cm"] <= e["vent_max_cm"]
    if "min_seats" in e:
        assert r["dining"]["max_seats"] >= e["min_seats"], r["dining"]
    if e.get("no_hob"):
        assert r["no_hob_cm"], "ряд под окном — варочной туда нельзя"
    _recheck(scene, r)


def _recheck(scene: dict, r: dict) -> None:
    """Независимая повторная проверка годной посадки: след ряда в комнате, не на двери и радиаторе, проход перед линией
    не меньше нормы, поворот набора по стене, холодильник внутри комнаты."""
    spec = FLAT if scene["room"] == "flat215" else SCENES["rooms"][scene["room"]]
    room = _room(spec)
    L, D = r["length_cm"], r["kit"]["depth_cm"]
    run = _wall_strip(room, r["wall"], r["u0_cm"], L, D)
    assert box(0, 0, room.width_cm, room.depth_cm).contains(run.buffer(-0.5))
    for op in room.openings:
        if op.kind != "window":
            assert run.intersection(swing_polygon(room, op)).area < 0.5, "ряд в дуге двери"
            assert run.intersection(_wall_strip(room, op.wall, op.offset_cm, op.width_cm, rule("openings", "door_passage_cm"))).area < 0.5
    for rad in room.radiators:
        assert run.intersection(_wall_strip(room, rad.wall, rad.offset_cm, rad.width_cm, rad.depth_cm)).area < 0.5
    need = rule("aisle", "work_two_cooks_cm" if scene.get("cooks") == 2 else "work_one_cook_cm")
    assert r["room_depth_cm"] - D >= need
    assert r["pose"]["rot"] == ROT[r["wall"]] and r["right"] == list(RIGHT[r["wall"]])
    if not r["kit"]["fridge_in_column"]:
        assert r["fridge"], "холодильнику нужно место"
        for f in r["fridge"]:
            fp = _wall_strip(room, f["wall"], f["offset_cm"], rule("fridge", "w_cm"), rule("fridge", "d_cm"))
            assert box(0, 0, room.width_cm, room.depth_cm).contains(fp.buffer(-0.5)) and run.intersection(fp).area < 0.5
    assert all(c["ok"] for c in r["checks"])


def test_flat215_reads_like_the_drawing():
    """Кухня 215: ряд по наружной глухой стене к вентканалу, колонна не у окна, проход ≥ 107, вентканал — допущение."""
    r = _run({"room": "flat215", "kit": "sima-300", "vent": "flat215"})
    assert r["ok"] and r["wall"] == "south" and r["vent_assumed"] is True
    assert r["u0_cm"] + r["length_cm"] == FLAT["w"], "ряд вплотную к углу у вентканала"
    assert r["columns_at"] == "end", "колонна у восточного конца: у западного она закрыла бы откос окна"
    aisle = next(c for c in r["checks"] if c["code"] == "KITCHEN_AISLE")
    assert aisle["value"] == 251 and aisle["need"] == 107


def test_deterministic():
    for s in SCENES["scenes"][:6]:
        assert _run(s) == _run(s)


def test_low_sill_blocks_base_high_sill_allows():
    room = SCENES["rooms"]["r12-sill-high"]
    low = {**room, "openings": [{**room["openings"][0], "sill_cm": 80}] + room["openings"][1:]}
    kit = _kit(SCENES["kits"]["base-240-open"])
    vent = Vent(wall="south", offset_cm=200, assumed=False)
    assert seat_kitchen(_room(room), kit, vent)["wall"] == "south"
    assert seat_kitchen(_room(low), kit, vent)["wall"] != "south"


def test_rules_have_sources():
    R = kitchen_rules()
    srcs = set(R["_meta"]["sources"]) | {"manual"}
    for section, body in R.items():
        if section.startswith("_") or section in ("score", "shapes", "views"):
            continue
        for key, val in body.items():
            if isinstance(val, dict):
                assert val.get("src") in srcs and val.get("status") in ("norm", "product", "hypothesis"), (section, key)
    assert R["aisle"]["work_one_cook_cm"]["v"] == 107 and R["aisle"]["work_two_cooks_cm"]["v"] == 122
    assert (R["triangle"]["side_min_cm"]["v"], R["triangle"]["side_max_cm"]["v"], R["triangle"]["sum_max_cm"]["v"]) == (120, 270, 790)
