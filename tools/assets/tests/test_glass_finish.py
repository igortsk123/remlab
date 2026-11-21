#!/usr/bin/env python3
"""Вид и тон стекла: каталожные характеристики → класс (glass / glass_frosted) и тон рецепта (T-20261121-169/9).
Три слоя: (1) правила `glass_finish` в material-classes.json через `material_class.classify` (класс, тон, отрицания, «не угадываем»);
(2) тон доезжает до частей (`resolve_parts`) и сверка с фото (`reconcile_tone`); (3) запекание: цвет меняется ТОЛЬКО под тоном стекла, форма не тронута.
Сети, Blender и чужих моделей нет — синтетика. Запуск: python3 tools/assets/tests/test_glass_finish.py   (numpy, scipy, trimesh, Pillow)"""
import os
import re
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.append(os.path.join(HERE, "..", "..", "scout"))
import remlab_tmp  # noqa: E402
remlab_tmp.use("test_glass_finish")
import material_class as MC  # noqa: E402
import material_stage as MS  # noqa: E402

R = MC.load_rules()
REC = MS.load_recipes()
FAIL = 0


def ok(cond, name):
    global FAIL
    print(("  ✓ " if cond else "  ✗ ") + name)
    FAIL += 0 if cond else 1


def cls(role, params, name=""):
    return MC.classify(R, {"role": role, "name": name, "params": params})


# 1. правила: каталог → класс и тон
r = cls("журнальный стол", {"Материал столешницы": "Стекло", "Материал столешницы: Цвет столешницы": "Коричневый", "Материал ножек": "Стекло", "Цвет основной": "Коричневый"}, "Журнальный стол Сего-2")
ok(r["class"] == "glass" and r["tone"] == [92, 62, 44], "стол: стекло, цвет столешницы «Коричневый» → прозрачное с коричневым тоном")
ok(r["parts"]["legs"]["class"] == "glass" and r["parts"]["legs"]["tone"] == [92, 62, 44], "ножки-стекло берут тон из «Цвет основной», когда своего цвета ножек нет")
ok(not r.get("conflict") and "Коричневый" in r["reason"], "тон не даёт ложного расхождения; цвет назван в причине")
r = cls("торшер", {"Материал корпуса": "Металл", "Материал плафона": "Стекло", "Цвет плафона": "Белый", "Цвет корпуса": "Черный, Медный"}, "Светильник напольный")
ok(r["class"] == "metal" and "tone" not in r, "торшер: класс товара — металл корпуса, цвет корпуса к стеклу не липнет")
ok(r["parts"]["shade"]["class"] == "glass_frosted" and r["parts"]["shade"]["tone"] == [236, 234, 228], "плафон «Белый» → матовое/опаловое стекло с молочным тоном")
r = cls("лампа", {"Материал корпуса": "Металл", "Материал плафона": "Стекло"}, "Светильник настольный")
ok(r["parts"]["shade"]["class"] == "glass" and "tone" not in r["parts"]["shade"], "цвет плафона в каталоге не назван → прозрачное без тона (не угадываем)")
r = cls("ваза", {"Цвет": "Прозрачный", "Материал": "Стекло"}, "Ваза")
ok(r["class"] == "glass" and "tone" not in r, "«Прозрачный» → обычное стекло без тона")
r = cls("ваза", {"Цвет": "Зеленый", "Материал": "Стекло"}, "Ваза")
ok(r["class"] == "glass" and r["tone"] == [66, 118, 88], "цветное стекло вазы: тон из «Цвет»")
r = cls("ваза", {"Цвет": "Серебристый", "Материал": "Стекло"}, "Ваза")
ok("tone" not in r, "«Серебристый» — не «серый» (граница слова)")
r = cls("ваза", {"Цвет": "Белый, Черный", "Материал": "Стекло"}, "Ваза")
ok(r["class"] == "glass" and "tone" not in r, "два цвета в поле — какой у стекла, не знаем: прозрачное без тона")
r = cls("лампа", {"Материал плафона": "Стекло матовое"}, "Лампа")
ok(r["parts"]["shade"]["class"] == "glass_frosted" and "tone" not in r["parts"]["shade"], "слово «матовое» в самом материале → опал; тона нет — цвет не назван")
r = cls("ваза", {"Материал": "Опаловое стекло", "Цвет": "Прозрачный"}, "Ваза")
ok(r["class"] == "glass_frosted", "слово «опаловое» главнее цвета «Прозрачный»")
r = cls("ваза", {"Материал": "Керамика", "Цвет": "Белый"}, "Ваза")
ok(r["class"] == "ceramic" and "tone" not in r, "не стекло — правило вида стекла не срабатывает")
r = cls("ваза", {"Материал": "Стекло", "Цвет": "Белый"}, "Ваза стеклянная")
ok(r["class"] == "glass_frosted" and not r.get("conflict"), "«стеклянная» в названии согласна и с glass_frosted (одно семейство)")
ok(MC.check() == 0, "material_class check: правила и сборка по ним согласованы")

# 2. тон у частей и сверка с фото
cat = {"shade": {"class": "glass_frosted", "reason": "x", "tone": [236, 234, 228]}, "legs": {"class": "metal", "reason": "y"}}
cl = {"class": "metal", "stage": "params", "confidence": 0.9, "reason": "корпус", "parts": cat, "group": "lamp"}
parts = [{"id": 0, "role": "shape:blob", "face_share": 0.5}, {"id": 1, "role": "shape:blob-top", "face_share": 0.3}, {"id": 2, "role": "shape:linear", "face_share": 0.2}]
res = MS.resolve_parts(parts, cl, REC, parts_known=False)
ok(res[1]["class"] == "glass_frosted" and res[1].get("tone") == [236, 234, 228], "часть-плафон получает тон из канала shade каталога")
ok(all("tone" not in res[i] for i in (0, 2)), "остальные части (металл) тона не получают")
gt = REC["glass_tone"]
a = MS.reconcile_tone([92, 62, 44], None, gt)
ok(a["source"] == "catalog" and a["used"] == [92, 62, 44], "нет фото — каталожный тон")
b = MS.reconcile_tone([92, 62, 44], [110, 80, 66], gt)
ok(b["source"] == "photo" and b["used"] == [110, 80, 66] and b["dE"] <= gt["photo_max_dE"], "фото рядом с каталогом (ΔE ≤ порога) уточняет тон")
c = MS.reconcile_tone([92, 62, 44], [240, 240, 240], gt)
ok(c["source"] == "catalog:photo-conflict" and c["used"] == [92, 62, 44] and c["dE"] > gt["photo_max_dE"], "фото далеко от каталога (блики, чужой фон) — остаётся каталог, пометка conflict")

# 3. запекание: цвет меняется только под тоном стекла
from PIL import Image  # noqa: E402
import trimesh  # noqa: E402


def glb_table(path):
    box = trimesh.creation.box(extents=(1, 0.5, 0.5))
    rng = np.random.default_rng(2)
    tex = Image.fromarray(rng.integers(0, 255, (64, 64, 4), dtype=np.uint8))
    uv = np.column_stack([(box.vertices[:, 0] + 0.5), (box.vertices[:, 2] + 0.25) * 2.0]).clip(0, 1)
    box.visual = trimesh.visual.TextureVisuals(uv=uv, material=trimesh.visual.material.PBRMaterial(baseColorTexture=tex))
    box.export(path)


try:
    MS._paint_stage()
    have_ps = True
except SystemExit:
    have_ps = False
    print("  – paint_stage.py не найден: сквозной прогон этапа пропущен")
if have_ps:
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "m.glb")
        glb_table(src)
        photo = os.path.join(d, "photo.png")
        Image.fromarray(np.dstack([np.full((60, 60, 3), (104, 74, 58), np.uint8), np.full((60, 60), 255, np.uint8)])).save(photo)
        prod = {"sid": "x", "name": "Журнальный стол Тест", "role": "журнальный стол", "params": {"Материал столешницы": "Стекло", "Материал столешницы: Цвет столешницы": "Коричневый"}}
        doc = MS.run_stage(src, os.path.join(d, "run"), "s1", prod, frame=False, photo=photo)
        ex = doc["extra"]
        ok(doc["metrics"]["recipe_share"]["value"] == 1.0 and doc["metrics"]["geometry_unchanged"]["ok"], "этап: рецепт у всех граней, форма не тронута")
        ok(ex["glass_tone"] and ex["glass_tone"][0]["source"] == "photo" and ex["glass_tone"][0]["used"] == [104, 74, 58], "цельностеклянный товар: тон уточнён фото, записан в check.json")
        out = os.path.join(d, "run", "s1", "08-material", "material.glb")
        a, b = np.asarray(MS._base_image(*MS.read_glb(src))), np.asarray(MS._base_image(*MS.read_glb(out)))
        covered = (a[..., :3] != b[..., :3]).any(axis=-1)
        ok(covered.any() and (b[covered][:, :3] == [104, 74, 58]).all(), "под стеклом цвет острова = тон")
        ok((a[..., 3] == b[..., 3]).all(), "прозрачность (альфа) карты цвета не тронута")
        ok(doc["metrics"]["color_unchanged"]["value"] is True, "метрика: вне тона цвет байт в байт")
        doc2 = MS.run_stage(src, os.path.join(d, "run"), "s1", prod, frame=False, photo=photo)
        ok(doc2["extra"]["glass_tone"] == ex["glass_tone"] and doc2["extra"]["glb"] == ex["glb"], "перевыпуск даёт тот же результат")
        prod2 = dict(prod, params={"Материал столешницы": "Стекло", "Материал столешницы: Цвет столешницы": "Прозрачный"})
        d3 = MS.run_stage(src, os.path.join(d, "run"), "s2", prod2, frame=False, photo=photo)
        ok(d3["extra"]["glass_tone"] == [] and MS.image_sha(src) == MS.image_sha(os.path.join(d, "run", "s2", "08-material", "material.glb")), "прозрачное без тона: карта цвета байт в байт")
        prod3 = dict(prod, params={"Материал столешницы": "Стекло", "Материал столешницы: Цвет столешницы": "Коричневый"})
        d4 = MS.run_stage(src, os.path.join(d, "run"), "s3", prod3, frame=False)
        ok(d4["extra"]["glass_tone"][0]["source"] == "catalog" and d4["extra"]["glass_tone"][0]["used"] == [92, 62, 44], "без фото — тон из каталога")

# 4. рецепты и правила: смысл
g, f = REC["recipes"]["glass"], REC["recipes"]["glass_frosted"]
ok(0.0 < f["transmission"] < g["transmission"] and f["roughness"] > g["roughness"], "опал рассеивает и прозрачен частично: transmission меньше, roughness больше, чем у прозрачного")
txt = open(os.path.join(HERE, "..", "material_class.py"), encoding="utf-8").read() + open(os.path.join(HERE, "..", "material_stage.py"), encoding="utf-8").read() + open(os.path.join(HERE, "..", "..", "..", "data", "flat3d", "material-classes.json"), encoding="utf-8").read()
ok(not re.search(r"\b\d{9,}\b", txt), "ID товаров в коде и правилах нет")
ok(MS.check() == 0, "material_stage check: рецепты целы")

print(f"test_glass_finish: ошибок {FAIL}")
sys.exit(1 if FAIL else 0)
