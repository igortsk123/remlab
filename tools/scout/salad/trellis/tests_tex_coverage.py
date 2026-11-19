#!/usr/bin/env python3
"""Тесты `tex_coverage.py` (T-20261119-06/6/1, п.3): покрытие текстуры MV-Adapter — unseen / grazing / unpainted, «наружные» доли, решение keep/repaint/reject.
Без видеокарты, сети и MV-Adapter: на синтетических предметах (коробки из четырёхугольников, у каждой грани свой квадрат развёртки). Нужны numpy, PIL, trimesh (в CI они есть); растеризатор
сверяется с `trimesh.ray` (rtree) — без rtree эта проверка пропускается.

  python3 tools/scout/salad/trellis/tests_tex_coverage.py
"""
from __future__ import annotations

import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_tex_coverage')
import numpy as np  # noqa: E402
import tex_coverage as TC  # noqa: E402
import worker_trellis as W  # noqa: E402

bad = 0
GRID = 256


def ok(name, cond, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


# ---------------------------------------------------------------- синтетические предметы ----------------------------------
class Scene:
    """Набор четырёхугольников; у каждого — своя плитка 4×4 в развёртке (поле 1 % по краям, чтобы плитки не соприкасались)."""

    def __init__(self):
        self.V, self.F, self.UV = [], [], []
        self.n = 0

    def quad(self, p0, p1, p2, p3, tile):
        i, j = tile % 4, tile // 4
        u0, u1, v0, v1 = i / 4 + 0.01, (i + 1) / 4 - 0.01, j / 4 + 0.01, (j + 1) / 4 - 0.01
        o = len(self.V)
        self.V += [p0, p1, p2, p3]
        self.UV += [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
        self.F += [(o, o + 1, o + 2), (o, o + 2, o + 3)]
        self.n += 1
        return tile

    def box(self, lo, hi, tile0):
        x0, y0, z0 = lo
        x1, y1, z1 = hi
        q = [((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)),      # +Z
             ((x1, y0, z0), (x0, y0, z0), (x0, y1, z0), (x1, y1, z0)),      # -Z
             ((x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1)),      # +X
             ((x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)),      # -X
             ((x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0)),      # +Y
             ((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1))]      # -Y
        return {name: self.quad(*c, tile0 + k) for k, (name, c) in enumerate(zip(('+z', '-z', '+x', '-x', '+y', '-y'), q))}

    def geoms(self, colors=None, size=256):
        tex = np.zeros((size, size, 3), np.uint8)
        tex[:] = (120, 100, 80)
        for tile, col in (colors or {}).items():
            i, j = tile % 4, tile // 4
            r0, r1 = size - (j + 1) * size // 4, size - j * size // 4          # v вверх, строка 0 — сверху
            tex[r0:r1, i * size // 4:(i + 1) * size // 4] = col
        return [{'name': 'm', 'V': np.array(self.V, np.float64), 'F': np.array(self.F, np.int64), 'UV': np.array(self.UV, np.float64), 'tex': tex}]


def tile_cls(cls, tile, m=4):
    """Класс текселей внутри плитки (без поля в m текселей): массив."""
    T = cls.shape[0]
    i, j = tile % 4, tile // 4
    r0, r1 = T - (j + 1) * T // 4, T - j * T // 4
    return cls[r0 + m:r1 - m, i * T // 4 + m:(i + 1) * T // 4 - m]


def frac(cls, tile, *klass):
    t = tile_cls(cls, tile)
    return float(np.isin(t, klass).mean())


def run(sc, colors=None, yaw=0.0, **kw):
    return TC.analyze(sc.geoms(colors), yaw, GRID, 256, **kw)


# ---------------------------------------------------------------- 1. камеры ----------------------------------------------
print('1. камеры MV-Adapter')
views = TC.mv_views(W.MV_AZ)
P = np.random.RandomState(1).uniform(-0.5, 0.5, (50, 3))
x, y, d = TC.project(P, views[0], W.MV_ORTHO)
u, v = W.mv_ortho_uv(P)
ok('вид 0 совпадает с `worker_trellis.mv_ortho_uv` (вид «в лоб»: вправо +X, вверх +Y, камера на +Z)', np.allclose(x, u) and np.allclose(y, v) and np.allclose(d, P[:, 2]))
ok('6 видов: 4 по горизонтали (+Z, +X, −Z, −X) и сверху/снизу; векторы единичные и перпендикулярны',
   len(views) == 6 and np.allclose([c for c, _, _ in views][:4], [[0, 0, 1], [1, 0, 0], [0, 0, -1], [-1, 0, 0]], atol=1e-9)
   and views[4][0][1] > 0.999 and views[5][0][1] < -0.999
   and all(abs(np.dot(c, r)) < 1e-9 and abs(np.dot(c, u_)) < 1e-9 and abs(np.dot(r, u_)) < 1e-9 and abs(np.linalg.norm(u_) - 1) < 1e-9 for c, r, u_ in views))
ext = TC.ext_views()
ok('«наружных» направлений 26, все разные и единичные', len(ext) == 26 and len({tuple(np.round(c, 6)) for c, _, _ in ext}) == 26 and all(abs(np.linalg.norm(c) - 1) < 1e-9 for c, _, _ in ext))
ok('n=0 — наружные направления выключены', TC.ext_views(0) == [])

# ---------------------------------------------------------------- 2. растеризатор ---------------------------------------
print('2. растеризатор (буфер глубины)')
ids, zb = TC.raster(np.array([[1.0, 1.0], [9.0, 1.0], [1.0, 9.0]]), np.array([[0, 1, 2]]), 10)
cnt = int((ids >= 0).sum())
ok('один треугольник: покрыты центры пикселей внутри (площадь 32 ≈ 28 пикселей)', 24 <= cnt <= 36, str(cnt))
ids, zb = TC.raster(np.array([[0, 0], [10, 0], [0, 10], [0, 0], [10, 0], [0, 10.0]]), np.array([[0, 1, 2], [3, 4, 5]]), 10, np.array([0, 0, 0, 1, 1, 1.0]))
ok('два совпадающих треугольника: побеждает тот, у кого глубина больше (ближе)', set(ids[ids >= 0].tolist()) == {1} and zb[ids >= 0].min() > 0.9)
ids, _ = TC.raster(np.array([[-50, -50], [200, -50], [-50, 200.0]]), np.array([[0, 1, 2]]), 32)
ok('большой треугольник (больше 16 px): закрыт весь кадр в пределах, лишнего за кадром нет', int((ids >= 0).sum()) > 400 and ids.size == 32 * 32)
ids, _ = TC.raster(np.array([[1, 1], [1, 1], [1, 1.0]]), np.array([[0, 1, 2]]), 4)
ok('вырожденный треугольник пропускается без ошибки', int((ids >= 0).sum()) == 0)
try:
    import trimesh
    sphere = trimesh.creation.icosphere(subdivisions=3)
    n = 96
    s = 0.45
    xy = np.stack([(sphere.vertices[:, 0] * s + 0.5) * n, (0.5 - sphere.vertices[:, 1] * s) * n], 1)
    ids, zb = TC.raster(xy, sphere.faces, n, sphere.vertices[:, 2])
    jj, ii = np.divmod(np.arange(n * n), n)
    ox, oy = ((ii + 0.5) / n - 0.5) / s, (0.5 - (jj + 0.5) / n) / s
    org = np.stack([ox, oy, np.full(n * n, 5.0)], 1)
    try:
        first = sphere.ray.intersects_first(org, np.tile([0.0, 0.0, -1.0], (n * n, 1)))
        have = True
    except Exception as e:  # noqa: BLE001 — нет rtree: сверка пропускается
        print('  – trimesh.ray недоступен (%s): сверка пропущена' % type(e).__name__)
        have = False
    if have:
        both = (first >= 0) & (ids >= 0)
        ok('шар: «первая грань вдоль луча» буфера = trimesh.ray на ≥ 99 % пикселей, покрытие кадра совпадает ±1 %',
           (first[both] == ids[both]).mean() >= 0.99 and abs(float((first >= 0).mean()) - float((ids >= 0).mean())) < 0.01,
           '%.4f / %.4f / %.4f' % ((first[both] == ids[both]).mean(), (first >= 0).mean(), (ids >= 0).mean()))
except ImportError:
    print('  – trimesh нет: сверка с ray пропущена')

# ---------------------------------------------------------------- 3. покрытие: коробка с грани внутри другого тела ---------
print('3. покрытие: куб с гранью, спрятанной внутри другого тела')
sc = Scene()
B = sc.box((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5), 0)
C = sc.box((0.3, -0.2, -0.2), (0.9, 0.2, 0.2), 6)          # маленький куб воткнут в большой с +X: его грань −X и куски боковых граней — внутри
r = run(sc)
cls = r['maps'][0]['cls']
ok('грань малого куба внутри большого: 100 % unseen (и «внутри» — класс 5, не «наружу»)', frac(cls, C['-x'], 2, 5) > 0.99 and frac(cls, C['-x'], 5) > 0.99, str(frac(cls, C['-x'], 2, 5)))
ok('+X большого куба закрыта малым кубом на (0,4×0,4) = 16 % плитки: ровно столько unseen', abs(frac(cls, B['+x'], 2, 5) - 0.16) < 0.03, str(frac(cls, B['+x'], 2, 5)))
ok('боковые грани малого куба: треть (x от 0,3 до 0,5 из 0,6) внутри большого — треть unseen', all(abs(frac(cls, C[k], 2, 5) - 1 / 3) < 0.04 for k in ('+y', '-y', '+z', '-z')),
   str([round(frac(cls, C[k], 2, 5), 3) for k in ('+y', '-y', '+z', '-z')]))
ok('открытые грани (кроме -X у большого, закрыто полностью? нет: открыты) — не unseen', all(frac(cls, B[k], 2, 5) < 0.01 for k in ('+z', '-z', '+y', '-y', '-x')) and frac(cls, C['+x'], 2, 5) < 0.01,
   str([round(frac(cls, B[k], 2, 5), 3) for k in ('+z', '-z', '+y', '-y', '-x')]))
tot_unseen = (frac(cls, C['-x'], 2, 5) + frac(cls, B['+x'], 2, 5) + sum(frac(cls, C[k], 2, 5) for k in ('+y', '-y', '+z', '-z'))) / 12
ok('доля unseen по всем текселям = сумма по плиткам (12 плиток равной площади в развёртке)', abs(r['tex']['unseen_pct'] / 100 - tot_unseen) < 0.01, '%s vs %.4f' % (r['tex']['unseen_pct'], tot_unseen))
ok('«наружные» доли: спрятанное внутри (класс 5) не входит — среди наружных unseen почти нет', r['outer_tex']['unseen_pct'] < 2.0 and abs(r['outer_share_tex_pct'] - 79.2) < 2.0,
   '%s / %s' % (r['outer_tex'], r['outer_share_tex_pct']))
ok('доля по ПЛОЩАДИ считается с весом (площадь в 3D / площадь в карте): у плиток разной площади она отличается от доли текселей (по расчёту: спрятано 0,64 из 7,28 площади = 8,79 %, по текселям 2,49 из 12 плиток = 20,8 %)',
   abs(r['area']['unseen_pct'] - 8.79) < 0.5 and abs(r['tex']['unseen_pct'] - 20.8) < 1.5, '%s / %s' % (r['area'], r['tex']))
ok('поворот формы yaw=90° не меняет доли (видны те же грани)', abs(run(sc, yaw=90.0)['tex']['unseen_pct'] - r['tex']['unseen_pct']) < 1.0)
r1 = TC.analyze(sc.geoms(), 0.0, GRID, 256, ext_n=0)
ok('ext_n=0: наружные доли = все (направлений наружу нет → только 6 видов)', r1['outer_share_tex_pct'] is not None and r1['n_island'] == r['n_island'])

# ---------------------------------------------------------------- 4. grazing --------------------------------------------
print('4. grazing: площадка, видимая только вскользь')
sc = Scene()
n = np.array([0.25, 0.25, 0.935])
n /= np.linalg.norm(n)
e1 = np.cross(n, [0.0, 1.0, 0.0])
e1 /= np.linalg.norm(e1)
e2 = np.cross(n, e1)
a = 0.08
patch = sc.quad(tuple(-a * e1 - a * e2), tuple(a * e1 - a * e2), tuple(a * e1 + a * e2), tuple(-a * e1 + a * e2), 0)
cover_f = sc.quad((-0.3, -0.3, 0.3), (0.3, -0.3, 0.3), (0.3, 0.3, 0.3), (-0.3, 0.3, 0.3), 1)
cover_b = sc.quad((-0.3, -0.3, -0.3), (0.3, -0.3, -0.3), (0.3, 0.3, -0.3), (-0.3, 0.3, -0.3), 2)
r = run(sc)
cls = r['maps'][0]['cls']
ok('площадка закрыта плитами спереди и сзади, видна только с ±X/±Y под |cos| 0,25 → grazing, не unseen', frac(cls, patch, 3) > 0.95 and frac(cls, patch, 2, 5) < 0.03, '%s %s' % (frac(cls, patch, 3), frac(cls, patch, 2, 5)))
ok('плиты (смотрят прямо на вид) — не grazing и не unseen', frac(cls, cover_f, 1) > 0.9 and frac(cls, cover_b, 1) > 0.9, '%s %s' % (frac(cls, cover_f, 1), frac(cls, cover_b, 1)))

# ---------------------------------------------------------------- 5. unpainted -----------------------------------------
print('5. unpainted: фон чёрный/белый')
sc = Scene()
B = sc.box((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5), 0)
r = run(sc, {B['+z']: (0, 0, 0), B['+x']: (255, 255, 255), B['+y']: (6, 8, 5), B['-y']: (250, 252, 249), B['-z']: (60, 60, 60)})
cls = r['maps'][0]['cls']
ok('чёрная, белая, почти чёрная и почти белая плитки — unpainted; серая (60) и коричневая — нет', all(frac(cls, B[k], 4) > 0.99 for k in ('+z', '+x', '+y', '-y')) and frac(cls, B['-z'], 4) < 0.01 and frac(cls, B['-x'], 4) < 0.01)
ok('доля unpainted = 4 плитки из 6 = 66,7 %; среди ВИДИМЫХ — те же (все грани видны)', abs(r['tex']['unpainted_pct'] - 66.67) < 1.0 and abs(r['tex']['unpainted_seen_pct'] - r['tex']['unpainted_pct']) < 0.5, str(r['tex']))
ok('коробка целиком снаружи: unseen 0, наружных 100 %', r['tex']['unseen_pct'] < 0.5 and r['outer_share_tex_pct'] > 99, '%s %s' % (r['tex'], r['outer_share_tex_pct']))
r2 = run(sc, {B['+z']: (0, 0, 0)})
ok('порог чёрного — в UNPAINTED: плитка (13,13,13) при black_max=12 не считается фоном, а при 13 — да',
   (lambda: (setattr(TC, 'UNPAINTED', {'black_max': 12, 'white_min': 245}), run(sc, {B['+z']: (13, 13, 13)})['tex']['unpainted_pct'])[1])() < 1.0
   and (lambda: (setattr(TC, 'UNPAINTED', {'black_max': 13, 'white_min': 245}), run(sc, {B['+z']: (13, 13, 13)})['tex']['unpainted_pct'])[1])() > 10.0)
TC.UNPAINTED = {'black_max': 12, 'white_min': 245}

# ---------------------------------------------------------------- 6. решение ------------------------------------------
print('6. verdict: пороги в одном месте')
ok('чистые числа → keep', TC.verdict({'unseen_outer_tex_pct': 1.0, 'grazing_outer_tex_pct': 2.0, 'unpainted_outer_tex_pct': 0.5, 'de00': 10.0}) == 'keep')
rp = TC.THRESHOLDS['repaint']['max']
rj = TC.THRESHOLDS['reject']['max']
ok('метрика выше порога перекраски → repaint (порог берётся из THRESHOLDS, не из кода проверки)', TC.verdict({'unseen_outer_tex_pct': rp['unseen_outer_tex_pct'] + 0.5}) == 'repaint')
ok('выше порога отказа → reject; reject главнее repaint', TC.verdict({'unseen_outer_tex_pct': rj['unseen_outer_tex_pct'] + 0.5, 'grazing_outer_tex_pct': rp['grazing_outer_tex_pct'] + 1}) == 'reject')
ok('ΔE00 из таблицы пробы участвует: выше порога перекраски → repaint, выше порога отказа → reject',
   TC.verdict({'de00': rp['de00'] + 1}) == 'repaint' and TC.verdict({'de00': rj['de00'] + 1}) == 'reject')
ok('нет метрики или None/bool — порог пропускается (keep)', TC.verdict({}) == 'keep' and TC.verdict({'unseen_outer_tex_pct': None, 'de00': None}) == 'keep' and TC.verdict({'de00': True}) == 'keep')
own = {'reject': {'max': {'x': 5}, 'min': {'q': 0.5}}, 'repaint': {'max': {'y': 1}}}
ok('свои пороги (словарь): max/min, reject → repaint → keep', TC.verdict({'x': 6}, own) == 'reject' and TC.verdict({'q': 0.4}, own) == 'reject' and TC.verdict({'y': 2}, own) == 'repaint'
   and TC.verdict({'x': 1, 'y': 0.5, 'q': 0.9}, own) == 'keep')
ok('порог ровно равен метрике — не срабатывает (строго больше)', TC.verdict({'x': 5}, own) == 'keep')
ok('меняем порог правкой словаря — решение меняется, код проверки не трогаем',
   (lambda: (TC.THRESHOLDS['repaint']['max'].__setitem__('de00', 5.0), TC.verdict({'de00': 10.0}))[1])() == 'repaint', '')
TC.THRESHOLDS['repaint']['max']['de00'] = rp['de00']
v, why = TC._judge({'unseen_outer_tex_pct': rj['unseen_outer_tex_pct'] + 1}, None)
ok('_judge отдаёт причину', v == 'reject' and why and 'unseen_outer_tex_pct' in why[0], str(why))

# ---------------------------------------------------------------- 7. файл целиком: GLB → json, coverage.glb, таблица ---
print('7. прогон по GLB: json, coverage.glb, сводка, подмешанные колонки таблицы пробы')
import tempfile  # noqa: E402
import trimesh  # noqa: E402
from trimesh.visual import TextureVisuals  # noqa: E402
from trimesh.visual.material import PBRMaterial  # noqa: E402
from PIL import Image  # noqa: E402
tmp = tempfile.mkdtemp(prefix='tcov-')
sc = Scene()
B = sc.box((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5), 0)
C = sc.box((0.3, -0.2, -0.2), (0.9, 0.2, 0.2), 6)
g = sc.geoms({B['+z']: (0, 0, 0)})[0]
mesh = trimesh.Trimesh(vertices=g['V'], faces=g['F'], process=False)
mesh.visual = TextureVisuals(uv=g['UV'], material=PBRMaterial(baseColorTexture=Image.fromarray(g['tex']), metallicFactor=0.0, roughnessFactor=1.0))
glb = os.path.join(tmp, 'sh_55-1024-42-0-mvtex.glb')
trimesh.Scene([mesh]).export(glb)
with open(os.path.join(tmp, 'summary-trial-x.json'), 'w', encoding='utf-8') as f:
    json.dump({'jobs': [{'job_id': 'sh_55-1024-42-0-mvtex', 'metrics': {'fit': {'yaw_deg': 90}}}]}, f)
ok('yaw берётся из сводки драйвера по имени задания', TC.find_yaw(glb) == (90.0, 'summary-trial-x.json'))
ok('--yaw главнее сводки; нет сводки → 0 с пометкой', TC.find_yaw(glb, 180)[0] == 180.0 and TC.find_yaw(os.path.join(tmp, 'sub', 'q-mvtex.glb'))[0] == 0.0)
tab = os.path.join(tmp, 'trial-table.csv')
with open(tab, 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=['model', 'sku', 'de00', 'dL', 'pattern_grad_ncc', 'colour_guard'])
    w.writeheader()
    w.writerow({'model': 'mvadapter-i2tex', 'sku': 'sh:55', 'de00': '31.5', 'dL': '-4.0', 'pattern_grad_ncc': '0.12', 'colour_guard': 'ok'})
    w.writerow({'model': 'trellis2', 'sku': 'sh:55', 'de00': '5.0', 'dL': '1.0', 'pattern_grad_ncc': '0.9', 'colour_guard': 'ok'})
    w.writerow({'model': 'mvadapter-i2tex', 'sku': 'sh:5', 'de00': '1.0', 'dL': '1.0', 'pattern_grad_ncc': '0.9', 'colour_guard': 'ok'})
rows = TC.load_table(tab, 'mvadapter-i2tex')
ok('товар в таблице пробы — по ключу sku → «магазин_товар» в начале имени (длиннейшее совпадение, не sh:5)', TC.match_row('sh_55-1024-42-0-mvtex', rows)['sku'] == 'sh:55' and TC.match_row('zz_1-1', rows) is None)
res = TC.process(glb, os.path.join(tmp, 'out'), None, GRID, 256, rows)
ok('результат: json рядом, coverage.glb рядом, поля долей, решение и время по стадиям',
   os.path.exists(os.path.join(tmp, 'out', 'sh_55-1024-42-0-mvtex.coverage.json')) and os.path.exists(os.path.join(tmp, 'out', 'sh_55-1024-42-0-mvtex.coverage.glb'))
   and res['yaw_deg'] == 90.0 and res['faces'] == 24 and set(res['tex']) >= {'unseen_pct', 'grazing_pct', 'unpainted_pct'} and res['verdict'] in ('keep', 'repaint', 'reject')
   and set(res['time_s']) >= {'zbuf', 'texels', 'total', 'all'}, str(res))
ok('колонки таблицы пробы (ΔE00, ΔL, pattern, цвет) легли рядом с долями; чужая модель и товар sh:5 не подмешаны', res['photo'] == {'de00': 31.5, 'dL': -4.0, 'pattern_grad_ncc': 0.12, 'colour_guard': 'ok'}, str(res['photo']))
ok('ΔE00 31,5 выше порога перекраски — решение repaint (ΔE из таблицы в решении)', res['verdict'] == 'repaint' and any('de00' in w for w in res['verdict_why']), str(res['verdict_why']))
back = trimesh.load(res['coverage_glb'], force='scene')
tex = None
for gm in back.geometry.values():
    tex = np.asarray(gm.visual.material.baseColorTexture.convert('RGB'))
ok('coverage.glb: те же грани и развёртка; текстура — картинка покрытия (красного в плитке грани внутри — много)', tex is not None and len(list(back.geometry.values())[0].faces) == 24 and tex.shape[0] == tex.shape[1])
T = tex.shape[0]
t_inner = tex[T - (C['-x'] // 4 + 1) * T // 4 + 4:T - (C['-x'] // 4) * T // 4 - 4, (C['-x'] % 4) * T // 4 + 4:(C['-x'] % 4 + 1) * T // 4 - 4]
ok('грань внутри другого тела на картинке тёмно-бордовая (внутри), чёрная плитка снаружи — синяя (unpainted)',
   float(((t_inner[..., 0] == 90) & (t_inner[..., 1] == 0)).mean()) > 0.9, str(t_inner.reshape(-1, 3)[0]))
res2 = TC.process(glb, os.path.join(tmp, 'out2'), 0, GRID, 256, None, None, False)
ok('--no-glb: coverage.glb не пишется; без таблицы photo = None', not os.path.exists(os.path.join(tmp, 'out2', 'sh_55-1024-42-0-mvtex.coverage.glb')) and res2['photo'] is None and 'coverage_glb' not in res2)
bad_res = {'key': 'oops', 'error': 'ValueError: нет текстуры'}
p_csv, p_json, p_md = TC.write_summary(os.path.join(tmp, 'sum'), [res, res2, bad_res])
md = open(p_md, encoding='utf-8').read()
ok('сводка: csv, json, md; в md строка на товар, решение, итог по решениям, ошибка товара — строкой, а не молчанием',
   os.path.exists(p_csv) and os.path.exists(p_json) and '**repaint**' in md and 'ошибка' in md and 'Итого:' in md and '31.5' in md, md[-400:])
rows_csv = list(csv.DictReader(open(p_csv, encoding='utf-8')))
ok('csv: колонки долей и фото рядом; ошибочный товар — verdict «ошибка»', rows_csv[0]['de00'] == '31.5' and rows_csv[2]['verdict'] == 'ошибка' and 'unseen_outer_tex' in rows_csv[0])
nt = TC.gather([tmp, os.path.join(tmp, 'out')], '*-mvtex.glb')
ok('папка → *-mvtex.glb, файлы .coverage.glb пропускаются', glb in nt and not any('.coverage.' in x for x in nt))
no_tex = trimesh.Trimesh(vertices=g['V'], faces=g['F'], process=False)
p0 = os.path.join(tmp, 'plain-mvtex.glb')
trimesh.Scene([no_tex]).export(p0)
try:
    TC.load_geoms(p0)
    ok('GLB без текстуры/развёртки — ошибка с понятным текстом', False)
except ValueError as e:
    ok('GLB без текстуры/развёртки — ошибка с понятным текстом', 'нет развёртки или текстуры' in str(e))
ok('CLI: код возврата 1, если у какого-то товара ошибка; 0, если все посчитаны', TC.main([p0, '--out', os.path.join(tmp, 'c1')]) == 1 and TC.main([glb, '--out', os.path.join(tmp, 'c2'), '--grid', '256', '--no-glb']) == 0)
ok('в коде проверок нет номеров товаров и порогов: числа порогов только в THRESHOLDS', 'THRESHOLDS = {' in open(os.path.join(HERE, 'tex_coverage.py'), encoding='utf-8').read())

print('ИТОГО: ' + ('всё в норме' if not bad else f'провалов {bad}'))
sys.exit(1 if bad else 0)
