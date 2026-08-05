#!/usr/bin/env python3
"""Рендер 3D-модели товара БЕЗ видеокарты: свой растеризатор на numpy.

Зачем свой: на fal рендера готовых моделей нет (проверено 2026-08-05 — там только «фото → модель»),
а на машине разработки нет ни видеокарты, ни OpenGL. Треугольный z-буфер на numpy обходится без
драйверов: модель товара рендерится под НУЖНЫМ УГЛОМ и вставляется в наш коллаж.

Части модели рендерятся ПО ОТДЕЛЬНОСТИ: при склейке теряются текстурные координаты, и столешница
выходила чёрной.

  ~/venvs/scout/bin/python mesh_render.py model.glb --yaw 155 --out t.png
"""
import math
import sys

import numpy as np
import trimesh
from PIL import Image


def load_parts(path: str) -> list:
    """GLB → список частей со своими текстурами, вписанных в единичный куб."""
    scene = trimesh.load(path, force='scene')
    if hasattr(scene, 'geometry'):
        parts = []
        for name, geom in scene.geometry.items():
            g = geom.copy()
            try:
                g.apply_transform(scene.graph.get(name)[0])
            except Exception:  # noqa: BLE001 — часть без трансформа берём как есть
                pass
            parts.append(g)
    else:
        parts = [scene]
    allv = np.vstack([np.asarray(p.vertices, np.float64) for p in parts])
    centre = (allv.max(axis=0) + allv.min(axis=0)) / 2
    scale = 1.0 / max((allv.max(axis=0) - allv.min(axis=0)).max(), 1e-6)
    for p in parts:
        p.apply_translation(-centre)
        p.apply_scale(scale)
    return parts


def texture_of(mesh):
    """Картинка текстуры и UV вершин, если они есть."""
    vis = getattr(mesh, 'visual', None)
    uv = getattr(vis, 'uv', None)
    mat = getattr(vis, 'material', None)
    img = getattr(mat, 'baseColorTexture', None) if mat is not None else None
    if img is None and mat is not None:
        img = getattr(mat, 'image', None)
    if uv is None or img is None:
        return None, None
    return np.asarray(img.convert('RGB')), np.asarray(uv, np.float32)


def flat_colors(mesh) -> np.ndarray:
    """Запасной цвет граней, если текстуры нет."""
    vis = getattr(mesh, 'visual', None)
    try:
        fc = getattr(vis, 'face_colors', None)
        if fc is not None:
            return np.asarray(fc)[:, :3].astype(np.float32)
        vc = getattr(vis, 'vertex_colors', None)
        if vc is not None:
            return np.asarray(vc)[:, :3].astype(np.float32)[mesh.faces].mean(axis=1)
    except Exception:  # noqa: BLE001
        pass
    return np.full((len(mesh.faces), 3), 175.0, np.float32)


def render(parts, yaw_deg: float, pitch_deg: float = 18.0,
           size: tuple[int, int] = (900, 900), light=(0.35, 0.7, 0.9),
           flat: tuple[int, int, int] | None = None) -> Image.Image:
    """Ортографический рендер с общим z-буфером. RGBA, фон прозрачный.

    `flat` — залить одним цветом вместо текстуры: нужен для СХЕМЫ, где важна форма и место
    предмета, а внешний вид модель берёт с эталона (владелец, 2026-08-05).
    """
    if not isinstance(parts, (list, tuple)):
        parts = [parts]
    W, H = size
    cy, sy = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    cp, sp = math.cos(math.radians(pitch_deg)), math.sin(math.radians(pitch_deg))
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], np.float32)
    rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]], np.float32)
    rot = ry.T @ rx.T

    allp = np.vstack([np.asarray(m.vertices, np.float32) @ rot for m in parts])
    span = max(np.ptp(allp[:, 0]), np.ptp(allp[:, 1])) * 1.08 or 1.0
    ox, oy = allp[:, 0].mean(), allp[:, 1].mean()

    img = np.zeros((H, W, 3), np.float32)
    zbuf = np.full((H, W), -1e9, np.float32)
    alpha = np.zeros((H, W), bool)
    key = np.array(light, np.float32) / np.linalg.norm(light)

    for mesh in parts:
        p = np.asarray(mesh.vertices, np.float32) @ rot
        f = np.asarray(mesh.faces, np.int32)
        sx = (p[:, 0] - ox) / span * W + W / 2
        sv = H / 2 - (p[:, 1] - oy) / span * W
        depth = p[:, 2]
        tex, uv = texture_of(mesh)
        cols = flat_colors(mesh)
        n = np.asarray(mesh.face_normals, np.float32) @ rot
        lam = np.clip(np.abs(n @ key), 0.0, 1.0)
        fill = np.clip(np.abs(n[:, 2]), 0.0, 1.0)
        shade = (0.55 + 0.5 * lam + 0.2 * fill)[:, None]

        for idx in np.argsort(depth[f].mean(axis=1)):
            a, b, c = f[idx]
            xs = np.array([sx[a], sx[b], sx[c]])
            ys = np.array([sv[a], sv[b], sv[c]])
            x0, x1 = int(max(0, xs.min())), int(min(W - 1, xs.max()) + 1)
            y0, y1 = int(max(0, ys.min())), int(min(H - 1, ys.max()) + 1)
            if x1 <= x0 or y1 <= y0:
                continue
            det = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
            if abs(det) < 1e-9:
                continue
            gy, gx = np.mgrid[y0:y1, x0:x1]
            w0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / det
            w1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / det
            w2 = 1 - w0 - w1
            inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if not inside.any():
                continue
            z = w0 * depth[a] + w1 * depth[b] + w2 * depth[c]
            sub = zbuf[y0:y1, x0:x1]
            upd = inside & (z > sub)
            if not upd.any():
                continue
            sub[upd] = z[upd]
            if flat is not None:
                col = np.repeat(np.array(flat, np.float32)[None, :], inside.size, axis=0)
                col = col.reshape(inside.shape + (3,)) * shade[idx]
                img[y0:y1, x0:x1][upd] = np.clip(col[upd], 0, 255)
            elif tex is not None:
                th, tw = tex.shape[:2]
                u = w0 * uv[a, 0] + w1 * uv[b, 0] + w2 * uv[c, 0]
                vv = w0 * uv[a, 1] + w1 * uv[b, 1] + w2 * uv[c, 1]
                tx = np.clip((u % 1.0) * (tw - 1), 0, tw - 1).astype(int)
                ty = np.clip((1.0 - (vv % 1.0)) * (th - 1), 0, th - 1).astype(int)
                col = tex[ty, tx].astype(np.float32) * shade[idx]
                img[y0:y1, x0:x1][upd] = np.clip(col[upd], 0, 255)
            else:
                img[y0:y1, x0:x1][upd] = np.clip(cols[idx] * shade[idx], 0, 255)
            alpha[y0:y1, x0:x1] |= upd

    return Image.fromarray(np.dstack([img.astype(np.uint8),
                                      (alpha * 255).astype(np.uint8)]), 'RGBA')


def main() -> None:
    path = sys.argv[1]
    yaw = float(sys.argv[sys.argv.index('--yaw') + 1]) if '--yaw' in sys.argv else 30.0
    pitch = float(sys.argv[sys.argv.index('--pitch') + 1]) if '--pitch' in sys.argv else 18.0
    out = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else 'render.png'
    parts = load_parts(path)
    print(f'частей {len(parts)}, граней {sum(len(p.faces) for p in parts)}')
    render(parts, yaw, pitch).save(out)
    print(out)


if __name__ == '__main__':
    main()
