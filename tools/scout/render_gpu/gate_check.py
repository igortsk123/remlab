#!/usr/bin/env python3
"""Проверка ВОРОТ сторожа кадров на НАСТОЯЩИХ заказах (render-qa-gate-01, шаг 5, T-20261118-03/7): боевой `LocalCpuExecutor` (процессор, Blender, без платного),
но сборка сцены берётся из уже подготовленного заказа `~/scout-cache/render-prepared/<ключ>/{dump,scene}` — то, что боевой исполнитель отдал бы Blender.

  gate_check.py <ключ-или-префикс> --out <папка> [--gate 0|1] [--inject hide_item:<слот>] [--fast]
    --gate    значение RENDER_QA_GATE (по умолчанию 1: ворота включены);
    --inject  проверка сторожа в кадре (`render_cycles.py --qa-inject …`): слот «пропадает» из кадра → ожидается кадровый брак;
    --fast    16 выборок и 35 % вместо пресета (геометрия, маски и проверки сторожа от шума не зависят; для сравнения «ворота вкл/выкл» оба прогона берут одно и то же).
  Печатает итог одной строкой: `ГОТОВО <ключ8> C1=<sha> C2=<sha>` либо `БРАК <ключ8> <где>: <класс слот; …>`.
Запуск на pakardev: `~/venvs/scout/bin/python tools/scout/render_gpu/gate_check.py 8684964e --out ~/remlab-logs/t18-1118/t7/run1 --fast`."""
import glob
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.abspath(os.path.join(HERE, '..'))
sys.path[:0] = [SCOUT, HERE]


def main(argv: list) -> int:
    g = lambda k, d=None: argv[argv.index(k) + 1] if k in argv else d  # noqa: E731
    pref, out = argv[0], os.path.expanduser(g('--out', ''))
    if not out:
        print(__doc__)
        return 2
    os.environ['RENDER_QA_GATE'] = g('--gate', '1')
    os.environ['RENDER_WORK'] = os.path.join(out, 'work')
    import render_exec as RE
    root = os.environ.get('RENDER_PREP_CACHE') or os.path.expanduser('~/scout-cache/render-prepared')
    hits = sorted(glob.glob(os.path.join(root, pref + '*')))
    if len(hits) != 1:
        print(f'заказ по префиксу {pref!r}: найдено {len(hits)}')
        return 2
    prepared, key = hits[0], os.path.basename(hits[0])
    inject = g('--inject')
    base = RE.preset

    def preset():
        p = dict(base())
        if '--fast' in argv:
            p.update(samples=16, pct=35, threads=2, cores=2, min_gb=6)
        if inject:
            p['flags'] = list(p['flags']) + ['--qa-inject', inject]
        return p
    RE.preset = preset

    class Prepped(RE.LocalCpuExecutor):
        def _prepare(self, snap, job, log, pr, progress, timing):
            progress('scene')
            self._link_tree(os.path.join(prepared, 'dump'), os.path.join(job, 'dump'))
            self._link_tree(os.path.join(prepared, 'scene'), os.path.join(job, 'scene'))
            timing['export'], timing['dump'] = 0.0, 0.0
            return os.path.join(job, 'dump')

    res_dir = os.path.join(out, f'{key[:8]}-gate{os.environ["RENDER_QA_GATE"]}' + ('-inj' if inject else ''))
    t0 = time.time()
    try:
        Prepped({}).render({'scene_hash': key + '0' * (64 - len(key)), 'v': 1, 'source': 'gate-check'}, res_dir, lambda s: print('  стадия', s, flush=True))
    except RE.RenderBrak as e:
        print(f'БРАК {key[:8]} {e.where}: ' + '; '.join(f"{b.get('code')} {b.get('slot') or ''} ({b.get('cam') or b.get('where')})".strip() for b in e.brak) + f' · {time.time() - t0:.0f} с')
        print('  каталог результата создан:', os.path.exists(res_dir))
        return 0
    sha = {c: hashlib.sha256(open(os.path.join(res_dir, f'{c}.jpg'), 'rb').read()).hexdigest()[:16] for c in ('C1', 'C2')}
    print(f'ГОТОВО {key[:8]} C1={sha["C1"]} C2={sha["C2"]} · {time.time() - t0:.0f} с')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
