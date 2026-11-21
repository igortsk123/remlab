"""Роль части меша = канал материала каталога (этап 3, шаг «роль», T-20261120-169/3).

ЗАЧЕМ. Этап 8 красит каждую часть по классу каталога; ему нужно знать, какая часть — ножки, ручки, плафон, видимый каркас, а какая — «всё остальное» (body: корпус, обивка, подушки, спинка).
Роль решают правила `tools/scout/rules/part-roles.json` (код только исполняет, ID товаров в код не попадают). Решение — не «ранг и запас», а:
  ① жёстко: роль ставится, если выполнены ВСЕ `require` и ни один `forbid`; роль с `only_if_catalog_channel` — только если такой канал есть у товара в каталоге;
  ② воздержание (`unknown` + причина): мелкая часть (tiny), недоверие этапа 3 (agree/seen — роль не может быть увереннее разбиения), две подходящие роли (ambiguous),
     нет фронта у роли с фронтом (no_front), нет контакта/опоры (no_contact), нет подходящего правила (no_rule), у типа нет канала (no_channel), тип неизвестен (группа `any`);
  ③ body — запасная: объёмная (kind body) часть, не подошедшая под иную роль и прошедшая доверие; у корпусной мебели — только крупнейшая, у стола body нет вовсе (столешница и ножки названы отдельно);
     тонкая/средняя без правила остаётся unknown;
  ③б объёмная часть, что стоит на полу и держит главную (цоколь, нижний модуль), но под ножки не подошла и по цвету заметно иная (ΔE ≥ порога) — unknown:support_unclear; ΔE здесь только ВЕТО (снимает роль, роль не ставит);
  ③в глобальная согласованность: части одной группы повторов (одинаковые размеры рамки и высота) получают ОДНУ роль, расходятся — вся группа unknown:group_disagree;
  ④ glass_mirror геометрия не ставит никогда; ΔE в роль не входит.
Тип товара — `role` каталога → группа в `data/flat3d/material-classes.json` (тот же источник, что у этапа 8); каналы — ключи `parts` результата `material_class.classify`.
"""
from __future__ import annotations

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


def assign_roles(features: dict[int, dict], rules: dict, product_role: str | None, catalog_channels: set[str] | None = None,
                 classes: dict | None = None) -> dict[int, dict]:
    """Роль каждой части: {id: {role, role_title, material_channel, role_conf, role_why, unknown_reason}}.
    `features` — `parts_features.part_features`; `catalog_channels` — ключи `parts` из `material_class.classify` товара (legs, frame, handles, shade)."""
    g = group_of(product_role, classes)
    grp = rules["groups"][g]
    ab = rules["decision"]["abstain"]
    rc = rules["decision"]["role_conf"]
    channels = catalog_channels or set()
    ctx = {"product_role": product_role}
    out: dict[int, dict] = {}

    def done(p, role, why, conf, reason=None):
        rd = rules["roles"][role]
        out[p] = {"role": role, "role_title": rd["titleRu"], "material_channel": rd.get("material_channel"), "role_conf": conf, "role_why": why, "unknown_reason": reason}

    live = []
    for p, f in features.items():
        if f["area_share"] < ab["tiny_area_share"]:
            done(p, "unknown", f"площадь {f['area_share']:.4f} меньше {ab['tiny_area_share']}", rc["unknown"], "tiny")
        elif (f["agree"] is not None and f["agree"] < ab["min_agree"]) or (f["seen"] is not None and f["seen"] < ab["min_seen_share"]):
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
        elif product_role in grp.get("no_body_for_types", []):
            done(p, "unknown", f"тип «{product_role}»: канала материала для частей нет", rc["unknown"], "no_channel")
        elif f["kind"] == "body" and f["supports_body"] and f["area_share"] <= ab["support_unclear_max_share"] and (f["delta_e_main"] is None or f["delta_e_main"] >= ab["support_unclear_de_veto"]):
            done(p, "unknown", "объёмная часть держит корпус на полу, но на ножки не похожа — материал основания не угадываем", rc["unknown"], "support_unclear")
        elif f["kind"] == "body" and (grp.get("body_scope", "all") == "none" or (grp.get("body_scope", "all") == "largest" and not f["is_largest"])):
            done(p, "unknown", "объёмная часть типа, где материал столешницы/фасада/корпуса назван отдельно — body только у крупнейшей", rc["unknown"], "body_scope")
        elif f["kind"] == "body":
            done(p, "body", "объёмная часть, не подошедшая ни под одну роль", rc["body"])
        else:
            done(p, "unknown", "тонкая часть без правила" + (f" ({fail[p]})" if p in fail else ""), rc["unknown"], fail.get(p, "no_rule"))
    gc = rules["decision"].get("group_consistency", {})
    if gc.get("enabled"):
        _group_consistency(features, out, gc, rules)
    return out


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
