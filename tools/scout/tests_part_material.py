#!/usr/bin/env python3
"""Тесты «материал части» (T-20261124-63, Ш4а): part_material.py + part_material_stage.py (CI, без Chromium и без GLB).

  python3 tools/scout/tests_part_material.py

Проверяется: ΔE2000 (контрольная пара Sharma), главный кластер, роли → группы, тон группы (тень-меньшинство отброшена), «тот же материал» (цветные по углу оттенка, нейтральные по светлоте),
лесенка донора (зад = бок, бок = фасад при том же материале, рисунок фасада остаётся), сборка текстуры, подбор альбедо по кадру (подставной рендер), растр меток по развёртке,
ВЫКЛ по умолчанию и «выключено ничего не пишет», ID товаров в коде нет.
"""
import json
import os
import re
import subprocess
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_part_material')

import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import part_material as PM  # noqa: E402

FAILS: list = []


def check(cond: bool, name: str) -> None:
    print(('  ✓ ' if cond else '  ✗ ') + name, flush=True)
    if not cond:
        FAILS.append(name)


def rgb_img(h, w, rgb):
    return np.tile(np.array(rgb, np.uint8), (h, w, 1))


R = PM.load_rules()
RU = dict(R, unify_max_dl=0)   # лесенка и unify — без ворот светлоты (они отдельно, _unify_dl)

# ── выключено по умолчанию, числа и ID
check(R['enabled'] is False, 'правило выключено по умолчанию (enabled=false)')
src = ''.join(open(os.path.join(HERE, f), encoding='utf-8').read() for f in ('part_material.py', 'part_material_stage.py'))
check(not re.search(r'\d{5,}_\d{8,}', src), 'ID товаров (длинные числа) в коде нет')

# ── ΔE2000: контрольные пары Sharma 2005
a = np.array([[50.0, 2.6772, -79.7751]]); b = np.array([[50.0, 0.0, -82.7485]])
check(abs(float(PM.de2000(a, b)[0]) - 2.0425) < 1e-3, 'ΔE2000: пара №1 Sharma = 2.0425')
a = np.array([[50.0, 2.5, 0.0]]); b = np.array([[73.0, 25.0, -18.0]])
check(abs(float(PM.de2000(a, b)[0]) - 27.1492) < 1e-3, 'ΔE2000: пара №17 Sharma = 27.1492')

# ── главный кластер
px = np.concatenate([np.tile([200, 180, 150], (700, 1)), np.tile([90, 60, 50], (300, 1))]).astype(np.uint8)
mm, share = PM.main_cluster(px, 3, 40000)
check(abs(share - 0.7) < 0.02 and mm[:700].all() and not mm[700:].any(), 'главный кластер: 70 % светлых — главный, тень-меньшинство отброшена')

# ── роли → группы
role = np.array(['top', 'top', 'legs', 'frame', 'side', 'handles', 'unknown', 'top'])
conf = np.array([0.7, 0.7, 0.6, 0.6, 0.65, 0.7, 0.0, 0.3])
fl, names = PM.role_groups(role, conf, R)
check(names == ['верх', 'ножки', 'бок'], 'роли → группы: верх, ножки(legs+frame), бок; имена без пустых')
check(list(fl) == [0, 0, 1, 1, 2, 3, 3, 3], 'роль вне таблицы, unknown и conf ниже min_conf → «не красим» (метка = число групп)')

# ── тон группы: тень-меньшинство не тянет тон
H = 80
prgb = np.zeros((H, H, 3), np.uint8)
prgb[:, :40] = [200, 180, 150]
prgb[:20, :40] = [90, 60, 50]                    # тень 25 % левой половины
prgb[:, 40:] = [60, 100, 60]
pp = np.full((H, H), -1, np.int16); pp[:, :40] = 0; pp[:, 40:] = 1
cosf = np.full((H, H), 0.9, np.float32)
R2 = json.loads(json.dumps(R)); R2['pixels']['min_px'] = 300; R2['pixels']['erode_px'] = [2]
tn = PM.group_tones(prgb, pp, ['верх', 'ножки'], cosf, R2)
lab_top = tn['верх']['lab']
check(tn['верх']['own'] and abs(lab_top[0] - PM.lab_of(np.array([200, 180, 150]))[0]) < 2, 'тон группы — главный кластер, а не среднее с тенью')
check(tn['верх']['share'] is not None and 0.7 < tn['верх']['share'] < 0.8, 'доля главного кластера идёт в отчёт (≈0,75)')
cosf2 = np.full((H, H), 0.1, np.float32)
tn2 = PM.group_tones(prgb, pp, ['верх', 'ножки'], cosf2, R2)
check(tn2['верх']['own'] and not tn2['ножки']['own'], 'скользящий угол: верх допускается (cos ≥ 0,03), ножки нет (cos ≥ 0,2) — тон со своей плоскости')

# ── тот же материал
sm = R['same_material']
okn, _ = PM.same_material(np.array([80.0, 0.5, 1.0]), np.array([66.0, 0.2, 0.5]), sm)
check(okn, 'нейтральные: бок темнее фасада на 14 L (студийная тень) — тот же материал')
okn2, _ = PM.same_material(np.array([80.0, 0.5, 1.0]), np.array([30.0, 0.2, 0.5]), sm)
check(not okn2, 'нейтральные: бок темнее на 50 L — другой материал')
oka, _ = PM.same_material(PM.lab_of(np.array([200, 120, 90])), PM.lab_of(np.array([140, 84, 63])), sm)
check(oka, 'цветные: тот же оттенок, темнее (тень) — тот же материал')
okb, _ = PM.same_material(PM.lab_of(np.array([200, 120, 90])), PM.lab_of(np.array([90, 120, 200])), sm)
check(not okb, 'цветные: оттенки разные — другой материал')

# ── лесенка
def tone(L, a_, b_, own=True, ab_minor=0.0):
    lab = np.array([L, a_, b_], float)
    return {'own': own, 'n_all': 1000 if own else 0, 'share': 0.9, 'ab_minor': ab_minor, 'lab': lab, 'lin': PM.srgb2lin(np.array([128, 128, 128]))} if own else {'own': False, 'n_all': 0, 'share': None, 'ab_minor': None}

t = {'фасад': tone(90, 0, 1), 'бок': tone(76, 0, 1), 'верх': tone(0, 0, 0, own=False), 'зад': tone(0, 0, 0, own=False)}
keep, bor, same = PM.pick_sources(t, RU)
check(bor.get('зад') in ('бок', 'фасад'), 'зад берёт тон бока (через цепочку — итоговый тон бока)')
check(bor.get('бок') == 'фасад' and same['бок']['same'], 'бок того же материала, что фасад → тон фасада (студийная тень не красится в серое)')
check(bor.get('верх') == 'бок' or bor.get('верх') == 'фасад', 'верх без пикселей → донор по лесенке (бок), а не родной цвет')
t = {'фасад': tone(70, 20, 25, ab_minor=0.3), 'бок': tone(0, 0, 0, own=False), 'зад': tone(0, 0, 0, own=False), 'верх': tone(0, 0, 0, own=False)}
keep, bor, same = PM.pick_sources(t, RU)
check('фасад' in keep, 'фасад с рисунком (другой оттенок на >2 %) — фото 06 остаётся')
check(bor.get('бок') != 'фасад' and bor.get('зад') is None, 'донор — не группа с рисунком: бок/зад не берут тон узорного фасада (нечем красить → «не уверен»)')
t = {'фасад': tone(70, 20, 25), 'ножки': tone(0, 0, 0, own=False)}
keep, bor, same = PM.pick_sources(t, RU)
check(bor.get('ножки', 'x') is None, 'ножки без пикселей: донора нет (ножки — своя группа) → не красим, «не уверен»')

t = {'фасад': tone(90, 0, 1), 'бок': tone(76, 0, 1), 'зад': tone(0, 0, 0, own=False)}
keep, bor, same = PM.pick_sources(t, RU)
check(bor.get('зад') == 'фасад', 'цепочка донора: зад ← бок ← фасад → итоговый тон фасада (а не тон теневого бока)')
t = {'фасад': tone(90, 0, 1), 'бок': tone(0, 0, 0, own=False), 'зад': tone(40, 0, 0, own=False), 'верх': tone(30, 40, 40)}
keep, bor, same = PM.pick_sources(t, RU)
t2 = {'фасад': tone(90, 0, 1), 'бок': tone(30, 40, 40), 'зад': tone(0, 0, 0, own=False)}
keep, bor, same = PM.pick_sources(t2, RU)
check(bor.get('зад') is None and 'gate:зад' in same, 'ворота: донор (бок) далеко от лица (ΔE2000 > порога) и не тот же материал → зад не красим, «не уверен»')

tw = {'фасад': tone(90, 0, 1), 'корпус': tone(60, 3, 3)}
tw['корпус']['n_all'] = 10
Rw = json.loads(json.dumps(R)); Rw['pixels']['weak_share'] = 0.1
keep, bor, same = PM.pick_sources(tw, Rw, {'фасад': 0.3, 'корпус': 0.3})
k2, b2, _s2 = PM.pick_sources({'фасад': tone(90, 0, 1), 'корпус': dict(tone(60, 3, 3), n_all=10)}, R, {'фасад': 0.3, 'корпус': 0.3})
check(b2.get('корпус') is None, 'слабый тон: по умолчанию ВЫКЛ (weak_share=0) — свой тон остаётся')
check(bor.get('корпус') == 'фасад' and tw['корпус'].get('weak'), 'слабый свой тон (мизер пикселей против главной группы) → донор по лесенке')

tu = {'верх': tone(76, 0, 2), 'бок': tone(79, 1, 2), 'корпус': tone(64, 3, 3), 'фасад': tone(73, 3, 3, ab_minor=0.3)}
for g_, n_ in (('верх', 200000), ('бок', 13000), ('корпус', 6000)):
    tu[g_]['n_all'] = n_
keep, bor, same = PM.pick_sources(tu, RU, {'верх': 1.0, 'бок': 1.0, 'корпус': 1.0, 'фасад': 1.0})
check('фасад' in keep and bor.get('верх') == 'бок' and bor.get('корпус') == 'бок', 'один материал — один тон: верх и корпус берут тон опорной части (бок; верх опорной не бывает — виден скользяще), фасад с рисунком — фото 06')
mids = PM.material_ids(['верх', 'бок', 'корпус', 'фасад'], tu, bor, R)
check(len(set(mids)) == 1 and mids[0] >= 0, 'карта материалов: части одного материала — один номер')
tz = {'верх': tone(76, 0, 2), 'корпус': tone(30, 40, 40)}
tz['верх']['n_all'] = 9000
tz['корпус']['n_all'] = 9000
k2, b2, s2 = PM.pick_sources(tz, R, {'верх': 1.0, 'корпус': 1.0})
mz = PM.material_ids(['верх', 'корпус'], tz, b2, R)
check(not s2['корпус' if 'корпус' in s2 else 'верх']['same'] and mz[0] != mz[1], 'разные материалы (оттенок разный): тона не сливаются, номера материалов разные — граница законный край')

# ── сборка текстуры + подбор по кадру (подставной рендер с потерей света 0,8)
T = 16
texmap = np.zeros((T, T), np.int16); texmap[:, 8:] = 1
ctl = rgb_img(T, T, (128, 128, 128))
names2 = ['верх', 'ножки']
tones2 = {'верх': {'own': True, 'lin': np.array([0.5, 0.4, 0.3])}, 'ножки': {'own': True, 'lin': np.array([0.2, 0.3, 0.1])}}
alb0 = {'верх': tones2['верх']['lin'], 'ножки': tones2['ножки']['lin']}
tex, painted = PM.compose(ctl, texmap, names2, alb0, {}, set())
check(painted.all() and tuple(tex[0, 0]) != (128, 128, 128) and tuple(tex[0, 0]) != tuple(tex[0, 15]), 'compose: каждая группа — свой ровный цвет, всё покрашено')
tex, painted = PM.compose(ctl, texmap, names2, alb0, {}, {'ножки'})
check((tex[:, 8:] == 128).all() and not painted[:, 8:].any(), 'compose: группа с рисунком остаётся как в 06')
lm = np.zeros((T, T), np.int16); lm[:, 8:] = 1


def render(tex_):                                  # «свет сайта» гасит линейный цвет до 0,8
    return np.clip(PM.lin2srgb(PM.srgb2lin(tex_) * 0.8) + 0.5, 0, 255).astype(np.uint8)


alb, hist = PM.fit_albedo(names2, tones2, {}, set(), texmap, ctl, render, lm, R)
fin, _p = PM.compose(ctl, texmap, names2, alb, {}, set())
fr = render(fin)
want = np.clip(PM.lin2srgb(tones2['верх']['lin']) + 0.5, 0, 255)
check(np.abs(fr[0, 0].astype(float) - want).max() <= 1.5 and len(hist) == R['fit']['iters'], 'подбор: кадр под светом совпал с тоном фото (потеря света 0,8 скомпенсирована)')

# ── растр меток по развёртке
UV = np.array([[0.1, 0.1], [0.4, 0.1], [0.1, 0.4], [0.6, 0.6], [0.9, 0.6], [0.6, 0.9]])
F = np.array([[0, 1, 2], [3, 4, 5]])
m = PM.uv_label_map(UV, F, np.array([0, 1], np.int16), 64)
check(m[int((1 - 0.15) * 64), int(0.15 * 64)] == 0 and m[int((1 - 0.65) * 64), int(0.65 * 64)] == 1 and (m >= 0).all(), 'растр меток: строка = (1 − uv_y)·T, пропуски заполнены ближайшей меткой')

# ── стадия: выключено — ничего не пишет
import tempfile  # noqa: E402
tmp = tempfile.mkdtemp(prefix='ptm_')
before = sorted(os.listdir(tmp))
r = subprocess.run([sys.executable, os.path.join(HERE, 'part_material_stage.py'), '--run', tmp, '--sku', 'x', '--glb', 'g.glb', '--photo', 'p.png', '--pose-run', tmp], capture_output=True, text=True, timeout=60)
check(r.returncode == 0 and 'выключено' in r.stdout and sorted(os.listdir(tmp)) == before, 'стадия ВЫКЛ: rc 0, сообщение, ничего не создано (06-visible байт в байт)')
# включено, но нет входов — воздержание со следом, rc 0
rp = os.path.join(tmp, 'on.json'); R3 = json.loads(json.dumps(R)); R3['enabled'] = True; json.dump(R3, open(rp, 'w'))
r = subprocess.run([sys.executable, os.path.join(HERE, 'part_material_stage.py'), '--run', tmp, '--sku', 'x', '--glb', 'g.glb', '--photo', 'p.png', '--pose-run', tmp, '--rules', rp, '--product-role', 'шкаф'], capture_output=True, text=True, timeout=120)
rep = json.load(open(os.path.join(tmp, 'x', '06-visible', 'part_material.json'), encoding='utf-8')) if os.path.exists(os.path.join(tmp, 'x', '06-visible', 'part_material.json')) else {}
check(r.returncode == 0 and rep.get('abstain'), 'стадия ВКЛ без входов: воздержание со следом и причиной, rc 0 (06/07 красят как раньше)')

# ── тень по форме: ниша в плоскости (круг 29, шкаф) — заслонена, плоскость вокруг — нет; косая плоскость не судится
H = 200
dep = np.full((H, H), 1.0, np.float32); dep[80:120, 80:120] = 1.1                    # ниша глубиной 100 длин пикселя
vv = np.ones((H, H), bool)
oc = PM.pixel_occlusion(dep, vv, np.ones((H, H), np.float32), 0.001, R)
check(oc[100, 100] >= R['occlusion']['pixel_min'] and oc[20, 20] == 0 and oc[170, 30] == 0, 'заслонённость: дно ниши — да, плоскость вокруг — нет')
oc2 = PM.pixel_occlusion(dep, vv, np.full((H, H), 0.3, np.float32), 0.001, R)
check(float(oc2.max()) == 0.0, 'заслонённость: косая плоскость (cos < cos_min) не судится')
yy_, xx_ = np.mgrid[0:H, 0:H]
ids_ = ((yy_ // 10) * 20 + xx_ // 10).astype(np.int32)
inn, info = PM.interior_faces(ids_, oc, vv, 400, R)
check(bool(inn[(10 * 20 + 10)]) and not inn[0] and not inn[399] and info['граней_внутренность'] >= 4, 'грани внутренности: блоки на дне ниши — да, вокруг — нет')
ids2 = ids_.copy(); ids2[80:120, 120:123] = 400                                     # тонкая боковая стенка рядом с нишей (3 px) — грань 400
inn2 = np.zeros(401, bool)
for rr_ in range(8, 12):
    for cc_ in range(8, 12):
        inn2[rr_ * 20 + cc_] = True
rg2 = PM.ring_faces(ids2, vv, inn2, 401, R)
check(bool(rg2[400]) and not rg2[8 * 20 + 13] and not rg2[0] and rg2[8 * 20 + 8], 'кольцо внутренности: тонкая стенка рядом — да, грань в 10 px от ниши и дальше — нет')
Vc = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [2, 0, 0], [2, 1, 0], [10, 10, 0], [11, 10, 0], [10, 11, 0], [30, 30, 0], [31, 30, 0], [30, 31, 0]], float)
Fc = np.array([[0, 1, 2], [1, 3, 2], [1, 4, 3], [6, 7, 8], [9, 10, 11]])                   # связный кусок из 3 граней, одиночная грань (0,5 площади) и далёкая грань-фон
Rc = json.loads(json.dumps(R)); Rc['occlusion']['min_area_frac'] = 0.3
cc = PM.interior_clusters(Vc, Fc, np.array([True, True, True, True, False]), np.array([0.5, 0.5, 0.5, 0.5, 0.5]), Rc)
check(cc.tolist() == [True, True, True, False, False], 'куски внутренности: связный кусок остаётся, одиночная грань (шум) отброшена')
Vg = np.array([[0, 0, 0], [0.1, 0, 0], [0, 0.1, 0], [1, 0, 0], [1.1, 0, 0], [1, 0.1, 0], [5, 0, 0], [5.1, 0, 0], [5, 0.1, 0]], float)
Fg = np.array([[0, 1, 2], [3, 4, 5], [6, 7, 8]])
Rg = json.loads(json.dumps(R)); Rg['occlusion']['grow_frac'] = 0.25
gr = PM.grow_faces(Vg, Fg, np.array([True, False, False]), Rg)
check(gr.tolist() == [True, True, False], 'рост внутренности: соседняя грань (в пределах grow_frac диагонали) — да, дальняя — нет')

# ── детали лица: линия-щель в группе остаётся, плавный градиент уходит в плоский тон, цвет — от тона
Tt = 128
ctl_d = np.full((Tt, Tt, 3), 180, np.uint8)
ctl_d[:, 60:62] = 100                                                                 # тонкая тёмная линия (щель)
gradr = np.linspace(0.85, 1.0, Tt)[None, :, None]
ctl_g = np.clip(ctl_d * gradr, 0, 255).astype(np.uint8)                              # + плавная запечённая тень слева направо
flat = np.full((Tt, Tt, 3), (200, 190, 180), np.uint8)
mp = np.zeros((Tt, Tt), np.int16)
allm = np.ones((Tt, Tt), bool)
Rd = json.loads(json.dumps(R)); Rd['details']['sigma_frac'] = 0.04
td, dn_ = PM.keep_details(flat, ctl_g, mp, allm, allm, ['a'], set(), Rd)
line, side = td[:, 60:62].astype(float).mean(), td[:, 20:40].astype(float).mean()
check(dn_.get('a') == Tt * Tt and line < 0.75 * side, 'детали лица: щель остаётся заметно темнее фона')
check(abs(float(td[:, 100:120].mean()) - float(td[:, 10:30].mean())) < 6, 'детали лица: плавная тень (градиент) в плоский тон ушла')
check(td[10, 10, 0] > td[10, 10, 2] and td[10, 10, 1] > td[10, 10, 2], 'детали лица: оттенок от тона материала (не от серого фото)')
tk, dk = PM.keep_details(flat, ctl_g, mp, allm, np.zeros((Tt, Tt), bool), ['a'], set(), Rd)
check(dk == {} and (tk == flat).all(), 'детали лица: нет известных текселей — плоский тон как есть')

# ── ворота «лицо против фото»
rg = np.zeros((200, 200), bool); rg[20:180, 20:180] = True
fa = np.full((200, 200, 3), 190, np.uint8); fa[:, 100:102] = 110
g_ok = PM.face_gate(fa, fa.copy(), rg, R)
check(g_ok['fail'] == [] and g_ok['seam_ratio'] is not None and abs(g_ok['seam_ratio'] - 1) < 0.01, 'ворота: кадр как фото — проходит, щели 1,0')
fb = np.full((200, 200, 3), 190, np.uint8)                                            # плоская заливка: щель стёрта
g_seam = PM.face_gate(fb, fa, rg, R)
check(any('щели' in x for x in g_seam['fail']) and g_seam['seam_ratio'] < 0.3, 'ворота: щель стёрта плоской заливкой — отказ')
fc = fa.copy(); fc[40:140, 40:140] = (90, 50, 30)                                      # тёмное пятно вместо материала
g_far = PM.face_gate(fc, fa, rg, R)
check(any('пятно' in x for x in g_far['fail']) and any('доля' in x for x in g_far['fail']), 'ворота: тёмное пятно вместо материала — отказ (доля и пятно)')
check(PM.face_gate(fa, fa, np.zeros((200, 200), bool), R).get('skipped') == 'мало пикселей региона', 'ворота: пустой регион — пропуск, не отказ')
fo = np.zeros((200, 200, 3), np.uint8); fo[:] = (200, 90, 50)                           # оранжевое фото с плавным запечённым градиентом света
grad = np.linspace(0.65, 1.0, 200)[None, :, None]
fo_g = (fo * grad).astype(np.uint8)
check(PM.face_gate(fo, fo_g, rg, R)['fail'] == [], 'ворота: снят плавный запечённый свет (тот же цвет) — проходит')
dots = np.full((400, 400, 3), 200, np.uint8); dots[::8, ::8] = 60; dots[1::8, ::8] = 60            # перфорация/сетка: тёмные точки, не щели
rg4 = np.zeros((400, 400), bool); rg4[20:380, 20:380] = True
gd = PM.face_gate(np.full((400, 400, 3), 200, np.uint8), dots, rg4, R)
check(gd['seam_ratio'] is None and gd['seam_px'] == 0 and not any('щели' in x for x in gd['fail']), 'ворота: точки сетки не считаются щелями (нет «потери деталей» от узора)')
hand = np.full((400, 400, 3), 225, np.uint8); hand[150:162, 200:208] = 90                       # ручка: тёмная компактная деталь на лице
hand_gone = np.full((400, 400, 3), 225, np.uint8)
g_h = PM.face_gate(hand_gone, hand, rg4, R)
check(g_h['spot_ratio'] is not None and g_h['spot_ratio'] < 0.1 and any('ручка' in x for x in g_h['fail']), 'ворота: ручка стёрта плоской заливкой — отказ (пятна)')
two = np.full((400, 400, 3), 225, np.uint8); two[150:162, 100:108] = 90; two[150:162, 300:308] = 90             # две ручки: одна на месте, другая исчезла — по КАЖДОМУ пятну, не по сумме
two_after = two.copy(); two_after[150:162, 100:108] = 225
g_two = PM.face_gate(two_after, two, rg4, R)
check(g_two['spot_n'] == 2 and g_two['spot_min'] is not None and g_two['spot_min'] < 0.1 and g_two['spot_ratio'] > 0.4 and any('ручка' in x for x in g_two['fail']), 'ворота: одна ручка исчезла, другая цела — отказ по худшему пятну (сумма 0,5 не прячет)')
# «чужой материал»: тёмная компактная ручка на светлой панели остаётся фото, щель (тонкая линия) и сама панель — красятся
Tt = 1024
ctl_f = np.full((Tt, Tt, 3), 225, np.uint8); ctl_f[400:440, 480:510] = 60; ctl_f[:, 160:162] = 80            # панель + ручка 40×30 + щель 2 текселя на всю высоту
tmap = np.zeros((Tt, Tt), np.int16); known_f = np.ones((Tt, Tt), bool)
tones_f = {'фасад': {'own': True, 'lab': PM.lab_of(np.array([225, 225, 225], np.uint8)[None])[0]}}
fg_f, fi_f = PM.foreign_texels(ctl_f, tmap, np.ones((Tt, Tt), bool), known_f, ['фасад'], {'фасад': 1}, {}, tones_f, R)
check(fg_f[430, 500] and not fg_f[600, 161] and not fg_f[10, 10], 'чужой материал: ручка остаётся фото, щель-линия и панель — нет')
check(PM.face_gate(hand.copy(), hand, rg4, R, 4.0)['seam_min_len_px'] == 40.0 and PM.face_gate(hand.copy(), hand, rg4, R, 0.5)['seam_min_len_px'] == 12.0, 'ворота: щель меряется в см по карточке (10 см × px/см, не короче 12 px)')
g_h2 = PM.face_gate(hand.copy(), hand, rg4, R)
check(g_h2['spot_ratio'] is not None and abs(g_h2['spot_ratio'] - 1) < 0.02 and g_h2['fail'] == [], 'ворота: ручка сохранена — проходит, число 1,0')
g_h3 = PM.face_gate(np.full((400, 400, 3), 200, np.uint8), dots, rg4, R)
check(g_h3['spot_ratio'] is None, 'ворота: точки сетки не пятна (слишком малы)')
fp = np.zeros((200, 200, 3), np.uint8); fp[:] = (230, 200, 190)                     # бледный верх вместо оранжевого
check(any('доля' in x for x in PM.face_gate(fp, fo, rg, R)['fail']), 'ворота: цвет ушёл (оранжевый → бледный) — отказ даже при снятии света')

# ── seed k-means: тон и доля воспроизводимы между вызовами
rs = np.random.RandomState(5)
pxs = np.concatenate([rs.normal((230, 230, 230), 6, (600, 3)), rs.normal((90, 60, 40), 8, (400, 3))]).clip(0, 255).astype(np.uint8)
check(PM.main_cluster(pxs)[1] == PM.main_cluster(pxs)[1] == PM.main_cluster(pxs)[1], 'kmeans: доля главного кластера воспроизводима (seed фиксирован)')

# ── обвязка: ВЫКЛ → шаг выпадает из плана (не берёт слот heavy-slot); ВКЛ → шаг в плане
smx = R['same_material']
L_ = lambda L, a_, b_: np.array([L, a_, b_], float)   # noqa: E731
check(not PM.same_material(L_(74.1, -2.1, -0.7), L_(72.2, -1.8, 7.3), smx)[0], 'материал: мятный и дуб (оба светлые «нейтральные», разница по a,b 8) — не один материал')
check(not PM.same_material(L_(95.8, 0.0, 0.0), L_(56.5, 8.0, 22.5), smx)[0], 'материал: белый верх и деревянные ножки — не сливать')
check(PM.same_material(L_(45.7, 0.0, 1.3), L_(43.0, 0.0, 1.0), smx)[0], 'материал: графит у фасада и у бока чуть темнее (Δab 0,3) — один')
check(PM.same_material(L_(60.0, 8.0, 22.0), L_(42.0, 5.6, 15.4), smx)[0], 'материал: те же ножки в тени (тот же оттенок, C/L как у света) — слить')
_r = {'unify_max_dl': 3}
check(PM._unify_dl(True, 'x', [45.7, 0, 0], [47.0, 0, 0], _r)[0] is True and PM._unify_dl(True, 'x', [41.6, 0, 0], [45.7, 0, 0], _r)[0] is False and PM._unify_dl(True, 'x', [41.6, 0, 0], [45.7, 0, 0], {})[0] is True, 'тон: часть берёт чужой тон только при |ΔL| ≤ unify_max_dl (настоящая разница светлоты — свой тон)')
import paint_run_all as PRA  # noqa: E402
rr = os.path.join(tmp, 'rules'); os.makedirs(rr)
json.dump({'enabled': False}, open(os.path.join(rr, 'f.json'), 'w'))
stg = {'steps': [{'argv': ['a']}, {'argv': ['b'], 'heavy': {'prio': 1}, 'enabled_by': {'file': 'rules/f.json', 'key': 'enabled'}}]}
cx = {'root': tmp, 'pythons': {}, 'py': 'py'}
check([s['argv'] for s in PRA.resolve_steps(stg, cx)] == [['a']], 'обвязка: флаг ВЫКЛ — шаг не в плане, слот heavy-slot не занимается')
json.dump({'enabled': True}, open(os.path.join(rr, 'f.json'), 'w'))
check([s['argv'] for s in PRA.resolve_steps(stg, cx)] == [['a'], ['b']], 'обвязка: флаг ВКЛ — шаг в плане')
os.remove(os.path.join(rr, 'f.json'))
check([s['argv'] for s in PRA.resolve_steps(stg, cx)] == [['a']], 'обвязка: файла правил нет — шаг не в плане')
real = json.load(open(os.path.join(HERE, 'rules', 'paint-run-all.json'), encoding='utf-8'))
pm_steps = [s for st in real['stages'].values() for s in st.get('steps', []) if any('part_material_stage' in t for t in s['argv'])]
check(len(pm_steps) == 1 and pm_steps[0].get('enabled_by', {}).get('file') == 'tools/scout/rules/part-material.json', 'правила обвязки: шаг материала части условный (enabled_by → part-material.json)')

# ── надёжность граней как источника деталей фото (reliability, круг 3 стола 25.11; флаг выкл по умолчанию) ──
RL = R['reliability']
check(RL['enabled'] is False, 'надёжность: по умолчанию ВЫКЛ (байт в байт как без правила)')
Hh = 96
ids_r = np.full((Hh, Hh), -1, np.int64)
for ty in range(Hh // 8):
    for tx in range(Hh // 8):
        ids_r[ty * 8:(ty + 1) * 8, tx * 8:(tx + 1) * 8] = ty * (Hh // 8) + tx            # грань = плитка 8×8 px
nF_r = (Hh // 8) ** 2
valid_r = np.zeros((Hh, Hh), bool)
valid_r[8:88, 8:88] = True                                                                # широкий блок 80×80
valid_r[:, 0:2] = True                                                                     # тонкая полоска у левого края (2 px)
cos_r = np.full((Hh, Hh), 0.9, np.float32)
cen_r = np.zeros((nF_r, 3))
for fi in range(nF_r):
    cen_r[fi] = [(fi % (Hh // 8)) * 8.0, (fi // (Hh // 8)) * 8.0, 0.0]                    # плоскость: соседи на расстоянии одной плитки
el_r = np.full(nF_r, 8.0)
rel_r = PM.face_reliability(ids_r, cos_r, cen_r, el_r, valid_r, 1.0, nF_r, RL)
ok_r, why_r = PM.reliable_faces(rel_r, RL)
fid_mid = 5 * (Hh // 8) + 5                                                               # плитка в середине блока
fid_edge = 1 * (Hh // 8) + 1                                                              # плитка у силуэта блока (кромка в 0 px)
fid_thin = 5 * (Hh // 8) + 0                                                              # тонкая полоска
check(bool(ok_r[fid_mid]), 'надёжность: середина широкого блока, прямо к камере — надёжна')
check(not bool(ok_r[fid_edge]), 'надёжность: у края силуэта (< 2 ошибок позы) — ненадёжна')
check(not bool(ok_r[fid_thin]), 'надёжность: тонкая деталь (< 4 ошибок позы шириной) — ненадёжна')
cos_g = cos_r.copy()
cos_g[ids_r == fid_mid] = 0.1
rel_g = PM.face_reliability(ids_r, cos_g, cen_r, el_r, valid_r, 1.0, nF_r, RL)
ok_g, _ = PM.reliable_faces(rel_g, RL)
check(not bool(ok_g[fid_mid]), 'надёжность: скользящая грань (cos 0,1 < cos_min) — ненадёжна')
cen_o = cen_r.copy()
cen_o[fid_mid, 2] = 500.0                                                                 # грань далеко от соседей в мире — перекрытие
rel_o = PM.face_reliability(ids_r, cos_r, cen_o, el_r, valid_r, 1.0, nF_r, RL)
ok_o, _ = PM.reliable_faces(rel_o, RL)
check(not bool(ok_o[fid_mid]) and not bool(ok_o[fid_mid + 1]), 'надёжность: разрыв по глубине между соседями (перекрытие) — обе стороны ненадёжны')
rl_off = dict(RL, cos_min=0.0, edge_errs=0.0, thin_errs=0.0)
ok_all, why_all = PM.reliable_faces(rel_g, rl_off)
check(bool(ok_all[fid_edge]) and bool(ok_all[fid_thin]) and bool(ok_all[fid_mid]) and why_all['надёжна'] == why_all['видна'], 'надёжность: пороги 0 — правила выключены по одному, остаётся «видна в кадре» (растекание не берётся)')
check(rel_r['cnt'][fid_mid] == 64.0 and rel_r['cnt'][nF_r - 1] == 0.0, 'надёжность: cnt — пиксели в кадре; вне предмета 0 (невидимая грань)')
UVt = np.array([[0.1, 0.1], [0.4, 0.1], [0.1, 0.4], [0.6, 0.6], [0.9, 0.6], [0.6, 0.9]])
Ft = np.array([[0, 1, 2], [3, 4, 5]])
fm_t = PM.uv_face_map(UVt, Ft, 100)
check(fm_t.shape == (100, 100) and fm_t[100 - 20, 20] == 0 and fm_t[100 - 70, 70] == 1, 'карта текселей: строка = (1 − v)·T, грань по текселю; пропуски — ближайшей гранью')
check(int(fm_t.min()) >= 0, 'карта текселей: пропусков нет')

print('\nИТОГО: %d провалов' % len(FAILS))
sys.exit(1 if FAILS else 0)
