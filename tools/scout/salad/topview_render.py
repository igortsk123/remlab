#!/usr/bin/env python3
"""Вид сверху из меша → лёгкий PNG-спрайт для планировщика (план topview-from-mesh).

GLB в браузер не грузим: страница остаётся мгновенной, механика — как со спрайтами
(поворот картинкой). Фронт берём из orientation_state (калибратор mesh_orient):
confident → его yaw, symmetric/unobservable → 0. Рендер ортографический, сверху,
текстура + мягкий свет, прозрачный фон; supersample ×2 и downscale — против зубцов.
"""
import glob
import json
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

SRC = os.path.expanduser('~/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2')
OUT = os.path.expanduser('~/scout-scenes/mesh-topview')
PX = 420          # длинная сторона итогового спрайта


def yaw_for(key: str) -> tuple[float, str]:
    r = subprocess.run(['docker', 'exec', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
                        '-t', '-A', '-c',
                        f"SELECT status, resolution FROM orientation_state WHERE revision_key='{key}'"],
                       capture_output=True, text=True).stdout.strip()
    if not r or '|' not in r:
        return 0.0, 'unknown'
    st, res = r.split('|', 1)
    try:
        yaw = float(json.loads(res).get('yaw') or 0)
    except Exception:  # noqa: BLE001
        yaw = 0.0
    return (yaw if st == 'confident' else 0.0), st


def render_top(glb: str, yaw_deg: float, out_png: str) -> None:
    import cv2
    import trimesh
    from PIL import Image
    m = trimesh.load(glb, force='mesh')
    V = np.asarray(m.vertices, float).copy()
    F = np.asarray(m.faces)
    uv = np.asarray(m.visual.uv)
    tex = np.asarray(m.visual.material.baseColorTexture.convert('RGB'))
    th, tw = tex.shape[:2]
    V -= V.mean(axis=0)
    a = np.deg2rad(yaw_deg)
    Ry = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    V = V @ Ry.T
    # план: X→экранный x, Z→экранный y (фронт калибратора yaw=0 смотрит на -Z → низ экрана)
    S = 2
    ptx, ptz = np.ptp(V[:, 0]), np.ptp(V[:, 2])
    big = max(ptx, ptz) + 1e-9
    W = int(round(PX * S * ptx / big)) + 8
    H = int(round(PX * S * ptz / big)) + 8
    sc = (PX * S) / big
    px = np.stack([(V[:, 0] - V[:, 0].min()) * sc + 4,
                   (V[:, 2] - V[:, 2].min()) * sc + 4], axis=1).astype(np.int32)
    fy = V[F][:, :, 1].mean(axis=1)                 # выше — ближе к камере сверху
    fuv = np.clip(uv[F], 0, 1)
    tx = (fuv[..., 0].mean(axis=1) % 1.0 * (tw - 1)).astype(int)
    ty = (fuv[..., 1].mean(axis=1) % 1.0 * (th - 1)).astype(int)
    cols = tex[ty, tx].astype(float)
    e1 = V[F][:, 1] - V[F][:, 0]
    e2 = V[F][:, 2] - V[F][:, 0]
    nrm = np.cross(e1, e2)
    nrm /= (np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-9)
    cols = (cols * (0.62 + 0.38 * np.abs(nrm[:, 1]))[:, None]).clip(0, 255).astype(np.uint8)
    img = np.zeros((H, W, 4), np.uint8)
    for i in np.argsort(fy):                        # снизу вверх: верхние грани поверх
        c = cols[i]
        cv2.fillPoly(img, [px[F[i]]], (int(c[0]), int(c[1]), int(c[2]), 255))
    out = Image.fromarray(img, 'RGBA').resize((max(1, W // S), max(1, H // S)), Image.LANCZOS)
    out.save(out_png)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    manifest = {}
    n = 0
    for mp in sorted(glob.glob(os.path.join(SRC, '*/*/manifest.json'))):
        d = os.path.dirname(mp)
        glb = os.path.join(d, 'model.repaired.glb')
        if not os.path.exists(glb):
            glb = os.path.join(d, 'model.glb')
        if not os.path.exists(glb) or os.path.exists(os.path.join(d, 'owner_reject.json')):
            continue
        man = json.load(open(mp, encoding='utf-8'))
        sku = man['sku'].replace(':', '_')
        if sku in manifest:                          # свежайший каталог уже обработан
            continue
        key = f"{man['sku']}|{(man.get('input') or {}).get('sha') or man.get('source_sha') or ''}|v1"
        yaw, st = yaw_for(key)
        png = os.path.join(OUT, f'{sku}.png')
        try:
            render_top(glb, yaw, png)
        except Exception as e:  # noqa: BLE001
            print(f'  сбой {sku}: {str(e)[:80]}')
            continue
        dims = (man.get('input') or {}).get('dims_cm') or {}
        manifest[sku] = {'png': f'{sku}.png', 'yaw': yaw, 'orient': st,
                         'role': man.get('role'), 'w': dims.get('w'), 'd': dims.get('d')}
        n += 1
    json.dump(manifest, open(os.path.join(OUT, 'topview.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f'видов сверху: {n} → {OUT}')


if __name__ == '__main__':
    main()
