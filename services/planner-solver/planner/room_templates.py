"""Общий формат комнатного шаблона `room-composition/1` (T-20261112-38/2; проект контракта —
`.memory_bank/_intake/codex/2026-11-12-bedroom-templates-answer.md` § «Универсальный формат»; расширение под полный состав
гостиной — T-20261112-63/1, план living-full-01 Т1 шаг 0, совет `_intake/codex/2026-11-12-living-passport-carriers-answer.md`).

Один модуль на все комнаты: паспорта лежат в `rules/room-templates/<room_type>.json`, здесь — загрузка, проверка схемы,
разворот уровня в список мест (`compile_level`) и выбор уровня. Геометрия групп (как ставится «сон» pair, посадка гостиной
и т. п.) — в движке комнаты (спальня — `planner/bedroom.py:_solve_groups`; гостиная — старый движок `rules/templates.json` +
`planner/template.py`, ссылка — `geometry_ref` из закрытого реестра GEOMETRY ниже); формат описывает ЧТО ставить, на что
опирается и в каком порядке уступать, а не координаты.

Сущности паспорта:
  groups      — группы комнаты: роли и варианты группы (общие для всех шаблонов комнаты). Вариант — либо счётчики ролей
                (`count`, спальня), либо явный состав: `slots[]` (самостоятельные места на полу/у стены) и `dependents[]`
                (места на носителе: подушки на сиденье дивана, ваза на столике, люстра над зоной, шторы у окна);
  order       — порядок групп по умолчанию (обязательные по назначению — раньше, это решает движок);
  templates[] — шаблон: id, purpose, priority, anchors, predicates, groups (какие группы и варианты в этом шаблоне, required),
                relations, levels (ЦЕЛЫЕ разрешённые составы по порядку предпочтения; `when` — условия комнаты, при которых
                уровень вообще рассматривается), next_step, label_without, invariants, selection_tags, geometry_ref.
                `modifier: true` — надстройка над любым шаблоном из `applies_to` (окно/эркер): её уровень добавляется к уровню
                основного шаблона, нет подходящего — остаётся основной уровень (`on_no_level: keep_base`);
  selection   — порядок шаблонов по фактам комнаты (кухня, пристройка, площадь, вытянутость): первое правило, чьи `when`
                выполнены, даёт порядок перебора (`select`).
Зависимое место: `carrier` — ровно одно из `slot_ref` («группа.место» носителя), `one_of` (носители по порядку: первый, что
есть в составе и подошёл геометрически), `zone` (группа — центр её зоны), `support` (опора комнаты: окно/эркер/стена/пол/
потолок); `anchor.kind` — общий набор ANCHOR_KINDS на все комнаты; `cardinality` — fixed с count или by_carrier_width с
rule_ref; fit/placement — rule_ref; `on_failure` — только reject_composition: не встало — отклоняется весь уровень, предмет
поштучно не выкидываем. `sellable: false` + `marker` — место без товара (виртуальный экран ТВ).
Числа — только через `rule_ref` на `occupancy.json` (distances_cm.*, вложенные ключи через точку); формулы строками не пишем.
Поля с `_` в начале — комментарии (`_why`, `_meta`); остальные неизвестные поля — ошибка схемы.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

SCHEMA = "room-composition/1"
DIR = Path(__file__).resolve().parent.parent / "rules" / "room-templates"
OCCUPANCY = Path(__file__).resolve().parent.parent / "rules" / "occupancy.json"
TEMPLATES = Path(__file__).resolve().parent.parent / "rules" / "templates.json"
ZONES = Path(__file__).resolve().parent.parent / "rules" / "zones.json"

# известные kind — неизвестный в паспорте = ошибка схемы (Codex: «запретить неизвестные kind»)
KINDS = {
    "anchors": {"wall_segment", "corner", "window", "door", "niche", "zone_edge", "axis", "free_zone",
                "stairs"},   # лестница в зале (прихожая H9, T-20261112-70); вход — door + qualifier entrance
    "predicates": {"side_access", "door_swing_clear", "route", "bed_sleep_width", "area_max", "aspect_min",
                   "radiator_clear", "tv_visibility", "kitchen_zone_reserved", "dining_operational_envelope",
                   "clear_width", "near_entrance", "entry_landing_clear", "turn_clear"},
    "relations": {"no_storage_in_sleep_side_zone", "no_storage_in_sleep_or_work_access", "storage_front_radiator",
                  "no_wardrobe_small_square", "reserve_wall_for",
                  "media_opposite_primary_seat", "no_route_between_sofa_and_coffee", "children_follow_actual_carrier",
                  "curtains_follow_opening", "sofa_back_faces_kitchen_or_dining", "dining_pendant_follows_table",
                  "living_chandelier_follows_seating_zone", "kitchen_route_not_cut_by_seating", "corner_sofa_in_corner",
                  "seating_along_long_wall",
                  # прихожая (T-20261112-70): хранение не на стене с дверями; банкетка рядом с обувницей; консоль (с зеркалом)
                  # напротив хранения в холле; зеркало не над вешалкой и не на проёме
                  "storage_on_solid_wall", "seat_beside_shoe", "console_opposite_storage", "mirror_not_over_hanger",
                  "single_primary_storage", "no_furniture_in_door_approach", "storage_in_l_branch"},
    "invariants": {"sku_dimensions_intact", "door_clear", "required_routes", "required_roles",
                   "required_groups_complete", "dependent_slots_have_carrier", "tv_visible", "no_silent_unplaced",
                   "kitchen_clear", "dining_operational", "storage_required"},
    "next_step": {"bed_sleep_width"},
}
# места на носителе — один набор на все комнаты (Codex carriers-answer § «Общий формат носителей»)
ANCHOR_KINDS = {"item_surface", "item_edge", "wall_above", "ceiling_over", "opening", "free_floor_region"}
SURFACES = {"seat", "top", "arm", "back", "arm_or_back", "front", "wall"}
SUPPORTS = {"window", "bay", "wall", "floor", "ceiling"}
CARDINALITY = {"fixed", "by_carrier_width"}
SYMMETRY = {"none", "balanced", "centered", "pair"}
# reject_composition — не встало место → отказ уровня целиком; leave_empty — место «условно обязательное» (картины при глухой
# стене, T-20261112-71): не встало → пусто с причиной в `Result.empty`, уровень остаётся
ON_FAILURE = {"reject_composition", "leave_empty"}
# условия комнаты: у уровня, места, модификатора и правила выбора. Числовые — через rule_ref, без чисел в паспорте
WHEN = {"room_has_window", "room_has_bay", "kitchen", "annex", "area_min", "area_below", "aspect_min", "dining_budget",
        "shape_l", "has_niche", "has_stairs", "door_dense", "squareish", "micro"}
# флаги формы комнаты (прихожая, T-20261112-70): факт комнаты true/false, без чисел — `when_ok` читает facts[kind]
WHEN_FLAGS = {"shape_l", "has_niche", "has_stairs", "door_dense", "squareish", "micro"}
WHEN_NUMERIC = {"area_min", "area_below", "aspect_min"}

# ЗАКРЫТЫЙ реестр geometry_ref: ключ → кто ставит крупную мебель в старом движке гостиной. Произвольный символ Python в
# паспорт не пишем — только ключ отсюда; новая схема → строка здесь (+ тест сверяет, что схема есть в templates.json).
# scheme None — вся зона: движок перебирает все её схемы сам (столовая, напольный декор).
GEOMETRY = {
    "seating.sofa_solo_group": {"zone": "seating", "scheme": "sofa_solo_group", "what": "диван + столик + ковёр без спутников"},
    "seating.sofa_lamp_group": {"zone": "seating", "scheme": "sofa_lamp_group", "what": "диван + торшер у подлокотника"},
    "seating.sofa_single_flank": {"zone": "seating", "scheme": "sofa_single_flank", "what": "кресло у торца дивана, столик по оси"},
    "seating.u": {"zone": "seating", "scheme": "u", "what": "П-композиция: диван + два кресла"},
    "seating.sectional_solo": {"zone": "seating", "scheme": "sectional_solo", "what": "угловой диван сам образует две стороны"},
    "seating.floating_sofa_opposite_media": {"zone": "seating", "scheme": "floating_sofa_opposite_media",
                                             "what": "диван-разделитель спинкой к кухне/столовой, напротив ТВ"},
    "seating.two_sofa_l_joint": {"zone": "seating", "scheme": "two_sofa_l_joint", "what": "два дивана Г + столик"},
    "media.media_centered": {"zone": "media", "scheme": "media_centered", "what": "ТВ-тумба по оси взгляда с дивана"},
    "dining": {"zone": "dining", "scheme": None, "what": "столовая: остров, у стены, круглый, откидной, уголок — перебор схем"},
    "dining.dining_round_compact": {"zone": "dining", "scheme": "dining_round_compact", "what": "компактный стол на 2"},
    "storage.storage_perimeter": {"zone": "storage", "scheme": "storage_perimeter", "what": "комод у свободной стены"},
    "decor": {"zone": "decor", "scheme": None, "what": "напольное кашпо: угол, у окна, эркер — перебор схем"},
    "decor.bay_plant": {"zone": "decor", "scheme": "bay_plant", "what": "кашпо в эркере"},
    "reading.bay_anchor": {"zone": "reading", "scheme": "bay_anchor", "what": "кресло в эркере лицом в комнату"},
    "reading.window_anchor": {"zone": "reading", "scheme": "window_anchor", "what": "кресло у окна лицом в комнату"},
    "reading.corner_vignette": {"zone": "reading", "scheme": "corner_vignette", "what": "кресло/столик + лампа в углу"},
}

_C = {"_why", "_meta", "_note", "_source"}
FIELDS = {
    "doc": {"schema_version", "unit", "room_type", "groups", "order", "templates", "selection"},
    "group": {"roles", "variants", "label"},
    "variant": {"count", "slots", "dependents", "geometry_ref", "label"},
    "slot": {"id", "role", "count", "sellable", "marker", "geometry_ref", "near", "rule_ref", "shape", "label", "required"},
    "dependent": {"id", "role", "carrier", "anchor", "cardinality", "fit", "placement", "symmetry", "when", "on_failure",
                  "sellable", "marker", "label"},
    "template": {"id", "purpose", "priority", "anchors", "predicates", "groups", "relations", "levels", "next_step",
                 "label_without", "invariants", "selection_tags", "geometry_ref", "modifier", "applies_to", "when",
                 "on_no_level", "storage_count_first", "sleep_before_mode", "label"},
    "tgroup": {"id", "variants", "required", "geometry_ref"},
    "level": {"id", "use", "when", "label"},
    "anchor": {"type", "qualifiers", "relation", "of"},
    "rule": {"kind", "rule_ref", "sides", "from", "to", "purpose", "of", "value", "before_level"},
    "carrier": {"slot_ref", "one_of", "zone", "support"},
    "danchor": {"kind", "surface", "of"},
    "cardinality": {"kind", "count", "rule_ref"},
    "fit": {"kind", "rule_ref"},
    "when": {"kind", "rule_ref", "seats"},
    "selection": {"when", "order", "label"},
    "label_without": {"group", "label"},
}


@lru_cache(maxsize=None)
def load(room_type: str) -> dict:
    """Паспорт комнаты; нет файла — {} (комната ещё не переведена на формат)."""
    p = DIR / f"{room_type}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _distances() -> dict:
    return json.loads(OCCUPANCY.read_text(encoding="utf-8")).get("distances_cm", {})


_MISSING = object()


def rule_value(ref: str, dist: dict | None = None):
    """Значение по rule_ref `distances_cm.a.b.c` (вложенные ключи — через точку); нет — _MISSING."""
    if not isinstance(ref, str) or not ref.startswith("distances_cm."):
        return _MISSING
    node = _distances() if dist is None else dist
    for k in ref.split(".")[1:]:
        if not isinstance(node, dict) or k not in node:
            return _MISSING
        node = node[k]
    return node


def norm_value(ref: str):
    """Значение нормы occupancy.json по пути от корня (`heights_cm.sofa_seat`) — для высот поверхностей носителя
    в решателе зависимых (`planner/dependents.py`); нет — _MISSING."""
    if not isinstance(ref, str) or not ref:
        return _MISSING
    node = json.loads(OCCUPANCY.read_text(encoding="utf-8"))
    for k in ref.split("."):
        if not isinstance(node, dict) or k not in node:
            return _MISSING
        node = node[k]
    return node


def geometry_target(key: str) -> dict | None:
    """Что в старом движке стоит за ключом реестра: {zone, scheme, what}; ключа нет — None."""
    return GEOMETRY.get(key)


def _unknown(where: str, obj, kind: str, err: list) -> None:
    if not isinstance(obj, dict):
        err.append(f"{where}: ожидался объект, а не {type(obj).__name__}")
        return
    extra = sorted(k for k in obj if not k.startswith("_") and k not in FIELDS[kind])
    if extra:
        err.append(f"{where}: неизвестные поля {extra}")


def _slot_index(doc: dict) -> dict[str, tuple[str, str, dict, str]]:
    """Все места паспорта: «группа.место» → (группа, вариант, описание, slot|dependent) — для ссылок «в никуда»."""
    out = {}
    for g, spec in (doc.get("groups") or {}).items():
        for v, var in (spec.get("variants") or {}).items():
            if not isinstance(var, dict):
                continue
            for kind, key in (("slot", "slots"), ("dependent", "dependents")):
                for s in var.get(key) or []:
                    if isinstance(s, dict) and s.get("id"):
                        out.setdefault(f"{g}.{s['id']}", (g, v, s, kind))
    return out


def _check_when(where: str, conds, dist: dict, err: list) -> None:
    if conds is None:
        return
    if not isinstance(conds, list):
        err.append(f"{where}: when — список условий")
        return
    for c in conds:
        _unknown(f"{where}.when", c, "when", err)
        if not isinstance(c, dict):
            continue
        k = c.get("kind")
        if k not in WHEN:
            err.append(f"{where}: when kind {k!r} неизвестен")
        elif k in WHEN_NUMERIC and rule_value(c.get("rule_ref"), dist) is _MISSING:
            err.append(f"{where}: when {k} — rule_ref {c.get('rule_ref')} нет в occupancy.json")
        elif k == "dining_budget" and not isinstance(c.get("seats"), int):
            err.append(f"{where}: when dining_budget без seats")


def _check_ref(where: str, x: dict, dist: dict, err: list) -> None:
    r = x.get("rule_ref") if isinstance(x, dict) else None
    if r and rule_value(r, dist) is _MISSING:
        err.append(f"{where}: rule_ref {r} нет в occupancy.json")


def _check_geometry(where: str, x: dict, err: list) -> None:
    g = x.get("geometry_ref") if isinstance(x, dict) else None
    if g is not None and g not in GEOMETRY:
        err.append(f"{where}: geometry_ref {g!r} вне реестра GEOMETRY")


def _check_variant(g: str, v: str, var: dict, groups: dict, index: dict, dist: dict, err: list) -> None:
    w = f"groups.{g}.{v}"
    _unknown(w, var, "variant", err)
    if not isinstance(var, dict):
        return
    _check_geometry(w, var, err)
    roles = set(groups[g].get("roles") or ())
    ids = set()
    for kind, key in (("slot", "slots"), ("dependent", "dependents")):
        for s in var.get(key) or []:
            sw = f"{w}.{(s or {}).get('id', '?') if isinstance(s, dict) else '?'}"
            _unknown(sw, s, kind, err)
            if not isinstance(s, dict):
                continue
            if not s.get("id") or not s.get("role"):
                err.append(f"{sw}: нет id или role")
            if s.get("id") in ids:
                err.append(f"{sw}: повтор id места в варианте")
            ids.add(s.get("id"))
            if s.get("role") and s.get("sellable", True) and s["role"] not in roles:
                err.append(f"{sw}: роль {s['role']!r} не в roles группы {g}")
            if s.get("sellable") is False and not s.get("marker"):
                err.append(f"{sw}: непродаваемое место без marker")
            _check_ref(sw, s, dist, err)
            _check_geometry(sw, s, err)
            if kind == "slot":
                if "count" in s and not (isinstance(s["count"], int) and s["count"] >= 1):
                    err.append(f"{sw}: count — целое ≥ 1")
                if s.get("near") and s["near"] not in index:
                    err.append(f"{sw}: near {s['near']} — ссылка в никуда")
                if isinstance(s.get("required"), list):
                    _check_when(f"{sw}.required", s["required"], dist, err)
                elif "required" in s and not isinstance(s["required"], bool):
                    err.append(f"{sw}: required — true/false или список условий when")
                continue
            _check_dependent(sw, s, groups, index, dist, err)


def _check_dependent(w: str, s: dict, groups: dict, index: dict, dist: dict, err: list) -> None:
    car = s.get("carrier")
    _unknown(f"{w}.carrier", car, "carrier", err)
    if isinstance(car, dict):
        given = [k for k in FIELDS["carrier"] if k in car]
        if len(given) != 1:
            err.append(f"{w}: carrier — ровно одно из {sorted(FIELDS['carrier'])}, а не {sorted(given)}")
        refs = [car["slot_ref"]] if "slot_ref" in car else list(car.get("one_of") or [])
        if "one_of" in car and not refs:
            err.append(f"{w}: carrier.one_of пуст")
        for r in refs:
            if r not in index:
                err.append(f"{w}: carrier {r} — ссылка в никуда")
        if "zone" in car and car["zone"] not in groups:
            err.append(f"{w}: carrier.zone {car['zone']} — нет такой группы")
        if "support" in car and car["support"] not in SUPPORTS:
            err.append(f"{w}: carrier.support {car['support']!r} неизвестен")
    an = s.get("anchor")
    _unknown(f"{w}.anchor", an, "danchor", err)
    if isinstance(an, dict):
        if an.get("kind") not in ANCHOR_KINDS:
            err.append(f"{w}: anchor kind {an.get('kind')!r} неизвестен")
        if an.get("surface") is not None and an["surface"] not in SURFACES:
            err.append(f"{w}: anchor surface {an['surface']!r} неизвестна")
    cd = s.get("cardinality")
    _unknown(f"{w}.cardinality", cd, "cardinality", err)
    if isinstance(cd, dict):
        k = cd.get("kind")
        if k not in CARDINALITY:
            err.append(f"{w}: cardinality kind {k!r} неизвестен")
        elif k == "fixed" and not (isinstance(cd.get("count"), int) and cd["count"] >= 1):
            err.append(f"{w}: cardinality fixed без count ≥ 1")
        elif k == "by_carrier_width" and not cd.get("rule_ref"):
            err.append(f"{w}: cardinality by_carrier_width без rule_ref")
        _check_ref(f"{w}.cardinality", cd, dist, err)
    for key in ("fit", "placement"):
        if key in s:
            _unknown(f"{w}.{key}", s[key], "fit", err)
            _check_ref(f"{w}.{key}", s[key], dist, err)
    if s.get("symmetry") is not None and s["symmetry"] not in SYMMETRY:
        err.append(f"{w}: symmetry {s['symmetry']!r} неизвестна")
    if s.get("on_failure") not in ON_FAILURE:
        err.append(f"{w}: on_failure {s.get('on_failure')!r} — допустимо {sorted(ON_FAILURE)}")
    _check_when(w, s.get("when"), dist, err)


def _variant_places(doc: dict, g: str, v: str) -> list[dict]:
    """Места варианта группы. Явный состав (slots/dependents) — как есть; иначе (спальня) — роли группы × count."""
    spec = (doc.get("groups") or {}).get(g) or {}
    var = (spec.get("variants") or {}).get(v)
    if not isinstance(var, dict):
        return []
    gref = var.get("geometry_ref")
    out = []
    if "slots" in var or "dependents" in var:
        for s in var.get("slots") or []:
            out.append({"id": f"{g}.{s['id']}", "group": g, "variant": v, "kind": "slot", "role": s["role"],
                        "count": s.get("count", 1), "sellable": s.get("sellable", True), "marker": s.get("marker"),
                        "near": s.get("near"), "geometry_ref": s.get("geometry_ref") or gref,
                        "required": s.get("required", True)})
        for s in var.get("dependents") or []:
            out.append({"id": f"{g}.{s['id']}", "group": g, "variant": v, "kind": "dependent", "role": s["role"],
                        "carrier": s.get("carrier"), "anchor": s.get("anchor"), "cardinality": s.get("cardinality"),
                        "sellable": s.get("sellable", True), "marker": s.get("marker"), "when": s.get("when"),
                        "on_failure": s.get("on_failure"),
                        # как ставить на носителе — решателю зависимых (`planner/dependents.py`, T-20261112-67)
                        "fit": s.get("fit"), "placement": s.get("placement"), "symmetry": s.get("symmetry", "none")})
        return out
    cnt = var.get("count") or {}
    for r in spec.get("roles") or []:
        n = cnt.get(r, 1)
        if n:
            out.append({"id": f"{g}.{r}", "group": g, "variant": v, "kind": "slot", "role": r, "count": n,
                        "sellable": True, "marker": None, "near": None, "geometry_ref": gref})
    return out


def _carrier_refs(p: dict, by_group: dict) -> list[str]:
    """Рёбра зависимостей места: носитель (место, любое из one_of, все места зоны) или `near` самостоятельного места."""
    if p["kind"] == "slot":
        return [p["near"]] if p.get("near") else []
    car = p.get("carrier") or {}
    if "slot_ref" in car:
        return [car["slot_ref"]]
    if "one_of" in car:
        return list(car["one_of"])
    if "zone" in car:
        return [x for x in by_group.get(car["zone"], []) if x != p["id"]]
    return []


def _find_cycle(places: list[dict]) -> list[str] | None:
    by_group: dict[str, list[str]] = {}
    for p in places:
        by_group.setdefault(p["group"], []).append(p["id"])
    edges = {p["id"]: _carrier_refs(p, by_group) for p in places}
    state: dict[str, int] = {}
    stack: list[str] = []

    def dfs(u):
        state[u] = 1
        stack.append(u)
        for w in edges.get(u, []):
            if w not in edges:
                continue
            if state.get(w) == 1:
                return stack[stack.index(w):] + [w]
            if not state.get(w):
                got = dfs(w)
                if got:
                    return got
        stack.pop()
        state[u] = 2
        return None

    for p in places:
        if not state.get(p["id"]):
            got = dfs(p["id"])
            if got:
                return got
    return None


def compile_level(doc: dict, tpl: dict, level_id: str, base: tuple[dict, str] | None = None) -> tuple[list[dict], list[str]]:
    """Уровень → конкретный список мест (самостоятельные и на носителях) + ошибки разворота.
    base=(шаблон, уровень) — для модификатора: его `use` добавляется к уровню основного шаблона (одноимённая группа —
    заменяется вариантом модификатора). Ошибки: уровень пуст, вариант без мест, носитель не в составе уровня, цикл."""
    err: list[str] = []
    lv = next((x for x in tpl.get("levels", []) if x.get("id") == level_id), None)
    tid = tpl.get("id", "?")
    if lv is None:
        return [], [f"{tid}: нет уровня {level_id}"]
    use = dict(lv.get("use") or {})
    where = f"{tid}.{level_id}"
    if base is not None:
        btpl, blv = base
        bl = next((x for x in btpl.get("levels", []) if x.get("id") == blv), None)
        if bl is None:
            return [], [f"{where}: у {btpl.get('id')} нет уровня {blv}"]
        use = {**(bl.get("use") or {}), **use}
        where = f"{btpl.get('id')}.{blv}+{where}"
    places: list[dict] = []
    for g, v in use.items():
        got = _variant_places(doc, g, v)
        if not got:
            err.append(f"{where}: вариант {g}.{v} не разворачивается в места")
        places += got
    if not places:
        err.append(f"{where}: уровень пуст — ни одного места")
    ids = {p["id"] for p in places}
    present_groups = {p["group"] for p in places}
    for p in places:
        if p["kind"] == "slot":
            if p.get("near") and p["near"] not in ids:
                err.append(f"{where}: {p['id']} near {p['near']} — места нет в составе уровня")
            continue
        car = p.get("carrier") or {}
        if "slot_ref" in car and car["slot_ref"] not in ids:
            err.append(f"{where}: {p['id']} — носителя {car['slot_ref']} нет в составе уровня")
        if "one_of" in car and not any(r in ids for r in car["one_of"]):
            err.append(f"{where}: {p['id']} — ни одного носителя из {car['one_of']} в составе уровня")
        if "zone" in car and car["zone"] not in present_groups:
            err.append(f"{where}: {p['id']} — зоны {car['zone']} нет в составе уровня")
    cyc = _find_cycle(places)
    if cyc:
        err.append(f"{where}: цикл зависимостей {' → '.join(cyc)}")
    return places, err


def check(doc: dict) -> list[str]:
    """Ошибки схемы паспорта (пусто — годен): версия, неизвестные поля и kind, ссылки на несуществующие группы/варианты/места,
    уровни без обязательной группы, rule_ref мимо occupancy.json, geometry_ref вне реестра, повтор id, зависимые места
    (носитель, якорь, количество, on_failure), циклы, и каждый уровень разворачивается в набор мест (`compile_level`)."""
    err = []
    if doc.get("schema_version") != SCHEMA:
        err.append(f"schema_version {doc.get('schema_version')!r} ≠ {SCHEMA}")
    _unknown("паспорт", doc, "doc", err)
    groups = doc.get("groups") or {}
    dist = _distances()
    for g in doc.get("order", []):
        if g not in groups:
            err.append(f"order: нет группы {g}")
    index = _slot_index(doc)
    for g, spec in groups.items():
        _unknown(f"groups.{g}", spec, "group", err)
        for v, var in ((spec or {}).get("variants") or {}).items():
            _check_variant(g, v, var, groups, index, dist, err)
    seen = set()
    by_id = {t.get("id"): t for t in doc.get("templates", [])}

    def ref(where, x):
        _check_ref(where, x, dist, err)

    for t in doc.get("templates", []):
        tid = t.get("id", "?")
        _unknown(tid, t, "template", err)
        if tid in seen:
            err.append(f"{tid}: повтор id")
        seen.add(tid)
        if not t.get("purpose"):
            err.append(f"{tid}: нет purpose")
        _check_geometry(tid, t, err)
        _check_when(tid, t.get("when"), dist, err)
        tg = {}
        for g in t.get("groups", []):
            _unknown(f"{tid}.groups", g, "tgroup", err)
            if g["id"] not in groups:
                err.append(f"{tid}: группа {g['id']} не описана в groups")
                continue
            _check_geometry(f"{tid}.{g['id']}", g, err)
            for v in g.get("variants", []):
                if v not in (groups[g["id"]].get("variants") or {}):
                    err.append(f"{tid}: вариант {g['id']}.{v} не описан")
            tg[g["id"]] = g
        for sec in ("predicates", "relations"):
            for x in t.get(sec, []):
                _unknown(f"{tid}.{sec}", x, "rule", err)
                if x.get("kind") not in KINDS[sec]:
                    err.append(f"{tid}: {sec} kind {x.get('kind')!r} неизвестен")
                ref(f"{tid}.{sec}", x)
        for a, x in (t.get("anchors") or {}).items():
            _unknown(f"{tid}.anchors.{a}", x, "anchor", err)
            if x.get("type") not in KINDS["anchors"]:
                err.append(f"{tid}: anchor {a} type {x.get('type')!r} неизвестен")
        for i in t.get("invariants", []):
            if i not in KINDS["invariants"]:
                err.append(f"{tid}: invariant {i!r} неизвестен")
        req = {g for g, x in tg.items() if x.get("required")}
        ids = [lv.get("id") for lv in t.get("levels", [])]
        if not ids:
            err.append(f"{tid}: нет levels")
        if len(set(ids)) != len(ids):
            err.append(f"{tid}: повтор id уровня")
        mod = bool(t.get("modifier"))
        bases = []
        if mod:
            if t.get("on_no_level", "keep_base") != "keep_base":
                err.append(f"{tid}: on_no_level — только keep_base")
            for b in t.get("applies_to") or []:
                if b not in by_id or by_id[b].get("modifier"):
                    err.append(f"{tid}: applies_to {b} — нет такого основного шаблона")
                else:
                    bases.append(by_id[b])
            if not t.get("applies_to"):
                err.append(f"{tid}: модификатор без applies_to")
        elif t.get("applies_to") or "on_no_level" in t:
            err.append(f"{tid}: applies_to/on_no_level — только у modifier")
        for lv in t.get("levels", []):
            _unknown(f"{tid}.{lv.get('id')}", lv, "level", err)
            _check_when(f"{tid}.{lv.get('id')}", lv.get("when"), dist, err)
            use = lv.get("use") or {}
            for g, v in use.items():
                if g not in tg:
                    err.append(f"{tid}.{lv['id']}: группа {g} не в шаблоне")
                elif v not in tg[g].get("variants", []):
                    err.append(f"{tid}.{lv['id']}: вариант {g}.{v} не в шаблоне")
            miss = req - set(use)
            if miss:
                err.append(f"{tid}.{lv['id']}: уровень без обязательной группы {sorted(miss)}")
            if mod:
                for b in bases:
                    for blv in b.get("levels", []):
                        err += compile_level(doc, t, lv["id"], base=(b, blv["id"]))[1]
            else:
                err += compile_level(doc, t, lv["id"])[1]
        ns = t.get("next_step")
        if ns:
            if ns.get("kind") not in KINDS["next_step"]:
                err.append(f"{tid}: next_step kind {ns.get('kind')!r} неизвестен")
            if ns.get("before_level") and ns["before_level"] not in ids:
                err.append(f"{tid}: next_step.before_level {ns['before_level']} нет в levels")
        lw = t.get("label_without")
        if lw:
            _unknown(f"{tid}.label_without", lw, "label_without", err)
            if lw.get("group") not in tg:
                err.append(f"{tid}: label_without.group {lw.get('group')} не в шаблоне")
    for i, r in enumerate(doc.get("selection") or []):
        _unknown(f"selection[{i}]", r, "selection", err)
        _check_when(f"selection[{i}]", r.get("when") or [], dist, err)
        for tid in r.get("order") or []:
            if tid not in by_id or by_id[tid].get("modifier"):
                err.append(f"selection[{i}]: шаблона {tid} нет (или это модификатор)")
        if not r.get("order"):
            err.append(f"selection[{i}]: пустой order")
    return err


def purpose_key(purpose: str | None, child_age: str | None = None) -> str:
    return f"{purpose}:{child_age}" if purpose == "child" and child_age else (purpose or "")


def template_for(room_type: str, purpose: str | None, child_age: str | None = None) -> dict | None:
    """Шаблон назначения (меньший priority — раньше); детская — сперва `child:<возраст>`, потом `child`. Модификаторы — нет."""
    doc = load(room_type)
    keys = [purpose_key(purpose, child_age), purpose or ""]
    for k in keys:
        got = sorted((t for t in doc.get("templates", []) if k in t.get("purpose", []) and not t.get("modifier")),
                     key=lambda t: t.get("priority", 100))
        if got:
            return got[0]
    return None


def template_by_id(room_type: str, tid: str) -> dict | None:
    return next((t for t in load(room_type).get("templates", []) if t.get("id") == tid), None)


def group_of(room_type: str, role_base: str) -> str | None:
    """Группа роли (роль — базовая, без «2» и псевдонимов) по паспорту комнаты; вне групп — None."""
    for g, spec in (load(room_type).get("groups") or {}).items():
        if role_base in spec.get("roles", ()):
            return g
    return None


def variants(tpl: dict, group: str) -> list[str]:
    return next((list(g.get("variants", [])) for g in tpl.get("groups", []) if g["id"] == group), [])


def dining_budget(area_m2: float) -> int:
    """Мест за столом в комплекте по общей площади комнаты — zones.json `template_slot_envelopes.slots.стол обеденный.
    seats_by_room_m2` (<22 → 2, <40 → 4, ≥40 → 6; ADR-0270), тот же разбор, что `tools/scout/slot_rules.py:seats_for_room`."""
    env = json.loads(ZONES.read_text(encoding="utf-8")).get("template_slot_envelopes", {})
    sb = ((env.get("slots") or {}).get("стол обеденный") or {}).get("seats_by_room_m2") or {"<22": "2", "<40": "4", ">=40": "6"}
    for lim, k in sorted((float(k[1:]), k) for k in sb if k.startswith("<") and not k.startswith("<=")):
        if area_m2 < lim:
            return int(sb[k])
    ge = [k for k in sb if k.startswith(">=")]
    return int(sb[ge[0]]) if ge else 6


def count_by_width(rule: dict, width_cm: float) -> int:
    """Количество по ширине носителя: rule {below: [пороги], count: [n0, n1, …]} — n_i, если ширина < below[i], иначе
    последний (подушки — `distances_cm.dependents.sofa_pillow_count.by_outer_width_cm`)."""
    for lim, n in zip(rule["below"], rule["count"]):
        if width_cm < lim:
            return int(n)
    return int(rule["count"][-1])


def when_ok(conds: list | None, facts: dict) -> bool:
    """Условия комнаты выполнены? facts: area_m2, aspect, kitchen, annex, has_window, has_bay, dining_budget
    (нет — считается по area_m2), прихожая — флаги формы `WHEN_FLAGS` (shape_l, has_niche, has_stairs, door_dense,
    squareish, micro).
    Неизвестный факт — условие не выполнено."""
    for c in conds or []:
        k = c.get("kind")
        if k in WHEN_NUMERIC:
            val = rule_value(c.get("rule_ref"))
            if val is _MISSING:
                return False
            x = facts.get("aspect" if k == "aspect_min" else "area_m2")
            if x is None or (k == "area_below" and not x < val) or (k != "area_below" and not x >= val):
                return False
        elif k == "dining_budget":
            b = facts.get("dining_budget")
            if b is None and facts.get("area_m2") is not None:
                b = dining_budget(facts["area_m2"])
            if b != c.get("seats"):
                return False
        elif k in ("room_has_window", "room_has_bay"):
            if not facts.get("has_window" if k == "room_has_window" else "has_bay"):
                return False
        elif k in ("kitchen", "annex") or k in WHEN_FLAGS:
            if not facts.get(k):
                return False
        else:
            return False
    return True


def select(doc: dict, facts: dict) -> list[str]:
    """Порядок перебора шаблонов для комнаты: первое правило `selection`, чьи условия выполнены."""
    for r in doc.get("selection") or []:
        if when_ok(r.get("when"), facts):
            return list(r.get("order") or [])
    return []


def levels_for(tpl: dict, facts: dict) -> list[str]:
    """Уровни шаблона, разрешённые для этой комнаты (по `when`), в порядке предпочтения."""
    return [lv["id"] for lv in tpl.get("levels", []) if when_ok(lv.get("when"), facts)]


# ───────────── выбор уровня по набору (T-20261112-71; ADR-0391 «шаблон собирается из предметов набора») ─────────────

def slot_required(p: dict, facts: dict) -> bool:
    """Обязательно ли место-слот в этой комнате. Поле паспорта `required`: true (по умолчанию), false («по желанию»: нет в
    наборе — место пусто) или список условий `when` (обязательно, когда все выполнены, — «от 16 м²», «в кухне-гостиной»)."""
    r = p.get("required", True)
    return when_ok(r, facts) if isinstance(r, list) else bool(r)


def coverage(places: list[dict], found: dict, facts: dict) -> tuple[list[str], list[str]]:
    """Что набор закрыл в уровне: found — {id места-слота: сколько предметов нашлось}. → (недостающее обязательное «id×n»,
    пустое по желанию «id×n»). Первое непусто — уровень не годится ЦЕЛЫМ составом; второе — места уровня остаются пустыми."""
    miss, empty = [], []
    for p in places:
        if p["kind"] != "slot":
            continue
        short = p.get("count", 1) - min(found.get(p["id"], 0), p.get("count", 1))
        if short > 0:
            (miss if slot_required(p, facts) else empty).append(f"{p['id']}×{short}")
    return miss, empty


def drop_places(places: list[dict], gone: set) -> list[dict]:
    """Уровень без пустых мест-слотов `gone`: убираются они и зависимые, чей носитель только среди них (у `one_of` остаются
    кандидаты, которые в уровне есть; у зоны — пока в ней есть хоть одно место)."""
    live = {p["id"] for p in places if p["kind"] == "slot"} - set(gone)
    out = []
    for p in places:
        if p["id"] in gone:
            continue
        car = p.get("carrier") or {}
        if "slot_ref" in car and car["slot_ref"] not in live:
            continue
        if "one_of" in car:
            keep = [r for r in car["one_of"] if r in live]
            if not keep:
                continue
            p = {**p, "carrier": {**car, "one_of": keep}}
        if "zone" in car and not any(x.split(".")[0] == car["zone"] for x in live):
            continue
        out.append(p)
    return out


def levels_by_set(doc: dict, facts: dict, found_of) -> tuple[list[dict], list[dict]]:
    """ВЫБОР УРОВНЯ ПО НАБОРУ — общее правило для любой комнаты с паспортом. Шаблоны — `select`, уровни — `levels_for`.
    found_of(places) → {id места-слота: сколько предметов набора на него нашлось} (сопоставление предметов — у вызывающего).
    Уровень годен, если набор закрыл все его ОБЯЗАТЕЛЬНЫЕ места (`slot_required`); место «по желанию», которого нет, — пусто,
    уровень не теряется. Нет обязательного — уровень не годен целиком (следующий). Внутри шаблона годные — по числу пустых мест
    (меньше — раньше: уровень, что лучше использует набор), при равенстве — порядок паспорта; шаблоны — порядок `select`.
    → (годные [{tpl, level, places (без пустых), empty}], негодные [{tpl, level, missing | error}]). Годных нет — честный отказ
    с причинами из второго списка."""
    ok, bad = [], []
    for tid in select(doc, facts):
        tpl = next((t for t in doc.get("templates", []) if t.get("id") == tid), None)
        if tpl is None or tpl.get("modifier"):
            continue
        good = []
        for i, lid in enumerate(levels_for(tpl, facts)):
            places, err = compile_level(doc, tpl, lid)
            if err:
                bad.append({"tpl": tid, "level": lid, "error": "; ".join(err)})
                continue
            found = found_of(places)
            miss, empty = coverage(places, found, facts)
            if miss:
                bad.append({"tpl": tid, "level": lid, "missing": miss})
                continue
            gone = {p["id"] for p in places if p["kind"] == "slot" and not found.get(p["id"])}   # частично закрытое — остаётся
            kept = drop_places(places, gone)
            ids = {p["id"] for p in kept}
            empty += [f"{p['id']}×1" for p in places if p["kind"] == "dependent" and p["id"] not in ids]  # ушли с носителем
            n_empty = sum(int(e.rsplit("×", 1)[1]) for e in empty)
            good.append((n_empty, i, {"tpl": tid, "level": lid, "places": kept, "empty": empty}))
        ok += [x[2] for x in sorted(good, key=lambda x: x[:2])]
    return ok, bad


def level_of(tpl: dict, found: dict, facts: dict | None = None) -> tuple[int, str | None]:
    """Уровень состава: первый по порядку, чей `use` целиком есть в раскладке (лишние группы не мешают).
    found — {группа: вариант} фактической раскладки → (индекс, id); не подошёл ни один — (len(levels), None).
    facts — факты комнаты: уровни, чьи `when` не выполнены, пропускаются (без facts — как раньше, все уровни)."""
    for i, lv in enumerate(tpl.get("levels", [])):
        if facts is not None and not when_ok(lv.get("when"), facts):
            continue
        if all(found.get(g) == v for g, v in (lv.get("use") or {}).items()):
            return i, lv["id"]
    return len(tpl.get("levels", [])), None


def best_possible(tpl: dict, group: str, variant: str | None) -> int:
    """Лучший уровень, достижимый при данном варианте группы (уровни без этой группы — тоже) — для ранней остановки."""
    for i, lv in enumerate(tpl.get("levels", [])):
        use = lv.get("use") or {}
        if group not in use or use[group] == variant:
            return i
    return len(tpl.get("levels", []))


def level_index(tpl: dict, level_id: str | None) -> int | None:
    return next((i for i, lv in enumerate(tpl.get("levels", [])) if lv["id"] == level_id), None)
