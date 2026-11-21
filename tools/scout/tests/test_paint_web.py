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


def test_decode_web_swaps_ktx2_for_png():
    """decode_web: KTX2-картинка web.glb заменяется PNG от утилиты ktx, KHR_texture_basisu уходит, GLB читается. Утилита — подставная (пишет PNG 4×4), бинарь не нужен."""
    import struct
    import runtime_mesh as RM
    from PIL import Image
    with tempfile.TemporaryDirectory() as t:
        fake = os.path.join(t, 'ktx')
        open(fake, 'w').write(f'#!{sys.executable}\nimport sys\nfrom PIL import Image\nImage.new("RGB", (4, 4), (200, 30, 30)).save(sys.argv[-1])\n')
        os.chmod(fake, 0o755)
        ktx2 = b'\xabKTX 20\xbb\r\n\x1a\n' + b'\0' * 20
        js = {'asset': {'version': '2.0'}, 'buffers': [{'byteLength': len(ktx2)}], 'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(ktx2)}],
              'images': [{'bufferView': 0, 'mimeType': 'image/ktx2'}], 'textures': [{'extensions': {'KHR_texture_basisu': {'source': 0}}}],
              'extensionsUsed': ['KHR_texture_basisu', 'KHR_mesh_quantization'], 'extensionsRequired': ['KHR_texture_basisu']}
        web, out = os.path.join(t, 'web.glb'), os.path.join(t, 'real.glb')
        open(web, 'wb').write(RM.write_glb(js, ktx2))
        ok, why, info = W.decode_web(web, out, fake, t)
        assert ok, why
        js2, b2 = RM.parse_glb(open(out, 'rb').read())
        im = js2['images'][0]
        assert im['mimeType'] == 'image/png' and Image.open(__import__('io').BytesIO(RM.image_bytes(im, js2, b2))).size == (4, 4)
        assert js2['textures'][0] == {'source': 0}, js2['textures']
        assert js2['extensionsUsed'] == ['KHR_mesh_quantization'] and 'extensionsRequired' not in js2
        assert js2['buffers'][0]['byteLength'] <= len(b2) < js2['buffers'][0]['byteLength'] + 4 and info['size'] == [4, 4]   # блок выровнен до 4 байт — по спецификации допустимо
        # без KTX2-картинок — отказ словами, не молчание
        js3 = {'asset': {'version': '2.0'}, 'buffers': [{'byteLength': 4}], 'images': [{'bufferView': 0, 'mimeType': 'image/jpeg'}], 'bufferViews': [{'buffer': 0, 'byteLength': 4}]}
        open(web, 'wb').write(RM.write_glb(js3, b'\0\0\0\0'))
        ok, why, _ = W.decode_web(web, out, fake, t)
        assert not ok and 'нет KTX2' in why
        # утилита сломалась (код ≠ 0) — отказ с её сообщением
        bad = os.path.join(t, 'ktxbad')
        open(bad, 'w').write(f'#!{sys.executable}\nimport sys\nsys.stderr.write("boom\\n")\nsys.exit(3)\n')
        os.chmod(bad, 0o755)
        open(web, 'wb').write(RM.write_glb(js, ktx2))
        ok, why, _ = W.decode_web(web, out, bad, t)
        assert not ok and 'boom' in why


def test_no_ktx_tool_is_failure():
    """Нет утилиты ktx — ktx_bin() даёт None (этап тогда не проходит с причиной, а не возвращается к JPEG)."""
    old = dict(os.environ)
    try:
        os.environ['KTX'] = '/нет/такого/ktx'
        os.environ['PATH'] = '/нет'
        assert W.ktx_bin() is None
    finally:
        os.environ.clear()
        os.environ.update(old)


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
