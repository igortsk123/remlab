#!/usr/bin/env python3
"""Расхождение модели с паспортом товара ПО ОСЯМ — основа карантина мешей (план conv-04).

Владелец 13.10: «пропорции расходятся с паспортом больше чем на 15 % по любой оси — в брак, отдавать
человеку». Меряем на ОРИЕНТИРОВАННОЙ модели (оси товара известны только после orient-v2): габариты в
каноническом фрейме (`mesh_dims.extents`, X — ширина, Y — высота, Z — глубина), масштаб — по высоте
паспорта, затем ширина и глубина сравниваются с паспортом (у круглых ролей — с диаметром). Высота так
не проверяется — масштаб от неё; второй масштаб по ширине выводится и пишется как `consistency`.

Режим `--measure` ТОЛЬКО ЧИТАЕТ: считает отклонения для всех ориентированных моделей с паспортом и
показывает, сколько ушло бы в карантин при 15 / 20 / 25 % — ДО включения (решение владельца).

  ~/venvs/scout/bin/python mesh_axes.py --measure [--limit N] [--workers 3]
  python3 mesh_axes.py --selftest
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT = os.path.join(HERE, 'mesh-axes-measure.json')
THRESHOLDS = (0.15, 0.20, 0.25)
ROLES = {'диван', 'кресло', 'столик', 'тв-тумба', 'стеллаж', 'комод', 'торшер', 'пуф', 'кашпо', 'витрина',
         'банкетка', 'стол обеденный', 'стул', 'ваза', 'стенка', 'камин', 'люстра', 'лампа', 'бра'}


def deviation(ext: tuple, w: float | None, d: float | None, h: float | None, dia: float | None = None) -> dict | None:
    """Отклонения ширины/глубины модели от паспорта при масштабе по высоте; None — не с чем сравнить."""
    ex_w, ex_h, ex_d = ext
    if not h or ex_h <= 0:
        return None
    s = h / ex_h
    pw = w or dia
    pd = d or (dia if dia and not d else None)
    out = {'scale_h': round(s, 4)}
    if pw:
        out['dw'] = round(ex_w * s / pw - 1, 3)
    if pd:
        out['dd'] = round(ex_d * s / pd - 1, 3)
    if pw:
        out['consistency'] = round((pw / ex_w) / s, 3)       # масштаб по ширине против масштаба по высоте
    devs = [abs(out[k]) for k in ('dw', 'dd') if k in out]
    if not devs:
        return None
    out['max_dev'] = max(devs)
    out['axis'] = 'ширина' if abs(out.get('dw', 0)) >= abs(out.get('dd', 0)) else 'глубина'
    return out


def measure(limit: int = 0, workers: int = 3) -> int:
    import mesh_dims as MD
    items = MD.rows(ROLES)
    if limit:
        items = items[:limit]
    print(f'ориентированных моделей с паспортом: {len(items)}', flush=True)

    def one(it):
        glb = MD.find_glb(it['sku'], it['glb_sha'])
        if not glb:
            return {'sku': it['sku'], 'skip': 'нет glb'}
        ex = MD.extents(glb, it['resolution']['R'])
        if not ex or min(ex) <= 0:
            return {'sku': it['sku'], 'skip': 'пустая геометрия'}
        dev = deviation(ex, it['w'], it['d'], it['h'])
        return {'sku': it['sku'], 'role': it['role'], 'name': it['name'][:60], 'ext': ex, **(dev or {'skip': 'нет осей'})}

    res = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, r in enumerate(ex.map(one, items), 1):
            res.append(r)
            if i % 100 == 0:
                print(f'  {i}/{len(items)}', flush=True)
    json.dump(res, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    ok = [r for r in res if 'max_dev' in r]
    print(f'измерено {len(ok)}, пропущено {len(res) - len(ok)}')
    by_role: dict = {}
    for r in ok:
        by_role.setdefault(r['role'], []).append(r['max_dev'])
    print(f"{'роль':16} {'n':>5} " + ' '.join(f'>{int(t * 100)}%'.rjust(7) for t in THRESHOLDS))
    for role, xs in sorted(by_role.items(), key=lambda kv: -len(kv[1])):
        print(f'{role:16} {len(xs):5d} ' + ' '.join(f'{sum(1 for x in xs if x > t):7d}' for t in THRESHOLDS))
    allx = [r['max_dev'] for r in ok]
    print(f"{'ВСЕГО':16} {len(allx):5d} " + ' '.join(f'{sum(1 for x in allx if x > t):7d}' for t in THRESHOLDS))
    return 0


def _selftest() -> int:
    bad = 0

    def ok(name, cond):
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    d = deviation((2.0, 0.8, 1.0), w=200, d=100, h=80)
    ok('модель в пропорциях паспорта — отклонение 0', d['max_dev'] == 0)
    d = deviation((2.4, 0.8, 1.0), w=200, d=100, h=80)
    ok('модель шире паспорта на 20 % — ось «ширина», 0.2', d['axis'] == 'ширина' and abs(d['max_dev'] - 0.2) < 1e-6)
    d = deviation((0.4, 1.6, 0.4), w=None, d=None, h=160, dia=40)
    ok('круглое — сравнение с диаметром по обеим осям', d['max_dev'] == 0)
    ok('без высоты — не с чем мерить', deviation((1, 0, 1), 100, 50, None) is None)
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    if '--measure' in sys.argv:
        lim = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 0
        wk = int(sys.argv[sys.argv.index('--workers') + 1]) if '--workers' in sys.argv else 3
        sys.exit(measure(lim, wk))
    print(__doc__)
