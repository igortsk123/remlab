"""Тесты vertex_normals и NORMAL в GLB писателей этапов 06/07 (T-20261124-10/4). Синтетика, без GPU и сети.
Сфера «широта–долгота» со швом UV по меридиану (позиции дублируются) и вырожденными гранями у полюсов; куб — складка 90°.
Запуск: python tests_vertex_normals.py → «ошибок 0»."""
import json
import os
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import numpy as np
import vertex_normals as VN

bad = 0


def ok(cond, msg):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + msg)
    if not cond:
        bad += 1


def sphere(nlat=16, nlon=24, flip_island=False):
    """Вершины сетки (nlat+1)×(nlon+1): последний столбец — дубль нулевого (шов UV). У полюсов вырожденные треугольники."""
    th = np.linspace(0, np.pi, nlat + 1)
    ph = np.linspace(0, 2 * np.pi, nlon + 1)
    T, P = np.meshgrid(th, ph, indexing='ij')
    V = np.stack([np.sin(T) * np.cos(P), np.cos(T), np.sin(T) * np.sin(P)], -1).reshape(-1, 3)
    UV = np.stack([P / (2 * np.pi), T / np.pi], -1).reshape(-1, 2)
    idx = lambda i, j: i * (nlon + 1) + j
    F = []
    for i in range(nlat):
        for j in range(nlon):
            a, b, c, d = idx(i, j), idx(i, j + 1), idx(i + 1, j), idx(i + 1, j + 1)
            F += [[a, b, c], [b, d, c]]          # обход: нормаль наружу
    F = np.array(F, np.int64)
    if flip_island:                               # правая половина по долготе — с обратным обходом (остров TRELLIS)
        half = (V[F].mean(axis=1)[:, 2] > 0)
        F[half] = F[half][:, ::-1]
    return V, F, UV


def test_sphere_seam_and_counts():
    V, F, UV = sphere()
    N, ref = VN.recipe_normals(V, F, return_ref=True)
    ok(N.shape == V.shape and np.isfinite(N).all(), 'нормали: форма как у вершин, без NaN (вырожденные грани у полюсов пропущены)')
    ok(np.allclose(np.linalg.norm(N, axis=1), 1.0, atol=1e-6), 'все нормали единичные (в том числе на полюсах)')
    mid = np.abs(V[:, 1]) < 0.8
    cos = (N[mid] * V[mid]).sum(1)
    ok(cos.min() > 0.99, f'сглаженная нормаль сферы смотрит наружу, как радиус (мин cos {cos.min():.4f})')
    nlon = 24
    seam_a = np.arange(0, len(V), nlon + 1)[3:-3]
    seam_b = seam_a + nlon
    ang = np.degrees(np.arccos(np.clip((N[seam_a] * N[seam_b]).sum(1), -1, 1)))
    ok(ang.max() < 0.5, f'шов UV: нормали дублей одной позиции совпали (макс {ang.max():.3f}°)')
    rep = VN.seam_report(V, N, ref)
    ok(rep['smooth_share'] > 0.5 and rep.get('smooth_max_deg', 99) < 0.5, f'seam_report: гладкие швы согласованы {rep}')


def test_crease_cube():
    b = np.array([[x, y, z] for x in (0, 1) for y in (0, 1) for z in (0, 1)], float)
    V, F = [], []
    for ax in range(3):                           # каждая грань куба — свои 4 вершины (как у развёртки по островам)
        for s in (0, 1):
            o = len(V)
            for u, w in ((0, 0), (1, 0), (1, 1), (0, 1)):
                p = [0.0, 0.0, 0.0]
                p[ax] = float(s)
                p[(ax + 1) % 3] = float(u)
                p[(ax + 2) % 3] = float(w)
                V.append(p)
            F += [[o, o + 1, o + 2], [o, o + 2, o + 3]]
    V, F = np.array(V), np.array(F)
    N = VN.recipe_normals(V, F)
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    fn /= np.linalg.norm(fn, axis=1, keepdims=True)
    mine = np.zeros_like(N)
    for k in range(3):
        mine[F[:, k]] = fn
    ok(np.allclose(N, mine, atol=1e-9), 'куб с вершинами по граням: складка 90° не сглаживается (нормаль вершины = нормаль её грани)')
    ok(len(N) == len(V) == 24, 'число вершин не меняется')


def test_flipped_island_not_averaged():
    V, F, UV = sphere(flip_island=True)
    N, ref = VN.recipe_normals(V, F, return_ref=True)
    # вершины, у которых все грани перевёрнуты (z заметно > 0): нормаль — по обходу, т.е. ВНУТРЬ (зритель с двусторонней отрисовкой её перевернёт сам)
    deep = (V[:, 2] > 0.3) & (np.abs(V[:, 1]) < 0.7)
    cos = (N[deep] * V[deep]).sum(1)
    ok(cos.max() < -0.9, f'остров с обратным обходом: нормаль по обходу (внутрь), с соседним не смешана (макс cos {cos.max():.3f})')


def test_degenerate_only():
    V = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [0, 1, 0]], float)
    F = np.array([[0, 1, 2], [0, 1, 3]])           # первая — вырожденная (коллинеарна)
    N = VN.recipe_normals(V, F)
    ok(np.isfinite(N).all() and np.allclose(np.linalg.norm(N, axis=1), 1.0), 'вырожденная грань не даёт NaN, нормали единичные')
    ok(np.allclose(N[3], (0, 0, 1)), 'нормаль годной грани сохранена')


def test_choice_file_vs_recipe():
    V, F, UV = sphere()
    N, ref = VN.recipe_normals(V, F, return_ref=True)
    g = {'V': V, 'F': F, 'UV': UV, 'VN': N.copy()}
    ok(np.allclose(VN.geom_normals(g), N), 'нормали файла, согласованные на швах, берутся как есть')
    bad_vn = N.copy()
    bad_vn[np.arange(0, len(V), 25 + 0)[::1]] *= -1                      # ломаем часть дублей шва
    g2 = {'V': V, 'F': F, 'UV': UV, 'VN': bad_vn}
    rn = VN.geom_normals(g2)
    ok(np.allclose(rn, N), 'нормали файла, несогласованные на гладких швах (> 1 % швов расходится > 5°), заменены рецептом')
    ok(np.allclose(VN.geom_normals({'V': V, 'F': F, 'UV': UV}), N), 'нет NORMAL в файле (VN нет) → рецепт')


def glb_has_normal(path):
    raw = open(path, 'rb').read()
    n = struct.unpack('<I', raw[12:16])[0]
    doc = json.loads(raw[20:20 + n])
    return all('NORMAL' in p['attributes'] for m in doc['meshes'] for p in m['primitives']), doc


def test_writers_put_normal():
    import trimesh
    from PIL import Image
    import tex_coverage as TC
    import tex_fill as TF
    import tex_visible as TV
    V, F, UV = sphere()
    tex = np.full((64, 64, 3), 128, np.uint8)
    with tempfile.TemporaryDirectory() as d:
        for case, vn in (('без NORMAL во входе', None), ('с NORMAL во входе', VN.recipe_normals(V, F))):
            g = {'name': 'g', 'V': V, 'F': F, 'UV': UV, 'tex': tex, 'VN': vn}
            for nm, wr in (('06 write_glb', TV.write_glb), ('07 write_glb', TF.write_glb)):
                p = os.path.join(d, nm[:2] + ('a' if vn is None else 'b') + '.glb')
                wr([g], [tex], p)
                has, doc = glb_has_normal(p)
                ok(has, f'{nm}: NORMAL в файле ({case})')
                sc = trimesh.load(p, force='scene', process=False)
                m = next(iter(sc.geometry.values()))
                ok(len(m.vertices) == len(V) and len(m.faces) == len(F), f'{nm}: число вершин и граней не изменилось ({case})')
        # round-trip: файл с NORMAL → load_geoms даёт VN, файл без → None
        g = {'name': 'g', 'V': V, 'F': F, 'UV': UV, 'tex': tex, 'VN': VN.recipe_normals(V, F)}
        TV.write_glb([g], [tex], os.path.join(d, 'with.glb'))
        gl = TC.load_geoms(os.path.join(d, 'with.glb'))[0]
        ok(gl['VN'] is not None and gl['VN'].shape == V.shape, 'load_geoms: VN из файла с NORMAL')
        m0 = trimesh.Trimesh(vertices=V, faces=F, process=False)
        m0.visual = trimesh.visual.TextureVisuals(uv=UV, material=trimesh.visual.material.PBRMaterial(baseColorTexture=Image.fromarray(tex)))
        m0.export(os.path.join(d, 'without.glb'))
        has0, _ = glb_has_normal(os.path.join(d, 'without.glb'))
        gw = TC.load_geoms(os.path.join(d, 'without.glb'))[0]
        ok((not has0) and gw['VN'] is None, 'load_geoms: файл без NORMAL → VN = None (писатель досчитает по рецепту)')
        # цепочка 06 → 07 на файле без NORMAL: нормаль появляется и доживает
        TV.write_glb([gw], [tex], os.path.join(d, 'v.glb'))
        g7 = TC.load_geoms(os.path.join(d, 'v.glb'))[0]
        TF.write_glb([g7], [tex], os.path.join(d, 'f.glb'))
        ok(glb_has_normal(os.path.join(d, 'f.glb'))[0], 'цепочка вход без NORMAL → 06 → 07: NORMAL есть и в filled.glb')


def main():
    test_sphere_seam_and_counts()
    test_crease_cube()
    test_flipped_island_not_averaged()
    test_degenerate_only()
    test_choice_file_vs_recipe()
    test_writers_put_normal()
    print(f'tests_vertex_normals: ошибок {bad}')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
