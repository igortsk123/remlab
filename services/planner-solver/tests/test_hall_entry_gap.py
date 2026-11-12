"""ЩЕЛЬ У ВХОДА (T-20261112-93; находка T-20261112-70): проход от входной двери меряется от того места, куда человек
ШАГАЕТ из двери (`hall_checks._entry_step`, глубина need/2 + `ENTRY_STEP_CM`), а не от глубокой полосы `_mouth` (need + 2).
Глубокая полоса дотягивалась за узкое место у самой двери: кусок пола за щелью «касался входа», и `route_ok` склеивал
его с куском у двери — щель 82 см между обувницей у входа и шкафом по диагонали сходила за 85.

Сцены — `tools/scout/hall-scenes.json` (c160x600, corner150x400), раскладки — шаблоны прихожей из T-70 (до растровой
мерки). Плюс обратная сторона: настоящий проход 85+ у двери по-прежнему проходит."""
import json
import math
import os

import pytest

from planner.hall_checks import ENTRY_STEP_CM, check_hall_passages, route_ok, validate_hall
from planner.models import Item, Opening, Placement, Room, Severity

SCENES = os.path.join(os.path.dirname(__file__), "..", "..", "..", "tools", "scout", "hall-scenes.json")


def scene(key: str) -> Room:
    s = json.load(open(SCENES, encoding="utf-8"))["rooms"][key]
    return Room(width_cm=s["w"], depth_cm=s["d"], contour=s.get("contour"),
                openings=[Opening(**{k: v for k, v in o.items() if not k.startswith("_")}) for o in s["openings"]])


def P(role, w, d, h, x, y, rot, elev=0.0) -> Placement:
    return Placement(role=role, x=x, y=y, rot=rot, elev_cm=elev, item=Item(role=role, w_cm=w, d_cm=d, h_cm=h))


def c160(shoe_d: float = 23.0) -> list[Placement]:
    """c160x600 (вход юг 35–125): обувница у западной стены у входа (глубина `shoe_d`), купе на востоке с y=90.
    Щель по диагонали — от угла обувницы (shoe_d, 60) до угла купе (100, 90)."""
    return [P("шкаф-купе", 210, 60, 230, 130, 195, 270),
            P("обувница", 60, shoe_d, 110, shoe_d / 2, 30, 90),
            P("банкетка", 67, 30, 49, 145, 33.5, 270),
            P("консоль", 92, 40, 79, 140, 426, 270),
            P("зеркало", 63.5, 3, 97.5, 158.5, 31.8, 270, 101.2)]


def corner() -> list[Placement]:
    """corner150x400 (вход в юго-западном углу 0–90): обувница у восточной стены у входа, купе на западе с y=190."""
    return [P("шкаф-купе", 210, 60, 230, 30, 295, 90),
            P("обувница", 60, 38, 102, 131, 30, 270),
            P("банкетка", 67, 30, 49, 135, 93.5, 270),
            P("консоль", 90, 30, 76, 15, 125, 90),
            P("зеркало", 63.5, 3, 97.5, 1.5, 108.2, 90, 101.2)]


def gap(shoe_d: float) -> float:
    return math.hypot(100 - shoe_d, 90 - 60)


def hard(room, ps) -> set[str]:
    return {v.code for v in check_hall_passages(room, ps) if v.severity is Severity.HARD}


@pytest.mark.parametrize("room, ps", [(scene("c160x600"), c160()), (scene("corner150x400"), corner())], ids=["c160", "corner"])
def test_gap_at_entrance_is_caught(room, ps):
    ok, lost, _main = route_ok(room, ps, 85)
    assert not ok and lost, "щель < 85 у входа: дальние двери недоступны"
    assert hard(room, ps) & {"HALL_DOOR_UNREACHABLE", "HALL_UNREACHABLE"}
    lay = validate_hall(room, ps)
    assert any(v.severity is Severity.HARD for v in lay.violations)


def test_c160_gap_is_really_under_norm():
    assert gap(23) < 85 - 2           # 82,6 см: не округление, а настоящая щель


@pytest.mark.parametrize("shoe_d", [12.0, 17.0])
def test_real_85_at_entrance_still_passes(shoe_d):
    """Та же прихожая с узкой обувницей: щель ≥ 85 — проход есть, как и раньше."""
    assert gap(shoe_d) > 85 + 2
    room = scene("c160x600")
    ok, lost, _main = route_ok(room, c160(shoe_d), 85)
    assert ok and not lost
    assert not hard(room, c160(shoe_d))


def test_cabinet_flush_at_entrance_jamb_passes():
    """Обувница вплотную к косяку входа (законная площадка входа) — проход 85 у двери 90 не режется."""
    room = scene("c160x600")
    ps = [P("обувница", 60, 35, 100, 17.5, 30, 90),           # x 0–35 = ровно до косяка (вход 35–125)
          P("шкаф-купе", 170, 60, 230, 130, 205, 270)]            # восток y 120–290: до двери востока 300; щель 88
    assert route_ok(room, ps, 85)[0]
    assert not hard(room, ps)


def test_empty_rooms_unchanged():
    """Пустая комната: мерка входа не делает дверей недоступными (база `HALL_ROOM_NARROW` прежняя)."""
    for key in ("c110x400", "c160x600", "corner150x400", "sq200", "wide250x350", "l250x300", "bath150x400"):
        ok, lost, _main = route_ok(scene(key), [], 85)
        assert ok and not lost, key


def test_entry_step_is_shallow():
    assert 0 < ENTRY_STEP_CM <= 10    # шаг из двери — сантиметры, не глубина прохода
