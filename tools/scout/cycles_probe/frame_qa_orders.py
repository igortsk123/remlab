#!/usr/bin/env python3
"""Сводка сторожа кадров по БОЕВЫМ заказам рендера (render-qa-gate-01, T-20261118-03/6): «вердикт · причина · заказ».

Заказ = подготовленная папка `~/scout-cache/render-prepared/<ключ>/{dump,scene}` (то, что боевой исполнитель отдаёт Blender; `RENDER_PREP_CACHE`);
дампы без сцены — `~/scout-cache/render-dump/<ключ>/` (кэш выгрузок страницы; ключ другой, сцены рядом нет).
  list                         — заказы: ключ, вариант (комната-набор), время;
  preflight [--md]             — предпроверка (без рендера, секунды) по всем заказам и по дампам без сцены: ошибки/предупреждения с причинами;
  render --out <папка> [--cams C1,C2] [--shard i/n] [--cores 2]
                               — контрольный рендер сторожем теми же ключами, что у боевого исполнителя (`render-preset.json:flags`, `--qa 1`), но 16 выборок,
                                 35 % (геометрия и маски сторожа от шума не зависят); кадры `<папка>/<вариант>-<ключ8>/<вариант>-<ключ8>-<кам>.png(.qa.json)`; уже готовое пропускает, если отчёт свежее `frame_qa.py` и `frame-qa-rules.json` (правили сторожа — пересчитает);
                                 под heavy-slot (`tools/ops/heavy-slot.sh`), 0 ₽, машину рендера не включает;
  table <папка>                — сводка «вердикт · причина · заказ» по отчётам `.qa.json` (+ `frame_qa_table.py <папка>` — таблица ковров).
Запуск на pakardev: `~/venvs/scout/bin/python tools/scout/cycles_probe/frame_qa_orders.py <команда>`."""
import glob
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
import frame_qa as Q  # noqa: E402

PREP = os.environ.get("RENDER_PREP_CACHE") or os.path.expanduser("~/scout-cache/render-prepared")
DUMPS = os.environ.get("RENDER_DUMP_CACHE") or os.path.expanduser("~/scout-cache/render-dump")
BLENDER = os.environ.get("RENDER_BLENDER") or os.path.expanduser("~/opt/blender-5.3.0-linux-x64/blender")
# Классы находок предпроверки, которые видны по одному дампу (без собранной сцены) — для дампов «только выгрузка»
DUMP_ONLY = ("SHELL_", "PLANT_", "NODE_HIDDEN", "MAP_BROKEN", "ART_", "NO_FIELD")


def jl(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def orders():
    """[(ключ, папка, вариант, время)] — заказы с готовыми дампом и сценой."""
    out = []
    for d in sorted(glob.glob(os.path.join(PREP, "*/"))):
        d = d.rstrip("/")
        if not os.path.exists(os.path.join(d, "dump", "scene_info.json")) or not os.path.isdir(os.path.join(d, "scene")):
            continue
        si = jl(os.path.join(d, "dump", "scene_info.json")) or {}
        out.append((os.path.basename(d), d, str(si.get("variant") or "?"), time.strftime("%d.%m %H:%M", time.localtime(os.path.getmtime(d)))))
    return sorted(out, key=lambda o: o[3][6:] + o[3][:5])


def dump_only():
    """Дампы кэша выгрузок, которых нет среди подготовленных заказов (по sha выгрузки сцены): проверяем то, что видно по одному дампу."""
    import hashlib

    def sha(p):
        return hashlib.sha1(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None
    known = {sha(os.path.join(d, "dump", "scene-export.json")) for _, d, _, _ in orders()}
    out = []
    for d in sorted(glob.glob(os.path.join(DUMPS, "*/"))):
        d = d.rstrip("/")
        s = sha(os.path.join(d, "scene-export.json"))
        if s is None or s in known or not os.path.exists(os.path.join(d, "scene_info.json")):
            continue
        si = jl(os.path.join(d, "scene_info.json")) or {}
        out.append((os.path.basename(d), d, str(si.get("variant") or "?"), time.strftime("%d.%m %H:%M", time.localtime(os.path.getmtime(d)))))
    return out


def preflight_rows():
    rules = Q.load_rules()
    rows = []
    for key, d, var, when in orders():
        r = Q.preflight(os.path.join(d, "dump"), os.path.join(d, "dump", "scene-export.json"), os.path.join(d, "scene"), rules=rules)
        rows.append(("заказ", key, var, when, [f for f in r["findings"]]))
    empty = os.path.join(os.path.expanduser("~"), "remlab-logs", "t18-1118", "t6", "_noscene")
    os.makedirs(empty, exist_ok=True)
    for key, d, var, when in dump_only():
        r = Q.preflight(d, os.path.join(d, "scene-export.json"), empty, rules=rules)
        rows.append(("дамп без сцены", key, var, when, [f for f in r["findings"] if f["code"].startswith(DUMP_ONLY) or (f["code"] == "NOT_IN_SCENE" and f["slot"].startswith("carrier:"))]))
    return rows


def cmd_preflight(md):
    rows = preflight_rows()
    bad = 0
    print("| тип | ключ | вариант | время | вердикт | причины |")
    print("|---|---|---|---|---|---|")
    for kind, key, var, when, fs in rows:
        er = [f for f in fs if f["level"] == "error"]
        wr = [f for f in fs if f["level"] == "warn"]
        bad += bool(er)
        why = "; ".join(f"{f['code']} {f['slot']}" for f in er + wr) or "-"
        print(f"| {kind} | {key[:10]} | {var} | {when} | {'БРАК' if er else ('предупр.' if wr else 'чисто')} | {why} |")
    print(f"\nвсего {len(rows)}, с браком предпроверки {bad}")


def cmd_render(out, cams, shard, cores):
    pr = json.load(open(os.path.join(HERE, "render-preset.json"), encoding="utf-8"))
    i, n = shard
    mine = [o for k, o in enumerate(orders()) if k % n == i]
    for key, d, var, _ in mine:
        name = f"{var}-{key[:8]}"
        od = os.path.join(out, name)
        os.makedirs(od, exist_ok=True)
        for cam in cams:
            png = os.path.join(od, f"{name}-{cam}.png")
            if os.path.exists(png + ".qa.json") and os.path.getmtime(png + ".qa.json") > max(os.path.getmtime(os.path.join(HERE, "frame_qa.py")), os.path.getmtime(Q.RULES_PATH)):
                continue     # отчёт свежее кода сторожа и его правил — не пересчитываем; старее (правили сторож) — пересчитать
            cmd = [os.path.join(REPO, "tools", "ops", "heavy-slot.sh"), f"t6-{name}-{cam}", "--cores", str(cores), "--",
                   BLENDER, "-b", "-P", os.path.join(HERE, "render_cycles.py"), "--", "--scene-dir", os.path.join(d, "scene"), "--cam", cam, "--out", png,
                   "--samples", "16", "--pct", "35", "--threads", str(cores),
                   "--demo-glb", os.path.join(d, "dump", "demo_nodes.glb"), "--demo-nodes", os.path.join(d, "dump", "demo_nodes_uuids.json"),
                   "--export", os.path.join(d, "dump", "scene-export.json"), "--public", os.path.join(REPO, "public"), *pr["flags"], "--qa", "1"]
            with open(png[:-4] + ".log", "w") as lg:
                subprocess.run(cmd, stdout=lg, stderr=subprocess.STDOUT)
            print("готово", name, cam, flush=True)


def cmd_table(root):
    print("| заказ (вариант-ключ8) | кадр | вердикт | причина (брак / предупреждение) | неопределимо |")
    print("|---|---|---|---|---|")
    n = {"ok": 0, "indeterminate": 0, "warn": 0, "brak": 0}
    for f in sorted(glob.glob(os.path.join(os.path.expanduser(root), "*", "*.png.qa.json"))):
        d = jl(f)
        base = os.path.basename(f)[:-12]
        order, cam = base.rsplit("-", 1)
        why = []
        for f_ in (d.get("preflight") or {}).get("findings", []):
            if f_["level"] == "error":
                why.append(f"предпроверка {f_['code']} {f_['slot']}")
        for s in d["slots"]:
            if s["level"] in ("brak", "warn"):
                why.append(f"{'БРАК' if s['level'] == 'brak' else 'предупр.'} {s['slot']}:{s['state']} — {s.get('why', '')[:70]}")
        for x in d["frame"]:
            if x["level"] in ("brak", "warn"):
                why.append(f"кадр {x['code']}")
        ind = [s["slot"] for s in d["slots"] if s["level"] == "indeterminate"]
        n[d["verdict"]] = n.get(d["verdict"], 0) + 1
        print(f"| {order} | {cam} | {d['verdict']} | {'; '.join(why) or '-'} | {', '.join(ind) or '-'} |")
    print(f"\nвердикты: {n}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "list":
        for key, d, var, when in orders():
            print(key, var, when)
    elif a[0] == "preflight":
        cmd_preflight("--md" in a)
    elif a[0] == "render":
        g = lambda k, dflt: a[a.index(k) + 1] if k in a else dflt  # noqa: E731
        sh = g("--shard", "0/1").split("/")
        cmd_render(os.path.expanduser(g("--out", "")), g("--cams", "C1,C2").split(","), (int(sh[0]), int(sh[1])), int(g("--cores", "2")))
    elif a[0] == "table":
        cmd_table(a[1])
    else:
        print(__doc__)
