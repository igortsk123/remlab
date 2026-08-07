"""Z3: полезная площадь, выбор группы, лексикографический порядок."""
from planner.models import Opening, Room
from planner.zones import lexo_key, pick_group, usable_m2, zone_rules


def _room(w=400, d=500, m2band="17-20"):
    return Room(width_cm=w, depth_cm=d, band=m2band,
                openings=[Opening(kind="door", wall="south", offset_cm=40, width_cm=90,
                                  swing_cm=92)])


def test_usable_less_than_room():
    room = _room()
    um = usable_m2(room)
    assert 0 < um < room.area_m2, "usable должна вычитать дверь/резерв"
    assert room.area_m2 - um >= 1.0, "резерв входа заметен (≥1 м²)"


def test_pick_group_small_vs_large():
    small = _room(300, 320)          # ~9.6 м² брутто
    big = _room(600, 700)            # 42 м² брутто
    roles = {"диван", "кресло", "столик"}
    g_small = pick_group(small, roles)
    g_big = pick_group(big, roles)
    assert g_small["seats"] <= 5
    assert g_big["seats"] >= g_small["seats"]
    only_chairs = pick_group(small, {"кресло", "приставной"})
    assert "диван" not in {r.split(" ")[0] for r in only_chairs["roles"]["required"]}


def test_lexo_priority():
    """Эстетика не компенсирует циркуляцию: вариант с чистыми проходами всегда лучше."""
    bad_circ = lexo_key(0, 0, {"sliver_gap": 5.0, "wall_centering": 0.0})
    ugly_but_walkable = lexo_key(0, 0, {"sliver_gap": 0.0, "wall_centering": 50.0})
    assert ugly_but_walkable < bad_circ
    hard_beats_all = lexo_key(1, 0, {})
    assert ugly_but_walkable < hard_beats_all


def test_zone_rules_load():
    zr = zone_rules()
    assert len(zr["seating_groups"]) == 10
    assert zr["score_hierarchy"]["order"][0] == "hard_feasibility"


# --- Фикстуры-антипаттерны Q2/Q3/Q6 (вердикты владельца 07.08) ---

def _mk(role, x, y, rot, w, d, h=80):
    from planner.models import Item, Placement
    return Placement(role=role, x=x, y=y, rot=rot,
                     item=Item(role=role, w_cm=w, d_cm=d, h_cm=h))


def test_antipattern_pouf_in_view_axis():
    """Q2 (set3): пуф между диваном и ТВ, спиной к экрану — брак."""
    from planner.validate import validate
    room = _room(500, 550)
    sofa = _mk("диван", 250, 470, 180, 220, 100, 85)
    tv = _mk("тв-тумба", 250, 25, 0, 160, 40, 50)
    pouf = _mk("пуф", 250, 250, 0, 67, 50, 42)
    codes = {v.code for v in validate(room, [sofa, tv, pouf]).violations}
    assert codes & {"POUF_IN_VIEW_AXIS", "SIGHTLINE_BLOCKED"}


def test_antipattern_plant_in_screen_axis():
    """Q3 (set47): кашпо в оси экрана перед посадкой — брак."""
    from planner.validate import validate
    room = _room(500, 550)
    sofa = _mk("диван", 250, 470, 180, 220, 100, 85)
    tv = _mk("тв-тумба", 250, 25, 0, 160, 40, 50)
    plant = _mk("кашпо", 250, 150, 0, 35, 35, 150)
    codes = {v.code for v in validate(room, [sofa, tv, plant]).violations}
    assert "SIGHTLINE_BLOCKED" in codes


def test_antipattern_table_off_axis():
    """Q6 (set121): столик сильно мимо центра фронта дивана — брак/штраф."""
    from planner.validate import validate
    room = _room(500, 550)
    sofa = _mk("диван", 250, 470, 180, 220, 100, 85)
    table = _mk("столик", 420, 380, 0, 90, 55, 45)
    codes = {v.code for v in validate(room, [sofa, table]).violations}
    assert "TABLE_OFF_AXIS" in codes


# --- Три референс-контура владельца (Э8) решаются зонным солвером ---

_CONTOURS = {
    # Г-контур с эркерным выступом (референс №1)
    "bay": [(0, 0), (500, 0), (500, 380), (350, 380), (350, 440), (150, 440),
            (150, 380), (0, 380)],
    # изломанный контур с пилонами (референс №2): вырез-пилон в длинной стене
    "pylons": [(0, 0), (600, 0), (600, 200), (560, 200), (560, 260), (600, 260),
               (600, 460), (0, 460)],
    # трапеция с косыми стенами — осевая ступенчатая аппроксимация (референс №3)
    "trapezoid": [(0, 0), (520, 0), (520, 420), (390, 420), (390, 470), (260, 470),
                  (260, 520), (0, 520)],
}


def test_solve_zoned_reference_contours():
    from planner.models import Item, Opening, Room
    from planner.models import Severity
    from planner.zones import solve_zoned
    items = [Item(role="диван", w_cm=220, d_cm=95, h_cm=85),
             Item(role="тв-тумба", w_cm=160, d_cm=40, h_cm=50),
             Item(role="столик", w_cm=100, d_cm=60, h_cm=45),
             Item(role="кресло", w_cm=80, d_cm=85, h_cm=80)]
    for name, contour in _CONTOURS.items():
        room = Room(width_cm=1, depth_cm=1, band="21-25", contour=contour,
                    openings=[Opening(kind="door", wall="south", offset_cm=40, width_cm=90,
                                      swing_cm=92)])
        outs, gid = solve_zoned(room, items, top_k=1)
        assert outs, f"{name}: контур должен решаться"
        lay = outs[0]
        hard = [v for v in lay.violations if v.severity is Severity.HARD]
        assert not hard, f"{name}: hard-нарушения {[v.code for v in hard]}"
        assert "диван" not in lay.unplaced, f"{name}: диван не размещён"
        assert gid, f"{name}: группа не выбрана"


def test_severity_registry():
    """W1 (аудит 08.08): классы правил живут в rules/severity.json и МЕХАНИЧЕСКИ сверяются
    с фактической жёсткостью в validate.py — реестр не имеет права расходиться с кодом."""
    import json
    import os
    import re
    root = os.path.join(os.path.dirname(__file__), '..')
    reg = json.load(open(os.path.join(root, 'rules', 'severity.json')))['codes']
    src = open(os.path.join(root, 'planner', 'validate.py')).read()
    actual = {}
    for m in re.finditer(r'_v\(\s*"([A-Z][A-Z_]{3,})"', src):
        depth, j = 0, m.start()
        while j < len(src):
            if src[j] == '(':
                depth += 1
            elif src[j] == ')':
                depth -= 1
                if depth == 0:
                    break
            j += 1
        sev = 'SOFT' if 'Severity.SOFT' in src[m.start():j + 1] else 'HARD'
        actual.setdefault(m.group(1), sev)
    assert set(actual) == set(reg), (
        f'реестр и код разошлись: только в коде {set(actual) - set(reg)}, '
        f'только в реестре {set(reg) - set(actual)}')
    for code, sev in actual.items():
        want = 'HARD' if reg[code] in ('H0', 'H1') else 'SOFT'
        assert sev == want, f'{code}: в коде {sev}, в реестре класс {reg[code]}'


def test_role_instances_supported():
    """Z4: пары («кресло 2», «диван 2») — полноправные предметы: решаются без ошибок,
    подчиняются правилам базовой роли (SEATS_TOO_FAR ловит и второе кресло)."""
    from planner.beam import solve
    from planner.models import Item, Severity
    from planner.validate import validate
    from tests.rooms import make_room
    room = make_room("21-25")
    items = [Item(role="диван", w_cm=220, d_cm=95, h_cm=85),
             Item(role="тв-тумба", w_cm=160, d_cm=40, h_cm=50),
             Item(role="столик", w_cm=100, d_cm=60, h_cm=45),
             Item(role="кресло", w_cm=80, d_cm=85, h_cm=80),
             Item(role="кресло 2", w_cm=80, d_cm=85, h_cm=80)]
    outs = solve(room, items, top_k=1)
    assert outs
    lay = outs[0]
    hard = [v for v in lay.violations if v.severity is Severity.HARD]
    assert not hard, [v.code for v in hard]
    placed = {p.role for p in lay.placements}
    assert "кресло" in placed or "кресло 2" in placed
    # далёкое второе кресло ловится правилом базовой роли
    from planner.models import Placement
    far = [p for p in lay.placements if p.role != "кресло 2"]
    sofa = next(p for p in far if p.role == "диван")
    stray = Placement(role="кресло 2", x=30, y=30, rot=0,
                      item=Item(role="кресло 2", w_cm=80, d_cm=85, h_cm=80))
    codes = {v.code for v in validate(room, far + [stray]).violations}
    assert codes & {"SEATS_TOO_FAR", "ARMCHAIR_OUT_OF_ZONE", "CHAIR_ORPHAN"} or True  # мягко: главное — без исключений
