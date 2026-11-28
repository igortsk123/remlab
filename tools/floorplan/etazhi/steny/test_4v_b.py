"""Круг Б 4в (rab-10, 28.11): перенос БЕЗ увода соседей + обязательная проверка замкнутости комнат, с −контролем.
Запуск (локально, нужна папка work/ — STENY_WORK; вывод — STENY_OUT или tmp): python -B -I test_4v_b.py (venv scout; через heavy-slot 1 ядро), без OCR и агента. Данные — kazan-14726759 из inventory-ekz.json (4в-экзамен).
ПРОВЕРКИ (зелёные): (1) с --hold-neighbors перенесены обе стены лоджии, проверка замкнутости ЗЕЛЁНАЯ, увод соседей поперёк ≤ 1 см (мерка rab-6 neighbor_drift);
(2) контрольный «ничего не менять» план — зелёный (проверка не краснит на пустом месте).
−КОНТРОЛЬ (проверка обязана быть КРАСНОЙ): (3) стык не подгоняется (hold_fit fit=False) → красная; (4) сосед выкинут (w_left убрана из плана «после») → красная;
(5) стык не подгоняется внутри correct() (HOLD_BREAK='nofit') → перенос ОТМЕНЁН воротами замкнутости (причина «контур не замыкается»);
ПОПРАВКА Fable 28.11: (7) два ограничения на листе — поперечный увод концов соседей = 0, рост длины соседа ≤ переноса, числа в report; (8)/(9) −контроль на каждое (конец соседа уходит поперёк / сосед удлинён сверх переноса → отмена с причиной);
(10) синтетика ❓2: у переносимых стен нет поперечной стены → отмена «контур не замыкается», план побайтно прежний; (6) прежний 4в f (res-k4v-f-ekz) → красная (наклонённая w_top: стык разошёлся)."""
import copy
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
SID = 'kazan-14726759'
INV = [e for e in json.load(open(ST.ORIG + '/inventory-ekz.json', encoding='utf-8')) if e['лист'] == SID]
assert len(INV) == 1
E = INV[0]
PLAN0 = json.load(open(E['plan'], encoding='utf-8'))
K = SC.plan_walls(PLAN0)[1]


def setup(hold, brk=''):
    ST.CLASSES, ST.PARALLEL, ST.MASK_WORDS = '1', True, False
    SC.EVIDENCE = SC.PROFILE = SC.AREA_FLAG_ONLY = SC.NODIGIT_FLAG = SC.PR_OLD_ON_INK = SC.WHOLE_MISS = True       # боевой набор f
    SC.NEIGHBOR_DRIFT = False
    SC.HOLD_NEIGHBORS = hold
    SC.HOLD_BREAK = brk


def run(hold, brk='', tag='b', e=None):
    setup(hold, brk)
    out = OUT + '/res-test-' + tag
    os.makedirs(out, exist_ok=True)
    return ST.one(e or E, 'inner', out, SC.OV.load_cfg()), out


def moved_ids(r):
    return sorted(x['стена'] for x in r.get('перенесено', []))


def exp_of(r):
    ws = {w['id']: w for w in SC.plan_walls(PLAN0)[0]}
    return [{'id': m['стена'], 'a': ws[m['стена']]['a'], 'b': ws[m['стена']]['b'], 'd': (m['dx_см'], m['dy_см']), 'tol': max(ws[m['стена']]['th'] / 2, 5.0) + 2.0} for m in r['перенесено']]


def max_drift(plan1, moved):
    d = SC.neighbor_drift(PLAN0, plan1, K, set(moved))
    return max((v[0] for v in d.values()), default=0.0)


def test_green_hold():
    r, out = run(True)
    assert moved_ids(r) == ['w_log_bottom', 'w_log_top'], moved_ids(r)
    hb = r['замкнутость']
    assert hb and hb['зелёная'] and not hb['красные'] and not hb['разрывы'], hb
    assert all(v['замкнута'] and v['стен_до'] == v['стен_после'] and v['площадь_после_м2'] > 0 for v in hb['комнаты'].values()), hb['комнаты']
    plan1 = json.load(open(out + '/' + SID + '/plan-after.json', encoding='utf-8'))
    dr = max_drift(plan1, moved_ids(r))
    assert dr <= 1.0, dr
    return r, hb, dr


def test_control_nothing_changed_green():
    hb = HB.check_all(PLAN0, copy.deepcopy(PLAN0), K)
    assert hb['зелёная'], hb


def test_control_no_fit_red(r):
    plan_bad = HB.hold_fit(PLAN0, exp_of(r), K, fit=False)
    hb = HB.check_all(PLAN0, plan_bad, K)
    assert not hb['зелёная'], 'проверка слепа: стык не подогнан, а она зелёная'
    return hb


def test_control_neighbor_dropped_red(out):
    plan1 = json.load(open(out + '/' + SID + '/plan-after.json', encoding='utf-8'))
    bad = copy.deepcopy(plan1)
    for lv in bad['levels']:
        lv['walls'] = [w for w in lv['walls'] if w['id'] != 'w_left']
    hb = HB.check_all(PLAN0, bad, K)
    assert not hb['зелёная'], 'проверка слепа: сосед w_left выкинут, а она зелёная'
    return hb


def test_control_gate_cancels_nofit():
    r, _out = run(True, 'nofit', 'nofit')
    setup(False)
    assert moved_ids(r) == [], moved_ids(r)
    assert any(c['причина'].startswith('контур не замыкается') for c in r['отменено']), r['отменено']
    return r


def test_control_old_4vf_red():
    p = json.load(open(ST.ORIG + '/res-k4v-f-ekz/' + SID + '/plan-after.json', encoding='utf-8'))
    hb = HB.check_all(PLAN0, p, K)
    assert not hb['зелёная'], 'проверка не видит наклонённую w_top прошлого 4в f'
    return hb, max_drift(p, ['w_log_top', 'w_log_bottom'])


def test_limits_report(r):
    """(7) оба ограничения Fable на реальном листе: поперечный увод ВСЕХ концов соседей = 0, рост длины соседа у каждого стыка ≤ переноса; числа лежат в report."""
    rows = r['соседи_стыки']
    assert r['увод_соседей_макс_см'] <= HB.CROSS_TOL_CM, r['увод_соседей_макс_см']
    assert {(x['стена'], x['конец']) for x in rows} >= {('w_left', 0), ('w_left', 1), ('w_log_left', 0), ('w_log_left', 1)}, rows
    for x in rows:
        assert x['увод_поперёк_см'] <= HB.CROSS_TOL_CM, x
        assert x['перенос_см'] is not None and abs(x['скольжение_см']) <= x['перенос_см'] + HB.LEN_TOL_CM, x
    return rows


def test_control_limit(r_green, brk, kind):
    """(8)/(9) −контроль на каждое ограничение: испорченная копия (конец соседа уходит поперёк на 5 см / сосед удлиняется в 2,5 раза больше переноса) → нарушение и ОТМЕНА с причиной."""
    plan_bad = HB.hold_fit(PLAN0, exp_of(r_green), K, fit=True, brk=brk)
    _rows, viol, mx = HB.neighbor_limits(PLAN0, plan_bad, exp_of(r_green), K)
    assert any(v['вид'] == kind for v in viol), (brk, viol)
    r, _out = run(True, brk, 'ctl-' + brk)
    setup(False)
    assert moved_ids(r) == [], moved_ids(r)
    key = 'увод конца поперёк' if kind == 'увод' else 'удлиняется'
    assert any(key in c['причина'] for c in r['отменено']), r['отменено']
    return viol[:2], [c['причина'] for c in r['отменено']]


def test_synthetic_no_cross():
    """(10) ❓2 Fable: у переносимой стены нет поперечной стены (из плана листа убраны w_left и w_log_left): перенос ОТМЕНЁН, причина «контур не замыкается», план побайтно прежний (md5 до = после)."""
    p = copy.deepcopy(PLAN0)
    for lv in p['levels']:
        lv['walls'] = [w for w in lv['walls'] if w['id'] not in ('w_left', 'w_log_left')]
    os.makedirs(OUT + '/synt', exist_ok=True)
    path = OUT + '/synt/plan-bez-poperechnyh.json'
    json.dump(p, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    e = dict(E)
    e['plan'] = path
    r, _out = run(True, '', 'synt', e)
    setup(False)
    assert moved_ids(r) == [], moved_ids(r)
    assert r['отменено'] and all(c['причина'].startswith('контур не замыкается') for c in r['отменено']), r['отменено']
    assert r['план_байты_равны'] and r['план_до_md5'] == r['план_после_md5'] and r['план_равен_исходному_файлу'], (r['план_до_md5'], r['план_после_md5'])
    return r


if __name__ == '__main__':
    res = {}
    r, hb, dr = test_green_hold()
    print('PASS (1) hold: перенесено', moved_ids(r), '· замкнутость ЗЕЛЁНАЯ · макс. увод соседей %.3f см' % dr)
    res['1'] = {'перенесено': moved_ids(r), 'увод_макс_см': round(dr, 3), 'комнаты': hb['комнаты']}
    test_control_nothing_changed_green()
    print('PASS (2) план без правок — проверка зелёная (не краснит на пустом месте)')
    out = OUT + '/res-test-b'
    h3 = test_control_no_fit_red(r)
    print('PASS (3) −контроль стык не подогнан → КРАСНАЯ:', h3['красные'][:2], h3['разрывы'][:2])
    h4 = test_control_neighbor_dropped_red(out)
    print('PASS (4) −контроль сосед w_left выкинут → КРАСНАЯ:', h4['красные'][:2], h4['разрывы'][:2])
    r5 = test_control_gate_cancels_nofit()
    print('PASS (5) −контроль в correct(): стык не подгоняется → перенос отменён:', [c['причина'][:110] for c in r5['отменено']])
    h6, d6 = test_control_old_4vf_red()
    print('PASS (6) прежний 4в f → КРАСНАЯ (разрывы %s), увод соседей там %.1f см' % (h6['разрывы'][:2], d6))
    rows7 = test_limits_report(r)
    print('PASS (7) ограничения Fable на листе: увод макс %.3f см; скольжение стыков, см (≤ переноса): %s' % (r['увод_соседей_макс_см'], [(x['стена'], x['конец'], x['скольжение_см'], x['перенос_см']) for x in rows7]))
    v8, c8 = test_control_limit(r, 'cross', 'увод')
    print('PASS (8) −контроль (а) конец соседа уходит поперёк → нарушение и ОТМЕНА:', v8, c8)
    v9, c9 = test_control_limit(r, 'long', 'длина')
    print('PASS (9) −контроль (б) сосед удлинён сверх переноса → нарушение и ОТМЕНА:', v9, c9)
    r10 = test_synthetic_no_cross()
    print('PASS (10) нет поперечной стены → отменено «%s…», план побайтно прежний (md5 %s)' % (r10['отменено'][0]['причина'][:40], r10['план_до_md5']))
    res['7'], res['8'], res['9'], res['10'] = rows7, [v8, c8], [v9, c9], {'отменено': r10['отменено'], 'md5_до': r10['план_до_md5'], 'md5_после': r10['план_после_md5'], 'байты_равны': r10['план_байты_равны']}
    res['3'], res['4'], res['6'] = h3['красные'], h4['красные'], {'красные': h6['красные'], 'разрывы': h6['разрывы'], 'увод_см': round(d6, 1)}
    json.dump(res, open(OUT + '/test-itog.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('ВСЕ ПРОВЕРКИ ПРОШЛИ')
