#!/usr/bin/env python3
"""Тесты ворот «этап красит только заявленную маску» (stage_mask_gate.py, T-20261124-23/г): синтетика, без Salad и GPU.
Запуск: python tools/scout/salad/trellis/tests_stage_mask_gate.py   (нужны numpy, trimesh, pillow, scipy)"""
import json
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stage_mask_gate as G  # noqa: E402

R = G.load_rules()
T = 64


def box_glb(path, tex):
    """Два квадрата: «лицо» (нормаль +Z) в левой половине карты, «бок» (нормаль +X) — в правой; один материал с картой tex."""
    import trimesh
    from trimesh.visual import TextureVisuals
    from trimesh.visual.material import PBRMaterial
    from PIL import Image
    V = np.array([[0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1], [1, 0, 0], [1, 1, 0]], float)
    F = np.array([[0, 1, 2], [0, 2, 3], [1, 4, 5], [1, 5, 2]])
    # одна вершина на угол: UV по половинам карты (лицо слева, бок справа)
    Vx = np.concatenate([V[F[0]], V[F[1]], V[F[2]], V[F[3]]])
    Fx = np.arange(12).reshape(4, 3)
    uv = np.array([[0.0, 0.0], [0.5, 0.0], [0.5, 1.0],  [0.0, 0.0], [0.5, 1.0], [0.0, 1.0],
                   [0.5, 0.0], [1.0, 0.0], [1.0, 1.0],  [0.5, 0.0], [1.0, 1.0], [0.5, 1.0]])
    m = trimesh.Trimesh(vertices=Vx, faces=Fx, process=False)
    m.visual = TextureVisuals(uv=uv, material=PBRMaterial(baseColorTexture=Image.fromarray(tex)))
    trimesh.Scene([m]).export(path)


def make(tmp, tex_b, tex_a, prov):
    from PIL import Image
    vis = os.path.join(tmp, '06-visible')
    os.makedirs(vis, exist_ok=True)
    Image.fromarray(prov).save(os.path.join(vis, 'prov.png'))
    box_glb(os.path.join(tmp, 'b.glb'), tex_b)
    box_glb(os.path.join(tmp, 'a.glb'), tex_a)
    return os.path.join(tmp, 'b.glb'), os.path.join(tmp, 'a.glb'), vis


def base():
    rng = np.random.RandomState(1)
    tex = rng.randint(30, 220, (T, T, 3)).astype(np.uint8)
    prov = np.zeros((T, T), np.uint8)
    prov[:, :16] = 1            # лицо: прямое фото
    prov[:, 16:32] = 3          # лицо: заполненная дыра этапа 6 (тоже «фото» по правилу)
    prov[:, 32:48] = 4          # бок: synth
    return tex, prov


def t_arrays():
    tex, prov = base()
    a = tex.copy()
    d = np.full((T, T), -2.0)
    d[:, :32] = 1.0
    m = G.measure_arrays(tex, a, prov, d, R)
    assert m['status'] == 'ok' and m['photo_changed'] == 0 and m['synth_changed'] == 0 and m['face_changed'] == 0, m
    a[3, 3] ^= 1                                        # один фото-тексель (prov 1) — на единицу в одном канале
    a[5, 40] ^= 1                                       # synth
    a[7, 60] ^= 1                                       # прочее (prov 0)
    m = G.measure_arrays(tex, a, prov, d, R)
    assert (m['photo_changed'], m['synth_changed'], m['other_changed'], m['face_changed'], m['face_nonphoto_changed']) == (1, 1, 1, 1, 0), m
    assert m['photo_total'] == T * 32 and m['synth_total'] == T * 16
    assert m['by_prov']['1'] == [T * 16, 1] and m['by_prov']['4'] == [T * 16, 1] and m['by_prov']['3'][1] == 0, m['by_prov']
    assert G.measure_arrays(tex, a[:, :-1], prov, d, R)['status'] == 'shape'
    assert G.measure_arrays(tex, a, None, d, R)['status'] == 'no_prov'
    assert G.measure_arrays(tex, a, prov, None, R)['face_total'] is None
    g = G.gate(G.measure_arrays(tex, a, prov, d, R), R)
    assert g['ok'] is False and 'photo_changed 1' in g['violations'][0], g
    print('ok arrays')


def t_files():
    tex, prov = base()
    with tempfile.TemporaryDirectory() as tmp:
        a = tex.copy()
        a[:, 40:48] = (10, 20, 30)                      # меняем только synth-полосу бока: лицо и фото целы
        b, af, vis = make(tmp, tex, a, prov)
        m = G.measure(b, af, vis, R, front=(2, 1))
        assert m['status'] == 'ok' and m['photo_changed'] == 0 and m['synth_changed'] > 0 and m['face_changed'] == 0, m
        assert m['face_total'] and m['face_total'] > 0
        assert G.gate(m, R)['ok'] is True
        a2 = tex.copy()
        a2[10:20, 2:10] = (1, 2, 3)                     # фото-тексели лица
        b, af, vis = make(os.path.join(tmp, 'x'), tex, a2, prov)
        m = G.measure(b, af, vis, R, front=(2, 1))
        g = G.gate(m, R)
        assert m['photo_changed'] > 0 and m['face_changed'] > 0 and g['ok'] is False, (m, g)
        # без оси лица: лицо не измерено, остальное считается
        m = G.measure(b, af, vis, R, front=None)
        assert m['status'] == 'ok' and m['face_changed'] is None and m['photo_changed'] > 0, m
        # нет prov.png — не измерено (= отказ), не тихий пропуск
        os.remove(os.path.join(vis, 'prov.png'))
        m = G.measure(b, af, vis, R, front=(2, 1))
        g = G.gate(m, R)
        assert m['status'] == 'unmeasured' and g['ok'] is None and g['unmeasured'] is True, (m, g)
        # нет файла — не исключение
        assert G.measure(os.path.join(tmp, 'нет.glb'), af, vis, R)['status'] == 'unmeasured'
    print('ok files')


def t_attach_chain():
    tex, prov = base()
    with tempfile.TemporaryDirectory() as tmp:
        sd = os.path.join(tmp, 'sku1')
        os.makedirs(sd)
        a = tex.copy()
        a[0, 0] = (9, 9, 9)
        b, af, vis = make(sd, tex, a, prov)
        os.makedirs(os.path.join(sd, '07-fill'))
        os.makedirs(os.path.join(sd, '07-seam'))
        os.replace(b, os.path.join(sd, '06-visible', 'visible.glb'))
        os.replace(af, os.path.join(sd, '07-fill', 'filled.glb'))
        pairs = G.chain_pairs(sd, R)
        assert [p[0] for p in pairs] == ['07'], pairs     # шов/08/07b без выхода — не в цепочке
        res = G.table(tmp, ['sku1'], R)
        assert res['sku1']['07']['m']['status'] == 'ok' and res['sku1']['07']['m']['photo_changed'] == 1, res
        assert 'sku1'[-10:] in G.table_md(res, R)
        ck = os.path.join(sd, '07-fill', 'check.json')
        json.dump({'passed': True, 'extra': {'k': 1}}, open(ck, 'w'))
        G.attach(os.path.join(sd, '07-fill'), res['sku1']['07']['m'], res['sku1']['07']['gate'])
        d = json.load(open(ck))
        assert d['passed'] is True and d['extra']['k'] == 1 and d['extra']['stage_mask']['gate']['ok'] is False, d
        G.attach(os.path.join(sd, '07-seam'), {}, {})   # нет check.json — тихо ничего
        assert not os.path.exists(os.path.join(sd, '07-seam', 'check.json'))
    print('ok attach/chain')


def t_allowed_contract():
    """Контракт «маска разрешено менять» (T-20261124-23/в2): изменение внутри маски — ворота ok (даже в фото-тексель); вне маски — отказ; нет маски — строго по фото."""
    tex, prov = base()
    with tempfile.TemporaryDirectory() as tmp:
        a = tex.copy()
        a[10:12, 2:4] = (1, 2, 3)                       # фото-тексели prov 1 — этап заявит их изменяемыми (слабое фото)
        b, af, vis = make(tmp, tex, a, prov)
        m0 = G.measure(b, af, vis, R, front=(2, 1))
        assert m0['mask'] == 'missing' and G.gate(m0, R)['ok'] is False        # маски нет — строго: фото тронуто
        allowed = np.zeros((T, T), bool)
        allowed[8:14, 0:8] = True
        G.write_allowed(tmp, [allowed], R)
        assert os.path.exists(os.path.join(tmp, 'changed-allowed.png'))
        m1 = G.measure(b, af, vis, R, front=(2, 1))
        g1 = G.gate(m1, R)
        assert m1['mask'] == 'declared' and m1['undeclared_changed'] == 0 and m1['photo_changed'] == 4 and g1['ok'] is True, (m1, g1)
        a[40, 40] = (7, 7, 7)                           # изменение вне маски (synth-полоса) — недекларированное
        b, af, vis = make(tmp, tex, a, prov)
        G.write_allowed(tmp, [allowed], R)
        m2 = G.measure(b, af, vis, R, front=(2, 1))
        g2 = G.gate(m2, R)
        assert m2['undeclared_changed'] == 1 and m2['undeclared_photo_changed'] == 0 and g2['ok'] is False and 'undeclared_changed 1' in g2['violations'][0], (m2, g2)
        assert 'недекл. 1' in G.table_md({'x' * 12: {'07': {'m': m2, 'gate': g2}}}, R)
    print('ok allowed contract')


def t_uncovered_allowed():
    """Заливка непокрытых текселей (texel_pad) разрешена любому этапу: изменение в зазоре развёртки — не «недекларированное»; на покрытом вне маски — по-прежнему отказ."""
    tex, prov = base()
    a = tex.copy()
    a[60:62, 60:62] = (5, 5, 5)                         # зазор развёртки (заливка соседей)
    allowed = np.zeros((T, T), bool)
    unc = np.zeros((T, T), bool)
    unc[58:64, 58:64] = True
    m = G.measure_arrays(tex, a, prov, None, R, allowed, unc)
    assert m['undeclared_changed'] == 0 and R['uncovered_allowed'] is True, m
    a[40, 40] = (7, 7, 7)                               # покрытый тексель вне маски
    m = G.measure_arrays(tex, a, prov, None, R, allowed, unc)
    assert m['undeclared_changed'] == 1, m
    R2 = dict(R, uncovered_allowed=False)
    assert G.measure_arrays(tex, a, prov, None, R2, allowed, unc)['undeclared_changed'] == 5, 'выкл — зазор считается'
    print('ok uncovered allowed')


def t_rules():
    assert R['max_changed']['photo'] == 0 and R['photo_prov'] == [1, 2, 3] and R['synth_prov'] == [4]
    assert [c['stage'] for c in R['chain']] == ['07', '07b', 'seam', '08']
    print('ok rules')


if __name__ == '__main__':
    t_rules()
    t_arrays()
    t_files()
    t_attach_chain()
    t_allowed_contract()
    t_uncovered_allowed()
    print('ВСЕ OK')
