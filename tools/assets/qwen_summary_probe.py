"""Сводка пробы Qwen3-VL: закрыто unknown / ошибки против каталога (ПОСЛЕ, Qwen каталога не видел) / отказы + контактные листы для проверки глазами."""
import json, os, sys
from PIL import Image, ImageDraw
O = os.path.expanduser("~/remlab-logs/t181-1121-out")
FAM = {"wood": "wood", "veneer": "wood", "ldsp": "wood", "mdf": "wood", "plywood": "wood", "fabric": "cloth", "velour": "cloth", "boucle": "cloth", "linen": "cloth", "textile": "cloth",
       "metal": "metal", "glass": "glass", "leather": "leather", "plastic": "plastic"}
def fam(c):
    for k, v in FAM.items():
        if c and k in c: return v
    return c
def chan(part):
    return {"leg": "legs", "frame_or_post": "frame", "lamp_shade": "shade", "handle": "handles"}.get(part, "main")
tot = dict(regions=0, refusals=0, with_catalog=0, vs_catalog_err=0, unk_regions=0, unk_closed=0, abstained=0)
for sku in sys.argv[1:]:
    q = json.load(open(f"{O}/{sku}.qwen.json")); L = json.load(open(f"{O}/{sku}.layers.json"))
    classes = dict(kv.split("=") for kv in (q.get("catalog") or {}).get("classes", "").split(",") if "=" in kv)
    cam = L.get("camera_passed"); tiles = []
    for r in q["regions"]:
        a = r["qwen"]; ref = a.get("part") == "other" or a.get("material") in ("unknown", None) or a.get("part") == "ОШИБКА"
        tot["regions"] += 1; tot["refusals"] += ref
        mark = ""
        if not ref and classes:
            ch = chan(a["part"]); cl = classes.get(ch) or classes.get("main")
            tot["with_catalog"] += 1; err = fam(cl) != fam(a["material"]); tot["vs_catalog_err"] += err
            mark = 'cat:%s %s' % (cl, 'ERR' if err else 'ok')
        if cam and r["role_03"] == "unknown":
            tot["unk_regions"] += 1; tot["unk_closed"] += (not ref)
        if not cam: tot["abstained"] += 1
        r03 = r['role_03'] if cam else '-'
        tiles.append(('%s r%s %s%%\n%s/%s\n03:%s %s' % (sku[-6:], r['region'], r['share_pct'], a.get('part'), a.get('material'), r03, mark), '%s/%s.qwen_r%s.jpg' % (O, sku, r['region'])))
    W, H, cols = 280, 230, 4; rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (W * cols, H * rows), "white"); d = ImageDraw.Draw(sheet)
    for i, (cap, p) in enumerate(tiles):
        im = Image.open(p); im.thumbnail((W - 6, 150)); x, y = (i % cols) * W, (i // cols) * H
        sheet.paste(im, (x + 3, y + 3)); d.multiline_text((x + 4, y + 156), cap, fill="black", spacing=2)
    sheet.save(f"{O}/{sku}.qwen_sheet.jpg", quality=85)
    print(sku, "камера", cam, "лист:", f"{O}/{sku}.qwen_sheet.jpg")
print(json.dumps(tot, ensure_ascii=False))
