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


def photo_upright_flip(glb: str, cutout_png: str, R=None) -> bool:
    """«Верх» по фото: профиль ширины маски фото (сверху вниз) против профиля меша по
    высоте в двух гипотезах — как есть и перевёрнут. Возвращает True, если перевёрнутая
    заметно лучше. Нужен, когда каскад отверг свой up-детектор (ваза/лампа 99272: identity).
    """
    import numpy as np
    import trimesh
    from PIL import Image
    try:
        cut = np.asarray(Image.open(cutout_png).convert('RGBA'))[..., 3] > 100
        rows = cut.sum(axis=1).astype(float)
        nz = np.where(rows > 0)[0]
        if len(nz) < 10:
            return False
        prof_photo = rows[nz[0]:nz[-1] + 1]
        B = 24
        idx = (np.linspace(0, len(prof_photo) - 1, B)).astype(int)
        prof_photo = prof_photo[idx]
        m = trimesh.load(glb, force='mesh')
        V = np.asarray(m.vertices, np.float32)
        if R is not None:
            V = V @ np.asarray(R, np.float32).T
        lo, hi = V[:, 1].min(), V[:, 1].max()
        ys = (V[:, 1] - lo) / max(hi - lo, 1e-6)
        prof_mesh = np.zeros(B)
        for i in range(B):
            sel = (ys >= i / B) & (ys < (i + 1) / B)
            if sel.sum() >= 6:
                prof_mesh[i] = np.ptp(V[sel][:, 0]) + np.ptp(V[sel][:, 2])
        prof_mesh = prof_mesh[::-1]                     # фото идёт сверху вниз
        def corr(a, b):
            a = (a - a.mean()) / (a.std() + 1e-6)
            b = (b - b.mean()) / (b.std() + 1e-6)
            return float((a * b).mean())
        c_asis = corr(prof_photo, prof_mesh)
        c_flip = corr(prof_photo, prof_mesh[::-1])
        return c_flip > c_asis + 0.10
    except Exception:  # noqa: BLE001 — проверка не должна ронять рендер
        return False


UP_HYPS = {                       # какая ось меша на самом деле «вверх» (пуф лежал на боку)
    'I':    [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    'X180': [[1, 0, 0], [0, -1, 0], [0, 0, -1]],
    'X90':  [[1, 0, 0], [0, 0, -1], [0, 1, 0]],
    'X-90': [[1, 0, 0], [0, 0, 1], [0, -1, 0]],
    'Z90':  [[0, -1, 0], [1, 0, 0], [0, 0, 1]],
    'Z-90': [[0, 1, 0], [-1, 0, 0], [0, 0, 1]],
}


def photo_upright_hyp(glb: str, cutout_png: str, dims: dict | None, R=None) -> str:
    """Выбор «верха» из 6 гипотез: корреляция профиля ширины с фото + соответствие
    пропорций паспорту (h/w различает лежащий пуф). Возвращает ключ UP_HYPS."""
    import numpy as np
    import trimesh
    from PIL import Image
    try:
        cut = np.asarray(Image.open(cutout_png).convert('RGBA'))[..., 3] > 100
        rows = cut.sum(axis=1).astype(float)
        nz = np.where(rows > 0)[0]
        if len(nz) < 10:
            return 'I'
        B = 24
        idx = (np.linspace(nz[0], nz[-1], B)).astype(int)
        prof_photo = rows[idx]
        m = trimesh.load(glb, force='mesh')
        V0 = np.asarray(m.vertices, np.float32)
        if R is not None:
            V0 = V0 @ np.asarray(R, np.float32).T
        d0 = dims or {}
        w, dd, h = d0.get('w'), d0.get('d'), d0.get('h')
        want_hw = (float(h) / float(max(w, dd or w))) if (h and w) else None
        def corr(a, b):
            a = (a - a.mean()) / (a.std() + 1e-6)
            b = (b - b.mean()) / (b.std() + 1e-6)
            return float((a * b).mean())
        best, best_score = 'I', -9
        for name, Rh in UP_HYPS.items():
            V = V0 @ np.asarray(Rh, np.float32).T
            lo, hi = V[:, 1].min(), V[:, 1].max()
            ys = (V[:, 1] - lo) / max(hi - lo, 1e-6)
            prof = np.zeros(B)
            for i in range(B):
                sel = (ys >= i / B) & (ys < (i + 1) / B)
                if sel.sum() >= 6:
                    prof[i] = np.ptp(V[sel][:, 0]) + np.ptp(V[sel][:, 2])
            score = corr(prof_photo, prof[::-1])
            if want_hw is not None:
                got_hw = float((hi - lo) / max(np.ptp(V[:, 0]), np.ptp(V[:, 2]), 1e-6))
                score += 0.5 * max(0.0, 1.0 - abs(got_hw - want_hw) / max(want_hw, 0.2))
            bonus = 0.06 if name == 'I' else 0.0       # гистерезис: не дёргать без нужды
            if score + bonus > best_score:
                best, best_score = name, score + bonus
        # куб/неразличимо (пуф 45³): гипотезы не разделяются — честно «не определено»
        ext = [float(np.ptp(V0[:, i])) for i in range(3)]
        cubish = max(ext) / max(min(ext), 1e-6) < 1.10
        return (best, not cubish)
    except Exception:  # noqa: BLE001
        return ('I', False)


def render_front(glb: str, yaw_deg: float, out_png: str) -> None:
    """Взгляд СПЕРЕДИ по вердикту фронта (владелец 31.08: «фронт не показал») —
    камера чуть сверху (pitch 15°), чтобы читалась форма."""
    import mesh_render as MR
    import numpy as np
    from PIL import Image
    img = MR.render(MR.load_parts(glb), yaw_deg=yaw_deg, pitch_deg=15.0, size=(700, 700))
    a = np.asarray(img)
    ys, xs = np.where(a[..., 3] > 8)
    if len(ys):
        img = img.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
    w, h = img.size
    k = 320 / max(w, h)
    img = img.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)
    img.save(out_png)


def render_top(glb: str, yaw_deg: float, out_png: str, R=None, flip=False) -> None:
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
    if flip and flip != 'I':
        Fx = np.asarray(UP_HYPS[flip], np.float32)
        for m in parts:
            m.vertices = np.asarray(m.vertices, np.float32) @ Fx.T
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
    skip = int(os.environ.get('TOPVIEW_SKIP', 0))
    lim = int(os.environ.get('TOPVIEW_LIMIT', 0)) or None
    seen_i = 0
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
        seen_i += 1
        if seen_i <= skip or (lim and seen_i > skip + lim):
            continue
        key = f"{man['sku']}|{(man.get('input') or {}).get('sha') or man.get('source_sha') or ''}|v1"
        res1 = orient_v1_for(man['sku'])
        if res1 is not None:
            # ТОЛЬКО снэпнутый фронт (владелец 31.08: полный R давал наклоны и «фронт под
            # углом», а мой авто-переворот портил здоровые диваны — «до этого было лучше»)
            raw_yaw = float(res1.get('legacy_front_yaw') or 0)
            yaw = float(round(raw_yaw / 90.0) * 90 % 360)
            st = f"orient-v1:{res1.get('status', '')}:{res1.get('source', '')}"
        else:
            yaw, st = yaw_for(key)
        png = os.path.join(OUT, f'{sku}.png')
        fpng = os.path.join(OUT, f'{sku}.front.png')
        VESSEL = {'ваза', 'кашпо', 'лампа', 'люстра', 'торшер'}
        base_role = (man.get('role') or '').split()[0] if man.get('role') else ''
        ext_ok = True
        try:
            import trimesh as _t
            import numpy as _np
            _m = _t.load(glb, force='mesh')
            _e = [float(_np.ptp(_np.asarray(_m.vertices)[:, k])) for k in range(3)]
            ext_ok = max(_e) / max(min(_e), 1e-6) >= 1.10
        except Exception:  # noqa: BLE001
            pass
        if base_role in VESSEL or not ext_ok:
            st += ':upright_unsure'
        # корпусная мебель: фронт по деталям фасада (ручки/филёнки) — владелец 31.08
        # «реальная проблема с тв-тумбами и комодами»; сильнее вердикта каскада
        if base_role in {'комод', 'тв-тумба', 'тумба'}:
            try:
                import importlib.util as _il
                _spc = _il.spec_from_file_location('cabf', os.path.join(HERE, 'cabinet_front.py'))
                _cf = _il.module_from_spec(_spc); _spc.loader.exec_module(_cf)
                cyaw, csrc, _dbg = _cf.front_by_depth(glb)
                if cyaw is not None:
                    yaw = cyaw
                    st = f'orient-v1:{csrc}'
                else:
                    st += ':cabinet_unsure'
            except Exception as _e:  # noqa: BLE001
                print(f'  cabinet_front пропущен {sku}: {str(_e)[:60]}')
        try:
            # кэш: рендер заново, если png отсутствует/старее меша или TOPVIEW_FORCE=1
            need = (os.environ.get('TOPVIEW_FORCE') == '1'
                    or not os.path.exists(png)
                    or os.path.getmtime(png) < os.path.getmtime(glb))
            if need:
                render_top(glb, yaw, png)
                render_front(glb, yaw, fpng)
        except Exception as e:  # noqa: BLE001 — один битый меш не валит страницу
            print(f'  сбой {sku}: {str(e)[:80]}')
            continue
        dims = (man.get('input') or {}).get('dims_cm') or {}
        manifest[sku] = {'png': f'{sku}.png', 'yaw': yaw, 'orient': st,
                         'role': man.get('role'), 'w': dims.get('w'), 'd': dims.get('d')}
        n += 1
    mpth = os.path.join(OUT, 'topview.json')
    if os.path.exists(mpth) and (skip or lim):
        base = json.load(open(mpth, encoding='utf-8'))
        base.update(manifest)
        manifest = base
    json.dump(manifest, open(mpth, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f'видов сверху: {n} → {OUT}')


if __name__ == '__main__':
    main()
