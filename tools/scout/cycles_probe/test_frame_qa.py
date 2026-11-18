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


if __name__ == "__main__":
    n = 0
    for k, v in sorted(globals().items()):
        if k.startswith("test_") and callable(v):
            v()
            n += 1
    print(f"test_frame_qa: ок ({n})")
