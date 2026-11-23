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
ok(P.judge(m, R)['status'] == 'soft', 'мягкая мерка: готов с пометкой')
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
ok(c['status'] == 'ok' and os.path.exists(p('out/surface.json')), 'classify пишет surface.json')

# 7б. «светлее фото»: нет фото / нет растра камеры → na (не «ок»); судья берёт долю и порог из paint-fill.json
ok(P.lighter_than_photo(p('good.glb'), None, None, R)['status'] == 'na', 'нет фото → na')
ok(P.lighter_than_photo(p('good.glb'), p('k_top.png'), p('нет-такой-папки'), R)['status'] == 'na', 'нет растра камеры → na, не «ок»')
mm = P.measure(p('good.glb'), p('k_top.png'), None, R)
ok(mm['lighter_than_photo']['status'] == 'na' and 'lighter_than_photo' not in P.judge(mm, R)['hard_failed'], 'na в судью не идёт')
for share, want in ((0.05, 'ok'), (3.5, 'refused')):
    mm2 = dict(mm, lighter_than_photo={'status': 'ok', 'share_pct': share, 'inner_px': 1000, 'spot_px': 1, 'threshold': ['<=', 0.2]})
    ok(P.judge(mm2, R)['status'] == want, f'доля пятен {share} % → {want}')
ok('timing_s' in mm and {'load', 'top_vs_photo', 'group_bleed'} <= set(mm['timing_s']), 'время по меркам записано (для расчёта на 50k)')

# 7в. класс каталога — подсказка: расхождение с геометрией → флаг role_mismatch (в гейт не идёт)
m = P.measure(p('good.glb'), p('k_top.png'), None, R, None, None, 'стол обеденный')
ok(m['role_mismatch']['flag'] is False and m['role_mismatch']['has_top'], 'стол с плоским верхом: класс и геометрия сходятся')
m = P.measure(p('good.glb'), p('k_top.png'), None, R, None, None, 'кресло')
ok(m['role_mismatch']['flag'] is True and 'не из списка' in m['role_mismatch']['why'], 'верх есть, класс «кресло» → флаг role_mismatch')
ok(P.judge(m, R)['status'] == 'ok' and 'role_mismatch' not in P.judge(m, R)['hard_failed'], 'флаг role_mismatch в гейт не идёт')
ok(P.measure(p('good.glb'), p('k_top.png'), None, R)['role_mismatch']['flag'] is False, 'класс не передан — флага нет')

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
