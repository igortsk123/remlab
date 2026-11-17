#!/usr/bin/env python3
"""Растения-декор кашпо и ваз (T-20261117-07, владелец TG 1307): реестр `data/flat3d/plants.json` и лёгкие копии `public/flat3d/plants/`.

Проверяем без сети и платного:
  • 4–6 моделей, id уникальны, тип каждой — из `fit`, каждый носитель `hosts` — на тип, у которого есть модели;
  • источник каждой модели — `data/flat3d/plants/<asset>/source.json`: лицензия CC0-1.0, страница, авторы, sha256 файлов;
  • лёгкая копия каждой модели лежит, весит ≤ `limits.maxBytes`, треугольников ≤ `limits.maxTris`, sha256 совпадает со списком
    `manifest.json`, версия набора (`rev`) та же, что в реестре; лишних записей в списке нет;
  • `stand_up` — растение стоит: вытянутая форма (ветка лежала) встаёт вертикально тонким концом вниз, низ в нуле, основание на оси.
Запуск: python -m pytest tools/assets/tests/test_plants.py -q   (или python …/test_plants.py)"""
import hashlib
import json
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import plant_from_scan as PS  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
CFG = PS.load_config()
OUT = os.path.join(ROOT, 'public', 'flat3d', 'plants')


def _manifest():
    with open(os.path.join(OUT, 'manifest.json'), encoding='utf-8') as f:
        return json.load(f)


def test_config_shape():
    plants = CFG['plants']
    assert 4 <= len(plants) <= 6
    ids = [p['id'] for p in plants]
    assert len(set(ids)) == len(ids)
    assert CFG['licence'] == 'CC0-1.0'
    for p in plants:
        assert p['kind'] in CFG['fit'], p['id']
        assert p['styles'], p['id']
    kinds = {p['kind'] for p in plants}
    for role, kind in CFG['hosts'].items():
        assert kind in kinds, f'носитель «{role}» — тип {kind} без моделей'
    assert {'green', 'dry'} <= kinds                      # и кашпо, и вазе есть что ставить


def test_sources_cc0_with_registry():
    for asset in sorted({p['asset'] for p in CFG['plants']}):
        with open(os.path.join(ROOT, 'data', 'flat3d', 'plants', asset, 'source.json'), encoding='utf-8') as f:
            s = json.load(f)
        assert s['licence'] == 'CC0-1.0' and s['site'] == 'Poly Haven', asset
        assert s['pageUrl'] == f'https://polyhaven.com/a/{asset}', asset
        assert s['authors'] and s['sha256'] and all(len(h) == 64 for h in s['sha256'].values()), asset


def test_light_copies_within_budget_and_listed():
    man = _manifest()
    assert man['rev'] == CFG['rev']
    rows = {r['id']: r for r in man['plants']}
    assert set(rows) == {p['id'] for p in CFG['plants']}   # ни лишних, ни недостающих
    lim = CFG['limits']
    for p in CFG['plants']:
        path = os.path.join(OUT, f"{p['id']}.glb")
        data = open(path, 'rb').read()
        assert data[:4] == b'glTF', p['id']
        assert struct.unpack('<I', data[8:12])[0] == len(data), p['id']   # длина в заголовке GLB — настоящая
        assert len(data) <= lim['maxBytes'], f"{p['id']}: {len(data)} байт"
        r = rows[p['id']]
        assert r['bytes'] == len(data) and r['sha256'] == hashlib.sha256(data).hexdigest(), p['id']
        assert 0 < r['tris'] <= lim['maxTris'], p['id']
        assert r['kind'] == p['kind'] and r['asset'] == p['asset'] and r['part'] == p['part'], p['id']


def test_stand_up_lying_branch():
    rng = np.random.default_rng(3)
    t = rng.random(4000)
    # ветка лежит вдоль X: низ (t≈0) — тонкий стебель радиуса 0,01, верх (t≈1) — крона радиуса 0,08; сдвинута от нуля
    r = 0.01 + 0.07 * t ** 2
    ang = rng.random(4000) * 2 * np.pi
    v = np.stack([t * 0.8 + 5.0, r * np.cos(ang) + 2.0, r * np.sin(ang) - 3.0], axis=1)
    out = PS.stand_up(v)
    assert abs(out[:, 1].min()) < 1e-9                       # низ — в нуле
    assert 0.75 < out[:, 1].max() < 0.85                     # вытянулась вдоль вертикали
    assert out[out[:, 1] < 0.1][:, [0, 2]].std() < out[out[:, 1] > 0.7][:, [0, 2]].std()   # тонкий конец внизу, крона вверху
    base = out[out[:, 1] <= 0.08 * out[:, 1].max()]
    assert abs(base[:, 0].mean()) < 1e-9 and abs(base[:, 2].mean()) < 1e-9   # основание на оси


def test_stand_up_squat_plant_untouched():
    rng = np.random.default_rng(5)
    v = np.stack([rng.random(2000) * 0.5, rng.random(2000) * 0.4 + 1.0, rng.random(2000) * 0.5], axis=1)   # приземистая листва
    out = PS.stand_up(v)
    assert abs(out[:, 1].min()) < 1e-9
    assert abs(np.ptp(out[:, 1]) - 0.4) < 0.01               # высота та же — не переворачивалась и не вытягивалась


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-q', '-p', 'no:cacheprovider']))
