"""T-111/3: тап по самому предмету → свой (выбран + карточка ≤10 с), расхождения pick/itemAt по сетке. python3 summary3.py <папка>…"""
import json, sys, glob, os

for d in sys.argv[1:]:
    for f in sorted(glob.glob(os.path.join(d, "*-pins.json"))):
        j = json.load(open(f))
        its = [(v["variant"], v["cam"], i) for v in j["variants"] for i in v["items"]]
        sel = [x for x in its if x[2]["tap"].get("sel") == x[2]["i"]]
        card = [x for x in its if x[2]["tap"].get("card")]
        visI = [x for x in its if x[2]["tap"].get("vis", True)]
        cardV = [x for x in visI if x[2]["tap"].get("card")]
        mism = [(v["variant"], v["cam"], m) for v in j["variants"] for m in v.get("mism", [])]
        emp = [v.get("empty") or {} for v in j["variants"]]
        turned = sum(1 for e in emp for k in ("left", "right") if isinstance(e.get(k), dict) and e[k]["turned"] and e[k]["sel"] is None)
        edges = sum(1 for e in emp for k in ("left", "right") if isinstance(e.get(k), dict))
        floor = [e["floor"] for e in emp if isinstance(e.get("floor"), dict)]
        print(f"{os.path.basename(f)}: кадров {len(j['variants'])} · тап по предмету → свой выбран {len(sel)}/{len(its)}, карточка ≤10 с {len(card)}/{len(its)} (якорь в кадре {len(cardV)}/{len(visI)})"
              f" · у края {sum(1 for x in sel if x[2]['edge'])}/{sum(1 for x in its if x[2]['edge'])}"
              f" · точек сетки, где pick≠itemAt {len(mism)} · пустое у края → поворот {turned}/{edges}"
              f" · пол → шторка та же {sum(1 for x in floor if x['sheet0'] == x['sheet1'])}/{len(floor)} · ошибок страницы {len(j.get('errs', []))}")
        for vi, c, i in its:
            if i["tap"].get("sel") != i["i"] or not i["tap"].get("card"):
                print(f"   v{vi} c{c} {i['name'][:40]:40} ({i['x']},{i['y']}) точек {i['n']} → выбран {i['tap'].get('sel')} карточка {i['tap'].get('card')} {i['tap'].get('ms')} мс якорь {'в кадре' if i['tap'].get('vis', True) else 'ЗА кадром'} тап {i.get('tapAt')} {'свежая' if i.get('fresh') else 'старая'}")
        for vi, c, m in mism[:8]:
            print(f"   pick≠itemAt v{vi} c{c} ({m[0]},{m[1]}) pick {m[2]} itemAt {m[3]}")
