"""SegviGen (Ш5 / T-183) — бэкенд разметки частей на kit: `MODEL=segvigen` в worker_parts (модуль едет в KIT_WORKER_Z вместе с воркером).
Что делает (режим full_seg без 2D-карты, один вызов на меш; код апстрима Nelipot-Lee/SegviGen @81ec99ed — `inference_full.py`, берём его функции, а не копируем):
  glb → воксели 512³ (o_voxel) → энкодеры TRELLIS.2 → кадр-условие (Blender подпроцессом, фон по альфе рендера, БЕЗ RMBG-2.0) → DINOv3 (веса в образе, зеркало, sha256 сверен) →
  сэмплер Gen3DSeg → декодер цвета → цвета вокселей → метки НАШИХ граней по вокселю под выборкой точек грани (без to_glb/remesh/nvdiffrast) → палитра цветов → части.
Выход: `faces.npy` int32[F] в порядке граней входного glb (метка = часть, 0 = самая крупная), `segvigen_vox.npz` (координаты и цвета вокселей — для кадров и разбора).
Пути к весам и pipeline.json — ТОЛЬКО абсолютные (апстрим открывает `microsoft/TRELLIS.2-4B/pipeline.json` от cwd — урок pl1/pl2: файлы по умолчанию); комплектность — до GPU (`missing_files`).
Чистые функции (numpy/PIL/trimesh, без GPU) проверяются в tests_segvigen.py; GPU-путь (`SegviGenBackend.segment`) — только в пробе. НЕ проверено на GPU: форма `tex_voxels` (берём как `slat_to_glb` апстрима)."""
import importlib.util
import os
import subprocess
import sys
import time
import types

GRID = 512                                                     # сетка апстрима (`process_glb_to_vxz`, grid_size=512, aabb ±0,5)
SCALE = 0.99999                                                # масштаб апстрима: 0,99999 / наибольший размер bbox
TEX_FLOW = 'slat_flow_imgshape2tex_dit_1_3B_512_bf16'
NAMES = {'shape_enc': 'shape_enc_next_dc_f16c32_fp16', 'tex_enc': 'tex_enc_next_dc_f16c32_fp16',
         'shape_dec': 'shape_dec_next_dc_f16c32_fp16', 'tex_dec': 'tex_dec_next_dc_f16c32_fp16', 'tex_flow': TEX_FLOW}
DINOV3_SHA256 = 'dcb2e45127cccbf1601e5f42fef165eea275c8e5213197e8dcf3f48822718179'          # facebook/dinov3-vitl16-pretrain-lvd1689m model.safetensors (= зеркало camenduru, сверено)


# ---------------------------------------------------------------- пути и комплектность (без GPU)
def trellis_paths(root: str) -> dict:
    """Абсолютные пути весов TRELLIS.2 в образе: {имя: путь без расширения} + pipeline.json."""
    root = os.path.abspath(root)
    d = {k: os.path.join(root, 'ckpts', v) for k, v in NAMES.items()}
    d['pipeline_json'] = os.path.join(root, 'pipeline.json')
    return d


def missing_files(trellis_root: str, segvigen_dir: str, ckpt: str, dino_dir: str, blender: str) -> list:
    """Что отсутствует/пусто — список строк; пустой список = комплектно. Вызывается в load() ДО чтения весов: прогрев падает за секунды с понятной причиной."""
    miss = []
    p = trellis_paths(trellis_root)

    def need(path, what):
        if not (os.path.exists(path) and (os.path.isdir(path) or os.path.getsize(path) > 0)):
            miss.append(f'{what}: {path}')
    need(p['pipeline_json'], 'pipeline.json TRELLIS.2')
    for k in NAMES:
        need(p[k] + '.json', f'{k} .json')
        need(p[k] + '.safetensors', f'{k} .safetensors')
    for rel in ('inference_full.py', 'data_toolkit/bpy_render.py', 'data_toolkit/transforms.json', 'trellis2/__init__.py'):
        need(os.path.join(segvigen_dir, rel), f'код SegviGen {rel}')
    need(ckpt, 'чекпойнт full_seg.ckpt')
    for rel in ('config.json', 'model.safetensors'):
        need(os.path.join(dino_dir, rel), f'DINOv3 {rel}')
    need(blender, 'Blender')
    return miss


# ---------------------------------------------------------------- кадр-условие
BLENDER_RENDER_PY = '''import sys, os
glb, transforms, out, seg = sys.argv[sys.argv.index('--') + 1:][:4]
sys.path.insert(0, os.path.join(seg, 'data_toolkit'))
from bpy_render import render_from_transforms
render_from_transforms(glb, transforms, out)
'''


def blender_cmd(blender: str, script: str, glb: str, transforms: str, out_png: str, segvigen_dir: str) -> list:
    return [blender, '-b', '-noaudio', '--python', script, '--', glb, transforms, out_png, segvigen_dir]


def render_condition(glb: str, out_png: str, blender: str, segvigen_dir: str, workdir: str, timeout: float = 600.0) -> float:
    """Кадр меша (RGBA, прозрачный фон) = вход DINOv3, как `render_from_transforms` апстрима, но Blender-бинарником подпроцессом (bpy 4.0 — только py3.10, а основа образа py3.12)."""
    script = os.path.join(workdir, 'blender_render.py')
    open(script, 'w').write(BLENDER_RENDER_PY)
    t = time.time()
    r = subprocess.run(blender_cmd(blender, script, glb, os.path.join(segvigen_dir, 'data_toolkit', 'transforms.json'), out_png, segvigen_dir),
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0 or not os.path.isfile(out_png):
        raise RuntimeError(f'Blender rc={r.returncode}, кадра нет: {(r.stderr or r.stdout)[-600:]}')
    return round(time.time() - t, 2)


def alpha_condition_image(png_path: str):
    """Подготовка кадра по АЛЬФЕ рендера (хвост `preprocess_image` апстрима без RMBG-2.0): квадрат по bbox пикселей alpha>0,8·255, цвет × альфа, RGB.
    Апстрим при RGBA сперва склеивает на белое и теряет альфу — поэтому всегда звал RMBG; здесь альфа берётся из файла напрямую."""
    import numpy as np
    from PIL import Image
    im = Image.open(png_path).convert('RGBA')
    a = np.array(im)[:, :, 3]
    ys, xs = np.nonzero(a > 0.8 * 255)
    if len(xs) == 0:
        raise ValueError('на кадре нет непрозрачных пикселей — Blender отрисовал пусто')
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    cx, cy, size = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0)
    box = (int(cx - size // 2), int(cy - size // 2), int(cx + size // 2), int(cy + size // 2))
    out = np.array(im.crop(box)).astype(np.float32) / 255
    out = out[:, :, :3] * out[:, :, 3:4]
    return Image.fromarray((out * 255).astype(np.uint8))


# ---------------------------------------------------------------- вход: текстура у каждой геометрии
def _has_texture(geom) -> bool:
    mat = getattr(getattr(geom, 'visual', None), 'material', None)
    return mat is not None and getattr(mat, 'baseColorTexture', None) is not None


def ensure_textured(path_in: str, path_out: str) -> bool:
    """Апстрим `textured_mesh_to_volumetric_attr` берёт материал из сцены; геометрии без baseColorTexture (цвет вершин/нет материала) получают нейтральную серую текстуру 4×4.
    Все с текстурой → файл не трогаем (False), иначе пишем копию в path_out (True). Порядок и число граней не меняются."""
    import numpy as np
    import trimesh
    from PIL import Image
    from trimesh.visual.material import PBRMaterial
    from trimesh.visual.texture import TextureVisuals
    sc = trimesh.load(path_in, force='scene', process=False)
    if all(_has_texture(g) for g in sc.geometry.values()):
        return False
    tex = Image.fromarray(np.full((4, 4, 3), 200, np.uint8))
    for g in sc.geometry.values():
        if not _has_texture(g):
            g.visual = TextureVisuals(uv=np.full((len(g.vertices), 2), 0.5), material=PBRMaterial(baseColorTexture=tex, baseColorFactor=[255, 255, 255, 255]))
    sc.export(path_out)
    return True


# ---------------------------------------------------------------- воксели → метки граней (без GPU)
def frame_params(mesh):
    """Центр и масштаб, как `process_glb_to_vxz`: сдвиг на центр bbox, масштаб 0,99999 / наибольший размер."""
    import numpy as np
    lo, hi = np.asarray(mesh.bounds[0], dtype=np.float64), np.asarray(mesh.bounds[1], dtype=np.float64)
    return (lo + hi) / 2, SCALE / float((hi - lo).max())


def face_sample_points(mesh, n: int = 4):
    """(F, n, 3) точки на гранях в КООРДИНАТАХ апстрима (куб ±0,5): центр грани + (n−1) точек, смещённых к вершинам (барицентры 0,6/0,2/0,2). Порядок граней — как в mesh.faces."""
    import numpy as np
    center, scale = frame_params(mesh)
    tri = np.asarray(mesh.triangles, dtype=np.float64)
    bary = [(1 / 3, 1 / 3, 1 / 3), (0.6, 0.2, 0.2), (0.2, 0.6, 0.2), (0.2, 0.2, 0.6)][:max(1, int(n))]
    pts = np.stack([np.tensordot(tri, np.array(b), axes=([1], [0])) for b in bary], axis=1)
    return (pts - center) * scale


def voxel_index(points):
    import numpy as np
    return np.clip(np.floor((np.asarray(points) + 0.5) * GRID).astype(np.int64), 0, GRID - 1)


def lookup_voxel_colors(vox_xyz, vox_rgb, idx):
    """Цвет вокселя под каждой точкой: точное попадание в активный воксель, иначе ближайший активный (cKDTree по индексам) — доля промахов и расстояние в метаданные.
    idx: (M,3) int. Возврат: rgb uint8 (M,3), miss_share, max_miss_dist (в вокселях)."""
    import numpy as np
    from scipy.spatial import cKDTree
    vox_xyz = np.asarray(vox_xyz, dtype=np.int64)
    key = lambda a: (a[:, 0] * GRID + a[:, 1]) * GRID + a[:, 2]  # noqa: E731
    vk = key(vox_xyz)
    order = np.argsort(vk)
    vk_s = vk[order]
    q = key(idx)
    pos = np.clip(np.searchsorted(vk_s, q), 0, len(vk_s) - 1)
    hit = vk_s[pos] == q
    out = np.asarray(vox_rgb)[order[pos]].copy()
    maxd = 0.0
    if (~hit).any():
        d, j = cKDTree(vox_xyz).query(idx[~hit].astype(np.float64))
        out[~hit] = np.asarray(vox_rgb)[j]
        maxd = float(d.max())
    return out.astype(np.uint8), float((~hit).mean()), maxd


def quantize_rgb(rgb, step: int):
    import numpy as np
    if not step or step <= 0:
        return np.asarray(rgb, dtype=np.uint8)
    return np.clip((np.asarray(rgb, dtype=np.int32) + step // 2) // step * step, 0, 255).astype(np.uint8)


def build_palette(rgb, step: int = 16, min_share: float = 0.002, merge_dist: float = 32.0, max_colors: int = 64):
    """Главные цвета вокселей (аналог палитры Space/split.py апстрима): квантование → частоты → редкие (< min_share) выбрасываются как шум границ → близкие (≤ merge_dist) сливаются
    взвешенно, самые частые первыми. Возврат: центры float32 (K,3), по убыванию размера."""
    import numpy as np
    q = quantize_rgb(rgb, step).reshape(-1, 3)
    cols, cnt = np.unique(q, axis=0, return_counts=True)
    keep = cnt >= max(1, int(min_share * len(q)))
    if not keep.any():
        keep = cnt >= cnt.max()
    cols, cnt = cols[keep].astype(np.float64), cnt[keep]
    o = np.argsort(-cnt)
    centers, w = [], []
    for i in o:
        x, c = cols[i], int(cnt[i])
        if centers:
            d = np.linalg.norm(np.stack(centers) - x, axis=1)
            k = int(np.argmin(d))
            if d[k] <= merge_dist:
                centers[k] = (centers[k] * w[k] + x * c) / (w[k] + c)
                w[k] += c
                continue
        centers.append(x.copy())
        w.append(c)
    o2 = np.argsort(-np.array(w))[:max_colors]
    return np.stack(centers)[o2].astype(np.float32)


def assign_palette(rgb, centers):
    """Ближайший центр палитры для каждого цвета (…,3) → метки int (…)."""
    import numpy as np
    flat = np.asarray(rgb, dtype=np.float32).reshape(-1, 3)
    d = ((flat[:, None, :] - np.asarray(centers)[None, :, :]) ** 2).sum(-1)
    return np.argmin(d, axis=1).reshape(np.asarray(rgb).shape[:-1])


def smooth_small_parts(labels, face_adjacency, min_faces: int, passes: int = 3):
    """Части меньше min_faces отдаются самому частому соседнему ярлыку (по смежности граней); затем нумерация 0..K−1 по убыванию размера."""
    import numpy as np
    lab = np.asarray(labels).astype(np.int64).copy()
    adj = np.asarray(face_adjacency)
    for _ in range(passes):
        ids, cnt = np.unique(lab, return_counts=True)
        small = set(int(i) for i, c in zip(ids, cnt) if c < min_faces)
        if not small or len(small) == len(ids):
            break
        for s in sorted(small):
            fs = np.nonzero(lab == s)[0]
            if len(fs) == 0:
                continue
            m = np.isin(adj[:, 0], fs) ^ np.isin(adj[:, 1], fs)
            if not m.any():
                continue
            e = adj[m]
            other = np.where(np.isin(e[:, 0], fs), e[:, 1], e[:, 0])
            nb = lab[other]
            nb = nb[~np.isin(nb, list(small))]
            if len(nb):
                lab[fs] = np.bincount(nb).argmax()
    ids, cnt = np.unique(lab, return_counts=True)
    remap = {int(i): r for r, i in enumerate(ids[np.argsort(-cnt)])}
    return np.array([remap[int(x)] for x in lab], dtype=np.int32)


def faces_from_voxels(mesh, vox_xyz, vox_rgb, params: dict | None = None) -> dict:
    """Ядро без GPU: цвета вокселей (куб апстрима) + меш → метки граней. params: color_quant_step, merge_dist, min_share, min_part_faces, points_per_face."""
    import numpy as np
    p = params or {}
    n = int(p.get('points_per_face', 4))
    pts = face_sample_points(mesh, n)
    F = len(pts)
    rgb, miss, maxd = lookup_voxel_colors(vox_xyz, vox_rgb, voxel_index(pts.reshape(-1, 3)))
    pal = build_palette(vox_rgb, int(p.get('color_quant_step', 16)), float(p.get('min_share', 0.002)), float(p.get('merge_dist', 32.0)), int(p.get('max_colors', 64)))
    lab_pts = assign_palette(rgb, pal).reshape(F, n)
    k = len(pal)
    votes = np.zeros((F, k), dtype=np.int32)
    for j in range(n):
        np.add.at(votes, (np.arange(F), lab_pts[:, j]), 1)
    lab = votes.argmax(1)
    out = smooth_small_parts(lab, mesh.face_adjacency, int(p.get('min_part_faces', 50)))
    return {'faces': out, 'palette': pal.round().astype(int).tolist(), 'miss_share': round(miss, 4), 'miss_max_dist_vox': round(maxd, 2), 'n_palette': int(k)}


# ---------------------------------------------------------------- разреженное внимание: ветка sdpa (на 5090 нет flash-attn)
SDPA_BRANCH = """    elif config.ATTN == 'sdpa':                      # Ш5/T-183: ветка из Pixal3D/T-94 — flash-attn под sm_120 нет (разреженное внимание SegviGen знает только xformers/flash_attn/flash_attn_3)
        from torch.nn.functional import scaled_dot_product_attention as _sdpa
        if num_all_args == 1:
            q, k, v = qkv.unbind(dim=1)
        elif num_all_args == 2:
            k, v = kv.unbind(dim=1)
        q_offs = [0] + list(torch.cumsum(torch.tensor(q_seqlen), dim=0).tolist())
        kv_offs = [0] + list(torch.cumsum(torch.tensor(kv_seqlen), dim=0).tolist())
        outs = []
        for i in range(len(q_seqlen)):
            qi = q[q_offs[i]:q_offs[i + 1]].unsqueeze(0).permute(0, 2, 1, 3)
            ki = k[kv_offs[i]:kv_offs[i + 1]].unsqueeze(0).permute(0, 2, 1, 3)
            vi = v[kv_offs[i]:kv_offs[i + 1]].unsqueeze(0).permute(0, 2, 1, 3)
            outs.append(_sdpa(qi, ki, vi).permute(0, 2, 1, 3).squeeze(0))
        out = torch.cat(outs, dim=0)
"""
SDPA_MARK = "config.ATTN == 'sdpa'"
SDPA_CFG_OLD = "in ['xformers', 'flash_attn', 'flash_attn_3']:"
SDPA_TAIL = '    else:\n        raise ValueError(f"Unknown attention module: {config.ATTN}")'


def patch_sparse_sdpa(seg_dir: str) -> list:
    """`trellis2/modules/sparse/config.py` и `.../attention/full_attn.py` SegviGen (копия TRELLIS.2) знают только xformers/flash_attn/flash_attn_3; flash-attn под Blackwell (sm_120) в образе нет →
    на первом же шаге сэмплера `ValueError: Unknown attention module: sdpa`. Дописываем ветку sdpa (модель tex-flow — attn_mode='full', оконного внимания нет). Идемпотентно; нет якоря → RuntimeError."""
    done = []
    cfg = os.path.join(seg_dir, 'trellis2', 'modules', 'sparse', 'config.py')
    fa = os.path.join(seg_dir, 'trellis2', 'modules', 'sparse', 'attention', 'full_attn.py')
    t = open(cfg, encoding='utf-8').read()
    if "'sdpa'" not in t:
        if t.count(SDPA_CFG_OLD) != 1:
            raise RuntimeError('sparse/config.py: нет ожидаемой строки со списком бэкендов — патч sdpa не применён')
        open(cfg, 'w', encoding='utf-8').write(t.replace(SDPA_CFG_OLD, "in ['xformers', 'flash_attn', 'flash_attn_3', 'sdpa']:"))
        done.append('config')
    t = open(fa, encoding='utf-8').read()
    if SDPA_MARK not in t:
        if t.count(SDPA_TAIL) != 1:
            raise RuntimeError('sparse/attention/full_attn.py: нет ожидаемого хвоста с ValueError — патч sdpa не применён')
        open(fa, 'w', encoding='utf-8').write(t.replace(SDPA_TAIL, SDPA_BRANCH + SDPA_TAIL))
        done.append('full_attn')
    return done


# ---------------------------------------------------------------- бэкенд (GPU)
def _stub_bpy(segvigen_dir: str) -> None:
    """`inference_full.py` на уровне модуля импортирует `data_toolkit.bpy_render` → `import bpy` (в образе bpy нет; кадр рисует Blender подпроцессом). Подставляем пустой модуль."""
    if 'data_toolkit.bpy_render' in sys.modules:
        return
    pkg = types.ModuleType('data_toolkit')
    pkg.__path__ = []
    mod = types.ModuleType('data_toolkit.bpy_render')

    def render_from_transforms(*_a, **_k):
        raise RuntimeError('bpy в образе нет: кадр — render_condition() (Blender подпроцессом)')
    mod.render_from_transforms = render_from_transforms
    sys.modules['data_toolkit'] = pkg
    sys.modules['data_toolkit.bpy_render'] = mod


class SegviGenBackend:
    def __init__(self, step=None):
        self.step = step or (lambda name, line=None: None)
        self.trellis = os.environ.get('TRELLIS_MODEL', '/opt/weights/TRELLIS.2-4B')
        self.seg_dir = os.environ.get('SEGVIGEN_DIR', '/opt/SegviGen')
        self.ckpt = os.environ.get('SEGVIGEN_CKPT', '/opt/weights/SegviGen/full_seg.ckpt')
        self.dino_dir = os.environ.get('DINOV3_DIR', '/opt/weights/dinov3-vitl16-pretrain-lvd1689m')
        self.blender = os.environ.get('BLENDER', '/opt/blender/blender')

    def load(self) -> dict:
        import json
        miss = missing_files(self.trellis, self.seg_dir, self.ckpt, self.dino_dir, self.blender)
        if miss:
            raise RuntimeError('в образе нет файлов SegviGen: ' + '; '.join(miss[:6]))
        sys.path.insert(0, self.seg_dir)
        attn = os.environ.get('SPARSE_ATTN_BACKEND') or os.environ.get('ATTN_BACKEND') or 'flash_attn'
        if attn == 'sdpa':
            self.patched = patch_sparse_sdpa(self.seg_dir)                                        # идемпотентно; образ собирается уже с патчем, здесь — страховка
        elif importlib.util.find_spec('flash_attn') is None:
            raise RuntimeError(f'ATTN_BACKEND={attn}, а flash_attn в образе нет: задайте ATTN_BACKEND=sdpa')
        _stub_bpy(self.seg_dir)
        spec = importlib.util.spec_from_file_location('segvigen_inference_full', os.path.join(self.seg_dir, 'inference_full.py'))
        IF = importlib.util.module_from_spec(spec)
        sys.modules['segvigen_inference_full'] = IF
        spec.loader.exec_module(IF)
        import torch
        from collections import OrderedDict
        from trellis2 import models
        self.IF, self.torch = IF, torch
        P = trellis_paths(self.trellis)
        self.pipeline_args = json.load(open(P['pipeline_json']))['args']
        flow = models.from_pretrained(P['tex_flow'])
        self.gen3dseg = IF.Gen3DSeg(flow)
        sd = torch.load(self.ckpt, map_location='cpu', weights_only=False)['state_dict']             # Lightning-чекпойнт: weights_only=True на torch ≥2.6 не читает его
        self.gen3dseg.load_state_dict(OrderedDict((k.replace('gen3dseg.', ''), v) for k, v in sd.items()))
        del sd
        self.gen3dseg.eval().cuda()
        self.sampler = IF.Sampler()
        self.shape_enc = models.from_pretrained(P['shape_enc']).cuda().eval()
        self.tex_enc = models.from_pretrained(P['tex_enc']).cuda().eval()
        self.shape_dec = models.from_pretrained(P['shape_dec']).cuda().eval()
        self.tex_dec = models.from_pretrained(P['tex_dec']).cuda().eval()
        self.dino = IF.DinoV3FeatureExtractor(model_name=self.dino_dir)                                  # локальная папка, не HF-имя facebook/… (gated)
        self.dino.cuda()
        return {'segvigen_dir': self.seg_dir, 'ckpt': self.ckpt, 'dino_dir': self.dino_dir, 'trellis': self.trellis, 'attn': attn, 'sdpa_patched': getattr(self, 'patched', None)}

    def segment(self, mesh, params: dict, outdir: str) -> dict:
        import numpy as np
        IF, torch = self.IF, self.torch
        t0 = time.time()
        stages = {}

        def tick(name, line=None):
            stages[name] = round(time.time() - t0, 2)
            self.step(name, line)
        glb = os.path.join(outdir, 'input.glb')
        work = os.path.join(outdir, 'input_textured.glb')
        tick('textured')
        glb_use = work if ensure_textured(glb, work) else glb
        tick('render')
        png = os.path.join(outdir, 'cond_render.png')
        stages['render_s'] = render_condition(glb_use, png, self.blender, self.seg_dir, outdir)
        cond_img = alpha_condition_image(png)
        tick('voxelize')
        vxz = os.path.join(outdir, 'input.vxz')
        IF.process_glb_to_vxz(glb_use, vxz)
        tick('encode')
        shape_slat, meshes, subs, tex_slat = IF.vxz_to_latent_slat(self.shape_enc, self.shape_dec, self.tex_enc, vxz)
        cond = IF.get_cond(self.dino, [cond_img])
        tick('sample')
        torch.manual_seed(int(params.get('seed', 0)))
        out_slat = IF.tex_slat_sample_single(self.gen3dseg, self.sampler, self.pipeline_args, shape_slat, tex_slat, cond)
        tick('decode')
        with torch.no_grad():
            tex_voxels = self.tex_dec(out_slat, guide_subs=subs) * 0.5 + 0.5
        v = next(iter(zip(meshes, tex_voxels)))[1]                                                      # как slat_to_glb апстрима
        vox_xyz = v.coords[:, 1:].cpu().numpy().astype(np.int64)
        vox_rgb = (v.feats[:, :3].float().clamp(0, 1) * 255).round().cpu().numpy().astype(np.uint8)
        np.savez_compressed(os.path.join(outdir, 'segvigen_vox.npz'), xyz=vox_xyz.astype(np.int16), rgb=vox_rgb)
        tick('labels')
        r = faces_from_voxels(mesh, vox_xyz, vox_rgb, params)
        del shape_slat, meshes, subs, tex_slat, out_slat, tex_voxels, v, cond
        torch.cuda.empty_cache()
        tick('done')
        return {'faces': r['faces'], 'names': None,
                'extra': {'n_voxels': int(len(vox_xyz)), 'palette': r['palette'], 'n_palette': r['n_palette'], 'miss_share': r['miss_share'],
                          'miss_max_dist_vox': r['miss_max_dist_vox'], 'stages_s': stages, 'glb_textured_copy': glb_use != glb}}
