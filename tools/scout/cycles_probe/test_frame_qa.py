#!/usr/bin/env python3
"""Юнит-тесты сторожа кадров (чистая логика, без Blender): классы слотов, оценка кадра, предпроверка на подделанных данных, хеш отчёта.
Запуск: `~/venvs/scout/bin/python tools/scout/cycles_probe/test_frame_qa.py` (работает и под pytest)."""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import frame_qa as Q  # noqa: E402

RULES = Q.load_rules()


def test_slot_classes():
    c = lambda s: Q.slot_class(s, RULES)
    assert c("диван#0") == "main" and c("кровать#0") == "main"
    assert c("картина 2#0") == "art" and c("textile:шторы#0") == "curtain"
    assert c("textile:подушка 2#0") == "pillow" and c("textile:плед#0") == "throw"
    assert c("ceiling:люстра#0") == "chandelier" and c("plant:кашпо#0") == "plant"
    assert c("ковёр#0") == "rug" and c("decor:ваза#0") == "decor" and c("carrier:лампа#0") == "lamp"
    assert c("стул 2#0") == "furniture" and c("тв-тумба#0") == "furniture"


def test_textile_form_and_exception():
    assert Q.textile_form("textile:плед#0") == "throw" and Q.textile_form("textile:подушка 2#0") == "pillow"
    assert Q.textile_form("диван#0") is None
    assert Q.textile_renders("throw", {"render": {"throw": False}}) is False
    assert Q.textile_renders("curtain", {"render": {"throw": False}}) is True


def _ev(px=None, geo=None, art=None, cam=None, cover=0.0, present=None, expect=None):
    expect = expect or {"диван#0": "main", "картина#0": "art", "textile:шторы#0": "curtain", "стул#0": "furniture", "textile:подушка#0": "pillow"}
    present = present if present is not None else {s: 1 for s in expect}
    px = px or {"диван#0": 20000, "картина#0:canvas": 900, "textile:шторы#0": 9000, "стул#0": 2000, "textile:подушка#0": 800}
    geo = geo or {s: {"inFrame": True, "clipped": 1.0, "rect": (0.2, 0.2, 0.4, 0.4)} for s in expect}
    return Q.evaluate_frame(expect, present, px, geo, lambda r, s: cover, RULES, art, cam)


def test_clean_frame_is_ok():
    r = _ev(art={"картина#0": {"hasMap": True, "content": True}})
    assert r["verdict"] == "ok", r


def test_art_without_map_is_brak():
    r = _ev(art={"картина#0": {"hasMap": False, "content": True}})
    assert r["verdict"] == "brak" and any(s["slot"] == "картина#0" and s["state"] == "art_no_map" for s in r["slots"])


def test_art_white_is_warn_not_brak():
    # белое искусство по выбору человека не бракуется (план): предупреждение, не стоп
    r = _ev(art={"картина#0": {"hasMap": True, "content": False, "detail": "белое"}})
    assert r["verdict"] == "warn"


def test_curtain_removed_is_brak():
    r = _ev(present={"диван#0": 1, "картина#0": 1, "textile:шторы#0": 0, "стул#0": 1, "textile:подушка#0": 1})
    s = next(x for x in r["slots"] if x["slot"] == "textile:шторы#0")
    assert s["state"] == "not_in_scene" and r["verdict"] == "brak"


def test_hidden_item_in_frame_is_brak():
    px = {"диван#0": 20000, "картина#0:canvas": 900, "textile:шторы#0": 9000, "стул#0": 0, "textile:подушка#0": 800}
    r = _ev(px=px)
    s = next(x for x in r["slots"] if x["slot"] == "стул#0")
    assert s["state"] == "missing" and s["level"] == "brak"


def test_paid_lamp_not_in_scene_is_brak_even_if_optional_class():
    r = _ev(expect={"диван#0": "main", "carrier:лампа#0": "lamp"}, present={"диван#0": 1, "carrier:лампа#0": 0}, px={"диван#0": 20000})
    assert next(x for x in r["slots"] if x["slot"] == "carrier:лампа#0")["level"] == "brak"


def test_out_of_frame_is_not_brak():
    px = {"диван#0": 20000, "картина#0:canvas": 900, "textile:шторы#0": 9000, "стул#0": 0, "textile:подушка#0": 800}
    expect_geo = {s: {"inFrame": True, "clipped": 1.0, "rect": (0.2, 0.2, 0.4, 0.4)} for s in ["диван#0", "картина#0", "textile:шторы#0", "textile:подушка#0"]}
    expect_geo["стул#0"] = {"inFrame": False, "clipped": 0.0, "rect": None}
    r = _ev(px=px, geo=expect_geo)
    assert next(x for x in r["slots"] if x["slot"] == "стул#0")["state"] == "out_of_frame" and r["verdict"] == "ok"


def test_occluded_and_few_pixels_are_indeterminate_not_clean():
    px = {"диван#0": 20000, "картина#0:canvas": 900, "textile:шторы#0": 9000, "стул#0": 0, "textile:подушка#0": 800}
    r = _ev(px=px, cover=0.9)
    s = next(x for x in r["slots"] if x["slot"] == "стул#0")
    assert s["state"] == "indeterminate" and r["verdict"] == "indeterminate"
    px["стул#0"] = 120   # мало пикселей, но не ноль
    r = _ev(px=px)
    assert next(x for x in r["slots"] if x["slot"] == "стул#0")["state"] == "indeterminate"


def test_object_at_camera_is_indeterminate():
    px = {"диван#0": 20000, "картина#0:canvas": 900, "textile:шторы#0": 9000, "стул#0": 0, "textile:подушка#0": 800}
    geo = {s: {"inFrame": True, "clipped": 1.0, "rect": (0.2, 0.2, 0.4, 0.4)} for s in ["диван#0", "картина#0", "textile:шторы#0", "textile:подушка#0"]}
    geo["стул#0"] = {"inFrame": True, "clipped": 1.0, "rect": (0.0, 0.0, 1.0, 1.0), "nearCam": True}
    r = _ev(px=px, geo=geo)
    assert next(x for x in r["slots"] if x["slot"] == "стул#0")["state"] == "indeterminate"


def test_small_canvas_is_indeterminate():
    r = _ev(px={"диван#0": 20000, "картина#0:canvas": 120, "textile:шторы#0": 9000, "стул#0": 2000, "textile:подушка#0": 800}, art={"картина#0": {"hasMap": True, "content": True}})
    assert next(x for x in r["slots"] if x["slot"] == "картина#0")["state"] == "indeterminate"


def test_main_not_visible_is_frame_brak():
    px = {"диван#0": 0, "картина#0:canvas": 900, "textile:шторы#0": 9000, "стул#0": 2000, "textile:подушка#0": 800}
    geo = {s: {"inFrame": False, "clipped": 0.0, "rect": None} for s in ["диван#0"]}
    geo.update({s: {"inFrame": True, "clipped": 1.0, "rect": (0.2, 0.2, 0.4, 0.4)} for s in ["картина#0", "textile:шторы#0", "стул#0", "textile:подушка#0"]})
    r = _ev(px=px, geo=geo)
    assert any(f["code"] == "MAIN_NOT_VISIBLE" for f in r["frame"]) and r["verdict"] == "brak"


def test_camera_mismatch_is_brak():
    r = _ev(cam={"posErrM": 0.0, "dirErrDeg": 75.0, "lensErrFrac": 0.0})
    assert any(f["code"] == "CAMERA_MISMATCH" for f in r["frame"]) and r["verdict"] == "brak"
    assert _ev(cam={"posErrM": 0.0, "dirErrDeg": 0.0, "lensErrFrac": 0.0})["verdict"] == "ok"


def test_verify_hash():
    d = tempfile.mkdtemp()
    try:
        f = os.path.join(d, "f.png")
        open(f, "wb").write(b"abc")
        assert Q.verify(f)[0] is False   # нет отчёта
        json.dump({"sha256": Q.sha256_file(f), "verdict": "ok"}, open(f + ".qa.json", "w"))
        assert Q.verify(f) == (True, "ok")
        open(f, "wb").write(b"abd")   # файл заменён после проверки
        assert Q.verify(f)[0] is False
    finally:
        shutil.rmtree(d)


def _mk_world(d, throw_in_export=False, art_map=True, drop_slot=None, drop_obj=None):
    """Минимальный набор: снимок, выгрузка, scene.json, GLB с узлом картины (с картой или без)."""
    import struct
    os.makedirs(os.path.join(d, "dump"))
    os.makedirs(os.path.join(d, "scene"))
    slots = [{"slotId": "диван#0", "role": "диван", "kind": "mesh", "unplaced": False}, {"slotId": "картина#0", "role": "картина", "kind": "kit", "unplaced": False},
             {"slotId": "textile:плед#0", "role": "плед", "kind": "kit", "unplaced": False}]
    json.dump({"variant": "t", "slots": slots}, open(os.path.join(d, "dump", "scene_info.json"), "w"))
    meshes = [{"slotId": "диван#0", "meshId": "1_2", "url": "/x.glb", "sha": "aa"}]
    kits = [{"slotId": "картина#0", "kit": "wall-plane", "surface": {"maps": {"color": "/a.png"}}}]
    if throw_in_export:
        kits.append({"slotId": "textile:плед#0", "kit": "textile", "surface": {}})
    if drop_slot:
        meshes = [m for m in meshes if m["slotId"] != drop_slot]
    json.dump({"meshes": meshes, "kits": kits, "plants": []}, open(os.path.join(d, "dump", "scene-export.json"), "w"))
    open(os.path.join(d, "scene", "m042.npz"), "wb").write(b"x" * 100)
    open(os.path.join(d, "scene", "t.jpg"), "wb").write(b"x" * 100)
    objs = [] if drop_obj else [{"role": "диван", "file": "m042.npz", "tex": "t.jpg", "n_faces": 100}]
    json.dump({"objs": objs, "rugs": [], "cams": []}, open(os.path.join(d, "scene", "scene.json"), "w"))
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 256, 256) + b"\x08\x02\x00\x00\x00" + b"\x00" * 8
    mats = [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}] if art_map else [{"pbrMetallicRoughness": {}}]
    j = {"asset": {"version": "2.0"}, "nodes": [{"name": "m__u1", "mesh": 0}], "meshes": [{"primitives": [{"material": 0}]}], "materials": mats,
         "textures": [{"source": 0}], "images": [{"bufferView": 0, "mimeType": "image/png"}], "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(png)}]}
    jb = json.dumps(j).encode()
    jb += b" " * (-len(jb) % 4)
    bb = png + b"\x00" * (-len(png) % 4)
    glb = b"glTF" + struct.pack("<II", 2, 12 + 8 + len(jb) + 8 + len(bb)) + struct.pack("<I", len(jb)) + b"JSON" + jb + struct.pack("<I", len(bb)) + b"BIN\x00" + bb
    open(os.path.join(d, "dump", "demo_nodes.glb"), "wb").write(glb)
    json.dump([{"uuid": "u1", "slot": "картина#0", "visible": True}], open(os.path.join(d, "dump", "demo_nodes_uuids.json"), "w"))
    tx = os.path.join(d, "textile.json")
    json.dump({"render": {"curtain": True, "throw": False, "pillow": True}}, open(tx, "w"))
    return tx


def _pf(d, tx):
    return Q.preflight(os.path.join(d, "dump"), os.path.join(d, "dump", "scene-export.json"), os.path.join(d, "scene"), textile_path=tx, rules=RULES)


def _codes(r, level="error"):
    return sorted((f["code"], f["slot"]) for f in r["findings"] if f["level"] == level)


def test_preflight_clean_and_textile_exempt():
    d = tempfile.mkdtemp()
    try:
        tx = _mk_world(d)
        r = _pf(d, tx)
        assert r["ok"] and r["exempt"] and r["exempt"][0]["slot"] == "textile:плед#0", r
    finally:
        shutil.rmtree(d)


def test_preflight_throw_missing_when_not_exempt():
    d = tempfile.mkdtemp()
    try:
        tx = _mk_world(d)
        json.dump({"render": {"throw": True}}, open(tx, "w"))   # плед должен рисоваться, а в выгрузке его нет → потеря
        r = _pf(d, tx)
        assert ("EXPORT_MISSING", "textile:плед#0") in _codes(r) and not r["ok"]
    finally:
        shutil.rmtree(d)


def test_preflight_catches_missing_art_map_and_geometry_and_export():
    d = tempfile.mkdtemp()
    try:
        r = _pf(d, _mk_world(d, art_map=False))
        assert ("ART_NO_MAP", "картина#0") in _codes(r)
    finally:
        shutil.rmtree(d)
    d = tempfile.mkdtemp()
    try:
        r = _pf(d, _mk_world(d, drop_slot="диван#0"))
        assert ("EXPORT_MISSING", "диван#0") in _codes(r)
    finally:
        shutil.rmtree(d)
    d = tempfile.mkdtemp()
    try:
        r = _pf(d, _mk_world(d, drop_obj=True))
        assert ("NOT_IN_SCENE", "диван#0") in _codes(r)
    finally:
        shutil.rmtree(d)


def test_preset_exports_every_paid_page_kind_server_scene_does_not_place():
    """T-20261118-03/2 ❷: серверная сцена (`draft_render.decor_layout`) не ставит `carrier_surface` (лампа на комоде/тумбе) — место их даёт
    только страница, поэтому выгрузка декора обязана их брать (`carrier`), иначе оплачиваемая лампа «не в сцене» (3 спальни, лампы пропадали
    из кадра). Классы слотов сторожа и ключи выгрузки пресета — из одних данных: каждый класс «слот страницы» (`carrier:`, `plant:`, `ceiling:`,
    `textile:`) есть в ключах пресета."""
    keys = json.load(open(os.path.join(HERE, "render-preset.json"), encoding="utf-8"))["dumpExport"].split(",")
    for need in ("carrier", "plant", "ceiling", "textile", "картин"):
        assert need in keys, need


# ---- T-20261118-03/4 ①: оболочка комнаты (шторы окон, радиатор, карниз) — потеря узла страницы в GLB ловится предпроверкой


def _shell_world(d, nodes, radiators="absent", windows=0, glb_has=()):
    """Мир с узлами страницы (`scene_info.json:nodes`); в GLB лежит только `u1` (картина) и uuid из `glb_has` (их тоже кладём в GLB-узлы)."""
    tx = _mk_world(d)
    ip = os.path.join(d, "dump", "scene_info.json")
    si = json.load(open(ip))
    si["nodes"] = nodes
    json.dump(si, open(ip, "w"))
    ep = os.path.join(d, "dump", "scene-export.json")
    ex = json.load(open(ep))
    if radiators != "absent":
        ex["radiators"] = radiators
    json.dump(ex, open(ep, "w"))
    sp = os.path.join(d, "scene", "scene.json")
    sc = json.load(open(sp))
    sc["openings"] = [{"wall": "north", "kind": "window"}] * windows
    json.dump(sc, open(sp, "w"))
    if glb_has:
        uu = json.load(open(os.path.join(d, "dump", "demo_nodes_uuids.json")))
        # GLB тестового мира один (узел `m__u1`); чтобы «лежало в GLB», подменяем его имя: узел u1 получает slot оболочки
        for n in nodes:
            if n["uuid"] in glb_has:
                uu.append({"uuid": n["uuid"], "slot": n.get("slot", ""), "visible": True})
        json.dump(uu, open(os.path.join(d, "dump", "demo_nodes_uuids.json"), "w"))
    return tx


def _node(uu, chain, slot="", y=(0.0, 1.0), visible=True):
    return {"uuid": uu, "type": "Mesh", "chain": chain, "slot": slot, "visible": visible, "min": [0, y[0], 0], "max": [1, y[1], 1]}


def test_shell_curtains_lost_is_brak_and_present_is_clean():
    d = tempfile.mkdtemp()
    try:
        r = _pf(d, _shell_world(d, [_node("c1", "Mesh<curtains<Scene")]))
        assert ("SHELL_LOST", "shell:curtains") in _codes(r) and not r["ok"], r
    finally:
        shutil.rmtree(d)
    d = tempfile.mkdtemp()
    try:
        # узел оболочки со штатным uuid `u1` (он есть в GLB) — потери нет
        r = _pf(d, _shell_world(d, [_node("u1", "Mesh<curtains<Scene")]))
        assert not [c for c in _codes(r) if c[0].startswith("SHELL")], r
    finally:
        shutil.rmtree(d)


def test_shell_rod_lost_but_baseboard_and_hidden_are_not():
    d = tempfile.mkdtemp()
    try:
        nodes = [_node("r1", "Mesh<fixtures:living:north<room:living<Scene", y=(2.1, 2.3)),          # карниз: выше 2 м
                 _node("p1", "Mesh<fixtures:living:north<room:living<Scene", y=(0.0, 0.1)),          # плинтус — не оболочка-карниз
                 _node("h1", "Mesh<curtains<Scene", visible=False)]                                  # скрытый — не требуем
        r = _pf(d, _shell_world(d, nodes))
        sh = [(c, sl) for c, sl in _codes(r) if c.startswith("SHELL")]
        assert sh == [("SHELL_LOST", "shell:rod")], sh
    finally:
        shutil.rmtree(d)


def test_shell_explicit_exclude_in_preset_keys_is_not_loss():
    d = tempfile.mkdtemp()
    keep = Q.dump_keys
    try:
        Q.dump_keys = lambda rules, dd="": ["textile", "-curtains"]      # владелец/заказ явно убрал шторы оболочки из выгрузки
        r = _pf(d, _shell_world(d, [_node("c1", "Mesh<curtains<Scene")]))
        assert not [c for c in _codes(r) if c[0].startswith("SHELL")], r
    finally:
        Q.dump_keys = keep
        shutil.rmtree(d)
    d = tempfile.mkdtemp()
    try:
        Q.dump_keys = lambda rules, dd="": ["textile"]                    # ключа `rod` нет — карниз не требуем
        r = _pf(d, _shell_world(d, [_node("r1", "Mesh<fixtures:living:north<room:living<Scene", y=(2.1, 2.3))]))
        assert not [c for c in _codes(r) if c[0].startswith("SHELL")], r
    finally:
        Q.dump_keys = keep
        shutil.rmtree(d)


def test_shell_radiators_field_missing_or_lost():
    d = tempfile.mkdtemp()
    try:   # окна есть, а в выгрузке нет поля radiators — выгрузка до радиаторов (старый дамп)
        r = _pf(d, _shell_world(d, [], windows=2))
        assert ("SHELL_NO_FIELD", "shell:radiator") in _codes(r), r
    finally:
        shutil.rmtree(d)
    d = tempfile.mkdtemp()
    try:   # поле есть, радиаторов 2, а узлов в GLB нет
        r = _pf(d, _shell_world(d, [], radiators=[{"opening": 1}, {"opening": 2}], windows=2))
        assert ("SHELL_LOST", "shell:radiator") in _codes(r), r
    finally:
        shutil.rmtree(d)
    d = tempfile.mkdtemp()
    try:   # окон нет — поля может не быть (комната без окон)
        r = _pf(d, _shell_world(d, [], windows=0))
        assert not [c for c in _codes(r) if c[0].startswith("SHELL")], r
    finally:
        shutil.rmtree(d)


def test_shell_kinds_follow_real_preset():
    keys = Q.dump_keys(RULES)
    assert keys and "rod" in keys and "-curtains" not in keys and "-radiator" not in keys, keys


def test_dump_keys_prefer_the_dump_own_record_over_preset():
    d = tempfile.mkdtemp()
    try:
        assert Q.dump_keys(RULES, d) == Q.dump_keys(RULES)                     # файла в дампе нет — пресет
        json.dump({"export": "textile,-curtains,rod"}, open(os.path.join(d, "dump_keys.json"), "w"))
        assert Q.dump_keys(RULES, d) == ["textile", "-curtains", "rod"]        # дамп помнит, чем его брали
        json.dump({"export": "all"}, open(os.path.join(d, "dump_keys.json"), "w"))
        assert Q.dump_keys(RULES, d) is None
    finally:
        shutil.rmtree(d)


# ---- T-20261118-03/4 ②: осколки/дыры внутри маски слота (ковёр с вырезом по маске)

try:
    import numpy as np
except ImportError:      # без numpy детектор не запустить (в образе Blender он есть)
    np = None

AN = RULES["anomaly"]


def _scene(holes=0.0, shade=1.0, grain=0.0, rug_col=((0.92, 0.92, 0.9), (0.1, 0.1, 0.1)), size=240, ring_free=True):
    """Кадр 240×240: пол (тёплое дерево), посередине ковёр 120×120 в клетку (светлый/тёмный), `holes` — доля клеток, где ковёр «вырезан» и виден пол."""
    fl = np.array([0.85, 0.72, 0.52], np.float32)
    fr = np.tile(fl, (size, size, 1))
    lab = np.ones((size, size), np.int32)
    a, b = (60, 180) if ring_free else (0, size)
    cell = 10
    yy, xx = np.mgrid[a:b, a:b]
    chk = ((xx // cell + yy // cell) % 2).astype(bool)
    rug = np.where(chk[..., None], np.array(rug_col[1], np.float32), np.array(rug_col[0], np.float32)) * shade
    rng = np.random.RandomState(3)
    nc = (b - a) // cell
    cut = rng.rand(nc, nc) < holes
    cutm = np.kron(cut, np.ones((cell, cell), bool))
    hole_px = fl * (1.0 + grain * (rng.rand(b - a, b - a, 1).astype(np.float32) - 0.5) * 2)     # зерно и тень на виднеющемся полу
    fr[a:b, a:b] = np.where(cutm[..., None], hole_px, rug)
    lab[a:b, a:b] = 2
    return fr, lab, rug_col


def _anom(**kw):
    fr, lab, rc = _scene(**kw)
    mask = lab == 2
    pal = Q.texture_palette(np, np.array([[rc[0], rc[1]]] * 4, np.float32).reshape(4, 2, 3), np.ones((4, 2), bool), AN)
    return Q.slot_anomaly(np, fr, mask, lab == 1, pal, AN)


def test_anomaly_clean_rug_is_zero_and_crumbled_rug_is_caught():
    if np is None:
        return
    assert _anom(holes=0.0)["share"] < 0.01
    assert _anom(holes=0.35)["share"] > 0.20          # клочья: дыры показывают пол
    assert _anom(holes=0.35, grain=0.25)["share"] > 0.20   # …и на зернистом полу в тени (яркость ±25 %): мера по цветности, не по яркости
    assert _anom(holes=0.15)["share"] >= AN["warnShare"]   # редкие дыры (≈1 клетка из 7) — уже предупреждение


def test_anomaly_shadow_and_light_rug_are_not_flagged():
    if np is None:
        return
    assert _anom(shade=0.6)["share"] < 0.01           # ковёр в тени кровати: темнее, но цветность та же
    # светлый ковёр цвета пола (дерево тон-в-тон): цвет пола ЕСТЬ в палитре материала — не «чужой»
    assert _anom(rug_col=((0.86, 0.73, 0.53), (0.80, 0.68, 0.50)))["share"] < 0.01


def test_anomaly_not_assessable_without_floor_ring_or_palette():
    if np is None:
        return
    r = _anom(ring_free=False)                        # ковёр на весь кадр — пола вокруг нет, оценить нечем
    assert r["share"] is None and "мало пола" in r["why"], r
    fr, lab, rc = _scene()
    r = Q.slot_anomaly(np, fr, lab == 2, lab == 1, np.zeros((0, 3), np.float32), AN)
    assert r["share"] is None, r


def test_anomaly_state_in_evaluate_frame():
    if np is None:
        return
    expect = {"диван#0": "main", "ковёр#0": "rug"}
    px = {"диван#0": 20000, "ковёр#0": 40000}
    geo = {s: {"inFrame": True, "clipped": 1.0, "rect": (0.2, 0.2, 0.4, 0.4)} for s in expect}

    def ev(share):
        an = {"ковёр#0": {"share": share, "n": 40000}} if share is not None else {"ковёр#0": {"share": None, "n": 40000, "why": "x"}}
        r = Q.evaluate_frame(expect, {s: 1 for s in expect}, px, geo, lambda r_, s: 0.0, RULES, None, None, an)
        return next(x for x in r["slots"] if x["slot"] == "ковёр#0"), r["verdict"]
    assert ev(0.0)[0]["state"] == "ok" and ev(0.0)[1] == "ok"
    assert ev(0.08)[0]["state"] == "shards" and ev(0.08)[0]["level"] == "warn" and ev(0.08)[1] == "warn"
    assert ev(0.30)[0]["level"] == "brak" and ev(0.30)[1] == "brak"
    assert ev(0.02)[0]["state"] == "ok"                # шум ниже порога не тревожит
    assert ev(None)[0]["state"] == "ok"                # не оценить — не «битый»


if __name__ == "__main__":
    n = 0
    for k, v in sorted(globals().items()):
        if k.startswith("test_") and callable(v):
            v()
            n += 1
    print(f"test_frame_qa: ок ({n})")
