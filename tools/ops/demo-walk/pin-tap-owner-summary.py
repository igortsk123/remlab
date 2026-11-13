"""T-111/2: чей ценник — по каждому ценнику мебели/предмета на ней: расстояние до своей рамки и есть ли чужая ближе.
python3 summary2.py <папка>…  (порог — один ряд: высота ценника + 4 + зазор 6 ≈ 30 px на 375, 32 на 1280)"""
import json, sys, glob, os

for d in sys.argv[1:]:
    for f in sorted(glob.glob(os.path.join(d, "*-pins.json"))):
        j = json.load(open(f))
        rows = [(v["variant"], v["cam"], p) for v in j["variants"] for p in v["pins"]]
        mine = [(vi, c, p) for vi, c, p in rows if "gapOwn" in p]
        bad = [(vi, c, p) for vi, c, p in mine if not p["ownWins"]]
        far = [(vi, c, p) for vi, c, p in mine if p["gapOwn"] > 32]
        nopin = [(v["variant"], v["cam"], x) for v in j["variants"] for x in v.get("noPin", []) if x.get("inFrame")]
        print(f"{os.path.basename(f)}: вариантов×видов {len(j['variants'])} · ценников {len(rows)} (мебель и предметы на ней {len(mine)}, фон {len(rows)-len(mine)})"
              f" · чужая рамка ближе своей {len(bad)} · дальше ряда от своей {len(far)} · макс до своей {max([p['gapOwn'] for _,_,p in mine] or [0])}"
              f" · товар в кадре без ценника {len(nopin)}"
              f" · ошибок страницы {len(j.get('errs', []))}")
        for vi, c, p in bad + [x for x in far if x not in bad]:
            print(f"   v{vi} c{c} {p['text']:>7} {p['name'][:40]:40} до своей {p['gapOwn']:>3} · ближе {p['closerOther']}")
        for vi, c, x in nopin:
            print(f"   без ценника: v{vi} c{c} {x['name']}")
