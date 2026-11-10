"""Кровать боком (T-20261110-20/3): свидетель изголовья в каскаде, сторож решений, блок в привязке, подбор спальни у окна.
Без сети, базы и моделей: вершины, решатель и окна подменены синтетикой.

  1) `orient_worker.decide`: изголовье у +Z канона → `orienter+headboard_agree` без VLM; изголовье сбоку → матрица доворачивается
     (`headboard_fix`), yaw и кватернион пересчитаны, изголовье в новом каноне у +Z; боком без ясного торца → `review_pending`
     `headboard_sideways`.
  2) `yaw_guard` не превращает исправление по геометрии в `review_pending` (иначе прод держал бы кровать боком).
     Изголовье с другого торца (180°) форма не подтверждает → `review_pending` `headboard_flip`, матрица прежняя.
  3) `bed_verdict`: решение человека не трогаем (расхождение — `human_conflict`), «VLM не уверен» с согласием — `promoted`,
     прочие причины разбора — `agree_kept`; разворот 180° у авто — `blocked`.
  4) `room_bindings.orient_only`: `orientation_mismatch` режим orient не пускает, прочие `orientation_*` — как раньше.
  5) `trial_bedroom.unique_sizes` — одна проба на размер; `window_low_beds` — после неудачи высокой рамы у окна берёт низкие,
     если та же рама ниже подоконника встаёт, и ничего не меняет, если окна нет или мешает не окно.
    ~/venvs/scout/bin/python tools/scout/tests/test_bed_headboard.py"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_bed_headboard')

import numpy as np  # noqa: E402

import bed_headboard as HB  # noqa: E402
import orient_worker as W  # noqa: E402
import room_bindings as RB  # noqa: E402

fails = 0


def check(name, cond, extra=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
    fails += 0 if cond else 1


# ---------------------------------------------------------------- 1) каскад
BED = HB._bed('+z')                                  # изголовье у +Z
TAHTA = np.vstack([BED, HB._box(0, 0.1, 0, 0.95, 0, 2.1, 10)])
UP = {'R': [[-1, 0, 0], [0, 1, 0], [0, 0, -1]], 'quat_wxyz': [0.0, 0.0, 1.0, 0.0], 'flip_prob': 0.6, 'pset_size': 1}
W.role_of = lambda sku: ('кровать', 'Кровать Тест', '')
cloud = {}
# вершины «сырого» меша такие, что в каноне решения (R·v) получается заданное облако: v = Rᵀ·c
W.HB.canonical_vertices = lambda glb, R: cloud['c']
vlm_called = []
W.vlm_side = lambda parts, role: vlm_called.append(1) or ('перед', 0.9)
W.canonical_parts = lambda glb, R: {}
import tempfile  # noqa: E402
GLB = os.path.join(tempfile.mkdtemp(prefix='bed-hb-'), 'model.glb')   # decide читает файл ради sha — содержимое не важно
open(GLB, 'wb').write(b'glTF-fake')

cloud['c'] = BED
r = W.decide('x:1', GLB, UP, use_vlm=True)
check('1) изголовье у +Z → auto_resolved orienter+headboard_agree, VLM не звали',
      r['status'] == 'auto_resolved' and r['source'] == 'orienter+headboard_agree' and not vlm_called, f"{r['status']} {r['source']}")
check('1) поворот каскада не тронут', r['R'] == UP['R'] and r['legacy_front_yaw'] == W.front_yaw_from_R(UP['R'])[0])

for deg in (90, 270):
    cloud['c'] = TAHTA @ np.asarray(HB.ry(deg)).T     # тахта боком в каноне решения
    r = W.decide('x:2', GLB, UP, use_vlm=True)
    fixed = TAHTA @ np.asarray(HB.ry(deg)).T @ np.asarray(HB.ry(r['evidence']['headboard'].get('fix_deg') or 0)).T
    check(f'1) тахта боком ({deg}°) → headboard_fix, доворот {(360 - deg) % 360}°',
          r['source'] == 'headboard_fix' and r['status'] == 'auto_resolved' and r['evidence']['headboard']['fix_deg'] == (360 - deg) % 360,
          f"{r['source']} {r['evidence'].get('headboard')}")
    check(f'1)   после доворота изголовье у +Z', HB.infer_headboard(fixed).get('head_side') == 0)
    want = HB.rotate_R(UP['R'], (360 - deg) % 360)
    check(f'1)   R = ry·R, кватернион и yaw пересчитаны, прежнее — в evidence',
          r['R'] == want and r['raw_to_canonical_quat_wxyz'] == HB.quat_wxyz(want)
          and r['legacy_front_yaw'] == W.front_yaw_from_R(want)[0] and r['evidence']['headboard']['prev']['yaw'] == 0,
          f"yaw={r['legacy_front_yaw']} prev={r['evidence']['headboard'].get('prev')}")

cloud['c'] = HB._bed('+z', foot_h=0.95) @ np.asarray(HB.ry(90)).T
r = W.decide('x:3', GLB, UP, use_vlm=True)
check('1) боком, торцы одинаковые → review_pending headboard_sideways', r['status'] == 'review_pending' and r['source'] == 'headboard_sideways')

cloud['c'] = BED @ np.asarray(HB.ry(180)).T                  # изголовье у −Z: форма разворот не подтверждает
r = W.decide('x:3b', GLB, UP, use_vlm=True)
check('1) изголовье с другого торца (180°) → не доворот, review_pending headboard_flip, R прежняя',
      r['status'] == 'review_pending' and r['source'] == 'headboard_flip' and r['R'] == UP['R'], f"{r['status']} {r['source']}")

vlm_called.clear()
cloud['c'] = HB._box(0, 1.3, 0, 0.4, 0, 2.1, 6)
r = W.decide('x:4', GLB, UP, use_vlm=True)
check('1) подиум без спинки → свидетель не уверен, дальше VLM как раньше', r['source'] == 'orienter+vlm_agree' and vlm_called)

# ---------------------------------------------------------------- 2) сторож поворота
cloud['c'] = TAHTA @ np.asarray(HB.ry(90)).T
r = W.decide('x:5', GLB, UP, use_vlm=True)
pub = {'x_5': {'yaw': 0.0, 'orient_sig': 'a|0123456789abcdef|p3'}}
g = W.yaw_guard(r, 'x:5|0123456789abcdef|orient-v1', pub, None)
check('2) yaw_guard пропускает исправление по изголовью (прод получит верный поворот)', g['status'] == 'auto_resolved', g.get('source'))
vlm = {**r, 'source': 'orienter+vlm_agree', 'evidence': {}}
g = W.yaw_guard(vlm, 'x:5|0123456789abcdef|orient-v1', pub, None)
check('2) смена от VLM — по-прежнему review_pending', g['status'] == 'review_pending' and g['source'] == 'yaw_change_guard')
agree = {**r, 'source': 'orienter+headboard_agree'}
g = W.yaw_guard(agree, 'x:5|0123456789abcdef|orient-v1', pub, None)
check('2) согласие изголовья, меняющее опубликованный поворот, сторожа не минует', g['source'] == 'yaw_change_guard')

# ---------------------------------------------------------------- 3) решения сторожа
side = HB.infer_headboard(TAHTA @ np.asarray(HB.ry(90)).T)
ok = HB.infer_headboard(BED)
base = {'R': UP['R'], 'legacy_front_yaw': 0, 'status': 'auto_resolved', 'source': 'orienter+vlm_agree', 'evidence': {'headboard': {}}}
check('3) человек решил, геометрия против → human_conflict, без записи', W.bed_verdict('human_resolved', dict(base), side) == ('human_conflict', None))
check('3) человек решил, геометрия согласна → ok', W.bed_verdict('human_resolved', dict(base), ok) == ('ok', None))
a, n = W.bed_verdict('auto_resolved', json.loads(json.dumps(base)), side)
check('3) авто боком → fixed', a == 'fixed' and n['source'] == 'headboard_fix')
check('3) авто верно → ok, без записи', W.bed_verdict('auto_resolved', dict(base), ok) == ('ok', None))
a, n = W.bed_verdict('review_pending', {**base, 'source': 'vlm_unsure'}, ok)
check('3) ждёт разбора, геометрия уверенно согласна → promoted (auto_resolved)', a == 'promoted' and n['status'] == 'auto_resolved')
check('3) ждёт разбора по другой причине (сторож поворота) → agree_kept, без записи',
      W.bed_verdict('review_pending', {**base, 'source': 'yaw_change_guard'}, ok) == ('agree_kept', None))
flip = HB.infer_headboard(BED @ np.asarray(HB.ry(180)).T)
a, n = W.bed_verdict('auto_resolved', json.loads(json.dumps(base)), flip)
check('3) авто, изголовье с другого торца → blocked (headboard_flip)', a == 'blocked' and n['source'] == 'headboard_flip')
check('3) свидетель не уверен → unsure, решение каскада остаётся',
      W.bed_verdict('auto_resolved', dict(base), HB.infer_headboard(HB._box(0, 1.3, 0, 0.4, 0, 2.1, 6)))[0] == 'unsure')

# ---------------------------------------------------------------- 4) привязка
check('4) orientation_mismatch — не «только разворот»: режим orient не пускает', not RB.orient_only(['orientation_mismatch']))
check('4) orientation_review_pending / rep:orientation_missing — как раньше', RB.orient_only(['orientation_review_pending'])
      and RB.orient_only(['rep:orientation_missing']) and not RB.orient_only(['orientation_missing', 'orientation_mismatch']))

# ---------------------------------------------------------------- 5) подбор спальни у окна
import trial_bedroom as TB  # noqa: E402

beds = [{'sid': 'a1', 'w': 130, 'd': 212, 'h': 91}, {'sid': 'a2', 'w': 130, 'd': 212, 'h': 91}, {'sid': 'b', 'w': 126, 'd': 210, 'h': 92},
        {'sid': 'c', 'w': 130, 'd': 210, 'h': 81}, {'sid': 'd', 'w': 135, 'd': 212, 'h': 82}]
check('5) unique_sizes: цвета одной модели — одна проба, порядок прежний', [b['sid'] for b in TB.unique_sizes(beds)] == ['a1', 'b', 'c', 'd'])


class Op:
    def __init__(self, kind, sill):
        self.kind, self.sill_cm = kind, sill


class Room:
    def __init__(self, ops):
        self.openings = ops


rooms = {'win': Room([Op('window', 85), Op('door', 0)]), 'none': Room([Op('door', 0)])}
TB.build_room = lambda cand, cfg, hinge, purpose: (rooms[cand['k']], [])
TB.template_ok = lambda res, tpl: bool(res)
fit = TB.unique_sizes(beds)
tpl = {'purpose': 'guest', 'id': 'guest-120'}


def solver(limit):
    return lambda ad, cand, cfg, kit, purpose: {'ok': 1} if float(kit['кровать']['h']) <= limit else None


TB.solve_kit = solver(85)
got = TB.window_low_beds({}, {'k': 'win'}, {}, {'кровать': beds[0], 'тумба прикроватная': {}}, tpl, fit, [beds[0], beds[2]])
check('5) у окна: высокая не встала, та же ниже подоконника встаёт → (предел 85, низкие рамы)',
      got is not None and got[0] == 85 and [b['sid'] for b in got[1]] == ['c', 'd'], got)
check('5) dominated: выше предела и не меньше — снимается; меньше по длине — остаётся',
      TB.dominated(beds[0], beds[0], 85) and not TB.dominated({'w': 130, 'd': 200, 'h': 91}, beds[0], 85)
      and not TB.dominated(beds[3], beds[0], 85))
check('5) size_key — точные размеры, как ключ памяти решателя', TB.size_key({'w': 130.4, 'd': 212, 'h': 91}) != TB.size_key(beds[0]))
check('5) окна нет → прежний подбор (None)',
      TB.window_low_beds({}, {'k': 'none'}, {}, {'кровать': beds[0], 'тумба прикроватная': {}}, tpl, fit, [beds[0]]) is None)
TB.solve_kit = solver(0)
check('5) и низкая не встаёт (мешает не окно) → None',
      TB.window_low_beds({}, {'k': 'win'}, {}, {'кровать': beds[0], 'тумба прикроватная': {}}, tpl, fit, [beds[0]]) is None)
TB.solve_kit = solver(85)
check('5) рама и так ниже подоконника → None',
      TB.window_low_beds({}, {'k': 'win'}, {}, {'кровать': beds[3], 'тумба прикроватная': {}}, tpl, fit, [beds[3]]) is None)

print('test_bed_headboard:', 'FAIL' if fails else 'OK')
sys.exit(1 if fails else 0)
