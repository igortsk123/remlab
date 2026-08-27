"""Компилятор сцены: управляющие карты из НАШЕЙ геометрии (Ф1 плана viz-scene-compiler).

Почему без Blender: сцена — это полигон комнаты и прямоугольные параллелепипеды. Для них глубина
и маски объектов считаются аналитически (проекция + сортировка по дальности) за миллисекунды на
CPU, детерминированно и без двух гигабайт зависимостей. Blender понадобится только если для вида
сверху захотим честные тени и материалы.

Выдаёт на камеру: карту глубины (метрическую), маску объектов (свой id на предмет), семантику,
нейтральный clay-превью и `frame.json` со списком ВИДИМЫХ предметов и долей их видимости.
Именно этот список уходит в промпт — вместо рассуждений модели о том, что попадает в кадр.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field

import numpy as np

from .geometry import footprint
from .models import Item, Placement, Room

SEMANTIC = {"floor": 1, "wall": 2, "ceiling": 3, "window": 4, "door": 5, "furniture": 6}


@dataclass
class Camera:
    """Камера в мировых координатах комнаты (см). eye/target — точки, fov_deg — по горизонтали."""

    name: str
    eye: tuple[float, float, float]
    target: tuple[float, float, float]
    fov_deg: float = 60.0
    ortho: bool = False
    cyl: bool = False          # цилиндрическая панорама: широкий обзор без «рыбьего глаза»
    ortho_width_cm: float = 0.0
    # размер кратен 64 и в пределах бюджета SDXL: иначе генератор округляет сам и кадр перестаёт
    # совпадать по пропорциям с картой глубины (2026-08-04)
    width: int = 1344
    height: int = 896
    vfov_deg: float = 55.0     # вертикальный угол — только для панорамы
    shift_y: float = 0.0       # сдвиг объектива, доля высоты кадра: архитектурная норма —
                               # НЕ наклонять камеру (вертикали сходятся), а сдвигать кадр

    def basis(self):
        ex, ey, ez = self.eye
        tx, ty, tz = self.target
        fwd = np.array([tx - ex, ty - ey, tz - ez], float)
        fwd /= np.linalg.norm(fwd) or 1.0
        up = np.array([0.0, 1.0, 0.0])
        # right = up × fwd, а не fwd × up: во втором варианте кадр выходил ЗЕРКАЛЬНЫМ плану
        # (стоя у ТВ лицом на север, восток должен быть справа) — поймано 2026-08-04
        right = np.cross(up, fwd)
        if np.linalg.norm(right) < 1e-6:
            right = np.array([1.0, 0.0, 0.0])
        right /= np.linalg.norm(right)
        true_up = np.cross(fwd, right)
        return np.array([ex, ey, ez], float), fwd, right, true_up


def cameras_for(room: Room, placements: list[Placement]) -> list[Camera]:
    """Камеры считаются ИЗ ПЛАНА: вид на зону отдыха, вид на ТВ-зону, вид сверху.

    Раньше камера ставилась вручную «у нижнего края», из-за чего ТВ оказывался за спиной и модель
    вытаскивала его в кадр (урок 56).
    """
    by = {p.role: p for p in placements}
    sofa, tv = by.get("диван"), by.get("тв-тумба")
    W, D, H = room.width_cm, room.depth_cm, 270.0
    eye_h = 135.0
    cams: list[Camera] = []
    if sofa is not None and tv is not None:
        sx, sy = sofa.x, sofa.y
        tx, ty = tv.x, tv.y
        # A: стоим у ТВ, смотрим на диван; B: стоим за диваном, смотрим на ТВ
        for name, a, b, anchor in (("A", (tx, ty), (sx, sy), tv), ("B", (sx, sy), (tx, ty), sofa)):
            dx, dy = b[0] - a[0], b[1] - a[1]
            n = math.hypot(dx, dy) or 1.0
            # встаём ПЕРЕД предметом, за которым стоим (за его переднюю грань + 25 см), иначе
            # телевизор на стене оказывается в 15 см от объектива и закрывает весь кадр
            it_a = anchor.item
            if it_a is None:
                half = 30.0
            else:                       # берём габарит ВДОЛЬ взгляда, а не наибольший:
                rot_a = int(round(anchor.rot)) % 180      # иначе камера уезжает за столик
                half = float(it_a.d_cm if rot_a == 0 else it_a.w_cm) / 2
            ex, ey = a[0] + dx / n * (half + 25.0), a[1] + dy / n * (half + 25.0)
            ex = min(max(ex, 25.0), W - 25.0)
            ey = min(max(ey, 25.0), D - 25.0)
            # 75° — как штатный интерьерный ширик: при 60° пол ближе 2,5 м не попадал в кадр
            # и комната читалась теснее, чем она есть (замечание владельца 2026-08-04)
            cams.append(Camera(name, (ex, eye_h, ey), (b[0], eye_h * 0.8, b[1]), fov_deg=75.0))
    else:
        cams.append(Camera("A", (W / 2, eye_h, -60.0), (W / 2, eye_h * 0.75, D / 2)))
    # вид сверху: кадр по пропорциям комнаты, иначе при 1536×1024 по вертикали влезает лишь
    # ~330 см и предметы у дальней/ближней стены выпадают из кадра (поймано на сете 21)
    def px64(v: float) -> int:
        return max(512, min(1280, int(round(v / 64) * 64)))

    long_px = 1216
    t_w, t_h = (long_px, px64(long_px * D / W)) if W >= D else (px64(long_px * W / D), long_px)
    # C1/C2: два кадра из противоположных углов — профессиональный стандарт интерьерной съёмки
    # (объектив 24–35 мм, высота 1,5–1,7 м, двухточечная перспектива). Панорама остаётся
    # служебной: архитектор говорит, что человек так пространство не воспринимает (2026-08-04).
    eye_c, inset = 155.0, 45.0
    corners = [(inset, inset), (W - inset, inset), (W - inset, D - inset), (inset, D - inset)]

    # КАМЕРА НЕ СТОИТ ВНУТРИ МЕБЕЛИ. Угловой диван занимает угол комнаты целиком, и точка съёмки
    # оказывалась внутри него — кадр переставал совпадать с планом (владелец, 2026-08-05). Такой
    # угол просто ВЫБЫВАЕТ из выбора: сдвигать камеру внутрь комнаты нельзя, иначе разваливается
    # диагональ и второй вид приходит пустым.
    def _obstacles():
        from .geometry import footprint
        out = []
        for q in placements:
            if q.item is None or float(getattr(q, 'elev_cm', 0.0)) > 1.0:
                continue
            try:
                out.append(footprint(q, q.item).buffer(20))
            except Exception:  # noqa: BLE001 — предмет без габаритов камере не мешает
                pass
        return out

    _OBST = _obstacles()

    def _free(cx: float, cy: float) -> bool:
        from shapely.geometry import Point
        pt = Point(cx, cy)
        return not any(o.contains(pt) for o in _OBST)

    def _corner_spot(cx: float, cy: float) -> tuple[float, float]:
        """Точка съёмки в этом углу, свободная от мебели.

        Угловой диван или кашпо занимают сам угол — тогда отходим ВДОЛЬ СТЕНЫ, оставаясь в
        углу комнаты. Сдвигать камеру внутрь комнаты нельзя: разваливается диагональ и второй
        вид приходит пустым (проверено, владелец 2026-08-05).
        """
        if _free(cx, cy):
            return cx, cy
        dx = 1.0 if cx < W / 2 else -1.0
        dy = 1.0 if cy < D / 2 else -1.0
        for step in range(1, 22):
            for px, py in ((cx + dx * step * 20.0, cy), (cx, cy + dy * step * 20.0)):
                if inset <= px <= W - inset and inset <= py <= D - inset and _free(px, py):
                    return px, py
        return cx, cy

    corners = [_corner_spot(cx, cy) for cx, cy in corners]

    # Взгляд — ПО ДИАГОНАЛИ, из угла в угол: так в кадр попадают две стены и вся комната.
    # Угол объектива считаем под конкретную комнату: берём ровно столько, чтобы перекрыть
    # её целиком, и не шире 84° (≈20 мм) — за этим пределом растяжение по краям заметно глазу.
    FOV_MIN, FOV_MAX = 70.0, 84.0

    def fov_for(cx: float, cy: float, tx: float, ty: float) -> float:
        base = math.atan2(ty - cy, tx - cx)
        worst = 0.0
        for px, py in ((0, 0), (W, 0), (W, D), (0, D)):
            a = math.atan2(py - cy, px - cx) - base
            a = (a + math.pi) % (2 * math.pi) - math.pi
            worst = max(worst, abs(a))
        return min(FOV_MAX, max(FOV_MIN, math.degrees(worst) * 2 + 4))

    def probe(ci: int) -> tuple[int, Camera, set]:
        """Сколько предметов реально попадает в кадр из этого угла (быстрый z-буфер 336×224)."""
        cx, cy = corners[ci]
        tx, ty = W - cx, D - cy                # противоположный угол — диагональ комнаты
        fov = fov_for(cx, cy, tx, ty)
        cam = Camera(f"C{ci}", (cx, eye_c, cy), (tx, eye_c, ty),
                     fov_deg=fov, shift_y=-0.10, width=1344, height=896)
        small = Camera(cam.name, cam.eye, cam.target, fov_deg=cam.fov_deg,
                       shift_y=cam.shift_y, width=336, height=224)
        out = compile_scene(room, placements, small)
        return len(out["visible"]), cam, set(out["visible"])

    seen = {ci: probe(ci) for ci in range(4)}
    # Точки съёмки ВСЕГДА диагонально противоположны: так два кадра показывают разные стены и
    # вместе дают всю комнату. Две камеры у одной стены дублируют друг друга (владелец, 2026-08-04).
    # Обе точки диагональны, но саму диагональ выбираем по СЛАБОМУ кадру: иначе второй вид
    # оказывается почти пустым и непонятным (владелец, 2026-08-04).
    def pair_score(d):
        a, b = len(seen[d[0]][2]), len(seen[d[1]][2])
        return (min(a, b), a + b)

    first, second = max([(0, 2), (1, 3)], key=pair_score)
    if len(seen[second][2]) > len(seen[first][2]):
        first, second = second, first
    # Обе точки — строго в углах, по диагонали. Камеру НЕ подвигаем под мебель: честный обзор
    # комнаты с двух разных углов, что видно с места — то и в кадре (владелец, 2026-08-04).
    for k, ci in enumerate((first, second)):
        cam = seen[ci][1]
        cam.name = f"C{k + 1}"
        cams.append(cam)

    # P: панорама «осмотреться от двери» — одна широкая картинка вместо трёх склеенных, чтобы
    # свет и материалы не разъезжались между кадрами (просьба владельца 2026-08-04)
    door = next((o for o in room.openings if o.kind in ("door", "balcony")), None)
    if door is not None:
        cx, cy = _wall_point(room, door.wall, door.offset_cm + door.width_cm / 2, inset=55.0)
    else:
        cx, cy = W / 2, 40.0
    # высота 1024 — родное разрешение SDXL: на 768 кадр выходил мыльным (владелец, 2026-08-04).
    # Вертикальный угол считаем из горизонтального, чтобы картинку не сплющивало по вертикали.
    p_w, p_h, p_fov = 2048, 1024, 140.0
    fv = p_w / math.radians(p_fov)
    cams.append(Camera("P", (cx, 160.0, cy), (W / 2, 120.0, D / 2), fov_deg=p_fov, cyl=True,
                       vfov_deg=math.degrees(2 * math.atan((p_h / 2) / fv)),
                       width=p_w, height=p_h))
    cams.append(Camera("T", (W / 2, max(W, D) * 1.15, D / 2), (W / 2, 0.0, D / 2),
                       ortho=True, ortho_width_cm=W * 1.08, width=t_w, height=t_h))
    return cams


def _wall_point(room: Room, wall: str, along_cm: float, inset: float) -> tuple[float, float]:
    """Точка у стены, сдвинутая внутрь комнаты на inset — куда встать «в дверях»."""
    W, D = room.width_cm, room.depth_cm
    return {"south": (along_cm, inset), "north": (along_cm, D - inset),
            "west": (inset, along_cm), "east": (W - inset, along_cm)}[wall]


def _box_corners(p: Placement, it: Item) -> np.ndarray:
    """8 углов коробки предмета в мировых координатах (x, height, y-глубина)."""
    poly = footprint(p, it)
    xs, ys = poly.exterior.coords.xy
    pts = list(zip(list(xs)[:-1], list(ys)[:-1]))
    h = float(it.h_cm or 60.0)
    return np.array([[x, hh, y] for (x, y) in pts for hh in (0.0, h)], float)


# Прокси-формы ролей в ДОЛЯХ габарита: (u0,u1 — по ширине, v0,v1 — по глубине от лица к спинке,
# h0,h1 — по высоте). Голая коробка на карте глубины читается как тумба — модель так её и рисует
# (поймано 2026-08-04 на сете 21: диван вышел белым комодом). Форма ставит смысл в саму геометрию.
_SEAT = [(0.0, 1.0, 0.0, 0.80, 0.0, 0.42),          # сиденье
         (0.0, 1.0, 0.80, 1.0, 0.0, 1.0),           # спинка
         (0.0, 0.11, 0.0, 0.80, 0.0, 0.62),         # подлокотники
         (0.89, 1.0, 0.0, 0.80, 0.0, 0.62)]
_TABLE = [(0.0, 1.0, 0.0, 1.0, 0.86, 1.0),          # столешница
          (0.04, 0.14, 0.06, 0.20, 0.0, 0.86),      # ножки
          (0.86, 0.96, 0.06, 0.20, 0.0, 0.86),
          (0.04, 0.14, 0.80, 0.94, 0.0, 0.86),
          (0.86, 0.96, 0.80, 0.94, 0.0, 0.86)]
_CASE = [(0.0, 1.0, 0.0, 1.0, 0.07, 1.0),           # корпус на цоколе
         (0.03, 0.13, 0.05, 0.15, 0.0, 0.07),
         (0.87, 0.97, 0.05, 0.15, 0.0, 0.07)]
_SHELF = ([(0.0, 0.05, 0.0, 1.0, 0.0, 1.0), (0.95, 1.0, 0.0, 1.0, 0.0, 1.0),   # боковины
           (0.0, 1.0, 0.88, 1.0, 0.0, 1.0)]                                     # задняя стенка
          + [(0.0, 1.0, 0.0, 1.0, k - 0.02, k + 0.02)                           # полки
             for k in (0.02, 0.26, 0.5, 0.74, 0.98)])
_PLANT = [(0.25, 0.75, 0.25, 0.75, 0.0, 0.45),     # горшок
          (0.43, 0.57, 0.43, 0.57, 0.45, 0.62),    # ствол
          (0.12, 0.88, 0.12, 0.88, 0.62, 0.86),    # крона ступенями — иначе слитная коробка
          (0.3, 0.7, 0.3, 0.7, 0.86, 1.0)]         # читается как пуф (поймано 2026-08-04)
_BED = [(0.0, 1.0, 0.0, 0.88, 0.0, 0.55), (0.0, 1.0, 0.88, 1.0, 0.0, 1.0)]
_PANEL = [(0.0, 1.0, 0.35, 0.65, 0.0, 1.0)]
_RUG = [(0.0, 1.0, 0.0, 1.0, 0.0, 0.02)]           # ковёр — почти плоский, но контур виден
_LAMP = [(0.42, 0.58, 0.42, 0.58, 0.0, 0.55),      # подвес
         (0.0, 1.0, 0.0, 1.0, 0.55, 1.0)]          # плафон

PROXY: dict[str, list[tuple[float, ...]]] = {
    "диван": _SEAT, "кресло": _SEAT, "кресло-качалка": _SEAT,
    "столик": _TABLE, "журнальный столик": _TABLE, "стол": _TABLE, "обеденный стол": _TABLE,
    "тумба": _CASE, "тв-тумба": _CASE, "комод": _CASE, "шкаф": _CASE, "стенка": _CASE,
    "стеллаж": _SHELF, "полка": _SHELF,
    "кашпо": _PLANT, "растение": _PLANT,
    "кровать": _BED, "тв": _PANEL, "телевизор": _PANEL,
    "ковёр": _RUG, "ковер": _RUG, "люстра": _LAMP,
}


def proxy_parts(p: Placement, it: Item) -> list[tuple[float, ...]]:
    """Части прокси-формы в мировых координатах: (x0, x1, h_lo, h_hi, y0, y1).

    Доли раскладываются по габариту с учётом поворота: v=0 — лицевая сторона предмета.
    """
    c = _box_corners(p, it)
    X0, X1 = float(c[:, 0].min()), float(c[:, 0].max())
    Z0, Z1 = float(c[:, 2].min()), float(c[:, 2].max())
    h = float(c[:, 1].max())
    base = float(p.elev_cm)                   # ТВ на стене, люстра под потолком
    parts = [] if it.corner else PROXY.get(p.role, [])
    if not parts:
        return [(X0, X1, base, base + h, Z0, Z1)]
    rot = int(round(p.rot)) % 360
    out = []
    for u0, u1, v0, v1, h0, h1 in parts:
        if rot in (0, 180):                       # ширина по x, глубина по y
            x0, x1 = X0 + (X1 - X0) * u0, X0 + (X1 - X0) * u1
            a, b = (Z1, Z0) if rot == 0 else (Z0, Z1)      # v=0 — лицо предмета
            z0, z1 = a + (b - a) * v0, a + (b - a) * v1
        else:                                     # ширина по y, глубина по x
            z0, z1 = Z0 + (Z1 - Z0) * u0, Z0 + (Z1 - Z0) * u1
            a, b = (X1, X0) if rot == 90 else (X0, X1)
            x0, x1 = a + (b - a) * v0, a + (b - a) * v1
        out.append((min(x0, x1), max(x0, x1), base + h * h0, base + h * h1,
                    min(z0, z1), max(z0, z1)))
    return out


def _project(cam: Camera, pts: np.ndarray):
    eye, fwd, right, up = cam.basis()
    rel = pts - eye
    z = rel @ fwd
    if cam.ortho:
        scale = cam.width / (cam.ortho_width_cm or 1.0)
        u = cam.width / 2 + (rel @ right) * scale
        v = cam.height / 2 - (rel @ up) * scale
        return u, v, z
    if cam.cyl:
        # разворачиваем обзор по кругу: колонка кадра = угол, строка = наклон. Прямой кадр шире
        # ~75° уже «пухнет» по краям, а панорама остаётся честной на все 150–180°
        ang = np.arctan2(rel @ right, rel @ fwd)
        horiz = np.hypot(rel @ right, rel @ fwd)
        fv = (cam.height / 2) / math.tan(math.radians(cam.vfov_deg) / 2)
        u = cam.width / 2 + ang / math.radians(cam.fov_deg) * cam.width
        v = cam.height / 2 - fv * (rel @ up) / np.where(horiz <= 1e-3, 1e-3, horiz)
        return u, v, horiz
    f = (cam.width / 2) / math.tan(math.radians(cam.fov_deg) / 2)
    zz = np.where(z <= 1e-3, 1e-3, z)
    u = cam.width / 2 + f * (rel @ right) / zz
    v = cam.height / 2 - f * (rel @ up) / zz + cam.shift_y * cam.height
    return u, v, z


def compile_scene(room: Room, placements: list[Placement], cam: Camera) -> dict:
    """Карты для одной камеры: depth (см), instance-id, semantic + список видимого."""
    Wp, Hp = cam.width, cam.height
    depth = np.full((Hp, Wp), np.inf, np.float32)
    inst = np.zeros((Hp, Wp), np.int32)
    sem = np.zeros((Hp, Wp), np.uint8)

    eye, fwd, right, up = cam.basis()
    focal = (Wp / 2) / math.tan(math.radians(cam.fov_deg) / 2)
    ortho_scale = Wp / (cam.ortho_width_cm or 1.0)

    def raster_flat(corners3d: np.ndarray, inst_id: int, sem_id: int):
        """Растеризация грани с ПОПИКСЕЛЬНОЙ глубиной (луч × плоскость).

        Раньше глубина бралась одним числом на грань — пол со средней глубиной «накрывал» мебель,
        и ни один предмет не попадал в маску.
        """
        u, v, z = _project(cam, corners3d)
        if np.all(z <= 1e-3):
            return
        x0, x1 = int(max(0, np.floor(u.min()))), int(min(Wp - 1, np.ceil(u.max())))
        y0, y1 = int(max(0, np.floor(v.min()))), int(min(Hp - 1, np.ceil(v.max())))
        if x1 <= x0 or y1 <= y0:
            return
        # плоскость грани в мире: n·X = d
        p0, p1, p2 = corners3d[0], corners3d[1], corners3d[2]
        n = np.cross(p1 - p0, p2 - p0)
        nn = np.linalg.norm(n)
        if nn < 1e-9:
            return
        n = n / nn
        d = float(n @ p0)
        ys, xs = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        if cam.ortho:
            origin = (eye[None, None, :]
                      + right[None, None, :] * ((xs - Wp / 2) / ortho_scale)[..., None]
                      + up[None, None, :] * ((Hp / 2 - ys) / ortho_scale)[..., None])
            denom = float(n @ fwd)
            if abs(denom) < 1e-9:
                return
            t = (d - origin @ n) / denom
            zpix = t
        elif cam.cyl:
            ang = (xs - Wp / 2) / Wp * math.radians(cam.fov_deg)
            fv = (Hp / 2) / math.tan(math.radians(cam.vfov_deg) / 2)
            dirs = (fwd[None, None, :] * np.cos(ang)[..., None]
                    + right[None, None, :] * np.sin(ang)[..., None]
                    + up[None, None, :] * ((Hp / 2 - ys) / fv)[..., None])
            denom = dirs @ n
            with np.errstate(divide="ignore", invalid="ignore"):
                t = (d - float(n @ eye)) / denom
            zpix = t          # горизонтальная часть луча единичная → t и есть расстояние
        else:
            dirs = (fwd[None, None, :] * focal
                    + right[None, None, :] * (xs - Wp / 2)[..., None]
                    + up[None, None, :] * (Hp / 2 + cam.shift_y * Hp - ys)[..., None])
            denom = dirs @ n
            with np.errstate(divide="ignore", invalid="ignore"):
                t = (d - float(n @ eye)) / denom
            zpix = t * (dirs @ fwd)
        valid = np.isfinite(zpix) & (zpix > 1e-3)
        inside = _point_in_convex(xs, ys, u, v) & valid
        sub = depth[y0:y1 + 1, x0:x1 + 1]
        upd = inside & (zpix < sub)
        sub[upd] = zpix[upd]
        inst[y0:y1 + 1, x0:x1 + 1][upd] = inst_id
        sem[y0:y1 + 1, x0:x1 + 1][upd] = sem_id

    def raster_quad(corners3d: np.ndarray, inst_id: int, sem_id: int, sub: int = 0):
        """В панораме прямая линия становится дугой, и выпуклая оболочка четырёх углов не
        покрывает истинную область — по краям кадра оставались чёрные клинья. Поэтому крупные
        грани режем на сетку мелких (2026-08-04)."""
        n_sub = sub or (10 if cam.cyl else 1)
        if n_sub <= 1:
            raster_flat(corners3d, inst_id, sem_id)
            return
        a, b, c, d_ = corners3d[0], corners3d[1], corners3d[2], corners3d[3]
        for i in range(n_sub):
            t0, t1 = i / n_sub, (i + 1) / n_sub
            for j in range(n_sub):
                s0, s1 = j / n_sub, (j + 1) / n_sub

                def pt(t, s):
                    return (a * (1 - t) * (1 - s) + b * t * (1 - s)
                            + c * t * s + d_ * (1 - t) * s)

                raster_flat(np.array([pt(t0, s0), pt(t1, s0), pt(t1, s1), pt(t0, s1)]),
                            inst_id, sem_id)

    def _point_in_convex(xs, ys, pu, pv):
        hull = _convex_hull(np.stack([pu, pv], 1))
        res = np.ones(xs.shape, bool)
        n = len(hull)
        for i in range(n):
            ax, ay = hull[i]
            bx, by = hull[(i + 1) % n]
            side = (bx - ax) * (ys - ay) - (by - ay) * (xs - ax)
            res &= side >= -1e-6
        return res

    def _convex_hull(pts: np.ndarray) -> np.ndarray:
        pts = np.unique(pts, axis=0)
        if len(pts) <= 3:
            return pts
        order = np.lexsort((pts[:, 1], pts[:, 0]))
        pts = pts[order]

        def cross2(a, b):        # numpy убрал 2D-вариант np.cross — считаем сами
            return a[0] * b[1] - a[1] * b[0]

        def half(seq):
            out = []
            for p in seq:
                while len(out) >= 2 and cross2(out[-1] - out[-2], p - out[-1]) <= 0:
                    out.pop()
                out.append(p)
            return out

        return np.array(half(pts)[:-1] + half(pts[::-1])[:-1])

    # комната: пол, стены, потолок
    W, D = room.width_cm, room.depth_cm
    H = 120.0 if cam.ortho else 270.0     # сверху стены подрезаны, чтобы видеть комнату
    raster_quad(np.array([[0, 0, 0], [W, 0, 0], [W, 0, D], [0, 0, D]], float), 0, SEMANTIC["floor"])
    for quad in (
        [[0, 0, D], [W, 0, D], [W, H, D], [0, H, D]],
        [[0, 0, 0], [0, 0, D], [0, H, D], [0, H, 0]],
        [[W, 0, 0], [W, 0, D], [W, H, D], [W, H, 0]],
        [[0, 0, 0], [W, 0, 0], [W, H, 0], [0, H, 0]],
    ):
        raster_quad(np.array(quad, float), 0, SEMANTIC["wall"])
    if not cam.ortho:      # вид сверху — «кукольный домик»: без потолка
        raster_quad(np.array([[0, H, 0], [W, H, 0], [W, H, D], [0, H, D]], float), 0,
                    SEMANTIC["ceiling"])
    for op in room.openings:
        sem_id = SEMANTIC["window"] if op.kind == "window" else SEMANTIC["door"]
        # ПОДОКОННИК — ИЗ ПРОЁМА (27.08): рисовали окно фиксированно 90–210 см, а в промпт уходила
        # своя высота подоконника — макет и текст противоречили друг другу.
        hi, lo = ((210.0, float(getattr(op, "sill_cm", 0) or 90.0)) if op.kind == "window"
                  else (205.0, 0.0))
        o0, o1 = op.offset_cm, op.offset_cm + op.width_cm
        # Проём рисуем НА САНТИМЕТР ВНУТРЬ комнаты, а не вглубь стены: утопленный проём
        # проигрывал стене по глубине и просто не появлялся в кадре — окно и дверь пропадали
        # (владелец, 2026-08-04).
        r = 1.0
        quad = {
            "south": [[o0, lo, r], [o1, lo, r], [o1, hi, r], [o0, hi, r]],
            "north": [[o0, lo, D - r], [o1, lo, D - r], [o1, hi, D - r], [o0, hi, D - r]],
            "west": [[r, lo, o0], [r, lo, o1], [r, hi, o1], [r, hi, o0]],
            "east": [[W - r, lo, o0], [W - r, lo, o1], [W - r, hi, o1], [W - r, hi, o0]],
        }[op.wall]
        raster_quad(np.array(quad, float), 0, sem_id)

    # предметы: прокси-форма роли (не голая коробка), у каждой части — 5 граней
    ids: dict[int, str] = {}
    for i, p in enumerate(placements, start=1):
        it = p.item
        if it is None:
            continue
        ids[i] = p.role
        for x0, x1, ylo, yhi, z0, z1 in proxy_parts(p, it):
            faces = [
                [[x0, ylo, z0], [x1, ylo, z0], [x1, yhi, z0], [x0, yhi, z0]],
                [[x0, ylo, z1], [x1, ylo, z1], [x1, yhi, z1], [x0, yhi, z1]],
                [[x0, ylo, z0], [x0, ylo, z1], [x0, yhi, z1], [x0, yhi, z0]],
                [[x1, ylo, z0], [x1, ylo, z1], [x1, yhi, z1], [x1, yhi, z0]],
                [[x0, yhi, z0], [x1, yhi, z0], [x1, yhi, z1], [x0, yhi, z1]],
                [[x0, ylo, z0], [x1, ylo, z0], [x1, ylo, z1], [x0, ylo, z1]],
            ]
            for f in faces:
                raster_quad(np.array(f, float), i, SEMANTIC["furniture"])

    # Предмет, от которого в кадр попало меньше 15% его собственной проекции, из
    # кадра ИСКЛЮЧАЕТСЯ целиком: тонкая полоска у края не читается ни человеком, ни моделью
    # (правило владельца 2026-08-04). Маска обнуляется, поэтому вклейка и подписи его не увидят.
    min_share = float(os.environ.get("FRAME_MIN_SHARE", 0.15))
    total = {i: int((inst == i).sum()) for i in ids}
    own: dict[int, float] = {}
    for i, p in enumerate(placements, start=1):
        if p.item is None or i not in ids:
            continue
        us, vs = [], []
        for x0, x1, ylo, yhi, z0, z1 in proxy_parts(p, p.item):
            corners = np.array([[X, Y, Z] for X in (x0, x1) for Y in (ylo, yhi) for Z in (z0, z1)],
                               float)
            u, v, z = _project(cam, corners)
            keep = z > 1e-3
            if keep.any():
                us += list(u[keep])
                vs += list(v[keep])
        own[i] = (max(us) - min(us)) * (max(vs) - min(vs)) * 0.6 if len(us) > 1 else 0.0

    dropped = [i for i in ids
               if total[i] <= 400 or (own.get(i, 0) > 1 and total[i] / own[i] < min_share)]
    for i in dropped:
        inst[inst == i] = 0
        total[i] = 0
    visible = {ids[i]: px for i, px in total.items() if px > 400}
    behind = [ids[i] for i in ids if total[i] <= 400]
    return {
        "depth": depth,
        "instances": inst,
        "semantic": sem,
        "ids": ids,
        "visible": visible,
        "behind": behind,
        "camera": {
            "name": cam.name, "eye": cam.eye, "target": cam.target,
            "fov": cam.fov_deg, "ortho": cam.ortho, "size": [cam.width, cam.height],
        },
    }


# Палитра clay-рендера: нейтральные материалы, роль отличается тоном (не «дизайн», а подложка).
_CLAY = {"floor": (196, 174, 148), "wall": (232, 230, 226), "ceiling": (240, 239, 236),
         # проёмы контрастнее: на светлой стене бледное окно не читается (владелец, 2026-08-04)
         "window": (108, 166, 208), "door": (176, 136, 84), "furniture": (176, 176, 172)}


def clay_render(out: dict) -> np.ndarray:
    """Нейтральный превью-рендер из тех же карт: цвет по семантике, свет — по глубине.

    Нужен как ОСНОВА для вида сверху: ортокарта глубины почти плоская, чистый depth-ControlNet
    сигнала не даёт и модель рисует чужую планировку целой квартиры (2026-08-04). Из clay же
    генерация идёт как лёгкая доводка картинки, а не как сочинение с нуля.
    """
    sem, inst, depth = out["semantic"], out["instances"], out["depth"]
    img = np.zeros((*sem.shape, 3), np.float32)
    inv = {v: k for k, v in SEMANTIC.items()}
    for sid, name in inv.items():
        img[sem == sid] = _CLAY[name]
    d = depth.copy()
    fin = np.isfinite(d)
    if fin.any():
        lo, hi = float(d[fin].min()), float(d[fin].max())
        shade = 1.18 - 0.42 * np.clip((d - lo) / max(hi - lo, 1e-6), 0, 1)   # ближе — светлее
        shade[~fin] = 1.0
        img *= shade[..., None]
    # ПРЕДМЕТЫ НЕ ДОЛЖНЫ СЛИВАТЬСЯ (27.08, владелец: «модель должна чётко видеть предметы, как
    # человек»). Случайный разброс тона ±10 % давал соседние объёмы почти одного цвета: стул у
    # стола, столик у дивана читались одним пятном. Теперь тон назначается ПО ГЛУБИНЕ: предметы
    # сортируются от камеры вглубь и получают чередующиеся ступени светлее/темнее, поэтому у
    # любых двух соседей по дальности тон заведомо разный. Отдельную карту глубины в модель не
    # шлём — у gpt-image нет управляющего входа, она уйдёт как ещё один референс (разбор 27.08).
    ids_d = []
    for i in np.unique(inst):
        if i == 0:
            continue
        m = inst == i
        dm = d[m & fin] if fin.any() else np.array([])
        ids_d.append((float(dm.mean()) if dm.size else 1e9, int(i)))
    ids_d.sort()
    steps = (0.74, 1.16, 0.88, 1.04, 0.80, 1.10)
    for k, (_, i) in enumerate(ids_d):
        img[inst == i] *= steps[k % len(steps)]
    # КОНТУР — ТОЛСТЫЙ И ТЁМНЫЙ: тонкая линия в 1 px пропадает при сжатии листа до 1536 px, и
    # границы предметов исчезали именно там, где важнее всего (ножки, спинки, углы).
    edge = np.zeros(inst.shape, bool)
    edge[:, 1:] |= inst[:, 1:] != inst[:, :-1]
    edge[1:, :] |= inst[1:, :] != inst[:-1, :]
    thick = max(1, int(round(min(inst.shape) / 320)))
    grow = edge.copy()
    for _ in range(thick):
        g = np.zeros_like(grow)
        g[:, 1:] |= grow[:, :-1]; g[:, :-1] |= grow[:, 1:]
        g[1:, :] |= grow[:-1, :]; g[:-1, :] |= grow[1:, :]
        grow |= g
    img[grow] *= 0.42
    return np.clip(img, 0, 255).astype(np.uint8)


def save_maps(out: dict, prefix: str) -> dict:
    """Пишет depth16/instances/semantic/frame.json рядом; возвращает пути."""
    from PIL import Image

    depth = out["depth"].copy()
    finite = np.isfinite(depth)
    far = float(depth[finite].max()) if finite.any() else 1.0
    depth[~finite] = far
    d16 = (np.clip(depth / max(far, 1.0), 0, 1) * 65535).astype(np.uint16)
    Image.fromarray(d16).save(f"{prefix}-depth16.png")
    # инстансы — различимыми цветами (для глаз) + сырой id-канал в R
    inst = out["instances"]
    rgb = np.zeros((*inst.shape, 3), np.uint8)
    rng = np.random.default_rng(7)
    for i in np.unique(inst):
        if i == 0:
            continue
        rgb[inst == i] = rng.integers(60, 255, 3)
    rgb[..., 0] = np.where(inst > 0, inst * 8, rgb[..., 0])
    Image.fromarray(rgb).save(f"{prefix}-instances.png")
    Image.fromarray((out["semantic"] * 40).astype(np.uint8)).save(f"{prefix}-semantic.png")
    Image.fromarray(clay_render(out)).save(f"{prefix}-clay.png")
    meta = {k: out[k] for k in ("visible", "behind", "camera")}
    meta["ids"] = {str(k): v for k, v in out["ids"].items()}
    open(f"{prefix}-frame.json", "w").write(json.dumps(meta, ensure_ascii=False, indent=1))
    return {"depth": f"{prefix}-depth16.png", "instances": f"{prefix}-instances.png",
            "semantic": f"{prefix}-semantic.png", "clay": f"{prefix}-clay.png",
            "meta": f"{prefix}-frame.json"}
