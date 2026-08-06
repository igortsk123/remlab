"""20 тест-комнат: 7 метражных бэндов проекта + вытянутые/узкие/с эркером-выступом.

Ручная («эталонная») раскладка строится детерминированно по правилам проекта: диван у
северной стены лицом на юг, ТВ-тумба у южной, столик — по шкале диван↔столик, кресло —
на дуге сбоку (ADR-0051). Приёмка Э1: валидатор согласен с этими раскладками.
"""
from __future__ import annotations

from planner.clearances import band_scale
from planner.models import Item, Opening, Placement, Radiator, Room

BANDS = ["14-16", "17-20", "21-25", "26-30", "31-40", "41-50", "50+"]
BAND_M2 = {"14-16": 15, "17-20": 18.5, "21-25": 23, "26-30": 28, "31-40": 35, "41-50": 45, "50+": 55}


def make_room(band: str, ratio: float = 1.15, m2: float | None = None) -> Room:
    area = (m2 or BAND_M2[band]) * 10_000
    w = round((area / ratio) ** 0.5 / 5) * 5
    d = round(area / w / 5) * 5
    return Room(
        width_cm=w,
        depth_cm=d,
        band=band,
        openings=[
            Opening(kind="door", wall="south", offset_cm=20, width_cm=90, swing_cm=100),
            Opening(kind="window", wall="east", offset_cm=d * 0.3, width_cm=min(160, d * 0.4), sill_cm=80),
        ],
        radiators=[Radiator(wall="east", offset_cm=d * 0.3, width_cm=min(160, d * 0.4))],
    )


def all_rooms() -> list[Room]:
    """7 бэндов × нормальная пропорция + вытянутые/узкие/квадратные варианты = 20 комнат."""
    rooms = [make_room(b) for b in BANDS]                                  # 7
    rooms += [make_room(b, ratio=2.2) for b in ("17-20", "21-25", "31-40", "41-50")]   # 4 вытянутые
    rooms += [make_room(b, ratio=1.0) for b in ("14-16", "26-30", "50+")]  # 3 квадратные
    rooms += [make_room(b, ratio=2.8) for b in ("21-25", "31-40")]         # 2 узкие
    rooms += [make_room("14-16", m2=14), make_room("50+", m2=60),
              make_room("26-30", ratio=1.6), make_room("41-50", ratio=1.35)]  # 4 краевые
    return rooms


CATALOG = {
    "диван": Item(role="диван", w_cm=220, d_cm=95, h_cm=85),
    "тв-тумба": Item(role="тв-тумба", w_cm=140, d_cm=42, h_cm=45),
    "столик": Item(role="столик", w_cm=100, d_cm=55, h_cm=45),
    "кресло": Item(role="кресло", w_cm=80, d_cm=80, h_cm=95),
    "торшер": Item(role="торшер", w_cm=35, d_cm=35, h_cm=160),
    "кашпо": Item(role="кашпо", w_cm=40, d_cm=40, h_cm=90),
}


def manual_layout(room: Room) -> list[Placement]:
    """Эталонная ручная раскладка под комнату (по нашим шкалам от площади)."""
    tv_lo, tv_hi = band_scale("sofa_tv_cm", room.band, [180, 300])
    tb_lo, tb_hi = band_scale("sofa_table_cm", room.band, [36, 50])
    gap_tbl = (tb_lo + tb_hi) / 2
    sofa, tvs, tbl, arm = (CATALOG[r].model_copy() for r in ("диван", "тв-тумба", "столик", "кресло"))
    # диван по ширине комнаты (узкая комната — короче), но не уже 160
    sofa.w_cm = max(160, min(sofa.w_cm, room.width_cm - 120))
    cx = room.width_cm / 2
    sofa_y = room.depth_cm - sofa.d_cm / 2
    sofa_front = sofa_y - sofa.d_cm / 2
    tv_y = tvs.d_cm / 2
    # ТВ-тумба у южной стены; если расстояние вылезает за шкалу — диван «отплывает» от стены
    gap = sofa_front - tvs.d_cm
    if gap > tv_hi:
        off = gap - tv_hi
        # щель за спинкой 20–76 см запрещена (SOFA_SLIVER, правило владельца 2026-08-02):
        # либо вплотную к стене (ТВ дальше шкалы — это лишь мягкий штраф), либо полный проход
        if 20 <= off < 76:
            off = 0.0 if off < 48 else 76.0
        sofa_y -= off
        sofa_front = sofa_y - sofa.d_cm / 2
    # ТВ-тумба не должна попадать в дугу двери на южной стене (в узких комнатах — двигаем)
    tv_x = cx
    for op in room.openings:
        if op.wall != "south" or op.swing_cm <= 0:
            continue
        d0, d1 = op.offset_cm, op.offset_cm + op.width_cm
        tvs.w_cm = min(tvs.w_cm, room.width_cm - d1 - 30)
        if tv_x - tvs.w_cm / 2 < d1 + 5:
            tv_x = min(room.width_cm - tvs.w_cm / 2 - 10, d1 + 5 + tvs.w_cm / 2)
    ps = [
        Placement(role="диван", x=cx, y=sofa_y, rot=180, item=sofa),
        Placement(role="тв-тумба", x=tv_x, y=tv_y, rot=0, item=tvs),
        Placement(role="столик", x=cx, y=sofa_front - gap_tbl - tbl.d_cm / 2, rot=180, item=tbl),
    ]
    # кресло на дуге 225° (запад от зоны), лицом к ТВ; в тесной комнате — пропускаем
    ax = cx - sofa.w_cm / 2 - 20 - arm.w_cm / 2
    ay = sofa_front - arm.d_cm / 2 - 10
    if ax - arm.w_cm / 2 > 25:
        ps.append(Placement(role="кресло", x=ax, y=ay, rot=180, item=arm))
    return ps
