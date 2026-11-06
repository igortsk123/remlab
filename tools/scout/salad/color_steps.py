#!/usr/bin/env python3
"""Разбор цвета покраски по шагам — на процессоре, без GPU (план mesh-color-03, T-20261106-85).

ЗАЧЕМ. Промах светлоты модели против фото (белый шкаф выходит серым, чёрный — «коллапсом») надо поймать на том шаге,
где он рождается: вход покраски → вид сети (multiview) → увеличение (super) → запекание в UV → дорисовка UV → итоговый
GLB. Воркер с `params._dump` кладёт файл каждого шага (`dbg-*`, см. `pipeline._Dump`); этот инструмент меряет на каждом
медианную ЛИНЕЙНУЮ яркость товара (та же мерка, что `photo_color.luminance`) и пишет сдвиг против фото:
  stops = log2(y_шаг / y_фото)  (минус — темнее фото),  dL255 = байт sRGB шага − байт фото (шкала порогов плана).

ВТОРОЕ — наклон камеры по силуэту. Прежний замер (`exposure_plan.one` → `render_front`, наклон 15°) у столов видел
то, чего нет на фото (низ столешницы, царги), и белые столы давали ложный промах −90…−104. Здесь камера подбирается
перебором поворота и наклона по совпадению силуэта (IoU) с маской фото — и замер идёт в этой позе. Старая поза тоже
пишется (`unlit_old`), чтобы видеть, сколько промаха было от позы, а сколько от цвета.

  # один прогон (папка комплекта с dbg-* и model.glb) против фото:
  python color_steps.py run <папка> --photo cutout.png [--json out.json] [--sheet out.png]
  # пачка: tsv «метка\\tпапка\\tфото» (у старых мешей v2 dbg нет — будет только фото, GLB и рендеры):
  python color_steps.py batch <list.tsv> <out.jsonl> <sheet.png>
  python color_steps.py --selftest
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]

YAWS = (-30, -15, 0, 15, 30)
PITCHES = (-10, 0, 10, 20, 30, 40)
SIL = 128            # сторона квадрата сравнения силуэтов
SEARCH_PX = 220      # рендер силуэта при переборе
SEARCH_FACES = 3000  # лёгкая копия меша для перебора
FINAL_PX = 480


def _lin(rgb: np.ndarray) -> np.ndarray:
    x = rgb.astype(np.float32) / 255.0
    lin = np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)
    return lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)


def to_byte(y: float) -> float:
    y = max(0.0, min(1.0, y))
    return 255.0 * (12.92 * y if y <= 0.0031308 else 1.055 * y ** (1 / 2.4) - 0.055)


def lum(rgb: np.ndarray, mask: np.ndarray | None = None, weights: np.ndarray | None = None) -> float | None:
    """Медианная линейная яркость пикселей маски (или взвешенная медиана). None — если пикселей мало."""
    y = _lin(rgb.reshape(-1, 3))
    if mask is not None:
        m = mask.reshape(-1)
        y = y[m]
        if weights is not None:
            weights = weights.reshape(-1)[m]
    if y.size < 50:
        return None
    if weights is None:
        return float(np.median(y))
    o = np.argsort(y)
    c = np.cumsum(weights[o])
    return float(y[o][np.searchsorted(c, c[-1] / 2)])


def rgba(path: str) -> np.ndarray:
    return np.asarray(Image.open(path).convert('RGBA'))


def resize_mask(mask: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    return np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).resize(size, Image.NEAREST)) > 127


def bg_mask(cond: np.ndarray) -> np.ndarray:
    """Маска товара на карте-условии (нормали/позиции): всё, что отличается от цвета углов (фон)."""
    rgb = cond[..., :3].astype(np.int16)
    corners = np.array([rgb[0, 0], rgb[0, -1], rgb[-1, 0], rgb[-1, -1]])
    bg = np.median(corners, axis=0)
    return np.abs(rgb - bg).max(axis=-1) > 8


def step(name: str, y: float | None, y_photo: float | None, **extra) -> dict:
    r = {'step': name, 'y': None if y is None else round(y, 4), **extra}
    if y is not None and y_photo:
        r['stops'] = round(math.log2(max(y, 1e-5) / y_photo), 2)
        r['dL255'] = round(to_byte(y) - to_byte(y_photo), 1)
    return r


# ── поза по силуэту ────────────────────────────────────────────────────────────────────────────────────────────────

def _square(mask: np.ndarray) -> np.ndarray | None:
    ys, xs = np.where(mask)
    if len(ys) < 20:
        return None
    m = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = m.shape
    k = SIL / max(h, w)
    im = Image.fromarray((m * 255).astype(np.uint8)).resize((max(1, round(w * k)), max(1, round(h * k))), Image.BILINEAR)
    out = np.zeros((SIL, SIL), bool)
    a = np.asarray(im) > 127
    oy, ox = (SIL - a.shape[0]) // 2, (SIL - a.shape[1]) // 2
    out[oy:oy + a.shape[0], ox:ox + a.shape[1]] = a
    return out


def iou(a: np.ndarray | None, b: np.ndarray | None) -> float:
    if a is None or b is None:
        return 0.0
    return float((a & b).sum() / max((a | b).sum(), 1))


def best_pose(glb: str, photo_alpha: np.ndarray) -> dict:
    """Перебор поворота и наклона по совпадению силуэта с маской фото. Силуэт — заливкой (цвет не важен)."""
    import mesh_render as MR
    target = _square(photo_alpha)
    parts = MR.lite_parts(glb, SEARCH_FACES)
    grid = []
    for yaw in YAWS:
        for pitch in PITCHES:
            im = MR.render(parts, yaw_deg=yaw, pitch_deg=pitch, size=(SEARCH_PX, SEARCH_PX), flat=(200, 200, 200))
            grid.append((iou(_square(np.asarray(im)[..., 3] > 8), target), yaw, pitch))
    s, yaw, pitch = max(grid)
    old = next(g[0] for g in grid if g[1] == 0 and g[2] == 10)      # ближайшая к прежней (0°, 15°) точка сетки
    return {'yaw': yaw, 'pitch': pitch, 'iou': round(s, 3), 'iou_pitch10': round(old, 3),
            'grid': [[round(g[0], 3), g[1], g[2]] for g in grid]}


def unlit(glb: str, yaw: float, pitch: float, out_png: str | None = None) -> tuple[float | None, Image.Image]:
    import mesh_render as MR
    prev = os.environ.get('UNLIT')
    os.environ['UNLIT'] = '1'
    try:
        im = MR.render(MR.load_parts(glb), yaw_deg=yaw, pitch_deg=pitch, size=(FINAL_PX, FINAL_PX))
    finally:
        if prev is None:
            os.environ.pop('UNLIT', None)
        else:
            os.environ['UNLIT'] = prev
    a = np.asarray(im)
    if out_png:
        im.save(out_png)
    return lum(a[..., :3], a[..., 3] > 128), im


def glb_basecolor(glb: str) -> float | None:
    """Медиана яркости текстуры итогового GLB по поверхности: текстура в UV центров граней, вес — площадь грани.
    Мимо рендера — чтобы видеть цвет, которым меш покрашен, без позы и перекрытий."""
    import trimesh
    import mesh_render as MR
    ys, ws = [], []
    for m in MR.load_parts(glb):
        tex, uv = MR.texture_of(m)
        if tex is None or not hasattr(m, 'faces'):
            continue
        f = np.asarray(m.faces)
        c = uv[f].mean(axis=1)
        th, tw = tex.shape[:2]
        tx = np.clip((c[:, 0] % 1.0) * (tw - 1), 0, tw - 1).astype(int)
        ty = np.clip((1.0 - c[:, 1] % 1.0) * (th - 1), 0, th - 1).astype(int)
        ys.append(tex[ty, tx])
        ws.append(np.asarray(trimesh.Trimesh(vertices=m.vertices, faces=f, process=False).area_faces, np.float32))
    if not ys:
        return None
    return lum(np.vstack(ys), None, np.concatenate(ws))


# ── один комплект ──────────────────────────────────────────────────────────────────────────────────────────────────

def analyse(run_dir: str, photo: str | None, label: str = '', tiles_dir: str | None = None) -> dict:
    d = os.path.join(run_dir, 'dbg') if os.path.isdir(os.path.join(run_dir, 'dbg')) else run_dir
    f = lambda n: os.path.join(d, n)                                       # noqa: E731
    have = lambda n: os.path.exists(f(n))                                  # noqa: E731
    photo = photo or (f('dbg-paint-input.png') if have('dbg-paint-input.png') else None)
    out = {'label': label, 'dir': run_dir, 'photo': photo, 'steps': [], 'tiles': {}}
    if not photo or not os.path.exists(photo):
        out['err'] = 'нет фото'
        return out
    P = rgba(photo)
    pa = P[..., 3] > 128
    y_photo = lum(P[..., :3], pa)
    out['y_photo'] = None if y_photo is None else round(y_photo, 4)
    out['tiles']['photo'] = photo
    S = out['steps']

    if have('dbg-paint-input.png'):
        A = rgba(f('dbg-paint-input.png'))
        S.append(step('paint_input', lum(A[..., :3], A[..., 3] > 128), y_photo))
        out['tiles']['paint_input'] = f('dbg-paint-input.png')
        if have('dbg-in-0.png'):                       # апстрим: RGBA → 512×512 (без сохранения пропорций) → на белое
            I = rgba(f('dbg-in-0.png'))
            m = resize_mask(A[..., 3] > 128, (I.shape[1], I.shape[0]))
            S.append(step('net_input', lum(I[..., :3], m), y_photo))
            out['tiles']['net_input'] = f('dbg-in-0.png')

    for stage, pref in (('multiview', 'dbg-mv-albedo-'), ('super', 'dbg-sr-albedo-')):
        views = []
        i = 0
        while have(f'{pref}{i}.png'):
            V = rgba(f(f'{pref}{i}.png'))
            cn = f'dbg-cond-pos-{i}.png' if have(f'dbg-cond-pos-{i}.png') else f'dbg-cond-normal-{i}.png'
            if have(cn):
                m = resize_mask(bg_mask(rgba(f(cn))), (V.shape[1], V.shape[0]))
            else:
                m = np.abs(V[..., :3].astype(np.int16) - 255).max(-1) > 8
            frac = float(m.mean())
            views.append({'i': i, 'y': lum(V[..., :3], m), 'mask_frac': round(frac, 3)})
            i += 1
        if views:
            ys = [v['y'] for v in views if v['y'] is not None]
            S.append(step(f'{stage}_front', views[0]['y'], y_photo, mask_frac=views[0]['mask_frac']))
            S.append(step(f'{stage}_all', float(np.median(ys)) if ys else None, y_photo,
                          views=[{**v, 'y': None if v['y'] is None else round(v['y'], 4)} for v in views]))
            out['tiles'][stage] = f(f'{pref}0.png')

    if have('dbg-uv-albedo-baked.png'):
        B = rgba(f('dbg-uv-albedo-baked.png'))
        bm = (rgba(f('dbg-uv-albedo-mask.png'))[..., 0] > 127) if have('dbg-uv-albedo-mask.png') else None
        S.append(step('uv_baked', lum(B[..., :3], bm), y_photo,
                      coverage=None if bm is None else round(float(bm.mean()), 3)))
        out['tiles']['uv_baked'] = f('dbg-uv-albedo-baked.png')
        if have('dbg-uv-albedo-inpainted.png'):
            N = rgba(f('dbg-uv-albedo-inpainted.png'))
            if bm is not None and bm.shape == N.shape[:2]:
                S.append(step('uv_inpainted_seen', lum(N[..., :3], bm), y_photo))
                S.append(step('uv_inpainted_filled', lum(N[..., :3], ~bm), y_photo))
            else:
                S.append(step('uv_inpainted', lum(N[..., :3]), y_photo))
            out['tiles']['uv_inpainted'] = f('dbg-uv-albedo-inpainted.png')

    glb = os.path.join(run_dir, 'model.glb')
    if os.path.exists(glb):
        S.append(step('glb_basecolor', glb_basecolor(glb), y_photo))
        pose = best_pose(glb, pa)
        out['pose'] = pose
        tiles_dir = tiles_dir or os.path.join(run_dir, 'color-steps')
        os.makedirs(tiles_dir, exist_ok=True)
        y_old, _ = unlit(glb, 0.0, 15.0, os.path.join(tiles_dir, 'unlit-old.png'))
        y_best, _ = unlit(glb, pose['yaw'], pose['pitch'], os.path.join(tiles_dir, 'unlit-pose.png'))
        S.append(step('unlit_old', y_old, y_photo, yaw=0, pitch=15))
        S.append(step('unlit_pose', y_best, y_photo, yaw=pose['yaw'], pitch=pose['pitch'], iou=pose['iou']))
        out['tiles']['unlit_old'] = os.path.join(tiles_dir, 'unlit-old.png')
        out['tiles']['unlit_pose'] = os.path.join(tiles_dir, 'unlit-pose.png')
    return out


# ── лист ───────────────────────────────────────────────────────────────────────────────────────────────────────────

COLS = ('photo', 'paint_input', 'net_input', 'multiview', 'super', 'uv_baked', 'uv_inpainted', 'unlit_old', 'unlit_pose')
STEP_OF = {'photo': None, 'paint_input': 'paint_input', 'net_input': 'net_input', 'multiview': 'multiview_front',
           'super': 'super_front', 'uv_baked': 'uv_baked', 'uv_inpainted': 'uv_inpainted_seen',
           'unlit_old': 'unlit_old', 'unlit_pose': 'unlit_pose'}


def _font(px: int):
    for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/TTF/DejaVuSans.ttf'):
        if os.path.exists(p):
            return ImageFont.truetype(p, px)
    return ImageFont.load_default()


def sheet(results: list[dict], out_png: str, tile: int = 150) -> None:
    """Строка на комплект: фото → шаги → рендеры; под каждой плиткой — сдвиг против фото (байты sRGB и ступени)."""
    lab_h, head = 34, 22
    W, H = tile * len(COLS), head + len(results) * (tile + lab_h + 18)
    sh = Image.new('RGB', (W, H), (236, 236, 236))
    dr = ImageDraw.Draw(sh)
    fs, fb = _font(12), _font(13)
    for j, c in enumerate(COLS):
        dr.text((j * tile + 4, 4), c, fill=(0, 0, 0), font=fb)
    for i, r in enumerate(results):
        y0 = head + i * (tile + lab_h + 18)
        dr.text((4, y0), f"{r.get('label', '')}  y_photo={r.get('y_photo')}", fill=(0, 0, 120), font=fs)
        steps = {s['step']: s for s in r.get('steps', [])}
        for j, c in enumerate(COLS):
            p = r.get('tiles', {}).get(c)
            if not p or not os.path.exists(p):
                continue
            im = Image.open(p).convert('RGBA')
            im.thumbnail((tile - 6, tile - 6))
            bgc = Image.new('RGBA', im.size, (255, 255, 255, 255) if c != 'uv_baked' else (255, 0, 255, 255))
            bgc.alpha_composite(im)
            sh.paste(bgc.convert('RGB'), (j * tile + 3, y0 + 16))
            s = steps.get(STEP_OF[c]) if STEP_OF[c] else None
            if s and 'dL255' in s:
                col = (0, 120, 0) if abs(s['dL255']) <= 15 else (180, 90, 0) if abs(s['dL255']) <= 40 else (190, 0, 0)
                dr.text((j * tile + 4, y0 + 18 + tile), f"dL {s['dL255']:+.0f}  {s['stops']:+.2f} st", fill=col, font=fs)
                if c == 'unlit_pose':
                    dr.text((j * tile + 4, y0 + 32 + tile), f"y{s['yaw']} p{s['pitch']} iou {s['iou']}", fill=(60, 60, 60),
                            font=fs)
    sh.save(out_png)


def main() -> int:
    a = sys.argv[1:]
    if not a or a[0] in ('-h', '--help'):
        print(__doc__)
        return 0
    if a[0] == '--selftest':
        return selftest()
    if a[0] == 'run':
        photo = a[a.index('--photo') + 1] if '--photo' in a else None
        r = analyse(a[1], photo, label=os.path.basename(a[1].rstrip('/')))
        if '--json' in a:
            json.dump(r, open(a[a.index('--json') + 1], 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        if '--sheet' in a:
            sheet([r], a[a.index('--sheet') + 1])
        for s in r['steps']:
            print(f"  {s['step']:<22} y={s['y']}  dL255={s.get('dL255')}  stops={s.get('stops')}")
        return 0
    if a[0] == 'batch':
        rows = [ln.rstrip('\n').split('\t') for ln in open(a[1], encoding='utf-8') if ln.strip()]
        res, bad = [], 0
        base = os.path.dirname(os.path.abspath(a[2]))
        with open(a[2], 'w', encoding='utf-8') as fo:
            for k, row in enumerate(rows):
                label, run_dir, photo = (row + ['', ''])[:3]
                try:
                    r = analyse(run_dir, photo or None, label, tiles_dir=os.path.join(base, 'tiles', f'{k:03d}'))
                except Exception as e:  # noqa: BLE001 — счётчик сбоев, не молча
                    r = {'label': label, 'dir': run_dir, 'err': f'{type(e).__name__}: {str(e)[:160]}', 'steps': []}
                bad += 1 if 'err' in r else 0
                fo.write(json.dumps(r, ensure_ascii=False) + '\n')
                fo.flush()
                res.append(r)
                print(f'[{k + 1}/{len(rows)}] {label}: ' + ('СБОЙ ' + r['err'] if 'err' in r else
                      ' '.join(f"{s['step']}={s.get('dL255')}" for s in r['steps'] if 'dL255' in s)))
        sheet(res, a[3])
        print(f'разобрано {len(rows)}, сбоев {bad}; лист {a[3]}')
        return 1 if bad else 0
    print(__doc__)
    return 2


# ── самопроверка ───────────────────────────────────────────────────────────────────────────────────────────────────

def _textured(mesh, rgb):
    import trimesh
    v = np.asarray(mesh.vertices)
    uv = (v[:, :2] - v[:, :2].min(0)) / max(np.ptp(v[:, :2], axis=0).max(), 1e-6)
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv, image=Image.new('RGB', (16, 16), rgb))
    return mesh


def selftest() -> int:
    import tempfile
    import trimesh
    import mesh_render as MR
    bad = 0

    def ok(name, cond, extra=''):
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if not cond else ''))
        bad += 0 if cond else 1

    with tempfile.TemporaryDirectory(prefix='color-steps-') as tmp:
        # стол: белая столешница, тёмные ножки и царга снизу — «фото» снято сверху под 25°
        top = _textured(trimesh.creation.box(extents=(1.0, 0.04, 0.6)), (240, 240, 240))
        top.apply_translation((0, 0.38, 0))
        apron = _textured(trimesh.creation.box(extents=(0.92, 0.1, 0.52)), (40, 40, 40))
        apron.apply_translation((0, 0.31, 0))
        legs = []
        for x in (-0.45, 0.45):
            for z in (-0.25, 0.25):
                lg = _textured(trimesh.creation.box(extents=(0.05, 0.74, 0.05)), (40, 40, 40))
                lg.apply_translation((x, 0.0, z))
                legs.append(lg)
        glb = os.path.join(tmp, 'run', 'model.glb')
        os.makedirs(os.path.dirname(glb))
        trimesh.Scene([top, apron, *legs]).export(glb)
        os.environ['UNLIT'] = '1'
        photo_im = MR.render(MR.load_parts(glb), yaw_deg=0, pitch_deg=25, size=(300, 300))
        os.environ.pop('UNLIT')
        photo = os.path.join(tmp, 'photo.png')
        photo_im.save(photo)
        pose = best_pose(glb, np.asarray(photo_im)[..., 3] > 128)
        ok('поза по силуэту: стол «сфотографирован» под 25° — найдено 20–30°, поворот 0',
           pose['pitch'] in (20, 30) and pose['yaw'] == 0 and pose['iou'] > 0.85, pose)

        # шаги: фото серое 128; сеть вернула темнее (100), UV ещё темнее (80)
        d = os.path.join(tmp, 'run', 'dbg')
        os.makedirs(d)
        sq = Image.new('RGBA', (64, 64), (255, 255, 255, 0))
        sq.paste((128, 128, 128, 255), (16, 16, 48, 48))
        sq.save(os.path.join(d, 'dbg-paint-input.png'))
        inp = Image.new('RGB', (64, 64), (255, 255, 255))
        inp.paste((128, 128, 128), (16, 16, 48, 48))
        inp.save(os.path.join(d, 'dbg-in-0.png'))
        for i in range(2):
            cond = Image.new('RGB', (32, 32), (0, 0, 0))
            cond.paste((90, 150, 200), (8, 8, 24, 24))
            cond.save(os.path.join(d, f'dbg-cond-pos-{i}.png'))
            mv = Image.new('RGB', (64, 64), (255, 255, 255))
            mv.paste((100, 100, 100), (16, 16, 48, 48))
            mv.save(os.path.join(d, f'dbg-mv-albedo-{i}.png'))
            mv.resize((128, 128)).save(os.path.join(d, f'dbg-sr-albedo-{i}.png'))
        uv = Image.new('RGB', (64, 64), (0, 0, 0))
        uv.paste((80, 80, 80), (0, 0, 64, 40))
        uv.save(os.path.join(d, 'dbg-uv-albedo-baked.png'))
        mk = Image.new('L', (64, 64), 0)
        mk.paste(255, (0, 0, 64, 40))
        mk.save(os.path.join(d, 'dbg-uv-albedo-mask.png'))
        uv2 = uv.copy()
        uv2.paste((60, 60, 60), (0, 40, 64, 64))
        uv2.save(os.path.join(d, 'dbg-uv-albedo-inpainted.png'))
        sq.save(photo.replace('.png', '-grey.png'))
        r = analyse(os.path.join(tmp, 'run'), photo.replace('.png', '-grey.png'), 'selftest')
        st = {s['step']: s for s in r['steps']}
        ok('шаги: вход и вход сети — как фото (0), маска входа сети — от альфы входа',
           st['paint_input']['dL255'] == 0 and st['net_input']['dL255'] == 0, st)
        ok('шаги: вид сети и увеличение −28 байт (100 против 128), маска вида — по карте позиций',
           st['multiview_front']['dL255'] == -28 and st['super_front']['dL255'] == -28
           and st['multiview_front']['mask_frac'] == 0.25, st)
        ok('шаги: UV до дорисовки −48 (видимое), дорисованное отдельно −68, покрытие 0.625',
           st['uv_baked']['dL255'] == -48 and st['uv_inpainted_filled']['dL255'] == -68
           and st['uv_baked']['coverage'] == 0.625, st)
        ok('шаги: у итогового GLB есть цвет по поверхности и оба рендера (старая поза и по силуэту)',
           st['glb_basecolor']['y'] is not None and 'unlit_old' in st and st['unlit_pose']['pitch'] in (-10, 0, 10, 20, 30, 40)
           and os.path.exists(r['tiles']['unlit_pose']), st)
        out = os.path.join(tmp, 'sheet.png')
        sheet([r, r], out)
        ok('лист собран', Image.open(out).size[0] == 150 * len(COLS))
    print(f'color_steps selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
