#!/usr/bin/env python3
"""check.json этапов 01/02 «лесенки форм» (T-20261123-45; ladder_checks.py, sg_color_transfer.stage02_form) на заглушках: годная форма, форма без цвета, нет файла, битый GLB, много граней,
раскладка папок, пересчёт по готовым файлам, 05 не выдумывается, этап 9 читает записанное. Запуск: python3 tools/scout/tests/test_ladder_checks.py (numpy, trimesh, Pillow, scipy)"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SC = os.path.join(HERE, '..')
sys.path.insert(0, SC)
sys.path.insert(0, os.path.join(SC, 'stablegen'))
sys.path.insert(0, os.path.join(SC, 'salad', 'trellis'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_ladder_checks')
import numpy as np  # noqa: E402
import trimesh  # noqa: E402
from PIL import Image  # noqa: E402
import ladder_checks as LC  # noqa: E402
import paint_stage as PS  # noqa: E402
import sg_color_transfer as T  # noqa: E402

FAIL = 0


def ok(c, m, extra=''):
    global FAIL
    print(('  ✓ ' if c else '  ✗ ') + m + (f'  [{extra}]' if extra and not c else ''))
    FAIL += 0 if c else 1


def grid(n):
    xs = np.linspace(0, 1, n + 1)
    X, Y = np.meshgrid(xs, xs)
    V = np.stack([X.ravel(), Y.ravel(), (0.1 * np.sin(2 * X) + 0.05 * Y).ravel()], 1)
    UV = np.stack([X.ravel(), Y.ravel()], 1)
    F = []
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            F += [[a, a + 1, a + n + 2], [a, a + n + 2, a + n + 1]]
    return V, np.array(F, np.int64), UV


def write(path, with_color=True, n=8, size=128):
    V, F, UV = grid(n)
    m = trimesh.Trimesh(vertices=V, faces=F, process=False)
    if with_color:
        u = (np.arange(size) + 0.5) / size
        U, W = np.meshgrid(u, 1.0 - u)
        base = np.stack([(U * 255), (W * 255), np.full_like(U, 128), np.full_like(U, 255)], -1).astype(np.uint8)
        mat = trimesh.visual.material.PBRMaterial(baseColorTexture=Image.fromarray(base, 'RGBA'), alphaMode='OPAQUE')
    else:
        mat = trimesh.visual.material.PBRMaterial(baseColorFactor=[200, 200, 200, 255])
    m.visual = trimesh.visual.TextureVisuals(uv=UV, material=mat)
    m.export(path, file_type='glb')


with tempfile.TemporaryDirectory() as t:
    good, plain, bad, missing = (os.path.join(t, x) for x in ('good-hd.glb', 'plain-hd.glb', 'bad-hd.glb', 'none-hd.glb'))
    write(good)
    write(plain, with_color=False)
    open(bad, 'wb').write(b'not a glb at all')
    run = os.path.join(t, 'run')

    # годная форма: оба этапа прошли, меры на месте, «против родной» нет
    r = LC.write_checks(run, 'good', good)
    c1, c2 = PS.read_check(os.path.join(run, 'good', '01-trellis')), PS.read_check(os.path.join(run, 'good', '02-prep'))
    ok(r['01']['passed'] and r['02']['passed'] and c1 and c2, 'годная форма: check.json 01 и 02 записаны и прошли', (r, c1, c2))
    ok(c1['metric']['name'] == 'has_base_color' and c1['metric']['value'] == 1, '01: главная мерка has_base_color = 1')
    ok(c2['metric']['name'] == 'faces_with_texel' and c2['metric']['ok'] and c2['metrics']['faces']['ok'] is None and c2['metrics']['faces']['value'] == 128, '02: доля граней с текселем измерена; число граней — справочно, без порога (лесенка не упрощает до 150 тыс.)')
    big = T.stage02_form(run, 'big', good)
    ok(big['passed'], '02: форма с числом граней больше 150 тыс. по умолчанию не отвергается (проверено порогом ниже)')
    ok(c2['extra']['compared_to_native'] is False and 'chamfer_diag' not in c2['metrics'] and 'color_texel_share' not in c2['metrics'], '02: мерок «против родной» нет, об этом записано (compared_to_native=false)')
    ok(os.path.isfile(os.path.join(run, 'good', '02-prep', 'frame.png')) and os.path.exists(os.path.join(run, 'good', '02-prep', 'shape.glb')), '02: кадр и ссылка на форму на месте')
    ok(not os.path.exists(os.path.join(run, 'good', '05-delight')), '05-delight лесенка НЕ пишет и не выдумывает')

    # форма без цвета / нет файла / битый GLB — этап не пройден с причиной, не падение
    r = LC.write_checks(run, 'plain', plain)
    ok(not r['01']['passed'] and 'цвет не пришёл' in r['01']['reason'] and not r['02']['passed'] and 'нет baseColor' in r['02']['reason'], 'форма без baseColor: 01 и 02 не пройдены, причины названы', r)
    r = LC.write_checks(run, 'none', missing)
    ok(not r['01']['passed'] and not r['02']['passed'] and 'нет GLB' in r['02']['reason'] and PS.read_check(os.path.join(run, 'none', '02-prep')) is not None, 'нет файла формы: check.json с passed=false и причиной, а не отсутствие файла', r)
    r = LC.write_checks(run, 'bad', bad)
    ok(not r['01']['passed'] and not r['02']['passed'] and r['02']['reason'], 'битый GLB: этапы не пройдены с причиной, исключение не вышло', r)
    c = T.stage02_form(run, 'many', good, faces_max=10)
    ok(not c['passed'] and c['metrics']['faces']['ok'] is False and 'faces' in c['reason'], '02: граней больше порога → не прошёл, мерка названа', c)

    # этап 9 читает записанное: 01/02 ок, 05 — нет данных, чужой прогон не подставляется
    try:
        import paint_check as PC
        R = PC.load_rules()
        s1 = PC.classify_stage('01-trellis', PS.read_check(os.path.join(run, 'good', '01-trellis')), R, run)
        s5 = PC.classify_stage('05-delight', PS.read_check(os.path.join(run, 'good', '05-delight')), R, run)
        s2p = PC.classify_stage('02-prep', PS.read_check(os.path.join(run, 'plain', '02-prep')), R, run)
        ok(s1['status'] == 'ok' and s5['status'] == 'missing' and s2p['status'] == 'refused', '09: 01 ок, 05 «нет данных» (missing), форма без цвета — отказ', (s1['status'], s5['status'], s2p['status']))
    except ImportError as e:
        print('  ~ paint_check не импортируется:', e)

    # раскладка папок для задания и пересчёт по готовым файлам
    out = os.path.join(t, 'out')
    w = LC.write_for_job(out, 'shop:good', 'hd', good)
    ok(w['01']['passed'] and os.path.isfile(os.path.join(out, 'ladder-run', 'hd', 'shop_good', '01-trellis', 'check.json')) and '05-delight' in w['not_run'], 'write_for_job: <out>/ladder-run/<ступень>/<товар>/01-trellis/check.json; 05 назван как «не выполняется»', w)
    gd = os.path.join(t, 'glbs')
    os.makedirs(gd)
    for nm in ('a-hd.glb', 'b-hd.glb', 'a-hd.raw.glb', 'a-hd1536.glb'):
        write(os.path.join(gd, nm))
    rows = LC.recompute(gd, 'hd', os.path.join(t, 'rec'))
    ok([s for s, _ in rows] == ['a', 'b'] and all(c['01']['passed'] and c['02']['passed'] for _, c in rows), 'recompute: только <товар>-hd.glb (без .raw. и других ступеней)', rows)
    ok([s for s, _ in LC.recompute(gd, 'hd', os.path.join(t, 'rec2'), ['b'])] == ['b'], 'recompute: фильтр по товару')

    # trellis_trial: ступень запоминается в задании; сбой записи — в сводку, не падение
    try:
        import trellis_trial as TT
        lj = TT.expand_ladder_jobs([{'sku': 'a:1', 'res': 1024, 'seed': 42, 'job_id': 'x'}], [{'name': 'hd', 'input': 'hd', 'res': 1024, 'params': {}}])
        ok(lj[0]['ladder_step'] == 'hd', 'expand_ladder_jobs: ступень (ladder_step) записана в задание')
        wf = TT.write_form_checks(os.path.join(t, 'o2'), 'a:1', 'hd', good)
        ok(wf['01']['passed'] and wf['02']['passed'] and wf['run'].endswith(os.path.join('ladder-run', 'hd')), 'write_form_checks из trellis_trial: записано', wf)
    except ImportError as e:
        print('  ~ trellis_trial не импортируется:', e)

print(f'test_ladder_checks: ошибок {FAIL}')
sys.exit(1 if FAIL else 0)
