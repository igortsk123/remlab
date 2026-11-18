"""КЭШ СЖАТЫХ МЕШЕЙ ВЫГРУЗКИ (T-20261118-10/2 (б)): `export_scene.put_npz` даёт ТЕ ЖЕ байты, что прямая запись `np.savez_compressed`, повтор — из кэша без сжатия, другое содержимое — другой
файл, потолок кэша держится. Blender не нужен. python tools/scout/tests/test_export_npz_cache.py"""
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, '..'), os.path.join(HERE, '..', 'cycles_probe')]
import export_scene as ES  # noqa: E402

fails = []


def check(name, cond):
    print(('OK   ' if cond else 'FAIL ') + name)
    if not cond:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix='npzc-')
ES.NPZ_CACHE = os.path.join(tmp, 'cache')
rng = np.random.default_rng(3)
mk = lambda n=4000: {'v': rng.standard_normal((n, 3)).astype(np.float32), 'f': rng.integers(0, n, (n * 2, 3)).astype(np.int32), 'uv': rng.random((n, 2)).astype(np.float32)}  # noqa: E731
d1 = mk()

direct = os.path.join(tmp, 'direct.npz')
np.savez_compressed(direct, **d1)
a = os.path.join(tmp, 'a.npz')
ES.put_npz(d1, a)
check('байты те же, что у прямой записи savez_compressed', open(a, 'rb').read() == open(direct, 'rb').read())
z = np.load(a)
check('содержимое читается: v, f, uv как были', all(np.array_equal(z[k], d1[k]) for k in d1))

# повтор — из кэша: сжатие не вызывается, файл в кэше один
calls = []
orig = np.savez_compressed
np.savez_compressed = lambda *x, **k: (calls.append(1), orig(*x, **k))[1]
try:
    b = os.path.join(tmp, 'b.npz')
    ES.put_npz({k: v.copy() for k, v in d1.items()}, b)
finally:
    np.savez_compressed = orig
check('повтор тех же массивов — без повторного сжатия', calls == [] and open(b, 'rb').read() == open(direct, 'rb').read())
check('в кэше один файл, без временных', [f for f in os.listdir(ES.NPZ_CACHE)] == [ES.npz_key(d1)])

# другое содержимое (один элемент, форма, тип) — другой ключ
d2 = {k: v.copy() for k, v in d1.items()}
d2['v'][0, 0] += 1e-3
d3 = {**d1, 'v': d1['v'].reshape(3, -1)}                      # те же байты, другая форма
d4 = {**d1, 'f': d1['f'].astype(np.int64)}
keys = {ES.npz_key(x) for x in (d1, d2, d3, d4)}
check('любое отличие (значение, форма, тип) — другой ключ', len(keys) == 4)

# жёсткая ссылка: удаление из кэша (потолок) не портит уже выданные файлы
os.chmod(a, 0o644)
ES.NPZ_CACHE_MB = 0.001
for _ in range(25):
    ES.put_npz(mk(2000), os.path.join(tmp, f'x{_}.npz'))
left = os.listdir(ES.NPZ_CACHE)
check('потолок кэша: старые убраны', len(left) < 25)
check('выданный файл жив после чистки кэша', np.array_equal(np.load(b)['f'], d1['f']))

print('итог:', 'чисто' if not fails else f'{len(fails)} падений')
sys.exit(1 if fails else 0)
