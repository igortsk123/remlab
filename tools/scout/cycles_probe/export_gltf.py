"""ПРОБА T-20261117-02, шаг 2 (трассировка в браузере): та же выгрузка сцены (`export_scene.py`) → один GLB + камеры для three.js.
  ~/venvs/scout/bin/python cycles_probe/export_gltf.py <папка выгрузки сцены> <выход-папка>
Координаты: Blender (x, y, z-вверх) → glTF (x, z, −y), метры; поворот собственный, зеркала нет. Комната — плиты (свет не протекает), проёмы
по `cuts`, как в `render_cycles.py`; вид из окна — плоскость с картинкой (светится)."""
import json
import math
import os
import sys

import numpy as np
import trimesh
from PIL import Image
from trimesh.visual import TextureVisuals
from trimesh.visual.material import PBRMaterial

src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
M = json.load(open(os.path.join(src, 'scene.json'), encoding='utf-8'))
W, D, H = M['W'], M['D'], M['H']
CORNER, THICK = 10.0, 12.0


def g(v):
    v = np.asarray(v, np.float64)
    return np.stack([v[..., 0], v[..., 2], -v[..., 1]], -1)


def b(x, y, z):
    return np.array([x / 100.0, -z / 100.0, y / 100.0])


def hexrgb(h):
    return [int(h[i:i + 2], 16) for i in (1, 3, 5)] + [255]


scene = trimesh.Scene()
_img = {}


def img_of(rel):
    if rel not in _img:
        _img[rel] = Image.open(os.path.join(src, rel)).convert('RGB')
    return _img[rel]


def add(name, verts, faces, rgba=None, tex=None, uv=None, rough=0.7, emissive=None):
    m = trimesh.Trimesh(vertices=g(verts), faces=np.asarray(faces), process=False)
    if tex is not None and uv is not None:
        mat = PBRMaterial(baseColorTexture=img_of(tex), roughnessFactor=rough, metallicFactor=0.0)
        m.visual = TextureVisuals(uv=np.asarray(uv, np.float64), material=mat)
    else:
        kw = dict(baseColorFactor=rgba or [200, 200, 200, 255], roughnessFactor=rough, metallicFactor=0.0, doubleSided=True)
        if emissive is not None:
            kw['emissiveFactor'] = emissive
        m.visual = TextureVisuals(material=PBRMaterial(**kw))
        m.visual.uv = np.zeros((len(m.vertices), 2))
    scene.add_geometry(m, node_name=name, geom_name=name)


def slab(name, x0, x1, y0, y1, z0, z1, rgba):
    v = np.array([(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], float)
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    add(name, v, f, rgba=rgba, rough=0.9)


wall = hexrgb(M['finish']['wall']['colorHex'])
slab('floor', -CORNER / 100, (W + CORNER) / 100, -(D + CORNER) / 100, CORNER / 100, -THICK / 100, 0.0, hexrgb(M['finish']['floor']['colorHex']))
slab('ceiling', -CORNER / 100, (W + CORNER) / 100, -(D + CORNER) / 100, CORNER / 100, H / 100, (H + THICK) / 100, hexrgb(M['finish']['ceiling']['colorHex']))
FR = {'south': ((0, 0), (1, 0), (0, 1)), 'north': ((W, D), (-1, 0), (0, -1)), 'west': ((0, D), (0, -1), (1, 0)), 'east': ((W, 0), (0, 1), (-1, 0))}


def wall_rects(length, height, cuts):
    res, cur = [], 0.0
    for u0, u1, bt, tp in sorted(cuts):
        u0, u1 = max(0.0, min(length, u0)), max(0.0, min(length, u1))
        if u1 <= u0:
            continue
        if u0 > cur:
            res.append((cur, u0, 0.0, height))
        if bt > 0:
            res.append((u0, u1, 0.0, min(bt, height)))
        if tp < height:
            res.append((u0, u1, tp, height))
        cur = max(cur, u1)
    if cur < length:
        res.append((cur, length, 0.0, height))
    return [r for r in res if r[1] - r[0] > 0.5 and r[3] - r[2] > 0.5]


BOXF = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
for wl, ((ox, oz), (dx, dz), (nx, nz)) in FR.items():
    length = W if wl in ('north', 'south') else D
    cl = [(c['u0'], c['u1'], c['bottom'], c['top']) for c in M['cuts'].get(wl, [])]
    for k, (u0, u1, v0, v1) in enumerate(wall_rects(length, H, cl)):
        u0 = u0 - CORNER if u0 <= 0 else u0
        u1 = u1 + CORNER if u1 >= length else u1
        pts = []
        for back in (0.0, THICK):
            bx, bz = ox - nx * back, oz - nz * back
            for (u, v) in ((u0, v0), (u1, v0), (u1, v1), (u0, v1)):
                pts.append(b(bx + dx * u, v, bz + dz * u))
        add(f'wall_{wl}_{k}', np.array(pts), BOXF, rgba=wall, rough=0.92)
    for c in M['cuts'].get(wl, []):
        if c['kind'] in ('window', 'balcony'):
            continue
        bx, bz = ox - nx * 90.0, oz - nz * 90.0
        pts = [b(bx + dx * u, v, bz + dz * u) for (u, v) in ((c['u0'] - 60, 0), (c['u1'] + 60, 0), (c['u1'] + 60, c['top'] + 40), (c['u0'] - 60, c['top'] + 40))]
        add('hall', np.array(pts), [(0, 1, 2), (0, 2, 3)], rgba=[158, 153, 145, 255], emissive=[0.25, 0.24, 0.22])
for k, bdv in enumerate(M.get('backdrops', [])):
    bd = bdv['bd']
    (ox, oz), (dx, dz), (nx, nz) = FR[bdv['wall']]
    bx, bz = ox - nx * bd['back'], oz - nz * bd['back']
    pts = [b(bx + dx * u, v, bz + dz * u) for (u, v) in ((bd['u0'], bd['bottom']), (bd['u1'], bd['bottom']), (bd['u1'], bd['top']), (bd['u0'], bd['top']))]
    uvr = bd['uv']
    uv = [(uvr['u0'], uvr['v0']), (uvr['u1'], uvr['v0']), (uvr['u1'], uvr['v1']), (uvr['u0'], uvr['v1'])]
    m = trimesh.Trimesh(vertices=g(np.array(pts)), faces=[(0, 1, 2), (0, 2, 3)], process=False)
    im = img_of(bdv['tex'])
    mat = PBRMaterial(baseColorFactor=[0, 0, 0, 255], emissiveTexture=im, emissiveFactor=[1.0, 1.0, 1.0], doubleSided=True)
    m.visual = TextureVisuals(uv=np.asarray(uv, np.float64), material=mat)
    scene.add_geometry(m, node_name='view', geom_name='view')

for o in M['objs']:
    z = np.load(os.path.join(src, o['file']))
    uv = z['uv'] if 'uv' in z.files else None
    if o['n_faces'] == 12 and not o['tex']:
        vv = z['v']
        k_ = int(o['file'][1:4])
        vv = vv.mean(axis=0) + (vv - vv.mean(axis=0)) * (1.0 + 0.0006 * (1 + k_ % 4))
    else:
        vv = z['v']
    rgba = [int(c) for c in o['rgb']] + [255] if o['rgb'] else None
    add(o['file'], vv, z['f'], rgba=rgba, tex=o['tex'], uv=uv, rough=0.85 if o['tex'] else 0.6)

for k, r in enumerate(M['rugs']):
    im = img_of(r['tex'])
    arr = np.asarray(im, np.float32)
    corn = np.concatenate([arr[:6, :6].reshape(-1, 3), arr[:6, -6:].reshape(-1, 3), arr[-6:, :6].reshape(-1, 3), arr[-6:, -6:].reshape(-1, 3)])
    msk = np.linalg.norm(arr - np.median(corn, axis=0), axis=2) > 22
    if msk.mean() < 0.30:
        msk[:] = True
    ys, xs = np.where(msk)
    bx0, bx1, by0, by1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    bw, bh = bx1 - bx0 + 1, by1 - by0 + 1
    crop = im.crop((bx0, by0, bx1 + 1, by1 + 1))
    rel = f'tex/rugcrop{k}.png'
    crop.save(os.path.join(src, rel))
    hw, hd = r['w'] / 2, r['d'] / 2
    ang = math.radians(r['rot'])
    ca, sa = math.cos(ang), math.sin(ang)
    rot90 = (bw >= bh) != (r['w'] >= r['d'])
    pts, uvs = [], []
    for dx_, dz_, u, v in ((-hw, -hd, 0, 0), (hw, -hd, 1, 0), (hw, hd, 1, 1), (-hw, hd, 0, 1)):
        pts.append(b(r['x'] + dx_ * ca + dz_ * sa, 0.8, r['y'] - dx_ * sa + dz_ * ca))
        ua, va = (v, 1.0 - u) if rot90 else (u, v)
        uvs.append((ua, 1.0 - va))
    add(f'rug{k}', np.array(pts), [(0, 2, 1), (0, 3, 2)], tex=rel, uv=uvs, rough=0.95)

scene.export(os.path.join(out, 'scene.glb'))
cams = {}
for c in M['cams']:
    cams[c['name']] = {'eye': g(c['eye']).tolist(), 'fwd': g(c['fwd']).tolist(), 'up': g(c['up']).tolist(), 'fov': c['fov'],
                       'shift_y': c['shift_y'], 'w': c['w'], 'h': c['h']}
win = next((o['wall'] for o in M['openings'] if o['kind'] in ('window', 'balcony')), 'west')
(_, _), (_, _), (nx, nz) = FR[win]
cams['_sun_dir_inward'] = g([nx, -nz, 0]).tolist()
cams['_room'] = {'W': W / 100, 'D': D / 100, 'H': H / 100}
json.dump(cams, open(os.path.join(out, 'cams.json'), 'w'), indent=1)
print('glb', os.path.getsize(os.path.join(out, 'scene.glb')) // 1024, 'КБ')
