#!/usr/bin/env python3
"""T-20261127-ЦП · рамка подписей (rab-8): подписи в сетке 0–1000 → пиксели листа, за выключателем storozh_rules.json (labels_frame, labels_total_not_room).
Проверяет: пересчёт на известных листах (kazan-14772418: pt y=706 ↔ ≈1320 при H=1869; spb-10228580: x=353 ↔ 174 при W=493), выключатель выкл = прежние числа, отказ с причиной (не сетка / нет листа / чужое поле frame),
порог привязки «ближе 60» — долей стороны листа (равносилен прежнему в сетке), «подпись = общая площадь → не комната». Сеть, платное, живые папки — не трогает: свои копии подписей в fixtures/, картинки листов нужного размера — во временной папке.
Запуск (обеднённо): bash ~/remlab-logs/common-manager/bedno.sh <папка> ~/venvs/nc-models ~/venvs/nc-models/bin/python -I test_ramka.py   (нужны cv2, numpy, shapely)."""
import json
import os
import sys
import tempfile
import types

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for name in ('nc_eval', 'neutral_names', 'words_on_sheet', 'vetka_a_eval', 'vetka_a_cmp_bd'):      # модули чужих папок (в обеднённом окружении их нет); пересчёту подписей они не нужны
    sys.modules.setdefault(name, types.ModuleType(name))
os.environ['SB_RULES'] = HERE + '/storozh_rules.json'
os.environ['LABELS_SRC'] = 'labels5'      # как у живого запуска стенда/мерки
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from shapely.geometry import box  # noqa: E402
import ru_eval as RE  # noqa: E402
import storozh as S  # noqa: E402

bad = []


def check(ok, msg, extra=''):
    print(('OK   ' if ok else 'FAIL ') + msg + ('' if ok else ' :: ' + str(extra)[:300]))
    if not ok:
        bad.append(msg)


def near(a, b, tol=0.51):
    return abs(a - b) <= tol


tmp = tempfile.TemporaryDirectory(prefix='ramka-test-')
T = tmp.name
SIZES = {'kazan-14772418': (971, 1869), 'spb-10228580': (493, 800)}      # (W, H) = размер __d.jpg = fit.json sheet_px наложения
for sid, (w, h) in SIZES.items():
    os.makedirs('%s/input' % T, exist_ok=True)
    cv2.imwrite('%s/input/%s__d.jpg' % (T, sid), np.full((h, w, 3), 255, np.uint8))
RE.VK = HERE + '/fixtures'
RE.SHEET_PATH = lambda sid: '%s/input/%s__d.jpg' % (T, sid)
S.RULES['labels_frame'] = dict(S.RULES['labels_frame'])
S.RULES['labels_total_not_room'] = dict(S.RULES['labels_total_not_room'])
RAW = {sid: RE.parse_labels(sid, 'labels5') for sid in SIZES}

# ---- 0. выключатели по умолчанию выключены (иначе «как раньше» — неправда)
rules0 = json.load(open(HERE + '/storozh_rules.json', encoding='utf-8'))
check(rules0['labels_frame']['enabled'] is True and rules0['labels_total_not_room']['enabled'] is True, 'выключатели labels_frame и labels_total_not_room — по умолчанию ВКЛ (директор 27.11); выключение — одна строка enabled=false')
check(all(len(v) >= 3 for v in RAW.values()), 'свои копии подписей прочитаны (fixtures/vlm2/<лист>/labels5.json)', {k: len(v) for k, v in RAW.items()})

# ---- 1. сетка → пиксели на известных листах
fx = {sid: RE.parse_labels(sid, 'labels5', frame='grid1000') for sid in SIZES}
w, h = SIZES['kazan-14772418']
k706 = [i for i, (x, y, a) in enumerate(RAW['kazan-14772418']) if y == 706]
check(bool(k706) and near(fx['kazan-14772418'][k706[0]][1], 706 * 1869 / 1000.0) and near(fx['kazan-14772418'][k706[0]][1], 1320, 1.0), 'kazan-14772418: pt y=706 ↔ ≈1320 px при H=1869', fx['kazan-14772418'][:3])
k353 = [i for i, (x, y, a) in enumerate(RAW['spb-10228580']) if x == 353]
check(bool(k353) and near(fx['spb-10228580'][k353[0]][0], 353 * 493 / 1000.0) and near(fx['spb-10228580'][k353[0]][0], 174, 0.5), 'spb-10228580: pt x=353 ↔ 174 px при W=493', fx['spb-10228580'][:3])
for sid, (w, h) in SIZES.items():
    ok = len(fx[sid]) == len(RAW[sid]) and all(near(a[0], b[0] * w / 1000.0, 1e-6) and near(a[1], b[1] * h / 1000.0, 1e-6) and a[2] == b[2] for a, b in zip(fx[sid], RAW[sid]))
    check(ok, '%s: каждая подпись x·W/1000, y·H/1000, площадь не тронута (%d шт.)' % (sid, len(RAW[sid])), fx[sid][:2])

# ---- 2. выключатель выкл → прежние числа (байт в байт), без причин отказа
for sid in SIZES:
    RE.LAST_REFUSAL.clear()
    off = RE.parse_labels(sid, 'labels5')
    check(off == RAW[sid] and all(x <= 1000 for t in off for x in t[:2]) and sid not in RE.LAST_REFUSAL, '%s: без frame — подписи как есть (прежний результат), отказа нет' % sid)
    S.RULES['labels_frame']['enabled'] = False
    lab, wh, why = S.read_labels(sid)
    check(lab == RAW[sid] and wh is None and why is None, '%s: storozh.read_labels при выключателе выкл — как раньше' % sid)
    S.RULES['labels_frame']['enabled'] = True
    lab, wh, why = S.read_labels(sid)
    check(lab == fx[sid] and wh == SIZES[sid] and why is None, '%s: storozh.read_labels при выключателе вкл — пиксели и размер листа %s' % (sid, SIZES[sid]), (wh, why))
    S.RULES['labels_frame']['enabled'] = False

# ---- 3. отказ с причиной, не молча
vk = tempfile.mkdtemp(prefix='ramka-vk-', dir=T)


def put(sid, obj, img=True):
    os.makedirs('%s/vlm2/%s' % (vk, sid), exist_ok=True)
    json.dump(obj, open('%s/vlm2/%s/labels5.json' % (vk, sid), 'w', encoding='utf-8'))
    if img:
        cv2.imwrite('%s/input/%s__d.jpg' % (T, sid), np.full((800, 493, 3), 255, np.uint8))


def rooms(*pts):
    return {'rooms': [{'area_m2': 5.0 + i, 'pt': list(p)} for i, p in enumerate(pts)]}


RE.VK = vk
put('t-bigpt', rooms((100, 200), (1200, 300), (500, 500)))
RE.LAST_REFUSAL.clear()
res = RE.parse_labels('t-bigpt', 'labels5', frame='grid1000')
check(res is None and 'сетке 0–1000' in RE.LAST_REFUSAL.get('t-bigpt', ''), 'pt=1200 (> сетки) → отказ с причиной, подписей нет', (res, RE.LAST_REFUSAL))
put('t-neg', rooms((-5, 200), (100, 300), (500, 500)))
check(RE.parse_labels('t-neg', 'labels5', frame='grid1000') is None and 'сетке' in RE.LAST_REFUSAL.get('t-neg', ''), 'pt<0 → отказ с причиной')
put('t-edge', rooms((1000, 1000), (0, 0), (500, 500)))
e = RE.parse_labels('t-edge', 'labels5', frame='grid1000')
check(e is not None and near(e[0][0], 493) and near(e[0][1], 800), 'pt=1000 — край сетки, пересчитывается в край листа', e)
put('t-nosheet', rooms((100, 200), (300, 300), (500, 500)), img=False)
RE.SHEET_PATH = lambda sid: T + '/нет-такого/' + sid + '__d.jpg'
check(RE.parse_labels('t-nosheet', 'labels5', frame='grid1000') is None and 'нет размера листа' in RE.LAST_REFUSAL.get('t-nosheet', ''), 'нет картинки листа → отказ с причиной (не угадываем размер)')
RE.SHEET_PATH = lambda sid: '%s/input/%s__d.jpg' % (T, sid)
put('t-decl-px', dict(rooms((1200, 200), (300, 300), (500, 500)), frame='px'))
dp = RE.parse_labels('t-decl-px', 'labels5', frame='grid1000')
check(dp is not None and dp[0][0] == 1200.0, 'поле frame=px в самих подписях главнее выключателя: не пересчитываем (пиксели)', dp)
put('t-decl-bad', dict(rooms((100, 200), (300, 300), (500, 500)), frame='grid100'))
check(RE.parse_labels('t-decl-bad', 'labels5', frame='grid1000') is None and 'неизвестна' in RE.LAST_REFUSAL.get('t-decl-bad', ''), 'чужое значение поля frame → отказ с причиной')
put('t-decl-g', dict(rooms((100, 200), (300, 300), (500, 500)), frame='grid1000'))
check(near(RE.parse_labels('t-decl-g', 'labels5', frame='grid1000')[0][0], 49.3), 'поле frame=grid1000 — пересчитывается')
put('t-off', rooms((1200, 200), (300, 300), (500, 500)))
RE.LAST_REFUSAL.clear()
check(RE.parse_labels('t-off', 'labels5')[0][0] == 1200.0 and not RE.LAST_REFUSAL, 'выкл: pt=1200 отдаётся как есть, без отказа (прежнее поведение)')
S.RULES['labels_frame']['enabled'] = True
lab, wh, why = S.read_labels('t-bigpt')
check(lab is None and wh is None and why and 'сетке' in why, 'storozh.read_labels: причина отказа доходит до guard (рамка_отказ)', (lab, wh, why))
S.RULES['labels_frame']['enabled'] = False


# ---- 4. порог привязки «подписи ближе 60»: доля стороны листа
def scene(dx, dy_ab, sheet, k=0.02):
    """три комнаты по подписям: A и B на расстоянии (dx, dy_ab) друг от друга, C с dy<порога к обеим — годится только пара A–B. Подписи в px листа; метры = px·k."""
    pts = [(100.0, 100.0), (100.0 + dx, 100.0 + dy_ab), (400.0, 100.0 + dy_ab / 2.0)]
    rms = []
    for i, (x, y) in enumerate(pts):
        side = (4.0 + 3 * i) ** 0.5
        cx, cy = x * k, y * k
        rms.append({'area': side * side, 'geom': box(cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)})
    labs = [(x, y, rms[i]['area']) for i, (x, y) in enumerate(pts)]
    return rms, labs


W5, H5 = SIZES['spb-10228580']
thr_x = 0.06 * W5            # 29,58 px
r_bad, l_bad = scene(thr_x - 0.5, 0.06 * H5 + 20, (W5, H5))
r_ok, l_ok = scene(thr_x + 0.5, 0.06 * H5 + 20, (W5, H5))
check(S.register(r_bad, l_bad, (W5, H5)) is None, 'порог в долях листа: dx = 29,1 px < 0,06·493 → пара не годится, привязки нет')
reg = S.register(r_ok, l_ok, (W5, H5))
check(reg is not None and reg['n'] == 3 and reg['how'] == 'по площадям', 'порог в долях листа: dx = 30,1 px > 0,06·493 → привязка по площадям, 3 пары', reg)
r_y, l_y = scene(thr_x + 5, 0.06 * H5 - 0.5, (W5, H5))
check(S.register(r_y, l_y, (W5, H5)) is None, 'порог по оси Y — доля ВЫСОТЫ (0,06·800 = 48 px): dy = 47,5 → нет привязки')
r60, l60 = scene(40.0, 70.0, (W5, H5))
check(S.register(r60, l60) is None and S.register(r60, l60, (W5, H5)) is not None, 'без sheet — прежний порог 60 (подписи 40 px — нет пары); с sheet — доля листа (40 > 29,6 — пара)')
# свойство: решение «привязалось / нет» одно и то же в сетке (старый порог 60) и в пикселях (новый, доля стороны)
same = []
for dxg in (50, 59, 61, 70):
    for dyg in (59, 61, 90):
        kx, ky = 0.02 * 1.0, 0.02 * 1.0
        gp = [(100.0, 100.0), (100.0 + dxg, 100.0 + dyg), (400.0, 100.0 + dyg / 2.0)]
        rg = []
        for i, (x, y) in enumerate(gp):
            side = (4.0 + 3 * i) ** 0.5
            cx, cy = x * kx, y * ky
            rg.append({'area': side * side, 'geom': box(cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)})
        lg = [(x, y, rg[i]['area']) for i, (x, y) in enumerate(gp)]
        lpx = [(x * W5 / 1000.0, y * H5 / 1000.0, a) for (x, y, a) in lg]
        rp = []
        for i, (x, y, a) in enumerate(lpx):
            side = (4.0 + 3 * i) ** 0.5
            cx, cy = x * kx, y * ky
            rp.append({'area': side * side, 'geom': box(cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)})
        a1 = S.register(rg, lg) is None
        a2 = S.register(rp, lpx, (W5, H5)) is None
        same.append((dxg, dyg, a1, a2))
check(all(a == b for (_x, _y, a, b) in same), 'решение привязки в сетке (порог 60) и в пикселях (0,06 стороны) совпадает на 12 сочетаниях dx/dy', [t for t in same if t[2] != t[3]])
check(any(t[2] for t in same) and any(not t[2] for t in same), 'проверка не вырождена: среди сочетаний есть и «нет привязки», и «есть»', same)

# ---- 5. «подпись = общая площадь объявления → не комната»
S.RULES['labels_total_not_room']['enabled'] = True
labs = [(100, 100, 4.54), (200, 100, 3.53), (300, 300, 26.24), (400, 400, 1.09)]
got, dropped = S.drop_total_labels(labs, 26.24)
check(dropped == [26.24] and len(got) == 3 and all(l[2] != 26.24 for l in got), 'подпись 26,24 = общая 26,24 → выброшена, остальные три на месте', (got, dropped))
got, dropped = S.drop_total_labels([(1, 1, 26.0), (2, 2, 10.0), (3, 3, 8.0)], 26.24)
check(dropped == [26.0], 'допуск: 26,0 при общей 26,24 (в пределах max(0,15; 3 %)) — тоже общая')
got, dropped = S.drop_total_labels([(1, 1, 24.0), (2, 2, 10.0), (3, 3, 8.0)], 26.24)
check(dropped == [] and len(got) == 3, 'допуск: 24,0 при общей 26,24 — комната, не трогаем')
got, dropped = S.drop_total_labels([(1, 1, 26.24), (2, 2, 10.0)], 26.24)
check(dropped == [] and len(got) == 2, 'после выбрасывания осталось бы меньше 2 подписей — не трогаем (студия)')
check(S.drop_total_labels(labs, None) == (labs, []), 'общей площади в объявлении нет — не трогаем')
check(S.drop_total_labels(None, 26.24) == (None, []), 'подписей нет — None как был')
S.RULES['labels_total_not_room']['enabled'] = False
check(S.drop_total_labels(labs, 26.24) == (labs, []), 'выключатель выкл — подписи как есть')

# ---- 6. spb-10228580 сквозняком: «26,24» — общая площадь студии, не комната (комната 17,08); лист с рамкой → привязка по площадям; выключатель выкл → как было
RE.VK = HERE + '/fixtures'
RE.SHEET_PATH = lambda sid: '%s/input/%s__d.jpg' % (T, sid)
W6, H6 = SIZES['spb-10228580']
K6 = 0.02                                                                         # метров на пиксель листа (синтетика: подписи легли в центры комнат ответа)
AREAS6 = [4.54, 3.53, 17.08, 1.09]                                                # ответ агента: ванная, прихожая, комната 17,08 (на листе напечатано 26,24 — общая), балкон
S.RULES['labels_frame']['enabled'] = True
S.RULES['labels_total_not_room']['enabled'] = True
lab6, wh6, why6 = S.read_labels('spb-10228580')
check(wh6 == (W6, H6) and why6 is None and len(lab6) == 4 and [l[2] for l in lab6] == [4.54, 3.53, 26.24, 1.09], 'spb-10228580: рамка вкл — 4 подписи (4,54 / 3,53 / 26,24 / 1,09) в пикселях листа', (wh6, why6, lab6))
rooms6 = []
for (x, y, a6), area in zip(lab6, AREAS6):
    side = area ** 0.5
    cx, cy = x * K6, y * K6
    rooms6.append({'area': area, 'geom': box(cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)})
reg6 = S.register(rooms6, lab6, wh6)
check(reg6 is not None and reg6['how'] == 'по площадям' and reg6['n'] == 3, 'spb-10228580: с рамкой подписи привязались к плану по площадям (3 пары: 4,54 / 3,53 / 1,09; 26,24 ≠ комнате 17,08 — в пару не идёт)', reg6)
check(all(abs(r['area'] - lab6[2][2]) > max(0.15, 0.03 * lab6[2][2]) for r in rooms6), 'spb-10228580: подпись 26,24 не равна площади ни одной комнаты ответа (комната гостиной — 17,08)')
kept6, dropped6 = S.drop_total_labels(lab6, 26.24)
check(dropped6 == [26.24] and [l[2] for l in kept6] == [4.54, 3.53, 1.09], 'spb-10228580: «общая 26,24» выброшена из подписей, три комнаты остались', (kept6, dropped6))
S.RULES['labels_total_not_room']['enabled'] = False
check(S.drop_total_labels(lab6, 26.24) == (lab6, []), 'spb-10228580: правило «общая — не комната» выкл → 26,24 остаётся подписью, как было')
S.RULES['labels_total_not_room']['enabled'] = True
S.RULES['labels_frame']['enabled'] = False
lab6o, wh6o, why6o = S.read_labels('spb-10228580')
check(lab6o == RAW['spb-10228580'] and wh6o is None and why6o is None, 'spb-10228580: рамка выкл — подписи как есть, в сетке 0–1000 (как было)')
rooms6o = [dict(r) for r in rooms6]
check(S.register(rooms6o, lab6o) is None, 'spb-10228580: рамка выкл — те же комнаты и подписи в сетке НЕ привязались по площадям (было: «по чернилам» / «не привязать»)')
S.RULES['labels_frame']['enabled'] = True

tmp.cleanup()
print('test_ramka: ошибок %d' % len(bad))
sys.exit(1 if bad else 0)
