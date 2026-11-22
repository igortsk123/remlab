#!/usr/bin/env python3
"""Тесты бэкенда SegviGen без GPU (Ш5/T-183): пути к весам — только абсолютные (урок pl1/pl2), кадр по альфе без RMBG, текстура у каждой геометрии, воксели → метки граней, подключение к воркеру.
Запуск: python tools/scout/salad/parts/tests_segvigen.py   (нужны numpy, scipy, trimesh, pillow)"""
import os
import sys
import tempfile
import types

os.environ['MODEL'] = 'fake'
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import numpy as np  # noqa: E402
import trimesh  # noqa: E402
from PIL import Image  # noqa: E402
import segvigen_backend as S  # noqa: E402
import parts_trial as PT  # noqa: E402
import worker_parts as W  # noqa: E402
import kit_worker as KW  # noqa: E402

FAILS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        FAILS.append(msg)


def touch(path, data=b'x'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'wb').write(data)


def make_tree(tmp):
    """Комплектный набор файлов образа во временной папке."""
    tr, seg, dino = os.path.join(tmp, 'w', 'TRELLIS.2-4B'), os.path.join(tmp, 'SegviGen'), os.path.join(tmp, 'w', 'dino')
    touch(os.path.join(tr, 'pipeline.json'), b'{"args":{}}')
    for v in S.NAMES.values():
        touch(os.path.join(tr, 'ckpts', v + '.json'))
        touch(os.path.join(tr, 'ckpts', v + '.safetensors'))
    for rel in ('inference_full.py', 'data_toolkit/bpy_render.py', 'data_toolkit/transforms.json', 'trellis2/__init__.py'):
        touch(os.path.join(seg, rel))
    ck, bl = os.path.join(tmp, 'w', 'SegviGen', 'full_seg.ckpt'), os.path.join(tmp, 'blender', 'blender')
    touch(ck)
    touch(bl)
    for rel in ('config.json', 'model.safetensors'):
        touch(os.path.join(dino, rel))
    return tr, seg, ck, dino, bl


def main() -> int:
    tmp = tempfile.mkdtemp()
    # --- пути: комплектность по абсолютным путям, независимо от cwd (апстрим открывает microsoft/TRELLIS.2-4B/pipeline.json от cwd)
    tr, seg, ck, dino, bl = make_tree(tmp)
    cwd0 = os.getcwd()
    other = tempfile.mkdtemp()
    os.chdir(other)
    try:
        check(S.missing_files(tr, seg, ck, dino, bl) == [], 'комплектный образ найден по абсолютным путям из чужого cwd')
        p = S.trellis_paths(tr)
        check(all(os.path.isabs(v) for v in p.values()) and p['pipeline_json'].endswith('pipeline.json') and p['tex_flow'].endswith(S.TEX_FLOW), 'trellis_paths: все пути абсолютные')
        rel_miss = S.missing_files('microsoft/TRELLIS.2-4B', seg, ck, dino, bl)
        check(any('pipeline.json' in m for m in rel_miss), 'относительный путь апстрима из чужого cwd — не находится (то, от чего защищаемся)')
        os.remove(p['tex_enc'] + '.safetensors')
        open(ck, 'wb').close()
        m2 = S.missing_files(tr, seg, ck, dino, bl)
        check(len(m2) == 2 and any('tex_enc' in m for m in m2) and any('full_seg.ckpt' in m for m in m2), f'нет файла / пустой чекпойнт — названы поимённо ({m2})')
        b = S.SegviGenBackend()
        b.trellis, b.seg_dir, b.ckpt, b.dino_dir, b.blender = tr, seg, ck, dino, bl
        try:
            b.load()
            ok = False
        except RuntimeError as e:
            ok = 'в образе нет файлов SegviGen' in str(e)
        check(ok, 'load() при неполном образе падает до чтения весов, с перечнем файлов')
    finally:
        os.chdir(cwd0)
    # --- кадр по альфе
    png = os.path.join(tmp, 'r.png')
    im = np.zeros((200, 200, 4), np.uint8)
    im[50:90, 120:160] = (200, 20, 20, 255)
    Image.fromarray(im).save(png)
    out = S.alpha_condition_image(png)
    a = np.array(out)
    check(out.size[0] == out.size[1] and 38 <= out.size[0] <= 41 and a[out.size[1] // 2, out.size[0] // 2].tolist() == [200, 20, 20], f'кадр: квадрат по bbox альфы, цвет внутри сохранён ({out.size})')
    Image.fromarray(np.zeros((50, 50, 4), np.uint8)).save(png)
    try:
        S.alpha_condition_image(png)
        ok = False
    except ValueError:
        ok = True
    check(ok, 'пустой кадр (нет непрозрачных пикселей) — ошибка, а не тихая чёрная картинка')
    cmd = S.blender_cmd('/opt/blender/blender', '/t/s.py', '/t/a.glb', '/s/t.json', '/t/o.png', '/opt/SegviGen')
    check(cmd[:3] == ['/opt/blender/blender', '-b', '-noaudio'] and cmd[-5:] == ['--', '/t/a.glb', '/s/t.json', '/t/o.png', '/opt/SegviGen'], 'команда Blender: фон, скрипт, аргументы после «--»')
    compile(S.BLENDER_RENDER_PY, 'blender_render.py', 'exec')
    # --- текстура у каждой геометрии
    bx = trimesh.creation.box(extents=(1, 2, 3))
    g0 = os.path.join(tmp, 'plain.glb')
    bx.export(g0)
    g1 = os.path.join(tmp, 'plain_t.glb')
    changed = S.ensure_textured(g0, g1)
    sc = trimesh.load(g1, force='scene', process=False)
    nf = sum(len(g.faces) for g in sc.geometry.values())
    check(changed and nf == 12 and all(S._has_texture(g) for g in sc.geometry.values()), f'меш без текстуры получает серую текстуру, граней столько же ({nf})')
    tx = trimesh.creation.box(extents=(1, 1, 1))
    tx.visual = trimesh.visual.texture.TextureVisuals(uv=np.random.rand(len(tx.vertices), 2), material=trimesh.visual.material.PBRMaterial(baseColorTexture=Image.fromarray(np.full((8, 8, 3), 90, np.uint8))))
    g2 = os.path.join(tmp, 'tex.glb')
    tx.export(g2)
    check(S.ensure_textured(g2, os.path.join(tmp, 'tex_t.glb')) is False and not os.path.exists(os.path.join(tmp, 'tex_t.glb')), 'меш с текстурой не трогаем (копию не пишем)')
    # --- воксели → метки граней: сфера, цвет вокселя по полупространству
    sph = trimesh.creation.icosphere(subdivisions=4, radius=1.7)
    sph.apply_translation((0.3, -0.2, 0.5))
    pts = S.face_sample_points(sph, 4)
    check(pts.shape == (len(sph.faces), 4, 3) and float(np.abs(pts).max()) <= 0.5 + 1e-6, f'точки граней — в кубе апстрима ±0,5 ({float(np.abs(pts).max()):.4f})')
    rng = np.random.default_rng(0)
    idx = np.unique(S.voxel_index(np.concatenate([pts.reshape(-1, 3), (rng.random((4000, 3)) - 0.5) * 0.0 + pts.reshape(-1, 3)[:4000]])), axis=0)
    cz = (idx[:, 2] + 0.5) / S.GRID - 0.5
    cx = (idx[:, 0] + 0.5) / S.GRID - 0.5
    col2 = np.where((cz > 0)[:, None], (200, 30, 30), (30, 30, 200)).astype(np.int32) + rng.integers(-4, 5, (len(idx), 3))
    r2 = S.faces_from_voxels(sph, idx, np.clip(col2, 0, 255).astype(np.uint8))
    f2 = r2['faces']
    truth = (S.face_sample_points(sph, 1)[:, 0, 2] > 0).astype(int)
    agree = max((f2 == truth).mean(), (f2 != truth).mean())
    check(len(f2) == len(sph.faces) and f2.dtype == np.int32 and len(np.unique(f2)) == 2 and agree > 0.97, f'2 цвета вокселей → 2 части, грани по полупространству ({agree:.3f}, палитра {r2["n_palette"]})')
    col4 = np.stack([np.where(cz > 0, 220, 20), np.where(cx > 0, 220, 20), np.full(len(idx), 60)], 1).astype(np.int32) + rng.integers(-4, 5, (len(idx), 3))
    r4 = S.faces_from_voxels(sph, idx, np.clip(col4, 0, 255).astype(np.uint8))
    check(len(np.unique(r4['faces'])) == 4, f'4 цвета → 4 части ({len(np.unique(r4["faces"]))})')
    f4, adj = r4['faces'], sph.face_adjacency
    perm = np.random.default_rng(0).permutation(f4)
    chk = PT.order_verdict(float((f4[adj[:, 0]] == f4[adj[:, 1]]).mean()), float((perm[adj[:, 0]] == perm[adj[:, 1]]).mean()))
    check(chk is True, 'метки граней SegviGen проходят проверку порядка граней (order_verdict)')
    keep = rng.random(len(idx)) > 0.15
    r2m = S.faces_from_voxels(sph, idx[keep], np.clip(col2, 0, 255).astype(np.uint8)[keep])
    agree_m = max((r2m['faces'] == truth).mean(), (r2m['faces'] != truth).mean())
    check(r2m['miss_share'] > 0 and agree_m > 0.95, f'15 % вокселей выброшено → ближайший воксель, доля промахов {r2m["miss_share"]}, согласие {agree_m:.3f}')
    # шум одиночных граней убирается (малые части → соседям)
    noisy = f2.copy()
    noisy[rng.choice(len(noisy), 10, replace=False)] ^= 1
    sm = S.smooth_small_parts(noisy, sph.face_adjacency, 50)
    check(len(np.unique(sm)) == 2 and sm.dtype == np.int32 and int((sm == np.bincount(sm).argmax()).sum()) >= int((sm != np.bincount(sm).argmax()).sum()), 'малые куски (меньше 50 граней) отдаются соседям, нумерация 0 = самая крупная')
    # палитра: редкий цвет границы выбрасывается, близкие сливаются
    cols = np.concatenate([np.tile((200, 30, 30), (50000, 1)), np.tile((205, 34, 28), (30000, 1)), np.tile((30, 30, 200), (60000, 1)), np.tile((120, 120, 120), (2, 1))])
    pal = S.build_palette(cols)
    check(len(pal) == 2, f'палитра: близкие красные слиты, серая пара пикселей отброшена ({len(pal)})')
    # --- патч sdpa: якоря — дословные строки SegviGen @81ec99ed
    sd = os.path.join(tmp, 'sg')
    os.makedirs(os.path.join(sd, 'trellis2', 'modules', 'sparse', 'attention'))
    open(os.path.join(sd, 'trellis2', 'modules', 'sparse', 'config.py'), 'w').write(
        "    if env_sparse_attn_backend is not None and env_sparse_attn_backend in ['xformers', 'flash_attn', 'flash_attn_3']:\n        ATTN = env_sparse_attn_backend\n")
    open(os.path.join(sd, 'trellis2', 'modules', 'sparse', 'attention', 'full_attn.py'), 'w').write(
        "def f(config, qkv, kv, num_all_args, q_seqlen, kv_seqlen, torch):\n    if config.ATTN == 'xformers':\n        out = 1\n    elif config.ATTN == 'flash_attn_3':\n        out = 3\n"
        "    else:\n        raise ValueError(f\"Unknown attention module: {config.ATTN}\")\n    return out\n")
    d1 = S.patch_sparse_sdpa(sd)
    ftxt = open(os.path.join(sd, 'trellis2', 'modules', 'sparse', 'attention', 'full_attn.py')).read()
    compile(ftxt, 'full_attn.py', 'exec')
    check(d1 == ['config', 'full_attn'] and "'sdpa'" in open(os.path.join(sd, 'trellis2', 'modules', 'sparse', 'config.py')).read() and ftxt.index("config.ATTN == 'sdpa'") < ftxt.index('Unknown attention module'),
          'патч sdpa: ветка добавлена в список бэкендов и в full_attn перед ValueError, файл компилируется')
    check(S.patch_sparse_sdpa(sd) == [], 'патч sdpa идемпотентен')
    open(os.path.join(sd, 'trellis2', 'modules', 'sparse', 'attention', 'full_attn.py'), 'w').write('def f():\n    pass\n')
    try:
        S.patch_sparse_sdpa(sd)
        ok = False
    except RuntimeError:
        ok = True
    check(ok, 'патч sdpa: нет якоря — громкая ошибка, а не тихий откат на flash_attn')
    ns = {}
    exec(compile(ftxt, 'x', 'exec'), ns)
    try:
        import torch
    except ImportError:
        torch = None
    if torch is not None:
        qkv = torch.randn(6, 3, 2, 4)
        o = ns['f'](types.SimpleNamespace(ATTN='sdpa'), qkv, None, 1, [4, 2], [4, 2], torch)
        q, k, v = qkv.unbind(1)
        ref = torch.cat([torch.einsum('hqk,khd->qhd', torch.softmax(torch.einsum('qhd,khd->hqk', q[a:b], k[a:b]) / 2.0, dim=-1), v[a:b]) for a, b in ((0, 4), (4, 6))])
        check(o.shape == (6, 2, 4) and torch.allclose(o, ref, atol=1e-5), 'ветка sdpa считает как softmax(QKᵀ/√d)V по каждой последовательности отдельно (torch есть)')
    else:
        print('SKIP ветка sdpa на torch: torch не установлен (CI), считается в пробе')
    # --- подключение к воркеру
    z = KW.bundle(W.WORKER_FILE if hasattr(W, 'WORKER_FILE') else os.path.join(HERE, 'worker_parts.py'), mods={'kit_worker': os.path.join(os.path.dirname(HERE), 'kit_worker.py'),
                                                                                                                    'segvigen_backend': os.path.join(HERE, 'segvigen_backend.py')})[1]
    import base64
    import json
    import zlib
    mods = json.loads(zlib.decompress(base64.b64decode(z)))['mods']
    check(set(mods) == {'kit_worker', 'segvigen_backend'}, 'пакет кода воркера содержит модуль segvigen_backend')
    import argparse
    a = argparse.Namespace(model='segvigen', image='ghcr.io/x/y@sha256:' + 'a' * 64, tier='high', cpu=8, mem_mb=32768, max_min=45, storage_gb=0, params='{}', max_meshes=1, stop_file='', out=tmp)
    body = PT.build_body('trial-parts-segvigen-t', 'cls', {}, a)
    c = body['container']
    z2 = json.loads(zlib.decompress(base64.b64decode(c['environment_variables']['KIT_WORKER_Z'])))
    check(c['resources']['storage_amount'] == 80 * 2 ** 30 and c['environment_variables']['HF_HUB_OFFLINE'] == '1' and 'segvigen_backend' in z2['mods'] and c['environment_variables']['MODEL'] == 'segvigen',
          'тело группы segvigen: диск 80 ГиБ, HF офлайн (gated не трогаем), модуль бэкенда в пакете кода')
    a.model = 'partllm'
    c2 = PT.build_body('trial-parts-partllm-t', 'cls', {}, a)['container']
    check(c2['resources']['storage_amount'] == 40 * 2 ** 30 and 'HF_HUB_OFFLINE' not in c2['environment_variables'] and set(json.loads(zlib.decompress(base64.b64decode(c2['environment_variables']['KIT_WORKER_Z'])))['mods']) == {'kit_worker'},
          'тело группы partllm не изменилось: диск 40 ГиБ, без офлайна, пакет прежний')
    check(PT.CARDS['segvigen'] == ('RTX 5090 (32 GB)', ('12.0',)), 'segvigen: карта 5090, архитектура 12.0')
    old = W.MODEL
    W.MODEL = 'segvigen'
    try:
        be = W.make_backend()
    finally:
        W.MODEL = old
    check(type(be).__name__ == 'SegviGenBackend', 'MODEL=segvigen → SegviGenBackend')
    sys.modules.pop('data_toolkit', None)
    sys.modules.pop('data_toolkit.bpy_render', None)
    S._stub_bpy('/x')
    from data_toolkit.bpy_render import render_from_transforms
    try:
        render_from_transforms()
        ok = False
    except RuntimeError:
        ok = True
    check(ok, 'заглушка bpy: импорт инференса проходит, вызов bpy-рендера — понятная ошибка')
    print('FAILS:', FAILS or 'нет')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
