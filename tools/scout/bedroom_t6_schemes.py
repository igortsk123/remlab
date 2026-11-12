"""Спальня Т6 «было | стало» в виде листа-образца (T-20261112-62, план bedroom-groups-01).

Те же пары, что в листах Т6 (`.t38-sheet.py`, T-20261112-38/2): демо-спальни 1 и 2 по стилям (банк `sets-bedroom.json`, пара,
тир «комфорт») — БЫЛО = раскладка банка, СТАЛО = движок групп (`planner.bedroom.solve_bedroom(engine='groups')`) на тех же
предметах; спальни UK-туров — БЫЛО = поштучный движок (`engine='items'`), СТАЛО = движок групп. Координаты — из результатов
движка (центр + поворот → след `planner.geometry.footprint`), своей геометрией не пересчитываем.

Рисование и проверки — `bedroom_schemes.py` импортом: масштаб и сетка 50 см, размер у предмета, зоны с числом см (бок 75 /
изножье 60, 90 перед шкафом, 76 перед комодом, 76 у двери и дуга), дорожки от двери к кровати/окну/столу, красная штриховка
нарушения и строка причины. Нормы — `services/planner-solver/rules/occupancy.json`. Отдельной строкой — что говорит проверка
движка (`planner.bedroom_checks.validate_bedroom`): обе проверки на листе, расхождение видно.

Запуск (без сети и БД): python tools/scout/bedroom_t6_schemes.py <папка-вывода> [банк.json] [папка UK scenes]
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'services' / 'planner-solver'))
sys.path.insert(0, str(HERE))
import bedroom_schemes as bs  # noqa: E402
from planner import passage_norms as PN  # noqa: E402

# T-20261112-68 (ADR-0394): проходы по норме обычного жилья — цель / допуск compact / жёстко (`distances_cm.clearances`).
# Проверка схемы (`bedroom_schemes`) идёт дважды: по цели и по допуску; итог панели — «цель» | «compact» | «✗».
# Заливка зон — допуск (меньше — нарушение), тонкий контур — цель.
MODE_RU = {'target': 'цель', 'compact': 'compact', 'refused': '✗ отказ', None: '—'}
REFUSAL_RU = {'COUPLE_NO_SECOND_SIDE': 'паре нет второго бока', 'BED_SIDE_NO_PASSAGE': 'нет прохода у бока',
              'ROUTE_TOO_NARROW': 'путь от двери уже 50', 'STORAGE_CANT_OPEN': 'шкаф/комод не открыть',
              'FURNITURE_IN_DOOR_SWING': 'мебель в дуге двери', 'WINDOW_UNREACHABLE': 'окно недостижимо',
              'RADIATOR_BLOCKED': 'радиатор закрыт', 'BED_NO_FIT': 'кровать не встала', 'REQUIRED_NO_FIT': 'не встало обязательное',
              'BED_NO_ROOM': 'кровать не влезает в контур'}


def set_norm(level, placements=()):
    """Числа проверки схемы `bedroom_schemes` по уровню прохода (target | compact): бок, изножье, шкаф и комод — как у
    движка, `PN.front_need` по предмету раскладки (тип шкафа из данных, неизвестен — распашной; вылет ящика неизвестен —
    70), путь от двери; подписи причин — заново под эти числа."""
    with PN.using(level):
        bs.SIDE, bs.FOOT = PN.clearance('bed_side_couple'), PN.clearance('bed_foot_route')
        bs.WARD = PN.clearance('wardrobe_hinged_front')
        bs.DRESS = max(PN.clearance('dresser_front'), PN.drawer_reach_unknown())
        for p in placements:
            k = kind_of(p.role)
            if k == 'wardrobe' and p.item is not None:
                bs.WARD = PN.front_need(p.item, 'шкаф')[1]
            elif k == 'dresser' and p.item is not None:
                bs.DRESS = PN.front_need(p.item, 'комод')[1]
        bs.ROUTE = PN.clearance('route_door_window')
    bs.CODE_RU.update({'BED_SIDE_PASSAGE': f'нет прохода {bs.SIDE:.0f} у бока кровати', 'BED_FOOT_PASSAGE': f'нет {bs.FOOT:.0f} у изножья',
                       'WARDROBE_FRONT': f'нет {bs.WARD:.0f} перед шкафом', 'DRESSER_FRONT': f'нет {bs.DRESS:.0f} перед комодом',
                       'ROUTE_BED': f'нет пути {bs.ROUTE:.0f} от двери к кровати', 'ROUTE_WINDOW': f'нет пути {bs.ROUTE:.0f} от двери к окну',
                       'ROUTE_DESK': f'нет пути {bs.ROUTE:.0f} от двери к столу'})

BANK = Path('/home/pakar/igor/remlab/tools/scout/sets-bedroom.json')     # не в git — основная копия (как в Т6)
UK_SCENES = Path('/home/pakar/remlab-logs/t13-1111/1943-r3/bed/scenes')   # сцены UK-туров, на которых строился Т6
UK_PICK = [('new-4y0opqHwp1gkKYnIDgm1Kw', 0), ('new-4y0opqHwp1gkKYnIDgm1Kw', 2), ('new-FjiOaFNsLKJoAZJSHSFz8w', 1),
           ('new-aOv8kTVEKMgu2H6iD6UIJg', 0)]
FURN = ('кровать', 'тумба', 'шкаф', 'комод', 'стол', 'стул', 'туалетный')
KIND = (('кровать', 'bed'), ('тумба', 'ns'), ('шкаф', 'wardrobe'), ('комод', 'dresser'), ('туалетный', 'desk'),
        ('стол', 'desk'), ('стул', 'chair'))
GROUP = {'bed': 'sleep', 'ns': 'sleep', 'wardrobe': 'wardrobe', 'dresser': 'dresser', 'desk': 'work', 'chair': 'work'}
BACK = {0: 'south', 90: 'west', 180: 'north', 270: 'east'}   # facing_vector(rot) = (sin, cos): 0 — лицом на север
PURPOSE = {'couple': 'couple', 'guest': 'guest', 'single': 'single', 'single_narrow': 'single_narrow'}
STYLE_ORDER = ['сканди', 'современный', 'минимализм', 'лофт', 'джапанди']


# ---------------------------------------------------------------- перевод результата движка в предметы схемы
def kind_of(role):
    r = role.lower()
    for k, v in KIND:
        if r.startswith(k):
            return v
    return None


def back_wall(rot):
    """Стена за спиной предмета по повороту движка (лицо — facing_vector)."""
    return BACK[int(round((rot % 360) / 90)) % 4 * 90]


def to_item(room, role, sku, rect, rot, variant=None):
    """Предмет схемы из следа движка: стена — за спиной, off — вдоль стены от её начала (как `bs.band`), g — зазор до
    стены. Зоны строятся от фактической грани (g + глубина), а не от стены."""
    kind = kind_of(role)
    wall = back_wall(rot)
    W, D = room['W'], room['D']
    off = rect[0] if wall in ('south', 'north') else rect[1]
    g = {'south': rect[1], 'north': D - rect[3], 'west': rect[0], 'east': W - rect[2]}[wall]
    w, d = sku['w'], sku['d']
    it = {'role': role, 'kind': kind, 'sku': sku, 'wall': wall, 'off': off, 'group': GROUP[kind], 'rect': tuple(rect),
          'zones': [], 'gap_wall': g}
    front = {'wardrobe': ('WARDROBE_FRONT', bs.WARD), 'dresser': ('DRESSER_FRONT', bs.DRESS), 'desk': ('DESK_CHAIR', bs.DESKZ)}
    if kind in front:
        code, depth = front[kind]
        it['zones'].append({'code': code, 'rect': bs.band(room, wall, off, w, g + d, g + d + depth), 'label': f'{depth:.0f}',
                            'kind': kind, 'wall': wall})
    if kind == 'bed':
        it['variant'] = variant or 'pair'
        it['side_zone'] = {'lo': bs.band(room, wall, off - bs.SIDE, bs.SIDE, g, g + d),
                           'hi': bs.band(room, wall, off + w, bs.SIDE, g, g + d)}
        it['foot_zone'] = bs.band(room, wall, off, w, g + d, g + d + bs.FOOT)
        it['gap'] = {'lo': off, 'hi': bs.wall_len(room, wall) - off - w}
    return it


def scheme_room(rid, title, model, notes=()):
    """Комната схемы из модели движка (`planner.models.Room`): те же стены — юг y=0, север y=D (`geometry._wall_strip`)."""
    ops = [o.model_dump() for o in model.openings]
    rads = [{'wall': r.wall, 'offset_cm': r.offset_cm, 'width_cm': r.width_cm, 'depth_cm': r.depth_cm} for r in model.radiators]
    room = bs._room(rid, title, 'движок', model.width_cm, model.depth_cm, ops, rads, list(notes))
    room['_geo'] = {'doors': [bs.door_geo(room, d) for d in room['doors']],
                    'rads': [bs.band(room, r['wall'], r['off'], r['width'], 0, r['depth']) for r in room['rads']],
                    'wins': [bs.band(room, w['wall'], w['off'], w['width'], 0, 1) for w in room['wins']]}
    return room


def items_from(room, placements, names, variant=None):
    from planner.geometry import footprint
    out = []
    for p in placements:
        if kind_of(p.role) is None or p.item is None:
            continue
        it = p.item
        sku = {'w': float(it.w_cm), 'd': float(it.d_cm), 'h': float(it.h_cm or 0), 'name': names.get(p.role) or p.role}
        out.append(to_item(room, p.role, sku, footprint(p).bounds, p.rot, variant))
    return out


def evaluate(room, items, purpose):
    """Проверки схемы (нормы occupancy.json) + дорожки от двери; результат в формате `bs.render`."""
    geo = room['_geo']
    vs = bs.evaluate(room, geo, items, purpose, {})
    rv, paths = bs.check_routes(room, geo, items, purpose, want_paths=True)
    vs += rv
    pins = pinches(room, geo, items, purpose) if rv else []
    return {'items': items, 'vs': vs, 'ok': not any(v['hard'] for v in vs), 'purpose': purpose, 'pins': pins}, paths


def clearance(room, geo, items):
    """Карта «сколько см до ближайшего препятствия» (сетка 1 см, как `bs.free_mask`): предметы, радиаторы, стены.
    Дуга двери — не препятствие (человек проходит через свой проём; в `bs.free_mask` её тоже нет)."""
    import numpy as np
    from scipy import ndimage
    _free, X, Y = bs.free_mask(room, geo, items)
    occ = np.zeros(X.shape, bool)
    for o in [i['rect'] for i in items] + list(geo['rads']):
        occ |= (X >= o[0]) & (X <= o[2]) & (Y >= o[1]) & (Y <= o[3])
    dist, idx = ndimage.distance_transform_edt(np.pad(~occ, 1), return_indices=True)   # за краем — стена
    return dist[1:-1, 1:-1] - 0.5, idx[1][1:-1, 1:-1] - 0.5, idx[0][1:-1, 1:-1] - 0.5, X, Y


def widest(c, start, m):
    """Самый широкий проход от start к цели m: наибольший t, при котором они связаны по клеткам c ≥ t (целые см)."""
    from scipy import ndimage
    sy, sx = start

    def linked(t):
        lab, _n = ndimage.label(c >= t)
        L0 = lab[sy, sx]
        return bool(L0 and (m & (lab == L0)).any())
    lo, hi = -1, int(bs.ROUTE / 2) + 1
    while hi - lo > 1:
        t = (lo + hi) // 2
        if linked(t):
            lo = t
        else:
            hi = t
    return lo


def obstacles(room, geo, items):
    """Препятствия пути с именами: предметы, радиаторы и четыре стены (полосы за краем комнаты)."""
    W, D, B = room['W'], room['D'], 1e4
    out = [(bs.ITEM_RU[i['kind']].lower(), i['rect']) for i in items] + [('радиатор', r) for r in geo['rads']]
    return out + [('стена', (-B, -B, 0, D + B)), ('стена', (W, -B, W + B, D + B)), ('стена', (-B, -B, W + B, 0)),
                  ('стена', (-B, D, W + B, D + B))]


def near_pt(r, p):
    return (min(max(p[0], r[0]), r[2]), min(max(p[1], r[1]), r[3]))


def gap_at(obs, p):
    """Ширина прохода в точке p: ближайшее препятствие и ближайшее ДРУГОЕ — с противоположной стороны.
    → (ширина см, точка 1, точка 2, имя 1, имя 2) или None."""
    import math
    d = sorted((math.dist(p, near_pt(r, p)), k) for k, (_n, r) in enumerate(obs))
    k1 = d[0][1]
    q1 = near_pt(obs[k1][1], p)
    v1 = (q1[0] - p[0], q1[1] - p[1])
    for _dist, k in d[1:]:
        q2 = near_pt(obs[k][1], p)
        if (q2[0] - p[0]) * v1[0] + (q2[1] - p[1]) * v1[1] < 0:      # по другую сторону от p
            return math.dist(q1, q2), q1, q2, obs[k1][0], obs[k][0]
    return None


def pinch_point(c, pts, t):
    """Где на пути (порог t) настоящее узкое место: путь переходит между разными областями порога t+1
    (сужение «перерезает» проход). Точки, где путь лишь огибает угол той же области, — не сужение."""
    from scipy import ndimage
    lab, _n = ndimage.label(c >= t + 1)
    H, Wd = c.shape
    cell = [(min(int(y), H - 1), min(int(x), Wd - 1)) for x, y in pts]
    L = [lab[q] for q in cell]
    best, i, n = None, 0, len(pts)
    while i < n:
        if L[i]:
            i += 1
            continue
        j = i
        while j < n and not L[j]:
            j += 1
        before = L[i - 1] if i > 0 else 'старт'
        after = L[j] if j < n else 'цель'
        if before != after:                               # отрезок без «широкой» области разделяет разные — сужение
            k = min(range(i, j), key=lambda q: c[cell[q]])
            if best is None or c[cell[k]] < c[cell[best]]:
                best = k
        i = j
    if best is None:                                      # запасной путь: самая тесная точка
        best = min(range(n), key=lambda q: c[cell[q]])
    return best


def pinches(room, geo, items, purpose):
    """Для каждого НЕпройденного пути от двери — самое узкое место лучшего маршрута: где, сколько см, между чем.
    Те же старты и цели, что `bs.check_routes` (паре — оба бока кровати; остальным — хотя бы один)."""
    from scipy import ndimage
    free, X, Y = bs.free_mask(room, geo, items)
    lab, _n = ndimage.label(free)
    c, _qx, _qy, _X, _Y = clearance(room, geo, items)
    obs = obstacles(room, geo, items)
    targets = bs.route_targets(room, geo, items, X, Y)
    out = []
    for d in room['doors']:
        sx, sy = bs.wall_point(room, d['wall'], d['off'] + d['width'] / 2, bs.ROUTE / 2 + 1)
        st = (int(sy), int(sx))
        L0 = lab[st] if 0 <= st[0] < lab.shape[0] and 0 <= st[1] < lab.shape[1] else 0
        fails = [(k, n, m) for k, n, m in targets if not (L0 and (m & (lab == L0)).any())]
        beds = [t for t in targets if t[0].startswith('bed')]
        if purpose != 'couple':      # не паре хватает одного бока — отмечаем лучший из непройденных, если не прошёл ни один
            bf = [t for t in fails if t[0].startswith('bed')]
            fails = [t for t in fails if not t[0].startswith('bed')]
            if beds and len(bf) == len(beds):
                fails.append(max(bf, key=lambda t: widest(c, st, t[2])))
        for key, name, m in fails:
            t = widest(c, st, m)
            p = {'key': key, 'name': name, 'width': None, 'seg': None, 'path_ok': [], 'path_bad': [], 'between': None}
            if t >= 0:
                pts = bs.bfs_path(c >= t, st, m) or bs.bfs_path(c >= t - 1, st, m)   # bfs по сетке 2 см может порвать путь
                if pts:
                    k = pinch_point(c, pts, t)
                    g = gap_at(obs, pts[k])
                    if g:
                        p.update(width=g[0], seg=(g[1], g[2]), between=(g[3], g[4]))
                    else:
                        p.update(width=2 * float(c[min(int(pts[k][1]), c.shape[0] - 1), min(int(pts[k][0]), c.shape[1] - 1)]))
                    p.update(path_ok=pts[:k + 1], path_bad=pts[k:])
            out.append(p)
    return out


def draw_pinches(pins):
    """Дорисовка для `bs.render(extra=…)`: путь до узкого места — своим цветом, после — красным; поперёк — красный
    отрезок с числом см."""
    red = (211, 47, 47)
    col = {'bed': (27, 94, 32), 'win': (13, 71, 161), 'desk': (230, 81, 0)}

    def dashed(cv, d, pts, c):
        pp = [cv.P(x, y) for x, y in pts[::3]] + ([cv.P(*pts[-1])] if pts else [])
        for i in range(0, len(pp) - 1, 2):
            d.line([pp[i], pp[i + 1]], fill=c, width=3)

    def f(cv, d):
        for p in pins:
            if not p['path_ok']:
                continue
            dashed(cv, d, p['path_ok'], col['bed' if p['key'].startswith('bed') else 'win' if p['key'].startswith('win') else 'desk'])
            dashed(cv, d, p['path_bad'], red)
            if p['path_bad']:
                ex, ey = cv.P(*p['path_bad'][-1])
                d.ellipse([ex - 5, ey - 5, ex + 5, ey + 5], outline=red, width=3)
            if not p['seg']:
                continue
            a, b = cv.P(*p['seg'][0]), cv.P(*p['seg'][1])
            d.line([a, b], fill=red, width=5)
            for q in (a, b):
                d.ellipse([q[0] - 4, q[1] - 4, q[0] + 4, q[1] + 4], fill=red)
            txt = f"{p['width']:.0f} см"
            fb = bs.font(15, True)
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            vert = abs(a[1] - b[1]) > abs(a[0] - b[0])
            tx, ty = (mx + 8, my - 9) if vert else (mx - d.textlength(txt, font=fb) / 2, my - 26)
            bb = d.textbbox((tx, ty), txt, font=fb)
            d.rectangle([bb[0] - 3, bb[1] - 2, bb[2] + 3, bb[3] + 2], fill=(255, 255, 255), outline=red)
            d.text((tx, ty), txt, font=fb, fill=red)
    return f


def engine_verdict(model, lay, strict=True):
    """Что говорит проверка движка (жёсткие коды) — для строки под схемой."""
    from planner.bedroom_checks import validate_bedroom
    from planner.models import Severity
    if not lay.placements:
        return []
    return [v.message or v.code for v in validate_bedroom(model, lay.placements, strict=strict).violations
            if v.severity is Severity.HARD]


def match(before, after):
    """Пары «было → стало» по виду предмета: одинаковые (две тумбы) — по ближайшему месту, а не по имени роли
    (движок может поменять «тумба» и «тумба 2» местами — это не сдвиг на 2 м)."""
    cand = sorted((abs(y['rect'][0] - x['rect'][0]) + abs(y['rect'][1] - x['rect'][1]), i, k)
                  for i, x in enumerate(before) for k, y in enumerate(after) if y['kind'] == x['kind'])
    got, used = {}, set()
    for _dist, i, k in cand:          # сначала самые близкие пары
        if i not in got and k not in used:
            got[i] = k
            used.add(k)
    pairs = [(x, after[got[i]] if i in got else None) for i, x in enumerate(before)]
    return pairs, [y for k, y in enumerate(after) if k not in used]


def moved(before, after):
    """Что поменялось между БЫЛО и СТАЛО: к другой стене / сдвиг вдоль стены, убранные и новые предметы."""
    out = []
    pairs, extra = match(before, after)
    for x, y in pairs:
        name = bs.ITEM_RU[x['kind']].lower()
        if y is None:
            out.append(f'{name} — убран')
        elif x['wall'] != y['wall']:
            out.append(f"{name}: к {bs.WALL_RU[y['wall']]} стене")
        else:
            dx = (y['rect'][0] - x['rect'][0], y['rect'][1] - x['rect'][1])
            if max(abs(dx[0]), abs(dx[1])) >= 1:
                ax = dx[0] if abs(dx[0]) >= abs(dx[1]) else dx[1]
                out.append(f"{name}: {'+' if ax > 0 else '−'}{abs(ax):.0f} см вдоль стены")
    out += [f"{bs.ITEM_RU[y['kind']].lower()} — добавлен" for y in extra]
    return list(dict.fromkeys(out))


def composition(items):
    k = [i['kind'] for i in items]
    p = ['кровать' if 'bed' in k else 'без кровати']
    n = k.count('ns')
    if n:
        p.append(f'{n} тумбы' if n > 1 else 'тумба')
    for kk, ru in (('wardrobe', 'шкаф'), ('dresser', 'комод'), ('desk', 'стол'), ('chair', 'стул')):
        if kk in k:
            p.append(ru)
    return ' + '.join(p)


# ---------------------------------------------------------------- пары «было | стало»
def sku_name(s, role):
    """Имя товара роли из набора банка (`items` — словарь роль→товар или список товаров с полем role)."""
    its = s.get('items') or {}
    x = its.get(role) if isinstance(its, dict) else next((i for i in its if isinstance(i, dict) and i.get('role') == role), None)
    if isinstance(x, dict):
        return x.get('name') or (x.get('sku') or {}).get('name')
    return x if isinstance(x, str) else None


def demo_pairs(bank_path):
    import compose_bedroom as CB
    from planner.bedroom import solve_bedroom
    from planner.models import Item, Placement
    from types import SimpleNamespace as NS
    bank = json.load(open(bank_path, encoding='utf-8'))
    bank = bank.get('sets', bank) if isinstance(bank, dict) else bank
    out = []
    for s in bank:
        if s['purpose'] != 'couple' or s.get('tier') != 'комфорт':
            continue
        lay = s['layout']
        model = CB._room_model(lay['_room'], s['purpose'])
        roles = [r for r in lay if not r.startswith('_') and r.split(' ')[0] in FURN]
        items = [Item(role=r, w_cm=lay[r]['w'], d_cm=lay[r]['d'], h_cm=lay[r]['h'], side_back=lay[r].get('side_back')) for r in roles]
        before = NS(placements=[Placement(role=r, x=lay[r]['x'], y=lay[r]['z'], rot=lay[r]['rot'], item=it)
                                for r, it in zip(roles, items)], meta={'engine': 'items'})
        after = solve_bedroom(model, items, 'couple', engine='groups')
        names = {r: sku_name(s, r) for r in roles}
        n = 1 if s['room_id'] == 'bedroom-1' else 2
        title = f"Демо спальня {n} · {s['style']} · {model.width_cm:.0f}×{model.depth_cm:.0f}"
        out.append({'id': f"{s['room_id']}-{s['style']}", 'group': f'demo-{n}', 'title': title, 'model': model,
                    'purpose': 'couple', 'before': before, 'after': after, 'names': names,
                    'before_src': 'раскладка банка', 'style': s['style']})
    out.sort(key=lambda p: (p['group'], STYLE_ORDER.index(p['style']) if p['style'] in STYLE_ORDER else 99))
    return out


def uk_name(sku):
    """В сценах UK у товара родовое имя («Кровать») — на схеме вместо него ширина спального места."""
    n = sku.get('name')
    if n == 'Кровать' and sku.get('sleep_w'):
        return f"спальное {sku['sleep_w']}"
    return n


def uk_pairs(scenes_dir):
    from planner.bedroom import solve_bedroom
    from planner.models import Item, Opening, Room
    out = []
    for sc, i in UK_PICK:
        d = json.load(open(Path(scenes_dir) / sc / 'bedrooms.json', encoding='utf-8'))
        rooms = d if isinstance(d, list) else d.get('rooms')
        r = rooms[i]
        v = r['variants'][0]
        purpose = v['purpose']
        ops = [Opening(**{k: x for k, x in o.items() if k in ('kind', 'wall', 'offset_cm', 'width_cm', 'swing_cm', 'hinge', 'sill_cm', 'height_cm')})
               for o in (v.get('openings_core') or r['openings_core'])]
        model = Room(width_cm=r['core']['w'], depth_cm=r['core']['d'], openings=ops, room_type='bedroom', purpose=purpose)
        its = [it for it in v['items'] if it['role'].split(' ')[0] in FURN]
        items = [Item(role=it['role'], w_cm=it['w'], d_cm=it['d'], h_cm=it['h']) for it in its]
        names = {it['role']: uk_name(it.get('sku') or {}) for it in its}
        before = solve_bedroom(model, items, purpose, engine='items')
        after = solve_bedroom(model, items, purpose, engine='groups')
        rid = f"uk-{sc[4:12]}-{i}-{int(model.width_cm)}x{int(model.depth_cm)}-{purpose}"
        title = f"UK {r.get('name') or 'Bedroom'} · {model.width_cm:.0f}×{model.depth_cm:.0f}"
        out.append({'id': rid, 'group': 'uk', 'title': title, 'model': model, 'purpose': purpose, 'before': before,
                    'after': after, 'names': names, 'before_src': 'поштучный движок',
                    'notes': ['радиаторов в сцене нет (как в Т6)']})
    return out


def before_allowances(model, placements):
    """Допуски раскладки «было» по той же мерке, что у движка (`planner.bedroom_allowances.allowances`, режим compact)."""
    from planner.bedroom_allowances import allowances
    with PN.using('compact'):
        return allowances(model, placements, {p.role for p in placements if not p.role.startswith('кровать')})


def target_outline(items):
    """Дорисовка: зоны по ЦЕЛИ тонким контуром (заливка на схеме — допуск)."""
    col = {'side': (46, 125, 50), 'foot': (46, 125, 50), 'WARDROBE_FRONT': (21, 101, 192), 'DRESSER_FRONT': (106, 27, 154),
           'DESK_CHAIR': (230, 81, 0)}

    def f(cv, d):
        for it in items:
            rects = [(z['code'], z['rect']) for z in it['zones']]
            if it['kind'] == 'bed':
                rects += [('side', it['side_zone']['lo']), ('side', it['side_zone']['hi']), ('foot', it['foot_zone'])]
            for code, r in rects:
                x0, y0 = cv.P(r[0], r[1])
                x1, y1 = cv.P(r[2], r[3])
                d.rectangle([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)], outline=col.get(code, (90, 90, 90)), width=2)
    return f


def both(*fs):
    def f(cv, d):
        for g in fs:
            g(cv, d)
    return f


from planner.bedroom_checks import AREA_EPS  # noqa: E402  залезание в зону до 100 см² — округление движка, не нарушение


def ok_tol(res):
    """Схема годна с допуском движка: у каждого жёсткого нарушения зон площадь залезания ≤ AREA_EPS (путь — без допуска)."""
    if res['ok']:
        return True
    for v in res['vs']:
        if v['hard']:
            area = sum((r[2] - r[0]) * (r[3] - r[1]) for r in v['regions'])
            if not v['regions'] or area > AREA_EPS:
                return False
    return True


_bs_route_targets = bs.route_targets


def route_targets_t68(room, geo, items, X, Y):
    """Цели пути от двери по канону T-68: до ПОЛОСЫ бока кровати (вдоль бока — своя норма бока 60/50, а не путь 75),
    а не до изголовья бока, как в Т6; окно и стол — как в Т6. Так же меряет движок (`bedroom_checks.route_violations`)."""
    import numpy as np
    out = [t for t in _bs_route_targets(room, geo, items, X, Y) if not t[0].startswith('bed')]
    beds = [i for i in items if i['kind'] == 'bed']
    if beds:
        b = beds[0]
        st = b.get('side_state', {})
        for s in ('lo', 'hi'):
            if st.get(s) == 'ok':     # дошёл телом: центр человека в ROUTE/2 + 1 от полосы (движок: main.buffer(need/2 + 1))
                z = b['side_zone'][s]
                dx = np.maximum(np.maximum(z[0] - X, X - z[2]), 0)
                dy = np.maximum(np.maximum(z[1] - Y, Y - z[3]), 0)
                out.insert(0, ('bed_' + s, 'кровать', dx * dx + dy * dy <= (bs.ROUTE / 2 + 1) ** 2))
    return out


bs.route_targets = route_targets_t68


def status(room, placements, names, variant, purpose):
    """Проверка схемы по цели и по допуску → (итог target|compact|refused, items/res/paths по допуску, items по цели)."""
    set_norm('target', placements)
    it_t = items_from(room, placements, names, variant)
    r_t, _p = evaluate(room, it_t, purpose)
    r_t['why'] = reasons(r_t)                          # подписи — под числа своей нормы, пока они выставлены
    set_norm('compact', placements)
    it_c = items_from(room, placements, names, variant)
    r_c, p_c = evaluate(room, it_c, purpose)
    r_c['why'] = reasons(r_c)
    st = 'target' if ok_tol(r_t) else 'compact' if ok_tol(r_c) else 'refused'
    decided = r_t if st == 'target' else r_c          # по какой норме вышел итог — её «впритык» и подписываем
    r_c['tol_only'] = st != 'refused' and not decided['ok']
    r_c['tol_res'] = decided
    return st, it_c, r_c, p_c, it_t


def build_panels(pair):
    """Две панели схемы на пару: БЫЛО и СТАЛО — с проверками по цели и допуску, дорожками, строкой движка, допусками
    покупателю и списком изменений."""
    room = scheme_room(pair['id'], pair['title'], pair['model'], pair.get('notes', ()))
    purpose = PURPOSE.get(pair['purpose'], 'couple')
    meta = pair['after'].meta or {}
    variant = meta.get('sleep_variant')
    sb, ib, rb, pb, tb = status(room, pair['before'].placements, pair['names'], variant, purpose)
    sa, ia, ra, pa, ta = status(room, pair['after'].placements, pair['names'], variant, purpose)
    comp = meta.get('composition') or {}
    cl = meta.get('clearance') or {}
    out = []
    for kind, res, paths, lay, st, tit in (('БЫЛО', rb, pb, pair['before'], sb, tb), ('СТАЛО', ra, pa, pair['after'], sa, ta)):
        res['tpl'] = bs.classify(room, res)
        if kind == 'СТАЛО':   # шифр шаблона, уровень и проход движка — из meta (composition, clearance)
            cipher = (f"{comp.get('template') or meta.get('template') or '—'} · ур. {comp.get('level') or '—'} · "
                      f"{MODE_RU.get(cl.get('mode'), cl.get('mode'))}")
            src = f"движок групп; раскладка группы сна {meta.get('template') or '—'}, вариант {variant or '—'}"
            if comp.get('degraded_from'):
                src += f"; упрощено с уровня {', '.join(comp['degraded_from'])}"
            allow = [a['text'] for a in meta.get('allowances') or []]
            refusal = cl.get('refusal') or []
            blockers = cl.get('bed_blockers') or []
        else:
            cipher = f"без шаблона · {MODE_RU[st]}"
            src = pair['before_src']
            allow = [a['text'] for a in before_allowances(pair['model'], lay.placements)] if st == 'compact' else []
            refusal, blockers = [], []
        eng = engine_verdict(pair['model'], lay, strict=True)
        out.append({'room': room, 'res': res, 'paths': paths, 'kind': kind, 'cipher': cipher, 'src': src, 'status': st,
                    'allow': list(dict.fromkeys(allow)), 'refusal': refusal, 'blockers': blockers, 'target_items': tit,
                    'engine_hard': eng, 'lost': [], 'moved': moved(ib, ia) if kind == 'СТАЛО' else []})
    lost = [bs.ITEM_RU[x['kind']].lower() for x, y in match(ib, ia)[0] if y is None]
    if lost:
        why = [w for w in (meta.get('sleep_why'), f"уровень {comp['level']}" if comp.get('degraded_from') else None) if w]
        out[1]['lost'] = lost
        out[1]['lost_why'] = ', '.join(why)
    return out


# ---------------------------------------------------------------- листы
SMALL = 20.0   # нарушение «на N см» пишем, когда залезание маленькое — видно, что это почти впритык, а не грубо


def reasons(res):
    """Жёсткие причины как `bs.hard_reasons`, но с глубиной залезания: «нет 90 перед шкафом — на 1 см»."""
    depth = {}
    for v in res['vs']:
        if v['hard']:
            t = bs.CODE_RU.get(v['code'], v['code'])
            dd = [min(r[2] - r[0], r[3] - r[1]) for r in v['regions']]
            depth[t] = max(depth.get(t) or 0, max(dd)) if dd else depth.get(t)
    narrow = {}       # путь от двери: самое узкое место (`pinches`) — «узко 69 см: кровать — радиатор»
    for p in res.get('pins', []):
        code = 'ROUTE_BED' if p['key'].startswith('bed') else 'ROUTE_WINDOW' if p['key'].startswith('win') else 'ROUTE_DESK'
        t = bs.CODE_RU[code]
        if p['width'] is None:
            cand = (-1.0, 'закрыто со всех сторон')
        else:
            a, b = p['between'] or ('?', '?')
            cand = (p['width'], f"узко {p['width']:.0f} см: {a} — {b}")
        if t not in narrow or cand[0] < narrow[t][0]:       # несколько непройденных (два бока) — самое узкое
            narrow[t] = cand
    return [t + (f' — {narrow[t][1]}' if t in narrow else f' — на {d:.0f} см' if d is not None and d <= SMALL else '')
            for t, d in depth.items()]


def wrap(text, f, maxw, indent='   '):
    d = ImageDraw.Draw(Image.new('RGB', (4, 4)))
    out, cur = [], ''
    for wd in text.split(' '):
        t = (cur + ' ' + wd) if cur else wd
        if cur and d.textlength(t, font=f) > maxw:
            out.append(cur)
            cur = indent + wd
        else:
            cur = t
    out.append(cur)
    return out


def foot_lines(pn, maxw):
    res = pn['res']
    f = bs.font(15)
    L = []
    st = pn.get('status')
    if st == 'target':
        L.append('✓ влезает по цели')
    elif st == 'compact':
        L.append('✓ влезает с допуском compact (по цели — нет)')
    else:
        L += ['✗ ' + t for t in reasons(res)]     # все, не прячем
    if res.get('tol_only'):
        L.append(f'впритык, залезание ≤{AREA_EPS:.0f} см² (округление, как у движка): ' + '; '.join(res['tol_res']['why']))
    L += ['допуск: ' + t for t in pn.get('allow', [])]
    if pn.get('refusal'):
        why = list(dict.fromkeys(pn['refusal'] + pn.get('blockers', [])))
        L.append('✗ отказ движка: ' + ', '.join(REFUSAL_RU.get(c, c) for c in why))
    if pn['engine_hard']:
        L.append('✗ проверка движка: ' + '; '.join(dict.fromkeys(pn['engine_hard']))[:200])
    else:
        L.append('проверка движка: жёстких нарушений нет')
    L.append(pn['src'])
    mv = [m for m in pn['moved'] if not m.endswith('— убран')]   # убранное — отдельной красной строкой ниже
    if mv:
        L.append('изменилось: ' + '; '.join(mv))
    elif pn['kind'] == 'СТАЛО':
        L.append('изменилось: ничего — та же расстановка')
    if pn['lost']:
        L.append('✗ движок не поставил: ' + ', '.join(pn['lost']) + (f" ({pn['lost_why']})" if pn.get('lost_why') else ''))
    for n in pn['room']['notes']:
        L.append('условно: ' + n)
    return [x for ln in L for x in wrap(ln, f, maxw)]


def render_panel(pn, colw):
    room, res = pn['room'], pn['res']
    s = min((colw - 100) / room['W'], 520 / room['D'])
    title = f"{pn['kind']} · {room['title']} — {pn['cipher']}"
    f = bs.font(20, True)
    d = ImageDraw.Draw(Image.new('RGB', (4, 4)))
    rt = room['title']
    for cut in (lambda t: t.rsplit(' · ', 1)[0],           # не влезло — без размеров (они на чертеже)
                lambda t: t.replace('Демо спальня', 'Спальня').replace('UK ', ''),
                lambda t: t.replace('Спальня ', 'сп. ').replace('Bedroom ', 'BR ')):
        if d.textlength(title, font=f) <= colw - 24:
            break
        rt = cut(rt)
        title = f"{pn['kind']} · {rt} — {pn['cipher']}"
    if d.textlength(title, font=f) > colw - 24:     # всё ещё не влезло — без шаблона: уровень и цель|compact|✗ важнее
        title = f"{pn['kind']} · {rt} — {pn['cipher'].split(' · ', 1)[-1]}"
    sub =f"{bs.PURPOSE_RU.get(res['purpose'], res['purpose'])} · схема {res['tpl']}: {composition(res['items'])}"
    return bs.render(room, res, s, compact=True, title=title, subtitle=sub[:84], foot_lines=foot_lines(pn, colw - 30),
                     paths=pn['paths'], extra=both(target_outline(pn.get('target_items', [])),
                                                   draw_pinches(res.get('pins', []))))


def _legend():
    t = {lv: {n: PN.clearance(n, lv) for n in ('bed_side_couple', 'bed_foot_route', 'wardrobe_hinged_front', 'dresser_front',
                                                 'route_door_window')} for lv in ('target', 'compact')}
    g = lambda n: f"{t['target'][n]:.0f}/{t['compact'][n]:.0f}"   # noqa: E731
    return (f"нормы обычного жилья (ADR-0394), цель/допуск: бок кровати {g('bed_side_couple')}, изножье {g('bed_foot_route')}, "
            f"распашной шкаф {g('wardrobe_hinged_front')}, комод {g('dresser_front')}, путь от двери {g('route_door_window')} · "
            'заливка зоны — допуск (меньше — нарушение), тонкий контур — цель · зелёное — бока и изножье, синее — шкаф, '
            'фиолетовое — комод, жёлтое — дверь 76 и дуга · пунктир — путь от двери шириной допуска: зелёный к кровати, синий к '
            'окну · красная штриховка — нарушение · в шапке: шаблон · уровень · цель | compact | ✗ · «допуск:» — строка покупателю')


LEGEND = _legend()


def make_sheets(out, pairs_panels, name, head, per=4, colw=640):
    files = []
    for si in range(0, len(pairs_panels), per):
        chunk = pairs_panels[si:si + per]
        rows = [[render_panel(pn, colw) for pn in pp] for pp in chunk]
        lf = bs.font(14)
        leg = wrap(LEGEND, lf, colw * 2 - 10, indent='')
        top = 50 + len(leg) * 20 + 10
        H = sum(max(im.height for im in r) + 16 for r in rows) + top
        sheet = Image.new('RGB', (colw * 2 + 30, H), (255, 255, 255))
        d = ImageDraw.Draw(sheet)
        n = si // per + 1
        tot = (len(pairs_panels) + per - 1) // per
        d.text((14, 12), f'{head} · БЫЛО | СТАЛО (масштаб, сетка 50 см)' + (f' · лист {n}/{tot}' if tot > 1 else ''),
               font=bs.font(24, True), fill=(0, 0, 0))
        for k, ln in enumerate(leg):
            d.text((14, 46 + 20 * k), ln, font=lf, fill=(70, 70, 70))
        y = top
        for r in rows:
            x = 10
            for im in r:
                sheet.paste(im, (x, y))
                d.rectangle([x, y, x + im.width - 1, y + im.height - 1], outline=(200, 200, 200))
                x += colw + 10
            y += max(im.height for im in r) + 16
        fn = out / f'{name}-{n}.png'
        sheet.save(fn)
        files.append(fn)
        print('sheet', fn, flush=True)
    return files


def main(out, bank=BANK, scenes=UK_SCENES):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    pairs = demo_pairs(bank) + uk_pairs(scenes)
    allp, notes = {}, []
    for p in pairs:
        pp = build_panels(p)
        allp.setdefault(p['group'], []).append(pp)
        b, a = pp
        cl = p['after'].meta.get('clearance') or {}
        notes.append({'id': p['id'], 'title': p['title'], 'before_status': b['status'], 'after_status': a['status'],
                      'engine_mode': cl.get('mode'), 'level': (p['after'].meta.get('composition') or {}).get('level'),
                      'before_hard': bs.hard_reasons(b['res']), 'after_hard': bs.hard_reasons(a['res']),
                      'engine_before': b['engine_hard'], 'engine_after': a['engine_hard'], 'cipher_after': a['cipher'],
                      'allow_before': b['allow'], 'allow_after': a['allow'], 'refusal': a['refusal'] + a['blockers'],
                      'moved': a['moved'], 'lost': a['lost'], 'lost_why': a.get('lost_why'),
                      'forecast': FORECAST.get(p['id'])})
        print(p['id'], '| было', b['status'], bs.hard_reasons(b['res']) if b['status'] == 'refused' else '', '| стало',
              a['status'], '| движок', cl.get('mode'), (p['after'].meta.get('composition') or {}).get('level'),
              '| потерял', a['lost'], flush=True)
    heads = {'demo-1': 'Демо спальня 1 (597×293) по стилям', 'demo-2': 'Демо спальня 2 (450×293) по стилям',
             'uk': 'Спальни UK-туров'}
    for g, pp in allp.items():
        make_sheets(out, pp, f'sheet-{g}', heads.get(g, g))
    json.dump(notes, open(out / 'notes.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    write_matrix(out / 'matrix.md', notes)


# прогноз канона (`.memory_bank/domain/room-templates.md` § «Пересчёт 14 спален листов T-62»): «стало» T-62 по новой норме,
# без смены уровня — 9 ✓ / 1 условно / 4 ✗ (ключ — id пары листа)
FORECAST_RULES = (('bedroom-1-', '✓'), ('bedroom-2-минимализм', '✓'), ('bedroom-2-лофт', '✓'), ('bedroom-2-современный', 'условно'),
                  ('bedroom-2-сканди', '✗'), ('bedroom-2-джапанди', '✗'), ('-325x280-', '✓'), ('-330x390-', '✓'),
                  ('-295x370-', '✗'), ('-210x370-', '✗'))


class _Forecast(dict):
    def get(self, k, default=None):
        return next((v for pre, v in FORECAST_RULES if pre in k), default)


FORECAST = _Forecast()
VERDICT = {'target': '✓ цель', 'compact': '✓ compact', 'refused': '✗'}


def write_matrix(path, notes):
    """Итог «комната → уровень → цель | compact | ✗ → почему» против прогноза канона 9 ✓ / 1 условно / 4 ✗."""
    L = ['# Спальни T-62 по нормам обычного жилья (T-20261112-68, ADR-0394)', '',
         'Было — раскладка банка (демо) или поштучный движок (UK); стало — движок групп: проход 1 все уровни по цели, '
         'проход 2 с допуском compact, дальше отказ. Проверка схемы — по цели и по допуску.', '',
         '| комната | прогноз канона | было | стало (схема) | движок: проход · уровень | ушло (уровень без предмета) | допуск покупателю / отказ |',
         '|---|---|---|---|---|---|---|']
    cnt = {}
    for n in notes:
        st = n['after_status']
        cnt[st] = cnt.get(st, 0) + 1
        lost = ', '.join(n['lost']) + (f" ({n['lost_why']})" if n.get('lost_why') else '') if n['lost'] else '—'
        why = '; '.join(n['allow_after']) or ('отказ: ' + ', '.join(REFUSAL_RU.get(c, c) for c in dict.fromkeys(n['refusal']))
                                              if n['refusal'] else '—')
        L.append(f"| {n['title']} | {n['forecast'] or '—'} | {VERDICT[n['before_status']]} | {VERDICT[st]} | "
                 f"{MODE_RU.get(n['engine_mode'], n['engine_mode'])} · {n['level'] or '—'} | {lost} | {why} |")
    fc = {}
    for n in notes:
        fc[n['forecast']] = fc.get(n['forecast'], 0) + 1
    L += ['', f"**Итог стало:** по цели {cnt.get('target', 0)} · с допуском {cnt.get('compact', 0)} · ✗ {cnt.get('refused', 0)} "
          f"(из {len(notes)}). **Прогноз канона:** ✓ {fc.get('✓', 0)} · условно {fc.get('условно', 0)} · ✗ {fc.get('✗', 0)} — "
          'по «стало» T-62 без смены уровня; движок теперь уходит на уровень без предмета (колонка «ушло»).']
    path.write_text('\n'.join(L) + '\n', encoding='utf-8')
    print('matrix', path, flush=True)


if __name__ == '__main__':
    a = sys.argv[1:]
    main(a[0], *(Path(x) for x in a[1:3]))
