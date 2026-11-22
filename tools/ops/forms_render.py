#!/usr/bin/env python3
"""T-180/5 (директор 22.11, владелец TG 1228): серые рендеры ФОРМ TRELLIS.2 для страницы этапа «форма» — 2 ракурса (az000 и az225), один и тот же свет «за камерой», режим «глина» (без цвета).
Бесплатно (процессор): Blender 4.5 + `tools/scout/stablegen/render_stand.py`. ОДНО задание heavy-slot (--prio 1) на все товары — цикл по товарам внутри, не билет на каждый
(директор 22.11: 31 билет × 95 с тонули в очереди); порог памяти по замеру прогона (пик дерева 1,51 ГБ → заявка 2,3 ГБ = 1,5 × пик). Уже отрисованное пропускается (повторный запуск дорисовывает).
Ракурсы: az000 — «как на фото» (спереди, лёгкий сверху 15°), az225 — 3/4 сзади; свет в обоих одинаков относительно камеры.
T-180/7 (директор 22.11, владелец TG 1373/1376): `--accept` — кадры ПРИЁМКИ формы по правилам `plans/mesh-type-rules-01.md` § «Приёмка формы TRELLIS.2»: 5 видов (спереди 0°, сбоку 90°, строго сзади 180°,
3/4 сзади 225°, косой сверху 40°; у диванов/кресел/стульев — ещё низкий боковой) × 2 света (обычный за камерой и боковой скользящий); глина, одинаковый масштаб на товар. Все виды — таблица `VIEW_DEFS`
здесь же (в render_stand констант нет, он получает `--views`). Кадры: `<out>/<товар>/NN_<вид>_clay.png` и `NN_<вид>_clay_graze.png`. `--shade recalc` — гладкие нормали (проверка «грань = плоский показ»).

  python3 tools/ops/forms_render.py --glbs <папка с GLB форм> --out <папка кадров> (--set set40.json | --ids 99272_1,112923_2) [--max N] [--cores 2] [--samples 16] [--no-slot]

Кадры: `<out>/<товар>/01_az000_clay.png`, `02_az225_clay.png`. GLB ищется как `<товар>*.glb` (предпочтительно `-hd`, свежий) — `find_glb_`. Код 1 — если у кого-то кадров нет (причина — в `<out>/render.log`)."""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

VIEW_DEFS = {'az000': (0, 15), 'az090': (90, 15), 'az180': (180, 15), 'az225': (225, 15), 'top40': (45, 40), 'low090': (90, 3)}    # вид → (азимут°, угол места°): ЕДИНСТВЕННЫЙ источник ракурсов
VIEWS = ('az000', 'az225')                                                                                                # страница этапа «форма» (T-180/5)
ACCEPT_VIEWS = ('az000', 'az090', 'az180', 'az225', 'top40')                                                              # приёмка формы (T-180/7)
SEAT_VIEWS = ('low090',)                                                                                                  # + у сидячих: низкий боковой (спинка, подлокотники, ножки, низ)
SEAT_ROLES = ('диван', 'кресло', 'стул', 'кушетка')
ACCEPT_LIGHTS = ('key', 'graze')
BLENDER = os.path.expanduser('~/opt/blender-4.5.9/blender')
RENDER_STAND = os.path.join(HERE, '..', 'scout', 'stablegen', 'render_stand.py')


def accept_views(role: str = '') -> tuple:
    """Виды приёмки для роли товара: общие + у сидячих (диван/кресло/стул/кушетка) низкий боковой."""
    return ACCEPT_VIEWS + (SEAT_VIEWS if any((role or '').lower().startswith(r) for r in SEAT_ROLES) else ())


def frame_names(views, lights=('key',)) -> list:
    """Имена файлов в порядке, в котором их пишет render_stand: по видам, внутри вида — по светам (NN сквозной)."""
    out, n = [], 0
    for v in views:
        for lt in lights:
            n += 1
            out.append(f'{n:02d}_{v}_clay' + ('_graze' if lt == 'graze' else '') + '.png')
    return out


def render_cmd(glb: str, out: str, views, lights, samples: int, cores: int, shade: str = 'orig') -> list:
    """Команда Blender для одного товара; виды и свет — из таблиц выше."""
    spec = ','.join(f'{v}:{VIEW_DEFS[v][0]}:{VIEW_DEFS[v][1]}' for v in views)
    cmd = ['timeout', '-k', '20', '900', BLENDER, '-b', '-P', RENDER_STAND, '--', '--glb', glb, '--out', out, '--samples', str(samples), '--modes', 'clay', '--views', spec,
           '--lights', ','.join(lights), '--threads', str(cores), '--w', '1200', '--h', '900']
    return cmd + (['--shade', shade] if shade != 'orig' else [])


def frames_of(out: str, sku: str, views=VIEWS, lights=('key',)) -> list:
    """Готовые кадры товара в порядке видов × светов (пусто, если хоть одного нет)."""
    d = os.path.join(out, sku)
    got = []
    for v in views:
        for lt in lights:
            suf = f'_{v}_clay' + ('_graze' if lt == 'graze' else '') + '.png'
            m = [f for f in sorted(os.listdir(d)) if f.endswith(suf)] if os.path.isdir(d) else []
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
    ap.add_argument('--accept', action='store_true', help='кадры приёмки формы: 5 видов (+низкий боковой у сидячих) × 2 света (T-180/7)')
    ap.add_argument('--shade', default='orig', choices=['orig', 'recalc', 'flat'], help='нормали: orig — как в GLB; recalc — гладкие')
    ap.add_argument('--inner', action='store_true', help=argparse.SUPPRESS)
    a = ap.parse_args()
    ids = [x for x in a.ids.split(',') if x]
    roles = {}
    if a.set:
        raw = json.load(open(os.path.expanduser(a.set), encoding='utf-8'))
        its = raw['items'] if isinstance(raw, dict) else raw
        ids += [it['id'] for it in its]
        roles = {it['id']: it.get('role', '') for it in its}
    lights = ACCEPT_LIGHTS if a.accept else ('key',)

    def views_of(s):
        return accept_views(roles.get(s, '')) if a.accept else VIEWS
    glbs, out = os.path.expanduser(a.glbs), os.path.expanduser(a.out)
    os.makedirs(out, exist_ok=True)
    if not a.inner and not a.no_slot:                                        # внешний запуск: сам себя — под ОДНИМ заданием heavy-slot
        inner = [sys.executable, os.path.abspath(__file__), '--inner'] + [x for x in sys.argv[1:]]
        cmd = [os.path.join(HERE, 'heavy-slot.sh'), 't180-forms-all', '--prio', '1', '--cores', str(a.cores), '--min-gb', f'{a.min_gb:g}', '--timeout', '14400', '--',
               'timeout', '-k', '20', '7200'] + inner
        return subprocess.run(cmd).returncode
    todo = [s for s in ids if find_glb_(glbs, s) and not frames_of(out, s, views_of(s), lights)]
    no_form = [s for s in ids if not find_glb_(glbs, s)]
    if a.max:
        todo = todo[:a.max]
    print(f'товаров {len(ids)} · нет формы {len(no_form)} · уже отрисовано {len([s for s in ids if frames_of(out, s, views_of(s), lights)])} · рисую {len(todo)}', flush=True)
    log = os.path.join(out, 'render.log')
    fails = 0
    for s in todo:
        g = find_glb_(glbs, s)
        t0 = time.time()
        cmd = render_cmd(g, os.path.join(out, s), views_of(s), lights, a.samples, a.cores, a.shade)
        with open(log, 'a', encoding='utf-8') as lg:
            lg.write(f'== {s} {g}\n')
            lg.flush()
            rc = subprocess.run(cmd, stdout=lg, stderr=subprocess.STDOUT).returncode
        ok = bool(frames_of(out, s, views_of(s), lights))
        fails += 0 if ok else 1
        print(f"{'ok ' if ok else 'НЕТ'} {s} rc={rc} {time.time() - t0:.0f} с", flush=True)
    return 1 if fails else 0


def find_glb_(glbs: str, sku: str):
    """GLB формы товара в папке: `<товар>*.glb`, предпочтительно `-hd`, из равных — свежий; без `.audit.glb`/`.raw.glb`. Нет — None."""
    try:
        names = [n for n in os.listdir(glbs) if (n.startswith(sku + '-') or n == sku + '.glb') and n.endswith('.glb') and not n.endswith(('.audit.glb', '.raw.glb'))]
    except OSError:
        return None
    if not names:
        return None
    names.sort(key=lambda n: (('-hd' in n), os.path.getmtime(os.path.join(glbs, n))), reverse=True)
    return os.path.join(glbs, names[0])


if __name__ == '__main__':
    sys.exit(main())
