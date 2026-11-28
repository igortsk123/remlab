"""T-98/11 · сторож устройства листа: 4 признака мерки на готовых ответах (plan.json), без нейросетей, без платных вызовов.
  ~/venvs/nc-models/bin/python -I storozh.py selftest   → selftest.txt (поломки руками на 2 листах)
  ~/venvs/nc-models/bin/python -I storozh.py run        → table.tsv, svod.json

Признаки (каждый: да / нет / н.п. + причина словами):
  П1 число помещений = числу подписей листа (все помещения). Подписи — labels4 (прошлый прогон читателя, точка в пикселях листа + число). < 3 подписей → класс Д, н.п.
     Жилые «как в объявлении» — только справочно (в объявлениях «комнат N» кухню-гостиную считают по-разному), в ворота не входят.
  П2 слитые/лишние: точка каждой подписи берётся С ЛИСТА (labels4), переводится в метры нашей подгонкой плана к чернилам листа (масштаб+сдвиг, vetka_a_eval.fit_plan);
     подпись ровно в одной комнате, в каждой комнате ровно одна подпись. Подгонка ненадёжна (опора < 0,5 или опора − контроль < 0,25) → «не могу проверить» = НЕТ.
  П3 входы: проём (дверь/проход; окна не считаются) касается комнаты (расстояние от центра проёма до комнаты ≤ 0,30 м); входная дверь = дверь на внешней стене,
     касающаяся ровно одной комнаты; все комнаты достижимы от комнат с входной дверью по проёмам, касающимся ≥ 2 комнат.
  П4 сумма комнат без балконов против площади объявления: площадь комнаты = заявленная area, если она есть у ВСЕХ комнат, иначе по контуру (контуры идут по осям стен: +4…+23 % к объявлению).
     Полоса: заявленные площади 0,90…1,10; по контуру 0,90…1,35; если у части комнат нет русских названий (балконы не отличить) верх +15 % / 1,50.
"""
import copy
import csv
import json
import math
import os
import sys

import cv2
import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union
import re

NC = os.path.expanduser('~/remlab-logs/etazhi-walls/nc-models')
sys.path.insert(0, NC)
sys.path.insert(0, os.environ.get('VORONKA_DIR') or os.path.expanduser('~/remlab-logs/etazhi-walls/voronka'))   # T-98/16: код р.5/OCR — из снимка voronka/versii/<время>, когда задан VORONKA_DIR
import neutral_names as NN  # noqa: E402  (р.5: один источник правил имён, T-98/14 п.10)
import words_on_sheet as WS  # noqa: E402  (T-98/15: флаг «имена словами на листе», OCR + кэш)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))      # T-ЦП рамка: СВОЙ ru_eval (рядом с этим файлом) — раньше nc-models и снимка
import ru_eval as RE  # noqa: E402
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'ops'))
try:
    from run_card import carded  # noqa: E402  (П1.161 шаг 5: карточка прогона RUN.json в выходной папке; сбой карточки прогон не валит)
except ImportError as _rc_err:  # снимок воронки копирует файлы плоско, без tools/ops (Fable 28.11): нет модуля → прогон идёт без карточки
    print('storozh: карточка прогона недоступна (%s) — прогон идёт без неё' % _rc_err, file=sys.stderr)

    def carded(run_dir, task=None, intermediate=None):
        return lambda fn: fn
import ext as X  # noqa: E402  (T-171/paket-ext: числа 2б/2в на листе; ExtStop — СТОП прогона)

ExtStop = X.ExtStop
import vetka_a_eval as E  # noqa: E402
import vetka_a_cmp_bd as CB  # noqa: E402  (EYE_D — мой глаз на d)

RE.SHEET_PATH = lambda sid: '%s/input/%s__d.jpg' % (E.A, sid)        # картинка листа для пересчёта рамки подписей — та же, что читает fit() и по которой строилось наложение
W = os.path.expanduser('~/remlab-logs/etazhi-walls')
PLANS = os.environ.get('SB_PLANS_DIR') or W + '/ru-plans'      # T-98/16: папка листов <id>/plan.* + listing.json (по умолчанию ru-plans)
U = W + '/ustroystvo'
R12 = W + '/vetka-a/12'
SHEETS = ['kazan-7065029', 'spb-10664362', 'kazan-14793283', 'kazan-14826118', 'kazan-11904669', 'ekb-10420322', 'kazan-14511278', 'kazan-10263001', 'kazan-14783942', 'kazan-13623941', 'ufa-10795859', 'kazan-9798362']
VARS = [('b', 'opus'), ('b', 'gpt'), ('d', 'gpt')]
UNITS = {'m': 1.0, 'cm': 0.01, 'mm': 0.001, 'ft': 0.3048, 'in': 0.0254}
TOUCH_M = 0.30
SUP_MIN, SUP_GAP = 0.5, 0.25
BAL = ('лодж', 'балкон', 'террас', 'loggia', 'balcon', 'terrace')


def has_ru_name(n):
    return any('а' <= c.lower() <= 'я' or c.lower() == 'ё' for c in (n or ''))


def is_balcony(n):
    n = (n or '').lower()
    return any(b in n for b in BAL)


def load(sid, var, model):
    p = '%s/%s/%s/%s/plan.json' % (R12, sid, var, model)
    return json.load(open(p)) if os.path.exists(p) else None


def level0(plan):
    lv = (plan or {}).get('levels') or []
    return lv[0] if lv else None


def poly_area(pts):
    a = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def get_rooms(plan, k):
    rooms = []
    for r in (level0(plan) or {}).get('rooms') or []:
        pg = r.get('polygon') or []
        if len(pg) < 3:
            continue
        q = [[float(x) * k, float(y) * k] for x, y in pg]
        g = Polygon(q)
        g = g if g.is_valid else g.buffer(0)
        if g.is_empty:
            continue
        a = r.get('area')
        rooms.append({'name': r.get('name') or '', 'id': r.get('id'), 'area': float(a) if isinstance(a, (int, float)) else None, 'geom': g, 'geo_area': poly_area(q)})
    return rooms


def opening_points(plan, k):
    """[(тип, центр (x,y), стена-вид, id)] для дверей и проходов (окна отдельно не нужны)"""
    lv = level0(plan) or {}
    walls = {w.get('id'): w for w in lv.get('walls') or [] if isinstance(w.get('from'), list) and isinstance(w.get('to'), list)}
    out = []
    for o in lv.get('openings') or []:
        t = o.get('type')
        if t not in ('door', 'passage'):
            continue
        w = walls.get(o.get('wall'))
        if not w:
            continue
        a = np.array(w['from'], float) * k
        b = np.array(w['to'], float) * k
        L = float(np.linalg.norm(b - a))
        if L < 1e-6:
            continue
        off, wd = float(o.get('offset') or 0) * k, float(o.get('width') or 0.8) * k
        c = a + (b - a) / L * min(max(off + wd / 2.0, 0), L)
        out.append({'type': t, 'c': (float(c[0]), float(c[1])), 'kind': w.get('kind'), 'id': o.get('id')})
    return out


# ---------- подгонка плана к чернилам листа (с кэшем) ----------
_FITS = {}


def fit(sid, plan, key):
    if key in _FITS:
        return _FITS[key]
    lv = level0(plan)
    walls = [w for w in (lv or {}).get('walls') or [] if isinstance(w.get('from'), list) and isinstance(w.get('to'), list)]
    if not walls:
        _FITS[key] = None
        return None
    img = cv2.imread('%s/input/%s__d.jpg' % (E.A, sid), cv2.IMREAD_COLOR)
    ink, dist, bb = E.ink_map(img)
    pts, wts = E.wall_samples(walls)
    p, sc = E.fit_plan(pts, dist, bb)
    s = p[0]
    tol = max(3.0, 0.10 * s)
    sup = E.support(p, pts, wts, dist, tol)
    ctrl = float(np.mean([E.support((s, p[1] + dx * s, p[2] + dy * s), pts, wts, dist, tol) for dx, dy in ((1.2, 0), (-1.2, 0), (0, 1.2), (0, -1.2), (1.5, 1.5), (-1.5, -1.5))]))
    res = {'s': float(s), 'tx': float(p[1]), 'ty': float(p[2]), 'sup': float(sup), 'ctrl': ctrl}
    _FITS[key] = res
    return res


# ---------- четыре признака ----------
def frame_cfg(rules=None):
    """T-ЦП рамка: настройка перевода подписей из сетки 0–1000 в пиксели (storozh_rules.json: labels_frame); выключена — None (как раньше)."""
    c = (rules or RULES).get('labels_frame') or {}
    return c if c.get('enabled') else None


def read_labels(sid, rules=None):
    """→ (подписи, (W, H) листа или None, причина отказа рамки или None). Выключатель labels_frame выкл — ровно прежний RE.parse_labels(sid)."""
    c = frame_cfg(rules)
    if not c:
        return RE.parse_labels(sid), None, None
    lab = RE.parse_labels(sid, frame=c.get('mode') or 'grid1000')
    return lab, (RE.sheet_wh(sid) if lab is not None else None), RE.LAST_REFUSAL.get(sid)


def drop_total_labels(labels, total, rules=None):
    """T-ЦП (Fable ответ 36 § замечания 4): подпись, равная ОБЩЕЙ площади объявления, — не комната (читатель берёт напечатанную общую площадь за комнату). За выключателем
    labels_total_not_room.enabled; не трогаем, если после выбрасывания осталось меньше min_others подписей. → (подписи, [выброшенные площади])."""
    c = (rules or RULES).get('labels_total_not_room') or {}
    if not c.get('enabled') or labels is None or not total:
        return labels, []
    tol = max(float(c.get('tol_abs', 0.15)), float(c.get('tol_rel', 0.03)) * total)
    drop = [l for l in labels if abs(l[2] - total) <= tol]
    if not drop or len(labels) - len(drop) < int(c.get('min_others', 2)):
        return labels, []
    return [l for l in labels if l not in drop], [l[2] for l in drop]


def labels_for(sid, rules=None):
    """Подписи листа так, как их видит guard(): рамка + «общая площадь — не комната»."""
    lab, _wh, _why = read_labels(sid, rules)
    return drop_total_labels(lab, listing_total(sid)[0], rules)[0]


def f1(rooms, labels):
    if labels is None or len(labels) < 3:
        return None, 'нет подписей на листе (класс Д)'
    ok = len(rooms) == len(labels)
    return ok, 'комнат %d, подписей %d' % (len(rooms), len(labels))


def register(rooms, labels, sheet=None, rules=None):
    """привязка подписей листа к плану ответа по напечатанной площади: пары (подпись, комната с той же заявленной площадью ±max(0,15; 3 %)),
    RANSAC по двум парам: независимый сдвиг+масштаб по осям (без поворота; у моделей масштаб по осям бывает разный), счёт — число подписей, лежащих в комнате той же площади.
    Возвращает {'ax','bx','ay','by','n','how'} или None. Оговорка: это согласованность ответа с подписями, не независимая проверка геометрии.
    T-ЦП рамка: порог «пара не годится, если подписи ближе 60» был в единицах сетки 0–1000; когда подписи уже в пикселях листа (sheet=(W, H)) — доля стороны листа (labels_frame.min_sep_frac = 0,06 = те же 60 из 1000)."""
    mdx = mdy = 60.0
    if sheet:
        fr = ((rules or RULES).get('labels_frame') or {}).get('min_sep_frac', 0.06)
        mdx, mdy = fr * sheet[0], fr * sheet[1]
    pairs = []
    for i, (x, y, a) in enumerate(labels):
        for j, r in enumerate(rooms):
            if r['area'] is not None and abs(r['area'] - a) <= max(0.15, 0.03 * a):
                pairs.append((i, j))
    if len(pairs) < 3:
        return None
    cen = [r['geom'].centroid for r in rooms]
    best = None
    for u in range(len(pairs)):
        for v in range(u + 1, len(pairs)):
            (i1, j1), (i2, j2) = pairs[u], pairs[v]
            if i1 == i2 or j1 == j2:
                continue
            dx, dy = labels[i2][0] - labels[i1][0], labels[i2][1] - labels[i1][1]
            if abs(dx) < mdx or abs(dy) < mdy:
                continue
            ax, ay = (cen[j2].x - cen[j1].x) / dx, (cen[j2].y - cen[j1].y) / dy
            if ax <= 0 or ay <= 0 or not 0.7 <= ax / ay <= 1.43:
                continue
            bx, by = cen[j1].x - ax * labels[i1][0], cen[j1].y - ay * labels[i1][1]
            good = 0
            for (i, j) in pairs:
                if rooms[j]['geom'].buffer(0.15).contains(Point(ax * labels[i][0] + bx, ay * labels[i][1] + by)):
                    good += 1
            if best is None or good > best['n']:
                best = {'ax': ax, 'bx': bx, 'ay': ay, 'by': by, 'n': good, 'how': 'по площадям'}
    if best is None or best['n'] < 3:
        return None
    return best


def p2_min_labels(rules=None):
    """T-ЦП круг 3б: наименьшее число подписей листа для привязки и П2 — 3, а при включённом p2_few_labels — min_labels (1). Выключено — 3, как было."""
    c = (rules or RULES).get('p2_few_labels') or {}
    return int(c.get('min_labels', 1)) if c.get('enabled') else 3


def f2(rooms, labels, ft, tr=None):
    m = p2_min_labels()
    if labels is None or len(labels) < m:
        return None, 'нет подписей на листе (класс Д)'
    if len(labels) < 3 and tr is None and ((RULES.get('p2_few_labels') or {}).get('unregistered') == 'none') and (ft is None or ft['sup'] < SUP_MIN or ft['sup'] - ft['ctrl'] < SUP_GAP):
        return None, 'подписей меньше 3, привязать не удалось — П2 не считаю'
    if tr is None:
        if ft is None or ft['sup'] < SUP_MIN or ft['sup'] - ft['ctrl'] < SUP_GAP:
            return False, 'не могу проверить: подписи не привязать к плану (по площадям — мало пар; подгонка к чернилам не взяла: опора %s, контроль %s)' % ('—' if ft is None else '%.2f' % ft['sup'], '—' if ft is None else '%.2f' % ft['ctrl'])
        tr = {'ax': 1.0 / ft['s'], 'bx': -ft['tx'] / ft['s'], 'ay': 1.0 / ft['s'], 'by': -ft['ty'] / ft['s'], 'n': 0, 'how': 'по чернилам'}
    cnt = [0] * len(rooms)
    out0, multi = 0, 0
    for (x, y, _a) in labels:
        px, py = tr['ax'] * x + tr['bx'], tr['ay'] * y + tr['by']
        hit = [i for i, r in enumerate(rooms) if r['geom'].buffer(0.15).contains(Point(px, py))]
        if not hit:
            out0 += 1
        if len(hit) >= 2:
            multi += 1
        for i in hit:
            cnt[i] += 1
    merged = sum(1 for c in cnt if c >= 2)
    empty = sum(1 for c in cnt if c == 0)
    bad = []
    if out0:
        bad.append('подписей вне комнат %d (комната пропущена)' % out0)
    if multi:
        bad.append('подписей в двух комнатах %d' % multi)
    if merged:
        bad.append('слитых комнат %d (в комнате ≥2 подписей)' % merged)
    if empty and not (len(labels) < 3 and (RULES.get('p2_few_labels') or {}).get('enabled') and (RULES.get('p2_few_labels') or {}).get('ignore_empty')):      # круг 3б: при 1–2 подписях комнат без подписи больше подписей — не дефект
        bad.append('лишних комнат %d (без подписи)' % empty)
    return (not bad), ('; '.join(bad) if bad else 'каждая подпись в одной комнате, в каждой комнате одна подпись')


OPEN_MIN_LEN, OPEN_COVER = 0.6, 0.5          # T-98/13: открытая граница = комнаты рядом, а стены на общей границе < половины
OUTLINE_PAD = 0.5                            # T-98/13: подпись дальше 0,5 м от объединения комнат ответа — чужая (соседняя квартира), не считается
AREA_TOL = 0.15                              # T-98/13: площадь ответа против цифры листа
EXTRA_MIN, EXTRA_INSIDE, EXTRA_PAD = 0.8, 0.7, 0.25   # T-98/13: лишняя стена — отрезок ≥ 0,8 м, ≥ 70 % длины внутри одной комнаты глубже 0,25 м
ROOM_N = re.compile(r'^\s*комната(\s+\d+)?\s*$', re.I)


def open_pairs(plan, rooms, k):
    """T-98/13: пары комнат с ОТКРЫТОЙ границей (пунктир на листе, кухня в прихожую): комнаты рядом (≤ 0,35 м), общая граница ≥ 0,6 м, стен на ней < 50 % → проход."""
    lv = level0(plan) or {}
    segs = []
    for w in lv.get('walls') or []:
        if isinstance(w.get('from'), list) and isinstance(w.get('to'), list):
            t = float(w.get('thickness') or 0.2) * k
            segs.append(LineString([(w['from'][0] * k, w['from'][1] * k), (w['to'][0] * k, w['to'][1] * k)]).buffer(max(t / 2.0, 0.08) + 0.05))
    wu = unary_union(segs) if segs else None
    out = set()
    for a in range(len(rooms)):
        for b in range(a + 1, len(rooms)):
            ga, gb = rooms[a]['geom'], rooms[b]['geom']
            if ga.distance(gb) > 0.35:
                continue
            inter = ga.buffer(0.25).intersection(gb.buffer(0.25))
            if inter.is_empty or inter.area < 1e-6:
                continue
            rect = inter.minimum_rotated_rectangle
            xs, ys = rect.exterior.coords.xy
            sides = sorted(math.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i]) for i in range(2))
            if sides[1] < OPEN_MIN_LEN:
                continue
            cover = 0.0 if wu is None else inter.intersection(wu).area / inter.area
            if cover < OPEN_COVER:
                out.add((a, b))
    return out


def f3(plan, rooms, k):
    ops = opening_points(plan, k)
    if len(rooms) < 2:
        return False, 'комнат меньше двух'
    touch = []
    for o in ops:
        pt = Point(*o['c'])
        touch.append([i for i, r in enumerate(rooms) if r['geom'].distance(pt) <= TOUCH_M])
    entrance = [i for i, t in enumerate(touch) if ops[i]['type'] == 'door' and len(t) == 1]   # T-98/13: вид стены не важен (вход с лестничной клетки Opus может поставить на «внутреннюю» стену)
    if not entrance:
        return False, 'нет входной двери квартиры (дверь, касающаяся ровно одной комнаты)'
    start = {touch[i][0] for i in entrance}
    adj = {i: set() for i in range(len(rooms))}
    for t in touch:
        for a in t:
            for b in t:
                if a != b:
                    adj[a].add(b)
    for a, b in open_pairs(plan, rooms, k):              # открытая граница — тоже проход
        adj[a].add(b)
        adj[b].add(a)
    seen, stack = set(start), list(start)
    while stack:
        a = stack.pop()
        for b in adj[a]:
            if b not in seen:
                seen.add(b)
                stack.append(b)
    lost = [rooms[i]['name'] or ('#%d' % (i + 1)) for i in range(len(rooms)) if i not in seen]
    if lost:
        return False, 'без входа (нет двери/прохода к нему от входной): ' + ', '.join(lost[:6]) + ('…' if len(lost) > 6 else '')
    return True, 'входная дверь есть, все %d комнат достижимы' % len(rooms)


RULES = json.load(open(os.environ.get('SB_RULES') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'storozh_rules.json'), encoding='utf-8'))   # T-98/19: правила звонок/справка по модели, П4 — всё здесь


def wall_cut(plan, k):
    """T-98/19: объединение полос стен ответа (толщины — storozh_rules.json) или None. Один источник для inner_areas и подтяжки."""
    th = RULES['p4']['wall_thickness_m']
    strips = []
    for w in (level0(plan) or {}).get('walls') or []:
        if not (isinstance(w.get('from'), list) and isinstance(w.get('to'), list)):
            continue
        t = th['exterior'] if w.get('kind') == 'exterior' else th['interior']
        a = np.array(w['from'], float) * k
        b = np.array(w['to'], float) * k
        if float(np.linalg.norm(b - a)) < 1e-6:
            continue
        strips.append(LineString([tuple(a), tuple(b)]).buffer(t / 2.0, cap_style=2))
    return unary_union(strips) if strips else None


def inner_areas(plan, rooms, k):
    """T-98/19: площадь каждой комнаты по ВНУТРЕННИМ граням стен: контур комнаты (идёт по осям) минус полоса полутолщины вдоль каждой стены ответа (wall_cut; толщины — storozh_rules.json,
    типовые, заданы до счёта). Комната без стены на краю (открытая планировка) не уменьшается на этом краю."""
    cut = wall_cut(plan, k)
    out = []
    for r in rooms:
        g = r['geom'] if cut is None else r['geom'].difference(cut)
        out.append(float(g.area))
    return out


def f4(plan, rooms, k, total):
    """T-98/19 (Fable 16 §4): сумма по ГЕОМЕТРИИ (внутренние грани), заявленные площади ответа — не свидетель (на 13 из 15 подогнаны к объявлению).
    Объявление то с лоджией, то без — сверяем с двумя суммами (без балконов / с балконами), проходит любая. Полоса и режим — storozh_rules.json (p4)."""
    if total is None:
        return None, 'в объявлении нет общей площади'
    ia = inner_areas(plan, rooms, k)
    s_all = sum(ia)
    s_nb = sum(a for a, r in zip(ia, rooms) if not is_balcony(r['name']))
    lo, hi = RULES['p4']['band']['lo'], RULES['p4']['band']['hi']
    r_nb, r_all = s_nb / total, s_all / total
    ok = (lo <= r_nb <= hi) or (lo <= r_all <= hi)
    return ok, 'по внутренним граням: без балконов %.1f из %.1f = %.2f; с балконами %.1f = %.2f (полоса %.2f…%.2f, проходит любая)' % (s_nb, total, r_nb, s_all, r_all, lo, hi)


def listing_total(sid):
    t = ((json.load(open('%s/%s/listing.json' % (PLANS, sid))).get('obyavlenie') or {}).get('dlya_llm')) or ''
    import re
    m = re.search(r'общая\s*([\d,\.]+)', t)
    return float(m.group(1).replace(',', '.')) if m else None, t


def residential(rooms):
    return sum(1 for r in rooms if any(w in (r['name'] or '').lower() for w in ('комнат', 'спальн', 'гостин', 'детск', 'кабинет', 'зал')))


def to_plan(tr, ft):
    """T-98/13: перевод точки подписи листа в метры плана (привязка по площадям, иначе подгонка к чернилам, иначе None)."""
    if tr is not None:
        return tr
    if ft is not None and ft['sup'] >= SUP_MIN and ft['sup'] - ft['ctrl'] >= SUP_GAP:
        return {'ax': 1.0 / ft['s'], 'bx': -ft['tx'] / ft['s'], 'ay': 1.0 / ft['s'], 'by': -ft['ty'] / ft['s']}
    return None


def wall_shell(plan, k):
    """T-98/13: выпуклая оболочка всех стен ответа (+0,3 м); None, если стен нет."""
    pts = []
    for w in (level0(plan) or {}).get('walls') or []:
        if isinstance(w.get('from'), list) and isinstance(w.get('to'), list):
            pts += [(w['from'][0] * k, w['from'][1] * k), (w['to'][0] * k, w['to'][1] * k)]
    if len(pts) < 3:
        return None
    return LineString(pts).convex_hull.buffer(0.3)


def own_labels(rooms, labels, T, shell=None):
    """T-98/13: подписи своей квартиры. Отбрасывает подпись дальше 0,5 м от объединения комнат ответа — чужая квартира на листе.
    → (свои подписи, число чужих, 0)"""
    if T is None or not rooms or not labels:
        return list(labels or []), 0, 0
    uni = unary_union([r['geom'] for r in rooms]).buffer(OUTLINE_PAD)
    if shell is not None:           # подпись внутри оболочки стен ответа — своя (комнату могли потерять); чужая — снаружи всех стен
        uni = unary_union([uni, shell])
    pts = [(lb, Point(T['ax'] * lb[0] + T['bx'], T['ay'] * lb[1] + T['by'])) for lb in labels]
    mine = [(lb, p) for lb, p in pts if uni.contains(p)]
    foreign = len(pts) - len(mine)
    # правило «лишняя подпись в комнате» (плита 6,0 у ufa) ОТМЕНЕНО: оно прячет и удалённую комнату (её подпись падает в соседнюю) — контроль не пройден
    return [lb for lb, _p in mine], foreign, 0


def f5(rooms):
    """T-98/13: имя не по-русски — латинские буквы в названии комнаты."""
    lat = [r['name'] for r in rooms if NN.is_english(r['name'])]       # тот же is_english, что у р.5 (voronka/neutral_names.py)
    return (not lat), ('названия по-русски' if not lat else 'имя не по-русски: ' + ', '.join(lat[:5]) + ('…' if len(lat) > 5 else ''))


def words_r5(sid):
    """T-98/15: флаг «на листе есть имена словами» — из ОДНОЙ точки с р.5: words_on_sheet.flag_for (OCR, кэш по sha256 файла листа); True/False.
    Нет листа/OCR → запасной путь, как у р.5 сейчас: глаз `voronka/words_eye.json`; нет и там → None (неизвестно)."""
    try:
        d = PLANS + '/' + sid
        sheet = next(d + '/' + f for f in sorted(os.listdir(d)) if f.startswith('plan.'))
        fl = WS.flag_for(sheet)
        if fl is not None:
            return bool(fl['words'])
    except (OSError, StopIteration, ValueError):
        pass
    try:
        return json.load(open(os.path.dirname(os.path.abspath(NN.__file__)) + '/words_eye.json', encoding='utf-8')).get(sid)
    except (OSError, ValueError):
        return None


def f6(plan, words):
    """T-98/13: имя без опоры на лист — ОДНА функция с р.5: `neutral_names.neutral(plan, words)` (слов на листе нет → «Комната N», кухня/санузел — только при видимой плите/сантехнике).
    Звонок = комнаты, которые р.5 заменил бы на «Комната N» (догадка); английские — это П5; перенумерация дублей и заглавная буква — не догадка."""
    if words is None or not plan:
        return None, 'на листе слова неизвестно (флаг не получен)'
    if words is True:
        return None, 'на листе имена словами есть (правило п.10 не применяется)'
    _new, rep = NN.neutral(plan, False)
    guess = [old for (_i, old, nw) in rep['переименовано'] if (old or '').strip() and not ROOM_N.match(old or '') and ROOM_N.match(nw or '') and not NN.is_english(old)
             and re.sub(r'[\d\s.()\-]+', '', str(old)).lower() not in ('', 'комната')]    # «3», «1 Комната» — номер/нейтральное имя с листа, не догадка
    return (not guess), ('имена «Комната N» или с опорой (плита/сантехника)' if not guess else 'имя без опоры на лист (слов на листе нет): ' + ', '.join(guess[:6]) + ('…' if len(guess) > 6 else ''))


def f7z(rooms, labels, T):
    """(старый П7, T-98/13; с T-98/19 — только справка «П7з») площадь ответа ≠ цифре листа > 0,15 м² (лучшая по значению подпись в комнате; подписи — свои)."""
    if T is None or not labels:
        return None, 'нет привязки подписей'
    by = {}
    for lb in labels:
        p = Point(T['ax'] * lb[0] + T['bx'], T['ay'] * lb[1] + T['by'])
        for j, r in enumerate(rooms):
            if r['area'] is not None and r['geom'].buffer(0.15).contains(p):
                by.setdefault(j, []).append(lb[2])
    bad = []
    for j, vs in by.items():
        best = min(vs, key=lambda v: abs(v - rooms[j]['area']))
        if abs(best - rooms[j]['area']) > AREA_TOL:
            bad.append('«%s»: ответ %.2f, на листе %.2f' % (rooms[j]['name'], rooms[j]['area'], best))
    return (not bad), ('площади сходятся с листом (±%.2f)' % AREA_TOL if not bad else 'площадь ≠ листу: ' + '; '.join(bad[:4]) + ('…' if len(bad) > 4 else ''))


def room_ratios(plan, rooms, k, labels_own, T):
    """T-98/19: по каждой своей комнате с цифрой листа → {'j','имя','цифра','а'}, а = площадь по ВНУТРЕННИМ граням стен / цифра листа (цифра вернее рисунка — владелец TG 3494).
    Привязка подписи к комнате — containment (+0,15 м) через T; если в комнате несколько подписей — ближайшая по значению к заявленной (иначе к геометрической) площади."""
    if T is None or not labels_own:
        return []
    ia = inner_areas(plan, rooms, k)
    by = {}
    for lb in labels_own:
        p = Point(T['ax'] * lb[0] + T['bx'], T['ay'] * lb[1] + T['by'])
        for j, r in enumerate(rooms):
            if r['geom'].buffer(0.15).contains(p):
                by.setdefault(j, []).append(lb)
    out = []
    for j, vs in sorted(by.items()):
        ref = rooms[j]['area'] if rooms[j]['area'] is not None else ia[j]
        lb = min(vs, key=lambda t: abs(t[2] - ref))
        if lb[2] > 0:
            out.append({'j': j, 'имя': rooms[j]['name'], 'цифра': lb[2], 'а': ia[j] / lb[2]})
    return out


def _p7g_ref(rr):
    """нормировка: медиана (а) по комнатам листа (не балкон, цифра ≥ min, отношение в «здравых» пределах); < N таких комнат → общая медиана из json. → (m, elig, как)"""
    c = RULES['p7g']
    elig = [r for r in rr if not is_balcony(r['имя']) and r['цифра'] >= c['min_label_m2'] and c['sanity'][0] <= r['а'] <= c['sanity'][1]]
    if len(elig) >= c['min_rooms_for_median']:
        pool = float(np.median([r['а'] for r in elig]))
        qmap = {}
        for r in rr:
            if r in elig:           # leave-one-out: медиана ДРУГИХ комнат листа (иначе раздутая комната на листе из 3 комнат сама становится медианой и маскирует себя)
                qmap[r['j']] = r['а'] / float(np.median([o['а'] for o in elig if o is not r]))
            else:
                qmap[r['j']] = r['а'] / pool
        return qmap, elig, 'медиана остальных комнат листа'
    return {r['j']: r['а'] / c['glob_median'] for r in rr}, elig, 'общая медиана'


def f7g(plan, rooms, k, labels_own, T):
    """T-98/19 (директор, владелец TG 3494 «цифра вернее рисунка»): П7 теперь по ГЕОМЕТРИИ ответа, а не по заявленной площади (она подгонялась и скрывала «раздуть ×1,25»).
    Комната с цифрой на листе: q = (а) / медиана (а) ДРУГИХ комнат листа (leave-one-out; < 3 комнат — общая медиана); q вне полосы p7g.band → звонок.
    Малые (< min_label_m2) и балконы по имени — не считаются (q для них — справочно). → (ok|None, причина, детали: rr, qmap {j: q}, вне, проверено)"""
    rr = room_ratios(plan, rooms, k, labels_own, T)
    if not rr:
        return None, 'нет комнат с цифрой листа', {'rr': []}
    qmap, elig, how = _p7g_ref(rr)
    lo, hi = RULES['p7g']['band']['lo'], RULES['p7g']['band']['hi']
    if not elig:
        return None, 'нет комнат с цифрой ≥ %.0f м² (не балкон)' % RULES['p7g']['min_label_m2'], {'rr': rr, 'qmap': qmap}
    bad = [r for r in elig if not lo <= qmap[r['j']] <= hi]
    det = {'rr': rr, 'qmap': qmap, 'как': how, 'вне': [(r['имя'], r['цифра'], round(r['а'], 2), round(qmap[r['j']], 2)) for r in bad], 'проверено': len(elig)}
    txt = ('площадь по геометрии сходится с цифрами листа (%d комн., норма — %s, полоса %.2f…%.2f)' % (len(elig), how, lo, hi)) if not bad else \
        'геометрия ≠ цифре листа: ' + '; '.join('«%s»: на листе %.1f, в ответе %.1f (%.2f от нормы листа)' % (r['имя'], r['цифра'], r['а'] * r['цифра'], qmap[r['j']]) for r in bad[:4]) + ('…' if len(bad) > 4 else '')
    return (not bad), txt, det


def f7s(plan, rooms, k):
    """T-98/19: П7с «контур комнаты держится на стенах ответа» — доля периметра комнаты в пределах p7s.tol_m от оси какой-либо стены ответа ≥ p7s.min_share (комнаты ≥ min_room_m2, не балкон).
    Не нужны цифры листа (годится для класса Д). Ловит комнату, чей контур разошёлся со стенами (в т.ч. «раздуть ×1,25» контрольной поломки). Оговорка: поломка, в которой стены двигаются вместе с комнатой, этим не видна — её ловит только П7г (цифры)."""
    c = RULES['p7s']
    lines = [LineString([(w['from'][0] * k, w['from'][1] * k), (w['to'][0] * k, w['to'][1] * k)]) for w in (level0(plan) or {}).get('walls') or [] if isinstance(w.get('from'), list) and isinstance(w.get('to'), list)]
    if not lines:
        return None, 'в ответе нет стен'
    wu = unary_union(lines).buffer(c['tol_m'])
    bad = []
    n = 0
    for r in rooms:
        if r['geom'].area < c['min_room_m2'] or is_balcony(r['name']):
            continue
        b = r['geom'].exterior
        if b.length <= 0:
            continue
        n += 1
        sh = float(b.intersection(wu).length / b.length)
        if sh < c['min_share']:
            bad.append((r['name'], sh))
    if n == 0:
        return None, 'нет комнат ≥ %.0f м²' % c['min_room_m2']
    return (not bad), ('контуры комнат держатся на стенах (%d комн., порог %.2f на ±%.2f м)' % (n, c['min_share'], c['tol_m']) if not bad else
                       'контур комнаты разошёлся со стенами ответа: ' + '; '.join('«%s» — %.0f %% периметра на стенах' % (nm, 100 * s) for nm, s in bad[:4]) + ('…' if len(bad) > 4 else ''))


def f10(det):
    """T-98/19: «комната вне контура?» — малая комната с номером вместо имени («9», «Комната 9»), цифра на листе ≤ max_label_m2 и q вне полосы: похоже на балкон/лоджию, нарисованный внутри контура."""
    if not det or not det.get('rr'):
        return None, 'нет комнат с цифрой листа'
    c = RULES['p10']
    lo, hi = RULES['p7g']['band']['lo'], RULES['p7g']['band']['hi']
    qm = det['qmap']
    bad = [r for r in det['rr'] if (not any(ch.isalpha() for ch in r['имя']) or ROOM_N.match(r['имя'])) and not is_balcony(r['имя']) and r['цифра'] <= c['max_label_m2'] and not lo <= qm[r['j']] <= hi]
    return (not bad), ('нет малых безымянных комнат вне нормы' if not bad else 'комната вне контура? «%s»: малая безымянная, на листе %.1f м², в ответе %.1f (балкон/лоджия?)' % (bad[0]['имя'], bad[0]['цифра'], bad[0]['а'] * bad[0]['цифра']) + ('; ещё %d' % (len(bad) - 1) if len(bad) > 1 else ''))


def f8(plan, rooms, k):
    """T-98/13: лишняя стена — отрезок стены ≥ 0,8 м, ≥ 70 % длины которого лежит внутри одной комнаты глубже 0,25 м от её границы."""
    bad = []
    for w in (level0(plan) or {}).get('walls') or []:
        if not (isinstance(w.get('from'), list) and isinstance(w.get('to'), list)) or w.get('kind') == 'exterior':
            continue
        a = np.array(w['from'], float) * k
        b = np.array(w['to'], float) * k
        L = float(np.linalg.norm(b - a))
        if L < EXTRA_MIN:
            continue
        u = (b - a) / L
        nrm = np.array([-u[1], u[0]])
        votes, why = 0, ''
        for t in (0.25, 0.5, 0.75):
            c = a + u * L * t
            side = []
            for sgn in (1, -1):
                p = Point(*(c + nrm * sgn * EXTRA_PAD))
                side.append(next((i for i, r in enumerate(rooms) if r['geom'].buffer(0.1).contains(p)), None))
            if side[0] is None and side[1] is None:
                votes += 1
                why = 'с обеих сторон пусто'
            elif side[0] == side[1]:
                votes += 1
                why = 'с обеих сторон «%s»' % rooms[side[0]]['name']
        if votes >= 2:
            bad.append('%s (%.1f м): %s' % (w.get('id'), L, why))
    return (not bad), ('лишних стен нет' if not bad else 'лишняя стена: ' + '; '.join(bad[:4]) + ('…' if len(bad) > 4 else ''))


def guard(sid, var, model, plan, key, overlay=None, ov=None):
    """→ dict признаки+исход. overlay — статус наложения листа («легло»/«частично»/«не легло»/«не проверено») или None (ворота не применяются; T-98/19, Fable 17 §7).
    ov — числа наложения (содержимое overlay.json: «на_линии», …) — для порога правила overlay_fail (T-171/nalozhenie, решение Fable 27.11); нет — правило считает «не легло» без смягчения"""
    res = {'лист': sid, 'вар': var, 'модель': model}
    if ov and ov.get('ext_статус'):
        res['ext_статус'] = ov['ext_статус']      # T-171/paket-ext: «не применяется: …» / статусы чисел 2б/2в — не молча (storozh.with_ext_live)
    if plan is None:
        res.update(исход='отказ — ответ не разобрался (нет plan.json)', П1=None, П2=None, П3=None, П4=None, п1='', п2='', п3='', п4='', комнат=0, подписей=None, класс='?')
        return res
    units = plan.get('units') or 'm'
    k = UNITS.get(units, 1.0)
    rooms = get_rooms(plan, k)
    labels, sheet, frame_why = read_labels(sid)
    total, dl = listing_total(sid)
    labels, dropped_total = drop_total_labels(labels, total)
    if frame_why:
        res['рамка_отказ'] = frame_why
    if dropped_total:
        res['подпись_общая'] = dropped_total
    res.update(комнат=len(rooms), подписей=None if labels is None else len(labels), класс='Д' if (labels is None or len(labels) < 3) else 'с подписями', жилых_в_ответе=residential(rooms), dlya_llm=dl)
    if len(rooms) < 2:
        res.update(исход='отказ — в ответе комнат %d' % len(rooms), П1=None, П2=None, П3=None, П4=None, п1='', п2='', п3='', п4='')
        return res
    ft = tr = T = None
    res['привязка_подписей'] = 'нет подписей'
    labels_own, n_foreign, n_extra = labels, 0, 0
    if labels is not None and len(labels) >= p2_min_labels() and units == 'm':
        tr = register(rooms, labels, sheet)
        if tr is None:
            ft = fit(sid, plan, key)
        T = to_plan(tr, ft)
        res['привязка_подписей'] = tr['how'] if tr is not None else ('по чернилам' if T is not None else 'не привязать')      # T-ЦП рамка: каким путём подписи листа привязаны к плану (в мерку и таблицы; на звонки не влияет)
        labels_own, n_foreign, n_extra = own_labels(rooms, labels, T, wall_shell(plan, k))      # T-98/13 (а): чужие подписи (соседние квартиры) и «плиту 6,0» не считаем
    p1, r1 = f1(rooms, labels_own)
    if n_foreign or n_extra:
        r1 += ' (не считал: чужих подписей %d, лишних в комнате %d)' % (n_foreign, n_extra)
    p2, r2 = f2(rooms, labels_own, ft, tr) if units == 'm' else (False, 'единицы %s, не метры — не проверяю' % units)
    if tr is not None and p2 is not None:
        r2 = '[привязка %s, %d пар] ' % (tr['how'], tr['n']) + r2
    p3, r3 = f3(plan, rooms, k)
    p4, r4 = f4(plan, rooms, k, total)
    p5, r5 = f5(rooms)
    p6, r6 = f6(plan, words_r5(sid))
    has_lab = labels is not None and len(labels) >= 3 and units == 'm'
    p7, r7, d7 = f7g(plan, rooms, k, labels_own, T) if has_lab else (None, 'нет подписей листа', {})        # T-98/19: П7 по ГЕОМЕТРИИ (было — по заявленной площади ответа, она подгонялась)
    p7z, r7z = f7z(rooms, labels_own, T) if has_lab else (None, 'нет подписей листа')                        # старый П7 — теперь только справка «П7з»
    p10, r10 = f10(d7) if has_lab else (None, 'нет подписей листа')
    p7s, r7s = f7s(plan, rooms, k)
    p8, r8 = f8(plan, rooms, k)
    res.update(П7с=p7s, п7с=r7s, П7з=p7z, п7з=r7z, П10=p10, п10=r10, п7_детали={kk: v for kk, v in d7.items() if kk != 'rr'}, комнат_с_цифрой=len(d7.get('rr') or []))
    res.update(П1=p1, П2=p2, П3=p3, П4=p4, П5=p5, П6=p6, П7=p7, П8=p8, п1=r1, п2=r2, п3=r3, п4=r4, п5=r5, п6=r6, п7=r7, п8=r8, чужих_подписей=n_foreign, лишних_подписей=n_extra)
    names = [r['name'] for r in rooms]
    res['названия_русские'] = sum(1 for n in names if has_ru_name(n))
    # T-98/19 (Fable 16): ЖЁСТКИЙ звонок только у признаков из storozh_rules.json для этой модели ответа; остальные «нет» — справка (в таблицу, без звонка)
    all_f = [(nm, r, p) for nm, (p, r) in zip(('П1', 'П2', 'П3', 'П4', 'П5', 'П6', 'П7', 'П8', 'П7з', 'П10', 'П7с'), ((p1, r1), (p2, r2), (p3, r3), (p4, r4), (p5, r5), (p6, r6), (p7, r7), (p8, r8), (p7z, r7z), (p10, r10), (p7s, r7s))) if p is False]
    bad, info = split_features(all_f, model, overlay, ov=ov)
    info = with_area_flag(res, info, plan, rooms, d7, overlay, ov)
    return finish(res, bad, info, overlay, ov=ov)


def with_area_flag(res, info, plan, rooms, d7, overlay, ov):
    """T-171 флажок площади (Fable ❓25/❓26): справка листа, не звонок. Выключатель area_flag.enabled (storozh_rules.json) ВЫКЛ — info возвращается как есть, res не тронут (вывод побайтно прежний)."""
    if not (RULES.get('area_flag') or {}).get('enabled'):
        return info
    return info + area_flag_info(res, plan, rooms, d7, overlay, ov)


def _area_flag_module():
    """T-171 флажок площади: модуль area_flag (tools/floorplan/area_flag.py) — ОДИН источник счёта и чисел; в storozh_rules.json (area_flag) — их копия для глаза.
    Расхождение json ↔ модуль — остановка с причиной (молчаливого сбоя нет). Путь модуля: AREA_FLAG_DIR или module_dir из правил (относительный — от папки этого файла)."""
    cfg = RULES['area_flag']
    d = os.path.expanduser(os.environ.get('AREA_FLAG_DIR') or cfg['module_dir'])
    d = os.path.normpath(d if os.path.isabs(d) else os.path.join(os.path.dirname(os.path.abspath(__file__)), d))
    if d not in sys.path:
        sys.path.insert(0, d)
    import area_flag as AF  # noqa: E402
    for key, val in (('boundary', AF.BOUNDARY), ('cond_ext_m', AF.COND_EXT_M), ('cond_int_m', AF.COND_INT_M), ('typ_ext_m', AF.TYP_EXT_M), ('typ_int_m', AF.TYP_INT_M)):
        if abs(float(cfg[key]) - val) > 1e-12:
            raise RuntimeError('area_flag: %s в storozh_rules.json (%s) ≠ в модуле %s (%s)' % (key, cfg[key], AF.__file__, val))
    return AF


def area_flag_info(res, plan, rooms, d7, overlay, ov):
    """→ [(‘Пл’, текст)] для справки листа. Подписи комнат — та же привязка, что у П7 (d7['rr']: комната ↔ цифра листа). На исход/звонки не влияет. Детали — res['площадь_флажок']."""
    AF = _area_flag_module()
    printed = {}
    for x in (d7 or {}).get('rr') or []:
        rid = rooms[x['j']].get('id')
        if rid is not None:
            printed[rid] = x['цифра']
    ovd = dict(ov or {})
    ovd.setdefault('overlay_status', overlay)
    ev = AF.evaluate(plan, printed, overlay=ovd, boundary=float(RULES['area_flag']['boundary']))
    res['площадь_флажок'] = {'группа_толщины': ev['mode'], 'схема': ev['scheme'], 'флажки': [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in f.items()} for f in ev['flags']], 'пропущено': ev['skipped'], 'строки': ev['lines']}
    out = []
    if ev['lines']:
        out.append(('Пл', '; '.join(ev['lines'])))
    for rid, why in ev['skipped']:
        if rid == '*':
            out.append(('Пл', 'флажок площади не посчитан: %s' % why))
    return out


def p3_only_loggia(reason, cfg):
    """T-171 задача 3 (Fable otvet-33): П3 «без входа» звонит зря, когда без входа ТОЛЬКО лоджии/балконы (двери на балкон на листах часто не рисуют; по глазу 0 из 2 по делу). Причина П3 из f3: «без входа (…): имя, имя».
    Список обрезан («…») или есть другое помещение — не смягчаем. Слова — storozh_rules.json (p3_loggia_soft.name_keywords)."""
    if not reason.startswith('без входа'):
        return False
    names = reason.partition(': ')[2]
    if not names or names.endswith('…'):
        return False
    kw = [k.lower() for k in cfg.get('name_keywords', [])]
    items = [x.strip() for x in names.split(', ') if x.strip()]
    return bool(items) and bool(kw) and all(any(k in it.lower() for k in kw) for it in items)


def clean_overlay(overlay, ov, cfg):
    """T-ЦП круг 3 (Fable otvet-35 § 5): наложение ЧИСТОЕ — статус из clean_statuses («легло»), «на линии» ≥ clean_line_min (0,75), доля выдуманных стен (по длине, walls.csv) < clean_fab_max (5 %).
    Нет числа «на линии» или списка стен (ov без «стены») — НЕ чистое: звонок остаётся (осторожно, как у «Ст»)."""
    if overlay not in (cfg.get('clean_statuses') or ['легло']):
        return False
    line = (ov or {}).get('на_линии')
    walls = (ov or {}).get('стены')
    if not isinstance(line, (int, float)) or line < cfg.get('clean_line_min', 0.75) or walls is None:
        return False
    tot = sum(w['длина_px'] for w in walls)
    fab = sum(w['длина_px'] for w in walls if w['класс'] == 'выдуманная')
    return (fab / tot if tot else 0.0) < cfg.get('clean_fab_max', 0.05)


def split_features(all_f, model, overlay, rules=None, ov=None):
    """ОДНО место разбора «жёсткий звонок / справка» (guard и тест регресса по сохранённым ответам). all_f — [(имя, причина, p)] провалившихся признаков листа.
    Жёсткие — по модели ответа (storozh_rules.json: hard_by_model, П4 по p4.mode); ворота наложения (overlay_gate) гасят П1–П3 в справку; T-171 задача 3: demote_to_info — признаки в справку
    (П7с: по делу 2 из 7), p3_loggia_soft — П3 в справку, если без входа только лоджии/балконы. Правила выключены — разбор прежний (порядок справки тот же)."""
    R = rules or RULES
    hard = set(R['hard_by_model'].get(model) or R['hard_by_model']['other'])
    if R['p4']['mode'] == 'hard':
        hard.add('П4')
    gate = R.get('overlay_gate') or {}
    gated = overlay is not None and overlay not in (gate.get('pass_status') or ['легло'])
    dem = R.get('demote_to_info') or {}
    soft = set(dem.get('features', [])) if dem.get('enabled') else set()
    if soft and dem.get('clean_only') and not clean_overlay(overlay, ov, dem):         # T-ЦП круг 3: в справку только при чистом наложении, иначе звонок остаётся
        soft = set()
    p3s = R.get('p3_loggia_soft') or {}
    bad, info, info_g = [], [], []
    for n, r, _ in all_f:
        h = n in hard and n not in soft and not (n == 'П3' and p3s.get('enabled') and p3_only_loggia(r, p3s))
        if not h:
            info.append((n, r))
        elif gated and n in gate.get('features', []):
            info_g.append((n, 'рисунок не подтвердил (наложение «%s») — %s' % (overlay, r)))
        else:
            bad.append((n, r))
    return bad, info + info_g


def read_walls(path):
    """walls.csv наложения → [{'стена','длина_px','класс'}] (для звонка «стены»); нет файла — None"""
    import csv
    try:
        rows = list(csv.DictReader(open(path, encoding='utf-8')))
    except OSError:
        return None
    out = []
    for r in rows:
        try:
            out.append({'стена': r['стена'], 'длина_px': float(r['длина_px']), 'класс': r['класс']})
        except (KeyError, ValueError, TypeError):
            continue
    return out


def with_walls(ov, overlay_dir):
    """копия чисел наложения (overlay.json) + список стен из walls.csv — вход звонка «стены» (walls_fail); overlay.json на диске не меняется"""
    o = dict(ov or {})
    w = read_walls(overlay_dir + '/walls.csv')
    if w is not None:
        o['стены'] = w
    return o


def with_ext(ov, ext_path):
    """T-ЦП круг 2б: добавочные числа наложения листа (cikl/stolb2b_ext.py, <лист>/ext2b.json) → ov['ext2b']; нет файла или статус не «ok» — ov без изменений (звонок «Ст» считается как раньше)"""
    try:
        e = json.load(open(ext_path, encoding='utf-8'))
    except (OSError, ValueError):
        return ov
    if e.get('статус') != 'ok':
        return ov
    o = dict(ov or {})
    o['ext2b'] = e
    return o


def with_ext2c(ov, ext_path):
    """T-ЦП круг 2в: числа «без окон» листа (cikl/stolb2c_ext.py, <лист>/ext2c.json) → ov['ext2c']; нет файла или статус не «ok» — ov без изменений (звонок «Ст» считается как раньше)"""
    try:
        e = json.load(open(ext_path, encoding='utf-8'))
    except (OSError, ValueError):
        return ov
    if e.get('статус') != 'ok':
        return ov
    o = dict(ov or {})
    o['ext2c'] = e
    return o


def with_ext_live(ov, sid, plan_clean, plan, img_d, img_b, fit, rows, vf, rules=None):
    """T-171/paket-ext (rab-9, OTCHET-ext.md «Строка вызова»; Fable 27.11 22:57): числа 2б/2в считаются НА ЛИСТЕ (ext.py) — вместо файловых with_ext / with_ext2c (папок --ext-dir в живом прогоне нет).
    Место вызова — где собирается ov после with_walls (rows = стены наложения, walls.csv); fit — fit.json; vf — модуль vetka_fit той же сборки (CORRECT_V2=1, SOFT_INK=1 в окружении ДО его импорта, иначе ext отказывает).
    Нужно, если включён хотя бы один из wide_line / pale_line (2б) / windows (2в); выключены все — числа не считаются (ov, {}). Для одного 2б на годном листе — только когда «Ст» звонит по базовым числам (экономия, как в мерке).
    Дальше решает ext.coverage (rab-9):
      • наложения нет / не «легло» / вход не «как есть» → «не применяется: причина» — пометка в ov['ext_статус'] (→ guard.json, поле ext_статус), числа не считаются, прогон идёт, «Ст» как раньше;
      • наложение «легло», а входа для расчёта нет (walls.csv, fit.json, картинка или ответ листа) → ext.ExtStop = storozh.ExtStop: СТОП прогона с причиной (выключатель ВКЛ, числа пропали по ошибке — тихо не продолжаем);
      • числа посчитаны, но статус «сбой: …» / «отказ: …» (исключение в расчёте / vetka_fit настроен не так) → тоже ExtStop; «не сошлось с walls.csv» — штатно (числа 2б/2в этого листа не берём, «Ст» как раньше).
    → (ov, статусы {'ext2b': …, 'ext2c': …, 'лист_для_ext': …, 'причина': …}); поля ext2b / ext2c в ov только при статусе ok."""
    wf = (rules or RULES)['walls_fail']
    need2b = bool((wf.get('wide_line') or {}).get('enabled') or (wf.get('pale_line') or {}).get('enabled'))
    need2c = bool((wf.get('windows') or {}).get('enabled'))
    if not (need2b or need2c):
        return ov, {}
    if need2b and not need2c and X.applicable(ov, rows) and not X.current_hit(rows, ov, wf):
        return ov, {}
    cands = X.candidates({'plan-clean.json': plan_clean, 'plan.json': plan}, {'d': img_d, 'b': img_b})
    o, st = X.with_ext_numbers(ov, sid, cands, fit, rows, vf, want_2b=need2b, want_2c=need2c)       # ExtStop (пропал вход при «легло») — не ловим: СТОП
    for k in ('ext2b', 'ext2c'):
        if str(st.get(k) or '').startswith(('сбой', 'отказ', 'стоп', 'СТОП')):         # «стоп: нет масштаба» (ext.no_scale) — тоже СТОП, а не молчаливое «Ст как раньше»
            raise ExtStop('%s: числа %s не посчитаны — %s' % (sid, k, st[k]))
    if st.get('лист_для_ext'):
        o['ext_статус'] = st
    return o, st


def finish(res, bad, info, overlay, rules=None, ov=None):
    """Сборка звонков/справки/исхода из уже посчитанных признаков (bad — жёсткие [(имя, причина)], info — справка). Вынесено из guard(), чтобы правило наложения проверялось
    без перечитывания листа (тест регресса по сохранённым guard.json) — признаки не пересчитываются, логика сборки та же."""
    # T-171/nalozhenie (Fable otvet-32 §А): статус наложения — часть исхода. «не легло» = чернила найдены, а план с ними не совпал → жёсткий звонок «Нал» (на правку агенту);
    # «частично» → не «готово» и не звонок, а «сверено частично». «не проверено» и overlay=None (нет наложения) — как раньше. Статусы и имя признака — storozh_rules.json (overlay_fail).
    # Решение Fable 27.11 (после глаза директора: ложных Нал 3 из 19 = 16 на 100 > 10): «не легло» звонит Нал только по ЧИСЛУ — «на линии» < fail_line_max (в storozh_rules.json);
    # «не легло» с «на линии» ≥ порога → «сверено частично» (причина «чернила листа не объяснены ответом»), не «готово» и не звонок. Нет числа («на_линии» не передано) → звонок, как до порога.
    bad = list(bad)
    of = (rules or RULES).get('overlay_fail') or {}
    partial = False
    why_partial = 'рисунок лёг не весь'
    line = (ov or {}).get('на_линии')
    if of.get('enabled') and overlay is not None:
        if overlay in of.get('fail_statuses', []):
            lmax = of.get('fail_line_max')
            if lmax is not None and isinstance(line, (int, float)) and line >= lmax:
                partial = True
                why_partial = 'чернила листа не объяснены ответом'
            else:
                bad.append((of['feature'], 'рисунок не подтвердил: наложение «%s», на линии %s (числа — overlay.json)' % (overlay, ('%.2f' % line) if isinstance(line, (int, float)) else 'н/д')))
        elif overlay in of.get('partial_statuses', []):
            partial = True
            pa = of.get('partial_alarm') or {}
            if pa.get('enabled') and not bad:                    # T-ЦП круг 2г (Fable otvet-38): «частично» → звонок с честной причиной; лист, у которого звонок уже есть, не меняется
                bad.append((pa.get('feature') or of['feature'], 'план лёг на лист частично: наложение «%s», на линии %s (числа — overlay.json)' % (overlay, ('%.2f' % line) if isinstance(line, (int, float)) else 'н/д')))
    # T-171 задача 2 (Fable otvet-33): при «легло» числа наложения могут врать «всё лежит» — стены ответа не на листе: выдуманных стен ≥ 15 % длины, или «лишнего» ≥ 8 м, или «на линии» < 0,60.
    # mode: off — не считается; shadow («в тени» до субботы) — считается и пишется в guard.json (`тень_стены`), в исход НЕ идёт; on — жёсткий звонок `feature`. Числа — storozh_rules.json (walls_fail).
    wf = (rules or RULES).get('walls_fail') or {}
    walls = (ov or {}).get('стены')
    if wf.get('mode') in ('on', 'shadow') and overlay in wf.get('statuses', ['легло']) and walls is not None:
        tot = sum(w['длина_px'] for w in walls)
        fab = [w for w in walls if w['класс'] == 'выдуманная']
        extra = (ov or {}).get('лишнее_м')
        e2 = (ov or {}).get('ext2b')
        pl = wf.get('pale_line') or {}
        if pl.get('enabled') and e2 and fab:                      # T-ЦП круг 2б (б): «бледная линия» — выдуманная стена, у которой вдоль оси есть чернила темнее местной бумаги → не выдуманная, не «лишнее»
            ex = {w['стена']: w for w in e2.get('стены', [])}
            pale = [w for w in fab if (ex.get(w['стена']) or {}).get('бледная', {}).get(str(pl.get('rel_max', 225)), 0.0) >= pl.get('min_share', 0.6)]
            if pale:
                fab = [w for w in fab if w not in pale]
                if isinstance(extra, (int, float)):
                    extra = max(0.0, extra - sum(ex[w['стена']]['длина_м'] for w in pale))
        wcls = {w['стена']: w['класс'] for w in walls}
        wn = wf.get('windows') or {}
        e3 = (ov or {}).get('ext2c')
        win_on = bool(wn.get('enabled') and e3)
        if win_on:                                                # T-ЦП круг 2в (Fable otvet-37): участки стены, где в САМОМ ОТВЕТЕ стоит окно, — не в «выдуманные», не в долю «на линии» (общее правило, без порога)
            ex3 = {w['стена']: w for w in e3.get('стены', [])}
            eff = {w['стена']: w['длина_px'] * (1.0 - (ex3[w['стена']]['окно_доля'] if w['стена'] in ex3 else 0.0)) for w in walls}
            for w in walls:
                x = ex3.get(w['стена'])
                if x and w['класс'] == 'выдуманная':
                    wcls[w['стена']] = x['класс_без_окон']
            for w in fab:
                x = ex3.get(w['стена'])
                if x and isinstance(extra, (int, float)):         # «лишнее, м»: стена перестала быть выдуманной — вся длина вон; осталась — только участок окна
                    extra = max(0.0, extra - (x['длина_м'] if x['класс_без_окон'] != 'выдуманная' else x['длина_м'] * x['окно_доля']))
            fab = [dict(w, длина_px=eff[w['стена']]) for w in fab if wcls[w['стена']] == 'выдуманная']
            tot = sum(eff.values())
            if e3.get('на_линии_узко_без_окон') is not None:
                line = e3['на_линии_узко_без_окон']
        share = (sum(w['длина_px'] for w in fab) / tot) if tot else 0.0
        hit = []
        if share >= wf['fabricated_share_min']:
            hit.append('выдуманных стен %d %% длины' % round(100 * share))
        if isinstance(extra, (int, float)) and extra >= wf['extra_m_min']:
            hit.append('лишнего (стены ответа без чернил) %.1f м' % extra)
        wl = wf.get('wide_line') or {}
        wide = None
        if wl.get('enabled') and e2:                              # T-ЦП круг 2б (а): звонок по «на линии» — только если и ШИРОКАЯ доля (допуск от толщины стены / 1,2 % стороны листа) ниже порога
            wide = e2.get('на_линии_широко_лист' if wl.get('variant') == 'sheet' else 'на_линии_широко_толщина')
        if wl.get('enabled') and win_on and wl.get('variant', 'thickness') != 'sheet' and e3.get('на_линии_широко_толщина_без_окон') is not None:
            wide = e3['на_линии_широко_толщина_без_окон']      # круг 2в: широкая доля — тоже без участков окон
        if isinstance(line, (int, float)) and line < wf['on_line_min'] and not (isinstance(wide, (int, float)) and wide >= wf['on_line_min']):
            hit.append('на линии %.2f' % line + ((', широко %.2f' % wide) if isinstance(wide, (int, float)) else ''))
        if hit:
            lst = [w for w in walls if wcls[w['стена']] not in ('на линии', 'не проверено')]
            why = 'стены ответа не лежат на листе: ' + '; '.join(hit) + ' — стены: ' + ', '.join('%s %s' % (w['стена'], wcls[w['стена']]) for w in lst[:10]) + ('…' if len(lst) > 10 else '')
            if wf['mode'] == 'on':
                bad.append((wf['feature'], why))
            else:
                res['тень_стены'] = why
    res['наложение'] = overlay
    res['звонки'] = [n for n, _ in bad]
    res['справка'] = [n for n, _ in info]
    sp = ('' if not info else ' · справка (не звонок): ' + '; '.join('%s: %s' % b for b in info))
    if res['класс'] == 'Д':
        if not bad:
            res['исход'] = 'сверено только с объявлением (П1, П2, П7 проверить нечем)' + (' · %s (наложение «%s»)' % ('рисунок лёг частично' if why_partial == 'рисунок лёг не весь' else why_partial, overlay) if partial else '') + sp
        else:
            res['исход'] = 'на правку — ' + '; '.join('%s: %s' % b for b in bad) + sp
    elif bad:
        res['исход'] = 'на правку — ' + '; '.join('%s: %s' % b for b in bad) + sp
    elif partial:
        res['исход'] = 'сверено частично — %s (наложение «%s»)' % (why_partial, overlay) + sp
    else:
        res['исход'] = 'готово' + sp
    return res


def verdict(g):
    """Ярлык исхода листа для таблиц воронки — ОДНО место (T-171/nalozhenie, Fable otvet-32 усл. 2): прогонщики (run_sb100.py, run_sb100.agent.py) только печатают его.
    Счётчик opus_agent.outcome_of читает ярлык по началу: «проверено …» / «проверено частично …» / «звонок …» / иначе «отказ/прочее»."""
    ish = g.get('исход') or ''
    sp = (' (справка: %s)' % ','.join(g['справка'])) if g.get('справка') else ''
    if ish.startswith('готово'):
        return 'проверено' + sp
    if ish.startswith('сверено только'):
        return 'проверено частично (только с объявлением)' + sp
    if ish.startswith('сверено частично'):
        return ('проверено частично (чернила листа не объяснены ответом)' if 'чернила листа не объяснены' in ish else 'проверено частично (рисунок лёг частично)') + sp
    if ish.startswith('на правку'):
        return 'звонок ' + ','.join(g.get('звонки') or []) + sp                # звонок — только жёсткие признаки по правилу модели (storozh_rules.json) + «Нал» (overlay_fail)
    return 'отказ' if ish.startswith('отказ') else '?'


def yn(v):
    return 'н.п.' if v is None else ('да' if v else 'нет')


# ---------- глаз ----------
def eye_tables():
    ey = {}
    for model in ('opus', 'gpt'):
        for r in csv.DictReader(open('%s/glaz-direktora-%s.tsv' % (R12, model), encoding='utf-8'), delimiter='\t'):
            if r['вар'] == 'b':
                ey[(r['лист'], 'b', model)] = ({'верно': 'верно', 'правка': 'правка', 'неверно': 'неверно'}[r['глаз']], 'директор')
    for s, (lab, _w) in CB.EYE_D.items():
        ey[(s, 'd', 'gpt')] = ({'как есть': 'верно', 'правка до 2 мин': 'правка', 'неверно': 'неверно'}[lab], 'р.1')
    return ey


def price_table():
    pr = {}
    for fn in ('svod-raw.tsv', 'svod-raw-d.tsv'):
        for r in csv.DictReader(open('%s/%s' % (R12, fn), encoding='utf-8'), delimiter='\t'):
            pr[(r['лист'], r['вариант'], r['модель'])] = float(r['цена_usd'] or 0)
    return pr


@carded(U)
def run():
    ey = eye_tables()
    pr = price_table()
    rows, svod = [], []
    for sid in SHEETS:
        for var, model in VARS:
            g = guard(sid, var, model, load(sid, var, model), '%s/%s/%s' % (sid, var, model))
            g['глаз'], g['источник_глаза'] = ey.get((sid, var, model), ('?', '?'))
            g['цена'] = pr.get((sid, var, model))
            svod.append(g)
    head = ['лист', 'вар', 'модель', 'класс', 'комнат', 'подписей', 'П1 число=подписям', 'П2 слитые/лишние', 'П3 входы', 'П4 сумма', 'исход', 'глаз', 'кто смотрел', 'пара (исход × глаз)',
            'причины П1', 'причины П2', 'причины П3', 'причины П4', 'цена листа, $']
    with open(U + '/table.tsv', 'w', encoding='utf-8') as f:
        f.write('\t'.join(head) + '\n')
        for g in svod:
            ok = g['исход'].startswith('готово')
            only = g['исход'].startswith('сверено')
            eye_ok = g['глаз'] == 'верно'
            if g['класс'] == 'Д' and only:
                pair = 'Д: по объявлению да, глаз ' + g['глаз']
            elif g['исход'].startswith('отказ'):
                pair = 'отказ при глазе ' + g['глаз']
            elif ok:
                pair = 'готово и верно' if eye_ok else 'ТИХО НЕВЕРНО (готово, глаз %s)' % g['глаз']
            else:
                pair = ('на правку при верном глазе' if eye_ok else 'на правку при неверном (%s)' % g['глаз'])
            g['пара'] = pair
            f.write('\t'.join([g['лист'], g['вар'], g['модель'], g['класс'], str(g['комнат']), '' if g['подписей'] is None else str(g['подписей']), yn(g['П1']), yn(g['П2']), yn(g['П3']), yn(g['П4']), g['исход'], g['глаз'], g['источник_глаза'], pair,
                               g.get('п1', ''), g.get('п2', ''), g.get('п3', ''), g.get('п4', ''), '' if g['цена'] is None else '%.4f' % g['цена']]) + '\n')
    json.dump([{k: v for k, v in g.items()} for g in svod], open(U + '/svod.json', 'w'), ensure_ascii=False, indent=1, default=str)
    print('строк', len(svod))
    return svod


# ---------- сверщик на себе ----------
def poly_to_json(g):
    if g.geom_type == 'MultiPolygon':
        g = max(g.geoms, key=lambda x: x.area)
    return [[round(x, 3), round(y, 3)] for x, y in list(g.exterior.coords)[:-1]]


def break_delete_room(plan):
    p = copy.deepcopy(plan)
    rs = level0(p)['rooms']
    rooms = get_rooms(p, 1.0)
    order = sorted(range(len(rooms)), key=lambda i: -rooms[i]['geom'].area)
    i = order[1]
    name = rooms[i]['name']
    geo = rooms[i]['geom']
    for j, r in enumerate(rs):
        if (r.get('name') or '') == name and abs(poly_area(r['polygon']) - rooms[i]['geo_area']) < 1e-6:
            del rs[j]
            break
    return p, 'удалена комната «%s» (%.1f м²)' % (name, geo.area)


def break_merge(plan, labels, ft):
    p = copy.deepcopy(plan)
    rooms = get_rooms(p, 1.0)
    best = None
    for i in range(len(rooms)):
        for j in range(i + 1, len(rooms)):
            if rooms[i]['geom'].distance(rooms[j]['geom']) <= 0.2:
                sz = min(rooms[i]['geom'].area, rooms[j]['geom'].area)
                if sz >= 3.0 and (best is None or rooms[i]['geom'].area + rooms[j]['geom'].area > best[0]):
                    best = (rooms[i]['geom'].area + rooms[j]['geom'].area, i, j)
    _, i, j = best
    u = unary_union([rooms[i]['geom'].buffer(0.12), rooms[j]['geom'].buffer(0.12)]).buffer(-0.12)
    rs = level0(p)['rooms']
    ids = {rooms[i]['id'], rooms[j]['id']}
    keep = [r for r in rs if r.get('id') not in ids]
    keep.append({'id': 'merged', 'name': rooms[i]['name'], 'polygon': poly_to_json(u), 'area': None})
    level0(p)['rooms'] = keep
    return p, 'слиты «%s» и «%s»' % (rooms[i]['name'], rooms[j]['name'])


def break_remove_doors(plan):
    p = copy.deepcopy(plan)
    rooms = get_rooms(p, 1.0)
    ops = opening_points(p, 1.0)
    cand = []
    for i, r in enumerate(rooms):
        t = [o for o in ops if r['geom'].distance(Point(*o['c'])) <= TOUCH_M]
        if t and r['geom'].area >= 2.0:
            cand.append((len(t), r['geom'].area, i, [o['id'] for o in t]))
    cand.sort()
    _, _, i, ids = cand[0]
    lv = level0(p)
    lv['openings'] = [o for o in lv['openings'] if o.get('id') not in ids]
    return p, 'убраны двери/проходы %s у «%s»' % (','.join(ids), rooms[i]['name'])


def break_inflate_room(plan):
    """T-98/19: раздуть комнату в 1,25 раза ПО ПЛОЩАДИ (линейно ×√1,25 вокруг центра; вторая по величине не-балкон), заявленная area в ответе не трогается."""
    from shapely import affinity
    p = copy.deepcopy(plan)
    rs = level0(p)['rooms']
    rooms = get_rooms(p, 1.0)
    order = sorted((i for i in range(len(rooms)) if not is_balcony(rooms[i]['name'])), key=lambda i: -rooms[i]['geom'].area)
    i = order[1] if len(order) > 1 else order[0]
    name, geo = rooms[i]['name'], rooms[i]['geom']
    for r in rs:
        if (r.get('name') or '') == name and abs(poly_area(r['polygon']) - rooms[i]['geo_area']) < 1e-6:
            r['polygon'] = poly_to_json(affinity.scale(geo, xfact=math.sqrt(1.25), yfact=math.sqrt(1.25), origin='centroid'))
            break
    return p, 'комната «%s» раздута ×1,25 по площади (%.1f → %.1f м²)' % (name, geo.area, geo.area * 1.25)


def break_inflate_walls(plan):
    """T-98/19 (❓3 директора): раздуть комнату ×1,25 по площади ВМЕСТЕ со стенами — полигон и стены, лежащие на его границе (оба конца ≤ 0,2 от контура), масштабируются вокруг центра; двери/соседи не трогаются.
    Честный потолок мерки: контур остаётся на своих (сдвинутых) стенах — П7с не звонит; ловит только П7г при q вне полосы и П1–П4 по соседям."""
    from shapely import affinity
    p = copy.deepcopy(plan)
    rs = level0(p)['rooms']
    rooms = get_rooms(p, 1.0)
    order = sorted((i for i in range(len(rooms)) if not is_balcony(rooms[i]['name'])), key=lambda i: -rooms[i]['geom'].area)
    i = order[1] if len(order) > 1 else order[0]
    name, geo = rooms[i]['name'], rooms[i]['geom']
    f = math.sqrt(1.25)
    c = geo.centroid
    for r in rs:
        if (r.get('name') or '') == name and abs(poly_area(r['polygon']) - rooms[i]['geo_area']) < 1e-6:
            r['polygon'] = poly_to_json(affinity.scale(geo, xfact=f, yfact=f, origin='centroid'))
            break
    bnd, n = geo.exterior, 0
    for w in level0(p).get('walls') or []:
        if isinstance(w.get('from'), list) and isinstance(w.get('to'), list) and bnd.distance(Point(*w['from'])) <= 0.2 and bnd.distance(Point(*w['to'])) <= 0.2:
            for key in ('from', 'to'):
                w[key] = [round(c.x + (w[key][0] - c.x) * f, 3), round(c.y + (w[key][1] - c.y) * f, 3)]
            n += 1
    return p, 'комната «%s» раздута ×1,25 по площади вместе с %d стенами (%.1f → %.1f м²)' % (name, n, geo.area, geo.area * 1.25)


BREAKS = ('удалить комнату', 'слить две', 'убрать дверь', 'раздуть ×1,25', 'раздуть ×1,25 со стенами')
BREAKS_INFO = ('раздуть ×1,25 со стенами',)           # справочно: честный потолок, в порог ≥ 90 % не входит
SEE = ('П1', 'П2', 'П3', 'П4', 'П7', 'П7с')


def break_control(sid, var, model, plan, key, base=None):
    """T-98/19: «сломать руками» на одном ответе → {вид: {'применимо', 'видит_любой' (новое «нет» по П1–П4/П7), 'видит_жёстко' (новое «нет» по жёсткому признаку этой модели), 'что', 'признаки'}}.
    base — уже посчитанный guard нетронутого ответа (иначе считаем)."""
    base = base or guard(sid, var, model, plan, key)
    labels, ft = labels_for(sid), _FITS.get(key)
    hard = set(RULES['hard_by_model'].get(model) or RULES['hard_by_model']['other']) | ({'П4'} if RULES['p4']['mode'] == 'hard' else set())
    res = {}
    for name, fn in zip(BREAKS, (lambda: break_delete_room(plan), lambda: break_merge(plan, labels, ft), lambda: break_remove_doors(plan), lambda: break_inflate_room(plan), lambda: break_inflate_walls(plan))):
        try:
            bp, what = fn()
            g = guard(sid, var, model, bp, key)
        except Exception as e:  # noqa: BLE001 — поломку не удалось применить (нет подходящей пары/двери) — «н.п.», не «не видит»
            res[name] = {'применимо': False, 'что': '%s: %s' % (type(e).__name__, str(e)[:60])}
            continue
        seen = [f for f in SEE if g.get(f) is False and base.get(f) is not False]
        res[name] = {'применимо': True, 'что': what, 'признаки': seen, 'видит_любой': bool(seen), 'видит_жёстко': bool([f for f in seen if f in hard])}
    return res


@carded(U)
def selftest(pairs):
    lines = ['Сверщик на себе (T-98/11): поломки руками на 2 листах; сторож должен увидеть все 3 вида на каждом; нетронутый ответ — как базовая линия.']
    allok = True
    for sid, var, model in pairs:
        key = '%s/%s/%s' % (sid, var, model)
        plan = load(sid, var, model)
        base = guard(sid, var, model, plan, key)
        lines.append('')
        lines.append('%s %s %s — нетронутый: П1 %s П2 %s П3 %s П4 %s → %s' % (sid, var, model, yn(base['П1']), yn(base['П2']), yn(base['П3']), yn(base['П4']), base['исход'][:140]))
        labels = labels_for(sid)
        ft = _FITS.get(key)
        tests = [('удалить комнату', break_delete_room(plan), ('П1', 'П2')), ('слить две', break_merge(plan, labels, ft), ('П1', 'П2')), ('убрать дверь', break_remove_doors(plan), ('П3',))]
        for name, (bp, what), feats in tests:
            g = guard(sid, var, model, bp, key)
            seen = [f for f in feats if g[f] is False and base[f] is not False]
            ok = bool(seen)
            allok &= ok
            lines.append('  %s: %s → П1 %s П2 %s П3 %s П4 %s; новые «нет» по %s: %s → %s' % (name, what, yn(g['П1']), yn(g['П2']), yn(g['П3']), yn(g['П4']), '/'.join(feats), ','.join(seen) or 'нет', 'ВИДИТ' if ok else 'НЕ ВИДИТ'))
    lines.append('')
    lines.append('ИТОГ: %s' % ('все поломки видны' if allok else 'есть НЕвидимые поломки'))
    open(U + '/selftest.txt', 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    if sys.argv[1] == 'selftest':
        pairs = [tuple(a.split(':')) for a in sys.argv[2:]] or [('kazan-7065029', 'd', 'gpt'), ('spb-10664362', 'd', 'gpt')]
        selftest(pairs)
    else:
        run()
