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
    assert 8 <= len(plants) <= 16
    ids = [p['id'] for p in plants]
    assert len(set(ids)) == len(ids)
    assert CFG['licence'] == 'CC0-1.0'
    for p in plants:
        assert p['kind'] in CFG['fit'] and set(CFG['fit'][p['kind']]) == {'floor', 'table'}, p['id']
        assert p['styles'], p['id']
    kinds = {p['kind'] for p in plants}
    for role, kind in CFG['hosts'].items():
        assert kind in kinds, f'носитель «{role}» — тип {kind} без моделей'
    assert {'green', 'dry'} <= kinds                      # и кашпо, и вазе есть что ставить


def test_sources_cc0_with_registry():
    for asset in sorted({p['asset'] for p in CFG['plants']}):
        with open(os.path.join(ROOT, 'data', 'flat3d', 'plants', asset, 'source.json'), encoding='utf-8') as f:
            s = json.load(f)
        assert s['licence'] == 'CC0-1.0', asset
        if s['site'] == 'Poly Haven':
            assert s['pageUrl'] == f'https://polyhaven.com/a/{asset}', asset
        else:                                              # свой букет, собранный кодом: ссылка — на сам генератор в репо
            assert s['site'] == 'own' and os.path.isfile(os.path.join(ROOT, s['pageUrl'])), asset
        assert s['authors'] and s['sha256'] and all(len(h) == 64 for h in s['sha256'].values()), asset


def test_vessels_have_fit_and_mounts():
    """У каждого носителя есть растения на оба места (пол, стол) — иначе носитель останется пустым."""
    for role, kind in CFG['hosts'].items():
        for mount in ('floor', 'table'):
            assert any(p['kind'] == kind and mount in (p.get('mounts') or [mount]) for p in CFG['plants']), f'{role}: нет растений для «{mount}»'
    for p in CFG['plants']:
        assert set(p.get('mounts') or ['floor', 'table']) <= {'floor', 'table', 'shelf'}, p['id']
        assert p.get('minThroatCm', 0) <= p.get('maxThroatCm', 1e9), p['id']


def test_procedural_bouquets_deterministic():
    """Свои букеты: одна сборка дважды даёт то же самое (зерно — от id), бюджет не превышен."""
    import plant_procedural as PP
    for p in [q for q in CFG['plants'] if q.get('builder') == 'procedural']:
        a, b = PP.MAKERS[p['maker']](__import__('numpy').random.default_rng(1)), PP.MAKERS[p['maker']](__import__('numpy').random.default_rng(1))
        assert len(a.f) == len(b.f) and len(a.f) <= CFG['limits']['maxTris'], p['id']
        assert (np.array(a.v) == np.array(b.v)).all(), p['id']


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
        assert r['kind'] == p['kind'] and r['asset'] == p['asset'] and r['part'] == (p.get('part') or p.get('maker') or ','.join(p['parts'])), p['id']


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


# ───── T-20261117-15: букет из настоящих листьев скана на стеблях кода (`plant_bouquet.py`) ─────
def test_bouquet_rules_are_data_and_consistent():
    """Букеты вазы — записи `builder: bouquet`: источник — скан Poly Haven (CC0 в реестре), листья и стебли заданы данными, списки согласованы."""
    rows = [p for p in CFG['plants'] if p.get('builder') == 'bouquet']
    assert len(rows) >= 2 and all(p['kind'] == 'dry' for p in rows)          # вазе есть из чего выбирать, и это букеты, не зелень
    assert not [p for p in CFG['plants'] if p.get('builder') == 'procedural']   # плоские процедурные букеты сняты (владелец: «нереалистичный эвкалипт»)
    for p in rows:
        b = p['bouquet']
        n = len(b['leaves'])
        assert 4 <= n <= 8 and len(set(b['leaves'])) == n, p['id']
        for key in ('stemCm', 'leanDeg', 'scale'):
            assert b[key] and all(x > 0 for x in b[key]), (p['id'], key)
        assert all(0 <= a <= 45 for a in b['leanDeg']) and all(15 <= s <= 80 for s in b['stemCm']), p['id']


def test_bouquet_rot_to_and_tube_geometry():
    import plant_bouquet as PB
    for a, b in [([0, 1, 0], [1, 0, 0]), ([0, 1, 0], [0, 1, 0]), ([0, 1, 0], [0, -1, 0]), ([1, 2, 3], [-3, 1, 2])]:
        a, b = np.array(a, float), np.array(b, float)
        R = PB.rot_to(a, b)
        assert np.allclose(R @ R.T, np.eye(3), atol=1e-9) and np.allclose(R @ (a / np.linalg.norm(a)), b / np.linalg.norm(b), atol=1e-9)
    path = np.stack([np.zeros(5), np.linspace(0, 0.4, 5), np.zeros(5)], axis=1)
    v, f = PB.tube(path, np.full(5, 0.004), sides=6)
    assert len(v) == 30 and len(f) == 4 * 6 * 2 and f.max() < len(v)
    assert np.allclose(np.hypot(v[:6, 0], v[:6, 2]), 0.004)                  # кольцо — радиуса стебля
    assert abs(v[:, 1].min()) < 1e-9 and abs(v[:, 1].max() - 0.4) < 1e-9


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-q', '-p', 'no:cacheprovider']))
