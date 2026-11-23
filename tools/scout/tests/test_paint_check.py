#!/usr/bin/env python3
"""Этап 9 «проверка» пути покраски (T-20261121-169/4): синтетика — свои check.json в временной папке, настоящий сторож охвата подменяется (его проверяет tests_tex_coverage.py).
Запуск: python3 tools/scout/tests/test_paint_check.py   (нужны numpy-free stdlib + Pillow)"""
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'assets'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_paint_check')
import paint_check as PC  # noqa: E402
import paint_stage as PS  # noqa: E402
from PIL import Image  # noqa: E402

R = PC.load_rules()
# сторож палитры (paint_palette, numpy/trimesh) в этом файле подменён «чисто»: его настоящую работу на GLB проверяет test_paint_palette.py
PAL_CLEAN = {'share': 0.0, 'photo_share': 0.0, 'rgb': None}
PC.run_palette = lambda glb, photo, guard: dict(PAL_CLEAN)
PC.run_surface = lambda glb, run, sku, out_dir, sr=None: {'stage': 'surface', 'status': 'ok', 'reason': '', 'hard_failed': [], 'soft_failed': [], 'metrics': {}, 'glb': glb}   # мерки поверхности (numpy/trimesh) здесь не гоним: их тест — test_paint_surface_checks.py
STAGES = R['required_stages']
FAIL = 0


def ok(cond, name):
    global FAIL
    print(('  ✓ ' if cond else '  ✗ ') + name)
    FAIL += 0 if cond else 1


def put(run, sku, stage, passed=True, metric=None, metrics=None, reason='', outputs=None):
    d = PS.stage_dir(run, sku, stage)
    Image.new('RGB', (200, 100), (200, 220, 200)).save(os.path.join(d, PS.FRAME))
    return PS.write_check(d, stage, sku, passed=passed, metric=metric or {'name': 'm', 'value': 1.0, 'threshold': 0.5, 'op': '>='}, metrics=metrics, reason=reason, outputs=outputs or [], frame=PS.FRAME)


def full(run, sku, glb=True, skip=()):
    for st in STAGES:
        if st in skip:
            continue
        out = []
        if st == '08-material' and glb:
            out = ['material.glb']
            open(os.path.join(PS.stage_dir(run, sku, st), 'material.glb'), 'wb').write(b'glb')
        put(run, sku, st, outputs=out)


def cov(verdict, why=None):
    return lambda glb, out_dir, rules: {'verdict': verdict, 'why': why or [], 'metrics': {k: 1.0 for k in R['coverage']['show_metrics']}, 'seconds': 0.1}


with tempfile.TemporaryDirectory() as run:
    full(run, 'a')
    d = PC.check_product(run, 'a', R, cov_fn=cov('keep'))
    ok(d['passed'] and d['extra']['final'] == 'ready' and not d['extra']['notes'], 'все 8 этапов прошли + охват keep → готов к показу')
    ok(os.path.exists(os.path.join(run, 'a', '09-check', 'frame.png')) and PS.read_check(os.path.join(run, 'a', '09-check'))['passed'], 'check.json и лента этапов записаны, 09 читается общим читателем')

    full(run, 'b', skip=('07-fill',))
    d = PC.check_product(run, 'b', R, cov_fn=cov('keep'))
    ok(not d['passed'] and d['extra']['final'] == 'not_ready' and '07-fill' in d['extra']['blocking'] and d['reason'].startswith('07-fill'), 'пропущенный этап → не готов, причина называет этап')
    ok(d['extra']['stages'][6]['status'] == 'missing', 'статус пропущенного — missing, не «прошёл»')

    full(run, 'c')
    put(run, 'c', '06-visible', passed=False, metric={'name': 'silhouette_iou', 'value': 0.92, 'threshold': 0.85, 'op': '>=', 'ok': True},
        metrics={'known_visible_share': {'value': 0.13, 'threshold': 0.30, 'op': '>=', 'ok': False}, 'edge_corr': {'value': 0.69, 'threshold': 0.7, 'op': '>=', 'ok': False}})
    d = PC.check_product(run, 'c', R, cov_fn=cov('keep'))
    ok(d['passed'] and d['extra']['final'] == 'ready_with_notes' and d['extra']['stages'][5]['status'] == 'soft', 'мягкий провал (мерки из списка мягких) → готов с пометкой')
    ok(len(d['extra']['notes']) == 1 and '06-visible' in d['extra']['notes'][0], 'пометка называет этап и причину')

    full(run, 'c2')
    put(run, 'c2', '06-visible', passed=False, metric={'name': 'silhouette_iou', 'value': 0.92, 'threshold': 0.85, 'op': '>=', 'ok': True},
        metrics={'known_visible_share': {'value': 0.1, 'threshold': 0.3, 'op': '>=', 'ok': False}})
    d = PC.check_product(run, 'c2', R, cov_fn=cov('keep'))
    ok(d['passed'] and d['extra']['final'] == 'ready_with_notes' and d['extra']['stages'][5]['status'] == 'soft', 'T-215: known_visible_share (мерка гейта 06) — мягкая: готов с пометкой, не отказ')

    full(run, 'd')
    put(run, 'd', '06-visible', passed=False, metric={'name': 'silhouette_iou', 'value': 0.7, 'threshold': 0.85, 'op': '>=', 'ok': False},
        metrics={'known_visible_share': {'value': 0.13, 'threshold': 0.30, 'op': '>=', 'ok': False}})
    d = PC.check_product(run, 'd', R, cov_fn=cov('keep'))
    ok(not d['passed'] and d['extra']['stages'][5]['status'] == 'refused', 'жёсткая мерка не прошла вместе с мягкой → отказ')

    full(run, 'e')
    put(run, 'e', '03-parts', passed=False, reason='отказ по правилу: плоская текстура', metric={'name': 'texture_std', 'value': 2.2})
    d = PC.check_product(run, 'e', R, cov_fn=cov('keep'))
    ok(not d['passed'] and 'плоская текстура' in d['reason'], 'этап не прошёл, мерку не назвал (отказ по правилу) → жёстко, причина этапа сохранена')

    full(run, 'f')
    put(run, 'f', '05-delight', passed=False, metric={'name': 'iid_shading_removed', 'value': 0.1, 'threshold': 0.5, 'op': '>=', 'ok': False})
    d = PC.check_product(run, 'f', R, cov_fn=cov('keep'))
    ok(d['passed'] and d['extra']['stages'][4]['status'] == 'soft', 'этап целиком мягкий («*») → не блокирует')

    full(run, 'g')
    put(run, 'g', '04-camera', passed=False, metric={'name': 'iou_silhouette', 'value': 0.5, 'threshold': 0.85, 'op': '>=', 'ok': False, 'soft': True})
    d = PC.check_product(run, 'g', R, cov_fn=cov('keep'))
    ok(d['passed'] and d['extra']['stages'][3]['status'] == 'soft', 'флаг soft в самой мерке этапа главнее таблицы')

    full(run, 'h')
    put(run, 'h', '02-prep', passed=True, metric={'name': 'faces', 'value': 1, 'threshold': 5, 'op': '<=', 'ok': None})
    ok(PC.check_product(run, 'h', R, cov_fn=cov('keep'))['passed'], 'мерка N/A (ok=None) при passed → не провал')

    full(run, 'i')
    d = PC.check_product(run, 'i', R, cov_fn=cov('repaint', ['unseen_outer_tex_pct 25 > 20']))
    ok(d['passed'] and d['extra']['final'] == 'ready_with_notes' and d['extra']['coverage']['verdict'] == 'repaint', 'охват repaint → мягко: готов с пометкой')
    d = PC.check_product(run, 'i', R, cov_fn=cov('reject', ['unseen_outer_tex_pct 60 > 45']))
    ok(not d['passed'] and 'coverage' in d['extra']['blocking'], 'охват reject → не готов')

    def boom(*a):
        raise RuntimeError('нет памяти')
    d = PC.check_product(run, 'i', R, cov_fn=boom)
    ok(not d['passed'] and 'упал' in d['reason'], 'сторож упал → не готов (нет измерения — не «ок»)')

    full(run, 'j', glb=False)
    d = PC.check_product(run, 'j', R, cov_fn=cov('keep'))
    ok(not d['passed'] and d['extra']['coverage']['status'] == 'missing', 'нет итогового GLB → охват не измерен → не готов')

    # палитра (T-20261121-174/1): малиновая заглушка вне палитры фото
    def pal(share, photo=0.0):
        return lambda glb, photo_path, guard: {'share': share, 'photo_share': photo, 'rgb': [158, 11, 115]}
    full(run, 'p1')
    d = PC.check_product(run, 'p1', R, cov_fn=cov('keep'), pal_fn=pal(0.04))
    ok(not d['passed'] and 'palette' in d['extra']['blocking'] and 'малиновая заглушка 4.00 %' in d['reason'], 'малиновая заглушка 4 % площади, на фото нет → не готов, причина названа (кровать №4)')
    ok(d['extra']['palette']['status'] == 'refused' and d['extra']['palette']['metrics']['magenta_surface_pct']['value'] == 4.0, 'в check.json палитра: статус и доля в процентах')
    d = PC.check_product(run, 'p1', R, cov_fn=cov('keep'), pal_fn=pal(0.04, photo=0.30))
    ok(d['passed'] and d['extra']['palette']['status'] == 'ok', 'розовый товар (на фото 30 % такого цвета) → допуск выше, не готов НЕ ставим')
    d = PC.check_product(run, 'p1', R, cov_fn=cov('keep'), pal_fn=pal(0.0008))
    ok(d['passed'] and d['extra']['final'] == 'ready_with_notes' and d['extra']['palette']['status'] == 'soft', 'крошка 0,08 % → готов с пометкой, не блокирует')
    d = PC.check_product(run, 'p1', R, cov_fn=cov('keep'), pal_fn=pal(0.0))
    ok(d['passed'] and d['extra']['final'] == 'ready', '0 % → готов')
    d = PC.check_product(run, 'p1', R, cov_fn=cov('keep'), pal_fn=pal(PC.load_guard(R)['magenta']['obj_frac_max']))
    ok(d['passed'], 'ровно на пороге допуска (не больше) → не отказ')
    d = PC.check_product(run, 'p1', R, cov_fn=cov('keep'), pal_fn=lambda *a: (_ for _ in ()).throw(RuntimeError('нет памяти')))
    ok(not d['passed'] and 'сторож палитры упал' in d['reason'], 'сторож палитры упал → не готов (нет измерения — не «ок»)')
    d = PC.check_product(run, 'p1', R, cov_fn=cov('keep'), pal_fn=lambda *a: {'share': None, 'photo_share': 0.0})
    ok(not d['passed'] and 'нет текстуры' in d['reason'], 'в GLB нет текстуры цвета → не измерено → не готов')
    put(run, 'p1', '04-camera', outputs=[])
    open(os.path.join(run, 'ph.png'), 'wb').write(b'x')
    PS.write_check(PS.stage_dir(run, 'p1', '04-camera'), '04-camera', 'p1', passed=True, metric={'name': 'm', 'value': 1.0, 'threshold': 0.5, 'op': '>='}, photo=os.path.join(run, 'ph.png'))
    ok(PC.find_photo(run, 'p1', R) == os.path.join(run, 'ph.png'), 'фото товара берётся из extra check.json этапа камеры (своего пути нет)')
    ok(PC.find_photo(run, 'zz-нет', R) is None, 'нет check.json этапа → фото None, допуска нет')

    # этапы в разных папках прогона
    with tempfile.TemporaryDirectory() as other:
        full(run, 'k', skip=('06-visible',))
        put(other, 'k', '06-visible')
        d = PC.check_product(run, 'k', R, stage_runs={'06-visible': other}, cov_fn=cov('keep'))
        ok(d['passed'] and d['extra']['stages'][5]['run'] == other, '--stage-run: этап берётся из своей папки, источник записан')

    # таблица прогона
    PC.check_batch(run, R, ['a', 'b', 'c'], cov_fn=cov('keep'))
    t = open(os.path.join(run, 'run_summary.tsv'), encoding='utf-8').read().splitlines()
    head = t[0].split('\t')
    ok(head[:2] == ['sku', 'final'] and all(s in head for s in STAGES) and 'unseen_outer_tex_pct' in head, 'run_summary.tsv: товар, итог, все этапы, ключевые числа охвата')
    rows = {r.split('\t')[0]: r.split('\t') for r in t[1:]}
    ok(rows['a'][1] == R['final_words']['ready'] and rows['b'][1] == R['final_words']['not_ready'] and rows['c'][1] == R['final_words']['ready_with_notes'], 'строки по товарам: готов / не готов / с пометкой')
    ok(rows['b'][head.index('07-fill')] == R['words']['missing'], 'в таблице пропущенный этап — «нет этапа»')

    # битый check.json = нет этапа
    full(run, 'm')
    open(os.path.join(run, 'm', '03-parts', 'check.json'), 'w').write('{плохо')
    ok(not PC.check_product(run, 'm', R, cov_fn=cov('keep'))['passed'], 'битый check.json = этап отсутствует')

src = open(os.path.join(HERE, '..', 'paint_check.py'), encoding='utf-8').read() + open(os.path.join(HERE, '..', 'rules', 'paint-check.json'), encoding='utf-8').read()
ok(not re.search(r'\b\d{9,}\b', src), 'ID товаров в коде и правилах нет')
ok(not re.search(r'"(threshold|op)"\s*:', open(os.path.join(HERE, '..', 'rules', 'paint-check.json'), encoding='utf-8').read()), 'пороги мерок в правилах этапа 9 не дублируются (живут в check.json этапов и в tex_coverage)')

print(f'paint_check: ошибок {FAIL}')
sys.exit(1 if FAIL else 0)
