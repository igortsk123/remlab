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


HY_ROOT = os.environ.get('HY_ROOT', '/opt/hunyuan')


def _fix_torchvision():
    """Апстрим кладёт рядом `torchvision_fix` и просит применить его до импортов — иначе
    на свежих torchvision ломается загрузка их трансформов. Молча пропустить нельзя:
    падение будет далеко от причины."""
    try:
        from torchvision_fix import apply_fix
        apply_fix()
    except Exception:  # noqa: BLE001 — модуля нет: работаем как есть, как и в их demo.py
        pass


def shape_pipeline():
    """Импорты и вызовы — как в `demo.py` апстрима, не по догадке.

    `from_pretrained` принимает путь к КОРНЮ набора весов и сам находит подпапку
    `hunyuan3d-dit-v2-1`; передача subfolder вручную ломается на их загрузчике.
    """
    global _SHAPE
    if _SHAPE is None:
        _fix_torchvision()
        from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline
        _SHAPE = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(MODEL_PATH)
    return _SHAPE


def paint_pipeline():
    """`textureGenPipeline` лежит в корне hy3dpaint и импортируется верхним уровнем
    (hy3dpaint в PYTHONPATH), а не как `hy3dpaint.textureGenPipeline`.

    Пути конфигов задаются явно и абсолютно: апстрим пишет их относительно корня
    репозитория, и при запуске из другого каталога пайплайн не находит ни ppbr-конфиг,
    ни чекпойнт RealESRGAN.
    """
    global _PAINT
    if _PAINT is None:
        from textureGenPipeline import Hunyuan3DPaintConfig, Hunyuan3DPaintPipeline
        cfg = Hunyuan3DPaintConfig(int(os.environ.get('MAX_NUM_VIEW', 6)),
                                   int(os.environ.get('PAINT_RESOLUTION', 512)))
        cfg.realesrgan_ckpt_path = os.path.join(HY_ROOT, 'hy3dpaint/ckpt/RealESRGAN_x4plus.pth')
        cfg.multiview_cfg_path = os.path.join(HY_ROOT, 'hy3dpaint/cfgs/hunyuan-paint-pbr.yaml')
        cfg.custom_pipeline = os.path.join(HY_ROOT, 'hy3dpaint/hunyuanpaintpbr')
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


def generate(image, out_dir: str, seed: int = 0, params: dict | None = None,
             paint_image=None) -> dict:
    """Одно задание: картинка → GLB с PBR-картами. Возвращает пути, времена и пики памяти.

    `image` — RGBA на полном холсте: альфа и есть маска товара, `ImageProcessorV2` сам кропает
    её по bbox и добавляет поле. `paint_image` — та же вырезка, но уже кропнутая: покраска вход
    не центрирует, только ужимает до 512, и без кропа половина её разрешения уходит на пустоту.
    """
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
    painted = paint_pipeline()(mesh_path=raw_glb, image_path=paint_image or image)
    timings['paint'] = round(time.time() - t1, 1)
    peaks['paint_gb'] = _peak_gb()

    t2 = time.time()
    final_glb = os.path.join(out_dir, 'model.glb')
    if isinstance(painted, str) and painted.lower().endswith('.obj'):
        # Покраска возвращает OBJ + mtl + карты РЯДОМ ОТДЕЛЬНЫМИ ФАЙЛАМИ. Переименовать его
        # в .glb — потерять материалы: первая десятка 29.08 уехала к нам геометрией без
        # текстур именно так. Конвертация обязана собрать САМОДОСТАТОЧНЫЙ GLB с PBR-картами —
        # это наш bpy-free convert_obj_to_glb (pygltflib, карты внутри base64).
        from DifferentiableRenderer.mesh_utils import convert_obj_to_glb
        ok = convert_obj_to_glb(painted, final_glb)
        if not ok or not os.path.exists(final_glb) or os.path.getsize(final_glb) == 0:
            raise RuntimeError('OBJ→GLB конвертация не удалась')
    elif isinstance(painted, str):
        os.replace(painted, final_glb)
    else:
        painted.export(final_glb)
    timings['export'] = round(time.time() - t2, 1)
    timings['total'] = round(time.time() - t0, 1)

    if STAGED:
        _unload('paint')

    return {'glb': final_glb, 'shape_glb': raw_glb, 'timings': timings,
            'gpu': {'name': torch.cuda.get_device_name(0), 'staged': STAGED, **peaks}}
