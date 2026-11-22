#!/usr/bin/env python3
"""СТРАНИЦА ЭТАПА 07 «залить невидимое» (T-189/2, P-065): на товар — фото | 06 с камеры | 07 с камеры | 07 слева 40° | 07 справа 40°, строка проверок и времени, легенда.
Ракурсы ±40° — от АЗИМУТА НАЙДЕННОЙ КАМЕРЫ (az из `pose.json` этапа 4), не от осей формы (урок 848): `tex_visible.side_view_angles`, рендер — `mesh_render.render` без света (как `recolor_lp.render_unlit` листа этапа 6), но рамка по габариту предмета и поле от силуэта ≥ 3 % со всех сторон (`render_framed`, T-189/3).
Фото и «06 с камеры» режутся из готового `06-visible/frame.png` (4 панели по 960 px: фото | 06 с камеры | слева | справа); 07 — рендерится здесь из `07-fill/filled.glb`.
Запуск (на pakardev, python venv scout, под heavy-slot — рендер на процессоре):
  python page07.py --vis-root <папка с <товар>/06-visible> --fill-root <папка с <товар>/07-fill> --pose-root <папка камер <товар>/pose.json> --set set40.json --out <папка страницы> [--times items-07.json]
Выход: `<out>/index.html` + `<out>/img/<товар>_<панель>.webp` (≤ 640 px по ширине, ≤ 120 КБ). Только чтение входов; ID товаров в код не зашиты (список — папки с готовым 07)."""
from __future__ import annotations

import argparse
import html
import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
TRELLIS = os.path.abspath(os.path.join(HERE, '..', 'trellis'))
sys.path[:0] = [TRELLIS, os.path.abspath(os.path.join(HERE, '..')), os.path.abspath(os.path.join(HERE, '..', '..'))]

PANEL = 960                                                   # сторона панели в frame.png этапа 6 (size*2, size=480)
SHOT = 640
MAX_KB = 120


def crop_panels(frame_png: str) -> list[Image.Image]:
    im = Image.open(frame_png).convert('RGB')
    n = im.width // PANEL
    return [im.crop((i * PANEL, 0, (i + 1) * PANEL, im.height)) for i in range(n)]


def save_webp(img: Image.Image, path: str, width: int = SHOT, max_kb: int = MAX_KB) -> int:
    img = img.convert('RGB')
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    for q in (86, 80, 74, 68, 60, 50):
        img.save(path, 'WEBP', quality=q, method=6)
        if os.path.getsize(path) <= max_kb * 1024:
            break
    return os.path.getsize(path)


def over_white(im: Image.Image) -> Image.Image:
    a = np.asarray(im.convert('RGBA'))
    return Image.fromarray(np.where((a[..., 3] > 8)[..., None], a[..., :3], 255).astype(np.uint8))


SIDE_DEG = 40.0


def side_view_angles(cam: dict, side_deg: float = SIDE_DEG) -> dict:
    """Те же ракурсы, что у листа этапа 6 (`tex_visible.side_view_angles`, урок 848): от азимута НАЙДЕННОЙ камеры фото (az ∓ 40°), высота — el камеры; `mesh_render.render` поворачивает предмет, поэтому yaw = −az.
    Своя копия формулы: в образе Salad лежит этап 06 на de5c8d52 (до правила 848), страница не должна зависеть от версии этапа."""
    az = (float(cam.get('az', 0.0)) + 180.0) % 360.0 - 180.0
    el = float(cam.get('el', 10.0))
    return {'az_cam': az, 'pitch': el, 'left': {'yaw': -(az - side_deg)}, 'right': {'yaw': -(az + side_deg)}}


MARGIN_MIN = 0.03                                             # поле от силуэта до края кадра, доля стороны (владелец TG 1661: край не должен обрезаться)
PAD_START = 0.05                                              # запас «отдаления» при первой отрисовке: поле ≈ 8 % (≈ запас 10 % от габарита)
PAD_TRIES = 5


def silhouette_margins(im: Image.Image, thr: int = 8) -> dict | None:
    """Поля от силуэта (альфа > thr) до краёв кадра, доли стороны кадра: left/right/top/bottom. None — силуэта нет."""
    a = np.asarray(im.convert('RGBA'))[..., 3] > thr
    if not a.any():
        return None
    ys, xs = np.where(a)
    h, w = a.shape
    return {'left': xs.min() / w, 'right': 1 - (xs.max() + 1) / w, 'top': ys.min() / h, 'bottom': 1 - (ys.max() + 1) / h}


def frame_ok(im: Image.Image, need: float = MARGIN_MIN) -> bool:
    m = silhouette_margins(im)
    return m is not None and min(m.values()) >= need


def zoom_out(im: Image.Image, pad: float) -> Image.Image:
    """Отдалить: добавить прозрачное поле pad·сторона со всех сторон и сжать обратно до прежней стороны (проекция ортографическая — расстояние = масштаб)."""
    w, h = im.size
    px, py = round(w * pad), round(h * pad)
    big = Image.new('RGBA', (w + 2 * px, h + 2 * py), (0, 0, 0, 0))
    big.paste(im.convert('RGBA'), (px, py))
    return big.resize((w, h), Image.LANCZOS)


def with_bbox_centering(parts: list, yaw: float, pitch: float) -> list:
    """`mesh_render.render` центрирует кадр по СРЕДНЕЙ вершин, а масштаб берёт по габариту: у предмета со смещённой массой (одна сторона плотнее сетка) силуэт уходит к краю и обрезается.
    Добавляем «груз без площади» — одну вырожденную грань с вершинами в точке, зеркальной среднему относительно середины габарита (она внутри габарита: габарит и масштаб те же, средняя = середина габарита).
    Никакой пиксель груз не рисует (площадь 0)."""
    import math
    import trimesh
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], np.float32)
    rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]], np.float32)
    rot = ry.T @ rx.T
    allp = np.vstack([np.asarray(m.vertices, np.float32) @ rot for m in parts])
    mean = allp.mean(axis=0)
    centre = (allp.min(axis=0) + allp.max(axis=0)) / 2
    n = len(allp)
    q = np.array([2 * centre[0] - mean[0], 2 * centre[1] - mean[1], mean[2]], np.float32)       # n точек в q: средняя всех = середина габарита по x, y
    v = np.tile(q @ rot.T, (n, 1)).astype(np.float32)
    ballast = trimesh.Trimesh(vertices=v, faces=[[0, 1, 2]], process=False)
    return list(parts) + [ballast]


def render_framed(glb_or_parts, yaw: float, pitch: float, size: int = PANEL, pad: float = PAD_START) -> tuple[Image.Image, dict]:
    """Кадр без света, силуэт по центру габарита, поле ≥ MARGIN_MIN со всех сторон. Не прошло — отдаляем (pad ×1,6) и рисуем заново. Возвращает (RGB поверх белого, {'margins', 'pad', 'tries', 'ok'})."""
    import mesh_render as MR
    parts = MR.load_parts(glb_or_parts) if isinstance(glb_or_parts, str) else glb_or_parts
    framed = with_bbox_centering(parts, yaw, pitch)
    prev = os.environ.get('UNLIT')
    os.environ['UNLIT'] = '1'
    try:
        raw = MR.render(framed, yaw_deg=yaw, pitch_deg=pitch, size=(size, size))
    finally:
        if prev is None:
            os.environ.pop('UNLIT', None)
        else:
            os.environ['UNLIT'] = prev
    p, im = pad, raw
    for t in range(1, PAD_TRIES + 1):
        im = zoom_out(raw, p)
        if frame_ok(im):
            break
        p *= 1.6
    m = silhouette_margins(im)
    return over_white(im), {'margins': m, 'pad': p, 'tries': t, 'ok': frame_ok(im)}


def render_07(glb: str, cam: dict, size: int = PANEL) -> dict[str, tuple[Image.Image, dict]]:
    """Три кадра 07: с камеры фото и слева/справа 40° от её азимута (pitch = el камеры). Рендер без света, рамка по габариту с полем ≥3 % (`render_framed`)."""
    import mesh_render as MR
    parts = MR.load_parts(glb)
    sv = side_view_angles(cam)
    out = {}
    for name, yaw in (('cam', -sv['az_cam']), ('left', sv['left']['yaw']), ('right', sv['right']['yaw'])):
        out[name] = render_framed(parts, yaw, sv['pitch'], size)
    return out


def load_json(p: str) -> dict:
    try:
        return json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def mv(chk: dict, key: str):
    m = (chk.get('metrics') or {}).get(key) or {}
    return m.get('value')


def coverage(v06: str, pose_dir: str) -> dict | None:
    """«Покрыто видимого» — как на странице этапа 06 (р.3, T-187/2): доля пикселей кадра камеры, цвет которых взят с фото (`known.png` через UV кадра камеры); c4 — то же среди поверхностей, повёрнутых к камере (cos ≥ 0,4)."""
    import cv2  # noqa: F401 — нужен только здесь
    rd = os.path.join(pose_dir, 'stages', 'render_view0')
    try:
        uv = np.load(os.path.join(rd, 'uv.npz'))
        known = np.asarray(Image.open(os.path.join(v06, 'known.png')).convert('L')) > 127
        cos = np.asarray(Image.open(os.path.join(rd, 'aoi_cos16.png'))).astype(np.float64) / 65535.0
    except (OSError, ValueError, KeyError):
        return None
    m = uv['mask'].astype(bool)
    uvv = uv['uv']
    T = known.shape[0]
    ys, xs = np.nonzero(m)
    tx = np.clip(np.floor(uvv[ys, xs, 0] * T).astype(int), 0, T - 1)
    ty = np.clip(np.floor(uvv[ys, xs, 1] * T).astype(int), 0, T - 1)
    kpx = np.zeros(m.shape, bool)
    kpx[ys, xs] = known[ty, tx]
    c4 = m & (cos >= 0.4)
    return {'all': float(kpx[m].mean() * 100), 'c4': float(kpx[c4].mean() * 100) if c4.any() else None}


def status06(chk: dict, cov: dict | None) -> str:
    """Строка этапа 06 без красного гейта: мерка known_share признана неверной (директор 22.11, р.4 чинит) — вместо неё «покрыто видимого N %»."""
    if not chk:
        return 'нет данных'
    out = []
    if cov:
        c4 = f' (на камеру смотрящих — {cov["c4"]:.0f} %)' if cov.get('c4') is not None else ''
        out.append(f'покрыто видимого {cov["all"]:.0f} %{c4}')
    v = (chk.get('metric') or {}).get('value')
    if isinstance(v, (int, float)):
        out.append(f'камера легла на фото на {round(float(v) * 100)} %')
    return ' · '.join(out) or 'нет данных'


FAIL_WORDS = {
    'filled_faces_step_pct': 'в залитой части много резких цветовых «ступенек» между соседними гранями: {value:g} % граней (допуск {op} {threshold:g} %)',
    'far_excess_pct': 'в залитой части больше «чужого» цвета (далеко от типичного цвета детали), чем в части с фото: на {value:g} п. п. (допуск {op} {threshold:g})',
    'dE00_front_back': 'перед и зад разного цвета: разница {value:g} (допуск {op} {threshold:g})',
    'known_changed_share_pct': 'заливка тронула то, что уже взято с фото: {value:g} % (допуск {op} {threshold:g})',
    'pool_rejected_pct': 'часть кусков для заливки отбракована: {value:g} % (допуск {op} {threshold:g})',
    'time_s': 'заливка шла дольше допуска: {value:g} с (допуск {op} {threshold:g})',
}


def fail_words(key: str, m: dict) -> str:
    t = FAIL_WORDS.get(key)
    try:
        if t:
            return html.escape(t.format(value=float(m.get('value')), op=m.get('op', '<='), threshold=float(m.get('threshold'))))
    except (TypeError, ValueError):
        pass
    return html.escape(f'{key}: {m.get("value")} (допуск {m.get("op")} {m.get("threshold")})')


def status07(chk: dict, secs) -> str:
    if not chk:
        return 'нет данных'
    ok = chk.get('passed')
    parts = ['заливка прошла проверку' if ok else 'заливка не прошла проверку']
    kp = (chk.get('extra') or {}).get('known_pct')
    if isinstance(kp, (int, float)):
        parts.append(f'со снимка закрашено {kp:g} % поверхности — остальное залито')
    de = mv(chk, 'dE00_front_back')
    if isinstance(de, (int, float)):
        parts.append(f'разница цвета «перед / зад» {de:g} (допуск 6)')
    if secs:
        parts.append(f'считалось на Salad {round(float(secs))} с')
    if not ok:
        for k, v in (chk.get('metrics') or {}).items():
            if isinstance(v, dict) and v.get('ok') is False:
                parts.append('НЕ ПРОШЛО — ' + fail_words(k, v))
    return '; '.join(parts)


CSS = """
:root{--bg:#f6f4ef;--fg:#23201b;--mut:#6c675d;--card:#fff;--line:#e3dfd6;--ok:#2f7d4f;--bad:#b3402f;--acc:#7a5a2b}
@media (prefers-color-scheme: dark){:root{--bg:#1c1a17;--fg:#ece8df;--mut:#a39d90;--card:#26231f;--line:#3a362f;--ok:#6cc48d;--bad:#e8806e;--acc:#d3a867}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1280px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:1.5rem;margin:0 0 6px}p.lead{margin:0 0 14px;color:var(--mut)}
.legend{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:0 0 20px;font-size:.95rem}
.legend b{color:var(--acc)}.legend ul{margin:6px 0 0;padding-left:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;margin:0 0 18px}
.card h2{font-size:1.1rem;margin:0 0 8px;display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.card h2 small{color:var(--mut);font-weight:400;font-size:.8rem}.card h2 small i{font-style:normal;overflow-wrap:anywhere}.card h2 small span{white-space:nowrap}
.row{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}
.row figure{margin:0;text-align:center}
.row img{width:100%;height:auto;display:block;background:#fff;border:1px solid var(--line);border-radius:8px}
.row figcaption{font-size:.8rem;color:var(--mut);margin-top:4px}
.st{margin:10px 0 0;font-size:.88rem;display:grid;gap:3px}
.st span.ok{color:var(--ok)}.st span.bad{color:var(--bad)}
@media (max-width:820px){.row{grid-template-columns:repeat(2,1fr)}}
"""


def build(a) -> int:
    items = {}
    sj = load_json(a.set)
    for n, it in enumerate(sj['items'] if isinstance(sj, dict) else sj, 1):
        items[it['id']] = (n, it.get('role', ''))
    times = {k: v.get('run_s') for k, v in load_json(a.times).items()} if a.times else {}
    skus = sorted([s for s in os.listdir(a.fill_root) if os.path.isfile(os.path.join(a.fill_root, s, '07-fill', 'filled.glb'))], key=lambda s: items.get(s, (999, ''))[0])
    if a.skus:
        want = set(a.skus.split(','))
        skus = [s for s in skus if s in want]
    os.makedirs(os.path.join(a.out, 'img'), exist_ok=True)
    cards, sizes = [], []
    for sku in skus:
        v06 = os.path.join(a.vis_root, sku, '06-visible')
        f07 = os.path.join(a.fill_root, sku, '07-fill')
        cam = (load_json(os.path.join(a.pose_root, sku, 'pose.json')).get('camera')) or {}
        if not cam:
            print(f'{sku}: нет camera в pose.json — пропуск', file=sys.stderr)
            continue
        names = ('photo', 'v06', 'c07', 'l07', 'r07')
        paths = {k: os.path.join(a.out, 'img', f'{sku}_{k}.webp') for k in names}
        if a.reuse and all(os.path.isfile(x) for x in paths.values()):
            sizes += [os.path.getsize(x) for x in paths.values()]
        else:
            panels = crop_panels(os.path.join(v06, 'frame.png'))
            r07 = render_07(os.path.join(f07, 'filled.glb'), cam)
            imgs = {'photo': panels[0], 'v06': panels[1], 'c07': r07['cam'][0], 'l07': r07['left'][0], 'r07': r07['right'][0]}
            for k in ('cam', 'left', 'right'):
                mm = r07[k][1]
                print(f'{sku}: кадр {k}: поле мин {min(mm["margins"].values()) * 100:.1f} %, отдалений {mm["tries"] - 1}, {"ок" if mm["ok"] else "НЕ ПРОШЁЛ (силуэт у края)"}')
            for k, im in imgs.items():
                sizes.append(save_webp(im, paths[k]))
        n, role = items.get(sku, (0, ''))
        c06, c07 = load_json(os.path.join(v06, 'check.json')), load_json(os.path.join(f07, 'check.json'))
        az = cam.get('az')
        figs = ''.join(f'<figure><a href="img/{sku}_{k}.webp" target="_blank"><img src="img/{sku}_{k}.webp" alt="{html.escape(cap)}" loading="lazy"></a><figcaption>{html.escape(cap)}</figcaption></figure>'
                       for k, cap in (('photo', 'фото (вход модели)'), ('v06', '06: перенос фото, с камеры'), ('c07', '07: залито, с камеры'),
                                      ('l07', f'07: слева 40°'), ('r07', f'07: справа 40°')))
        cls6 = ''
        cov = coverage(v06, os.path.join(a.pose_root, sku))
        cls7 = 'ok' if c07.get('passed') else 'bad'
        cards.append(f'<section class="card"><h2>№ {n} · {html.escape(role)} <small><i>{html.escape(sku)}</i> · <span>камера: поворот {az:.0f}°, высота {cam.get("el", 0):.0f}°</span></small></h2>'
                     f'<div class="row">{figs}</div><div class="st"><span class="{cls6}">06 · {status06(c06, cov)}</span><span class="{cls7}">07 · {status07(c07, times.get(sku))}</span></div></section>')
        print(f'{sku}: ок (№ {n})')
    legend = ('<div class="legend"><b>Как читать.</b> Для каждого товара — одни и те же ракурсы по шагам конвейера:<ul>'
              '<li><b>фото</b> — вырезка, из которой модель считала камеру;</li>'
              '<li><b>06</b> — фото перенесено на форму: цвет взят только с той части, которую видела камера («покрыто видимого» — доля кадра камеры, закрашенная фото);</li>'
              '<li><b>07</b> — невидимое залито цветом и фактурой видимой части (зеркалом и по поверхности);</li>'
              '<li><b>слева / справа 40°</b> — поворот на 40° от направления камеры, с которого снято фото (не от осей формы), чтобы увидеть бока и то, что залито.</li></ul>'
              'Нажмите на кадр — откроется крупнее. Строка 06 — сколько видимого покрыто фото; строка 07 — проверки заливки: зелёная — прошла, красная — нет (причина рядом).</div>')
    page = (f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Этап 07: заливка невидимого</title>'
            f'<style>{CSS}</style></head><body><main><h1>Этап 07 · залить невидимое</h1><p class="lead">{len(cards)} форм. Было → стало: что осталось от фото и как залито остальное.</p>{legend}{"".join(cards)}</main></body></html>')
    open(os.path.join(a.out, 'index.html'), 'w', encoding='utf-8').write(page)
    print(f'страница: {len(cards)} форм, кадров {len(sizes)}, макс. кадр {max(sizes or [0]) / 1024:.0f} КБ, всего {sum(sizes) / 2 ** 20:.1f} МБ → {a.out}/index.html')
    return 0 if cards else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--vis-root', required=True)
    ap.add_argument('--fill-root', required=True)
    ap.add_argument('--pose-root', required=True)
    ap.add_argument('--set', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--times', default='', help='items-07.json драйвера (run_s на товар)')
    ap.add_argument('--skus', default='')
    ap.add_argument('--reuse', action='store_true', help='кадры, что уже лежат в <out>/img, не рисовать заново (только пересобрать html)')
    return build(ap.parse_args())


if __name__ == '__main__':
    sys.exit(main())
