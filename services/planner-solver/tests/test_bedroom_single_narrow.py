"""Узкая односпальная UK single 90×190 (план bedroom-uk-single-01, владелец TG 297 09.11: «не поправить, а добавить»).

1) Прежние назначения, шаблоны, правила, слоты состава и теги каталога — ровно те, что были до 09.11: текущий файл
   МИНУС перечисленные добавки даёт тот же JSON, что зафиксирован эталоном (sha256), и добавки стоят последними ключами.
2) Новое назначение single_narrow раскладывает кровать 90×190 (рама ≤ ~105) без жёстких нарушений в спальнях
   из объявления (`tools/scout/uk-bedrooms.json`): Bedroom Three 2,44×3,33 и Bedroom Two 3,96×3,60.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

from planner.bedroom import solve_bedroom
from planner.bedroom_checks import is_bed, side_on_wall
from planner.models import Item, Opening, Radiator, Room, Severity
from planner.validate import validate

ROOT = Path(__file__).resolve().parents[3]
UK = ROOT / "tools" / "scout" / "uk-bedrooms.json"

# Что такое «пометка» — то же правило, что в метке набора правил (tools/scout/rules_label.py:_is_comment): ключ на «_» с ТЕКСТОМ (`_about`, `_why`, `_note`) на любой
# глубине; «_»-ключ с числом/флагом/списком — ДАННЫЕ и в хеш входит. Единственное добавление здесь — объект-пометка `_meta` (в этих файлах он был до 27.11 и до сих пор
# стоит в bedroom.json): пометкой он считается, только если внутри один текст (Fable 27.11: источник/описание/примечание о ролях, данных там не было); положили в него
# число или список — это данные, хеш краснеет.
sys.path.insert(0, str(ROOT / "tools" / "scout"))
import rules_label  # noqa: E402  (стандартная библиотека; тот же файл, что считает метку набора правил)

# Файл bedroom.json метка набора правил НЕ видит (в срез Salad он не едет — T-175/12-дыра, решение Fable 27.11), поэтому ключ-данные внутри объекта-пометки `_meta`
# сторожит ЭТОТ тест: NOTES = {объект-пометка: [ключи-данные]} — `_meta.engine` (движок солвера спальни, читает planner/bedroom_checks.py:74). Список текстовых «_»-ключей с
# данными (text_data) — общий с меткой, `tools/scout/rules/rules-label.json`.
DATA_NAMES = rules_label.text_data_names(rules_label.load_cfg())
NOTES = {"_meta": ["engine"]}


def _is_note(k, v) -> bool:
    return rules_label._is_comment(k, v, DATA_NAMES) or rules_label.is_note_object(k, v, NOTES)


def _no_notes(o):
    """Убрать пометки на любой глубине; правка пояснения хеш не двигает (T-175: пометка _meta → _about уже раз уронила сборку, 27.11). Ключи-данные из note_objects (`_meta.engine`) остаются."""
    return rules_label._strip(o, DATA_NAMES, NOTES)


# эталон: sha256(json.dumps(<файл до 09.11 БЕЗ пометок>, sort_keys=True, ensure_ascii=False)) по коммиту cabfe9fc (main на старте
# задачи T-20261109-07). Меняется только осознанно — тогда прежние записи правились, а не дополнялись.
# 27.11 (fix/bedroom-etalon-hash): хеш считается БЕЗ пометок — прежние значения (с пометками) 8027995a…/32acf826…/955a0fe6… заменены; правила те же.
FROZEN = {
    "services/planner-solver/rules/bedroom.json": "eb408846ca6cd364e8728e588eaef75c4c7af97f6667a2f0c31c3a0644948660",
    "tools/scout/rules/bedroom-composition.json": "32c49f69f3a057b7a9f3cf334b76ca45dfd987ac8eedc49949abc9a7fce39f73",
    "tools/scout/rules/bedroom-roles.json": "ee8c5eb0dbf81c932403b31483852e7e3ebf02d2f05c5a15afae12e34e052867",
}
# ровно эти добавки (раздел → ключ); всё прочее — прежнее
ADDED = {
    "services/planner-solver/rules/bedroom.json": [("purposes", "single_narrow"), ("templates", "bed_narrow_wall"),
                                                   ("rules", "bed_narrow_side_wall")],
    "tools/scout/rules/bedroom-composition.json": [("purposes", "single_narrow")],
}
# добавки T-20261112-31 (боковая спинка, полоса прохода, ковёр) — тоже только дописаны, после добавок 09.11; раздел None — корень
ADDED_T31 = {
    "services/planner-solver/rules/bedroom.json": [("templates", "bed_side_back_corner"), ("rules", "bed_side_back_wall"),
                                                   ("rules", "bed_side_back_not_couple"), (None, "switches")],
    "tools/scout/rules/bedroom-roles.json": [(None, "bed_side_back")],
    "tools/scout/rules/bedroom-composition.json": [(None, "rug_fit")],
}


# добавки T-20261112-38/2 (движок групп) — дописаны после добавок T-31; ключи на «_» (пояснения) снимаются без проверки порядка
ADDED_T38 = {
    "services/planner-solver/rules/bedroom.json": [("_meta", "_engine_why"), ("_meta", "engine"),
                                                   ("rules", "bed_foot_not_in_swing"), ("rules", "bed_side_in_swing_soft"),
                                                   ("rules", "storage_front_radiator"), ("rules", "no_storage_at_bed_head_side"),
                                                   ("rules", "couple_small_no_wardrobe"), (None, "group_templates")],
}


# добавки T-20261112-68 (проходы по норме обычного жилья, ADR-0394) — дописаны после добавок T-38
ADDED_T68 = {
    "services/planner-solver/rules/bedroom.json": [("rules", "bed_long_side_window_wall"), ("rules", "route_to_window_and_bed_sides")],
}


# добавки T-20261112-95 (лестница тумб пары) — дописаны в конец назначения couple; раздел — путь (кортеж)
ADDED_T95 = {
    "tools/scout/rules/bedroom-composition.json": [(("purposes", "couple"), "_nightstand_steps_why"),
                                                   (("purposes", "couple"), "nightstand_steps")],
}


# добавки T-20261117-13 (полоса высоты лампы от 33 см и запас у соседнего стиля) — дописаны последними ключами лампы каждого назначения;
# пояснения верхнего уровня `_lamp_band_why` / `_lamp_spare_why` на «_» снимаются без проверки порядка
_LAMP = ["band_min", "neighbour_spare", "mesh_first"]   # T-13 + T-20261118-04/4: ключи в порядке добавления, mesh_first — последним
ADDED_T13 = {
    "tools/scout/rules/bedroom-composition.json": [(("purposes", p, "decor", "лампа"), k) for p in ("couple", "single", "guest", "single_narrow")
                                                   for k in _LAMP] + [(None, "_lamp_band_why"), (None, "_lamp_spare_why")],
}


# добавки T-20261120-163 (шторы: фотопечать нигде, рулонные лофта по стилю, по окну, запас соседа) — дописаны последними
# ключами штор каждого назначения; пояснение верхнего уровня `_curtain_spare_why` на «_» снимается без проверки порядка
_CURTAIN = ["deny_all", "deny_by_style", "per_window", "neighbour_spare", "neighbour_pool"]
ADDED_T163 = {
    "tools/scout/rules/bedroom-composition.json": [(("purposes", p, "decor", "шторы"), k) for p in ("couple", "single", "guest", "single_narrow")
                                                   for k in _CURTAIN] + [(None, "_curtain_spare_why")],
}


def _sec(d: dict, sec):
    if sec is None:
        return d
    for k in (sec if isinstance(sec, tuple) else (sec,)):
        d = d[k]
    return d


def _drop_t38(name: str, d: dict, check_order: bool = False) -> dict:
    d = copy.deepcopy(d)
    for sec, key in reversed(ADDED_T38.get(name, []) + ADDED_T68.get(name, []) + ADDED_T95.get(name, []) + ADDED_T13.get(name, []) + ADDED_T163.get(name, [])):
        tgt = _sec(d, sec)
        if check_order and not key.startswith("_"):
            assert list(k for k in tgt if not k.startswith("_"))[-1] == key, f"{name}: {key} — не последним ключом"
        tgt.pop(key)
    return d


def _h(o) -> str:
    return hashlib.sha256(json.dumps(o, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _without_additions(name: str, d: dict) -> dict:
    d = _drop_t38(name, d, check_order=True)
    for sec, key in reversed(ADDED_T31.get(name, [])):
        tgt = d if sec is None else d[sec]
        assert list(k for k in tgt if not k.startswith("_"))[-1] == key, f"{name}: {key} — не последним ключом"
        tgt.pop(key)
    if name.endswith("bedroom-roles.json"):           # тег назначения — последним ключом у каждой роли
        n = 0
        for tags in d["purposes"].values():          # детские роли тега не получили — у них прежний набор
            if "single_narrow" in tags:
                assert list(tags)[-1] == "single_narrow", "новый тег должен идти после прежних"
                tags.pop("single_narrow")
                n += 1
        assert n == 6, n                              # кровать, тумба, комод, шкаф, стол рабочий, стул рабочий
        return d
    for sec, key in ADDED[name]:
        assert key in d[sec], (sec, key)
        d[sec].pop(key)
    return d


def _drop_t31(name: str, d: dict) -> dict:
    d = _drop_t38(name, d)
    for sec, key in ADDED_T31.get(name, []):
        (d if sec is None else d[sec]).pop(key)
    return d


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_old_entries_unchanged(name):
    cur = json.loads((ROOT / name).read_text(encoding="utf-8"))
    assert _h(_no_notes(_without_additions(name, cur))) == FROZEN[name], f"{name}: прежние записи изменились — добавлять, не править"


def _frozen_ok(name: str, cur: dict) -> bool:
    return _h(_no_notes(_without_additions(name, copy.deepcopy(cur)))) == FROZEN[name]


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_etalon_red_on_rule_change(name):
    """Сломал — покраснело: поменяли ПРАВИЛО (число, текст значения, ключ, ключ на «_» с данными) → эталон красный; без этого теста хеш мог бы молчать."""
    cur = json.loads((ROOT / name).read_text(encoding="utf-8"))
    assert _frozen_ok(name, cur)                                           # исходное — зелёное (иначе контроль ничего не доказывает)

    def leaf(o):                                                           # первый числовой лист вне пометок
        if isinstance(o, dict):
            for k, v in o.items():
                if _is_note(k, v):
                    continue
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    return o, k
                r = leaf(v)
                if r:
                    return r
        elif isinstance(o, list):
            for v in o:
                r = leaf(v)
                if r:
                    return r
        return None

    base = _without_additions(name, copy.deepcopy(cur))
    found = leaf(base)
    assert found is not None, f"{name}: в файле нет числового значения правила — контроль ничего не доказывает"
    h0, k0 = found
    h0[k0] = h0[k0] + 1                                                    # правило поменяли
    assert _h(_no_notes(base)) != FROZEN[name], f"{name}: правка числа правила эталон не заметил"
    c = _without_additions(name, copy.deepcopy(cur))
    c["_default"] = 0                                                      # «_»-ключ с ЧИСЛОМ — данные, как в метке правил
    assert _h(_no_notes(c)) != FROZEN[name], f"{name}: «_»-ключ с данными не заметил"
    d = _without_additions(name, copy.deepcopy(cur))
    d["новое_правило"] = {"x": 1}                                          # добавили ключ
    assert _h(_no_notes(d)) != FROZEN[name], f"{name}: добавленный ключ не заметил"
    e = _without_additions(name, copy.deepcopy(cur))
    e["_meta"] = {"source": "текст", "limit": 5}                           # объект на «_» с не-текстом — данные
    assert _h(_no_notes(e)) != FROZEN[name], f"{name}: _meta с числом не заметил"


def test_meta_engine_is_data_not_note():
    """`_meta.engine` в bedroom.json — ДАННЫЕ (движок солвера спальни, planner/bedroom_checks.py:74), а не пометка (замечание Fable 27.11, та же дыра, что `_default`):
    смена движка двигает хеш (метка набора правил и этот хеш видят её), правка текста `_meta.about` / `_engine_why` — нет; а без `engine` объект остаётся пометкой."""
    cur = json.loads((ROOT / "services/planner-solver/rules/bedroom.json").read_text(encoding="utf-8"))
    assert "engine" in cur["_meta"] and "engine" in NOTES["_meta"], "engine должен стоять в NOTES этого теста"
    h0 = _h(_no_notes(cur))
    other = copy.deepcopy(cur)
    other["_meta"]["engine"] = "items" if cur["_meta"]["engine"] != "items" else "groups"
    assert _h(_no_notes(other)) != h0, "смена _meta.engine хеш не двинула — слепое пятно"
    text = copy.deepcopy(cur)
    text["_meta"]["about"] = "совсем другое описание"
    text["_meta"]["_engine_why"] = "другое пояснение"
    text["_meta"]["roles_note"] = "иное примечание"
    assert _h(_no_notes(text)) == h0, "правка пояснений в _meta двинула хеш"
    no_engine = copy.deepcopy(cur)
    no_engine["_meta"].pop("engine")
    assert "_meta" not in _no_notes(no_engine), "без engine объект из одних текстов — пометка"


def test_meta_reads_are_declared_as_data():
    """Сторож: код планировщика читает из объекта-пометки `_meta` файла правил только ключи, объявленные данными (NOTES) — новое `…get("_meta", {}).get("x")` без записи → красный
    (иначе правка `x` не двигала бы эталон, как было с `engine`). −Контроль: тот же поиск на строке без записи находит ключ."""
    import re
    rx = re.compile(r"""(?:\.get\(\s*|\[\s*)['"]_meta['"][^)\]]*[\)\]]\s*(?:\.get\(\s*|\[\s*)['"](\w+)['"]""")
    found = {}
    for p in sorted((ROOT / "services" / "planner-solver" / "planner").rglob("*.py")):
        for i, ln in enumerate(p.read_text(encoding="utf-8").split("\n"), 1):
            for m in rx.finditer(ln):
                found.setdefault(m.group(1), []).append(f"{p.name}:{i}")
    assert "engine" in found, "поиск не нашёл чтение _meta.engine в bedroom_checks.py — сторож слеп (поменялся код чтения?)"
    undeclared = {k: v for k, v in found.items() if k not in NOTES["_meta"]}
    assert not undeclared, f"код читает ключ из объекта-пометки _meta, а в NOTES его нет (данные → добавить в NOTES): {undeclared}"
    assert [m.group(1) for m in rx.finditer('x = rules().get("_meta", {}).get("новый_ключ")')] == ["новый_ключ"], "−контроль: поиск не ловит чтение"


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_etalon_green_on_note_change(name):
    """Поменяли ПОМЕТКУ → эталон зелёный: переписали/добавили/убрали `_about`, `_why`, текстовый `_meta` на любой глубине."""
    cur = json.loads((ROOT / name).read_text(encoding="utf-8"))
    assert _frozen_ok(name, cur)
    a = _without_additions(name, copy.deepcopy(cur))
    a["_about"] = "совсем другой текст пояснения"
    a["_новая_пометка_why"] = "ещё одна"
    a["_meta"] = {"source": "другой источник", "description": "другое описание", "roles": {"примечание": "иначе"}}
    assert _h(_no_notes(a)) == FROZEN[name], f"{name}: правка пометки двинула эталон"
    b = _without_additions(name, copy.deepcopy(cur))
    for k in [k for k, v in b.items() if k.startswith("_") and isinstance(v, str)]:
        b.pop(k)                                                           # пометок вообще нет
    b.pop("_meta", None)
    assert _h(_no_notes(b)) == FROZEN[name], f"{name}: удаление пометок двинуло эталон"
    for sec in b.values():                                                 # вложенные пометки (в разделах) — тоже не в счёт
        if isinstance(sec, dict):
            sec["_вложенная_why"] = "пояснение внутри раздела"
    assert _h(_no_notes(b)) == FROZEN[name], f"{name}: вложенная пометка двинула эталон"


def test_additions_are_last_keys():
    br = _drop_t31("services/planner-solver/rules/bedroom.json",
                   json.loads((ROOT / "services/planner-solver/rules/bedroom.json").read_text(encoding="utf-8")))
    assert list(br["purposes"])[-1] == "single_narrow"
    assert list(k for k in br["templates"] if not k.startswith("_"))[-1] == "bed_narrow_wall"
    assert list(k for k in br["rules"] if not k.startswith("_"))[-1] == "bed_narrow_side_wall"
    assert br["templates"]["bed_narrow_wall"]["for"] == ["single_narrow"]
    assert br["purposes"]["single_narrow"]["bed_template"] == "bed_narrow_wall"
    # прежние назначения bed_template не задают — их путь шаблонов прежний
    assert not [k for k, v in br["purposes"].items() if k != "single_narrow" and "bed_template" in v]


def _uk(room_id: str, purpose: str = "single_narrow") -> Room:
    spec = next(r for r in json.loads(UK.read_text(encoding="utf-8"))["rooms"] if r["id"] == room_id)
    return Room(width_cm=spec["w"], depth_cm=spec["d"], room_type="bedroom", purpose=purpose,
                openings=[Opening(**o) for o in spec["openings"]],
                radiators=[Radiator(**r) for r in spec.get("radiators", [])])


NARROW = [Item(role="кровать", w_cm=96, d_cm=200, h_cm=90),          # UK single 90×190 в раме 96×200
          Item(role="тумба прикроватная", w_cm=40, d_cm=35, h_cm=50),
          Item(role="шкаф", w_cm=100, d_cm=58, h_cm=200),
          Item(role="комод", w_cm=80, d_cm=45, h_cm=85),
          Item(role="стол рабочий", w_cm=100, d_cm=55, h_cm=75),
          Item(role="стул рабочий", w_cm=50, d_cm=50, h_cm=85)]


def _sig(lay):
    return [(p.role, p.x, p.y, p.rot, p.tpl_id) for p in lay.placements]


@pytest.mark.parametrize("room_id", ["bedroom-three", "bedroom-two"])
def test_narrow_bed_fits_uk_rooms(room_id):
    room = _uk(room_id)
    lay = solve_bedroom(room, NARROW)
    hard = [v.message for v in lay.violations if v.severity is Severity.HARD]
    assert lay.ok and not hard, hard
    bed = next(p for p in lay.placements if is_bed(p))
    assert (bed.item.w_cm, bed.item.d_cm) == (96, 200)
    assert bed.tpl_id == "bed_narrow_wall"
    assert side_on_wall(room, bed), "длинный бок узкой кровати — к стене"
    assert not [v for v in lay.violations if v.code == "BED_NARROW_OFF_WALL"]
    re = validate(room, lay.placements)          # повторная проверка тем же диспетчером
    assert not [v for v in re.violations if v.severity is Severity.HARD]
    assert _sig(lay) == _sig(solve_bedroom(_uk(room_id), NARROW))      # детерминизм


def test_narrow_refuses_double_bed():
    lay = solve_bedroom(_uk("bedroom-two"), [Item(role="кровать", w_cm=160, d_cm=210, h_cm=95)])
    assert lay.meta["reason"] == ["BED_NOT_SINGLE"] and lay.unplaced == ["кровать"] and not lay.placements


def test_side_rule_only_for_narrow_purpose():
    """BED_NARROW_OFF_WALL — только у назначения с bed_template; прежнее single его не получает."""
    from planner.models import Placement
    room_n, room_s = _uk("bedroom-two"), _uk("bedroom-two", "single")
    mid = [Placement(role="кровать", item=NARROW[0], x=250, y=100, rot=0)]   # у южной стены, оба длинных бока далеко от стен
    codes_n = {v.code for v in validate(room_n, mid).violations}
    codes_s = {v.code for v in validate(room_s, mid).violations}
    assert "BED_NARROW_OFF_WALL" in codes_n
    assert "BED_NARROW_OFF_WALL" not in codes_s


def test_old_single_path_unchanged_in_box_room():
    """Прежнее single в тех же комнатах шаблон bed_narrow_wall не берёт (путь шаблонов прежний)."""
    lay = solve_bedroom(_uk("bedroom-three", "single"), NARROW)
    assert not [p for p in lay.placements if p.tpl_id == "bed_narrow_wall"]
