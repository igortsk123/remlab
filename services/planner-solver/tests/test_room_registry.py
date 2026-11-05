"""Реестр типов комнат (T-20261105-37, план room-pipeline-01): кухня и прихожая без своего плагина НЕ получают
проверки гостиной, неизвестный тип — ошибка; гостиная и спальня — прежние функции проверок."""
from __future__ import annotations

import sys
import types
from typing import get_args

import pytest
from pydantic import ValidationError

from planner import room_registry, validate as validate_mod
from planner.models import Item, Layout, Placement, Room, RoomType


def _room(room_type: str) -> Room:
    return Room(width_cm=400, depth_cm=300, room_type=room_type)


def _sofa() -> list[Placement]:
    # диван наполовину за стеной: у гостиной это hard-нарушения, «успеха» быть не может
    return [Placement(role="диван", item=Item(role="диван", w_cm=220, d_cm=95), x=-50, y=60, rot=0)]


def test_reestr_sovpadaet_s_tipami() -> None:
    assert set(room_registry.PLAGINY) == set(get_args(RoomType)) == {"living", "bedroom", "kitchen", "hall"}


@pytest.mark.parametrize("room_type", ["kitchen", "hall"])
def test_kuhnya_i_prihozhaya_bez_plagina_ne_gostinaya(room_type: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Пока T-33/T-34 не положили свои файлы — ошибка; проверки гостиной не вызываются вовсе."""
    monkeypatch.delitem(sys.modules, f"planner.{room_type}_checks", raising=False)
    monkeypatch.setattr(room_registry, "_NAYDENO", {})
    vyzovy: list[str] = []
    monkeypatch.setattr(validate_mod, "validate_living", lambda *a, **k: vyzovy.append("living"))
    real = room_registry.importlib.import_module

    def bez_plagina(name: str, *a: object) -> object:
        if name == f"planner.{room_type}_checks":
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return real(name, *a)

    monkeypatch.setattr(room_registry.importlib, "import_module", bez_plagina)
    with pytest.raises(room_registry.TipKomnatyNeZaregistrirovan, match=room_type):
        validate_mod.validate(_room(room_type), _sofa())
    with pytest.raises(room_registry.TipKomnatyNeZaregistrirovan):
        validate_mod.validate(_room(room_type), _sofa(), fast_hard=True)
    assert vyzovy == []


def test_neizvestnyy_tip_oshibka() -> None:
    with pytest.raises(ValidationError):
        _room("garage")
    with pytest.raises(room_registry.TipKomnatyNeZaregistrirovan, match="garage"):
        validate_mod.validate(Room.model_construct(width_cm=400, depth_cm=300, room_type="garage", contour=None,
                                                   openings=[], radiators=[]), _sofa())


def test_plagin_komnaty_iz_svoego_fayla(monkeypatch: pytest.MonkeyPatch) -> None:
    """Так T-33/T-34 подключают свои проверки: файл `planner/<тип>_checks.py` с `validate_<тип>` — без правок
    `models.py`/`validate.py`; аргументы `passage`/`fast_hard` доходят."""
    poluchil: list[tuple[str, str, bool]] = []

    def validate_hall(room: Room, placements: list[Placement], *, passage: str = "secondary",
                      fast_hard: bool = False) -> Layout:
        poluchil.append((room.room_type, passage, fast_hard))
        return Layout(room=room, placements=placements, violations=[], floor_used_pct=0.0)

    modul = types.ModuleType("planner.hall_checks")
    modul.validate_hall = validate_hall  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "planner.hall_checks", modul)
    monkeypatch.setattr(room_registry, "_NAYDENO", {})
    lay = validate_mod.validate(_room("hall"), _sofa(), passage="main", fast_hard=True)
    assert lay.violations == [] and poluchil == [("hall", "main", True)]


def test_slomannyy_import_vnutri_plagina_ne_skryvaetsya(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ошибка импорта ВНУТРИ файла плагина — его дефект, а не «плагина нет»: видна как есть."""
    monkeypatch.setattr(room_registry, "_NAYDENO", {})

    def slomano(name: str, *a: object) -> object:
        raise ModuleNotFoundError("No module named 'shapely_x'", name="shapely_x")

    monkeypatch.setattr(room_registry.importlib, "import_module", slomano)
    with pytest.raises(ModuleNotFoundError, match="shapely_x"):
        room_registry.proverki("kitchen")


def test_gostinaya_i_spalnya_prezhnie_funkcii() -> None:
    from planner.bedroom_checks import validate_bedroom

    assert room_registry.proverki("living") is validate_mod.validate_living
    assert room_registry.proverki("bedroom") is validate_bedroom
    from planner.bedroom import solve_bedroom

    assert room_registry.solver("bedroom") is solve_bedroom
    with pytest.raises(room_registry.TipKomnatyNeZaregistrirovan):
        room_registry.solver("living")  # гостиная решается своим путём, не через реестр
    kody = {v.code for v in validate_mod.validate(_room("living"), _sofa()).violations}
    assert kody == {v.code for v in validate_mod.validate_living(_room("living"), _sofa()).violations} and kody
