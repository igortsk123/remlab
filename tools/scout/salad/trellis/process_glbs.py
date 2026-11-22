#!/usr/bin/env python3
"""КОНВЕЙЕР ПОСЛЕ ПРОГОНА МОДЕЛИ (T-20261118-91): сырой GLB каждого товара → очистка одним правилом → кадры стенда → аудит-кадр удалённого → results.json для страницы.

На товар: ① `mesh_clean.clean_glb` (плита у пола отрезана одинаково у ВСЕХ моделей; метрики и `.audit.glb`); ② кадры стенда `render_stand.py` по ЧИСТОМУ мешу — набор видов
`--views` × режимы `--modes` (по умолчанию 4 вида × текстура/«глина» = 8 кадров; полные 20 — `--views az000,az045,az090,az135,az180,az225,az270,az315,top55,bot-20`);
③ кадр-аудит `az045` по `.audit.glb` (удалённое красным; смотреть глазами, не срезано ли лишнее). Блендер — под `tools/ops/heavy-slot.sh` (4 ядра, очередь).
Готовое не повторяется (метка `done` в папке кадров). `--watch` — ждать новые GLB, пока не обработан весь набор или не истёк `--max-wait-min`.

  python3 process_glbs.py --model trellis2 [--glb-suffix -1024-42-0] [--watch] [--samples 32]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mesh_clean  # noqa: E402

ROOT = os.path.expanduser('~/remlab-logs/mesh-models-1118')
REPO = os.path.normpath(os.path.join(HERE, '..', '..', '..', '..'))
BLENDER = os.path.expanduser('~/opt/blender-4.5.9/blender')


def fn(sku: str) -> str:
    return sku.replace(':', '_')


def render(label: str, glb: str, out: str, views: str, modes: str, samples: int, log: str) -> int:
    cmd = [os.path.join(REPO, 'tools/ops/heavy-slot.sh'), label, '--cores', '4', '--min-gb', '3', '--timeout', '3000', '--',
           BLENDER, '-b', '-P', os.path.join(HERE, 'render_stand.py'), '--', '--glb', glb, '--out', out, '--samples', str(samples), '--modes', modes, '--only', views]
    with open(log, 'a', encoding='utf-8') as f:
        return subprocess.call(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=REPO)


def one(model: str, c: dict, a, summary: dict) -> bool:
    sku = c['sku']
    raw = os.path.join(a.glb_dir, f'{fn(sku)}{a.glb_suffix}.glb')
    if not os.path.exists(raw):
        return False
    frames = os.path.join(a.frames, model, fn(sku))
    if os.path.exists(os.path.join(frames, 'done')):
        return True
    m = mesh_clean.clean_glb(raw, dims_cm=c.get('dims_cm'))
    clean = raw[:-4] + '.clean.glb'
    log = os.path.join(a.frames, f'process-{model}.log')
    os.makedirs(frames, exist_ok=True)
    rc = render(f'p91-{model[:4]}-{fn(sku)[-6:]}', clean, frames, a.views, a.modes, a.samples, log)
    if m.get('audit_glb'):
        render(f'p91a-{model[:4]}-{fn(sku)[-6:]}', raw[:-4] + '.audit.glb', os.path.join(a.audit, model, fn(sku)), 'az045', 'tex', a.samples, log)
    summary[sku] = {'status': 'done' if rc == 0 else 'frames_failed', 'triangles': m.get('clean_tris'), 'size_mb': round(os.path.getsize(clean) / 2 ** 20, 1),
                    'note': f"плоский слой {int(m['flat_layer']['tris_share'] * 100)} %, отрезано {m.get('removed', {}).get('tris', 0)} треуг.; пропорции без слоя {m.get('item_ratio_w_d_h')} (фид {m.get('feed_ratio_w_d_h')})"}
    if rc == 0:
        open(os.path.join(frames, 'done'), 'w').write(time.strftime('%F %T'))
    print(time.strftime('%H:%M:%S'), sku, summary[sku]['status'], flush=True)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', required=True)
    ap.add_argument('--glb-dir', default=os.path.join(ROOT, 'trellis'))
    ap.add_argument('--glb-suffix', default='-1024-42-0')
    ap.add_argument('--set', default=os.path.join(ROOT, 'trellis', 'set30.json'))
    ap.add_argument('--frames', default=os.path.join(ROOT, 'frames'))
    ap.add_argument('--audit', default=os.path.join(ROOT, 'frames-audit'))
    ap.add_argument('--views', default='az000,az045,az180,top55')
    ap.add_argument('--modes', default='tex,clay')
    ap.add_argument('--samples', type=int, default=32)
    ap.add_argument('--watch', action='store_true')
    ap.add_argument('--max-wait-min', type=int, default=240)
    a = ap.parse_args()
    items = json.load(open(a.set, encoding='utf-8'))
    rj = os.path.join(a.frames, a.model, 'results.json')
    os.makedirs(os.path.dirname(rj), exist_ok=True)
    summary = json.load(open(rj, encoding='utf-8')) if os.path.exists(rj) else {}
    t0 = time.time()
    while True:
        did = 0
        left = 0
        for c in items:
            if os.path.exists(os.path.join(a.frames, a.model, fn(c['sku']), 'done')):
                continue
            if one(a.model, c, a, summary):
                did += 1
                json.dump(summary, open(rj, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            else:
                left += 1
        if not a.watch or left == 0 or time.time() - t0 > a.max_wait_min * 60:
            print(f'итого: обработано в этом проходе {did}, ждёт GLB {left}', flush=True)
            return 0
        if did == 0:
            time.sleep(120)


if __name__ == '__main__':
    sys.exit(main())
