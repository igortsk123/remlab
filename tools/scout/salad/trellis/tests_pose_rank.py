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

def fam(az, score, bf2, ch, floor_ok=True):
    return {'cam': {'az': az, 'el': 5.0}, 'floor_ok': floor_ok, 'score': score, 'bf': {'2': bf2}, 'chamfer_px': ch}


check('правила: choose — пороги в одном месте', all(k in R['choose'] for k in ('flip_tol', 'bf_gain', 'chamfer_tol_px')))
c = PR.choose([fam(10, 0.90, 0.50, 3.0), fam(190, 0.90, 0.90, 1.0)], R)
check('choose: зеркальное семейство (yaw+180°) не выбирается, даже если у него Boundary-F и Chamfer лучше', c['index'] == 0 and c['changed'] is False, c['why'])
c = PR.choose([fam(10, 0.90, 0.50, 3.0), fam(100, 0.90, 0.70, 2.5)], R)
check('choose: не зеркальное семейство с заметным выигрышем Boundary-F и без ухудшения Chamfer — выбирается', c['index'] == 1 and c['changed'] is True, c['why'])
c = PR.choose([fam(10, 0.90, 0.50, 3.0), fam(100, 0.90, 0.52, 2.5)], R)
check('choose: выигрыш Boundary-F меньше bf_gain — остаётся боевая', c['index'] == 0 and c['changed'] is False, c['why'])
c = PR.choose([fam(10, 0.90, 0.50, 3.0), fam(100, 0.90, 0.80, 19.0)], R)
check('choose: Boundary-F лучше, но Chamfer резко хуже — остаётся боевая', c['index'] == 0 and c['changed'] is False, c['why'])
c = PR.choose([fam(10, 0.90, 0.50, 3.0, floor_ok=False), fam(190, 0.90, 0.60, 3.0)], R)
check('choose: боевая под полом, единственная над полом — зеркальная → остаётся боевая (перёд/зад решает orientation)', c['index'] == 0 and c['changed'] is False, c['why'])

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
check('pose_fit: --rank-pick по умолчанию выключен (боевая поза не меняется без флага)', inspect.signature(PF.fit_pose).parameters['rank_pick'].default is False)

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

# ---------- DINOv2: чистое ядро (без torch) ----------
import pose_dino as PD  # noqa: E402

im = np.zeros((200, 300, 3), np.uint8) + 50
mk = np.zeros((200, 300), bool)
mk[40:120, 100:260] = True
cr = PD.crop_masked(im, mk, size=64)
check('dino.crop_masked: квадрат нужного размера, маска предмета в центре, вне маски — нейтральный фон', cr.shape == (64, 64, 3) and abs(int(cr[32, 32, 0]) - 50) <= 1 and int(cr[0, 0, 0]) == 235, str(cr.shape))
check('dino.crop_masked: пустая маска → None', PD.crop_masked(im, np.zeros((200, 300), bool)) is None)
mk2 = np.zeros((200, 300), bool)
mk2[0:60, 0:80] = True
check('dino.crop_masked: предмет у края кадра — не падает, размер тот же', PD.crop_masked(im, mk2, size=64).shape == (64, 64, 3))
px = PD.prep(np.full((28, 28, 3), 255, np.uint8))
check('dino.prep: форма [1, 3, H, W], белый → (1 − среднее) / σ по каналам (нормализация ImageNet)', px.shape == (1, 3, 28, 28) and abs(float(px[0, 0, 0, 0]) - (1 - 0.485) / 0.229) < 1e-4 and px.dtype == np.float32)
va = np.array([1.0, 0.0, 0.0])
check('dino.cosine: одинаковые = 1, ортогональные = 0, противоположные = −1', abs(PD.cosine(va, va) - 1) < 1e-9 and abs(PD.cosine(va, np.array([0, 1.0, 0]))) < 1e-9 and abs(PD.cosine(va, -va) + 1) < 1e-9)
check('dino.dino_vote: выбранная ближе к фото на ≥ gap — «за»; дальше — «против»; иначе «—»; нет данных — «нет»',
      (PD.dino_vote(0.80, 0.70, 0.03), PD.dino_vote(0.70, 0.80, 0.03), PD.dino_vote(0.80, 0.79, 0.03), PD.dino_vote(None, 0.5, 0.03)) == ('за', 'против', '—', 'нет'))

check('правила: dino.gap в одном месте', R['dino']['gap'] > 0)
vd = PR.orientation_votes(0.0, cues(2.0, 0.30), cues(5.0, 0.10), R, dino={'pick': 0.8, 'flip': 0.5})
check('голоса: DINO у выбранной ближе к фото на ≥ gap → «за», разрыв в gap.dino', vd['dino'] == 'за' and abs(vd['gap']['dino'] - 0.3) < 1e-9)
check('голоса: DINO без данных → «нет», без аргумента то же', PR.orientation_votes(0.0, cues(2, .3), cues(2, .3), R)['dino'] == 'нет' and PR.orientation_votes(0.0, cues(2, .3), cues(2, .3), R, dino={'pick': None, 'flip': 0.5})['dino'] == 'нет')
x = PR.orientation_verdict(PR.orientation_votes(0.0, cues(2.0, 0.10), cues(2.1, 0.10), R, dino={'pick': 0.8, 'flip': 0.5}), None, R)
check('итог: ничья, DINO «за» один → ambiguous (нужно 2 голоса), метка содержит голос DINO', x['verdict'] == 'ambiguous' and x['votes']['dino'] == 'за')
x = PR.orientation_verdict(PR.orientation_votes(0.0, cues(2.0, 0.30), cues(2.1, 0.10), R, dino={'pick': 0.8, 'flip': 0.5}), None, R)
check('итог: ничья, геометрия и DINO «за» → front_cues', x['verdict'] == 'front_cues')
x = PR.orientation_verdict(PR.orientation_votes(0.05, cues(2.0, 0.30), cues(2.1, 0.30), R, dino={'pick': 0.4, 'flip': 0.8}), None, R)
check('итог: силуэт «за», но DINO «против» → ambiguous (спор)', x['verdict'] == 'ambiguous')


# ---- разворот позы на 180° (T-20261123-43): чистое решение, триггер, рельеф, перехват в fit-цепочке на заглушках ----
FR = R['flip_pick']
check('правила: flip_pick — все ключи, пороги положительные, порог триггера не здесь (camera-check.json: edge_ref)', all(k in FR for k in ('enabled', 'sil_drop_max', 'sil_gain', 'edge_gain', 'need_votes', 'relief_rel', 'relief_abs')) and 'edge_ref' not in FR and FR['need_votes'] >= 2)
check('триггер: согласие кромок ниже порога → да; не ниже / нет кромок / нет данных → нет', PR.flip_trigger({'agree': 0.3}, 0.5) and not PR.flip_trigger({'agree': 0.5}, 0.5) and not PR.flip_trigger({'agree': 0.1, 'no_edges': True}, 0.5) and not PR.flip_trigger(None, 0.5))


def sg(score, edge, color, relief):
    return {'score': score, 'edge': edge, 'color': color, 'relief': relief}


pick = sg(0.89, 0.26, 6.0, 1.0)
d = PR.flip_decision(pick, sg(0.93, 0.59, 2.0, 3.0), R)
check('разворот: силуэт не хуже, кромки+цвет+рельеф «за» → apply', d['apply'] and d['votes']['edge'] == 'за' and d['votes']['color'] == 'за' and d['votes']['relief'] == 'за', str(d['votes']))
d = PR.flip_decision(pick, sg(0.88, 0.40, 2.0, 1.0), R)
check('разворот: два голоса (кромки, цвет), рельеф «—» → apply (нужно need_votes)', d['apply'] and d['votes']['relief'] == '—')
d = PR.flip_decision(pick, sg(0.89, 0.40, 6.1, 1.0), R)
check('без разворота: один голос (кромки) из двух нужных → оставляем', not d['apply'] and 'голосов' in d['why'])
d = PR.flip_decision(pick, sg(0.89 - FR['sil_drop_max'] - 0.02, 0.9, 1.0, 5.0), R)
check('без разворота: силуэт перевёрнутой сильно хуже, хоть все сигналы «за» → оставляем (голос силуэта «против»)', not d['apply'] and d['votes']['sil'] == 'против')
d = PR.flip_decision(pick, sg(0.89, 0.45, 2.0, 0.2), R)
check('без разворота: есть голос «против» (рельеф у выбранной сильнее) → оставляем при двух «за»', not d['apply'] and d['votes']['relief'] == 'против')
d = PR.flip_decision(sg(0.80, 0.30, 4.0, 1.0), sg(0.90, 0.30, 4.0, 2.0), R)
check('голос силуэта: перевёрнутая лучше на sil_gain и рельеф «за» → apply', d['apply'] and d['votes']['sil'] == 'за')
d = PR.flip_decision(sg(0.9, None, None, None), sg(0.9, None, None, None), R)
check('нет данных ни у одного сигнала → оставляем, голоса «нет»', not d['apply'] and set(d['votes'].values()) <= {'нет', '—'})
sym = PR.flip_decision(sg(0.90, 0.30, 4.0, 2.0), sg(0.90, 0.31, 4.1, 2.05), R)
check('симметричный предмет (всё почти равно): не разворачиваем', not sym['apply'])

# рельеф: ровная плоскость → ~0, шум/рёбра → больше; мало пикселей → None
flat = np.full((64, 64), 120.0)
ribs = flat.copy()
ribs[:, ::6] = 40.0
mk = np.ones((64, 64), bool)
check('рельеф: плоскость ~0, рёбра сильнее, пустая маска → None', PR.relief_strength(flat, mk) == 0.0 and PR.relief_strength(ribs, mk) > 5 and PR.relief_strength(flat, np.zeros((64, 64), bool)) is None)

# flip_pick на заглушке PF: триггер не сработал → перевыбор не считается (дорогая часть не вызывается); сработал и решено «да» → поза заменена, до-поза сохранена
class Boom:
    def __getattr__(self, k):
        raise AssertionError('дорогая часть вызвана: ' + k)


pk = {'cam': {'az': 161.0, 'el': 4.0, 'd': 10.0}, 'score': 0.89, 'iou': 0.97, 'edge': {'agree': 0.7, 'no_edges': False}}
out, info = PR.flip_pick(Boom(), {}, pk, None, None, 64, None, None, {}, None, 0.5, R=R)
check('flip_pick: кромки ≥ edge_ref → поза не тронута, дорогая часть не вызвана', out is pk and info['triggered'] is False and info['applied'] is False)
off = {**R, 'flip_pick': {**FR, 'enabled': False}}
pk2 = {**pk, 'edge': {'agree': 0.1, 'no_edges': False}}
out, info = PR.flip_pick(Boom(), {}, pk2, None, None, 64, None, None, {}, None, 0.5, R=off)
check('flip_pick: выключено правилом → поза не тронута', out is pk2 and info['enabled'] is False and not info['triggered'])

_orig = (PR.flip_hypothesis, PR.flip_signals)
cams = {'a': {'az': 161.0, 'el': 4.0, 'd': 10.0}, 'b': {'az': 342.0, 'el': 4.5, 'd': 10.1}}
PR.flip_hypothesis = lambda PF_, geo, cam, *a, **k: {'cam': cams['b'], 'iou': 0.98, 'iou_sil': 0.96, 'edge': {'agree': 0.59}, 'steps': 5}
sigs = {id(cams['a']): sg(0.89, 0.26, 6.0, 1.0), id(cams['b']): sg(0.93, 0.59, 2.0, 3.0)}
PR.flip_signals = lambda PF_, geo, cam, *a, **k: sigs[id(cam)]
try:
    pk3 = {'cam': cams['a'], 'score': 0.89, 'iou': 0.97, 'edge': {'agree': 0.26, 'no_edges': False}}
    out, info = PR.flip_pick(object(), {}, pk3, None, None, 64, None, None, {}, None, 0.5, log=lambda *a: None, R=R)
    check('flip_pick: низкие кромки, сигналы «за» → поза заменена на az+180, до-поза и метка сохранены, камера из той же pose.json-структуры', info['applied'] and out['cam'] is cams['b'] and out['flip_pick'] is True and out['cam_before_flip'] is cams['a'] and out['edge']['agree'] == 0.59 and out['score'] == 0.93)
    sigs[id(cams['b'])] = sg(0.89, 0.27, 6.0, 1.0)
    out, info = PR.flip_pick(object(), {}, pk3, None, None, 64, None, None, {}, None, 0.5, log=lambda *a: None, R=R)
    check('flip_pick: сигналы без разницы → камера не тронута, но триггер и голоса записаны для pose.json', out is pk3 and info['triggered'] and not info['applied'] and 'votes' in info)
finally:
    PR.flip_hypothesis, PR.flip_signals = _orig

src_pr = inspect.getsource(PR.flip_pick) + inspect.getsource(PR.flip_decision) + inspect.getsource(PR.flip_hypothesis)
import re  # noqa: E402
check('код разворота: ID товаров и числа порогов не вшиты (пороги — в rules/pose-rank.json, edge_ref — из camera-check.json)', not re.search(r'\d{8,}', src_pr) and 'edge_ref' in inspect.signature(PR.flip_pick).parameters)

# ---- П1.158 (T-88): «перёд всегда» для типов с перёдом, решение голосами; флаг по умолчанию ВЫКЛ ----
FA = R['flip_always']
check('правила: flip_always выключено по умолчанию, роли заданы, нужно 2 голоса', FA['enabled'] is False and FA['need_votes'] == 2 and 'шкаф' in FA['roles_corpus'] and 'диван' in FA['roles_soft'] and 0 < FA['mesh_front_cam_deg'] < 90)
on = {**R, 'flip_always': {**FA, 'enabled': True}}
check('front_kind: выкл → None у любой роли; вкл → корпусная/мягкая/симметричная (стол, ваза — None), кресло-кровать — мягкая',
      PR.front_kind('шкаф', R) is None and PR.front_kind('диван', R) is None and PR.front_kind('шкаф', on) == 'corpus' and PR.front_kind('Комод', on) == 'corpus' and PR.front_kind('тв-тумба', on) == 'corpus'
      and PR.front_kind('диван', on) == 'soft' and PR.front_kind('кресло-кровать', on) == 'soft' and PR.front_kind('стул', on) == 'soft'
      and PR.front_kind('стол обеденный', on) is None and PR.front_kind('ваза', on) is None and PR.front_kind('', on) is None and PR.front_kind(None, on) is None)
os.environ['POSE_FLIP_ALWAYS'] = '1'
try:
    check('front_kind: env POSE_FLIP_ALWAYS=1 включает при выкл правиле', PR.front_kind('шкаф', R) == 'corpus')
    os.environ['POSE_FLIP_ALWAYS'] = '0'
    check('front_kind: env 0 выключает при вкл правиле', PR.front_kind('шкаф', on) is None)
finally:
    os.environ.pop('POSE_FLIP_ALWAYS', None)
# флаг выкл + роль корпусной → как раньше: кромки выше порога — дорогая часть не вызвана
out, info = PR.flip_pick(Boom(), {}, pk, None, None, 64, None, None, {}, None, 0.5, R=R, role='шкаф')
check('flip_pick: флаг выкл, роль есть → как раньше (поза не тронута, не вызвано)', out is pk and info['triggered'] is False and 'always' not in info)
out, info = PR.flip_pick(Boom(), {}, pk, None, None, 64, None, None, {}, None, 0.5, R=on, role='стол обеденный')
check('flip_pick: флаг вкл, симметричный тип → как раньше (поза не тронута, не вызвано)', out is pk and info['triggered'] is False and 'always' not in info)

_orig2 = (PR.flip_hypothesis, PR.flip_signals, PR.front_form_votes)
_orig_iou = PR._pose_iou
IOU = {}
PR._pose_iou = lambda PF_, Pc, cam, Mp, n: IOU.get(id(cam), 0.95)
PR.flip_hypothesis = lambda PF_, geo, cam, *a, **k: {'cam': cams['b'], 'iou': 0.98, 'iou_sil': 0.96, 'edge': {'agree': 0.6}, 'steps': 5}
PR.flip_signals = lambda PF_, geo, cam, *a, **k: sigs[id(cam)]
try:
    sigs[id(cams['a'])] = sg(0.89, 0.70, 6.0, 1.0)                    # кромки выбранной позы высокие (0,70) — старый триггер молчит
    sigs[id(cams['b'])] = sg(0.90, 0.83, 2.0, 1.2)                    # перевёрнутая: кромки +0,13, цвет лучше; рельеф затенения ~
    pkA = {'cam': cams['a'], 'score': 0.89, 'iou': 0.97, 'edge': {'agree': 0.7, 'no_edges': False}}

    def fp(pk, role):
        return PR.flip_pick(object(), {}, pk, None, None, 64, None, None, {}, None, 0.5, log=lambda *a: None, R=on, role=role)

    # ── мягкие: голоса, как раньше ──
    PR.front_form_votes = lambda geo, cam, kind, R_: ({'relief_form': 'за'}, {'relief_form': {'verdict': 'opposite'}})
    out, info = fp(pkA, 'диван')
    check('«всегда» (мягкая): кромки высокие, голоса за (кромки, цвет, рельеф формы), против нет → развёрнут; вердикт и голоса в info.front', info['applied'] and out['cam'] is cams['b'] and out['cam_before_flip'] is cams['a'] and info['front']['verdict'] == 'развёрнут' and info['front']['pro'] >= 2 and info['front']['con'] == 0 and info['front']['kind'] == 'soft')
    PR.front_form_votes = lambda geo, cam, kind, R_: ({'relief_form': 'против'}, {})
    out, info = fp(pkA, 'кресло')
    check('«всегда» (мягкая): рельеф формы против → не разворачиваем (вето), «перёд не определён», поза не тронута', not info['applied'] and out is pkA and info['front']['verdict'] == 'перёд не определён' and info['front']['con'] == 1)
    sigs[id(cams['b'])] = sg(0.89, 0.70, 6.0, 1.0)                    # перевёрнутая не лучше
    PR.front_form_votes = lambda geo, cam, kind, R_: ({'relief_form': 'против', 'mesh_front': 'против'}, {})
    out, info = fp(pkA, 'диван')
    check('«всегда» (мягкая): голоса форме против, за нет → «перёд верный», поза не тронута', not info['applied'] and out is pkA and info['front']['verdict'] == 'перёд верный' and info['front']['con'] == 2)
    sigs[id(cams['b'])] = sg(0.95, 0.40, 2.0, 4.0)
    out, info = fp(pkA, 'диван')
    check('мягкая: кромки против остаются вето → не разворачиваем', not info['applied'] and info['front']['con'] >= 1)
    sigs[id(cams['b'])] = sg(0.89, 0.70, 9.0, 1.0)                    # один слабый голос «против» (цвет) — «перёд верный» нельзя
    PR.front_form_votes = lambda geo, cam, kind, R_: ({'relief_form': '—'}, {})
    out, info = fp(pkA, 'стул')
    check('«всегда» (мягкая): один голос «против» (цвет), за нет → «перёд не определён» (верный — только при ≥2 против)', not info['applied'] and info['front']['con'] == 1 and info['front']['verdict'] == 'перёд не определён')

    # ── корпусные: оси формы (az выбранной позы), силуэт, рельеф формы; цвет и кромки не входят ──
    cF = {'az': 340.4, 'el': 1.0, 'd': 3.0}                           # передняя половина (Висмар)
    cD1, cD2 = {'az': 90.0, 'el': 1.0, 'd': 3.0}, {'az': 250.0, 'el': 1.0, 'd': 3.0}
    for c in (cF, cD1, cD2):
        sigs[id(c)] = sg(0.89, 0.70, 6.0, 1.0)
    pkF, pkD1, pkD2 = ({'cam': c, 'score': 0.89, 'iou': 0.97, 'edge': {'agree': 0.7, 'no_edges': False}} for c in (cF, cD1, cD2))
    sigs[id(cams['b'])] = sg(0.90, 0.40, 9.0, 0.5)                    # силуэт перевёрнутой не хуже; кромки и цвет «против» (как у Теджонса, Рошаль): в решение не входят
    PR.front_form_votes = lambda geo, cam, kind, R_: ({'relief_form': 'за'}, {})
    out, info = fp(pkA, 'комод')
    check('корпусной (Теджонс): az 161 в задней половине, силуэт не хуже, рельеф формы «за», кромки и цвет «против» не входят → развёрнут', info['applied'] and out['cam'] is cams['b'] and info['front']['verdict'] == 'развёрнут' and info['front']['axes'] == 'зад' and info['front']['votes']['edge'] == 'против' and info['front']['votes']['color'] == 'против')
    PR.front_form_votes = lambda geo, cam, kind, R_: ({'relief_form': '—'}, {})
    out, info = fp(pkA, 'шкаф')
    check('корпусной (Рошаль): az 161, рельеф формы неоднозначен (не «camera») → развёрнут', info['applied'] and info['front']['verdict'] == 'развёрнут')
    PR.front_form_votes = lambda geo, cam, kind, R_: ({'relief_form': 'против'}, {})
    out, info = fp(pkA, 'шкаф')
    check('корпусной: az в задней половине, но рельеф формы уверенно «camera» → не разворачиваем, «перёд не определён»', not info['applied'] and out is pkA and info['front']['verdict'] == 'перёд не определён')
    PR.front_form_votes = lambda geo, cam, kind, R_: ({'relief_form': 'за'}, {})
    out, info = fp(pkF, 'шкаф')
    check('корпусной (Висмар): az 340 в передней половине, рельеф формы «за» (выдуманный зад) → не трогаем, «перёд верный по осям, рельеф спорит»', not info['applied'] and out is pkF and info['front']['verdict'] == 'перёд верный по осям, рельеф спорит' and info['front']['axes'] == 'перёд')
    PR.front_form_votes = lambda geo, cam, kind, R_: ({'relief_form': '—'}, {})
    out, info = fp(pkF, 'шкаф')
    check('корпусной: передняя половина, рельеф не спорит → «перёд верный», поза не тронута', not info['applied'] and info['front']['verdict'] == 'перёд верный')
    PR.front_form_votes = lambda geo, cam, kind, R_: ({'relief_form': 'за'}, {})
    ok = True
    for pk_ in (pkD1, pkD2):
        out, info = fp(pk_, 'тумба')
        ok = ok and not info['applied'] and out is pk_ and info['front']['verdict'] == 'перёд не определён' and info['front']['axes'] == 'мёртвая'
    check('корпусной: мёртвая зона (az 90, 250) → «перёд не определён», поза не тронута даже при рельефе «за»', ok)
    PR.front_form_votes = lambda geo, cam, kind, R_: ({'relief_form': '—'}, {})
    sigs[id(cams['b'])] = sg(0.89 - 0.149, 0.9, 1.0, 5.0)              # Трейвис: оценка с полосой низа хуже на 0,149, а IoU почти тот же (−0,004) → не запрет
    IOU[id(cams['a'])], IOU[id(cams['b'])] = 0.9407, 0.9365
    out, info = fp(pkA, 'тв-тумба')
    check('корпусной (Трейвис): оценка низа хуже на 0,149, IoU −0,004 → разворачиваем (полоса низа в проверку не входит); IoU в info.front', info['applied'] and info['front']['verdict'] == 'развёрнут' and info['front']['iou'] == {'pick': 0.9407, 'flip': 0.9365})
    IOU[id(cams['b'])] = 0.9407 - 0.05                                  # az в задней половине, но IoU перевёрнутой заметно хуже
    out, info = fp(pkA, 'шкаф')
    check('корпусной: IoU перевёрнутой хуже порога → не разворачиваем при любых осях', not info['applied'] and out is pkA and info['front']['verdict'] == 'перёд не определён')
    IOU.clear()
    check('front_axes: границы зон (60/120/240/300 — мёртвые; 59,9 и 300,1 — перёд; 120,1 и 239,9 — зад; az нет → «нет»)', [PR.front_axes(x, on) for x in (60.0, 120.0, 240.0, 300.0, 59.9, 300.1, 120.1, 239.9, 0.0, 359.0, 180.0)] == ['мёртвая', 'мёртвая', 'мёртвая', 'мёртвая', 'перёд', 'перёд', 'зад', 'зад', 'перёд', 'перёд', 'зад'] and PR.front_axes(None, on) == 'нет')
finally:
    PR._pose_iou = _orig_iou
    PR.flip_hypothesis, PR.flip_signals, PR.front_form_votes = _orig2

# гипотеза az+180° с несколькими стартами (корпусные): лучшая по pose_score, в заднюю половину не возвращаемся; без refit — один старт
class _FakePF:
    def __init__(self, table):
        self.table, self.calls = table, []

    def _blur(self, Mp, n):
        return Mp

    def nm_two_stage(self, Pc, Mp, Mpb, n, cam0):
        self.calls.append((round(cam0['az'], 1), round(cam0['el'], 1)))
        return dict(self.table(cam0)), 3

    def splat_mask(self, Pc, c, n):
        return c

    def pose_score(self, S, Mp):
        return {'score': S['q']}

    def iou(self, S, Mp):
        return 0.9

    def edge_score(self, *a, **k):
        return {'agree': 0.5}

    def refine_v2_rules(self):
        return None

    def refine_by_edges(self, geo, c, *a, **k):
        return c, {'agree': 0.5}

    def refine_ok(self, a, b):
        return True


def _tab(c0):                                                          # качество подгонки зависит от старта: старт az+15° и наклона +7 — лучший; старт az−15° уходит в заднюю половину (az 160) с самой высокой оценкой
    a = round(c0['az'] % 360.0, 1)
    if a == round((334.3 - 15) % 360.0, 1):
        return {'az': 160.0, 'el': 3.0, 'q': 0.99}
    q = 0.70 + (0.10 if abs(c0['el'] - 10.6) < 0.1 else 0.0) + (0.15 if abs(a - 349.3) < 0.1 else 0.0)
    return {'az': a, 'el': c0['el'], 'q': q}


fpf = _FakePF(_tab)
fh = PR.flip_hypothesis(fpf, {}, {'az': 154.3, 'el': 3.6}, None, np.zeros((4, 4)), 4, None, None, {}, None, log=lambda *a: None,
                        refit={'enabled': True, 'az_offsets_deg': [-15, 0, 15], 'el_offsets_deg': [0, 7], 'max_az_from_front_deg': 90})
check('flip_hypothesis (refit): 6 стартов вокруг az+180°, лучшая по pose_score, не уходящая в заднюю половину (старт с az 160 и оценкой 0,99 отброшен)', len(fpf.calls) == 6 and abs(fh['cam']['az'] - 349.3) < 0.2 and abs(fh['cam']['el'] - 10.6) < 0.2)
fpf = _FakePF(_tab)
fh = PR.flip_hypothesis(fpf, {}, {'az': 154.3, 'el': 3.6}, None, np.zeros((4, 4)), 4, None, None, {}, None, log=lambda *a: None)
check('flip_hypothesis без refit (мягкая мебель и прежний путь): один старт az+180°', len(fpf.calls) == 1 and fpf.calls[0][0] == round((154.3 + 180.0) % 360.0, 1))
check('правило flip_refit: выключено (замер на Трейвисе: не помогло), три азимута × два наклона, не дальше 90° от 0°', R['flip_always']['flip_refit']['enabled'] is False and len(R['flip_always']['flip_refit']['az_offsets_deg']) == 3 and R['flip_always']['flip_refit']['max_az_from_front_deg'] == 90)

# load_geoms: GLB без читаемого буфера (как сжатые meshopt GLB сайта) → понятная ValueError, а не голый IndexError
def _glb_no_buffer(path):
    import json as _j, struct as _s
    j = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
         'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1}]}],
         'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3', 'min': [0, 0, 0], 'max': [1, 1, 0]}, {'bufferView': 1, 'componentType': 5123, 'count': 3, 'type': 'SCALAR'}],
         'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': 36}, {'buffer': 0, 'byteOffset': 36, 'byteLength': 6}], 'buffers': [{'byteLength': 42}]}
    js = _j.dumps(j).encode()
    js += b' ' * ((4 - len(js) % 4) % 4)
    with open(path, 'wb') as f:
        f.write(_s.pack('<4sII', b'glTF', 2, 12 + 8 + len(js)))
        f.write(_s.pack('<II', len(js), 0x4E4F534A) + js)


try:
    import tempfile as _tf
    import tex_coverage as _TC
    _p = os.path.join(_tf.mkdtemp(prefix='t88_glb_'), 'nobuf.glb')
    _glb_no_buffer(_p)
    try:
        _TC.load_geoms(_p)
        _ok = False
    except ValueError as _e:
        _ok = 'GLB не читается' in str(_e) and 'nobuf.glb' in str(_e)
    except Exception:                                                  # noqa: BLE001
        _ok = False
    check('load_geoms: GLB без читаемого буфера → ValueError с понятным текстом (не голый IndexError)', _ok)
except ImportError:
    check('load_geoms: trimesh/tex_coverage недоступны — тест пропущен', True)

# голоса формы: mesh_front — перёд рядом с камерой → против, далеко → за, нет уверенности → нет; на синтетическом «диване» (спинка у −Z, перёд +Z)
def _sofa():
    def box(x0, x1, y0, y1, z0, z1):
        V = np.array([[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)], float)
        Fq = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
        return V, np.array(Fq, int)
    parts = [box(-0.5, 0.5, 0.0, 0.15, -0.3, 0.3), box(-0.5, 0.5, 0.15, 0.4, -0.3, 0.3), box(-0.5, 0.5, 0.4, 0.9, -0.3, -0.2)]     # низ, сиденье, спинка у −Z
    Vs, Fs, o = [], [], 0
    for V, Fq in parts:
        Vs.append(V)
        Fs.append(Fq + o)
        o += len(V)
    return {'V': np.vstack(Vs), 'F': np.vstack(Fs)}


try:
    sofa = _sofa()
    v_front, inf = PR.front_form_votes(sofa, {'az': 10.0, 'el': 5.0}, 'soft', on)
    v_back, _i = PR.front_form_votes(sofa, {'az': 190.0, 'el': 5.0}, 'soft', on)
    check('front_form_votes: диван, камера у перёда → mesh_front «против», камера сзади → «за»; рельеф формы не падает', inf['mesh_front'].get('status') in ('confident', 'ambiguous', 'no_seat') and (inf['mesh_front'].get('status') != 'confident' or (v_front['mesh_front'] == 'против' and v_back['mesh_front'] == 'за')) and 'relief_form' in v_front)
except Exception as e:                                                # noqa: BLE001
    check(f'front_form_votes на синтетическом диване упал: {type(e).__name__}: {e}', False)

src_fa = inspect.getsource(PR.front_kind) + inspect.getsource(PR.front_form_votes) + inspect.getsource(PR.front_decision) + inspect.getsource(PR._flip_always)
check('код «перёд всегда»: ID товаров не вшиты', not re.search(r'\d{8,}', src_fa))

# T-20261126-99/3: камера 04 корпусных — только в передней половине осей (front_half_pick)
import copy
Rfp = copy.deepcopy(on)
Rfp['flip_always']['corpus_axes']['front_pick'] = {'enabled': True, 'iou_gap_max': 0.03}
_c = lambda az, iou, sc: {'cam': {'az': az, 'el': 5.0}, 'iou': iou, 'score': sc}                    # noqa: E731
_pk = _c(160.0, 0.9431, 0.9456)
_o, _i = PR.front_half_pick(_pk, [_c(340.8, 0.9442, 0.9409)], {'starts': []}, Rfp)
check('front_half_pick: боевая сзади, передняя не хуже → переставлена, вердикт «перёд по осям», исходная поза в cam_before_front_pick', _o['cam']['az'] == 340.8 and _o.get('front_pick') and _o['cam_before_front_pick']['az'] == 160.0 and not _i['stop'] and _i['az_after'] == 340.8)
_o, _i = PR.front_half_pick(_c(340.0, 0.98, 0.95), [_c(160.0, 0.97, 0.93)], {'starts': []}, Rfp)
check('front_half_pick: боевая уже в передней половине → «согласны», поза не тронута', _o['cam']['az'] == 340.0 and _i['verdict'] == 'согласны' and 'front_pick' not in _o)
_o, _i = PR.front_half_pick(_pk, [_c(340.8, 0.9431 - 0.05, 0.90)], {'starts': []}, Rfp)
check('front_half_pick: передняя хуже по IoU больше порога → поза остаётся, «СТОП: оси ≠ поза»', _o is _pk and _i['stop'] and _i['verdict'].startswith('СТОП') and _i['iou_gap'] > 0.03)
_o, _i = PR.front_half_pick(_pk, [_c(170.0, 0.94, 0.9)], {'starts': []}, Rfp)
check('front_half_pick: кандидатов в передней половине нет → «СТОП», поза не тронута', _o is _pk and _i['stop'] and _i['n_front'] == 0)
_o, _i = PR.front_half_pick(_c(90.0, 0.94, 0.9), [_c(10.0, 0.94, 0.9)], {'starts': []}, Rfp)
check('front_half_pick: боевая в мёртвой зоне (90°) ищет переднюю как при «зад»', _o['cam']['az'] == 10.0 and _i['axes_before'] == 'мёртвая')
_o, _i = PR.front_half_pick(_pk, [_c(340.8, 0.9442, 0.9409), _c(20.0, 0.95, 0.95)], {'starts': [_c(330.0, 0.9, 0.5)]}, Rfp)
check('front_half_pick: из передней половины берётся лучшая по оценке (пул = боевая + кандидаты + старты)', _o['cam']['az'] == 20.0 and _i['n_pool'] == 4)
_o, _i = PR.front_half_pick(_pk, [_c(340.8, 0.9442, 0.9409)], {'starts': []}, on)
check('front_half_pick: флаг выкл (по умолчанию) — поза не тронута, info {enabled: False}', _o is _pk and _i == {'enabled': False})
_o, _i = PR.front_half_pick(_pk, [_c(340.8, 0.9442, 0.9409)], {'starts': []}, on, '1')
check('front_half_pick: env POSE_FRONT_PICK=1 включает при выкл. правиле; env 0 выключает при вкл. правиле', _o['cam']['az'] == 340.8 and PR.front_half_pick(_pk, [_c(340.8, 0.9442, 0.9409)], {'starts': []}, Rfp, '0')[1] == {'enabled': False})
check('is_corpus_role: комод/шкаф да, диван/стол нет, пусто нет (от flip_always.enabled не зависит)', PR.is_corpus_role('Комод', on) and PR.is_corpus_role('шкаф-купе', on) and not PR.is_corpus_role('диван', on) and not PR.is_corpus_role('', on) and not PR.is_corpus_role(None, on))
check('front_half_pick: правило в pose-rank.json выкл. по умолчанию', PR.rules()['flip_always']['corpus_axes']['front_pick']['enabled'] is False and 'front_half_pick' in inspect.getsource(PR) and not re.search(r'\d{8,}', inspect.getsource(PR.front_half_pick)))

# T-99/5: v2 — окно «каталог слева» az 300…360 ∪ 0…10 (зеркало 3/4: кандидат справа при фото слева не берётся)
Rw = copy.deepcopy(Rfp)
Rw['flip_always']['corpus_axes']['front_pick']['az_window_deg'] = [300, 10]
_pm = _c(137.5, 0.9320, 0.7815)                                                                      # Модерн: боевая сзади
_o, _i = PR.front_half_pick(_pm, [_c(15.9, 0.9584, 0.8525), _c(321.8, 0.9263, 0.7924)], {'starts': []}, Rw)
check('v2 зеркало: боевая сзади, справа (az 16, оценка выше) и слева (az 322) → берём левый', _o['cam']['az'] == 321.8 and _i['az_after'] == 321.8 and not _i['stop'] and _i['window'] == [300, 10])
_o, _i = PR.front_half_pick(_pm, [_c(15.9, 0.9584, 0.8525)], {'starts': []}, Rw)
check('v2 зеркало: только справа (az 16) → СТОП, поза не тронута (v1 взяла бы 16)', _o is _pm and _i['stop'] and _i['n_front'] == 0 and PR.front_half_pick(_pm, [_c(15.9, 0.9584, 0.8525)], {'starts': []}, Rfp)[0]['cam']['az'] == 15.9)
_o, _i = PR.front_half_pick(_c(15.9, 0.9584, 0.8525), [_c(321.8, 0.945, 0.7924)], {'starts': []}, Rw)
check('v2 зеркало: боевая справа-спереди (az 16, вне окна) при кандидате слева → переставлена на левый', _o['cam']['az'] == 321.8 and not _i['stop'])
_o, _i = PR.front_half_pick(_c(340.0, 0.98, 0.95), [_c(15.9, 0.99, 0.99)], {'starts': []}, Rw)
check('v2: боевая в окне (340) → «согласны», лучший справа не берётся', _o['cam']['az'] == 340.0 and _i['verdict'] == 'согласны')
_o, _i = PR.front_half_pick(_c(5.0, 0.98, 0.95), [], {'starts': []}, Rw)
check('v2: граница окна — az 5 и 359 «согласны», az 10,5 и 299 вне окна', _i['verdict'] == 'согласны' and PR.front_half_pick(_c(359.0, 0.9, 0.9), [], {'starts': []}, Rw)[1]['verdict'] == 'согласны' and PR.front_half_pick(_c(10.5, 0.9, 0.9), [], {'starts': []}, Rw)[1]['stop'] and PR.front_half_pick(_c(299.0, 0.9, 0.9), [], {'starts': []}, Rw)[1]['stop'])
check('v2: в pose-rank.json окно [300, 10], флаг выкл.', PR.rules()['flip_always']['corpus_axes']['front_pick']['az_window_deg'] == [300, 10] and PR.rules()['flip_always']['corpus_axes']['front_pick']['enabled'] is False)

print('all ok' if not bad else f'FAILED: {bad}')
sys.exit(1 if bad else 0)
