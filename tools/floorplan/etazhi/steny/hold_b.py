"""T-171/4в · круг Б (rab-10, Сб 28.11): перенос стены БЕЗ увода соседей + проверка замкнутости комнат.
hold_fit(plan0, exp, k, fit=True) — план «после»: переносимые стены (exp: {'id','a','b','d','tol'} в см) сдвинуты на d; НЕпереносимые соседи ДЕРЖАТСЯ на своей линии
(их конец может только скользить ВДОЛЬ собственной линии до новой линии переносимой стены — поперёк не уходит ни на сантиметр); стык переносимой стены подгоняется к соседям
(конец = пересечение новой линии с линией соседа). Соседи, лежащие на одной линии с переносимой (угол < PAR_DEG), не двигаются совсем.
Комнаты: вершина комнаты, граничащей с переносимой стеной, едет в подогнанный конец; остальные комнаты не меняются. Проёмы остаются на своих местах вдоль стены (offset пересчитан).
check_all(plan0, plan1, k) — ОБЯЗАТЕЛЬНАЯ проверка замкнутости: у каждой комнаты число и набор стен до = после, каждая кромка покрыта стенами не хуже, чем до,
контур — валидный многоугольник с площадью > 0; все стыки, замкнутые до (≤3 см), после не разошлись больше 3 см. fit=False — испорченная копия для −контроля.
Единицы: внутри — см; план — в единицах plan['units'] (k = множитель в см)."""
import copy
import math

import numpy as np

PAR_DEG = 20.0          # стена, чей угол с переносимой меньше этого, — «параллельная»: стык с ней не подгоняется, она держится
JOIN_TOL_CM = 3.0       # стык, замкнутый до, после не должен разойтись больше
BORDER_MIN_CM = 10.0    # комната «граничит» со стеной, если её кромка идёт вдоль стены не меньше этого
COVER_SLACK = 0.02      # покрытие кромки стенами после не хуже, чем до, минус это
SLIDE_CAP = 3.5         # конец соседа скользит не дальше SLIDE_CAP·|d| + 5 см (на угле ≥ 20° — 1/sin20° ≈ 2,9)


def _sd(p, a, b):
    ab = b - a
    L2 = float(ab @ ab)
    if L2 == 0:
        return float(np.hypot(*(p - a))), 0.0
    t = float((p - a) @ ab) / L2
    q = a + ab * max(0.0, min(1.0, t))
    return float(np.hypot(*(p - q))), t


def _unit(a, b):
    v = b - a
    n = float(np.hypot(*v))
    return v / n if n > 1e-9 else np.array([1.0, 0.0])


def _parallel(u, v, deg=PAR_DEG):
    return abs(float(u[0] * v[1] - u[1] * v[0])) < math.sin(math.radians(deg))


def _inter(p, u, q, v):
    den = float(u[0] * v[1] - u[1] * v[0])
    if abs(den) < 1e-9:
        return None
    t = float((q[0] - p[0]) * v[1] - (q[1] - p[1]) * v[0]) / den
    return p + t * u


def _walls(lv, k):
    out = {}
    for w in lv.get('walls', []):
        if w.get('id'):
            th = float(w['thickness']) * k if w.get('thickness') else {'exterior': 30.0, 'partition': 8.0}.get(w.get('kind'), 12.0)
            out[w['id']] = (np.array(w['from'], float) * k, np.array(w['to'], float) * k, th)
    return out


def borders(poly_cm, M, tol_extra=0.0):
    """комната (вершины в см) граничит с переносимой стеной M ({'a','b','tol'}), если какая-то её кромка идёт вдоль M не меньше BORDER_MIN_CM (до сдвига)."""
    a, b = np.array(M['a'], float), np.array(M['b'], float)
    u = _unit(a, b)
    n = len(poly_cm)
    for i in range(n):
        P, Q = poly_cm[i], poly_cm[(i + 1) % n]
        e = Q - P
        Le = float(np.hypot(*e))
        if Le < 1e-6 or not _parallel(e / Le, u, 5.0):
            continue
        if max(abs(float((P - a) @ np.array([-u[1], u[0]]))), abs(float((Q - a) @ np.array([-u[1], u[0]])))) > M['tol'] + tol_extra:
            continue
        ta, tb = float((a - P) @ (e / Le)), float((b - P) @ (e / Le))
        lo, hi = max(0.0, min(ta, tb)), min(Le, max(ta, tb))
        if hi - lo >= BORDER_MIN_CM:
            return True
    return False


CROSS_TOL_CM = 0.05     # поперечный увод конца непереносимого соседа: допуск = 0 (на округление координат до 1e-4 м = 0,01 см)
LEN_TOL_CM = 1.0        # рост/убыль длины соседа у стыка не больше переноса стены лоджии + это (Fable Б-2, 28.11: 0,2 см — погрешность счёта; было 0,1)
COLLAPSE_EXTRA_CM = 2.0  # Б-2: стена-ступенька, исчезающая от самого сдвига, не длиннее переноса + это


def neighbor_limits(plan0, plan1, exp, k, collapse=None):
    """ДВА ОГРАНИЧЕНИЯ Fable (28.11): (а) поперечный увод КАЖДОГО конца каждого непереносимого соседа = 0; (б) изменение длины соседа у стыка с переносимой стеной ≤ величины её переноса.
    → (строки по всем непереносимым стенам, чей конец сдвинулся, [нарушения], максимальный поперечный увод среди ВСЕХ непереносимых стен, см).
    строка: {'стена','конец','стык_с','скольжение_см' (рост длины со знаком), 'увод_поперёк_см','перенос_см'}"""
    mv = {s['id']: s for s in exp}
    rows, viol, mx = [], [], 0.0
    for lv0, lv1 in zip(plan0['levels'], plan1['levels']):
        W0, W1 = _walls(lv0, k), _walls(lv1, k)
        for i, (a0, b0, _th) in W0.items():
            if i in mv or i not in W1:
                continue
            a1, b1, _t1 = W1[i]
            u = _unit(a0, b0)
            n = np.array([-u[1], u[0]])
            for e, (p0, p1) in enumerate(((a0, a1), (b0, b1))):
                dv = p1 - p0
                cross = abs(float(dv @ n))
                mx = max(mx, cross)
                along = float(dv @ u)
                grow = -along if e == 0 else along                  # конец «from» назад / конец «to» вперёд — стена длиннее
                owner, best = None, None
                for j, s in mv.items():
                    a, b, _tj = W0[j] if j in W0 else (None, None, None)
                    if a is None or _parallel(u, _unit(a, b)):
                        continue
                    dist, _t = _sd(p0, a, b)
                    if dist <= s['tol'] and (best is None or dist < best):
                        owner, best = j, dist
                if cross > 1e-6 or abs(grow) > 1e-6 or cross > CROSS_TOL_CM:
                    pm = float(np.hypot(*mv[owner]['d'])) if owner else None
                    rows.append({'стена': i, 'конец': e, 'стык_с': owner, 'скольжение_см': round(grow, 2), 'увод_поперёк_см': round(cross, 3), 'перенос_см': round(pm, 2) if pm is not None else None})
                    if cross > CROSS_TOL_CM:
                        viol.append({'стена': i, 'конец': e, 'вид': 'увод', 'см': round(cross, 2), 'предел_см': 0.0, 'M': owner})
                    if pm is not None and abs(grow) > pm + LEN_TOL_CM and not (grow < 0 and collapse is not None and collapse(i)[0]):     # Б-2: ступенька, которой можно схлопнуться, укорачивается по своему правилу
                        viol.append({'стена': i, 'конец': e, 'вид': 'длина', 'см': round(abs(grow), 1), 'предел_см': round(pm, 1), 'M': owner})
    return rows, viol, mx


def _vertex_on_edge_line(poly, jv, i, s, a, b, M, W, fit):
    """Б-3 (Fable 28.11 ~10:45): вершина комнаты, лежащая у переносимой стены i, едет в пересечение НОВОЙ линии этой стены с линией ДРУГОЙ кромки вершины (та, что идёт не вдоль стены).
    Другая кромка держится на своей линии; если вдоль неё стоит ещё одна переносимая стена — берём её новую линию. None — не применимо (оба края вдоль стены / ни один / далеко): остаётся прежняя привязка."""
    if not fit:
        return None
    n = len(poly)
    v = poly[jv]
    u = _unit(a, b)
    d = np.array(s['d'], float)
    edges = []
    for nb in (poly[(jv - 1) % n], poly[(jv + 1) % n]):
        e = nb - v
        L = float(np.hypot(*e))
        edges.append((e / L) if L > 1e-6 else None)
    if any(e is None for e in edges):
        return None
    along = [_parallel(e, u, 5.0) for e in edges]
    if along[0] == along[1]:
        return None
    e2 = edges[1] if along[0] else edges[0]
    p2, u2 = v, e2
    for j, sj in M.items():
        if j == i:
            continue
        ja, jb, _t = W[j]
        uj = _unit(ja, jb)
        if _parallel(e2, uj, 5.0) and _sd(v, ja, jb)[0] <= sj['tol']:
            p2, u2 = ja + np.array(sj['d'], float), uj
            break
    x = _inter(a + d, u, p2, u2)
    if x is None or float(np.hypot(*(x - v))) > SLIDE_CAP * float(np.hypot(*d)) + 5.0:
        return None
    return x


def hold_fit(plan0, exp, k, fit=True, brk=''):
    """→ план «после» (копия plan0). exp — переносимые + виртуальные соосные стены; d — вектор сдвига (см). brk — ТОЛЬКО для −контроля: 'cross' — конец скользнувшего соседа ещё и уходит поперёк на 5 см;
    'long' — сосед удлиняется в 2,5 раза больше положенного."""
    plan = copy.deepcopy(plan0)
    mv = {s['id']: s for s in exp}
    flags = set(str(brk).split(','))                                    # ТОЛЬКО для −контролей: cross, long, oldvertex (старая привязка вершины Б-1/Б-2), nofit:<id> (у этой стены стык не подгоняется)
    nofit = {f[6:] for f in flags if f.startswith('nofit:')}
    brk = 'long' if 'long' in flags else ('cross' if 'cross' in flags else '')
    for lv0, lv in zip(plan0['levels'], plan['levels']):
        W = _walls(lv0, k)
        M = {i: s for i, s in mv.items() if i in W}
        if not M:
            continue

        def line_of(i):
            a, b, _th = W[i]
            if i in M:
                a = a + np.array(M[i]['d'], float)
                b = b + np.array(M[i]['d'], float)
            return a, _unit(a, b)
        new = {}
        for i, s in M.items():                                           # 1) концы переносимых: сдвиг на d, затем подгонка к соседям (пересечение линий)
            a, b, _th = W[i]
            d = np.array(s['d'], float)
            u = _unit(a, b)
            for e, p0 in enumerate((a, b)):
                dflt = p0 + d
                c = []
                if fit and i not in nofit:
                    for j, (ja, jb, _jt) in W.items():
                        if j == i:
                            continue
                        uj = _unit(ja, jb)
                        if _parallel(u, uj):
                            continue
                        if _sd(p0, ja, jb)[0] > s['tol']:
                            continue
                        pj, uj2 = line_of(j)
                        x = _inter(dflt, u, pj, uj2)
                        if x is not None:
                            c.append(x)
                new[(i, e)] = min(c, key=lambda x: float(np.hypot(*(x - dflt)))) if c else dflt
        if fit:
            for j, (ja, jb, _jt) in W.items():                           # 2) концы непереносимых соседей: только ВДОЛЬ своей линии до новой линии переносимой
                if j in M:
                    continue
                uj = _unit(ja, jb)
                for e, q in enumerate((ja, jb)):
                    c = []
                    for i, s in M.items():
                        if i in nofit:
                            continue
                        a, b, _th = W[i]
                        u = _unit(a, b)
                        if _parallel(u, uj):
                            continue
                        dist, _t = _sd(q, a, b)
                        if dist > s['tol']:
                            continue
                        x = _inter(q, uj, a + np.array(s['d'], float), u)
                        if x is not None and float(np.hypot(*(x - q))) <= SLIDE_CAP * float(np.hypot(*s['d'])) + 5.0:
                            c.append(x)
                    if c:
                        x = min(c, key=lambda x: float(np.hypot(*(x - q))))
                        if brk == 'long':
                            x = q + (x - q) * 2.5
                        elif brk == 'cross':
                            x = x + np.array([-uj[1], uj[0]]) * 5.0
                        new[(j, e)] = x
        old_from = {}
        for w in lv['walls']:                                            # 3) записываем стены
            i = w.get('id')
            if i not in W:
                continue
            old_from[i] = W[i][0]
            for e, key in enumerate(('from', 'to')):
                if (i, e) in new:
                    w[key] = [round(float(new[(i, e)][0]) / k, 4), round(float(new[(i, e)][1]) / k, 4)]
        for o in lv.get('openings', []):                                 # 4) проём остаётся на месте вдоль стены (на переносимой — едет вместе со стеной)
            i = o.get('wall')
            if i not in W or (i, 0) not in new:
                continue
            a, b, _th = W[i]
            u = _unit(a, b)
            shift = np.array(mv[i]['d'], float) if i in mv else np.zeros(2)
            o['offset'] = round(float(o['offset']) + float((a + shift - new[(i, 0)]) @ u) / k, 4)
        for r in lv.get('rooms', []):                                    # 5) вершины комнат, граничащих с переносимой стеной, едут в подогнанный конец
            poly = np.array(r['polygon'], float) * k
            bm = [i for i, s in M.items() if borders(poly, s)]
            if not bm:
                continue
            for jv, v in enumerate(poly):
                for i in bm:
                    s = M[i]
                    a, b, _th = W[i]
                    dist, _t = _sd(v, a, b)
                    if dist > s['tol']:
                        continue
                    x = None if 'oldvertex' in flags else _vertex_on_edge_line(poly, jv, i, s, a, b, M, W, fit and i not in nofit)    # Б-3: к пересечению НОВОЙ линии стены с линией соседней кромки
                    if x is not None:
                        pass
                    elif float(np.hypot(*(v - a))) <= s['tol'] and (i, 0) in new:
                        x = new[(i, 0)]
                    elif float(np.hypot(*(v - b))) <= s['tol'] and (i, 1) in new:
                        x = new[(i, 1)]
                    else:
                        x = v + np.array(s['d'], float)
                    r['polygon'][jv] = [round(float(x[0]) / k, 4), round(float(x[1]) / k, 4)]
                    break
    return plan


def collapse_check(plan0, exp, k, wid, cls_of, brk=''):
    """Б-2 (Fable 28.11): схлопывание короткой стены (ступенька от самого сдвига) разрешено, только если (1) её длина до ≤ перенос стены, к которой она примыкает, + 2 см;
    (2) на ней НЕТ чернил — класс наложения walls.csv не «на линии» (настоящая ниша остаётся); (3) число комнат прежнее и контур замкнут — это проверяет check_all по остальным пунктам.
    → (ok, причина, длина_см, перенос_см). brk='niche' — ТОЛЬКО −контроль: условия (1)(2) выключены."""
    if brk == 'niche':
        return True, 'контроль: условия выключены', None, None
    for lv in plan0['levels']:
        W = _walls(lv, k)
        if wid not in W:
            continue
        a, b, _th = W[wid]
        L = float(np.hypot(*(b - a)))
        tr = [float(np.hypot(*s['d'])) for s in exp if s['id'] in W and s['id'] != wid and any(_sd(p, W[s['id']][0], W[s['id']][1])[0] <= s['tol'] for p in (a, b))]
        if not tr:
            return False, 'не примыкает к переносимой стене', round(L, 1), None
        t = max(tr)
        if L > t + COLLAPSE_EXTRA_CM:
            return False, 'длина %.1f см > переноса %.1f + %.0f см' % (L, t, COLLAPSE_EXTRA_CM), round(L, 1), round(t, 1)
        c = cls_of(wid)
        if c is None or c == 'на линии':
            return False, 'на стене чернила (класс «%s»): ниша, не ступенька' % c, round(L, 1), round(t, 1)
        return True, 'ступенька: длина %.1f ≤ перенос %.1f + %.0f, класс «%s» (чернил нет)' % (L, t, COLLAPSE_EXTRA_CM, c), round(L, 1), round(t, 1)
    return False, 'стены нет в плане', None, None


def rot_of(plan0, plan1):
    old = {w['id']: w for lv in plan0['levels'] for w in lv.get('walls', []) if w.get('id')}
    rot = {}
    for lv in plan1['levels']:
        for w in lv.get('walls', []):
            o = old.get(w.get('id'))
            if o:
                a0 = math.atan2(o['to'][1] - o['from'][1], o['to'][0] - o['from'][0])
                a1 = math.atan2(w['to'][1] - w['from'][1], w['to'][0] - w['from'][0])
                rot[w['id']] = abs((math.degrees(a1 - a0) + 180) % 360 - 180)
    return rot


def room_walls(plan, k):
    """{id комнаты: {'стены': {id стены: длина вдоль кромок, см}, 'покрытие': [доля каждой кромки, закрытая стенами], 'площадь_м2', 'валидна'}} — по ВСЕМ комнатам всех этажей."""
    from shapely.geometry import Polygon
    out = {}
    for lv in plan['levels']:
        W = _walls(lv, k)
        for r in lv.get('rooms', []):
            poly = np.array(r['polygon'], float) * k
            n = len(poly)
            on, cov, edl = {}, [], []
            for i in range(n):
                P, Q = poly[i], poly[(i + 1) % n]
                e = Q - P
                Le = float(np.hypot(*e))
                edl.append(round(Le, 2))
                iv = []
                if Le < 1e-6:
                    cov.append(1.0)
                    continue
                ue = e / Le
                ne = np.array([-ue[1], ue[0]])
                for j, (a, b, th) in W.items():
                    if not _parallel(ue, _unit(a, b), 5.0):
                        continue
                    tol = max(th / 2, 5.0) + 2.0
                    if max(abs(float((a - P) @ ne)), abs(float((b - P) @ ne))) > tol:
                        continue
                    ta, tb = float((a - P) @ ue), float((b - P) @ ue)
                    lo, hi = max(0.0, min(ta, tb)), min(Le, max(ta, tb))
                    if hi - lo >= 1.0:
                        iv.append((lo, hi))
                        if hi - lo >= BORDER_MIN_CM:
                            on[j] = on.get(j, 0.0) + (hi - lo)
                iv.sort()
                tot, cur = 0.0, None
                for lo, hi in iv:
                    if cur is None or lo > cur[1]:
                        if cur:
                            tot += cur[1] - cur[0]
                        cur = [lo, hi]
                    else:
                        cur[1] = max(cur[1], hi)
                if cur:
                    tot += cur[1] - cur[0]
                cov.append(tot / Le)
            g = Polygon([tuple(p) for p in poly]) if n >= 3 else None
            out[r.get('id', '')] = {'стены': on, 'покрытие': cov, 'кромки_см': edl,'площадь_м2': round(g.area / 1e4, 3) if g else 0.0, 'валидна': bool(g is not None and g.is_valid)}
    return out


def joint_breaks(plan0, plan1, k, tol=JOIN_TOL_CM):
    """конец стены, «пришитый» до к другой стене (≤ tol), после тоже должен лежать на какой-нибудь стене (≤ tol), иначе висит → список разрывов (расстояние до ближайшей стены).
    Пары не требуем: два соосных куска, разведённых переносом на 17 см, замыкает поперечная стена — конец лежит на ней."""
    def segs(plan):
        return {w['id']: (np.array(w['from'], float) * k, np.array(w['to'], float) * k) for lv in plan['levels'] for w in lv.get('walls', []) if w.get('id')}
    s0, s1 = segs(plan0), segs(plan1)
    out = []
    for i, ends in s0.items():
        for ei, p in enumerate(ends):
            near = [j for j, (c, d) in s0.items() if j != i and _sd(p, c, d)[0] <= tol]       # к какой стене конец был «пришит» до
            if not near:
                continue
            if i not in s1:
                continue
            # после: конец должен лежать на какой-нибудь стене (не обязательно на той же: два соосных куска, разведённых переносом, замыкаются поперечной стеной)
            g = min((_sd(s1[i][ei], c, d)[0] for j, (c, d) in s1.items() if j != i), default=1e9)
            if g > tol:
                out.append({'стена': i, 'конец': ei, 'с_стеной': near[0], 'разрыв_см': round(g, 1)})
    for i in s0:
        if i not in s1:
            out.append({'стена': i, 'конец': -1, 'с_стеной': '', 'разрыв_см': -1.0, 'нет_стены': True})
    return out


def check_all(plan0, plan1, k, collapse=None, collapsed=None):
    """→ {'красные': [строки], 'комнаты': {rid: {...}}, 'разрывы': [...]}; пусто в 'красные' и 'разрывы' = ЗЕЛЁНАЯ.
    collapse (Б-2) — функция wid → (ok, причина, длина, перенос); если задана, стена, пропавшая из комнаты, но прошедшая collapse (ступенька), не краснит комнату, а её
    короткая кромка (после ≤ перенос+2 см) не требует покрытия; остальное (другие стены, покрытие других кромок, число вершин, площадь, валидность, разрывы) — как раньше. collapsed — список для отчёта."""
    r0, r1 = room_walls(plan0, k), room_walls(plan1, k)
    rooms, red = {}, []
    for rid, a in r0.items():
        b = r1.get(rid)
        if b is None:
            red.append('комната %s пропала' % rid)
            continue
        s0, s1 = set(a['стены']), set(b['стены'])
        why = []
        lost_ok, ok_len = set(), 0.0
        if collapse is not None:
            for w in sorted(s0 - s1):
                ok, cwhy, ln, tr = collapse(w)
                if ok:
                    lost_ok.add(w)
                    ok_len = max(ok_len, (tr or 0.0) + COLLAPSE_EXTRA_CM)
                    if collapsed is not None and w not in {x['стена'] for x in collapsed}:
                        collapsed.append({'стена': w, 'комната': rid, 'длина_до_см': ln, 'перенос_см': tr, 'почему_можно': cwhy})
        if len(s0 - lost_ok) != len(s1) or (s0 - lost_ok) != s1:
            why.append('стены до %d / после %d (потеряны %s, новые %s)' % (len(s0), len(s1), sorted(s0 - s1), sorted(s1 - s0)))
        if len(a['покрытие']) != len(b['покрытие']):
            why.append('число вершин %d → %d' % (len(a['покрытие']), len(b['покрытие'])))
        else:
            for e, (c0, c1) in enumerate(zip(a['покрытие'], b['покрытие'])):
                if c1 < c0 - COVER_SLACK:
                    if lost_ok and b['кромки_см'][e] <= ok_len:
                        continue                                                # кромка самой схлопнувшейся ступеньки — стены под ней больше нет
                    why.append('кромка %d покрыта стенами %.0f%% (было %.0f%%)' % (e, 100 * c1, 100 * c0))
        if not b['площадь_м2'] > 0:
            why.append('площадь %.2f ≤ 0' % b['площадь_м2'])
        if a['валидна'] and not b['валидна']:
            why.append('контур невалиден (самопересечение)')
        rooms[rid] = {'стен_до': len(s0), 'стен_после': len(s1), 'площадь_до_м2': a['площадь_м2'], 'площадь_после_м2': b['площадь_м2'], 'покрытие_мин_до': round(min(a['покрытие']), 3) if a['покрытие'] else None,
                      'покрытие_мин_после': round(min(b['покрытие']), 3) if b['покрытие'] else None, 'замкнута': not why, 'почему_нет': why}
        if why:
            red.append('комната %s: %s' % (rid, '; '.join(why)))
    brk = joint_breaks(plan0, plan1, k)
    return {'красные': red, 'комнаты_красные': [rid for rid, v in rooms.items() if not v['замкнута']] + [rid for rid in r0 if rid not in r1], 'комнаты': rooms, 'разрывы': brk, 'зелёная': not red and not brk}
