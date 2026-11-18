"""Таблица «поймано / ложных / неопределимо» по отчётам сторожа кадров (`*.png.qa.json`) из папки матрицы: python3 frame_qa_table.py [папка] [--skip имя.qa.json,…]."""
import glob, json, os, sys, collections
root = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/remlab-logs/t18-1118/qa")
SKIP = set((sys.argv[sys.argv.index("--skip") + 1] if "--skip" in sys.argv else "").split(","))
rows = []
for f in sorted(glob.glob(root + "/*/*.png.qa.json")):
    d = json.load(open(f, encoding="utf-8"))
    if os.path.basename(f) in SKIP:
        continue   # самый первый прогон — до правок сторожа
    for s_ in d["slots"]:
        if s_["state"] == "missing" and "нет в собранной сцене" in s_["why"]:
            s_["state"], s_["level"] = "not_in_scene", "brak"
    rows.append((os.path.basename(f)[:-12], d))
EXPECT = {
    "art_nomap": lambda d, spec: any(s["class"] == "art" and s["state"] == "art_no_map" for s in d["slots"]),
    "art_white": lambda d, spec: any(s["class"] == "art" and s["state"] == "art_blank" for s in d["slots"]),
    "curtain_remove": lambda d, spec: any(s["class"] == "curtain" and s["state"] in ("missing", "not_in_scene") for s in d["slots"]),
    "hide_item": lambda d, spec: any(s["slot"] == spec.split(":", 1)[1] and s["state"] == "missing" for s in d["slots"]),
    "camera": lambda d, spec: any(f["code"] == "CAMERA_MISMATCH" for f in d["frame"]),
}
print("| прогон | вердикт | брак | предупр. | неопределимо |")
print("|---|---|---|---|---|")
by = collections.defaultdict(lambda: collections.Counter())
for name, d in rows:
    inj = d.get("injected") or []
    br = [f"{s['slot']}:{s['state']}" for s in d["slots"] if s["level"] == "brak"] + [f["code"] for f in d["frame"] if f["level"] == "brak"]
    wr = [f"{s['slot']}:{s['state']}" for s in d["slots"] if s["level"] == "warn"]
    ind = [s["slot"] for s in d["slots"] if s["level"] == "indeterminate"]
    print(f"| {name} | {d['verdict']} | {'; '.join(br) or '-'} | {'; '.join(wr) or '-'} | {', '.join(ind) or '-'} |")
    if not inj:
        by["без инъекции"]["кадров"] += 1
        by["без инъекции"]["ложный брак"] += bool(br)
        by["без инъекции"]["ложное предупр."] += bool(wr)
        by["без инъекции"]["неопределимых слотов"] += len(ind)
        by["без инъекции"]["слотов оценено"] += len(d["slots"])
    for spec in inj:
        k = spec.split(":")[0]
        by[k]["кадров"] += 1
        by[k]["поймано"] += bool(EXPECT[k](d, spec))
        by[k]["пропущено"] += not EXPECT[k](d, spec)
        by[k]["неопределимых слотов"] += len(ind)
        # ложный брак при инъекции — брак по слотам, не относящимся к инъекции
print()
for k, c in by.items():
    print(k, dict(c))
