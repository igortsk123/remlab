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


def test_pick_light_best_that_fits():
    """pick_light: кандидаты из правила по порядку, победитель — первый, что влез; ключи gltfpack уходят в build_light; ни один — запасная лестница сайта."""
    calls, fits = [], {}
    real = W.RM.build_light

    def fake(src, dst, size, quality, simplify, ktx2, rule, tex_flags=()):
        key = (size, tuple(tex_flags))
        calls.append((key, bool(rule.get('ladder'))))
        ok = fits.get(key, False)
        return {'ok': ok, 'kind': '' if ok else 'weight', 'bytes': 1000 if ok else 9 * 1048576, 'tried': [{'step': str(size), 'bytes': 1000}], 'probs': []}
    W.RM.build_light = fake
    try:
        cands = [(c['size'], tuple(c['tex_flags'])) for c in RULE['candidates']]
        assert len(cands) >= 2 and RULE['quality'] > 0
        for win in range(len(cands)):
            calls.clear()
            fits.clear()
            fits[cands[win]] = True
            res, label = W.pick_light(b'', 'x.glb', RULE, {'max_bytes': 5 * 1048576, 'ladder': [{'size': 512}]})
            assert res['ok'] and [c[0] for c in calls] == cands[:win + 1], (win, calls)
            assert all(not c[1] for c in calls), 'у кандидатов своя лестница не нужна: шаги — сами кандидаты'
            assert str(cands[win][0]) in label and len(res['steps']) == win + 1
        calls.clear()
        fits.clear()
        res, label = W.pick_light(b'', 'x.glb', RULE, {'max_bytes': 5 * 1048576, 'ladder': [{'size': 512}]})
        assert not res['ok'] and 'лестница сайта' in label and calls[-1][1], 'ни один кандидат не влез — запасная лестница rt-weight'
    finally:
        W.RM.build_light = real


def test_no_ktx_tool_is_failure():
    """Нет утилиты ktx (CI её не ставит): ktx_bin() даёт None, а run_one отказывает check.json с причиной словами — не падает с трассой и не возвращается к JPEG.
    Кэш такого отказа повторно не берётся (поставили утилиту — пересчёт)."""
    old = dict(os.environ)
    try:
        os.environ['KTX'] = '/нет/такого/ktx'
        os.environ['PATH'] = '/нет'
        rule = dict(RULE, ktx_bin='/нет/в/правиле/ktx')
        assert W.ktx_bin() is None and W.ktx_bin(rule) is None
        with tempfile.TemporaryDirectory() as t:
            glb = os.path.join(t, 'x.glb')
            open(glb, 'wb').write(b'not-a-glb')   # до проверки утилиты GLB не открывается
            c = W.run_one(os.path.join(t, 'run'), 'x', glb, rule, {'max_bytes': 5 * 1048576, 'ladder': []})
            assert c['passed'] is False and 'ktx' in c['reason'] and 'install-ktx.sh' in c['reason'], c
            assert c['extra']['ktx2_measured'] is False and c['extra']['no_tool'] is True
            c2 = W.run_one(os.path.join(t, 'run'), 'x', glb, rule, {'max_bytes': 5 * 1048576, 'ladder': []})
            assert c2['extra']['no_tool'] is True and c2['passed'] is False   # снова отказ, а не кэш успеха
        # путь из правила работает: подставная утилита по ktx_bin
        with tempfile.TemporaryDirectory() as t:
            fake = os.path.join(t, 'ktx')
            open(fake, 'w').write('#!/bin/sh\n')
            os.chmod(fake, 0o755)
            assert W.ktx_bin(dict(RULE, ktx_bin=fake)) == fake
    finally:
        os.environ.clear()
        os.environ.update(old)


def test_run_one_picks_first_that_fits_and_passes():
    """run_one: кандидаты по порядку; победитель — первый, что влез И прошёл мерки. «Влез, но не прошёл» не останавливает перебор; никто не прошёл —
    итог — первый из влезших (его же и пересобирают, чтобы файлы и кадры совпали с check.json); никто не влез — запасная лестница сайта. Сборку и кадры подменяем."""
    cands = [c for c in RULE['candidates']]
    assert len(cands) >= 3
    calls = []
    real_attempt, real_ktx = W._attempt, W.ktx_bin

    def fake_factory(fits, passes):
        def fake(run, sku, glb, rule, weight, ktx, t0, earlier, fallback, fp):
            c = rule['candidates'][0]
            key = (c['size'], tuple(c['tex_flags']))
            calls.append((key, fallback, len(earlier)))
            if fallback:
                return {'passed': False, 'reason': 'лестница', 'extra': {'fits': False, 'texture_step': 'лестница сайта'}}
            f, ps = key in fits, key in passes
            return {'passed': f and ps, 'reason': '' if (f and ps) else ('не влез' if not f else 'ssim'), 'extra': {'fits': f, 'texture_step': str(key)}}
        return fake
    keys = [(c['size'], tuple(c['tex_flags'])) for c in cands]
    W.ktx_bin = lambda rule=None: '/bin/true'
    try:
        with tempfile.TemporaryDirectory() as t:
            glb = os.path.join(t, 'x.glb')
            open(glb, 'wb').write(b'not-a-glb')
            wt = {'max_bytes': 5 * 1048576, 'ladder': []}
            # 0-й влез, но не прошёл; 1-й влез и прошёл → победил 1-й
            W._attempt = fake_factory({keys[0], keys[1]}, {keys[1]})
            calls.clear()
            c = W.run_one(os.path.join(t, 'a'), 'x', glb, RULE, wt, force=True)
            assert c['passed'] and [k for k, _, _ in calls] == keys[:2], calls
            # 0-й не влез, 1-й влез и прошёл
            W._attempt = fake_factory({keys[1]}, {keys[1]})
            calls.clear()
            c = W.run_one(os.path.join(t, 'b'), 'x', glb, RULE, wt, force=True)
            assert c['passed'] and [k for k, _, _ in calls] == keys[:2]
            # влезли 1-й и 2-й, не прошёл никто → итог по первому из влезших (1-й), пересобран последним
            W._attempt = fake_factory({keys[1], keys[2]}, set())
            calls.clear()
            c = W.run_one(os.path.join(t, 'c'), 'x', glb, RULE, wt, force=True)
            assert not c['passed'] and calls[-1][0] == keys[1] and not calls[-1][1] and len(calls) == len(keys) + 1, calls
            # никто не влез → запасная лестница сайта
            W._attempt = fake_factory(set(), set())
            calls.clear()
            c = W.run_one(os.path.join(t, 'd'), 'x', glb, RULE, wt, force=True)
            assert not c['passed'] and calls[-1][1] is True and len(calls) == len(keys) + 1, calls
    finally:
        W._attempt, W.ktx_bin = real_attempt, real_ktx


def test_install_ktx_data():
    """tools/ops/install-ktx.sh: версия и контрольные суммы — в ktx-release.json, не в скрипте; установка в домашнюю папку, не в remlab-logs; путь бинаря в правиле совпадает."""
    import subprocess
    ops = os.path.join(HERE, '..', '..', 'ops')
    rel = json.load(open(os.path.join(ops, 'ktx-release.json'), encoding='utf-8'))
    sh = open(os.path.join(ops, 'install-ktx.sh'), encoding='utf-8').read()
    assert rel['sha1'] not in sh and rel['sha256'] not in sh and rel['version'] not in sh, 'версия и суммы — только в данных'
    assert 'sudo' not in re.sub(r'#.*', '', sh) and 'remlab-logs' not in rel['install_dir']
    assert os.path.expanduser(RULE['ktx_bin']) == os.path.join(os.path.expanduser(rel['install_dir']), rel['binary']), 'путь в правиле и в данных релиза должен совпадать'
    if os.path.isfile('/bin/bash'):
        r = subprocess.run(['bash', os.path.join(ops, 'install-ktx.sh'), '--selftest'], capture_output=True, text=True)
        assert r.returncode == 0 and 'ok' in r.stdout, r.stdout + r.stderr


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
