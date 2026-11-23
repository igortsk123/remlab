#!/usr/bin/env python3
"""Ворота кадра страницы как решение этапа 9 (T-20261123-25/1): pass / fail / uncertain на синтетике и на кадрах реального товара из out-batch р.1 (фикстура fixtures/frame_gate_real/).
Пороги — data/flat3d/material-recipes.json#frame_gate (в тесте чисел порогов нет). ID товаров в тесте нет.
Запуск: python tools/scout/tests/test_paint_frame_gate.py   (numpy + Pillow)"""
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'assets'))
import numpy as np  # noqa: E402
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_paint_frame_gate')
import frame_gate as FG  # noqa: E402
import material_stage as MS  # noqa: E402
import paint_check as PC  # noqa: E402
import paint_decisions as PD  # noqa: E402
import paint_stage as PS  # noqa: E402
from PIL import Image  # noqa: E402

R = PC.load_rules()
FG_RULES = MS.load_recipes()['frame_gate']
REG = PD.load()
FAIL = 0


def ok(cond, name):
    global FAIL
    print(('  ✓ ' if cond else '  ✗ ') + name)
    FAIL += 0 if cond else 1


def frames(d, now_rgb=(190, 140, 60), mat_rgb=(190, 140, 60), mask_px=30, size=40, skip=()):
    """Три кадра на синтетике: предмет — квадрат mask_px×mask_px посреди кадра size×size; mask.png — альфа предмета."""
    os.makedirs(d, exist_ok=True)
    o = (size - mask_px) // 2
    a = np.zeros((size, size, 4), np.uint8)
    m = np.zeros((size, size, 4), np.uint8)
    for arr, rgb in ((a, now_rgb),):
        arr[...] = (255, 255, 255, 255)
        arr[o:o + mask_px, o:o + mask_px, :3] = rgb
    b = a.copy()
    b[o:o + mask_px, o:o + mask_px, :3] = mat_rgb
    m[o:o + mask_px, o:o + mask_px] = (0, 0, 0, 255)
    for name, arr in (('now.png', a), ('mat.png', b), ('mask.png', m)):
        if name not in skip:
            Image.fromarray(arr).save(os.path.join(d, name))
    return d


# 1. сами ворота по папке кадров
with tempfile.TemporaryDirectory() as t:
    r = FG.gate_dir(frames(f'{t}/same'), FG_RULES)
    ok(r['status'] == 'ok' and r['dE'] == 0 and r['dC'] == 0, 'тот же цвет → ok')
    dE_ok = FG_RULES['dE_max'] / 2
    r = FG.gate_dir(frames(f'{t}/small', mat_rgb=(190, 140 + int(dE_ok), 60)), FG_RULES)
    ok(r['status'] == 'ok' and 0 < r['dE'] <= FG_RULES['dE_max'], f"малый сдвиг цвета внутри порога → ok (ΔE {r['dE']})")
    r = FG.gate_dir(frames(f'{t}/pale', mat_rgb=(190, 175, 150)), FG_RULES)
    ok(r['status'] == 'refused' and r['dC'] < FG_RULES['dC_min'], f"бледнее (ΔC {r['dC']} < порога) → refused")
    r = FG.gate_dir(frames(f'{t}/shift', mat_rgb=(230, 140, 60)), FG_RULES)
    ok(r['status'] == 'refused' and r['dE'] > FG_RULES['dE_max'], f"сдвиг цвета (ΔE {r['dE']} > порога) → refused")
    n_min = FG_RULES['min_mask_px']
    r = FG.gate_dir(frames(f'{t}/tiny', mask_px=max(1, int(n_min ** 0.5) - 2)), FG_RULES)
    ok(r['status'] == 'missing' and 'пиксел' in r['reason'], f"маска меньше min_mask_px → missing (не измерено): {r['reason']}")
    r = FG.gate_dir(frames(f'{t}/nomask', skip=('mask.png',)), FG_RULES)
    ok(r['status'] == 'missing' and 'mask.png' in r['reason'], 'нет mask.png → missing')
    r = FG.gate_dir(f'{t}/empty-nowhere', FG_RULES)
    ok(r['status'] == 'missing' and 'now.png' in r['reason'], 'нет папки кадров → missing')
    d = frames(f'{t}/bad')
    open(f'{d}/mat.png', 'wb').write(b'not a png')
    ok(FG.gate_dir(d, FG_RULES)['status'] == 'missing', 'битый PNG → missing, не проход и не падение')
    d = frames(f'{t}/size')
    Image.new('RGB', (30, 30), (1, 2, 3)).save(f'{d}/mat.png')
    ok(FG.gate_dir(d, FG_RULES)['status'] == 'missing', 'размеры кадров разные → missing')

# 2. стадия этапа 9 и решение реестра (pass / fail / uncertain)
    def stage_for(sub, **kw):
        run = f'{t}/run'
        frames(os.path.join(run, PS.safe_name(sub), R['frame_gate']['stage']), **kw)
        return PC.classify_frame_gate(run, sub, R)
    S06 = {'stage': '06-visible', 'status': 'ok', 'reason': '', 'metrics': {}}
    for name, kw, want_stage, want_dec in (('p', {}, 'ok', 'pass'), ('f', {'mat_rgb': (230, 140, 60)}, 'refused', 'fail'), ('m', {'mask_px': 3}, 'missing', 'uncertain')):
        fgs = stage_for(name, **kw)
        dec = PD.decide_product([S06], {'frame_gate': fgs}, REG)
        ok(fgs['status'] == want_stage and dec['items']['09.frame_gate']['state'] == want_dec, f"стадия {want_stage} → решение 09.frame_gate = {want_dec}")
        if want_dec == 'fail':
            ok('09.frame_gate' in dec['fail'] and dec['state'] == 'fail', 'ворота не прошли → итог товара fail (жёстко)')
            ok(fgs['hard_failed'] == ['frame_gate'] and fgs['metrics']['frame_dE']['ok'] is False, 'метрики ΔE/ΔC записаны с порогом из рецептов')
    ok(stage_for('p')['metrics']['frame_dE']['threshold'] == FG_RULES['dE_max'] and stage_for('p')['metrics']['frame_dC']['threshold'] == FG_RULES['dC_min'], 'порог в метрике — число из material-recipes.json')
    d_none = PD.decide_product([S06], {}, REG)
    ok(d_none['items']['09.frame_gate']['state'] == 'uncertain', 'ворот нет во входе → uncertain')

# 3. итог товара: ворота не прошли → «не готов»; кадров нет → старый итог не меняется
PC.run_palette = lambda glb, photo, guard: {'share': 0.0, 'photo_share': 0.0, 'rgb': None}
PC.run_surface = lambda glb, run, sku, out_dir, sr=None: {'stage': 'surface', 'status': 'ok', 'reason': '', 'hard_failed': [], 'soft_failed': [], 'metrics': {}, 'glb': glb}
COV = lambda glb, out_dir, rules: {'verdict': 'keep', 'why': [], 'metrics': {k: 1.0 for k in R['coverage']['show_metrics']}, 'seconds': 0.1}  # noqa: E731


def full(run, sku):
    for st in R['required_stages']:
        d = PS.stage_dir(run, sku, st)
        Image.new('RGB', (200, 100), (200, 220, 200)).save(os.path.join(d, PS.FRAME))
        out = []
        if st == '08-material':
            out = ['material.glb']
            open(os.path.join(d, 'material.glb'), 'wb').write(b'glb')
        PS.write_check(d, st, sku, passed=True, metric={'name': 'm', 'value': 1.0, 'threshold': 0.5, 'op': '>='}, outputs=out, frame=PS.FRAME)


with tempfile.TemporaryDirectory() as run:
    for sku in ('good', 'bad', 'noframes'):
        full(run, sku)
    frames(os.path.join(run, 'good', R['frame_gate']['stage']))
    frames(os.path.join(run, 'bad', R['frame_gate']['stage']), mat_rgb=(190, 175, 150))
    g = PC.check_product(run, 'good', R, cov_fn=COV, ribbon=False)
    b = PC.check_product(run, 'bad', R, cov_fn=COV, ribbon=False)
    n = PC.check_product(run, 'noframes', R, cov_fn=COV, ribbon=False)
    ok(g['extra']['final'] == 'ready' and g['extra']['decisions']['items']['09.frame_gate']['state'] == 'pass', 'кадры в норме → готов, решение pass')
    ok(not b['passed'] and b['extra']['final'] == 'not_ready' and 'frame_gate' in b['extra']['blocking'] and '09.frame_gate' in b['extra']['decisions']['fail'], 'ворота не прошли → товар «не готов», решение fail')
    ok(b['extra']['frame_gate']['status'] == 'refused' and 'ΔC' in b['extra']['frame_gate']['reason'], 'причина в check.json простыми цифрами (ΔC)')
    ok(n['passed'] and n['extra']['final'] == 'ready' and n['extra']['decisions']['items']['09.frame_gate']['state'] == 'uncertain' and n['extra']['decisions']['state'] == 'uncertain', 'кадров нет → старый итог «готов» не тронут, решение uncertain, итог решений uncertain')

# 4. реестр и код: порог один (в json рецептов), ID товаров нет
txt = open(PD.RULES, encoding='utf-8').read()
row = [x for x in REG['decisions'] if x['id'] == '09.frame_gate'][0]
ok(row['threshold_ref'] == 'data/flat3d/material-recipes.json#frame_gate' and row['severity'] == 'hard', 'реестр: ссылка на рецепты, строгость hard')
src = open(os.path.join(HERE, '..', 'paint_check.py'), encoding='utf-8').read() + open(os.path.join(HERE, '..', '..', 'assets', 'frame_gate.py'), encoding='utf-8').read()
ok(not re.search(r'dE_max\s*=\s*[\d.]|dC_min\s*=\s*-?[\d.]|min_mask_px\s*=\s*\d', src) and not re.search(r'\b\d{5,6}_\d{6,}\b', src + open(__file__, encoding='utf-8').read()), 'чисел порогов в коде нет, ID товаров нет')

# 5. реальные товары из out-batch р.1: кадры страницы 07→«как сейчас» / 08→«с материалом» (смотрено глазами при создании фикстуры)
real = os.path.join(HERE, 'fixtures', 'frame_gate_real')
cases = sorted(os.listdir(real)) if os.path.isdir(real) else []
ok(len(cases) >= 2, f'фикстуры реальных товаров на месте: {cases}')
for name in cases:
    d = os.path.join(real, name)
    meta = json.load(open(os.path.join(d, 'meta.json'), encoding='utf-8'))
    r = FG.gate_dir(d, FG_RULES)
    ok(r['status'] == meta['expect_status'] and abs(r['dE'] - meta['dE']) < 0.05 and abs(r['dC'] - meta['dC']) < 0.05, f"реальный товар {name}: {r['status']}, ΔE {r['dE']} ΔC {r['dC']} (ожидалось {meta['expect_status']} {meta['dE']}/{meta['dC']})")
    with tempfile.TemporaryDirectory() as run:                                     # через стадию и решение реестра, как в этапе 9
        sd = os.path.join(run, 'x', R['frame_gate']['stage'])
        os.makedirs(sd)
        for f in FG.FILES:
            Image.open(os.path.join(d, f)).save(os.path.join(sd, f))
        dec = PD.decide_product([{'stage': '06-visible', 'status': 'ok', 'reason': '', 'metrics': {}}], {'frame_gate': PC.classify_frame_gate(run, 'x', R)}, REG)
        ok(dec['items']['09.frame_gate']['state'] == ('fail' if meta['expect_status'] == 'refused' else 'pass'), f'{name}: решение реестра {dec["items"]["09.frame_gate"]["state"]}')
ok_dir = os.path.join(real, 'ok_table')
if os.path.isdir(ok_dir):
    with tempfile.TemporaryDirectory() as bad:
        for f in FG.FILES:
            Image.open(os.path.join(ok_dir, f)).save(os.path.join(bad, f))
        mat = np.asarray(Image.open(os.path.join(bad, 'mat.png')).convert('RGBA')).astype(int)
        mat[..., :3] = np.clip(mat[..., :3] * 0.6 + 100, 0, 255)
        Image.fromarray(mat.astype(np.uint8)).save(os.path.join(bad, 'mat.png'))
        ok(FG.gate_dir(bad, FG_RULES)['status'] == 'refused', 'тот же реальный кадр, но mat выцвел → refused (чувствительность на реальных пикселях)')
print('FAIL' if FAIL else 'ВСЁ ЗЕЛЁНОЕ', FAIL)
sys.exit(1 if FAIL else 0)
