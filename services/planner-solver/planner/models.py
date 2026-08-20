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
    # СТОРОНА ПЕТЕЛЬ (замечание владельца 12.08): створка открывается в ОДНУ сторону,
    # а не в обе. Держим четверть круга у своей петли, а не полосу во всю ширину —
    # прежняя модель съедала лишнее место у входа.
    hinge: Literal["left", "right"] = "left"


class Radiator(BaseModel):
    wall: Wall
    offset_cm: float = Field(ge=0)
    width_cm: float = Field(gt=0)
    depth_cm: float = Field(default=12, gt=0)


class Room(BaseModel):
    """Комната: прямоугольник (width×depth) или произвольный контур (Э8, [[layout-polygon-rooms]]).

    `contour` — вершины (см), обход любой; пока поддержаны ОСЕВЫЕ рёбра (Г/П-контуры, пилоны —
    референсы владельца а/б); косые стены (трапеция, референс в) — следующий шаг: требуют
    неквантованных поворотов в доводке. width/depth при контуре = его bbox (шкалы от площади и
    легаси-код продолжают работать)."""

    width_cm: float = Field(gt=0)
    depth_cm: float = Field(gt=0)
    contour: list[tuple[float, float]] | None = Field(default=None)
    openings: list[Opening] = Field(default_factory=list)
    radiators: list[Radiator] = Field(default_factory=list)
    band: str | None = Field(default=None, description="метражный бэнд проекта, напр. '21-25'")
    ceiling_cm: float | None = Field(default=None, description="высота потолка (D5, свод №5); нет значения — правило вертикального масштаба спит")

    @model_validator(mode="after")
    def _contour_bbox(self) -> "Room":
        if self.contour:
            xs = [p[0] for p in self.contour]
            ys = [p[1] for p in self.contour]
            object.__setattr__(self, "width_cm", max(xs) - min(xs))
            object.__setattr__(self, "depth_cm", max(ys) - min(ys))
        return self

    @property
    def area_m2(self) -> float:
        if self.contour:
            from .geometry import room_polygon
            return room_polygon(self).area / 10_000
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
    corner_side_fixed: bool = False   # сторона угла задана SKU — зеркало не пробовать
    # Q6a/Q6b (Codex 17.08): СПОСОБНОСТИ SKU из capability-проекции каталога (`tools/scout/capabilities.py`)
    # — не пересчитывать их из габаритов в солвере (места банкетки = guaranteed_seats, а не w/60).
    # Пусто = данных нет (unknown), НЕ «нет способности»: шаблон, требующий caps, тогда не собирается.
    caps: dict = Field(default_factory=dict)
    # Q6d свода №13: круглый/овальный предмет (стол, столик) — след ОКРУЖНОСТЬ реального
    # диаметра, а не описанный прямоугольник: bbox круга Ø110 «съедает» 0.32 м² лишнего пола
    # и режет компактные схемы (dining_round_compact был sleeping именно поэтому)
    round_shape: bool = False


class Placement(BaseModel):
    """Предмет, поставленный в точку: центр footprint + поворот."""

    role: str
    x: float
    y: float
    rot: float = 0
    item: Item | None = None
    elev_cm: float = Field(default=0, ge=0, description="подъём над полом: ТВ на стене, люстра")
    # ПРОСЛЕЖИВАЕМОСТЬ ШАБЛОНА (ADR template-integrity, 12.08): каким паспортом схемы
    # поставлен предмет. Пусто = вне шаблона; при LAYOUT_ONLY_TEMPLATES=1 это ошибка.
    tpl_id: str = ""
    tpl_version: str = ""
    # V3-H свода №9 (PACKAGE I): точная схема/вариант блока (default/u/facing/…),
    # для identity зоны в экспорте; пусто у зон без вариантов
    tpl_variant: str = ""
    # Q12-4 (ADR-0112, CPSC Anchor It): требование МОНТАЖА, а не геометрии — высокий корпус
    # обязан крепиться к стене. Планировщик его не решает, но обязан донести до сборки/сметы.
    installation_requirement: str = ""

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
    # П8: произвольные метаданные раскладки (топ-пары ТВ↔диван и т.п.)
    meta: dict = Field(default_factory=dict)

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
