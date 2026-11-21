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
        metrics={'known_share': {'value': 0.13, 'threshold': 0.15, 'op': '>=', 'ok': False}, 'edge_corr': {'value': 0.89, 'threshold': 0.9, 'op': '>=', 'ok': False}})
    d = PC.check_product(run, 'c', R, cov_fn=cov('keep'))
    ok(d['passed'] and d['extra']['final'] == 'ready_with_notes' and d['extra']['stages'][5]['status'] == 'soft', 'мягкий провал (мерки из списка мягких) → готов с пометкой')
    ok(len(d['extra']['notes']) == 1 and '06-visible' in d['extra']['notes'][0], 'пометка называет этап и причину')

    full(run, 'd')
    put(run, 'd', '06-visible', passed=False, metric={'name': 'silhouette_iou', 'value': 0.7, 'threshold': 0.85, 'op': '>=', 'ok': False},
        metrics={'known_share': {'value': 0.13, 'threshold': 0.15, 'op': '>=', 'ok': False}})
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
