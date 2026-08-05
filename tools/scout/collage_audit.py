#!/usr/bin/env python3
"""Автоматическая приёмка коллажа: конвейер сам сверяет каждый предмет с геометрией.

Смысл. Коллаж — это фотографии товаров, положенные в наш собственный рендер сцены. У каждого
предмета ЕСТЬ аналитический эталон: место, куда вклейка ОБЯЗАНА лечь — прямоугольник, стоящий на
полу по следу предмета, шириной в видимую ширину следа и высотой в видимую высоту предмета
(высота плюс запрокинутая верхняя плоскость: карточки сняты сверху-сбоку, и крышка видна).
Эталон считается той же камерой, что и кадр, — сравнение честное и без нейросети.

Что проверяем по каждому предмету:
  ШИРИНА  — какую долю положенного прямоугольника заняла вклейка. Карточка снята в три четверти,
            её пропорция не равна пропорции предмета: при вписывании «по пропорции» широкая
            ТВ-тумба садится на 60% своего места, и коллаж спорит сам с собой.
  ВЫСОТА  — то же по вертикали.
  ВИСИТ   — низ вклейки выше низа эталона: товар оторван от пола.
  СМЕЩЕН  — центр вклейки уехал от центра эталона.
  НЕТ ФОТО — предмет в кадре, но показан серым объёмом (вклеить не удалось) — кандидат в 3D.

Предметы, которые мы намеренно не вклеиваем (подушки, плед, ТВ — их рисует модель по легенде),
в брак не идут: у них статус «рисует модель».

Пороги — в PASS. Возврат ненулевого кода = коллаж отправлять нельзя.

  ~/venvs/scout/bin/python collage_audit.py 21 --cams C1,C2
"""
import json
import os
import sys

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE_DIR = os.environ.get('SCENE_DIR', os.path.expanduser('~/scout-scenes'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '../../services/planner-solver'))

from scene_build import load_scene  # noqa: E402
from viz_paste import FLOOR, SKIP, SOFT, billboard, floor_quad  # noqa: E402
from planner.scene import cameras_for  # noqa: E402

PASS = {
    'width': (0.85, 1.15),      # доля ширины предмета, занятая вклейкой
    'height': (0.70, 1.30),
    'float': 0.10,              # низ вклейки выше низа предмета, доля высоты предмета
    'shift': 0.15,              # смещение центра, доля размера предмета
}
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'


def bbox(mask: np.ndarray):
    ys, xs = np.nonzero(mask)
    if not len(ys):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def project(pts: np.ndarray, cam, W: int, H: int):
    """Точки мира → пиксели кадра той же камерой, что рисовала сцену (со сдвигом объектива)."""
    eye, fwd, right, up = cam.basis()
    rel = pts - eye
    if cam.cyl:
        fv = (H / 2) / math.tan(math.radians(cam.vfov_deg) / 2)
        ang = np.arctan2(rel @ right, rel @ fwd)
        horiz = np.hypot(rel @ right, rel @ fwd)
        return W / 2 + ang / math.radians(cam.fov_deg) * W, H / 2 - fv * (rel @ up) / np.maximum(horiz, 1e-3)
    focal = (W / 2) / math.tan(math.radians(cam.fov_deg) / 2)
    z = np.maximum(rel @ fwd, 1e-3)
    return (W / 2 + focal * (rel @ right) / z,
            H / 2 - focal * (rel @ up) / z + cam.shift_y * H)


def target_box(p, it, cam, W: int, H: int):
    """Эталон: прямоугольник, который вклейка обязана заполнить (в пикселях кадра)."""
    corner, wvec, hvec, _ = (floor_quad(p, it) if p.role in FLOOR else billboard(p, it, cam))
    quad = np.array([corner, corner + wvec, corner + wvec + hvec, corner + hvec])
    us, vs = project(quad, cam, W, H)
    return int(us.min()), int(vs.min()), int(us.max()), int(vs.max())


def visible_share(mask: np.ndarray, alone_px: float) -> float:
    """Какая доля предмета реально видна: закрыт другими и обрезан краем — это законно."""
    return float(mask.sum()) / alone_px if alone_px > 1 else 1.0


def alone_areas(n: int, room, placements, cam, W: int, H: int) -> dict[str, float]:
    """Площадь каждого предмета, если бы его ничто не закрывало (рендер по одному, мелко)."""
    from planner.scene import Camera, compile_scene
    small = Camera(cam.name, cam.eye, cam.target, fov_deg=cam.fov_deg, ortho=cam.ortho,
                   cyl=cam.cyl, ortho_width_cm=cam.ortho_width_cm, vfov_deg=cam.vfov_deg,
                   shift_y=cam.shift_y, width=336, height=224)
    out = {}
    for p in placements:
        if p.item is None:
            continue
        try:
            res = compile_scene(room, [p], small)
        except Exception:  # noqa: BLE001 — оценка не должна валить приёмку
            continue
        out[p.role] = float((res['instances'] > 0).sum()) * (W * H) / (small.width * small.height)
    return out


def check(n: int, cam_name: str) -> list[dict]:
    prefix = os.path.join(SCENE_DIR, f'scene{n}-{cam_name}')
    paint = np.asarray(Image.open(f'{prefix}-painted.png'))
    H, W = paint.shape[:2]
    inst = np.asarray(Image.open(f'{prefix}-instances.png').convert('RGB'))[..., 0] // 8
    inst = np.asarray(Image.fromarray(inst.astype(np.uint8)).resize((W, H), Image.NEAREST))
    meta = json.load(open(f'{prefix}-paint.json'))
    frame = json.load(open(f'{prefix}-frame.json'))
    in_frame = set(frame['visible'])
    room, placements = load_scene(n)
    cam = next(c for c in cameras_for(room, placements) if c.name == cam_name)
    by = {p.role: p for p in placements}
    alone = alone_areas(n, room, placements, cam, W, H)
    rows = []
    for sid, role in meta['ids'].items():
        if role not in in_frame or role not in by:
            continue
        cam_key = cam_name
        if role in SKIP or role in SOFT:
            rows.append({'role': role, 'cam': cam_key, 'status': 'рисует модель', 'bad': []})
            continue
        try:
            geom = target_box(by[role], by[role].item, cam, W, H)
        except Exception:  # noqa: BLE001 — предмет без габаритов не проверяем
            continue
        # Предмет, закрытый другим или обрезанный краем кадра, меряться числами не может: его
        # вклейка законно меньше эталона. Такие честно помечаем и в брак не пишем — за них
        # отвечает признак видимости (`viz_marks.own_area`).
        vis = visible_share(inst == int(sid), alone.get(role, 0.0))
        if vis < 0.85:
            rows.append({'role': role, 'cam': cam_key, 'status': 'частично закрыт',
                         'visible': round(vis, 2), 'bad': []})
            continue
        gx0, gy0, gx1, gy1 = geom
        gx0, gx1 = max(gx0, 0), min(gx1, W - 1)
        gy0, gy1 = max(gy0, 0), min(gy1, H - 1)
        gw, gh = max(gx1 - gx0, 1), max(gy1 - gy0, 1)
        rec = {'role': role, 'cam': cam_key, 'target_px': [gw, gh],
               'target': [gx0, gy0, gx1, gy1], 'bad': []}
        got = bbox(paint == int(sid))
        if got is None:
            rec['status'] = 'объём' if role in meta['volumes'] else 'нет'
            rec['bad'].append('НЕТ ФОТО')
            rows.append(rec)
            continue
        px0, py0, px1, py1 = got
        pw, ph = max(px1 - px0, 1), max(py1 - py0, 1)
        rec['status'] = 'фото'
        rec['width'] = round(pw / gw, 2)
        rec['height'] = round(ph / gh, 2)
        rec['float'] = round((gy1 - py1) / gh, 2)
        rec['shift'] = round(abs(((px0 + px1) / 2) - ((gx0 + gx1) / 2)) / gw, 2)
        if not PASS['width'][0] <= rec['width'] <= PASS['width'][1]:
            rec['bad'].append('ШИРИНА')
        if not PASS['height'][0] <= rec['height'] <= PASS['height'][1]:
            rec['bad'].append('ВЫСОТА')
        if rec['float'] > PASS['float']:
            rec['bad'].append('ВИСИТ')
        if rec['shift'] > PASS['shift']:
            rec['bad'].append('СМЕЩЕН')
        rows.append(rec)
    return rows


def draw_report(n: int, cam_name: str, rows: list[dict]) -> str:
    """Картинка приёмки: зелёный — куда предмет обязан лечь, красный — куда легла вклейка."""
    prefix = os.path.join(SCENE_DIR, f'scene{n}-{cam_name}')
    im = Image.open(f'{prefix}-pasted.jpg').convert('RGB')
    paint = np.asarray(Image.open(f'{prefix}-painted.png'))
    paint = np.asarray(Image.fromarray(paint).resize(im.size, Image.NEAREST))
    meta = json.load(open(f'{prefix}-paint.json'))
    by_role = {v: int(k) for k, v in meta['ids'].items()}
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(FONT, 26)
    for r in rows:
        if r['status'] in ('рисует модель', 'частично закрыт'):
            continue
        g = r.get('target')
        if g:
            d.rectangle(g, outline=(40, 190, 90), width=4)
        p = bbox(paint == by_role.get(r['role'], -1))
        if p:
            d.rectangle(p, outline=(230, 40, 40), width=4)
        if g:
            label = r['role'] + (' · ' + ', '.join(r['bad']) if r['bad'] else ' · ок')
            d.text((g[0] + 4, max(g[1] - 30, 2)), label,
                   fill=(230, 40, 40) if r['bad'] else (40, 190, 90), font=f)
    dst = f'{prefix}-audit.jpg'
    im.save(dst, quality=92)
    return dst


def main() -> None:
    n = int(sys.argv[1])
    cams = (sys.argv[sys.argv.index('--cams') + 1].split(',')
            if '--cams' in sys.argv else ['C1', 'C2'])
    all_rows, bad = [], 0
    for cam in cams:
        rows = check(n, cam)
        all_rows += rows
        print(f'\nвид {cam}')
        print(f'{"предмет":14s} {"как показан":15s} {"ширина":>7s} {"высота":>7s} '
              f'{"висит":>6s} {"сдвиг":>6s}   замечания')
        for r in rows:
            if r['status'] in ('рисует модель', 'частично закрыт'):
                note = f'видно {r["visible"]:.0%}' if 'visible' in r else '—'
                print(f'{r["role"]:14s} {r["status"]:15s} {"—":>7s} {"—":>7s} {"—":>6s} '
                      f'{"—":>6s}   {note}')
                continue
            if r['status'] == 'фото':
                print(f'{r["role"]:14s} {r["status"]:15s} {r["width"]:7.2f} {r["height"]:7.2f} '
                      f'{r["float"]:6.2f} {r["shift"]:6.2f}   {", ".join(r["bad"]) or "—"}')
            else:
                print(f'{r["role"]:14s} {r["status"]:15s} {"—":>7s} {"—":>7s} {"—":>6s} '
                      f'{"—":>6s}   {", ".join(r["bad"])}')
            bad += bool(r['bad'])
        print('приёмка:', draw_report(n, cam, rows))
    dst = os.path.join(SCENE_DIR, f'scene{n}-audit.json')
    json.dump(all_rows, open(dst, 'w'), ensure_ascii=False, indent=1)
    ok = len(all_rows) - bad
    print(f'\nитого: {ok} из {len(all_rows)} позиций без замечаний, брак — {bad}')
    print(dst)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
