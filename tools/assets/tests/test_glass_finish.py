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
ok(r["parts"]["shade"]["class"] == "glass_frosted" and r["parts"]["shade"]["tone"] == [236, 234, 228] and r["parts"]["shade"].get("tone_source") == "white-shade-key", "плафон «Белый» без сильных слов: ключ «Материал плафона» ∈ white_is_opal_for → опал, источник white-shade-key (замер: 85 % молочные)")
r2 = cls("торшер", {"Материал корпуса": "Металл", "Материал плафона": "Стекло матовое", "Цвет плафона": "Белый"}, "Светильник напольный")
ok(r2["parts"]["shade"]["class"] == "glass_frosted" and r2["parts"]["shade"]["tone"] == [236, 234, 228], "«Стекло матовое» + «Белый» → опал с молочным тоном (сильное слово в материале)")
r2 = cls("торшер", {"Материал корпуса": "Металл", "Материал плафона": "Стекло", "Цвет плафона": "Молочный"}, "Светильник напольный")
ok(r2["parts"]["shade"]["class"] == "glass_frosted" and r2["parts"]["shade"]["tone"] == [236, 234, 228], "«Молочный» — сильное слово → опал")
import copy  # noqa: E402
R_st = copy.deepcopy(R)
R_st["glass_finish"]["white_is_opal_for"] = []
rst = MC.classify(R_st, {"role": "торшер", "name": "Светильник напольный", "params": {"Материал корпуса": "Металл", "Материал плафона": "Стекло", "Цвет плафона": "Белый"}})
ok(rst["parts"]["shade"]["class"] == "glass" and "tone" not in rst["parts"]["shade"] and "опал не доказан" in rst["parts"]["shade"]["reason"], "строгое положение (white_is_opal_for пуст): «Белый» без сильных слов → обычное стекло без тона, причина «опал не доказан»")
ok(R["glass_finish"]["white_is_opal_for"] == ["Материал плафона"], "по умолчанию переключатель включён только для «Материал плафона» (светильники; решение директора 21.11)")
for params, nm in (({"Материал": "Стекло", "Цвет": "Белый"}, "ваза"), ({"Материал столешницы": "Стекло", "Материал столешницы: Цвет столешницы": "Белый"}, "журнальный стол")):
    rv = cls(nm, params, "Тест")
    ok(rv["class"] == "glass" and "tone" not in rv, f"«{nm}» с «Белый»: остаётся строго (ключ не в white_is_opal_for)")
for cv, want_opal in (("Прозрачный и Белый", False), ("Прозрачный, Белый", False), ("Белый с прозрачным рисунком", True)):
    r3 = cls("люстра", {"Материал корпуса": "Металл", "Материал плафона": "Стекло", "Цвет плафона": cv}, "Люстра")
    ok((r3["parts"]["shade"]["class"] == "glass_frosted") == want_opal, f"плафон «{cv}»: опал = {want_opal} (отсечка white_opal_blockers: смесь прозрачного и белого — не однотонный опал; «с прозрачным рисунком» — опал)")
r2 = cls("торшер", {"Материал корпуса": "Металл", "Материал плафона": "Стекло", "Цвет плафона": "Прозрачный"}, "Светильник")
ok(r2["parts"]["shade"]["class"] == "glass" and "tone_source" not in r2["parts"]["shade"], "«Прозрачный» плафон не трогает переключатель «Белый»")
r2 = cls("торшер", {"Материал корпуса": "Металл", "Материал плафона": "Стекло", "Цвет плафона": "Белый, Черный"}, "Светильник")
ok(r2["parts"]["shade"]["class"] == "glass" and "tone" not in r2["parts"]["shade"], "два цвета у плафона — переключатель «Белый» не срабатывает")
for w in ("Сатиновое", "Опаловое", "Морозное", "Пескоструйное", "Матовое"):
    ok(cls("лампа", {"Материал плафона": "Стекло", "Цвет плафона": w}, "Лампа")["parts"]["shade"]["class"] == "glass_frosted", f"«{w}» в цвете плафона → опал")
r = cls("лампа", {"Материал корпуса": "Металл", "Материал плафона": "Стекло"}, "Светильник настольный")
ok(r["parts"]["shade"]["class"] == "glass" and "tone" not in r["parts"]["shade"], "цвет плафона в каталоге не назван → прозрачное без тона (не угадываем)")
r = cls("ваза", {"Цвет": "Прозрачный", "Материал": "Стекло"}, "Ваза")
ok(r["class"] == "glass" and "tone" not in r, "«Прозрачный» → обычное стекло без тона")
r = cls("ваза", {"Цвет": "Зеленый", "Материал": "Стекло"}, "Ваза")
ok(r["class"] == "glass" and r["tone"] == [66, 118, 88], "цветное стекло вазы: тон из «Цвет»")
r = cls("ваза", {"Цвет": "Серебристый", "Материал": "Стекло"}, "Ваза")
ok("tone" not in r, "«Серебристый» — не «серый» (граница слова)")
for word, want in (("Шампань", "шампань"), ("Коньячный", "бронзовый"), ("Светло-коньячный", "бронзовый"), ("Коньячная бронза", "бронзовый"), ("Золотистый", "золотой"), ("Золотой тик", "золотой"),
                   ("Бежевый", "бежевый"), ("Кремовый", "бежевый"), ("Розовый", "розовый"), ("Желтый", "жёлтый"), ("Оранжевый", "оранжевый"), ("Красный", "красный"),
                   ("Дымный", "серый"), ("Смоук", "серый"), ("Бирюзовый", "бирюзовый")):
    r = cls("ваза", {"Цвет": word, "Материал": "Стекло"}, "Ваза")
    tone = [c for c in R["glass_finish"]["colours"] if c["name"] == want][0]["rgb"]
    ok(r["class"] == "glass" and r.get("tone") == tone, f"«{word}» → тон «{want}», прозрачное стекло с тоном")
ok(cls("ваза", {"Цвет": "Бирюзовый", "Материал": "Стекло"}, "Ваза")["tone"] != [78, 108, 150], "бирюзовый — не синий (дефект бирюзовой вазы)")
ok(cls("ваза", {"Цвет": "Кремовый", "Материал": "Стекло"}, "Ваза")["class"] == "glass", "кремовый — тон бежевый, не автоматически опал")
for word in ("Хром", "Серебристый", "Платиновый", "Мультиколор"):
    ok("tone" not in cls("ваза", {"Цвет": word, "Материал": "Стекло"}, "Ваза"), f"«{word}» — тона нет (не цвет стекла / не один цвет)")
r = cls("ваза", {"Цвет": "Белый, Черный", "Материал": "Стекло"}, "Ваза")
ok(r["class"] == "glass" and "tone" not in r, "два цвета в поле — какой у стекла, не знаем: прозрачное без тона")
r = cls("лампа", {"Материал плафона": "Стекло матовое"}, "Лампа")
ok(r["parts"]["shade"]["class"] == "glass_frosted" and "tone" not in r["parts"]["shade"], "слово «матовое» в самом материале → опал; тона нет — цвет не назван")
r = cls("ваза", {"Материал": "Опаловое стекло", "Цвет": "Прозрачный"}, "Ваза")
ok(r["class"] == "glass_frosted", "слово «опаловое» главнее цвета «Прозрачный»")
r = cls("ваза", {"Материал": "Керамика", "Цвет": "Белый"}, "Ваза")
ok(r["class"] == "ceramic" and "tone" not in r, "не стекло — правило вида стекла не срабатывает")
r = cls("ваза", {"Материал": "Стекло", "Цвет": "Молочный"}, "Ваза стеклянная")
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
ok(a["source"] == "catalog" and a["used"] == [92, 62, 44] and a["conflict"] is None, "нет фото (или грязная вырезка) — каталожный тон")
b = MS.reconcile_tone([92, 62, 44], [110, 80, 66], gt)
ok(b["source"] == "photo" and b["used"] == [110, 80, 66] and b["conflict"] is None and b["dE"] <= gt["photo_max_dE"], "фото рядом с каталогом: тон = фото, без пометки")
c = MS.reconcile_tone([78, 108, 150], [170, 196, 172], gt)
ok(c["source"] == "photo" and c["used"] == [170, 196, 172] and c["conflict"] == "catalog:photo-conflict" and c["dE"] > gt["photo_max_dE"], "фото далеко от каталога (было: бирюзовая ваза с ошибочным синим тоном, на фото бледно-мятная): верим фото, каталог — пометкой conflict")

# 2б. вырезка: чистая и грязная; блики не тянут медиану
from PIL import Image  # noqa: E402


def png(arr, path):
    Image.fromarray(arr.astype(np.uint8)).save(path)


with tempfile.TemporaryDirectory() as d0:
    base = np.zeros((100, 100, 4), np.uint8)
    base[20:80, 20:80] = (100, 130, 110, 255)                      # предмет 3600 пикселей
    pc = os.path.join(d0, "clean.png")
    png(base, pc)
    ok(MS.photo_tone(pc, gt) == [100, 130, 110], "чистая вырезка: медиана цвета предмета")
    hl = base.copy()
    hl[20:25, 20:80] = (255, 255, 255, 255)                        # блик 5 % площади (300 пикселей) — не должен тянуть медиану
    ph = os.path.join(d0, "hl.png")
    png(hl, ph)
    ok(MS.photo_tone(ph, gt) == [100, 130, 110], "верхние 5 % по яркости (блики) выкинуты")
    sm = base.copy()
    sm[:, :, 3] = 120                                                 # весь предмет полупрозрачный — вырезка грязная, фото не берём
    sm[20:30, 20:80, 3] = 255
    ps = os.path.join(d0, "semi.png")
    png(sm, ps)
    ok(MS.photo_tone(ps, gt) is None, "грязная вырезка (много полупрозрачного) → фото не используется")
    few = np.zeros((100, 100, 4), np.uint8)
    few[:10, :10] = (100, 130, 110, 255)
    pf = os.path.join(d0, "few.png")
    png(few, pf)
    ok(MS.photo_tone(pf, gt) is None, "мало пикселей предмета (< min_pixels) → фото не используется")
    ok(MS.photo_tone(os.path.join(d0, "нет.png"), gt) is None, "нет файла → None")

# 3. запекание: цвет меняется только под тоном стекла
from PIL import Image  # noqa: E402
import trimesh  # noqa: E402


def glb_table(path):
    box = trimesh.creation.box(extents=(1, 0.5, 0.5))
    rng = np.random.default_rng(2)
    g = rng.integers(0, 255, (64, 64, 1), dtype=np.uint8)                  # карта TRELLIS у стекла — серая с рисунком (цвета нет): тон её законно заменяет; цветную карту 07 шаг 08 не трогает (тест в test_material_stage)
    tex = Image.fromarray(np.concatenate([g, g, g, np.full((64, 64, 1), 255, np.uint8)], axis=2))
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
        ok(ex["glass_tone"] and ex["glass_tone"][0]["source"] == "photo" and ex["glass_tone"][0]["used"] == [104, 74, 58] and ex["glass_tone"][0]["conflict"] is None, "цельностеклянный товар: тон уточнён фото, записан в check.json")
        out = os.path.join(d, "run", "s1", "08-material", "material.glb")
        a, b = np.asarray(MS._base_image(*MS.read_glb(src))), np.asarray(MS._base_image(*MS.read_glb(out)))
        covered = (a[..., :3] != b[..., :3]).any(axis=-1)
        ok(covered.any() and (b[covered][:, :3] == [104, 74, 58]).all(), "под стеклом цвет острова = тон")
        ok((a[..., 3] == b[..., 3]).all(), "прозрачность (альфа) карты цвета не тронута")
        ok(doc["metrics"]["color_unchanged"]["value"] is True, "метрика: вне тона цвет байт в байт")
        doc2 = MS.run_stage(src, os.path.join(d, "run"), "s1", prod, frame=False, photo=photo)
        ok(doc2["extra"]["glass_tone"] == ex["glass_tone"] and doc2["extra"]["glb"] == ex["glb"], "перевыпуск даёт тот же результат")
        photo2 = os.path.join(d, "photo2.png")
        Image.fromarray(np.dstack([np.full((60, 60, 3), (170, 196, 172), np.uint8), np.full((60, 60), 255, np.uint8)])).save(photo2)
        dc = MS.run_stage(src, os.path.join(d, "run"), "s0", prod, frame=False, photo=photo2)
        t0 = dc["extra"]["glass_tone"][0]
        ok(t0["used"] == [170, 196, 172] and t0["source"] == "photo" and t0["conflict"] == "catalog:photo-conflict", "этап: фото расходится с каталогом — тон с фото, пометка catalog:photo-conflict в check.json")
        prod2 = dict(prod, params={"Материал столешницы": "Стекло", "Материал столешницы: Цвет столешницы": "Прозрачный"})
        d3 = MS.run_stage(src, os.path.join(d, "run"), "s2", prod2, frame=False, photo=photo)
        ok(not any(t.get("applied") or t.get("used") for t in d3["extra"]["glass_tone"]) and MS.image_sha(src) == MS.image_sha(os.path.join(d, "run", "s2", "08-material", "material.glb")), "прозрачное без тона: карта цвета байт в байт")
        prod3 = dict(prod, params={"Материал столешницы": "Стекло", "Материал столешницы: Цвет столешницы": "Коричневый"})
        d4 = MS.run_stage(src, os.path.join(d, "run"), "s3", prod3, frame=False)
        ok(d4["extra"]["glass_tone"][0]["source"] == "catalog" and d4["extra"]["glass_tone"][0]["used"] == [92, 62, 44], "без фото — тон из каталога")

# 3б. утечка тона в соседний остров (советник Codex): тексели граней БЕЗ тона неприкосновенны, проверка — строго вне маски
def two_islands(path, glass_gap_px=1):
    """Две грани на листе 64×64: левая (стекло) и правая (металл) почти вплотную — зазор glass_gap_px текселей; карта цвета — однотонный «шум» известных цветов."""
    verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [2, 0, 0], [2, 1, 0]], float)
    faces_ = np.array([[0, 1, 2], [1, 3, 2], [1, 4, 3], [4, 5, 3]])
    m = trimesh.Trimesh(vertices=verts, faces=faces_, process=False)
    g = 0.5 - glass_gap_px / 64 / 2
    uvs = np.array([[0.05, 0.05], [g, 0.05], [0.05, 0.9], [g, 0.9], [0.5 + glass_gap_px / 64 / 2, 0.05], [0.5 + glass_gap_px / 64 / 2, 0.9]])
    tex = np.zeros((64, 64, 4), np.uint8)
    tex[...] = (10, 10, 10, 255)
    tex[:, 32:] = (200, 90, 40, 255)                                 # правая половина — «металл» с известным цветом
    img = Image.fromarray(tex)
    m.visual = trimesh.visual.TextureVisuals(uv=uvs, material=trimesh.visual.material.PBRMaterial(baseColorTexture=img))
    m.export(path)
    return m


with tempfile.TemporaryDirectory() as d1:
    gp = os.path.join(d1, "two.glb")
    two_islands(gp)
    doc_, binb_ = MS.read_glb(gp)
    mesh_ = trimesh.load(gp, force="mesh", process=False)
    uv_ = np.asarray(mesh_.visual.uv)
    f_ = np.asarray(mesh_.faces)
    ftone = np.full((len(f_), 3), np.nan)
    ftone[:2] = (60, 140, 120)                                       # грани 0,1 — стекло с тоном (левый остров)
    res_ = MS.tint_base_color(gp, uv_, f_, ftone, dict(gt, patch_dilate_px=6))
    png_, mask_, info_ = res_
    base0 = np.asarray(MS._base_image(doc_, binb_))
    new_ = np.asarray(Image.open(__import__("io").BytesIO(png_)).convert("RGBA"))
    other = np.asarray(MS._raster_faces(uv_, f_, np.array([2, 3]), (64, 64))) > 0
    ok(not (mask_ & other).any(), "маска тона не заходит в тексели граней без тона (утечка в соседний остров исключена даже при поле 6 px)")
    ok((new_[other] == base0[other]).all(), "тексели «металла» байт в байт после тона соседа")
    ok((new_[mask_][:, :3] == (60, 140, 120)).all(), "под тоном цвет = тон")
    ok((new_[~mask_] == base0[~mask_]).all(), "вне маски цвет не тронут (проверка строго вне маски)")
    open(os.path.join(d1, "o.glb"), "wb").write(open(gp, "rb").read())
    ok(MS.colour_unchanged_outside(gp, gp, mask_) is True, "colour_unchanged_outside на неизменённом файле = True")
    # проверка ловит утечку: портим «металл» у шва и убеждаемся, что проверка это видит (маска честная)
    bad = new_.copy()
    bad[other] = (255, 0, 255, 255)
    Image.fromarray(bad).save(os.path.join(d1, "bad.png"))
    from PIL import Image as _I
    doc2 = MS.read_glb(gp)[0]
    png_bad = MS._png(bad)
    MS.patch_glb(gp, os.path.join(d1, "leak.glb"), {"mr": np.zeros((4, 4, 4), np.uint8), "hasSheen": False, "hasTransmission": False, "sheen": None, "trans": None, "sheenRoughness": 0.0}, png_bad)
    ok(MS.colour_unchanged_outside(gp, os.path.join(d1, "leak.glb"), mask_) is False, "утечка в чужой остров ловится проверкой color_unchanged (маска её не прикрывает)")

# 3в. нейтральная база под прозрачным стеклом без тона (советник Codex): тёмная карта TRELLIS → нейтральный цвет; нетёмная не трогается
with tempfile.TemporaryDirectory() as d2:
    def glb_flat(path, rgb):
        box = trimesh.creation.box(extents=(1, 0.5, 0.5))
        uv = np.column_stack([(box.vertices[:, 0] + 0.5), (box.vertices[:, 2] + 0.25) * 2.0]).clip(0, 1)
        tex = Image.fromarray(np.dstack([np.full((64, 64, 3), rgb, np.uint8), np.full((64, 64), 255, np.uint8)]))
        box.visual = trimesh.visual.TextureVisuals(uv=uv, material=trimesh.visual.material.PBRMaterial(baseColorTexture=tex))
        box.export(path)
    pv = {"sid": "v", "name": "Ваза Тест", "role": "ваза", "params": {"Материал": "Стекло", "Цвет": "Прозрачный"}}
    dark, bright = os.path.join(d2, "dark.glb"), os.path.join(d2, "bright.glb")
    glb_flat(dark, (12, 12, 14))
    glb_flat(bright, (190, 150, 90))
    dd = MS.run_stage(dark, os.path.join(d2, "run"), "dark", pv, frame=False)
    nb = [t for t in dd["extra"]["glass_tone"] if t["source"] == "neutral-base"]
    outd = np.asarray(MS._base_image(*MS.read_glb(os.path.join(d2, "run", "dark", "08-material", "material.glb"))))
    ok(nb and nb[0]["applied"] and nb[0]["used"] == gt_n["glass"] if (gt_n := REC["glass_tone"]["neutral_rgb"]) else False, "тёмная карта под прозрачным стеклом → нейтральная база (в check.json: median_L, applied)")
    ok((outd[..., :3] == REC["glass_tone"]["neutral_rgb"]["glass"]).all(), "карта цвета островов = нейтральный цвет, не чёрный")
    ok(dd["metrics"]["color_unchanged"]["value"] is True and dd["metrics"]["geometry_unchanged"]["ok"], "форма не тронута, цвет вне стекла не тронут")
    db_ = MS.run_stage(bright, os.path.join(d2, "run"), "bright", pv, frame=False)
    nb2 = [t for t in db_["extra"]["glass_tone"] if t["source"] == "neutral-base"]
    ok(nb2 and not nb2[0]["applied"] and MS.image_sha(bright) == MS.image_sha(os.path.join(d2, "run", "bright", "08-material", "material.glb")), "нетёмная карта (янтарь/молоко TRELLIS) не трогается: байт в байт")

# 3г. составной товар (стекло + металл): фото не берём — стеклянную часть на фото от остального не отделить
cat_c = {"shade": {"class": "glass", "reason": "x", "tone": [60, 140, 120]}, "legs": {"class": "metal", "reason": "y"}}
cl_c = {"class": "metal", "stage": "params", "confidence": 0.9, "reason": "корпус", "parts": cat_c, "group": "lamp"}
res_c = MS.resolve_parts(parts, cl_c, REC, parts_known=False)
gcls = {c for c, dd_ in R["_byId"].items() if dd_["family"] == "glass"}
ok(not (bool(res_c) and all(r_["class"] in gcls for r_ in res_c.values())), "составной товар: не «цельностеклянный» → фото тон не сверяет (тон из каталога)")

# 4. рецепты и правила: смысл
g, f = REC["recipes"]["glass"], REC["recipes"]["glass_frosted"]
ok(0.0 < f["transmission"] < g["transmission"] and f["roughness"] > g["roughness"], "опал рассеивает и прозрачен частично: transmission меньше, roughness больше, чем у прозрачного")
txt = open(os.path.join(HERE, "..", "material_class.py"), encoding="utf-8").read() + open(os.path.join(HERE, "..", "material_stage.py"), encoding="utf-8").read() + open(os.path.join(HERE, "..", "..", "..", "data", "flat3d", "material-classes.json"), encoding="utf-8").read()
ok(not re.search(r"\b\d{9,}\b", txt), "ID товаров в коде и правилах нет")
ok(MS.check() == 0, "material_stage check: рецепты целы")

print(f"test_glass_finish: ошибок {FAIL}")
sys.exit(1 if FAIL else 0)
