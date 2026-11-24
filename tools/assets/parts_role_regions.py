"""Роли по областям слитой части меша → `roles.json` на товар (T-20261124-64, Ш1 плана paint-material-01; вхолостую: в покраску 06/07/08 не подключено).

ЗАЧЕМ. Новая покраска «поверхность → материал → вся поверхность» стоит на частях с ролями. Мост «имя части PartLLM → роль» (`parts_names_roles`) ставит роль целой части, но у корпусной мебели часть «Drawer» —
весь корпус комода (65–76 % площади), безымянный остаток — до 87 %: роли у них нет (решение директора 24.11 по Codex: `to_body`/`unnamed` в мосте ВЫКЛЮЧЕНЫ — body не честная метка слитых фасад+бок+зад).
Главный брак корпусной (советник Fable 24.11, 6 из 11): БОК крашен тоном фасада/ниши. Поэтому роли здесь: top (верх), facade (фасад), side (бок), back (зад), body (всё остальное: низ, внутренности, ниши).

ТОНКИЙ СЛОЙ. Своей геометрии здесь нет — всё готовое берётся вызовом:
  • панели (связные области граней, излом ребра ≤ `panel_deg` = 15°, внутри одной части) — `ref_zone.panel_ids`;
  • оси предмета и стороны граней (лицо/зад/право/лево/верх/низ; «внешняя» плоскость у края габарита — внутренности ящиков и ниши стороной не считаются) — `ref_zone.object_basis` + `ref_zone.face_sides`;
  • ножки и плита СТОЛА, ручки, роли целых частей, признаки частей — мост (`bridge_roles`, `features_for_glb`; R-PART-ROLES-GEOM-03); для стола резка не пишется вообще.
Здесь только: (1) какие части резать — крупные (≥ `part.min_area_share`) без роли у типов `groups` (корпусная); (2) какая из четырёх сторон — ФАСАД: по геометрии (внешняя плоскость с наибольшей площадью + сторона, куда смотрят РУЧКИ — роль handles у частей моста, — доля × `handles.weight`; доля ≥ `handles.decisive` решает сама), камера 04
третьим признаком: добавляет к счёту `camera.bonus·cos` и подтверждает уверенность (нет ни ручек, ни камеры при равных сторонах — ambiguous_side, уверенность ниже порога); зад — сторона напротив фасада, бока — две другие; (3) панель получает роль своей стороны целиком
(голос по площади ≥ `geometry.panel_vote_min`), панель вне внешних сторон — body; (4) вывод `roles.json` (часть → куски → роль, conf, источник, доля площади; сводка) и `roles-faces.npz` (роль/кусок/conf по граням, порядок = parts.npz).
Мерка — доля площади с ролью (conf ≥ `conf.min_known`); цель Ш1 ≥ 0,90. Часть без роли или с низкой уверенностью красится нынешним 06/07 (запасной путь). Что не получило роль — unknown числом, не прячется.
Правила и пороги — `tools/scout/rules/part-role-regions.json` (+ `ref-zone.json` для панелей); ID товаров в код не попадают.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, "..", "scout", "rules", "part-role-regions.json")
TRELLIS = os.path.join(HERE, "..", "scout", "salad", "trellis")
VERSION = 2
SIDE_NAMES = {-1: "front", 0: "back", 1: "right", 2: "left", 3: "top", 4: "bottom", -2: "inner"}


def load_rules(path: str = RULES) -> dict:
    """Правила областей; целостность: роли — из словаря part-roles.json, доли/пороги в допустимых пределах. Нарушение — ValueError."""
    import parts_roles as pro

    with open(path, encoding="utf-8") as fh:
        r = json.load(fh)
    roles = pro.load_rules()["roles"]
    for need in ("top", "facade", "side", "back", "body"):
        if need not in roles:
            raise ValueError(f"part-role-regions.json: роли {need!r} нет в словаре part-roles.json")
    if not (0 < r["part"]["min_area_share"] < 1) or not (0 < r["conf"]["min_known"] <= 1) or not (0 < r["geometry"]["panel_vote_min"] <= 1):
        raise ValueError("part-role-regions.json: доли вне (0, 1]")
    return r


def _ref_zone():
    """Готовые панели/стороны. Модуль лежит в trellis (рядом свои зависимости); импорт лёгкий (numpy + rules/ref-zone.json)."""
    for p in (TRELLIS, os.path.dirname(TRELLIS), os.path.dirname(os.path.dirname(TRELLIS))):
        p = os.path.abspath(p)
        if p not in sys.path:
            sys.path.insert(0, p)
    import ref_zone as rz

    return rz


def _basis(cam_az: float | None):
    """(right, up, fwd) камеры по азимуту (как pose_fit.cam_basis; нет камеры — az 0: оси предмета ref_zone берёт по нормалям граней, а не по камере)."""
    import numpy as np

    a = np.radians(cam_az or 0.0)
    fwd = -np.array([np.sin(a), 0.0, np.cos(a)])
    right = np.array([np.cos(a), 0.0, -np.sin(a)])
    return right, np.cross(right, fwd), fwd


def mesh_sides(vertices, faces, part, cam_az: float | None):
    """Стороны граней и панели через ref_zone → (side[грань], panel[грань], dirs{код стороны: единичный вектор наружу в (x, z)})."""
    import numpy as np

    rz = _ref_zone()
    obj, _delta = rz.object_basis(vertices, faces, _basis(cam_az))
    side = rz.face_sides(vertices, faces, obj)
    pid = rz.panel_ids(vertices, faces, part)
    right, _up, fwd = (np.asarray(b, np.float64) for b in obj)
    dirs = {-1: -fwd, 0: fwd, 1: right, 2: -right}
    return side, pid, {k: np.array([v[0], v[2]]) / max(np.hypot(v[0], v[2]), 1e-12) for k, v in dirs.items()}


def handle_fractions(area, nrm, cen, mid, dirs, idx) -> dict:
    """Куда смотрят ручки: доля площади граней `idx` (части-ручки) по четырём сторонам предмета — по горизонтальной нормали грани (знак — наружу от центра габарита `mid`; верх/низ ручки не в счёт).
    Нормаль, а не положение: ручка у края широкого комода сидит на фасаде, а не на боку. → {код стороны: доля}; нет ручек — {}."""
    import numpy as np

    if len(idx) == 0 or float(area[idx].sum()) <= 0:
        return {}
    n = nrm[idx][:, [0, 2]]
    hz = np.linalg.norm(n, axis=1)
    keep = hz >= 0.5
    if not keep.any():
        return {}
    n = n[keep] / hz[keep][:, None]
    sg = np.sign(((cen[idx][keep][:, [0, 2]] - np.asarray(mid)[[0, 2]]) * n).sum(axis=1))
    n = n * np.where(sg == 0, 1.0, sg)[:, None]
    best = np.argmax(np.stack([n @ dirs[c] for c in (-1, 0, 1, 2)], axis=1), axis=1)
    w = area[idx][keep]
    return {c: float(w[best == k].sum() / w.sum()) for k, c in enumerate((-1, 0, 1, 2))}


def split_part(idx, area, side, pid, dirs, cfg: dict, cam_az: float | None = None, handle_frac: dict | None = None, scope=None, cache: dict | None = None) -> dict:
    """Роли областей ОДНОЙ части (idx — номера её граней) по сторонам и панелям. → {'labels': роль по idx ('top'|'facade'|'side'|'back'|'body'), 'conf': уверенность по idx, 'facade': {...}|None, 'flags': [...]}.
    `scope` — номера граней, по которым решается сторона-фасад (весь корпус товара: у каждой части он один и тот же); нет — только `idx`.
    Фасад — внешняя сторона с наибольшей площадью (+ ручки `handle_frac` × weight, + бонус камеры); зад — напротив; бока — две другие; верх — сторона 3; низ/внутренности/вне внешних сторон — body."""
    import numpy as np

    g, cm, cf = cfg["geometry"], cfg["camera"], cfg["conf"]
    sc_idx = np.asarray(idx if scope is None else scope)
    a, sd, pn = area[sc_idx], side[sc_idx], pid[sc_idx]
    tot = float(a.sum())
    labels = np.full(len(idx), "body", dtype="<U8")
    conf = np.full(len(idx), cf["body"], dtype=np.float64)
    flags: list = []
    out = {"labels": labels, "conf": conf, "facade": None, "flags": flags}
    if tot <= 0:
        return out
    # голос панели (векторно): сторона с наибольшей площадью среди внешних граней панели; панель идёт целиком, если на внешних сторонах ≥ panel_vote_min её площади
    sv_all = None if cache is None else cache.get("sv_all")
    if sv_all is None:
        _u, inv = np.unique(pn, return_inverse=True)
        W = np.bincount(inv * 7 + (sd + 2), weights=a, minlength=len(_u) * 7).reshape(len(_u), 7)      # столбцы: коды сторон −2…4
        totp, outer = W.sum(axis=1), W.sum(axis=1) - W[:, 0]
        best = np.argmax(W[:, 1:], axis=1) - 1                                                          # код стороны с наибольшей внешней площадью
        pick = np.where((outer > 0) & (outer >= g["panel_vote_min"] * totp), best, -2).astype(np.int32)
        sv_all = pick[inv]
        if cache is not None:
            cache["sv_all"] = sv_all
    order = np.argsort(sc_idx, kind="stable")
    sv = sv_all[order[np.searchsorted(sc_idx[order], idx)]]                     # сторона граней самой части (idx ⊂ scope)
    to_cam = np.array([np.sin(np.radians(cam_az)), np.cos(np.radians(cam_az))]) if cam_az is not None else None
    sc, share = {}, {}
    for c in (-1, 0, 1, 2):
        share[c] = float(a[sv_all == c].sum()) / tot
        sc[c] = share[c] + (cm["bonus"] * max(0.0, float(dirs[c] @ to_cam)) if to_cam is not None else 0.0) + (cfg["handles"]["weight"] * handle_frac.get(c, 0.0) if handle_frac else 0.0)
    fc_ = max(sc, key=lambda c: sc[c])
    opp = {-1: 0, 0: -1, 1: 2, 2: 1}[fc_]
    if share[fc_] < g["min_facade_share"]:
        flags.append("facade_too_small")
        fc_ = None
    cam_state, ambiguous, by_handles, fcn, bcn = "none", False, False, cf["facade_no_camera"], cf["back"]
    if fc_ is not None:
        runner = max(sc[c] for c in sc if c != fc_)
        by_handles = bool(handle_frac) and handle_frac.get(fc_, 0.0) >= cfg["handles"]["decisive"]
        ambiguous = runner > 0 and sc[fc_] / runner < g["ambiguous_ratio"] and not by_handles
        if to_cam is not None:
            ang = float(np.degrees(np.arccos(np.clip(dirs[fc_] @ to_cam, -1, 1))))
            cam_state = "agree" if ang <= cm["agree_deg"] else "disagree"
        fcn = {"none": cf["facade_no_camera"], "agree": cf["facade_camera_agree"], "disagree": cf["facade_camera_disagree"]}[cam_state]
        bcn = cf["back_camera_disagree"] if cam_state == "disagree" else cf["back"]
        if by_handles and cam_state != "disagree":
            fcn = max(fcn, cf["facade_handles"])
        if ambiguous and cam_state != "agree":
            fcn, bcn = max(0.0, fcn - cf["ambiguous_penalty"]), max(0.0, bcn - cf["ambiguous_penalty"])
            flags.append("ambiguous_side")
        if cam_state == "disagree":
            flags.append("camera_disagrees")
    for c in (-1, 0, 1, 2):
        m = sv == c
        if not m.any():
            continue
        if fc_ is None:                                     # фасада нет → перёд/зад честно не размечаем (body), бока — по геометрии
            labels[m], conf[m] = ("side", cf["side"]) if c in (1, 2) else ("body", cf["body"])
        elif c == fc_:
            labels[m], conf[m] = "facade", fcn
        elif c == opp:
            labels[m], conf[m] = "back", bcn
        else:
            labels[m], conf[m] = "side", cf["side"]
    mt = sv == 3
    if mt.any():
        labels[mt], conf[mt] = "top", cf["top"]
    if fc_ is not None:
        out["facade"] = {"side": SIDE_NAMES[fc_], "area_share_of_scope": round(share[fc_], 4), "camera": cam_state, "ambiguous": bool(ambiguous), "by_handles": by_handles,
                         "sides": {SIDE_NAMES[c]: round(share[c], 4) for c in (-1, 0, 1, 2)}}
    return out


def load_mesh(glb: str):
    """Вершины/грани всех геометрий GLB подряд — порядок граней как у parts.npz этапа 3."""
    import numpy as np
    import trimesh

    sc = trimesh.load(glb, process=False)
    geoms = list(sc.geometry.values()) if hasattr(sc, "geometry") else [sc]
    verts, faces, off = [], [], 0
    for g in geoms:
        verts.append(np.asarray(g.vertices, dtype=np.float64))
        faces.append(np.asarray(g.faces, dtype=np.int64) + off)
        off += len(g.vertices)
    return np.concatenate(verts), np.concatenate(faces)


def _cut_part(r: dict, f: dict, pr: dict) -> bool:
    """Режем ли часть: слитая крупная без роли; плоская панель от panel_min_area_share без роли; общая роль body моста у плоской панели (refine_bridge_body)."""
    plate = max(f.get("plate_horizontal") or 0.0, f.get("plate_vertical") or 0.0)
    panel = plate >= pr["panel_min_plate"]
    if r["role"] == "unknown":
        if r.get("unknown_reason") not in pr["unknown_reasons"]:
            return False
        return f["area_share"] >= pr["min_area_share"] or (panel and f["area_share"] >= pr["panel_min_area_share"])
    return bool(pr.get("refine_bridge_body")) and r["role"] == "body" and panel and f["area_share"] >= pr["panel_min_area_share"]


def _face_normals(vertices, faces):
    import numpy as np

    t = vertices[faces]
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)


def _face_centers(vertices, faces):
    return vertices[faces].mean(axis=1)


def _face_areas(vertices, faces):
    import numpy as np

    t = vertices[faces]
    return np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1) / 2


def build_roles(vertices, faces, part, names: list, product_role: str | None, channels: set | None = None, channel_classes: dict | None = None,
                cam_az: float | None = None, bridge_rules: dict | None = None, region_rules: dict | None = None, feats: dict | None = None, glb: str | None = None) -> dict:
    """Один товар: роли частей моста + резка крупных безродных частей корпусной по панелям/сторонам → {'doc': roles.json-словарь, 'face_role', 'face_piece', 'face_conf': массивы по граням}.
    `feats` — признаки частей моста; нет — берутся `parts_names_roles.features_for_glb(glb, part, cam_az)` (нужен `glb`; тяжело: десятки секунд на 0,5 млн граней)."""
    import numpy as np
    import parts_names_roles as pn
    import parts_roles as pro

    rr = region_rules or load_rules()
    pr = pro.load_rules()
    br = bridge_rules or pn.load_rules()
    part = np.asarray(part, dtype=np.int64)
    if len(part) != len(faces):
        raise ValueError(f"граней {len(faces)}, меток частей {len(part)}")
    if feats is None:
        if not glb:
            raise ValueError("нужны признаки частей `feats` или путь `glb`")
        feats = pn.features_for_glb(glb, part, cam_az)
    grp = pro.group_of(product_role)
    nm = {int(i): (names[i] if 0 <= i < len(names) else "") for i in feats}
    roles = pn.bridge_roles(nm, feats, br, pr, product_role, channels, channel_classes)
    area = _face_areas(vertices, faces)
    tot = float(area.sum())
    can_split = bool(rr.get("enabled")) and grp in rr["groups"]
    side = pid = dirs = scope = None
    cache: dict = {}
    face_role = np.full(len(faces), "unknown", dtype="<U10")
    face_piece = np.full(len(faces), -1, dtype=np.int32)
    face_conf = np.zeros(len(faces), dtype=np.float32)
    parts_out, piece = [], 0
    for p in sorted(feats, key=lambda k: -feats[k]["area_share"]):
        f, r = feats[p], roles[p]
        idx = np.nonzero(part == p)[0]
        ent = {"part": int(p), "name": nm.get(p, ""), "area_share": round(float(area[idx].sum() / tot), 4) if tot else 0.0, "bridge_role": r["role"], "bridge_unknown_reason": r.get("unknown_reason"), "pieces": []}
        cut = can_split and _cut_part(r, f, rr["part"])
        if r["role"] != "unknown" and not cut:
            face_role[idx], face_piece[idx], face_conf[idx] = r["role"], piece, r.get("role_conf") or 0.0
            ent.update(role=r["role"], conf=r.get("role_conf"), source="bridge")
            ent["pieces"].append({"piece": piece, "role": r["role"], "conf": r.get("role_conf"), "area_share": ent["area_share"]})
            piece += 1
        elif cut:
            if side is None:
                side, pid, dirs = mesh_sides(vertices, faces, part, cam_az)
            hidx = np.nonzero(np.isin(part, [q for q in roles if roles[q]["role"] == "handles"]))[0]
            hf = handle_fractions(area, _face_normals(vertices, faces), _face_centers(vertices, faces), 0.5 * (vertices.min(0) + vertices.max(0)), dirs, hidx)
            if scope is None:
                scope = np.nonzero(~np.isin(part, [q for q in roles if roles[q]["role"] in ("legs", "handles", "frame")]))[0]
            sp = split_part(idx, area, side, pid, dirs, rr, cam_az, hf, scope, cache)
            ent.update(role=None, conf=None, source="region", facade=sp["facade"], region_flags=sp["flags"])
            for role in ("top", "facade", "side", "back", "body"):
                m = sp["labels"] == role
                if not m.any():
                    continue
                fi = idx[m]
                cv = float(np.median(sp["conf"][m]))
                face_role[fi], face_piece[fi], face_conf[fi] = role, piece, cv
                ent["pieces"].append({"piece": piece, "role": role, "conf": round(cv, 3), "area_share": round(float(area[fi].sum() / tot), 4)})
                piece += 1
        else:
            face_piece[idx] = piece
            ent.update(role="unknown", conf=r.get("role_conf"), source="unknown")
            ent["pieces"].append({"piece": piece, "role": "unknown", "conf": r.get("role_conf"), "area_share": ent["area_share"]})
            piece += 1
        parts_out.append(ent)
    mk = rr["conf"]["min_known"]
    known = (face_role != "unknown") & (face_conf >= mk)
    by_role, by_src, unk = {}, {}, {}
    for e in parts_out:
        for pc in e["pieces"]:
            by_role[pc["role"]] = round(by_role.get(pc["role"], 0.0) + pc["area_share"], 4)
            src = e["source"] if pc["role"] != "unknown" else "unknown"
            by_src[src] = round(by_src.get(src, 0.0) + pc["area_share"], 4)
        if e["source"] == "unknown":
            d = unk.setdefault(e.get("bridge_unknown_reason") or "?", {"parts": 0, "area": 0.0})
            d["parts"] += 1
            d["area"] = round(d["area"] + e["area_share"], 4)
    share = float(area[known].sum() / tot) if tot else 0.0
    summary = {"area_with_role": round(share, 4), "ok": share >= rr["metric"]["min"], "threshold": rr["metric"]["min"], "area_by_role": by_role, "area_by_source": by_src,
               "area_unknown": round(1.0 - share, 4), "unknown_by_reason": unk}
    if grp == "table":
        summary["table"] = {"top": by_role.get("top", 0.0) > 0, "legs": by_role.get("legs", 0.0) > 0, "separate": by_role.get("top", 0.0) > 0 and by_role.get("legs", 0.0) > 0}
    doc = {"version": VERSION, "mode": "dry", "group": grp, "product_role": product_role, "camera": cam_az is not None, "n_faces": int(len(faces)), "parts": parts_out, "summary": summary,
           "fallback": "часть без роли или с conf ниже conf.min_known красится нынешним 06/07"}
    return {"doc": doc, "face_role": face_role, "face_piece": face_piece, "face_conf": face_conf}


def write_roles(res: dict, out_dir: str) -> None:
    """`roles.json` + `roles-faces.npz` (роль строкой, кусок, conf по граням) в out_dir."""
    import numpy as np

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "roles.json"), "w", encoding="utf-8") as fh:
        json.dump(res["doc"], fh, ensure_ascii=False, indent=1, default=float)
    np.savez_compressed(os.path.join(out_dir, "roles-faces.npz"), role=res["face_role"], piece=res["face_piece"], conf=res["face_conf"])


def main(argv: list | None = None) -> int:
    """python parts_role_regions.py <glb> <03-parts> <out_dir> [--product-role R] [--channels a,b] [--channel-classes k=v,..] [--cam-az N]: роли товара → out_dir/roles.json + roles-faces.npz."""
    import argparse

    import numpy as np

    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("glb")
    ap.add_argument("parts_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--product-role", default="")
    ap.add_argument("--channels", default="")
    ap.add_argument("--channel-classes", default="")
    ap.add_argument("--cam-az", type=float, default=None)
    a = ap.parse_args(argv)
    with open(os.path.join(a.parts_dir, "parts.json"), encoding="utf-8") as fh:
        doc = json.load(fh)
    part = np.load(os.path.join(a.parts_dir, "parts.npz"))["part"]
    names = [""] * (max(p["id"] for p in doc["parts"]) + 1)
    for p in doc["parts"]:
        names[p["id"]] = p["name"]
    v, f = load_mesh(a.glb)
    cc = dict(kv.split("=", 1) for kv in a.channel_classes.split(",") if "=" in kv and not kv.startswith("main="))
    res = build_roles(v, f, part, names, a.product_role or None, set(filter(None, a.channels.split(","))), cc, a.cam_az, glb=a.glb)
    write_roles(res, a.out_dir)
    s = res["doc"]["summary"]
    print(f"роли: с ролью {s['area_with_role']:.1%}, по ролям {s['area_by_role']}, без роли {s['area_unknown']:.1%} → {a.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
