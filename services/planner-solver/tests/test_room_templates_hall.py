"""Паспорт прихожей `rules/room-templates/hall.json` (T-20261112-70/1 — ТЕНЬ, движок `planner/hall.py` его не читает):
схема чиста, спальня и гостиная не сломаны; семейства H1–H9 × ветки хранения (CS купе, CH распашной, M модуль, OW вешалка)
разворачиваются в места; хранение — ветка, а не ступень (внутри шаблона одно и то же на всех уровнях); уровни — целые составы
в порядке уступок консоль → банкетка → зеркало → обувница; H7 «ниша» — надстройка к закрытым веткам; выбор по флагам формы
(`WHEN_FLAGS`); числа — только `rule_ref` на настоящие ключи occupancy.json; поломанные копии паспорта ловятся."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from planner import room_templates as RT

RULES = Path(__file__).resolve().parent.parent / "rules"
FAMILIES = {"H1": "CS CH M OW", "H2": "OW M", "H3": "CS CH M OW", "H4": "CS CH M", "H5": "CS CH M OW",
            "H6": "CS CH M OW", "H8": "OW", "H9": "OW"}
IDS = [f"{f}.{b}" for f, bs in FAMILIES.items() for b in bs.split()]
STORAGE = {"шкаф-купе", "шкаф", "прихожая", "вешалка", "крючки"}
BRANCH_ROLE = {"CS": "шкаф-купе", "CH": "шкаф", "M": "прихожая", "OW": "вешалка"}
YIELD = ["консоль", "банкетка", "зеркало", "обувница"]       # порядок уступок (Codex § 3)
OTHER = "open_other"      # «другое хранение» у веток купе (владелец TG 907, T-20261112-72): купе не влезло → вешалка подписью
HALL_KEYS = ["hall_route", "hall_door_head_on", "hall_door_side_750", "hall_door_side_775", "hall_door_side_800",
             "hall_hinged_front", "hall_sliding_front", "hall_shoe_tilt", "hall_bench_front", "hall_entry_inside"]


def _branch_levels(tpl):
    return [lv for lv in tpl["levels"] if lv["use"].get("storage") != OTHER]


def _doc():
    return copy.deepcopy(RT.load("hall"))


def _tpl(doc, tid):
    return next(t for t in doc["templates"] if t["id"] == tid)


def _err(doc):
    return " | ".join(RT.check(doc))


def test_hall_passport_clean():
    doc = RT.load("hall")
    assert RT.check(doc) == []
    assert doc["room_type"] == "hall"
    assert {t["id"] for t in doc["templates"]} == set(IDS) | {"H7", "H10.SH"}


def test_other_passports_still_clean():
    assert RT.check(RT.load("bedroom")) == []
    assert RT.check(RT.load("living")) == []


@pytest.mark.parametrize("tid", IDS)
def test_each_level_compiles_and_keeps_branch_storage(tid):
    doc = RT.load("hall")
    tpl = _tpl(doc, tid)
    assert tpl["levels"]
    want = BRANCH_ROLE[tid.split(".")[1]]
    for lv in tpl["levels"]:
        places, err = RT.compile_level(doc, tpl, lv["id"])
        assert err == [], (tid, lv["id"], err)
        roles = [p["role"] for p in places]
        other = lv["use"].get("storage") == OTHER       # «другое хранение» — только у купе и только с подписью
        assert not other or (tid.endswith(".CS") and "другое хранение" in lv["label"]), (tid, lv["id"])
        assert [r for r in roles if r in STORAGE] == (["вешалка"] if other else [want]), (tid, lv["id"], roles)
        assert roles.count("зеркало") <= 1
        for p in places:
            if p["kind"] == "dependent":                                   # зеркало над низкой — только при носителе
                assert p["role"] == "зеркало" and p["on_failure"] == "reject_composition"


@pytest.mark.parametrize("tid", IDS)
def test_levels_yield_whole_items_in_order(tid):
    """Уровни — целые составы: каждый следующий = предыдущий без ровно одного предмета, и уходят они в порядке YIELD."""
    doc = RT.load("hall")
    tpl = _tpl(doc, tid)
    prev = None
    for lv in _branch_levels(tpl):
        places, _ = RT.compile_level(doc, tpl, lv["id"])
        roles = {p["role"] for p in places} - {"коврик"}      # коврик — на всех уровнях (TG 1176), не ступень уступок
        if prev is not None:
            gone = prev - roles
            assert roles < prev and len(gone) == 1, (tid, lv["id"], gone)
            assert gone <= set(YIELD)
            assert all(r not in roles for r in YIELD[: YIELD.index(gone.pop())]), (tid, lv["id"])
        prev = roles
    assert _branch_levels(tpl)[-1]["id"] == "E" and len(prev) == 1      # последний ветки — только хранение
    rest = tpl["levels"][len(_branch_levels(tpl)):]
    assert [lv["use"]["storage"] for lv in rest] == ([OTHER, OTHER] if tid.endswith(".CS") else [])   # после ветки, не вперемешку


def test_niche_modifier_applies_to_closed_branches_only():
    doc = RT.load("hall")
    h7 = _tpl(doc, "H7")
    assert h7["modifier"] and h7["applies_to"]
    assert all(t.endswith((".CS", ".CH")) for t in h7["applies_to"])
    for base in h7["applies_to"]:
        btpl = _tpl(doc, base)
        places, err = RT.compile_level(doc, h7, "N", base=(btpl, "C"))
        assert err == [], err
        assert [p["role"] for p in places if p["role"] in STORAGE] == ["шкаф-купе"], base   # шкаф ветки заменён купе в нише


@pytest.mark.parametrize("facts, first", [
    ({"has_stairs": True, "shape_l": True, "area_m2": 9}, "H9.OW"),
    ({"micro": True, "area_m2": 1.2}, "H8.OW"),
    ({"shape_l": True, "door_dense": True}, "H6.CS"),
    ({"door_dense": True, "area_m2": 9}, "H3.CS"),
    ({"squareish": True, "area_m2": 4}, "H5.CS"),
    ({"has_niche": True, "area_m2": 7}, "H4.CS"),          # ниша — надстройка, не выбор семейства
    ({}, "H4.CS"),
])
def test_selection_by_shape_flags(facts, first):
    order = RT.select(RT.load("hall"), facts)
    assert order[0] == first
    assert "H7" not in order
    assert order[-1] == "H10.SH"                # короткая прихожая — последний запас в каждом правиле (владелец TG 907)
    assert order[-2].startswith(("H8", "H2"))   # перед ней — узкая линия / тамбур
    assert len(order) == len(set(order))


def test_shape_flags_are_room_facts_not_numbers():
    for k in ("shape_l", "has_niche", "has_stairs", "door_dense", "squareish", "micro"):
        assert k in RT.WHEN and k in RT.WHEN_FLAGS
        assert RT.when_ok([{"kind": k}], {k: True})
        assert not RT.when_ok([{"kind": k}], {k: False})
        assert not RT.when_ok([{"kind": k}], {})              # неизвестный факт — условие не выполнено


def test_rule_refs_point_to_real_occupancy_keys():
    occ = json.loads((RULES / "occupancy.json").read_text())
    refs = []

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k == "rule_ref":
                    refs.append(v)
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(RT.load("hall"))
    assert refs, "паспорт без rule_ref — числа должны идти ссылками на occupancy.json"
    for r in refs:
        node = occ
        for k in r.split("."):                       # вложенные ключи: distances_cm.clearances.hall_route
            assert isinstance(node, dict) and k in node, r
            node = node[k]
    # проходы — по стране (T-20261112-72): прежних ключей 85 / 90 / 120 / 60 в паспорте больше нет; полоса 76 перед дверью
    # (глубина без мебели) — без страны, ширину пути у двери держит hall_route.door_zone
    old = {"distances_cm.hall_passage_min", "distances_cm.hall_passage_comfort", "distances_cm.hall_entry_depth",
           "distances_cm.bench_legroom"}
    assert not old & set(refs)
    assert "distances_cm.clearances.hall_route" in refs


@pytest.mark.parametrize("key", HALL_KEYS)
def test_hall_clearances_by_country(key):
    """У каждого прохода прихожей — числа РФ и UK отдельно и источник у каждой страны (где нормы нет — так и сказано)."""
    cl = json.loads((RULES / "occupancy.json").read_text())["distances_cm"]["clearances"]
    spec = cl[key]
    assert "general" not in spec                     # не профиль-исключение, а страна
    for c in ("ru", "uk"):
        t = spec[c]
        assert set(t) == {"target", "compact", "hard"}
        assert t["target"] >= t["compact"] >= t["hard"] > 0, (key, c, t)
        assert isinstance(spec["_source"][c], str) and len(spec["_source"][c]) > 10, (key, c)
    assert set(cl["_countries"]) >= {"ru", "uk", "default", "_source"}
    assert "m4_2" in cl["_profiles"] and "mgn" in cl["_profiles"]    # надстройки доступности остались


def test_hall_route_local_narrowing_rule():
    r = json.loads((RULES / "occupancy.json").read_text())["distances_cm"]["clearances"]["hall_route"]
    assert r["uk"] == {"target": 90, "compact": 75, "hard": 75}       # ADM M4(1) 1.15 / табл. 1.1
    assert r["ru"] == r["uk"]                                          # владелец TG 907: РФ — так же
    assert r["local_max_length"] == 200 and r["door_zone"] > 0


def test_short_hall_template():
    """H10 «зашёл, повесил, пошёл»: крючки или вешалка (+ полка над ними, + коврик), без шкафа и обувницы."""
    doc = RT.load("hall")
    tpl = _tpl(doc, "H10.SH")
    seen = set()
    for lv in tpl["levels"]:
        places, err = RT.compile_level(doc, tpl, lv["id"])
        assert err == [], (lv["id"], err)
        roles = [p["role"] for p in places]
        seen |= set(roles)
        assert [r for r in roles if r in STORAGE] in (["крючки"], ["вешалка"]), (lv["id"], roles)
        assert not {"шкаф-купе", "шкаф", "прихожая", "обувница", "банкетка", "консоль"} & set(roles)
        for p in places:
            if p["role"] == "полка":
                assert p["kind"] == "dependent" and p["on_failure"] == "leave_empty"
    assert {"крючки", "вешалка", "полка", "коврик"} <= seen
    assert {"shelf", "mat"} <= set(doc["order"])
    assert RT.select(doc, {"micro": True})[-1] == "H10.SH"


def test_no_bare_numbers_in_rules():
    """Пороги — только rule_ref: в predicates/relations нет числовых полей (кроме count носителя)."""
    for t in RT.load("hall")["templates"]:
        for sec in ("predicates", "relations"):
            for x in t.get(sec, []):
                assert not [k for k, v in x.items() if isinstance(v, (int, float)) and not isinstance(v, bool)], (t["id"], x)


@pytest.mark.parametrize("break_it, msg", [
    (lambda d: d["templates"][0]["levels"][0]["use"].update({"storage": "wall_hooks"}), "storage"),
    (lambda d: d["templates"][-1]["applies_to"].append("H99.CS"), "H99.CS"),
    (lambda d: d["groups"]["mirror"]["variants"]["over_low"]["dependents"][0].pop("carrier"), "carrier"),
    (lambda d: d["selection"][0]["when"].append({"kind": "has_garage"}), "has_garage"),
    (lambda d: d["templates"][1].setdefault("relations", []).append({"kind": "mirror_on_ceiling"}), "mirror_on_ceiling"),
    (lambda d: d["templates"][2]["levels"][0]["use"].pop("storage"), "storage"),
])
def test_broken_copies_are_caught(break_it, msg):
    doc = _doc()
    break_it(doc)
    err = _err(doc)
    assert err and msg in err, err


# ---- листы прихожей `tools/scout/hall_schemes.py` (растр — scipy; в окружении решателя без scipy — пропуск) ----
@pytest.fixture
def hs():
    """Модуль листов с числами РФ; `norms` подменяет числа движка в процессе — после теста вернуть (иначе соседние тесты
    движка прихожей считают по стране)."""
    pytest.importorskip("scipy")
    pytest.importorskip("PIL")
    import sys
    scout = Path(__file__).resolve().parents[3] / "tools" / "scout"
    if str(scout) not in sys.path:
        sys.path.insert(0, str(scout))
    import hall_schemes as mod
    prev = mod.norms("ru")
    yield mod
    mod.norms(prev)


def _corridor(hs, gap_y):
    """Коридор 150×400: вход с юга, дверь на севере; обувница у западной и банкетка у восточной стены друг напротив
    друга на высоте gap_y — щель между ними 80 (уже цели 90, но не уже местных 75)."""
    room = hs.to_room({"w": 150, "d": 400, "radiators": [],
                       "openings": [hs._d("south", 30, 90, ent=True), hs._d("north", 30, 80)]})
    shoe = hs.Placement(role="обувница", x=17.5, y=gap_y, rot=90, item=hs.Item(role="обувница", w_cm=30, d_cm=35, h_cm=50))
    bench = hs.Placement(role="банкетка", x=132.5, y=gap_y, rot=270, item=hs.Item(role="банкетка", w_cm=30, d_cm=35, h_cm=45))
    return room, [shoe, bench]


def test_hall_narrowing_at_door_is_caught(hs):
    """T-20261112-72/3: короткая щель 80 между двумя предметами в полосе у входа — «у двери» (раньше круг цели её закрывал
    и 80 у входа сходило за 90), та же щель в середине коридора — допустимое местное сужение."""
    room, near = _corridor(hs, 60)
    loc = hs.local_narrowing(room, near, 75)
    assert loc["at_door"] and not loc["ok"], loc
    room, far = _corridor(hs, 250)
    loc = hs.local_narrowing(room, far, 75)
    assert loc["ok"] and not loc["at_door"], loc
    room, _ = _corridor(hs, 60)
    assert hs.local_narrowing(room, [], 75)["ok"]                    # пустой коридор 150 — без сужения


def test_sheet_pinch_sits_in_the_real_gap(hs):
    """T-20261112-72/4: точка «узкое место» на листе — в самой щели (середина коридора), а не у входа; число в ней —
    та же ширина, с которой путь проходит целиком (`best_width`), как мерит сверка по полосам (diag_zone)."""
    room, far = _corridor(hs, 250)
    bw = hs.best_width(room, far)
    assert bw == 80
    _paths, pinch = hs.route_paths(room, far, bw, widest=True)
    assert pinch is not None
    w, (x, y) = pinch
    assert 230 <= y <= 270 and 55 <= x <= 95, pinch          # в щели между обувницей и банкеткой
    assert bw - 2 <= w <= bw + 4, pinch
    room, near = _corridor(hs, 60)
    _paths, pinch = hs.route_paths(room, near, hs.best_width(room, near), widest=True)
    assert pinch and 40 <= pinch[1][1] <= 80, pinch           # щель у входа — точка у входа


def test_hall_shelf_slides_from_corner(hs):
    """T-20261112-72/3: полка над крючками в углу сдвигается вдоль стены (в пределах стены, над крючками)."""
    room = hs.to_room({"w": 100, "d": 120, "radiators": [], "openings": [hs._d("south", 10, 80, ent=True)]})
    hooks = hs.Placement(role="крючки", x=2, y=15, rot=90, item=hs.Item(role="крючки", w_cm=30, d_cm=4, h_cm=8))
    poly = hs.room_polygon(room)
    shelf = {"w": 50, "d": 20, "h": 15}
    fp = hs.shelf_over(poly, hooks, shelf)
    assert fp is not None and fp.difference(poly).area <= 1.0
    assert fp.contains(hs.footprint(hooks).centroid.buffer(1)) or fp.buffer(0.5).covers(hs.footprint(hooks).centroid)
    lo, hi = fp.bounds[1], fp.bounds[3]
    assert lo >= -0.5 and hi - lo == pytest.approx(50, abs=0.5) and lo <= 0 + 0.5 and hi >= 30   # прижата к углу, над крючками
    need = [{"role": "полка", "kind": "dependent"}]
    out, empty, miss = hs.place_extras(room, [hooks], need, {"полка": [shelf]})
    assert miss is None and [o[0] for o in out] == ["полка"] and empty == []


def test_hall_shelf_wider_than_hooks(hs):
    """Владелец TG 1221 (T-20261112-72/4): полка над крючками может быть шире крючков — до свободной длины стены, выше
    головы; проход не меняет. Шкаф или дверь на стене — полка сдвигается мимо них или не ставится (строка почему)."""
    room = hs.to_room({"w": 100, "d": 120, "radiators": [], "openings": [hs._d("south", 20, 80, ent=True)]})
    hooks = hs.Placement(role="крючки", x=2, y=15, rot=90, item=hs.Item(role="крючки", w_cm=30, d_cm=4, h_cm=8))
    need = [{"role": "полка", "kind": "dependent"}]
    wide = {"w": 80.5, "d": 19, "h": 26}
    # дверь в 10 см от угла: полка не висит над её проёмом — уходит от двери, но остаётся над крючками (≥ 3/4)
    near = hs.to_room({"w": 100, "d": 120, "radiators": [], "openings": [hs._d("south", 10, 80, ent=True)]})
    out, empty, _ = hs.place_extras(near, [hooks], need, {"полка": [wide]})
    lo, hi = out[0][1].bounds[1], out[0][1].bounds[3]
    assert lo >= 4.5 and min(hi, 30) - lo >= 0.75 * 30 - 0.5, (out, empty)
    placed = [hooks]
    bw0, pinch0 = hs.best_width(room, placed), hs.route_paths(room, placed, 60, widest=True)[1]
    out, empty, miss = hs.place_extras(room, placed, need, {"полка": [wide]})
    assert miss is None and empty == [] and [o[0] for o in out] == ["полка"], (out, empty)
    fp = out[0][1]
    lo, hi = fp.bounds[1], fp.bounds[3]
    assert hi - lo == pytest.approx(80.5, abs=0.5) and lo <= 0.5 and hi >= 30, fp.bounds   # накрывает крючки, у угла
    # полка висит выше головы: в расстановку не попадает, ширина прохода и узкое место те же
    assert placed == [hooks]
    assert hs.best_width(room, placed) == bw0 and hs.route_paths(room, placed, 60, widest=True)[1] == pinch0
    # шкаф вплотную над крючками (высокий) — полка 80 не влезает, узкая 30 — встаёт
    tall = hs.Placement(role="шкаф", x=25, y=70, rot=90, item=hs.Item(role="шкаф", w_cm=40, d_cm=50, h_cm=210))
    out, empty, miss = hs.place_extras(room, [hooks, tall], need, {"полка": [wide]})
    assert out == [] and miss is None and "не помещается на свободной стене" in empty[0], (out, empty)
    out, empty, miss = hs.place_extras(room, [hooks, tall], need, {"полка": [wide, {"w": 30, "d": 19, "h": 26}]})
    assert [o[3]["w"] for o in out] == [30], (out, empty)
    # низкая обувница под полкой не мешает
    low = hs.Placement(role="обувница", x=12, y=70, rot=90, item=hs.Item(role="обувница", w_cm=60, d_cm=23, h_cm=90))
    out, empty, miss = hs.place_extras(room, [hooks, low], need, {"полка": [wide]})
    assert [o[3]["w"] for o in out] == [80.5], (out, empty)


def test_mat_in_every_hall_template():
    """Владелец TG 1176 (T-20261112-72/3): коврик у входа — в каждом уровне каждого шаблона (H7 — надстройка ниши, без
    своего пола); на листе не лёг — строка почему, а состав уровня не роняется."""
    doc = RT.load("hall")
    for t in doc["templates"]:
        if t["id"] == "H7":
            continue
        for lv in t["levels"]:
            assert lv["use"].get("mat") == "door", (t["id"], lv["id"])
            places, err = RT.compile_level(doc, t, lv["id"])
            assert err == [] and "коврик" in [p["role"] for p in places], (t["id"], lv["id"], err)


def test_mat_never_drops_the_level(hs):
    """Коврик не лёг (мебель у входа) или нет товара — строка почему, состав уровня остаётся (TG 1176)."""
    room = hs.to_room({"w": 100, "d": 120, "radiators": [], "openings": [hs._d("south", 10, 80, ent=True)]})
    need = [{"role": "коврик"}]
    out, empty, miss = hs.place_extras(room, [], need, {"коврик": [{"w": 90, "d": 60, "h": 1}]})
    assert miss is None and [o[0] for o in out] == ["коврик"] and empty == []
    box = hs.Placement(role="обувница", x=50, y=30, rot=0, item=hs.Item(role="обувница", w_cm=100, d_cm=60, h_cm=50))
    out, empty, miss = hs.place_extras(room, [box], need, {"коврик": [{"w": 90, "d": 60, "h": 1}]})
    assert miss is None and out == [] and "коврик: не ложится" in empty[0], empty
    out, empty, miss = hs.place_extras(room, [], need, {})
    assert miss is None and out == [] and "нет товара" in empty[0], empty
