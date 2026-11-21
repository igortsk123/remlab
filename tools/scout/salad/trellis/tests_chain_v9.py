#!/usr/bin/env python3
"""Тесты склейки шагов цепочки (`chain_v9.py`, T-20261119-88): порядок, передача выхода на вход, проверка формы на каждом шаге, остановка при сбое, `chain.json`; плюс `form_guard` на малом GLB.

  python tools/scout/salad/trellis/tests_chain_v9.py   # нужны numpy, trimesh
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import chain_v9 as C  # noqa: E402


def _glb(path, shift=0.0, uv_shift=0.0, tex=64):
    import trimesh
    from PIL import Image
    V = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float)
    V[2] += shift
    F = np.array([[0, 1, 2], [0, 2, 3]])
    UV = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float) + uv_shift
    img = Image.fromarray(np.full((tex, tex, 3), 128, np.uint8))
    m = trimesh.Trimesh(vertices=V, faces=F, process=False, visual=trimesh.visual.TextureVisuals(uv=UV, material=trimesh.visual.material.PBRMaterial(baseColorTexture=img)))
    trimesh.Scene(m).export(path)


def t_form_guard():
    d = tempfile.mkdtemp()
    try:
        a, b, c, e = (os.path.join(d, n) for n in ('a.glb', 'b.glb', 'c.glb', 'e.glb'))
        _glb(a)
        _glb(b, tex=128)                                  # другая карта, та же форма → ок
        _glb(c, shift=0.01)                               # сдвинута вершина → отказ
        _glb(e, uv_shift=0.001)                           # сдвинут UV → отказ
        assert C.form_guard(a, b)['ok']
        g = C.form_guard(a, c)
        assert not g['ok'] and g['max_diff_vertices'] > 1e-3, g
        assert not C.form_guard(a, e)['ok']
    finally:
        shutil.rmtree(d)


def _copy_step(name, log):
    def fn(glb, d):
        log.append((name, glb))
        out = os.path.join(d, name + '.glb')
        shutil.copyfile(glb, out)
        return out
    return name, fn


def t_chain_order_and_json():
    d = tempfile.mkdtemp()
    try:
        src = os.path.join(d, 'in.glb')
        _glb(src)
        log, measured = [], []
        steps = [_copy_step('s2', log), _copy_step('s3', log), _copy_step('s4', log)]
        res = C.run_chain(steps, src, os.path.join(d, 'out'), lambda g, dd, n: measured.append((n, g)) or {'n': n})
        assert res['ok'] and res['failed_step'] is None, res
        assert [n for n, _ in log] == ['s2', 's3', 's4']
        assert log[0][1] == src and log[1][1].endswith('s2.glb') and log[2][1].endswith('s3.glb'), log      # выход шага — вход следующего
        assert [n for n, _ in measured] == ['s1-mv12', 's2', 's3', 's4'], measured                          # мерки на каждом шаге, включая вход
        assert res['final'].endswith('s4.glb')
        assert all(s['form_guard']['ok'] for s in res['steps'][1:])
        j = json.load(open(os.path.join(d, 'out', 'chain.json'), encoding='utf-8'))
        assert [s['name'] for s in j['steps']] == ['s1-mv12', 's2', 's3', 's4'] and j['ok']
    finally:
        shutil.rmtree(d)


def t_chain_stops_on_form_change():
    d = tempfile.mkdtemp()
    try:
        src = os.path.join(d, 'in.glb')
        _glb(src)
        log = []

        def bad(glb, dd):
            log.append('bad')
            out = os.path.join(dd, 'bad.glb')
            _glb(out, shift=0.05)
            return out
        steps = [_copy_step('s2', log), ('s3', bad), _copy_step('s4', log)]
        res = C.run_chain(steps, src, os.path.join(d, 'out'), lambda g, dd, n: {})
        assert not res['ok'] and res['failed_step'] == 's3' and res['final'] is None, res
        assert [x if isinstance(x, str) else x[0] for x in log] == ['s2', 'bad'], log                          # s4 не запускался
        assert res['steps'][-1]['error'] == 'форма/развёртка изменились'
    finally:
        shutil.rmtree(d)


def t_chain_stops_on_exception():
    d = tempfile.mkdtemp()
    try:
        src = os.path.join(d, 'in.glb')
        _glb(src)

        def boom(glb, dd):
            raise RuntimeError('шаг упал')
        res = C.run_chain([('s2', boom), ('s3', lambda g, dd: g)], src, os.path.join(d, 'out'), lambda g, dd, n: {})
        assert not res['ok'] and res['failed_step'] == 's2' and 'шаг упал' in res['steps'][-1]['error'], res
        assert len(res['steps']) == 2                                   # вход + упавший шаг, третий не пытался
    finally:
        shutil.rmtree(d)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith('t_') and callable(v)]
    for t in tests:
        t()
        print('ok', t.__name__)
    print('all ok')
    return 0


if __name__ == '__main__':
    sys.exit(main())
