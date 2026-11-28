"""T-171 круг Б-3 4в (rab-10): чистые проверки hold_b.py — только numpy, без чернил/OCR/чужих папок, годится для CI.
Ключ --hold-neighbors ВЫКЛ по умолчанию (в steny_core: HOLD_NEIGHBORS=False), здесь проверяется сам модуль подгонки стыков и ворот замкнутости.
(1) РЕАЛЬНЫЙ лист kazan-14825916 (фикстура fixtures/steny/kazan-14825916.json: план «до» + 4 переноса прогона Б-3): новая привязка вершины комнаты — к пересечению новой линии
    переносимой стены с линией соседней кромки → комната r8 прямоугольник, замкнутость зелёная; −КОНТРОЛЬ: старая привязка (brk='oldvertex') → красная («кромка wl_bottom не покрыта»);
(2) синтетика: комната 400×300, переносимые M1 и M2, увод соседей поперёк = 0 (ограничение «а»), рост соседа у стыка ≤ перенос + 1 см (ограничение «б»);
    −КОНТРОЛЬ: без подгонки стыков (fit=False) контур красный;
(3) ничего не менялось → ворота зелёные;
(4) СИНТЕТИКА на вершину у переносимой стены (пересечение линий): прямоугольник, угол двух переносимых стен, косая кромка + −контроль «oldvertex» (по просьбе rab-8: не одним реальным листом).
Запуск: python tools/floorplan/etazhi/steny/test_hold_b_pure.py (нужен numpy)."""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hold_b as HB  # noqa: E402

RES = []


def check(name, cond, extra=''):
    RES.append((name, bool(cond)))
    print('%s  %s%s' % ('OK  ' if cond else 'FAIL', name, (' — ' + str(extra)) if (extra and not cond) else ''))


def exp_of(plan0, k, moved):
    W = HB._walls(plan0['levels'][0], k)
    exp = []
    for x in moved:
        a, b, th = W[x['стена']]
        exp.append({'id': x['стена'], 'a': a, 'b': b, 'd': (x['dx_см'], x['dy_см']), 'tol': max(th / 2, 5.0) + 2.0})
    return exp


def real_sheet():
    fx = json.load(open(os.path.join(HERE, '..', 'fixtures', 'steny', 'kazan-14825916.json'), encoding='utf-8'))
    plan0, k = fx['plan0'], fx['k']
    exp = exp_of(plan0, k, fx['перенесено'])
    new = HB.hold_fit(plan0, exp, k, fit=True)
    old = HB.hold_fit(plan0, exp, k, fit=True, brk='oldvertex')
    z_new, z_old = HB.check_all(plan0, new, k), HB.check_all(plan0, old, k)
    r8 = [r for r in new['levels'][0]['rooms'] if r['id'] == 'r8'][0]['polygon']
    xs, ys = sorted({round(p[0], 3) for p in r8}), sorted({round(p[1], 3) for p in r8})
    check('(1) реальный лист: новая привязка → ворота зелёные', z_new['зелёная'], z_new['красные'])
    check('(1) комната r8 — прямоугольник (2 разных x, 2 разных y)', len(xs) == 2 and len(ys) == 2 and len(r8) == 4, r8)
    check('(1) −контроль: старая привязка → красная, кромка wl_bottom не покрыта', (not z_old['зелёная']) and any('wl_bottom' in x for x in z_old['красные']), z_old['красные'])
    check('(1) поперечный увод соседей = 0 (≤ %.2f см)' % HB.CROSS_TOL_CM, HB.neighbor_limits(plan0, new, exp, k)[2] <= HB.CROSS_TOL_CM)


def plan_room():
    return {'units': 'cm', 'levels': [{
        'walls': [
            {'id': 'T', 'from': [0, 0], 'to': [400, 0], 'thickness': 10},
            {'id': 'M2', 'from': [400, 0], 'to': [400, 300], 'thickness': 10},
            {'id': 'B', 'from': [400, 300], 'to': [0, 300], 'thickness': 10},
            {'id': 'M1', 'from': [0, 300], 'to': [0, 0], 'thickness': 10}],
        'rooms': [{'id': 'r1', 'name': 'комната', 'polygon': [[0, 0], [400, 0], [400, 300], [0, 300]]}],
        'openings': []}]}


def synthetic():
    plan0 = plan_room()
    k = 1.0
    exp = [{'id': 'M1', 'a': (0.0, 300.0), 'b': (0.0, 0.0), 'd': (10.0, 0.0), 'tol': 7.0},
           {'id': 'M2', 'a': (400.0, 0.0), 'b': (400.0, 300.0), 'd': (-10.0, 0.0), 'tol': 7.0}]
    ok = HB.hold_fit(plan0, exp, k, fit=True)
    bad = HB.hold_fit(plan0, exp, k, fit=False)
    z_ok, z_bad = HB.check_all(plan0, ok, k), HB.check_all(plan0, bad, k)
    _rows, viol, mx = HB.neighbor_limits(plan0, ok, exp, k)
    check('(2) синтетика: две переносимые стены со стыками → ворота зелёные', z_ok['зелёная'], z_ok['красные'])
    check('(2) увод соседей поперёк ≤ %.2f см, нарушений ограничений нет' % HB.CROSS_TOL_CM, mx <= HB.CROSS_TOL_CM and not viol, (mx, viol))
    check('(2) −контроль: без подгонки стыков (fit=False) контур красный', not z_bad['зелёная'], z_bad)


def room_poly(plan, rid='r1'):
    return [[round(x, 3), round(y, 3)] for x, y in [r for r in plan['levels'][0]['rooms'] if r['id'] == rid][0]['polygon']]


def synthetic_vertex():
    """вершина у переносимой стены — в пересечение НОВОЙ линии стены с линией соседней кромки (маленькая синтетика, без реальных листов)"""
    k = 1.0
    # (а) прямоугольник, M1 (слева) едет на +10 по x: вершины (0,0),(0,300) → (10,0),(10,300); соседние кромки остаются на своих линиях
    plan0 = plan_room()
    exp = [{'id': 'M1', 'a': (0.0, 300.0), 'b': (0.0, 0.0), 'd': (10.0, 0.0), 'tol': 7.0}]
    new = HB.hold_fit(plan0, exp, k, fit=True)
    check('(4а) прямоугольник: вершины у M1 — (10,0) и (10,300)', room_poly(new) == [[10.0, 0.0], [400.0, 0.0], [400.0, 300.0], [10.0, 300.0]], room_poly(new))
    # (б) обе кромки у угла переносимые: M1 едет на +10 по x, T — на +5 по y → угол в пересечении ИХ НОВЫХ линий (10,5), а не (10,0) и не (0,5)
    exp2 = exp + [{'id': 'T', 'a': (0.0, 0.0), 'b': (400.0, 0.0), 'd': (0.0, 5.0), 'tol': 7.0}]
    new2 = HB.hold_fit(plan0, exp2, k, fit=True)
    p = room_poly(new2)
    check('(4б) угол двух переносимых стен — в пересечении их новых линий (10,5)', p[0] == [10.0, 5.0], p)
    # (в) верхняя кромка косая: вершина едет ВДОЛЬ её линии до новой линии M1 (x=10 → y=0,5), а не сдвигается на вектор переноса (10,0)
    plan3 = plan_room()
    plan3['levels'][0]['walls'][0]['to'] = [400, 20]
    plan3['levels'][0]['walls'][1]['from'] = [400, 20]
    plan3['levels'][0]['rooms'][0]['polygon'] = [[0, 0], [400, 20], [400, 300], [0, 300]]
    new3 = HB.hold_fit(plan3, exp, k, fit=True)
    old3 = HB.hold_fit(plan3, exp, k, fit=False)
    p3, q3 = room_poly(new3), room_poly(old3)
    check('(4в) косая кромка: вершина на линии кромки в x=10 → (10; 0,5)', p3[0] == [10.0, 0.5], p3)
    check('(4в) −контроль: без привязки к линии кромки (fit=False) вершина просто сдвинута на вектор переноса (10; 0), не на линии кромки', q3[0] == [10.0, 0.0] and q3[0] != p3[0], q3)
    # старая привязка (brk=oldvertex) на этой простой синтетике даёт то же, что новая (вершина привязана к концу стены, а конец стены тоже встал на линию кромки) —
    # различаются они на толстой стене с вершиной вне её оси: это ловит реальный лист (1)
    check('(4в) замкнутость новой — зелёная', HB.check_all(plan3, new3, k)['зелёная'], HB.check_all(plan3, new3, k)['красные'])


def nothing_changed():
    plan0 = plan_room()
    z = HB.check_all(plan0, copy.deepcopy(plan0), 1.0)
    check('(3) ничего не менялось → ворота зелёные', z['зелёная'], z['красные'])


if __name__ == '__main__':
    real_sheet()
    synthetic()
    synthetic_vertex()
    nothing_changed()
    bad = [n for n, ok in RES if not ok]
    print('ИТОГ: %d проверок, красных %d' % (len(RES), len(bad)))
    sys.exit(1 if bad else 0)
