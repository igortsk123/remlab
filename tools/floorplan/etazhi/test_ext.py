#!/usr/bin/env python3
"""T-171/paket-ext · тест ext.py (числа кругов 2б/2в на листе). Герметичный: синтетические листы из fixtures/ext/{a,b}.json (рисуются в памяти, файлов листов нет),
вместо vetka_fit — маленькая заглушка с теми же именами (load_gray, ink_mask, segs_of, rot_about, bg_kernel, TOL_MIN и настройки). Сеть, платное, живые папки не трогает.
Проверяет: «на линии узко/широко», «бледная» (3 порога), окно ответа (offset от `from`, дверь и окно на несуществующей стене не считаются), класс без окон, фикстура b (масштаб 2 + flipy) = числа фикстуры a,
поворот плана (rot_deg/rot_center_cm), отказ при чужих настройках vetka_fit, нет входа, размер картинки ≠ sheet_px, «не сошлось с walls.csv», порядок вариантов, with_ext_numbers, applicable, current_hit.
Запуск: python -I test_ext.py   (нужны numpy, cv2; нет — «SKIP», код 0). Обеднённо: bash ~/remlab-logs/common-manager/bedno.sh <папка> ~/venvs/nc-models ~/venvs/nc-models/bin/python -I test_ext.py"""
import copy
import json
import math
import os
import sys
import types

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import numpy as np  # noqa: E402
    import cv2  # noqa: E402,F401
except ImportError as ex:
    print('SKIP: нет %s' % ex)
    sys.exit(0)
import ext as X  # noqa: E402

bad = []


def check(ok, msg, extra=''):
    print(('OK   ' if ok else 'FAIL ') + msg + ('' if ok else ' :: ' + str(extra)[:300]))
    if not ok:
        bad.append(msg)


def near(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol


def make_vf(**over):
    """заглушка vetka_fit: чернила = тёмное (<128), единицы — см, как настоящий segs_of; настройки как у мерки (V2, SOFT_INK)"""
    vf = types.SimpleNamespace(V2=True, SOFT_INK=True, INK_PALE=False, INK_THICK=False, INK_LAYERS='', TOL_MIN=3.0)
    vf.load_gray = lambda p: (_ for _ in ()).throw(AssertionError('картинки — массивами, файлы не читаем'))
    vf.ink_mask = lambda g: g < 128
    vf.bg_kernel = lambda g: max(15, int(0.02 * max(g.shape)) | 1)

    def segs_of(plan):
        out = []
        for lv in plan['levels']:
            for w in lv.get('walls', []):
                out.append((w['from'][0], w['from'][1], w['to'][0], w['to'][1], float(w['thickness']), w.get('id', '')))
        return out
    vf.segs_of = segs_of

    def rot_about(Q, deg, c):
        a = math.radians(deg)
        ca, sa = math.cos(a), math.sin(a)
        d = Q - np.array(c)
        return np.stack([c[0] + d[:, 0] * ca - d[:, 1] * sa, c[1] + d[:, 0] * sa + d[:, 1] * ca], 1)
    vf.rot_about = rot_about
    for k, v in over.items():
        setattr(vf, k, v)
    return vf


def load_fx(name):
    return json.load(open(os.path.join(HERE, 'fixtures', 'ext', name + '.json'), encoding='utf-8'))


def draw(fx):
    W, H = fx['sheet']
    g = np.full((H, W), 255, np.uint8)
    for x0, y0, x1, y1, val, th in fx['draw']:
        h = th // 2
        g[min(y0, y1) - h:max(y0, y1) + h + 1, min(x0, x1) - h:max(x0, x1) + h + 1] = val
    return g


def run(fx, vf=None, **kw):
    vf = vf or make_vf()
    g = draw(fx)
    cands = X.candidates({'plan-clean.json': fx['plan'], 'plan.json': None}, {'d': g, 'b': None})
    e2 = X.ext2b('fx', cands, kw.get('fit', fx['fit']), kw.get('rows', fx['rows']), vf)
    e3 = X.ext2c('fx', cands, kw.get('fit', fx['fit']), kw.get('rows', fx['rows']), vf, **kw.get('c_kw', {}))
    return e2, e3


def wall(e, wid):
    return next(w for w in e['стены'] if w['стена'] == wid)


# ── фикстура a: числа 2б и 2в ───────────────────────────────────────────────
fa = load_fx('a')
b2, b3 = run(fa)
check(b2['статус'] == 'ok' and b3['статус'] == 'ok', 'a: оба статуса ok', (b2['статус'], b3['статус']))
check(b2['картинка'] == 'plan-clean.json/d' and b2['допуск_узкий_px'] == 4.0 and b2['допуск_лист_px'] == 3.6, 'a: вариант и допуски (TOL_MIN+1; 1,2 % большей стороны листа)', (b2['картинка'], b2['допуск_узкий_px'], b2['допуск_лист_px']))
check(wall(b2, 'w1')['узко'] == 1.0 and wall(b2, 'w2')['узко'] == 0.0 and near(wall(b2, 'w3')['узко'], 0.519, 0.012) and wall(b2, 'w4')['узко'] == 0.0, 'a: узкая доля на чернилах по стенам (1 / 0 / ≈0,52 / 0)',
      [wall(b2, w)['узко'] for w in ('w1', 'w2', 'w3', 'w4')])
check(near(wall(b2, 'w3')['широко_толщина'], 0.542, 0.002) and near(wall(b2, 'w3')['широко_лист'], 0.527, 0.003), 'a: «широко» w3: от толщины (0,542) шире, чем от листа (0,527)', (wall(b2, 'w3')['широко_толщина'], wall(b2, 'w3')['широко_лист']))
check(wall(b2, 'w4')['широко_толщина'] == 0.0, 'a: w4 (серая линия, не чернила) — широко 0', wall(b2, 'w4'))
check(b2['на_линии_узко'] == round(sum(w['длина_px'] * w['узко'] for w in b2['стены']) / sum(w['длина_px'] for w in b2['стены']), 3) and near(b2['на_линии_узко'], 0.488, 0.005), 'a: на линии по листу — длинно-взвешенно', b2['на_линии_узко'])
pal = lambda w: wall(b2, w)['бледная']
check(set(pal('w4')) == {'215', '225', '235'} and pal('w4')['225'] == 1.0 and pal('w2')['225'] == 0.0 and pal('w1')['225'] == 1.0 and near(pal('w3')['225'], 0.504, 0.012), 'a: бледная линия по 3 порогам: серая w4 = 1, пустая w2 = 0, чернила w1 = 1, w3 ≈ 0,50',
      [pal(w) for w in ('w1', 'w2', 'w3', 'w4')])
check(b3['окон'] == 1 and b3['стен_с_окном'] == 1, 'a: окон 1 (дверь и окно на несуществующей стене не считаются)', (b3['окон'], b3['стен_с_окном']))
w3c = wall(b3, 'w3')
check(0.49 <= w3c['окно_доля'] <= 0.51 and w3c['узко_без_окон'] == 1.0 and w3c['класс'] == 'выдуманная' and w3c['класс_без_окон'] == 'на линии', 'a: w3 — правая половина окно; без окна чернила 1,0 → «выдуманная» → «на линии»', w3c)
check(wall(b3, 'w2')['окно_доля'] == 0.0 and wall(b3, 'w2')['класс_без_окон'] == 'выдуманная' and wall(b3, 'w4')['класс_без_окон'] == 'выдуманная', 'a: стены без окна остаются «выдуманная»', (wall(b3, 'w2'), wall(b3, 'w4')))
check(near(b3['на_линии_узко'], 0.482, 0.005) and near(b3['на_линии_узко_без_окон'], 0.565, 0.01), 'a: на линии по листу с окнами 0,48 → без окон ≈0,565', (b3['на_линии_узко'], b3['на_линии_узко_без_окон']))
for end, want in ((130, 'на линии'), (90, 'неполная'), (50, 'выдуманная')):      # чернила w3 кончаются раньше окна: доля без окон 0,88 / 0,57 / 0,26 → пороги 0,7 и 0,35
    fp = copy.deepcopy(fa)
    fp['draw'][1] = [20, 160, end, 160, 0, 5]
    _, p3 = run(fp)                                                              # статус может быть «не сошлось» (walls.csv фикстуры не менялась) — числа считаются всё равно
    check(wall(p3, 'w3')['класс_без_окон'] == want, 'a: w3 с чернилами до x=%d — класс без окон «%s»' % (end, want), (wall(p3, 'w3')['узко_без_окон'], wall(p3, 'w3')['класс_без_окон']))
_, d3 = run(fa, c_kw={'types': ('window', 'door')})
check(d3['окон'] == 2 and 0.3 < wall(d3, 'w2')['окно_доля'] < 0.5, 'a: виды проёмов — параметр (с дверью окон 2, дверь «съедает» ≈40 % w2)', (d3['окон'], wall(d3, 'w2')['окно_доля']))

# ── фикстура b: масштаб 2 + flipy = числа a ─────────────────────────────────
fb = load_fx('b')
c2, c3 = run(fb)


def same(e1, e2, skip=('длина_м',)):
    def norm(v):
        if isinstance(v, dict):
            return {k: norm(x) for k, x in v.items() if k not in skip}
        if isinstance(v, list):
            return [norm(x) for x in v]
        return v
    return norm(e1) == norm(e2)


check(same(b2, c2) and same(b3, c3), 'b: масштаб 2 + перевёрнутая ось Y дают ТЕ ЖЕ числа, что фикстура a (кроме длины в единицах плана)', (c2['статус'], c3['статус']))
check(near(wall(c2, 'w1')['длина_м'] * 2, wall(b2, 'w1')['длина_м'], 1e-9), 'b: длина_м пересчитана по масштабу плана', (wall(c2, 'w1')['длина_м'], wall(b2, 'w1')['длина_м']))

# ── поворот плана: план повёрнут на 180° вокруг центра, fit.rot_deg=180 возвращает его обратно ──
fr = copy.deepcopy(fa)
cx, cy = 150.0, 100.0
for lv in fr['plan']['levels']:
    for w in lv['walls']:
        w['from'] = [2 * cx - w['from'][0], 2 * cy - w['from'][1]]
        w['to'] = [2 * cx - w['to'][0], 2 * cy - w['to'][1]]
fr['fit'] = dict(fa['fit'], rot_deg=180.0, rot_center_cm=[cx, cy])
r2, r3 = run(fr)
check(r2['статус'] == 'ok' and r3['статус'] == 'ok' and same(b2, r2) and same(b3, r3), 'поворот: план на 180° + fit.rot_deg=180 → те же числа, что без поворота', (r2['статус'], r3['статус']))

# ── отказы и крайние случаи ───────────────────────────────────────────────────
for nm, over in (('CORRECT_V2', {'V2': False}), ('SOFT_INK', {'SOFT_INK': False}), ('INK_PALE', {'INK_PALE': True}), ('INK_THICK', {'INK_THICK': True}), ('INK_LAYERS', {'INK_LAYERS': '1'})):
    e2, e3 = run(fa, vf=make_vf(**over))
    check(e2['статус'].startswith('отказ') and e3['статус'].startswith('отказ') and nm in e2['статус'], 'отказ при чужой настройке vetka_fit: %s — не «ok», причина названа' % nm, (e2['статус'], e3['статус']))
e2, e3 = run(fa, fit=None)
check(e2['статус'] == 'нет входа' and e3['статус'] == 'нет входа', 'нет fit → «нет входа»', (e2['статус'], e3['статус']))
fw = copy.deepcopy(fa)
fw['fit']['sheet_px'] = [301, 200]
e2, e3 = run(fa, fit=fw['fit'])
check(e2['статус'] == 'нет картинки листа' and e3['статус'] == 'нет картинки листа', 'размер картинки ≠ sheet_px наложения → «нет картинки листа»', (e2['статус'], e3['статус']))
rows_bad = copy.deepcopy(fa['rows'])
rows_bad[0]['доля_на_чернилах'] = '0.2'
e2, e3 = run(fa, rows=rows_bad)
check(e2['статус'] == 'не сошлось с walls.csv' and e3['статус'] == 'не сошлось с walls.csv' and near(e2['расхождение_узкой_доли_макс'], 0.8, 0.001), 'узкая доля не сходится с walls.csv (>0,03) → «не сошлось», расхождение 0,8', (e2['статус'], e2['расхождение_узкой_доли_макс']))
e2, e3 = run(fa, rows=[])
check(e2['статус'] == 'ok' and e3['статус'] == 'ok' and wall(e3, 'w2')['класс'] == '', 'без строк walls.csv считает по плану (класс пустой) — как мерка', (e2['статус'], e3['статус']))
boom = make_vf()
boom.segs_of = lambda p: (_ for _ in ()).throw(KeyError('x'))
e2, e3 = run(fa, vf=boom)
check(e2['статус'].startswith('сбой: KeyError') and e3['статус'].startswith('сбой: KeyError'), 'исключение внутри → «сбой: …», не падение', (e2['статус'], e3['статус']))

# ── порядок вариантов, with_ext_numbers, applicable, current_hit ──────────────
g = draw(fa)
cs = X.candidates({'plan-clean.json': fa['plan'], 'plan.json': fa['plan']}, {'d': g, 'b': g})
check([c[0] for c in cs] == ['plan-clean.json/d', 'plan-clean.json/b', 'plan.json/d', 'plan.json/b'], 'порядок вариантов как у мерки: plan-clean/d, plan-clean/b, plan/d, plan/b', [c[0] for c in cs])
check(X.candidates({'plan-clean.json': None, 'plan.json': fa['plan']}, {'d': None, 'b': g}) == [('plan.json/b', fa['plan'], g)], 'нет плана или картинки — вариант пропущен')
ov0 = dict(fa['ov'])
o, st = X.with_ext_numbers(ov0, 'fx', X.candidates({'plan-clean.json': fa['plan']}, {'d': g}), fa['fit'], fa['rows'], make_vf())
check(st['ext2b'] == 'ok' and st['ext2c'] == 'ok' and st['лист_для_ext'] == X.APPLIES and o['ext2b']['статус'] == 'ok' and o['ext2c']['статус'] == 'ok' and 'ext2b' not in ov0 and 'ext2c' not in ov0, 'with_ext_numbers: добавляет ext2b/ext2c копией, исходное наложение не меняется', (st, sorted(o)))
o, st = X.with_ext_numbers(ov0, 'fx', X.candidates({'plan-clean.json': fa['plan']}, {'d': g}), fa['fit'], fa['rows'], make_vf(V2=False))
check(st['ext2b'].startswith('отказ') and 'ext2b' not in o and 'ext2c' not in o, 'with_ext_numbers: отказ → полей нет (звонок «Ст» как раньше), статус виден для guard.json', st)
o, st = X.with_ext_numbers(ov0, 'fx', X.candidates({'plan-clean.json': fa['plan']}, {'d': g}), fa['fit'], fa['rows'], make_vf(), want_2c=False)
check('ext2b' in o and 'ext2c' not in o and st['ext2c'] is None, 'with_ext_numbers: можно считать только 2б')
check(X.applicable(fa['ov'], fa['rows']) and not X.applicable(dict(fa['ov'], overlay_status='частично'), fa['rows']) and not X.applicable(dict(fa['ov'], вход='кроп'), fa['rows']) and not X.applicable(fa['ov'], []) and not X.applicable(None, fa['rows']), 'applicable: «легло» + вход «как есть» + есть стены')
wf = {'fabricated_share_min': 0.15, 'extra_m_min': 8.0, 'on_line_min': 0.60}
check(X.current_hit(fa['rows'], fa['ov'], wf), 'current_hit: выдуманных 600 из 820 px (≥15 %) → «Ст» звонит')
check(not X.current_hit([fa['rows'][0]], dict(fa['ov'], на_линии=0.9, лишнее_м=1.0), wf) and X.current_hit([fa['rows'][0]], dict(fa['ov'], на_линии=0.5, лишнее_м=1.0), wf) and X.current_hit([fa['rows'][0]], dict(fa['ov'], на_линии=0.9, лишнее_м=9.0), wf), 'current_hit: пороги «на линии» и «лишнее, м»')

# ── два случая «листа без чисел» (Fable по ext): нет наложения → не применяется + пометка; файл/вход пропал по ошибке → СТОП ──────────────────────────────────────────
cs_ok = X.candidates({'plan-clean.json': fa['plan']}, {'d': g})
for nm, ov_x, kind_w, why_w in (('нет наложения (overlay.json не получен)', None, X.SKIP, 'нет наложения'),
                                ('наложение «не легло»', dict(fa['ov'], overlay_status='не легло'), X.SKIP, 'не легло'),
                                ('наложение «частично»', dict(fa['ov'], overlay_status='частично'), X.SKIP, 'частично'),
                                ('вход не «как есть» (4c)', dict(fa['ov'], вход='4c'), X.SKIP, '4c')):
    kd, ws = X.coverage(ov_x, fa['rows'], fa['fit'], cs_ok)
    o, st = X.with_ext_numbers(ov_x, 'fx', cs_ok, fa['fit'], fa['rows'], make_vf())          # без исключения; числа не считаются; пометка в статусах
    check(kd == kind_w and why_w in ws and st['лист_для_ext'] == X.SKIP and st['ext2b'].startswith('не применяется') and st['ext2c'].startswith('не применяется') and why_w in st['ext2b'] and 'ext2b' not in o and 'ext2c' not in o,
          'не применяется + пометка: %s' % nm, (kd, ws, st))
kd, ws = X.coverage(fa['ov'], fa['rows'], fa['fit'], cs_ok)
check(kd == X.APPLIES and ws == '', 'применяется: «легло», вход «как есть», стены/fit/картинка есть', (kd, ws))
for nm, rows_x, fit_x, cs_x, want_w in (('нет walls.csv', [], fa['fit'], cs_ok, 'walls.csv'), ('нет fit.json', fa['rows'], None, cs_ok, 'fit.json'), ('нет картинки/ответа листа', fa['rows'], fa['fit'], [], 'картинки'),
                                        ('пропало всё сразу', [], None, [], 'walls.csv (или пуст); нет fit.json; нет картинки')):
    kd, ws = X.coverage(fa['ov'], rows_x, fit_x, cs_x)
    try:
        X.with_ext_numbers(fa['ov'], 'fx', cs_x, fit_x, rows_x, make_vf())
        raised = None
    except X.ExtStop as ex:
        raised = str(ex)
    o, st = X.with_ext_numbers(fa['ov'], 'fx', cs_x, fit_x, rows_x, make_vf(), stop=False)
    check(kd == X.STOP and want_w in ws and raised is not None and raised.startswith('fx:') and want_w in raised and st['лист_для_ext'] == X.STOP and st['ext2b'].startswith('СТОП') and 'ext2b' not in o and 'ext2c' not in o,
          'СТОП (пропал вход при «легло»): %s — ExtStop, а с stop=False пометка «СТОП» и чисел нет' % nm, (kd, ws, raised, st))
for vh, want_kind in (('как есть', X.APPLIES), ('как есть (4c не лучше)', X.APPLIES), ('4c', X.SKIP), ('4c, потом как есть', X.SKIP), ('', X.SKIP)):   # правило «префикс как есть» (директор 27.11): оба вида «как есть» применяются
    ov_v = dict(fa['ov'], вход=vh)
    kd, ws = X.coverage(ov_v, fa['rows'], fa['fit'], cs_ok)
    o, st = X.with_ext_numbers(ov_v, 'fx', cs_ok, fa['fit'], fa['rows'], make_vf())
    ok_v = (kd == want_kind and X.applicable(ov_v, fa['rows']) == (want_kind == X.APPLIES) and (st['ext2b'] == 'ok' and 'ext2b' in o) == (want_kind == X.APPLIES))
    check(ok_v, 'вход «%s» → %s (coverage, applicable и числа согласованы)' % (vh, want_kind), (kd, ws, st))
o, st = X.with_ext_numbers(dict(fa['ov']), 'fx', cs_ok, fa['fit'], fa['rows'], make_vf())
check(X.coverage({k: v for k, v in fa['ov'].items() if k != 'вход'}, fa['rows'], fa['fit'], cs_ok)[0] == X.APPLIES, 'нет поля «вход» → как есть (применяется)')
o, st = X.with_ext_numbers(fa['ov'], 'fx', [], None, [], make_vf(), want_2b=False, want_2c=False)
check(st['лист_для_ext'] is None and o == fa['ov'], 'оба выключателя 2б/2в выкл — листы не классифицируются, СТОПа нет')

print('ошибок %d' % len(bad))
sys.exit(1 if bad else 0)
