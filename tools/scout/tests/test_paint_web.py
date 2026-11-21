#!/usr/bin/env python3
"""Этап 10 «сайт» (paint_web.py, T-20261121-171/1): пороги — только в данных, ID товаров в коде нет, вес — из rt-weight.json, решение «прошёл» — по правилу.
Зависит от paint_stage.py (ветка paint-fill-1120; после её вливания лежит рядом). Запуск: python tools/scout/tests/test_paint_web.py
"""
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.join(HERE, '..')
if os.environ.get('PAINT_STAGE_DIR'):
    sys.path.insert(0, os.environ['PAINT_STAGE_DIR'])
sys.path.insert(0, SCOUT)
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_paint_web')
import paint_web as W  # noqa: E402
import paint_stage as PS  # noqa: E402

SRC = {n: open(os.path.join(SCOUT, n), encoding='utf-8').read() for n in ('paint_web.py', 'paint_web_render.py')}
RULE = json.load(open(os.path.join(SCOUT, 'rules', 'paint-web.json'), encoding='utf-8'))


def test_selftest():
    assert W.selftest() == 0


def test_thresholds_only_in_data():
    """Числа порогов из paint-web.json не зашиты в коде; порога веса в правиле похожести нет (он один — rt-weight.json)."""
    for k, t in RULE['thresholds'].items():
        assert re.search(r'(?<![\w.])' + re.escape(str(t['value'])) + r'(?![\w.])', SRC['paint_web.py']) is None, f'порог {k} зашит в коде'
    assert 'max_bytes' not in json.dumps(RULE), 'порог веса — только в rules/rt-weight.json'
    assert 'weight_rule()' in SRC['paint_web.py']
    w = json.load(open(os.path.join(SCOUT, 'rules', 'rt-weight.json')))
    assert w['max_bytes'] == 5 * 1024 * 1024  # P-040


def test_no_product_ids():
    """В коде и правиле — ни одного ID товара (номер_длинное число)."""
    for name, text in list(SRC.items()) + [('paint-web.json', json.dumps(RULE))]:
        assert re.search(r'\b\d{4,7}_\d{12,}\b', text) is None, name


def test_judge_follows_rule():
    """«Прошёл» решает правило из данных: хорошие мерки — прошёл; одна мерка за порогом — не прошёл, причина словами с именем мерки."""
    good = {'de00_p95': 1.0, 'ssim': 0.99, 'silhouette_iou': 0.999}
    for bad_key, bad_val in (('ssim', 0.5), ('de00_p95', 99.0), ('silhouette_iou', 0.5)):
        for ok in (True, False):
            m = dict(good, **({} if ok else {bad_key: bad_val}))
            metrics = {k: {'value': m[k], 'threshold': RULE['thresholds'][k]['value'], 'op': RULE['thresholds'][k]['op']} for k in m}
            metrics['bytes'] = {'name': 'bytes', 'value': 900000, 'threshold': 5 * 1024 * 1024, 'op': '<='}
            with tempfile.TemporaryDirectory() as t:
                c = PS.write_check(PS.stage_dir(t, 'x', W.STAGE), W.STAGE, 'x', passed=None,
                                   metric={'name': 'de00_mean', 'value': 0.5, 'threshold': RULE['thresholds']['de00_mean']['value'], 'op': RULE['thresholds']['de00_mean']['op']},
                                   metrics=metrics)
            assert c['passed'] is ok, (bad_key, ok, c)
            if not ok:
                assert bad_key in c['reason'], c['reason']


def test_overweight_is_reported():
    """Тяжелее порога веса — не прошёл, с причиной (проверка по check.json, без сборки)."""
    with tempfile.TemporaryDirectory() as t:
        c = PS.write_check(PS.stage_dir(t, 'x', W.STAGE), W.STAGE, 'x', passed=None,
                           metric={'name': 'bytes', 'value': 6 * 1024 * 1024, 'threshold': 5 * 1024 * 1024, 'op': '<='})
    assert c['passed'] is False and 'bytes' in c['reason']


if __name__ == '__main__':
    for n, f in sorted(globals().items()):
        if n.startswith('test_') and callable(f):
            f()
            print('ok', n)
    print('ALL OK')
