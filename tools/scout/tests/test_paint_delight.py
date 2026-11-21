#!/usr/bin/env python3
"""Этап 05 «снять свет» (paint_delight.py, T-20261121-160/3): на синтетике (эллипс со «стёжкой» и плавным светом, модель подменена «идеальным» albedo) — свет снят, стёжка цела,
размер и альфа те же, мало света → N/A без красного; пороги — только в rules/paint-delight.json, ID товаров в коде нет; в check.json независимая проверка `pending`.
Нужны numpy, pillow, scipy (torch/diffusers не нужны). Запуск: python tools/scout/tests/test_paint_delight.py"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.join(HERE, '..')
sys.path.insert(0, SCOUT)
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_paint_delight')
import paint_delight as D  # noqa: E402

SRC = open(os.path.join(SCOUT, 'paint_delight.py'), encoding='utf-8').read()
RULE = json.load(open(os.path.join(SCOUT, 'rules', 'paint-delight.json'), encoding='utf-8'))


def test_selftest():
    assert D.selftest() == 0


def test_thresholds_only_in_data():
    """Числа порогов и параметров мерки из paint-delight.json не зашиты в коде (кроме 0/1 и общих констант)."""
    code = SRC.split('# ---------- самопроверка')[0]      # самопроверка на синтетике — не рабочий код, свои числа в ней допустимы
    code = re.sub(r'""".*?"""', '', code, flags=re.S)
    code = re.sub(r'#.*', '', code)
    code = '\n'.join(ln for ln in code.splitlines() if '255.0 + 0.5' not in ln)   # округление при переводе в sRGB — математика, не порог
    for k in ('ratio_max', 'na_spread_below', 'tone_split_max', 'min_cluster_share', 'lf_sigma'):
        v = RULE['light'][k]
        assert re.search(r'(?<![\w.])' + re.escape(str(v)) + r'(?![\w.])', code) is None, f'порог light.{k}={v} зашит в коде'
    for k in ('hf_corr_min', 'hf_energy_min', 'sigma', 'metric_side', 'min_mask_px'):
        assert re.search(r'(?<![\w.])' + re.escape(str(RULE[k])) + r'(?![\w.])', code) is None, f'{k}={RULE[k]} зашит в коде'
    assert RULE['light']['ratio_max'] <= 0.5 and RULE['sigma'] <= 0.03   # решение директора 21.11: σ 2–3 %, ratio ≤ 0,5


def test_no_product_ids():
    """В коде и правиле — ни одного ID товара (номер_длинное число)."""
    pat = re.compile(r'\b\d{4,}_\d{6,}\b')
    assert not pat.search(SRC) and not pat.search(json.dumps(RULE))


def test_rules_required():
    """Нет ключа правила — падаем, а не берём умолчание из кода."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix='delight-rules-') as t:
        p = os.path.join(t, 'r.json')
        broken = dict(RULE)
        del broken['hf_corr_min']
        json.dump(broken, open(p, 'w'))
        try:
            D.load_rules(p)
        except KeyError:
            return
        raise AssertionError('load_rules должен падать без ключа')


if __name__ == '__main__':
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            n += 1
            print('ok', name)
    print(f'{n} тестов ок')
