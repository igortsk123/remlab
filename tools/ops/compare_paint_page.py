#!/usr/bin/env python3
"""Страница для владельца: «старая модель | крашеная» бок о бок (T-20261120-120, владелец TG 2687).

ЗАЧЕМ: по ней владелец решает, какую покраску ставить. Все модели — лёгкие копии ≤5 МБ (`tools/assets/runtime_mesh.py`),
на страницу 15-МБ оригиналы не кладём. Нейросеть и платное не зовутся; только чтение готовых прогонов.

ЧТО ДЕЛАЕТ (идемпотентно, пересборка по мере готовности — просто запустить снова):
  1. находит готовые `painted.glb` (прогон закончен: `blender/status.json` → done=true, error пусто) в `--runs`;
     на один товар (часть имени папки до «@») — самый свежий прогон;
  2. название и тип (роль) — из `cfg.json` прогона (`catalog_name`, `cat_role`);
  3. старая модель — та же, что сейчас на сайте: `runtime_mesh.fetch_source(<id товара>)`;
  4. лёгкие копии обеих (≤5 МБ; не уложилась — меньше текстура и упрощение); копия не пересчитывается, пока исходник
     (размер+время) и рецепт те же — кэш `cache.json`; копии прежних прогонов того же товара перезаписываются в ту же папку;
  5. `index.html` (две `<model-viewer>`, вращаются синхронно) и `status.json` в `--out`;
  6. `--publish` — на прод `/opt/remlab/test/compare-paint-1120/` (rsync по ssh; уже выложенное не передаётся).

Запуск (тяжёлое — только так):
    tools/ops/heavy-slot.sh t120-compare --prio 0 -- nice -n 19 ~/venvs/scout/bin/python tools/ops/compare_paint_page.py --publish
"""
from __future__ import annotations

import argparse
import glob
import html
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "assets"))
import runtime_mesh as RM  # noqa: E402

LIMIT = 5 * 1024 * 1024
# ступени: (размер текстуры, доля треугольников) — пока копия не уложится в 5 МБ
STEPS = [(1024, 0.0), (768, 0.0), (512, 0.0), (512, 0.5), (512, 0.3)]
RECIPE = "cmp-1"
HOME = os.path.expanduser("~")
DEFAULT_RUNS = os.path.join(HOME, "remlab-logs/t90-1119/sg/salad/*")
DEFAULT_OUT = os.path.join(HOME, "remlab-logs/T-20261120-120/site")
REMOTE = "root@89.167.127.0"
REMOTE_DIR = "/opt/remlab/test/compare-paint-1120"
URL = "https://remont-lab.online/test/compare-paint-1120/"


def _roles() -> dict[str, str]:
    try:
        d = json.load(open(os.path.join(HERE, "..", "..", "data", "flat3d", "material-class-assign.json"), encoding="utf-8"))
        return {k: v.get("role", "") for k, v in d.items() if isinstance(v, dict) and v.get("role")}
    except Exception:  # noqa: BLE001
        return {}


ROLES = _roles()


def mid_of(run_dir: str) -> str:
    return os.path.basename(run_dir).split("@", 1)[0]


def finished(run_dir: str) -> bool:
    glb = os.path.join(run_dir, "blender", "painted.glb")
    try:
        st = json.load(open(os.path.join(run_dir, "blender", "status.json"), encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return False
    return bool(st.get("done")) and not st.get("error") and os.path.exists(glb) and os.path.getsize(glb) > 1024


def runs_from_list(path: str) -> dict[str, str]:
    """Список готовых (его ведёт менеджер покраски): sku, key, роль, путь painted.glb — последняя строка товара главнее."""
    out: dict[str, str] = {}
    for ln in open(path, encoding="utf-8").read().splitlines()[1:]:
        c = ln.split("\t")
        if len(c) < 4 or not c[3].endswith("painted.glb"):
            continue
        d = os.path.dirname(os.path.dirname(c[3]))
        if finished(d):
            out[c[0]] = d
    return out


def find_runs(pattern: str) -> dict[str, str]:
    best: dict[str, str] = {}
    for d in sorted(glob.glob(pattern)):
        if not os.path.isdir(d) or not finished(d):
            continue
        glb = os.path.join(d, "blender", "painted.glb")
        m = mid_of(d)
        if m not in best or os.path.getmtime(glb) > os.path.getmtime(os.path.join(best[m], "blender", "painted.glb")):
            best[m] = d
    return best


def light_copy(src: bytes, dst: str) -> dict:
    """Исходные байты → лёгкая копия ≤5 МБ. Возвращает {size, how}; ошибка — исключением."""
    last = "нет ступени"
    for size, simp in STEPS:
        out, stats = RM.optimise(src, size, 82)
        with tempfile.TemporaryDirectory(prefix="cmp120-", dir=os.path.dirname(dst)) as td:
            tmp = os.path.join(td, "s.glb")
            new = os.path.join(td, "d.glb")
            open(tmp, "wb").write(out)
            ok, how, probs = RM.build_copy(tmp, new, simp, True, stats["images_out"] > 0)
            if probs:
                last = "; ".join(probs)[:160]
                continue
            n = os.path.getsize(new)
            if n > LIMIT:
                last = f"{n/1e6:.1f} МБ на ступени {size}/{simp}"
                continue
            os.replace(new, dst)
            return {"size": n, "how": f"{how}, текстура {size}, треугольников {int((1-simp)*100) if simp else 100}%"}
    raise RuntimeError(f"не уложилась в 5 МБ или битая: {last}")


def stamp(path: str) -> str:
    st = os.stat(path)
    return f"{RECIPE}:{st.st_size}:{int(st.st_mtime)}"


def build(args) -> dict:
    out = os.path.expanduser(args.out)
    mdir = os.path.join(out, "m")
    os.makedirs(mdir, exist_ok=True)
    cpath = os.path.join(out, "cache.json")
    try:
        cache = json.load(open(cpath, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        cache = {}
    lst = os.path.expanduser(args.list)
    runs = runs_from_list(lst) if os.path.exists(lst) else find_runs(os.path.expanduser(args.runs))
    items, fails = [], []
    for mid, d in sorted(runs.items()):
        try:
            cfg = json.load(open(os.path.join(d, "cfg.json"), encoding="utf-8"))
        except Exception:  # noqa: BLE001
            cfg = {}
        glb = os.path.join(d, "blender", "painted.glb")
        role = cfg.get("cat_role") or ROLES.get(mid, "—")
        # у части прогонов название не записано (`cfg.json: catalog_name` пусто) — тогда роль и номер товара, а не «пустая» строка
        entry = {"id": mid, "name": cfg.get("catalog_name") or f"{role.capitalize()} (название не записано) №{mid.split('_')[-1][-6:]}",
                 "role": role, "run": os.path.basename(d)}
        try:
            for kind, srcpath in (("new", glb), ("old", None)):
                dst = os.path.join(mdir, f"{mid}-{kind}.glb")
                if kind == "old":
                    # исходник старой — из галереи/кэша/прода; метка по самим байтам (файла-пути может не быть)
                    try:
                        data = RM.fetch_source(mid)
                    except urllib.error.HTTPError as he:
                        if he.code != 404:
                            raise
                        entry["old"] = None      # старой модели нет ни в галерее, ни на проде — показываем одну крашеную
                        continue
                    key = f"{RECIPE}:{len(data)}:{RM.src_sha(data, RECIPE)}"
                else:
                    data = None
                    key = stamp(srcpath)
                ck = f"{mid}-{kind}"
                if os.path.exists(dst) and cache.get(ck, {}).get("key") == key:
                    info = cache[ck]
                else:
                    if data is None:
                        data = open(srcpath, "rb").read()
                    print(f"  собираю {ck}: {len(data)/1e6:.1f} МБ", flush=True)
                    info = light_copy(data, dst)
                    info["key"] = key
                    info["src_mb"] = round(len(data) / 1e6, 1)
                    cache[ck] = info
                entry[kind] = {"file": f"m/{mid}-{kind}.glb", "size": os.path.getsize(dst), "how": info.get("how", ""),
                               "v": key.split(":")[-1][:8]}
            items.append(entry)
        except Exception as exc:  # noqa: BLE001 — отказ в счёт и на страницу, молчать нельзя
            fails.append({"id": mid, "name": entry["name"], "why": str(exc)[:200]})
            print(f"ОТКАЗ {mid}: {exc}", file=sys.stderr, flush=True)
    json.dump(cache, open(cpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # автоочистка: копии товаров, которых больше нет в списке готовых (прогон убрали), — перезаписью не нужны, но лежат;
    # удалять командой запрещено, поэтому они просто не попадают в index.html
    page = render(items, fails, args.total)
    open(os.path.join(out, "index.html"), "w", encoding="utf-8").write(page)
    stat = {"built": time.strftime("%H:%M:%S", time.gmtime()) + " UTC", "ready": len(items), "total": args.total,
            "failed": fails, "with_old": sum(1 for i in items if i["old"]), "bytes": sum((i["old"] or {"size": 0})["size"] + i["new"]["size"] for i in items),
            "max_copy": max([i[k]["size"] for i in items for k in ("old", "new") if i[k]] or [0])}
    json.dump(stat, open(os.path.join(out, "status.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return stat


def card(i: dict, n: int) -> str:
    e = html.escape
    def mv(kind: str, label: str) -> str:
        m = i[kind]
        if not m:
            return ('<figure><div class="none"><div>Старой модели на сайте нет<br><small>у товара не было 3D-модели</small></div></div>'
                    f'<figcaption>{label}</figcaption></figure>')
        return (f'<figure><model-viewer data-pair="{n}" src="{m["file"]}?v={m["v"]}" camera-controls touch-action="pan-y" '
                f'loading="lazy" reveal="auto" shadow-intensity="0.8" exposure="1" environment-image="neutral" '
                f'camera-orbit="30deg 70deg auto" interaction-prompt="none" alt="{e(i["name"])} — {label}"></model-viewer>'
                f'<figcaption>{label} · {m["size"]/1e6:.1f} МБ</figcaption></figure>')
    return (f'<section class="pair" id="p{n}"><h2><span class="n">{n}</span> {e(i["name"])} <small>{e(i["role"])}</small></h2>'
            f'<div class="row">{mv("old", "Старая модель")}{mv("new", "Крашеная")}</div></section>')


def render(items: list, fails: list, total: int) -> str:
    cards = "\n".join(card(i, n) for n, i in enumerate(items, 1))
    bad = ""
    if fails:
        bad = ('<p class="bad">Не собрались: ' + "; ".join(html.escape(f"{f['name']} ({f['why']})") for f in fails) + "</p>")
    return PAGE.replace("@@READY@@", str(len(items))).replace("@@OLD@@", str(sum(1 for i in items if i["old"]))).replace("@@TOTAL@@", str(total)) \
        .replace("@@BAD@@", bad).replace("@@CARDS@@", cards or "<p>Пока ни одной готовой пары.</p>") \
        .replace("@@BUILT@@", time.strftime("%H:%M", time.gmtime()) + " UTC")


PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Покраска: старая и новая</title>
<script type="module">
  // копии упакованы meshopt (gltfpack -cc): без декодера model-viewer их не разберёт («setMeshoptDecoder must be called»)
  import { ModelViewerElement } from 'https://unpkg.com/@google/model-viewer@3.5.0/dist/model-viewer.min.js';
  ModelViewerElement.meshoptDecoderLocation = 'https://cdn.jsdelivr.net/npm/meshoptimizer@0.20.0/meshopt_decoder.js';
</script>
<style>
  html, body { margin: 0; background: #e9e9e7; font-family: system-ui, sans-serif; color: #222; }
  header { position: sticky; top: 0; z-index: 5; background: #e9e9e7ee; padding: 8px 16px; border-bottom: 1px solid #d0d0cc; }
  header b { font-size: 17px; }
  header span { font-size: 14px; color: #555; }
  main { padding: 0 16px 40px; max-width: 1400px; margin: 0 auto; }
  .pair { margin: 22px 0 30px; }
  h2 { font-size: 16px; margin: 0 0 8px; font-weight: 600; }
  h2 small { font-weight: 400; color: #666; margin-left: 6px; }
  .n { display: inline-block; min-width: 24px; text-align: center; background: #222; color: #fff; border-radius: 12px; font-size: 13px; padding: 1px 6px; }
  .row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  figure { margin: 0; }
  model-viewer { width: 100%; height: 56vh; min-height: 300px; max-height: 620px; background: #f4f4f2; border-radius: 10px; --poster-color: #f4f4f2; }
  .none { height: 56vh; min-height: 300px; max-height: 620px; display: flex; align-items: center; justify-content: center; text-align: center; background: #efefec; border: 2px dashed #c4c4be; border-radius: 10px; color: #777; }
  figcaption { font-size: 13px; color: #555; padding: 4px 2px; }
  .bad { color: #b00020; font-size: 13px; }
  @media (max-width: 760px) {
    header { padding: 5px 12px; } header b { font-size: 14px; } header span { font-size: 12px; } .hint { display: none; }
    .row { grid-template-columns: 1fr; }
    model-viewer { height: 46vh; min-height: 260px; }
    .none { height: 70px; min-height: 0; }
  }
</style>
</head>
<body>
<header><b>Покраска: старая модель | крашеная</b> <span>— готово @@READY@@ из @@TOTAL@@ (со старой моделью — @@OLD@@) · @@BUILT@@</span> <span class="hint">Крутите одну — вторая поворачивается так же.</span></header>
<main>
@@BAD@@
@@CARDS@@
</main>
<script>
// синхронное вращение: камера одной модели двигает камеру второй из той же пары (угол и наклон; приближение у каждой своё)
(function () {
  var lock = false;
  function link(a, b) {
    a.addEventListener('camera-change', function (ev) {
      if (lock || !ev.detail || ev.detail.source === 'none') return;
      var o = a.getCameraOrbit();
      lock = true;
      b.cameraOrbit = o.theta + 'rad ' + o.phi + 'rad auto';
      setTimeout(function () { lock = false; }, 0);
    });
  }
  function init() {
    var by = {};
    document.querySelectorAll('model-viewer').forEach(function (m) { (by[m.dataset.pair] = by[m.dataset.pair] || []).push(m); });
    Object.keys(by).forEach(function (k) { var p = by[k]; if (p.length === 2) { link(p[0], p[1]); link(p[1], p[0]); } });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
</script>
</body>
</html>
"""


def publish(out: str) -> None:
    out = os.path.expanduser(out)
    sh = lambda *c: subprocess.run(c, check=True)  # noqa: E731
    sh("ssh", "-o", "BatchMode=yes", REMOTE, f"mkdir -p {REMOTE_DIR}/m")
    # модели — сперва (rsync не передаёт неизменённое), страница — последней, чтобы не ссылаться на ещё не лежащее
    sh("rsync", "-a", "--size-only", "-e", "ssh -o BatchMode=yes", out + "/m/", f"{REMOTE}:{REMOTE_DIR}/m/")
    sh("rsync", "-a", "-e", "ssh -o BatchMode=yes", out + "/index.html", out + "/status.json", f"{REMOTE}:{REMOTE_DIR}/")
    sh("ssh", "-o", "BatchMode=yes", REMOTE, f"chmod -R a+rX {REMOTE_DIR}")
    print("выложено:", URL)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", default=DEFAULT_RUNS, help="маска папок прогонов (каждая с cfg.json и blender/painted.glb)")
    ap.add_argument("--list", default=os.path.join(HOME, "remlab-logs/t90-1119/sg/painted-1120.tsv"),
                    help="список готовых (sku, key, роль, путь painted.glb); нет файла — перебор папок --runs")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--total", type=int, default=39, help="сколько товаров покраски всего (для счётчика)")
    ap.add_argument("--publish", action="store_true")
    a = ap.parse_args()
    st = build(a)
    print(f"готово пар {st['ready']} из {st['total']} (со старой {st['with_old']}), отказов {len(st['failed'])}, вес копий {st['bytes']/1e6:.0f} МБ, "
          f"самая большая {st['max_copy']/1e6:.1f} МБ")
    if a.publish and st["ready"]:
        publish(a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
