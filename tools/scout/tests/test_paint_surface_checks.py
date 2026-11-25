#!/usr/bin/env python3
"""Мерки паспорта типа этапа 9 (T-20261123-19/1): синтетические столы-квадраты в временной папке, ID товаров нет.
Случаи: правильный верх; серый верх с узким известным кусочком фото; верх не виден на фото (na); честный графит (серый и на фото — не пустой вид);
затёк цвета одной группы в другую (залитые тексели) и тот же цвет в известных с фото (не дефект); класс каталога на результат не влияет; настоящие правила целы.
Запуск: python tools/scout/tests/test_paint_surface_checks.py   (нужны numpy, pillow, trimesh, scipy)"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'assets'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_paint_surface_checks')
import numpy as np  # noqa: E402
import paint_surface_checks as P  # noqa: E402
import trimesh  # noqa: E402
from PIL import Image  # noqa: E402

R = P.rules()
W = 512
FAIL = 0
WOOD, WHITE, GREY = (200, 160, 110), (235, 235, 230), (128, 128, 128)


def ok(cond, name):
    global FAIL
    print(('  ✓ ' if cond else '  ✗ ') + name)
    FAIL += 0 if cond else 1


def uvr(x0, y0, x1, y1):
    """Углы прямоугольника атласа (пиксели) → UV (V вверх)."""
    return [(x0 / (W - 1), 1 - y0 / (W - 1)), (x0 / (W - 1), 1 - y1 / (W - 1)), (x1 / (W - 1), 1 - y1 / (W - 1)), (x1 / (W - 1), 1 - y0 / (W - 1))]


TOP_BOX = (20, 20, 300, 300)
LEG_BOX = (330, 20, 500, 280)


def make_table(path, top_fill, leg_fill, mr_flat=False, spot=None):
    """Стол из двух квадратов: верх (нормаль вверх) и один вертикальный лист. Атлас W×W: верх и «ножка» в своих прямоугольниках. spot=(rect, цвет) — пятно на верх."""
    V = np.array([(0, 1, 0), (0, 1, 2), (2, 1, 2), (2, 1, 0), (0, 0, 0), (0, 1, 0), (2, 1, 0), (2, 0, 0)], float)
    F = np.array([(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7)])
    uv = np.array(uvr(*TOP_BOX) + uvr(*LEG_BOX))
    alb = np.full((W, W, 3), 60, np.uint8)
    rng = np.random.default_rng(0)
    for box, fill in ((TOP_BOX, top_fill), (LEG_BOX, leg_fill)):
        x0, y0, x1, y1 = box
        alb[y0:y1 + 1, x0:x1 + 1] = np.clip(np.array(fill) + rng.integers(-1, 2, (y1 - y0 + 1, x1 - x0 + 1, 3)), 0, 255)
    if spot:
        (x0, y0, x1, y1), col = spot
        alb[y0:y1, x0:x1] = col
    mr = np.full((W, W, 3), (0, 200, 0), np.uint8)
    if mr_flat:
        mr[...] = (0, 128, 128)
    mat = trimesh.visual.material.PBRMaterial(baseColorTexture=Image.fromarray(alb), metallicRoughnessTexture=Image.fromarray(mr))
    m = trimesh.Trimesh(V, F, visual=trimesh.visual.TextureVisuals(uv=uv, material=mat), process=False)
    m.export(path)
    return alb


def known_png(path, rects):
    k = np.zeros((W, W), np.uint8)
    for x0, y0, x1, y1 in rects:
        k[y0:y1, x0:x1] = 255
    Image.fromarray(k).save(path)


def parts_npz(path, top_id=0, leg_id=1):
    np.savez(path, part=np.array([top_id, top_id, leg_id, leg_id]))


d = tempfile.mkdtemp(prefix='surf_')
p = lambda n: os.path.join(d, n)  # noqa: E731

# 1. правильный верх: цвет итога = цвет известного куска фото
make_table(p('good.glb'), WOOD, WHITE)
known_png(p('k_top.png'), [(20, 20, 300, 120)])
m = P.measure(p('good.glb'), p('k_top.png'), None, R)
t = m['top_vs_photo']
ok(t['status'] == 'ok' and t['dE00'] < 3, f"верх как на фото: ΔE00 {t.get('dE00')} (< 3)")
ok(m['empty_flat']['status'] == 'ok' and m['empty_flat']['empty_pct'] == 0, 'цветной верх — не пустой вид')
j = P.judge(m, R)
ok(j['status'] == 'ok', f"судья: ok ({j['status']})")

# 2. серый верх: известен только узкий кусок фото (цвет дерева), остальной верх — серый ≈128
alb = make_table(p('grey.glb'), GREY, WHITE, mr_flat=True)
alb[20:50, 20:301] = WOOD                                   # узкий кусок верха — «видно с фото»
trimesh_scene = trimesh.load(p('grey.glb'), force='scene', process=False)
g = list(trimesh_scene.geometry.values())[0]
g.visual.material.baseColorTexture = Image.fromarray(alb)
g.export(p('grey.glb'))
known_png(p("k_grey.png"), [(20, 20, 300, 50)])
m = P.measure(p('grey.glb'), p('k_grey.png'), None, R)
t = m['top_vs_photo']
ok(t['status'] == 'ok' and t['dE00'] > 15, f"серый верх против фото: ΔE00 {t.get('dE00')} > 15")
ok(m['empty_flat']['status'] == 'ok' and m['empty_flat']['empty_pct'] > R['empty_flat']['threshold'][1], f"серая плоскость расходится с фото: {m['empty_flat'].get('empty_pct')} %")
j = P.judge(m, R)
ok(j['status'] == 'refused' and 'top_vs_photo' in j['hard_failed'] and 'empty_flat' in j['hard_failed'], f"судья: отказ по верху и пустому виду {j['hard_failed']}")

# 3. верх не виден на фото: известных текселей на верхе нет → na, не отказ
known_png(p('k_none.png'), [(330, 20, 500, 280)])           # известна только ножка
m = P.measure(p('good.glb'), p('k_none.png'), None, R)
ok(m['top_vs_photo']['status'] == 'na' and 'не виден' in m['top_vs_photo']['why'], 'верх не виден на фото → na')
ok(P.judge(m, R)['status'] == 'ok', 'na не блокирует')
m = P.measure(p('good.glb'), None, None, R)
ok(m['top_vs_photo']['status'] == 'na', 'нет known.png → na, а не «ок»')

# 4. честный графит: серый и на фото тоже (известный кусок того же серого) — не пустой вид
make_table(p('graphite.glb'), GREY, WHITE, mr_flat=True)
m = P.measure(p('graphite.glb'), p('k_top.png'), None, R)
ok(m['empty_flat']['empty_pct'] == 0 and any(x.get('grey_flat') and not x.get('disagrees') for x in m['empty_flat']['parts']), 'серый и на фото — честный серый, не пустой вид')

# 5. затёк: на белой «ножке» пятно цвета дерева; в ЗАЛИТЫХ текселях — дефект, в известных с фото — нет
SPOT = ((340, 40, 400, 100), WOOD)
make_table(p('bleed.glb'), WOOD, WHITE, spot=SPOT)
parts_npz(p('parts.npz'))
known_png(p('k_none2.png'), [(20, 20, 300, 120)])
m = P.measure(p('bleed.glb'), p('k_none2.png'), p('parts.npz'), R)
gb = m['group_bleed']
ok(gb['status'] == 'ok' and gb['groups_source'] == 'parts' and gb['value_pct'] > R['group_bleed']['threshold'][1], f"затёк в залитых текселях: {gb.get('value_pct')} % > порога")
ok(gb['pairs'] and gb['pairs'][0]['B'] == 0 and gb['pairs'][0]['A'] == 1, 'найдено, кто в кого затёк: ножка ← верх')
ok('group_bleed' in P.judge(m, R)['soft_failed'] and 'group_bleed' not in P.judge(m, R)['hard_failed'], 'мягкая мерка затёка: пометка, не отказ (зад с пятном при этом ещё и не одним тоном — это жёсткая мерка тона)')
known_png(p('k_leg.png'), [(330, 20, 500, 280)])            # ножка с пятном — известна с фото: пятно настоящее
m = P.measure(p('bleed.glb'), p('k_leg.png'), p('parts.npz'), R)
ok(m['group_bleed']['value_pct'] == 0, f"то же пятно в известных с фото — не затёк ({m['group_bleed']['value_pct']})")
make_table(p('clean.glb'), WOOD, WHITE)
m = P.measure(p('clean.glb'), p('k_none2.png'), p('parts.npz'), R)
ok(m['group_bleed']['value_pct'] == 0, 'чистые группы — нет затёка')
m = P.measure(p('clean.glb'), p('k_none2.png'), None, R)
ok(m['group_bleed']['groups_source'] == 'geometry', 'нет parts08 — группы по геометрии (запасной путь)')

# 6. класс каталога на результат не влияет: мерка принимает только GLB, known, parts
import inspect  # noqa: E402
ok(list(inspect.signature(P.measure).parameters)[:3] == ['glb', 'known_png', 'parts_path'], 'роль каталога в мерку не передаётся (геометрия решает)')

# 7. упавший сторож — не «ок»; нет GLB — не «ок»
bad = P.classify(p('clean.glb'), None, None, fn=lambda *a: 1 / 0)
ok(bad['status'] == 'missing' and 'упали' in bad['reason'], 'сбой мерки → missing')
ok(P.classify(None, None, None)['status'] == 'missing', 'нет GLB → missing')
c = P.classify(p('good.glb'), p('k_top.png'), None, out_dir=p('out'))
ok(c['status'] == 'missing' and os.path.exists(p('out/surface.json')), 'classify пишет surface.json; без фото палитры нет → не измерено (missing)')

# 7б. «светлее фото»: нет фото / нет растра камеры → na (не «ок»); судья берёт долю и порог из paint-fill.json
ok(P.lighter_than_photo(p('good.glb'), None, None, R)['status'] == 'na', 'нет фото → na')
ok(P.lighter_than_photo(p('good.glb'), p('k_top.png'), p('нет-такой-папки'), R)['status'] == 'na', 'нет растра камеры → na, не «ок»')
mm = P.measure(p('good.glb'), p('k_top.png'), None, R)
ok(mm['lighter_than_photo']['status'] == 'na' and 'lighter_than_photo' not in P.judge(mm, R)['hard_failed'], 'na в судью не идёт')
for share, want in ((0.05, 'ok'), (3.5, 'refused')):
    mm2 = dict(mm, lighter_than_photo={'status': 'ok', 'share_pct': share, 'inner_px': 1000, 'spot_px': 1, 'threshold': ['<=', 0.2]})
    ok(P.judge(mm2, R)['status'] == want, f'доля пятен {share} % → {want}')
ok('timing_s' in mm and {'load', 'top_vs_photo', 'group_bleed'} <= set(mm['timing_s']), 'время по меркам записано (для расчёта на 50k)')

# 7а. кадры срабатываний: верх и затёк подсвечены, файлы ≤ max_kb
fr = P.frames(p('bleed.glb'), p('k_none2.png'), p('parts.npz'), p('fr'))
ok('surface-top.jpg' in fr and 'surface-bleed.jpg' in fr, f'кадры верха и затёка записаны ({sorted(fr)})')
ok(all(os.path.getsize(v) <= R['frames']['max_kb'] * 1024 for v in fr.values()), 'кадры ≤ max_kb')
fr0 = P.frames(p('clean.glb'), p('k_none2.png'), p('parts.npz'), p('fr0'))
ok('surface-bleed.jpg' not in fr0, 'нет затёка — кадра затёка нет')

# 7г. верх не виден на фото совсем → цвет верха против ПАЛИТРЫ фото: серый на «деревянном» фото — далеко, дерево — рядом
photo_wood = np.full((64, 64, 4), 255, np.uint8)
photo_wood[8:56, 8:56, :3] = WOOD
photo_wood[8:56, 8:30, :3] = WHITE
Image.fromarray(photo_wood).save(p('photo.png'))
known_png(p('k_leg_only.png'), [(330, 20, 500, 280)])             # на верхе известных текселей нет
mg = P.measure(p('grey.glb'), p('k_leg_only.png'), None, R, p('photo.png'), None)
mw = P.measure(p('good.glb'), p('k_leg_only.png'), None, R, p('photo.png'), None)
ok(mg['top_vs_photo'].get('ref') == 'photo_palette' and mg['top_vs_photo']['dE00'] > R['top_vs_photo']['threshold'][1], f"серый верх vs палитра фото-дерево: dE00 {mg['top_vs_photo'].get('dE00')} > порога")
ok(mw['top_vs_photo'].get('ref') == 'photo_palette' and mw['top_vs_photo']['dE00'] < 3, f"деревянный верх входит в палитру: dE00 {mw['top_vs_photo'].get('dE00')}")
ok(P.judge(mg, R)['status'] == 'refused' and 'top_vs_photo' in P.judge(mg, R)['hard_failed'], 'серый верх вне палитры фото → отказ (мерка жёсткая)')

# 7в. класс каталога — подсказка: расхождение с геометрией → флаг role_mismatch (в гейт не идёт)
m = P.measure(p('good.glb'), p('k_top.png'), None, R, None, None, 'стол обеденный')
ok(m['role_mismatch']['flag'] is False and m['role_mismatch']['has_top'], 'стол с плоским верхом: класс и геометрия сходятся')
m = P.measure(p('good.glb'), p('k_top.png'), None, R, None, None, 'кресло')
ok(m['role_mismatch']['flag'] is True and 'не из списка' in m['role_mismatch']['why'], 'верх есть, класс «кресло» → флаг role_mismatch')
ok(P.judge(m, R)['status'] == 'ok' and 'role_mismatch' not in P.judge(m, R)['hard_failed'], 'флаг role_mismatch в гейт не идёт')
ok(P.measure(p('good.glb'), p('k_top.png'), None, R)['role_mismatch']['flag'] is False, 'класс не передан — флага нет')

# 7д. «один материал — один тон» верха и зада (T-20261123-32): мерится ВСЕГДА, против палитры фото; нет данных — «не измерено», а не «ок»
parts_npz(p('parts_tone.npz'))
mt = P.measure(p('good.glb'), p('k_top.png'), p('parts_tone.npz'), R, p('photo.png'), None)
ok(mt['top_tone']['status'] == 'ok' and mt['top_tone']['dev_share_pct'] <= R['tone']['top']['one_tone_max_pct'] and mt['top_tone']['off_palette_pct'] == 0, f"ровный верх цвета фото: один тон {mt['top_tone'].get('dev_share_pct')} %, мимо палитры {mt['top_tone'].get('off_palette_pct')} %")
ok(mt['back_tone']['status'] == 'ok', f"зад (лист ножки) измерен: {mt['back_tone'].get('status')}")
jt = P.judge(mt, R)
ok(jt['status'] == 'ok' and not jt['unmeasured'] and jt['metrics']['top_one_tone_pct']['ok'] is True, 'судья: ровный верх и зад проходят, всё измерено')
alb = make_table(p('patch.glb'), WOOD, WHITE)                    # лоскуты: половина верха — чужой тон (лоскуты/градиент: зерно усредняется, это нет)
alb[20:300, 160:301] = (90, 70, 50)
sc_ = list(trimesh.load(p('patch.glb'), force='scene', process=False).geometry.values())[0]
sc_.visual.material.baseColorTexture = Image.fromarray(alb)
sc_.export(p('patch.glb'))
mp = P.measure(p('patch.glb'), p('k_top.png'), p('parts_tone.npz'), R, p('photo.png'), None)
jp = P.judge(mp, R)
ok(mp['top_tone']['dev_share_pct'] > 30 and 'top_one_tone_pct' in jp['hard_failed'], f"лоскуты на верхе: {mp['top_tone'].get('dev_share_pct')} % не одним тоном → отказ {jp['hard_failed']}")
make_table(p('black.glb'), (25, 25, 25), WHITE)                  # чёрный верх при светлом дереве на фото: «чёрный металл» вместо материала товара
mb = P.measure(p('black.glb'), p('k_top.png'), p('parts_tone.npz'), R, p('photo.png'), None)
jb = P.judge(mb, R)
ok(mb['top_tone']['off_palette_pct'] > 90 and 'top_off_palette_pct' in jb['hard_failed'] and 'top_one_tone_pct' not in jb['hard_failed'], f"ровный чёрный верх мимо палитры фото: {mb['top_tone'].get('off_palette_pct')} % → отказ только по палитре")
mn = P.measure(p('good.glb'), p('k_top.png'), p('parts_tone.npz'), R, None, None)
jn = P.judge(mn, R)
ok(mn['top_tone']['off_palette_pct'] is None and 'top_off_palette_pct' in jn['unmeasured'] and jn['metrics']['top_off_palette_pct']['ok'] is None and 'error' in jn['metrics']['top_off_palette_pct'], 'нет фото → «не измерено» (error), не 0')
cn = P.classify(p('good.glb'), p('k_top.png'), p('parts_tone.npz'), photo=None)
ok(cn['status'] == 'missing' and 'не измерено' in cn['reason'], f"этап 9: не измерено → missing, не ready ({cn['status']})")
cg = P.classify(p('good.glb'), p('k_top.png'), p('parts_tone.npz'), photo=p('photo.png'))
ok(cg['status'] == 'ok', f"этап 9: всё измерено и в норме → ok ({cg['status']}: {cg['reason']})")
ok(P.judge({'top_vs_photo': {'status': 'na'}, 'empty_flat': {'status': 'na'}, 'group_bleed': {'status': 'na'}, 'top_tone': {'status': 'na', 'why': 'нет плоского верха по геометрии'}, 'back_tone': {'status': 'small', 'why': 'мало'}}, R)['unmeasured'] == [], 'нет верха по геометрии / сторона ничтожна → не блок')
ok(P.judge({'top_vs_photo': {'status': 'na'}, 'empty_flat': {'status': 'na'}, 'group_bleed': {'status': 'na'}, 'top_tone': {'status': 'unmeasured', 'why': 'x'}, 'back_tone': {'status': 'ok', 'dev_share_pct': 0.0, 'off_palette_pct': 0.0}}, R)['unmeasured'] == ['top_one_tone_pct', 'top_off_palette_pct'], 'большая сторона без измерения → не измерено')
ok(all(k in R['tone'][s] for s in ('top', 'back') for k in ('one_tone_max_pct', 'off_palette_max_pct', 'min_texels')) and R['tone']['dev_dE00'] > 0, 'пороги тона — в rules (paint-surface-checks.json → tone)')

# 7б. холодные пятна на белой опоре (T-20261124-57/4): ядро на массивах; в этой версии в кадрах круга 29 положительного примера нет — проверка держится на синтетике
CS = R['cold_spots']
THR = {'db_max': CS['db_max'], 'cold_share_max': CS['cold_share_max']}
ok(CS['enabled'] is False, 'cold_spots: по умолчанию выключена')
N = 6000
white_photo = np.tile(np.array([[236, 236, 234]], np.uint8), (N, 1))
r0 = P.cold_stats(white_photo, white_photo.copy(), CS, THR)
ok(r0['status'] == 'ok' and not r0['would_flag'] and r0['cold_share'] == 0.0, 'cold_spots: белое осталось белым → не метка')
cold = np.tile(np.array([[222, 232, 244]], np.uint8), (N, 1))                       # голубо-серое: b заметно ниже
r1 = P.cold_stats(white_photo, cold, CS, THR)
ok(r1['status'] == 'ok' and r1['would_flag'] and r1['db_median'] < -CS['db_max'], f'cold_spots: сплошь голубоватое на белой опоре → метка (Δb {r1["db_median"]})')
patch = white_photo.copy()
patch[: int(N * 0.12)] = cold[: int(N * 0.12)]                                        # пятна на 12 % белого: медиана ровная, доля холодных выше порога
r2 = P.cold_stats(white_photo, patch, CS, THR)
ok(r2['would_flag'] and abs(r2['db_median']) <= CS['db_max'] and r2['cold_share'] > CS['cold_share_max'], f'cold_spots: пятна на части белого ловит доля холодных ({r2["cold_share"]})')
warm = np.tile(np.array([[240, 234, 222]], np.uint8), (N, 1))                       # теплее фото — не «холодные пятна», но Δb большой по модулю
r3 = P.cold_stats(white_photo, warm, CS, THR)
ok(r3['status'] == 'ok' and r3['db_median'] > 0 and r3['cold_share'] == 0.0, 'cold_spots: потепление не считается холодным пятном (доля 0; метка — только по |медиане|)')
wood_photo = np.tile(np.array([[200, 160, 110]], np.uint8), (N, 1))
r4 = P.cold_stats(wood_photo, cold, CS, THR)
ok(r4['status'] == 'na' and not r4['would_flag'], 'cold_spots: на фото не белое (дерево) → na, не метка')
r5 = P.cold_stats(white_photo[:500], cold[:500], CS, THR)
ok(r5['status'] == 'na' and 'px' in r5['why'], 'cold_spots: белого мало → na с причиной')
r6 = P.cold_spots('/нет/glb', None, None, R)
ok(r6['status'] == 'na' and not r6['would_flag'], 'cold_spots: нет фото → na')

# 8. настоящие правила: пороги в данных, у каждой мерки есть порог и операция, ID товаров в правилах нет
ok(all(len(R[k]['threshold']) == 2 for k in ('top_vs_photo', 'group_bleed', 'empty_flat')), 'у трёх мерок есть (op, порог)')
txt = open(P.RULES, encoding='utf-8').read()
import re  # noqa: E402
ok(not re.search(r'\b\d{5,6}_\d{6,}\b', txt), 'в правилах нет ID товаров')
src = open(P.__file__, encoding='utf-8').read()
ok(not re.search(r'\b\d{5,6}_\d{6,}\b', src), 'в коде нет ID товаров')
ok(P.selftest() == 0, 'selftest модуля')
print('FAIL' if FAIL else 'ВСЁ ЗЕЛЁНОЕ', FAIL)
sys.exit(1 if FAIL else 0)
