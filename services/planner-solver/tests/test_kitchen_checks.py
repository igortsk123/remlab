"""Проверки кухни — плагин типа комнаты (`planner/kitchen_checks.py`, реестр T-20261105-37): годная посадка экзамена
проходит их без жёстких нарушений (вторая, независимая проверка ответа посадки), сдвинутые предметы ловятся, два вида
кадра — внутри комнаты. Подключение через реестр — когда реестр влит (до того тест пропускается)."""
from __future__ import annotations

import pytest

from planner.kitchen import ROLE_FRIDGE, ROLE_RUN, ROLE_TABLE, ROLE_TALL, kitchen_placements
from planner.kitchen_checks import validate_kitchen
from planner.models import Severity
from tests.test_kitchen_seating import FLAT, SCENES, _room, _run

OK_SCENES = [s for s in SCENES["scenes"] if s["expect"]["ok"]]


def _spec(scene: dict) -> dict:
    return FLAT if scene["room"] == "flat215" else SCENES["rooms"][scene["room"]]


def _hard(lay) -> list[str]:
    return sorted({v.code for v in lay.violations if v.severity is Severity.HARD})


@pytest.mark.parametrize("scene", OK_SCENES, ids=lambda s: s["id"])
def test_seating_passes_kitchen_checks(scene):
    room = _room(_spec(scene))
    ps = kitchen_placements(room, _run(scene))
    assert ps[0].role == ROLE_RUN
    assert _hard(validate_kitchen(room, ps)) == []


def _flat(kit: str = "sima-300"):
    s = {"room": "flat215", "kit": kit, "vent": "flat215"}
    room = _room(FLAT)
    return room, kitchen_placements(room, _run(s))


def test_run_on_door_is_caught():
    room, ps = _flat()
    run = next(p for p in ps if p.role == ROLE_RUN)
    door = next(o for o in room.openings if o.kind == "door")
    moved = run.model_copy(update={"x": room.width_cm - run.item.d_cm / 2, "y": door.offset_cm + door.width_cm / 2, "rot": 270})
    others = [p for p in ps if p.role not in (ROLE_RUN, ROLE_TABLE)]
    hard = _hard(validate_kitchen(room, [moved, *others]))
    assert {"DOOR_SWING", "DOOR_PASSAGE"} & set(hard), hard


def test_tall_at_window_is_caught():
    room, ps = _flat()
    tall = next(p for p in ps if p.role == ROLE_TALL)
    win = next(o for o in room.openings if o.kind == "window")
    moved = tall.model_copy(update={"x": tall.item.d_cm / 2, "y": win.offset_cm - 20, "rot": 90})
    assert "KITCHEN_WINDOW_TALL" in _hard(validate_kitchen(room, [moved]))


def test_table_in_work_aisle_is_caught():
    room, ps = _flat()
    run = next(p for p in ps if p.role == ROLE_RUN)
    table = next(p for p in ps if p.role == ROLE_TABLE)
    moved = table.model_copy(update={"x": run.x, "y": run.item.d_cm + 40})
    assert "KITCHEN_AISLE" in _hard(validate_kitchen(room, [run, moved]))


def test_low_sill_under_run_is_caught():
    spec = SCENES["rooms"]["r12-sill-high"]
    low = {**spec, "openings": [{**spec["openings"][0], "sill_cm": 80}] + spec["openings"][1:]}
    r = _run({"room": "r12-sill-high", "kit": "base-240-open", "vent": {"wall": "south", "offset_cm": 200}})
    assert r["wall"] == "south"
    room_low = _room(low)
    assert "KITCHEN_WINDOW_SILL" in _hard(validate_kitchen(room_low, kitchen_placements(room_low, r)))


def test_fridge_present_when_not_in_column():
    _, ps = _flat("sima-240")
    assert any(p.role == ROLE_FRIDGE for p in ps)


@pytest.mark.parametrize("scene", OK_SCENES[:8], ids=lambda s: s["id"])
def test_two_views_inside_room(scene):
    spec = _spec(scene)
    v = _run(scene)["views"]
    assert set(v) == {"kit", "counter"}
    for view in v.values():
        for pt in (view["eye"], view["target"]):
            assert -0.5 <= pt["x"] <= spec["w"] + 0.5 and -0.5 <= pt["y"] <= spec["d"] + 0.5


def test_registry_routes_kitchen_here():
    room_registry = pytest.importorskip("planner.room_registry", reason="реестр типов комнат (T-37) ещё не влит")
    from planner import validate as validate_mod
    assert room_registry.proverki("kitchen") is validate_kitchen
    room, ps = _flat()
    lay = validate_mod.validate(room, ps)
    assert _hard(lay) == [] and any(v.code == "KITCHEN_NO_TABLE" for v in lay.violations) is False


def test_kitchen_fit_file_is_fresh():
    """`data/partners/kitchen-fit/flat215.json` = пересчёт `tools/scout/kitchen_fit.py` (правила или посадка поменялись —
    пересчитай файл, иначе набор и 3D возьмут старую посадку)."""
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("kitchen_fit", root / "tools" / "scout" / "kitchen_fit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.OUT.read_text(encoding="utf-8") == mod.dump(mod.build()), "kitchen-fit устарел: python3 tools/scout/kitchen_fit.py"
