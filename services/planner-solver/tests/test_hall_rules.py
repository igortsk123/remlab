"""ПРАВИЛА ПРИХОЖЕЙ (план onb-13 Т3, T-20261105-34): rules/hall.json + planner/hall_checks.py.

Каждое правило имеет проверку (`_enforce`), числа — в occupancy.json (одно число — одно место), и каждое ломается
своим кодом на эталонной прихожей flat215 (153×620, вход с юга — гипотеза, двери кухни и гостиной на западе,
санузел на севере с дугой внутрь).
"""
import json
import os
import re

import pytest

from planner.hall_checks import (check_hall_passages, entrance, hall_rules, is_low, is_wall_mirror, room_widths,
                                 validate_hall)
from planner.models import Item, Opening, Placement, Room, Severity

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCOUT = os.path.join(ROOT, "..", "..", "tools", "scout")


def hall_room(**kw) -> Room:
    ops = [Opening(kind="door", wall="south", offset_cm=31, width_cm=90),
           Opening(kind="door", wall="west", offset_cm=160, width_cm=85),
           Opening(kind="door", wall="west", offset_cm=420, width_cm=85),
           Opening(kind="door", wall="north", offset_cm=20, width_cm=70, swing_cm=70)]
    return Room(width_cm=kw.get("w", 153), depth_cm=kw.get("d", 620), openings=kw.get("openings", ops),
                contour=kw.get("contour"))


def P(role, w, d, h, x, y, rot, elev=0.0) -> Placement:
    p = Placement(role=role, x=x, y=y, rot=rot, item=Item(role=role, w_cm=w, d_cm=d, h_cm=h))
    p.elev_cm = elev
    return p


# эталон: всё у стен, проход свободен (раскладка солвера flat215 «full», округлена)
def reference() -> list[Placement]:
    return [P("шкаф-купе", 150, 60, 240, 123, 520, 270),      # восток, дальний конец, глухая стена
            P("обувница", 99, 39, 44, 133.5, 140, 270),       # восток у входа
            P("банкетка", 80, 43, 49, 131.5, 240, 270),
            P("зеркало", 50, 3, 150, 151.5, 140, 270, 75),    # над обувницей
            P("вешалка", 46, 17, 92, 8.5, 60, 90)]            # запад у входа


def hard(lay) -> list[str]:
    return sorted({v.code for v in lay.violations if v.severity is Severity.HARD})


def soft(lay) -> list[str]:
    return sorted({v.code for v in lay.violations if v.severity is Severity.SOFT})


def test_every_rule_enforced_and_numbers_in_occupancy():
    R = hall_rules()
    occ = json.load(open(os.path.join(ROOT, "rules", "occupancy.json"), encoding="utf-8"))["distances_cm"]
    src = "".join(open(os.path.join(ROOT, "planner", f), encoding="utf-8").read()
                  for f in ("hall_checks.py", "hall.py", "validate.py"))
    for name, r in {**R["rules"], **R["templates"]}.items():
        enf = r.get("_enforce")
        assert enf, f"{name}: у правила нет проверки"
        for code in re.findall(r"\b[A-Z][A-Z_]{3,}\b", enf):
            assert f'"{code}"' in src, f"{name}: код {code} не найден в коде"
        if "num" in r:
            assert r["num"].split(".")[1] in occ, f"{name}: числа {r['num']} нет в occupancy.json"
    for role, cfg in R["roles"].items():
        if "front" in cfg:
            assert cfg["front"] in occ, f"{role}: фронт {cfg['front']} не в occupancy.json"


def test_catalog_roles_match_solver_roles():
    cat = json.load(open(os.path.join(SCOUT, "rules", "hall-roles.json"), encoding="utf-8"))
    roles = set(cat["categories"].values()) | {r for _p, r in cat["name_rules"]} | set(cat["roles_enabled"])
    assert roles <= set(hall_rules()["roles"]), roles - set(hall_rules()["roles"])
    assert set(hall_rules()["composition"]["storage_any"]) <= set(hall_rules()["roles"])


def test_two_views_per_zone():
    v = {k: x for k, x in hall_rules()["views"].items() if not k.startswith("_")}
    assert set(v) == {"entry_storage", "counter"} and v["counter"]["pair"] == "entry_storage"


def test_entrance_south_first_else_first_door():
    assert entrance(hall_room()).wall == "south"
    r = hall_room(openings=[Opening(kind="door", wall="west", offset_cm=30, width_cm=90),
                            Opening(kind="door", wall="east", offset_cm=150, width_cm=80)])
    assert entrance(r).wall == "west"


def test_reference_clean():
    lay = validate_hall(hall_room(), reference())
    assert hard(lay) == [], [(v.code, v.message) for v in lay.violations]


def _swap(role, new):
    return [new if p.role == role else p for p in reference()]


BREAKS = {
    # перед дверью кухни (запад, 160–245) — обувница
    "HALL_DOOR_FRONT": _swap("вешалка", P("вешалка", 46, 17, 92, 8.5, 200, 90)),
    # не спинкой к стене — посреди коридора
    "HALL_NOT_AT_WALL": _swap("банкетка", P("банкетка", 80, 43, 49, 76, 300, 270)),
    # банкетка вплотную перед обувницей (в её фронте 50)
    "HALL_ACCESS_BLOCKED": _swap("банкетка", P("банкетка", 80, 43, 49, 92, 140, 270)),
    # купе поперёк коридора — до санузла и гостиной не пройти
    "HALL_DOOR_UNREACHABLE": _swap("шкаф-купе", P("шкаф-купе", 150, 60, 240, 76, 330, 0)),
    # зеркало над высоким купе — столкновение
    "COLLISION": _swap("зеркало", P("зеркало", 50, 3, 150, 151.5, 520, 270, 75)),
}


@pytest.mark.parametrize("code", sorted(BREAKS))
def test_rule_breaks_with_its_code(code):
    lay = validate_hall(hall_room(), BREAKS[code])
    assert code in hard(lay), (code, [(v.code, v.message) for v in lay.violations])


def test_mirror_over_low_only_listed_roles():
    """Зеркало над обувницей — законно; над вешалкой (на ней одежда) — столкновение."""
    shoe = P("обувница", 99, 39, 44, 133.5, 140, 270)
    hanger = P("вешалка", 46, 17, 92, 144.5, 140, 270)
    m = P("зеркало", 50, 3, 150, 151.5, 140, 270, 75)
    assert is_wall_mirror(m) and is_low(shoe) and not is_low(hanger)
    assert "COLLISION" not in hard(validate_hall(hall_room(), [shoe, m]))
    assert "COLLISION" in hard(validate_hall(hall_room(), [hanger, m]))


def test_mirror_not_on_opening_or_jamb():
    m = P("зеркало", 50, 3, 150, 1.5, 250, 90, 75)          # запад, у двери кухни (160–245) ближе наличника
    assert "HALL_DOOR_FRONT" in hard(validate_hall(hall_room(), [P("шкаф-купе", 150, 60, 240, 123, 520, 270), m]))


def test_soft_codes():
    far_shoe = _swap("обувница", P("обувница", 99, 39, 44, 133.5, 380, 270))
    lay = validate_hall(hall_room(), [p for p in far_shoe if p.role != "зеркало"])
    assert "HALL_SHOE_FAR" in soft(lay) and not hard(lay)
    at_door = _swap("банкетка", P("банкетка", 80, 43, 49, 131.5, 60, 270))
    assert "HALL_ENTRY_TIGHT" in soft(validate_hall(hall_room(), at_door))
    far_mirror = [p for p in reference() if p.role != "зеркало"] + [P("зеркало", 50, 3, 150, 151.5, 400, 270, 75)]
    assert "HALL_MIRROR_FAR" in soft(validate_hall(hall_room(), far_mirror))


def test_room_narrower_than_norm_is_soft_and_furniture_may_not_narrow_it():
    """Г-прихожая с полосой 80 к санузлу-2 и спальне: стены уже 85 — это мягкое HALL_ROOM_NARROW, а не провал
    любой раскладки; мебель, которая сужает полосу ещё сильнее, — жёсткое HALL_DOOR_UNREACHABLE."""
    ops = hall_room().openings + [Opening(kind="door", wall="north", offset_cm=290, width_cm=90)]
    L = hall_room(w=380, d=620, contour=[(0, 0), (153, 0), (153, 540), (380, 540), (380, 620), (0, 620)], openings=ops)
    base = room_widths(L, 85)
    assert base and all(0 < w < 85 for w in base.values())
    empty = check_hall_passages(L, [])
    assert {v.code for v in empty} == {"HALL_ROOM_NARROW"}
    assert all(v.severity is Severity.SOFT for v in empty)
    plug = P("обувница", 99, 39, 44, 250, 600, 180)              # в полосе 80 у северной стены — сужает до 41
    assert "HALL_DOOR_UNREACHABLE" in {v.code for v in check_hall_passages(L, [plug])}


def test_fast_hard_stops_early():
    lay = validate_hall(hall_room(), BREAKS["HALL_NOT_AT_WALL"], fast_hard=True)
    assert hard(lay)
