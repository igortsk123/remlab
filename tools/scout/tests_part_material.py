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
keep, bor, same = PM.pick_sources(t, R)
check(bor.get('зад') in ('бок', 'фасад'), 'зад берёт тон бока (через цепочку — итоговый тон бока)')
check(bor.get('бок') == 'фасад' and same['бок']['same'], 'бок того же материала, что фасад → тон фасада (студийная тень не красится в серое)')
check(bor.get('верх') == 'бок' or bor.get('верх') == 'фасад', 'верх без пикселей → донор по лесенке (бок), а не родной цвет')
t = {'фасад': tone(70, 20, 25, ab_minor=0.3), 'бок': tone(0, 0, 0, own=False), 'зад': tone(0, 0, 0, own=False), 'верх': tone(0, 0, 0, own=False)}
keep, bor, same = PM.pick_sources(t, R)
check('фасад' in keep, 'фасад с рисунком (другой оттенок на >2 %) — фото 06 остаётся')
check(bor.get('бок') != 'фасад' and bor.get('зад') is None, 'донор — не группа с рисунком: бок/зад не берут тон узорного фасада (нечем красить → «не уверен»)')
t = {'фасад': tone(70, 20, 25), 'ножки': tone(0, 0, 0, own=False)}
keep, bor, same = PM.pick_sources(t, R)
check(bor.get('ножки', 'x') is None, 'ножки без пикселей: донора нет (ножки — своя группа) → не красим, «не уверен»')

t = {'фасад': tone(90, 0, 1), 'бок': tone(76, 0, 1), 'зад': tone(0, 0, 0, own=False)}
keep, bor, same = PM.pick_sources(t, R)
check(bor.get('зад') == 'фасад', 'цепочка донора: зад ← бок ← фасад → итоговый тон фасада (а не тон теневого бока)')
t = {'фасад': tone(90, 0, 1), 'бок': tone(0, 0, 0, own=False), 'зад': tone(40, 0, 0, own=False), 'верх': tone(30, 40, 40)}
keep, bor, same = PM.pick_sources(t, R)
t2 = {'фасад': tone(90, 0, 1), 'бок': tone(30, 40, 40), 'зад': tone(0, 0, 0, own=False)}
keep, bor, same = PM.pick_sources(t2, R)
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
keep, bor, same = PM.pick_sources(tu, R, {'верх': 1.0, 'бок': 1.0, 'корпус': 1.0, 'фасад': 1.0})
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

# ── обвязка: ВЫКЛ → шаг выпадает из плана (не берёт слот heavy-slot); ВКЛ → шаг в плане
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

print('\nИТОГО: %d провалов' % len(FAILS))
sys.exit(1 if FAILS else 0)
