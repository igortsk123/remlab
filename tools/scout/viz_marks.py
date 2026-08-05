#!/usr/bin/env python3
"""Разметка кадра номерами (Set-of-Mark) + легенда для модели.

Приём опубликован Microsoft (arXiv 2310.11441): если нанести на картинку номера и контуры
областей, модель начинает понимать, ЧТО и ГДЕ на ней, а не догадываться. Нам это дешевле, чем
авторам статьи: маски у нас точные, из собственной геометрии, сегментация не нужна.

Легенда несёт то, что модель по картинке не выведет: название товара, реальные габариты и
ОТНОШЕНИЕ («плед лежит на диване»). Без этого она честно оставит плед висящим в воздухе.

  ~/venvs/scout/bin/python viz_marks.py 21 --cam C1
"""
import json
import math
import os
import sys

sys.path.insert(0, '/home/pakar/igor/remlab/services/planner-solver')

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import scene_build  # noqa: E402
from planner.scene import Camera, cameras_for, compile_scene  # noqa: E402
from scene_build import SCENE_DIR, load_scene  # noqa: E402
from viz_objects import product  # noqa: E402
from viz_paste import FRONTED  # noqa: E402  (единый список предметов с выраженным фасадом)

FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
SKIP_MARK: set[str] = set()   # ТВ тоже подписываем: он есть всегда, где есть тумба
# Рамку-габарит рисуем ТОЛЬКО у ключевых предметов: у мелочи и текстиля она превращает кадр
# в клетку и мешает модели (владелец, 2026-08-04). Номер при этом получают все.
KEY_BOX = {'диван', 'кресло', 'комод', 'тв-тумба', 'стеллаж', 'шкаф', 'стенка', 'кровать',
           'тумба', 'столик', 'стол', 'обеденный стол', 'пуф', 'тв', 'телевизор'}


WALL_RU = {'north': 'дальней', 'south': 'ближней', 'west': 'левой', 'east': 'правой'}


def axis_of(p, placements, room) -> str:
    """Как лежит ДЛИННАЯ сторона предмета — для вещей без фасада (столик, ковёр, пуф).

    У них нет «лица», но есть вытянутость: столик должен стоять длинной стороной параллельно
    дивану, а не поперёк. Раньше такие предметы вообще не получали ориентации, и модель ставила
    их как придётся (владелец, 2026-08-04).
    """
    import math
    it = p.item
    if it is None:
        return ''
    w, d = float(it.w_cm), float(it.d_cm)
    if max(w, d) < 1e-6 or abs(w - d) / max(w, d) < 0.12:
        return ''                                   # почти квадратный — разворот не важен
    rot = int(round(p.rot)) % 180
    long_along_x = (w >= d) if rot == 0 else (d > w)
    axis = (1.0, 0.0) if long_along_x else (0.0, 1.0)
    anchor = None
    for role in ('диван', 'кровать', 'стенка'):
        q = next((x for x in placements if x.role == role and x.item is not None), None)
        if q is not None:
            anchor = q
            break
    if anchor is not None and anchor is not p:
        aw, ad = float(anchor.item.w_cm), float(anchor.item.d_cm)
        arot = int(round(anchor.rot)) % 180
        a_along_x = (aw >= ad) if arot == 0 else (ad > aw)
        same = (a_along_x == long_along_x)
        rel = 'ПАРАЛЛЕЛЬНО' if same else 'ПОПЕРЁК'
        return f'длинной стороной {rel} {anchor.role}у' if anchor.role == 'диван' else \
               f'длинной стороной {rel} предмету «{anchor.role}»'
    wall = 'левой и правой' if axis == (0.0, 1.0) else 'дальней и ближней'
    return f'длинной стороной вдоль {wall} стены'


def orientation_of(p, placements, room) -> str:
    """Куда предмет повёрнут — считается из геометрии, а не пишется руками.

    Луч из центра предмета по направлению его лица: если упирается в другой предмет — «развёрнут
    к нему», иначе — в стену. Плюс отмечается, если предмет стоит спинкой к стене. Так правило
    работает для ЛЮБОЙ расстановки, а не для одного примера (владелец, 2026-08-04).
    """
    import math

    from planner.geometry import footprint
    from shapely.geometry import LineString
    # Ориентацию имеет смысл описывать только у предметов с выраженным фасадом: у ковра,
    # люстры, пледа и подушек «лица» нет, и фраза «развёрнут к столику» была бы шумом.
    if p.item is None:
        return ''
    if p.role not in FRONTED:
        return axis_of(p, placements, room)        # без фасада — описываем вытянутость
    rot = int(round(p.rot)) % 360
    face = {0: (0.0, 1.0), 90: (1.0, 0.0), 180: (0.0, -1.0), 270: (-1.0, 0.0)}.get(rot)
    if face is None:
        return ''
    reach = 420.0
    ray = LineString([(p.x, p.y), (p.x + face[0] * reach, p.y + face[1] * reach)])
    best, best_d = None, 1e9
    from shapely.geometry import Point
    self_poly = footprint(p, p.item)
    for q in placements:
        if q is p or q.item is None or q.role == p.role:
            continue
        if float(getattr(q, 'elev_cm', 0.0)) > 1.0:
            continue                                   # предмет НА чём-то (ваза, лампа, ТВ)
        poly = footprint(q, q.item)
        if self_poly.contains(Point(q.x, q.y)):
            continue                                   # стоит внутри нашего же следа
        if ray.intersects(poly):
            d = math.hypot(q.x - p.x, q.y - p.y)
            if d < best_d:
                best, best_d = q.role, d
    ANCHORS = {'диван', 'кресло', 'тв-тумба', 'кровать'}
    parts = []
    if best in ANCHORS:
        parts.append(f'фасадом к: {best}')
    else:
        wall = {(0.0, 1.0): 'north', (1.0, 0.0): 'east', (0.0, -1.0): 'south',
                (-1.0, 0.0): 'west'}[face]
        parts.append(f'фасадом в сторону {WALL_RU[wall]} стены')
    back = {(0.0, 1.0): ('south', p.y), (1.0, 0.0): ('west', p.x),
            (0.0, -1.0): ('north', room.depth_cm - p.y),
            (-1.0, 0.0): ('east', room.width_cm - p.x)}[face]
    if back[1] <= float(p.item.d_cm) / 2 + 30:
        parts.append(f'стоит спинкой к {WALL_RU[back[0]]} стене')
    return ', '.join(parts)


def numbering(n: int, cams=('C1', 'C2')) -> dict:
    """Сквозная нумерация предметов НА КОМПЛЕКТ: один и тот же номер во всех видах.

    Раньше номера считались внутри каждого кадра, и диван был №1 в одном виде и №4 в другом —
    модели приходилось давать два разных списка (владелец, 2026-08-04).
    """
    order, seen = [], set()
    for c in cams:
        meta_p = os.path.join(SCENE_DIR, f'scene{n}-{c}-frame.json')
        if not os.path.exists(meta_p):
            continue
        ids = json.load(open(meta_p))['ids']
        for _, role in sorted(ids.items(), key=lambda kv: int(kv[0])):
            if role not in seen:
                seen.add(role)
                order.append(role)
    return {role: i + 1 for i, role in enumerate(order)}


def build(n: int, cam_name: str = 'C1', nums: dict | None = None) -> tuple[str, str, list[dict]]:
    prefix = os.path.join(SCENE_DIR, f'scene{n}-{cam_name}')
    # Подписи всегда строятся по КОЛЛАЖУ, а не по результату генерации: иначе в контроль
    # и на лист уезжает нарисованная картинка (владелец, дважды, 2026-08-04).
    src = f'{prefix}-pasted.jpg'
    img = Image.open(src).convert('RGB')
    W, H = img.size
    ids_img = Image.open(f'{prefix}-instances.png').convert('RGB').resize((W, H), Image.NEAREST)
    ids = np.asarray(ids_img)[..., 0] // 8
    meta = json.load(open(f'{prefix}-frame.json'))
    room, placements = load_scene(n)                # заодно заполняет scene_build.RELATIONS
    rel = dict(scene_build.RELATIONS)
    cam = next(c for c in cameras_for(room, placements) if c.name == cam_name)
    by = {p.role: p for p in placements}
    items = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        'sets3.json')))[n - 1]['items']

    def own_area(role: str) -> float:
        """Площадь предмета в кадре, если бы его ничто не закрывало и не обрезало.

        Считаем честно: рендерим ОДИН этот предмет в уменьшенном кадре и меряем его маску.
        Прежняя грубая оценка по габаритному прямоугольнику врала на подвесных предметах —
        у люстры подвес раздувал прямоугольник, и она вечно числилась «частью» (2026-08-05).
        """
        p = by.get(role)
        if p is None or p.item is None:
            return 0.0
        small = Camera(cam.name, cam.eye, cam.target, fov_deg=cam.fov_deg, ortho=cam.ortho,
                       cyl=cam.cyl, ortho_width_cm=cam.ortho_width_cm, vfov_deg=cam.vfov_deg,
                       shift_y=cam.shift_y, width=336, height=224)
        try:
            out = compile_scene(room, [p], small)
        except Exception:  # noqa: BLE001 — оценка не должна валить сборку
            return 0.0
        px = float((out['instances'] > 0).sum())
        return px * (W * H) / (small.width * small.height)

    objs = ids > 0
    marked = img.copy()
    d = ImageDraw.Draw(marked, 'RGBA')
    nums = nums if nums is not None else numbering(n)
    legend: list[dict] = []
    placed: list[tuple[float, float, int]] = []
    for sid, role in meta['ids'].items():
        if role in SKIP_MARK:
            continue
        # Роли, которых нет в каталоге (телевизор достраивается к тумбе), тоже подписываем:
        # иначе модель не знает, что этот прямоугольник — ТВ (владелец, 2026-08-04).
        spec = items.get(role)
        if spec is None and role not in by:
            continue
        m = ids == int(sid)
        if m.sum() < 400:
            continue
        # Доля видимости: если предмет обрезан краем кадра или закрыт другим, модель должна об
        # этом ЗНАТЬ — иначе она пытается дорисовать целый предмет из фрагмента (владелец,
        # 2026-08-04). Совсем мелкие фрагменты в легенду не попадают вовсе.
        ys_a, xs_a = np.where(m)
        touches_edge = (xs_a.min() <= 1 or xs_a.max() >= W - 2
                        or ys_a.min() <= 1 or ys_a.max() >= H - 2)
        share = float(m.sum()) / max(1.0, (xs_a.max() - xs_a.min() + 1) * (ys_a.max() - ys_a.min() + 1))
        # Доля видимости считается от площади САМОГО предмета: тонкая полоска у края кадра —
        # это не предмет, модели о нём говорить не надо (владелец: «на виде 2 одна подушка, а
        # подписано две», 2026-08-04).
        own = own_area(role)
        share_own = float(m.sum()) / own if own > 0 else 0.0
        big_in_frame = m.sum() / (W * H) >= 0.015      # заметный кусок кадра — оставляем
        if m.sum() / (W * H) < 0.004 or (share_own < 0.15 and not big_in_frame):
            continue
        # «часть» ставим по ДОЛЕ ВИДИМОСТИ, а не по касанию края: у люстры маска доходит до
        # верха кадра из-за подвеса, хотя сам светильник виден целиком (владелец, 2026-08-05)
        seen_txt = ('виден целиком' if share_own >= 0.9 else
                    f'в кадр попадает ТОЛЬКО ЧАСТЬ предмета ({role}) — рисовать именно эту часть, '
                    'не достраивать предмет целиком')
        num = nums.get(role, 0)
        if not num:
            continue
        ys, xs = np.where(m)
        cx = float(xs.mean())
        top = float(ys.min())
        # Номер ставим НАД предметом, а не по центру: на мелких (лампа, ваза) кружок закрывал
        # сам товар, и модель не видела, о чём речь (замечание владельца 2026-08-04).
        r = int(min(26, max(13, (xs.max() - xs.min()) / 6)))
        def ok_at(px, py):
            """Место годится, если номер не закрывает товар, не липнет к другому номеру и
            стоит от него ОТДЕЛЬНО ПО ГОРИЗОНТАЛИ — иначе два номера читаются как один
            (владелец: «4 и 10 сливаются»)."""
            if py - r < 2 or px - r < 2 or px + r > W - 2:
                return False
            box = objs[max(0, int(py - r)):int(py + r), max(0, int(px - r)):int(px + r)]
            if box.size and box.mean() > 0.02:
                return False
            for ux, uy, ur in placed:
                if abs(px - ux) < r + ur + 12 and abs(py - uy) < (r + ur) * 3.2:
                    return False                       # столбиком друг под другом — запрещено
                if (px - ux) ** 2 + (py - uy) ** 2 < (r + ur + 8) ** 2:
                    return False
            return True

        mx, my = cx, top - r - 10
        if not ok_at(mx, my):
            found = False
            for k in range(1, 9):                      # сначала вбок, потом чуть выше
                for dx in (-1, 1):
                    for dy in (0, -1.4, -2.8):
                        px = cx + dx * k * (r * 1.9)
                        py = top - r - 10 + dy * r
                        if ok_at(px, py):
                            mx, my, found = px, py, True
                            break
                    if found:
                        break
                if found:
                    break
        my = max(r + 4, my)
        mx = min(max(r + 4, mx), W - r - 4)
        placed.append((mx, my, r))
        # Рамка по габаритам предмета в кадре: она задаёт РАЗМЕР. Контур следа на полу отвечает
        # за разворот, рамка — за то, чтобы предмет не вырос (владелец, 2026-08-04).
        # Выноска ведёт В САМ ПРЕДМЕТ, а не к его верхней кромке: иначе у соседних объектов
        # (подушки, ваза с комодом) непонятно, к кому относится номер (владелец, 2026-08-04).
        cy_m, cx_m = float(ys.mean()), float(xs.mean())
        near = np.argmin((ys - cy_m) ** 2 + (xs - cx_m) ** 2)   # точка внутри маски
        ax, ay = float(xs[near]), float(ys[near])
        d.line([mx, my + r, ax, ay], fill=(200, 30, 30, 210), width=2)
        d.ellipse([ax - 6, ay - 6, ax + 6, ay + 6], fill=(200, 30, 30, 235),
                  outline=(255, 255, 255, 220), width=2)
        d.ellipse([mx - r, my - r, mx + r, my + r], fill=(200, 30, 30, 235),
                  outline=(255, 255, 255, 255), width=3)
        fnt = ImageFont.truetype(FONT, int(r * 1.35))
        d.text((mx, my), str(num), fill=(255, 255, 255), font=fnt, anchor='mm')
        it = spec if spec is not None else {
            'name': 'телевизор (подбирается моделью по размеру тумбы)',
            'w': by[role].item.w_cm, 'd': by[role].item.d_cm, 'h': by[role].item.h_cm}
        try:
            _, photo = product(n, role)
        except KeyError:
            photo = ''
        # Материал и ЦВЕТ пишем явно. У части карточек полей материала нет (у пуфа в фиде пусто),
        # поэтому цвет берём измеренный по самой фотографии товара — модель рисовала тканевый пуф
        # кожаным, потому что о материале и цвете ей никто не сказал (владелец, 2026-08-05).
        def _hex(v):
            try:
                r, g, b = json.loads(v) if isinstance(v, str) else v
                return f'#{int(r):02X}{int(g):02X}{int(b):02X}'
            except Exception:  # noqa: BLE001 — нет цвета: просто не пишем
                return ''
        colour = _hex(it.get('rgb')) if it.get('rgb') not in (None, 'None') else ''
        # Всё, что даёт фид: материал, цвет, обивка, тип, коллекция, особенности и описание.
        from viz_objects import feed_card
        fc = feed_card(it)
        prm = fc.get('params') or {}
        feed_bits = [f'{k}: {prm[k]}' for k in
                     ('Материал', 'Материал обивки', 'Ткань', 'Материал каркаса', 'Материал корпуса',
                      'Цвет', 'Цвет корпуса', 'Тип товара', 'Тип дивана', 'Конфигурация',
                      'Коллекция/серия', 'Серия', 'Особенности', 'Стиль')
                     if prm.get(k)]
        if fc.get('description'):
            feed_bits.append(f'описание: {fc["description"][:180]}')
        def _f(key):
            v = it.get(key)
            return None if v in (None, 'None', '') else v
        details = '; '.join(x for x in (
            '; '.join(feed_bits),
            colour and f'средний цвет по фото: {colour}',
            _f('wood') and f'дерево: {_f("wood")}',
            _f('metal') and f'металл: {_f("metal")}') if x)
        legend.append({
            'n': num, 'роль': role, 'товар': (it.get('name') or '')[:80],
            'описание': details[:420],
            'габариты_см': ([int(by[role].item.w_cm), int(by[role].item.d_cm),
                             int(by[role].item.h_cm or 0)] if role in by and by[role].item
                            else [int(it.get('w') or 0), int(it.get('d') or 0), int(it.get('h') or 0)]),
            'положение': rel.get(role, 'стоит на полу'),
            'ориентация': orientation_of(by[role], placements, room) if role in by else '',
            'видимость': seen_txt,
            'фото': os.path.basename(photo),
        })
    dst = f'{prefix}-marked.jpg'
    marked.save(dst, quality=93)
    json.dump(legend, open(f'{prefix}-legend.json', 'w'), ensure_ascii=False, indent=1)
    return src, dst, legend


def legend_text(legend: list[dict]) -> str:
    """Легенда одной строкой на запрос — то, что уходит модели вместе с размеченной картинкой."""
    return '; '.join(
        f'{e["n"]} — {e["роль"]} ({e["товар"]}), {e["габариты_см"][0]}×{e["габариты_см"][1]}×'
        f'{e["габариты_см"][2]} см, {e["положение"]}' for e in legend)


def main() -> None:
    n = int(sys.argv[1])
    cam = sys.argv[sys.argv.index('--cam') + 1] if '--cam' in sys.argv else 'C1'
    src, dst, legend = build(n, cam)
    print(dst)
    for e in legend:
        print(f'  {e["n"]:>2} {e["роль"]:<12} {e["положение"]}')


if __name__ == '__main__':
    main()
