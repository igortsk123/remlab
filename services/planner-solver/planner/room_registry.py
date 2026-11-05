"""РЕЕСТР ТИПОВ КОМНАТ солвера (T-20261105-37, план room-pipeline-01): тип комнаты → плагин (проверки, позже солвер).

Раньше `validate.validate` уводил в проверки гостиной всё, кроме спальни: кухня и прихожая получали бессмысленный
«успех» (разбор Codex 05.11). Теперь проверки ищутся здесь по `room.room_type`; тип без плагина — ошибка
`TipKomnatyNeZaregistrirovan`, а не гостиная.

Плагин — строка «модуль:функция» в `PLAGINY`. Модуль грузится при первом обращении (без циклического импорта:
проверки спальни импортируют общие проверки из `validate`). Своя комната — СВОЙ файл, общие (`models.py`,
`validate.py`) не трогать:
  проверки — `def validate_<тип>(room, placements, *, passage="secondary", fast_hard=False) -> Layout`;
  кухня — `planner/kitchen_checks.py:validate_kitchen`, прихожая — `planner/hall_checks.py:validate_hall`.
Пока файла нет, тип не зарегистрирован (ошибка при проверке). `fast_hard=True` — путь поиска: выход на первом hard
(см. `validate.validate`). Общие физические проверки — из `validate` (`check_boundary`, `check_collisions`,
`check_openings`, `check_radiators`, `check_wall_only`), как у спальни (`bedroom_checks.validate_bedroom`).
"""
from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, get_args

from .models import RoomType

if TYPE_CHECKING:
    from .models import Layout, Placement, Room

Proverki = Callable[..., "Layout"]  # (room, placements, *, passage, fast_hard) -> Layout


class TipKomnatyNeZaregistrirovan(ValueError):
    """У типа комнаты нет плагина нужного вида (проверок): путь гостиной для него не годится."""


@dataclass(frozen=True, slots=True)
class Plagin:
    """Что умеет тип комнаты: «модуль:функция» проверок и (позже) солвера; None — места нет."""

    proverki: str | None
    solver: str | None = None


PLAGINY: dict[str, Plagin] = {
    "living": Plagin("planner.validate:validate_living"),
    "bedroom": Plagin("planner.bedroom_checks:validate_bedroom", "planner.bedroom:solve_bedroom"),
    "kitchen": Plagin("planner.kitchen_checks:validate_kitchen"),  # T-33: файл кухни
    "hall": Plagin("planner.hall_checks:validate_hall", "planner.hall:solve_hall"),  # T-34: файлы прихожей
}
assert set(PLAGINY) == set(get_args(RoomType)), "реестр и models.RoomType разошлись"

_NAYDENO: dict[tuple[str, str], Callable[..., object]] = {}


def _zagruzit(room_type: str, vid: str) -> Callable[..., object]:
    if (room_type, vid) in _NAYDENO:
        return _NAYDENO[(room_type, vid)]
    plagin = PLAGINY.get(room_type)
    if plagin is None:
        raise TipKomnatyNeZaregistrirovan(f"тип комнаты «{room_type}» неизвестен солверу (известны: "
                                          f"{', '.join(PLAGINY)}) — планер не подставляет проверки гостиной")
    put = getattr(plagin, vid)
    if put is None:
        raise TipKomnatyNeZaregistrirovan(f"у типа комнаты «{room_type}» нет плагина «{vid}»")
    modul, _, funkciya = put.partition(":")
    try:
        fn = getattr(importlib.import_module(modul), funkciya)
    except ModuleNotFoundError as e:
        if e.name != modul:  # сломан импорт ВНУТРИ плагина — это его ошибка, не «нет плагина»
            raise
        raise TipKomnatyNeZaregistrirovan(f"тип комнаты «{room_type}»: плагин «{vid}» ещё не написан ({modul}.py "
                                          f"нет) — проверки гостиной к нему не применяются") from None
    except AttributeError:
        raise TipKomnatyNeZaregistrirovan(f"тип комнаты «{room_type}»: в {modul} нет функции {funkciya}") from None
    _NAYDENO[(room_type, vid)] = fn
    return fn


def proverki(room_type: str) -> Proverki:
    """Функция проверок типа комнаты; нет — `TipKomnatyNeZaregistrirovan`."""
    return _zagruzit(room_type, "proverki")  # type: ignore[return-value]


def solver(room_type: str) -> Callable[..., object]:
    """Солвер типа комнаты (место под общий конвейер; гостиная пока решается своим путём, без реестра)."""
    return _zagruzit(room_type, "solver")


def proverit(room: Room, placements: list[Placement], *, passage: str = "secondary",
             fast_hard: bool = False) -> Layout:
    return proverki(room.room_type)(room, placements, passage=passage, fast_hard=fast_hard)
