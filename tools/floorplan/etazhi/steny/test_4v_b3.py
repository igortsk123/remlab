"""Круг Б-3 4в (rab-10, 28.11, Fable ~10:45): (1) вершина комнаты — к пересечению НОВОЙ линии переносимой стены с линией соседней кромки; (2) при красной замкнутости отменяются только ВИНОВНЫЕ
(после одного его переноса контур не замыкается) + переносы, делящие с ними вершину; ворота затем снова на итоговом плане; (3) ступенька — строкой в счёте (в test_4v_b2.py).
Запуск (без внешних данных: модули чтения — steny/work/, лист — fixtures/steny/; CI job planner; вывод — STENY_OUT или tmp): python -B -I test_4v_b3.py (venv scout, heavy-slot 1 ядро; без чернил и OCR).
(1) РЕАЛЬНЫЙ лист kazan-14825916 (комната r8 с толстой w_left2): новая привязка → комната прямоугольник, замкнута, красных 0; −КОНТРОЛЬ: старая привязка (oldvertex) → КРАСНАЯ (кромка wl_bottom не покрыта);
(2) синтетика: комната с двумя переносимыми стенами M1 (слева) и M2 (справа), у M2 стык не подгоняется (nofit:M2) → отменена ТОЛЬКО M2, M1 перенесена, ворота на итоговом плане зелёные;
    −КОНТРОЛЬ: старое правило (allgroup) отменяет обе → утверждение «M1 перенесена» на нём КРАСНОЕ;
(3) синтетика: верхняя стена T делит вершину с виновной M2 → отменяются M2 и T (в report — «делит вершину с отменённой M2»), M1 остаётся."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import steny_ten as ST  # noqa: E402      # без SKIP: модули чтения — steny/work/, данные листа — fixtures/steny/ (steny_testenv.py); нет зависимости → тест КРАСНЫЙ, не молчит
import steny_testenv as TE  # noqa: E402
import tempfile  # noqa: E402
OUT = os.environ.get('STENY_OUT') or os.path.join(tempfile.gettempdir(), 'steny-test')      # вывод тестов — не в папку репо
os.makedirs(OUT, exist_ok=True)

SC, HB = ST.SC, ST.SC.HB


def setup(brk=''):
    SC.EVIDENCE = SC.PROFILE = SC.AREA_FLAG_ONLY = SC.NODIGIT_FLAG = SC.PR_OLD_ON_INK = SC.WHOLE_MISS = True
    SC.NEIGHBOR_DRIFT = False
    SC.HOLD_NEIGHBORS = True
    SC.HOLD_BREAK = brk


def test_vertex_real_sheet():
    sid = 'kazan-14825916'
    fx = json.load(open(os.path.join(HERE, '..', 'fixtures', 'steny', sid + '.json'), encoding='utf-8'))      # план «до» и 4 переноса прогона Б-3 (фикстура репо)
    plan0 = fx['plan0']
    ws, k = SC.plan_walls(plan0)
    res = {'перенесено': fx['перенесено']}
    W = HB._walls(plan0['levels'][0], k)
    exp = []
    for x in res['перенесено']:
        a, b, th = W[x['стена']]
        exp.append({'id': x['стена'], 'a': a, 'b': b, 'd': (x['dx_см'], x['dy_см']), 'tol': max(th / 2, 5.0) + 2.0})
    new = HB.hold_fit(plan0, exp, k, fit=True)
    old = HB.hold_fit(plan0, exp, k, fit=True, brk='oldvertex')
    z_new, z_old = HB.check_all(plan0, new, k), HB.check_all(plan0, old, k)
    r8 = [r for r in new['levels'][0]['rooms'] if r['id'] == 'r8'][0]['polygon']
    assert z_new['зелёная'], z_new['красные']
    assert not z_old['зелёная'] and any('wl_bottom' in x for x in z_old['красные']), z_old['красные']
    return r8, z_old['красные'][0][:140]


def plan_room(extra_walls=()):
    return {'units': 'cm', 'levels': [{
        'walls': [
            {'id': 'T', 'from': [0, 0], 'to': [400, 0], 'thickness': 10},
            {'id': 'M2', 'from': [400, 0], 'to': [400, 300], 'thickness': 10},
            {'id': 'B', 'from': [400, 300], 'to': [0, 300], 'thickness': 10},
            {'id': 'M1', 'from': [0, 300], 'to': [0, 0], 'thickness': 10}] + list(extra_walls),
        'rooms': [{'id': 'r1', 'name': 'комната', 'polygon': [[0, 0], [400, 0], [400, 300], [0, 300]]}],
        'openings': []}]}


def cand(i, a, b, d):
    return {'id': i, 'a': a, 'b': b, 'd': d, 'tol': 7.0, 'класс': 1}


def run(cands, brk):
    setup(brk)
    plan0 = plan_room()
    rows = {c['id']: {'класс': 'сдвинута'} for c in cands}
    info = {}
    plan1, shifted, cancelled, flags, rooms = SC.correct(plan0, 1.0, cands, {}, {}, rows=rows, parallel=False, info=info)
    setup('')
    return plan1, [s['id'] for s in shifted], cancelled, info


M1 = lambda: cand('M1', (0.0, 300.0), (0.0, 0.0), (10.0, 0.0))
M2 = lambda: cand('M2', (400.0, 0.0), (400.0, 300.0), (-10.0, 0.0))
TT = lambda: cand('T', (0.0, 0.0), (400.0, 0.0), (0.0, 10.0))


def test_partial_cancel():
    _p, moved, canc, info = run([M1(), M2()], 'nofit:M2')
    assert moved == ['M1'], (moved, canc)
    assert [c['стена'] for c in canc] == ['M2'] and canc[0]['причина'].startswith('контур не замыкается'), canc
    assert info['замкнутость']['зелёная'], info['замкнутость']['красные']
    assert info['частичная_отмена'] and info['частичная_отмена'][0]['виновные'] == ['M2'], info['частичная_отмена']
    return canc[0]['причина'][:110], info['частичная_отмена']


def test_control_old_group():
    _p, moved, canc, info = run([M1(), M2()], 'nofit:M2,allgroup')
    assert sorted(c['стена'] for c in canc) == ['M1', 'M2'] and moved == [], (moved, canc)       # старое правило снимает и невиновную
    try:
        assert moved == ['M1'], 'M1 должна остаться перенесённой'
    except AssertionError:
        return 'на старом правиле утверждение «M1 перенесена» КРАСНОЕ (отменены обе: %s)' % sorted(c['стена'] for c in canc)
    raise AssertionError('−контроль не сработал')


def test_share_vertex():
    _p, moved, canc, info = run([M1(), M2(), TT()], 'nofit:M2')
    ids = sorted(c['стена'] for c in canc)
    assert ids == ['M2', 'T'] and moved == ['M1'], (moved, canc)
    why = {c['стена']: c['причина'] for c in canc}
    assert 'делит вершину с отменённой M2' in why['T'], why
    assert info['замкнутость']['зелёная'], info['замкнутость']['красные']
    return why


if __name__ == '__main__':
    out = {}
    r8, red_old = test_vertex_real_sheet()
    print('PASS (1) kazan-14825916 новая привязка: комната r8 =', r8, '— замкнута; −контроль старая привязка КРАСНАЯ:', red_old)
    c2, log = test_partial_cancel()
    print('PASS (2) виновна M2 → отменена только она («%s…»), M1 перенесена, ворота на итоговом плане зелёные; log %s' % (c2, log))
    print('PASS (2к) −контроль:', test_control_old_group())
    w3 = test_share_vertex()
    print('PASS (3) делят вершину: отменены M2 и T, M1 остаётся:', w3)
    out.update({'1': [r8, red_old], '2': [c2, log], '3': w3})
    json.dump(out, open(OUT + '/test-b3-itog.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('ВСЕ ПРОВЕРКИ Б-3 ПРОШЛИ')
