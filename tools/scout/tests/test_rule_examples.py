#!/usr/bin/env python3
"""Положительный и отрицательный пример типа для каждого active-правила реестра (T-20261123-48/2, аудит Codex a-dupes § 3 п.4): правило active
только если есть тест, где оно СРАБАТЫВАЕТ на плохом примере и НЕ срабатывает на хорошем. Имена функций — в rule-registry.json (test_positive / test_negative);
rule_registry_audit находит их через ast. Сети, GPU и ID товаров нет; примеры — типовые заглушки (ящик «комод», сетка формы, названия по классам).
Запуск: python tools/scout/tests/test_rule_examples.py   (нужны numpy, scipy, trimesh, Pillow)"""
import json
import tempfile
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SC = os.path.join(HERE, '..')
sys.path.insert(0, SC)
sys.path.insert(0, os.path.join(SC, 'stablegen'))
sys.path.insert(0, os.path.join(SC, 'salad', 'trellis'))
sys.path.insert(0, os.path.join(SC, '..', 'assets'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_rule_examples')
import numpy as np  # noqa: E402
import trimesh  # noqa: E402
from PIL import Image  # noqa: E402
import mesh_winding as MW  # noqa: E402
import paint_surface_checks as PSC  # noqa: E402
import plan09 as P09  # noqa: E402
import sg_color_transfer as T  # noqa: E402
import material_stage as MS  # noqa: E402

# ящик «комод»: 8 вершин, 12 граней, нормали наружу
BOX_V = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], float)
BOX_F = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]], int)


def _judge(a):
    R = PSC.rules()
    cl = {'top_vs_photo': {'status': 'na', 'why': 'нет'}, 'empty_flat': {'status': 'na'}, 'group_bleed': {'status': 'na'}}
    return PSC.judge(dict(cl, winding=a), R)


# ── R-WIND-09 ────────────────────────────────────────────────────────────────
def test_wind_positive():
    """Хороший ящик (обход согласован, объём наружу): мерка в пороге, судья не режет."""
    j = _judge(MW.analyze(BOX_V, BOX_F))
    assert j['status'] == 'ok' and 'winding' not in (j.get('hard_failed') or []), j


def test_wind_negative():
    """Ящик с одной вывернутой гранью и ящик наизнанку: судья → refused, hard winding."""
    F = BOX_F.copy()
    F[0] = F[0][::-1]
    j = _judge(MW.analyze(BOX_V, F))
    assert j['status'] == 'refused' and 'winding' in j['hard_failed'], j
    j2 = _judge(MW.analyze(BOX_V, BOX_F[:, ::-1]))
    assert j2['status'] == 'refused' and 'winding' in j2['hard_failed'], j2


# ── R-LADDER-02 ──────────────────────────────────────────────────────────────
def _grid(n):
    xs = np.linspace(0, 1, n + 1)
    X, Y = np.meshgrid(xs, xs)
    V = np.stack([X.ravel(), Y.ravel(), (0.1 * np.sin(2 * X) + 0.05 * Y).ravel()], 1)
    UV = np.stack([X.ravel(), Y.ravel()], 1)
    F = []
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            F += [[a, a + 1, a + n + 2], [a, a + n + 2, a + n + 1]]
    return V, np.array(F, np.int64), UV


def _form(path, collapse_rows=0, n=8, size=128):
    V, F, UV = _grid(n)
    UV = UV.copy()
    if collapse_rows:                                                      # вершины нижних рядов — в одну точку атласа: грани без своего текселя
        UV[:(n + 1) * collapse_rows] = 0.5
    m = trimesh.Trimesh(vertices=V, faces=F, process=False)
    u = (np.arange(size) + 0.5) / size
    U, W = np.meshgrid(u, 1.0 - u)
    base = np.stack([(U * 255), (W * 255), np.full_like(U, 128), np.full_like(U, 255)], -1).astype(np.uint8)
    m.visual = trimesh.visual.TextureVisuals(uv=UV, material=trimesh.visual.material.PBRMaterial(baseColorTexture=Image.fromarray(base, 'RGBA'), alphaMode='OPAQUE'))
    m.export(path, file_type='glb')


def test_ladder_positive():
    """Форма лесенки с текселем у каждой грани: этап 02 прошёл, faces_with_texel ≥ порога."""
    d = tempfile.mkdtemp(prefix='ladder-pos-')
    _form(os.path.join(d, 'f-hd.glb'))
    c = T.stage02_form(os.path.join(d, 'run'), 'k', os.path.join(d, 'f-hd.glb'))
    assert c['passed'] and c['metric']['name'] == 'faces_with_texel' and c['metric']['ok'], c


def test_ladder_negative():
    """Форма, где 2 ряда из 8 схлопнуты в точку атласа (≈ 25 % граней без текселя): этап 02 не пройден, мерка названа."""
    d = tempfile.mkdtemp(prefix='ladder-neg-')
    _form(os.path.join(d, 'f-hd.glb'), collapse_rows=2)
    c = T.stage02_form(os.path.join(d, 'run'), 'k', os.path.join(d, 'f-hd.glb'))
    assert not c['passed'] and c['metric']['name'] == 'faces_with_texel' and c['metric']['ok'] is False, c


# ── R-PHOTO-05 ───────────────────────────────────────────────────────────────
def _stage05(root, sku, photo):
    d = os.path.join(root, sku, '05-delight')
    os.makedirs(d, exist_ok=True)
    json.dump({'passed': True, 'extra': {'source_photo': photo}}, open(os.path.join(d, 'check.json'), 'w'))
    return d


def _photos(root):
    pkg, same, other = (os.path.join(root, n) for n in ('pkg.png', 'same.png', 'other.png'))
    open(pkg, 'w').write('ФОТО-ПАКЕТА')
    open(same, 'w').write('ФОТО-ПАКЕТА')                                    # копия по содержимому (другой путь)
    open(other, 'w').write('ДРУГОЕ-ФОТО')
    return pkg, same, other


def test_photo_positive():
    """05 посчитан по тому же фото (sha256 совпал, путь другой) — этап берётся."""
    root = tempfile.mkdtemp(prefix='photo-pos-')
    pkg, same, _ = _photos(root)
    d = _stage05(root, 'a', same)
    assert P09.photo_matches(d, {'photo': pkg}, '05-delight') is True


def test_photo_negative():
    """05 посчитан по ДРУГОМУ фото, или фото стёрто, или не названо — этап не берётся («нет данных»)."""
    root = tempfile.mkdtemp(prefix='photo-neg-')
    pkg, _, other = _photos(root)
    assert P09.photo_matches(_stage05(root, 'b', other), {'photo': pkg}, '05-delight') is False
    assert P09.photo_matches(_stage05(root, 'c', os.path.join(root, 'стёрто.png')), {'photo': pkg}, '05-delight') is False
    assert P09.photo_matches(_stage05(root, 'd', ''), {'photo': pkg}, '05-delight') is False


# ── R-GLOSS-08 ───────────────────────────────────────────────────────────────
def _gloss(name, **params):
    return MS.gloss_of({'name': name, 'params': params}, MS.load_recipes())


def test_gloss_positive():
    """Комод назван глянцевым и лакированным — глянец включается; матовые рецепты щита и дерева ≥ 0,7."""
    assert _gloss('Комод Венда Оранжевый Глянец') is not None
    assert _gloss('Комод', **{'Покрытие': 'лакированный МДФ'}) is not None
    rc = MS.load_recipes()['recipes']
    assert all(rc[c]['roughness'] >= 0.7 for c in ('ldsp', 'mdf_film', 'wood_solid', 'wood_veneer'))


def test_gloss_negative():
    """Комод без слов глянца, «лакон…» (часть слова) и «глянец… полуматовая» — остаются матовыми."""
    assert _gloss('Комод Монблан', **{'Материал фасада': 'МДФ в пленке ПВХ'}) is None
    assert _gloss('Комод Лаконика') is None
    assert _gloss('Комод «Глянец» полуматовая') is None


if __name__ == '__main__':
    n = 0
    for k, v in sorted(globals().items()):
        if k.startswith('test_') and callable(v):
            v()
            n += 1
            print('  ✓', k)
    print('OK: test_rule_examples %d проверок' % n)
