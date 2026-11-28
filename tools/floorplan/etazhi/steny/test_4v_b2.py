"""Круг Б-2 4в (rab-10, 28.11, Fable ~10:30): схлопывание ступеньки разрешено только при трёх условиях (длина ≤ перенос + 2 см; чернил нет — класс walls.csv не «на линии»; комнаты/контур целы);
(б) допуск +1 см; порог кромки 93 % не тронут. Запуск (локально, нужна папка work/ — STENY_WORK; вывод — STENY_OUT или tmp): python -B -I test_4v_b2.py (venv scout, heavy-slot 1 ядро, без OCR и без чернил — синтетический план).
ПЛАН: комната r1 со ступенькой — стена M (400,0)→(400,200) переносится на +17 см, ступенька S (400,200)→(417,200) длиной 17 см (от самого сдвига), дальше C на x=417.
(1) СТУПЕНЬКА: S без чернил, 17 ≤ 17+2 → перенос проходит, у комнаты стен 6→5 (S схлопнулась), контур замкнут, красных 0; без разрешения (старые ворота Б-1) тот же перенос КРАСНЫЙ (причина «стены до 6 / после 5»);
(2) НИША: та же S, но класс «на линии» (на ней чернила) → перенос ОТМЕНЁН, причина «контур не замыкается», план побайтно прежний;
(3) НЕ СТУПЕНЬКА: S без чернил, но длиннее переноса + 2 (перенос 10 при длине 17) → ОТМЕНА;
(4) −КОНТРОЛЬ: испорченная копия (HOLD_BREAK='niche': условия (1) и (2) выключены) схлопывает и нишу — тест (2) на ней КРАСНЫЙ (проверено: утверждение «ниша отменена» падает);
(5) допуск (б) +1 см: рост соседа переноса + 0,9 см проходит, + 1,5 см — нарушение."""
import copy
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import steny_ten as ST  # noqa: E402
except ImportError as _ex:      # нет cv2 или чужой папки work/ (STENY_WORK): в CI тест не гоняется — гонять у себя, где она есть
    print('SKIP: %s (нужны cv2 и папка work/ — STENY_WORK)' % _ex)
    sys.exit(0)
import tempfile  # noqa: E402
OUT = os.environ.get('STENY_OUT') or os.path.join(tempfile.gettempdir(), 'steny-test')      # вывод тестов — не в папку репо
os.makedirs(OUT, exist_ok=True)

SC, HB = ST.SC, ST.SC.HB


def plan_step(step_len=17.0):
    return {'units': 'cm', 'levels': [{
        'walls': [
            {'id': 'T', 'from': [0, 0], 'to': [400, 0], 'thickness': 10},
            {'id': 'M', 'from': [400, 0], 'to': [400, 200], 'thickness': 10},
            {'id': 'S', 'from': [400, 200], 'to': [400 + step_len, 200], 'thickness': 10},
            {'id': 'C', 'from': [400 + step_len, 200], 'to': [400 + step_len, 300], 'thickness': 10},
            {'id': 'B', 'from': [400 + step_len, 300], 'to': [0, 300], 'thickness': 10},
            {'id': 'L', 'from': [0, 300], 'to': [0, 0], 'thickness': 10}],
        'rooms': [{'id': 'r1', 'name': 'комната', 'polygon': [[0, 0], [400, 0], [400, 200], [400 + step_len, 200], [400 + step_len, 300], [0, 300]]}],
        'openings': []}]}


def setup(brk=''):
    SC.EVIDENCE = SC.PROFILE = SC.AREA_FLAG_ONLY = SC.NODIGIT_FLAG = SC.PR_OLD_ON_INK = SC.WHOLE_MISS = True
    SC.NEIGHBOR_DRIFT = False
    SC.HOLD_NEIGHBORS = True
    SC.HOLD_BREAK = brk


def correct(plan0, d, cls_s, brk=''):
    setup(brk)
    cand = [{'id': 'M', 'a': (400.0, 0.0), 'b': (400.0, 200.0), 'd': (d, 0.0), 'tol': 7.0, 'класс': 1}]
    rows = {'M': {'класс': 'сдвинута'}, 'S': {'класс': cls_s}}
    info = {}
    plan1, shifted, cancelled, flags, rooms = SC.correct(plan0, 1.0, cand, {}, {}, rows=rows, parallel=False, info=info)
    setup('')
    return plan1, shifted, cancelled, info


def md5(p):
    return hashlib.md5(json.dumps(p, ensure_ascii=False, indent=1).encode('utf-8')).hexdigest()


def test_step_passes():
    plan0 = plan_step()
    plan1, shifted, cancelled, info = correct(plan0, 17.0, 'остаток подгонки')
    assert [s['id'] for s in shifted] == ['M'], (shifted, cancelled)
    z = info['замкнутость']
    assert z['зелёная'] and not z['красные'] and not z['разрывы'], z
    assert (z['комнаты']['r1']['стен_до'], z['комнаты']['r1']['стен_после']) == (6, 5), z['комнаты']
    assert [c['стена'] for c in info['схлопнуто']] == ['S'], info['схлопнуто']
    assert info['увод_соседей_макс_см'] <= HB.CROSS_TOL_CM
    # те же данные БЕЗ разрешения (воротами Б-1) — красный: потеряна S
    hb_old = HB.check_all(plan0, plan1, 1.0)
    assert not hb_old['зелёная'] and any('потеряны' in x and "'S'" in x for x in hb_old['красные']), hb_old['красные']
    return z['комнаты']['r1'], info['схлопнуто']


def test_niche_cancelled():
    plan0 = plan_step()
    plan1, shifted, cancelled, info = correct(plan0, 17.0, 'на линии')
    assert shifted == [] and cancelled and all(c['причина'].startswith('контур не замыкается') for c in cancelled), (shifted, cancelled)
    assert md5(plan1) == md5(plan0), 'план не побайтно прежний'
    return cancelled[0]['причина'][:120], md5(plan1)


def test_not_a_step_cancelled():
    plan0 = plan_step(17.0)
    plan1, shifted, cancelled, info = correct(plan0, 10.0, 'остаток подгонки')       # перенос 10 → ступенька длиной 17 > 10 + 2
    assert shifted == [] and cancelled, (shifted, cancelled)
    return cancelled[0]['причина'][:120]


def test_control_broken_gate_collapses_niche():
    plan0 = plan_step()
    _p, shifted, cancelled, info = correct(plan0, 17.0, 'на линии', brk='niche')
    assert [s['id'] for s in shifted] == ['M'], 'испорченная копия обязана схлопнуть и нишу'
    try:
        assert shifted == [] and cancelled, 'ниша должна быть отменена'      # это утверждение теста (2) — на испорченной копии оно ПАДАЕТ
    except AssertionError:
        return 'тест ниши на испорченной копии КРАСНЫЙ (ниша схлопнута, перенос прошёл)'
    raise AssertionError('−контроль не сработал: тест ниши зелёный на испорченной копии')


def test_len_tolerance():
    plan0 = plan_step()
    exp = [{'id': 'M', 'a': (400.0, 0.0), 'b': (400.0, 200.0), 'd': (17.0, 0.0), 'tol': 7.0}]
    res = []
    for extra in (0.9, 1.5):
        plan1 = copy.deepcopy(plan0)
        for w in plan1['levels'][0]['walls']:
            if w['id'] == 'T':
                w['to'] = [400 + 17.0 + extra, 0]                 # сосед T у стыка удлинён на 17 + extra
        _r, viol, _m = HB.neighbor_limits(plan0, plan1, exp, 1.0)
        res.append((extra, [v for v in viol if v['вид'] == 'длина' and v['стена'] == 'T']))
    assert not res[0][1], res[0]
    assert res[1][1], res[1]
    return res


if __name__ == '__main__':
    out = {}
    r1, col = test_step_passes()
    print('PASS (1) ступенька S 17 см без чернил: перенос ПРОШЁЛ, стен у r1 %d→%d, контур замкнут; без разрешения (Б-1) — красный. схлопнуто: %s' % (r1['стен_до'], r1['стен_после'], col))
    c2, m2 = test_niche_cancelled()
    print('PASS (2) ниша (класс «на линии») → перенос отменён «%s…», план побайтно прежний md5 %s' % (c2, m2))
    c3 = test_not_a_step_cancelled()
    print('PASS (3) не ступенька (17 > перенос 10 + 2) → отмена «%s…»' % c3)
    c4 = test_control_broken_gate_collapses_niche()
    print('PASS (4) −контроль:', c4)
    c5 = test_len_tolerance()
    print('PASS (5) допуск (б) +1 см: +0,9 проходит, +1,5 — нарушение', c5)
    out.update({'1': {'комната': r1, 'схлопнуто': col}, '2': [c2, m2], '3': c3, '4': c4, '5': c5})
    json.dump(out, open(OUT + '/test-b2-itog.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('ВСЕ ПРОВЕРКИ Б-2 ПРОШЛИ')
