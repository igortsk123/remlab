"""Мост «название части PartLLM → роль» (этап 03, T-20261123-17/2; план ~/remlab-logs/t217-1123/plan.md).

ЗАЧЕМ. PartLLM называет части («Leg», «Drawer», «Seat Cushion»), но роли (ножки, ручки, фасад, верх, плафон, корпус) не ставит — 07 и 08 без `role`/`material_channel` идут
«по форме» и каналы каталога не применяют. SAM-ветка этапа 3 роли ставит по геометрии (`parts_roles.assign_roles`); здесь — тот же словарь ролей и те же числа, но кандидата даёт ИМЯ.

ПРАВИЛО (таблица — `tools/scout/rules/part-llm-roles.json`, код её только исполняет; ID товаров в код не попадают):
  ① имя → кандидат роли; имени нет / «Other» / название целого — `unknown` с причиной (`no_name`, `not_a_part`);
  ② кандидат с геометрическим условием (legs, frame, handles, facade, top, shade) ставится, только если часть проходит `require` этой роли в группе товара
     (`parts_roles.role_fit` — те же `require`/`alt_require`/`forbid`/`only_if_catalog_channel`); не прошла — `else`-роль из таблицы (если проходит её), иначе `unknown:name_geometry`;
     причина геометрии (`no_front` — камеры нет, `no_contact` — нет опоры, `forbid`…) — в поле `geometry_why`; канала роли у товара в каталоге нет — `unknown:no_channel`;
  ③ `body` по имени — без геометрического условия, но не у типа без канала (`no_body_for_types`) и не у стола (`body_scope: none`: столешница и ножки названы отдельно) — там `no_channel`/`body_scope`;
  ④ `agree`/`seen` у PartLLM нет (None) — воздержание по доверию не включается (решение директора П-3; сперва dry).
  ⑤ «Геометрический запас» (T-20261124-03, блок `geometry_fallback` в таблице; выключатель `enabled`), чтобы крупная часть не оставалась «без роли»:
     а) фасад/верх по имени, геометрия не подтвердила (самая крупная часть = фасад слит с корпусом; «ящик» с дном) — канал каталога тот же (main), что у корпуса → `body`;
     б) общее имя («Base», «Horizontal Panel») у типа без `body` (стол) → столешница/ножки по геометрии, если подходит ровно одна роль;
     в) имени нет вовсе (строка `""` с `geometry_fallback: unnamed`) → роль по геометрии, иначе объёмная часть = `body`.
     Ножки/каркас/ручки/плафон, не подтверждённые геометрией, по-прежнему `unknown:name_geometry` (другой канал — подставлять корпус нельзя).
  ⑥ `name_relax` (T-20261124-64): имя назвало роль (legs), строгая геометрия группы не прошла, но часть стоит на полу и тонкая — ослабленная геометрия (`parts_roles.role_fit_relaxed`: те же условия группы без «касается тела» и потолка
     up_q90 ≤ 0,4, свой потолок 0,6) → роль с пометкой `relaxed`; только группы из таблицы (seating). Выключатель `enabled`.
  ⑦ `no_rule_other_channel` (T-20261124-64): имя назвало роль другого канала (не main), у группы товара правила этой роли нет (рама лампы: у lamp только shade) → unknown:no_channel, а не name_geometry (геометрию не проверяли
     — проверять нечего). Роли основного канала (top/facade) не затрагивает. Меняет причину и знаменатель мерки, не роль и не покраску.
Режим — `mode` в таблице: `off` | `dry` (по умолчанию; роли только в отчёт) | `on` (поля пишутся в parts.json). Мерка — `parts_roles.known_role_area_share` ≥ `metric.min`,
знаменатель без частей `unknown:no_channel` (у типа канала нет — не провал, отдельная строка; П-2).
"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, "..", "scout", "rules", "part-llm-roles.json")
SAM_RULES = os.path.join(HERE, "..", "..", "data", "flat3d", "parts-sam-rules.json")
MODES = ("off", "dry", "on")
FIELDS = ("role", "role_title", "material_channel", "role_conf", "role_why", "unknown_reason")


def load_rules(path: str = RULES) -> dict:
    """Таблица названий; проверка целостности: режим из `MODES`, каждая роль — из словаря part-roles.json, у `unknown` есть причина, `else` — роль словаря. Нарушение — ValueError."""
    import parts_roles as pro

    with open(path, encoding="utf-8") as fh:
        t = json.load(fh)
    if t.get("mode", "dry") not in MODES:
        raise ValueError(f"part-llm-roles.json: mode={t.get('mode')!r}, ожидалось одно из {MODES}")
    roles = pro.load_rules()["roles"]
    for name, e in t["map"].items():
        for k in ("role", "else"):
            if k in e and e[k] not in roles:
                raise ValueError(f"part-llm-roles.json: «{name}» → {k}={e[k]!r} нет в словаре ролей part-roles.json")
        if e["role"] == "unknown" and not e.get("reason"):
            raise ValueError(f"part-llm-roles.json: «{name}» → unknown без причины (reason)")
        if e.get("geometry_fallback") not in (None, "unnamed"):
            raise ValueError(f"part-llm-roles.json: «{name}» → geometry_fallback={e['geometry_fallback']!r}, ожидалось unnamed")
    gf = t.get("geometry_fallback") or {}
    for blk in ("generic_in_no_body_types", "unnamed"):
        for r in (gf.get(blk) or {}).get("roles_order", []):
            if r not in roles:
                raise ValueError(f"part-llm-roles.json: geometry_fallback.{blk}.roles_order: роли {r!r} нет в словаре ролей part-roles.json")
    nr = t.get("name_relax") or {}
    for role, cfg in nr.items():
        if role in ("enabled",) or role.startswith("_"):
            continue
        if role not in roles:
            raise ValueError(f"part-llm-roles.json: name_relax: роли {role!r} нет в словаре ролей part-roles.json")
        for g in cfg.get("groups", []):
            if g not in pro.load_rules()["groups"]:
                raise ValueError(f"part-llm-roles.json: name_relax.{role}: группы {g!r} нет в part-roles.json")
    return t


def mode(rules: dict | None = None) -> str:
    return (rules or load_rules()).get("mode", "dry")


def _entry(rules: dict, name: str) -> dict | None:
    """Строка таблицы по имени (пробелы по краям не в счёт); пустое имя — строка `""`; нет строки — None."""
    return rules["map"].get((name or "").strip())


def _done(rr: dict, role: str, why: str, conf: float, reason: str | None = None, grp: dict | None = None) -> dict:
    """Запись роли. Канал материала — через `parts_roles.role_channel` (канал роли в группе товара, иначе глобальный): у стола frame красится каналом ножек (T-20261124-03/2)."""
    import parts_roles as pro
    rd = rr["roles"][role]
    return {"role": role, "role_title": rd["titleRu"], "material_channel": pro.role_channel(rr, grp, role), "role_conf": conf, "role_why": why, "unknown_reason": reason}


def _geometry_roles(f: dict, role_rules: dict, product_role: str | None, channels: set[str] | None, order: list[str], catalog_classes: dict[str, str] | None) -> list[str]:
    """Роли из `order`, под которые часть подходит ТОЛЬКО по геометрии группы товара (`parts_roles.role_fit`: те же require/alt_require/forbid, что у SAM-ветки)."""
    import parts_roles as pro

    return [r for r in order if pro.role_fit(f, role_rules, product_role, channels, r, catalog_classes=catalog_classes)[0]]


def _body_allowed(grp: dict, product_role: str | None) -> bool:
    """Можно ли тут поставить `body`: тип не без канала (`no_body_for_types`) и не тип, где материал столешницы/ножек назван отдельно (`body_scope: none`)."""
    return product_role not in grp.get("no_body_for_types", []) and grp.get("body_scope", "all") != "none"


def bridge_roles(names: dict[int, str], feats: dict[int, dict], rules: dict, role_rules: dict, product_role: str | None, channels: set[str] | None = None,
                 catalog_classes: dict[str, str] | None = None) -> dict[int, dict]:
    """{id части: {role, role_title, material_channel, role_conf, role_why, unknown_reason, name}} — по имени (кандидат) и геометрии (`feats` из `parts_features.part_features`).
    `rules` — part-llm-roles.json, `role_rules` — part-roles.json. Названия вне таблицы — `unknown:name_unknown` (не молчком)."""
    import parts_roles as pro

    g = pro.group_of(product_role)
    grp = role_rules["groups"][g]
    rc = role_rules["decision"]["role_conf"]
    ab = role_rules["decision"]["abstain"]
    out: dict[int, dict] = {}
    facades = set()                                                                # как у assign_roles: правила с touches_facade (ручка) видят уже подтверждённые фасады
    for p, f in feats.items():
        e = _entry(rules, names.get(p, ""))
        if e and e["role"] == "facade" and pro.role_fit(f, role_rules, product_role, channels, "facade", catalog_classes=catalog_classes)[0]:
            facades.add(p)
    feats = {p: {**f, "touches_facade": any(q in facades for q in f.get("contacts", []))} for p, f in feats.items()}
    for p, f in feats.items():
        name = names.get(p, "")
        e = _entry(rules, name)
        if e is None:
            out[p] = {**_done(role_rules, "unknown", f"название «{name}» не в таблице part-llm-roles.json", rc["unknown"], "name_unknown"), "name": name}
            continue
        role, reason = e["role"], e.get("reason")
        gf = rules.get("geometry_fallback") or {}
        gf_on = bool(gf.get("enabled"))
        tiny = f["area_share"] < ab["tiny_area_share"]
        if role == "unknown":
            un = gf.get("unnamed") or {}
            if gf_on and un.get("enabled") and e.get("geometry_fallback") == "unnamed" and not tiny and f["area_share"] >= float(un.get("min_area_share", 0)):
                fits = _geometry_roles(f, role_rules, product_role, channels, un.get("roles_order", []), catalog_classes)           # имени нет: роль решает геометрия части
                if len(fits) == 1:
                    out[p] = {**_done(role_rules, fits[0], f"имени нет → роль по геометрии: {fits[0]} (условия роли выполнены)", rc["matched"], grp=grp), "name": name}
                    continue
                if len(fits) > 1:
                    out[p] = {**_done(role_rules, "unknown", f"имени нет, геометрии подходят роли {fits}", rc["unknown"], "ambiguous"), "name": name}
                    continue
                if un.get("body") and _body_allowed(grp, product_role):                                                             # объёмная часть, ни под какую иную роль не подошла → корпус (запасная роль)
                    out[p] = {**_done(role_rules, "body", "имени нет, иная роль геометрией не подтверждена → корпус (объёмная часть)", rc["body"]), "name": name}
                    continue
            out[p] = {**_done(role_rules, "unknown", e.get("why") or f"название «{name}» → без роли ({reason})", rc["unknown"], reason or rules["defaults"]["no_name_reason"]), "name": name}
            continue
        if tiny:
            out[p] = {**_done(role_rules, "unknown", f"площадь {f['area_share']:.4f} меньше {ab['tiny_area_share']}", rc["unknown"], "tiny"), "name": name}
            continue
        if role == "body":
            if product_role in grp.get("no_body_for_types", []):
                out[p] = {**_done(role_rules, "unknown", f"тип «{product_role}»: канала материала для частей нет", rc["unknown"], "no_channel"), "name": name}
            elif grp.get("body_scope", "all") == "none":
                gen = gf.get("generic_in_no_body_types") or {}
                fits = _geometry_roles(f, role_rules, product_role, channels, gen.get("roles_order", []), catalog_classes) if gf_on and gen.get("enabled") else []
                if len(fits) == 1:                                                                                                  # у стола «Base»/«Horizontal Panel»: корпуса нет, роль — столешница или ножки по форме
                    out[p] = {**_done(role_rules, fits[0], f"название «{name}» (общее) → роль по геометрии: {fits[0]} (условия роли выполнены)", rc["matched"], grp=grp), "name": name}
                else:
                    out[p] = {**_done(role_rules, "unknown", "тип, где материал столешницы/ножек назван отдельно: body не ставим" + (f"; геометрии подходят роли {fits}" if fits else ""),
                                      rc["unknown"], "body_scope"), "name": name}
            else:
                out[p] = {**_done(role_rules, "body", f"название «{name}» → корпус/обивка (без геометрического условия)", rc["body"]), "name": name}
            continue
        ok, why = pro.role_fit(f, role_rules, product_role, channels, role, catalog_classes=catalog_classes)
        picked = role if ok else None
        relaxed = False
        nr = (rules.get("name_relax") or {}).get(role) if (rules.get("name_relax") or {}).get("enabled") else None
        if not ok and nr and why not in ("no_channel", "no_rule") and pro.role_fit_relaxed(f, role_rules, product_role, channels, role, nr, catalog_classes=catalog_classes)[0]:
            picked, relaxed = role, True                                                   # имя «Leg» + стоит на полу + тонкая: коническая ножка стула проходит ослабленную геометрию (name_relax)
        if not picked and e.get("else"):
            ok2, _ = pro.role_fit(f, role_rules, product_role, channels, e["else"], catalog_classes=catalog_classes)
            picked = e["else"] if ok2 else None
        if picked:
            out[p] = {**_done(role_rules, picked, f"название «{name}» → {role}" + ("" if picked == role else f", геометрия — {picked}")
                              + ("; строгая геометрия не прошла, ослабленная (name_relax: на полу, тонкая) — да" if relaxed else "; условия роли выполнены"), rc["matched"], grp=grp), "name": name}
            if relaxed:
                out[p]["relaxed"] = True
        elif why == "no_channel":                                                  # у товара нет такого канала в каталоге (плафон без «shade»): не провал геометрии
            out[p] = {**_done(role_rules, "unknown", f"название «{name}» → {role}, но канала «{role}» у товара в каталоге нет", rc["unknown"], "no_channel"), "name": name}
        elif (why == "no_rule" and (rules.get("no_rule_other_channel") or {}).get("enabled")
              and pro.role_channel(role_rules, grp, role) != pro.role_channel(role_rules, grp, "body")):
            # у группы правила роли НЕТ, и канал роли — не корпусной (ножки/каркас/ручки/плафон): типу такой канал не положен (рама лампы) — это не «геометрия не подтвердила»
            out[p] = {**_done(role_rules, "unknown", f"название «{name}» → {role}, но у типа «{product_role}» такого канала материала нет (у группы нет правила роли)", rc["unknown"], "no_channel"), "name": name,
                      "geometry_why": why}
        elif (gf_on and (gf.get("to_body") or {}).get("enabled") and _body_allowed(grp, product_role)
              and pro.role_channel(role_rules, grp, role) == pro.role_channel(role_rules, grp, "body")):
            # фасад/верх по имени, геометрия не подтвердила (самая крупная часть, фасад слит с корпусом, «ящик» с дном): канал каталога тот же, что у корпуса, — корпус, а не «нет роли»
            out[p] = {**_done(role_rules, "body", f"название «{name}» → {role}, геометрия не подтвердила ({why or 'условия роли не выполнены'}); канал каталога тот же (main) → корпус", rc["body"]), "name": name,
                      "geometry_why": why}
        else:                                                                    # геометрия не подтвердила имя; почему именно (no_front, no_contact, forbid…) — в geometry_why
            out[p] = {**_done(role_rules, "unknown", f"название «{name}» → {role}, геометрия не подтверждена ({why or 'условия роли не выполнены'})", rc["unknown"],
                              rules["defaults"]["geometry_reason"]), "name": name, "geometry_why": why}
    return out


def summarize(feats: dict[int, dict], roles: dict[int, dict], rules: dict) -> dict:
    """Мерка и разбор: доля площади с ролью (весь знаменатель и без `exclude_unknown_reasons`), число частей/площадь по причинам воздержания, по ролям. Порог — `metric.min`."""
    import parts_roles as pro

    m = rules["metric"]
    ex = set(m.get("exclude_unknown_reasons", []))
    keep = {p: f for p, f in feats.items() if roles[p]["unknown_reason"] not in ex}
    tot_all = sum(f["area_share"] for f in feats.values())
    share_all = pro.known_role_area_share(feats, roles)
    share = pro.known_role_area_share(keep, {p: roles[p] for p in keep})
    reasons: dict = {}
    by_role: dict = {}
    for p, r in roles.items():
        a = feats[p]["area_share"]
        by_role[r["role"]] = round(by_role.get(r["role"], 0.0) + a, 4)
        if r["role"] == "unknown":
            d = reasons.setdefault(r["unknown_reason"], {"parts": 0, "area": 0.0})
            d["parts"] += 1
            d["area"] = round(d["area"] + a, 4)
    no_ch = sum(f["area_share"] for p, f in feats.items() if roles[p]["unknown_reason"] in ex)
    return {"known_role_area_share": share, "known_role_area_share_all_parts": share_all, "threshold": m["min"], "ok": share >= m["min"],
            "no_channel_area_share": round(no_ch / tot_all, 4) if tot_all else 0.0, "unknown_reasons": reasons, "area_by_role": by_role}


def features_for_glb(glb: str, part: "np.ndarray", cam_az: float | None = None, sam_rules_path: str = SAM_RULES) -> dict[int, dict]:
    """Признаки частей по ТОЙ ЖЕ склейке геометрий GLB, что даёт порядок граней `part` (parts.npz этапа 3): вершины/грани всех геометрий подряд, форма — `part_shapes`, соседство — `weld_adjacency`.
    agree/seen — None (у PartLLM их нет)."""
    import numpy as np
    import trimesh
    import part_shapes as shp  # noqa: F401
    import parts_features as pfe
    import parts_refine as pr
    import parts_roles as pro
    import parts_vote as pv

    sc = trimesh.load(glb, process=False)
    geoms = list(sc.geometry.values()) if hasattr(sc, "geometry") else [sc]
    verts, faces, off = [], [], 0
    for g in geoms:
        verts.append(np.asarray(g.vertices, dtype=np.float64))
        faces.append(np.asarray(g.faces, dtype=np.int64) + off)
        off += len(g.vertices)
    vertices, fcs = np.concatenate(verts), np.concatenate(faces)
    if len(fcs) != len(part):
        raise ValueError(f"граней в GLB {len(fcs)}, меток частей {len(part)}")
    with open(sam_rules_path, encoding="utf-8") as fh:
        srules = json.load(fh)
    kind_f, _, _ = pr.shp.face_shapes(vertices, fcs, pr.shape_cfg(srules))
    adj = pv.weld_adjacency(vertices, fcs)
    part = np.asarray(part, dtype=np.int64)
    return pfe.part_features(part, vertices, fcs, kind_f, pr.part_kinds(part, kind_f), lab=None, cam_az=cam_az, adj=adj, agree=None, seen=None, **pro.load_rules()["features_params"])


def run_glb(glb: str, part: "np.ndarray", names: list[str], product_role: str | None, channels: set[str] | None = None, channel_classes: dict[str, str] | None = None,
            cam_az: float | None = None, rules: dict | None = None) -> dict:
    """Один товар целиком: признаки → роли по именам → мерка. → {mode, roles: {id: {...}}, summary, group, product_role, channels, camera}. Ошибка расчёта — {error}: части остаются."""
    import parts_roles as pro

    rules = rules or load_rules()
    try:
        feats = features_for_glb(glb, part, cam_az)
        rr = pro.load_rules()
        roles = bridge_roles({i: (names[i] if 0 <= i < len(names) else "") for i in feats}, feats, rules, rr, product_role, channels, channel_classes)
        return {"mode": mode(rules), "group": pro.group_of(product_role), "product_role": product_role, "channels": sorted(channels or []), "camera": cam_az is not None,
                "summary": summarize(feats, roles, rules), "roles": {str(p): r for p, r in roles.items()}}
    except Exception as e:  # noqa: BLE001 — роли не посчитались: части остаются, причина в отчёте
        return {"mode": mode(rules), "error": f"{type(e).__name__}: {str(e)[:200]}"}
