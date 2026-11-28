"""Флажок «проверь площадь» (T-171/флажок-площади; Fable ❓9, ❓25/❓26; rab-7 28.11): модуль `area_flag`, выключатель FP_AREA_FLAG, по умолчанию ВЫКЛ.

Без сети и моделей (идёт в CI): план — маленький рукописный plan.v1 в см.
  • граница 0,2216532258064516 (20-я из 20 худших слепой выборки полным числом, сравнение «не меньше»; Fable ❓38): расхождение 0,20 — тихо, 0,25 — строка «проверь площадь: комната X расходится с подписью на N % (толщина своя|условная)»;
  • толщина — РОВНО проверенный прибор: своя там, где есть; на листе «нет ни у одной» наружной своей — условные 0,35/0,06; на прочих — типовые 0,40/0,15; метка «своя/условная» у строки;
  • балкон/лоджия — вне флажка совсем (ни метки, ни «оправдания»), коэффициентов ×0,5/×0,3 нет; лист-схема (легло + широкая доля на линии + ≥ 2 комнат вне порога) — флажков нет;
  • выключатель: выкл (по умолчанию) — `sheet_lines` пуст; включён — строки; план и входы не меняются (глубокое сравнение);
  • ВОСПРОИЗВЕДЕНИЕ выборки (tests/floorplan/data/area_flag_sample.json — реальные 20 «худших» и 20 контрольных комнат слепой выборки 28.11, планы листов как есть): модуль метит 20 из 20 худших
    (20-я — граница по определению, «не меньше») и 0/20 контрольных, расхождения совпадают с прибором rab-7 до 1,5e-3; −контроль: типовые 0,40/0,15 на всех листах («другой прибор») метят меньше 20/20 — тест чувствителен;
  • сломал — покраснело: граница 0 флажит всё, «по осям» без вычета толщины уходит за допуск, подпись = чистой → флажка нет."""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import area_flag as AF  # noqa: E402

SAMPLE = ROOT / 'tests' / 'floorplan' / 'data' / 'area_flag_sample.json'


def wall(i, a, b, t=15, kind='interior'):
    return {'id': i, 'from': list(a), 'to': list(b), 'thickness': t, 'kind': kind}


def box(rid, name, x0, y0, w, h, t=15, kind='interior', **kw):
    """комната w×h см c четырьмя стенами на ребре; чистая площадь = (w−t)(h−t) см²"""
    pts = [[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]]
    walls = [wall('%s-w%d' % (rid, i), pts[i], pts[(i + 1) % 4], t, kind) for i in range(4)]
    room = {'id': rid, 'name': name, 'polygon': pts}
    room.update(kw)
    return room, walls


def make_plan(*boxes):
    rooms, walls = [], []
    for r, w in boxes:
        rooms.append(r)
        walls += w
    return {'units': 'cm', 'levels': [{'id': 'L1', 'rooms': rooms, 'walls': walls}]}


NET_4x3 = (4.0 - 0.15) * (3.0 - 0.15)      # 10,9725 м²


def test_net_area_minus_half_walls():
    plan = make_plan(box('r1', 'Комната', 0, 0, 400, 300))
    got = AF.net_areas(plan)['r1']
    assert abs(got - NET_4x3) < 1e-6
    assert got < 12.0 - 0.5            # −контроль: «по осям» 12 м² — вычет толщины живой


def test_boundary_just_below_and_above():
    plan = make_plan(box('r1', 'Комната', 0, 0, 400, 300))
    below = AF.evaluate(plan, {'r1': NET_4x3 / (1 - 0.20)})      # расхождение −20 % (чистая меньше подписи)
    above = AF.evaluate(plan, {'r1': NET_4x3 / (1 - 0.25)})      # −25 %
    assert below['flags'] == [] and below['lines'] == []
    assert len(above['flags']) == 1
    assert above['lines'] == ['проверь площадь: комната Комната расходится с подписью на 25 % (толщина своя)']


def test_printed_equal_to_clean_no_flag_and_boundary_zero_flags_all():
    plan = make_plan(box('r1', 'Комната', 0, 0, 400, 300))
    assert AF.evaluate(plan, {'r1': NET_4x3})['flags'] == []
    # −контроль: сломанная граница (0) флажит и почти точное совпадение → тест границы красный бы поймал замену числа
    assert len(AF.evaluate(plan, {'r1': NET_4x3 * 1.001}, boundary=0.0)['flags']) == 1


def test_boundary_value_frozen():
    assert AF.BOUNDARY == 0.2216532258064516      # полным числом, не 0,222 и не 0,2217 (0,2217 > 0,22165 — 20-я комната выпала бы)
    plan = make_plan(box('r1', 'Комната', 0, 0, 400, 300))
    assert len(AF.evaluate(plan, {'r1': NET_4x3 / (1 - (AF.BOUNDARY + 1e-9))})['flags']) == 1      # чуть выше границы — флажок (ровно на границе — тест воспроизведения ниже: 20-я комната)
    assert AF.evaluate(plan, {'r1': NET_4x3 / (1 - (AF.BOUNDARY - 1e-4))})['flags'] == []      # чуть ниже границы — тихо


def test_thickness_modes_and_label():
    # лист «нет ни у одной» наружной своей толщины → условные 0,35/0,06 (стены без своей толщины), метка «условная»
    r, w = box('r1', 'Комната', 0, 0, 400, 300, kind='exterior')
    for x in w:
        x['thickness'] = None
    plan = make_plan((r, w))
    assert AF.thickness_group(plan) == AF.NO_OWN
    assert abs(AF.net_areas(plan)['r1'] - (4.0 - AF.COND_EXT_M) * (3.0 - AF.COND_EXT_M)) < 1e-6
    res = AF.evaluate(plan, {'r1': 30.0})
    assert res['flags'][0]['thickness'] == 'условная' and res['lines'][0].endswith('(толщина условная)')
    # лист «у части»: одна наружная со своей, остальные без → типовые 0,40 для без-своей, метка «условная»
    w[0]['thickness'] = 40
    assert AF.thickness_group(plan) == AF.SOME_OWN
    assert abs(AF.net_areas(plan)['r1'] - (4.0 - 0.40) * (3.0 - 0.40)) < 1e-6
    assert AF.evaluate(plan, {'r1': 30.0})['flags'][0]['thickness'] == 'условная'
    # все стены со своей → метка «своя»; нет наружных, внутренние без толщины → типовые 0,15
    r2, w2 = box('r2', 'Комната', 0, 0, 400, 300)
    for x in w2:
        x['thickness'] = None
    p2 = make_plan((r2, w2))
    assert AF.thickness_group(p2) == AF.NO_EXT
    assert abs(AF.net_areas(p2)['r2'] - (4.0 - AF.TYP_INT_M) * (3.0 - AF.TYP_INT_M)) < 1e-6
    assert AF.evaluate(make_plan(box('r1', 'Комната', 0, 0, 400, 300)), {'r1': 30.0})['flags'][0]['thickness'] == 'своя'


def test_unknown_units_is_a_reason_not_a_guess():
    plan = make_plan(box('r1', 'Комната', 0, 0, 400, 300))
    plan['units'] = 'ft'
    res = AF.evaluate(plan, {'r1': 30.0})
    assert res['flags'] == [] and res['lines'] == [] and res['skipped'] and 'единицы' in res['skipped'][0][1]


def test_balcony_excluded_entirely_no_coefficients():
    """балкон/лоджия не метится и не «оправдывается»; ×0,5/×0,3 отменены; комната с подписью «в половину» — по-прежнему флажок"""
    plan = make_plan(box('r1', 'Комната', 0, 0, 400, 300), box('b1', 'Балкон', 500, 0, 300, 100, use='balcony'), box('b2', 'Лоджия', 900, 0, 500, 100))
    res = AF.evaluate(plan, {'r1': NET_4x3, 'b1': 6.0, 'b2': 0.5})
    assert res['flags'] == [] and res['lines'] == [] and 'balcony' not in res
    assert not hasattr(AF, 'BALCONY_K') and not hasattr(AF, 'balcony_dev')
    # комната: ни ×0,5, ни ×0,3 её не «оправдывают»
    for k in (0.5, 0.3):
        res = AF.evaluate(plan, {'r1': NET_4x3 * k})
        assert [f['id'] for f in res['flags']] == ['r1'], k


def test_scheme_sheet_gets_label_not_flags():
    plan = make_plan(box('r1', 'Спальня', 0, 0, 400, 300), box('r2', 'Кухня', 500, 0, 400, 300), box('r3', 'Зал', 1000, 0, 400, 300))
    printed = {'r1': 20.0, 'r2': 20.0, 'r3': NET_4x3}
    ov = {'overlay_status': 'легло', 'на_линии': 0.9}
    res = AF.evaluate(plan, printed, overlay=ov)
    assert res['scheme'] is True and res['flags'] == []
    assert res['lines'] == ['чертёж не сходится со своими подписями']
    # −контроль: без наложения (None) или при «не легло» класс «схема» не ставится — флажки на месте
    for o in (None, {'overlay_status': 'не легло', 'на_линии': 0.9}, {'overlay_status': 'легло', 'на_линии': 0.5}):
        r = AF.evaluate(plan, printed, overlay=o)
        assert r['scheme'] is False and {f['id'] for f in r['flags']} == {'r1', 'r2'}
    # одна комната вне порога — ещё не схема
    one = AF.evaluate(plan, {'r1': 20.0, 'r2': NET_4x3, 'r3': NET_4x3}, overlay=ov)
    assert one['scheme'] is False and [f['id'] for f in one['flags']] == ['r1']


def test_switch_default_off_and_on(monkeypatch):
    plan = make_plan(box('r1', 'Комната', 0, 0, 400, 300))
    printed = {'r1': 20.0}
    monkeypatch.delenv('FP_AREA_FLAG', raising=False)
    assert AF.enabled() is False
    assert AF.sheet_lines(plan, printed) == []
    for v in ('', '0', 'false', 'off', 'нет'):
        monkeypatch.setenv('FP_AREA_FLAG', v)
        assert AF.sheet_lines(plan, printed) == [], v
    monkeypatch.setenv('FP_AREA_FLAG', '1')
    lines = AF.sheet_lines(plan, printed)
    assert len(lines) == 1 and lines[0].startswith('проверь площадь: комната Комната расходится с подписью на ')


def test_does_not_change_inputs(monkeypatch):
    plan = make_plan(box('r1', 'Комната', 0, 0, 400, 300), box('b1', 'Лоджия', 500, 0, 300, 100))
    plan['levels'][0]['rooms'][0]['area'] = 12.0
    printed = {'r1': 20.0}
    ov = {'overlay_status': 'легло', 'на_линии': 0.9}
    snap = copy.deepcopy((plan, printed, ov))
    monkeypatch.setenv('FP_AREA_FLAG', '1')
    AF.sheet_lines(plan, printed, overlay=ov)
    AF.evaluate(plan, printed, overlay=ov)
    assert (plan, printed, ov) == snap


def test_missing_data_is_skipped_with_reason_not_guessed():
    plan = make_plan(box('r1', 'Комната', 0, 0, 400, 300))
    plan['levels'][0]['rooms'].append({'id': 'r9', 'name': 'Без контура'})
    res = AF.evaluate(plan, {'r1': None, 'r9': 20.0, 'zzz': 20.0, 'r0': 0})
    assert res['flags'] == [] and res['lines'] == []
    assert dict(res['skipped']) == {'r1': 'нет подписи', 'r9': 'нет контура комнаты', 'zzz': 'нет контура комнаты', 'r0': 'нет контура комнаты'}


def test_reproduces_blind_sample_20_of_20():
    """Приёмка Fable ❓25/❓38: модуль метит 20 из 20 худших слепой выборки (граница = расхождение 20-й, полным числом, «не меньше») и 0 из 20 контрольных, как прибор rab-7;
    расхождения модуля с ключом прибора — не больше 1,5e-3 на всех 40 комнатах"""
    data = json.loads(SAMPLE.read_text(encoding='utf-8'))
    rows = data['rooms']
    assert len(rows) == 40 and sum(1 for r in rows if r['class'] == 'worst') == 20

    def flagged(r, plan):
        res = AF.evaluate(plan, {r['room']: r['printed']})
        return [f for f in res['flags'] if f['id'] == r['room']]
    worst, ctrl, missed = 0, 0, []
    for r in rows:
        plan = data['plans'][r['sheet']]
        fl = flagged(r, plan)
        net = AF.net_areas(plan)[r['room']]
        assert abs((net - r['printed']) / r['printed'] - r['dev_key']) < 1.5e-3, (r['sheet'], r['room'])
        if r['class'] == 'worst':
            worst += 1 if fl else 0
            if not fl:
                missed.append((r['sheet'], r['room'], abs((net - r['printed']) / r['printed'])))
        else:
            ctrl += 1 if fl else 0
    # Решение Fable ❓38 (28.11): граница = |откл| 20-й худшей, kazan-14559042 r7, ПОЛНЫМ числом 0,2216532258064516 (ключ хранит округлённое −0,222), сравнение «не меньше» → 20/20.
    # Ближайший контроль — kazan-14132836 r6: 0,2215 (ниже границы), поэтому 0/20 контрольных.
    assert worst == 20 and missed == []
    r7 = [r for r in rows if (r['sheet'], r['room']) == ('kazan-14559042', 'r7')][0]
    net7 = AF.net_areas(data['plans']['kazan-14559042'])['r7']
    assert abs((net7 - r7['printed']) / r7['printed']) == AF.BOUNDARY      # 20-я комната лежит РОВНО на границе: это и есть определение (без «не меньше» она выпала бы)
    assert ctrl == data['control_flagged_by_instrument'] == 0       # столько же, сколько у прибора rab-7 (ключ слепой выборки): 0 из 20


def test_reproduction_minus_control_other_instrument_flags_fewer(monkeypatch):
    """−контроль: «другой прибор» (типовые 0,40/0,15 на всех листах, без условных 0,35/0,06) метит меньше 20/20 — выборка и тест чувствительны к толщине"""
    data = json.loads(SAMPLE.read_text(encoding='utf-8'))
    monkeypatch.setattr(AF, 'COND_EXT_M', AF.TYP_EXT_M)
    monkeypatch.setattr(AF, 'COND_INT_M', AF.TYP_INT_M)
    n = 0
    for r in data['rooms']:
        if r['class'] != 'worst':
            continue
        res = AF.evaluate(data['plans'][r['sheet']], {r['room']: r['printed']})
        n += 1 if any(f['id'] == r['room'] for f in res['flags']) else 0
    assert n < 20      # с условными 0,35/0,06 помечено 20; на «другом приборе» (типовые везде) заметно меньше (в замере 28.11 — 14)
