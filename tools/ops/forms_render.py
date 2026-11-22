#!/usr/bin/env python3
"""T-180/5 (директор 22.11, владелец TG 1228): серые рендеры ФОРМ TRELLIS.2 для страницы этапа «форма» — 2 ракурса (az000 и az225), один и тот же свет «за камерой», режим «глина» (без цвета).
Бесплатно (процессор): Blender 4.5 + `tools/scout/salad/trellis/render_stand.py`. ОДНО задание heavy-slot (--prio 1) на все товары — цикл по товарам внутри, не билет на каждый
(директор 22.11: 31 билет × 95 с тонули в очереди); порог памяти по замеру прогона (пик дерева 1,51 ГБ → заявка 2,3 ГБ = 1,5 × пик). Уже отрисованное пропускается (повторный запуск дорисовывает).
Ракурсы: az000 — «как на фото» (спереди, лёгкий сверху 15°), az225 — 3/4 сзади; свет в обоих одинаков относительно камеры.

  python3 tools/ops/forms_render.py --glbs <папка с GLB форм> --out <папка кадров> (--set set40.json | --ids 99272_1,112923_2) [--max N] [--cores 2] [--samples 16] [--no-slot]

Кадры: `<out>/<товар>/01_az000_clay.png`, `02_az225_clay.png`. GLB ищется как `<товар>*.glb` (предпочтительно `-hd`, свежий) — `paint_run_report.find_glb`. Код 1 — если у кого-то кадров нет (причина — в `<out>/render.log`)."""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paint_run_report as prr  # noqa: E402

VIEWS = ('az000', 'az225')
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
    ap.add_argument('--samples', type=int, default=16)
    ap.add_argument('--min-gb', type=float, default=2.3, help='заявка памяти: 1,5 × пик дерева Blender на форме (замер 1,51 ГБ)')
    ap.add_argument('--no-slot', action='store_true', help='без очереди heavy-slot (отладка)')
    ap.add_argument('--inner', action='store_true', help=argparse.SUPPRESS)
    a = ap.parse_args()
    ids = [x for x in a.ids.split(',') if x]
    if a.set:
        raw = json.load(open(os.path.expanduser(a.set), encoding='utf-8'))
        ids += [it['id'] for it in (raw['items'] if isinstance(raw, dict) else raw)]
    glbs, out = os.path.expanduser(a.glbs), os.path.expanduser(a.out)
    os.makedirs(out, exist_ok=True)
    if not a.inner and not a.no_slot:                                        # внешний запуск: сам себя — под ОДНИМ заданием heavy-slot
        inner = [sys.executable, os.path.abspath(__file__), '--inner'] + [x for x in sys.argv[1:]]
        cmd = [os.path.join(HERE, 'heavy-slot.sh'), 't180-forms-all', '--prio', '1', '--cores', str(a.cores), '--min-gb', f'{a.min_gb:g}', '--timeout', '14400', '--',
               'timeout', '-k', '20', '7200'] + inner
        return subprocess.run(cmd).returncode
    todo = [s for s in ids if find_glb_(glbs, s) and not frames_of(out, s)]
    no_form = [s for s in ids if not find_glb_(glbs, s)]
    if a.max:
        todo = todo[:a.max]
    print(f'товаров {len(ids)} · нет формы {len(no_form)} · уже отрисовано {len([s for s in ids if frames_of(out, s)])} · рисую {len(todo)}', flush=True)
    log = os.path.join(out, 'render.log')
    fails = 0
    for s in todo:
        g = find_glb_(glbs, s)
        t0 = time.time()
        cmd = ['timeout', '-k', '20', '900', BLENDER, '-b', '-P', os.path.join(HERE, '..', 'scout', 'salad', 'trellis', 'render_stand.py'), '--',
               '--glb', g, '--out', os.path.join(out, s), '--samples', str(a.samples), '--modes', 'clay', '--only', ','.join(VIEWS), '--threads', str(a.cores), '--w', '1200', '--h', '900']
        with open(log, 'a', encoding='utf-8') as lg:
            lg.write(f'== {s} {g}\n')
            lg.flush()
            rc = subprocess.run(cmd, stdout=lg, stderr=subprocess.STDOUT).returncode
        ok = bool(frames_of(out, s))
        fails += 0 if ok else 1
        print(f"{'ok ' if ok else 'НЕТ'} {s} rc={rc} {time.time() - t0:.0f} с", flush=True)
    return 1 if fails else 0


def find_glb_(glbs: str, sku: str):
    return prr.find_glb(glbs, sku)


if __name__ == '__main__':
    sys.exit(main())
