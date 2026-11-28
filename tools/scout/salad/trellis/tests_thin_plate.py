#!/usr/bin/env python3
"""Тест thin_plate (T-97/1 фаза 7): синтетика — плита-коробка 1,0×0,5×0,03: лицо (группа «верх», дубовый узор), низ (группа «ножки», серый), торец (серый).
Проверяем: тонкая плита → низ и торец берут цвет лица, лицо не тронуто, маска = перекрашенное; «известные на фото» торец не трогается; толстая плита и плита без нижней плоскости — текстура та же с причиной;
ключ меняет выход (выкл по умолчанию в rules-json; включённый обязан менять); check_rules ловит плохие пороги; load_rules при enabled=false thin_plate не читает."""
import os as _rt_os  # noqa: E402
import sys as _rt_sys  # noqa: E402
_rt_sys.path.append(_rt_os.path.join(_rt_os.path.dirname(_rt_os.path.abspath(__file__)), '../..'))
import remlab_tmp  # noqa: E402,I001  — временное теста на диске и с уборкой при выходе (T-20261107-13)
remlab_tmp.use('tests_thin_plate')
import copy
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import part_grain as PG  # noqa: E402
import thin_plate as TPL  # noqa: E402

OK = []


def check(cond, msg):
    if not cond:
        print('FAIL:', msg)
        sys.exit(1)
    OK.append(msg)
    print('ok:', msg)


def box(th):
    """Плита x∈[0,1], z∈[0,0.5], y∈[0,th]: лицо (группа 0), низ и торец (группа 1); развёртка: лицо [0,.5]², низ [.5,1]×[0,.5], торец — полосы в v∈[.5,1]."""
    V, UV, F, G = [], [], [], []

    def tri(p3, uv3, grp, out_dir):
        p3 = np.array(p3, float)
        n = np.cross(p3[1] - p3[0], p3[2] - p3[0])
        if np.dot(n, out_dir) < 0:
            p3, uv3 = p3[[0, 2, 1]], np.array(uv3, float)[[0, 2, 1]]
        base = len(V)
        V.extend(p3.tolist())
        UV.extend(np.array(uv3, float).tolist())
        F.append([base, base + 1, base + 2])
        G.append(grp)

    def quad_xz(y, u0, grp, out_dir):
        for i in range(8):                                           # сетка 8×4: центры граней занимают почти весь размер (размер верха меряется по центрам граней)
            for j in range(4):
                x0, x1, z0, z1 = i / 8, (i + 1) / 8, j / 8, (j + 1) / 8
                c = [(x0, z0), (x1, z0), (x1, z1), (x0, z1)]
                P = [(x, y, z) for x, z in c]
                U = [(u0 + 0.5 * x, z) for x, z in c]
                for ids in ([0, 1, 2], [0, 2, 3]):
                    tri([P[q] for q in ids], [U[q] for q in ids], grp, out_dir)

    quad_xz(th, 0.0, 0, (0, 1, 0))
    quad_xz(0.0, 0.5, 1, (0, -1, 0))
    for k, (a, b, nrm) in enumerate((((0, 0, 0), (1, 0, 0), (0, 0, -1)), ((0, 0, 0.5), (1, 0, 0.5), (0, 0, 1)), ((0, 0, 0), (0, 0, 0.5), (-1, 0, 0)), ((1, 0, 0), (1, 0, 0.5), (1, 0, 0)))):
        a, b = np.array(a, float), np.array(b, float)
        P = [a, b, b + (0, th, 0), a + (0, th, 0)]
        U = [(0.25 * k + 0.25 * s, 0.5 + 0.1 * y / th) for s, y in ((0, 0), (1, 0), (1, th), (0, th))]
        for ids in ([0, 1, 2], [0, 2, 3]):
            tri([P[i] for i in ids], [U[i] for i in ids], 1, nrm)
    return np.array(V), np.array(UV), np.array(F), np.array(G)


def texture(rng):
    T = 256
    tex = np.full((T, T, 3), 120, np.uint8)                          # серый — низ и торец
    face = np.clip(np.array([150, 100, 50]) + rng.integers(-12, 13, (T // 2, T // 2, 1)), 0, 255)
    tex[:T // 2, :T // 2] = face.astype(np.uint8)                       # лицо — дуб с узором
    return tex


rules = PG.load_rules()
tp = copy.deepcopy(rules['thin_plate'])
check(tp['enabled'] is False, 'в rules-json thin_plate.enabled=false по умолчанию')
rng = np.random.default_rng(7)
tex = texture(rng)
V, UV, F, G = box(0.03)
known = np.zeros(tex.shape[:2], bool)
new, ch, info = TPL.apply(tex, V, UV, F, G, 0, known, tp)
check(info['applied'] and info.get('тонкая'), 'тонкая плита (0,03 при размере 0,5) распознана: %s' % {k: info[k] for k in ('y_лицо', 'y_низ', 'толщина')})
check(abs(info['y_низ']) < 1e-6 and abs(info['y_лицо'] - 0.03) < 1e-6, 'y_низ=0, y_лицо=0,03')
check((new[:128, :128] == tex[:128, :128]).all(), 'лицо не тронуто')
bot = new[:128, 128:256]
check(float(np.abs(bot.astype(float).mean((0, 1)) - tex[:128, :128].astype(float).mean((0, 1))).max()) < 6, 'низ взял средний цвет лица (≠ серого)')
check(not (bot == 120).all(), 'низ больше не серый')
check(float(bot.astype(float).std()) > 1.0, 'на низе есть узор лица (не плоский тон)')
check(int(ch.sum()) > 10000 and info['перекрашено_текселей'] == int(ch.sum()), 'маска перекрашенного = число в следе (%d)' % int(ch.sum()))
check((new[128:] != tex[128:]).any(), 'торец (полосы развёртки) перекрашен')
check((new != tex).any(), 'включённый ключ меняет выход')
# известные на фото торец — свой
kn = np.zeros_like(known)
kn[128:, :] = True
new2, ch2, info2 = TPL.apply(tex, V, UV, F, G, 0, kn, tp)
check((new2[128:] == tex[128:]).all(), 'известные на фото тексели торца не тронуты')
check(int(ch2.sum()) < int(ch.sum()), 'с известным торцем перекрашено меньше')
# толстая плита — не тонкая
V2, UV2, F2, G2 = box(0.2)
new3, ch3, info3 = TPL.apply(tex, V2, UV2, F2, G2, 0, known, tp)
check((not info3['applied']) and not (new3 != tex).any() and not ch3.any() and ('не тонкая' in info3['reason'] or 'нет вниз-смотрящих' in info3['reason']), 'толстая плита — текстура та же, причина: %s' % info3['reason'])
# нет верха
new4, ch4, info4 = TPL.apply(tex, V, UV, F, G, 5, known, tp)
check((not info4['applied']) and not (new4 != tex).any(), 'нет группы лица — текстура та же (%s)' % info4['reason'])
# пороги
bad = copy.deepcopy(tp)
bad['thin_ratio'] = 0.9
try:
    TPL.check_rules(bad)
    check(False, 'плохой thin_ratio должен падать')
except ValueError:
    check(True, 'check_rules: thin_ratio 0,9 отклонён')
bad = copy.deepcopy(tp)
del bad['dilate_px']
try:
    TPL.check_rules(bad)
    check(False, 'нет ключа должен падать')
except ValueError:
    check(True, 'check_rules: нет ключа dilate_px отклонён')
# load_rules: выкл — ключ не читается; вкл — проверяется
with open(PG.RULES_PATH, encoding='utf-8') as fh:
    base = json.load(fh)
import tempfile  # noqa: E402
d = tempfile.mkdtemp()
p = os.path.join(d, 'r.json')
r1 = copy.deepcopy(base)
r1['thin_plate'] = {'enabled': False, 'thin_ratio': 99}
json.dump(r1, open(p, 'w'))
PG.load_rules(p)
check(True, 'load_rules: при enabled=false thin_plate не проверяется')
r2 = copy.deepcopy(base)
r2['thin_plate'] = dict(base['thin_plate'], enabled=True, thin_ratio=99)
json.dump(r2, open(p, 'w'))
try:
    PG.load_rules(p)
    check(False, 'load_rules должен падать на плохом включённом thin_plate')
except ValueError:
    check(True, 'load_rules: включённый thin_plate с плохим порогом отклонён')
print('ВСЕ %d ПРОВЕРОК ПРОШЛИ' % len(OK))
