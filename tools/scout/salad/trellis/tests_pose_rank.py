#!/usr/bin/env python3
"""Тесты `pose_rank.py` (T-173/3 Ш2б(а)): расстояние контуров и Boundary-F, семейства поз, гипотеза yaw+180°, «камера не под полом», выбор. Синтетика, без GLB и сети.
  python3 tools/scout/salad/trellis/tests_pose_rank.py"""
from __future__ import annotations

import inspect
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
import numpy as np  # noqa: E402
import pose_fit as PF  # noqa: E402
import pose_rank as PR  # noqa: E402

bad = 0


def check(name: str, ok: bool, extra: str = '') -> None:
    global bad
    if not ok:
        bad += 1
    print(('ok   ' if ok else 'FAIL ') + name + (f'  [{extra}]' if extra else ''))


def disc(n: int, cx: float, cy: float, r: float) -> np.ndarray:
    yy, xx = np.mgrid[:n, :n]
    return (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r


R = PR.rules()
check('правила: ключи и допуски 1/2/4/8', all(k in R for k in ('version', 'fam_k', 'fam_sep_az', 'fam_sep_el', 'floor_margin', 'tie_score', 'weak_gain_eps', 'bf_tols')) and R['bf_tols'] == [1, 2, 4, 8])

A = disc(768, 384, 384, 200)
m0 = PR.contour_metrics(A, A)
check('контуры: одинаковые маски → Chamfer 0, Boundary-F 1 на всех допусках', m0['chamfer_px'] == 0 and all(v == 1.0 for v in m0['bf'].values()), str(m0))
m3 = PR.contour_metrics(disc(768, 387, 384, 200), A)
check('контуры: сдвиг на 3 px — на допуске 1 px низко, на 4 и 8 px полно', m3['bf']['1'] < 0.7 and m3['bf']['4'] >= 0.99 and m3['bf']['8'] == 1.0, str(m3['bf']))
check('контуры: Boundary-F не убывает с допуском', all(m3['bf'][a] <= m3['bf'][b] for a, b in (('1', '2'), ('2', '4'), ('4', '8'))))
check('контуры: Chamfer при сдвиге 3 px в разумных пределах', 0.8 < m3['chamfer_px'] < 3.2, str(m3['chamfer_px']))
m3s = PR.contour_metrics(disc(384, 193.5, 192, 100), disc(384, 192, 192, 100))
check('контуры: px приведены к кадру 768 (сдвиг 1,5 px в кадре 384 ≈ 3 px в 768)', abs(m3s['chamfer_px'] - m3['chamfer_px']) < 0.8, f"{m3s['chamfer_px']} vs {m3['chamfer_px']}")
m_big = PR.contour_metrics(disc(768, 384, 384, 150), A)
check('контуры: форма мельче фото на 50 px → Chamfer ≈ 50, Boundary-F на 8 px ≈ 0', 45 < m_big['chamfer_px'] < 55 and m_big['bf']['8'] < 0.05, str(m_big))
check('контуры: пустая форма → без падения, F = 0', PR.contour_metrics(np.zeros((768, 768), bool), A)['chamfer_px'] is None)
check('контуры: Chamfer % — доля диагонали фото', abs(m3['chamfer_pct'] - 100 * m3['chamfer_px'] / (400 * 2 ** 0.5)) < 0.05, str(m3['chamfer_pct']))

recs = [{'cam': {'az': a, 'el': e}, 'score': s} for a, e, s in ((10, 10, .9), (15, 12, .89), (190, 10, .88), (100, 10, .87), (355, 30, .86), (350, 11, .85))]
fam = PR.separate(recs, 5, 30.0, 12.0)
check('семейства: близкие позы (10/15/350) сливаются, 190 и 100 остаются, 355/el 30 отдельно по подъёму', [(f['cam']['az'], f['cam']['el']) for f in fam] == [(10, 10), (190, 10), (100, 10), (355, 30)], str([(f['cam']['az'], f['cam']['el']) for f in fam]))
check('семейства: не больше k', len(PR.separate(recs, 2, 30.0, 12.0)) == 2)
check('азимут по кругу: 359 и 1 — одно семейство', len(PR.separate([{'cam': {'az': 359, 'el': 5}}, {'cam': {'az': 1, 'el': 5}}], 5, 30.0, 12.0)) == 1)
check('yaw+180°: 350 и 170 перевёрнуты, 350 и 200 — тоже в допуске, 350 и 100 — нет', PR.is_flip_of({'az': 350}, {'az': 170}) and PR.is_flip_of({'az': 350}, {'az': 200}) and not PR.is_flip_of({'az': 350}, {'az': 100}))

cb = PF.cam_basis
check('высота камеры: на уровне центра (el 0) — половина высоты над низом', abs(PR.cam_height_rel({'az': 0, 'el': 0, 'd': 3.0}, -.5, .5, cb) - 0.5) < 1e-9)
check('высота камеры: сверху (el 40, d 3) — выше предмета, > 1', PR.cam_height_rel({'az': 0, 'el': 40, 'd': 3.0}, -.5, .5, cb) > 1.0)
h_low = PR.cam_height_rel({'az': 0, 'el': -30, 'd': 3.0}, -.5, .5, cb)
check('высота камеры: снизу (el −30, d 3) — под полом (< порога)', h_low < R['floor_margin'], f'{h_low:.3f}')
# высокий шкаф: камера на уровне полу-метра ниже центра, но над полом — не под полом (по углу к центру это el < 0)
tall = PR.cam_height_rel({'az': 0, 'el': -8, 'd': 3.0}, -.5, .5, cb)
check('высота камеры: el −8, d 3 — ниже центра предмета (угол к центру отрицательный), но выше пола → не под полом', 0 < R['floor_margin'] <= tall < 0.5, f'{tall:.3f}')

fams = [{'floor_ok': False, 'score': 0.90, 'bf': {'2': 0.9}, 'chamfer_px': 2.0}, {'floor_ok': True, 'score': 0.88, 'bf': {'2': 0.7}, 'chamfer_px': 3.0}, {'floor_ok': True, 'score': 0.875, 'bf': {'2': 0.8}, 'chamfer_px': 2.5},
        {'floor_ok': True, 'score': 0.70, 'bf': {'2': 0.99}, 'chamfer_px': 1.0}]
c = PR.choose(fams, R)
check('выбор: лучшая под полом пропущена; ничья в tie_score — по Boundary-F(2 px); далёкая по оценке не берётся', c['index'] == 2 and c['changed'] is True, str(c))
c0 = PR.choose([{'floor_ok': False, 'score': .9, 'bf': {'2': .9}, 'chamfer_px': 1.0}], R)
check('выбор: все под полом → остаётся боевая, changed False', c0['index'] == 0 and c0['changed'] is False)

cube_V = np.array([[x, y, z] for x in (-.5, .5) for y in (-.5, .5) for z in (-.5, .5)], float)
cube_F = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]])
S_pts = PF._surf_points({'V': cube_V, 'F': cube_F}, n_pts=20000)
n = 64
cam_true = {'az': 35.0, 'el': 20.0, 'd': 3.0, 'f': 2.0, 'cx': 0.5, 'cy': 0.5}
Mp = PF.splat_mask(S_pts, cam_true, n)
Mb = PF._blur(Mp, n)
cam0 = {'az': 25.0, 'el': 12.0, 'd': 3.5, 'f': 2.0, 'cx': 0.5, 'cy': 0.5}
c1, nit = PF.nm_two_stage(S_pts, Mp, Mb, n, cam0)
s0, s1 = PF.pose_score(PF.splat_mask(S_pts, cam0, n), Mp)['score'], PF.pose_score(PF.splat_mask(S_pts, c1, n), Mp)['score']
check('nm_two_stage: подбор улучшает оценку и держит d в пределах', s1 > s0 and PF.D_MIN <= c1['d'] <= PF.D_MAX, f'{s0} → {s1}, шагов {nit}')
check('pose_fit: --rank по умолчанию выключен, блок rank в ответе', inspect.signature(PF.fit_pose).parameters['rank'].default is False)

# ---------- «перёд или зад» (тень): голоса и итог ----------
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
O = R['orientation']
check('правила: orientation — все пороги в одном месте', all(k in O for k in ('sil_gap', 'color_rel', 'color_abs', 'geom_gap', 'need_votes', 'sym_de', 'sym_shade', 'sym_iou', 'blur_frac')))
rng = np.random.default_rng(1)
base = (rng.random((96, 96, 3)) * 255).astype(np.uint8)
shifted = np.roll(base, 1, axis=1)
cmk = np.ones((96, 96), bool)
d_raw, d_blur = PR.lab_diff(base, shifted, cmk), PR.lab_diff(base, shifted, cmk, blur_px=4.0)
check('lab_diff: сдвиг мелкого узора на пиксель — попиксельно велик, после сглаживания мал', d_raw['de_med'] > 8 and d_blur['de_med'] < d_raw['de_med'] / 3, f"{d_raw['de_med']} → {d_blur['de_med']}")
tone = np.clip(base.astype(np.int16) + 20, 0, 255).astype(np.uint8)
check('lab_diff: общий сдвиг яркости вычитается (не ошибка цвета)', PR.lab_diff(base, tone, cmk, blur_px=2.0)['de_med'] < PR.lab_diff(base, np.flip(base, 0).copy(), cmk, blur_px=2.0)['de_med'])
check('lab_diff: пустая маска → None', PR.lab_diff(base, base, np.zeros((96, 96), bool)) is None)


def cues(color, geom):
    return {'color': {'de_blur_med': color}, 'geom_edge': geom}


v = PR.orientation_votes(0.05, cues(2.0, 0.30), cues(5.0, 0.10), R)
check('голоса: силуэт/цвет/геометрия «за», когда выбранная лучше с запасом', (v['silhouette'], v['color'], v['geom']) == ('за', 'за', 'за'), str(v))
v = PR.orientation_votes(0.0, cues(2.0, 0.30), cues(2.1, 0.32), R)
check('голоса: разрыв внутри порога — «—» (ни за, ни против)', (v['silhouette'], v['color'], v['geom']) == ('—', '—', '—'), str(v))
v = PR.orientation_votes(-0.05, cues(5.0, 0.10), cues(2.0, 0.30), R)
check('голоса: у +180° лучше — «против» по всем трём', (v['silhouette'], v['color'], v['geom']) == ('против', 'против', 'против'))
v = PR.orientation_votes(0.0, cues(2.0, 0.3), None, R)
check('голоса: нет позы +180° → цвет и геометрия «нет»', (v['color'], v['geom']) == ('нет', 'нет'))
v = PR.orientation_votes(0.0, {'color': None, 'geom_edge': 0.3}, {'color': None, 'geom_edge': 0.1}, R)
check('голоса: форма без текстуры (цвета нет) — «нет», геометрия считается', (v['color'], v['geom']) == ('нет', 'за'))


def verdict(gap, c_pick, c_flip, pair=None):
    return PR.orientation_verdict(PR.orientation_votes(gap, c_pick, c_flip, R), pair, R)


check('итог: силуэт разводит → front_silhouette, отказа нет', verdict(0.3, cues(2, .3), cues(2, .3))['verdict'] == 'front_silhouette')
x = verdict(0.0, cues(2.0, 0.30), cues(5.0, 0.10))
check('итог: ничья силуэта, цвет и геометрия оба «за» → front_cues', x['verdict'] == 'front_cues' and not x['ambiguous'] and x['shadow'] is True)
x = verdict(0.0, cues(2.0, 0.30), cues(2.1, 0.10))
check('итог: ничья, «за» только у геометрии (need_votes 2) → ambiguous + код ORIENTATION_AMBIGUOUS', x['verdict'] == 'ambiguous' and x['ambiguous'] and x['code'] == 'ORIENTATION_AMBIGUOUS')
x = verdict(0.0, cues(5.0, 0.10), cues(2.0, 0.30))
check('итог: ничья, цвет и геометрия оба «против» → flip_suggested (подсказка, поза не меняется)', x['verdict'] == 'flip_suggested' and not x['ambiguous'])
x = verdict(0.0, cues(2.0, 0.10), cues(5.0, 0.30))
check('итог: ничья, цвет «за», геометрия «против» → ambiguous (конфликт)', x['verdict'] == 'ambiguous')
check('итог: силуэт «против» → flip_suggested', verdict(-0.1, cues(2, .3), cues(2, .3))['verdict'] == 'flip_suggested')
PAIR = {'de_med': 0.5, 'shade_mad': 0.5, 'mask_iou': 0.97}
x = verdict(0.0, cues(2.0, 0.10), cues(2.1, 0.10), pair=PAIR)
check('итог: два рендера почти одинаковы по форме и цвету (симметрия по виду, а не по названию) → symmetric, не отказ', x['verdict'] == 'symmetric' and not x['ambiguous'])
x = verdict(0.0, cues(2.0, 0.10), cues(2.1, 0.10), pair=dict(PAIR, de_med=6.0))
check('итог: цвет рендеров различается (сторона важна), сигналов нет → ambiguous', x['verdict'] == 'ambiguous')
x = verdict(0.0, cues(2.0, 0.10), cues(2.1, 0.10), pair=dict(PAIR, shade_mad=12.0))
check('итог: однотонный предмет, цвет одинаков, но форма фасада различается (ручки, щели) — не симметрия → ambiguous', x['verdict'] == 'ambiguous')
x = verdict(0.0, cues(2.0, 0.10), cues(2.1, 0.10), pair=dict(PAIR, de_med=None))
check('итог: без текстуры симметрию решает форма (цвета нет)', x['verdict'] == 'symmetric')
x = verdict(0.0, cues(2.0, 0.10), cues(2.1, 0.10), pair=dict(PAIR, mask_iou=0.5))
check('итог: рендеры похожи, но маски разные (iou < sym_iou) — это не симметрия', x['verdict'] == 'ambiguous')
check('итог: силуэт «за», но цвет «против» → ambiguous (спор, не уверенный перёд)', verdict(0.05, cues(5.0, 0.30), cues(2.0, 0.30))['verdict'] == 'ambiguous')
check('итог: силуэт «против», но геометрия «за» → ambiguous (спор, не подсказка переворота)', verdict(-0.05, cues(2.0, 0.30), cues(2.1, 0.10))['verdict'] == 'ambiguous')
R1 = dict(R, orientation=dict(O, need_votes=1))
x1 = PR.orientation_verdict(PR.orientation_votes(0.0, cues(2.0, 0.30), cues(2.1, 0.10), R1), None, R1)
x2 = PR.orientation_verdict(PR.orientation_votes(0.0, cues(2.0, 0.30), cues(2.1, 0.10), R), None, R)
check('итог: need_votes 1 — одного «за» (геометрия) без «против» достаточно; при 2 — ambiguous', x1['verdict'] == 'front_cues' and x2['verdict'] == 'ambiguous')

print('all ok' if not bad else f'FAILED: {bad}')
sys.exit(1 if bad else 0)
