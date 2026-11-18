#!/usr/bin/env python3
"""Сторож кадров Cycles (render-qa-gate-01, шаги 1–2, T-20261118-03/1): брак рендера ловит программа, а не владелец.

ЦЕПОЧКА. Проверяем не намерение, а то, что реально есть: товар (оплачиваемые позиции снимка) → выгрузка сцены → собранная сцена
(узлы GLB, карты, материалы) → видимый пиксель этого кадра → ровно тот файл, что уйдёт человеку (хеш).

ШАГ 1 — ДО РЕНДЕРА (`preflight`, только стандартная библиотека). Оплачиваемые слоты (`scene_info.json:slots`, размещённые) против выгрузки
(`scene-export.json`: меши, киты, растения) и собранной сцены (`scene.json`: npz и текстуры мебели, ковры; `demo_nodes.glb`: узлы
шторы/картины/подушки/люстры/растений с картой в материале). Нет обязательной геометрии или карты — ошибка с причиной. Исключения ткани —
ЯВНЫЕ, из `data/flat3d/textile.json` (форма с `render: false` в сцену не идёт, это не «потеря»).

ШАГ 2 — КАЖДЫЙ КАДР (`Guard`, Blender). После обычных кадров сцена перекрашивается плоскими цветами — свой цвет на каждый слот (аналог
Cryptomatte/object index: «пиксель → предмет»), и тем же ракурсом, тем же размером кадра рендерится маска в 1 выборку. По маске:
сколько пикселей у каждого обязательного предмета; у картины — полотно БЕЗ рамы ≥ 400 пикселей и карта в материале с рисунком
(`wall_art.has_content`); предмет по положению в кадре, но без пикселей и не закрытый другими — брак; мало пикселей — «неопределимо»,
не «чисто». Камера сравнивается с той, что поставили при сборке кадра. Правила и пороги — `data/flat3d/frame-qa-rules.json` (данные).

ОТЧЁТ — `<кадр>.qa.json` рядом с кадром: сцена, вариант, ракурс, sha256 файла кадра, итог предпроверки, таблица слотов, итог кадра.
Ворота в публикацию (шаг 5) НЕ включены: сторож пишет отчёт и строку «СТОРОЖ КАДРА» в журнал, кадр не блокирует. `verify` сверяет хеш
отчёта с файлом (замена кадра после проверки).

ИНЪЕКЦИИ (проверка самого сторожа, `--qa-inject`): art_nomap[:слот] · art_white[:слот] · curtain_remove · hide_item:слот · camera · rug_shards[:слот].

Запуск предпроверки отдельно:  python3 frame_qa.py preflight --dump <папка demo_dump/…> --export scene-export.json --scene-dir <export2/…>
Сверка файла с отчётом:        python3 frame_qa.py verify <кадр.png>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
RULES_PATH = os.path.join(ROOT, "data", "flat3d", "frame-qa-rules.json")
TEXTILE_PATH = os.path.join(ROOT, "data", "flat3d", "textile.json")
VERSION = 1
TEXTILE_FORM = {"шторы": "curtain", "подушка": "pillow", "плед": "throw"}


# ---------------------------------------------------------------- правила и классы


def load_rules(path: str = RULES_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def slot_class(slot: str, rules: dict) -> str:
    for r in rules["slotClasses"]["rules"]:
        if "prefix" in r and slot.startswith(r["prefix"]):
            return r["class"]
        if "roles" in r and role_of(slot) in r["roles"]:
            return r["class"]
    return "furniture"


def role_of(slot: str) -> str:
    """`стул 2#0` → `стул`; `decor:ваза#0` → `ваза`; `textile:подушка 2#0` → `подушка`."""
    s = slot.split(":")[-1].split("#")[0].strip()
    return s.split(" ")[0] if s.split(" ")[0] in TEXTILE_FORM or s[-2:-1] == " " and s[-1].isdigit() else s


def textile_form(slot: str) -> str | None:
    if not slot.startswith("textile:"):
        return None
    return TEXTILE_FORM.get(slot[len("textile:"):].split("#")[0].strip().split(" ")[0])


def textile_renders(form: str, textile: dict) -> bool:
    return textile.get("render", {}).get(form, True) is not False


# ---------------------------------------------------------------- чтение GLB без Blender


def _glb(path: str):
    with open(path, "rb") as f:
        b = f.read()
    if b[:4] != b"glTF":
        raise ValueError("не GLB")
    ln, _ = struct.unpack_from("<II", b, 12)
    j = json.loads(b[20:20 + ln])
    off = 20 + ln
    binoff = None
    if off + 8 <= len(b):
        blen, btype = struct.unpack_from("<II", b, off)
        if btype == 0x004E4942:
            binoff = off + 8
    return j, b, binoff


def image_dims(data: bytes):
    """Размер картинки PNG/JPEG по заголовку; нет — None."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            m = data[i + 1]
            if m in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            if m == 0xD8 or 0xD0 <= m <= 0xD7:
                i += 2
                continue
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    return None


def glb_nodes(path: str) -> dict:
    """uuid узла → {mesh, images: [(w,h)|None], materials: n, hasTexSlot: bool} по `Mesh__<uuid>`/`mesh_0__<uuid>` в имени узла."""
    j, b, binoff = _glb(path)
    out = {}
    for n in j.get("nodes", []):
        if "mesh" not in n or "__" not in n.get("name", ""):
            continue
        uu = n["name"].split("__")[-1].split(".")[0]
        imgs, mats, tex_slots = [], 0, False
        for p in j["meshes"][n["mesh"]].get("primitives", []):
            mi = p.get("material")
            if mi is None:
                continue
            mats += 1
            bct = (j["materials"][mi].get("pbrMetallicRoughness") or {}).get("baseColorTexture")
            if not bct:
                continue
            tex_slots = True
            ti = j["textures"][bct["index"]]
            si = ti.get("source")
            if si is None and "extensions" in ti:
                si = next((e.get("source") for e in ti["extensions"].values() if isinstance(e, dict) and "source" in e), None)
            im = j["images"][si] if si is not None else None
            dims = None
            if im is not None and "bufferView" in im and binoff is not None:
                bv = j["bufferViews"][im["bufferView"]]
                o = binoff + bv.get("byteOffset", 0)
                dims = image_dims(b[o:o + min(bv["byteLength"], 65536)])
            imgs.append(dims)
        out[uu] = {"images": imgs, "materials": mats, "hasTexSlot": tex_slots, "mesh": n["mesh"]}
    return out


# ---------------------------------------------------------------- шаг 1: до рендера


def dump_keys(rules: dict, dump_dir: str = "") -> list[str] | None:
    """Ключи, которыми взяты узлы страницы: `dump_keys.json` рядом с дампом (пишет `demo_scene_dump.mjs`, едет в пакет задания) → иначе пресет
    (`render-preset.json:dumpExport`, только на DEV). None — `all` или источника нет."""
    sh = rules.get("shell") or {}
    v = None
    for p, key in ((os.path.join(dump_dir, "dump_keys.json") if dump_dir else "", "export"), (os.path.join(ROOT, sh.get("presetFile", "")), sh.get("presetKey", "dumpExport"))):
        try:
            with open(p, encoding="utf-8") as f:
                v = json.load(f).get(key)
            break
        except (OSError, ValueError):
            continue
    if not v or v == "all":
        return None
    return [k.strip() for k in str(v).split(",") if k.strip()]


def shell_wanted(kind: dict, keys: list[str] | None) -> bool:
    """Должен ли этот вид узлов оболочки быть в выгрузке при таком списке ключей (зеркало правил `demo_scene_dump.mjs`)."""
    if kind.get("excludeKey") and keys and kind["excludeKey"] in keys:
        return False
    if kind.get("needKey") and keys and kind["needKey"] not in keys:
        return False
    return True


def shell_nodes(info_nodes: list[dict], kind: dict) -> list[dict]:
    """Видимые сетки страницы этого вида оболочки (`scene_info.json:nodes`)."""
    out = []
    for n in info_nodes:
        if not n.get("visible") or n.get("type") != "Mesh":
            continue
        if kind.get("slot") and n.get("slot") != kind["slot"]:
            continue
        if kind.get("chainHas") and kind["chainHas"] not in (n.get("chain") or ""):
            continue
        if "yMin" in kind and not ((n.get("min") or [0, 0])[1] > kind["yMin"] and (n.get("max") or [0, 9])[1] < kind.get("yMax", 99)):
            continue
        out.append(n)
    return out


def preflight(dump_dir: str, export_path: str, scene_dir: str, textile_path: str = TEXTILE_PATH, rules: dict | None = None) -> dict:
    """Оплачиваемые слоты против выгрузки и собранной сцены. Возвращает {ok, findings, expect, paid, exempt}; `expect` — слот → класс (обязательны в сцене)."""
    rules = rules or load_rules()
    findings: list[dict] = []

    def add(level, code, slot, why):
        findings.append({"level": level, "code": code, "slot": slot, "why": why})

    def jload(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    info_p = os.path.join(dump_dir, "scene_info.json")
    if not os.path.exists(info_p):
        add("error", "NO_SNAPSHOT", "", "нет scene_info.json (снимка оплачиваемых позиций)")
        return {"ok": False, "findings": findings, "expect": {}, "paid": 0, "exempt": []}
    si = jload(info_p)
    textile = jload(textile_path) if os.path.exists(textile_path) else {}
    exp = jload(export_path) if export_path and os.path.exists(export_path) else None
    if exp is None:
        add("error", "NO_EXPORT", "", "нет scene-export.json (выгрузки сцены)")
        return {"ok": False, "findings": findings, "expect": {}, "paid": 0, "exempt": []}
    scene = jload(os.path.join(scene_dir, "scene.json")) if os.path.exists(os.path.join(scene_dir, "scene.json")) else None
    if scene is None:
        add("error", "NO_SCENE", "", "нет scene.json собранной сцены")
    nodes_p = os.path.join(dump_dir, "demo_nodes.glb")
    uu_p = os.path.join(dump_dir, "demo_nodes_uuids.json")
    gnodes, uuinfo = {}, {}
    if os.path.exists(nodes_p) and os.path.exists(uu_p):
        try:
            gnodes = glb_nodes(nodes_p)
            uuinfo = {n["uuid"]: n for n in jload(uu_p)}
        except Exception as e:  # noqa: BLE001 — любой сбой разбора GLB — находка, не падение
            add("error", "GLB_BROKEN", "", f"demo_nodes.glb не разобрать: {e}")
    elif any(s["kind"] == "kit" for s in si["slots"]):
        add("error", "NO_GLB", "", "нет demo_nodes.glb / demo_nodes_uuids.json (шторы, картины, подушки, растения идут только из него)")
    by_slot: dict[str, list[dict]] = {}
    for uu, g in gnodes.items():
        n = uuinfo.get(uu) or {}
        if n.get("slot"):
            by_slot.setdefault(n["slot"], []).append({**g, "visible": n.get("visible", True), "min": n.get("min"), "max": n.get("max")})
    exp_ids = {m["slotId"] for m in exp.get("meshes", [])} | {k["slotId"] for k in exp.get("kits", [])}
    exp_meshes = {m["slotId"]: m for m in exp.get("meshes", [])}
    exp_kits = {k["slotId"]: k for k in exp.get("kits", [])}
    objs = (scene or {}).get("objs", [])
    obj_by_role: dict[str, dict] = {}
    for o in objs:
        obj_by_role.setdefault(o["role"], o)
    expect: dict[str, str] = {}
    exempt: list[dict] = []
    paid = [s for s in si["slots"] if not s.get("unplaced")]
    for s in paid:
        slot = s["slotId"]
        cls = slot_class(slot, rules)
        form = textile_form(slot)
        if slot not in exp_ids:
            if form and not textile_renders(form, textile):
                exempt.append({"slot": slot, "why": f"исключение ткани: textile.json render.{form}=false"})
                add("info", "TEXTILE_EXEMPT", slot, f"форма «{form}» не рисуется геометрией (data/flat3d/textile.json)")
                continue
            add("error", "EXPORT_MISSING", slot, "оплачиваемая позиция есть в снимке, а в выгрузке сцены её нет")
            continue
        expect[slot] = cls
        role = s.get("role") or role_of(slot)
        nodes = by_slot.get(slot, [])
        if slot in exp_meshes:
            m = exp_meshes[slot]
            if not m.get("url") or not m.get("meshId"):
                add("error", "MESH_URL", slot, "у меша в выгрузке нет адреса/идентификатора")
            if not m.get("sha"):
                add("warn", "MESH_HASH", slot, "у меша в выгрузке нет хеша содержимого (sha)")
            o = obj_by_role.get(slot.split("#")[0].split(":")[-1])
            if o is not None:
                p = os.path.join(scene_dir, o["file"])
                if not os.path.exists(p) or os.path.getsize(p) < 64:
                    add("error", "GEOM_MISSING", slot, f"нет файла геометрии {o['file']}")
                if not o.get("n_faces", 1):
                    add("error", "GEOM_EMPTY", slot, "в сцене у предмета 0 граней")
                if o.get("tex") and (not os.path.exists(os.path.join(scene_dir, o["tex"])) or os.path.getsize(os.path.join(scene_dir, o["tex"])) < 64):
                    add("error", "MAP_MISSING", slot, f"нет карты цвета {o['tex']}")
                if not o.get("tex"):
                    add("warn", "MAP_NONE", slot, "у предмета в сцене нет карты цвета (плоский цвет)")
            elif not nodes:
                add("error", "NOT_IN_SCENE", slot, "в собранной сцене нет ни геометрии (scene.json), ни узла GLB")
        if slot in exp_kits:
            k = exp_kits[slot]
            kind = k.get("kit")
            surf = k.get("surface") or {}
            if kind in ("rug", "wall-plane") and not (surf.get("maps") or {}).get("color"):
                add("error", "KIT_NO_MAP", slot, "у ковра/картины в выгрузке нет карты цвета")
            if kind == "rug" and scene is not None and not scene.get("rugs"):
                add("error", "NOT_IN_SCENE", slot, "ковёр в выгрузке есть, а в собранной сцене (scene.json: rugs) нет")
            if kind == "rug" and scene is not None:
                for r in scene.get("rugs", []):
                    if r.get("tex") and not os.path.exists(os.path.join(scene_dir, r["tex"])):
                        add("error", "MAP_MISSING", slot, f"нет карты ковра {r['tex']}")
            if kind != "rug":
                if not nodes:
                    add("error", "NOT_IN_SCENE", slot, "в demo_nodes.glb нет узла этого слота")
                elif not any(n["visible"] for n in nodes):
                    add("error", "NODE_HIDDEN", slot, "узел слота скрыт в сцене")
                if cls == "art":
                    dims = [d for n in nodes for d in n["images"] if d]
                    if not dims:
                        add("error", "ART_NO_MAP", slot, "у картины в GLB нет карты цвета с картинкой (материал без текстуры)")
                    elif max(w * h for w, h in dims) < 64 * 64:
                        add("error", "ART_MAP_TINY", slot, f"карта картины {max(dims)} — слишком мала")
                for n in nodes:
                    if n["hasTexSlot"] and any(d is None for d in n["images"]):
                        add("error", "MAP_BROKEN", slot, "материал ссылается на карту, которой в GLB нет")
        elif slot not in exp_meshes:
            pass
        if cls in ("pillow", "chandelier") and slot in exp_meshes and not nodes and obj_by_role.get(slot.split("#")[0].split(":")[-1]) is None:
            add("error", "NOT_IN_SCENE", slot, "в сцене нет узла GLB этого слота")
    for p in exp.get("plants", []):
        gs = "plant:" + p["slotId"]
        expect[gs] = "plant"
        nodes = by_slot.get(gs, [])
        if not nodes:
            add("warn" if False else "error", "PLANT_MISSING", gs, "растение есть в выгрузке, а узла в demo_nodes.glb нет")
        elif not any(n["visible"] for n in nodes):
            add("error", "NODE_HIDDEN", gs, "узел растения скрыт")
    # оболочка комнаты (шторы окон, радиатор, карниз): страница ставит их сама, выгрузка берёт отдельными правилами — потерю ловим здесь
    if gnodes:
        shell = rules.get("shell") or {}
        keys = dump_keys(rules, dump_dir)
        for kind in shell.get("kinds", []):
            if not shell_wanted(kind, keys):
                continue
            want = shell_nodes(si.get("nodes", []), kind)
            lost = [n for n in want if n["uuid"] not in gnodes]
            if lost:
                add("error", "SHELL_LOST", f"shell:{kind['id']}", f"{kind['label']}: на странице {len(want)} узл., в demo_nodes.glb нет {len(lost)} — дамп собран старым кодом или правило выгрузки потеряло их; кадр выйдет без них")
        rf = shell.get("radiatorsField")
        if rf and any(k["id"] == "radiator" and shell_wanted(k, keys) for k in shell.get("kinds", [])):
            win = sum(1 for o in (scene or {}).get("openings", []) if o.get("kind") == "window")
            rads = exp.get(rf)
            if rads is None and win:
                add("error", "SHELL_NO_FIELD", "shell:radiator", f"в выгрузке сцены нет поля «{rf}» при окнах ({win}): выгрузка собрана до радиаторов, на кадре их не будет")
            elif rads:
                have = sum(1 for g in gnodes for n in [uuinfo.get(g) or {}] if n.get("slot") == "radiator")
                if have < len(rads):
                    add("error", "SHELL_LOST", "shell:radiator", f"радиаторов в выгрузке {len(rads)}, в demo_nodes.glb узлов {have}")
    return {"ok": not any(f["level"] == "error" for f in findings), "findings": findings, "expect": expect, "paid": len(paid), "exempt": exempt}


# ---------------------------------------------------------------- шаг 2: оценка кадра (чистая функция, без Blender)


def _luma(a):
    return a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722


def texture_palette(np, rgb, mask, an: dict):
    """Палитра карты материала: цвета (кодирование как у кадра, 0..1), занимающие ≥ `paletteMinShare` площади под маской (прозрачное не считаем)."""
    nb = int(an["paletteBits"])
    px = rgb[mask]
    if len(px) == 0:
        return np.zeros((0, 3), np.float32)
    q = (px * (2 ** nb - 1) + 0.5).astype(np.int64)
    key = (q[:, 0] << (2 * nb)) | (q[:, 1] << nb) | q[:, 2]
    u, c = np.unique(key, return_counts=True)
    u = u[c >= an["paletteMinShare"] * len(key)]
    top = 2 ** nb - 1
    return (np.stack([(u >> (2 * nb)) & top, (u >> nb) & top, u & top], 1) / top).astype(np.float32)


def _dilate(np, m, k):
    for _ in range(k):
        g = m.copy()
        g[1:] |= m[:-1]
        g[:-1] |= m[1:]
        g[:, 1:] |= m[:, :-1]
        g[:, :-1] |= m[:, 1:]
        m = g
    return m


def slot_anomaly(np, frame, mask, room, pal, an: dict) -> dict:
    """Осколки/дыры внутри маски слота. frame — кадр (H,W,3, 0..1, как записан); mask — пиксели слота; room — пиксели «комната» (метка 1: пол, стены);
    pal — палитра карты слота. Аномальный пиксель = цвет ПОЛА вокруг слота (цветность в `floorChroma`, яркость `floorLumaLo…floorLumaHi` от яркости пола) и ни одного цвета самого материала (по цветности, с допуском на тень).
    Возвращает {share, n, ring, floor, palette} или {share: None, why} — оценить нечем (нет кольца вокруг, нет палитры)."""
    n = int(mask.sum())
    if n == 0 or len(pal) == 0:
        return {"share": None, "n": n, "why": "нет пикселей слота или палитры его карты"}
    ring = _dilate(np, mask, int(an["ringPx"])) & room
    nr = int(ring.sum())
    if nr < an["minRingPx"]:
        return {"share": None, "n": n, "ring": nr, "why": f"вокруг слота мало пола для сравнения ({nr} < {an['minRingPx']} px)"}
    floor = np.median(frame[ring], axis=0)
    p = frame[mask]
    pL = _luma(p)
    cf = floor / max(float(floor.sum()), 1e-3)
    lr = pL / max(float(_luma(floor)), 1e-3)
    near_floor = (np.abs(p / np.maximum(p.sum(1, keepdims=True), 1e-3) - cf).sum(1) < an["floorChroma"]) & (lr > an["floorLumaLo"]) & (lr < an["floorLumaHi"])
    palL = _luma(pal)
    gain = float(np.median(pL)) / max(float(np.median(palL)), 1e-3)
    cs = p / np.maximum(p.sum(1, keepdims=True), 1e-3)
    cp = pal / np.maximum(pal.sum(1, keepdims=True), 1e-3)
    best = np.full(len(p), 9.0, np.float32)
    for i in range(len(pal)):
        if palL[i] < an["darkLuma"]:
            d = np.where(pL < 0.35 * gain + 0.1, 0.0, 9.0)
        else:
            r = pL / (gain * palL[i])
            d = np.where((r > an["shadeLo"]) & (r < an["shadeHi"]), np.abs(cs - cp[i]).sum(1), 9.0)
        best = np.minimum(best, d)
    bad = near_floor & (best > an["chromaTol"])
    return {"share": float(bad.mean()), "n": n, "ring": nr, "floor": [round(float(x), 3) for x in floor], "palette": int(len(pal))}


def evaluate_frame(expect: dict, present: dict, px: dict, geo: dict, cover, rules: dict, art: dict | None = None, cam: dict | None = None, anom: dict | None = None) -> dict:
    """Разбор одного кадра по маске.
    expect  слот → класс (обязательные в сцене); present — слот → сколько объектов в сцене; px — слот (у картины `слот:canvas`) → пикселей;
    geo     слот → {inFrame, clipped (доля прямоугольника, что внутри кадра), rect (x0,y0,x1,y1 в долях)}; cover(rect, слот) → доля прямоугольника, закрытая ДРУГИМИ предметами;
    art     слот → {hasMap, content}; cam — {posErrM, dirErrDeg, lensErrFrac} относительно поставленной камеры; anom — слот → результат `slot_anomaly` (осколки внутри маски)."""
    brak_cls, warn_cls = set(rules["required"]["brak"]), set(rules["required"]["warn"])
    res: list[dict] = []
    for slot, cls in expect.items():
        minpx = rules["minPx"].get(cls, 100)
        key = slot + ":canvas" if cls == "art" else slot
        n = int(px.get(key, 0))
        r = {"slot": slot, "class": cls, "px": n, "minPx": minpx, "state": "ok", "level": "ok", "why": ""}
        res.append(r)
        if not present.get(slot):
            r.update(state="not_in_scene", why="оплачиваемого предмета нет в собранной сцене (объектов 0) — на кадре его быть не может")
        elif cls == "art" and art is not None and not (art.get(slot) or {}).get("hasMap", True):
            r.update(state="art_no_map", why="у картины в материале нет карты цвета (полотно без рисунка)")
        elif cls == "art" and art is not None and not (art.get(slot) or {}).get("content", True):
            r.update(state="art_blank", why="карта картины без рисунка: " + str((art.get(slot) or {}).get("detail", "белое/тон-в-тон")))
        elif n >= minpx:
            an_r = (anom or {}).get(slot)
            if an_r is not None:
                r["anomaly"] = an_r
                if an_r.get("share") is not None and an_r["share"] >= rules["anomaly"]["warnShare"]:
                    r.update(state="shards", why=f"внутри предмета {an_r['share']:.0%} пикселей цвета пола, которых нет в его материале — осколки/дыры (кадр {an_r['n']} px)")
        else:
            g = geo.get(slot) or {}
            if not g.get("inFrame"):
                r.update(state="out_of_frame", why="по положению вне кадра")
            else:
                occ = cover(g["rect"], slot) if g.get("rect") else 0.0
                if g.get("nearCam"):
                    r.update(state="indeterminate", why="вплотную к камере (часть габаритов за ней) — проекцию не оценить, неопределимо")
                elif n > 0:
                    r.update(state="indeterminate", why=f"мало пикселей ({n} < {minpx}) — неопределимо")
                elif occ >= rules["occludedShare"]:
                    r.update(state="indeterminate", why=f"закрыт другими предметами ({occ:.0%} площади) — неопределимо")
                elif g.get("clipped", 1.0) < 0.5:
                    r.update(state="indeterminate", why="у края кадра (больше половины вне кадра) — неопределимо")
                else:
                    r.update(state="missing", why="по положению в кадре, но пикселей 0 и другими не закрыт")
        if r["state"] == "not_in_scene":
            r["level"] = "brak"
        elif r["state"] == "missing":
            r["level"] = "brak" if cls in brak_cls else "warn"
        elif r["state"] == "art_no_map":
            r["level"] = "brak"
        elif r["state"] == "art_blank":
            r["level"] = "warn"
        elif r["state"] == "shards":
            r["level"] = "brak" if r["anomaly"]["share"] >= rules["anomaly"]["brakShare"] else "warn"
        elif r["state"] == "indeterminate":
            r["level"] = "indeterminate"
    frame: list[dict] = []
    if rules.get("mainMustBeVisible"):
        mains = [r for r in res if r["class"] == "main"]
        if mains and not any(r["state"] == "ok" for r in mains):
            frame.append({"code": "MAIN_NOT_VISIBLE", "level": "brak", "why": "главный предмет (диван/кровать) не виден в кадре — не тот ракурс или он пропал"})
    if cam:
        t = rules["camera"]
        bad = []
        if cam.get("posErrM", 0) > t["posTolM"]:
            bad.append(f"положение {cam['posErrM']:.2f} м")
        if cam.get("dirErrDeg", 0) > t["dirTolDeg"]:
            bad.append(f"направление {cam['dirErrDeg']:.1f}°")
        if cam.get("lensErrFrac", 0) > t["lensTolFrac"]:
            bad.append(f"объектив {cam['lensErrFrac']:.0%}")
        if bad:
            frame.append({"code": "CAMERA_MISMATCH", "level": "brak", "why": "камера в момент кадра не та, что поставили: " + ", ".join(bad)})
    levels = [r["level"] for r in res] + [f["level"] for f in frame]
    verdict = "brak" if "brak" in levels else "warn" if "warn" in levels else "indeterminate" if "indeterminate" in levels else "ok"
    return {"verdict": verdict, "slots": res, "frame": frame}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(frame_path: str) -> tuple[bool, str]:
    """Отчёт принадлежит ровно этому файлу? (хеш на момент сверки против хеша в отчёте) — основа ворот шага 5."""
    rp = frame_path + ".qa.json"
    if not os.path.exists(rp):
        return False, "нет отчёта сторожа рядом с кадром"
    with open(rp, encoding="utf-8") as f:
        rep = json.load(f)
    if rep.get("sha256") != sha256_file(frame_path):
        return False, "хеш файла не совпадает с отчётом — кадр подменён или перезаписан после проверки"
    return True, rep.get("verdict", "?")


# ---------------------------------------------------------------- шаг 2: сторож внутри Blender


def _lin(v: float) -> float:
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


class Guard:
    """Подключается к `render_cycles.py` четырьмя вызовами: `scene_ready`, `camera_ready`, `frame_done`, `finish`. Любой сбой сторожа — в журнал, рендер не ломает."""

    def __init__(self, a, M: dict, enabled: bool = True):
        self.a, self.M, self.on = a, M, enabled
        self.rules = load_rules()
        self.inject = [s for s in (getattr(a, "qa_inject", "") or "").split(",") if s]
        self.pre: dict = {}
        self.cams: dict[str, dict] = {}
        self.frames: list[dict] = []
        self.t_qa = 0.0
        self.art: dict = {}
        self.dump_dir = os.path.dirname(os.path.abspath(a.demo_nodes)) if getattr(a, "demo_nodes", "") else ""
        if not enabled:
            return
        try:
            t0 = time.time()
            self.pre = preflight(self.dump_dir, getattr(a, "export", ""), a.scene_dir, rules=self.rules) if self.dump_dir else {"ok": True, "findings": [], "expect": {}, "paid": 0, "exempt": []}
            self.t_qa += time.time() - t0
            for f in self.pre["findings"]:
                if f["level"] != "info":
                    print(f"СТОРОЖ ДО РЕНДЕРА [{f['level']}] {f['code']} · {f['slot'] or '-'} · {f['why']}", flush=True)
            print(f"СТОРОЖ ДО РЕНДЕРА: {'чисто' if self.pre['ok'] else 'ЕСТЬ ОШИБКИ'} · оплачиваемых позиций {self.pre['paid']} · исключений ткани {len(self.pre['exempt'])}", flush=True)
        except Exception as e:  # noqa: BLE001
            print("СТОРОЖ ДО РЕНДЕРА: сбой предпроверки —", repr(e), flush=True)
            self.pre = {"ok": None, "findings": [{"level": "error", "code": "QA_CRASH", "slot": "", "why": repr(e)}], "expect": {}, "paid": 0, "exempt": []}

    # ---- реестр «объект Blender → слот»
    def _registry(self, bpy):
        a = self.a
        info = {}
        if getattr(a, "demo_nodes", "") and os.path.exists(a.demo_nodes):
            info = {n["uuid"]: n for n in json.load(open(a.demo_nodes, encoding="utf-8"))}
        expect = self.pre.get("expect", {})
        by_role = {}
        for s in expect:
            if not s.startswith("plant:") and slot_class(s, self.rules) not in ("art", "curtain"):
                by_role.setdefault(s.split("#")[0].split(":")[-1], s)
        rug_slots = [s for s, c in expect.items() if c == "rug"]
        obj_role = {o["file"]: o["role"] for o in self.M.get("objs", [])}
        reg: dict[str, list] = {}
        labels: dict = {}
        for ob in bpy.data.objects:
            if ob.type != "MESH":
                continue
            slot, part = None, ""
            uu = ob.name.split("__")[-1].split(".")[0] if "__" in ob.name else ""
            if uu in info and info[uu].get("slot"):
                slot = info[uu]["slot"]
                if slot_class(slot, self.rules) == "art":
                    has_img = any(n.type == "TEX_IMAGE" and n.image for m in ob.data.materials if m and m.use_nodes for n in m.node_tree.nodes)
                    part = "canvas" if has_img else "frame"
            elif ob.name in obj_role:
                slot = by_role.get(obj_role[ob.name])
            elif ob.name.startswith("rug") and rug_slots:
                slot = rug_slots[0]
            if slot and slot in expect:
                reg.setdefault(slot, []).append(ob)
                labels[ob] = slot + (":" + part if part else "")
        return reg, labels

    # ---- инъекции (проверка самого сторожа)
    def _slot_palettes(self, bpy, np, reg):
        """Слот → палитра цветов его карты (только классы из `anomaly.classes`): картинка в «Base Color», пиксели под прозрачным вырезом (картинка в «Alpha») не берём.
        Читаем копию картинки в Non-Color и уменьшаем до `paletteSide` — те же значения, что кадр (без повторного гамма-пересчёта)."""
        an = self.rules["anomaly"]
        out = {}
        for slot, obs in reg.items():
            if slot_class(slot, self.rules) not in an["classes"]:
                continue
            pals = []
            for ob in obs:
                for m in ob.data.materials:
                    if not (m and m.use_nodes):
                        continue
                    bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
                    if bsdf is None:
                        continue

                    def src(name, bsdf=bsdf):
                        ls = bsdf.inputs[name].links
                        return ls[0].from_node.image if ls and ls[0].from_node.type == "TEX_IMAGE" and ls[0].from_node.image else None

                    def read(img, f=None):
                        """Пиксели картинки (0..1, как записаны) → (массив, шаг уменьшения). Файловую копируем в Non-Color и уменьшаем (`image.scale`); сгенерированную
                        (маска ковра `rugmask`, создана `bpy.data.images.new`) `copy()` отдаёт пустой — её читаем как есть и берём каждый f-й пиксель."""
                        w, h = img.size
                        f = f or max(1, max(w, h) // int(an["paletteSide"]))
                        if img.source == "GENERATED" or not img.filepath:
                            buf = np.empty(w * h * 4, np.float32)
                            img.pixels.foreach_get(buf)
                            return buf.reshape(h, w, 4)[::f, ::f, :3], f
                        c = img.copy()
                        c.colorspace_settings.name = "Non-Color"
                        if f > 1:
                            c.scale(max(1, w // f), max(1, h // f))
                        w2, h2 = c.size
                        buf = np.empty(w2 * h2 * 4, np.float32)
                        c.pixels.foreach_get(buf)
                        bpy.data.images.remove(c)
                        return buf.reshape(h2, w2, 4)[:, :, :3], f
                    ci, ai = src("Base Color"), src("Alpha")
                    if ci is not None:
                        rgb, f = read(ci)
                        msk = np.ones(rgb.shape[:2], bool)
                        if ai is not None and tuple(ai.size) == tuple(ci.size):
                            am, _ = read(ai, f)
                            am = am[:, :, 0] > 0.99
                            if am.shape != msk.shape:                      # шаг и scale округляют по-разному — берём общий угол
                                hh, ww = min(am.shape[0], msk.shape[0]), min(am.shape[1], msk.shape[1])
                                rgb, msk = rgb[:hh, :ww], am[:hh, :ww]
                            else:
                                msk = am
                        pal = texture_palette(np, rgb, msk, an)
                        print(f"СТОРОЖ палитра {slot}: {len(pal)} цветов, непрозрачных пикселей карты {int(msk.sum())} из {msk.size}", flush=True)
                        pals.append(pal)
            if pals:
                out[slot] = np.concatenate(pals)
        return out

    def _art_state(self, bpy, np, reg):
        """Слот картины → {hasMap, content, detail}: есть ли в материале полотна карта с картинкой и есть ли в ней рисунок (опора — `wall_art.has_content`/`metrics`, правила `data/flat3d/wall-art.json`)."""
        expect = self.pre.get("expect", {})
        art = {}
        try:
            sys.path.insert(0, os.path.join(HERE, ".."))
            import wall_art as WA
            R = WA.rules()
        except Exception:  # noqa: BLE001
            WA = None
        for s, c in expect.items():
            if c != "art":
                continue
            imgs = [n.image for ob in reg.get(s, []) for m in ob.data.materials if m and m.use_nodes for n in m.node_tree.nodes if n.type == "TEX_IMAGE" and n.image]
            rec = {"hasMap": bool(imgs), "content": True}
            if imgs and WA is not None:
                im = max(imgs, key=lambda i: i.size[0] * i.size[1])
                w, h = im.size
                pxs = np.empty(w * h * 4, np.float32)
                im.pixels.foreach_get(pxs)
                pxs = pxs.reshape(h, w, 4)[:, :, :3]
                m = WA.canvas_metrics(pxs * 255.0, R)
                rec["content"] = bool(WA.has_content(m, R))
                rec["detail"] = f"цвет {m['chroma']:.0f}, яркость {m['luma']:.0f}, рисунок {(m['ink_d'] >= R['art_content']['ink_delta']).mean() * 100:.1f} % площади"
            art[s] = rec
        return art

    def scene_ready(self, bpy, np):
        """Сцена собрана, кадров ещё нет: инъекции (если заказаны), затем снимок «что реально загружено у картин» (карта в материале, рисунок в ней)."""
        if not self.on:
            return
        reg, _ = self._registry(bpy)
        try:
            self._inject(bpy, np, reg)
            self.art = self._art_state(bpy, np, reg)
        except Exception as e:  # noqa: BLE001
            print("СТОРОЖ сцена: сбой", repr(e), flush=True)

    def _inject(self, bpy, np, reg):
        for spec in self.inject:
            kind, _, target = spec.partition(":")
            try:
                if kind in ("art_nomap", "art_white"):
                    slot = target or next((s for s, c in self.pre["expect"].items() if c == "art"), "")
                    for ob in reg.get(slot, []):
                        for m in ob.data.materials:
                            if not (m and m.use_nodes):
                                continue
                            for n in list(m.node_tree.nodes):
                                if n.type == "TEX_IMAGE" and n.image:
                                    if kind == "art_nomap":
                                        for l in list(m.node_tree.links):
                                            if l.from_node == n:
                                                m.node_tree.links.remove(l)
                                        n.image = None
                                    else:
                                        w, h = n.image.size
                                        n.image.pixels.foreach_set(np.ones(w * h * 4, np.float32))
                                        n.image.update()
                    print(f"СТОРОЖ ИНЪЕКЦИЯ {kind}: {slot}", flush=True)
                elif kind == "rug_shards":
                    n_done = 0
                    for slot in [target] if target else [s for s, c in self.pre["expect"].items() if c == "rug"]:
                        for ob in reg.get(slot, []):
                            for m in ob.data.materials:
                                bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if m and m.use_nodes else None
                                ls = bsdf.inputs["Alpha"].links if bsdf else []
                                if not ls or ls[0].from_node.type != "TEX_IMAGE" or not ls[0].from_node.image:
                                    continue
                                im = ls[0].from_node.image
                                w, h = im.size
                                buf = np.empty(w * h * 4, np.float32)
                                im.pixels.foreach_get(buf)
                                a4 = buf.reshape(h, w, 4)
                                yy, xx = np.mgrid[0:h, 0:w]
                                cell = max(8, w // 28)
                                holes = (((xx // cell) * 73856093) ^ ((yy // cell) * 19349663)) % 100 < 45
                                a4[holes, :3] = 0.0
                                im.pixels.foreach_set(a4.ravel())
                                im.update()
                                n_done += 1
                    print(f"СТОРОЖ ИНЪЕКЦИЯ rug_shards: дыр-клеток в маске ковра ({n_done} карт)", flush=True)
                elif kind == "curtain_remove":
                    for slot in [s for s, c in self.pre["expect"].items() if c == "curtain"]:
                        for ob in reg.get(slot, []):
                            bpy.data.objects.remove(ob, do_unlink=True)
                    print("СТОРОЖ ИНЪЕКЦИЯ curtain_remove", flush=True)
                elif kind == "hide_item":
                    for ob in reg.get(target, []):
                        ob.hide_render = True
                    print(f"СТОРОЖ ИНЪЕКЦИЯ hide_item: {target} ({len(reg.get(target, []))} объектов)", flush=True)
            except Exception as e:  # noqa: BLE001
                print("СТОРОЖ ИНЪЕКЦИЯ сбой", spec, repr(e), flush=True)

    @staticmethod
    def _pose(bpy, cam):
        mw = cam.matrix_world
        return {"pos": tuple(mw.translation), "fwd": tuple(-(mw.to_3x3() @ __import__("mathutils").Vector((0, 0, 1)))), "lens": cam.data.lens,
                "shift": (cam.data.shift_x, cam.data.shift_y), "res": (bpy.context.scene.render.resolution_x, bpy.context.scene.render.resolution_y,
                                                                         bpy.context.scene.render.resolution_percentage), "matrix": [list(r) for r in mw]}

    def camera_ready(self, bpy, cam, name):
        """Сразу после постановки камеры: запомнить, ЧТО поставили; инъекция `camera` — после этого запоминания."""
        if not self.on:
            return
        try:
            self.cams[name] = {"expected": self._pose(bpy, cam)}
            if any(s.split(":")[0] == "camera" for s in self.inject):
                import mathutils
                p = cam.matrix_world.translation.copy()
                rot = mathutils.Matrix.Translation(p) @ mathutils.Matrix.Rotation(math.radians(75), 4, "Z") @ mathutils.Matrix.Translation(-p)
                cam.matrix_world = rot @ cam.matrix_world
                bpy.context.view_layer.update()
                print("СТОРОЖ ИНЪЕКЦИЯ camera: поворот на 75°", flush=True)
        except Exception as e:  # noqa: BLE001
            print("СТОРОЖ камера: сбой", repr(e), flush=True)

    def frame_done(self, bpy, cam, name, out_png):
        if not self.on:
            return
        try:
            self.cams.setdefault(name, {})["actual"] = self._pose(bpy, cam)
            self.frames.append({"cam": name, "out": out_png})
        except Exception as e:  # noqa: BLE001
            print("СТОРОЖ кадр: сбой", repr(e), flush=True)

    # ---- маски и отчёт
    def finish(self, bpy, np):
        if not self.on or not self.frames:
            return
        t0 = self._t_fin0 = time.time()
        try:
            self._finish(bpy, np)
        except Exception as e:  # noqa: BLE001
            import traceback
            print("СТОРОЖ КАДРА: сбой маски —", repr(e), flush=True)
            traceback.print_exc()
            for fr in self.frames:
                self._write(fr, {"verdict": "error", "slots": [], "frame": [{"code": "QA_CRASH", "level": "error", "why": repr(e)}]}, None)
        self.t_qa += time.time() - t0

    def _finish(self, bpy, np):
        import mathutils
        from bpy_extras.object_utils import world_to_camera_view
        sc = bpy.context.scene
        cam = sc.camera
        reg, labels = self._registry(bpy)
        expect = self.pre.get("expect", {})
        # слот → (код цвета); 0 — пусто, 1 — комната; слоты и части картины — с 2
        names = []
        for s in expect:
            names += [s + ":canvas", s + ":frame"] if expect[s] == "art" else [s]
        code = {n: 2 + i for i, n in enumerate(names) if 2 + i < 64}
        art = self.art
        pals = self._slot_palettes(bpy, np, reg) if self.rules.get("anomaly") else {}
        # --- перекраска в плоские цвета слотов
        mats = {}

        def flat(idx):
            if idx in mats:
                return mats[idx]
            r, g, b = (idx >> 4) & 3, (idx >> 2) & 3, idx & 3
            m = bpy.data.materials.new(f"qa_{idx}")
            m.use_nodes = True
            nt = m.node_tree
            for n in list(nt.nodes):
                nt.nodes.remove(n)
            em = nt.nodes.new("ShaderNodeEmission")
            em.inputs["Color"].default_value = (_lin(r / 3), _lin(g / 3), _lin(b / 3), 1.0)
            em.inputs["Strength"].default_value = 1.0
            out = nt.nodes.new("ShaderNodeOutputMaterial")
            nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
            mats[idx] = m
            return m
        for ob in bpy.data.objects:
            if ob.type != "MESH":
                continue
            idx = code.get(labels.get(ob, ""), 1)
            m = flat(idx)
            if not ob.material_slots:
                ob.data.materials.append(m)
            for ms in ob.material_slots:
                ms.link = "OBJECT"
                ms.material = m
        for l in list(bpy.data.lights):
            bpy.data.lights.remove(l)
        wnt = sc.world.node_tree if sc.world and sc.world.use_nodes else None
        if wnt is not None:
            for l in list(wnt.links):
                wnt.links.remove(l)
            for n in wnt.nodes:
                if n.type == "BACKGROUND":
                    n.inputs["Color"].default_value = (0, 0, 0, 1)
                    n.inputs["Strength"].default_value = 0.0
        sc.view_settings.view_transform = "Standard"
        try:
            sc.view_settings.look = "None"
        except TypeError:
            pass
        sc.view_settings.exposure = 0.0
        sc.view_settings.gamma = 1.0
        sc.render.dither_intensity = 0.0
        sc.render.film_transparent = False
        sc.render.image_settings.file_format = "PNG"
        sc.render.image_settings.color_mode = "RGB"
        sc.render.image_settings.color_depth = "8"
        cy = sc.cycles
        cy.samples = 1
        cy.use_adaptive_sampling = False
        cy.use_denoising = False
        try:
            cy.filter_width = 0.01
        except AttributeError:
            pass
        for fr in self.frames:
            cn = fr["cam"]
            rec = self.cams[cn]
            ex, ac = rec["expected"], rec["actual"]
            cam.matrix_world = mathutils.Matrix(ac["matrix"])
            cam.data.lens = ac["lens"]
            cam.data.shift_x, cam.data.shift_y = ac["shift"]
            sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = ac["res"]
            bpy.context.view_layer.update()
            mp = fr["out"] + ".qa-mask.png"
            sc.render.filepath = mp
            bpy.ops.render.render(write_still=True)
            img = bpy.data.images.load(mp, check_existing=False)
            img.colorspace_settings.name = "Non-Color"
            w, h = img.size
            pxs = np.empty(w * h * 4, np.float32)
            img.pixels.foreach_get(pxs)
            arr = np.rint(pxs.reshape(h, w, 4)[:, :, :3] * 3).astype(np.int32)
            lab = (arr[:, :, 0] << 4) | (arr[:, :, 1] << 2) | arr[:, :, 2]
            bpy.data.images.remove(img)
            counts = np.bincount(lab.ravel(), minlength=64)
            px = {n: int(counts[c]) for n, c in code.items()}
            anom = {}
            if pals and os.path.exists(fr["out"]):
                try:
                    fi = bpy.data.images.load(fr["out"], check_existing=False)
                    fi.colorspace_settings.name = "Non-Color"
                    if tuple(fi.size) == (w, h):
                        fb = np.empty(w * h * 4, np.float32)
                        fi.pixels.foreach_get(fb)
                        frame_rgb = fb.reshape(h, w, 4)[:, :, :3]
                        for s_, pal_ in pals.items():
                            if s_ in code and px.get(s_, 0) >= self.rules["minPx"].get(expect.get(s_, ""), 100):
                                anom[s_] = slot_anomaly(np, frame_rgb, lab == code[s_], lab == 1, pal_, self.rules["anomaly"])
                    bpy.data.images.remove(fi)
                except Exception as e:  # noqa: BLE001
                    print("СТОРОЖ осколки: сбой", repr(e), flush=True)
            # геометрия: проекция габаритов слота в кадр
            geo = {}
            for s, obs in reg.items():
                xs, ys, front = [], [], 0
                for ob in obs:
                    for corner in ob.bound_box:
                        co = world_to_camera_view(sc, cam, ob.matrix_world @ mathutils.Vector(corner))
                        if co.z > 0:
                            front += 1
                            xs.append(co.x)
                            ys.append(co.y)
                if not xs:
                    geo[s] = {"inFrame": False, "rect": None, "clipped": 0.0}
                    continue
                mixed = front < 8 * len(obs)
                x0_, x1_, y0_, y1_ = (0.0, 1.0, 0.0, 1.0) if mixed else (min(xs), max(xs), min(ys), max(ys))
                full = max((x1_ - x0_) * (y1_ - y0_), 1e-9)
                cx0, cx1, cy0, cy1 = max(x0_, 0.0), min(x1_, 1.0), max(y0_, 0.0), min(y1_, 1.0)
                inside = cx1 > cx0 and cy1 > cy0
                geo[s] = {"nearCam": bool(front) and front < 8 * len(obs), "behind": 8 * len(obs) - front, "inFrame": bool(inside), "rect": (cx0, cy0, cx1, cy1) if inside else None, "clipped": ((cx1 - cx0) * (cy1 - cy0) / full) if inside else 0.0}
            slot_codes = {s: [code[n] for n in (s + ":canvas", s + ":frame", s) if n in code] for s in expect}

            def cover(rect, slot, lab=lab, h=h, w=w, slot_codes=slot_codes):
                xa, xb = int(rect[0] * w), max(int(rect[2] * w), int(rect[0] * w) + 1)
                ya, yb = int((1.0 - rect[3]) * h), max(int((1.0 - rect[1]) * h), int((1.0 - rect[3]) * h) + 1)
                sub = lab[ya:yb, xa:xb]
                if sub.size == 0:
                    return 0.0
                own = slot_codes.get(slot, [])
                other = (sub >= 2) & ~np.isin(sub, own)
                return float(other.mean())
            posd = math.dist(ex["pos"], ac["pos"])
            dot = max(-1.0, min(1.0, sum(p * q for p, q in zip(ex["fwd"], ac["fwd"]))))
            camrec = {"posErrM": posd, "dirErrDeg": math.degrees(math.acos(dot)), "lensErrFrac": abs(ac["lens"] - ex["lens"]) / max(ex["lens"], 1e-9)}
            present = {s: len(obs) for s, obs in reg.items()}
            ev = evaluate_frame(expect, present, px, geo, cover, self.rules, art, camrec, anom)
            ev["camera"] = {**camrec, "expected": {"pos": ex["pos"], "lens": ex["lens"]}, "actual": {"pos": ac["pos"], "lens": ac["lens"]}}
            ev["maskFile"] = os.path.basename(mp)
            ev["geo"] = {k: {"nearCam": v.get("nearCam", False), "inFrame": v["inFrame"], "clipped": round(v["clipped"], 3), "rect": [round(x, 3) for x in v["rect"]] if v["rect"] else None, "behind": v.get("behind", 0)} for k, v in geo.items()}
            self._write(fr, ev, (w, h))

    def _write(self, fr, ev, size):
        out = fr["out"]
        rep = {
            "version": VERSION,
            "scene": os.path.basename(os.path.abspath(self.a.scene_dir)),
            "variant": self._variant(),
            "camera": fr["cam"],
            "file": os.path.basename(out),
            "sha256": sha256_file(out) if os.path.exists(out) else None,
            "frameSize": size,
            "gate": "off (шаг 5 не включён): отчёт и предупреждение, кадр не блокируется",
            "injected": self.inject,
            "preflight": {"ok": self.pre.get("ok"), "paid": self.pre.get("paid"), "exempt": self.pre.get("exempt"), "findings": self.pre.get("findings")},
            "qaSec": round(self.t_qa + (time.time() - getattr(self, "_t_fin0", time.time())), 1),
            **ev,
        }
        with open(out + ".qa.json", "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)
        bad = [f"{r['slot']} ({r['state']})" for r in ev["slots"] if r["level"] in ("brak", "warn")]
        ind = [r["slot"] for r in ev["slots"] if r["level"] == "indeterminate"]
        bad += [f["code"] for f in ev["frame"]]
        print(f"СТОРОЖ КАДРА {fr['cam']}: {ev['verdict'].upper()} · брак/предупреждения: {'; '.join(bad) or '-'} · неопределимо: {', '.join(ind) or '-'} · {out}.qa.json", flush=True)

    def _variant(self):
        try:
            return json.load(open(os.path.join(self.dump_dir, "scene_info.json"), encoding="utf-8")).get("variant")
        except Exception:  # noqa: BLE001
            return None


# ---------------------------------------------------------------- CLI


def _main(argv=None):
    ap = argparse.ArgumentParser(description="Сторож кадров: предпроверка и сверка хеша")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("preflight", help="оплачиваемые позиции против выгрузки и собранной сцены (до рендера)")
    p.add_argument("--dump", required=True)
    p.add_argument("--export", required=True)
    p.add_argument("--scene-dir", required=True)
    p.add_argument("--strict", action="store_true", help="код выхода 1 при ошибках")
    v = sub.add_parser("verify", help="отчёт сторожа относится к этому файлу кадра?")
    v.add_argument("frame")
    a = ap.parse_args(argv)
    if a.cmd == "preflight":
        r = preflight(a.dump, a.export, a.scene_dir)
        print(json.dumps({k: r[k] for k in ("ok", "paid", "exempt", "findings")}, ensure_ascii=False, indent=1))
        return 1 if (a.strict and not r["ok"]) else 0
    ok, why = verify(a.frame)
    print(("ОК: " if ok else "НЕ ОК: ") + why)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_main())
