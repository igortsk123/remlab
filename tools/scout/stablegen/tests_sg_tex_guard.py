#!/usr/bin/env python3
"""Тесты `sg_tex_guard.py` и пути камер прогона (T-20261120-152/1): таблица SKU → keep/repaint/reject, запись `guard` в склад, камеры едут со складом.
Синтетика (куб с текстурой, прогон с status.json) — без видеокарты и сети; нужны numpy, PIL, trimesh. Если на машине есть настоящий прогон комода (`~/remlab-logs/t90-1119/sg/runpod/…`) —
дополнительно: сторож на настоящем painted.glb и сверка решения по восстановленным камерам; нет прогона (CI) — этот блок пропускается и говорит об этом.

  python3 tools/scout/stablegen/tests_sg_tex_guard.py
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'salad', 'trellis'))
sys.path.insert(0, os.path.join(HERE, '..'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_sg_tex_guard')
import tempfile  # noqa: E402

import numpy as np  # noqa: E402
import sg_cams  # noqa: E402
import sg_tex_guard as G  # noqa: E402
import sg_store  # noqa: E402

bad = 0


def ok(name, cond, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


def write_cube(path: str) -> None:
    """Куб 1×1×1: у каждой из 6 граней своя плитка 4×4 развёртки; текстура 256² не «фон»."""
    import trimesh
    from PIL import Image
    V, F, UV = [], [], []
    x0 = y0 = z0 = -0.5
    x1 = y1 = z1 = 0.5
    quads = (((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)), ((x1, y0, z0), (x0, y0, z0), (x0, y1, z0), (x1, y1, z0)),
             ((x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1)), ((x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)),
             ((x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0)), ((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)))
    for t, q in enumerate(quads):
        i, j = t % 4, t // 4
        u0, u1, v0, v1 = i / 4 + 0.01, (i + 1) / 4 - 0.01, j / 4 + 0.01, (j + 1) / 4 - 0.01
        o = len(V)
        V += list(q)
        UV += [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
        F += [(o, o + 1, o + 2), (o, o + 2, o + 3)]
    tex = np.full((256, 256, 3), 128, np.uint8)
    tex[::2, ::2] = (150, 120, 100)
    m = trimesh.Trimesh(vertices=np.array(V), faces=np.array(F), process=False)
    m.visual = trimesh.visual.TextureVisuals(uv=np.array(UV), image=Image.fromarray(tex))
    m.export(path)


def make_run(root: str, name: str, with_status=True, dist=2.0, mode='orbit_ring') -> str:
    d = os.path.join(root, name)
    os.makedirs(os.path.join(d, 'blender'), exist_ok=True)
    write_cube(os.path.join(d, 'blender', 'painted.glb'))
    if with_status:
        json.dump({'framing': [{'cam': f'Camera_{i}', 'dist': dist, 'w': 0.5, 'h': 0.5} for i in range(8)]}, open(os.path.join(d, 'blender', 'status.json'), 'w'))
    json.dump({'cameras': {'mode': mode, 'num': 8}, 'cat_role': 'sofa'}, open(os.path.join(d, 'cfg.json'), 'w'))
    return d


with tempfile.TemporaryDirectory(dir=os.environ.get('REMLAB_TMP') or None) as T:
    # ---------------------------------------------------------------- 1. одна папка --------------------------------------------------
    print('1. прогон → решение сторожа')
    run = make_run(T, '111_222@form1+q2509t5i-rp-1')
    r = G.guard_dir(run, os.path.join(T, 'json'), grid=256, view_res=384)
    ok('SKU из имени папки прогона: 111:222', r['sku'] == '111:222', r['sku'])
    ok('камеры восстановлены по status.json (у прогона нет cameras.json): 8, source reconstructed', r['cameras']['n'] == 8 and r['cameras']['source'] == 'reconstructed', r['cameras'])
    ok('куб: решение keep (unseen 16,7 % и grazing 16,7 % меньше порогов THRESHOLDS)', r['verdict'] == 'keep', (r['verdict'], r['verdict_why']))
    ok('доли в результате: unseen и grazing ≈ 16,7 % среди наружных (одна грань из шести — низ, верх вскользь)', abs(r['outer_tex']['unseen_pct'] - 100 / 6) < 2.5 and abs(r['outer_tex']['grazing_pct'] - 100 / 6) < 2.5, r['outer_tex'])
    ok('нет записанных поз — файла cameras.json сторож не создаёт (прогон не трогает)', not os.path.exists(os.path.join(run, 'blender', 'cameras.json')))
    # записанные позы главнее восстановленных
    doc = sg_cams.reconstruct(json.load(open(os.path.join(run, 'blender', 'status.json'))), json.load(open(os.path.join(run, 'cfg.json'))), [0.0, 0.0, 0.0])
    doc['source'] = 'recorded'
    json.dump(doc, open(os.path.join(run, 'blender', 'cameras.json'), 'w'))
    r2 = G.guard_dir(run, os.path.join(T, 'json'), grid=256, view_res=384)
    ok('есть cameras.json → камеры «recorded» и те же доли (позы те же)', r2['cameras']['source'] == 'recorded' and r2['outer_tex'] == r['outer_tex'], (r2['cameras'], r2['outer_tex']))

    # ---------------------------------------------------------------- 2. набор: ошибка в таблице, не молчание ----------------------
    print('2. набор: нет камер → строка «ошибка», остальные идут; таблица и счётчик')
    run_bad = make_run(T, '333_444@form1+q2509t5i-rp-2', with_status=False)
    run_fan = make_run(T, '555_666@form1+q2509t5i-rp-3', mode='fan')
    out = os.path.join(T, 'out')
    res = G.run_set([run, run_bad, run_fan], out, thresholds=None)
    ok('3 прогона → 3 результата', len(res) == 3)
    ok('нет status.json и нет cameras.json → ошибка «нет камер», а не молчаливый MV-Adapter', 'error' in res[1] and 'нет камер' in res[1]['error'], res[1])
    ok('режим камер не орбитальное кольцо → тоже «нет камер»', 'error' in res[2] and 'нет камер' in res[2]['error'], res[2])
    p_csv, p_md, p_json = G.write_table(out, res)
    rows = json.load(open(p_json, encoding='utf-8'))
    ok('таблица: счётчик решений keep — 1, ошибка — 2', rows['verdicts'] == {'keep': 1, 'ошибка': 2}, rows['verdicts'])
    md = open(p_md, encoding='utf-8').read()
    ok('в .md все три SKU и итоговая строка', all(f'`{s}`' in md for s in ('111:222', '333:444', '555:666')) and 'Итого:' in md)
    ok('CSV: заголовок и 3 строки', len(open(p_csv, encoding='utf-8').read().strip().splitlines()) == 4)
    ok('код возврата CLI при ошибке — 1', G.main(['table', run, run_bad, '--out', os.path.join(T, 'out2')]) == 1)

    # ---------------------------------------------------------------- 3. склад: камеры едут с записью, guard пишется ----------------
    print('3. склад: store_run кладёт камеры рядом, `store` пишет guard')
    cfg = sg_store.painted_cfg()
    root = os.path.join(T, 'meshes-painted')
    it = {'key': '111_222@form1', 'variant': 'q2509t5i', 'label': 'rp-1', 'dir': run}
    rec = sg_store.store_run(it, cfg, root)
    dest = rec['stored']
    ok('в записи склада: model.glb, manifest.json, cameras.json, status.json, cfg.json', all(os.path.isfile(os.path.join(dest, f)) for f in ('model.glb', 'manifest.json', 'cameras.json', 'status.json', 'cfg.json')), os.listdir(dest))
    ok('guard у новой записи — none (по умолчанию из канона)', rec['guard'] == cfg['guard_none'])
    rs = G.run_set([dest], os.path.join(T, 'out3'), write_guard=True)
    ok('сторож по записи склада читает камеры из записи: source recorded', rs[0]['cameras']['source'] == 'recorded', rs[0].get('cameras') or rs[0])
    man = json.load(open(os.path.join(dest, 'manifest.json'), encoding='utf-8'))
    ok('keep → guard = guard_pass из канона (`pass`)', man['guard'] == cfg['guard_pass'] == 'pass', man['guard'])
    ok('отчёт сторожа в манифесте: решение, камеры, доли, время проверки', man['guard_report']['verdict'] == 'keep' and man['guard_report']['cameras']['source'] == 'recorded' and 'checked_at' in man['guard_report'])
    ok('SKU записи — из манифеста', rs[0]['sku'] == '111:222')
    ok('guard_value: repaint → repaint, reject → reject, keep → pass', (G.guard_value('repaint', cfg), G.guard_value('reject', cfg), G.guard_value('keep', cfg)) == ('repaint', 'reject', 'pass'))
    ok('guard pass БЕЗ отметки «принято владельцем» победителем не делает (второе условие — rules/painted-accepted.json)', sg_store.painted_cfg()['guard_pass'] == 'pass' and not json.load(open(os.path.join(HERE, '..', 'rules', 'painted-accepted.json'), encoding='utf-8')).get('accepted'))

    # ---------------------------------------------------------------- 4. настоящий комод (если прогон есть) -----------------------------
    print('4. настоящий прогон комода (если есть на машине)')
    komod = os.path.expanduser('~/remlab-logs/t90-1119/sg/runpod/112923_13224664101879413845@r2b1+newcut-q2509t5i-rp-133800')
    if not os.path.isfile(os.path.join(komod, 'blender', 'painted.glb')):
        print('  · прогона комода на этой машине нет — блок пропущен')
    else:
        rk = G.guard_dir(komod, os.path.join(T, 'json'))
        ok('комод: решение из keep/repaint/reject, камер 8, источник — recorded или reconstructed', rk['verdict'] in ('keep', 'repaint', 'reject') and rk['cameras']['n'] == 8, rk.get('cameras'))
        print(f"  · комод: {rk['verdict']} — unseen {rk['outer_tex']['unseen_pct']} % / grazing {rk['outer_tex']['grazing_pct']} % / unpainted {rk['outer_tex']['unpainted_pct']} % (наружных {rk['outer_share_tex_pct']} % карты); {rk['verdict_why']}")

print('ИТОГО: всё в норме' if not bad else f'ИТОГО: провалов {bad}')
sys.exit(1 if bad else 0)
