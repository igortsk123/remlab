#!/usr/bin/env python3
"""Тесты сторожа покрытия под КАМЕРЫ ПРОГОНА StableGen (T-20261120-152/1): `tex_coverage.analyze(rig=…)` + `stablegen/sg_cams.py`.
Видимость считается по камерам из ДАННЫХ прогона (8 перспективных камер орбитального кольца: подъём, расстояние и кадр записаны в `cameras.json`/`status.json`), а не по константам MV-Adapter.
Синтетика, без видеокарты и сети: куб, куб с гранью внутри другого тела, кольцо снизу, две камеры, ортографическая камера, пересчёт кадра Blender → GLB, восстановление поз.
Пороги решения keep/repaint/reject — тот же словарь `THRESHOLDS`, что у MV-Adapter (проверяется: решение по тем же правилам). Нужны numpy.

  python3 tools/scout/salad/trellis/tests_tex_coverage_rig.py
"""
from __future__ import annotations

import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..', 'stablegen')))
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_tex_coverage_rig')
import numpy as np  # noqa: E402
import sg_cams as C  # noqa: E402
import tex_coverage as TC  # noqa: E402

bad = 0
GRID = 256


def ok(name, cond, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


class Scene:
    """Четырёхугольники; у каждого — своя плитка 4×4 в развёртке. Кадр GLB: Y вверх."""

    def __init__(self):
        self.V, self.F, self.UV = [], [], []
        self.tile = 0

    def quad(self, p0, p1, p2, p3):
        i, j = self.tile % 4, self.tile // 4
        u0, u1, v0, v1 = i / 4 + 0.01, (i + 1) / 4 - 0.01, j / 4 + 0.01, (j + 1) / 4 - 0.01
        o = len(self.V)
        self.V += [p0, p1, p2, p3]
        self.UV += [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
        self.F += [(o, o + 1, o + 2), (o, o + 2, o + 3)]
        self.tile += 1

    def box(self, lo, hi):
        x0, y0, z0 = lo
        x1, y1, z1 = hi
        for q in (((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)), ((x1, y0, z0), (x0, y0, z0), (x0, y1, z0), (x1, y1, z0)),
                  ((x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1)), ((x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)),
                  ((x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0)), ((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1))):
            self.quad(*q)

    def geoms(self):
        tex = np.full((GRID, GRID, 3), 128, np.uint8)
        tex[::2, ::2] = (150, 120, 100)                      # не «фон»: ни чёрный, ни белый
        return [{'V': np.array(self.V, np.float64), 'F': np.array(self.F, np.int64), 'UV': np.array(self.UV, np.float64), 'tex': tex}]


def ring(dist=2.0, centre=(0.0, 0.0, 0.0), rl=None):
    """Кольцо из 8 камер по правилам `rules/sg-cameras.json` → камеры в кадре GLB (как их получит сторож у прогона без записанных поз)."""
    status = {'framing': [{'cam': f'Camera_{i}', 'dist': dist} for i in range(8)]}
    doc = C.reconstruct(status, {'cameras': {'mode': 'orbit_ring', 'num': 8}}, C.centre_blender(list(centre)), rl)
    return doc, C.rig_glb(doc)


def tl(cls, k):
    """Плитка k карты классов (v вверх: плитки идут снизу вверх; поле 6 px от краёв)."""
    j, i = k // 4, k % 4
    return cls[(3 - j) * GRID // 4 + 6:(4 - j) * GRID // 4 - 6, i * GRID // 4 + 6:(i + 1) * GRID // 4 - 6]


def run(sc, rig, **kw):
    return TC.analyze(sc.geoms(), 0.0, GRID, 384, ext_n=26, rig=rig, **kw)


# ---------------------------------------------------------------- 1. сборка камер из данных прогона ---------------------
print('1. камеры прогона: восстановление, кадр Blender → GLB')
doc, rig = ring()
ok('кольцо: 8 камер, источник «reconstructed», перспектива 50 мм / сенсор 36', len(doc['cameras']) == 8 and doc['source'] == 'reconstructed'
   and all(c['type'] == 'PERSP' and c['lens'] == 50.0 for c in doc['cameras']))
el = [math.degrees(math.asin(-c['forward'][2])) for c in doc['cameras']]
ok('подъём камер — из правил (≈26°, смотрят вниз) и одинаков у всех', all(abs(e - 26.48) < 0.01 for e in el), el)
az = sorted(round(math.degrees(math.atan2(-c['forward'][1], -c['forward'][0])) % 360, 1) for c in doc['cameras'])
ok('азимуты — шаг 45° по кругу', all(abs((az[(i + 1) % 8] - az[i]) % 360 - 45.0) < 0.2 for i in range(8)), az)
ok('расстояние до центра у каждой — из status.json (2,0)', all(abs(math.dist(c['location'], [0, 0, 0]) - 2.0) < 1e-6 for c in doc['cameras']))
ok('режим камер не орбитальное кольцо → камер нет (None), а не догадка', C.reconstruct({'framing': []}, {'cameras': {'mode': 'fan', 'num': 8}}, [0, 0, 0]) is None)
ok('камер не 8 → None', C.reconstruct({'framing': [{'cam': 'Camera_0', 'dist': 2}]}, {'cameras': {'mode': 'orbit_ring', 'num': 6}}, [0, 0, 0]) is None)
ok('нет расстояний (status без framing) → None', C.reconstruct({}, {'cameras': {'mode': 'orbit_ring', 'num': 8}}, [0, 0, 0]) is None)
ok('центр формы неизвестен → None', C.reconstruct({'framing': [{'cam': f'Camera_{i}', 'dist': 2} for i in range(8)]}, {'cameras': {'mode': 'orbit_ring', 'num': 8}}, None) is None)
rec = {'type': 'PERSP', 'lens': 50, 'sensor_width': 36, 'name': 'Camera_0', 'location': [0, -2, 0], 'forward': [0, 1, 0], 'up': [0, 0, 1]}
g = C.rig_glb({'res': [1120, 1120], 'cameras': [rec]})[0]
ok('кадр Blender → GLB: камера «спереди» (0,−2,0) взгляд +Y → глаз (0,0,2), взгляд −Z, вверх +Y', np.allclose(g['eye'], [0, 0, 2]) and np.allclose(g['forward'], [0, 0, -1]) and np.allclose(g['up'], [0, 1, 0]), g)
g2 = C.rig_glb({'res': [1120, 1120], 'cameras': [{**rec, 'res': [800, 1200]}]})[0]
ok('у камеры свой кадр: 800×1200 → полуширина меньше полувысоты в 2/3, длинная сторона — по сенсору (0,36)', abs(g2['hy'] - 0.36) < 1e-9 and abs(g2['hx'] - 0.24) < 1e-9, g2)
try:
    C.rig_glb({'res': [1, 1], 'cameras': [{**rec, 'type': 'PANO'}]})
    ok('неизвестный тип камеры — ошибка', False)
except ValueError:
    ok('неизвестный тип камеры — ошибка (не гадаем)', True)
ok('сравнение поз: одинаковые — нулевое расхождение', C.compare(doc, doc, 1.0) == {'position_frac': 0.0, 'forward_deg': 0.0})

# ---------------------------------------------------------------- 2. куб ------------------------------------------------------
print('2. куб: что видит кольцо StableGen')
sc = Scene()
sc.box((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5))
r = run(sc, rig)
cls = r['maps'][0]['cls']
tile = lambda k: tl(cls, k)
share = lambda t, v: float((t == v).mean())  # noqa: E731
ok('6 граней, в карте 6 плиток', sc.tile == 6)
ok('четыре боковые грани видны кольцу (норма, класс 1)', all(share(tile(k), 1) > 0.97 for k in (0, 1, 2, 3)), [share(tile(k), 1) for k in range(4)])
ok('верх куба камеры видят только вскользь (класс 3): они на высоте 0,89 при грани на 0,5 — луч на грань идёт под ≈12° (cos 0,21 < 0,35), а не под 26° к центру', share(tile(4), 3) > 0.97, share(tile(4), 3))
ok('низ куба (плитка 5) кольцо сверху не видит: класс «unseen наружу» (2), а не «внутри»', share(tile(5), 2) > 0.97, share(tile(5), 2))
ok('доля unseen среди наружных ≈ 1/6 (одна грань из шести)', abs(r['outer_tex']['unseen_pct'] - 100 / 6) < 2.5, r['outer_tex'])
ok('grazing = одна грань из шести (верх), остальные видны нормально', abs(r['outer_tex']['grazing_pct'] - 100 / 6) < 2.5, r['outer_tex'])
ok('verdict по тем же THRESHOLDS: unseen 16,7 % < 20 % и grazing 16,7 % < 30 % → keep', TC.verdict(TC.flat_metrics({**r, 'seam': r['seam']})) == 'keep')

# ---------------------------------------------------------------- 3. грань внутри другого тела --------------------------------
print('3. грань внутри другого тела: не видна и «наружу» тоже нет')
sc2 = Scene()
sc2.box((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5))
sc2.box((-0.2, -0.2, -0.2), (0.2, 0.2, 0.2))                       # вторая коробка целиком внутри первой — её плитки 6…11
r2 = run(sc2, rig)
cls2 = r2['maps'][0]['cls']
inner = np.concatenate([tl(cls2, k).ravel() for k in range(6, 12)])
ok('грани внутреннего тела: все тексели «unseen внутри» (класс 5)', float((inner == 5).mean()) > 0.97, float((inner == 5).mean()))
ok('наружная доля unseen такая же, как у одного куба (внутренние не портят оценку)', abs(r2['outer_tex']['unseen_pct'] - r['outer_tex']['unseen_pct']) < 1.0, (r2['outer_tex'], r['outer_tex']))
ok('доля «наружных» среди всех текселей ≈ 50 % (6 из 12 плиток)', abs(r2['outer_share_tex_pct'] - 50.0) < 3.0, r2['outer_share_tex_pct'])

# ---------------------------------------------------------------- 4. данные прогона решают, а не константы -----------------------
print('4. камеры из данных: другой подъём и меньше камер — другой результат')
rl = C.rules()
below = {**rl, 'elevation_deg': -40.0}                             # кольцо снизу: верх куба не виден, низ виден
_d, rig_below = ring(rl=below)
r3 = run(sc, rig_below)
cls3 = r3['maps'][0]['cls']
t3 = lambda k: tl(cls3, k)
ok('кольцо снизу (подъём −40°): верх куба (плитка 4) — «unseen наружу», низ (плитка 5) — виден', share(t3(4), 2) > 0.97 and share(t3(5), 1) > 0.97, (share(t3(4), 2), share(t3(5), 1)))
r4 = run(sc, rig[:2])
ok('две соседние камеры вместо восьми: unseen среди наружных вырос (спина и низ не видны)', r4['outer_tex']['unseen_pct'] > r['outer_tex']['unseen_pct'] + 25.0, (r4['outer_tex'], r['outer_tex']))
ok('и решение хуже: у 8 камер — не reject, у 2 — reject (порог unseen наружных 45 %)',
   TC.verdict(TC.flat_metrics({**r, 'seam': r['seam']})) != 'reject' and TC.verdict(TC.flat_metrics({**r4, 'seam': r4['seam']})) == 'reject')
# констант MV-Adapter у rig-режима нет: те же данные с rig=None дали бы другой, «чужой» ответ — куб осевой, 6 видов видят и низ
r5 = TC.analyze(sc.geoms(), 0.0, GRID, 384, ext_n=26)
ok('те же данные по MV-Adapter (rig=None): низ куба виден (6 видов: подъём −89,99°) — сторож StableGen его НЕ видит; режимы разные', r5['outer_tex']['unseen_pct'] < 3.0 and r['outer_tex']['unseen_pct'] > 12.0, (r5['outer_tex'], r['outer_tex']))

# ---------------------------------------------------------------- 5. перспектива и ортография -------------------------------
print('5. перспектива считается точно (глубина по 1/расстоянию), ортография — как у MV-Adapter')
sc6 = Scene()
sc6.box((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5))
front = [{'name': 'F', 'eye': [0.0, 0.0, 2.0], 'forward': [0.0, 0.0, -1.0], 'up': [0.0, 1.0, 0.0], 'hx': 0.36, 'hy': 0.36, 'ortho': False}]
r6 = run(sc6, front)
c6 = r6['maps'][0]['cls']
t6 = lambda k: tl(c6, k)
ok('одна камера спереди (+Z): видна ровно грань +Z (плитка 0) с нормалью к камере; соседние боковые — ребром (unseen/grazing)', share(t6(0), 1) > 0.97 and share(t6(1), 1) < 0.05, (share(t6(0), 1), share(t6(1), 1)))
ok('боковые грани ±X при камере спереди: под нулевым углом — не видны (не «norm»)', share(t6(2), 1) < 0.05 and share(t6(3), 1) < 0.05)
orth = [{**front[0], 'ortho': True, 'hx': 0.6, 'hy': 0.6}]
r7 = run(sc6, orth)
c7 = r7['maps'][0]['cls']
ok('ортографическая камера из данных: та же грань +Z видна', float((tl(c7, 0) == 1).mean()) > 0.97)
# перспектива: пластина перед кубом закрывает половину грани +Z — закрытая часть не «видна»
sc8 = Scene()
sc8.box((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5))
sc8.quad((-0.7, -0.7, 1.0), (-0.2, -0.7, 1.0), (-0.2, 0.7, 1.0), (-0.7, 0.7, 1.0))    # плитка 6: плита на z=1 (камера на z=2), x от −0,7 до −0,2; перспектива проецирует её край на грань z=0,5 в x=−0,3
r8 = run(sc8, front)
c8 = r8['maps'][0]['cls']
face = tl(c8, 0)
vis = float((face == 1).mean())
ok('плита перед гранью: закрыто x<−0,3 (перспектива). Внутри измеряемой области (грань без 6-пиксельного поля: x от −0,44 до 0,44) видно 0,84; ортография дала бы 0,73 — перспектива считается точно', 0.82 < vis < 0.87, vis)

# ---------------------------------------------------------------- 5б. мера unpainted у StableGen: ровный чёрный внутри островков -----------------
print('5б. unpainted у камер StableGen: ровный чёрный (≤3) или магента ВНУТРИ островков; чёрные ножки, белый — краска; фон атласа вне островков не считается (P-034: мера для всех товаров)')


def unp(color=None, rows=None):
    g = sc.geoms()
    if color is not None:
        g[0]['tex'][:] = color
    if rows is not None:
        g[0]['tex'][rows[0]:rows[1]] = rows[2]
    return TC.analyze(g, 0.0, GRID, 384, ext_n=26, rig=rig)['tex']['unpainted_pct']


ok('белый товар (250,250,250): unpainted ≈ 0 (белый — краска)', unp((250, 250, 250)) < 1.0, unp((250, 250, 250)))
ok('белый крайний (255,255,255): тоже краска', unp((255, 255, 255)) < 1.0)
ok('чёрные ножки/каркас: честно тёмный (15,15,15) и (30,30,30), (45,45,45) — не unpainted', all(unp((v, v, v)) < 1.0 for v in (15, 30, 45)), [unp((v, v, v)) for v in (15, 30, 45)])
ok('граница: (4,4,4) — краска, (3,3,3) — залито', unp((4, 4, 4)) < 1.0 and unp((3, 3, 3)) > 99.0, (unp((4, 4, 4)), unp((3, 3, 3))))
ok('незакрашенный остров: вся карта ровный чёрный (0,0,0) → unpainted ≈ 100 % текселей островков', unp((0, 0, 0)) > 99.0, unp((0, 0, 0)))
ok('вся карта магента (255,0,255): unpainted ≈ 100 %; с допуском (230,30,225) — тоже', unp((255, 0, 255)) > 99.0 and unp((230, 30, 225)) > 99.0)
ok('розовое дерево (230,120,200) — не магента, краска', unp((230, 120, 200)) < 1.0)
# фон вне островков: на карте заняты плитки 0–5 (полосы 0–1 из 4 по высоте), остальное — «фон атласа»; чёрная половина карты считается ТОЛЬКО там, где острова
H2 = GRID // 2
top, bot = unp((140, 130, 120), (0, H2, (0, 0, 0))), unp((140, 130, 120), (H2, GRID, (0, 0, 0)))
ok('чёрная половина атласа: та, что без островков, не даёт ничего (≈0), та, что с островками, — всё (≈100); фон не считается', sorted((round(top), round(bot))) == [0, 100], (top, bot))
mv_white = TC.analyze((lambda g: (g[0]['tex'].__setitem__(slice(None), 250), g)[1])(sc.geoms()), 0.0, GRID, 384, ext_n=26)['tex']['unpainted_pct']
ok('режим MV-Adapter (rig=None) не тронут: белый (250) там по-прежнему «фон»', mv_white > 90.0, mv_white)

# ---------------------------------------------------------------- 6. process: камеры обязательны ------------------------------
print('6. process(): камер нет — «нет камер», а не молчаливый MV-Adapter')
import tempfile  # noqa: E402
try:
    import trimesh  # noqa: E402
    mesh = trimesh.Trimesh(vertices=np.array(sc.V), faces=np.array(sc.F), process=False)
    from PIL import Image  # noqa: E402
    mesh.visual = trimesh.visual.TextureVisuals(uv=np.array(sc.UV), image=Image.fromarray(sc.geoms()[0]['tex']))
    with tempfile.TemporaryDirectory(dir=os.environ.get('REMLAB_TMP') or None) as d:
        glb = os.path.join(d, 'cube.glb')
        mesh.export(glb)
        try:
            TC.process(glb, d, grid=GRID, write_glb=False, rig=lambda geoms: (None, 'нет'))
            ok('rig без камер → ValueError', False)
        except ValueError as e:
            ok('rig без камер → ValueError «нет камер прогона»', 'нет камер' in str(e), str(e))
        res = TC.process(glb, d, grid=GRID, write_glb=False, rig=lambda geoms: (rig, 'reconstructed'))
        ok('process(rig=…): в результате — число камер и источник; решение по THRESHOLDS', res['cameras'] == {'n': 8, 'source': 'reconstructed', 'names': [f'Camera_{i}' for i in range(8)]} and res['verdict'] in ('keep', 'repaint', 'reject'), res.get('cameras'))
        ok('  поворота нет (камеры уже в кадре GLB): yaw 0', res['yaw_deg'] == 0.0)
        res0 = TC.process(glb, d, grid=GRID, write_glb=False)
        ok('process() без rig — прежний режим MV-Adapter (6 видов)', res0['cameras'] == {'n': 6, 'source': 'MV-Adapter'})
except ImportError as e:
    ok('process(): нужны trimesh и PIL', False, str(e))

print('ИТОГО: всё в норме' if not bad else f'ИТОГО: провалов {bad}')
sys.exit(1 if bad else 0)
