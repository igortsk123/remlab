#!/usr/bin/env python3
"""Тесты переноса родного цвета и сторожа шага 0 (T-20261120-167). Без видеокарты и Blender: numpy + scipy + trimesh + PIL. Запуск: python tools/scout/stablegen/tests_color_transfer.py
Подставные формы — сетки-«ткань»: родная частая (48×48) с развёрткой XY и картой, где цвет = функция точки; упрощённая редкая (6×6) с ДРУГОЙ развёрткой (повёрнута, меньше карты)."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402
import trimesh  # noqa: E402
from PIL import Image  # noqa: E402

import sg_color_transfer as T  # noqa: E402

FAILS = []


def check(name, cond, extra=''):
    print(('  ✓ ' if cond else '  ✗ ') + name + (f'  [{extra}]' if extra and not cond else ''))
    if not cond:
        FAILS.append(name)


def zf(x, y):
    return 0.1 * np.sin(2.0 * x) + 0.05 * y


def grid(n, uvfun, zshift=0.0):
    xs = np.linspace(0, 1, n + 1)
    X, Y = np.meshgrid(xs, xs)
    V = np.stack([X.ravel(), Y.ravel(), zf(X, Y).ravel() + zshift], 1)
    UV = np.stack(uvfun(X.ravel(), Y.ravel()), 1)
    F = []
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            F += [[a, a + 1, a + n + 2], [a, a + n + 2, a + n + 1]]
    return V, np.array(F, np.int64), UV


def write(path, V, F, UV, base=None, mr=None):
    m = trimesh.Trimesh(vertices=V, faces=F, process=False)
    if base is None:
        m.visual = trimesh.visual.TextureVisuals(uv=UV, material=trimesh.visual.material.PBRMaterial(baseColorFactor=[200, 200, 200, 255]))   # форма без текстуры, как выход Blender без материала
    else:
        mat = trimesh.visual.material.PBRMaterial(baseColorTexture=base, metallicRoughnessTexture=mr, metallicFactor=1.0 if mr else 0.0, alphaMode='OPAQUE')
        m.visual = trimesh.visual.TextureVisuals(uv=UV, material=mat)
    m.export(path, file_type='glb')


def native_textures(n=256, alpha_rule=lambda u: 255 if u < 0.5 else 100):
    u = (np.arange(n) + 0.5) / n
    U, W = np.meshgrid(u, 1.0 - u)                 # строка 0 — верх карты (v = 1)
    base = np.zeros((n, n, 4), np.uint8)
    base[..., 0] = (U * 255).astype(np.uint8)
    base[..., 1] = (W * 255).astype(np.uint8)
    base[..., 2] = 128
    base[..., 3] = np.array([alpha_rule(x) for x in u], np.uint8)[None, :]
    mr = np.zeros((n, n, 3), np.uint8)
    mr[..., 1] = 200
    mr[..., 2] = 30
    return Image.fromarray(base, 'RGBA'), Image.fromarray(mr, 'RGB')


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        nat, shp, out = (os.path.join(d, x) for x in ('nat.glb', 'shape.glb', 'out.glb'))
        Vn, Fn, UVn = grid(48, lambda x, y: (x, y))
        base, mr = native_textures()
        write(nat, Vn, Fn, UVn, base, mr)
        Vs, Fs, UVs = grid(6, lambda x, y: (0.1 + 0.8 * y, 0.1 + 0.8 * (1.0 - x)))     # другая развёртка: повёрнута, меньше карты
        write(shp, Vs, Fs, UVs)

        rep = T.transfer(nat, shp, out, size=128)
        check('доля текселей с цветом ≥ 99 %', rep['share'] >= T.MIN_SHARE, rep)
        check('размер новой карты 128 и родной 256', rep['size'] == 128 and rep['native_size'] == 256, rep)
        g = T.load_glb(out)
        check('в результате есть baseColor и металл-шероховатость', g['base'] is not None and g['mr'] is not None)
        check('форма и развёртка упрощённой не тронуты (вершины, грани, UV)',
              np.allclose(g['V'], Vs) and (g['F'] == Fs).all() and np.allclose(g['UV'], UVs, atol=1e-6))
        py, px, P = T.texel_points(g['V'], g['F'], g['UV'], 128)
        rgba = np.asarray(g['base'].convert('RGBA'))
        exp_r, exp_g = P[:, 0] * 255, P[:, 1] * 255
        err_r = np.abs(rgba[py, px, 0].astype(float) - exp_r)
        err_g = np.abs(rgba[py, px, 1].astype(float) - exp_g)
        check('цвет каждого тексела = цвет родной формы в той же точке 3D (ошибка ≤ 8 из 255, p99)', np.percentile(err_r, 99) <= 8 and np.percentile(err_g, 99) <= 8,
              (float(np.percentile(err_r, 99)), float(np.percentile(err_g, 99))))
        far = np.abs(P[:, 0] - 0.5) > 0.04
        al = rgba[py, px, 3]
        check('альфа переносится (255 слева от x=0,5, 100 справа)', (al[far & (P[:, 0] < 0.5)] == 255).all() and (al[far & (P[:, 0] > 0.5)] == 100).all())
        mrr = np.asarray(g['mr'].convert('RGB'))
        check('металл/шероховатость переносятся (G=200, B=30)', (np.abs(mrr[py, px, 1].astype(int) - 200) <= 1).all() and (np.abs(mrr[py, px, 2].astype(int) - 30) <= 1).all())
        check('поля вокруг островков залиты цветом (нет чёрных текселей)', int((rgba[..., :3].sum(2) == 0).sum()) <= 2)

        # нормали: у родного есть NORMAL → переходят на упрощённую (ближайшая вершина), без NORMAL у родного — не пишем свои (T-167: плашки после упрощения)
        nn = np.tile(np.array([0.0, 0.6, 0.8]), (len(Vn), 1))
        mn = trimesh.Trimesh(vertices=Vn, faces=Fn, vertex_normals=nn, process=False)
        mn.visual = trimesh.visual.TextureVisuals(uv=UVn, material=trimesh.visual.material.PBRMaterial(baseColorTexture=base, alphaMode='OPAQUE'))
        nat_n = os.path.join(d, 'nat-n.glb')
        mn.export(nat_n, file_type='glb')
        rep_n = T.transfer(nat_n, shp, os.path.join(d, 'out-n.glb'), size=64)
        gn = T.load_glb(os.path.join(d, 'out-n.glb'))
        check('нормали родного переходят на упрощённую (NORMAL записан, значения те же)',
              rep_n.get('normals_from_native') and gn['has_normals'] and np.allclose(gn['N'], [0.0, 0.6, 0.8], atol=1e-3), (rep_n.get('normals_from_native'), gn['has_normals']))

        # нормали с обратной стороны (тонкая стенка рядом) не берём: у половины родной нормали перевёрнуты, у упрощённой все должны остаться «наружу» (cos с собственной нормалью > 0)
        own = np.asarray(trimesh.Trimesh(vertices=Vs, faces=Fs, process=False).vertex_normals)
        sign = np.where(Vn[:, 0] < 0.5, 1.0, -1.0)[:, None]
        flip_N = np.array([0.0, 0.0, 1.0]) * sign * (1.0 if (own[:, 2].mean() > 0) else -1.0)
        tn = T.transfer_normals(Vn, flip_N, Vs, Fs)
        check('нормали родной с обратной стороны отбрасываются (у упрощённой cos с собственной нормалью > 0 у всех вершин, длина 1)',
              (np.einsum('nc,nc->n', tn, own) > 0).all() and np.allclose(np.linalg.norm(tn, axis=1), 1.0, atol=1e-6), float(np.einsum('nc,nc->n', tn, own).min()))

        # мерка «разница затенения»: гладкая сфера (родная, с NORMAL) против грубой сферы без NORMAL (плоские грани) и с нормалями родной
        hi = trimesh.creation.icosphere(subdivisions=4)
        lo = trimesh.creation.icosphere(subdivisions=0)             # 20 плоских граней: заведомо «плашки»
        sph_nat, sph_flat, sph_ok = (os.path.join(d, x) for x in ('sph-nat.glb', 'sph-flat.glb', 'sph-ok.glb'))
        trimesh.Trimesh(vertices=hi.vertices, faces=hi.faces, vertex_normals=hi.vertices / np.linalg.norm(hi.vertices, axis=1, keepdims=True), process=False).export(sph_nat, file_type='glb')
        trimesh.Trimesh(vertices=lo.vertices, faces=lo.faces, process=False).export(sph_flat, file_type='glb')
        trimesh.Trimesh(vertices=lo.vertices, faces=lo.faces, vertex_normals=lo.vertices / np.linalg.norm(lo.vertices, axis=1, keepdims=True), process=False).export(sph_ok, file_type='glb')
        nd_flat, nd_ok = T.normal_deviation(sph_nat, sph_flat), T.normal_deviation(sph_nat, sph_ok)
        check('мерка нормалей: без NORMAL (плоские грани) — среднее выше порога, с нормалями родной — ниже; флаг «NORMAL в файле» верен',
              nd_flat[0] > T.NORMAL_DEV_MEAN_MAX > nd_ok[0] and not nd_flat[2] and nd_ok[2], (nd_flat, nd_ok))

        # плита-подложка TRELLIS (T-20261121-170): упрощённая форма собрана БЕЗ плиты → перенос и Chamfer сравнивают её с родной тоже без плиты
        def box(sx, sy, sz, cx, cy, cz):
            b = trimesh.creation.box(extents=(sx, sy, sz))
            b.apply_translation((cx, cy, cz))
            return b
        prod_parts = [box(0.6, 0.01, 0.4, 0, 0.3, 0)] + [box(0.04, 0.3, 0.04, sx, 0.15, sz) for sx in (-0.25, 0.25) for sz in (-0.15, 0.15)]
        plate_parts = [box(1.0, 0.002, 1.0, 0, -0.001, 0), box(0.95, 0.001, 0.9, 0, -0.002, 0), box(1.0, 0.001, 1.0, 0, -0.003, 0)]
        rng = np.random.default_rng(3)
        for _ in range(40):
            px_, pz_ = rng.uniform(-0.48, 0.48, 2)
            plate_parts.append(box(0.03, 0.001, 0.03, px_, -0.0015, pz_))
        with_plate = trimesh.util.concatenate(prod_parts + plate_parts)
        only_prod = trimesh.util.concatenate(prod_parts)
        uv_top = lambda v: np.stack([v[:, 0] + 0.5, v[:, 2] + 0.5], 1) * 0.98 + 0.01         # вид сверху на карту
        pn, ps_ = os.path.join(d, 'plate-nat.glb'), os.path.join(d, 'plate-shape.glb')
        write(pn, np.asarray(with_plate.vertices), np.asarray(with_plate.faces), uv_top(np.asarray(with_plate.vertices)), base, mr)
        write(ps_, np.asarray(only_prod.vertices), np.asarray(only_prod.faces), uv_top(np.asarray(only_prod.vertices)))
        ch_on = T.chamfer_ratio(pn, ps_)
        ch_off = T.chamfer_ratio(pn, ps_, strip_plate=False)
        check('Chamfer: родная без плиты ≈ упрощённая (≤ порога), с плитой — форма «не та» (> порога)', ch_on[0] <= T.CHAMFER_MAX < ch_off[0], (ch_on, ch_off))
        rp = T.transfer(pn, ps_, os.path.join(d, 'plate-out.glb'), size=128)
        check('перенос видит плиту родной и вычитает её (plate_found, доля с цветом ≥ 99 %)', rp['plate_found'] and rp['share'] >= T.MIN_SHARE, rp)
        rp0 = T.transfer(pn, ps_, os.path.join(d, 'plate-out0.glb'), size=128, strip_plate=False)
        check('выключатель: strip_plate=False плиту не ищет', not rp0['plate_found'], rp0)

        # слишком далёкая форма — цвета нет, доля низкая (отказ по порогу)
        Vf, Ff, UVf = grid(6, lambda x, y: (x, y), zshift=2.0)
        far_shape = os.path.join(d, 'far.glb')
        write(far_shape, Vf, Ff, UVf)
        rep2 = T.transfer(nat, far_shape, os.path.join(d, 'far-out.glb'), size=64)
        check('форма далеко от родной → доля с цветом < 50 %', rep2['share'] < 0.5, rep2)

        # родной GLB без цвета — понятная ошибка, а не тихий пустой результат
        bare = os.path.join(d, 'bare.glb')
        write(bare, Vn, Fn, UVn)
        try:
            T.transfer(bare, shp, os.path.join(d, 'x.glb'))
            check('родной без baseColor → ошибка', False)
        except ValueError as e:
            check('родной без baseColor → ошибка', 'нет baseColor' in str(e))

        # сторож шага 0
        code, line, reps = T.guard([out])
        check('сторож: GLB с цветом → код 0 и счётчик «пришёл 1 из 1»', code == 0 and 'пришёл 1 из 1' in line and 'не пришёл 0' in line, line)
        code, line, reps = T.guard([out, shp])
        check('сторож: форма без цвета → код 1, имя в списке', code == 1 and 'пришёл 1 из 2' in line and 'shape.glb' in line, line)
        code, line, reps = T.guard([d])
        check('сторож: папка — берёт все *.glb (без .raw.)', len(reps) == len([x for x in os.listdir(d) if x.endswith('.glb') and '.raw.' not in x]) and len(reps) >= 6, [r['file'] for r in reps])
        base_sus, mr_ = native_textures(alpha_rule=lambda u: 255 if u < 0.1 else 50)
        sus = os.path.join(d, 'sus.glb')
        write(sus, Vn, Fn, UVn, base_sus, mr_)
        r = T.guard_report(sus)
        check('сторож: альфа<128 на ~90 % занятых текселей → «подозрительно», но не отказ', r['has_color'] and r['alpha_suspect'] and 0.85 < r['alpha_lt128'] < 0.95, r)
        code, line, _ = T.guard([sus])
        check('сторож: подозрительная альфа не даёт код 1 (только сообщение)', code == 0 and 'больше 30 %: 1' in line, line)
        r = T.guard_report(out)
        check('сторож: у родного-образца доля альфа<128 ≈ половина занятого (x>0,5)', r['has_color'] and 0.3 < r['alpha_lt128'] < 0.7, r)
        r = T.guard_report(os.path.join(d, 'нет-такого.glb'))
        check('сторож: не открылся файл → has_color False и ошибка в отчёте', (not r['has_color']) and r['error'], r)

        # этапы 01 и 02 «проверки на каждом этапе» (paint_stage.py, T-164)
        run = os.path.join(d, 'run')
        c1 = T.stage01(run, 'mid:eid1', nat)
        check('этап 01: check.json есть, прошёл, главная мерка has_base_color = 1', c1['passed'] and c1['metric']['value'] == 1 and c1['metric']['ok'], c1)
        check('этап 01: кадр и ссылка на модель на месте',
              os.path.exists(os.path.join(run, 'mid_eid1', '01-trellis', 'frame.png')) and os.path.exists(os.path.join(run, 'mid_eid1', '01-trellis', 'model.glb')))
        check('этап 01: доля альфа<128 — справочная мерка без порога (на passed не влияет)', c1['metrics']['alpha_lt128']['ok'] is None and c1['metrics']['alpha_lt128']['value'] > 0.3, c1['metrics'])
        c1b = T.stage01(run, 'mid:eid2', shp)
        check('этап 01: форма без baseColor → не прошёл, причина «цвет не пришёл»', (not c1b['passed']) and 'цвет не пришёл' in c1b['reason'], c1b)
        c2 = T.stage02(run, 'mid:eid1', nat, out, rep)
        check('этап 02: грани с текселем ≥ 99 %, граней ≤ 150k, Chamfer ≤ порога, цвет ≥ 99 % → прошёл',
              c2['passed'] and c2['metric']['name'] == 'faces_with_texel' and c2['metric']['ok'] and c2['metrics']['faces']['ok']
              and c2['metrics']['chamfer_diag']['ok'] and c2['metrics']['color_texel_share']['ok'], c2)
        check('этап 02: кадр (карта цвета) записан', os.path.getsize(os.path.join(run, 'mid_eid1', '02-prep', 'frame.png')) > 1000)
        c2e = T.stage02(run, 'mid:eid5', nat, out)
        check('этап 02: без готового отчёта доля пересчитывается из файлов и проходит', c2e['passed'] and c2e['metrics']['color_texel_share']['value'] >= T.MIN_SHARE, c2e)
        c2b = T.stage02(run, 'mid:eid6', nat, out, rep, faces_max=10)
        check('этап 02: граней больше порога → не прошёл, причина называет faces', (not c2b['passed']) and 'faces' in c2b['reason'], c2b['reason'])
        c2c = T.stage02(run, 'mid:eid3', nat, os.path.join(run, 'нет.glb'), None)
        check('этап 02: нет выходного GLB → не прошёл', (not c2c['passed']) and c2c['metric']['value'] is None, c2c)
        c2d = T.stage02(run, 'mid:eid4', nat, out, {'share': 0.5, 'native_texels': 1, 'target_texels': 2, 'size': 128})
        check('этап 02: доля цвета 50 % → не прошёл (мерка color_texel_share)', (not c2d['passed']) and 'color_texel_share' in c2d['reason'], c2d['reason'])
        # грани без текселя (крошечные островки разворачки) — пятна не того цвета на кадрах; мерка должна это ловить
        # (все 72 грани сброшены в один пиксель развёртки: цвет у большинства взят от далёкой грани → мерка должна отказать)
        Vg0, Fg0, _ = grid(6, lambda x, y: (x, y))
        Vt = Vg0[Fg0].reshape(-1, 3)
        Ft = np.arange(len(Vt), dtype=np.int64).reshape(-1, 3)
        UVt = np.tile(np.array([[0.5, 0.5], [0.5 + 0.004, 0.5], [0.5, 0.5 + 0.004]]), (len(Ft), 1))
        tiny = os.path.join(d, 'tiny.glb')
        write(tiny, Vt, Ft, UVt)
        rep_t = T.transfer(nat, tiny, os.path.join(d, 'tiny-out.glb'), size=128)
        c2f = T.stage02(run, 'mid:eid8', nat, os.path.join(d, 'tiny-out.glb'), rep_t)
        check('этап 02: большинство граней без текселя → не прошёл (faces_with_texel < 99 %)',
              (not c2f['passed']) and c2f['metric']['value'] < T.FACES_TEXEL_MIN and 'faces_with_texel' in c2f['reason'], c2f)
        # каждая грань — свой крошечный островок (0,6 пикселя) в разных местах карты: центр пикселя в них почти не попадает; тексель по центру развёртки даёт цвет верного места
        Vg, Fg, _ = grid(6, lambda x, y: (x, y))
        Vd = Vg[Fg].reshape(-1, 3)
        Fd = np.arange(len(Vd), dtype=np.int64).reshape(-1, 3)
        cells = 12
        UVd = np.zeros((len(Vd), 2))
        for i in range(len(Fd)):
            cx, cy = (i % cells + 0.5) * 64 / cells + 0.13, (i // cells + 0.5) * 64 / cells + 0.13
            for k, (ox, oy) in enumerate(((0.0, 0.0), (0.6, 0.0), (0.0, 0.6))):
                UVd[i * 3 + k] = ((cx + ox) / 64, 1.0 - (cy + oy) / 64)
        dense = os.path.join(d, 'dense.glb')
        write(dense, Vd, Fd, UVd)
        py0, px0, _ = T.texel_points(Vd, Fd, UVd, 64)
        py1, px1, P1 = T.texel_points(Vd, Fd, UVd, 64, conservative=True)
        check('консервативные тексели: у крошечных островков появились свои (точек больше, чем без них)', len(py1) > len(py0) and len(py1) >= 0.99 * len(Fd), (len(py0), len(py1), len(Fd)))
        rep_d = T.transfer(nat, dense, os.path.join(d, 'dense-out.glb'), size=64)
        gd = T.load_glb(os.path.join(d, 'dense-out.glb'))
        rgd = np.asarray(gd['base'].convert('RGBA'))
        err = np.abs(rgd[py1, px1, 0].astype(float) - P1[:, 0] * 255)
        check('мелкие грани: цвет тексела по центру развёртки верный (ошибка ≤ 12 из 255, p99)', np.percentile(err, 99) <= 12, float(np.percentile(err, 99)))
        c2h = T.stage02(run, 'mid:eid9', nat, os.path.join(d, 'dense-out.glb'), rep_d)
        check('этап 02: крошечные островки, но цвет с верного места → faces_with_texel ≥ 99 %', c2h['metric']['value'] >= T.FACES_TEXEL_MIN, c2h['metric'])
        # форма не от этого черновика (другое положение/оси) — Chamfer выше порога
        c2g = T.stage02(run, 'mid:eid7', nat, os.path.join(d, 'far-out.glb'), rep2)
        check('этап 02: форма не от этого черновика → не прошёл, причина называет Chamfer',
              (not c2g['passed']) and c2g['metrics']['chamfer_diag']['value'] > T.CHAMFER_MAX and 'chamfer_diag' in c2g['reason'], c2g['reason'])
        ps = T._paint_stage()
        ok, why = ps.gate(run, 'mid:eid1', ['01-trellis', '02-prep'])
        check('gate: eid1 оба этапа пройдены → можно дальше', ok, why)
        ok2, why2 = ps.gate(run, 'mid:eid2', ['01-trellis'])
        check('gate: eid2 без baseColor — дальше не идёт', not ok2, why2)

        # команда transfer: отказ → код 3 и под рабочим именем файла НЕТ (лежит `.rejected.glb`); успех → код 0 и файл есть
        import subprocess
        cli = [sys.executable, os.path.join(HERE, 'sg_color_transfer.py'), 'transfer', '--native', nat, '--size', '64']
        o_bad = os.path.join(d, 'cli-bad.glb')
        r_bad = subprocess.run(cli + ['--shape', far_shape, '--out', o_bad], capture_output=True, text=True)
        check('transfer (CLI): далёкая форма → код 3, рабочего файла нет, есть .rejected.glb',
              r_bad.returncode == 3 and not os.path.exists(o_bad) and os.path.exists(os.path.join(d, 'cli-bad.rejected.glb')), (r_bad.returncode, r_bad.stdout[-200:], r_bad.stderr[-200:]))
        o_ok = os.path.join(d, 'cli-ok.glb')
        r_ok = subprocess.run(cli + ['--shape', shp, '--out', o_ok], capture_output=True, text=True)
        check('transfer (CLI): своя форма → код 0 и файл есть', r_ok.returncode == 0 and os.path.exists(o_ok), (r_ok.returncode, r_ok.stderr[-200:]))

    # sg_prep_shape: по умолчанию выключено (Blender в CI нет — проверяем текст)
    src = open(os.path.join(HERE, 'sg_prep_shape.py'), encoding='utf-8').read()
    check("sg_prep_shape.py: флаг --color-from есть, по умолчанию None", "'--color-from'" in src and 'default=None' in src.split("'--color-from'")[1].split('\n')[0])
    check('sg_prep_shape.py: перенос только при флаге (`if a.color_from`)', 'if a.color_from' in src)
    check('sg_prep_shape.py: развёртка при --color-from 89/0.0005, без флага прежняя 66/0.003',
          'a.angle = 89.0 if a.color_from else 66.0' in src and 'a.margin = 0.0005 if a.color_from else 0.003' in src)
    print('ИТОГО:', 'всё в норме' if not FAILS else f'провалено {len(FAILS)}: {FAILS}')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
