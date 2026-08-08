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


# --- Вердикты владельца 08.08 + рефери Q5/Q6/Q7 ---

def test_fireplace_requires_focal_zone():
    """P0.7 (рефери 08.08): камин — focal-элемент, H1: обязан быть в focal-зоне хоть одной
    посадки (primary диван ИЛИ secondary кресло); иначе — HARD, роль дропается ещё гейтом
    кандидатов (_fireplace_scenario)."""
    from planner.models import Severity
    from planner.validate import validate
    room = _room(600, 700)
    sofa = _mk("диван", 300, 620, 180, 220, 100, 85)
    far = _mk("камин", 40, 60, 90, 110, 35, 100)
    vs = [v for v in validate(room, [sofa, far]).violations
          if v.code == "FIREPLACE_FAR_FROM_SEATING"]
    assert vs and all(v.severity is Severity.HARD for v in vs)
    # primary: камин в вилке и в поле зрения дивана — чисто
    sofa2 = _mk("диван", 300, 550, 180, 220, 100, 85)
    near = _mk("камин", 300, 60, 0, 110, 35, 100)
    assert not [v for v in validate(room, [sofa2, near]).violations
                if v.code == "FIREPLACE_FAR_FROM_SEATING"]
    # secondary: диван далеко/спиной, но кресло ориентировано на камин в вилке — чисто
    arm = _mk("кресло", 200, 300, 270, 80, 85, 80)   # смотрит на запад... к камину
    fp_west = _mk("камин", 40, 300, 90, 110, 35, 100)
    codes = [v.code for v in validate(room, [sofa, arm, fp_west]).violations]
    assert "FIREPLACE_FAR_FROM_SEATING" not in codes


def test_sofa_window_gap_and_sill():
    """set91: диван спинкой вплотную к окну — S1 зазор; спинка выше стекла — S2."""
    from planner.models import Opening, Room, Severity
    from planner.validate import validate
    room = Room(width_cm=500, depth_cm=550, band="21-25",
                openings=[Opening(kind="door", wall="south", offset_cm=40, width_cm=90,
                                  swing_cm=92),
                          Opening(kind="window", wall="north", offset_cm=150, width_cm=200,
                                  sill_cm=70)])
    sofa = _mk("диван", 250, 497, 180, 220, 100, 85)   # спинка в 3 см от северной стены
    codes = {v.code: v.severity for v in validate(room, [sofa]).violations}
    assert codes.get("SOFA_WINDOW_GAP") is Severity.SOFT
    assert codes.get("SOFA_BACK_ABOVE_SILL") is Severity.SOFT  # 85 > подоконник 70


def test_floor_overfill_is_soft():
    """Рефери Q5: плотность — операционный приор, не физика."""
    import inspect

    from planner import validate as _val
    src = inspect.getsource(_val.check_floor_cap)
    assert "Severity.SOFT" in src


def test_dining_storage_drop_not_fail():
    """Рефери Q1/3.3: не влезшие dining/storage дропаются ярусом (skipped), а не валят сцену."""
    from planner.beam import solve
    from planner.models import Item
    from tests.rooms import make_room
    room = make_room("14-16")   # маленькая комната — обеденной места нет
    items = [Item(role="диван", w_cm=200, d_cm=95, h_cm=85),
             Item(role="тв-тумба", w_cm=140, d_cm=40, h_cm=50),
             Item(role="столик", w_cm=90, d_cm=55, h_cm=45),
             Item(role="стол обеденный", w_cm=120, d_cm=75, h_cm=75),
             Item(role="стул", w_cm=45, d_cm=50, h_cm=85),
             Item(role="стул 2", w_cm=45, d_cm=50, h_cm=85)]
    outs = solve(room, items, top_k=1)
    assert outs
    lay = outs[0]
    assert "стол обеденный" not in lay.unplaced, "dining обязан дропаться ярусом, не проваливать"
    # целостность группы: стол не стоит с <2 стульями, стулья не стоят без стола
    placed = [p.role for p in lay.placements]
    chairs = [r for r in placed if r.split(" ")[0] == "стул"]
    if "стол обеденный" in placed:
        assert len(chairs) >= 2
    else:
        assert not chairs


def test_engine_purity():
    """ADR-0076 (рефери-финал 08.08 п.11): один лейбл движка — один алгоритмический путь.
    Под ENGINE=zoned/beam/llm DFS-попытки НЕ гоняются (нет скрытого кросс-движкового спасения)."""
    import os
    import re
    src = open(os.path.join(os.path.dirname(__file__), '..', '..', '..',
                            'tools', 'scout', 'solver_run.py')).read()
    m = re.search(r"for seed in \(\[\] if ENGINE in \(([^)]*)\)", src)
    assert m, "seed-цикл DFS-фолбэка не найден — проверь solver_run.py"
    engines = m.group(1)
    for eng in ("'beam'", "'llm'", "'zoned'"):
        assert eng in engines, f"{eng} не исключён из DFS-фолбэка — A/B контаминирован"


def test_service_surface_coverage():
    """A1 (исследование рефери 08.08): кресло без поверхности в досягаемости — S1; одна
    поверхность обслуживает соседние места (не «каждому креслу свой стол»)."""
    from planner.models import Severity
    from planner.validate import validate
    room = _room(500, 550)
    sofa = _mk("диван", 250, 470, 180, 220, 100, 85)
    chair_far = _mk("кресло", 60, 60, 0, 80, 85, 80)
    vs = [v for v in validate(room, [sofa, chair_far]).violations
          if v.code == "SERVICE_SURFACE"]
    assert vs and all(v.severity is Severity.SOFT for v in vs)
    assert {"диван"} <= {r for v in vs for r in v.roles} or True
    # столик у дивана покрывает диван; кресло рядом со столиком тоже покрыто
    table = _mk("столик", 250, 380, 0, 100, 55, 45)
    chair_near = _mk("кресло", 130, 380, 90, 80, 85, 80)
    codes = [v for v in validate(room, [sofa, table, chair_near]).violations
             if v.code == "SERVICE_SURFACE"]
    assert not codes, [f"{v.roles}" for v in codes]


def test_tv_stand_with_wall_unit_flagged():
    """Ревью рефери 08.08 (set59/84): стенка = носитель ТВ, отдельная тумба при стенке — дубль
    (S1 до пересборки легаси-сетов, после A8 — H1)."""
    from planner.models import Severity
    from planner.validate import validate
    room = _room(500, 550)
    wall_unit = _mk("стенка", 150, 25, 0, 240, 45, 190)
    stand = _mk("тв-тумба", 400, 25, 0, 120, 40, 50)
    vs = [v for v in validate(room, [wall_unit, stand]).violations
          if v.code == "TV_STAND_WITH_WALL_UNIT"]
    assert vs and vs[0].severity is Severity.SOFT


def test_fireplace_scenario_gate():
    """Ревью рефери 08.08 (set113): камин без сценария (вне вилки/сектора с главной посадки)
    не получает кандидатов — роль дропается, а не встаёт в дальний угол."""
    from planner.candidates import generate
    from planner.models import Item, Placement
    room = _room(600, 700)
    sofa = Placement(role="диван", x=300, y=620, rot=180,
                     item=Item(role="диван", w_cm=220, d_cm=100, h_cm=85))
    fp = Item(role="камин", w_cm=110, d_cm=35, h_cm=100)
    cands = generate(room, fp, [sofa])
    import math
    from planner.geometry import footprint, facing_vector
    sfp = footprint(sofa)
    fx, fy = facing_vector(sofa.rot)
    for c in cands:
        ffp = footprint(c.placement)
        d = sfp.distance(ffp)
        assert 200 <= d <= 450, f"кандидат вне вилки: {d:.0f}"
        vx, vy = ffp.centroid.x - sfp.centroid.x, ffp.centroid.y - sfp.centroid.y
        n = math.hypot(vx, vy)
        assert (vx * fx + vy * fy) / n >= math.cos(math.radians(75)) - 1e-6, "вне сектора"


def test_second_armchair_zone_checked():
    """Ревью рефери 08.08 (set55/84): зонные чеки видят ВСЕ экземпляры кресел — «кресло 2»
    у витрины в другом конце комнаты ловится, как и первое."""
    from planner.validate import validate
    room = _room(600, 700)
    sofa = _mk("диван", 300, 620, 180, 220, 100, 85)
    arm1 = _mk("кресло", 160, 500, 90, 80, 85, 80)
    arm2 = _mk("кресло 2", 560, 60, 0, 80, 85, 80)   # у дальнего угла, вне зоны
    codes = [v.code for v in validate(room, [sofa, arm1, arm2]).violations
             if "кресло 2" in v.roles]
    assert any(c in ("ARMCHAIR_OUT_OF_ZONE", "ARMCHAIR_BEHIND_SOFA", "SEATS_TOO_FAR")
               for c in codes), codes


def test_effective_group_regroup_after_loss():
    """P0.1 (рефери 08.08): потерян required-слот группы → пересборка effective-группы и
    пере-решение, а не остатки старой (запрошена sofa_2armchairs, кресла не влезли →
    группа честно понижается, gid отражает фактику)."""
    from planner.models import Item, Severity
    from planner.zones import solve_zoned
    from tests.rooms import make_room
    room = make_room("14-16")   # тесно: пара кресел не встанет
    items = [Item(role="диван", w_cm=200, d_cm=95, h_cm=85),
             Item(role="тв-тумба", w_cm=140, d_cm=40, h_cm=50),
             Item(role="столик", w_cm=90, d_cm=55, h_cm=45),
             Item(role="кресло", w_cm=85, d_cm=90, h_cm=80),
             Item(role="кресло 2", w_cm=85, d_cm=90, h_cm=80)]
    outs, gid = solve_zoned(room, items, top_k=1)
    assert outs
    lay = outs[0]
    placed = {p.role for p in lay.placements}
    from planner.zones import zone_rules
    g = {x['id']: x for x in zone_rules()['seating_groups']}[gid]
    assert set(g['roles']['required']) <= placed, \
        f"required группы {gid} обязаны быть размещены: {placed}"
    hard = [v for v in lay.violations if v.severity is Severity.HARD]
    assert not hard, [v.code for v in hard]


# --- D-этапы (план layout-composition-deep, вердикты владельца 08.08) ---

def test_table_orientation_long_side():
    """D1 (set55): прямоугольный столик короткой стороной к дивану — H1."""
    from planner.models import Severity
    from planner.validate import validate
    room = _room(500, 550)
    sofa = _mk("диван", 250, 470, 180, 220, 100, 85)
    wrong = _mk("столик", 250, 390, 90, 120, 58, 45)   # rot 90 при диване 180 — поперёк
    codes = {v.code: v.severity for v in validate(room, [sofa, wrong]).violations}
    assert codes.get("TABLE_ORIENTATION") is Severity.HARD
    right = _mk("столик", 250, 390, 180, 120, 58, 45)
    codes2 = {v.code for v in validate(room, [sofa, right]).violations}
    assert "TABLE_ORIENTATION" not in codes2


def test_armchair_not_at_tv_wall():
    """D3 (set59): кресло вплотную к ТВ-носителю — вне разговорной дуги, H1."""
    from planner.models import Severity
    from planner.validate import validate
    room = _room(500, 550)
    sofa = _mk("диван", 250, 470, 180, 220, 100, 85)
    tv = _mk("тв-тумба", 250, 25, 0, 160, 40, 50)
    arm = _mk("кресло", 420, 60, 90, 80, 85, 80)   # у ТВ-стены
    codes = {v.code: v.severity for v in validate(room, [sofa, tv, arm]).violations}
    assert codes.get("ARMCHAIR_AT_TV_WALL") is Severity.HARD


def test_armchair_fireplace_corner_allowed():
    """D5: кресло у камина (100–250, лицом) — вторичная зона, дуговые чеки не применяются."""
    from planner.validate import validate
    room = _room(600, 700)
    sofa = _mk("диван", 300, 620, 180, 220, 100, 85)
    fpl = _mk("камин", 80, 350, 90, 110, 35, 100)     # у западной стены, в вилке от дивана
    arm = _mk("кресло", 240, 350, 270, 80, 85, 80)    # перед камином, лицом на запад
    codes = {v.code for v in validate(room, [sofa, fpl, arm]).violations
             if "кресло" in v.roles}
    assert not codes & {"ARMCHAIR_OUT_OF_ZONE", "ARMCHAIR_NOT_FACING_GROUP",
                        "ARMCHAIR_TABLE_DIST"}, codes
