"""Узкая односпальная UK single 90×190 (план bedroom-uk-single-01, владелец TG 297 09.11: «не поправить, а добавить»).

1) Прежние назначения, шаблоны, правила, слоты состава и теги каталога — ровно те, что были до 09.11: текущий файл
   МИНУС перечисленные добавки даёт тот же JSON, что зафиксирован эталоном (sha256), и добавки стоят последними ключами.
2) Новое назначение single_narrow раскладывает кровать 90×190 (рама ≤ ~105) без жёстких нарушений в спальнях
   из объявления (`tools/scout/uk-bedrooms.json`): Bedroom Three 2,44×3,33 и Bedroom Two 3,96×3,60.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from planner.bedroom import solve_bedroom
from planner.bedroom_checks import is_bed, side_on_wall
from planner.models import Item, Opening, Radiator, Room, Severity
from planner.validate import validate

ROOT = Path(__file__).resolve().parents[3]
UK = ROOT / "tools" / "scout" / "uk-bedrooms.json"

# эталон: sha256(json.dumps(<файл до 09.11>, sort_keys=True, ensure_ascii=False)) по коммиту cabfe9fc (main на старте
# задачи T-20261109-07). Меняется только осознанно — тогда прежние записи правились, а не дополнялись.
FROZEN = {
    "services/planner-solver/rules/bedroom.json": "8027995af1880c2e087051e76844473f73a49bb3ac9bcc7f9db113413a95b555",
    "tools/scout/rules/bedroom-composition.json": "324077eac29fc35848cf300b211a3b6359c122aada49b299cd5a734548e2f50a",
    "tools/scout/rules/bedroom-roles.json": "955a0fe64471429456d658a2ed404b1378feda0be7fde3d37516462d74b7f6df",
}
# ровно эти добавки (раздел → ключ); всё прочее — прежнее
ADDED = {
    "services/planner-solver/rules/bedroom.json": [("purposes", "single_narrow"), ("templates", "bed_narrow_wall"),
                                                   ("rules", "bed_narrow_side_wall")],
    "tools/scout/rules/bedroom-composition.json": [("purposes", "single_narrow")],
}
# добавки T-20261112-31 (боковая спинка, полоса прохода, ковёр) — тоже только дописаны, после добавок 09.11; раздел None — корень
ADDED_T31 = {
    "services/planner-solver/rules/bedroom.json": [("templates", "bed_side_back_corner"), ("rules", "bed_side_back_wall"),
                                                   ("rules", "bed_side_back_not_couple"), (None, "switches")],
    "tools/scout/rules/bedroom-roles.json": [(None, "bed_side_back")],
    "tools/scout/rules/bedroom-composition.json": [(None, "rug_fit")],
}


# добавки T-20261112-38/2 (движок групп) — дописаны после добавок T-31; ключи на «_» (пояснения) снимаются без проверки порядка
ADDED_T38 = {
    "services/planner-solver/rules/bedroom.json": [("_meta", "_engine_why"), ("_meta", "engine"),
                                                   ("rules", "bed_foot_not_in_swing"), ("rules", "bed_side_in_swing_soft"),
                                                   ("rules", "storage_front_radiator"), ("rules", "no_storage_at_bed_head_side"),
                                                   ("rules", "couple_small_no_wardrobe"), (None, "group_templates")],
}


# добавки T-20261112-68 (проходы по норме обычного жилья, ADR-0394) — дописаны после добавок T-38
ADDED_T68 = {
    "services/planner-solver/rules/bedroom.json": [("rules", "bed_long_side_window_wall"), ("rules", "route_to_window_and_bed_sides")],
}


def _drop_t38(name: str, d: dict, check_order: bool = False) -> dict:
    d = copy.deepcopy(d)
    for sec, key in reversed(ADDED_T38.get(name, []) + ADDED_T68.get(name, [])):
        tgt = d if sec is None else d[sec]
        if check_order and not key.startswith("_"):
            assert list(k for k in tgt if not k.startswith("_"))[-1] == key, f"{name}: {key} — не последним ключом"
        tgt.pop(key)
    return d


def _h(o) -> str:
    return hashlib.sha256(json.dumps(o, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _without_additions(name: str, d: dict) -> dict:
    d = _drop_t38(name, d, check_order=True)
    for sec, key in reversed(ADDED_T31.get(name, [])):
        tgt = d if sec is None else d[sec]
        assert list(k for k in tgt if not k.startswith("_"))[-1] == key, f"{name}: {key} — не последним ключом"
        tgt.pop(key)
    if name.endswith("bedroom-roles.json"):           # тег назначения — последним ключом у каждой роли
        n = 0
        for tags in d["purposes"].values():          # детские роли тега не получили — у них прежний набор
            if "single_narrow" in tags:
                assert list(tags)[-1] == "single_narrow", "новый тег должен идти после прежних"
                tags.pop("single_narrow")
                n += 1
        assert n == 6, n                              # кровать, тумба, комод, шкаф, стол рабочий, стул рабочий
        return d
    for sec, key in ADDED[name]:
        assert key in d[sec], (sec, key)
        d[sec].pop(key)
    return d


def _drop_t31(name: str, d: dict) -> dict:
    d = _drop_t38(name, d)
    for sec, key in ADDED_T31.get(name, []):
        (d if sec is None else d[sec]).pop(key)
    return d


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_old_entries_unchanged(name):
    cur = json.loads((ROOT / name).read_text(encoding="utf-8"))
    assert _h(_without_additions(name, cur)) == FROZEN[name], f"{name}: прежние записи изменились — добавлять, не править"


def test_additions_are_last_keys():
    br = _drop_t31("services/planner-solver/rules/bedroom.json",
                   json.loads((ROOT / "services/planner-solver/rules/bedroom.json").read_text(encoding="utf-8")))
    assert list(br["purposes"])[-1] == "single_narrow"
    assert list(k for k in br["templates"] if not k.startswith("_"))[-1] == "bed_narrow_wall"
    assert list(k for k in br["rules"] if not k.startswith("_"))[-1] == "bed_narrow_side_wall"
    assert br["templates"]["bed_narrow_wall"]["for"] == ["single_narrow"]
    assert br["purposes"]["single_narrow"]["bed_template"] == "bed_narrow_wall"
    # прежние назначения bed_template не задают — их путь шаблонов прежний
    assert not [k for k, v in br["purposes"].items() if k != "single_narrow" and "bed_template" in v]


def _uk(room_id: str, purpose: str = "single_narrow") -> Room:
    spec = next(r for r in json.loads(UK.read_text(encoding="utf-8"))["rooms"] if r["id"] == room_id)
    return Room(width_cm=spec["w"], depth_cm=spec["d"], room_type="bedroom", purpose=purpose,
                openings=[Opening(**o) for o in spec["openings"]],
                radiators=[Radiator(**r) for r in spec.get("radiators", [])])


NARROW = [Item(role="кровать", w_cm=96, d_cm=200, h_cm=90),          # UK single 90×190 в раме 96×200
          Item(role="тумба прикроватная", w_cm=40, d_cm=35, h_cm=50),
          Item(role="шкаф", w_cm=100, d_cm=58, h_cm=200),
          Item(role="комод", w_cm=80, d_cm=45, h_cm=85),
          Item(role="стол рабочий", w_cm=100, d_cm=55, h_cm=75),
          Item(role="стул рабочий", w_cm=50, d_cm=50, h_cm=85)]


def _sig(lay):
    return [(p.role, p.x, p.y, p.rot, p.tpl_id) for p in lay.placements]


@pytest.mark.parametrize("room_id", ["bedroom-three", "bedroom-two"])
def test_narrow_bed_fits_uk_rooms(room_id):
    room = _uk(room_id)
    lay = solve_bedroom(room, NARROW)
    hard = [v.message for v in lay.violations if v.severity is Severity.HARD]
    assert lay.ok and not hard, hard
    bed = next(p for p in lay.placements if is_bed(p))
    assert (bed.item.w_cm, bed.item.d_cm) == (96, 200)
    assert bed.tpl_id == "bed_narrow_wall"
    assert side_on_wall(room, bed), "длинный бок узкой кровати — к стене"
    assert not [v for v in lay.violations if v.code == "BED_NARROW_OFF_WALL"]
    re = validate(room, lay.placements)          # повторная проверка тем же диспетчером
    assert not [v for v in re.violations if v.severity is Severity.HARD]
    assert _sig(lay) == _sig(solve_bedroom(_uk(room_id), NARROW))      # детерминизм


def test_narrow_refuses_double_bed():
    lay = solve_bedroom(_uk("bedroom-two"), [Item(role="кровать", w_cm=160, d_cm=210, h_cm=95)])
    assert lay.meta["reason"] == ["BED_NOT_SINGLE"] and lay.unplaced == ["кровать"] and not lay.placements


def test_side_rule_only_for_narrow_purpose():
    """BED_NARROW_OFF_WALL — только у назначения с bed_template; прежнее single его не получает."""
    from planner.models import Placement
    room_n, room_s = _uk("bedroom-two"), _uk("bedroom-two", "single")
    mid = [Placement(role="кровать", item=NARROW[0], x=250, y=100, rot=0)]   # у южной стены, оба длинных бока далеко от стен
    codes_n = {v.code for v in validate(room_n, mid).violations}
    codes_s = {v.code for v in validate(room_s, mid).violations}
    assert "BED_NARROW_OFF_WALL" in codes_n
    assert "BED_NARROW_OFF_WALL" not in codes_s


def test_old_single_path_unchanged_in_box_room():
    """Прежнее single в тех же комнатах шаблон bed_narrow_wall не берёт (путь шаблонов прежний)."""
    lay = solve_bedroom(_uk("bedroom-three", "single"), NARROW)
    assert not [p for p in lay.placements if p.tpl_id == "bed_narrow_wall"]
