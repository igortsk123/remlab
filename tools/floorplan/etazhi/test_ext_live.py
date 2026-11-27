#!/usr/bin/env python3
"""T-171/paket-ext · storozh.with_ext_live (строка вызова из OTCHET-ext.md): числа 2б/2в считаются на листе ТОЛЬКО когда нужны — по выключателям walls_fail (wide_line / pale_line / windows),
лист «легло» + вход «как есть» + есть стены; для одного 2б — ещё и когда «Ст» звонит по базовым числам. Сами числа — ext.py (test_ext.py). Герметично: ext.with_ext_numbers подменяется записью вызова.
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


def fake(ov, sid, cands, fit, rows, vf, want_2b=True, want_2c=True):
    CALLS.append({'sid': sid, 'labels': [c[0] for c in cands], 'plans': [c[1] for c in cands], 'imgs': [c[2] for c in cands], 'b': want_2b, 'c': want_2c})
    o = dict(ov)
    o['ext_called'] = True
    return o, {'ext2b': 'ok' if want_2b else None, 'ext2c': 'ok' if want_2c else None}


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
PC, P = {'rooms': 'pc'}, {'rooms': 'p'}


def call(ov, r, rows=ROWS, pc=PC, p=P, d='d.jpg', b='b.jpg'):
    CALLS.clear()
    return S.with_ext_live(ov, 'лист-1', pc, p, d, b, {'fit': 1}, rows, object(), rules=r)


# ---- 0. умолчания репо: wide_line и windows вкл → числа нужны
res, st = call(OV_QUIET, S.RULES)
check(len(CALLS) == 1 and CALLS[0]['b'] and CALLS[0]['c'] and res.get('ext_called') and st == {'ext2b': 'ok', 'ext2c': 'ok'}, 'умолчания (wide_line + windows вкл): числа 2б и 2в считаются, статусы отдаются', (CALLS, st))
check(CALLS[0]['labels'] == ['plan-clean.json/d', 'plan-clean.json/b', 'plan.json/d', 'plan.json/b'] and CALLS[0]['sid'] == 'лист-1', 'варианты — в порядке мерки: plan-clean d/b, plan d/b', CALLS)
check(CALLS[0]['plans'] == [PC, PC, P, P] and CALLS[0]['imgs'] == ['d.jpg', 'b.jpg', 'd.jpg', 'b.jpg'], 'в вариантах — свой план (plan-clean / plan) и своя картинка (d / b), не перепутаны', CALLS)
# ---- 1. все три выкл → ничего не считаем
res, st = call(OV_HIT, rules())
check(not CALLS and res is OV_HIT and st == {}, 'все три выключателя выкл → числа не считаются, ov тот же', (CALLS, st))
# ---- 2. только 2б (wide_line или pale_line): считаем, лишь когда «Ст» звонит по базовым числам
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
# ---- 4. лист не годится: не «легло» / вход не «как есть» / нет стен / нет ov
for nm, ov, rows in (('«частично»', dict(OV_HIT, overlay_status='частично'), ROWS), ('вход не «как есть»', dict(OV_HIT, вход='вырезка'), ROWS), ('нет стен', OV_HIT, []), ('нет ov', None, ROWS)):
    res, st = call(ov, S.RULES, rows=rows)
    check(not CALLS and res is ov and st == {}, 'лист не годится (%s) → числа не считаются' % nm, CALLS)
# ---- 5. варианты: нет plan-clean / нет картинки d — пропускаются, порядок сохранён
call(OV_QUIET, S.RULES, pc=None)
check(CALLS[0]['labels'] == ['plan.json/d', 'plan.json/b'], 'нет plan-clean.json → только варианты plan.json', CALLS)
call(OV_QUIET, S.RULES, d=None)
check(CALLS[0]['labels'] == ['plan-clean.json/b', 'plan.json/b'], 'нет картинки d → только варианты b', CALLS)
call(OV_QUIET, S.RULES, pc=None, p=None)
check(CALLS[0]['labels'] == [], 'нет планов → пустой список вариантов (ext вернёт статус «нет входа», не молча)', CALLS)
# ---- 6. настоящий with_ext_numbers: нет входа → статус, ov без полей ext2b/ext2c (звонок «Ст» как раньше)
X.with_ext_numbers = REAL
res, st = S.with_ext_live(OV_QUIET, 'лист-1', None, None, None, None, {}, ROWS, object(), rules=S.RULES)
check('ext2b' not in res and 'ext2c' not in res and st.get('ext2b') not in (None, 'ok') and st.get('ext2c') not in (None, 'ok'), 'без планов и картинок: статус не «ok», полей ext2b/ext2c в ov нет', (st, sorted(res)))
check(res is not OV_QUIET and OV_QUIET == {'overlay_status': 'легло', 'вход': 'как есть', 'на_линии': 0.9, 'лишнее_м': 0.0}, 'исходный ov не изменён (копия)')

print('test_ext_live: ошибок %d' % len(bad))
sys.exit(1 if bad else 0)
