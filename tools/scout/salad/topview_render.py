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


def orient_v1_for(sku: str):
    """Вердикт БОЕВОГО каскада (contract orient-v1): полная матрица R (up+front) для меша.
    Есть R → применяем её и рендерим в канонике (фронт = MR-yaw 180); нет — фолбэк на yaw
    пилотного калибратора. Ваза 99272_180… (перевёрнутый меш) чинится именно этим."""
    import subprocess as sp
    r = sp.run(['docker', 'exec', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
                '-t', '-A', '-c',
                "SELECT resolution FROM orientation_state WHERE sku='" + sku + "' AND "
                "revision_key LIKE '%|orient-v1' ORDER BY updated DESC LIMIT 1"],
               capture_output=True, text=True).stdout.strip()
    if not r:
        return None
    try:
        res = json.loads(r)
        return res if res.get('R') else None
    except Exception:  # noqa: BLE001
        return None


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


def render_top(glb: str, yaw_deg: float, out_png: str, R=None) -> None:
    """Честный попиксельный рендер (z-buffer + UV) из mesh_render — камера строго сверху.
    Прежний центроидный сэмплинг давал «кляксы» цвета (владелец 31.08)."""
    import mesh_render as MR
    import numpy as np
    from PIL import Image
    parts = MR.load_parts(glb)
    if R is not None:
        Rm = np.asarray(R, np.float32)
        for m in parts:
            m.vertices = np.asarray(m.vertices, np.float32) @ Rm.T
        yaw_deg = 180.0                      # канон фронта боевого контура (MR-yaw 180)
    img = MR.render(parts, yaw_deg=yaw_deg, pitch_deg=90.0, size=(900, 900))
    a = np.asarray(img)
    ys, xs = np.where(a[..., 3] > 8)
    if len(ys):
        img = img.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
    w, h = img.size
    k = PX / max(w, h)
    img = img.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)
    img.save(out_png)


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
        # канон стратегий: ковры и прочие не-hunyuan виду сверху из МЕША не подлежат —
        # их фото и есть вид сверху (владелец 31.08), спрайт берётся из фото плоскостью
        import asset_strategy as AS
        if AS.strategy(man.get('role')) != 'hunyuan3d':
            continue
        key = f"{man['sku']}|{(man.get('input') or {}).get('sha') or man.get('source_sha') or ''}|v1"
        res1 = orient_v1_for(man['sku'])
        if res1 is not None:
            yaw, st = 180.0, f"orient-v1:{res1.get('status', '')}"
        else:
            yaw, st = yaw_for(key)
        png = os.path.join(OUT, f'{sku}.png')
        try:
            # кэш: рендер заново, если png отсутствует/старее меша или TOPVIEW_FORCE=1
            need = (os.environ.get('TOPVIEW_FORCE') == '1'
                    or not os.path.exists(png)
                    or os.path.getmtime(png) < os.path.getmtime(glb))
            if need:
                render_top(glb, yaw, png, R=(res1 or {}).get('R'))
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
