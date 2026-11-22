#!/usr/bin/env python3
"""T-180/5 (директор 22.11, владелец TG 1228): серые рендеры ФОРМ TRELLIS.2 для страницы этапа «форма» — 2 ракурса (az045 и az225), один и тот же свет «за камерой», режим «глина» (без цвета).
Бесплатно (процессор): Blender 4.5 + `tools/scout/salad/trellis/render_stand.py`, каждый товар — отдельным заданием heavy-slot (--prio 1). Уже отрисованное пропускается (повторный запуск дорисовывает).

  python3 tools/ops/forms_render.py --glbs <папка с GLB форм> --out <папка кадров> (--set set40.json | --ids 99272_1,112923_2) [--max N] [--cores 2]

Кадры: `<out>/<товар>/01_az045_clay.png`, `02_az225_clay.png`. GLB ищется как `<товар>*.glb` (предпочтительно `-hd`, свежий) — `paint_run_report.find_glb`. Код 1 — если у кого-то кадров нет (причина — в `<out>/render.log`)."""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paint_run_report as prr  # noqa: E402

VIEWS = ('az045', 'az225')
BLENDER = os.path.expanduser('~/opt/blender-4.5.9/blender')


def frames_of(out: str, sku: str) -> list:
    """Готовые кадры товара в порядке VIEWS (пусто, если хоть одного нет)."""
    d = os.path.join(out, sku)
    got = []
    for v in VIEWS:
        m = [f for f in sorted(os.listdir(d)) if f.endswith(f'_{v}_clay.png')] if os.path.isdir(d) else []
        if not m:
            return []
        got.append(os.path.join(d, m[0]))
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--glbs', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--set')
    ap.add_argument('--ids', default='')
    ap.add_argument('--max', type=int, default=0, help='не больше N товаров за запуск (проба вида)')
    ap.add_argument('--cores', type=int, default=2)
    a = ap.parse_args()
    ids = [x for x in a.ids.split(',') if x]
    if a.set:
        raw = json.load(open(os.path.expanduser(a.set), encoding='utf-8'))
        ids += [it['id'] for it in (raw['items'] if isinstance(raw, dict) else raw)]
    glbs, out = os.path.expanduser(a.glbs), os.path.expanduser(a.out)
    os.makedirs(out, exist_ok=True)
    todo = [s for s in ids if prr.find_glb(glbs, s) and not frames_of(out, s)]
    skipped = [s for s in ids if not prr.find_glb(glbs, s)]
    if a.max:
        todo = todo[:a.max]
    print(f'товаров {len(ids)} · нет формы {len(skipped)} · уже отрисовано {len([s for s in ids if frames_of(out, s)])} · рисую {len(todo)}', flush=True)
    log = os.path.join(out, 'render.log')
    fails = 0
    for s in todo:
        g = prr.find_glb(glbs, s)
        cmd = [os.path.join(HERE, 'heavy-slot.sh'), f't180-form-{s[-8:]}', '--prio', '1', '--cores', str(a.cores), '--min-gb', '3', '--timeout', '3000', '--',
               'timeout', '-k', '20', '3000', BLENDER, '-b', '-P', os.path.join(HERE, '..', 'scout', 'salad', 'trellis', 'render_stand.py'), '--',
               '--glb', g, '--out', os.path.join(out, s), '--samples', '32', '--modes', 'clay', '--only', ','.join(VIEWS), '--threads', str(a.cores), '--w', '1200', '--h', '900']
        with open(log, 'a', encoding='utf-8') as lg:
            lg.write(f'== {s} {g}\n')
            lg.flush()
            rc = subprocess.run(cmd, stdout=lg, stderr=subprocess.STDOUT).returncode
        ok = bool(frames_of(out, s))
        fails += 0 if ok else 1
        print(f"{'ok ' if ok else 'НЕТ'} {s} rc={rc}", flush=True)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
