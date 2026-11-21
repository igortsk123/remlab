"""T-181/Ш4 v1b: Qwen3-VL называет области фото (часть + материал); сравнение с ролью этапа 3 по тем же граням. Только чтение, ≤$1."""
import base64, io, json, os, sys
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

sys.path.insert(0, os.path.expanduser("~/igor/remlab/tools/scout"))
from llm_gateway import chat  # noqa: E402
from openai_budget import log_spend  # noqa: E402

MODEL = "alibaba/qwen3-vl-instruct"
O = os.path.expanduser("~/remlab-logs/t181-1121-out"); R = os.path.expanduser(os.environ.get("QWEN_R", "~/remlab-logs/e2eHD-1121"))
PARTS = ["seat_cushion", "backrest", "armrest", "leg", "frame_or_post", "base_or_skirt", "side_panel", "back_panel", "drawer_or_door_front", "top_surface", "table_edge", "handle", "glass_panel", "lamp_shade", "pillow", "other"]
MATS = ["fabric", "wood", "laminate_board", "metal", "leather", "glass_clear", "glass_frosted_or_painted", "plastic", "unknown"]
PROMPT = ("Это фото предмета мебели или светильника из интернет-магазина. Часть, которую нужно назвать, закрашена ПУРПУРНЫМ с контуром; остальное — обычное фото.\n"
          f"Ответь только JSON без markdown: {{\"part\": одно из {PARTS}, \"material\": одно из {MATS}, \"why\": \"один видимый признак по-русски\"}}.\n"
          "Если пурпурная область — несколько разных частей или не видно, что это, пиши part=\"other\", material=\"unknown\". Материал — по виду поверхности, не по цвету: laminate_board — гладкая однородная плита без видимого рисунка древесины (белая или окрашенная ЛДСП/МДФ); wood — видна текстура дерева; glass_frosted_or_painted — матовое или окрашенное стекло (плафон-шар); если по фото материал не отличить (светлый металл или крашеное дерево) — material=\"unknown\", это нормальный ответ.")
sku = sys.argv[1]; maxn = int(sys.argv[2]) if len(sys.argv) > 2 else 14
z = np.load(f"{O}/{sku}.photo_regions.npz"); lab, obj, ids = z["lab"], z["obj"], z["ids"]
cv = Image.open(f"{O}/{sku}.canvas.png").convert("RGB"); A = np.asarray(cv)
ys, xs = np.nonzero(obj); y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max(); m = 30
box = (max(0, x0 - m), max(0, y0 - m), min(1536, x1 + m), min(1536, y1 + m))
tot = float(obj.sum())
parts = json.load(open(f"{R}/{sku}/03-parts/parts.json"))
pp = np.load(f"{R}/{sku}/03-parts/parts.npz")["part"]
role_of = {int(p["id"] if "id" in p else i): p.get("role") for i, p in enumerate(parts["parts"])}
cat = json.load(open(f"{O}/{sku}.layers.json")).get("catalog")
regs = [(int(r), float((lab == r).sum()) / tot) for r in np.unique(lab) if r >= 0]
regs = sorted([x for x in regs if x[1] >= float(os.environ.get("QWEN_MIN", "0.004"))], key=lambda t: -t[1])[:maxn]
usd = 0.0; rows = []
for r, share in regs:
    mk = lab == r
    img = A.copy().astype(np.float32); tint = np.array([200, 0, 220], np.float32)
    img[mk] = 0.45 * img[mk] + 0.55 * tint
    edge = mk & ~ndimage.binary_erosion(mk, iterations=2); img[edge] = (255, 0, 255)
    pim = Image.fromarray(img.astype(np.uint8)).crop(box); pim.thumbnail((768, 768))
    buf = io.BytesIO(); pim.save(buf, "JPEG", quality=88)
    msg = [{"role": "user", "content": [{"type": "text", "text": PROMPT}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}}]}]
    try:
        out = chat(MODEL, msg, direct_fallback=False, max_tokens=140, temperature=0)
        txt = (out["choices"][0]["message"]["content"] or "").strip().strip("`").removeprefix("json").strip()
        ans = json.loads(txt)
        log_spend(MODEL, out.get("usage"), 1, "t181_regions")
        u = out.get("usage") or {}; usd += u.get("prompt_tokens", 0) * 2e-7 + u.get("completion_tokens", 0) * 8.8e-7
    except Exception as e:  # noqa: BLE001
        ans = {"part": "ОШИБКА", "material": str(e)[:80], "why": ""}
    fid = ids[mk & (ids >= 0)]
    rl = [role_of.get(int(pp[f])) for f in fid if f < len(pp)]
    maj = max(set(rl), key=rl.count) if rl else None
    rows.append({"region": r, "share_pct": round(share * 100, 1), "qwen": ans, "role_03": maj, "role_03_share": round(rl.count(maj) / max(1, len(rl)), 2) if rl else 0})
    pim.save(f"{O}/{sku}.qwen_r{r}.jpg")
json.dump({"sku": sku, "model": MODEL, "catalog": cat, "usd_est": round(usd, 4), "regions": rows}, open(f"{O}/{sku}.qwen.json", "w"), ensure_ascii=False, indent=1)
print(sku, "регионов", len(rows), "≈$%.4f" % usd, "каталог:", cat)
for x in rows:
    print(f"  р{x['region']:>2} {x['share_pct']:>5}%  Qwen: {x['qwen'].get('part')}/{x['qwen'].get('material')} ({str(x['qwen'].get('why'))[:50]})  | 03: {x['role_03']} ({x['role_03_share']})")
