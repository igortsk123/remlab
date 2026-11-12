"""Приёмка Э2–Э5: beam search даёт валидные РАЗНЫЕ раскладки быстро, с объяснениями."""
from __future__ import annotations

import os
import time

import pytest

from planner.beam import solve
from planner.candidates import generate, order_items
from planner.explain import explain, why_not
from planner.geometry import footprint
from planner.models import Item
from planner.refine import refine
from planner.validate import validate
from tests.rooms import CATALOG, all_rooms

ROOMS = all_rooms()
LIVING_ROOM = ("диван", "тв-тумба", "столик", "кресло", "торшер", "кашпо")


def _items(roles=LIVING_ROOM) -> list[Item]:
    return [CATALOG[r].model_copy() for r in roles]


def test_order_puts_tv_and_sofa_first():
    roles = [it.role for it in order_items(_items())]
    assert roles[:2] == ["тв-тумба", "диван"], "ТВ-зона задаёт ось — ставится первой"
    assert roles.index("кресло") > roles.index("столик")


def test_candidates_exist_and_fit():
    room = ROOMS[2]
    item = CATALOG["диван"].model_copy()
    cands = generate(room, item, [])
    assert cands, "для дивана в пустой комнате обязаны быть кандидаты"
    assert {c.kind for c in cands} & {"wall", "corner"}
    for c in cands:
        assert int(c.placement.rot) % 90 == 0, "только осевые повороты"


def test_candidates_shrink_as_room_fills():
    room = ROOMS[2]
    sofa = CATALOG["диван"].model_copy()
    first = generate(room, sofa, [])
    placed = [first[0].placement]
    second = generate(room, CATALOG["шкаф"].model_copy() if "шкаф" in CATALOG else sofa, placed)
    assert len(second) <= len(first)


SPEED_CASES = (0, 2, 4, 9)


def _ref_cpu() -> float:
    """Эталонная нагрузка той же библиотеки, что у перебора (shapely + чистый Python), — секунды процессора. Мерка «сколько
    стоит работа на этой машине сейчас»: занятые соседями ядра и кэш замедляют её так же, как движок."""
    from shapely.geometry import Point, box
    c, acc = time.process_time(), 0.0
    for i in range(4000):
        a, b = box(0, 0, 200 + i % 50, 150), box(100, 50 + i % 30, 300, 260)
        acc += a.intersection(b).area + Point(i % 90, 40).buffer(35, quad_segs=8).intersection(a).area
        acc += a.distance(b) + sum(1 for _ in range(60))
    return time.process_time() - c


@pytest.fixture(scope="module")
def solved():
    """Случаи скорости считаются ОДИН раз на модуль: валидность и скорость читают один и тот же прогон. Эталон — до и после
    каждого случая (нагрузка машины плавает), берётся медиана."""
    import statistics
    res, refs = {}, [_ref_cpu()]
    for idx in SPEED_CASES:
        t, c = time.time(), time.process_time()
        outs = solve(ROOMS[idx], _items(), top_k=3)
        res[idx] = (outs, time.process_time() - c, time.time() - t)
        refs.append(_ref_cpu())
    return res, statistics.median(refs)


@pytest.mark.parametrize("idx", SPEED_CASES)
def test_solve_returns_valid_diverse_layouts(idx, solved):
    outs, cpu, dt = solved[0][idx]
    assert outs, "движок обязан вернуть хотя бы один вариант"
    assert outs[0].ok, f"лучший вариант забракован: {why_not(outs[0])}"
    # Защита от зависания — везде; скорость движка — `test_solve_speed_vs_machine` (здесь только явная поломка).
    # Время ПРОЦЕССОРА, не часы (T-20261112-87): перебор однопоточный, без пулов и бюджета времени — ожидание процессора на
    # занятой машине работой движка не считается. На раннере GitHub случаи — 16–18 с по часам (08.09).
    assert cpu < 25.0, f"слишком долго: {cpu:.1f} с процессора ({dt:.1f} с по часам)"
    assert dt < 120.0, f"похоже на зависание: {dt:.1f} с по часам"


# ПОРОГ СКОРОСТИ — ОТНОСИТЕЛЬНО МАШИНЫ, НЕ В СЕКУНДАХ (T-20261112-87). Был «каждый случай < 9 с» (08.09, тихая DEV: 4,9–7,8 с).
# 12.11 на занятой DEV (load 18–49 на 15 ядрах) тот же код давал 9,4–19,5 с ПРОЦЕССОРА — 10 прогонов из 10 красные, номера
# «плавали»; виновного коммита нет (версии 12.11 — 7,6–14,7 с вперемешку, версия до 05.11 — 15–27 с: движок ускорился).
# Теперь: Σ(время процессора 4 случаев) / эталон shapely той же минуты. Замер 12.11, 3 круга, load 9–22: HEAD 416639ff —
# 38,6 / 44,8 / 45,7; версия 6aaf114e (до 05.11, вдвое медленнее) — 77,9 / 83,8 / 92,9. Порог 60 ловит замедление ~×1,35.
# На CI не проверяем: отношение снято на процессоре DEV, на другом железе его надо мерить заново (там держит 25 с выше).
SPEED_RATIO_MAX = 60.0


@pytest.mark.skipif(bool(os.environ.get('CI')), reason="отношение откалибровано на DEV; на CI — защита 25 с процессора на случай")
def test_solve_speed_vs_machine(solved):
    res, ref = solved
    total = sum(cpu for _, cpu, _ in res.values())
    ratio = total / ref
    assert ratio < SPEED_RATIO_MAX, (f"движок потяжелел: {total:.1f} с процессора на {len(res)} случая = {ratio:.1f} эталонов "
                                     f"(эталон {ref:.2f} с, порог {SPEED_RATIO_MAX:g}; HEAD 12.11 — 39–46)")


def test_unsolvable_room_gets_explicit_reason():
    """Каморка 200×260: диван 220 см физически не влезает.

    Движок обязан не врать «всё хорошо», а назвать, что именно не встало (требование спеки).
    """
    from planner.models import Opening, Room

    room = Room(width_cm=200, depth_cm=260, band="14-16",
                openings=[Opening(kind="door", wall="south", offset_cm=20, width_cm=90, swing_cm=100)])
    best = solve(room, _items(), top_k=1)[0]
    assert not best.ok
    reason = why_not(best)
    assert reason and "диван" in reason


def test_top_k_variants_differ():
    room = ROOMS[2]
    outs = solve(room, _items(), top_k=3)
    assert len(outs) >= 2
    a, b = outs[0], outs[1]
    moved = max(((p.x - q.x) ** 2 + (p.y - q.y) ** 2) ** 0.5
                for p in a.placements for q in b.placements if p.role == q.role)
    assert moved > 30, "варианты должны реально отличаться, а не быть клонами"


def test_determinism_same_input_same_output():
    room = ROOMS[2]
    a = solve(room, _items(), top_k=3)
    b = solve(room, _items(), top_k=3)
    ka = [[(p.role, round(p.x, 3), round(p.y, 3), p.rot) for p in l.placements] for l in a]
    kb = [[(p.role, round(p.x, 3), round(p.y, 3), p.rot) for p in l.placements] for l in b]
    assert ka == kb


def test_zone_is_assembled_not_scattered():
    """Главный вердикт владельца по старому солверу: зона разваливалась."""
    room = ROOMS[2]
    best = solve(room, _items(), top_k=1)[0]
    by = {p.role: p for p in best.placements}
    sofa, tv, tbl = by["диван"], by["тв-тумба"], by["столик"]
    assert (int(sofa.rot) - int(tv.rot)) % 360 == 180, "диван и ТВ смотрят друг на друга"
    assert footprint(sofa).distance(footprint(tbl)) < 70, "столик у дивана"
    assert footprint(by["кресло"]).distance(footprint(tbl)) <= 120, "кресло в полукруге"


def test_refine_fixes_a_broken_layout():
    room = ROOMS[2]
    ps = solve(room, _items(), top_k=1, polish=False)[0].placements
    broken = [p.model_copy(update={"x": p.x + 12, "y": p.y + 12}) if p.role == "столик" else p
              for p in ps]
    before = validate(room, broken)
    after = refine(room, before)
    assert len(after.violations) <= len(before.violations)


def test_explanations_are_human_readable():
    room = ROOMS[2]
    best = solve(room, _items(), top_k=1)[0]
    e = explain(room, best)
    assert isinstance(e["score"], float)
    assert e["strengths"], "у валидного варианта должны быть сильные стороны"
    assert all(isinstance(t, str) for t in e["tradeoffs"])
    assert why_not(best) is None


def test_why_not_explains_invalid_layout():
    room = ROOMS[2]
    ps = solve(room, _items(), top_k=1)[0].placements
    broken = [p.model_copy(update={"x": p.x + 200}) if p.role == "тв-тумба" else p for p in ps]
    layout = validate(room, broken)
    assert not layout.ok and why_not(layout)


def test_polygon_room_L_shape():
    """Э8: Г-контур (референс владельца — кухня-гостиная) — beam расставляет внутри контура."""
    from planner.beam import solve
    from planner.geometry import room_polygon, footprint
    from planner.models import Item, Opening, Room
    room = Room(width_cm=1, depth_cm=1, band="21-25",
                contour=[(0, 0), (620, 0), (620, 780), (320, 780), (320, 420), (0, 420)],
                openings=[Opening(kind="door", wall="south", offset_cm=40, width_cm=90,
                                  swing_cm=92)])
    assert room.width_cm == 620 and room.depth_cm == 780   # bbox из контура
    items = [Item(role="диван", w_cm=220, d_cm=95, h_cm=85),
             Item(role="тв-тумба", w_cm=160, d_cm=40, h_cm=50),
             Item(role="столик", w_cm=100, d_cm=60, h_cm=45),
             Item(role="кресло", w_cm=80, d_cm=85, h_cm=80)]
    outs = solve(room, items, top_k=1)
    assert outs, "Г-контур должен решаться"
    lay = outs[0]
    assert "диван" not in lay.unplaced and "тв-тумба" not in lay.unplaced
    rp = room_polygon(room).buffer(1)
    for p in lay.placements:
        assert rp.contains(footprint(p)), f"{p.role} вне контура"
