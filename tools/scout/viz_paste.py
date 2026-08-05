#!/usr/bin/env python3
"""Ф2 (дешёвый путь): фотография товара НАТЯГИВАЕТСЯ на его грань в кадре — без нейросети.

Почему так: пообъектная правка нейросетью стоит ~5–19 центов ЗА ПРЕДМЕТ, а комплект — это
12–17 предметов. Между тем мы знаем точную геометрию: где стоит предмет, какого он размера и
какой стороной повёрнут. Значит фотографию товара можно спроецировать на его переднюю грань
математикой — локально, бесплатно и со стопроцентной узнаваемостью (это буквально фото товара).

Нейросеть остаётся нужна только на финальное согласование света и краёв — один вызов на кадр
независимо от числа предметов.

  ~/venvs/scout/bin/python viz_paste.py 21              # вклеить все товары в панораму
  ~/venvs/scout/bin/python viz_paste.py 21 --only диван
"""
import io
import json
import math
import os
import sys

sys.path.insert(0, '/home/pakar/igor/remlab/services/planner-solver')

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from planner.scene import cameras_for, proxy_parts  # noqa: E402
from scene_build import SCENE_DIR, load_scene  # noqa: E402
from viz_objects import product  # noqa: E402
from viz_base import fal_key, fal_run, uri_from_image  # noqa: E402

import steps  # noqa: E402

# Плоские/мелкие роли не вклеиваем: у ковра и люстры фронтальной грани нет, декор не опознаётся
# Ковёр лежит на полу — у него отдельная ветка проекции. ТВ рисует базовый проход.
SKIP = {'тв'}
FLOOR = {'ковёр', 'ковер'}
# Мягкий декор снимают на белом фоне и часто «в наборе» — вырезка тащит в кадр белую подложку
# карточки. Такие позиции не вклеиваем никогда, их рисует модель по фото (владелец, 2026-08-04).
SOFT = {'подушка', 'подушка 2', 'плед', 'плед 2', 'покрывало'}
# Правило ракурса имеет смысл только для предметов с ЯВНЫМ ЛИЦОМ. У журнального столика, пуфа,
# вазы, лампы, кашпо и люстры фасада нет — они одинаковы со всех сторон, и проверять их на
# разворот нельзя: иначе они исчезают из коллажа (владелец, 2026-08-04).
FRONTED = {'диван', 'кресло', 'комод', 'тв-тумба', 'стеллаж', 'шкаф', 'стенка', 'кровать',
           'тумба', 'полка'}
# Прямоугольник следа рисуем на полу только у КЛЮЧЕВОЙ мебели: он задаёт и место, и размер
# основания, и разворот. У мелочи он захламляет кадр (владелец, 2026-08-04).
KEY_FLOOR = FRONTED | {'столик', 'стол', 'обеденный стол', 'пуф'}
# Низкую мебель (столик, пуф) фотографией не вклеиваем: вырезка всегда смотрит в камеру, и в
# двух видах один и тот же столик выглядит развёрнутым по-разному. Оставляем след на полу и
# серый объём, а внешний вид уходит эталоном отдельной картинкой (владелец, 2026-08-05).
LOW = {'столик', 'стол', 'обеденный стол', 'пуф'}
LOW_MAX_H = 60.0
# Подвесное под потолком (люстра, бра) 3D-моделью не заменяем никогда: оно высоко, разворот с
# пола не читается, а тонкие рожки и стекло генератор не восстанавливает — выходит мятая железка
# (владелец, 2026-08-05). Ни одна мебельная поверхность так высоко не поднимается.
HANG_MIN_ELEV = 150.0
# Роли, которым в ЭТОМ прогоне разрешено подставить 3D-модель. Список приходит от приёмки
# (`viz_build.py`): модель ставится не «на всякий случай», а только там, где фотография уже
# провалила проверку числами. По умолчанию — пусто: фото как есть (владелец, 2026-08-05).
MESH_ROLES: set[str] = set()


_CUTS: list[tuple[str, str]] = []      # что вырезали в этом прогоне — для журнала
# birefnet/v2 — вдвое чище край, чем birefnet и bria (замер на диване: светлый ореол 7,3% против
# 14,9% и 14,8% краевых пикселей). Разово на товар, ~1 цент, кэш навсегда.
CUTOUT = 'fal-ai/birefnet/v2'


def cutout(path: str) -> Image.Image:
    """Фото товара без фона (RGBA). Кэшируется рядом: `-cut.png`.

    Без этого вклейка тащит в кадр подложку карточки — у дивана белый ореол, у столика синий
    прямоугольник (поймано 2026-08-04).
    """
    dst = os.path.splitext(path)[0] + '-cut.png'
    if os.path.exists(dst):
        return Image.open(dst).convert('RGBA')
    _CUTS.append((path, dst))
    src = Image.open(path).convert('RGB')
    res = fal_run(CUTOUT, {'image_url': uri_from_image(src)}, fal_key())
    url = (res.get('image') or {}).get('url') or (res.get('images') or [{}])[0].get('url')
    if not url:
        return src.convert('RGBA')
    import urllib.request as _u
    raw = Image.open(io.BytesIO(_u.urlopen(url, timeout=120).read())).convert('RGBA')
    clean = defringe(raw)
    clean.save(dst)
    return clean


def defringe(img: Image.Image) -> Image.Image:
    """Снимает светлую кайму: у полупрозрачных пикселей вычитаем подмешанный фон карточки.

    Иначе вместе с товаром в кадр уезжает белый ободок, и предмет выглядит наклеенным.
    """
    a = np.asarray(img).astype(np.float32)
    rgb, alpha = a[..., :3], a[..., 3:4] / 255.0
    corners = np.concatenate([a[:4, :4, :3].reshape(-1, 3), a[:4, -4:, :3].reshape(-1, 3),
                              a[-4:, :4, :3].reshape(-1, 3), a[-4:, -4:, :3].reshape(-1, 3)])
    bg = corners.mean(axis=0) if len(corners) else np.array([255.0, 255.0, 255.0])
    soft = (alpha > 0.05) & (alpha < 0.97)
    fixed = np.where(soft, np.clip((rgb - (1 - alpha) * bg) / np.maximum(alpha, 0.05), 0, 255), rgb)
    out = np.concatenate([fixed, alpha * 255], axis=2).astype(np.uint8)
    return Image.fromarray(out, 'RGBA')


def trim_alpha(img: Image.Image) -> Image.Image:
    """Обрезает пустые поля по альфе — предмет должен занимать всю грань."""
    a = np.asarray(img)
    if a.shape[2] < 4:
        return img
    ys, xs = np.where(a[..., 3] > 8)
    if not len(xs):
        return img
    return img.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))


def trim_white(img: Image.Image, thr: int = 244) -> Image.Image:
    """Обрезает белые поля фотографии товара — иначе предмет вклеится с воздухом по краям."""
    a = np.asarray(img.convert('RGB'))
    nonwhite = (a < thr).any(axis=2)
    if not nonwhite.any():
        return img
    ys, xs = np.where(nonwhite)
    return img.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))


def face_of(p, it) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, float]:
    """Передняя грань предмета: точка-угол, вектор ширины, нормаль, ширина и высота (см)."""
    parts = proxy_parts(p, it)
    x0 = min(q[0] for q in parts)
    x1 = max(q[1] for q in parts)
    z0 = min(q[4] for q in parts)
    z1 = max(q[5] for q in parts)
    h = max(q[3] for q in parts)
    rot = int(round(p.rot)) % 360
    if rot in (0, 180):
        zf = z1 if rot == 0 else z0                       # лицевая плоскость по глубине
        n = np.array([0.0, 0.0, 1.0 if rot == 0 else -1.0])
        corner = np.array([x0, 0.0, zf])
        wvec = np.array([x1 - x0, 0.0, 0.0])
    else:
        xf = x1 if rot == 90 else x0
        n = np.array([1.0 if rot == 90 else -1.0, 0.0, 0.0])
        corner = np.array([xf, 0.0, z0])
        wvec = np.array([0.0, 0.0, z1 - z0])
    return corner, wvec, n, float(np.linalg.norm(wvec)), h


def axis_plane(p, it, cam):
    """Плоскость вырезки ВДОЛЬ СОБСТВЕННОЙ длинной стороны предмета, а не лицом к камере.

    Для столика, ковра, пуфа «лица» нет, но есть вытянутость. Камерная вырезка показывала их
    развёрнутыми к зрителю — и модель честно копировала этот разворот, игнорируя текст
    (владелец: «столик не развёрнут», 2026-08-04). Здесь предмет стоит своей осью, как в плане.
    """
    eye, fwd, right, up = cam.basis()
    w, d = float(it.w_cm), float(it.d_cm)
    rot = int(round(p.rot)) % 180
    long_x = (w >= d) if rot == 0 else (d > w)
    axis = np.array([1.0, 0.0, 0.0]) if long_x else np.array([0.0, 0.0, 1.0])
    length = max(w, d)
    normal = np.array([0.0, 0.0, 1.0]) if long_x else np.array([1.0, 0.0, 0.0])
    to_cam = np.array([eye[0] - p.x, 0.0, eye[2] - p.y])
    if float(normal @ to_cam) < 0:
        normal = -normal
    base = float(getattr(p, 'elev_cm', 0.0))
    h_cm = float(it.h_cm or 60.0)
    corner = np.array([p.x, base, p.y]) - axis * (length / 2)
    return corner, axis * length, np.array([0.0, h_cm, 0.0]), normal


def billboard(p, it, cam):
    """Вырезка товара СТОИТ НА ПОЛУ лицом к камере — как фигура на подставке.

    Раньше фото натягивалось на переднюю плоскость коробки. У низкой мебели (столик, тумба) мы
    сверху видим не перёд, а столешницу, и фотография оказывалась вертикальной картинкой ВНУТРИ
    серого объёма — «отражение внутри модели» (владелец, 2026-08-04). Стоячая вырезка так не врёт:
    предмет всегда повёрнут к зрителю тем, что снято на фото.
    """
    eye, fwd, right, up = cam.basis()
    centre = np.array([p.x, 0.0, p.y])
    look = centre - eye
    look[1] = 0.0
    n = np.linalg.norm(look)
    look = look / (n if n > 1e-6 else 1.0)
    side = np.cross(np.array([0.0, 1.0, 0.0]), look)          # горизонтальная ось вырезки
    side /= max(float(np.linalg.norm(side)), 1e-6)
    # Ширину берём НЕ из паспорта, а как видимую ширину следа под текущим углом: пуф 71×57,
    # повёрнутый к нам углом, занимает больше 71 см по горизонтали, и вырезка вылезала за свой
    # след (владелец: «пуф крупнее», 2026-08-04).
    from planner.geometry import footprint as _fp
    poly = _fp(p, it)
    xs_f, ys_f = poly.exterior.coords.xy
    proj = [float(x) * side[0] + float(y) * side[2] for x, y in zip(xs_f, ys_f)]
    w_cm = max(max(proj) - min(proj), 1.0)
    h_cm = float(it.h_cm or 60.0) + float(getattr(p, "elev_cm", 0.0))
    base = float(getattr(p, "elev_cm", 0.0))
    # Плоскость вырезки ставим не в ЦЕНТР предмета, а на его БЛИЖНЮЮ грань. Из центра низ
    # предмета проецируется выше настоящей линии касания пола, и товар выглядит висящим —
    # особенно низкая мебель, на которую смотрят сверху (владелец, 2026-08-05).
    depth = [float(x) * look[0] + float(y) * look[2] for x, y in zip(xs_f, ys_f)]
    # Сдвиг ОГРАНИЧЕН. На всю глубину предмета его двигать нельзя: диван глубиной 150 см уезжал
    # к зрителю на 75 см и выглядел отставленным от стены, а пуф уходил ниже кадра целиком
    # (владелец, 2026-08-05). 20 см хватает, чтобы низкая мебель перестала висеть.
    near = min((max(depth) - min(depth)) / 2, 20.0)
    centre = centre - look * near
    corner = centre - side * (w_cm / 2) + np.array([0.0, base, 0.0])
    return corner, side * w_cm, np.array([0.0, h_cm - base, 0.0]), look


def floor_quad(p, it):
    """Горизонтальный четырёхугольник ковра: он лежит, а не стоит."""
    from planner.geometry import footprint
    poly = footprint(p, it)
    xs, ys = poly.exterior.coords.xy
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    corner = np.array([x0, 0.6, y0])
    return (corner, np.array([x1 - x0, 0.0, 0.0]), np.array([0.0, 0.0, y1 - y0]),
            np.array([0.0, 1.0, 0.0]))


def mesh_yaw_pitch(p, it, cam) -> tuple[float, float]:
    """Под каким углом развернуть 3D-модель, чтобы камера увидела предмет как в плане.

    Знак разворота выводится, а не подбирается: у модели, собранной по фронтальному фото, «лицо»
    смотрит в камеру при yaw = 0, а положительный yaw выводит на экран ЛЕВЫЙ бок. Поэтому
    считаем, какой бок предмета виден по плану и с какой стороны кадра он окажется.
    """
    face = {0: (0.0, 1.0), 90: (1.0, 0.0), 180: (0.0, -1.0),
            270: (-1.0, 0.0)}.get(int(round(p.rot)) % 360, (0.0, 1.0))
    eye, fwd, right, up = cam.basis()
    v = np.array([eye[0] - p.x, eye[2] - p.y], float)
    v /= max(float(np.linalg.norm(v)), 1e-6)
    f = np.array(face, float)
    mag = math.degrees(math.acos(max(-1.0, min(1.0, float(f @ v)))))
    side = np.array([f[1], -f[0]])                    # какой бок предмета повёрнут к камере
    if float(side @ v) < 0:
        side = -side
    on_screen = float(side[0] * right[0] + side[1] * right[2])   # он слева или справа в кадре
    yaw = mag if on_screen < 0 else -mag
    dist = math.hypot(p.x - eye[0], p.y - eye[2])
    h = float(getattr(it, 'h_cm', 0) or 0) + float(getattr(p, 'elev_cm', 0.0))
    pitch = math.degrees(math.atan2(max(float(eye[1]) - h, 0.0), max(dist, 1.0)))
    return yaw, pitch


def mesh_source(n: int, role: str, p, it, cam) -> Image.Image | None:
    """Картинка предмета с 3D-модели под углом камеры — ЕСЛИ модель тут вообще уместна.

    Модель подставляется не всегда, а по трём правилам подряд (владелец, 2026-08-05):
      1. Подвесное под потолком (люстра, бра) — НИКОГДА. Оно высоко, разворот с пола не читается,
         а тонкие рожки и стекло генератор не восстанавливает: выходит мятая железка.
      2. Решение «этому предмету нужна модель» принимает ПРИЁМКА кадра (`viz_build`): фото
         подставляется по умолчанию, и только провалившие проверку числами уходят на 3D.
         Роль обязана быть в `MESH_ROLES` — сюда её кладёт сборщик, а не догадка.
      3. Сама модель должна пройти самопроверку: рендер под ракурсом карточки обязан совпасть с
         силуэтом этой карточки. Не совпал — модель бракованная, работаем по фото.
    """
    try:
        if float(getattr(p, 'elev_cm', 0.0)) > 1.0:
            return None      # правило 1: моделим только напольное (подвесное и то, что стоит
                             # на мебели, — фотографией)
        from mesh_make import mesh_path, mesh_trusted
        from mesh_render import load_parts, render
        from viz_objects import product as _product
        it_card, photo = _product(n, role)
        path = mesh_path(it_card)
        if not os.path.exists(path) or not mesh_trusted(path, photo):   # правило 3
            return None
        yaw, pitch = mesh_yaw_pitch(p, it, cam)
        return trim_alpha(render(load_parts(path), yaw, pitch, size=(900, 900)))
    except Exception as e:  # noqa: BLE001 — нет модели/сбой рендера: работаем по фотографии
        print(f'  {role}: 3D не вышло ({str(e)[:60]}) — беру фото')
        return None


def _footprint_mask(p, it, cam, W: int, H: int) -> np.ndarray | None:
    """След предмета на полу, залитый в пикселях кадра. Внутри него пол предмету не помеха."""
    if cam.cyl or float(getattr(p, 'elev_cm', 0.0)) > 1.0:
        return None
    try:
        from PIL import ImageDraw
        from planner.geometry import footprint as _fp
        eye, fwd, right, up = cam.basis()
        focal = (W / 2) / math.tan(math.radians(cam.fov_deg) / 2)
        xs, ys = _fp(p, it).exterior.coords.xy
        pts = []
        for x, y in zip(xs, ys):
            rel = np.array([float(x), 0.0, float(y)]) - eye
            z = float(rel @ fwd)
            if z <= 1e-3:
                return None
            pts.append((W / 2 + focal * float(rel @ right) / z,
                        H / 2 - focal * float(rel @ up) / z + cam.shift_y * H))
        m = Image.new('L', (W, H), 0)
        ImageDraw.Draw(m).polygon(pts, fill=255)
        return np.asarray(m) > 0
    except Exception:  # noqa: BLE001 — нет следа: работаем как раньше
        return None


def paste_mesh_screen(pano: np.ndarray, cam, p, it, img: Image.Image,
                      paint: np.ndarray | None = None, sid: int = 0) -> int:
    """Рендер 3D-модели ставится по РЕАЛЬНОМУ МЕСТУ предмета в кадре.

    Ширина — видимая ширина следа под этим углом, низ — линия касания пола (обе величины считает
    та же геометрия, что рисует сцену). Пропорции рендера не ломаем: он уже сделан под углом
    камеры. Если предмет обрезан краем кадра, рендер уходит за край и обрезается естественно —
    подгонять его под обрезанный силуэт нельзя, иначе он сжимается или вытягивается (владелец,
    2026-08-05).
    """
    H, W = pano.shape[:2]
    eye, fwd, right, up = cam.basis()
    corner, wv, hv, _n = billboard(p, it, cam)
    quad = np.array([corner, corner + wv, corner + wv + hv, corner + hv])
    rel = quad - eye
    if float(np.max(rel @ fwd)) <= 1.0:
        return 0
    focal = (W / 2) / math.tan(math.radians(cam.fov_deg) / 2)
    z = np.maximum(rel @ fwd, 1e-3)
    us = W / 2 + focal * (rel @ right) / z
    vs = H / 2 - focal * (rel @ up) / z + cam.shift_y * H
    bw = float(us.max() - us.min())
    if bw < 4:
        return 0
    cut = trim_alpha(img)
    k = bw / cut.width
    nw, nh = max(int(cut.width * k), 2), max(int(cut.height * k), 2)
    cut = cut.resize((nw, nh), Image.LANCZOS)
    src = np.asarray(cut).astype(np.float32)
    ox = int(round((us.min() + us.max()) / 2 - nw / 2))
    oy = int(round(float(vs.max()) - nh))            # низ рендера — на линии касания пола
    y_from, x_from = max(oy, 0), max(ox, 0)
    y_to, x_to = min(oy + nh, H), min(ox + nw, W)
    if y_to <= y_from or x_to <= x_from:
        return 0
    src = src[y_from - oy:y_to - oy, x_from - ox:x_to - ox]
    alpha = (src[..., 3:4] / 255.0) if src.shape[2] > 3 else np.ones(src.shape[:2] + (1,), np.float32)
    ok = alpha[..., 0] > 0.15
    if ok.sum() < 50:
        return 0
    yy, xx = np.nonzero(ok)
    Y, X = yy + y_from, xx + x_from
    a = alpha[yy, xx]
    base = pano[Y, X].astype(np.float32)
    pano[Y, X] = np.clip(src[yy, xx, :3] * a + base * (1 - a), 0, 255).astype(np.uint8)
    if paint is not None:
        paint[Y, X] = sid
    return int(ok.sum())


def paste_role(pano: np.ndarray, zbuf: np.ndarray, cam, p, it, photo: Image.Image,
               paint: np.ndarray | None = None, sid: int = 0, is_mesh: bool = False) -> int:
    """Ставит вырезку товара в кадр. Рисуем по прямоугольнику вырезки, а не по силуэту коробки:
    иначе часть товара срезается по её краю (у столика отрезало половину столешницы — владелец,
    2026-08-04). Что чем перекрыто, решает z-буфер сцены."""
    H, W = pano.shape[:2]
    eye, fwd, right, up = cam.basis()
    fv = (H / 2) / math.tan(math.radians(cam.vfov_deg) / 2)
    if p.role in FLOOR:                    # ковёр лежит НА ПОЛУ: проекция на горизонталь
        corner, wvec, hvec, n = floor_quad(p, it)
    # ОТКАЧЕНО 2026-08-04: постановка вытянутых предметов по собственной оси искажала форму —
    # фронтальное фото, показанное боком, сплющивается. Вырезка снова смотрит на камеру,
    # а разворот описывается словами в легенде (`axis_of`).
    else:
        # Фронтальное фото годится, только пока мы смотрим предмету В ЛИЦО. Если по плану он
        # повёрнут к нам боком, вырезка врёт: диван «разворачивается» во всю ширину там, где
        # виден торец (владелец, 2026-08-04). Такие предметы уходят на нейросетевой проход.
        # Фотографию вставляем КАК ЕСТЬ. Отказываемся от неё только при СИЛЬНОМ развороте —
        # когда камера смотрит на сторону, которой на карточке просто нет (правило владельца
        # 2026-08-05: порог 90°, `mesh_need`). При меньших углах фото честнее любого рендера:
        # это настоящий вид товара.
        if not is_mesh:
            from mesh_need import needs_mesh as _needs
            if _needs(p, it, cam) and p.role not in MESH_ROLES:
                return -1
        corner, wvec, hvec, n = billboard(p, it, cam)
    w_cm = float(np.linalg.norm(wvec))
    h_cm = float(np.linalg.norm(hvec))
    quad = np.array([corner, corner + wvec, corner + wvec + hvec, corner + hvec])
    rel = quad - eye
    # Предмет, оказавшийся ЗА камерой, рисовать нельзя: проекция «заворачивается» и в кадр
    # попадает призрак (в виде C2 так появлялся диван, которого там нет — 2026-08-04).
    if not cam.cyl and float(np.max(rel @ fwd)) <= 1.0:
        return 0
    centre_dir = (corner + wvec / 2 + hvec / 2) - eye
    centre_dir = centre_dir / max(float(np.linalg.norm(centre_dir)), 1e-6)
    if not cam.cyl:
        ang_off = math.degrees(math.acos(max(-1.0, min(1.0, float(centre_dir @ fwd)))))
        if ang_off > cam.fov_deg / 2 + 30:
            return 0
    if cam.cyl:
        angq = np.arctan2(rel @ right, rel @ fwd)
        horiz = np.hypot(rel @ right, rel @ fwd)
        uq = W / 2 + angq / math.radians(cam.fov_deg) * W
        vq = H / 2 - fv * (rel @ up) / np.maximum(horiz, 1e-3)
    else:
        focal = (W / 2) / math.tan(math.radians(cam.fov_deg) / 2)
        zq = np.maximum(rel @ fwd, 1e-3)
        uq = W / 2 + focal * (rel @ right) / zq
        vq = H / 2 - focal * (rel @ up) / zq + cam.shift_y * H
    x0, x1 = int(max(0, np.floor(uq.min()))), int(min(W - 1, np.ceil(uq.max())))
    y0, y1 = int(max(0, np.floor(vq.min()))), int(min(H - 1, np.ceil(vq.max())))
    if x1 <= x0 or y1 <= y0:
        return 0
    gy, gx = np.mgrid[y0:y1 + 1, x0:x1 + 1]
    ys, xs = gy.ravel(), gx.ravel()
    if cam.cyl:                                            # панорама
        ang = (xs - W / 2) / W * math.radians(cam.fov_deg)
        dirs = (fwd[None, :] * np.cos(ang)[:, None]
                + right[None, :] * np.sin(ang)[:, None]
                + up[None, :] * ((H / 2 - ys) / fv)[:, None])
    else:                                                  # обычный кадр со сдвигом объектива
        focal2 = (W / 2) / math.tan(math.radians(cam.fov_deg) / 2)
        dirs = (fwd[None, :] * focal2
                + right[None, :] * (xs - W / 2)[:, None]
                + up[None, :] * (H / 2 + cam.shift_y * H - ys)[:, None])
    denom = dirs @ n
    with np.errstate(divide='ignore', invalid='ignore'):
        t = ((corner - eye) @ n) / denom
    hit = eye[None, :] + dirs * t[:, None]
    s = ((hit - corner[None, :]) @ wvec) / (w_cm ** 2)
    v = ((hit - corner[None, :]) @ hvec) / (h_cm ** 2)
    ok = np.isfinite(t) & (t > 0) & (s >= -0.02) & (s <= 1.02) & (v >= -0.02) & (v <= 1.02)
    if ok.sum() < 200:
        return 0

    if p.role in SOFT:
        return -1
    cut = trim_alpha(photo)
    a = np.asarray(cut)
    if a.shape[2] > 3 and not is_mesh:
        # Признак несработавшего матирования — НЕПРОЗРАЧНАЯ РАМКА по краю: у настоящей вырезки
        # углы прозрачны. Белый товар на белом фоне (подушки, плед) режется плохо, и в кадр
        # уезжает белый прямоугольник (владелец, 2026-08-04).
        al = a[..., 3] > 128
        border = np.concatenate([al[0], al[-1], al[:, 0], al[:, -1]])
        rgb_op = a[..., :3][al]
        near_white = float((rgb_op.min(axis=1) > 238).mean()) if len(rgb_op) else 0.0
        if border.mean() > 0.5 or al.mean() > 0.88 or near_white > 0.45:
            return -1                              # в вырезке осталась белая подложка карточки
    if p.role in FLOOR:
        # У ковра снимок обычно вертикальный, а след — вдоль дивана. Разворачиваем фото под след
        # и заполняем его целиком: иначе ковёр ложится поперёк (владелец, 2026-08-04).
        long_x = float(np.linalg.norm(wvec)) >= float(np.linalg.norm(hvec))
        if (cut.width >= cut.height) != long_x:
            cut = cut.transpose(Image.ROTATE_90)
    # Картинку сперва УМЕНЬШАЕМ под размер её места в кадре, и только потом выбираем пиксели.
    # Иначе выборка «через один» теряет тонкие детали: у столика пропадали ножки, и приёмка
    # честно писала «висит» (2026-08-05). Усреднение при уменьшении делает их полупрозрачными,
    # но видимыми.
    box_w, box_h = max(x1 - x0, 1), max(y1 - y0, 1)
    if cut.width > box_w * 1.4 or cut.height > box_h * 1.4:
        # Уменьшаем ПРОПОРЦИОНАЛЬНО. Подгонка прямо под размеры рамки сплющивала предмет: пуф
        # 71×57 растягивался в длинную банкетку, потому что после такой подгонки пропорция
        # картинки становилась равна пропорции рамки и вписывание уже ничего не исправляло
        # (владелец, 2026-08-05).
        k = max(box_w / cut.width, box_h / cut.height)
        cut = cut.resize((max(int(cut.width * k), 8), max(int(cut.height * k), 8)), Image.LANCZOS)
    src = np.asarray(cut).astype(np.float32)
    sh, sw = src.shape[:2]
    # ПРОПОРЦИИ ФОТО НЕ ЛОМАЕМ: вписываем снимок в габарит предмета и ставим по низу и центру,
    # иначе диван сплющивается по высоте, а стеллаж растягивается (владелец, 2026-08-04)
    box_ar = (w_cm / h_cm) if h_cm > 1e-6 else 1.0
    ph_ar = sw / max(sh, 1)
    if p.role in FLOOR:                    # ковёр растягиваем на весь след — он и есть его размер
        fit_w = fit_h = 1.0
    else:
        # ПРОПОРЦИИ РЕНДЕРА НЕ ЛОМАЕМ. Растягивание модели на всю рамку превращало пуф 71×57
        # в длинную банкетку (владелец, 2026-08-05). Рендер уже сделан под углом камеры, значит
        # его пропорция верна — вписываем как фотографию.
        # ЗАПОЛНЯЕМ ШИРИНУ. Карточку снимают в три четверти, поэтому пропорция фотографии не
        # равна пропорции места: при вписывании «по меньшей стороне» широкая ТВ-тумба садилась
        # на 60% своего следа и выглядела висящей. Ширину задаёт след на полу — её и держим,
        # высоте разрешаем выйти за габарит не больше чем на треть (владелец, 2026-08-05).
        fit_w = 1.0
        fit_h = min(1.0, (box_ar / ph_ar) * 1.35)
        if ph_ar < box_ar:                       # фото уже места — тогда как раньше, по высоте
            fit_w = min(1.0, ph_ar / box_ar * 1.35)
            fit_h = 1.0
    su = (s[ok] - (1 - fit_w) / 2) / fit_w          # центрируем по ширине
    sv = v[ok] / fit_h                              # прижимаем к полу
    inside = (su >= 0) & (su <= 1) & (sv >= 0) & (sv <= 1)
    if inside.sum() < 100:
        return 0
    px = np.clip((su[inside] * (sw - 1)).astype(int), 0, sw - 1)
    py = np.clip(((1 - sv[inside]) * (sh - 1)).astype(int), 0, sh - 1)
    smp = src[py, px]
    rgb = smp[:, :3]
    alpha = (smp[:, 3:4] / 255.0) if src.shape[2] > 3 else np.ones((len(px), 1), np.float32)
    yy, xx = ys[ok][inside], xs[ok][inside]
    zpix = (t[ok][inside] if cam.cyl else t[ok][inside] * (dirs[ok][inside] @ fwd))
    # ПОЛ НЕ МОЖЕТ ЗАКРЫВАТЬ ПРЕДМЕТ, КОТОРЫЙ НА НЁМ СТОИТ. Вырезка стоит в плоскости центра
    # предмета, а пол перед ней ближе к камере — из-за этого у низкой мебели z-буфер срезал низ:
    # у столика с высоты 155 см пропадала треть высоты вместе с ножками, и приёмка честно писала
    # «ВИСИТ» (2026-08-05). Внутри собственного следа предмета глубина сцены не действует.
    free = _footprint_mask(p, it, cam, W, H)
    saved = None
    if free is not None:
        saved = zbuf[free].copy()
        zbuf[free] = 1e9
    visible = (zpix < zbuf[yy, xx] + 1.0) & (alpha[:, 0] > 0.02)   # 1 см допуска на стену за спиной
    if free is not None:
        zbuf[free] = saved
    if visible.sum() < 50:
        return 0
    yy, xx, rgb, alpha, zpix = (yy[visible], xx[visible], rgb[visible],
                                alpha[visible], zpix[visible])
    base_px = pano[yy, xx].astype(np.float32)
    pano[yy, xx] = np.clip(rgb * alpha + base_px * (1 - alpha), 0, 255).astype(np.uint8)
    hard = alpha[:, 0] > 0.5
    # Ковёр лежит на полу и не может ничего заслонять: когда он писал глубину, у мебели, стоящей
    # НА нём, срезались ножки (приёмка ловила это как «ВИСИТ» у столика, 2026-08-05).
    if p.role not in FLOOR:
        zbuf[yy[hard], xx[hard]] = zpix[hard]                      # ближние перекроют дальние
    if paint is not None:
        # Карта «что куда легло» — по ней конвейер сам себя проверяет. Порог мягче, чем у
        # z-буфера: тонкие ножки столика почти прозрачны, и по жёсткому порогу приёмка считала
        # предмет висящим над полом, хотя ножки нарисованы (2026-08-05).
        soft = alpha[:, 0] > 0.15
        paint[yy[soft], xx[soft]] = sid
    return int(hard.sum())


HARMONIZE = 'fal-ai/nano-banana/edit'      # один вызов на кадр, ~4 цента, независимо от числа
                                           # предметов — иначе цена растёт линейно и не влезает


def harmonize(pano: Image.Image) -> Image.Image:
    """Согласование вклеенных фотографий со сценой: тени, контакт с полом, края.

    Товары уже стоят на своих местах и это ИХ фотографии — модели остаётся только «подружить»
    их со светом сцены. Composition при этом менять нельзя, о чём и говорит промпт.
    """
    prompt = ('Blend the furniture into this interior photo: add soft contact shadows under every '
              'piece, match the room lighting and white balance, soften the cut-out edges. '
              'Do NOT move, resize, replace or restyle any object: every piece of furniture must '
              'keep exactly its current position, size, shape, colour and fabric. Keep walls, '
              'floor, window and door exactly as they are. Photorealistic interior photo.')
    res = fal_run(HARMONIZE, {'prompt': prompt, 'image_urls': [uri_from_image(pano)],
                              'num_images': 1, 'output_format': 'png'}, fal_key())
    url = (res.get('images') or [{}])[0].get('url')
    if not url:
        return pano
    import io as _io
    import urllib.request as _u
    out = Image.open(_io.BytesIO(_u.urlopen(url, timeout=240).read())).convert('RGB')
    return out.resize(pano.size)


def ref_sheet(n: int, roles: list[str]) -> tuple[Image.Image, list[str]]:
    """Лист референсов: фото товаров с подписями ролей — чтобы модель видела, ЧТО стоит в кадре."""
    from PIL import ImageDraw, ImageFont
    cells, names = [], []
    for role in roles:
        try:
            it, path = product(n, role)
        except KeyError:
            continue
        if not os.path.exists(path):
            continue
        cells.append((role, cutout(path)))
        names.append(f'{role}: {(it.get("name") or "")[:70]}')
    if not cells:
        return None, []
    cols = min(4, len(cells))
    rows = (len(cells) + cols - 1) // cols
    cw, ch = 420, 400
    sheet = Image.new('RGB', (cols * cw, rows * ch), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    f = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 26)
    for i, (role, img) in enumerate(cells):
        im = trim_alpha(img).convert('RGBA')
        im.thumbnail((cw - 30, ch - 70))
        x, y = (i % cols) * cw, (i // cols) * ch
        bg = Image.new('RGBA', im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        sheet.paste(bg.convert('RGB'), (x + (cw - im.width) // 2, y + 20))
        d.text((x + 14, y + ch - 42), role, fill=(20, 20, 20), font=f)
    return sheet, names


def harmonize_gpt(frame: Image.Image, sheet: Image.Image, names: list[str]) -> Image.Image:
    """Согласование через OpenAI: кадр + ЛИСТ РЕФЕРЕНСОВ с подписями, до 16 картинок за запрос.

    Идея владельца: пусть модель сама видит и мебель, и сцену. Геометрию ей при этом не доверяем —
    предметы уже вклеены на свои места, менять их запрещено промптом.
    """
    from viz_objects import edit_gpt_raw
    prompt = ('This is a photo-collage of a real living room: every piece of furniture is a real '
              'product photo pasted at its exact position and size. Turn it into one believable '
              'photograph: add soft contact shadows under each piece, unify lighting and white '
              'balance, soften the pasted edges, fix the floor and wall junctions. '
              'STRICT: do not move, resize, rotate, remove, add or restyle any furniture; keep '
              'every product exactly as shown, including fabric, colour and proportions. '
              'The second image is a reference sheet of the same products with labels: '
              + '; '.join(names) + '.')
    return edit_gpt_raw([frame, sheet], prompt, size='1536x1024')


def main() -> None:
    n = int(sys.argv[1])
    if '--mesh-roles' in sys.argv:
        MESH_ROLES.update(r for r in sys.argv[sys.argv.index('--mesh-roles') + 1].split(',') if r)
    only = sys.argv[sys.argv.index('--only') + 1] if '--only' in sys.argv else None
    cam_name = sys.argv[sys.argv.index('--cam') + 1] if '--cam' in sys.argv else 'P'
    prefix = os.path.join(SCENE_DIR, f'scene{n}-{cam_name}')
    # По умолчанию вклеиваем в НАШ clay-рендер: он геометрически точен. Сгенерированная оболочка
    # ставит пол и стены «примерно», из-за чего вклеенная мебель повисает в воздухе (2026-08-04).
    # База — рендер ПУСТОЙ комнаты. Объём (серую коробку) дорисовываем только тем предметам,
    # которые не удалось вклеить. Обратный порядок — стирать коробки из полного рендера — оставлял
    # на полу заплатки другого тона (владелец: «что это за жёлтые зоны», 2026-08-04).
    base = f'{prefix}-empty-clay.png'
    if '--base' in sys.argv:
        base = f'{prefix}-{sys.argv[sys.argv.index("--base") + 1]}.jpg'
    pano = np.asarray(Image.open(base).convert('RGB')).copy()
    H, W = pano.shape[:2]
    full_p = f'{prefix}-clay.png'
    full = (np.asarray(Image.open(full_p).convert('RGB').resize((W, H))).copy()
            if os.path.exists(full_p) else None)
    inst_img = Image.open(f'{prefix}-instances.png').convert('RGB').resize((W, H), Image.NEAREST)
    ids_full = np.asarray(inst_img)[..., 0] // 8
    meta = json.load(open(f'{prefix}-frame.json'))
    id_map = meta['ids']
    in_frame = set(meta['visible'])        # правило «меньше 15% предмета → вне кадра» — общее
    room, placements = load_scene(n)
    cam = next(c for c in cameras_for(room, placements) if c.name == cam_name)
    by = {p.role: p for p in placements}
    # z-буфер стартует с ПУСТОЙ комнаты: дальше каждый вклеенный товар пишет в него свою глубину,
    # поэтому ближние честно перекрывают дальние, а стены отсекают то, что за ними
    from planner.scene import compile_scene
    zbuf = compile_scene(room, [], cam)['depth'].copy()
    ex, _, ez = cam.eye
    # Ковёр кладём ПЕРВЫМ, остальное — от дальнего к ближнему. По одному только расстоянию ковёр
    # оказывался последним (его центр ближе к камере) и закрашивал ножки мебели, стоящей на нём
    # (поймано приёмкой: у столика «ВИСИТ 0.45», 2026-08-05).
    order = sorted(id_map.items(),
                   key=lambda kv: (0 if kv[1] in FLOOR else 1,
                                   -((by[kv[1]].x - ex) ** 2 + (by[kv[1]].y - ez) ** 2)
                                   if kv[1] in by else 0))

    total = 0
    angled: list[str] = []
    done_roles: list[str] = []
    # Карта «что куда легло»: id предмета в каждом закрашенном пикселе. Нужна, чтобы конвейер САМ
    # сверял коллаж с геометрией (`collage_audit.py`) и не отправлял в модель заведомый брак.
    paint = np.zeros((H, W), np.int32)
    volumes: list[str] = []
    meshed: list[str] = []
    for sid, role in order:
        if role not in in_frame:           # компилятор уже решил, что предмета в кадре нет
            continue
        if role in SKIP or (only and role != only) or role not in by:
            continue
        try:
            it, photo_path = product(n, role)
        except KeyError:
            continue
        if not os.path.exists(photo_path):
            print(f'  {role}: нет фото товара')
            continue
        mesh_img = (mesh_source(n, role, by[role], by[role].item, cam)
                    if role in MESH_ROLES else None)
        if mesh_img is not None:
            # у модели есть настоящий силуэт в карте объектов — ставим по нему
            px = paste_mesh_screen(pano, cam, by[role], by[role].item, mesh_img,
                                   paint, int(sid))
        else:
            px = paste_role(pano, zbuf, cam, by[role], by[role].item, cutout(photo_path),
                            paint=paint, sid=int(sid))
        if mesh_img is not None and px > 0:
            meshed.append(role)
        if px <= 0:
            # СЕРЫЙ ОБЪЁМ БОЛЬШЕ НЕ РИСУЕМ. Он давал модели ложную форму: непоставленный комод
            # выходил ступенчатым обрубком у дивана, и модель честно рисовала мебель по нему
            # (владелец: «что за бред», 2026-08-05). Предмету достаточно контура следа на полу
            # (место, размер, разворот) и эталона товара картинкой 4 — по ним модель рисует
            # настоящую вещь, а приёмка помечает позицию как «нет фото».
            volumes.append(role)
        if px < 0:
            angled.append(role)
            print(f'  {role}: сильный ракурс — на нейросетевой проход')
            continue
        total += px
        if px:
            done_roles.append(role)
        print(f'  {role}: {px} px' if px else f'  {role}: не попал в кадр')
    # След предмета на полу тонким контуром: фотография не может показать разворот (вырезка
    # всегда смотрит на камеру), а контур показывает — и модель ставит предмет на него.
    # Так разворот задаётся ГЕОМЕТРИЕЙ, а не словами (владелец, 2026-08-04).
    if '--no-footprints' not in sys.argv:
        from PIL import ImageDraw
        from planner.geometry import footprint as _fp
        img_fp = Image.fromarray(pano)
        dr = ImageDraw.Draw(img_fp, 'RGBA')
        eye, fwd, right, up = cam.basis()
        focal = (W / 2) / math.tan(math.radians(cam.fov_deg) / 2)

        def to_px(x, y):
            rel = np.array([x, 0.0, y], float) - eye
            z = float(rel @ fwd)
            if z <= 1e-3:
                return None
            return (W / 2 + focal * float(rel @ right) / z,
                    H / 2 - focal * float(rel @ up) / z + cam.shift_y * H)

        for role in in_frame:
            pl = by.get(role)
            if pl is None or pl.item is None:
                continue
            # контур рисуем ВСЕМ напольным предметам: он задаёт не только разворот, но и РАЗМЕР —
            # без него модель рисует предметы крупнее их следа (владелец, 2026-08-04)
            if float(getattr(pl, 'elev_cm', 0.0)) > 1.0 or role in FLOOR or role in SOFT:
                continue
            if role not in KEY_FLOOR:              # только ключевая мебель, без мелочи
                continue
            xs_f, ys_f = _fp(pl, pl.item).exterior.coords.xy
            pts = [to_px(x, y) for x, y in zip(xs_f, ys_f)]
            if any(q is None for q in pts):
                continue
            dr.line(pts + [pts[0]], fill=(70, 70, 70, 190), width=3)
        pano = np.asarray(img_fp)

    img = Image.fromarray(pano)
    dst = f'{prefix}-pasted.jpg'
    img.save(dst, quality=93)
    Image.fromarray(np.clip(paint, 0, 255).astype(np.uint8)).save(f'{prefix}-painted.png')
    json.dump({'ids': {str(k): v for k, v in id_map.items()}, 'pasted': done_roles,
               'volumes': volumes, 'angled': angled, 'meshed': meshed},
              open(f'{prefix}-paint.json', 'w'), ensure_ascii=False, indent=1)
    refs = []
    for role in done_roles:
        try:
            refs.append(product(n, role)[1])
        except KeyError:
            pass
    steps.log(prefix, 'Ставим фотографии товаров на их места',
              params={'товаров вклеено': len(done_roles), 'предметы': done_roles,
                      'на нейросетевой проход (сильный ракурс)': angled,
                      'генераций': 0},
              inputs=[f'{prefix}-empty-clay.png'] + refs[:8], outputs=[dst],
              note='Вырезка товара ставится на пол лицом к камере, размер и место — из плана. '
                   'Это математика, не генерация: узнаваемость стопроцентная.')
    print(f'{dst}  (закрашено {total} px, генераций 0)'
          + (f'; на нейросетевой проход: {", ".join(angled)}' if angled else ''))
    json.dump(angled, open(f'{prefix}-angled.json', 'w'), ensure_ascii=False)
    if '--realism' in sys.argv:
        # доводка поверх ТОЧНОЙ геометрии: низкая сила — структура не уезжает
        from viz_base import fal_key, fal_run, uri_from_image
        img = Image.fromarray(pano)
        res = fal_run('fal-ai/fast-sdxl/image-to-image', {
            'prompt': ('Photorealistic interior photo of a living room, natural daylight, soft '
                       'shadows, matte walls, wooden floor. Keep every object exactly where it is.'),
            'negative_prompt': 'extra furniture, moved furniture, distorted perspective, text',
            'image_url': uri_from_image(img),
            'strength': float(os.environ.get('REALISM_STRENGTH', 0.35)),
            'num_inference_steps': 30, 'guidance_scale': 6.0,
            'image_size': {'width': img.width, 'height': img.height},
            'preserve_aspect_ratio': True, 'enable_safety_checker': False,
            'seed': int(os.environ.get('VIZ_SEED', 4242)),
        }, fal_key())
        url = (res.get('images') or [{}])[0].get('url')
        if url:
            import urllib.request as _u
            out = Image.open(io.BytesIO(_u.urlopen(url, timeout=240).read())).convert('RGB')
            out.resize(img.size).save(f'{prefix}-final.jpg', quality=93)
            steps.log(prefix, 'Доводим до фотореализма', model='fal-ai/fast-sdxl/image-to-image',
                      prompt='Photorealistic interior photo…',
                      params={'сила': os.environ.get('REALISM_STRENGTH', 0.35)},
                      inputs=[f'{prefix}-pasted.jpg'], outputs=[f'{prefix}-final.jpg'],
                      note='Открытый вопрос: без управления глубиной на большой силе модель '
                           'начинает пересочинять комнату.')
            print(f'{prefix}-final.jpg  (реализм поверх точной геометрии)')
        return
    if '--finish' in sys.argv:
        # Доводка ТОЛЬКО по кайме вокруг предметов: модель получает маску-полоску, поэтому
        # физически не может ни перекрасить товар, ни дорисовать шкаф на пустой стене.
        from scipy import ndimage
        from viz_objects import edit_gpt_raw
        obj = ids > 0
        band = ndimage.binary_dilation(obj, iterations=26) & ~ndimage.binary_erosion(obj, iterations=5)
        img = Image.fromarray(pano)
        pr = ('Photo of a living room where furniture was composited in. Blend it into the scene: '
              'add soft contact shadows on the floor under each piece, soften the pasted outlines, '
              'match the room lighting. Do not change the furniture itself and do not add anything.')
        edited = edit_gpt_raw([img.resize((1536, 1024))], pr, size='1536x1024',
                              mask=Image.fromarray((band * 255).astype(np.uint8)).resize((1536, 1024)))
        edited.resize(img.size).save(f'{prefix}-final.jpg', quality=93)
        print(f'{prefix}-final.jpg  (доводка по кайме, 1 вызов)')
        return
    if '--gpt-frames' in sys.argv:
        roles = [r for _, r in id_map.items() if r not in SKIP and r in by]
        sheet, names = ref_sheet(n, roles)
        from pano_views import crop_view
        meta = json.load(open(f'{prefix}-frame.json'))
        for yaw, name in ((-45.0, 'left'), (0.0, 'center'), (45.0, 'right')):
            view = crop_view(pano, meta['camera']['fov'], yaw, 65.0, (1536, 1024))
            out = harmonize_gpt(view, sheet, names)
            out.save(f'{prefix}-{name}-gpt.jpg', quality=93)
            print(f'{prefix}-{name}-gpt.jpg  (кадр + лист референсов, 1 вызов)')
        sheet.save(f'{prefix}-refsheet.jpg', quality=90)
        return
    if '--harmonize' in sys.argv:
        out = harmonize(img)
        dst2 = f'{prefix}-final.jpg'
        out.save(dst2, quality=93)
        print(f'{dst2}  (согласование: 1 вызов {HARMONIZE})')


if __name__ == '__main__':
    main()
