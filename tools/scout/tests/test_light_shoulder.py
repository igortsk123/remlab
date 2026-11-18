"""ПЛЕЧО СВЕТОВ РЕНДЕРА (T-20261118-08/1, П1.78): `render_cycles.py: shoulder_fn` — пик канала «до колена как есть, выше плавно сжимается к потолку».
Чистая функция, Blender не нужен (берём её исходник из файла). python tools/scout/tests/test_light_shoulder.py"""
import ast
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, '..', 'cycles_probe', 'render_cycles.py'), encoding='utf-8').read()
node = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == 'shoulder_fn')
import numpy as np  # noqa: E402
ns: dict = {'np': np}
exec(compile(ast.Module([node], []), 'shoulder', 'exec'), ns)
shoulder_fn = ns['shoulder_fn']
fails = []


def check(name, cond):
    print(('OK   ' if cond else 'FAIL ') + name)
    if not cond:
        fails.append(name)


k, P = 0.85, 1.35
xs = np.linspace(0, 8, 801)
ys = shoulder_fn(xs, k, P)
check('до колена тождество (x ≤ k → y = x)', np.allclose(ys[xs <= k], xs[xs <= k]))
check('монотонна: светлее вход — не темнее выход', bool(np.all(np.diff(ys) >= -1e-6)))
check('выше колена выход меньше входа и не больше потолка', bool(np.all(ys[xs > k + 1e-6] < xs[xs > k + 1e-6]) and ys.max() <= P + 1e-6))
check('у колена наклон ≈ 1 (стык без излома)', abs((shoulder_fn(k + 1e-3, k, P) - k) / 1e-3 - 1.0) < 0.01)
check('далеко за коленом выход почти у потолка', P - float(shoulder_fn(8.0, k, P)) < 0.01)
check('число и массив дают одно и то же', abs(float(shoulder_fn(2.0, k, P)) - float(shoulder_fn(np.array([2.0]), k, P)[0])) < 1e-6)
try:
    shoulder_fn(1.0, 1.4, 1.2)
    bad = False
except ValueError:
    bad = True
check('колено ≥ потолка — ValueError', bad)
# оттенок: масштаб по пику сохраняет отношения каналов (небо остаётся голубым)
rgb = np.array([0.8, 1.6, 3.0], np.float32)
pk = float(rgb.max())
out = rgb * (float(shoulder_fn(pk, k, P)) / pk)
check('отношения каналов после плеча те же (оттенок не меняется)', np.allclose(out / out.max(), rgb / rgb.max(), atol=1e-5) and out.max() <= P)
import json  # noqa: E402
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
rules = json.load(open(os.path.join(ROOT, 'data', 'flat3d', 'light-rules.json'), encoding='utf-8'))
preset = json.load(open(os.path.join(HERE, '..', 'cycles_probe', 'render-preset.json'), encoding='utf-8'))
fl = preset['flags']
check('пресет рендера несёт плечо ровно из data/flat3d/light-rules.json (одно правило, числа не расходятся)',
      '--shoulder' in fl and fl[fl.index('--shoulder') + 1] == f"{rules['shoulder']['knee']},{rules['shoulder']['ceil']}")
check('правила: колено < потолок, пределы мерки заданы', 0.2 < rules['shoulder']['knee'] < rules['shoulder']['ceil'] and set(rules['limits']) >= {'clip_any', 'wall_clip'})
print('итог:', 'чисто' if not fails else f'{len(fails)} падений')
sys.exit(1 if fails else 0)
