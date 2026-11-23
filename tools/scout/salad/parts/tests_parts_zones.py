#!/usr/bin/env python3
"""Тест подключения частей PartLLM к 07 (T-198/1): faces.npy → parts.npz (формат `tex_fill.parts_from_npz`), флаг `zones_from`, выбор источника зон, вход задания 07.
Запуск: python tools/scout/salad/parts/tests_parts_zones.py"""
import io
import json
import os
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SALAD = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, SALAD)
sys.path.insert(0, os.path.join(SALAD, 'stage'))
import numpy as np  # noqa: E402
import trimesh  # noqa: E402
import parts_to_npz as PN  # noqa: E402

FAILS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        FAILS.append(msg)


def two_boxes(path):
    """GLB из двух кубов (две геометрии по 12 граней = 24) — как у формы с несколькими геометриями."""
    sc = trimesh.Scene()
    sc.add_geometry(trimesh.creation.box(extents=(1, 1, 1)), node_name='a', geom_name='a')
    b = trimesh.creation.box(extents=(1, 1, 1))
    b.apply_translation((2, 0, 0))
    sc.add_geometry(b, node_name='b', geom_name='b')
    sc.export(path)
    return 24


with tempfile.TemporaryDirectory() as td:
    glb = os.path.join(td, 'm.glb')
    n = two_boxes(glb)
    check(PN.glb_face_count(glb) == n, f'glb_face_count: {n} граней по всем геометриям')

    # convert: нормальный выход воркера
    src = os.path.join(td, 'src', 'sku1')
    os.makedirs(src)
    lab = np.array([0] * 12 + [1] * 8 + [-1] * 4, dtype=np.int32)
    np.save(os.path.join(src, 'faces.npy'), lab)
    json.dump({'names': ['Seat', 'Leg']}, open(os.path.join(src, 'meta.json'), 'w'))
    out = os.path.join(td, 'root', 'sku1', '03-parts')
    r = PN.convert(src, glb, out)
    check(r['ok'] and r['n_parts'] == 2 and r['share_unlabeled'] == round(4 / 24, 4), f'convert: 2 части, без метки 4/24: {r}')
    z = np.load(os.path.join(out, 'parts.npz'))
    check(list(z.files) == ['part'] and z['part'].dtype == np.int32 and z['part'].shape == (24,), 'parts.npz: один ключ part, int32, длина = граням')
    pj = json.load(open(os.path.join(out, 'parts.json'), encoding='utf-8'))
    check([p['name'] for p in pj['parts']] == ['Seat', 'Leg'] and abs(sum(p['face_share'] for p in pj['parts']) - 20 / 24) < 1e-3 and all('role' not in p for p in pj['parts']),
          'parts.json: имена PartLLM, доли, поля role нет (роли этапа 3 не выдумываем)')

    # формат читает именно код 07 (tex_fill.parts_from_npz), если он доступен в этом дереве
    tex_dir = os.path.join(SALAD, 'trellis')
    if os.path.isfile(os.path.join(tex_dir, 'tex_fill.py')):
        sys.path.insert(0, tex_dir)
        sys.path.insert(0, os.path.abspath(os.path.join(SALAD, '..')))
        try:
            import tex_fill as TF
            parts, note = TF.parts_from_npz(os.path.join(out, 'parts.npz'), [{'F': np.zeros((12, 3))}, {'F': np.zeros((12, 3))}])
            check(len(parts) == 2 and len(parts[0]) == 12 and parts[1].max() == 2 and 'частей' in note, f'tex_fill.parts_from_npz читает файл: {note}')   # −1 → отдельный номер (max+1 = 2)
        except ImportError as e:
            print('SKIP parts_from_npz (нет библиотек этапа 07):', e)

    # convert: чужой меш / нет файла
    np.save(os.path.join(src, 'faces.npy'), np.zeros(7, dtype=np.int32))
    r2 = PN.convert(src, glb, os.path.join(td, 'root2'))
    check(not r2['ok'] and 'другого меша' in r2['reason'] and not os.path.exists(os.path.join(td, 'root2', 'parts.npz')), 'convert: число граней не совпало → отказ и parts.npz нет')
    c2 = json.load(open(os.path.join(td, 'root2', 'check.json')))
    check(c2['passed'] is False and 'другого меша' in c2['reason'] and c2['stage'] == '03-parts', 'convert: отказ пишет check.json passed=false с причиной (этап без check.json = не пройден)')
    c1 = json.load(open(os.path.join(out, 'check.json')))
    check(c1['stage'] == '03-parts' and c1['sku'] == 'sku1' and c1['metrics']['n_parts']['value'] == 2 and c1['metrics']['faces_with_part_share']['value'] == round(1 - 4 / 24, 4)
          and c1['passed'] is False and c1['metrics']['faces_with_part_share']['ok'] is False, 'convert: годный выход пишет check.json с мерами; 4/24 без метки < 0,98 → passed=false')
    src_ok = os.path.join(td, 'src', 'sku2')
    os.makedirs(src_ok)
    np.save(os.path.join(src_ok, 'faces.npy'), np.array([0] * 12 + [1] * 12, dtype=np.int32))
    out_ok = os.path.join(td, 'root', 'sku2', '03-parts')
    PN.convert(src_ok, glb, out_ok)
    c_ok = json.load(open(os.path.join(out_ok, 'check.json')))
    check(c_ok['passed'] is True and c_ok['outputs'] == ['parts.npz', 'parts.json'], 'convert: все грани с меткой, 2 части → check.json passed=true')
    r3 = PN.convert(os.path.join(td, 'nope'), glb, os.path.join(td, 'root3'))
    check(not r3['ok'] and 'нет faces.npy' in r3['reason'], 'convert: нет faces.npy → отказ')

    # pick_parts
    root = os.path.join(td, 'root')
    p, why = PN.pick_parts(root, 'sku1', glb, 'parts')
    check(p == os.path.join(root, 'sku1', '03-parts', 'parts.npz') and why == 'parts', 'pick_parts(parts): файл годный → путь')
    p, why = PN.pick_parts(root, 'sku1', glb, 'panels')
    check(p is None and why == 'zones_from=panels', 'pick_parts(panels): ничего не кладём')
    p, why = PN.pick_parts(root, 'нет-такого', glb, 'parts')
    check(p is None and 'нет parts.npz' in why, 'pick_parts: нет файла → panels + причина')
    glb6 = os.path.join(td, 'box.glb')
    trimesh.creation.box().export(glb6)
    p, why = PN.pick_parts(root, 'sku1', glb6, 'parts')
    check(p is None and 'другого меша' in why, 'pick_parts: граней не столько → panels + причина')

    # zones_mode
    rj = os.path.join(td, 'rules.json')
    json.dump({}, open(rj, 'w'))
    check(PN.zones_mode(rj) == 'parts', 'zones_mode: ключа нет → parts (по умолчанию)')
    json.dump({'zones_from': 'panels'}, open(rj, 'w'))
    check(PN.zones_mode(rj) == 'panels', 'zones_mode: panels')
    json.dump({'zones_from': 'parts '}, open(rj, 'w'))
    try:
        PN.zones_mode(rj)
        check(False, 'zones_mode: чужое значение → ValueError')
    except ValueError:
        check(True, 'zones_mode: чужое значение → ValueError')
    check(PN.zones_mode() in PN.MODES, 'zones_mode: настоящий rules/paint-fill.json содержит допустимое значение')

    # вход 07: parts.npz едет в zip, когда выбран; когда нет — в zip его нет
    import stage_trial as ST
    vis = os.path.join(td, 'vis', 'sku1', '06-visible')
    os.makedirs(vis)
    open(os.path.join(vis, 'visible.glb'), 'wb').write(open(glb, 'rb').read())
    open(os.path.join(vis, 'check.json'), 'w').write('{}')
    inputs = ST.vis_inputs(os.path.join(td, 'vis'))
    zl = ST.attach_parts(inputs, root, os.path.join(td, 'vis'), 'parts')
    check(zl['sku1']['source'] == 'parts' and inputs['sku1']['extra_in'] == {'parts.npz': os.path.join(root, 'sku1', '03-parts', 'parts.npz')}, 'attach_parts(parts): extra_in = parts.npz')
    data = ST.input_zip_07(vis, None, inputs['sku1'])
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    check('parts.npz' in names and '06-visible/visible.glb' in names, 'zip входа 07: parts.npz рядом с 06-visible')
    inputs2 = ST.vis_inputs(os.path.join(td, 'vis'))
    zl2 = ST.attach_parts(inputs2, root, os.path.join(td, 'vis'), 'panels')
    check(zl2['sku1']['source'] == 'panels' and 'extra_in' not in inputs2['sku1'], 'attach_parts(panels): вход без parts.npz')
    names2 = zipfile.ZipFile(io.BytesIO(ST.input_zip_07(vis, None, inputs2['sku1']))).namelist()
    check('parts.npz' not in names2, 'zip входа 07 при panels: parts.npz нет')

print('\nИТОГ:', 'всё прошло' if not FAILS else f'ПРОВАЛОВ {len(FAILS)}: {FAILS}')
sys.exit(1 if FAILS else 0)
