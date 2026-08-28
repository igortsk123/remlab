"""Hunyuan3D 2.1: форма → выгрузка → PBR-текстура, с замером памяти и времени по стадиям.

ГЛАВНОЕ РЕШЕНИЕ — СТАДИЙНОСТЬ. Официальные требования 2.1: форма 10 ГБ VRAM, покраска 21 ГБ,
обе модели одновременно 29 ГБ. Публичные замеры «139 с на модель» получены на 24-гиговой
4090, где обе модели держат в памяти и система вынуждена выгружать веса в RAM.
Если выгружать форму ПЕРЕД покраской, пик равен 21 ГБ и укладывается в 24 ГБ без offload.
Это гипотеза, которую пилот обязан проверить измерением, поэтому режим переключаемый
(`STAGED=0/1`) и обе стадии инструментированы: без парного замера вывод сделать нельзя.

Времена и пики пишутся в манифест каждого ассета — из них потом считается не «цена за
генерацию», а цена за ГОДНЫЙ ассет с учётом всех попыток.
"""
import gc
import os
import time

import torch

STAGED = os.environ.get('STAGED', '1') == '1'
WEIGHTS = os.environ.get('WEIGHTS_DIR', '/opt/weights')
MODEL_PATH = os.path.join(WEIGHTS, 'hunyuan3d-2.1')

_SHAPE = None
_PAINT = None


def _peak_gb() -> float:
    return round(torch.cuda.max_memory_allocated() / 2 ** 30, 2)


def _free():
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()


def shape_pipeline():
    global _SHAPE
    if _SHAPE is None:
        from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline
        _SHAPE = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
            MODEL_PATH, subfolder='hunyuan3d-dit-v2-1')
    return _SHAPE


def paint_pipeline():
    global _PAINT
    if _PAINT is None:
        from hy3dpaint.textureGenPipeline import Hunyuan3DPaintConfig, Hunyuan3DPaintPipeline
        cfg = Hunyuan3DPaintConfig(max_num_view=6, resolution=512)
        cfg.multiview_pretrained_path = os.path.join(MODEL_PATH, 'hunyuan3d-paintpbr-v2-1')
        _PAINT = Hunyuan3DPaintPipeline(cfg)
    return _PAINT


def _unload(name: str):
    """Выгрузка стадии. Без явного удаления ссылок и сборки мусора VRAM не возвращается —
    и весь смысл стадийности теряется."""
    global _SHAPE, _PAINT
    if name == 'shape':
        _SHAPE = None
    else:
        _PAINT = None
    _free()


def generate(image, out_dir: str, seed: int = 0, params: dict | None = None) -> dict:
    """Одно задание: картинка → GLB с PBR-картами. Возвращает пути, времена и пики памяти."""
    p = {'octree_resolution': 380, 'num_inference_steps': 50, 'guidance_scale': 5.0}
    p.update(params or {})
    os.makedirs(out_dir, exist_ok=True)
    timings, peaks = {}, {}
    generator = torch.Generator(device='cuda').manual_seed(seed)

    _free()
    t0 = time.time()
    mesh = shape_pipeline()(
        image=image, generator=generator,
        octree_resolution=p['octree_resolution'],
        num_inference_steps=p['num_inference_steps'],
        guidance_scale=p['guidance_scale'])[0]
    timings['shape'] = round(time.time() - t0, 1)
    peaks['shape_gb'] = _peak_gb()

    raw_glb = os.path.join(out_dir, 'shape.glb')
    mesh.export(raw_glb)

    if STAGED:
        _unload('shape')          # ← ради этой строки вся конструкция и затевалась

    t1 = time.time()
    painted = paint_pipeline()(mesh_path=raw_glb, image_path=image)
    timings['paint'] = round(time.time() - t1, 1)
    peaks['paint_gb'] = _peak_gb()

    t2 = time.time()
    final_glb = os.path.join(out_dir, 'model.glb')
    if isinstance(painted, str):
        os.replace(painted, final_glb)
    else:
        painted.export(final_glb)
    timings['export'] = round(time.time() - t2, 1)
    timings['total'] = round(time.time() - t0, 1)

    if STAGED:
        _unload('paint')

    return {'glb': final_glb, 'shape_glb': raw_glb, 'timings': timings,
            'gpu': {'name': torch.cuda.get_device_name(0), 'staged': STAGED, **peaks}}
