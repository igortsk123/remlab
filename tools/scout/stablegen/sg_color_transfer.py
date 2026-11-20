#!/usr/bin/env python3
"""ПЕРЕНОС РОДНОГО ЦВЕТА TRELLIS.2 НА УПРОЩЁННУЮ ФОРМУ + СТОРОЖ ШАГА 0 (T-20261120-167; план paint-photo-fill-01, шаг 0).

ЗАЧЕМ. `sg_prep_shape.py` режет форму до ≤150 тыс. граней и строит НОВУЮ развёртку — родная текстура TRELLIS.2 (baseColor + металл/шероховатость + альфа) при этом пропадала.
Здесь цвет переносится в новую развёртку по ближайшим точкам поверхности в 3D: у каждого текселя НОВОЙ карты берётся его точка на упрощённой форме, ищется ближайшая точка
родной формы (по тексельным точкам родной карты) и копируется её baseColor / металл-шероховатость / альфа. Только numpy + scipy + trimesh + PIL, видеокарта и Blender не нужны.

  python3 sg_color_transfer.py transfer --native родной.glb --shape упрощённая.glb --out результат.glb [--size 2048] [--max-dist 0.03]
      --shape — GLB с НОВОЙ развёрткой (`BakeUV` из sg_prep_shape.py), без текстуры; --size — сторона новой карты (по умолчанию — как у родной);
      --max-dist — доля диагонали габарита: дальше этого родной точки нет, тексель считается «без цвета» (заполняется ближайшим цветным; в отчёт идёт счётчик).
      Печатает одну строку `перенос: …` с долей текселей с цветом (ЦЕЛЬ ≥ 99 %). Код 0 — доля ≥ `--min-share` (99 %), 3 — меньше.
  python3 sg_color_transfer.py guard ПУТЬ...          # сторож шага 0: «baseColor пришёл?» и доля альфа<128 по занятым текселям; ПУТЬ — GLB или папка
      Счётчик: `ЦВЕТ: пришёл N из M; не пришёл K [список]; альфа<128 больше 30 %: J` — код 1, если хоть у одного GLB нет baseColor (fail-closed).
      Альфа — только сообщение, не отказ: замер T-166 (17 из 30 GLB с долей 31–94 % даже у велюра) показал, что как маска стекла она пока ненадёжна.
  python3 sg_color_transfer.py --selftest

ПОЧЕМУ БЕЗ НОРМАЛЕЙ. У сеток TRELLIS порядок обхода граней не всегда «наружу» (см. tex_coverage.py), знак нормали дал бы ложные несовпадения; ищем по положению.
Ограничение: у тонких двойных стенок (<~ шага текселя родной карты) ближайшая точка может оказаться на соседней стенке — такой тексель цвета той стенки; на мебели цвета сторон там совпадают.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'salad', 'trellis'))   # tex_coverage.raster — растеризатор граней на numpy

MIN_SHARE = 0.99          # доля текселей нового атласа с цветом, ниже — отказ (T-167)
MAX_DIST = 0.03           # доля диагонали габарита для «родная точка найдена»
ALPHA_SUSPECT = 0.30      # доля альфа<128 по занятым текселям, выше — «подозрительно» (только сообщение)
ALPHA_LT = 128


def load_glb(path: str):
    """GLB → {'V','F','UV','mesh','base','mr'}: вершины с применёнными трансформами сцены, развёртка (v вверх, как в trimesh), текстуры PIL (или None). Несколько геометрий сливаются."""
    import numpy as np
    import trimesh
    sc = trimesh.load(path, force='scene', process=False)
    parts = []
    for name, g in sc.geometry.items():
        try:
            g.apply_transform(sc.graph.get(name)[0])
        except Exception:  # noqa: BLE001
            pass
        parts.append(g)
    if not parts:
        raise ValueError(f'{os.path.basename(path)}: в файле нет геометрии')
    out = {'V': [], 'F': [], 'UV': [], 'base': None, 'mr': None}
    off = 0
    for g in parts:
        vis = getattr(g, 'visual', None)
        uv = getattr(vis, 'uv', None)
        mat = getattr(vis, 'material', None)
        if out['base'] is None:
            out['base'] = getattr(mat, 'baseColorTexture', None) or getattr(mat, 'image', None)
            out['mr'] = getattr(mat, 'metallicRoughnessTexture', None)
        out['V'].append(np.asarray(g.vertices, np.float64))
        out['F'].append(np.asarray(g.faces, np.int64) + off)
        out['UV'].append(np.asarray(uv, np.float64) if uv is not None else np.zeros((len(g.vertices), 2)))
        off += len(g.vertices)
    out['V'], out['F'], out['UV'] = np.concatenate(out['V']), np.concatenate(out['F']), np.concatenate(out['UV'])
    return out


def texel_points(V, F, UV, size: int):
    """Занятые развёрткой тексели карты size×size → (индексы пикселей (y, x), положения в 3D). Тексель — центр пикселя; точка = барицентрика грани."""
    import numpy as np
    from tex_coverage import raster
    xy = np.stack([UV[:, 0] * size, (1.0 - UV[:, 1]) * size], 1)
    ids, _ = raster(xy, F, size)
    pix = np.nonzero(ids >= 0)[0]
    f = ids[pix].astype(np.int64)
    py, px = pix // size, pix % size
    cx, cy = px + 0.5, py + 0.5
    A, B, C = xy[F[f, 0]], xy[F[f, 1]], xy[F[f, 2]]
    ar = (B[:, 0] - A[:, 0]) * (C[:, 1] - A[:, 1]) - (B[:, 1] - A[:, 1]) * (C[:, 0] - A[:, 0])
    ar = np.where(np.abs(ar) < 1e-12, 1e-12, ar)
    wa = ((B[:, 0] - cx) * (C[:, 1] - cy) - (B[:, 1] - cy) * (C[:, 0] - cx)) / ar
    wb = ((C[:, 0] - cx) * (A[:, 1] - cy) - (C[:, 1] - cy) * (A[:, 0] - cx)) / ar
    wc = 1.0 - wa - wb
    P = wa[:, None] * V[F[f, 0]] + wb[:, None] * V[F[f, 1]] + wc[:, None] * V[F[f, 2]]
    return py, px, P


def _rgba(img, size: int | None = None):
    import numpy as np
    from PIL import Image
    if img is None:
        return None
    im = img.convert('RGBA')
    if size and im.size != (size, size):
        im = im.resize((size, size), Image.BILINEAR)
    return np.asarray(im, np.uint8)


def _fill_empty(arr, filled):
    """Тексели вне островков и «без цвета» берут цвет ближайшего цветного (поля вокруг островков — иначе в швах просвечивает чёрное)."""
    import numpy as np
    from scipy import ndimage
    if filled.all() or not filled.any():
        return arr
    idx = ndimage.distance_transform_edt(~filled, return_distances=False, return_indices=True)
    return arr[idx[0], idx[1]]


def transfer(native_path: str, shape_path: str, out_path: str, size: int | None = None, max_dist: float = MAX_DIST) -> dict:
    """Главная функция: родной GLB (с цветом) + упрощённая форма с НОВОЙ развёрткой → GLB с перенесёнными baseColor / металл-шероховатость / альфа. Возвращает отчёт."""
    import numpy as np
    import trimesh
    from PIL import Image
    from scipy.spatial import cKDTree
    t0 = time.time()
    nat = load_glb(native_path)
    if nat['base'] is None:
        raise ValueError(f'{os.path.basename(native_path)}: в родном GLB нет baseColor — переносить нечего')
    tgt = load_glb(shape_path)
    nsize = nat['base'].size[0]
    size = int(size or nsize)
    base = _rgba(nat['base'])
    mr = _rgba(nat['mr'], nsize) if nat['mr'] is not None else None
    ny, nx, NP = texel_points(nat['V'], nat['F'], nat['UV'], nsize)
    ty, tx, TP = texel_points(tgt['V'], tgt['F'], tgt['UV'], size)
    t_ras = time.time() - t0
    diag = float(np.linalg.norm(nat['V'].max(0) - nat['V'].min(0))) or 1.0
    tree = cKDTree(NP)
    dist, j = tree.query(TP, k=1, workers=-1)
    ok = dist <= max_dist * diag
    oc_native = base[ny[j], nx[j]]
    oc_mr = mr[ny[j], nx[j]] if mr is not None else None
    res = np.zeros((size, size, 4), np.uint8)
    resmr = np.zeros((size, size, 4), np.uint8) if mr is not None else None
    filled = np.zeros((size, size), bool)
    res[ty[ok], tx[ok]] = oc_native[ok]
    if resmr is not None:
        resmr[ty[ok], tx[ok]] = oc_mr[ok]
    filled[ty[ok], tx[ok]] = True
    res = _fill_empty(res, filled)
    if resmr is not None:
        resmr = _fill_empty(resmr, filled)
    share = float(ok.mean()) if len(ok) else 0.0
    mat = trimesh.visual.material.PBRMaterial(
        baseColorTexture=Image.fromarray(res, 'RGBA'), baseColorFactor=np.array([255, 255, 255, 255], np.uint8),
        metallicRoughnessTexture=Image.fromarray(resmr[..., :3], 'RGB') if resmr is not None else None,
        metallicFactor=1.0 if resmr is not None else 0.0, roughnessFactor=1.0 if resmr is not None else 0.8, alphaMode='OPAQUE')
    m = trimesh.Trimesh(vertices=tgt['V'], faces=tgt['F'], process=False)
    m.visual = trimesh.visual.TextureVisuals(uv=tgt['UV'], material=mat)
    tmp = out_path + '.tmp.glb'
    m.export(tmp, file_type='glb')
    os.replace(tmp, out_path)
    rep = {'native': os.path.basename(native_path), 'native_size': nsize, 'size': size, 'native_texels': int(len(ny)), 'target_texels': int(len(ty)), 'with_color': int(ok.sum()),
           'share': round(share, 5), 'max_dist_m': round(max_dist * diag, 5), 'dist_p50': round(float(np.median(dist)), 6) if len(dist) else 0.0,
           'dist_p99': round(float(np.percentile(dist, 99)), 6) if len(dist) else 0.0, 'has_mr': mr is not None, 'sec_raster': round(t_ras, 1), 'sec_total': round(time.time() - t0, 1)}
    return rep


def guard_report(path: str) -> dict:
    """Сторож шага 0 по одному GLB: пришёл ли baseColor и какая доля альфа<128 по ЗАНЯТЫМ текселям развёртки (пустое поле атласа всегда 0 и не считается)."""
    import numpy as np
    r = {'file': os.path.basename(path), 'has_color': False, 'tex_size': None, 'alpha_lt128': None, 'alpha_suspect': False, 'error': None}
    try:
        g = load_glb(path)
    except Exception as e:  # noqa: BLE001
        r['error'] = str(e)[:120]
        return r
    if g['base'] is None:
        return r
    r['has_color'] = True
    n = g['base'].size[0]
    r['tex_size'] = n
    a = _rgba(g['base'])[..., 3]
    if a.min() == a.max() == 255:
        r['alpha_lt128'] = 0.0
        return r
    py, px, _ = texel_points(g['V'], g['F'], g['UV'], n)
    if len(py):
        r['alpha_lt128'] = round(float((a[py, px] < ALPHA_LT).mean()), 4)
        r['alpha_suspect'] = r['alpha_lt128'] > ALPHA_SUSPECT
    return r


def guard(paths: list[str]) -> tuple[int, str, list]:
    """Счётчик по набору: (код, строка итога, отчёты). Код 1 — есть GLB без baseColor или не открылся."""
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(os.path.join(p, x) for x in os.listdir(p) if x.endswith('.glb') and '.raw.' not in x)
        else:
            files.append(p)
    reps = [guard_report(f) for f in files]
    bad = [r for r in reps if not r['has_color']]
    sus = [r for r in reps if r['alpha_suspect']]
    line = (f'ЦВЕТ: пришёл {len(reps) - len(bad)} из {len(reps)}; не пришёл {len(bad)}'
            + (' [' + ', '.join(r['file'] for r in bad[:8]) + ('…' if len(bad) > 8 else '') + ']' if bad else '')
            + f'; альфа<128 больше {int(ALPHA_SUSPECT * 100)} %: {len(sus)}')
    return (1 if bad else 0), line, reps


# ---------------------------------------------------------------- проверка на каждом этапе (T-20261120-167; paint_stage.py — общий писатель check.json, T-164) -----------------------
FACES_MAX = 150000        # этап 02: граней упрощённой формы не больше


def _paint_stage():
    sys.path.insert(0, os.path.dirname(HERE))           # tools/scout
    import paint_stage
    return paint_stage


def _link(src: str, dst: str) -> None:
    import shutil
    if os.path.exists(dst):
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _atlas_frame(img, dst: str, side: int = 768) -> None:
    """Контрольный кадр этапа без Blender: карта цвета (baseColor) в квадрате side×side; альфа<255 показана шахматкой — сразу видно, цвет пришёл и не пустой."""
    import numpy as np
    from PIL import Image
    im = img.convert('RGBA').resize((side, side), Image.BILINEAR)
    a = np.asarray(im).astype(np.float32)
    yy, xx = np.mgrid[0:side, 0:side]
    chk = np.where(((yy // 24) + (xx // 24)) % 2 == 0, 200.0, 120.0)[..., None]
    al = a[..., 3:4] / 255.0
    rgb = a[..., :3] * al + chk * (1 - al)
    Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), 'RGB').save(dst)


def stage01(run: str, sku: str, native_glb: str, frame_src: str | None = None, seconds: float | None = None) -> dict:
    """Этап 01-trellis: родной GLB TRELLIS.2 — есть ли baseColor (главная мерка, порог 1) и доля альфа<128 по занятым текселям (справочная: пока ненадёжна как маска стекла, T-166).
    Папка `<run>/<sku>/01-trellis/`: `model.glb` (ссылка на родной), `frame.png` (кадр из `frame_src` или карта цвета), `check.json`."""
    ps = _paint_stage()
    d = ps.stage_dir(run, sku, '01-trellis')
    rep = guard_report(native_glb)
    if os.path.exists(native_glb):
        _link(native_glb, os.path.join(d, 'model.glb'))
    frame = None
    if frame_src and os.path.exists(frame_src):
        import shutil
        shutil.copy2(frame_src, os.path.join(d, 'frame.png'))
        frame = 'frame.png'
    elif rep['has_color']:
        _atlas_frame(load_glb(native_glb)['base'], os.path.join(d, 'frame.png'))
        frame = 'frame.png'
    return ps.write_check(d, '01-trellis', sku, None,
                          metric={'name': 'has_base_color', 'value': 1 if rep['has_color'] else 0, 'threshold': 1, 'op': '>='},
                          metrics={'alpha_lt128': {'value': rep['alpha_lt128'], 'op': '<=', 'note': 'справочная, без порога: у 17 из 30 GLB 31–94 % даже у велюра (T-166)'}},
                          reason=rep['error'] or ('' if rep['has_color'] else 'в родном GLB нет baseColor — цвет не пришёл'),
                          seconds=seconds, outputs=['model.glb'] if os.path.exists(native_glb) else [], frame=frame,
                          tex_size=rep['tex_size'], alpha_suspect=rep['alpha_suspect'], file=rep['file'])


def stage02(run: str, sku: str, native_glb: str, out_glb: str, rep: dict | None = None, faces_max: int = FACES_MAX, min_share: float = MIN_SHARE,
            frame_src: str | None = None, seconds: float | None = None) -> dict:
    """Этап 02-prep: упрощённая форма с НОВОЙ развёрткой и перенесённым цветом — доля текселей с цветом ≥ 99 % (главная мерка) и граней ≤ 150 тыс.
    `rep` — отчёт `transfer()`; нет — считается заново из файлов. Папка `<run>/<sku>/02-prep/`: `shape.glb`, `frame.png`, `check.json`."""
    ps = _paint_stage()
    d = ps.stage_dir(run, sku, '02-prep')
    if not os.path.exists(out_glb):
        return ps.write_check(d, '02-prep', sku, False, metric={'name': 'color_texel_share', 'value': None, 'threshold': min_share, 'op': '>='},
                              reason='нет выходного GLB упрощённой формы (перенос не удался или упрощение не прошло)', seconds=seconds)
    g = load_glb(out_glb)
    faces = int(len(g['F']))
    if rep is None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            rep = transfer(native_glb, out_glb, os.path.join(tmp, 'x.glb'), size=g['base'].size[0] if g['base'] is not None else None)
    _link(out_glb, os.path.join(d, 'shape.glb'))
    frame = None
    if frame_src and os.path.exists(frame_src):
        import shutil
        shutil.copy2(frame_src, os.path.join(d, 'frame.png'))
        frame = 'frame.png'
    elif g['base'] is not None:
        _atlas_frame(g['base'], os.path.join(d, 'frame.png'))
        frame = 'frame.png'
    return ps.write_check(d, '02-prep', sku, None,
                          metric={'name': 'color_texel_share', 'value': rep['share'], 'threshold': min_share, 'op': '>='},
                          metrics={'faces': {'value': faces, 'threshold': faces_max, 'op': '<='}},
                          seconds=seconds, outputs=['shape.glb'], frame=frame, native_texels=rep.get('native_texels'), target_texels=rep.get('target_texels'),
                          dist_p50=rep.get('dist_p50'), dist_p99=rep.get('dist_p99'), atlas=rep.get('size'), has_mr=rep.get('has_mr'))



def selftest() -> int:
    """Тот же набор проверок, что `tests_color_transfer.py` (отдельный файл запускается в CI)."""
    sys.path.insert(0, HERE)
    import tests_color_transfer as T
    return T.main()


def main() -> int:
    if '--selftest' in sys.argv:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    t = sub.add_parser('transfer')
    t.add_argument('--native', required=True)
    t.add_argument('--shape', required=True)
    t.add_argument('--out', required=True)
    t.add_argument('--size', type=int, default=None)
    t.add_argument('--max-dist', type=float, default=MAX_DIST)
    t.add_argument('--min-share', type=float, default=MIN_SHARE)
    g = sub.add_parser('guard')
    g.add_argument('paths', nargs='+')
    st = sub.add_parser('stages', help='записать этапы 01-trellis и (если есть --out) 02-prep в <run>/<sku>/NN-этап/ (check.json + кадр)')
    st.add_argument('--run', required=True)
    st.add_argument('--sku', required=True)
    st.add_argument('--native', required=True)
    st.add_argument('--out', default=None, help='упрощённая форма с перенесённым цветом (выход sg_prep_shape.py --color-from)')
    st.add_argument('--frame01', default=None)
    st.add_argument('--frame02', default=None)
    a = ap.parse_args()
    if a.cmd == 'stages':
        c1 = stage01(a.run, a.sku, a.native, a.frame01)
        print('01-trellis:', 'прошёл' if c1['passed'] else 'НЕ прошёл', c1['reason'])
        code = 0 if c1['passed'] else 1
        if a.out:
            c2 = stage02(a.run, a.sku, a.native, a.out, None, frame_src=a.frame02)
            print('02-prep:', 'прошёл' if c2['passed'] else 'НЕ прошёл', c2['reason'])
            code = code or (0 if c2['passed'] else 1)
        return code
    if a.cmd == 'guard':
        code, line, reps = guard(a.paths)
        for r in reps:
            if not r['has_color'] or r['alpha_suspect']:
                print('  ', r)
        print(line)
        return code
    rep = transfer(a.native, a.shape, a.out, a.size, a.max_dist)
    print('перенос:', rep)
    print(f'перенос: с цветом {rep["share"]:.2%} текселей нового атласа (цель ≥ {a.min_share:.0%}), расстояние p50 {rep["dist_p50"]}, p99 {rep["dist_p99"]}, {rep["sec_total"]} с')
    return 0 if rep['share'] >= a.min_share else 3


if __name__ == '__main__':
    sys.exit(main())
