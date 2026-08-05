"""Контракты геометрического ядра (Э1 plan prod-layout-engine).

Система координат — top-down, сантиметры, как в scout/solver_run.py:
  x  — вправо (0 … room.width_cm), y — вглубь (0 … room.depth_cm);
  y=0 — «южная» стена (стена ТВ по умолчанию), y=depth — «северная» (обычно диван).
Поворот rot — градусы по часовой; направление «лица» предмета:
  rot 0 → +y, rot 90 → +x, rot 180 → −y, rot 270 → −x  (диван у северной стены = rot 180).
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Wall = Literal["south", "north", "west", "east"]


class Severity(str, Enum):
    HARD = "hard"
    SOFT = "soft"


class Opening(BaseModel):
    """Проём в стене: дверь (с дугой открывания), окно, балконная дверь."""

    kind: Literal["door", "window", "balcony"]
    wall: Wall
    offset_cm: float = Field(ge=0, description="от начала стены (запад→восток / юг→север)")
    width_cm: float = Field(gt=0)
    swing_cm: float = Field(
        default=0, ge=0, description="глубина зоны открывания внутрь комнаты (двери)"
    )
    sill_cm: float = Field(default=0, ge=0, description="высота подоконника (окна)")


class Radiator(BaseModel):
    wall: Wall
    offset_cm: float = Field(ge=0)
    width_cm: float = Field(gt=0)
    depth_cm: float = Field(default=12, gt=0)


class Room(BaseModel):
    """Прямоугольная комната (Э1). Полигональные комнаты — расширение Э2+."""

    width_cm: float = Field(gt=0)
    depth_cm: float = Field(gt=0)
    openings: list[Opening] = Field(default_factory=list)
    radiators: list[Radiator] = Field(default_factory=list)
    band: str | None = Field(default=None, description="метражный бэнд проекта, напр. '21-25'")

    @property
    def area_m2(self) -> float:
        return self.width_cm * self.depth_cm / 10_000


class Item(BaseModel):
    """Предмет каталога, приведённый к габаритам (см)."""

    role: str
    w_cm: float = Field(gt=0)
    d_cm: float = Field(gt=0)
    h_cm: float | None = None
    name: str | None = None
    item_id: str | None = None
    corner: bool = Field(default=False, description="Г-образный диван — полигон из 6 точек")
    corner_section_cm: float = Field(default=95, gt=0, description="глубина секции Г-дивана")
    corner_left: bool = Field(default=False, description="плечо Г-дивана на левой стороне")


class Placement(BaseModel):
    """Предмет, поставленный в точку: центр footprint + поворот."""

    role: str
    x: float
    y: float
    rot: float = 0
    item: Item | None = None
    elev_cm: float = Field(default=0, ge=0, description="подъём над полом: ТВ на стене, люстра")

    @model_validator(mode="after")
    def _role_matches(self) -> "Placement":
        if self.item is not None and self.item.role != self.role:
            raise ValueError(f"placement.role={self.role} != item.role={self.item.role}")
        return self


class Violation(BaseModel):
    code: str
    severity: Severity
    message: str
    roles: list[str] = Field(default_factory=list)
    value: float | None = None
    expected: str | None = None


class Layout(BaseModel):
    """Раскладка + результат проверки (объяснимость — требование спеки)."""

    room: Room
    placements: list[Placement]
    violations: list[Violation] = Field(default_factory=list)
    floor_used_pct: float | None = None
    unplaced: list[str] = Field(default_factory=list, description="базовое/крупное, что НЕ встало — это проблема")
    skipped_optional: list[str] = Field(default_factory=list,
                                        description="опциональное, для которого не нашлось места — норма")

    @property
    def ok(self) -> bool:
        """Валидна = нет hard-нарушений И всё ОБЯЗАТЕЛЬНОЕ размещено.

        Пропуск опционального (кресло/пуф/кашпо в тесной комнате) браком не считается —
        состав гостиной зависит от площади (чек-лист + решение владельца 2026-08-03).
        """
        return not self.unplaced and not any(v.severity is Severity.HARD for v in self.violations)
