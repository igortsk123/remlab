"""Решатель зависимых мест (T-20261112-67): каждый вид крепления ставится, отказ — целиком и с причиной, детерминизм,
старый Placement без новых полей не меняется. Сцены синтетические: готовых размещений носителей с `slot_instance_id`
в приёмке нет (`tools/scout/acceptance-scenes.json` — только размеры комнат)."""
from __future__ import annotations

import json

import pytest

from planner import dependents as D
from planner import room_templates as RT
from planner.models import Item, Opening, Placement, Room

DOC = RT.load("living")

# носители: роль → (w, d, h) — типовые габариты каталога гостиной
SIZES = {"диван": (220, 95, 85), "диван 2": (200, 90, 85), "столик": (110, 60, 42), "ковёр": (200, 140, 1),
         "кресло": (80, 80, 85), "тв-тумба": (160, 40, 45), "комод": (120, 45, 80), "торшер": (40, 40, 160),
         "приставной": (45, 45, 55), "стол обеденный": (120, 80, 75), "стул": (45, 50, 90), "кашпо": (40, 40, 100)}


def _pl(sid: str, role: str, x: float, y: float, rot: float, size=None, **kw) -> Placement:
    w, d, h = size or SIZES[role]
    return Placement(role=role, x=x, y=y, rot=rot, item=Item(role=role, w_cm=w, d_cm=d, h_cm=h, **kw), slot_instance_id=sid)


def scene(places: list[dict], room: Room, sofa_x: float | None = None) -> list[Placement]:
    """Носители уровня в типовой расстановке: диван у северной стены, ТВ у южной, комод у восточной, стол — запад."""
    W, Dp = room.width_cm, room.depth_cm
    sx = W / 2 if sofa_x is None else sofa_x
    out = []
    for p in places:
        if p["kind"] != "slot":
            continue
        role, pid = p["role"], p["id"]
        for i in range(p.get("count", 1)):
            sid = f"{pid}#{i}"
            if pid == "seating.sofa":
                out.append(_pl(sid, role, sx, Dp - 95 / 2, 180))
            elif pid == "seating.sofa2":
                out.append(_pl(sid, "диван 2", 90 / 2, Dp / 2, 90))
            elif pid == "seating.coffee":
                out.append(_pl(sid, role, sx, Dp - 95 - 45 - 30, 0))
            elif pid == "seating.rug":
                out.append(_pl(sid, role, sx, Dp - 95 - 45 - 30, 0))
            elif pid in ("seating.armchair", "reading.armchair"):
                out.append(_pl(sid, role, sx + (150 if i == 0 else -150), Dp - 180, 270 if i == 0 else 90))
            elif pid == "media.tv_stand":
                out.append(_pl(sid, role, sx, 40 / 2, 0))
            elif pid == "light.dresser":
                out.append(_pl(sid, role, W - 45 / 2, Dp / 2 - 40, 270))
            elif pid == "light.floor_lamp":
                out.append(_pl(sid, role, sx - 135, Dp - 25, 180))
            elif pid == "light.side_table":
                out.append(_pl(sid, role, sx + 140, Dp - 30, 180))
            elif pid == "dining.table":
                out.append(_pl(sid, role, 110, 110, 0))
            elif pid == "dining.chairs":
                out.append(_pl(sid, role, 110 + (i - 1.5) * 50, 110 + (55 if i % 2 else -55), 0 if i % 2 else 180))
            elif pid == "plant.planter":
                out.append(_pl(sid, role, W - 25, 25, 0))
    return out


def room(w=500, d=420, ceiling=270, openings=None) -> Room:
    return Room(width_cm=w, depth_cm=d, ceiling_cm=ceiling, openings=openings if openings is not None else [
        Opening(kind="window", wall="south", offset_cm=30, width_cm=110, sill_cm=85, height_cm=150),
        Opening(kind="door", wall="west", offset_cm=300, width_cm=90, swing_cm=90, height_cm=210)])


def _tpl(tid):
    return RT.template_by_id("living", tid)


def _level(tid, lid):
    places, err = RT.compile_level(DOC, _tpl(tid), lid)
    assert not err, err
    return places


def _by(res, prefix):
    return [p for p in res.placements if p.slot_instance_id.startswith(prefix)]


# ── каждый вид крепления ставится ──

def test_full_level_places_every_kind():
    places = _level("LR-C1", "A4")
    r = room()
    res = D.resolve(places, scene(places, r), r)
    assert res.ok, res.reject
    kinds = {p.anchor.kind for p in res.placements}
    assert kinds == {"item_surface", "item_edge", "wall_above", "ceiling_over", "opening"}
    dep_ids = {p["id"] for p in places if p["kind"] == "dependent"}
    assert {p.slot_instance_id.split("#")[0] for p in res.placements} == dep_ids   # ни одно место не выпало молча
    for p in res.placements:
        assert p.parent_slot_instance_id and p.mount and p.local is not None


def test_pillows_count_by_sofa_width_and_on_seat():
    places = _level("LR-C1", "A4")
    r = room()
    res = D.resolve(places, scene(places, r), r)
    pil = _by(res, "soft.pillows#")
    rule = RT.rule_value("distances_cm.dependents.sofa_pillow_count")
    assert len(pil) == RT.count_by_width(rule["by_outer_width_cm"], 220) == 3
    seat = RT.norm_value("heights_cm.sofa_seat")
    assert all(p.elev_cm == (seat[0] + seat[1]) / 2 and p.mount == "surface" for p in pil)
    assert all(p.parent_slot_instance_id == "seating.sofa#0" for p in pil)
    xs = sorted(p.x for p in pil)
    assert xs[1] == pytest.approx(r.width_cm / 2) and xs[0] - r.width_cm / 2 == pytest.approx(r.width_cm / 2 - xs[2])  # balanced


def test_throw_on_free_arm_and_back_when_both_blocked():
    places = _level("LR-C1", "A4")
    r = room()
    res = D.resolve(places, scene(places, r), r)
    (t,) = _by(res, "soft.throw#")
    assert t.anchor.surface == "arm"
    # диван во всю стену: оба подлокотника упираются в стены → плед на спинке, не выпадает
    cars = scene(places, r)
    cars = [_pl(c.slot_instance_id, "диван", r.width_cm / 2, r.depth_cm - 95 / 2, 180, size=(r.width_cm, 95, 85))
            if c.slot_instance_id == "seating.sofa#0" else c for c in cars]
    res2 = D.resolve(places, cars, r)
    assert res2.ok, res2.reject
    (t2,) = _by(res2, "soft.throw#")
    assert t2.anchor.surface == "back" and t2.anchor.edge == "back"


def test_lamp_and_vase_share_dresser_top():
    places = _level("LR-C1", "A4")
    places = [p for p in places if p["group"] != "vase"] + RT._variant_places(DOC, "vase", "vase_on_dresser")
    r = room()
    res = D.resolve(places, scene(places, r), r)
    assert res.ok, res.reject
    on = [p for p in res.placements if p.parent_slot_instance_id == "light.dresser#0" and p.anchor.kind == "item_surface"]
    assert sorted(p.role for p in on) == ["ваза", "лампа"]
    assert on[0].elev_cm == on[1].elev_cm == 80
    assert on[0].local.dx == -on[1].local.dx != 0          # две клетки вдоль столешницы


def test_screen_virtual_not_priced():
    places = _level("LR-C1", "A4")
    r = room()
    res = D.resolve(places, scene(places, r), r)
    (s,) = _by(res, "media.screen#")
    assert s.priced is False and s.marker == "virtual_screen" and s.mount == "wall" and s.anchor.wall == "south"
    tv = RT.rule_value("distances_cm.mounting.tv_screen")
    assert s.elev_cm == (tv["center_from_floor"][0] + tv["center_from_floor"][1]) / 2
    assert res.limits["media.screen#0"]["w_max"] == pytest.approx(tv["max_share_of_stand"] * 160)


def test_art_pair_over_sofa_heights_from_rule():
    places = _level("LR-C1", "A4")
    r = room()
    res = D.resolve(places, scene(places, r), r)
    art = _by(res, "art.art#")
    rule = RT.rule_value("distances_cm.mounting.wall_art")
    assert len(art) == rule["max_count"] and {a.parent_slot_instance_id for a in art} == {"seating.sofa#0"}
    assert all(a.elev_cm == 85 + (rule["bottom_above_carrier"][0] + rule["bottom_above_carrier"][1]) / 2 for a in art)
    assert all(a.anchor.wall == "north" for a in art)


def test_art_falls_to_next_carrier_when_wall_has_window():
    """Окно над диваном: стена не сплошная → картины над комодом (следующий носитель one_of), а не тихо без картин."""
    places = _level("LR-C1", "A4")
    r = room(openings=[Opening(kind="window", wall="north", offset_cm=200, width_cm=100, sill_cm=85, height_cm=150)])
    res = D.resolve(places, scene(places, r), r)
    assert res.ok, res.reject
    assert {a.parent_slot_instance_id for a in _by(res, "art.art#")} == {"light.dresser#0"}


def test_art_rejects_composition_when_no_solid_wall():
    """Окна над диваном и над комодом — уровень честно не годится (отказ с причиной), не «без картин»."""
    places = _level("LR-C1", "A4")
    r = room(openings=[Opening(kind="window", wall="north", offset_cm=200, width_cm=100, sill_cm=85, height_cm=150),
                       Opening(kind="window", wall="east", offset_cm=120, width_cm=100, sill_cm=85, height_cm=150)])
    res = D.resolve(places, scene(places, r), r)
    assert not res.ok and res.placements == []
    assert res.reject["code"] == "WALL_NOT_SOLID" and res.reject["place"] == "art.art"


def test_chandelier_center_of_rug_and_long_one_rejected():
    places = _level("LR-C1", "A4")
    r = room()
    cars = scene(places, r)
    res = D.resolve(places, cars, r)
    (c,) = _by(res, "ceiling.chandelier#")
    rug = next(p for p in cars if p.slot_instance_id == "seating.rug#0")
    assert (c.x, c.y) == (rug.x, rug.y) and c.mount == "ceiling" and c.anchor.ceiling
    ch = RT.rule_value("distances_cm.mounting.chandelier")
    assert res.limits["ceiling.chandelier#0"]["drop_max"] == 270 - ch["over_seating_bottom"][0]
    long = Item(role="люстра", w_cm=60, d_cm=60, h_cm=80)        # 270 − 80 = 190 < 210
    bad = D.resolve(places, cars, r, items={"ceiling.chandelier": long})
    assert bad.reject["code"] == "FIT_FAIL" and bad.reject["place"] == "ceiling.chandelier"


def test_pendant_over_dining_table():
    places, err = RT.compile_level(DOC, _tpl("LR-O1"), "A4")
    assert not err
    r = room(w=600, d=500)
    res = D.resolve(places, scene(places, r), r)
    assert res.ok, res.reject
    (pd,) = _by(res, "ceiling.pendant#")
    ch = RT.rule_value("distances_cm.mounting.chandelier")
    assert pd.parent_slot_instance_id == "dining.table#0" and (pd.x, pd.y) == (110, 110)
    assert pd.elev_cm == 75 + (ch["above_dining_table"][0] + ch["above_dining_table"][1]) / 2


def test_curtains_one_per_window_and_skipped_without_window():
    places = _level("LR-C1", "A4")
    r = room(openings=[Opening(kind="window", wall="south", offset_cm=30, width_cm=110, sill_cm=85, height_cm=150),
                       Opening(kind="window", wall="west", offset_cm=60, width_cm=100, sill_cm=85, height_cm=150)])
    res = D.resolve(places, scene(places, r), r)
    assert res.ok, res.reject
    cur = _by(res, "textile.curtains#")
    assert len(cur) == 2 and all(c.mount == "rod" for c in cur)
    cr = RT.rule_value("distances_cm.mounting.curtains")
    assert cur[0].elev_cm == 85 + 150 + (cr["rod_above_opening"][0] + cr["rod_above_opening"][1]) / 2
    assert res.limits["textile.curtains#0"]["rod_w"] == 110 + 2 * (cr["beyond_opening_each_side"][0] + cr["beyond_opening_each_side"][1]) / 2
    no = D.resolve(places, scene(places, room(openings=[])), room(openings=[]))
    assert no.ok and "textile.curtains" in no.skipped and not _by(no, "textile.curtains#")


def test_wall_planter_on_free_wall_not_floor():
    places = RT._variant_places(DOC, "plant", "wall")
    r = room()
    res = D.resolve(places, [], r)
    assert res.ok, res.reject
    (pl,) = res.placements
    wp = RT.rule_value("distances_cm.mounting.wall_planter")
    assert pl.mount == "wall" and pl.elev_cm >= wp["bottom_from_floor"][0] and pl.local.dy == wp["off_wall_min"]


# ── отказ целиком, не тихо без предмета ──

def test_missing_carrier_rejects_with_reason():
    places = _level("LR-C1", "A4")
    r = room()
    cars = [c for c in scene(places, r) if not c.slot_instance_id.startswith("seating.sofa")]
    res = D.resolve(places, cars, r)
    assert not res.ok and res.placements == []
    assert res.reject["code"] == "CARRIER_MISSING" and res.reject["place"] in ("soft.pillows", "soft.throw", "art.art")


def test_ceiling_unknown_rejects():
    places = _level("LR-C1", "A4")
    r = room(ceiling=None)
    res = D.resolve(places, scene(places, r), r)
    assert res.reject["code"] == "CEILING_UNKNOWN"


def test_carrier_away_from_wall_rejects_screen():
    places = _level("LR-C1", "A4")
    r = room()
    cars = [_pl("media.tv_stand#0", "тв-тумба", 250, 80, 0) if c.slot_instance_id == "media.tv_stand#0" else c
            for c in scene(places, r)]
    res = D.resolve(places, cars, r)
    assert res.reject["code"] == "CARRIER_NOT_AT_WALL" and res.reject["place"] == "media.screen"


def test_curtain_next_to_tv_screen_rejects():
    """Окно у тумбы: штанга штор (за край проёма) заходит под экран — стена занята, отказ, а не наезд в 3D."""
    places = _level("LR-C1", "SA")
    # окно 5–100 само экран (108–252) не задевает, а штанга шире проёма на 11,5 см — задевает
    r = room(w=360, d=330, ceiling=250, openings=[Opening(kind="window", wall="south", offset_cm=5, width_cm=95,
                                                          sill_cm=85, height_cm=150)])
    res = D.resolve(places, scene(places, r), r)
    assert res.reject["code"] == "WALL_NOT_SOLID" and res.reject["place"] == "media.screen"
    assert "textile.curtains#0" in res.reject["message"]


def test_too_wide_pillow_sku_rejects():
    places = _level("LR-C1", "A4")
    r = room()
    res = D.resolve(places, scene(places, r), r, items={"soft.pillows": Item(role="подушка", w_cm=90, d_cm=20, h_cm=50)})
    assert res.reject["code"] == "FIT_FAIL" and res.reject["place"] == "soft.pillows"


# ── детерминизм и обратная совместимость ──

def test_deterministic_two_runs_equal():
    places = _level("LR-O1", "A4")
    r = room(w=600, d=500)
    a = D.resolve(places, scene(places, r), r)
    b = D.resolve(list(reversed(places)), list(reversed(scene(places, r))), r)
    assert [p.model_dump() for p in a.placements] == [p.model_dump() for p in b.placements]
    assert a.limits == b.limits


def test_old_placement_serializes_as_before():
    """Старая сцена: новые поля пусты и в сериализации без значений по умолчанию не появляются."""
    old = Placement(role="диван", x=100, y=200, rot=180, item=Item(role="диван", w_cm=220, d_cm=95), tpl_id="t")
    assert old.model_dump(exclude_defaults=True) == {
        "role": "диван", "x": 100, "y": 200, "rot": 180, "item": {"role": "диван", "w_cm": 220, "d_cm": 95}, "tpl_id": "t"}
    new_fields = {"slot_instance_id", "parent_slot_instance_id", "anchor", "local", "mount", "priced", "marker"}
    dump = old.model_dump()
    assert {k: dump[k] for k in new_fields} == {"slot_instance_id": "", "parent_slot_instance_id": "", "anchor": None,
                                                "local": None, "mount": None, "priced": None, "marker": None}
    assert json.loads(old.model_dump_json(exclude=new_fields)) == json.loads(
        Placement(role="диван", x=100, y=200, rot=180, item=Item(role="диван", w_cm=220, d_cm=95), tpl_id="t")
        .model_dump_json(exclude=new_fields))


def test_no_numbers_in_solver_code():
    """Числа правил — только из occupancy.json: в коде решателя нет числовых литералов, кроме 0/1/2, осей поворота
    (90/180/270/360) и единиц (2.54 см в дюйме)."""
    import ast
    from pathlib import Path
    tree = ast.parse(Path(D.__file__).read_text(encoding="utf-8"))
    nums = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and type(n.value) in (int, float)}
    assert nums <= {0, 1, 2, 90, 180, 270, 360, 2.54}, nums


# ── прогон по уровням паспорта на трёх сценах ──

SCENES = {
    "S0 12 м², окно на западе, потолок 250": room(w=360, d=330, ceiling=250, openings=[
        Opening(kind="window", wall="west", offset_cm=40, width_cm=100, sill_cm=85, height_cm=150),
        Opening(kind="door", wall="south", offset_cm=270, width_cm=80, swing_cm=80, height_cm=210)]),
    "S1 20 м², окно на юге": room(),
    "S2 17 м², окно за диваном": room(w=450, d=380, ceiling=250, openings=[
        Opening(kind="window", wall="north", offset_cm=175, width_cm=100, sill_cm=85, height_cm=150),
        Opening(kind="door", wall="south", offset_cm=330, width_cm=90, swing_cm=90, height_cm=210)]),
    "S3 30 м², два окна, потолок 240": room(w=600, d=500, ceiling=240, openings=[
        Opening(kind="window", wall="south", offset_cm=400, width_cm=140, sill_cm=85, height_cm=150),
        Opening(kind="window", wall="east", offset_cm=280, width_cm=120, sill_cm=85, height_cm=150),
        Opening(kind="door", wall="west", offset_cm=380, width_cm=90, swing_cm=90, height_cm=210)]),
}


def run_scene(r: Room) -> list[tuple[str, str, str]]:
    facts = {**D.room_facts(r), "aspect": max(r.width_cm, r.depth_cm) / min(r.width_cm, r.depth_cm)}
    rows = []
    for tid in RT.select(DOC, facts):
        tpl = _tpl(tid)
        if tpl is None or tpl.get("modifier"):
            continue
        for lid in RT.levels_for(tpl, facts):
            places, err = RT.compile_level(DOC, tpl, lid)
            res = D.resolve(places, scene(places, r), r) if not err else None
            rows.append((tid, lid, "OK" if res and res.ok else (res.reject["code"] + " " + res.reject["place"]) if res else "LEVEL_INVALID"))
    return rows


@pytest.mark.parametrize("name", sorted(SCENES))
def test_levels_run_on_scenes(name):
    rows = run_scene(SCENES[name])
    assert rows, "нет уровней для сцены"
    assert any(r[2] == "OK" for r in rows), rows
    known = {"OK", "WALL_NOT_SOLID", "CARRIER_NOT_AT_WALL", "FIT_FAIL", "CEILING_TOO_LOW", "WALL_EDGE", "CARRIER_MISSING"}
    assert {r[2].split()[0] for r in rows} <= known, rows
