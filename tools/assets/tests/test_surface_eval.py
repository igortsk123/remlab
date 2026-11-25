#!/usr/bin/env python3
"""Мерка «по поверхностям» (tools/assets/surface_eval.py, T-20261124-65) БЕЗ сети, браузера и товаров: синтетический ящик с текстурой.
«Фото» = кадр камеры ящика (камера пересчитана в кадр-квадрат вокруг силуэта, как у конвейера). Проверяет: та же раскраска — ΔE ≈ 0 по всем поверхностям; чужой цвет на боку — ΔE бока большой
(перёд и верх — малые); бок, которого на фото нет (камера прямо), — «не измерено», а не «прошло»; зад сравнивается с полосой бока (ref); классы по нормали; разброс повтора нулевой;
в коде нет ID товаров и чисел порогов (они в data/flat3d/surface-eval.json). Запуск: python tools/assets/tests/test_surface_eval.py   (numpy + scipy + Pillow + OpenCV + trimesh)"""
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, '..')
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, ASSETS)
sys.path.insert(0, os.path.join(ROOT, 'tools', 'scout', 'salad', 'trellis'))
sys.path.append(os.path.join(ROOT, 'tools', 'scout'))
import numpy as np  # noqa: E402
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_surface_eval')
import surface_eval as SU  # noqa: E402
import pose_fit as PF  # noqa: E402
from PIL import Image  # noqa: E402

R = SU.load_rules()
FAIL = 0
TMPD = os.environ.get('REMLAB_TMP') or os.environ.get('TMPDIR') or '.'


def ok(cond, name):
    global FAIL
    print(('  ✓ ' if cond else '  ✗ ') + name)
    FAIL += 0 if cond else 1


# 1. классы по нормали (нормали смотрят в камеру; h — направление на камеру фото)
h = np.array([0.0, 1.0])                                              # камера на +Z
N = np.array([[0, 1, 0], [0, 0, 1], [1, 0, 0], [-1, 0, 0], [0, 0, -1], [0, -1, 0], [0.5, 0.0, 0.866]], float)
cl = SU.classify(N, h, R)
ok(cl.tolist() == [0, 1, 3, 2, 4, -1, 1] or cl.tolist() == [0, 1, 2, 3, 4, -1, 1], f'верх / перёд / бока / зад / низ / косой перёд: {cl.tolist()}')
ok(cl[2] != cl[3] and {cl[2], cl[3]} == {2, 3}, 'два бока — разные классы (по знаку угла)')

# 2. цвет: взвешенная медиана и ΔE
rgb = np.array([[200, 60, 60]] * 90 + [[10, 10, 10]] * 10, np.uint8)
lab_a = SU.lab_med(rgb, np.ones(100))
lab_b = SU.lab_med(np.array([[200, 60, 60]] * 5, np.uint8))
ok(SU.delta(lab_a, lab_b)['dE'] < 1.0, 'медиана — не среднее: 10 % тёмных пикселей цвет поверхности не меняют')
red = SU.lab_med(np.array([[200, 60, 60]], np.uint8))
V = R['verdict']


def lch(L, C, h):
    return np.array([L, C * math.cos(math.radians(h)), C * math.sin(math.radians(h))])


# вердикт по оттенку (чистая арифметика Lab, без ящика)
dv = SU.decide(lch(75, 28, 60), lch(75, 14, 60), lch(75, 28, 60), V)
ok(not dv['flag'] and dv['kind'] == 'цвет' and dv['dh'] < 1.0 and abs(dv['dC_rel'] - 0.5) < 0.02, f'тот же оттенок, вдвое насыщеннее бледного: нет ⚑ (Δh {dv["dh"]}°, ΔC/C {dv["dC_rel"]})')
dv = SU.decide(lch(70, 30, 60 + V['dh_deg'] + 40), lch(70, 30, 60), lch(70, 30, 60 + V['dh_deg'] + 40), V)
ok(dv['flag'] and dv['kind'] == 'цвет' and abs(dv['dh'] - (V['dh_deg'] + 40)) < 0.5, f'другой оттенок (Δh {dv["dh"]}° > порога {V["dh_deg"]}°) при C > C_min: ⚑')
dv = SU.decide(lch(45, 2, 200), lch(60, 2, 10), lch(45, 2, 200), V)
ok(not dv['flag'] and dv['kind'] == 'нейтр.' and dv['dh'] is None, 'нейтральный серый против серого другой яркости (и «оттенка» другого — шум): нет ⚑')
dv = SU.decide(lch(40, 13, 60), lch(40, 6, 60), lch(40, 13, 60), V)
ok(not dv['flag'] and dv['kind'] == 'цвет↔нейтр.', 'чуть цветной (C ниже c_clear) против нейтрального: нет ⚑')
dv = SU.decide(lch(60, 30, 355), lch(60, 30, 5), lch(60, 30, 355), V)
ok(abs(dv['dh'] - 10.0) < 0.5 and not dv['flag'], f'угол через 0°: 355° и 5° — Δh {dv["dh"]}°, не 350°')
dv = SU.decide(lch(19, 0.7, 10), lch(40, 18, 105), lch(40, 18, 105), V)                  # вся поверхность — тёмная рама, полоса — сиденье, и модель в пикселях полосы верна
ok(dv['mismatch_whole'] and not dv['mismatch_vis'] and not dv['flag'], 'поверхность из двух деталей, пиксели полосы верные: по всей поверхности расходится, ⚑ нет')
dv = SU.decide(lch(54, 76, 40), lch(76, 8, 40), lch(54, 76, 40), V)
ok(dv['mismatch_whole'] and dv['mismatch_vis'] and dv['gloss'] and not dv['flag'], 'блик на фото (светлее, C полосы ≪ C модели): «глянец?» вместо ⚑')
dv = SU.decide(lch(70, 76, 40), lch(76, 8, 40), lch(70, 76, 40), V)
ok(dv['flag'] and not dv['gloss'], 'фото светлее лишь немного — это не блик, ⚑ остаётся')
dv = SU.decide(lch(60, 30, 20), lch(60, 30, 20), None, V)
ok(not dv['flag'] and 'mismatch_vis' not in dv, 'копия бока (пикселей полосы нет): решает вся поверхность, ключей полосы нет')
rt = SU.lab_med(np.array([SU.lab_to_rgb(red)], np.uint8))
ok(SU.delta(red, rt)['dE'] < 1.5, f'Lab → sRGB → Lab возвращает цвет (образцы на кадрах не врут): ΔE {SU.delta(red, rt)["dE"]}')
dd = SU.delta(red - np.array([15.0, 0, 0]), red)
ok(dd['dEab'] == 0.0 and abs(dd['dL'] + 15.0) < 1e-6 and dd['dE'] >= 15.0, f'ΔE_ab не видит яркость, ΔE и ΔL — видят: {dd}')
w = np.array([1.0] * 5 + [100.0] * 5)
ok(abs(SU.lab_med(np.array([[255, 255, 255]] * 5 + [[0, 0, 0]] * 5, np.uint8), w)[0]) < 1, 'вес площади: тяжёлая половина определяет медиану')


# 3. сквозной прогон на синтетическом ящике
def box_glb(path, bands):
    """Ящик (1 × 0,6 × 0,6) из 12 граней с отдельными вершинами; цвет по оси нормали: полосы текстуры по u (ось x, y, z), v одинаков — ориентация v не важна."""
    import trimesh
    from trimesh.visual import TextureVisuals
    from trimesh.visual.material import PBRMaterial
    b = trimesh.creation.box(extents=(1.0, 0.6, 0.6))
    V, UV = [], []
    for tri in b.faces:
        p = b.vertices[tri]
        nrm = np.cross(p[1] - p[0], p[2] - p[0])
        ax = int(np.argmax(np.abs(nrm)))
        V.extend(p.tolist())
        UV.extend([[(ax + 0.5) / 3.0, 0.5]] * 3)
    tex = np.zeros((16, 48, 3), np.uint8)
    for ax in range(3):
        tex[:, ax * 16:(ax + 1) * 16] = bands[ax]
    m = trimesh.Trimesh(vertices=np.array(V), faces=np.arange(len(V)).reshape(-1, 3), process=False)
    m.visual = TextureVisuals(uv=np.array(UV), material=PBRMaterial(baseColorTexture=Image.fromarray(tex)))
    m.export(path)


def photo_of(glb, cam, photo_path, check_path, n=512):
    """«Фото» = кадр камеры cam (n×n) модели glb; камера пересчитана в квадрат вокруг силуэта (cx' = (n·cx − x0)/side, f' = n·f/side) — как её хранит 06-visible/check.json."""
    geo = SU.load_geo(glb)
    r = PF.render_persp(geo, cam, n)
    rgbp = SU.texel(geo['tex'], r['uv'])
    img = np.zeros((n, n, 4), np.uint8)
    img[..., :3] = rgbp
    img[..., 3] = np.where(r['mask'], 255, 0)
    Image.fromarray(img).save(photo_path)
    cv = SU.photo_canvas_of(photo_path, R['canvas_margin'])
    c2 = dict(cam, cx=(n * cam['cx'] - cv['x0']) / cv['side'], cy=(n * cam['cy'] - cv['y0']) / cv['side'], f=n * cam['f'] / cv['side'])
    json.dump({'extra': {'camera': c2}}, open(check_path, 'w'))


A = [(200, 60, 60), (60, 200, 60), (60, 60, 200)]                         # x-грани красные, y (верх) зелёные, z синие
B = [(60, 60, 60), (60, 200, 60), (60, 60, 200)]                          # то же, но бока (x) серые — «чужой цвет на боку»
cam = {'az': 30.0, 'el': 15.0, 'd': 3.0, 'f': 2.6, 'cx': 0.5, 'cy': 0.5}
ga, gb = os.path.join(TMPD, 'surf-a.glb'), os.path.join(TMPD, 'surf-b.glb')
photo, chk = os.path.join(TMPD, 'surf-photo.png'), os.path.join(TMPD, 'surf-check.json')
box_glb(ga, A)
box_glb(gb, B)
photo_of(ga, cam, photo, chk)
good = SU.measure_item({'glb': ga, 'photo': photo, 'check06': chk}, R)
bad = SU.measure_item({'glb': gb, 'photo': photo, 'check06': chk}, R)
ok(good['registration']['ok'], f"синтетическое фото легло на модель: IoU {good['registration']['iou']}")
s = good['surfaces']
ok({'перёд', 'бок', 'верх'} <= set(s), f'у ящика под углом 30° измерены перёд, бок, верх: {sorted(s)}')
ok(all(d['dE'] < 3.0 for k, d in s.items() if k != 'зад'), f"та же раскраска — ΔE малые (зад не берём: у ящика он синий, а правило сравнивает его с полосой бока): {({k: d['dE'] for k, d in s.items()})}")
ok(all(d['n_strip'] > R['regions']['min_px'] for d in s.values()), 'число пикселей полосы возвращается и больше порога')
sb = bad['surfaces']
ok(sb['бок']['flag'] and sb['бок']['kind'] == 'цвет↔нейтр.' and sb['бок']['mismatch_whole'], f"чужой цвет на боку (серый вместо красного): метка есть, {sb['бок']['kind']}, C {sb['бок']['C_photo']} → {sb['бок']['C_model']}")
ok(sb['перёд']['dE'] < 3.0 and sb['верх']['dE'] < 3.0 and not sb['перёд']['flag'] and not sb['верх']['flag'], 'перёд и верх при этом не тронуты')
ok(sb['бок']['mismatch_vis'] and sb['бок']['dE_vis'] > sb['бок']['dEab'] / 2, f"«в тех же пикселях полосы» тоже видно: dE_vis {sb['бок']['dE_vis']}")

# T-20261125-73 и /2: ⚑ — по оттенку (Δh), яркость и насыщенность в метку не входят
red_lab = SU.lab_med(np.array([[200, 60, 60]], np.uint8))
dark_rgb = SU.lab_to_rgb(red_lab - np.array([15.0, 0, 0]))                  # тот же цвет, темнее на 15 L (тень на боку фото)
grey_rgb = SU.lab_to_rgb(np.array([red_lab[0], 0.0, 0.0]))                  # серый той же яркости, другая цветность («чужой цвет»)
gc, gd = os.path.join(TMPD, 'surf-c.glb'), os.path.join(TMPD, 'surf-d.glb')
box_glb(gc, [dark_rgb, A[1], A[2]])
box_glb(gd, [grey_rgb, A[1], A[2]])
dark = SU.measure_item({'glb': gc, 'photo': photo, 'check06': chk}, R)['surfaces']['бок']
grey = SU.measure_item({'glb': gd, 'photo': photo, 'check06': chk}, R)['surfaces']['бок']
ok(not dark['flag'] and dark['dh'] < V['dh_deg'] / 4 and 12.0 < -dark['dL'] < 18.0 and dark['dE'] >= 12.0,
   f"тот же цвет темнее на 15 L: без ⚑ (Δh {dark['dh']}°, ΔL {dark['dL']}; по прежнему правилу «ΔE ≥ 12» был бы ⚑: ΔE {dark['dE']})")
ok(grey['flag'] and grey['kind'] == 'цвет↔нейтр.' and abs(grey['dL']) < 3.0,
   f"серый бок той же яркости, другая цветность: ⚑ ({grey['kind']}, ΔE_ab {grey['dEab']}, ΔL {grey['dL']})")


def side_case(photo_side, model_side):
    """Ящик-«фото» с боком photo_side (Lab) и ящик-модель с боком model_side; остальные грани те же. → измерение «бока»."""
    gp, gm = os.path.join(TMPD, 'surf-p.glb'), os.path.join(TMPD, 'surf-m.glb')
    ph, ck = os.path.join(TMPD, 'surf-pp.png'), os.path.join(TMPD, 'surf-pc.json')
    box_glb(gp, [SU.lab_to_rgb(photo_side), A[1], A[2]])
    box_glb(gm, [SU.lab_to_rgb(model_side), A[1], A[2]])
    photo_of(gp, cam, ph, ck)
    got = SU.measure_item({'glb': gm, 'photo': ph, 'check06': ck}, R)['surfaces']['бок']
    for p in (gp, gm, ph, ck):
        os.remove(p)
    return got


t = side_case(lch(75, 14, 60), lch(75, 28, 60))
ok(not t['flag'] and t['kind'] == 'цвет' and t['dC_rel'] > 0.3 and t['dh'] < V['dh_deg'] / 2, f"ящик: тот же оттенок, вдвое насыщеннее бледного — нет ⚑ (Δh {t['dh']}°, ΔC/C {t['dC_rel']}, ΔE_ab {t['dEab']})")
t = side_case(lch(70, 30, 40), lch(70, 30, 40 + V['dh_deg'] + 50))
ok(t['flag'] and t['dh'] >= V['dh_deg'], f"ящик: другой оттенок — ⚑ (Δh {t['dh']}°)")
t = side_case(lch(60, 1, 90), lch(45, 1, 270))
ok(not t['flag'] and t['kind'] == 'нейтр.' and t['dL'] < -10, f"ящик: серый против серого другой яркости — нет ⚑ ({t['kind']}, ΔL {t['dL']})")
cf = os.path.join(TMPD, 'surf-frame.png')
fd = SU.cal_frame({'glb': gd, 'photo': photo, 'check06': chk}, R, 'бок', cf, 'тест')
ok(os.path.getsize(cf) > 2000 and fd['flag'] and Image.open(cf).size[0] > 600, 'кадр калибровки (фото | модель | образцы) рисуется и совпадает с измерением')
for p in (gc, gd, cf):
    os.remove(p)
ok('зад' not in s or s['зад']['ref'] == R['back_ref'], f"зад (его на фото нет) сравнён с полосой бока: ref={s.get('зад', {}).get('ref')}")
ok(sb['бок-2']['flag'] and sb['бок-2']['ref'] == 'бок', 'скрытый бок: цвет модели против полосы видимого бока')

# камера прямо спереди: бока на фото нет — «не измерено» с причиной, не «прошло»
cam0 = dict(cam, az=0.0, el=3.0)
photo0, chk0 = os.path.join(TMPD, 'surf-photo0.png'), os.path.join(TMPD, 'surf-check0.json')
photo_of(ga, cam0, photo0, chk0)
fr = SU.measure_item({'glb': ga, 'photo': photo0, 'check06': chk0}, R)
um = {u['what']: u['reason'] for u in fr['unmeasured']}
ok('бок' not in fr['surfaces'] and 'бок' in um and 'нет полосы' in um['бок'], f"камера прямо: бок — «не измерено»: {um.get('бок')}")
ok('перёд' in fr['surfaces'] and fr['surfaces']['перёд']['dE'] < 3.0, 'перёд измерен')

# свод, таблица, разброс
ev = {'abc12345': dict(bad, id='abc12345', type='шкаф'), 'def67890': dict(fr, id='def67890', type='комод')}
sm = SU.summary(ev, R)
ok(sm['by_surface']['бок']['n_flagged'] == 1 and sm['unmeasured_by_surface'].get('бок') == 1, f"свод: флагов бока {sm['by_surface']['бок']['n_flagged']}, не измерено {sm['unmeasured_by_surface'].get('бок')}")
tb = SU.table_md(ev, R, SU.spread(ev, json.loads(json.dumps(ev))))
ok('abc12345' in tb and '⚑' in tb and 'нет полосы' in tb and 'Разброс повтора' in tb, 'таблица: Δh · ΔC/C · ΔE_ab (px) ⚑, причины «не измерено», разброс')
ok('ΔL' in tb and 'Δh мед.' in tb and 'ΔC/C' in tb and sm['by_surface']['бок']['dEab_median'] > 0 and sm['by_surface']['бок']['n_gloss'] == 0, 'таблица: ΔL отдельной таблицей «для сведения», свод с Δh, ΔC/C, ΔE_ab, глянцем')
cp = sm['copy_of_side']
ok(cp['measured'] >= 1 and cp['n_flagged'] >= 1 and 'зад' not in sm['by_surface'], f"свод: зад/бок-2 с ref:бок — отдельной строкой «копия бока» ({cp['measured']}), не в своих ⚑")
ok('копия' in tb, 'таблица помечает копии бока')
ok(SU.spread(ev, json.loads(json.dumps(ev)))['max_dE'] == 0.0, 'повтор тех же входов — нулевой разброс')
for p in (ga, gb, photo, chk, photo0, chk0):
    os.remove(p)

# 4. правила: ID товаров и числа порогов в коде нет
src = open(os.path.join(ASSETS, 'surface_eval.py'), encoding='utf-8').read()
ok(not re.search(r'\b\d{5,6}_\d{10,}\b', src), 'в коде мерки нет ID товаров')
ok(V['dh_deg'] > 0 and V['c_min'] > 0 and V['c_clear'] >= V['c_min'] and 'flags' not in R and R['regions']['min_px'] > 0 and R['registration']['iou_min'] > 0, 'пороги — в data/flat3d/surface-eval.json')

print('FAIL', FAIL)
sys.exit(1 if FAIL else 0)
