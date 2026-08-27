#!/usr/bin/env python3
"""Сценовый рендер 3D-мешей товаров: один z-buffer на комнату и все GLB (план viz-mesh-orientation).

КОНВЕНЦИЯ (закреплена `orient_selftest.py`, НЕ выводить на бумаге — мерить):
- мир = оси сцены `planner.scene`: X — восток, Y — вверх, Z — «север» комнаты (рост y плана);
- поворот плана: front_world(rot) = (sin rot, 0, cos rot) — сверено со всеми предметами
  живого примера (диван rot 0 у южной стены лицом на север; стол rot 270 у восточной — на запад);
- канонический меш: фронт = +Z; выравнивание из калибровки — ry(−front_yaw)
  (ЗАМЕРЕНО mr-yaw-test 28.08; прежний комментарий с ry(front_yaw) был неверен — q23);
- итог: world = ry(rot) @ ry(front_yaw) @ scale(W,H,D) @ centre(v). `rot` — ИСТИНА ПЛАНА,
  рендер никогда не доворачивает предметы семантикой (разбор Codex q22).

Масштаб — по осям в реальные Ш×Г×В ПОСЛЕ выравнивания фронта (урок 28.08: иначе при
калибровке 90/270 ширина растягивает глубинную ось — столик вставал поперёк).
"""
import json
import math
import os

import numpy as np
from PIL import Image, ImageDraw

import mesh_render as MR

HERE = os.path.dirname(os.path.abspath(__file__))
# Высоты: measured (каталог/данные) → estimated (типовая по роли, ТОЛЬКО для черновика —
# меш с estimated-высотой не получает статус trusted, разбор q22)
H_DEF = {'диван': 85, 'стул': 92, 'столик': 45, 'тв-тумба': 50, 'стеллаж': 120, 'торшер': 160,
         'стол обеденный': 75, 'стол': 75, 'кашпо': 45, 'тв': 70, 'кресло': 80, 'комод': 85,
         'пуф': 42, 'банкетка': 45, 'витрина': 160, 'стенка': 180}
ANISO_MAX = 2.6           # max/min поосевого масштаба сверх естественного аспекта → geometry_suspect


def ry(deg: float) -> np.ndarray:
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], np.float32)


def front_world(rot_deg: float) -> np.ndarray:
    """Куда смотрит предмет плана: ry(rot) @ +Z."""
    return ry(rot_deg) @ np.array([0.0, 0.0, 1.0], np.float32)


def base_role(role: str) -> str:
    import re
    return re.sub(r'\s+\d+$', '', role or '').strip()


def item_height(it, name2h: dict | None = None) -> tuple[float, str]:
    """Высота и её происхождение: measured | catalog | estimated."""
    if getattr(it, 'h_cm', None):
        return float(it.h_cm), 'measured'
    nm = getattr(it, 'name', '') or ''
    if name2h and name2h.get(nm):
        return float(name2h[nm]), 'catalog'
    return float(H_DEF.get(base_role(getattr(it, 'role', '')), 80)), 'estimated'


def world_vertices(parts, place, front_yaw: float, name2h: dict | None = None):
    """Вершины всех частей в мировых см + матрица поворота и происхождение высоты."""
    it = place.item
    w, d = float(it.w_cm), float(it.d_cm)
    h, h_src = item_height(it, name2h)
    # ЗАМЕР mr-yaw-test 28.08: «фронт виден при yaw Yf» ⟺ фронт меша = ry(Yf)·Z ⟹
    # выравнивание на +Z — ОБРАТНЫЙ поворот. Знак не выводить на бумаге — мерить.
    Ra = ry(-front_yaw)
    allv = np.vstack([np.asarray(m.vertices, np.float32) for m in parts]) @ Ra.T
    ext = allv.max(axis=0) - allv.min(axis=0)
    lo = allv.min(axis=0)
    sx, sy, sz = w / max(ext[0], 1e-6), h / max(ext[1], 1e-6), d / max(ext[2], 1e-6)
    aniso = max(sx, sy, sz) / max(min(sx, sy, sz), 1e-6)
    R = ry(float(place.rot or 0))
    elev = float(getattr(place, 'elev_cm', 0) or 0)
    out = []
    for m in parts:
        v = np.asarray(m.vertices, np.float32) @ Ra.T
        v = (v - lo - ext / 2) * [sx, sy, sz]
        v[:, 1] += h / 2
        v = v @ R.T
        out.append(np.stack([place.x + v[:, 0], elev + v[:, 1], place.y + v[:, 2]], 1))
    return out, Ra, R, h_src, aniso


def raster_mesh(img, zbuf, parts, place, cam, W, Hpx, front_yaw: float,
                name2h: dict | None = None) -> dict:
    """Меш в общий буфер кадра; возвращает диагностику (h_src, aniso)."""
    worlds, Ra, R, h_src, aniso = world_vertices(parts, place, front_yaw, name2h)
    eye, fwd, right, up = cam.basis()
    eye = np.array(eye, np.float32)
    focal = (cam.width / 2) / math.tan(math.radians(cam.fov_deg) / 2)
    kx, ky = W / cam.width, Hpx / cam.height
    light = np.array([0.35, 0.7, 0.55], np.float32)
    light /= np.linalg.norm(light)
    for mesh, world in zip(parts, worlds):
        rel = world - eye
        z = rel @ np.array(fwd, np.float32)
        u = (cam.width / 2 + focal * (rel @ np.array(right, np.float32))
             / np.maximum(z, 1e-3)) * kx
        vv = (cam.height / 2 - focal * (rel @ np.array(up, np.float32)) / np.maximum(z, 1e-3)
              + getattr(cam, 'shift_y', 0.0) * cam.height) * ky
        f = np.asarray(mesh.faces, np.int32)
        tex, uvm = MR.texture_of(mesh)
        cols = MR.flat_colors(mesh)
        n = np.asarray(mesh.face_normals, np.float32) @ Ra.T @ R.T
        lam = np.clip(np.abs(n @ light), 0, 1)
        shade = (0.62 + 0.45 * lam)[:, None]
        for idx in np.argsort(-z[f].mean(axis=1)):
            a, b, c = f[idx]
            if z[a] <= 5 or z[b] <= 5 or z[c] <= 5:
                continue
            xs = np.array([u[a], u[b], u[c]])
            ys = np.array([vv[a], vv[b], vv[c]])
            x0, x1 = int(max(0, xs.min())), int(min(W - 1, xs.max()) + 1)
            y0, y1 = int(max(0, ys.min())), int(min(Hpx - 1, ys.max()) + 1)
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
            zz = w0 * z[a] + w1 * z[b] + w2 * z[c]
            sub = zbuf[y0:y1, x0:x1]
            upd = inside & (zz < sub)
            if not upd.any():
                continue
            sub[upd] = zz[upd]
            if tex is not None and uvm is not None:
                th_, tw_ = tex.shape[:2]
                uu = w0 * uvm[a, 0] + w1 * uvm[b, 0] + w2 * uvm[c, 0]
                vvv = w0 * uvm[a, 1] + w1 * uvm[b, 1] + w2 * uvm[c, 1]
                tx = np.clip((uu % 1.0) * (tw_ - 1), 0, tw_ - 1).astype(int)
                ty = np.clip((1.0 - (vvv % 1.0)) * (th_ - 1), 0, th_ - 1).astype(int)
                col = tex[ty, tx].astype(np.float32) * shade[idx]
            else:
                col = np.broadcast_to(cols[idx] * shade[idx], inside.shape + (3,))
            img[y0:y1, x0:x1][upd] = np.clip(col[upd], 0, 255)
    return {'h_src': h_src, 'aniso': round(float(aniso), 2),
            'suspect': aniso > ANISO_MAX}


def project_pts(cam, pts, W, Hpx):
    eye, fwd, right, up = cam.basis()
    eye = np.array(eye, np.float32)
    focal = (cam.width / 2) / math.tan(math.radians(cam.fov_deg) / 2)
    out = []
    for p in pts:
        rel = np.array(p, np.float32) - eye
        z = float(rel @ np.array(fwd, np.float32))
        if z <= 5:
            return None
        out.append(((cam.width / 2 + focal * float(rel @ np.array(right, np.float32)) / z)
                    * W / cam.width,
                    (cam.height / 2 - focal * float(rel @ np.array(up, np.float32)) / z
                     + getattr(cam, 'shift_y', 0.0) * cam.height) * Hpx / cam.height))
    return out


def draw_window_glass(out_img: Image.Image, room, cam) -> Image.Image:
    """Синее clay-окно → стекло с рамой по проекции проёма (стены за камерой пропускаются)."""
    W, Hpx = out_img.size
    arr = np.asarray(out_img).astype(int)
    win = ((np.abs(arr[..., 0] - 108) < 48) & (np.abs(arr[..., 1] - 166) < 48)
           & (np.abs(arr[..., 2] - 208) < 48))
    if win.sum() > 400:
        a = np.asarray(out_img).copy()
        ys, xs = np.where(win)
        y0, y1 = ys.min(), ys.max()
        grad = np.linspace(0, 1, max(2, y1 - y0 + 1))
        sky = (np.outer(1 - grad, [198, 222, 238])
               + np.outer(grad, [236, 238, 233])).astype(np.uint8)
        a[win] = sky[(ys - y0)]
        out_img = Image.fromarray(a)
    d2 = ImageDraw.Draw(out_img)
    ex, _, ez = (float(v) for v in cam.eye)
    beyond = {'north': ez > room.depth_cm, 'south': ez < 0, 'west': ex < 0,
              'east': ex > room.width_cm}
    for op in (getattr(room, 'openings', []) or []):
        if getattr(op, 'kind', '') != 'window' or beyond.get(op.wall):
            continue
        o0, o1 = op.offset_cm, op.offset_cm + op.width_cm
        lo = float(getattr(op, 'sill_cm', 0) or 90)
        hi = 210.0
        Wr, Dr = room.width_cm, room.depth_cm
        r = 1.5
        ends = {'south': [(o0, r), (o1, r)], 'north': [(o0, Dr - r), (o1, Dr - r)],
                'west': [(r, o0), (r, o1)], 'east': [(Wr - r, o0), (Wr - r, o1)]}[op.wall]
        quad = [(ends[0][0], hi, ends[0][1]), (ends[1][0], hi, ends[1][1]),
                (ends[1][0], lo, ends[1][1]), (ends[0][0], lo, ends[0][1])]
        dst = project_pts(cam, quad, W, Hpx)
        if dst is None:
            continue
        pts = [tuple(map(int, q)) for q in dst]
        if any(q[0] < -0.3 * W or q[0] > 1.3 * W or q[1] < -0.3 * Hpx or q[1] > 1.3 * Hpx
               for q in pts):
            continue
        d2.line(pts + [pts[0]], fill=(250, 250, 250), width=5)
        mt = ((pts[0][0] + pts[1][0]) // 2, (pts[0][1] + pts[1][1]) // 2)
        mb = ((pts[3][0] + pts[2][0]) // 2, (pts[3][1] + pts[2][1]) // 2)
        d2.line([mt, mb], fill=(250, 250, 250), width=4)
    return out_img
