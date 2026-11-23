"""Роль части меша = канал материала каталога (этап 3, шаг «роль», T-20261120-169/3).

ЗАЧЕМ. Этап 8 красит каждую часть по классу каталога; ему нужно знать, какая часть — ножки, ручки, плафон, видимый каркас, а какая — «всё остальное» (body: корпус, обивка, подушки, спинка).
Роль решают правила `tools/scout/rules/part-roles.json` (код только исполняет, ID товаров в код не попадают). Решение — не «ранг и запас», а:
  ① жёстко: роль ставится, если выполнены ВСЕ `require` и ни один `forbid`; роль с `only_if_catalog_channel` — только если такой канал есть у товара в каталоге;
  ② воздержание (`unknown` + причина): мелкая часть (tiny), недоверие этапа 3 (agree/seen — роль не может быть увереннее разбиения), две подходящие роли (ambiguous),
     нет фронта у роли с фронтом (no_front), нет контакта/опоры (no_contact), нет подходящего правила (no_rule), у типа нет канала (no_channel), тип неизвестен (группа `any`);
  ③ body — запасная: объёмная (kind body) часть, не подошедшая под иную роль и прошедшая доверие; у корпусной мебели — только крупнейшая, у стола body нет вовсе (столешница и ножки названы отдельно);
     тонкая/средняя без правила остаётся unknown;
  ③б объёмная часть, что стоит на полу и держит главную (цоколь, нижний модуль), но под ножки не подошла и по цвету заметно иная (ΔE ≥ порога) — unknown:support_unclear; ΔE здесь только ВЕТО (снимает роль, роль не ставит);
  ③в глобальная согласованность: части одной группы повторов (одинаковые размеры рамки и высота; либо один нижний слой — оба объёмные у пола, та же толщина) получают ОДНУ роль, расходятся — вся группа unknown:group_disagree;
  ③г ножка по геометрии при размытом голосовании (`leg_rescue`): unknown:unreliable → legs, если у предмета уже есть доверенные ножки, часть проходит все условия legs и стоит отвесно на полу;
  ④ glass_mirror геометрия не ставит никогда; ΔE в роль не входит.
Тип товара — `role` каталога → группа в `data/flat3d/material-classes.json` (тот же источник, что у этапа 8); каналы — ключи `parts` результата `material_class.classify`.
"""
from __future__ import annotations

import math
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, "..", "scout", "rules", "part-roles.json")
CLASSES = os.path.join(HERE, "..", "..", "data", "flat3d", "material-classes.json")
_FRONT_KEYS = {"front", "right", "front_facing_share"}
_CONTACT_KEYS = {"supports_body", "contacts_main", "touches_facade"}


def load_rules(path: str = RULES) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def group_of(product_role: str | None, classes: dict | None = None) -> str:
    """Группа правил по типу товара каталога (seating, bed, case, table, lamp, decor); тип неизвестен — `any`."""
    if classes is None:
        with open(CLASSES, encoding="utf-8") as fh:
            classes = json.load(fh)
    if not product_role:
        return "any"
    for g, v in classes["groups"].items():
        if product_role in v["roles"]:
            return g
    words = set(product_role.lower().split())                      # «журнальный стол» → слово «стол» есть в ролях группы table; ровно одна группа — берём её, иначе any
    hit = {g for g, v in classes["groups"].items() if any(words & set(r.lower().split()) for r in v["roles"])}
    return hit.pop() if len(hit) == 1 else "any"


def _get(f: dict, key: str):
    cur = f
    for k in key.split("."):
        cur = cur.get(k) if isinstance(cur, dict) else None
        if cur is None:
            return None
    return cur


def _cmp(a, op: str, b) -> bool:
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    if a is None:
        return False                                                               # нет данных — условие не выполнено
    if op == "in":
        return isinstance(b, list) and a in b
    return {"<=": lambda: a <= b, ">=": lambda: a >= b, "<": lambda: a < b, ">": lambda: a > b}[op]()


def _eval(conds: list[dict], f: dict, ctx: dict) -> tuple[bool, str | None]:
    """(все выполнены, причина «почти подошла»). Причина no_front / no_contact — только если НЕ выполнены лишь условия фронта (камеры нет) или контакта/опоры:
    тогда часть могла бы быть этой ролью, и вместо запасной body она честно остаётся unknown. Иное невыполненное условие — просто не эта роль (None)."""
    failed = []
    for c in conds:
        key = c["f"]
        val = ctx["product_role"] if key == "type_is" else _get(f, key)
        if not _cmp(val, c["op"], c["v"]):
            failed.append((key, val))
    if not failed:
        return True, None
    if all(k in _FRONT_KEYS and v is None for k, v in failed):
        return False, "no_front"
    if all(k in _CONTACT_KEYS for k, _ in failed):
        return False, "no_contact"
    return False, None


def _colour_gate(cq: dict | None, ct: dict | None, st: dict) -> bool:
    """Часть «похожа» на доверенную: цвет по текстуре входа (ΔE по lab_median по всем граням части) и разброс (p90 ΔE до медианы без чёрных дыр текстуры — `spread_p90_clean`, иначе `spread_p90`; в `tx_max` раз по log2)."""
    if not isinstance(cq, dict) or not isinstance(ct, dict) or "lab_median" not in cq or "lab_median" not in ct:
        return False
    de = sum((a - b) ** 2 for a, b in zip(cq["lab_median"], ct["lab_median"])) ** 0.5
    k = st.get("tx_key", "spread_p90_clean")
    sq, stt = cq.get(k, cq.get("spread_p90", 0)), ct.get(k, ct.get("spread_p90", 0))
    tx = abs(math.log2((sq + 1) / (stt + 1)))
    if st.get("tx_skip_de") is not None and de <= st["tx_skip_de"]:                  # цвет совпал почти точно: узорная ткань и гладкая часть той же ткани отличаются разбросом, а не материалом
        return True
    return de <= st["de_max"] and tx <= st["tx_max"]


def _similar_to_trusted(features: dict, out: dict, st: dict, colours: dict, rules: dict) -> None:
    """«Материал по частям» (T-169 ②, 21.11): неизвестная часть берёт канал ДОВЕРЕННЫХ частей того же товара (роль задана, agree/seen не ниже `trusted_*`), чей цвет и текстура по видимым
    текселям фото близки, если у всех прошедших один канал (иначе остаётся unknown). Ножки по этому пути — только при выполненной защите legs_guard (низкое основание не того же цвета, что главная часть).
    Классы каталога дерево↔ткань не пересекаются сами: канал берётся у доверенной части этого же товара. dry — `dry_hint`, иначе роль меняется (P-062)."""
    trusted = {q: o for q, o in out.items() if o["role"] != "unknown" and o.get("material_channel") and features[q]["agree"] is not None and features[q]["agree"] >= st["trusted_min_agree"]
               and features[q]["seen"] is not None and features[q]["seen"] >= st["trusted_min_seen"]}
    rc = rules["decision"]["role_conf"]
    lg = rules["decision"].get("legs_guard", {})
    for q, o in list(out.items()):
        if o["role"] != "unknown" or o.get("unknown_reason") in st.get("skip_reasons", ["tiny"]):
            continue
        match = [t for t in trusted if t != q and _colour_gate(colours.get(q), colours.get(t), st)]
        chans = {trusted[t]["material_channel"] for t in match}
        if len(chans) != 1:
            continue
        roles = {trusted[t]["role"] for t in match}
        role = next(iter(roles)) if len(roles) == 1 else ("body" if chans == {"main"} else None)
        if role is None or role not in rules["roles"]:
            continue
        f = features[q]
        if role == "legs" and lg.get("enabled") and f["kind"] in lg.get("kinds", ["body"]):          # крупная объёмная «ножка» — только низкая и не цвета главной (как legs_guard)
            de = f.get("delta_e_main")
            if f["up_q90"] > lg["max_up_q90"] or (de is not None and de < lg["min_de_main"]):
                continue
        rd = rules["roles"][role]
        new = {**o, "role": role, "role_title": rd["titleRu"], "material_channel": rd.get("material_channel"), "role_conf": rc["matched"], "unknown_reason": None,
               "role_why": f"сходство с доверенной частью(ями) {sorted(match)}: цвет ΔE<={st['de_max']}, текстура x{2 ** st['tx_max']:.1f}, канал {next(iter(chans))}"}
        _rule_apply(st, q, out, "similar_to_trusted", new)


def _legs_guard_veto(f: dict, rules: dict, ctx: dict, p: int) -> bool:
    """Защита legs (T-169, 21.11): крупная ОБЪЁМНАЯ часть (kind body) не ножка, если она высокая (up_q90 > max_up_q90) или по цвету близка к главной части (ΔE < min_de_main):
    цоколь модуля мягкой мебели той же обивки. Низкое плоское основание с другим цветом (ножки-основание дивана) проходит. mode "dry": роль остаётся, в out пишется dry_hint; "on": вето."""
    g = rules["decision"].get("legs_guard", {})
    if not g.get("enabled") or f["kind"] not in g.get("kinds", ["body"]) or f["area_share"] < g.get("min_area_share", 0.03):
        return False
    de = f.get("delta_e_main")
    why = []
    if f["up_q90"] > g["max_up_q90"]:
        why.append(f"высота up_q90 {f['up_q90']:.2f} > {g['max_up_q90']}")
    if de is not None and de < g["min_de_main"]:
        why.append(f"ΔE к главной {de:.1f} < {g['min_de_main']}")
    if not why:
        return False
    if g.get("mode") == "on":
        return True
    ctx.setdefault("legs_hints", {})[p] = "; ".join(why)
    return False


def assign_roles(features: dict[int, dict], rules: dict, product_role: str | None, catalog_channels: set[str] | None = None,
                 classes: dict | None = None, catalog_classes: dict[str, str] | None = None, colours: dict[int, dict] | None = None) -> dict[int, dict]:
    """Роль каждой части: {id: {role, role_title, material_channel, role_conf, role_why, unknown_reason}}.
    `features` — `parts_features.part_features`; `catalog_channels` — ключи `parts` из `material_class.classify` товара (legs, frame, handles, shade)."""
    g = group_of(product_role, classes)
    grp = rules["groups"][g]
    ab = rules["decision"]["abstain"]
    rc = rules["decision"]["role_conf"]
    channels = catalog_channels or set()
    ctx = {"product_role": product_role, "group": g, "catalog_classes": catalog_classes or {}}   # классы материала каналов каталога: {"legs": "wood_solid", "frame": …}
    out: dict[int, dict] = {}

    def done(p, role, why, conf, reason=None):
        rd = rules["roles"][role]
        out[p] = {"role": role, "role_title": rd["titleRu"], "material_channel": rd.get("material_channel"), "role_conf": conf, "role_why": why, "unknown_reason": reason}

    live = []
    for p, f in features.items():
        if f["area_share"] < ab["tiny_area_share"]:
            done(p, "unknown", f"площадь {f['area_share']:.4f} меньше {ab['tiny_area_share']}", rc["unknown"], "tiny")
        elif (f["agree"] is not None and f["agree"] < ab["min_agree"]) or (f["seen"] is not None and f["seen"] < ab["min_seen_share"]
                                                                         and not (ab.get("seen_exempt_area_share") and f["area_share"] >= ab["seen_exempt_area_share"])):   # крупная часть почти не видна камерам: решает геометрия, а не обрыв порога seen (T-169, комод HD: 0,051→0,048 ронял роль)
            done(p, "unknown", f"доверие этапа 3: agree={f['agree']}, seen={f['seen']}", rc["unknown"], "unreliable")
        else:
            live.append(p)
    matched: dict[int, list[str]] = {p: [] for p in live}
    fail: dict[int, str] = {}
    f2 = {p: dict(features[p]) for p in live}
    for second in (False, True):                                                       # второй проход: правила с touches_facade видят уже поставленные фасады
        for p in live:
            f = f2[p]
            f["touches_facade"] = any(q in matched and "facade" in matched[q] for q in f["contacts"])
            for name, r in grp["roles"].items():
                needs_t = any(c["f"] == "touches_facade" for c in r["require"])
                if needs_t != second or name in matched[p]:
                    continue
                if "only_if_catalog_channel" in r and r["only_if_catalog_channel"] not in channels:
                    continue
                ok, why = _eval(r["require"], f, ctx)
                for alt in r.get("alt_require", []):                                   # запасной набор условий (OR): ножки с царгой в одной части, у которой рамка «толстая»
                    ok_a, _ = _eval(alt, f, ctx)
                    if ok_a:
                        ok, why = True, None
                        break
                if any(_eval([c], f, ctx)[0] for c in r.get("forbid", [])):          # forbid: сработало ХОТЬ ОДНО условие — роль запрещена
                    continue
                if not ok:
                    if why:
                        fail.setdefault(p, why)
                    continue
                if name == "legs" and _legs_guard_veto(f, rules, ctx, p):
                    continue
                matched[p].append(name)
    for p in live:
        f = features[p]
        trusted = f["agree"] is not None and f["agree"] >= rc["trusted_agree"] and f["seen"] is not None and f["seen"] >= rc["trusted_seen"]
        m = matched[p]
        if len(m) > 1:
            done(p, "unknown", "подходят роли: " + ", ".join(m), rc["unknown"], "ambiguous")
        elif len(m) == 1:
            done(p, m[0], "условия роли выполнены: " + ", ".join(f"{c['f']} {c['op']} {c['v']}" for c in grp["roles"][m[0]]["require"]), rc["matched_trusted"] if trusted else rc["matched"])
        elif p in fail:
            done(p, "unknown", "роль возможна, но не хватает " + ("фронта (камера этапа 4 не passed)" if fail[p] == "no_front" else "контакта/опоры"), rc["unknown"], fail[p])
            _no_front_same_channel(p, features[p], out, grp, rules, channels, ctx, rc, fail[p])
        elif product_role in grp.get("no_body_for_types", []):
            done(p, "unknown", f"тип «{product_role}»: канала материала для частей нет", rc["unknown"], "no_channel")
        elif f["kind"] == "body" and f["supports_near_body"] and f["area_share"] <= ab["support_unclear_max_share"] and (f["delta_e_main"] is None or f["delta_e_main"] >= ab["support_unclear_de_veto"]):
            done(p, "unknown", "объёмная часть держит корпус на полу, но на ножки не похожа — материал основания не угадываем", rc["unknown"], "support_unclear")
            _single_class_support(p, out, rules, ctx, rc)
        elif f["kind"] == "body" and (grp.get("body_scope", "all") == "none" or (grp.get("body_scope", "all") == "largest" and not f["is_largest"])):
            done(p, "unknown", "объёмная часть типа, где материал столешницы/фасада/корпуса назван отдельно — body только у крупнейшей", rc["unknown"], "body_scope")
        elif f["kind"] == "body":
            done(p, "body", "объёмная часть, не подошедшая ни под одну роль", rc["body"])
        else:
            done(p, "unknown", "тонкая часть без правила" + (f" ({fail[p]})" if p in fail else ""), rc["unknown"], fail.get(p, "no_rule"))
    lr = rules["decision"].get("leg_rescue", {})
    if lr.get("enabled"):
        _leg_rescue(features, out, grp, lr, rules, channels, ctx)
    gc = rules["decision"].get("group_consistency", {})
    if gc.get("enabled"):
        _group_consistency(features, out, gc, rules)
    ua = rules["decision"].get("unseen_adopt", {})
    if ua.get("enabled"):
        _unseen_adopt(features, out, ua)
    st = rules["decision"].get("similar_to_trusted", {})
    if st.get("enabled") and colours:
        _similar_to_trusted(features, out, st, colours, rules)
    for q, h in (ctx.get("legs_hints") or {}).items():
        if out.get(q, {}).get("role") == "legs":
            out[q].setdefault("dry_hint", []).append({"rule": "legs_guard", "role": "не legs", "why": h})
    return out


def _fits(f: dict, grp: dict, channels: set[str], ctx: dict) -> list[str]:
    """Роли группы, подходящие части по ГЕОМЕТРИИ (require/alt_require выполнены, ни один forbid), без воздержаний по доверию."""
    fits = []
    for name, r in grp["roles"].items():
        if "only_if_catalog_channel" in r and r["only_if_catalog_channel"] not in channels:
            continue
        ok = _eval(r["require"], f, ctx)[0] or any(_eval(a, f, ctx)[0] for a in r.get("alt_require", []))
        if ok and not any(_eval([c], f, ctx)[0] for c in r.get("forbid", [])):
            fits.append(name)
    return fits


def role_fit(f: dict, rules: dict, product_role: str | None, channels: set[str] | None, role: str, classes: dict | None = None,
             catalog_classes: dict[str, str] | None = None) -> tuple[bool, str | None]:
    """T-217: подходит ли часть с признаками `f` под роль `role` ПО ГЕОМЕТРИИ в группе товара — те же `require`/`alt_require`/`forbid` и `only_if_catalog_channel`, что у `assign_roles`
    (одно правило, не копия). → (да/нет, причина): no_rule — у группы такой роли нет; no_channel — канала каталога нет; no_front / no_contact — не хватает только камеры или опоры;
    forbid — сработал запрет; None — геометрия не та. Воздержаний по доверию (tiny, agree, seen) здесь нет — их решает вызывающий."""
    grp = rules["groups"][group_of(product_role, classes)]
    r = grp["roles"].get(role)
    if r is None:
        return False, "no_rule"
    if "only_if_catalog_channel" in r and r["only_if_catalog_channel"] not in (channels or set()):
        return False, "no_channel"
    ctx = {"product_role": product_role, "group": group_of(product_role, classes), "catalog_classes": catalog_classes or {}}
    ok, why = _eval(r["require"], f, ctx)
    if not ok:
        for alt in r.get("alt_require", []):
            if _eval(alt, f, ctx)[0]:
                ok, why = True, None
                break
    if ok and any(_eval([c], f, ctx)[0] for c in r.get("forbid", [])):
        return False, "forbid"
    return (True, None) if ok else (False, why)


def _rule_apply(rule: dict, p: int, out: dict, name: str, new: dict) -> None:
    """Общий переключатель «включить / вхолостую» (P-062): enabled+mode!=dry — роль меняется; dry — роль прежняя, в `dry_hint` пишется, что было бы."""
    if not rule or not rule.get("enabled"):
        return
    if rule.get("mode") == "dry":
        out[p].setdefault("dry_hint", []).append({"rule": name, "role": new["role"], "why": new["role_why"]})
    else:
        out[p] = new


def _front_free_roles(f: dict, grp: dict, rules: dict, channels: set, ctx: dict) -> list[str]:
    """Роли группы, у которых НЕ хватает только фронта: прочие условия выполнены, запретов нет, канал каталога есть (если нужен)."""
    names = []
    for name, r in grp["roles"].items():
        if not any(c["f"] in _FRONT_KEYS for c in r["require"]):
            continue
        if "only_if_catalog_channel" in r and r["only_if_catalog_channel"] not in channels:
            continue
        rest = [c for c in r["require"] if c["f"] not in _FRONT_KEYS and c["f"] != "touches_facade"]
        if _eval(rest, f, ctx)[0] and not any(_eval([c], f, ctx)[0] for c in r.get("forbid", [])):
            names.append(name)
    return names


def _no_front_same_channel(p: int, f: dict, out: dict, grp: dict, rules: dict, channels: set, ctx: dict, rc: dict, why: str) -> None:
    """no_front, когда ВСЕ роли, которым не хватает фронта, красятся одним каналом с body (фасад/верх = основной класс): фронт не меняет материал → роль без фронта
    (фасад как при камере). Есть среди кандидатов роль другого канала (ручки) — воздерживаемся по-прежнему."""
    rule = rules["decision"].get("no_front_same_channel")
    if why != "no_front" or not rule or not rule.get("enabled"):
        return
    names = _front_free_roles(f, grp, rules, channels, ctx)
    main = rules["roles"]["body"].get("material_channel")
    if not names or any(rules["roles"][n].get("material_channel") != main for n in names):
        return
    rd = rules["roles"][names[0]]
    _rule_apply(rule, p, out, "no_front_same_channel", {"role": names[0], "role_title": rd["titleRu"], "material_channel": rd.get("material_channel"), "role_conf": rc["matched"],
                "role_why": "фронта нет, но роли " + "/".join(names) + " красятся одним каналом с основной частью — фронт материал не меняет", "unknown_reason": None})


def _single_class_support(p: int, out: dict, rules: dict, ctx: dict, rc: dict) -> None:
    """support_unclear: вето ΔE нужно, пока основание МОЖЕТ быть другим материалом (ножки/каркас каталога ≠ основной класс). Каталог даёт один класс (каналов ножек/каркаса нет
    или они того же класса, что основной) — основание красится основным классом, неопределённости нет → body."""
    rule = rules["decision"].get("single_class_support")
    cc = ctx.get("catalog_classes") or {}
    if not rule or not rule.get("enabled") or not cc.get("main"):
        return
    if any(cc.get(k) and cc[k] != cc["main"] for k in ("legs", "frame", "handles", "shade")):
        return
    rd = rules["roles"]["body"]
    _rule_apply(rule, p, out, "single_class_support", {"role": "body", "role_title": rd["titleRu"], "material_channel": rd.get("material_channel"), "role_conf": rc["body"],
                "role_why": "каталог даёт один класс материала (" + cc["main"] + ") без отдельных ножек/каркаса — вето по цвету не нужно", "unknown_reason": None})


def _wood_material_ok(ctx: dict) -> bool:
    """Режим wood — только если по каталогу материал ножек = материалу каркаса (или каркаса нет); классов каталога нет — режим молчит (сигнала «одно дерево» нет)."""
    cc = ctx.get("catalog_classes") or {}
    return bool(cc.get("legs")) and (not cc.get("frame") or cc["frame"] == cc["legs"])


def _legs_geometry_ok(f: dict, r0: dict, ctx: dict, max_up_q90: float) -> bool:
    """Групповые ограничения роли legs (require/alt_require/forbid — вето плиты у столов, лимит площади), КРОМЕ потолка высоты ножки: стойка уходит выше, потолок — `max_up_q90`."""
    strip = lambda cs: [c for c in cs if c["f"] != "up_q90"]
    ok = _eval(strip(r0["require"]), f, ctx)[0] or any(_eval(strip(a), f, ctx)[0] for a in r0.get("alt_require", []))
    return ok and not any(_eval([c], f, ctx)[0] for c in r0.get("forbid", [])) and f["up_q90"] <= max_up_q90


def _leg_rescue(features: dict[int, dict], out: dict[int, dict], grp: dict, lr: dict, rules: dict, channels: set[str], ctx: dict) -> None:
    """НОЖКА ПО ГЕОМЕТРИИ, КОГДА ГОЛОСОВАНИЕ КАДРОВ РАЗМЫТО (T-20261121-169/4, кадр Sakura: низ передней ножки — отдельная часть agree 0.016).
    Часть, которой роль не дали только из-за недоверия кадров (`unknown:unreliable`; tiny не в счёт), становится ножкой, если ВСЕ:
    ① у предмета уже есть ножки, поставленные с доверием (matched_trusted) — ножки у него вообще есть (link=touches_legs: и она касается такой ножки);
    ② по геометрии подходит РОВНО одна роль группы и это legs (все require, ни одного forbid — те же числа, что у обычных ножек);
    ③ `extra_require` из правил: ось почти отвесна, часть стоит на полу. Ткань, подушка, подлокотник этого не пройдут (нет пола/отвесной оси).
    Недоверие кадров касается только границы части, не того, что она ножка. Роль ставится с обычной (не высокой) уверенностью."""
    role = lr["role"]
    r0 = grp["roles"].get(role)
    if not r0 or ("only_if_catalog_channel" in r0 and r0["only_if_catalog_channel"] not in channels):
        return
    rc = rules["decision"]["role_conf"]
    trusted = {q for q, o in out.items() if o["role"] == role and o["role_conf"] >= rc["matched_trusted"]}
    if not trusted:
        return
    for p, o in list(out.items()):
        if o["unknown_reason"] not in lr["from_reasons"]:
            continue
        f = features[p]
        if lr.get("link") == "touches_legs" and not (set(f["contacts"]) & trusted):
            continue
        if not all(_eval([c], f, ctx)[0] for c in lr.get("extra_require", [])):
            continue
        if _fits(f, grp, channels, ctx) != [role]:
            continue
        rd = rules["roles"][role]
        out[p] = {"role": role, "role_title": rd["titleRu"], "material_channel": rd.get("material_channel"), "role_conf": rc["matched"],
                  "role_why": f"ножка по геометрии при размытом голосовании кадров (agree={f['agree']}, seen={f['seen']}): условия роли и отвесная ось у пола выполнены, ножки у предмета уже есть",
                  "unknown_reason": None}
    wd = lr.get("wood")
    if wd and wd.get("enabled") and ctx.get("group") in wd.get("groups", [ctx.get("group")]) and _wood_material_ok(ctx):                                       # ножка и стойка из одного дерева: часть уходит выше сиденья, но это те же ножки
        for p, o in list(out.items()):
            if o["unknown_reason"] not in wd["from_reasons"]:
                continue
            f = features[p]
            if not all(_eval([c], f, ctx)[0] for c in wd["require"]) or not _legs_geometry_ok(f, r0, ctx, wd.get("max_up_q90", 0.75)):
                continue
            rd = rules["roles"][role]
            out[p] = {"role": role, "role_title": rd["titleRu"], "material_channel": rd.get("material_channel"), "role_conf": rc["matched"],
                      "role_why": f"ножка вместе со стойкой (одно дерево): тонкая, стоит на полу, касается тела, в его объёме {f['body_overlap']:.0%}, высота до {f['up_q90']}; ножки у предмета уже есть",
                      "unknown_reason": None}


def _unseen_adopt(features: dict[int, dict], out: dict[int, dict], ua: dict) -> None:
    """НЕВИДИМАЯ ЧАСТЬ БЕРЁТ РОЛЬ СОСЕДА (T-169, розовые пятна Sakura HD: части 5 и 7 — ни одна камера их не видит, голосов нет).
    Часть с причиной из `from_reasons` (unreliable; tiny не в счёт) и видимостью seen ≤ `max_seen` получает роль соседней части с НАИБОЛЬШЕЙ общей границей,
    если у соседа роль известна и его доля границы ≥ `min_share`. Соседа выбираем по итоговым ролям после остальных правил (за один проход, цепочек нет).
    Видимая часть с неясной ролью сюда не попадает: невидимость — причина, по которой голосам верить нечему, а не признак «не знаем, что это»."""
    snap = {p: dict(o) for p, o in out.items()}
    for p, o in snap.items():
        f = features[p]
        if o["unknown_reason"] not in ua["from_reasons"] or (f.get("seen") or 0.0) > ua["max_seen"]:
            continue
        if ua.get("kinds") and f.get("kind") not in ua["kinds"]:
            continue                                                   # тонкая часть у тела (ножка, стойка) — соседство ≠ роль
        sh = f.get("shared_faces") or {}
        tot = sum(sh.values())
        if not tot:
            continue
        q = max(sh, key=lambda k: sh[k])
        if snap[q]["role"] == "unknown" or sh[q] / tot < ua["min_share"]:
            continue
        if ua.get("mode") == "dry":                                    # сухой режим: роль не меняем, только подсказка в отчёт
            out[p] = {**snap[p], "unseen_hint": {"role": snap[q]["role"], "neighbor": q, "border_share": round(sh[q] / tot, 2)}}
            continue
        out[p] = {**snap[q], "role_conf": min(snap[q]["role_conf"], ua["role_conf"]),
                  "role_why": f"невидимая часть (seen={f.get('seen')}, голосов нет) берёт роль соседа {q} с наибольшей общей границей ({sh[q] / tot:.0%} её границы)",
                  "unknown_reason": None}


def _group_consistency(features: dict[int, dict], out: dict[int, dict], gc: dict, rules: dict) -> None:
    """Глобальная согласованность: части одной группы повторов (одинаковая рамка и высота; связность — по цепочке попарных совпадений) получают ОДНУ роль.
    Роли расходятся — вся группа unknown:group_disagree. Части с причинами из `ignore_unknown_reasons` (tiny, unreliable — данных мало) в сравнение не входят и не меняются."""
    parent = {p: p for p in features}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for p, f in features.items():
        for q in f.get("symmetry_members", []):
            parent[find(p)] = find(q)
    groups: dict[int, list[int]] = {}
    for p in features:
        groups.setdefault(find(p), []).append(p)
    for members in groups.values():
        cmp = [p for p in members if out[p]["unknown_reason"] not in gc["ignore_unknown_reasons"]]
        if len(cmp) < 2 or len({out[p]["role"] for p in cmp}) < 2:
            continue
        roles = sorted({out[p]["role"] for p in cmp})
        for p in cmp:
            rd = rules["roles"]["unknown"]
            out[p] = {"role": "unknown", "role_title": rd["titleRu"], "material_channel": None, "role_conf": 0.0,
                      "role_why": "группа повторов из %d частей получила разные роли: %s" % (len(cmp), ", ".join(roles)), "unknown_reason": gc["unknown_reason"]}


def known_role_area_share(features: dict[int, dict], roles: dict[int, dict]) -> float:
    """Доля ПЛОЩАДИ частей с известной ролью (мерка check.json)."""
    tot = sum(f["area_share"] for f in features.values())
    return round(sum(features[p]["area_share"] for p, r in roles.items() if r["role"] != "unknown") / tot, 4) if tot else 0.0
