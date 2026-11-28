"""Круг Б-3 4в, дописка (rab-10, 28.11 ~11:25): случай, не покрытый test_4v_b3.py, — «после частичной отмены красное ОСТАЛОСЬ → отменяется вся группа» + −контроль «без повторного прохода ворот».
Запуск (без внешних данных: модули чтения — steny/work/, лист — fixtures/steny/; CI job planner; вывод — STENY_OUT или tmp): python -B -I test_4v_b4.py (venv scout, heavy-slot 1 ядро; без чернил и OCR).
СЛУЧАЙ (синтетика): комната r1, переносимые M1 (слева) и M2 (справа); у M2 стык не подгоняется (nofit:M2) → после первого прохода ворот M2 виновна одна (её перенос в одиночку красный), M1 в одиночку зелёная.
Частичная отмена снимает только M2. Красное, которое остаётся ПОСЛЕ неё, в плане из одной-двух невиновных стен собрать не удалось (по одной они зелёные, а вместе красные — такого плана на синтетике и на 150 листах нет) —
поэтому красное остатка ИМИТИРУЕТСЯ: обёртка над HB.check_all возвращает красный на ЧЕТВЁРТОМ вызове (1 — вся группа, 2 — M1 одна, 3 — M2 одна, 4 — повторный проход ворот на итоговом плане). Проверяется порядок действий кода, не геометрия.
(1) ожидание: повторный проход ВЫПОЛНЕН (4 вызова), красное → отменена вся группа: M2 (частично) и затем M1 («контур не замыкается»), перенесённых нет, план побайтно прежний (md5);
(2) −КОНТРОЛЬ (HOLD_BREAK='nofit:M2,norecheck': повторный проход пропущен): M1 остаётся перенесённой, контур итогового плана КРАСНЫЙ → утверждение (1) на нём КРАСНОЕ (тест ловит отсутствие повтора);
(3) без имитации (штатный случай test_4v_b3: красного остатка нет) — 5 вызовов (4-й — повторный проход, зелёный; 5-й — строка отчёта), перенесена M1, итог зелёный: повторный проход выполняется всегда, красного не выдумывает."""
import hashlib
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
_REAL = HB.check_all


def setup(brk=''):
    SC.EVIDENCE = SC.PROFILE = SC.AREA_FLAG_ONLY = SC.NODIGIT_FLAG = SC.PR_OLD_ON_INK = SC.WHOLE_MISS = True
    SC.NEIGHBOR_DRIFT = False
    SC.HOLD_NEIGHBORS = True
    SC.HOLD_BREAK = brk


def plan_room():
    return {'units': 'cm', 'levels': [{
        'walls': [
            {'id': 'T', 'from': [0, 0], 'to': [400, 0], 'thickness': 10},
            {'id': 'M2', 'from': [400, 0], 'to': [400, 300], 'thickness': 10},
            {'id': 'B', 'from': [400, 300], 'to': [0, 300], 'thickness': 10},
            {'id': 'M1', 'from': [0, 300], 'to': [0, 0], 'thickness': 10}],
        'rooms': [{'id': 'r1', 'name': 'комната', 'polygon': [[0, 0], [400, 0], [400, 300], [0, 300]]}],
        'openings': []}]}


def cand(i, a, b, d):
    return {'id': i, 'a': a, 'b': b, 'd': d, 'tol': 7.0, 'класс': 1}


def md5(p):
    return hashlib.md5(json.dumps(p, ensure_ascii=False, indent=1).encode('utf-8')).hexdigest()


def run(brk, fake_red_on_call):
    calls = []

    def wrapped(plan0, plan1, k, collapse=None, collapsed=None):
        r = _REAL(plan0, plan1, k, collapse=collapse, collapsed=collapsed)
        calls.append(r['зелёная'])
        if fake_red_on_call and len(calls) == fake_red_on_call:
            r = dict(r)
            r.update({'зелёная': False, 'красные': ['комната r1: ИМИТАЦИЯ — красное осталось после частичной отмены'], 'комнаты_красные': ['r1'], 'разрывы': []})
            calls[-1] = False
        return r
    HB.check_all = wrapped
    try:
        setup(brk)
        plan0 = plan_room()
        cands = [cand('M1', (0.0, 300.0), (0.0, 0.0), (10.0, 0.0)), cand('M2', (400.0, 0.0), (400.0, 300.0), (-10.0, 0.0))]
        rows = {c['id']: {'класс': 'сдвинута'} for c in cands}
        info = {}
        plan1, shifted, cancelled, flags, rooms = SC.correct(plan0, 1.0, cands, {}, {}, rows=rows, parallel=False, info=info)
    finally:
        HB.check_all = _REAL
        setup('')
    return plan0, plan1, [s['id'] for s in shifted], cancelled, info, calls


def check_group_cancel(brk):
    plan0, plan1, moved, canc, info, calls = run(brk, 4)
    assert len(calls) >= 4, ('повторный проход ворот не выполнен: вызовов', len(calls))
    assert moved == [] and [c['стена'] for c in canc] == ['M2', 'M1'], (moved, canc)
    assert canc[0]['причина'].startswith('контур не замыкается') and 'ИМИТАЦИЯ' in canc[1]['причина'], canc
    assert md5(plan1) == md5(plan0), 'план не побайтно прежний'
    assert info['частичная_отмена'] and info['частичная_отмена'][0]['виновные'] == ['M2'], info['частичная_отмена']
    return len(calls), [c['стена'] for c in canc], md5(plan1)


def test_group_cancel_after_partial():
    return check_group_cancel('nofit:M2')


def test_control_no_recheck():
    try:
        check_group_cancel('nofit:M2,norecheck')
    except AssertionError as ex:
        _p0, _p1, moved, canc, info, calls = run('nofit:M2,norecheck', 4)
        # вызовы: 1 вся группа, 2 M1 одна, 3 M2 одна — повторного прохода на итоговом плане НЕТ; 4-й — лишь строка отчёта в конце (с имитацией красного остатка)
        assert moved == ['M1'] and len(calls) == 4 and not info['замкнутость']['зелёная'], (moved, calls)
        return 'без повторного прохода M1 осталась перенесённой, а контур итогового плана КРАСНЫЙ (%s); утверждение теста красное: %s' % (info['замкнутость']['красные'][0][:60], str(ex)[:90])
    raise AssertionError('−контроль не сработал: тест зелёный без повторного прохода ворот')


def test_normal_case_recheck_green():
    plan0, plan1, moved, canc, info, calls = run('nofit:M2', 0)
    assert len(calls) == 5 and moved == ['M1'] and [c['стена'] for c in canc] == ['M2'], (calls, moved, canc)      # 1 вся группа (красный), 2–3 по одной, 4 повторный проход на итоговом плане, 5 строка отчёта
    assert calls[3] is True and calls[4] is True and info['замкнутость']['зелёная']
    return len(calls)


if __name__ == '__main__':
    n, ids, m = test_group_cancel_after_partial()
    print('PASS (1) красное после частичной отмены → отменена вся группа %s, повторный проход выполнен (вызовов ворот %d), план побайтно прежний md5 %s' % (ids, n, m))
    c = test_control_no_recheck()
    print('PASS (2) −контроль:', c)
    n3 = test_normal_case_recheck_green()
    print('PASS (3) штатный случай без имитации: вызовов ворот %d, M1 перенесена, итог зелёный' % n3)
    json.dump({'1': [n, ids, m], '2': c, '3': n3}, open(OUT + '/test-b4-itog.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('ВСЕ ПРОВЕРКИ Б-3 (ДОПИСКА) ПРОШЛИ')
