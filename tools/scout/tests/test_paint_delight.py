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
    for k in ('follow_max', 'na_spread_below', 'na_amp_below', 'tone_split_max', 'min_cluster_share', 'lf_sigma'):
        v = RULE['light'][k]
        assert re.search(r'(?<![\w.])' + re.escape(str(v)) + r'(?![\w.])', code) is None, f'порог light.{k}={v} зашит в коде'
    for k in ('hf_corr_min', 'hf_energy_min', 'sigma', 'metric_side', 'min_mask_px'):
        assert re.search(r'(?<![\w.])' + re.escape(str(RULE[k])) + r'(?![\w.])', code) is None, f'{k}={RULE[k]} зашит в коде'
    assert RULE['light']['follow_max'] <= 0.5 and RULE['sigma'] <= 0.03   # решение директора 21.11: σ 2–3 %, следование ≤ 0,5
    assert D.METRIC == 'iid_follow_ratio'                                 # честное имя: «следование IID», не «свет снят»


def test_no_product_ids():
    """В коде и правиле — ни одного ID товара (номер_длинное число)."""
    pat = re.compile(r'\b\d{4,}_\d{6,}\b')
    assert not pat.search(SRC) and not pat.search(json.dumps(RULE))


def test_follow_ratio_ignores_albedo_pattern():
    """Рисунок albedo (плавная смена тона ткани) — не свет: «результат/фото» на нём краснеет (Сакура 0,55), iid_follow_ratio — нет."""
    import numpy as np
    rules = D.load_rules()
    n = 320
    yy, xx = np.mgrid[0:n, 0:n]
    mask = ((xx - n / 2) / (0.45 * n)) ** 2 + ((yy - n / 2) / (0.4 * n)) ** 2 < 1
    pattern = 1 + 0.10 * np.sin(2 * np.pi * xx / (n * 0.6))           # тон ткани меняется плавно — это albedo
    light = 1 + 0.90 * (xx / n - 0.5)                                # плавный свет слева→справа
    base = np.array([200.0, 150.0, 150.0])
    alb = np.clip(base * pattern[..., None], 0, 255).astype(np.uint8)
    photo = np.clip(alb * light[..., None], 0, 255).astype(np.uint8)
    g = rules['bg_grey']
    alb[~mask], photo[~mask] = g, g
    res = D.soft_transfer(photo, alb, mask, rules['sigma'])
    _, _, mm = D.evaluate(photo, res, alb, mask, rules)
    assert not mm['light_na'] and mm['follow_ratio'] <= rules['light']['follow_max'], mm
    assert mm['photo_spread_ratio'] > mm['follow_ratio'] + 0.1, mm       # прежняя мерка рисунок засчитала бы как неснятый свет
    assert mm['light_amp_iid'] > mm['light_resid'], mm


def test_photo_only_from_camera():
    """Общее правило конвейера: фото этапа 05 — только из пути, записанного этапом 04; «фото не то, что у камеры», нет пути, камера не прошла → отказ с причиной, без картинки."""
    import tempfile
    import numpy as np
    from PIL import Image
    rules = D.load_rules()
    boom = lambda *a: (_ for _ in ()).throw(AssertionError('при отказе модель не нужна'))  # noqa: E731
    with tempfile.TemporaryDirectory(prefix='delight-cam-') as t:
        cam_photo, other = os.path.join(t, 'cam.png'), os.path.join(t, 'vyb.png')
        for p in (cam_photo, other):
            Image.fromarray(np.full((40, 40, 4), 255, np.uint8), 'RGBA').save(p)
        run = os.path.join(t, 'run')

        def cam(sku, passed=True, **extra):
            D.PS.write_check(D.PS.stage_dir(run, sku, D.CAMERA_STAGE), D.CAMERA_STAGE, sku, passed, None, '' if passed else 'не легла', **extra)

        cam('a', photo=cam_photo)
        cam('nopath')
        cam('failed', passed=False, photo=cam_photo)
        cam('gone', photo=os.path.join(t, 'нет-такого.png'))
        assert D.camera_photo(run, 'a') == cam_photo and D.camera_photo(run, 'a', cam_photo) == cam_photo
        for sku, declared, word in (('a', other, 'фото не то'), ('nopath', None, 'не записал путь'), ('failed', None, 'камера не прошла'),
                                    ('gone', None, 'не найдено'), ('nocam', None, 'не посчитана')):
            doc, cached = D.run_one(sku, run, rules, declared, model_fn=boom)
            assert not cached and doc['passed'] is False and doc['extra']['refused'] and word in doc['reason'] and not doc['outputs'], (sku, doc['reason'])
            assert not os.path.exists(os.path.join(run, sku, D.STAGE, 'delight.rgba.png'))
    # свой путь в обход камеры невозможен: публичного входа с произвольным файлом нет
    assert 'path' not in D.run_one.__code__.co_varnames[:D.run_one.__code__.co_argcount]


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
