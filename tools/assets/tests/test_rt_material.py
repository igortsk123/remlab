#!/usr/bin/env python3
"""Лёгкая копия модели для сайта сохраняет материал источника (T-20261123-10; дефект нашёл рабочий 4 в T-20261123-05).
`tools/assets/runtime_mesh.py:optimise/build_light/ladder_steps/recipe_for` + `rules/rt-weight.json:material`.
Раньше optimise выкидывал metallicRoughness и occlusion и ставил metallic 0 / roughness 0.75, а sheen терял картинку — всё, что кладёт этап 08
(`tools/assets/material_stage.py`), на сайте пропадало. Проверяем на подменных GLB (gltfpack подменён, как в `test_rt_weight.py`):
  * карты материала (metallicRoughness, sheenColor, transmission) и расширения на месте после optimise, индексы текстур целы (в т.ч. когда выброшенная
    картинка стоит ПЕРЕД нужной), нет висячих ссылок, картинки — JPEG в бинарном чанке, сторона ≤ правила, каналы roughness/metal не размыты;
  * keep=false (или drop_mr=True) — прежнее поведение: карты долой, скаляры; GLB без карт и без материала — как раньше;
  * лестница веса: не влезло — СНАЧАЛА карты материала (512, 256), цвет остаётся 1024; у модели без карт шаги карт не делаются вовсе;
  * отпечаток копии: метка карт — только у исходников с картами (перевыпуск остальным не нужен);
  * правило: блок material проверяется, mat_size без блока — ошибка.
Запуск: python tools/assets/tests/test_rt_material.py"""
import io
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.append(os.path.join(HERE, '..', '..', 'scout'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_rt_material')
import runtime_mesh as RM  # noqa: E402
from PIL import Image, ImageChops, ImageStat  # noqa: E402

FAILS = []


def ok(name, cond, extra=''):
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
    if not cond:
        FAILS.append(name)


def png(im) -> bytes:
    b = io.BytesIO()
    im.save(b, format='PNG')
    return b.getvalue()


def jpg(im, q=90) -> bytes:
    b = io.BytesIO()
    im.convert('RGB').save(b, format='JPEG', quality=q)
    return b.getvalue()


PX = 2048
GRAD = Image.linear_gradient('L').resize((PX, PX))
STRIPES = Image.new('L', (PX, PX), 0)
STRIPES.paste(255, (0, 0, PX // 2, PX))
MR = Image.merge('RGB', (Image.new('L', (PX, PX), 255), GRAD, STRIPES))               # R — свободный, G — roughness, B — metalness
BASE = Image.effect_noise((PX, PX), 40).convert('RGB')
SHEEN = Image.new('RGB', (PX, PX), (200, 120, 60))
TRANS = Image.new('RGB', (PX, PX), (180, 180, 180))


def pack_images(imgs):
    """imgs: список (байты, mime) → (бинарный чанк, bufferViews, images)."""
    bin_, views, images = bytearray(), [], []
    for data, mime in imgs:
        bin_ += b'\x00' * (-len(bin_) % 4)
        views.append({'buffer': 0, 'byteOffset': len(bin_), 'byteLength': len(data)})
        bin_ += data
        images.append({'bufferView': len(views) - 1, 'mimeType': mime})
    return bytes(bin_), views, images


def source_glb(with_maps=True, junk_first=False, occlusion=True, mark=None) -> bytes:
    """Один материал: цвет (JPEG 2048²); с картами — metallicRoughness (PNG), occlusion, sheen (цвет-карта) и transmission (карта). junk_first — перед нужными
    лежит неиспользуемая картинка (индексы текстур и картинок после выброса пересчитываются; прежний код оставлял лишние текстуры и не правил индексы в материалах)."""
    imgs = []
    if junk_first:
        imgs.append((jpg(Image.new('RGB', (64, 64), (1, 2, 3))), 'image/jpeg'))
    j = len(imgs)
    imgs.append((jpg(BASE), 'image/jpeg'))                      # цвет
    mat = {'pbrMetallicRoughness': {'baseColorTexture': {'index': j}}}
    textures = ([{'source': 0}] if junk_first else []) + [{'source': j}]
    ext_used = []
    if with_maps:
        imgs += [(png(MR), 'image/png'), (png(MR), 'image/png'), (png(SHEEN), 'image/png'), (png(TRANS), 'image/png')]
        k = len(textures)
        textures += [{'source': j + 1}, {'source': j + 2}, {'source': j + 3}, {'source': j + 4}]
        pbr = mat['pbrMetallicRoughness']
        pbr['metallicRoughnessTexture'] = {'index': k}
        pbr['metallicFactor'] = 1.0
        pbr['roughnessFactor'] = 1.0
        if occlusion:
            mat['occlusionTexture'] = {'index': k + 1}
        mat['extensions'] = {'KHR_materials_sheen': {'sheenColorFactor': [1.0, 1.0, 1.0], 'sheenColorTexture': {'index': k + 2}, 'sheenRoughnessFactor': 0.5},
                             'KHR_materials_transmission': {'transmissionFactor': 1.0, 'transmissionTexture': {'index': k + 3}}}
        ext_used = ['KHR_materials_sheen', 'KHR_materials_transmission']
    bin_, views, images = pack_images(imgs)
    js = {'asset': {'version': '2.0', **({'extras': mark} if mark else {})}, 'materials': [mat], 'textures': textures, 'images': images, 'bufferViews': views, 'buffers': [{'byteLength': len(bin_)}]}
    if ext_used:
        js['extensionsUsed'] = ext_used
    return RM.write_glb(js, bin_)


RULE = {'keep': True, 'max_side': 1024, 'quality': 90, 'subsampling': 0}
TEX = {'size': 1024, 'quality': 82}      # блок texture правила обязателен (T-20261123-31)


def problems(js, bin_chunk) -> list[str]:
    """Висячие ссылки и негодные картинки: индекс текстуры вне списка, источник вне images, картинка без bufferView или не JPEG/PNG."""
    out = []
    n_tex, n_img = len(js.get('textures', [])), len(js.get('images', []))
    for m in js['materials']:
        for parent, key in RM.material_refs(m):
            if not parent[key]['index'] < n_tex:
                out.append(f'ссылка {key} → текстура {parent[key]["index"]} из {n_tex}')
    for t in js.get('textures', []):
        if not t.get('source', 0) < n_img:
            out.append(f'текстура → картинка {t.get("source")} из {n_img}')
    for im in js.get('images', []):
        raw = RM.image_bytes(im, js, bin_chunk)
        if 'uri' in im or raw is None or im.get('mimeType') != 'image/jpeg':
            out.append('картинка не в бинарном чанке или не JPEG')
            continue
        try:
            Image.open(io.BytesIO(raw)).load()
        except Exception as e:  # noqa: BLE001
            out.append(f'картинка не открывается: {e}')
    return out


def image_of(js, bin_chunk, ref):
    return Image.open(io.BytesIO(RM.image_bytes(js['images'][js['textures'][ref['index']]['source']], js, bin_chunk))).convert('RGB')


# ——— 1. карты материала на месте ———
src = source_glb()
out, st = RM.optimise(src, 1024, 82, material=RULE)
js, bn = RM.parse_glb(out)
m = js['materials'][0]
pbr = m['pbrMetallicRoughness']
ok('metallicRoughnessTexture на месте', 'metallicRoughnessTexture' in pbr, pbr)
ok('факторы metallic/roughness как в источнике (1.0, не скаляры по роли)', pbr.get('metallicFactor') == 1.0 and pbr.get('roughnessFactor') == 1.0, pbr)
ok('occlusionTexture на месте', 'occlusionTexture' in m)
sheen = (m.get('extensions') or {}).get('KHR_materials_sheen') or {}
ok('KHR_materials_sheen: цвет-карта, фактор цвета и шероховатость на месте', 'sheenColorTexture' in sheen and sheen.get('sheenRoughnessFactor') == 0.5 and sheen.get('sheenColorFactor') == [1.0, 1.0, 1.0], sheen)
trans = (m.get('extensions') or {}).get('KHR_materials_transmission') or {}
ok('KHR_materials_transmission: карта и фактор на месте', 'transmissionTexture' in trans and trans.get('transmissionFactor') == 1.0, trans)
ok('extensionsUsed не потерян', set(js.get('extensionsUsed', [])) >= {'KHR_materials_sheen', 'KHR_materials_transmission'}, js.get('extensionsUsed'))
ok('нет висячих ссылок, все картинки — JPEG в бинарном чанке', problems(js, bn) == [], problems(js, bn))
ok('картинок 5 (цвет + 4 карты), карт материала 4, цвет 1024, карты ≤ 1024', len(js['images']) == 5 and st['maps_out'] == 4 and st['px'] == 1024 and st['map_px'] == 1024, st)
ok('в JSON нет base64 (текстуры в бинарном чанке)', 'data:' not in json.dumps(js))
mr_back = image_of(js, bn, pbr['metallicRoughnessTexture'])
ref = MR.resize(mr_back.size, Image.LANCZOS)
diff = ImageChops.difference(ref, mr_back)
g_err, b_err = ImageStat.Stat(diff).mean[1], ImageStat.Stat(diff).mean[2]
ok('каналы карты MR не размыты: средняя ошибка G (roughness) ≤ 3, B (metalness) ≤ 6 уровней из 255', g_err <= 3 and b_err <= 6, (g_err, b_err))
ok('сторона карты по правилу: при mat_side=256 карты 256, цвет остаётся 1024', (lambda s: s[1]['map_px'] == 256 and s[1]['px'] == 1024)(RM.optimise(src, 1024, 82, material=RULE, mat_side=256)))
ok('карты не больше стороны цвета: запуск 512 (-lite) → карты 512', RM.optimise(src, 512, 82, material=RULE)[1]['map_px'] == 512)
# индексы, когда выброшенная картинка стоит ПЕРЕД нужными (старый код правил индексы неверно)
out_j, st_j = RM.optimise(source_glb(junk_first=True), 1024, 82, material=RULE)
js_j, bn_j = RM.parse_glb(out_j)
pj = js_j['materials'][0]['pbrMetallicRoughness']
col = image_of(js_j, bn_j, pj['baseColorTexture'])
ok('выброшенная картинка перед нужными: цвет по ссылке — это цвет (шум), а не чужая картинка', ImageStat.Stat(col).stddev[0] > 10 and problems(js_j, bn_j) == [], ImageStat.Stat(col).stddev)
mrj = image_of(js_j, bn_j, pj['metallicRoughnessTexture'])
ok('  карта MR по ссылке — это MR (G растёт слева направо… по градиенту, B — полосы)', ImageStat.Stat(mrj).stddev[2] > 100 and len(js_j['images']) == 5, ImageStat.Stat(mrj).stddev)

# ——— 2. прежнее поведение: keep=false / drop_mr=True ———
for label, kw in (('keep=false', {'material': {'keep': False}}), ('drop_mr=True', {'drop_mr': True, 'material': RULE})):
    o2, s2 = RM.optimise(src, 1024, 82, **kw)
    j2, b2 = RM.parse_glb(o2)
    m2 = j2['materials'][0]
    p2 = m2['pbrMetallicRoughness']
    ok(f'{label}: карты MR и occlusion долой, metallic 0, roughness как в источнике (setdefault)', 'metallicRoughnessTexture' not in p2 and 'occlusionTexture' not in m2 and p2['metallicFactor'] == 0.0 and p2['roughnessFactor'] == 1.0, p2)
    ok(f'{label}: картинка одна (цвет), ссылок на выброшенные нет, расширения без карт', len(j2['images']) == 1 and problems(j2, b2) == [] and 'sheenColorTexture' not in json.dumps(m2) and s2['maps_out'] == 0, s2)
ok('drop_mr=False оставляет карты и при keep=false', RM.optimise(src, 1024, 82, drop_mr=False, material={'keep': False})[1]['maps_out'] == 4)
# roughnessFactor по умолчанию 0.75 — когда его в источнике нет
nofac = source_glb()
jn, bn_ = RM.parse_glb(nofac)
jn['materials'][0]['pbrMetallicRoughness'].pop('roughnessFactor')
o3, _s3 = RM.optimise(RM.write_glb(jn, bn_), 1024, 82, material={'keep': False})
ok('keep=false, фактора шероховатости не было → 0.75 (как раньше)', RM.parse_glb(o3)[0]['materials'][0]['pbrMetallicRoughness']['roughnessFactor'] == 0.75)

# ——— 3. GLB без карт и без материала: как раньше ———
plain = source_glb(with_maps=False)
o4, s4 = RM.optimise(plain, 1024, 82, material=RULE)
j4, b4 = RM.parse_glb(o4)
ok('без карт: цвет JPEG 1024, карт нет, материал как был', s4['maps_out'] == 0 and s4['px'] == 1024 and len(j4['images']) == 1 and problems(j4, b4) == [] and list(j4['materials'][0]['pbrMetallicRoughness']) == ['baseColorTexture'], s4)
o4b, _ = RM.optimise(plain, 1024, 82, material={'keep': False})
ok('без карт: результат keep=true и keep=false одинаков байт в байт', o4 == o4b)
bare = RM.write_glb({'asset': {'version': '2.0'}, 'meshes': []}, b'')
o5, s5 = RM.optimise(bare, 1024, 82, material=RULE)
ok('GLB без материала и без картинок: не падает, картинок нет', s5['images_out'] == 0 and RM.parse_glb(o5)[0].get('images', []) == [], s5)
ok('has_material_maps: с картами да, только цвет нет, без материала нет', RM.has_material_maps(src) and not RM.has_material_maps(plain) and not RM.has_material_maps(bare))

# ——— 4. лестница веса: сперва карты, потом цвет ———
MB = 1_000_000


def packed_glb(nbytes: int) -> bytes:
    jp = jpg(Image.new('RGB', (8, 8), (120, 100, 90)))
    js_ = {'asset': {'version': '2.0'}, 'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}], 'textures': [{'source': 0}],
           'images': [{'bufferView': 0, 'mimeType': 'image/jpeg'}], 'buffers': [{'byteLength': 0}], 'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(jp)}]}
    base = len(RM.write_glb(js_, jp))
    return RM.write_glb(js_, jp + b'\x00' * max(0, int(nbytes) - base))


class FakePack:
    """gltfpack: вес = f(сторона цвета, сторона карт или None) из имени `.src<цвет>[-m<карты>].glb`."""
    def __init__(self, weight):
        self.weight, self.calls = weight, []

    def __call__(self, src_path, dst, simplify=0.0, ktx2=True):
        mm = re.search(r'\.src(\d+)(?:-m(\d+))?\.glb$', src_path)
        size, mat = int(mm.group(1)), (int(mm.group(2)) if mm.group(2) else None)
        self.calls.append((size, mat))
        with open(dst, 'wb') as fh:
            fh.write(packed_glb(self.weight(size, mat)))
        return True, ''


def leftovers(d):
    return sorted(f for f in os.listdir(d) if re.search(r'\.(src\d*(-m\d+)?|cand|new)\.glb$|\.cand\.new\.glb$|\.cand\.glb$', f))


LADDER = [{'mat_size': 512}, {'mat_size': 256}, {'size': 512}]
real_pack = RM.pack
with tempfile.TemporaryDirectory(dir=os.environ.get('REMLAB_TMP') or None) as d:
    rp = os.path.join(d, 'r.json')
    json.dump({'max_bytes': 5 * MB, 'texture': TEX, 'ladder': LADDER, 'min_triangles': 0, 'refuse_reason': 'rt_weight_over_limit', 'material': RULE}, open(rp, 'w'))
    rule = RM.weight_rule(rp)
    try:
        # 4a. с картами: 1024/1024 тяжело, карты 512 тяжело, карты 256 влезло → цвет НЕ трогали
        fp = FakePack(lambda s, m: {1024: 6 * MB, 512: 5.5 * MB, 256: 4 * MB}[m])
        RM.pack = fp
        res = RM.build_light(src, os.path.join(d, 'a.glb'), 1024, 82, 0.0, True, rule)
        steps = [t['step'] for t in res['tried']]
        ok('с картами: шаги 1024 → 1024+m512 → 1024+m256, дальше не шли', res['ok'] and steps == ['1024', '1024+m512', '1024+m256'], steps)
        ok('  цвет остался 1024, карты стали 256', res['stats']['px'] == 1024 and res['stats']['map_px'] == 256, res['stats'])
        ok('  вес ≤ предела (4 МБ ≤ 5 МБ)', res['bytes'] <= rule['max_bytes'], res['bytes'])
        ok('  рабочих файлов нет', leftovers(d) == [], leftovers(d))
        # 4b. без карт: шаги карт не делаются, сразу цвет 512
        fp = FakePack(lambda s, m: {1024: 6 * MB, 512: 4 * MB}[s])
        RM.pack = fp
        res = RM.build_light(plain, os.path.join(d, 'b.glb'), 1024, 82, 0.0, True, rule)
        steps = [t['step'] for t in res['tried']]
        ok('без карт: шаги 1024 → 512 (шаги карт пропущены), упаковщик звали дважды', res['ok'] and steps == ['1024', '512'] and len(fp.calls) == 2, (steps, fp.calls))
        ok('  рабочих файлов нет', leftovers(d) == [], leftovers(d))
        # 4c. карты уже не больше стороны шага (запуск -lite 512, карты 512): шаг 512 пустой, идёт 256
        fp = FakePack(lambda s, m: 4 * MB if m == 256 else 6 * MB)
        RM.pack = fp
        res = RM.build_light(src, os.path.join(d, 'c.glb'), 512, 82, 0.0, True, rule)
        steps = [t['step'] for t in res['tried']]
        ok('-lite (запуск 512): шаг карт 512 пустой (карты и так 512) — сразу 256', res['ok'] and steps == ['512', '512+m256'], steps)
        # 4d. ничего не помогло: отказ, причина та же, рабочие файлы убраны, шаги — в tried
        fp = FakePack(lambda s, m: 9 * MB)
        RM.pack = fp
        res = RM.build_light(src, os.path.join(d, 'e.glb'), 1024, 82, 0.0, True, rule)
        ok('не влезло ни с чем: отказ по весу, дошли до цвета 512', (not res['ok']) and res['kind'] == 'weight' and [t['step'] for t in res['tried']][-1] == '512+m256', res['tried'])
        ok('  рабочих файлов нет', leftovers(d) == [], leftovers(d))
        # 4e. правило без блока material (старое/тестовое): карты не хранятся, лестница прежняя
        old = os.path.join(d, 'old.json')
        json.dump({'max_bytes': 5 * MB, 'texture': TEX, 'ladder': [{'size': 512}], 'min_triangles': 0}, open(old, 'w'))
        RM.pack = FakePack(lambda s, m: 6 * MB if s == 1024 else 4 * MB)
        res = RM.build_light(src, os.path.join(d, 'f.glb'), 1024, 82, 0.0, True, RM.weight_rule(old))
        ok('правило без блока material: карты долой (maps_out 0), шаги 1024 → 512', res['ok'] and res['stats']['maps_out'] == 0 and [t['step'] for t in res['tried']] == ['1024', '512'], (res['stats'], res['tried']))
    finally:
        RM.pack = real_pack

    # ——— 5. отпечаток: метка карт только у исходников с картами ———
    base_recipe = 'size=1024;q=82;simplify=0.0;ktx2=True;gltfpack 0.24;guard=tex-1'
    ok('recipe_for: исходник с картами → рецепт с меткой mat=…', RM.recipe_for(src, base_recipe, rule).startswith(base_recipe + ';mat='), RM.recipe_for(src, base_recipe, rule))
    ok('  без карт — рецепт БЕЗ изменений (отпечаток прежний, перевыпуск не нужен)', RM.recipe_for(plain, base_recipe, rule) == base_recipe)
    ok('  правило без блока material — рецепт без изменений и у исходника с картами', RM.recipe_for(src, base_recipe, RM.weight_rule(old)) == base_recipe)
    changed = {**rule, 'material': {**RULE, 'max_side': 512}}
    ok('  правило карт сменилось (max_side) → метка другая → копии с картами пересоберутся', RM.recipe_for(src, base_recipe, changed) != RM.recipe_for(src, base_recipe, rule))

    # ——— 6. проверка правила ———
    def bad_rule(name, doc):
        p = os.path.join(d, name)
        json.dump(doc, open(p, 'w'))
        try:
            RM.weight_rule(p)
            return False
        except ValueError:
            return True
    base_doc = {'max_bytes': 100, 'texture': TEX, 'ladder': []}
    ok('material.quality 0 — ошибка правила', bad_rule('q0.json', {**base_doc, 'material': {**RULE, 'quality': 0}}))
    ok('material.subsampling 3 — ошибка правила', bad_rule('s3.json', {**base_doc, 'material': {**RULE, 'subsampling': 3}}))
    ok('material без keep — ошибка правила', bad_rule('nk.json', {**base_doc, 'material': {'max_side': 1024, 'quality': 90, 'subsampling': 0}}))
    ok('шаг mat_size при блоке material нет — ошибка правила', bad_rule('nm.json', {**base_doc, 'ladder': [{'mat_size': 256}]}))
    ok('шаг и с mat_size, и с size — ошибка правила', bad_rule('both.json', {**base_doc, 'material': RULE, 'ladder': [{'mat_size': 256, 'size': 512}]}))

# ——— 7. числа — в правиле, в коде литералов нет ———
code = open(os.path.join(HERE, '..', 'runtime_mesh.py'), encoding='utf-8').read()
lit = re.findall(r'max_side[^\n]*\b(?:1024|512|256)\b|quality[^\n]*=\s*(?:90|85)\b', code)
ok('в коде нет умолчаний сторон/качества карт (всё из rules/rt-weight.json:material)', not lit, lit)
real = RM.weight_rule()
ok('реальное правило: карты материала хранятся, сперва карты (mat_size) потом цвет (size) в лестнице',
   real['material']['keep'] is True and [next(iter(s)) for s in real['ladder']][:3] == ['mat_size', 'mat_size', 'size'], real['ladder'])

# ——— 8. карты — только у моделей, прошедших этап 08 (отметка в самом GLB, решение директора по TG 2025; T-20261123-10) ———
print('8. отметка этапа 08')
SM = real['material'].get('stage_mark')
ok('реальное правило: stage_mark задан (key и value — строки)', isinstance(SM, dict) and SM.get('key') and SM.get('value'), SM)
RULE_M = {**RULE, 'stage_mark': SM}
new = source_glb(mark={SM['key']: SM['value']})
old = source_glb()                                              # старая модель (Hunyuan и др.): карты MR есть, отметки нет
foreign = source_glb(mark={SM['key']: 'другой-этап'})
o_new, s_new = RM.optimise(new, 1024, 82, material=RULE_M)
ok('прошла этап 08: карты остаются (4), нет висячих ссылок', s_new['maps_out'] == 4 and problems(*RM.parse_glb(o_new)) == [], s_new)
o_old, s_old = RM.optimise(old, 1024, 82, material=RULE_M)
js_old = RM.parse_glb(o_old)[0]
pbr_old = js_old['materials'][0]['pbrMetallicRoughness']
ok('старая модель (с картами, без отметки): карт нет, MR и occlusion долой, скаляры metallic 0 / roughness 1.0 как было',
   s_old['maps_out'] == 0 and 'metallicRoughnessTexture' not in pbr_old and 'occlusionTexture' not in js_old['materials'][0] and pbr_old['metallicFactor'] == 0.0, s_old)
ok('старая модель: байт в байт как прежнее поведение (drop_mr=True)', o_old == RM.optimise(old, 1024, 82, drop_mr=True, material=RULE_M)[0])
ok('в старой модели нет и висячих ссылок расширений (sheen/transmission без картинок убраны)', problems(*RM.parse_glb(o_old)) == [] and not any('Texture' in json.dumps(v) for v in (js_old['materials'][0].get('extensions') or {}).values()), js_old['materials'][0].get('extensions'))
ok('чужая отметка (другое значение) — не этап 08: карты долой', RM.optimise(foreign, 1024, 82, material=RULE_M)[1]['maps_out'] == 0)
ok('правило без stage_mark отметки не требует: старая модель сохраняет карты (прежний T-10/1)', RM.optimise(old, 1024, 82, material=RULE)[1]['maps_out'] == 4)
ok('keep=false сильнее отметки: у модели этапа 08 карты долой', RM.optimise(new, 1024, 82, material={**RULE_M, 'keep': False})[1]['maps_out'] == 0)
ok('drop_mr=False — прямое указание: карты есть и у старой', RM.optimise(old, 1024, 82, drop_mr=False, material=RULE_M)[1]['maps_out'] == 4)
ok('stage_passed: отметка, нет отметки, чужая, extras не словарь, правило без stage_mark',
   RM.stage_passed(RM.parse_glb(new)[0], RULE_M) and not RM.stage_passed(RM.parse_glb(old)[0], RULE_M) and not RM.stage_passed(RM.parse_glb(foreign)[0], RULE_M)
   and not RM.stage_passed({'asset': {'extras': 'x'}}, RULE_M) and RM.stage_passed({}, RULE))
# отпечаток: метка карт — только там, где карты РЕАЛЬНО остаются (этап 08 + карты); старые модели не перевыпускаются без нужды
rule_m = {'max_bytes': 100, 'texture': TEX, 'ladder': [], 'material': RULE_M}
rcp = 'size=1024;q=82;simplify=0'
ok('отпечаток: модель этапа 08 с картами — метка есть; старая с картами — рецепт прежний; этап 08 без карт — прежний',
   RM.recipe_for(new, rcp, rule_m) != rcp and RM.recipe_for(old, rcp, rule_m) == rcp and RM.recipe_for(source_glb(with_maps=False, mark={SM['key']: SM['value']}), rcp, rule_m) == rcp)
ok('keeps_material_maps: да / нет / нет / нет (мусор вместо GLB)', RM.keeps_material_maps(new, rule_m) and not RM.keeps_material_maps(old, rule_m) and not RM.keeps_material_maps(new, {'material': {'keep': False}}) and not RM.keeps_material_maps(b'not a glb', rule_m))
with tempfile.TemporaryDirectory() as d8:
    def bad_mark(name, mark):
        p = os.path.join(d8, name)
        json.dump({'max_bytes': 100, 'texture': TEX, 'ladder': [], 'material': {**RULE, 'stage_mark': mark}}, open(p, 'w'))
        try:
            RM.weight_rule(p)
            return False
        except ValueError:
            return True
    ok('stage_mark без key / пустое value / не словарь — ошибка правила', bad_mark('m1.json', {'value': 'x'}) and bad_mark('m2.json', {'key': 'k', 'value': ''}) and bad_mark('m3.json', 'x'))
code8 = open(os.path.join(HERE, '..', 'runtime_mesh.py'), encoding='utf-8').read()
ok('в коде сборки нет литерала отметки (ни «remlab_stage», ни «08-material»): они в правиле', 'remlab_stage' not in code8 and '08-material' not in code8)

print('\nвсе проверки прошли' if not FAILS else f'\nПРОВАЛЕНО: {len(FAILS)}')
sys.exit(1 if FAILS else 0)
