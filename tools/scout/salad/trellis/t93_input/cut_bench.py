#!/usr/bin/env python3
"""T-93 п.2: «сырая» мягкая маска разных моделей вырезки на ПРОЦЕССОРЕ (свободный счёт). Дальше — единая чистка (post.py) для всех.
  cut_bench.py --model birefnet|birefnet_hr|birefnet_hr_matting|birefnet_dynamic|ben2 --mode stretch|pad --src A|B [--size N] [--cores N] <ключ> […]
Источник: A — фото из фида (450 px, как берёт make_inputs), B — original_picture (image_url_hd). Маска: ~/remlab-logs/t93-1119/masks/<модель>_<режим>_<src><size>/<ключ>.mask.png (L, размер исходника) + times.json.
stretch — как у боевого `preprocess.cutout` (Resize((S,S)) искажает пропорции); pad — поля до квадрата цветом фона (медиана рамки), потом обрезать назад."""
import argparse
import json
import os
import sys
import time

import numpy as np
import torch
from PIL import Image

ROOT = '/home/pakar/remlab-logs/t93-1119'
INPUTS30 = '/home/pakar/remlab-logs/mesh-models-1118/trellis/inputs30'
REPOS = {'birefnet': 'ZhengPeng7/BiRefNet', 'birefnet_hr': 'ZhengPeng7/BiRefNet_HR', 'birefnet_hr_matting': 'ZhengPeng7/BiRefNet_HR-matting',
         'birefnet_dynamic': 'ZhengPeng7/BiRefNet_dynamic', 'birefnet_matting': 'ZhengPeng7/BiRefNet-matting'}
DEFAULT_SIZE = {'birefnet': 1024, 'birefnet_hr': 2048, 'birefnet_hr_matting': 2048, 'birefnet_dynamic': 1024, 'birefnet_matting': 1024, 'ben2': 1024}


def src_image(sku, which):
    key = sku.replace(':', '_')
    if which == 'A':
        # фото из фида: то, что реально ушло в пробу (inputs30 хранит только вырезку, поэтому берём скачанное; запасной путь — сама вырезка на белом)
        for ext in ('jpg', 'png', 'webp'):
            p = f'{ROOT}/photos/{key}/A_feed_picture.{ext}'
            if os.path.exists(p):
                return Image.open(p).convert('RGB')
        rgba = Image.open(f'{INPUTS30}/{key}.rgba.png').convert('RGBA')
        bg = Image.new('RGBA', rgba.size, (255, 255, 255, 255))
        bg.alpha_composite(rgba)
        return bg.convert('RGB')
    for ext in ('jpg', 'png', 'webp'):
        p = f'{ROOT}/photos/{key}/B_original_picture.{ext}'
        if os.path.exists(p):
            return Image.open(p).convert('RGB')
    raise SystemExit(f'нет фото B для {sku}')


def frame_bg(im):
    a = np.asarray(im)
    band = np.concatenate([a[:3].reshape(-1, 3), a[-3:].reshape(-1, 3), a[:, :3].reshape(-1, 3), a[:, -3:].reshape(-1, 3)])
    return tuple(int(v) for v in np.median(band, axis=0))


def prep(im, size, mode):
    """-> (PIL RGB нужного размера, как вернуть маску к исходному размеру: функция)."""
    W, H = im.size
    if mode == 'stretch':
        return im.resize((size, size), Image.BICUBIC), (lambda m: m.resize((W, H), Image.BICUBIC))
    s = max(W, H)
    pad = Image.new('RGB', (s, s), frame_bg(im))
    ox, oy = (s - W) // 2, (s - H) // 2
    pad.paste(im, (ox, oy))
    return pad.resize((size, size), Image.BICUBIC), (lambda m: m.resize((s, s), Image.BICUBIC).crop((ox, oy, ox + W, oy + H)))


def load(model):
    if model == 'ben2':
        from huggingface_hub import hf_hub_download
        sys.path.insert(0, os.path.dirname(hf_hub_download('PramaLLC/BEN2', 'BEN2.py')))
        import BEN2 as B
        m = B.BEN_Base()
        m.loadcheckpoints(hf_hub_download('PramaLLC/BEN2', 'BEN2_Base.pth'))
        return m.eval()
    from transformers import AutoModelForImageSegmentation
    return AutoModelForImageSegmentation.from_pretrained(REPOS[model], trust_remote_code=True).float().eval()


def run(model, net, im, size, mode):
    if model == 'ben2':
        # BEN2 сам готовит вход (1024) и возвращает RGBA; режимов у него нет — отдаём как есть, альфа и есть маска
        out = net.inference(im, refine_foreground=False)
        return out.getchannel('A') if out.mode == 'RGBA' else out.convert('L')
    from torchvision import transforms
    x, back = prep(im, size, mode)
    tf = transforms.Compose([transforms.ToTensor(), transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])
    with torch.no_grad():
        pred = net(tf(x).unsqueeze(0))[-1].sigmoid().cpu()[0].squeeze()
    m = Image.fromarray((pred.numpy() * 255).astype(np.uint8))
    return back(m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', required=True)
    ap.add_argument('--mode', default='stretch')
    ap.add_argument('--src', default='B')
    ap.add_argument('--size', type=int, default=0)
    ap.add_argument('--cores', type=int, default=4)
    ap.add_argument('skus', nargs='+')
    a = ap.parse_args()
    torch.set_num_threads(a.cores)
    size = a.size or DEFAULT_SIZE[a.model]
    tag = f'{a.model}_{a.mode}_{a.src}{size}'
    out = f'{ROOT}/masks/{tag}'
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    net = load(a.model)
    times = {'load_s': round(time.time() - t0, 1), 'cores': a.cores, 'device': 'cpu', 'torch': torch.__version__}
    print(tag, 'загружена за', times['load_s'], 'с', flush=True)
    per = {}
    for sku in a.skus:
        im = src_image(sku, a.src)
        t1 = time.time()
        m = run(a.model, net, im, size, a.mode)
        dt = round(time.time() - t1, 1)
        m.save(f"{out}/{sku.replace(':', '_')}.mask.png")
        per[sku] = {'src_size': list(im.size), 'seconds': dt}
        print(tag, sku, im.size, f'{dt} с', flush=True)
    times['per'] = per
    json.dump(times, open(f'{out}/times.json', 'w'), indent=1)


main()
