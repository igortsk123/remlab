#!/usr/bin/env python3
"""Пол без рисунка (T-20261111-24/2): процедурная доска — ширина ровно заданная, шов 0,1–0,2 см без чёрной решётки, без
тёмных жил; пол из CC0-сканов (`tools/assets/material_from_scan.py`) — тип покрытия → скан → размер → оттенок, json
источника и лицензии у каждого скана, вес ≤ 1,5 МБ на материал, цвет 512 для телефона. Сетей и платного нет.
Запуск: python -m pytest tools/assets/tests/test_floor_materials.py -q   (или python …/test_floor_materials.py)"""
import hashlib
import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import material_pipeline as MP  # noqa: E402
import material_from_scan as MS  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
PLANKS = [k for k, p in MP.PRESETS.items() if p['gen'] == 'planks']


def _lum(img):
    return img.astype(np.float64) @ np.array([0.2126, 0.7152, 0.0722])


def test_plank_width_exact_and_seam_thin():
    for name in PLANKS:
        p = MP.PRESETS[name]
        rows, tile_y, seam_y, seam_x = MP.plank_layout(float(p['plank']), float(p['tile']))
        if rows == 1:
            continue                                   # столешница — цельная плита
        assert abs(tile_y / rows - p['plank']) < 1e-9, name      # ширина доски — ровно из пресета
        assert seam_y * tile_y / MP.TILE <= 0.2, name             # шов поперёк рядов ≤ 0,2 см
        assert seam_x * p['tile'] / MP.TILE <= 0.2, name          # торцевой шов ≤ 0,2 см


def test_plank_image_rows_and_soft_seam():
    p = MP.PRESETS['laminate-oak-light']
    rows, tile_y, seam_y, _ = MP.plank_layout(float(p['plank']), float(p['tile']))
    col, _h = MP.gen_planks(1, p['rgb'], float(p['plank']), float(p['tile']), p['contrast'])
    lum = _lum(col)
    for r in range(rows):
        y0, y1 = round(r * MP.TILE / rows), round((r + 1) * MP.TILE / rows)
        # ширина ряда на картинке = заданная ширина доски (±1 px округления границ)
        assert abs((y1 - y0) * tile_y / MP.TILE - p['plank']) <= tile_y / MP.TILE + 1e-9
        shift = (r * (MP.TILE // 3)) % MP.TILE           # торцевой шов ряда — столбцы [shift, shift+seam_x)
        keep = np.ones(MP.TILE, bool)
        keep[max(0, shift - 3) : shift + 6] = False
        keep[:40] = keep[-40:] = False
        body = lum[y0 + seam_y + 2 : y1 - 2][:, keep]
        seam = lum[y0 : y0 + seam_y][:, keep]
        ratio = float(seam.mean() / body.mean())
        assert 0.78 <= ratio <= 0.95, ratio       # шов виден, но не чёрный (прежде ×0,45)
        # без тёмных жил: внутри доски нет пикселей темнее 80 % её среднего
        assert float(body.min()) > 0.8 * float(body.mean()), r


def test_plank_tile_seamless():
    p = MP.PRESETS['oak-grey']
    col, _h = MP.gen_planks(3, p['rgb'], float(p['plank']), float(p['tile']), p['contrast'])
    lum = _lum(col)
    rows = MP.plank_layout(float(p['plank']), float(p['tile']))[0]
    # край тайла сходится: перепад между последним и первым столбцом — как между соседними внутри
    # (торцевой шов ряда может лечь ровно на край — медиана по строкам его не замечает, а сдвиг рисунка заметила бы)
    ys = np.arange(round(MP.TILE / rows) + 2, MP.TILE)
    edge = float(np.median(np.abs(lum[ys, -1] - lum[ys, 0])))
    inner = np.abs(np.diff(lum[ys, 400:900], axis=1)).mean()
    assert edge < inner * 3 + 1.0, (edge, inner)


def test_tint_and_wrap_blur():
    rng = np.random.default_rng(0)
    img = (rng.random((64, 64, 3)) * 120 + 60).astype(np.uint8)
    out = MS.tint(img, (200.0, 180.0, 150.0), contrast=0.7, chroma=0.5, flatten=0.8)
    assert np.allclose(out.reshape(-1, 3).mean(0), (200, 180, 150), atol=1.5)
    a = rng.random((32, 32))
    b = MS.wrap_blur(a, 3.0)
    assert abs(a.mean() - b.mean()) < 1e-9          # энергия не теряется
    assert abs(b[0, 0] - b[-1, -1]) < 0.2           # по тору: углы соседи


def test_rotate_normal_vectors():
    n = np.full((2, 2, 3), 128, np.uint8)
    n[..., 0] = 255                                   # наклон вправо (+x)
    r = MS.rotate(n, 90, normal=True)
    assert int(r[0, 0, 0]) == 128 and int(r[0, 0, 1]) == 255   # после поворота на 90° против часовой — вверх (+y)


def test_floor_type_mapping():
    cfg = MS.load_config()
    mats = json.load(open(os.path.join(ROOT, 'data/flat3d/materials.json'), encoding='utf-8'))['materials']
    by = {e['id']: e for e in mats}
    plan = {e['id']: (t, r['scan']) for e, t, r in MS.scan_plan(mats, cfg)}
    assert plan['laminate-oak-light'] == ('planks', 'laminate_floor_02')
    assert plan['parquet-herringbone'][0] == 'herringbone45'
    assert plan['vinyl-stone-grey'][0] == 'tiles' and 'oak' not in plan['vinyl-stone-grey'][1]
    assert 'laminate-oak-top' not in plan            # столешница — не пол
    assert 'tile-stone-grey' not in plan             # плитка и на стену — сканом пола не подменяем
    assert 'parquet-blocks' not in plan              # модульный паркет — процедурный запасной путь
    assert MS.floor_type(by['floor-photo-demo']) is None   # фото застройщика — уже настоящая фактура


def test_scans_have_source_licence_and_files():
    cfg = MS.load_config()
    assert isinstance(cfg['enabled'], bool)
    for rule in cfg['types'].values():
        sdir = os.path.join(ROOT, 'data/flat3d/scans', rule['scan'])
        src = json.load(open(os.path.join(sdir, 'source.json'), encoding='utf-8'))
        assert src['licence'] == 'CC0-1.0' and src['licenceUrl'].startswith('https://')
        assert src['pageUrl'].startswith('https://polyhaven.com/a/') and src['downloaded'][:2] == '20'
        assert len(src['realMm']) == 2 and min(src['realMm']) > 300
        for name, sha in src['sha256'].items():
            assert hashlib.sha256(open(os.path.join(sdir, name), 'rb').read()).hexdigest() == sha, name


def test_scan_materials_weight_and_sizes():
    cfg = MS.load_config()
    ver = int(cfg['version'])
    mats = json.load(open(os.path.join(ROOT, 'data/flat3d/materials.json'), encoding='utf-8'))['materials']
    by = {e['id']: e for e in mats}
    out = os.path.join(ROOT, 'public/flat3d/materials')
    plan = MS.scan_plan(mats, cfg)
    assert plan
    for entry, _t, rule in plan:
        e = by.get(f"scan-{entry['id']}")
        assert e, entry['id']
        files = MS.scan_files(ver, entry['id'])
        assert all(e[k] == v for k, v in files.items())
        total = sum(os.path.getsize(os.path.join(out, f)) for f in files.values())
        assert total <= 1_500_000, (entry['id'], total)          # ≤ 1,5 МБ на вариант
        assert Image.open(os.path.join(out, files['baseColorUrl'])).size == (1024, 1024)
        assert Image.open(os.path.join(out, files['baseColorLiteUrl'])).size == (512, 512)
        src = json.load(open(os.path.join(ROOT, 'data/flat3d/scans', rule['scan'], 'source.json'), encoding='utf-8'))
        assert e['tileCm'] == [round(src['realMm'][0] / 10, 1), round(src['realMm'][1] / 10, 1)]   # размер — из источника
        assert e['source']['licence'] == 'CC0-1.0' and e['source']['kind'] == 'photo-material'


if __name__ == '__main__':
    fails = 0
    for k, f in sorted(globals().items()):
        if k.startswith('test_') and callable(f):
            try:
                f()
                print('OK  ', k)
            except AssertionError as exc:
                fails += 1
                print('FAIL', k, exc)
    raise SystemExit(1 if fails else 0)
