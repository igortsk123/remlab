#!/usr/bin/env python3
"""ПРОЁМЫ СЕРВЕРНОГО КАДРА ИЗ ОБЩЕГО ОПИСАНИЯ (план demo-04 п.2, разбор Codex 14.10).

Описание проёма (IR) генерирует ОДНА функция — `lib/viewer3d/opening-ir.ts`, та же, что строит окна и двери в браузере;
комната витрины получает его при ночной сборке (`tools/flat3d/opening-ir.mjs` → `room.openings_ir`). Здесь IR
превращается в коробки trimesh и в место в комнате по тем же правилам, что у браузера (`lib/viewer3d/rooms.ts:frameOf`):
начало стены, направление вдоль неё и поворот лицом в комнату. Раньше сервер собирал окно своими формулами
(`draft_render._window_parts`, другая глубина и профиль), а дверь брал чужой моделью `kit-door` — в браузере и на кадре
были разные проёмы.

Самопроверка: `python tools/scout/opening_ir.py --selftest`.
"""
from __future__ import annotations

import math
import os
import re
import sys

import numpy as np

# цвета деталей — те же, что у материалов браузера (`openings.ts`: WHITE_FRAME, REVEAL, GLASS, DOOR_LEAF, DOOR_PANEL, HANDLE);
# стекло на сервере непрозрачное — холодный светлый (вид за окном — п.5 плана)
PALETTE = {'frame': (244, 243, 240), 'reveal': (236, 234, 229), 'glass': (188, 212, 230),
           'leaf': (242, 240, 236), 'panel': (232, 229, 224), 'handle': (185, 189, 194),
           # обжитая коробка (demo-04 п.6, `lib/viewer3d/fixtures-ir.ts`): плинтус, карниз, плафон
           'skirting': (244, 242, 238), 'cornice': (61, 61, 61), 'lamp': (251, 250, 247)}
INSET_CM = 1.0      # стена браузера стоит на 1 см внутрь от контура комнаты (`rooms.ts:INSET_CM`)


MAX_ENTRIES, MAX_BOXES, MAX_CM = 16, 24, 1000.0
_KINDS = ('window', 'door', 'opening', 'balcony')
_WALLS = ('south', 'north', 'west', 'east')


def sanitize(entries) -> list | None:
    """Описание приходит СО СТРАНИЦЫ (запрос кадра) — чужим данным не верим: не больше 16 проёмов и 24 коробок в каждом,
    числа конечные и в пределах 10 м, материал — из палитры. Битое — None: кадр строит проёмы прежним путём."""
    if not isinstance(entries, list) or not entries or len(entries) > MAX_ENTRIES:
        return None

    def num(v, lo=-MAX_CM, hi=MAX_CM):
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and lo <= v <= hi

    out = []
    for e in entries:
        ir = e.get('ir') if isinstance(e, dict) else None
        if not isinstance(ir, dict) or e.get('wall') not in _WALLS or ir.get('kind') not in _KINDS:
            return None
        cut, boxes, groups = ir.get('cut'), ir.get('boxes'), ir.get('groups') or {}
        if (not isinstance(cut, dict) or not all(num(cut.get(k)) for k in ('u0', 'u1', 'bottom', 'top'))
                or not isinstance(boxes, list) or not boxes or len(boxes) > MAX_BOXES or not isinstance(groups, dict)
                or len(groups) > 4):
            return None
        gs = {}
        for name, g in groups.items():
            if not isinstance(g, dict) or not all(num(g.get(k)) for k in ('x', 'y', 'z')) or not num(g.get('rotYDeg'), -360, 360):
                return None
            gs[str(name)[:16]] = {k: float(g[k]) for k in ('x', 'y', 'z', 'rotYDeg')}
        bs = []
        for b in boxes:
            if (not isinstance(b, dict) or b.get('material') not in PALETTE
                    or not all(num(b.get(k), 0, MAX_CM) for k in ('w', 'h', 'd'))
                    or not all(num(b.get(k)) for k in ('x', 'y', 'z'))
                    or (b.get('group') is not None and b.get('group') not in gs)):
                return None
            bs.append({'role': str(b.get('role') or '')[:16], 'material': b['material'],
                       **{k: float(b[k]) for k in ('w', 'h', 'd', 'x', 'y', 'z')},
                       **({'group': b['group']} if b.get('group') is not None else {})})
        clean = {'kind': ir['kind'], 'cut': {k: float(cut[k]) for k in ('u0', 'u1', 'bottom', 'top')}, 'boxes': bs, 'groups': gs}
        bd = ir.get('backdrop')
        if bd is not None:      # вид из окна: только id нашего набора и числа в пределах — иначе проём без вида
            uv = bd.get('uv') if isinstance(bd, dict) else None
            if (isinstance(bd, dict) and isinstance(bd.get('assetId'), str) and re.fullmatch(r'[a-z0-9-]{1,32}', bd['assetId'])
                    and all(num(bd.get(k)) for k in ('back', 'u0', 'u1', 'bottom', 'top')) and isinstance(uv, dict)
                    and all(num(uv.get(k), -3, 3) for k in ('u0', 'u1', 'v0', 'v1'))):
                clean['backdrop'] = {'assetId': bd['assetId'], **{k: float(bd[k]) for k in ('back', 'u0', 'u1', 'bottom', 'top')},
                                     'uv': {k: float(uv[k]) for k in ('u0', 'u1', 'v0', 'v1')}}
        out.append({'wall': e['wall'], 'ir': clean})
    return out


def sanitize_fixtures(entries) -> list | None:
    """Плинтус, карниз, светильник со страницы (`room.fixtures_ir`) — та же недоверчивость, что к проёмам: ≤ 6 записей по
    ≤ 40 коробок, стены или 'room', материал из палитры, числа конечные и в пределах 10 м. Битое — None (кадр без них)."""
    if not isinstance(entries, list) or not entries or len(entries) > 6:
        return None

    def num(v, lo=-MAX_CM, hi=MAX_CM):
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and lo <= v <= hi

    out = []
    for e in entries:
        boxes = e.get('boxes') if isinstance(e, dict) else None
        if e.get('wall') not in _WALLS + ('room',) or not isinstance(boxes, list) or len(boxes) > 40:
            return None
        bs = []
        for b in boxes:
            if (not isinstance(b, dict) or b.get('material') not in PALETTE or not all(num(b.get(k), 0, MAX_CM) for k in ('w', 'h', 'd'))
                    or not all(num(b.get(k)) for k in ('x', 'y', 'z'))):
                return None
            bs.append({'role': str(b.get('role') or '')[:16], 'material': b['material'], **{k: float(b[k]) for k in ('w', 'h', 'd', 'x', 'y', 'z')}})
        if bs:
            out.append({'wall': e['wall'], 'ir': {'boxes': bs, 'groups': {}}})
    return out or None


def ry(deg: float) -> np.ndarray:
    """Поворот вокруг вертикали, как `rotation.y` three.js и `scene_mesh.ry`: фронт (0,0,1) → (sin, 0, cos)."""
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], np.float64)


def wall_frame(side: str, w: float, d: float) -> tuple[float, float, float]:
    """Начало стены (x, z — в координатах комнаты, z = y плана) и поворот лицом в комнату, градусы (`rooms.ts:frameOf`).
    'room' — оси самой комнаты (светильник: x, высота, y плана)."""
    return {'south': (0.0, INSET_CM, 0.0), 'north': (w, d - INSET_CM, 180.0),
            'west': (INSET_CM, d, 90.0), 'east': (w - INSET_CM, 0.0, 270.0), 'room': (0.0, 0.0, 0.0)}[side]


def local_boxes(ir: dict) -> list[tuple[str, str, np.ndarray]]:
    """Коробки IR в осях стены: (смысловой id, материал, 8 вершин в см). Группа (полотно двери) — со своим поворотом."""
    out = []
    groups = ir.get('groups') or {}
    for b in ir.get('boxes') or []:
        hx, hy, hz = b['w'] / 2, b['h'] / 2, b['d'] / 2
        corners = np.array([[sx * hx, sy * hy, sz * hz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)], np.float64)
        corners += [b['x'], b['y'], b['z']]
        g = groups.get(b.get('group') or '')
        if g:
            corners = corners @ ry(g['rotYDeg']).T + [g['x'], g['y'], g['z']]
        out.append((b['role'], b['material'], corners))
    return out


def world_boxes(entry: dict, w: float, d: float) -> list[tuple[str, str, np.ndarray]]:
    """Коробки проёма в координатах комнаты (x, высота, z): начало стены + поворот лицом в комнату."""
    ox, oz, rot = wall_frame(entry['wall'], w, d)
    R = ry(rot)
    return [(role, mat, c @ R.T + [ox, 0.0, oz]) for role, mat, c in local_boxes(entry['ir'])]


_VIEWS: dict = {}
VIEW_HTTP = os.environ.get('VIEW_HTTP', 'https://remont-lab.online/scene/views')
GLASS_TINT, GLASS_MIX = (234, 242, 246), 0.07    # как стекло браузера (`openings.ts:GLASS`, opacity 0.07)


def view_image(asset_id: str):
    """Картинка вида из окна по id нашего набора: из репозитория (`public/scene/views`), иначе с прода в кэш.
    Нет — None (проём рисуется с небом). Ошибка печатается, а не глотается молча."""
    if not re.fullmatch(r'[a-z0-9-]{1,32}', asset_id or ''):
        return None
    if asset_id in _VIEWS:
        return _VIEWS[asset_id]
    img = None
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'public', 'scene', 'views', asset_id + '.webp')
    cache = os.path.join(os.environ.get('SCENE3D_CACHE', '/tmp'), 'views', asset_id + '.webp')
    try:
        from PIL import Image
        src = local if os.path.exists(local) else cache
        if not os.path.exists(src):
            import urllib.request
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            data = urllib.request.urlopen(f'{VIEW_HTTP}/{asset_id}.webp', timeout=30).read()
            if len(data) > 4 << 20:
                raise ValueError('картинка вида больше 4 МБ')
            open(cache, 'wb').write(data)
        img = np.asarray(Image.open(src).convert('RGB'), np.float32)
    except Exception as e:  # noqa: BLE001 — без вида кадр собирается с небом, но громко
        print(f'  вид из окна {asset_id}: не загрузился ({str(e)[:80]})', flush=True)
    _VIEWS[asset_id] = img
    return img


def has_view(entry: dict) -> bool:
    bd = (entry.get('ir') or {}).get('backdrop')
    return bool(bd) and view_image(bd.get('assetId', '')) is not None


def _rgb(hexs: str):
    return tuple(int(hexs[i:i + 2], 16) for i in (1, 3, 5))


def trimesh_parts(entry: dict, colors: dict | None = None):
    """Части для растеризатора: коробки в осях стены (фронт +Z — внутрь комнаты), цвет — из палитры. Есть вид из окна —
    стекло не рисуется: непрозрачное закрыло бы вид (его тон кладёт `paint_beyond`)."""
    import trimesh as _t
    parts = []
    skip_glass = has_view(entry)
    for _role, mat, c in local_boxes(entry['ir']):
        if skip_glass and mat == 'glass':
            continue
        m = _t.Trimesh(vertices=c, faces=_BOX_FACES.copy(), process=False)
        rgb = _rgb(colors[mat]) if colors and colors.get(mat) else PALETTE.get(mat, (230, 230, 230))
        m.visual = _t.visual.color.ColorVisuals(mesh=m, face_colors=np.tile(np.array([*rgb, 255], np.uint8), (12, 1)))
        parts.append(m)
    return parts


# грани коробки по 8 вершинам в порядке (sx, sy, sz) ∈ {−1,1}³ (индекс = 4·ix + 2·iy + iz), наружу
_BOX_FACES = np.array([
    [0, 1, 3], [0, 3, 2],      # −x
    [4, 6, 7], [4, 7, 5],      # +x
    [0, 4, 5], [0, 5, 1],      # −y
    [2, 3, 7], [2, 7, 6],      # +y
    [0, 2, 6], [0, 6, 4],      # −z
    [1, 5, 7], [1, 7, 3],      # +z
], np.int64)


def placement_of(entry: dict, w: float, d: float) -> tuple[float, float, float, float, tuple[float, float, float]]:
    """Где поставить набор коробок как «предмет»: центр габарита на плане (x, y), поворот, подъём низа и габарит
    (ш, в, г) в осях стены. `scene_mesh.world_vertices` центрирует габарит в точке и ставит низ на подъём — с габаритом,
    равным собственному, масштаб 1, и коробки встают ровно туда же, куда их ставит браузер."""
    allc = np.vstack([c for _, _, c in local_boxes(entry['ir'])])
    lo, hi = allc.min(axis=0), allc.max(axis=0)
    ox, oz, rot = wall_frame(entry['wall'], w, d)
    centre = ry(rot) @ ((lo + hi) / 2) + [ox, 0.0, oz]
    return float(centre[0]), float(centre[2]), rot, float(lo[1]), tuple(float(v) for v in (hi - lo))


# что видно в прорези стены, пока нет вида из окна (п.5): у окна — небо (как `scene_mesh.draw_window_glass`), у двери
# и портала — приглушённый коридор, чтобы распахнутый проём не читался стеной
BEYOND_SKY = ((198, 222, 238), (236, 238, 233))
BEYOND_HALL = ((150, 145, 138), (176, 170, 161))
CUT_EPS_CM = 4.0    # «за проёмом» = глубина не ближе плоскости стены на столько (clay-стена стоит на контуре, ≤1 см дальше)


def paint_beyond(canvas: np.ndarray, zbuf: np.ndarray, entries: list, cam, w: float, d: float) -> int:
    """ЧТО ВИДНО СКВОЗЬ ПРОЁМ НА СЕРВЕРНОМ КАДРЕ (план demo-04 п.3; у окна с видом — картинка вида, п.5).

    Стену вокруг проёма вырезает `planner/scene.py:compile_scene` (`wall_rects`), за вырезом стоит плоскость «снаружи» с
    clay-цветом окна/двери (синяя плашка, коричневая). Здесь пиксели, где луч камеры попадает в прямоугольник `ir.cut`
    на плоскости стены и ближе ничего нет (мебель clay перед стеной не трогаем), перекрашиваются: окно — небо, дверь —
    приглушённый коридор. Глубина не меняется. Меши проёма потом растеризуются поверх. Возвращает число пикселей."""
    H, Wpx = zbuf.shape
    eye, fwd, right, up = (np.asarray(v, np.float64) for v in cam.basis())
    focal = (cam.width / 2) / math.tan(math.radians(cam.fov_deg) / 2)
    kx, ky = Wpx / cam.width, H / cam.height
    gy, gx = np.mgrid[0:H, 0:Wpx]
    a = (gx / kx - cam.width / 2) / focal
    b = (cam.height / 2 + getattr(cam, 'shift_y', 0.0) * cam.height - gy / ky) / focal
    # луч с глубиной 1 вдоль взгляда: P = eye + t·(fwd + a·right + b·up), t = глубина z-буфера
    dirs = fwd[None, None, :] + a[..., None] * right[None, None, :] + b[..., None] * up[None, None, :]
    total = 0
    for e in entries:
        ir = e.get('ir') or {}
        cut = ir.get('cut')
        if not cut:
            continue
        ox, oz, rot = wall_frame(e['wall'], w, d)
        R = ry(rot)
        normal = R @ np.array([0.0, 0.0, 1.0])            # лицо стены — внутрь комнаты
        origin = np.array([ox, 0.0, oz])
        den = dirs @ normal
        with np.errstate(divide='ignore', invalid='ignore'):
            t = ((origin - eye) @ normal) / den
        hit = eye[None, None, :] + t[..., None] * dirs
        loc = (hit - origin) @ R                           # в оси стены: x — вдоль, y — высота
        m = ((t > 1) & np.isfinite(t) & (loc[..., 0] >= cut['u0']) & (loc[..., 0] <= cut['u1'])
             & (loc[..., 1] >= cut['bottom']) & (loc[..., 1] <= cut['top']) & (zbuf >= t - CUT_EPS_CM))
        n = int(m.sum())
        if not n:
            continue
        lo, hi = BEYOND_SKY if ir.get('kind') in ('window', 'balcony') else BEYOND_HALL
        k = np.clip((cut['top'] - loc[..., 1]) / max(cut['top'] - cut['bottom'], 1.0), 0, 1)[m][:, None]
        canvas[m] = np.asarray(lo, np.float32) * (1 - k) + np.asarray(hi, np.float32) * k
        bd = ir.get('backdrop')
        img = view_image(bd['assetId']) if bd else None
        if img is not None:
            # ВИД ИЗ ОКНА (demo-04 п.5): тот же луч продолжаем до плоскости вида на `back` см за стеной — та же геометрия,
            # что у браузера (`openings.ts:backdropMesh`), — и берём её точку картинки (билинейно), с тоном стекла
            o2 = origin - normal * bd['back']
            with np.errstate(divide='ignore', invalid='ignore'):
                t2 = ((o2 - eye) @ normal) / den
            l2 = ((eye[None, None, :] + t2[..., None] * dirs) - o2) @ R
            uv = bd['uv']
            su = uv['u0'] + (l2[..., 0] - bd['u0']) / max(bd['u1'] - bd['u0'], 1e-6) * (uv['u1'] - uv['u0'])
            sv = uv['v0'] + (l2[..., 1] - bd['bottom']) / max(bd['top'] - bd['bottom'], 1e-6) * (uv['v1'] - uv['v0'])
            ih, iw = img.shape[:2]
            fx = np.clip(su[m], 0, 1) * (iw - 1)
            fy = np.clip(1 - sv[m], 0, 1) * (ih - 1)
            x0, y0 = np.floor(fx).astype(int), np.floor(fy).astype(int)
            x1, y1 = np.minimum(x0 + 1, iw - 1), np.minimum(y0 + 1, ih - 1)
            ax, ay = (fx - x0)[:, None], (fy - y0)[:, None]
            col = (img[y0, x0] * (1 - ax) * (1 - ay) + img[y0, x1] * ax * (1 - ay)
                   + img[y1, x0] * (1 - ax) * ay + img[y1, x1] * ax * ay)
            canvas[m] = col * (1 - GLASS_MIX) + np.asarray(GLASS_TINT, np.float32) * GLASS_MIX
        total += n
    return total


def _selftest() -> int:
    fails = 0

    def ok(cond, name):
        nonlocal fails
        print(('ok   ' if cond else 'FAIL ') + name)
        fails += 0 if cond else 1

    ir = {'boxes': [{'role': 'frame', 'material': 'frame', 'w': 10, 'h': 20, 'd': 4, 'x': 50, 'y': 100, 'z': 0}], 'groups': {}}
    for side, want in (('south', (50, 100, 1)), ('north', (400 - 50, 100, 300 - 1)), ('west', (1, 100, 300 - 50)),
                       ('east', (400 - 1, 100, 50))):
        c = world_boxes({'wall': side, 'ir': ir}, 400, 300)[0][2].mean(axis=0)
        ok(np.allclose(c, want, atol=1e-6), f'{side}: центр коробки в комнате {tuple(np.round(c, 3))}')
    # лицо внутрь комнаты: точка с z>0 в осях стены уходит от стены внутрь
    for side in ('south', 'north', 'west', 'east'):
        ir2 = {'boxes': [{'role': 'sill', 'material': 'frame', 'w': 1, 'h': 1, 'd': 1, 'x': 50, 'y': 0, 'z': 10}], 'groups': {}}
        c = world_boxes({'wall': side, 'ir': ir2}, 400, 300)[0][2].mean(axis=0)
        inside = 0 < c[0] < 400 and 0 < c[2] < 300 and min(c[0], 400 - c[0], c[2], 300 - c[2]) > 5
        ok(inside, f'{side}: подоконник внутри комнаты')
    door = {'boxes': [{'role': 'leaf', 'material': 'leaf', 'w': 80, 'h': 200, 'd': 4, 'x': 40, 'y': 100, 'z': 0, 'group': 'leaf'}],
            'groups': {'leaf': {'x': 205, 'y': 0, 'z': 2, 'rotYDeg': -99}}}
    c = local_boxes(door)[0][2].mean(axis=0)
    ok(c[2] > 30, f'распахнутое полотно уходит внутрь комнаты (z={c[2]:.1f})')
    x, y, rot, elev, size = placement_of({'wall': 'south', 'ir': ir}, 400, 300)
    ok(abs(x - 50) < 1e-6 and abs(y - 1) < 1e-6 and rot == 0 and abs(elev - 90) < 1e-6 and size == (10.0, 20.0, 4.0),
       'место «предмета» проёма: центр габарита, низ, габарит')
    good = [{'wall': 'south', 'ir': {'kind': 'window', 'cut': {'u0': 1, 'u1': 2, 'bottom': 0, 'top': 3}, 'boxes': ir['boxes'], 'groups': {}}}]
    ok(sanitize(good) is not None, 'описание со страницы: правильное проходит')
    ok(sanitize([{**good[0], 'wall': 'up'}]) is None, 'чужая стена — отказ')
    ok(sanitize(good * 17) is None, 'больше 16 проёмов — отказ')
    big = [{**good[0], 'ir': {**good[0]['ir'], 'boxes': [{**ir['boxes'][0], 'w': 1e9}]}}]
    ok(sanitize(big) is None, 'коробка больше 10 м — отказ')
    nan = [{**good[0], 'ir': {**good[0]['ir'], 'boxes': [{**ir['boxes'][0], 'x': float('nan')}]}}]
    ok(sanitize(nan) is None, 'не число — отказ')
    fx = [{'wall': 'south', 'boxes': [{'role': 'skirting', 'material': 'skirting', 'w': 100, 'h': 7, 'd': 1.6, 'x': 50, 'y': 3.5, 'z': 0.8}]},
          {'wall': 'room', 'boxes': [{'role': 'lamp', 'material': 'lamp', 'w': 42, 'h': 3, 'd': 42, 'x': 200, 'y': 267.5, 'z': 150}]}]
    ok(sanitize_fixtures(fx) is not None, 'плинтус и светильник со страницы проходят')
    ok(sanitize_fixtures([{'wall': 'roof', 'boxes': fx[0]['boxes']}]) is None, 'чужая «стена» — отказ')
    c = world_boxes(sanitize_fixtures(fx)[1], 400, 300)[0][2].mean(axis=0)
    ok(np.allclose(c, (200, 267.5, 150)), f'светильник — в центре комнаты у потолка {tuple(np.round(c, 1))}')
    print('итог:', 'чисто' if not fails else f'{fails} провал(ов)')
    return 1 if fails else 0


if __name__ == '__main__' and '--selftest' in sys.argv:
    sys.exit(_selftest())
