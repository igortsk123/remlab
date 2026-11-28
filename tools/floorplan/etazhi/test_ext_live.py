#!/usr/bin/env python3
"""T-171/paket-ext · storozh.with_ext_live (строка вызова из OTCHET-ext.md + правило Fable 27.11 22:57): числа 2б/2в считаются на листе, когда нужны — по выключателям walls_fail (wide_line / pale_line / windows);
для одного 2б на годном листе — только когда «Ст» звонит по базовым числам. Два исхода без чисел: «наложения нет / не «легло» / вход не «как есть»» → «не применяется» + пометка ext_статус в guard.json, прогон идёт;
«легло», а вход для расчёта пропал (walls.csv / fit.json / картинка / ответ) или числа не посчитаны («сбой» / «отказ») → ExtStop = СТОП с причиной. Сами числа — ext.py (test_ext.py).
Герметично: ext.with_ext_numbers подменяется записью вызова (кроме разделов с настоящим), vetka_fit — заглушка.
Запуск (обеднённо): bash ~/remlab-logs/common-manager/bedno.sh <папка> ~/venvs/nc-models python tools/floorplan/etazhi/test_ext_live.py   (нужны numpy, cv2, shapely — их тянет storozh)."""
import copy
import os
import sys
import types

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for name in ('nc_eval', 'neutral_names', 'words_on_sheet', 'vetka_a_eval', 'vetka_a_cmp_bd'):      # модули чужих папок (в обеднённом окружении их нет); вызову они не нужны
    sys.modules.setdefault(name, types.ModuleType(name))
os.environ['SB_RULES'] = HERE + '/storozh_rules.json'
import ext as X  # noqa: E402
import storozh as S  # noqa: E402

bad = []


def check(ok, msg, extra=''):
    print(('OK   ' if ok else 'FAIL ') + msg + ('' if ok else ' :: ' + str(extra)[:300]))
    if not ok:
        bad.append(msg)


CALLS = []
FAKE_ST = {}          # что вернёт подмена: статусы чисел; по умолчанию — ok по запрошенному


def fake(ov, sid, cands, fit, rows, vf, want_2b=True, want_2c=True, stop=True):
    CALLS.append({'sid': sid, 'labels': [c[0] for c in cands], 'plans': [c[1] for c in cands], 'imgs': [c[2] for c in cands], 'b': want_2b, 'c': want_2c})
    o = dict(ov or {})
    o['ext_called'] = True
    st = {'ext2b': 'ok' if want_2b else None, 'ext2c': 'ok' if want_2c else None}
    st.update(FAKE_ST)
    return o, st


REAL = X.with_ext_numbers
X.with_ext_numbers = fake


def rules(wide=False, pale=False, win=False):
    r = copy.deepcopy(S.RULES)
    r['walls_fail']['wide_line']['enabled'] = wide
    r['walls_fail']['pale_line']['enabled'] = pale
    r['walls_fail']['windows']['enabled'] = win
    return r


OV_QUIET = {'overlay_status': 'легло', 'вход': 'как есть', 'на_линии': 0.9, 'лишнее_м': 0.0}          # «Ст» по базовым числам не звонит
OV_HIT = dict(OV_QUIET, на_линии=0.4)                                                                  # звонит: на линии < 0,6
ROWS = [{'стена': 'w1', 'длина_px': 100.0, 'класс': 'верная'}, {'стена': 'w2', 'длина_px': 80.0, 'класс': 'верная'}]
FIT = {'fit': 1}
PC, P = {'rooms': 'pc'}, {'rooms': 'p'}


def call(ov, r, rows=ROWS, pc=PC, p=P, d='d.jpg', b='b.jpg', fit=FIT, vf=None):
    CALLS.clear()
    return S.with_ext_live(ov, 'лист-1', pc, p, d, b, fit, rows, object() if vf is None else vf, rules=r)


def stops(fn):
    try:
        fn()
    except X.ExtStop as ex:
        return str(ex)
    return None


# ---- 0. умолчания репо: wide_line и windows вкл → числа нужны
FAKE_ST.clear()
res, st = call(OV_QUIET, S.RULES)
check(len(CALLS) == 1 and CALLS[0]['b'] and CALLS[0]['c'] and res.get('ext_called') and st['ext2b'] == 'ok' and st['ext2c'] == 'ok', 'умолчания (wide_line + windows вкл): числа 2б и 2в считаются, статусы отдаются', (CALLS, st))
check(CALLS[0]['labels'] == ['plan-clean.json/d', 'plan-clean.json/b', 'plan.json/d', 'plan.json/b'] and CALLS[0]['sid'] == 'лист-1', 'варианты — в порядке мерки: plan-clean d/b, plan d/b', CALLS)
check(CALLS[0]['plans'] == [PC, PC, P, P] and CALLS[0]['imgs'] == ['d.jpg', 'b.jpg', 'd.jpg', 'b.jpg'], 'в вариантах — свой план (plan-clean / plan) и своя картинка (d / b), не перепутаны', CALLS)
check(S.ExtStop is X.ExtStop, 'storozh.ExtStop — то же исключение, что ext.ExtStop (вызывающий ловит одно)')
res, st = call(dict(OV_QUIET, вход='как есть (4c не лучше)'), rules(win=True))
check(len(CALLS) == 1 and CALLS[0]['c'], 'вход «как есть (4c не лучше)» — тоже «как есть» (префикс, решение директора 27.11): числа считаются', (CALLS, st))
# ---- 1. все три выкл → ничего не считаем и не классифицируем
res, st = call(OV_HIT, rules())
check(not CALLS and res is OV_HIT and st == {}, 'все три выключателя выкл → числа не считаются, ov тот же', (CALLS, st))
res, st = call(None, rules(), rows=[])
check(not CALLS and res is None and st == {}, 'все выкл + нет наложения → тоже тихо: правило не включено, СТОП не нужен')
# ---- 2. только 2б (wide_line или pale_line): на годном листе считаем, лишь когда «Ст» звонит по базовым числам
for nm, r in (('wide_line', rules(wide=True)), ('pale_line', rules(pale=True))):
    res, st = call(OV_QUIET, r)
    check(not CALLS and res is OV_QUIET and st == {}, '%s один: «Ст» не звонит → числа не считаются (экономия, как в мерке)' % nm, CALLS)
    res, st = call(OV_HIT, r)
    check(len(CALLS) == 1 and CALLS[0]['b'] and not CALLS[0]['c'] and st['ext2c'] is None, '%s один: «Ст» звонит → считается только 2б' % nm, (CALLS, st))
# ---- 3. только 2в (windows): считаем на любом годном листе, 2б не просим
res, st = call(OV_QUIET, rules(win=True))
check(len(CALLS) == 1 and CALLS[0]['c'] and not CALLS[0]['b'] and st['ext2b'] is None, 'windows один: считается 2в на любом годном листе (текущий звонок не нужен), 2б не просим', (CALLS, st))
res, st = call(OV_QUIET, rules(wide=True, win=True))
check(len(CALLS) == 1 and CALLS[0]['b'] and CALLS[0]['c'], '2б + 2в вместе: считаем оба и при тихом «Ст» (2в нужен всем годным)', CALLS)

# ---- 4. «не применяется» + пометка, прогон идёт (настоящий ext.with_ext_numbers): наложения нет / не «легло» / вход не «как есть»
X.with_ext_numbers = REAL
for nm, ov, why in (('нет наложения (ov пуст)', None, 'нет наложения'), ('«частично»', dict(OV_HIT, overlay_status='частично'), 'не «легло»'), ('«не легло»', dict(OV_HIT, overlay_status='не легло'), 'не «легло»'),
                    ('вход не «как есть»', dict(OV_HIT, вход='вырезка'), 'вход не «как есть»'), ('вход «4c»', dict(OV_HIT, вход='4c'), 'вход не «как есть»')):
    err = stops(lambda: call(ov, S.RULES))
    res, st = (None, None) if err else call(ov, S.RULES)
    ok = err is None and st['лист_для_ext'] == 'не применяется' and st['ext2b'].startswith('не применяется') and st['ext2c'].startswith('не применяется') and why in st['причина']
    check(ok and 'ext2b' not in res and 'ext2c' not in res and res.get('ext_статус') == st, '%s → «не применяется: …», пометка ext_статус в ov, чисел нет, СТОП нет — прогон идёт' % nm, (err, st))
# ---- 5. СТОП: «легло», а входа для расчёта нет — файл пропал по ошибке
for nm, kw, frag in (('нет walls.csv (стен нет)', {'rows': []}, 'walls.csv'), ('нет fit.json', {'fit': None}, 'fit.json'), ('нет картинок и планов', {'pc': None, 'p': None}, 'картинки'), ('нет обеих картинок', {'d': None, 'b': None}, 'картинки')):
    msg = stops(lambda: call(OV_QUIET, S.RULES, **kw))
    check(msg is not None and frag in msg and 'лист-1' in msg, 'СТОП: «легло» и %s → ExtStop с причиной и именем листа' % nm, msg)
msg = stops(lambda: call(OV_QUIET, rules(win=True), rows=[]))
check(msg is not None and 'walls.csv' in msg, 'СТОП и при одном windows (2в): без стен наложения числа не считаются — не тихий пропуск', msg)
# ---- 6. СТОП: числа посчитаны с ошибкой («сбой» / «отказ») — выключатель ВКЛ, а чисел нет
X.with_ext_numbers = fake
for stt in ('сбой: ValueError: что-то', 'отказ: vetka_fit с INK_PALE'):
    FAKE_ST.clear()
    FAKE_ST['ext2c'] = stt
    msg = stops(lambda: call(OV_QUIET, S.RULES))
    check(msg is not None and stt in msg and 'ext2c' in msg and 'лист-1' in msg, 'СТОП: статус «%s» → ExtStop с причиной' % stt[:12], msg)
FAKE_ST.clear()
FAKE_ST.update({'ext2b': 'не сошлось с walls.csv', 'ext2c': 'не сошлось с walls.csv'})
res, st = call(OV_QUIET, S.RULES)
check(stops(lambda: call(OV_QUIET, S.RULES)) is None and 'ext2b' not in res and 'ext2c' not in res, '«не сошлось с walls.csv» — штатно: без СТОПа, чисел в ov нет («Ст» как раньше)')
FAKE_ST.clear()
# ---- 7. настоящий расчёт с заглушкой vetka_fit без настроек → не тихо: отказ/сбой → СТОП
X.with_ext_numbers = REAL
FIT_REAL = {'scale_px_per_unit_cm': 1.0, 'shift_px': [0, 0], 'sheet_px': [10, 10]}      # настоящему ext нужен fit с масштабом (без него — «стоп: нет масштаба», test_ext_masshtab.py); здесь проверяется отказ по настройкам vetka_fit
msg = stops(lambda: call(OV_QUIET, S.RULES, vf=types.SimpleNamespace(), fit=FIT_REAL))
check(msg is not None and ('отказ' in msg or 'сбой' in msg), 'настоящий ext + vetka_fit без CORRECT_V2/SOFT_INK → ExtStop (не тихий пропуск)', msg)
msg = stops(lambda: call(OV_QUIET, S.RULES, vf=types.SimpleNamespace()))
check(msg is not None and 'нет масштаба' in msg, 'настоящий ext + fit без масштаба (FIT = {fit: 1}) → ExtStop «нет масштаба» (раньше отказ по vetka_fit/KeyError)', msg)
# ---- 8. пометка попадает в guard.json: guard() кладёт ov['ext_статус'] в результат; без пометки вывод прежний
mark = {'ext2b': 'не применяется: нет наложения', 'ext2c': 'не применяется: нет наложения', 'лист_для_ext': 'не применяется', 'причина': 'нет наложения'}
g1 = S.guard('лист-1', 'b', 'opus', None, 'k', ov={'ext_статус': mark})
g2 = S.guard('лист-1', 'b', 'opus', None, 'k', ov={'на_линии': 0.9})
g3 = S.guard('лист-1', 'b', 'opus', None, 'k')
check(g1.get('ext_статус') == mark and 'ext_статус' not in g2 and 'ext_статус' not in g3, 'guard.json: поле ext_статус есть только если with_ext_live поставил пометку (остальным вывод прежний)', (g1, g2))
res, st = call(None, S.RULES)
check(S.guard('лист-1', 'b', 'opus', None, 'k', ov=res).get('ext_статус', {}).get('лист_для_ext') == 'не применяется', 'сквозняком: нет наложения → with_ext_live → guard() → пометка «не применяется» в guard.json')
# ---- 9. исходный ov не меняется (копия)
ov0 = dict(OV_QUIET)
X.with_ext_numbers = fake
FAKE_ST.clear()
res, st = call(ov0, S.RULES)
check(res is not ov0 and ov0 == OV_QUIET, 'исходный ov не изменён (копия)')

print('test_ext_live: ошибок %d' % len(bad))
sys.exit(1 if bad else 0)
