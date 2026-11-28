#!/usr/bin/env python3
"""T-171 (директор 28.11): ext.py на листе БЕЗ масштаба (kazan-14066977: наложение «не проверено — чернил не найдено», fit.json без scale_px_per_unit_cm) обязан давать «стоп: нет масштаба», а не KeyError/«сбой: KeyError».
Правило общее, на все листы (fit без годного масштаба: нет ключа / не число / ≤ 0 / NaN). Герметично, как test_ext.py: синтетический лист из fixtures/ext/a.json, заглушка vetka_fit, сеть и живые папки не трогает.
Старый код (до правки): ext2b/ext2c дают «сбой: KeyError: 'scale_px_per_unit_cm'», with_ext_numbers/with_ext_live — ExtStop с текстом KeyError без слов «нет масштаба» → проверки Н3–Н7 красные (−контроль: прогон на ext.py из origin/main).
Запуск: python -I test_ext_masshtab.py (нужны numpy, cv2, shapely; нет numpy/cv2 — «SKIP», код 0)."""
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
for _name in ('nc_eval', 'neutral_names', 'words_on_sheet', 'vetka_a_eval', 'vetka_a_cmp_bd'):      # модули чужих папок: в CI их нет, этим проверкам они не нужны
    sys.modules.setdefault(_name, types.ModuleType(_name))
os.environ['SB_RULES'] = HERE + '/storozh_rules.json'
import ext as X  # noqa: E402
import storozh as S  # noqa: E402

bad = []


def check(ok, msg, extra=''):
    print(('OK   ' if ok else 'FAIL ') + msg + ('' if ok else ' :: ' + str(extra)[:300]))
    if not ok:
        bad.append(msg)


def make_vf():
    """заглушка vetka_fit (как в test_ext.py): чернила = тёмное, единицы плана — см; настройки как у мерки (V2, SOFT_INK)"""
    vf = types.SimpleNamespace(V2=True, SOFT_INK=True, INK_PALE=False, INK_THICK=False, INK_LAYERS='', TOL_MIN=3.0)
    vf.load_gray = lambda p: (_ for _ in ()).throw(AssertionError('картинки — массивами, файлы не читаем'))
    vf.ink_mask = lambda g: g < 128
    vf.bg_kernel = lambda g: max(15, int(0.02 * max(g.shape)) | 1)
    vf.segs_of = lambda plan: [(w['from'][0], w['from'][1], w['to'][0], w['to'][1], float(w['thickness']), w.get('id', '')) for lv in plan['levels'] for w in lv.get('walls', [])]

    def rot_about(Q, deg, c):
        a = math.radians(deg)
        ca, sa = math.cos(a), math.sin(a)
        d = Q - np.array(c)
        return np.stack([c[0] + d[:, 0] * ca - d[:, 1] * sa, c[1] + d[:, 0] * sa + d[:, 1] * ca], 1)
    vf.rot_about = rot_about
    return vf


FX = json.load(open(os.path.join(HERE, 'fixtures', 'ext', 'a.json'), encoding='utf-8'))
W, H = FX['sheet']
G = np.full((H, W), 255, np.uint8)
for x0, y0, x1, y1, val, th in FX['draw']:
    h = th // 2
    G[min(y0, y1) - h:max(y0, y1) + h + 1, min(x0, x1) - h:max(x0, x1) + h + 1] = val
NS = getattr(X, 'no_scale', lambda fit: None)      # на старом ext.py функции нет — проверки краснеют по поведению, а не падают на AttributeError (−контроль)
VF = make_vf()
CANDS = X.candidates({'plan-clean.json': FX['plan'], 'plan.json': None}, {'d': G, 'b': None})
ROWS = FX['rows']
FIT_OK = FX['fit']
FIT_KAZAN = {'found': 'не проверено', 'причина': 'чернил не найдено', 'sheet_px': [W, H], 'самый_тёмный_0.1%': 139}      # форма fit.json kazan-14066977 (ekz-20261128/…/opus/overlay/fit.json)
OV = {'overlay_status': 'легло', 'вход': 'как есть', 'на_линии': 0.9, 'лишнее_м': 0.0}

# ── Н1. no_scale: чистая проверка ────────────────────────────────────────────
check(NS(FIT_OK) is None, 'Н1 годный fit (масштаб 1,0) → None')
check('нет масштаба' in (NS(FIT_KAZAN) or '') and 'чернил не найдено' in NS(FIT_KAZAN), 'Н1б fit как у kazan-14066977 → «нет масштаба — …» с причиной из fit.json', NS(FIT_KAZAN))
for nm, bad_scale in (('ноль', 0), ('минус', -2.0), ('строка', 'abc'), ('None', None), ('True', True), ('NaN', float('nan')), ('inf', float('inf'))):
    check('нет масштаба' in (NS(dict(FIT_OK, scale_px_per_unit_cm=bad_scale)) or ''), 'Н1в негодный масштаб (%s) → «нет масштаба»' % nm)
check(NS(None) is None and NS({}) is None, 'Н1г fit нет / пустой — это «нет fit.json» (другая причина), не «нет масштаба»')
fit_nokey = {k: v for k, v in FIT_OK.items() if k != 'scale_px_per_unit_cm'}
check('нет масштаба' in (NS(fit_nokey) or ''), 'Н1д fit без ключа масштаба (остальное на месте) → «нет масштаба»')

# ── Н2. −контроль: годный fit по-прежнему считается ──────────────────────────
e2 = X.ext2b('fx', CANDS, FIT_OK, ROWS, VF)
e3 = X.ext2c('fx', CANDS, FIT_OK, ROWS, VF)
check(e2['статус'] == 'ok' and e3['статус'] == 'ok', 'Н2 −КОНТРОЛЬ: годный fit → ext2b/ext2c «ok» (правка не ломает расчёт)', (e2['статус'], e3['статус']))

# ── Н3–Н7. fit без масштаба ──────────────────────────────────────────────────
n2 = X.ext2b('kazan-14066977', CANDS, FIT_KAZAN, ROWS, VF)
n3 = X.ext2c('kazan-14066977', CANDS, FIT_KAZAN, ROWS, VF)
check(n2['статус'].startswith('стоп: нет масштаба') and n3['статус'].startswith('стоп: нет масштаба'), 'Н3 ext2b/ext2c без масштаба: статус «стоп: нет масштаба …», не «сбой: KeyError»', (n2['статус'], n3['статус']))
check('KeyError' not in n2['статус'] and 'KeyError' not in n3['статус'], 'Н3б в статусе нет KeyError')
kind, why = X.coverage(OV, ROWS, FIT_KAZAN, CANDS)
check(kind == X.STOP and 'нет масштаба' in why, 'Н4 coverage: «легло» + fit без масштаба → СТОП «нет масштаба»', (kind, why))
try:
    X.with_ext_numbers(OV, 'kazan-14066977', CANDS, FIT_KAZAN, ROWS, VF)
    check(False, 'Н5 with_ext_numbers (stop=True) → ExtStop «нет масштаба»', 'исключения нет')
except X.ExtStop as ex:
    check('нет масштаба' in str(ex) and 'KeyError' not in str(ex) and 'kazan-14066977' in str(ex), 'Н5 with_ext_numbers (stop=True) → ExtStop «нет масштаба» с id листа, без KeyError', str(ex))
except Exception as ex:      # noqa: BLE001
    check(False, 'Н5 with_ext_numbers: падение %s вместо ExtStop' % type(ex).__name__, ex)
o, st = X.with_ext_numbers(OV, 'kazan-14066977', CANDS, FIT_KAZAN, ROWS, VF, stop=False)
check(st['лист_для_ext'] == X.STOP and str(st['ext2b']).startswith('СТОП: нет масштаба') and 'ext2b' not in o and 'ext2c' not in o, 'Н6 with_ext_numbers (stop=False): пометка «СТОП: нет масштаба», чисел в ov нет', st)
RULES = copy.deepcopy(S.RULES)
RULES['walls_fail']['wide_line']['enabled'] = True
RULES['walls_fail']['windows']['enabled'] = True
try:
    S.with_ext_live(OV, 'kazan-14066977', FX['plan'], FX['plan'], G, None, FIT_KAZAN, ROWS, VF, rules=RULES)
    check(False, 'Н7 storozh.with_ext_live → ExtStop «нет масштаба»', 'исключения нет')
except S.ExtStop as ex:
    check('нет масштаба' in str(ex) and 'KeyError' not in str(ex), 'Н7 storozh.with_ext_live (сторож сквозняком) → ExtStop «нет масштаба», не KeyError', str(ex))
except Exception as ex:      # noqa: BLE001
    check(False, 'Н7 with_ext_live: падение %s вместо ExtStop' % type(ex).__name__, ex)
# статус «стоп…» из ext2b (прямой вызов мимо coverage) — тоже СТОП у сторожа
_real = X.with_ext_numbers
X.with_ext_numbers = lambda ov, sid, cands, fit, rows, vf, want_2b=True, want_2c=True, stop=True: (dict(ov), {'ext2b': 'стоп: нет масштаба — тест', 'ext2c': None})
try:
    S.with_ext_live(OV, 'x', FX['plan'], FX['plan'], G, None, FIT_OK, ROWS, VF, rules=RULES)
    check(False, 'Н8 with_ext_live: статус «стоп: …» от ext → ExtStop', 'исключения нет')
except S.ExtStop as ex:
    check('нет масштаба' in str(ex), 'Н8 with_ext_live: статус «стоп: …» от ext2b → ExtStop (не молчаливое «Ст как раньше»)', str(ex))
finally:
    X.with_ext_numbers = _real
# ── П1–П6. НАСТОЯЩАЯ пара kazan-14066977 (ekz-20261128/…/opus): overlay.json = легло, вход «4c»; fit.json без масштаба. Вход «не как есть» → SKIP РАНЬШЕ проверки масштаба ──
OV_4C = {'overlay_status': 'легло', 'легло_по_зоне': False, 'на_линии': 0.817, 'покрыто': 0.546, 'доля_точек_3px': 0.756, 'лишнее_м': 0.0, 'пропущено_м': 0.0, 'стена_без_комнаты': [], 'вход': '4c'}


def real_pair_ok(mod):
    """kazan-14066977 через модуль mod (настоящий ext или его копия с порчей): coverage → SKIP «вход не «как есть»», with_ext_numbers (stop=True) НЕ поднимает ExtStop, чисел нет, пометка «не применяется»"""
    try:
        kind, why = mod.coverage(OV_4C, ROWS, FIT_KAZAN, CANDS)
        o, st = mod.with_ext_numbers(OV_4C, 'kazan-14066977', CANDS, FIT_KAZAN, ROWS, VF)
    except Exception as ex:      # noqa: BLE001  (в т.ч. ExtStop)
        return False, '%s: %s' % (type(ex).__name__, str(ex)[:120])
    ok = (kind == mod.SKIP and 'вход не «как есть»' in why and 'нет масштаба' not in why and st['лист_для_ext'] == mod.SKIP
          and str(st['ext2b']).startswith('не применяется') and str(st['ext2c']).startswith('не применяется') and 'ext2b' not in o and 'ext2c' not in o)
    return ok, (kind, why, st)


ok, info = real_pair_ok(X)
check(ok, 'П1 настоящая пара kazan-14066977 (легло, вход 4c, fit без масштаба) → SKIP «вход не «как есть»», ExtStop нет, числа не считаются', info)
check(X.coverage(OV_4C, ROWS, FIT_KAZAN, CANDS)[0] == X.SKIP and X.coverage(dict(OV_4C, вход='как есть'), ROWS, FIT_KAZAN, CANDS)[0] == X.STOP, 'П2 тот же fit без масштаба: вход 4c → SKIP, вход «как есть» → СТОП «нет масштаба» (порядок: сперва вход, потом масштаб)')
check(X.coverage(dict(OV_4C, вход='как есть (4c не лучше)'), ROWS, FIT_KAZAN, CANDS)[0] == X.STOP, 'П2б вход «как есть (4c не лучше)» — тоже как есть → доходит до проверки масштаба (СТОП)')
check(X.coverage(dict(OV_4C, overlay_status='не легло'), ROWS, FIT_KAZAN, CANDS)[0] == X.SKIP, 'П2в наложение не «легло» + fit без масштаба → SKIP (статус раньше масштаба)')
check(X.coverage(None, ROWS, FIT_KAZAN, CANDS)[0] == X.SKIP, 'П2г нет overlay.json + fit без масштаба → SKIP')
# −контроль: копия ext.py с порчей «проверка входа убрана» (масштаб проверяется раньше входа) — на настоящей паре тест обязан краснеть
_src = open(X.__file__, encoding='utf-8').read()
_cut = "    if not as_is(ov):\n        return SKIP, 'вход не «как есть» (вход: %s)' % ov.get('вход')\n"
check(_src.count(_cut) == 1, 'П3 набор −контроля: кусок «проверка входа» в ext.py ровно один', _src.count(_cut))
for nm, _new in (('проверка входа убрана (масштаб раньше входа)', _src.replace(_cut, '')), ('проверка входа после масштаба', _src.replace(_cut, '').replace("    if lost:\n        return STOP, '; '.join(lost)\n    return APPLIES, ''", "    if lost:\n        return STOP, '; '.join(lost)\n" + _cut + "    return APPLIES, ''"))):
    _m = types.ModuleType('ext_porcha')
    exec(compile(_new, 'ext_porcha.py', 'exec'), _m.__dict__)      # noqa: S102
    _ok, _info = real_pair_ok(_m)
    check(not _ok, 'П4 −КОНТРОЛЬ: порча «%s» → проверка настоящей пары краснеет (тест её ловит)' % nm, _info)
_m = types.ModuleType('ext_cop')
exec(compile(_src, 'ext_cop.py', 'exec'), _m.__dict__)      # noqa: S102
check(real_pair_ok(_m)[0], 'П5 контроль без порчи: копия ext.py проходит ту же проверку (порча — единственная разница)')
print('ИТОГ: красных %d' % len(bad))
sys.exit(1 if bad else 0)
