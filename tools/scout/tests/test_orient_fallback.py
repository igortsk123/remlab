"""Каскад ориентации (`orient_worker.decide`): роль из manifest.json и запасной поворот при заваленном «верхе»
(T-20261105-36/2). Без сети, базы и нейросетей: `role_of`, `canonical_parts`, `infer_seat_front` подменены.

  1) Меш без карточки в БД (роль «?») берёт роль из manifest.json рядом — кровать становится направленной
     (раньше «symmetric_by_role» и поворот нейросети без проверки: волна 2 спальни, перед сбоку у 5 из 45).
  2) Без manifest роль «?» — по-прежнему симметричная (поведение для прочих не меняется).
  3) Наклон > 15° → поворот 180° вокруг вертикали: перед сырого меша (к камере фото, MR-yaw 0) уходит в перед канона
     (MR-yaw 180), legacy_front_yaw = 0, R и кватернион согласованы. Прежняя единичная матрица давала 180 = зад
     (VLM «зад» у 49 из 67 таких комодов; 46 сидячих — «конфликт сиденья» с передом на 0°).
  4) Сидячий с заваленным верхом и сиденьем, найденным на сыром переде, теперь сходится (orienter+seat_agree).
    ~/venvs/scout/bin/python tools/scout/tests/test_orient_fallback.py"""
import json
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import orient_worker as W  # noqa: E402

fails = 0


def check(name, cond, extra=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
    fails += 0 if cond else 1


def matvec(R, v):
    return [sum(R[i][j] * v[j] for j in range(3)) for i in range(3)]


def quat_to_R(q):
    w, x, y, z = q
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


W.role_of = lambda sku: ('?', '', '')
W.canonical_parts = lambda glb, R: {'R': R}
seat_calls = []


def fake_seat(parts, role, has_back=True):
    # сиденье «найдено» на сыром переде (+Z): в каноне оно там, куда R отправил +Z
    seat_calls.append(parts['R'])
    f = matvec(parts['R'], [0, 0, 1])
    yaw = round(math.degrees(math.atan2(-f[0], f[2]))) % 360     # MR: yaw Y видит грань (−sin Y, 0, cos Y)
    return {'status': 'confident', 'front_yaw': yaw, 'margin': 0.5}


W.infer_seat_front = fake_seat

c, s = math.cos(math.radians(40)), math.sin(math.radians(40))
TILTED = {'R': [[1, 0, 0], [0, c, -s], [0, s, c]], 'quat_wxyz': [math.cos(math.radians(20)), math.sin(math.radians(20)), 0, 0],
          'flip_prob': 0.5, 'pset_size': 1}
UPRIGHT90 = {'R': [[0, 0, 1], [0, 1, 0], [-1, 0, 0]], 'quat_wxyz': [math.cos(math.radians(45)), 0, math.sin(math.radians(45)), 0],
             'flip_prob': 0.5, 'pset_size': 1}

with tempfile.TemporaryDirectory(prefix='orient-fb-') as td:
    bed_dir, bare_dir = os.path.join(td, 'bed'), os.path.join(td, 'bare')
    os.makedirs(bed_dir), os.makedirs(bare_dir)
    for d in (bed_dir, bare_dir):
        open(os.path.join(d, 'model.glb'), 'wb').write(b'glTF-fake')
    json.dump({'role': 'кровать', 'name': 'Кровать Тест'}, open(os.path.join(bed_dir, 'manifest.json'), 'w'),
              ensure_ascii=False)

    r = W.decide('x:1', os.path.join(bed_dir, 'model.glb'), UPRIGHT90, use_vlm=False)
    check('1) роль из manifest: кровать направленная, не symmetric_by_role',
          r['role'] == 'кровать' and r.get('source') == 'awaiting_vlm', f"role={r['role']} source={r.get('source')}")
    check('1) стоящий меш — поворот нейросети не тронут', r['legacy_front_yaw'] == W.front_yaw_from_R(UPRIGHT90['R'])[0] and r['R'] == UPRIGHT90['R'],
          f"yaw={r['legacy_front_yaw']}")

    r = W.decide('x:2', os.path.join(bare_dir, 'model.glb'), UPRIGHT90, use_vlm=False)
    check('2) без manifest роль «?» — симметричная, как раньше',
          r['role'] == '?' and r.get('source') == 'symmetric_by_role', f"role={r['role']} source={r.get('source')}")

    r = W.decide('x:3', os.path.join(bed_dir, 'model.glb'), TILTED, use_vlm=False)
    front_canon = matvec(r['R'], [0, 0, 1])
    check('3) наклон > 15°: up_rejected, legacy_front_yaw = 0, наклон 0',
          r['evidence']['orienter'].get('up_rejected') and r['legacy_front_yaw'] == 0 and r['up_tilt_deg'] == 0.0,
          f"yaw={r['legacy_front_yaw']} tilt={r['up_tilt_deg']}")
    check('3) сырой перед (+Z) → перед канона (−Z = MR-yaw 180), верх на месте',
          front_canon == [0, 0, -1] and matvec(r['R'], [0, 1, 0]) == [0, 1, 0], f'front={front_canon}')
    qR = quat_to_R(r['raw_to_canonical_quat_wxyz'])
    check('3) кватернион совпадает с R', all(abs(qR[i][j] - r['R'][i][j]) < 1e-9 for i in range(3) for j in range(3)),
          f'q={r["raw_to_canonical_quat_wxyz"]}')

    W.role_of = lambda sku: ('кресло', 'Кресло Тест', '')
    r = W.decide('x:4', os.path.join(bare_dir, 'model.glb'), TILTED, use_vlm=False)
    check('4) кресло с заваленным верхом: сиденье на сыром переде → orienter+seat_agree',
          r.get('source') == 'orienter+seat_agree' and r['evidence']['seat']['front_yaw'] == W.FRONT_CANON_YAW,
          f"source={r.get('source')} seat={r['evidence'].get('seat')}")

print('test_orient_fallback:', 'FAIL' if fails else 'OK')
sys.exit(1 if fails else 0)
